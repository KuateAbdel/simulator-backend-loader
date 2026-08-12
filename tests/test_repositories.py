"""Tests hors ligne du socle de persistance.

Aucun MongoDB requis : on verifie ici ce qui doit etre juste AVANT toute base —
le hachage, la serialisation, et la machine d'etat. Les tests d'integration des
repositories exigeront une instance vivante, ils viendront separement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from app.core.configuration import ConfigurationExecution
from app.core.security import hacher, verifier
from app.models.domain import FakerConsumptionLedger, LoaderRun, OrgHierarchyNode
from app.models.enums import (
    EtatConsommationFaker,
    FakerConsumptionType,
    NiveauOrganisation,
    RunMode,
    RunStatus,
)
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
            consumed_for=FakerConsumptionType.COLLECT_CLIENT,
            country_code="CM",
            run_id=uuid4(),
            reserved_at=datetime.now(UTC),
        )
        document = en_document(entree)
        assert "_id" in document and "id" not in document
        assert document["_id"] == "RC-CM-IND-CMC1"

    def test_une_reservation_neuve_ne_porte_ni_entite_ni_date_de_consommation(self) -> None:
        """Le premier temps du registre (correctif du 11/08) : la reservation est
        ecrite AVANT l'appel reseau, donc avant qu'aucune entite n'existe. C'est
        `resulting_entity_id` a `None` qui distingue un client revendique d'un
        client reellement employe."""
        entree = FakerConsumptionLedger(
            id="RC-CM-IND-CMC2",
            consumed_for=FakerConsumptionType.COLLECT_CLIENT,
            country_code="CM",
            run_id=uuid4(),
            reserved_at=datetime.now(UTC),
        )
        assert entree.state is EtatConsommationFaker.RESERVE
        assert entree.resulting_entity_id is None
        assert entree.consumed_at is None

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


class TestNiveauAgent:
    """D-11 — le sixieme niveau du CDC, que nous ne modelisions pas.

    Le CDC §6 decrit SIX niveaux ; org_hierarchy s'arretait au cinquieme.
    L'Agent existe cote serveur — c'est un User — mais SON RATTACHEMENT AU
    KIOSQUE n'existe nulle part : `User` porte `company_id` et `identity`,
    jamais de reference vers un Depositaire.
    """

    def test_l_enum_porte_les_cinq_niveaux_dans_l_ordre_d_emboitement(self) -> None:
        """L'ORDRE compte : `verifier_cr02()` verifie que chaque noeud est
        rattache au niveau immediatement superieur. CLIENT est cinquieme — ce
        n'est pas un niveau du CDC §6.2, qui s'arrete a l'Agent, mais le
        rattachement Client -> Kiosque n'existe nulle part cote serveur
        (`EF-26`), exactement l'argument qui a fait entrer l'AGENT."""
        assert [n.value for n in NiveauOrganisation] == [
            "BRANCHE",
            "AGENCE",
            "KIOSQUE",
            "AGENT",
            "CLIENT",
        ]

    def test_un_noeud_agent_porte_son_user_et_son_kiosque(self) -> None:
        kiosque = uuid4()
        agent = OrgHierarchyNode(
            _id=uuid4(),
            run_id=uuid4(),
            niveau=NiveauOrganisation.AGENT,
            parent_id=kiosque,
            company_id=uuid4(),
            name="DEMO_CM_Agent_001",
            country_code="CM",
            user_id=uuid4(),
        )
        assert agent.parent_id == kiosque
        assert agent.user_id is not None
        assert agent.depositary_id is None, "depositary_id reste au niveau KIOSQUE"

    def test_les_niveaux_superieurs_n_ont_pas_de_user_id(self) -> None:
        """`user_id` est au niveau AGENT uniquement, comme `depositary_id` est
        au niveau KIOSQUE uniquement."""
        kiosque = OrgHierarchyNode(
            _id=uuid4(),
            run_id=uuid4(),
            niveau=NiveauOrganisation.KIOSQUE,
            parent_id=uuid4(),
            company_id=uuid4(),
            name="Kiosque Bastos",
            country_code="CM",
            district_id="CM-DT-001",
            depositary_id=uuid4(),
        )
        assert kiosque.user_id is None
        assert kiosque.depositary_id is not None

    def test_le_noeud_agent_survit_a_la_serialisation(self) -> None:
        agent = OrgHierarchyNode(
            _id=uuid4(),
            run_id=uuid4(),
            niveau=NiveauOrganisation.AGENT,
            parent_id=uuid4(),
            company_id=uuid4(),
            name="DEMO_SN_Agent_007",
            country_code="SN",
            user_id=uuid4(),
        )
        relu = OrgHierarchyNode.model_validate(en_document(agent))
        assert relu.niveau is NiveauOrganisation.AGENT
        assert relu.user_id == agent.user_id


# ---------------------------------------------------------------------------
# EF-26 — le rattachement Client -> Kiosque, contre le vrai MongoDB
# ---------------------------------------------------------------------------


class TestRattachementClientEF26:
    """`EF-26` — *« rattacher chaque client a un Kiosque existant du pays cible »*.

    Mesure du 09/08 : la fiche Client rendue par client-service porte quinze cles
    et **aucune** ne permet ce rattachement — ni `depositary_id`, ni
    `kiosque_id`, ni `company_id`. L'exigence est donc **inapplicable a la
    creation** et se satisfait en deux temps ; ce noeud est le premier, et la
    seule trace jusqu'a la premiere collecte.

    Ces tests tournent contre MongoDB parce que **la garantie qu'ils verifient
    est un index** : `uniq_client_par_run`. Un double en memoire ne prouverait
    que la fidelite du double.
    """

    @pytest.fixture
    async def arbre(self):  # type: ignore[misc,no-untyped-def]
        from app.core.database import COLLECTION_ORG_HIERARCHY, close, connect, ensure_indexes
        from app.core.database import get_collection as collection
        from app.repositories.org_hierarchy import OrgHierarchyRepository

        connect()
        await ensure_indexes()
        depot = OrgHierarchyRepository()
        await collection(COLLECTION_ORG_HIERARCHY).delete_many({"name": {"$regex": "TEST26"}})
        yield depot
        await collection(COLLECTION_ORG_HIERARCHY).delete_many({"name": {"$regex": "TEST26"}})
        close()

    async def _kiosque(self, arbre, run: UUID, pays: str = "CM", suffixe: str = ""):  # type: ignore[no-untyped-def]
        """La chaine complete : `EF-18` interdit tout raccourci."""
        imf = uuid4()
        branche = await arbre.ajouter_branche(
            run, imf, f"TEST26 Branche{suffixe}", pays, f"{pays}-RG-{suffixe or '1'}"
        )
        agence = await arbre.ajouter_agence(
            run, branche.id, imf, f"TEST26 Agence{suffixe}", pays, f"{pays}-CT-{suffixe or '1'}"
        )
        return imf, await arbre.ajouter_kiosque(
            run, agence.id, imf, f"TEST26 Kiosque{suffixe}", pays,
            f"{pays}-DT-{suffixe or '1'}", uuid4(),
        )

    async def test_le_rattachement_porte_son_client_et_son_kiosque(self, arbre) -> None:  # type: ignore[no-untyped-def]
        run = uuid4()
        imf, kiosque = await self._kiosque(arbre, run)
        client = uuid4()
        noeud = await arbre.ajouter_client(
            run_id=run, kiosque_id=kiosque.id, company_id=imf,
            country_code="CM", msisdn="237673689015", client_id=client,
        )
        assert noeud.niveau is NiveauOrganisation.CLIENT
        assert noeud.parent_id == kiosque.id
        assert noeud.client_id == client
        assert noeud.name == "DEMO_Client 237673689015", (
            "un artefact du Loader porte le prefixe (CR-07/EF-63) ; une personne, non"
        )
        assert noeud.district_id is None, (
            "le district n'est PAS duplique : il est derive du Kiosque, donc "
            "l'incoherence est impossible plutot que detectable"
        )

    async def test_EF_18_un_client_sans_kiosque_est_REFUSE(self, arbre) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(ValueError, match="introuvable"):
            await arbre.ajouter_client(
                run_id=uuid4(), kiosque_id=uuid4(), company_id=uuid4(),
                country_code="CM", msisdn="237673689015", client_id=uuid4(),
            )

    async def test_MILLE_clients_tiennent_dans_le_MEME_quartier(self, arbre) -> None:  # type: ignore[no-untyped-def]
        """L'index `uniq_district_par_run` est UNIQUE. Si le noeud CLIENT portait
        un `district_id`, le SECOND client d'un quartier serait rejete — et la
        campagne place 2000 clients sur une soixantaine de quartiers."""
        run = uuid4()
        imf, kiosque = await self._kiosque(arbre, run)
        for rang in range(50):
            await arbre.ajouter_client(
                run_id=run, kiosque_id=kiosque.id, company_id=imf,
                country_code="CM", msisdn=f"2376736{rang:05d}", client_id=uuid4(),
            )
        assert await arbre.compter_clients(run) == 50
        assert len(await arbre.clients_du_kiosque(kiosque.id)) == 50

    async def test_rejouer_le_MEME_client_ne_cree_pas_de_second_noeud(self, arbre) -> None:  # type: ignore[no-untyped-def]
        """`CR-03` — la reprise repasse par ce chemin. Sans l'index
        `uniq_client_par_run`, « quels clients dans ce Kiosque ? » repondrait
        4000 pour 2000 clients."""
        run = uuid4()
        imf, kiosque = await self._kiosque(arbre, run)
        client = uuid4()
        premier = await arbre.ajouter_client(
            run_id=run, kiosque_id=kiosque.id, company_id=imf,
            country_code="CM", msisdn="237673689015", client_id=client,
        )
        second = await arbre.ajouter_client(
            run_id=run, kiosque_id=kiosque.id, company_id=imf,
            country_code="CM", msisdn="237673689015", client_id=client,
        )
        assert second.id == premier.id, "le noeud existant est rendu, pas duplique"
        assert await arbre.compter_clients(run) == 1

    async def test_CR_02_accepte_un_client_du_pays_de_son_kiosque(self, arbre) -> None:  # type: ignore[no-untyped-def]
        run = uuid4()
        imf, kiosque = await self._kiosque(arbre, run, "CI")
        await arbre.ajouter_client(
            run_id=run, kiosque_id=kiosque.id, company_id=imf,
            country_code="CI", msisdn="22507123456", client_id=uuid4(),
        )
        assert await arbre.verifier_cr02(run) == []

    async def test_CR_02_DENONCE_un_client_rattache_hors_de_son_pays(self, arbre) -> None:  # type: ignore[no-untyped-def]
        """Le controle n'a de valeur que parce que le pays vient du CLIENT.
        Le prendre du Kiosque le rendrait tautologique — il comparerait une
        valeur a elle-meme et ne pourrait JAMAIS echouer."""
        run = uuid4()
        imf, kiosque = await self._kiosque(arbre, run, "CM")
        await arbre.ajouter_client(
            run_id=run, kiosque_id=kiosque.id, company_id=imf,
            country_code="SN", msisdn="221771234567", client_id=uuid4(),
        )
        anomalies = await arbre.verifier_cr02(run)
        assert any("SN" in a and "EF-26" in a for a in anomalies), anomalies

    async def test_CR_02_DENONCE_un_client_rattache_a_une_agence(self, arbre) -> None:  # type: ignore[no-untyped-def]
        """`EF-18` est controle a l'ecriture, mais la recette doit pouvoir le
        constater sur des donnees deja en base — un noeud pose hors de ce chemin
        ne passerait pas en silence."""
        from app.core.database import COLLECTION_ORG_HIERARCHY
        from app.core.database import get_collection as collection
        from app.repositories.base import en_document

        run = uuid4()
        imf = uuid4()
        branche = await arbre.ajouter_branche(run, imf, "TEST26 Br", "CM", "CM-RG-9")
        agence = await arbre.ajouter_agence(run, branche.id, imf, "TEST26 Ag", "CM", "CM-CT-9")
        await collection(COLLECTION_ORG_HIERARCHY).insert_one(
            en_document(
                OrgHierarchyNode(
                    _id=uuid4(), run_id=run, niveau=NiveauOrganisation.CLIENT,
                    parent_id=agence.id, company_id=imf,
                    name="TEST26 DEMO_Client 237600000001", country_code="CM",
                    client_id=uuid4(),
                )
            )
        )
        anomalies = await arbre.verifier_cr02(run)
        assert any("rattache a un AGENCE" in a for a in anomalies), anomalies
