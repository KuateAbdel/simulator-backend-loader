"""Tests hors ligne du socle de persistance.

Aucun MongoDB requis : on verifie ici ce qui doit etre juste AVANT toute base —
le hachage, la serialisation, et la machine d'etat. Les tests d'integration des
repositories exigeront une instance vivante, ils viendront separement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.core.security import hacher, verifier
from app.models.domain import FakerConsumptionLedger, LoaderRun, OrgHierarchyNode
from app.models.enums import FakerConsumptionType, NiveauOrganisation, RunMode, RunStatus
from app.repositories.base import en_document
from app.repositories.loader_runs import _TRANSITIONS


class TestSecurite:
    def test_aller_retour(self) -> None:
        empreinte = hacher("Pass1234")
        assert verifier("Pass1234", empreinte)

    def test_mauvais_mot_de_passe(self) -> None:
        assert not verifier("mauvais", hacher("Pass1234"))

    def test_le_sel_rend_chaque_empreinte_unique(self) -> None:
        """Deux fois le meme mot de passe ne doit jamais donner la meme empreinte."""
        assert hacher("Pass1234") != hacher("Pass1234")

    def test_le_clair_n_apparait_jamais_dans_l_empreinte(self) -> None:
        assert "Pass1234" not in hacher("Pass1234")

    @pytest.mark.parametrize(
        "empreinte", ["", "nimporte-quoi", "bcrypt$1$2$3$4", "scrypt$a$b$c$d$e"]
    )
    def test_empreinte_illisible_refuse_sans_lever(self, empreinte: str) -> None:
        """Un format inattendu en base refuse l'acces — il ne provoque pas une
        erreur serveur."""
        assert verifier("Pass1234", empreinte) is False


class TestSerialisation:
    def test_l_alias_id_est_ecrit(self) -> None:
        entree = FakerConsumptionLedger(
            id="RC-CM-IND-CMC1",
            consumed_at=datetime.now(UTC),
            consumed_for=FakerConsumptionType.COLLECT_CLIENT,
            resulting_entity_id=uuid4(),
            country_code="CM",
        )
        document = en_document(entree)
        assert "_id" in document and "id" not in document
        assert document["_id"] == "RC-CM-IND-CMC1"

    def test_les_dates_deviennent_des_chaines_iso(self) -> None:
        """BSON ne sait pas encoder datetime.date — d'ou la regle JSON-native."""
        run = LoaderRun(
            id=uuid4(),
            sim_start_date=date(2026, 2, 9),
            sim_end_date=date(2026, 8, 8),
            status=RunStatus.PENDING,
            mode=RunMode.DRY_RUN,
        )
        document = en_document(run)
        assert document["sim_start_date"] == "2026-02-09"
        assert isinstance(document["_id"], str)
        assert document["mode"] == "DRY_RUN"

    def test_aller_retour_complet(self) -> None:
        origine = OrgHierarchyNode(
            id=uuid4(),
            run_id=uuid4(),
            niveau=NiveauOrganisation.KIOSQUE,
            parent_id=uuid4(),
            company_id=uuid4(),
            name="DEMO_Kiosque Bepanda",
            country_code="CM",
            district_id="CM-DOUALA-BEPANDA",
            depositary_id=uuid4(),
        )
        relu = OrgHierarchyNode.model_validate(en_document(origine))
        assert relu == origine

    def test_champ_surnumeraire_refuse(self) -> None:
        """extra='forbid' : un champ non prevu au diagramme de classe est rejete."""
        with pytest.raises(ValueError, match="Extra inputs"):
            LoaderRun.model_validate(
                {
                    "_id": str(uuid4()),
                    "sim_start_date": "2026-02-09",
                    "sim_end_date": "2026-08-08",
                    "champ_invente": "x",
                }
            )


class TestMachineDEtat:
    """06_state.puml — LoaderRun.status."""

    def test_le_depart_est_pending(self) -> None:
        run = LoaderRun(id=uuid4(), sim_start_date=date(2026, 2, 9), sim_end_date=date(2026, 8, 8))
        assert run.status is RunStatus.PENDING
        assert run.mode is RunMode.DRY_RUN, "le mode REEL doit rester une action explicite"

    def test_transitions_conformes_au_diagramme(self) -> None:
        assert _TRANSITIONS[RunStatus.PENDING] == frozenset({RunStatus.RUNNING})
        assert _TRANSITIONS[RunStatus.PAUSED] == frozenset({RunStatus.RUNNING})
        assert _TRANSITIONS[RunStatus.RUNNING] == frozenset(
            {RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED}
        )

    @pytest.mark.parametrize("terminal", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.PARTIAL])
    def test_les_etats_terminaux_n_ont_aucune_sortie(self, terminal: RunStatus) -> None:
        """PARTIAL est terminal et LEGITIME : le CDC prevoit qu'une entite en
        echec soit journalisee et que l'execution se poursuive (UC-07/UC-08)."""
        assert _TRANSITIONS[terminal] == frozenset()

    def test_tous_les_statuts_sont_couverts(self) -> None:
        assert set(_TRANSITIONS) == set(RunStatus)
