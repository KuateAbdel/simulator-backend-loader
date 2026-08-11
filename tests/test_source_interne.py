"""
tests/test_source_interne.py
============================
La source d'identites INTERNE — arbitrage `A-01`, le Senegal.

**Ce que ces tests protegent** : que le Senegal soit servi comme les autres
pays, et que sa provenance reste LISIBLE. Deux echecs symetriques a eviter —
un Senegal absent (`OBJ-01` exige quatre pays), et un Senegal indiscernable
des trois autres (l'ecart au CDC deviendrait invisible).

Le test `test_le_contrat_faker_exclut_toujours_le_senegal` fige la mesure qui
justifie ce module : si Oti ajoute SN un jour, il tombera — et c'est le signal
qu'il faut retirer ce module plutot que le maintenir.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from app.clients.faker_service import PAYS_FAKER, CategorieClient
from app.core.cdc import PAYS_CIBLES
from app.core.invariants import GENRES_EMIS
from app.services.clients_composition import ancrer_sur_kiosque, composer
from app.services.clients_execution import (
    SOLDE_INITIAL_MAX,
    SOLDE_INITIAL_MIN,
    solde_initial,
)
from app.services.generateur import CLES_PROFIL_INTERNE, PATRONYMES_PAR_PAYS, Generateur
from app.services.geographie import charger_referentiel
from app.services.source_interne import (
    PREFIXE_INTERNE,
    SourceInterne,
    est_interne,
    source_pour,
)

REFERENTIEL = charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))
RUN = UUID(int=7)


@pytest.fixture
def source() -> SourceInterne:
    return SourceInterne()


class TestLaRaisonDExister:
    def test_le_contrat_faker_exclut_toujours_le_senegal(self) -> None:
        """LA mesure qui justifie ce module, figee : Faker declare
        `enum: ["BF","CI","CM"]`, verifie en direct le 11/08.

        Si ce test tombe un jour, Oti a ajoute SN — et la bonne reponse est
        alors de SUPPRIMER ce module, pas de le maintenir."""
        assert PAYS_FAKER == frozenset({"BF", "CI", "CM"})
        assert "SN" not in PAYS_FAKER

    def test_la_source_interne_couvre_exactement_le_trou(self) -> None:
        """Ni moins (un pays cible non servi), ni plus (un doublon de Faker)."""
        assert SourceInterne.PAYS_SERVIS == frozenset({"SN"})
        assert SourceInterne.PAYS_SERVIS | PAYS_FAKER == set(PAYS_CIBLES)
        assert not SourceInterne.PAYS_SERVIS & PAYS_FAKER, "aucun pays servi deux fois"

    def test_les_patronymes_senegalais_sont_authentiques(self) -> None:
        """Le referentiel les portait deja — Diallo, Ndiaye, Fall, Sow, Gueye.
        Aucun besoin d'inventer, et surtout aucun droit de le faire."""
        assert PATRONYMES_PAR_PAYS["SN"] == ("Diallo", "Ndiaye", "Fall", "Sow", "Gueye")


class TestLArbitrageDeSource:
    def test_le_senegal_va_a_la_source_interne(self) -> None:
        faker, interne = object(), object()
        assert source_pour("SN", faker, interne) is interne  # type: ignore[arg-type]

    @pytest.mark.parametrize("pays", sorted(PAYS_FAKER))
    def test_les_trois_autres_vont_a_faker(self, pays: str) -> None:
        faker, interne = object(), object()
        assert source_pour(pays, faker, interne) is faker  # type: ignore[arg-type]

    def test_l_arbitrage_est_insensible_a_la_casse(self) -> None:
        faker, interne = object(), object()
        assert source_pour("sn", faker, interne) is interne  # type: ignore[arg-type]


class TestLaProvenanceEstLisible:
    async def test_l_identifiant_porte_la_provenance(self, source: SourceInterne) -> None:
        """Elle voyage avec l'`_id` : rapport, registre, journal — partout, sans
        table de correspondance."""
        client = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, 42)
        assert client is not None
        assert client.client_id == f"{PREFIXE_INTERNE}-SN-IND-42"
        assert est_interne(client.client_id)

    async def test_un_business_est_distingue_dans_l_identifiant(
        self, source: SourceInterne
    ) -> None:
        client = await source.tirer_client("SN", CategorieClient.BUSINESS, 42)
        assert client is not None
        assert client.client_id == f"{PREFIXE_INTERNE}-SN-BIZ-42"

    async def test_un_client_faker_n_est_jamais_pris_pour_interne(self) -> None:
        assert not est_interne("CM-IND-895367")
        assert not est_interne("RC-CM-IND-CMC827162")


class TestCeQueLaSourceNeFabriquePas:
    """Fabriquer un faux `sim_number` ou une fausse `company_name` pour « faire
    comme Faker » serait l'invention arbitraire que le CDC interdit — et cela
    effacerait la trace de la provenance."""

    async def test_aucun_msisdn_faker_n_est_invente(self, source: SourceInterne) -> None:
        client = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, 1)
        assert client is not None and client.msisdn is None

    async def test_aucune_piece_d_identite_n_est_inventee(
        self, source: SourceInterne
    ) -> None:
        """Le generateur la compose — `D-CLI-3` alphanumerique majuscules,
        `D-CLI-2` expiration toujours posee."""
        client = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, 1)
        assert client is not None and client.identite is None

    async def test_aucune_company_faker_n_est_inventee(self, source: SourceInterne) -> None:
        """Le secteur vient du moteur de quotas (`EF-24`), pas d'une fausse
        trace Faker."""
        client = await source.tirer_client("SN", CategorieClient.BUSINESS, 1)
        assert client is not None and client.company is None

    async def test_un_pays_non_servi_rend_None_sans_lever(
        self, source: SourceInterne
    ) -> None:
        """Un pays non servi n'est pas une panne : la boucle doit continuer sur
        les autres."""
        for pays in (*sorted(PAYS_FAKER), "ZZ"):
            assert await source.tirer_client(pays, CategorieClient.INDIVIDUAL, 1) is None


