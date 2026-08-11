"""
tests/test_faker_ledger.py
==========================
Le registre de consommation Faker — `D-FAKER-1`.

**Ce que ces tests protegent** : qu'une entite IRREVERSIBLE ne puisse jamais
naitre d'un client Faker deja employe ailleurs. Les trois services sans `DELETE`
rendent cette erreur definitive, donc elle doit etre impossible et non
rattrapable.

Le test central est `test_deux_workers_concurrents...` : il rejoue la fenetre que
la v1 laissait ouverte.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from app.core.database import close, connect, ensure_indexes, get_collection
from app.models.enums import EtatConsommationFaker, FakerConsumptionType
from app.repositories.faker_ledger import ConsommationIncoherente, FakerLedgerRepository

USAGE = FakerConsumptionType.COLLECT_CLIENT


@pytest.fixture
async def depot() -> FakerLedgerRepository:  # type: ignore[misc]
    connect()
    await ensure_indexes()
    depot = FakerLedgerRepository()
    await get_collection(depot.collection_name).delete_many({"_id": {"$regex": "^TEST-"}})
    yield depot
    await get_collection(depot.collection_name).delete_many({"_id": {"$regex": "^TEST-"}})
    close()


def _id(suffixe: str) -> str:
    return f"TEST-CM-IND-{suffixe}"


class TestLaReservationTrancheSeule:
    async def test_une_premiere_reservation_passe(self, depot: FakerLedgerRepository) -> None:
        assert await depot.reserver(
            _id("1"), consumed_for=USAGE, country_code="CM", run_id=uuid4(), seed=7
        )

    async def test_une_seconde_reservation_du_meme_client_est_refusee(
        self, depot: FakerLedgerRepository
    ) -> None:
        """Le `False` n'est pas une erreur : c'est le signal du CDC §185 —
        changer le `seed` et rappeler."""
        cible = _id("2")
        run = uuid4()
        assert await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=run)
        assert not await depot.reserver(
            cible, consumed_for=USAGE, country_code="CM", run_id=run
        )

    async def test_un_autre_usage_ne_peut_pas_reprendre_le_meme_client(
        self, depot: FakerLedgerRepository
    ) -> None:
        """Le coeur de `D-FAKER-1` : « consomme pour UN usage, plus jamais pour
        un autre ». Un Depositaire ne recycle pas le client d'un Lender."""
        cible = _id("3")
        assert await depot.reserver(
            cible, consumed_for=FakerConsumptionType.LENDER_LOCAL, country_code="CM", run_id=uuid4()
        )
        assert not await depot.reserver(
            cible, consumed_for=FakerConsumptionType.DEPOSITARY, country_code="CM", run_id=uuid4()
        )

    async def test_un_autre_run_ne_peut_pas_reprendre_un_client_consomme(
        self, depot: FakerLedgerRepository
    ) -> None:
        """`D-FAKER-1` est GLOBAL, pas par run. Un client consomme hier reste
        consomme aujourd'hui — sinon deux runs produiraient deux entites
        irreversibles a partir de la meme identite."""
        cible = _id("4")
        assert await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())
        await depot.confirmer(cible, uuid4())
        assert not await depot.reserver(
            cible, consumed_for=USAGE, country_code="CM", run_id=uuid4()
        )

    async def test_deux_workers_concurrents_ne_peuvent_pas_reserver_le_meme_client(
        self, depot: FakerLedgerRepository
    ) -> None:
        """**LE TEST QUI PORTE LA CORRECTION DU 11/08.**

        20 tentatives simultanees sur le meme `client_id`. Exactement UNE doit
        passer. C'est ce que la v1 ne garantissait pas : elle lisait
        (`est_consomme`) puis ecrivait apres un appel reseau irreversible.
        """
        cible = _id("5")
        run = uuid4()
        resultats = await asyncio.gather(
            *(
                depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=run, seed=i)
                for i in range(20)
            )
        )
        assert sum(resultats) == 1, f"{sum(resultats)} reservations ont passe au lieu d'une"


class TestLaConfirmation:
    async def test_confirmer_scelle_l_entite_et_l_horodate(
        self, depot: FakerLedgerRepository
    ) -> None:
        cible, entite = _id("6"), uuid4()
        await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())
        await depot.confirmer(cible, entite)

        entree = await depot.obtenir(cible)
        assert entree is not None
        assert entree.state is EtatConsommationFaker.CONSOMME
        assert entree.resulting_entity_id == entite
        assert entree.consumed_at is not None, "la date de consommation est la preuve"

    async def test_confirmer_sans_reserver_CRIE(self, depot: FakerLedgerRepository) -> None:
        """Ce cas signifie qu'une entite a ete creee AVANT d'entrer au registre —
        exactement la fenetre que `reserver()` ferme. Le taire laisserait une
        entite irreversible sans trace de son origine."""
        with pytest.raises(ConsommationIncoherente, match="sans avoir ete reserve"):
            await depot.confirmer(_id("7"), uuid4())

    async def test_une_double_confirmation_CRIE(self, depot: FakerLedgerRepository) -> None:
        """Deux entites nees du meme client Faker, toutes deux irreversibles."""
        cible = _id("8")
        await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())
        await depot.confirmer(cible, uuid4())
        with pytest.raises(ConsommationIncoherente, match="D-FAKER-1 est viole"):
            await depot.confirmer(cible, uuid4())


