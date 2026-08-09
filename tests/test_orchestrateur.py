"""
tests/test_orchestrateur.py
===========================
`S3-01` — les garanties de l'enchainement, pas son cablage.

Ce que ces tests protegent, dans l'ordre d'importance :

  1. **l'ordre topologique** — il n'existe QUE dans la declaration de `Etape`.
     Une reorganisation involontaire de l'enum casserait le run sans qu'aucun
     autre test ne le voie.
  2. **`PARTIAL` poursuit, `FAILED` arrete** — la distinction porte tout le
     comportement du CDC (UC-07/UC-08, cas alternatif).
  3. **le module non livre est DIT** — jamais confondu avec un succes.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.enums import RunMode, RunStatus
from app.services.orchestrateur import (
    PLAFOND_WORKERS,
    Etape,
    Issue,
    Orchestrateur,
)


class _RapportFactice:
    def __init__(self, statut: RunStatus, resume: str = "factice") -> None:
        self._statut = statut
        self._resume = resume

    @property
    def statut(self) -> RunStatus:
        return self._statut

    def resume(self) -> str:
        return self._resume


def _travail(statut: RunStatus, journal: list[Etape] | None = None, etape: Etape | None = None):
    async def _f():
        if journal is not None and etape is not None:
            journal.append(etape)
        return _RapportFactice(statut)

    return _f


class TestOrdreTopologique:
    def test_l_ordre_de_l_enum_est_l_ordre_du_cdc(self) -> None:
        """L'ordre n'est ecrit NULLE PART ailleurs que dans cette enumeration.

        Chaque module consomme un identifiant produit par le precedent :
        un Admin User exige un `group_id`, un Produit un `company_id`, un
        AGENT un Kiosque (`D-11`), un onboarding un `product_id`.
        """
        assert list(Etape) == [
            Etape.ROLES,
            Etape.ORGANISATION,
            Etape.CATALOGUE,
            Etape.DEPOSITAIRES,
            Etape.STAFF,
            Etape.CLIENTS,
            Etape.VIE,
            Etape.RECETTE,
        ]

    def test_les_roles_passent_en_premier_car_seul_module_reversible(self) -> None:
        """`DELETE /groupes/{id}` existe ; rien d'equivalent sur account,
        identity ou depositary. Un echec au module 1 ne laisse aucune trace."""
        assert next(iter(Etape)) is Etape.ROLES

    @pytest.mark.asyncio
    async def test_les_etapes_s_executent_dans_l_ordre_declare(self) -> None:
        journal: list[Etape] = []
        orch = Orchestrateur(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            travaux={
                e: _travail(RunStatus.COMPLETED, journal, e)
                for e in (Etape.STAFF, Etape.ROLES, Etape.ORGANISATION)  # ordre volontairement faux
            },
        )
        await orch.executer()
        assert journal == [Etape.ROLES, Etape.ORGANISATION, Etape.STAFF]


class TestPartielContreEchec:
    """La distinction qui porte tout le comportement du CDC."""

    @pytest.mark.asyncio
    async def test_partial_ne_bloque_pas_la_suite(self) -> None:
        """UC-07 : « le Loader journalise l'erreur et poursuit avec la Company
        suivante ». Une entite recalcitrante n'arrete pas la campagne."""
        journal: list[Etape] = []
        orch = Orchestrateur(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            travaux={
                Etape.ROLES: _travail(RunStatus.PARTIAL, journal, Etape.ROLES),
                Etape.ORGANISATION: _travail(RunStatus.COMPLETED, journal, Etape.ORGANISATION),
            },
        )
        rapport = await orch.executer()
        assert journal == [Etape.ROLES, Etape.ORGANISATION]
        assert rapport.interrompu_a is None
        assert rapport.statut is RunStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_failed_arrete_tout_car_la_suite_attend_ses_identifiants(self) -> None:
        journal: list[Etape] = []
        orch = Orchestrateur(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            travaux={
                Etape.ROLES: _travail(RunStatus.FAILED, journal, Etape.ROLES),
                Etape.ORGANISATION: _travail(RunStatus.COMPLETED, journal, Etape.ORGANISATION),
            },
        )
        rapport = await orch.executer()
        assert journal == [Etape.ROLES], "l'Organisation ne doit PAS avoir ete tentee"
        assert rapport.interrompu_a is Etape.ROLES
        assert rapport.statut is RunStatus.FAILED

    @pytest.mark.asyncio
    async def test_une_exception_est_isolee_et_traitee_comme_un_echec(self) -> None:
        """Une exception qui traverse un executeur est un defaut de CE module.
        On l'isole pour que le rapport reste lisible — et on ne la rejoue pas."""

        async def _explose():
            raise RuntimeError("connexion perdue")

        orch = Orchestrateur(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            travaux={Etape.ROLES: _explose},
        )
        rapport = await orch.executer()
        assert rapport.etapes[0].issue is Issue.FAILED
        assert "RuntimeError" in rapport.etapes[0].detail


