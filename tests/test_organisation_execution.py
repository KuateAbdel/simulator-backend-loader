"""Execution du module Organisation en DRY_RUN — hors ligne, avec des doublures.

Ce que ce test prouve : la chaine complete de l'etape 2 se deroule de bout en
bout **sans emettre une seule ecriture**. C'est la seule facon responsable
d'aborder company-service et account-service, qui n'exposent aucun DELETE.

Il verifie aussi le comportement en echec : UC-07 exige que « le Loader
journalise l'erreur et poursuit avec la Company suivante ». Le statut devient
alors PARTIAL — un etat terminal LEGITIME, pas un plantage.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.clients.base import ErreurService
from app.core.cdc import COMPTES_LENDER, LENDERS_INSTITUTIONNELS
from app.models.enums import RunMode, RunStatus
from app.services.generateur import Generateur
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.organisation import planifier
from app.services.organisation_execution import (
    DEVISE_PAR_PAYS,
    ExecuteurOrganisation,
    RapportOrganisation,
)

RUN_ID = UUID("11111111-2222-3333-4444-555555555555")
SIM_START = date(2026, 2, 9)
SIM_END = date(2026, 8, 8)


# -- Doublures : aucune sortie reseau -------------------------------------


class CompanyClientMuet:
    """Repond « rien ne pre-existe » et compte les ecritures tentees."""

    def __init__(self) -> None:
        self.ecritures = 0

    async def chercher_par_short_name(self, short_name: str) -> dict[str, Any] | None:
        return None

    async def creer_company(self, **kwargs: Any) -> dict[str, Any]:
        self.ecritures += 1
        return {"_id": str(uuid4()), "name": kwargs["name"], "owner": {"_id": str(uuid4())}}

    async def creer_licence(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.ecritures += 1
        return {"_id": str(uuid4())}

    async def a_une_licence(self, company_id: Any) -> bool:
        return False

    @staticmethod
    def identifiant(company: dict[str, Any]) -> str | None:
        return str(company.get("_id")) if company.get("_id") else None

    @staticmethod
    def identifiant_owner(company: dict[str, Any]) -> str | None:
        owner = company.get("owner")
        return str(owner.get("_id")) if isinstance(owner, dict) and owner.get("_id") else None


class CompanyClientDefaillant(CompanyClientMuet):
    """Reproduit ANO-CPY-BUG-06 : la creation echoue en HTTP 400."""

    async def creer_company(self, **kwargs: Any) -> dict[str, Any]:
        raise ErreurService(
            "company-service",
            "POST",
            "/api/v1/companies/",
            400,
            "'NoneType' object has no attribute 'email'",
            "req-test",
        )


class UserClientMuet:
    def __init__(self) -> None:
        self.ecritures = 0

    async def creer_utilisateur_applicatif(self, **kwargs: Any) -> dict[str, Any]:
        self.ecritures += 1
        return {"access_token": "x"}


class AccountClientMuet:
    def __init__(self) -> None:
        self.ecritures = 0

    async def comptes_du_proprietaire(self, owner_id: Any) -> list[dict[str, Any]]:
        return []

    async def creer_compte(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ecritures += 1
        return {"_id": str(uuid4())}

    def payload_compte(self, **kwargs: Any) -> dict[str, Any]:
        return {"type": kwargs["type_compte"].value}

    def payloads_des_4_comptes_lender(
        self, company_id: Any, owner_name: str, currency: str
    ) -> dict[str, dict[str, Any]]:
        return {nom.lower(): {"type": nom, "currency": currency} for nom in COMPTES_LENDER}

    @staticmethod
    def identifiant(compte: dict[str, Any]) -> str | None:
        return str(compte.get("_id"))

    @staticmethod
    def types_presents(comptes: list[dict[str, Any]]) -> set[str]:
        return set()


class RegistreMuet:
    def __init__(self) -> None:
        self.inscrits: list[str] = []

    async def enregistrer(self, **kwargs: Any) -> Any:
        self.inscrits.append(str(kwargs["company_id"]))

        class _Entree:
            id = uuid4()

        return _Entree()


class AuditMuet:
    def __init__(self) -> None:
        self.entrees: list[str] = []

    async def journaliser(self, **kwargs: Any) -> None:
        self.entrees.append(str(kwargs["entity_type"]))


@pytest.fixture(scope="module")
def referentiel() -> ReferentielGeo:
    return charger_referentiel(
        __import__("pathlib").Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
    )


def _executeur(mode: RunMode, referentiel: ReferentielGeo, company_client: Any = None):  # type: ignore[no-untyped-def]
    doublures = {
        "company": company_client or CompanyClientMuet(),
        "user": UserClientMuet(),
        "account": AccountClientMuet(),
        "registre": RegistreMuet(),
        "audit": AuditMuet(),
    }
    executeur = ExecuteurOrganisation(
        run_id=RUN_ID,
        mode=mode,
        referentiel=referentiel,
        generateur=Generateur(RUN_ID),
        company_client=doublures["company"],
        user_client=doublures["user"],
        account_client=doublures["account"],
        registre_lenders=doublures["registre"],
        audit=doublures["audit"],
    )
    return executeur, doublures


class TestDryRun:
    async def test_aucune_ecriture_n_est_emise(self, referentiel: ReferentielGeo) -> None:
        """Le coeur du DRY_RUN : la chaine se deroule, rien n'est ecrit."""
        executeur, doublures = _executeur(RunMode.DRY_RUN, referentiel)
        plan = planifier(referentiel, RUN_ID)

        rapport = await executeur.executer(plan, SIM_START, SIM_END)

        assert doublures["company"].ecritures == 0
        assert doublures["user"].ecritures == 0
        assert doublures["account"].ecritures == 0
        assert rapport.companies_creees, "le dry-run doit annoncer ce qui serait cree"

    async def test_le_rapport_annonce_la_volumetrie_du_plan(
        self, referentiel: ReferentielGeo
    ) -> None:
        executeur, _ = _executeur(RunMode.DRY_RUN, referentiel)
        plan = planifier(referentiel, RUN_ID)

        rapport = await executeur.executer(plan, SIM_START, SIM_END)

        attendu = sum(p.nb_companies for p in plan.pays)
        assert len(rapport.companies_creees) == attendu
        assert len(rapport.admins_crees) == attendu, "un Admin User par Company (D-CMP-2)"
        assert rapport.statut is RunStatus.COMPLETED

    async def test_les_4_lenders_institutionnels_sont_prevus(
        self, referentiel: ReferentielGeo
    ) -> None:
        """UC-08 : noms fixes, jamais issus de Faker."""
        executeur, _ = _executeur(RunMode.DRY_RUN, referentiel)
        rapport = await executeur.executer(planifier(referentiel, RUN_ID), SIM_START, SIM_END)
        for nom in LENDERS_INSTITUTIONNELS:
            assert any(nom in ligne for ligne in rapport.lenders_enregistres)


