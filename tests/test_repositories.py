"""Tests hors ligne du socle de persistance.

Aucun MongoDB requis : on verifie ici ce qui doit etre juste AVANT toute base —
le hachage, la serialisation, et la machine d'etat. Les tests d'integration des
repositories exigeront une instance vivante, ils viendront separement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.core.configuration import ConfigurationExecution
from app.core.security import hacher, verifier
from app.models.domain import FakerConsumptionLedger, LoaderRun, OrgHierarchyNode
from app.models.enums import FakerConsumptionType, NiveauOrganisation, RunMode, RunStatus
from app.repositories.audit_trail import (
    ACTION_INTENTION,
    ACTION_RESULTAT,
    STATUT_ECHEC,
    STATUT_SUCCES,
    SuiviIntention,
)
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


class TestJournalIntention:
    """Sprint 1 — la seule atomicite disponible.

    `POST /clients/onboard` ecrit dans TROIS services, sans transaction, sans
    rollback, et sans `DELETE` nulle part. Une cascade interrompue laisse une
    Identity et un compte orphelins, definitifs.

    Ces tests verifient la machine d'etat du journal **hors ligne** : le cycle
    INTENTION -> RESULTAT, et le fait qu'une issue soit toujours declaree.
    """

    def test_une_intention_neuve_n_a_pas_d_issue(self) -> None:
        suivi = SuiviIntention(intention_id=uuid4(), entity_id=uuid4())
        assert suivi.statut is None

    def test_reussi_porte_le_rendu_du_serveur(self) -> None:
        suivi = SuiviIntention(intention_id=uuid4(), entity_id=uuid4())
        suivi.reussi({"client_id": "abc", "account_id": "def"})
        assert suivi.statut == STATUT_SUCCES
        assert suivi.detail["account_id"] == "def"

    def test_echoue_porte_le_motif(self) -> None:
        suivi = SuiviIntention(intention_id=uuid4(), entity_id=uuid4())
        suivi.echoue("HTTP 400 Client already exists")
        assert suivi.statut == STATUT_ECHEC
        assert "Client already exists" in suivi.detail["motif"]

    def test_le_motif_est_tronque(self) -> None:
        """ANO-CPY-LEAK-07 : les erreurs serveur fuient des traces Python. On
        les tronque avant de les journaliser, jamais on ne les parse."""
        suivi = SuiviIntention(intention_id=uuid4(), entity_id=uuid4())
        suivi.echoue("x" * 2000)
        assert len(suivi.detail["motif"]) == 500

    def test_les_deux_actions_sont_distinctes(self) -> None:
        """Le cycle vit dans `action` : le schema des 6 collections n'a pas
        bouge."""
        assert ACTION_INTENTION != ACTION_RESULTAT
        assert {ACTION_INTENTION, ACTION_RESULTAT}.isdisjoint({STATUT_SUCCES, STATUT_ECHEC})


class TestConfigurationDuRun:
    """D-10 — le 7e champ de `loader_runs`.

    Des que la volumetrie devient parametrable, le `run_id` NE SUFFIT PLUS a
    reproduire une execution. Sans ce champ, ENF-15 est perdue et CR-04
    invérifiable.
    """

    def test_un_run_nu_porte_une_configuration_vide(self) -> None:
        """Cas nominal : sans parametre, le CDC s'applique — l'empreinte vide
        le dit."""
        run = LoaderRun(
            _id=uuid4(),
            sim_start_date=date(2026, 2, 9),
            sim_end_date=date(2026, 8, 8),
        )
        assert run.configuration == {}

    def test_la_configuration_survit_a_la_serialisation(self) -> None:
        """Elle doit se relire telle quelle apres un aller-retour MongoDB."""
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "Faker ne sert pas le Senegal")

        run = LoaderRun(
            _id=uuid4(),
            sim_start_date=date(2026, 2, 9),
            sim_end_date=date(2026, 8, 8),
            configuration=config.empreinte(),
        )
        document = en_document(run)
        relu = LoaderRun.model_validate(document)

        assert relu.configuration["pays"]["SN"]["actif"] is False
        assert relu.configuration["ecarts_au_cdc"]

    def test_la_configuration_n_est_pas_dans_les_checkpoints(self) -> None:
        """Les checkpoints portent la reprise apres interruption : ils changent
        PENDANT l'execution. La configuration est figee au lancement. Les
        melanger rendrait impossible de dire ce qui avait ete DEMANDE."""
        run = LoaderRun(
            _id=uuid4(),
            sim_start_date=date(2026, 2, 9),
            sim_end_date=date(2026, 8, 8),
            configuration=ConfigurationExecution.defaut_cdc().empreinte(),
        )
        assert run.checkpoints == []
        assert "pays" in run.configuration

    def test_l_empreinte_porte_la_repartition_des_clients(self) -> None:
        """Rejouer un run, c'est rejouer run_id ET la repartition."""
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "A-01")
        empreinte = config.empreinte()

        assert empreinte["repartition_clients"]["SN"] == 0
        assert sum(empreinte["repartition_clients"].values()) == config.nb_clients
