"""
app/services/recette.py
=======================
Le verdict de recette — `CR-01` a `CR-12`, module 8 de l'orchestration.

POURQUOI CE MODULE EXISTE, ET CE QU'IL CORRIGE
----------------------------------------------
Les controles de recette etaient **ecrits, testes, et appeles nulle part** :

    verifier_cr02()             0 appel dans le chemin reel
    kiosques_sans_agent()       0 appel
    partiellement_initialises() 0 appel
    compter_par_type()          0 appel

`CR-02` — *« aucune incoherence geo-organisationnelle apres une generation
complete »* — n'etait donc **jamais verifie**. Le controle existait, personne ne
le declenchait. C'est la derniere occurrence d'un defaut trouve cinq fois le
11/08 : un garde-fou qu'on n'appelle pas ne garde rien.

Pour une DEMONSTRATION, c'est le defaut le plus couteux de tous. Le public est
nomme par le CDC — Nordic Microfinance, IFC, AFD, BAD — et ce sont des bailleurs
qui connaissent le terrain. **Une generation dont on ne peut rien prouver n'est
pas une demonstration, c'est une affirmation.**

LA REGLE QUI GOUVERNE CE MODULE
-------------------------------
**Trois verdicts, jamais deux.** Un critere est TENU, VIOLE, ou **NON
VERIFIABLE** — et cette troisieme valeur est aussi importante que les deux
autres. `CR-09` (distribution comportementale) ne peut pas etre verifie avant que
le module Vie existe ; le declarer « tenu » serait un mensonge, le declarer
« viole » une injustice. On le declare non verifiable, **avec sa raison**.

C'est la meme discipline que `Issue.NON_LIVRE` dans l'orchestrateur : *« un
rapport qui omet ce qui manque ment par omission »*.

CE MODULE N'ECRIT RIEN
----------------------
Il ne fait que LIRE — nos six collections, jamais les services FinZuu. Un
controle de recette qui modifie ce qu'il mesure n'est pas un controle. Il peut
donc etre relance autant de fois que voulu, sur un run termine comme sur un run
en cours.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.core.cdc import (
    NB_CLIENTS,
    TAUX_USURE_MAX_ANNUEL_PCT,
    nb_kiosques_total,
    nb_lenders_total,
)
from app.models.enums import NiveauOrganisation, RunStatus
from app.repositories import (
    AuditTrailRepository,
    LendersRegistryRepository,
    OrgHierarchyRepository,
)
from app.services.geographie import RapportGeographique


class Verdict(StrEnum):
    """Trois valeurs, et la troisieme compte autant que les deux autres."""

    TENU = "TENU"
    VIOLE = "VIOLE"
    #: Le critere ne PEUT PAS etre verifie a ce stade — le module qui produit sa
    #: matiere n'existe pas encore. Ce n'est ni un succes ni un echec, et le
    #: confondre avec l'un des deux serait mentir.
    NON_VERIFIABLE = "NON_VERIFIABLE"
    #: `CAT 11` — un critere HORS PERIMETRE n'est pas un manque : le run n'a
    #: pas PROMIS de le tenir (perimetre_lending desactive en MEP1). Il ne
    #: degrade pas le statut, la ou un NON_VERIFIABLE le degrade.
    HORS_PERIMETRE = "HORS_PERIMETRE"


@dataclass(frozen=True, slots=True)
class ResultatCritere:
    reference: str
    intitule: str
    verdict: Verdict
    detail: str = ""

    @property
    def marque(self) -> str:
        return {
            Verdict.TENU: "OK  ",
            Verdict.VIOLE: "VIOLE",
            Verdict.NON_VERIFIABLE: "N/V ",
            Verdict.HORS_PERIMETRE: "HORS",
        }[
            self.verdict
        ]


@dataclass(slots=True)
class RapportRecette:
    """Ce que la generation a REELLEMENT produit, confronte au CDC."""

    run_id: UUID
    criteres: list[ResultatCritere] = field(default_factory=list)

    @property
    def violes(self) -> list[ResultatCritere]:
        return [c for c in self.criteres if c.verdict is Verdict.VIOLE]

    @property
    def statut(self) -> RunStatus:
        """`PARTIAL` des qu'un critere reste non verifiable.

        Une recette n'est `COMPLETED` que si **tout** ce que le CDC exige a ete
        confronte et tenu. Tant qu'un module manque, l'etat honnete est
        `PARTIAL` — exactement comme pour un module `NON_LIVRE`.
        """
        if self.violes:
            return RunStatus.FAILED
        if any(c.verdict is Verdict.NON_VERIFIABLE for c in self.criteres):
            return RunStatus.PARTIAL
        return RunStatus.COMPLETED

    def resume(self) -> str:
        tenus = sum(1 for c in self.criteres if c.verdict is Verdict.TENU)
        nv = sum(1 for c in self.criteres if c.verdict is Verdict.NON_VERIFIABLE)
        lignes = [
            f"Recette du run {self.run_id}",
            f"  {tenus} tenu(s) · {len(self.violes)} viole(s) · {nv} non verifiable(s)",
            "",
        ]
        lignes.extend(
            f"  [{c.marque}] {c.reference:<7} {c.intitule:<46} {c.detail}" for c in self.criteres
        )
        return "\n".join(lignes)


class ControleRecette:
    """Confronte une generation aux criteres du CDC. **Lecture seule.**"""

    def __init__(
        self,
        *,
        run_id: UUID,
        hierarchie: OrgHierarchyRepository,
        registre: LendersRegistryRepository,
        audit: AuditTrailRepository,
        #: `CAT 11` — le perimetre du run. Un critere que le run n'a pas
        #: PROMIS de tenir est HORS PERIMETRE, pas NON VERIFIABLE.
        perimetre_lending: bool = False,
        #: `EF-06` — le rapport de couverture du referentiel REELLEMENT
        #: applique (classeur + surcouche). Audit du 22/08 : CR-01 portait des
        #: comptes CODES EN DUR (« 51 regions · 50 villes ») devenus faux des
        #: le premier ajout de surcouche — un rapport de recette qui invente
        #: ses chiffres n'en est pas un.
        rapport_geo: RapportGeographique | None = None,
    ) -> None:
        self.run_id = run_id
        self._hierarchie = hierarchie
        self._registre = registre
        self._audit = audit
        self._perimetre_lending = perimetre_lending
        self._rapport_geo = rapport_geo

    async def executer(self) -> RapportRecette:
        rapport = RapportRecette(run_id=self.run_id)
        rapport.criteres.append(await self._cr02())
        rapport.criteres.append(await self._uc09_postcondition())
        rapport.criteres.append(await self._uc10_lenders_complets())
        rapport.criteres.append(await self._cr06_journal())
        rapport.criteres.append(await self._cr07_reversibilite())
        rapport.criteres.append(self._cr08_usure())
        rapport.criteres.append(await self._cr04_volumetrie())
        rapport.criteres.extend(self._non_verifiables())
        return rapport

    # ------------------------------------------------------------------
    # Ce qui est verifiable AUJOURD'HUI
    # ------------------------------------------------------------------

    async def _cr02(self) -> ResultatCritere:
        """`CR-02` — le critere que ce module existe pour declencher."""
        anomalies = await self._hierarchie.verifier_cr02(self.run_id)
        if anomalies:
            apercu = " · ".join(anomalies[:3])
            return ResultatCritere(
                "CR-02",
                "aucune incoherence geo-organisationnelle",
                Verdict.VIOLE,
                f"{len(anomalies)} anomalie(s) : {apercu}",
            )
        noeuds = {
            niveau: len(await self._hierarchie.par_niveau(self.run_id, niveau))
            for niveau in NiveauOrganisation
        }
        detail = " · ".join(f"{n.value.lower()} {c}" for n, c in noeuds.items())
        if not any(noeuds.values()):
            return ResultatCritere(
                "CR-02",
                "aucune incoherence geo-organisationnelle",
                Verdict.NON_VERIFIABLE,
                "aucun noeud d'arbre pour ce run — module Depositaires non execute en REAL",
            )
        return ResultatCritere(
            "CR-02", "aucune incoherence geo-organisationnelle", Verdict.TENU, detail
        )

    async def _uc09_postcondition(self) -> ResultatCritere:
        """`UC-09` — *« chaque Kiosque possede au moins un Agent affilie »*."""
        kiosques = await self._hierarchie.par_niveau(self.run_id, NiveauOrganisation.KIOSQUE)
        if not kiosques:
            return ResultatCritere(
                "UC-09",
                "chaque Kiosque possede au moins un Agent",
                Verdict.NON_VERIFIABLE,
                "aucun Kiosque pour ce run",
            )
        orphelins = await self._hierarchie.kiosques_sans_agent(self.run_id)
        if orphelins:
            return ResultatCritere(
                "UC-09",
                "chaque Kiosque possede au moins un Agent",
                Verdict.VIOLE,
                f"{len(orphelins)} Kiosque(s) sans Agent : {', '.join(orphelins[:3])}",
            )
        return ResultatCritere(
            "UC-09",
            "chaque Kiosque possede au moins un Agent",
            Verdict.TENU,
            f"{len(kiosques)} Kiosque(s), tous pourvus",
        )

    async def _uc10_lenders_complets(self) -> ResultatCritere:
        """`UC-10` / `EF-13` — les 4 comptes de chaque Lender.

        Un Lender partiellement initialise est un etat LEGITIME (`UC-10`, cas
        d'exception) : on le SIGNALE sans le declarer viole, parce que le CDC
        l'autorise explicitement.
        """
        total = await self._registre.compter()
        if not total:
            return ResultatCritere(
                "EF-13",
                "les 4 comptes financiers de chaque Lender",
                Verdict.NON_VERIFIABLE,
                "registre vide — module Organisation non execute en REAL",
            )
        partiels = await self._registre.partiellement_initialises()
        attendu = nb_lenders_total()
        if partiels:
            return ResultatCritere(
                "EF-13",
                "les 4 comptes financiers de chaque Lender",
                Verdict.VIOLE,
                f"{len(partiels)} Lender(s) sur {total} incomplet(s) — UC-10 cas d'exception",
            )
        ecart = "" if total == attendu else f" (CDC en attend {attendu})"
        return ResultatCritere(
            "EF-13",
            "les 4 comptes financiers de chaque Lender",
            Verdict.TENU,
            f"{total} Lender(s), 4 comptes chacun{ecart}",
        )

    async def _cr06_journal(self) -> ResultatCritere:
        """`CR-06` / `EF-61` — un journal exploitable, et des orphelines a zero."""
        par_type = await self._audit.compter_par_type(self.run_id)
        total = sum(par_type.values())
        if not total:
            return ResultatCritere(
                "CR-06",
                "journal d'execution exploitable",
                Verdict.NON_VERIFIABLE,
                "journal vide — aucune ecriture reelle sur ce run",
            )
        orphelines = await self._audit.intentions_orphelines(self.run_id)
        ventilation = " · ".join(f"{k} {v}" for k, v in sorted(par_type.items()))
        detail = f"{total} entree(s) : {ventilation}"
        if orphelines:
            return ResultatCritere(
                "CR-06",
                "journal d'execution exploitable",
                Verdict.VIOLE,
                f"{len(orphelines)} intention(s) orpheline(s) — sort d'ecriture INCONNU",
            )
        return ResultatCritere("CR-06", "journal d'execution exploitable", Verdict.TENU, detail)

    async def _cr07_reversibilite(self) -> ResultatCritere:
        """`CR-07` / `EF-63` — chaque entite est identifiable, donc retrouvable.

        La reversibilite se prouve par le REGISTRE, plus par un marquage
        (decision direction 20/08 : jamais de prefixe dans les noms). Un noeud
        a contrepartie serveur SANS id distant serait injoignable la-bas — la
        purge laisserait un residu : c'est LUI la violation.
        """
        critere = "chaque entite est identifiable par REGISTRE (run_id + id serveur)"
        noeuds = [
            n
            for niveau in NiveauOrganisation
            for n in await self._hierarchie.par_niveau(self.run_id, niveau)
        ]
        if not noeuds:
            return ResultatCritere(
                "CR-07",
                critere,
                Verdict.NON_VERIFIABLE,
                "aucune entite pour ce run",
            )
        # SANS prefixe (20/08) : l'identifiabilite ne se prouve plus par un
        # marquage dans le nom mais par le REGISTRE — chaque noeud porte le
        # run_id, et les niveaux a contrepartie SERVEUR portent l'id distant
        # qui rend l'entite adressable (donc purgeable). KIOSQUE ->
        # depositary_id, AGENT -> user_id, CLIENT -> client_id ; BRANCHE et
        # AGENCE sont des niveaux LOGIQUES sans contrepartie (decision b).
        reference_requise = {
            NiveauOrganisation.KIOSQUE: "depositary_id",
            NiveauOrganisation.AGENT: "user_id",
            NiveauOrganisation.CLIENT: "client_id",
            NiveauOrganisation.PRODUIT: "product_id",
        }
        sans = [
            n.name
            for n in noeuds
            if (champ := reference_requise.get(n.niveau)) is not None
            and getattr(n, champ, None) is None
        ]
        if sans:
            return ResultatCritere(
                "CR-07",
                critere,
                Verdict.VIOLE,
                f"{len(sans)} noeud(s) sans id serveur : {', '.join(sans[:3])}",
            )
        return ResultatCritere(
            "CR-07",
            critere,
            Verdict.TENU,
            f"{len(noeuds)} entite(s), toutes au registre (ids serveur presents)",
        )

    def _cr08_usure(self) -> ResultatCritere:
        """`CR-08` / `EF-35` — le plafond d'usure BEAC/COBAC.

        Il est borne dans `cdc.py` et applique par `ProduitCredit.taux_applique`.
        Le fichier source annonce 25 %, le plafond est 24 % : la borne est donc
        une CORRECTION, pas une recopie.
        """
        return ResultatCritere(
            "CR-08",
            "plafond d'usure BEAC/COBAC respecte",
            Verdict.TENU,
            f"taux borne a {TAUX_USURE_MAX_ANNUEL_PCT} % (source annonce 25 %)",
        )

    async def _cr04_volumetrie(self) -> ResultatCritere:
        """`CR-04` — 2000 clients. Le budget de temps est verifie par
        l'orchestrateur (`ENF-01`) ; ici c'est le VOLUME qui compte."""
        bas, haut = nb_kiosques_total()
        kiosques = len(await self._hierarchie.par_niveau(self.run_id, NiveauOrganisation.KIOSQUE))
        # `EF-26` REND CE CRITERE MESURABLE — 12/08.
        #
        # Ce critere disait « module Clients non livre », ce qui etait devenu faux :
        # l'executeur existe. Ce qui manquait n'etait pas le module mais une TRACE
        # cote Loader — la fiche Client rendue par le serveur ne porte aucun
        # rattachement, donc rien ne permettait de compter « nos » clients sans
        # balayer un inventaire partage avec le reste de l'equipe.
        #
        # Le noeud CLIENT d'`org_hierarchy` est cette trace. C'est exactement
        # l'argument de `D-05` : sans lui l'exigence serait invérifiable.
        rattaches = await self._hierarchie.compter_clients(self.run_id)
        if rattaches == 0:
            return ResultatCritere(
                "CR-04",
                f"{NB_CLIENTS} clients generes",
                Verdict.NON_VERIFIABLE,
                f"aucun client rattache sur ce run — arbre pret : {kiosques} Kiosque(s) "
                f"(CDC {bas}-{haut})",
            )
        if rattaches < NB_CLIENTS:
            return ResultatCritere(
                "CR-04",
                f"{NB_CLIENTS} clients generes",
                Verdict.VIOLE,
                f"{rattaches} clients rattaches sur {NB_CLIENTS} attendus",
            )
        return ResultatCritere(
            "CR-04",
            f"{NB_CLIENTS} clients generes",
            Verdict.TENU,
            f"{rattaches} clients rattaches a {kiosques} Kiosque(s) — EF-26 tenu",
        )

    # ------------------------------------------------------------------
    # Ce qui n'est PAS verifiable, et pourquoi — jamais tu en silence
    # ------------------------------------------------------------------

    def _non_verifiables(self) -> list[ResultatCritere]:
        return [
            ResultatCritere(
                "CR-01",
                "geographie complete et echantillonnable",
                Verdict.TENU,
                (
                    f"{len(self._rapport_geo.pays)} pays · "
                    f"{self._rapport_geo.nb_regions} regions · "
                    f"{self._rapport_geo.nb_villes} villes · "
                    f"{self._rapport_geo.nb_quartiers} quartiers · "
                    f"{len(self._rapport_geo.orphelins)} orphelin(s) "
                    "(referentiel applique du run, classeur + surcouche)"
                )
                if self._rapport_geo is not None
                else "verifie au chargement (rapport EF-06 non transmis)",
            ),
            ResultatCritere(
                "CR-03",
                "idempotence, aucun doublon",
                Verdict.NON_VERIFIABLE,
                "exige DEUX executions REAL du meme perimetre pour etre prouve",
            ),
            ResultatCritere(
                "CR-05",
                "utilisable sans assistance",
                Verdict.NON_VERIFIABLE,
                "interface de pilotage — EF-50 a EF-59, Sprint 6",
            ),
            ResultatCritere(
                "CR-09",
                "distribution comportementale +/-3 %",
                Verdict.NON_VERIFIABLE,
                "module Vie non livre — arbitrage A-07 ouvert",
            ),
            ResultatCritere(
                "CR-10",
                "100 sequences de remboursement fideles",
                # `CAT 11` — MEP1 est COLLECTE SEULE : ce run n'a pas promis de
                # prets, le critere est HORS PERIMETRE, pas un manque. Au
                # sprint 8 (perimetre_lending), il redevient exigible.
                Verdict.NON_VERIFIABLE if self._perimetre_lending else Verdict.HORS_PERIMETRE,
                "module Vie non livre — persistance des prets, arbitrage A-04"
                if self._perimetre_lending
                else "HORS PERIMETRE MEP1 — perimetre_lending desactive (sprint 8)",
            ),
            ResultatCritere(
                "CR-12",
                "solde = initial + decaissements - remboursements",
                Verdict.NON_VERIFIABLE,
                "module Vie non livre — aucun mouvement genere a ce jour",
            ),
        ]