class TestEF22LeRatioDesGenres:
    async def test_deux_femmes_pour_un_homme_sur_un_echantillon_reel(
        self, source: SourceInterne
    ) -> None:
        """Produit directement, puisque nous controlons la source. Le moteur de
        quotas verifie quand meme — il ecarte simplement beaucoup moins."""
        genres = [
            c.genre
            for seed in range(1, 601)
            if (c := await source.tirer_client("SN", CategorieClient.INDIVIDUAL, seed))
        ]
        assert genres.count("WOMAN") == 400
        assert genres.count("MAN") == 200

    async def test_le_genre_emis_est_du_vocabulaire_de_faker(
        self, source: SourceInterne
    ) -> None:
        """C'est le composeur qui traduit vers `MALE`/`FEMALE` — la source parle
        la meme langue que Faker pour emprunter le meme chemin."""
        for seed in range(1, 20):
            client = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, seed)
            assert client is not None and client.genre in ("WOMAN", "MAN")
            assert client.genre not in GENRES_EMIS, "la traduction appartient au composeur"


class TestLeProfilSocioEconomique:
    async def test_les_onze_cles_sont_toutes_posees(self, source: SourceInterne) -> None:
        """Une cle absente serait un solde calcule sur du vide (`A-09`)."""
        client = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, 5)
        assert client is not None
        assert set(client.quick_win) == set(CLES_PROFIL_INTERNE)
        assert all(v in (0, 1) for v in client.quick_win.values())

    async def test_la_dotation_senegalaise_s_etale_comme_celle_des_voisins(
        self, source: SourceInterne
    ) -> None:
        """Un profil constant donnerait 500 Senegalais au solde identique —
        visible au premier graphique."""
        soldes = {
            solde_initial(c)
            for seed in range(1, 300)
            if (c := await source.tirer_client("SN", CategorieClient.INDIVIDUAL, seed))
        }
        assert len(soldes) == 299, "un solde distinct par client, pas dix paliers"
        assert all(SOLDE_INITIAL_MIN <= s <= SOLDE_INITIAL_MAX for s in soldes)


class TestENF15LaReproductibilite:
    async def test_le_meme_seed_rend_le_meme_client(self, source: SourceInterne) -> None:
        """« Deux executions avec les memes parametres et le meme run_id DOIVENT
        produire strictement le meme ecosysteme. » Aucun tirage aleatoire ici :
        tout derive du seed par calcul."""
        a = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, 12345)
        b = await SourceInterne().tirer_client("SN", CategorieClient.INDIVIDUAL, 12345)
        assert a == b, "deux instances distinctes, un resultat identique"

    async def test_le_seed_survit_pour_etre_rejoue(self, source: SourceInterne) -> None:
        client = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, 999)
        assert client is not None and client.seed == 999


class TestLIntegrationAvecLeComposeur:
    """La source emprunte le MEME chemin que Faker — c'est tout l'objet du
    Protocol partage. Un client senegalais doit se composer sans aucun cas
    particulier."""

    async def test_un_senegalais_se_compose_de_bout_en_bout(
        self, source: SourceInterne
    ) -> None:
        from app.models.domain import OrgHierarchyNode
        from app.models.enums import NiveauOrganisation

        ville = REFERENTIEL.villes_porteuses_de_quartiers("SN")[0]
        quartier = REFERENTIEL.quartiers_de_ville(ville.city_id)[0]
        kiosque = OrgHierarchyNode(
            id=UUID(int=1),
            run_id=RUN,
            niveau=NiveauOrganisation.KIOSQUE,
            parent_id=UUID(int=2),
            company_id=UUID(int=3),
            name=f"DEMO_Kiosque {quartier.name}",
            country_code="SN",
            district_id=quartier.district_id,
            depositary_id=UUID(int=4),
        )
        client = await source.tirer_client("SN", CategorieClient.INDIVIDUAL, 3)
        assert client is not None

        import random

        compose = composer(
            client,
            ancrer_sur_kiosque(kiosque, REFERENTIEL),
            Generateur(RUN, reference=date(2026, 8, 11)),
            REFERENTIEL,
            random.Random(1),  # noqa: S311 — reproductibilite, pas de crypto
            jeune=True,
        )

        # La devise suit le pays : zone UEMOA.
        assert compose.devise == "XOF"
        # Le MSISDN est compose depuis le plan de numerotation reel, et valide.
        assert REFERENTIEL.operateur_du_msisdn(compose.msisdn, "SN") is not None
        assert compose.msisdn_faker is None, "aucun numero Faker a tracer"
        # La geographie decoule du Kiosque.
        assert compose.ancrage.pays == "SN"
        assert compose.ancrage.quartier == quartier.name
        # Le genre est traduit vers le vocabulaire de la plateforme.
        assert compose.identite.gender in GENRES_EMIS
        # `D-CLI-8` — l'identite porte le meme numero que le client.
        assert compose.identite.phone == compose.msisdn
        # Le patronyme est senegalais, pas emprunte a un voisin.
        assert compose.identite.last_name in PATRONYMES_PAR_PAYS["SN"]
        # La langue : le Senegal est francophone.
        assert compose.langue.value == "fr"