class TestLaLiberationPourQuota:
    """« Un client ecarte pour raison de quota n'est PAS consomme. » Sans cette
    regle, 2000 clients demandes epuiseraient le vivier sans rien creer."""

    async def test_un_client_ecarte_pour_quota_est_rendu_au_vivier(
        self, depot: FakerLedgerRepository
    ) -> None:
        cible = _id("9")
        await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())
        assert await depot.liberer(cible)
        assert await depot.obtenir(cible) is None
        # Et il redevient tirable — c'est tout l'objet de la liberation.
        assert await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())

    async def test_une_consommation_CONFIRMEE_ne_se_libere_JAMAIS(
        self, depot: FakerLedgerRepository
    ) -> None:
        """L'entite existe sur le serveur et aucun `DELETE` ne la reprend :
        liberer son client Faker autoriserait une seconde entite jumelle."""
        cible = _id("10")
        await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())
        await depot.confirmer(cible, uuid4())

        assert not await depot.liberer(cible)
        entree = await depot.obtenir(cible)
        assert entree is not None and entree.state is EtatConsommationFaker.CONSOMME

    async def test_liberer_un_client_inconnu_rend_False_sans_lever(
        self, depot: FakerLedgerRepository
    ) -> None:
        assert not await depot.liberer(_id("inconnu"))


class TestLaReconciliation:
    async def test_une_reservation_qui_survit_est_orpheline(
        self, depot: FakerLedgerRepository
    ) -> None:
        """Meme role qu'`intentions_orphelines()` : elle dit qu'un client a ete
        revendique sans rien produire."""
        run = uuid4()
        await depot.reserver(_id("11"), consumed_for=USAGE, country_code="CM", run_id=run)
        await depot.reserver(_id("12"), consumed_for=USAGE, country_code="CI", run_id=run)
        await depot.confirmer(_id("12"), uuid4())

        orphelines = await depot.reservations_orphelines(run)
        assert [o.id for o in orphelines] == [_id("11")]

    async def test_les_orphelines_d_un_autre_run_ne_sont_pas_les_notres(
        self, depot: FakerLedgerRepository
    ) -> None:
        """`run_id` etait absent de la v1 : la reconciliation confondait alors les
        orphelines d'un run mort avec les siennes."""
        notre, autre = uuid4(), uuid4()
        await depot.reserver(_id("13"), consumed_for=USAGE, country_code="CM", run_id=autre)
        assert await depot.reservations_orphelines(notre) == []
        assert len(await depot.reservations_orphelines(autre)) == 1

    async def test_reclamer_exige_un_age_et_epargne_les_reservations_fraiches(
        self, depot: FakerLedgerRepository
    ) -> None:
        """Sans borne d'age, cette methode viderait les reservations d'un run
        CONCURRENT en cours d'execution."""
        await depot.reserver(_id("14"), consumed_for=USAGE, country_code="CM", run_id=uuid4())
        assert await depot.reclamer_orphelines(plus_vieilles_que=timedelta(hours=1)) == 0
        assert await depot.obtenir(_id("14")) is not None

    async def test_reclamer_libere_les_reservations_assez_vieilles(
        self, depot: FakerLedgerRepository
    ) -> None:
        await depot.reserver(_id("15"), consumed_for=USAGE, country_code="CM", run_id=uuid4())
        libere = await depot.reclamer_orphelines(plus_vieilles_que=timedelta(seconds=-1))
        assert libere >= 1
        assert await depot.obtenir(_id("15")) is None

    async def test_reclamer_ne_touche_pas_aux_consommations_scellees(
        self, depot: FakerLedgerRepository
    ) -> None:
        cible = _id("16")
        await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())
        await depot.confirmer(cible, uuid4())
        await depot.reclamer_orphelines(plus_vieilles_que=timedelta(seconds=-1))
        assert await depot.obtenir(cible) is not None


class TestLesComptesDuRapport:
    async def test_une_reservation_en_vol_n_est_pas_comptee_comme_consommee(
        self, depot: FakerLedgerRepository
    ) -> None:
        """L'inclure gonflerait le rapport de clients qui n'existent peut-etre
        pas — et c'est le rapport qui prouve la generation devant un bailleur."""
        run = uuid4()
        avant = await depot.compter_par_usage(USAGE)
        await depot.reserver(_id("17"), consumed_for=USAGE, country_code="CM", run_id=run)
        assert await depot.compter_par_usage(USAGE) == avant

        await depot.confirmer(_id("17"), uuid4())
        assert await depot.compter_par_usage(USAGE) == avant + 1

    async def test_la_repartition_par_pays_respecte_les_pays_reels(
        self, depot: FakerLedgerRepository
    ) -> None:
        """`OBJ-01` exige les 4 pays. La repartition doit les montrer tels
        qu'ils sont — y compris `SN` absent tant qu'il vient du generateur
        interne (`A-01`). C'est une information, pas une anomalie a masquer."""
        run = uuid4()
        for suffixe, pays in (("18", "CM"), ("19", "CI"), ("20", "CI"), ("21", "BF")):
            await depot.reserver(
                _id(suffixe), consumed_for=USAGE, country_code=pays, run_id=run
            )
            await depot.confirmer(_id(suffixe), uuid4())

        assert await depot.compter_par_pays(run) == {"CM": 1, "CI": 2, "BF": 1}

    async def test_le_code_pays_est_normalise_en_majuscules(
        self, depot: FakerLedgerRepository
    ) -> None:
        run = uuid4()
        await depot.reserver(_id("22"), consumed_for=USAGE, country_code="cm", run_id=run)
        await depot.confirmer(_id("22"), uuid4())
        assert await depot.compter_par_pays(run) == {"CM": 1}


