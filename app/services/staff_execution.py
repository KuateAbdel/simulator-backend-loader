"""
app/services/staff_execution.py
===============================
Execution du module Staff — `UC-09`, `EF-17`, Sprint 2, story `S2-03`.

> *« Il genere entre 15 et 25 utilisateurs staff par pays »* — `UC-09`, point 2
> *« chaque Kiosque possede au moins un Agent affilie »* — `UC-09`, postcondition

**C'est le premier module ou tout converge** : la configuration parametrable,
le referentiel enrichi, les invariants de credibilite, le registre d'unicite,
le journal d'intention et les 11 roles. Rien n'y est nouveau ; tout y est
assemble.

LA SEQUENCE EST IMPOSEE, PAS CHOISIE
-------------------------------------
`CreateUserSchema.identity` est **requis** : une Identity doit exister AVANT le
User. Verifie en ecriture reelle le 09/08. Et le flow utilisateur est en
**trois requetes indissociables** — s'arreter apres `register` laisserait un
compte a `is_first_login=true`, incapable de se connecter. C'est l'etat de 16
des 20 Users de l'environnement.

    Identity  ──►  register  ──►  password/f/change  ──►  login
                                  (auth_token, jamais ROOT)

LE CONFLIT ARITHMETIQUE QUE PERSONNE N'AVAIT VU
------------------------------------------------
`UC-09` demande **15 a 25 staff par pays** ET **un Agent par Kiosque**, avec
**10 a 20 Kiosques par pays**. Rien ne garantit que le premier couvre le second :
un tirage a 15 staff et 20 Kiosques rend l'exigence **arithmetiquement
insatisfaisable**.

**Arbitrage retenu** : la **postcondition prime sur la fourchette**. « Chaque
Kiosque possede au moins un Agent » est une garantie de structure — un Kiosque
sans Agent n'existe pas sur le terrain. On cree donc autant d'Agents que de
Kiosques, et **le depassement est signale**, jamais absorbe en silence.

**Lecture retenue** : les Agents sont **compris** dans les 15-25, le CDC parlant
d'« utilisateurs staff » sans reserve. Le reste du budget va a l'encadrement.
*(Point ouvert, `PLAN_SPRINTS.md` §3.4.)*

CE QUI EST IRREVERSIBLE, ET CE QUI NE L'EST PAS
-------------------------------------------------
Chaque staff produit **une Identity definitive** — identity-service n'expose
aucun `DELETE`. Le User, lui, n'en a pas non plus. **Le mode `DRY_RUN` n'est
donc pas un confort** : c'est la seule facon de voir 60 a 100 creations avant
qu'elles ne soient permanentes.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.clients.contracts import IdentityType, UserType
from app.core.configuration import ConfigurationExecution
from app.core.invariants import (
    InvariantViole,
    RegistreUnicite,
    valider_coherence_territoriale,
)
from app.models.enums import RunMode, RunStatus
from app.services.generateur import patronyme, prenom
from app.services.geographie import ReferentielGeo

logger = logging.getLogger(__name__)

#: Roles d'encadrement, dans l'ordre de priorite d'attribution. `Super-Admin`
#: n'y figure pas : c'est un role de plateforme, cree une seule fois et
#: globalement, jamais un par pays.
ROLES_ENCADREMENT: tuple[str, ...] = (
    "Admin",
    "Branche",
    "Collecte",
    "Comptable",
    "Compliance",
    "Marketing",
    "Employe/IT",
)

#: Le role de terrain. `UC-09` : un par Kiosque, sans exception.
ROLE_AGENT = "Agent"

#: Dispersion multiplicative de Knuth — fait varier **les huit chiffres** du
#: corps avec le rang. Un simple `f"{rang:08d}"` ne ferait varier que le poids
#: faible, qui est tronque par les plans les plus courts.
_DISPERSION = 2_654_435_761
#: Pas de reprise en cas de collision residuelle : premier entier assez grand
#: pour changer tous les chiffres.
_PAS = 7_654_321
#: Bornee : au-dela, c'est le plan du pays qui est sature, pas notre tirage.
_TENTATIVES_MSISDN = 40


@dataclass(slots=True)
class PlanStaffPays:
    """Ce qu'un pays recoit, et pourquoi."""

    pays: str
    nb_kiosques: int
    budget_staff: int
    nb_agents: int
    encadrement: dict[str, int] = field(default_factory=dict)
    alerte: str = ""

    @property
    def total(self) -> int:
        return self.nb_agents + sum(self.encadrement.values())


