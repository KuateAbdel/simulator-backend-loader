"""
app/services/orchestrateur.py
=============================
L'enchainement des huit modules — `S3-01`, doctrine dans `docs/ORCHESTRATION.md`.

CE QUI MANQUAIT
---------------
Quatre executeurs etaient ecrits — Roles, Organisation, Depositaires, Staff — et
**rien ne les enchainait**. Chacun savait faire son metier ; aucun ne savait
quand son tour venait, ni ce qu'il devait au precedent, ni ce qui se passait si
celui-ci avait echoue a moitie.

Un orchestrateur qui improvise son ordre ecrit dans le desordre. Et **trois
services n'exposent aucun `DELETE`** : account-service, identity-service,
depositary-service. Le desordre y serait definitif.

L'ORDRE N'EST PAS UN CHOIX
--------------------------
C'est le seul tri topologique du graphe de dependances. Chaque module consomme
un identifiant produit par un autre :

  1 Roles          aucune dependance — et **seul module reversible**
  2 Organisation   un Admin User exige un `group_id` (1)
  3 Catalogue      AUCUNE dependance. Mesure du 11/08 : `CreateProductSchema`
                   n'a pas de `company_id` — requis : `type`, `name`, `category`.
                   L'ordre annoncait une contrainte qui n'existe pas.
  4 Depositaires   un Depositaire exige un `company_id` (2)
  5 Staff/Agents   un User exige (1) ET (2) ; un AGENT exige un Kiosque (4), D-11
  6 Clients        un onboarding exige un `product_id` (3) et un Kiosque (4)
  7 Vie 180 jours  exige des clients et leurs comptes (6)
  8 Recette        exige tout ce qui precede

Deux proprietes voulues, pas fortuites :

  - **Le module 1 est le seul reversible.** `DELETE /groupes/{id}` existe ; rien
    d'equivalent ailleurs. Commencer par lui, c'est commencer par l'etape dont
    un echec ne laisse aucune trace.
  - **`EF-13` passe tot.** Les 4 comptes du Lender sont la derniere hypothese de
    `D-01` jamais verifiee en ecriture. Elle se joue sur 4 objets au module 2,
    plutot que d'etre decouverte au module 6 sur 2 000.

L'INVARIANT QUE CET ORDRE OFFRE
-------------------------------
**Un run interrompu s'arrete toujours sur un PREFIXE valide.** Les modules 1..N
sont faits, N+1..8 ne le sont pas. Jamais un trou au milieu. C'est ce qui rend
la reprise possible sans inventaire — et `CR-04` verifiable.

CE QUE CET ORCHESTRATEUR REFUSE DE FAIRE
----------------------------------------
  - **enchainer apres un echec systemique.** Un module `FAILED` (rien n'a
    abouti) arrete tout : les suivants dependent de ses identifiants. Un module
    `PARTIAL` poursuit — c'est un etat terminal LEGITIME (UC-07/UC-08).
  - **ecrire un module non livre.** Clients, Vie et Recette n'existent pas
    encore. Ils sont declares `NON_LIVRE`, jamais silencieusement sautes : un
    rapport qui omet ce qui manque ment par omission.
  - **passer en `REAL` sans `DRY_RUN` prealable.** Discipline `D-01`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from traceback import format_exc
from typing import Any, Final, Protocol
from uuid import UUID

from app.clients.base import MAX_CONCURRENCE
from app.models.enums import RunMode, RunStatus
from app.repositories import LoaderRunRepository

logger = logging.getLogger(__name__)

#: Plafond de concurrence — **une seule source**, celle du transport.
#:
#: Il vivait ici en double de `MAX_CONCURRENCE` (`app/clients/base.py`), et les
#: deux valeurs DIVERGEAIENT : 20 ici, 25 la-bas. Un plafond declare deux fois
#: n'est pas un plafond, c'est une opinion. Le garde-fou reel est le semaphore
#: partage du client HTTP ; l'orchestrateur ne fait que le refleter.
#:
#: Rappel du fait mesure (`H14`/`H15`, 08/08) : au-dela de 20 a 30 requetes
#: simultanees, la degradation est SILENCIEUSE, sans `429`. Un service qui
#: repond `429` se laisse piloter ; un service qui degrade sans le dire
#: transforme la surcharge en corruption — sur des services sans `DELETE`.
PLAFOND_WORKERS: Final = MAX_CONCURRENCE

#: Budget de temps, `ENF-01` : 30 minutes pour la campagne complete.
#: ~25 000 requetes -> ~14 req/s -> ~1,4 s par requete a 20 workers.
#: Ce n'est pas serre ; c'est le rappel qu'une seule route lente le mange en
#: entier. `GET /playground-client/random` a un timeout mesure a 90 s — il est
#: INTERDIT en campagne (`L-04`).
BUDGET_SECONDES: Final = 30 * 60


class Etape(StrEnum):
    """Les huit modules, dans l'ordre topologique. **L'ordre de declaration
    est l'ordre d'execution** — il n'existe nulle part ailleurs."""

    ROLES = "ROLES"
    ORGANISATION = "ORGANISATION"
    CATALOGUE = "CATALOGUE"
    DEPOSITAIRES = "DEPOSITAIRES"
    STAFF = "STAFF"
    CLIENTS = "CLIENTS"
    VIE = "VIE"
    RECETTE = "RECETTE"