class TestAnticipationDesAnomalies:
    async def test_ano_cpy_bug_06_journalise_et_poursuit(self, referentiel: ReferentielGeo) -> None:
        """UC-07, cas alternatif : « le Loader journalise l'erreur et poursuit
        avec la Company suivante ». Le run ne s'arrete jamais sur une entite."""
        executeur, _ = _executeur(RunMode.REAL, referentiel, CompanyClientDefaillant())
        plan = planifier(referentiel, RUN_ID)

        rapport = await executeur.executer(plan, SIM_START, SIM_END)

        assert rapport.companies_echouees, "l'echec doit etre journalise"
        assert all("NoneType" in motif for _, motif in rapport.companies_echouees)
        assert len(rapport.companies_echouees) == sum(p.nb_companies for p in plan.pays), (
            "toutes les Companies ont ete tentees, aucune interruption"
        )
        assert rapport.statut is RunStatus.FAILED, "aucune Company creee = probleme systemique"

    async def test_un_echec_partiel_donne_partial(self, referentiel: ReferentielGeo) -> None:
        """PARTIAL est un etat terminal LEGITIME, pas un plantage."""
        rapport = RapportOrganisation(mode=RunMode.REAL)
        rapport.companies_creees.append("DEMO_SARL Kouassi")
        rapport.companies_echouees.append(("DEMO_SA Kabore", "HTTP 400"))
        assert rapport.statut is RunStatus.PARTIAL

    async def test_le_detail_serveur_est_tronque(self, referentiel: ReferentielGeo) -> None:
        """ANO-CPY-LEAK-07 : les messages fuient des traces Python. On les
        tronque avant journalisation, on ne les parse jamais."""
        executeur, _ = _executeur(RunMode.REAL, referentiel, CompanyClientDefaillant())
        rapport = await executeur.executer(planifier(referentiel, RUN_ID), SIM_START, SIM_END)
        for _, motif in rapport.companies_echouees:
            assert len(motif) <= 200


def test_fra199_la_devise_est_connue_du_loader() -> None:
    """`Company.currency` est write-only et perdue a la persistance — le Loader
    doit savoir laquelle il a envoyee."""
    assert DEVISE_PAR_PAYS["CM"] == "XAF"
    assert DEVISE_PAR_PAYS["CI"] == DEVISE_PAR_PAYS["BF"] == DEVISE_PAR_PAYS["SN"] == "XOF"