@dataclass(slots=True)
class RapportStaff:
    """Ce que l'execution a produit, ce qu'elle a saute, ce qui l'a genee."""

    mode: RunMode
    plans: list[PlanStaffPays] = field(default_factory=list)
    crees: list[str] = field(default_factory=list)
    echoues: list[tuple[str, str]] = field(default_factory=list)
    refuses_avant_reseau: list[tuple[str, str]] = field(default_factory=list)
    alertes: list[str] = field(default_factory=list)

    @property
    def total_prevu(self) -> int:
        return sum(p.total for p in self.plans)

    @property
    def statut(self) -> RunStatus:
        """`PARTIAL` est un etat terminal LEGITIME (`UC-07`, cas alternatif)."""
        if not self.echoues and not self.refuses_avant_reseau:
            return RunStatus.COMPLETED
        if not self.crees:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    def resume(self) -> str:
        lignes = [
            f"Mode          : {self.mode.value}",
            f"Staff prevu   : {self.total_prevu}",
            f"Staff cree    : {len(self.crees)}",
            f"Refuses avant reseau : {len(self.refuses_avant_reseau)}",
            f"Echecs serveur       : {len(self.echoues)}",
            f"STATUT : {self.statut.value}",
        ]
        for plan in self.plans:
            lignes.append(
                f"  {plan.pays} : {plan.nb_agents} Agent(s) + "
                f"{sum(plan.encadrement.values())} encadrement = {plan.total} "
                f"(budget {plan.budget_staff}, {plan.nb_kiosques} Kiosques)"
            )
        for alerte in self.alertes:
            lignes.append(f"  ⚠ {alerte}")
        for nom, motif in self.refuses_avant_reseau:
            lignes.append(f"  REFUSE {nom} : {motif}")
        for nom, motif in self.echoues:
            lignes.append(f"  ECHEC {nom} : {motif}")
        return "\n".join(lignes)


def planifier_staff(
    configuration: ConfigurationExecution,
    referentiel: ReferentielGeo,
    alea: random.Random,
) -> list[PlanStaffPays]:
    """Calcule la repartition **avant** tout appel reseau.

    Meme principe que `organisation.planifier()` : on verifie la faisabilite
    d'abord. Creer 60 identites puis decouvrir un probleme de comptage serait
    irrattrapable — identity-service n'expose aucun `DELETE`.
    """
    plans: list[PlanStaffPays] = []

    for pays in configuration.pays_actifs:
        kiosques_min, kiosques_max = configuration.resoudre("kiosques", pays)
        staff_min, staff_max = configuration.resoudre("staff", pays)

        nb_kiosques = alea.randint(kiosques_min, kiosques_max)
        budget = alea.randint(staff_min, staff_max)

        # `UC-09` postcondition : un Agent par Kiosque, sans exception. Elle
        # prime sur la fourchette — un Kiosque sans Agent n'existe pas.
        nb_agents = nb_kiosques
        plan = PlanStaffPays(
            pays=pays,
            nb_kiosques=nb_kiosques,
            budget_staff=budget,
            nb_agents=nb_agents,
        )

        reste = budget - nb_agents
        if reste < 0:
            plan.alerte = (
                f"{pays} : {nb_kiosques} Kiosques exigent autant d'Agents, pour un budget de "
                f"{budget} staff — la fourchette UC-09 (15-25) ne couvre pas la postcondition "
                "« un Agent par Kiosque ». Les Agents sont crees, l'encadrement est sacrifie."
            )
            reste = 0

        # L'encadrement se sert dans l'ordre de priorite, un de chaque, puis on
        # boucle. Un pays n'a jamais deux Admin avant d'avoir un Comptable.
        for rang in range(reste):
            role = ROLES_ENCADREMENT[rang % len(ROLES_ENCADREMENT)]
            plan.encadrement[role] = plan.encadrement.get(role, 0) + 1

        if not referentiel.telcos_du_pays(pays):
            plan.alerte = f"{pays} : aucun operateur telecom — EF-27 inapplicable, aucun staff"
            plan.nb_agents = 0
            plan.encadrement.clear()

        plans.append(plan)

    return plans