class Issue(StrEnum):
    """Ce qu'une etape a produit — distinct de `RunStatus`, qui qualifie le run."""

    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    #: Deja faite par un run precedent : la reprise la saute.
    REPRISE = "REPRISE"
    #: Le module n'est pas encore ecrit. **Jamais confondu avec un succes.**
    NON_LIVRE = "NON_LIVRE"


class RapportEtape(Protocol):
    """Ce que tout executeur rend. Le seul contrat exige est `statut` : c'est
    lui qui decide si la chaine continue."""

    @property
    def statut(self) -> RunStatus: ...

    def resume(self) -> str: ...


@dataclass(slots=True)
class ResultatEtape:
    etape: Etape
    issue: Issue
    detail: str = ""
    duree_s: float = 0.0
    #: Le RESUME COMPLET du module — persiste avec le checkpoint depuis le
    #: 21/08. `detail` reste la ligne courte (l'etiquette d'un tableau) ; mais
    #: le premier run REAL a montre qu'on ne diagnostique RIEN avec 160
    #: caracteres : les trois causes ont du etre re-prouvees a la main faute
    #: d'avoir persiste les messages entiers.
    resume_complet: str = ""

    @property
    def bloquante(self) -> bool:
        """`FAILED` seul arrete la chaine.

        `PARTIAL` ne l'arrete PAS : une entite recalcitrante est prevue par le
        CDC (UC-07/UC-08, cas alternatif). `FAILED` signifie que **rien** n'a
        abouti — les etapes suivantes attendraient des identifiants qui
        n'existent pas.
        """
        return self.issue is Issue.FAILED


@dataclass(slots=True)
class RapportRun:
    """Le deroule complet, etape par etape."""

    run_id: UUID
    mode: RunMode
    etapes: list[ResultatEtape] = field(default_factory=list)
    interrompu_a: Etape | None = None

    @property
    def duree_totale_s(self) -> float:
        return sum(e.duree_s for e in self.etapes)

    @property
    def budget_respecte(self) -> bool:
        """`ENF-01` / `CR-04` — la campagne complete tient-elle en 30 minutes ?

        `BUDGET_SECONDES` etait declare depuis le debut, les durees etaient
        mesurees par etape, et **rien ne les comparait jamais**. Une exigence
        qui a sa constante, sa mesure, et aucun verdict n'est une exigence non
        verifiee.
        """
        return self.duree_totale_s <= BUDGET_SECONDES

    @property
    def statut(self) -> RunStatus:
        """`COMPLETED` exige que **toutes** les etapes livrees aient abouti.

        Une etape `NON_LIVRE` ne peut pas rendre un run `COMPLETED` : le Loader
        n'a pas fait ce que le CDC lui demande. Elle le rend `PARTIAL` — un etat
        honnete, qui dit « ce qui existe a marche, il en manque ».
        """
        if self.interrompu_a is not None:
            return RunStatus.FAILED
        if any(e.issue is Issue.FAILED for e in self.etapes):
            return RunStatus.FAILED
        if any(e.issue in (Issue.PARTIAL, Issue.NON_LIVRE) for e in self.etapes):
            return RunStatus.PARTIAL
        return RunStatus.COMPLETED

    def resume(self) -> str:
        lignes = [
            f"Run {self.run_id} — mode {self.mode.value}",
            f"Plafond de concurrence : {PLAFOND_WORKERS} workers (H14/H15)",
            "",
        ]
        for r in self.etapes:
            marque = {
                Issue.COMPLETED: "OK  ",
                Issue.PARTIAL: "PART",
                Issue.FAILED: "ECHEC",
                Issue.REPRISE: "SAUT",
                Issue.NON_LIVRE: "MANQ",
            }[r.issue]
            lignes.append(f"  [{marque}] {r.etape.value:14} {r.duree_s:6.1f}s  {r.detail}")
        if self.interrompu_a:
            lignes.append("")
            lignes.append(
                f"  INTERROMPU a {self.interrompu_a.value} — les etapes suivantes "
                "dependent de ses identifiants et n'ont pas ete tentees."
            )
        lignes.append("")
        verdict = "tenu" if self.budget_respecte else "DEPASSE"
        lignes.append(
            f"ENF-01 : {self.duree_totale_s:.1f}s sur un budget de {BUDGET_SECONDES}s — {verdict}"
        )
        lignes.append(f"STATUT : {self.statut.value}")
        return "\n".join(lignes)