class TestCeQueLaV1PromettaitATort:
    async def test_est_consomme_reste_disponible_mais_ne_decide_de_rien(
        self, depot: FakerLedgerRepository
    ) -> None:
        """La methode existe pour les journaux. Son docstring interdit de s'en
        servir pour decider d'un tirage : entre elle et l'ecriture, un autre
        worker passe. Ce test verifie qu'elle voit AUSSI les reservations en
        vol — sinon elle donnerait un faux « libre » sur un client deja pris."""
        cible = _id("23")
        assert not await depot.est_consomme(cible)
        await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=uuid4())
        assert await depot.est_consomme(cible), "une reservation en vol compte comme prise"

    async def test_le_seed_survit_a_la_reservation(self, depot: FakerLedgerRepository) -> None:
        """`ENF-15` : rejouer un run, c'est rejouer ses tirages. Sans le `seed`,
        la reproductibilite n'est pas verifiable."""
        cible = _id("24")
        await depot.reserver(
            cible, consumed_for=USAGE, country_code="CM", run_id=uuid4(), seed=4242
        )
        entree = await depot.obtenir(cible)
        assert entree is not None and entree.seed == 4242

    async def test_le_run_qui_a_revendique_est_conserve(
        self, depot: FakerLedgerRepository
    ) -> None:
        run: UUID = uuid4()
        cible = _id("25")
        await depot.reserver(cible, consumed_for=USAGE, country_code="CM", run_id=run)
        entree = await depot.obtenir(cible)
        assert entree is not None and entree.run_id == run


class TestLEtatQuiPermetLaReprise:
    """`CR-03` — `reserver()` rend `False` pour trois raisons distinctes.

    Les confondre coutait l'idempotence : un refus etait traite comme une
    collision de cache (CDC §185, « changer le seed »), alors qu'il pouvait dire
    « une entite existe deja ». Le second cas exige l'inverse exact — reconnaitre
    l'entite au lieu d'en tirer une autre.
    """

    async def test_un_client_inconnu_n_a_pas_d_etat(
        self, depot: FakerLedgerRepository
    ) -> None:
        assert await depot.etat("TEST-jamais-vu") is None

    async def test_une_reservation_se_lit_RESERVE_avec_son_run(
        self, depot: FakerLedgerRepository
    ) -> None:
        run = uuid4()
        await depot.reserver("TEST-etat-1", consumed_for=USAGE, country_code="CM", run_id=run)
        entree = await depot.etat("TEST-etat-1")
        assert entree is not None
        assert entree.state is EtatConsommationFaker.RESERVE
        assert entree.run_id == run

    async def test_une_consommation_scellee_se_lit_CONSOMME_avec_son_entite(
        self, depot: FakerLedgerRepository
    ) -> None:
        """C'est CE cas qui autorise la reprise : l'entite existe, et le registre
        sait laquelle. Un second run doit la compter, pas la recreer."""
        run, entite = uuid4(), uuid4()
        await depot.reserver("TEST-etat-2", consumed_for=USAGE, country_code="CI", run_id=run)
        await depot.confirmer("TEST-etat-2", entite)
        entree = await depot.etat("TEST-etat-2")
        assert entree is not None
        assert entree.state is EtatConsommationFaker.CONSOMME
        assert entree.resulting_entity_id == entite
        assert entree.run_id == run, (
            "le run d'origine doit rester lisible : c'est lui qui distingue une "
            "reprise d'une collision interne au run courant"
        )

    async def test_le_registre_est_GLOBAL_et_non_indexe_par_run(
        self, depot: FakerLedgerRepository
    ) -> None:
        """La propriete sur laquelle repose toute la reprise. Si le registre
        etait indexe par run, un second run ne verrait rien du premier."""
        premier, second = uuid4(), uuid4()
        await depot.reserver("TEST-etat-3", consumed_for=USAGE, country_code="BF", run_id=premier)
        await depot.confirmer("TEST-etat-3", uuid4())

        assert not await depot.reserver(
            "TEST-etat-3", consumed_for=USAGE, country_code="BF", run_id=second
        )
        vu_du_second = await depot.etat("TEST-etat-3")
        assert vu_du_second is not None
        assert vu_du_second.run_id == premier != second