class TestHonnetete:
    @pytest.mark.asyncio
    async def test_un_module_non_livre_est_dit_et_empeche_COMPLETED(self) -> None:
        """Clients, Vie et Recette n'existent pas encore. Un rapport qui les
        omettrait mentirait par omission — et ces trous sont le plan de travail."""
        orch = Orchestrateur(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            travaux={e: _travail(RunStatus.COMPLETED) for e in list(Etape)[:5]},
        )
        rapport = await orch.executer()
        manquants = [e.etape for e in rapport.etapes if e.issue is Issue.NON_LIVRE]
        assert manquants == [Etape.CLIENTS, Etape.VIE, Etape.RECETTE]
        assert rapport.statut is RunStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_un_run_entierement_livre_et_reussi_est_COMPLETED(self) -> None:
        orch = Orchestrateur(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            travaux={e: _travail(RunStatus.COMPLETED) for e in Etape},
        )
        assert (await orch.executer()).statut is RunStatus.COMPLETED


class TestReprise:
    def test_seul_un_checkpoint_COMPLETED_est_acquis(self) -> None:
        """Une etape `PARTIAL` est REJOUEE : son `GET`-avant-`POST` reutilisera
        l'existant et rattrapera les entites qu'elle avait ratees."""
        acquises = Orchestrateur.etapes_acquises(
            [
                {"phase": "ROLES", "detail": {"issue": "COMPLETED"}},
                {"phase": "ORGANISATION", "detail": {"issue": "PARTIAL"}},
            ]
        )
        assert acquises == [Etape.ROLES]

    def test_un_checkpoint_de_phase_inconnue_est_ignore_pas_fatal(self) -> None:
        """Un run d'une version anterieure ne doit pas faire planter la reprise —
        et l'etape inconnue sera rejouee, jamais sautee a tort."""
        assert (
            Orchestrateur.etapes_acquises(
                [{"phase": "ANCIENNE_PHASE", "detail": {"issue": "COMPLETED"}}]
            )
            == []
        )

    @pytest.mark.asyncio
    async def test_une_etape_acquise_n_est_pas_rejouee(self) -> None:
        journal: list[Etape] = []
        orch = Orchestrateur(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            travaux={
                Etape.ROLES: _travail(RunStatus.COMPLETED, journal, Etape.ROLES),
                Etape.ORGANISATION: _travail(RunStatus.COMPLETED, journal, Etape.ORGANISATION),
            },
            etapes_deja_faites=[Etape.ROLES],
        )
        rapport = await orch.executer()
        assert journal == [Etape.ORGANISATION]
        assert rapport.etapes[0].issue is Issue.REPRISE


class TestPlafondDeConcurrence:
    def test_le_plafond_est_la_borne_BASSE_du_domaine_mesure(self) -> None:
        """`H14`/`H15` : degradation SILENCIEUSE au-dela de 20 a 30 workers,
        sans `429`. On ne s'approche pas du bord d'une falaise invisible."""
        assert PLAFOND_WORKERS == 20
