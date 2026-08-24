"""Execution du module Staff — UC-09, story S2-03.

Le premier module ou TOUT converge : configuration parametrable, referentiel
enrichi, invariants de credibilite, registre d'unicite, les 11 roles.

Chaque staff produit une Identity DEFINITIVE — identity-service n'expose aucun
DELETE. Le DRY_RUN n'est donc pas un confort : c'est la seule facon de voir 60 a
100 creations avant qu'elles ne soient permanentes.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.configuration import ConfigurationExecution, Surcharge
from app.models.enums import RunMode, RunStatus
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.staff_execution import (
    ROLE_AGENT,
    ROLES_ENCADREMENT,
    ExecuteurStaff,
    planifier_staff,
)

RUN_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture(scope="module")
def base() -> ReferentielGeo:
    return charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))


def graine(valeur: int) -> random.Random:
    return random.Random(valeur)  # noqa: S311


class IdentityDouble:
    def __init__(self) -> None:
        self.creees: list[dict[str, Any]] = []

    async def creer_si_absente(self, **champs: Any) -> tuple[dict[str, Any], bool]:
        self.creees.append(champs)
        return {"_id": f"id-{len(self.creees)}"}, True

    @staticmethod
    def identifiant(identite: dict[str, Any]) -> str | None:
        return str(identite.get("_id"))


class UserDouble:
    def __init__(self) -> None:
        self.creees: list[dict[str, Any]] = []

    async def creer_utilisateur_applicatif(self, **champs: Any) -> dict[str, Any]:
        self.creees.append(champs)
        return {"access_token": "x"}


class UserDefaillant(UserDouble):
    async def creer_utilisateur_applicatif(self, **champs: Any) -> dict[str, Any]:
        raise RuntimeError("HTTP 400 refuse")


def _executeur(mode: RunMode, base: ReferentielGeo, config: ConfigurationExecution | None = None):  # type: ignore[no-untyped-def]
    identites, users = IdentityDouble(), UserDouble()
    executeur = ExecuteurStaff(
        run_id=RUN_ID,
        mode=mode,
        configuration=config or ConfigurationExecution.defaut_cdc(),
        referentiel=base,
        identity_client=identites,
        user_client=users,
    )
    return executeur, identites, users


class TestPlanification:
    """Meme principe qu'`organisation.planifier()` : la faisabilite est
    verifiee AVANT tout appel. Creer 60 identites puis decouvrir un probleme
    serait irrattrapable."""

    def test_un_agent_par_kiosque_sans_exception(self, base: ReferentielGeo) -> None:
        """UC-09, postcondition : « chaque Kiosque possede au moins un Agent »."""
        plans = planifier_staff(ConfigurationExecution.defaut_cdc(), base, graine(1))
        assert all(p.nb_agents == p.nb_kiosques for p in plans)

    def test_les_quatre_pays_sont_planifies(self, base: ReferentielGeo) -> None:
        plans = planifier_staff(ConfigurationExecution.defaut_cdc(), base, graine(1))
        assert sorted(p.pays for p in plans) == ["BF", "CI", "CM", "SN"]

    def test_un_pays_desactive_n_est_pas_planifie(self, base: ReferentielGeo) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "A-01")
        plans = planifier_staff(config, base, graine(1))
        assert "SN" not in {p.pays for p in plans}

    def test_le_conflit_arithmetique_est_signale_pas_absorbe(self, base: ReferentielGeo) -> None:
        """UC-09 demande 15-25 staff ET un Agent par Kiosque, avec 10-20
        Kiosques. Rien ne garantit que le premier couvre le second."""
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].surcharge = Surcharge(staff=(15, 15), kiosques=(20, 20))
        plan = next(p for p in planifier_staff(config, base, graine(1)) if p.pays == "CM")

        assert plan.nb_agents == 20, "la postcondition prime sur la fourchette"
        assert plan.encadrement == {}, "l'encadrement est sacrifie, pas les Agents"
        assert "ne couvre pas la postcondition" in plan.alerte

    def test_l_encadrement_se_sert_dans_l_ordre_de_priorite(self, base: ReferentielGeo) -> None:
        """Un pays n'a jamais deux Admin avant d'avoir un Comptable."""
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CI"].surcharge = Surcharge(staff=(13, 13), kiosques=(10, 10))
        plan = next(p for p in planifier_staff(config, base, graine(2)) if p.pays == "CI")

        assert plan.nb_agents == 10
        assert sum(plan.encadrement.values()) == 3
        assert list(plan.encadrement) == list(ROLES_ENCADREMENT[:3])

    def test_super_admin_n_est_jamais_par_pays(self) -> None:
        """C'est un role de plateforme, cree une seule fois."""
        assert "Super-Admin" not in ROLES_ENCADREMENT