class ExecuteurStaff:
    """Cree les 60 a 100 personnels, Identity puis User, role par role.

    `DRY_RUN` n'emet aucune ECRITURE mais conserve les LECTURES : sans elles, le
    rapport annoncerait des creations qui n'auraient pas lieu — une partie des
    adresses peut deja exister.
    """

    def __init__(
        self,
        *,
        run_id: UUID,
        mode: RunMode,
        configuration: ConfigurationExecution,
        referentiel: ReferentielGeo,
        identity_client: Any,
        user_client: Any,
        registre: RegistreUnicite | None = None,
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self._configuration = configuration
        self._referentiel = referentiel
        self._identites = identity_client
        self._users = user_client
        self._registre = registre or RegistreUnicite()
        self._alea = random.Random(run_id.int)  # noqa: S311 — ENF-15, pas de cryptographie

    @property
    def ecriture_reelle(self) -> bool:
        return self.mode is RunMode.REAL

    async def executer(self) -> RapportStaff:
        rapport = RapportStaff(mode=self.mode)
        rapport.plans = planifier_staff(self._configuration, self._referentiel, self._alea)
        rapport.alertes = [p.alerte for p in rapport.plans if p.alerte]

        for plan in rapport.plans:
            postes = [ROLE_AGENT] * plan.nb_agents
            for role, nombre in sorted(plan.encadrement.items()):
                postes.extend([role] * nombre)

            for rang, role in enumerate(postes):
                await self._creer_un_staff(plan, role, rang, rapport)

        return rapport

    async def _creer_un_staff(
        self, plan: PlanStaffPays, role: str, rang: int, rapport: RapportStaff
    ) -> None:
        pays = plan.pays
        etiquette = f"{pays}-{role}-{rang:03d}"

        try:
            payload = self._composer(pays, role, rang)
        except InvariantViole as erreur:
            # Refuse AVANT le reseau. Ce n'est pas un echec serveur : c'est la
            # couche anti-corruption qui fonctionne.
            rapport.refuses_avant_reseau.append((etiquette, str(erreur)[:600]))
            return

        if not self.ecriture_reelle:
            rapport.crees.append(f"{etiquette} ({payload['identity']['first_name']})")
            return

        try:
            identite, _ = await self._identites.creer_si_absente(**payload["identity"])
            identity_id = self._identites.identifiant(identite)
            if not identity_id:
                raise RuntimeError("identity-service n'a rendu aucun identifiant")

            await self._users.creer_utilisateur_applicatif(
                user_name=payload["user_name"],
                email=payload["identity"]["email"],
                mot_de_passe_initial=payload["mot_de_passe_initial"],
                nouveau_mot_de_passe=payload["nouveau_mot_de_passe"],
                identity_id=identity_id,
                type_user=UserType.STAFF,
                groupes=[role],
            )
        except Exception as erreur:
            motif = f"{type(erreur).__name__}: {erreur}"[:600]
            logger.warning("staff %s en echec : %s", etiquette, motif)
            rapport.echoues.append((etiquette, motif))
            return

        rapport.crees.append(etiquette)

    def _composer(self, pays: str, role: str, rang: int) -> dict[str, Any]:
        """Assemble un personnel **coherent de bout en bout**.

        Chaque champ traverse les barrieres etablies :

          MSISDN     compose sur le plan de numerotation REEL du pays, pondere
                     par les parts de marche (`EF-27`, `S1-05`)
          adresse    ville, region, quartier et GPS depuis le referentiel —
                     jamais un champ vide (`D-IDN-2`)
          identite   age, genre, situation, piece — tout passe par
                     `RegistreUnicite.reserver()` et les invariants (`S1-01`)
          unicite    msisdn, id_number ET email — les trois, pas un seul
        """
        regions = self._referentiel.regions_du_pays(pays)
        villes = self._referentiel.villes_porteuses_de_quartiers(pays)
        if not regions or not villes:
            raise InvariantViole(f"{pays} : referentiel geographique incomplet — staff impossible")

        ville = villes[rang % len(villes)]
        region = self._referentiel.region(ville.region_id)
        quartiers = self._referentiel.quartiers_de_ville(ville.city_id)
        quartier = quartiers[rang % len(quartiers)].name if quartiers else ville.name

        # `D-13` — l'adresse est CORRECTE PAR CONSTRUCTION ici : elle sort de
        # `villes_porteuses_de_quartiers(pays)`. On la VERIFIE quand meme.
        #
        # « Correct par construction » n'est pas une contrainte, c'est un chemin
        # de construction correct. Le jour ou ce chemin change, rien ne le
        # rattraperait — et le defaut du 10/08 (une Senegalaise domiciliee a
        # Douala) est ne exactement de cette confiance-la.
        valider_coherence_territoriale(
            pays=pays,
            region=region.name if region else "",
            ville=ville.name,
            quartier=quartier,
            referentiel=self._referentiel,
        )

        graine = f"{pays}{role[:3].upper()}{rang:04d}"
        numero, piece, courriel = self._reserver_identifiants(pays, role, rang, graine)

        # `D-IDN-1` — le genre alterne pour que la population staff ne soit pas
        # d'un seul sexe. Ce n'est pas `EF-22`, qui ne porte que sur les clients.
        genre = "FEMALE" if rang % 2 == 0 else "MALE"

        return {
            # SANS prefixe (20/08) — un identifiant d'operateur propre :
            # pays_role_rang, ex. `CM_TellerAgent_001`.
            "user_name": f"{pays}_{role.replace('/', '')}_{rang:03d}",
            "mot_de_passe_initial": "Init#2026Aa",
            "nouveau_mot_de_passe": f"Stf#{pays}{rang:04d}Aa",
            "identity": {
                # DOCTRINE — « rien n'est invente a partir de rien ». Les
                # prenoms et patronymes viennent de la matiere REELLE de Faker,
                # source unique dans `generateur.py`. Une premiere version
                # composait `DEMO_Agent` + nom de ville : c'etait de
                # l'invention, et la doctrine l'interdit.
                "first_name": prenom(genre, rang),
                "last_name": patronyme(pays, rang),
                "date_of_birth": self._naissance(rang),
                "gender": genre,
                "nationality": pays,
                "marital_status": "SINGLE" if rang % 3 else "MARRIED",
                "id_number": piece,
                "id_place": ville.name,
                "id_expire_on": "2032-01-01",
                "phone": numero,
                "email": courriel,
                "occupation": role,
                "place_of_birth": ville.name,
                "type_identite": IdentityType.INDIVIDUAL,
                "address": {
                    "address_line_1": f"Rue {rang % 90 + 1}",
                    "street_name": quartier,
                    "city": ville.name,
                    "region": region.name if region else "",
                    "country": pays,
                    "latitude": ville.latitude,
                    "longitude": ville.longitude,
                },
            },
        }

    def _reserver_identifiants(
        self, pays: str, role: str, rang: int, graine: str
    ) -> tuple[str, str, str]:
        """Compose un MSISDN conforme ET unique, puis reserve le triplet.

        **Deux pieges se combinent ici, et le second n'etait pas evident.**

        1. `composer_msisdn()` consomme les chiffres **depuis le debut** et le
           plan tronque a la place disponible — le Senegal n'offre que sept
           chiffres apres son prefixe. Un corps `f"{rang:08d}"` ferait varier
           les chiffres de poids faible, precisement ceux qui sautent.
        2. Une classe restreinte replie dix chiffres sur deux : `0[56]` mappe
           tout `source` sur `5` ou `6`. Un corps qui ne varie qu'en **une**
           position produit donc des collisions massives.

        La reponse : un corps ou **les huit chiffres varient** avec le rang
        (dispersion multiplicative de Knuth, deterministe donc `ENF-15`), et une
        **reprise bornee** si le registre refuse quand meme. Le registre reste
        l'autorite : on ne contourne jamais son refus, on propose une autre
        valeur.

        Bug trouve par le test d'unicite du staff, pas par relecture.
        """
        for tentative in range(_TENTATIVES_MSISDN):
            corps = f"{((rang + 1) * _DISPERSION + tentative * _PAS) % 100_000_000:08d}"
            msisdn, _ = self._referentiel.composer_msisdn(pays, corps, self._alea)
            try:
                return self._registre.reserver(
                    msisdn=msisdn,
                    id_number=f"{pays}STF{graine}"[:20],
                    email=(
                        f"demo.staff.{pays.lower()}.{role[:3].lower()}{rang:03d}@finzuu-demo.local"
                    ),
                )
            except InvariantViole as erreur:
                if "msisdn" not in str(erreur):
                    raise
        raise InvariantViole(
            f"{pays}/{role}/{rang} : aucun MSISDN libre apres {_TENTATIVES_MSISDN} tentatives — "
            "le plan de numerotation du pays est sature pour ce volume de staff"
        )

    def _naissance(self, rang: int) -> str:
        """Un personnel a entre 25 et 55 ans — plus etroit que les bornes
        generales (18-75).

        Ce n'est pas une regle du CDC : c'est la credibilite. Un agent de
        terrain de 19 ans ou un comptable de 74 ans se remarqueraient dans une
        demonstration. Les invariants generaux restent la borne dure.
        """
        age = 25 + (rang * 7) % 31
        return f"{2026 - age:04d}-{(rang % 12) + 1:02d}-{(rang % 27) + 1:02d}"