#: Une etape est une coroutine sans argument qui rend un rapport. Le cablage
#: des dependances (plan, companies, produits) est fait par l'appelant, qui seul
#: connait les artefacts deja produits — l'orchestrateur ne les invente pas.
Travail = Callable[[], Awaitable[RapportEtape]]


class Orchestrateur:
    """Deroule les huit modules dans l'ordre, et sait reprendre.

    L'orchestrateur ne CONSTRUIT aucun executeur : il les recoit deja cables.
    C'est delibere — un orchestrateur qui instancie ses dependances ne peut plus
    etre teste sans reseau, et devient le point ou tout se couple.
    """

    def __init__(
        self,
        *,
        run_id: UUID,
        mode: RunMode,
        travaux: Mapping[Etape, Travail],
        runs: LoaderRunRepository | None = None,
        etapes_deja_faites: Sequence[Etape] = (),
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self._travaux = dict(travaux)
        self._runs = runs
        self._deja_faites = set(etapes_deja_faites)

    @property
    def ecriture_reelle(self) -> bool:
        return self.mode is RunMode.REAL

    # ------------------------------------------------------------------
    # Reprise
    # ------------------------------------------------------------------

    @staticmethod
    def etapes_acquises(checkpoints: Sequence[Mapping[str, Any]]) -> list[Etape]:
        """Relit les checkpoints d'un run interrompu.

        Seul `COMPLETED` compte comme acquis. Une etape `PARTIAL` est **rejouee**
        — son `GET`-avant-`POST` reutilisera ce qui existe deja et completera le
        reste. C'est le seul moyen de rattraper les entites qu'elle avait
        journalisees en echec.
        """
        acquises: list[Etape] = []
        for point in checkpoints:
            phase = str(point.get("phase", ""))
            detail = point.get("detail") or {}
            issue = str(detail.get("issue", "")) if isinstance(detail, Mapping) else ""
            if issue == Issue.COMPLETED.value:
                try:
                    acquises.append(Etape(phase))
                except ValueError:
                    # Un checkpoint d'une version anterieure : on l'ignore
                    # plutot que de planter. Il sera rejoue, jamais saute a tort.
                    logger.warning("checkpoint de phase inconnue, ignore : %s", phase)
        return acquises

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def executer(self) -> RapportRun:
        rapport = RapportRun(run_id=self.run_id, mode=self.mode)

        for etape in Etape:  # l'ordre de declaration EST l'ordre topologique
            if etape in self._deja_faites:
                rapport.etapes.append(
                    ResultatEtape(etape, Issue.REPRISE, "acquise par un run precedent")
                )
                continue

            travail = self._travaux.get(etape)
            if travail is None:
                # Module non livre. On le DIT. Un rapport qui omet ce qui manque
                # ment par omission — et ces trous sont le plan de travail.
                rapport.etapes.append(
                    ResultatEtape(etape, Issue.NON_LIVRE, "executeur non ecrit a ce jour")
                )
                continue

            resultat = await self._executer_une(etape, travail)
            rapport.etapes.append(resultat)
            await self._journaliser(resultat)

            if resultat.bloquante:
                # On n'essaie pas la suite : elle attend des identifiants qui
                # n'existent pas. Mieux vaut un run court et lisible qu'une
                # cascade d'echecs derives qui masquent la cause premiere.
                rapport.interrompu_a = etape
                logger.error("run %s interrompu a %s : %s", self.run_id, etape, resultat.detail)
                break

        if self._runs is not None:
            await self._runs.changer_statut(self.run_id, rapport.statut)
        return rapport

    async def _executer_une(self, etape: Etape, travail: Travail) -> ResultatEtape:
        debut = datetime.now(UTC)
        try:
            rapport_module = await travail()
        except Exception as erreur:
            # Une exception qui traverse un executeur est un defaut de CE
            # module, pas du run. On l'isole ici pour que les autres etapes
            # restent interpretables — et on ne la rejoue pas. La trace
            # COMPLETE part dans `resume_complet` : le 21/08, le E11000
            # tronque a masque la cle en collision, donc la cause.
            duree = (datetime.now(UTC) - debut).total_seconds()
            motif = f"{type(erreur).__name__}: {erreur}"[:600]
            logger.exception("etape %s en exception", etape)
            return ResultatEtape(
                etape,
                Issue.FAILED,
                motif,
                duree,
                resume_complet=f"{type(erreur).__name__}: {erreur}\n\n{format_exc()}",
            )

        duree = (datetime.now(UTC) - debut).total_seconds()
        issue = {
            RunStatus.COMPLETED: Issue.COMPLETED,
            RunStatus.PARTIAL: Issue.PARTIAL,
        }.get(rapport_module.statut, Issue.FAILED)
        resume = rapport_module.resume()
        return ResultatEtape(etape, issue, _essentiel(resume), duree, resume_complet=resume)

    @staticmethod
    def _resume_utile(texte: str) -> str:
        return _essentiel(texte)

    async def _journaliser(self, resultat: ResultatEtape) -> None:
        """Un checkpoint par etape — c'est le support de la reprise.

        Ecrit AUSSI en `DRY_RUN` : le checkpoint est une trace locale, pas une
        ecriture serveur. Sans lui, un dry-run interrompu ne dirait rien de ce
        qu'il avait deja deroule.
        """
        if self._runs is None:
            return
        await self._runs.ajouter_checkpoint(
            self.run_id,
            phase=resultat.etape.value,
            detail={
                "issue": resultat.issue.value,
                "detail": resultat.detail,
                "duree_s": round(resultat.duree_s, 2),
                "mode": self.mode.value,
                # Le rapport ENTIER du module — 21/08 : une ligne de 160
                # caracteres ne permet aucun diagnostic apres coup.
                "resume": resultat.resume_complet,
            },
        )


def _essentiel(resume: str) -> str:
    """La ligne qui explique, pas la premiere venue.

    Le premier jet prenait `splitlines()[0]` — soit « Mode : DRY_RUN » pour
    tous les executeurs. Un run interrompu affichait donc son mode a la place
    de sa cause. Un rapport d'echec qui ne dit pas pourquoi ne sert a rien.

    On prend en priorite la premiere ligne d'ECHEC ou de BLOCAGE, sinon le
    comptage le plus informatif — jamais l'en-tete.
    """
    lignes = [ligne.strip() for ligne in resume.splitlines() if ligne.strip()]
    for ligne in lignes:
        if ligne.startswith(("ECHEC", "BLOCAGE", "⚠")):
            return ligne[:160]
    utiles = [
        ligne for ligne in lignes if not ligne.startswith(("Mode", "STATUT")) and ":" in ligne
    ]

    # LA LIGNE QUI COMPTE N'EST PAS TOUJOURS LA PREMIERE (24/08).
    #
    # Defaut mesure sur le DRY_RUN du 24/08 : DEPOSITAIRES affichait
    # « Branches : 19 » — la premiere ligne utile — et cachait ce qui
    # interesse vraiment : « Kiosques : 28 crees, 32 sautes, 0 en echec ».
    # Le detail existait (range dans les checkpoints), mais il fallait aller
    # le chercher : devant l'administration, personne ne saura qu'il est la.
    #
    # Chaque module a UNE grandeur qui le juge. On la nomme, et si elle est
    # absente du resume on retombe sur l'ancien comportement — jamais un
    # rapport vide parce qu'un intitule a change.
    GRANDEUR_DECISIVE = ("Kiosques", "Clients crees", "Companies", "Staff cree", "Produits crees")
    for cle in GRANDEUR_DECISIVE:
        for ligne in utiles:
            if ligne.startswith(cle):
                return ligne[:160]
    return (utiles[0] if utiles else lignes[0] if lignes else "")[:160]