class TestDryRun:
    async def test_aucune_ecriture_n_est_emise(self, base: ReferentielGeo) -> None:
        executeur, identites, users = _executeur(RunMode.DRY_RUN, base)
        rapport = await executeur.executer()

        assert identites.creees == []
        assert users.creees == []
        assert rapport.crees, "le dry-run doit annoncer ce qui serait cree"
        assert rapport.statut is RunStatus.COMPLETED

    async def test_le_volume_annonce_correspond_au_plan(self, base: ReferentielGeo) -> None:
        executeur, _, _ = _executeur(RunMode.DRY_RUN, base)
        rapport = await executeur.executer()
        assert len(rapport.crees) == rapport.total_prevu


class TestCoherenceDeChaqueStaff:
    """Chaque champ traverse les barrieres etablies aux sprints precedents."""

    async def test_le_msisdn_est_attribuable_a_un_operateur_reel(
        self, base: ReferentielGeo
    ) -> None:
        """EF-27 — le numero doit appartenir a un reseau du pays."""
        executeur, identites, _ = _executeur(RunMode.REAL, base)
        await executeur.executer()

        for champs in identites.creees:
            pays = champs["nationality"]
            assert base.operateur_du_msisdn(champs["phone"], pays) is not None

    async def test_aucune_adresse_n_a_de_champ_vide(self, base: ReferentielGeo) -> None:
        """D-IDN-2 — le serveur les accepte a null ; nous non."""
        executeur, identites, _ = _executeur(RunMode.REAL, base)
        await executeur.executer()

        for champs in identites.creees:
            adresse = champs["address"]
            for cle in ("address_line_1", "street_name", "city", "region", "country"):
                assert adresse[cle], f"{cle} vide"

    async def test_les_trois_unicites_tiennent_sur_tout_le_staff(
        self, base: ReferentielGeo
    ) -> None:
        """EF-25 n'en cite qu'une ; le serveur en impose trois."""
        executeur, identites, _ = _executeur(RunMode.REAL, base)
        await executeur.executer()

        for cle in ("phone", "id_number", "email"):
            valeurs = [c[cle] for c in identites.creees]
            assert len(valeurs) == len(set(valeurs)), f"doublon sur {cle}"

    async def test_l_age_reste_dans_les_bornes_de_credibilite(self, base: ReferentielGeo) -> None:
        executeur, identites, _ = _executeur(RunMode.REAL, base)
        await executeur.executer()

        for champs in identites.creees:
            annee = int(str(champs["date_of_birth"])[:4])
            assert 25 <= 2026 - annee <= 55, "un agent de 19 ans se remarquerait"

    async def test_le_staff_n_est_pas_d_un_seul_genre(self, base: ReferentielGeo) -> None:
        executeur, identites, _ = _executeur(RunMode.REAL, base)
        await executeur.executer()
        assert {c["gender"] for c in identites.creees} == {"MALE", "FEMALE"}

    async def test_chaque_user_porte_son_role_et_le_type_staff(self, base: ReferentielGeo) -> None:
        executeur, _, users = _executeur(RunMode.REAL, base)
        await executeur.executer()

        roles_attendus = set(ROLES_ENCADREMENT) | {ROLE_AGENT}
        for champs in users.creees:
            assert champs["type_user"].value == "STAFF"
            assert len(champs["groupes"]) == 1
            assert champs["groupes"][0] in roles_attendus

    async def test_l_identity_precede_toujours_le_user(self, base: ReferentielGeo) -> None:
        """`CreateUserSchema.identity` est REQUIS — la sequence n'est pas un
        choix."""
        executeur, identites, users = _executeur(RunMode.REAL, base)
        await executeur.executer()
        assert len(identites.creees) == len(users.creees)


class TestResilience:
    async def test_un_echec_serveur_journalise_et_poursuit(self, base: ReferentielGeo) -> None:
        """UC-07, cas alternatif : le run ne s'arrete jamais sur une entite."""
        executeur = ExecuteurStaff(
            run_id=RUN_ID,
            mode=RunMode.REAL,
            configuration=ConfigurationExecution.defaut_cdc(),
            referentiel=base,
            identity_client=IdentityDouble(),
            user_client=UserDefaillant(),
        )
        rapport = await executeur.executer()

        assert rapport.statut is RunStatus.FAILED, "aucun staff cree"
        assert rapport.echoues
        assert all(len(motif) <= 200 for _, motif in rapport.echoues)

    async def test_le_rapport_distingue_refus_et_echec(self, base: ReferentielGeo) -> None:
        """Un refus avant reseau n'est pas un echec serveur : c'est la couche
        anti-corruption qui fonctionne."""
        executeur, _, _ = _executeur(RunMode.DRY_RUN, base)
        rapport = await executeur.executer()
        assert "Refuses avant reseau" in rapport.resume()
        assert "Echecs serveur" in rapport.resume()

class ArbreDouble:
    """Un arbre en memoire : les Kiosques que Depositaires aurait crees, et
    les Agents que le Staff y rattache."""

    def __init__(self, kiosques_par_pays: dict[str, int]) -> None:
        from types import SimpleNamespace

        self.kiosques = [
            SimpleNamespace(
                id=uuid4(),
                company_id=uuid4(),
                country_code=pays,
                name=f"Kiosque {pays}-{i}",
            )
            for pays, nombre in kiosques_par_pays.items()
            for i in range(nombre)
        ]
        self.agents: list[dict[str, Any]] = []

    async def par_niveau(self, run_id: Any, niveau: Any) -> list[Any]:
        from app.models.enums import NiveauOrganisation

        return self.kiosques if niveau is NiveauOrganisation.KIOSQUE else []

    async def ajouter_agent(self, **champs: Any) -> None:
        self.agents.append(champs)


class TestUC09UnAgentParKiosque:
    """`UC-09` postcondition — « chaque Kiosque possede au moins un Agent ».

    Le defaut que ces tests verrouillent : `org_hierarchy.ajouter_agent()`
    n'avait AUCUN appelant dans tout le depot. Le niveau AGENT etait declare,
    la recette comptait les Agents par Kiosque, et rien n'en creait jamais un.
    Chaque run REEL violait donc la postcondition PAR CONSTRUCTION, quel que
    soit le budget — le run du 24/08 a conclu « 4 Kiosque(s) sans Agent ».

    Second defaut, meme cause racine : le plan tirait son `nb_kiosques` dans
    `alea.randint()`, sans regarder ce que le module Depositaires venait de
    creer. Il a planifie 17 Agents pour le Cameroun quand la plateforme
    portait 4 Kiosques au Burkina.
    """

    async def test_chaque_kiosque_REEL_recoit_au_moins_un_agent(
        self, base: ReferentielGeo
    ) -> None:
        arbre = ArbreDouble({"CM": 4, "CI": 3})
        executeur = ExecuteurStaff(
            run_id=RUN_ID,
            mode=RunMode.REAL,
            configuration=ConfigurationExecution.defaut_cdc(),
            referentiel=base,
            identity_client=IdentityDouble(),
            user_client=UserDouble(),
            arbre=arbre,
        )
        await executeur.executer()

        servis = {champs["kiosque_id"] for champs in arbre.agents}
        attendus = {k.id for k in arbre.kiosques if k.country_code in {"CM", "CI"}}
        assert attendus <= servis, (
            f"{len(attendus - servis)} Kiosque(s) sans Agent — UC-09 viole"
        )

    async def test_le_plan_se_recadre_sur_les_kiosques_qui_EXISTENT(
        self, base: ReferentielGeo
    ) -> None:
        """4 Kiosques reels => 4 Agents, jamais les 17 du tirage."""
        arbre = ArbreDouble({"CM": 4})
        executeur = ExecuteurStaff(
            run_id=RUN_ID,
            mode=RunMode.REAL,
            configuration=ConfigurationExecution.defaut_cdc(),
            referentiel=base,
            identity_client=IdentityDouble(),
            user_client=UserDouble(),
            arbre=arbre,
        )
        rapport = await executeur.executer()
        plan_cm = next(p for p in rapport.plans if p.pays == "CM")
        assert plan_cm.nb_kiosques == 4
        assert plan_cm.nb_agents == 4

    async def test_l_encadrement_n_est_affilie_a_AUCUN_kiosque(
        self, base: ReferentielGeo
    ) -> None:
        """Un Comptable ne tient pas un guichet. Seuls les Agents sont
        rattaches — sinon le compte par Kiosque devient un mensonge."""
        arbre = ArbreDouble({"CM": 2})
        executeur = ExecuteurStaff(
            run_id=RUN_ID,
            mode=RunMode.REAL,
            configuration=ConfigurationExecution.defaut_cdc(),
            referentiel=base,
            identity_client=IdentityDouble(),
            user_client=UserDouble(),
            arbre=arbre,
        )
        rapport = await executeur.executer()
        plan_cm = next(p for p in rapport.plans if p.pays == "CM")
        assert len(arbre.agents) == plan_cm.nb_agents
        assert sum(plan_cm.encadrement.values()) > 0, "l'encadrement doit exister"

    async def test_sans_arbre_le_staff_ne_fabrique_aucune_affectation(
        self, base: ReferentielGeo
    ) -> None:
        """DRY_RUN, ou module Depositaires non execute : on ne rattache rien a
        un Kiosque qui n'existe pas."""
        executeur, _, _ = _executeur(RunMode.REAL, base)
        rapport = await executeur.executer()
        assert rapport.affectations == []

