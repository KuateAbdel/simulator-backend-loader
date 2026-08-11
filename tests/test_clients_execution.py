"""
tests/test_clients_execution.py
===============================
L'executeur CLIENTS — `UC-12`, `UC-13`, `EF-22`/`EF-23`/`EF-24`, `D-FAKER-1`.

**Ce que ces tests protegent avant tout** : les deux moities du write-ahead.
`reserver()` avant le reseau, `confirmer()` apres — c'est en ecrivant ce fichier
que la seconde moitie s'est revelee absente : en REEL, 1500 clients seraient
tous restes RESERVE, la reconciliation aurait crie 1500 orphelines sur un run
reussi, et le rapport aurait affiche zero client consomme.

Aucun test ne touche le reseau ni MongoDB : Faker, le registre et client-service
sont des faux en memoire. Le referentiel et le generateur sont les vrais.
"""



from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_OID, UUID, uuid4, uuid5

import pytest

from app.clients.account_service import AccountServiceClient
from app.clients.base import ErreurService
from app.clients.contracts import ClientCategory, ProductType
from app.clients.faker_service import CategorieClient, ClientFaker
from app.core.configuration import ConfigurationExecution
from app.models.enums import RunMode, RunStatus
from app.repositories.faker_ledger import ConsommationIncoherente
from app.services.clients_execution import (
    CLES_QUICK_WIN_BINAIRES,
    SOLDE_INITIAL_MAX,
    SOLDE_INITIAL_MIN,
    ExecuteurClients,
    QuotaPays,
    RapportClients,
    solde_initial,
)
from app.services.depositaires_execution import ProduitSouscriptible
from app.services.generateur import Generateur
from app.services.geographie import charger_referentiel
from app.services.source_interne import est_interne

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
REFERENTIEL = charger_referentiel(CLASSEUR)
#: Fige : les seeds derivent du run_id, donc tout le deroule est deterministe.
RUN = UUID(int=42)

PRENOMS = ("Aya", "Moussa", "Ines", "Salif", "Awa", "Koffi")
NOMS = ("Kouassi", "Ouattara", "Tamadou", "Sidibe", "Kabore", "Ngwa")


def _tirage(
    pays: str = "CM",
    *,
    genre: str = "WOMAN",
    business: bool = False,
    seed: int = 1,
    quick_win: dict[str, Any] | None = None,
) -> ClientFaker:
    return ClientFaker(
        client_id=f"{pays}-{'BIZ' if business else 'IND'}-{seed}",
        pays=pays,
        devise="XAF",
        categorie=CategorieClient.BUSINESS if business else CategorieClient.INDIVIDUAL,
        msisdn=f"+23738{seed:06d}",
        prenom=PRENOMS[seed % len(PRENOMS)],
        nom=NOMS[seed % len(NOMS)],
        nom_complet="",
        genre=genre,
        identite=None,
        company=None,
        quick_win=quick_win if quick_win is not None else {"IS_RGS_1": 1},
        seed=seed,
    )


class FauxFaker:
    """Famille A simulee : deterministe par seed, 2 femmes pour 1 homme."""

    def __init__(self) -> None:
        self.appels = 0

    async def tirer_client(self, pays: str, categorie: str, seed: int) -> ClientFaker:
        self.appels += 1
        return _tirage(
            pays,
            genre="WOMAN" if seed % 3 else "MAN",
            business=categorie == CategorieClient.BUSINESS,
            seed=seed,
        )


class FauxLedger:
    """Le registre D-FAKER-1, en memoire, avec les memes regles que le vrai."""

    def __init__(self) -> None:
        self.reserves: set[str] = set()
        self.confirmes: dict[str, UUID] = {}
        self.liberations = 0

    async def reserver(self, client_id: str, **_: Any) -> bool:
        if client_id in self.reserves or client_id in self.confirmes:
            return False
        self.reserves.add(client_id)
        return True

    async def liberer(self, client_id: str) -> bool:
        if client_id in self.reserves:
            self.reserves.discard(client_id)
            self.liberations += 1
            return True
        return False

    async def confirmer(self, client_id: str, resulting_entity_id: UUID) -> None:
        if client_id not in self.reserves:
            raise ConsommationIncoherente(f"{client_id} confirme sans avoir ete reserve")
        self.reserves.discard(client_id)
        self.confirmes[client_id] = resulting_entity_id


class FauxArbre:
    """org_hierarchy simule. Vide par defaut -> ancres planifiees en DRY_RUN."""

    def __init__(self, noeuds: list[Any] | None = None) -> None:
        self.noeuds = noeuds or []

    async def par_niveau(self, run_id: UUID, niveau: Any) -> list[Any]:
        return list(self.noeuds)


class ServiceInterdit:
    """client-service qui refuse d'etre appele — la preuve du DRY_RUN."""

    async def onboarder(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("DRY_RUN ne doit JAMAIS appeler client-service")


class FauxClientService:
    """client-service simule ; `echouer_1_sur` fait echouer un appel sur N."""

    def __init__(self, echouer_1_sur: int = 0, *, sans_account_id: bool = False) -> None:
        self.onboardes: list[dict[str, Any]] = []
        self.fiches: list[dict[str, Any]] = []
        self._echouer = echouer_1_sur
        self._sans_account = sans_account_id
        self._n = 0

    async def onboarder(self, **kwargs: Any) -> dict[str, Any]:
        self._n += 1
        if self._echouer and self._n % self._echouer == 0:
            raise ErreurService("client-service", "POST", "/onboard", 500, "panne simulee", "-")
        self.onboardes.append(kwargs)
        # La VRAIE cascade rend les trois : Client, Identity et le compte
        # CHECKING (`D-CLI-1`). Un double qui omet `account_id` ferait croire a
        # un defaut de dotation alors que c'est le double qui est infidele.
        fiche: dict[str, Any] = {"_id": str(uuid4()), "msisdn": kwargs["msisdn"],
                                 "identity": {"_id": str(uuid4())}}
        if not self._sans_account:
            fiche["account_id"] = str(uuid4())
        self.fiches.append(fiche)
        return fiche


class FauxComptes:
    """account-service simule. Reproduit le piege `FRA-218` : le solde relu
    n'est PAS le montant demande — des frais sont retranches et credites nulle
    part. Un compteur qui ferait confiance au montant emis serait faux."""

    FRAIS = 0.97

    def __init__(self, *, echouer: bool = False, solde_illisible: bool = False) -> None:
        self.credits: list[dict[str, Any]] = []
        self._echouer = echouer
        self._illisible = solde_illisible

    def payload_solde_initial_client(
        self, *, compte_checking_id: Any, montant: float, nom_client: str
    ) -> dict[str, Any]:
        return AccountServiceClient.payload_solde_initial_client(
            self,  # type: ignore[arg-type]
            compte_checking_id=compte_checking_id,
            montant=montant,
            nom_client=nom_client,
        )

    async def crediter(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._echouer:
            raise ErreurService("account-service", "POST", "/credit", 500, "panne", "-")
        self.credits.append(payload)
        return {"ok": True}

    async def solde(self, account_id: Any) -> float | None:
        if self._illisible:
            return None
        return round(self.credits[-1]["amount"] * self.FRAIS, 2) if self.credits else None


def _produits() -> list[ProduitSouscriptible]:
    return [
        ProduitSouscriptible(uuid4(), "DEMO_Cotisation", ProductType.COLLECT, "INDIVIDUAL"),
        ProduitSouscriptible(uuid4(), "DEMO_Cotisation Corp", ProductType.COLLECT, "CORPORATE"),
        # Un LENDING dans la liste : il DOIT etre filtre (UC-13).
        ProduitSouscriptible(uuid4(), "DEMO_Nano", ProductType.LENDING, "INDIVIDUAL"),
    ]


def _kiosques(pays: str, nb: int = 4) -> list[Any]:
    from app.models.domain import OrgHierarchyNode
    from app.models.enums import NiveauOrganisation

    noeuds = []
    for ville in REFERENTIEL.villes_porteuses_de_quartiers(pays):
        for quartier in REFERENTIEL.quartiers_de_ville(ville.city_id):
            noeuds.append(
                OrgHierarchyNode(
                    id=uuid4(),
                    run_id=RUN,
                    niveau=NiveauOrganisation.KIOSQUE,
                    parent_id=uuid4(),
                    company_id=uuid4(),
                    name=f"DEMO_Kiosque {quartier.name}",
                    country_code=pays,
                    district_id=quartier.district_id,
                    depositary_id=uuid4(),
                )
            )
    return noeuds[:nb]


def _executeur(
    *,
    mode: RunMode,
    nb_clients: int,
    pays_actifs: tuple[str, ...] = ("CM", "CI", "BF", "SN"),
    faker: Any = None,
    ledger: Any = None,
    clients: Any = None,
    arbre: Any = None,
    comptes: Any = None,
) -> ExecuteurClients:
    configuration = ConfigurationExecution.defaut_cdc()
    configuration.nb_clients = nb_clients
    for code in ("CM", "CI", "BF", "SN"):
        if code not in pays_actifs:
            configuration.desactiver_pays(code, "hors de ce test")
    return ExecuteurClients(
        run_id=RUN,
        mode=mode,
        configuration=configuration,
        referentiel=REFERENTIEL,
        generateur=Generateur(RUN, reference=date(2026, 8, 11)),
        faker=faker or FauxFaker(),
        client_service=clients or ServiceInterdit(),
        account_service=comptes or FauxComptes(),
        hierarchie=arbre or FauxArbre(),
        ledger=ledger or FauxLedger(),
        produits=_produits(),
    )


# ---------------------------------------------------------------------------
# solde_initial — arbitrage A-09, recommandation appliquee
# ---------------------------------------------------------------------------


class TestSoldeInitial:
    def test_un_client_dormant_tombe_dans_la_strate_la_plus_basse(self) -> None:
        """Aucun signal d'activite -> la premiere bande de l'Annexe E."""
        largeur = (SOLDE_INITIAL_MAX - SOLDE_INITIAL_MIN) / (len(CLES_QUICK_WIN_BINAIRES) + 1)
        solde = solde_initial(_tirage(quick_win={}))
        assert SOLDE_INITIAL_MIN <= solde < SOLDE_INITIAL_MIN + largeur

    def test_un_client_au_profil_complet_tombe_dans_la_strate_la_plus_haute(self) -> None:
        largeur = (SOLDE_INITIAL_MAX - SOLDE_INITIAL_MIN) / (len(CLES_QUICK_WIN_BINAIRES) + 1)
        solde = solde_initial(_tirage(quick_win=dict.fromkeys(CLES_QUICK_WIN_BINAIRES, 1)))
        assert SOLDE_INITIAL_MAX - largeur <= solde <= SOLDE_INITIAL_MAX

    def test_deux_clients_de_MEME_profil_n_ont_pas_le_MEME_solde(self) -> None:
        """DEFAUT TROUVE PAR LES TESTS DE LA SOURCE INTERNE : la premiere version
        comptait neuf booleens, donc DIX montants possibles — 2000 clients
        auraient partage dix soldes. Le graphique plat, sur l'axe des montants.
        La strate vient du profil ; la position DANS la strate vient d'une
        empreinte stable du `client_id`."""
        profil = {"IS_RGS_1": 1, "IS_SMARTPHONE_USER": 1}
        soldes = {solde_initial(_tirage(seed=s, quick_win=profil)) for s in range(50)}
        assert len(soldes) == 50, "chaque client a son propre solde au centime"

    def test_le_solde_est_DETERMINISTE(self) -> None:
        """`ENF-15`, et « sans invention arbitraire de montants » : le meme
        client rend le meme solde, toujours."""
        client = _tirage(quick_win={"IS_RGS_1": 1, "IS_SMARTPHONE_USER": 1})
        assert solde_initial(client) == solde_initial(client)

    def test_le_solde_croit_avec_le_profil(self) -> None:
        """Un client plus actif a un patrimoine plus solide — les mots du CDC.
        Compare a `client_id` CONSTANT pour isoler l'effet du profil de celui de
        l'empreinte."""
        soldes = [
            solde_initial(_tirage(seed=1, quick_win=dict.fromkeys(CLES_QUICK_WIN_BINAIRES[:n], 1)))
            for n in range(len(CLES_QUICK_WIN_BINAIRES) + 1)
        ]
        assert soldes == sorted(soldes)
        assert len(set(soldes)) == len(soldes), "chaque signal supplementaire compte"

    def test_le_solde_reste_toujours_dans_les_strates_de_l_annexe_E(self) -> None:
        for n in range(len(CLES_QUICK_WIN_BINAIRES) + 1):
            solde = solde_initial(_tirage(quick_win=dict.fromkeys(CLES_QUICK_WIN_BINAIRES[:n], 1)))
            assert SOLDE_INITIAL_MIN <= solde <= SOLDE_INITIAL_MAX


# ---------------------------------------------------------------------------
# QuotaPays — verifier et compter sont LE MEME GESTE
# ---------------------------------------------------------------------------


class TestQuotaPays:
    def test_les_cibles_decoulent_du_cdc(self) -> None:
        quota = QuotaPays(pays="CM", cible=500)
        assert quota.cible_corporate == 100  # EF-23 : 20 %
        assert quota.cible_individual == 400
        assert quota.cible_femmes == 333  # EF-22 : 2 femmes / 1 homme
        assert quota.cible_jeunes == 300  # EF-22 : 60 % de moins de 25 ans
        assert quota.cible_agricoles == 20  # EF-24 : 20 % des professionnels

    def test_reserver_verifie_ET_compte_dans_le_meme_geste(self) -> None:
        """LE defaut mesure en deux passes : verifier sans compter laissait
        vingt arbitrages passer le meme controle. `Corp 101/100`,
        `Femmes 311/333`, `<25ans 320/300` — tous la meme cause."""
        quota = QuotaPays(pays="CM", cible=25)
        reservation = quota.reserver(_tirage(genre="WOMAN", business=True))
        assert reservation is not None
        assert quota.femmes == 1, "compte immediatement, pas apres l'ecriture"
        assert quota.corporate_faits == 1

    def test_la_categorie_saturee_rejette(self) -> None:
        quota = QuotaPays(pays="CM", cible=25)  # corp cible = 5
        for seed in range(5):
            assert quota.reserver(_tirage(genre="MAN", business=True, seed=seed)) is not None
        assert quota.reserver(_tirage(genre="MAN", business=True, seed=99)) is None
        assert quota.corporate_faits == 5, "le rejet ne compte pas"

    def test_le_genre_sature_rejette(self) -> None:
        # cible 6 -> corp 1, individual 5, femmes 4, hommes 2. Quatre femmes
        # passent en INDIVIDUAL (4 < 5) ; la cinquieme est rejetee par le GENRE,
        # pas par la categorie — c'est precisement ce que le test doit isoler.
        quota = QuotaPays(pays="CM", cible=6)
        for seed in range(1, 5):
            assert quota.reserver(_tirage(genre="WOMAN", seed=seed)) is not None
        assert quota.reserver(_tirage(genre="WOMAN", seed=5)) is None, "femmes saturees"
        assert quota.reserver(_tirage(genre="MAN", seed=6)) is not None

    def test_les_jeunes_sont_attribues_jusqu_a_la_cible_puis_plus_jamais(self) -> None:
        quota = QuotaPays(pays="CM", cible=5)  # jeunes cible = 3
        jeunes = [
            r.jeune
            for seed in range(5)
            if (r := quota.reserver(_tirage(genre="WOMAN" if seed % 3 else "MAN", seed=seed)))
        ]
        assert jeunes.count(True) == 3
        assert jeunes[:3] == [True, True, True]

    def test_l_agriculture_est_servie_en_premier_puis_les_trois_autres_familles(self) -> None:
        """`EF-24` : 20 % agricole, le reste en transports/commerce/services."""
        quota = QuotaPays(pays="CM", cible=25)  # corp 5, agri 1
        secteurs = [
            r.secteur
            for seed in range(5)
            if (r := quota.reserver(_tirage(genre="MAN", business=True, seed=seed)))
        ]
        assert secteurs[0] == "AGRICULTURE"
        assert "AGRICULTURE" not in secteurs[1:]
        assert all(s in ("TRANSPORTS", "COMMERCE", "SERVICES") for s in secteurs[1:])

    def test_un_individual_n_a_pas_de_secteur(self) -> None:
        quota = QuotaPays(pays="CM", cible=25)
        reservation = quota.reserver(_tirage(genre="WOMAN", business=False))
        assert reservation is not None and reservation.secteur == ""

    def test_rendre_defait_la_reservation_EN_ENTIER(self) -> None:
        """Un client qui echoue ne compte pas — sinon la cible se remplit de
        clients inexistants et le rapport ment sur la distribution."""
        quota = QuotaPays(pays="CM", cible=25)
        reservation = quota.reserver(_tirage(genre="WOMAN", business=True))
        assert reservation is not None
        quota.rendre(reservation)
        assert (quota.faits, quota.femmes, quota.jeunes, quota.agricoles) == (0, 0, 0, 0)

    def test_la_reservation_est_immuable(self) -> None:
        quota = QuotaPays(pays="CM", cible=25)
        reservation = quota.reserver(_tirage(genre="WOMAN"))
        assert reservation is not None
        with pytest.raises(AttributeError):
            reservation.jeune = False  # type: ignore[misc]

    def test_l_ancien_decoupage_verifier_puis_compter_n_existe_plus(self) -> None:
        """Les methodes `categorie_ouverte()` et `genre_ouvert()` sont
        SUPPRIMEES : leur seule existence invitait a « verifier maintenant,
        compter plus tard » — la cause des deux depassements mesures."""
        assert not hasattr(QuotaPays, "categorie_ouverte")
        assert not hasattr(QuotaPays, "genre_ouvert")
        assert not hasattr(QuotaPays, "enregistrer")


# ---------------------------------------------------------------------------
# L'essai a blanc — tout montrer, rien ecrire
# ---------------------------------------------------------------------------


class TestDryRun:
    async def _rapport(self) -> tuple[RapportClients, FauxFaker, FauxLedger]:
        faker, ledger = FauxFaker(), FauxLedger()
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=100, faker=faker, ledger=ledger)
        return await ex.executer(), faker, ledger

    async def test_les_quatre_pays_du_cdc_sont_servis_avec_des_quotas_EXACTS(self) -> None:
        """`OBJ-01` exige QUATRE pays, et le Senegal en est un — servi par la
        source interne depuis que Faker a confirme son `enum: ["BF","CI","CM"]`.
        La table est celle que l'operateur lit avant de dire oui (`D-01`)."""
        rapport, _, _ = await self._rapport()
        servis = {q.pays: q for q in rapport.quotas}
        assert set(servis) == {"CM", "CI", "BF", "SN"}, "les 4 pays cibles, sans exception"
        for quota in servis.values():
            assert quota.faits == 25, quota.resume()
            assert quota.corporate_faits == quota.cible_corporate == 5
            assert quota.femmes == quota.cible_femmes == 17
            assert quota.jeunes == quota.cible_jeunes == 15
            assert quota.agricoles == quota.cible_agricoles == 1

    async def test_le_senegal_est_SERVI_et_sa_provenance_est_declaree(self) -> None:
        """`A-01` tranche : le Senegal est servi par la source interne (CDC
        §321), et la provenance se LIT au rapport. Elle n'est pas une alerte —
        un ecart declare et arbitre n'est pas un echec, et le faire basculer le
        run en PARTIAL a chaque fois noierait les vraies alertes."""
        rapport, _, _ = await self._rapport()
        sn = next(q for q in rapport.quotas if q.pays == "SN")
        assert sn.faits == 25, "le Senegal est peuple, plus laisse a zero"
        assert rapport.servis_en_interne == {"SN": 25}, "provenance VISIBLE au rapport"
        assert "Source INTERNE" in rapport.resume()
        assert not any("A-01" in a for a in rapport.alertes), (
            "la provenance est un fait declare, pas une alerte"
        )



    async def test_aucune_ecriture_serveur_n_est_partie(self) -> None:
        """Le client-service est un stub qui leve si on l'appelle : le simple
        fait que le test passe est la preuve."""
        rapport, _, _ = await self._rapport()
        assert rapport.echoues == []

    async def test_le_rapport_annonce_ce_que_le_reel_ferait(self) -> None:
        """La lecon des Kiosques (« Comptes attendus : 0 » a blanc, 354 en
        reel) : un essai a blanc qui ne montre pas le reel n'en est pas un."""
        rapport, _, _ = await self._rapport()
        assert len(rapport.crees) == 100, "les 4 pays, source interne comprise"
        assert all(nom.endswith("[prevu]") for nom in rapport.crees)
        assert rapport.comptes_attendus == 100
        assert rapport.solde_dote > 0

    async def test_D_FAKER_1_le_registre_est_rendu_intact(self) -> None:
        """LE defaut des 1227 orphelines : a blanc, rien n'est produit, donc
        rien n'est consomme. Le registre doit finir VIDE."""
        rapport, _, ledger = await self._rapport()
        assert ledger.reserves == set(), "aucune reservation ne survit a l'essai a blanc"
        assert ledger.confirmes == {}, "a blanc, rien n'est jamais scelle"
        assert rapport.liberes_a_blanc == 100

    async def test_l_arbre_vide_est_signale_et_les_ancres_planifiees(self) -> None:
        rapport, _, _ = await self._rapport()
        assert any("PLANIFIEES" in a for a in rapport.alertes)
        assert rapport.statut is RunStatus.PARTIAL


# ---------------------------------------------------------------------------
# Le REEL — les deux moities du write-ahead
# ---------------------------------------------------------------------------


class TestReel:
    async def test_chaque_client_cree_est_SCELLE_au_registre(self) -> None:
        """LE TEST QUI A REVELE LE DEFAUT : `confirmer()` n'etait appele nulle
        part. En REEL, tous les clients restaient RESERVE — la reconciliation
        criait des orphelines sur un run reussi, et `compter_par_usage()` (qui ne
        compte que le SCELLE) affichait zero client au rapport."""
        faker, ledger, clients = FauxFaker(), FauxLedger(), FauxClientService()
        ex = _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("CM",),
            faker=faker,
            ledger=ledger,
            clients=clients,
            arbre=FauxArbre(_kiosques("CM")),
        )
        rapport = await ex.executer()

        assert [q.pays for q in rapport.quotas] == ["CM"], (
            "un pays desactive ne fabrique ni quota ni alerte — bruit dans le rapport D-01"
        )
        assert len(rapport.crees) == 40
        assert len(ledger.confirmes) == 40, "chaque entite creee est scellee — D-FAKER-1"
        assert ledger.reserves == set(), "aucune reservation ne survit au run"
        assert len(clients.onboardes) == 40
        assert rapport.statut is RunStatus.COMPLETED

    async def test_un_echec_serveur_libere_et_rend_le_quota(self) -> None:
        """L'entite n'existe pas : le client Faker redevient tirable et la
        distribution finale reste EXACTE malgre les pannes."""
        ledger, clients = FauxLedger(), FauxClientService(echouer_1_sur=5)
        ex = _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("CM",),
            ledger=ledger,
            clients=clients,
            arbre=FauxArbre(_kiosques("CM")),
        )
        rapport = await ex.executer()

        assert rapport.echoues, "les pannes simulees doivent apparaitre au rapport"
        assert rapport.statut is RunStatus.PARTIAL
        quota = next(q for q in rapport.quotas if q.pays == "CM")
        assert quota.faits == len(rapport.crees), "le quota compte le REEL, pas l'intention"
        assert len(ledger.confirmes) == len(rapport.crees)
        assert ledger.reserves == set(), "les echecs sont liberes, jamais retenus"

    async def test_la_provenance_interne_survit_jusqu_au_REGISTRE(self) -> None:
        """Un operateur qui compte 500 Senegalais doit pouvoir dire d'ou ils
        viennent SANS relire le code : le prefixe voyage avec l'`_id` jusque
        dans `faker_consumption_ledger`, ou `compter_par_pays()` le relira."""
        ledger, clients = FauxLedger(), FauxClientService()
        ex = _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("SN",),
            ledger=ledger,
            clients=clients,
            arbre=FauxArbre(_kiosques("SN")),
        )
        rapport = await ex.executer()

        assert rapport.servis_en_interne == {"SN": 40}
        assert len(ledger.confirmes) == 40
        assert all(est_interne(cid) for cid in ledger.confirmes), (
            "chaque id scelle porte sa provenance"
        )
        assert all(cid.startswith("INTERNE-SN-") for cid in ledger.confirmes)

    async def test_en_reel_un_arbre_vide_est_un_VRAI_blocage(self) -> None:
        """`EF-26` exige un Kiosque EXISTANT : on n'invente pas un rattachement
        vers un Depositaire jamais cree."""
        clients = FauxClientService()
        ex = _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("CM",),
            clients=clients,
            arbre=FauxArbre([]),
        )
        rapport = await ex.executer()
        assert rapport.crees == []
        assert clients.onboardes == []
        assert any("DEPOSITAIRES" in a for a in rapport.alertes)


class TestSceller:
    async def test_un_id_serveur_uuid_est_scelle_tel_quel(self) -> None:
        ledger = FauxLedger()
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=ledger)
        entite = uuid4()
        await ledger.reserver("TEST-CM-IND-1")
        await ex._sceller("TEST-CM-IND-1", {"_id": str(entite)})
        assert ledger.confirmes["TEST-CM-IND-1"] == entite

    async def test_un_id_serveur_hors_uuid_est_scelle_sous_un_uuid_STABLE(self) -> None:
        """Le contrat de client-service ne garantit pas le format de `_id`, et
        l'ecriture reelle n'a jamais eu lieu. Un id illisible ne perd pas le
        lien : uuid5 est deterministe, et l'id brut vit dans le log."""
        ledger = FauxLedger()
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=ledger)
        await ledger.reserver("TEST-CM-IND-2")
        await ex._sceller("TEST-CM-IND-2", {"_id": "68c0ffee00b1ec7"})
        attendu = uuid5(NAMESPACE_OID, "finzuu-client:68c0ffee00b1ec7")
        assert ledger.confirmes["TEST-CM-IND-2"] == attendu

    async def test_sceller_sans_reservation_CRIE(self) -> None:
        """Une entite irreversible hors registre est un defaut de cablage —
        jamais un aleas d'exploitation a rattraper en silence."""
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=FauxLedger())
        with pytest.raises(ConsommationIncoherente):
            await ex._sceller("TEST-JAMAIS-RESERVE", {"_id": str(uuid4())})


# ---------------------------------------------------------------------------
# Les produits — UC-13, la coherence est a notre charge
# ---------------------------------------------------------------------------


class TestProduits:
    def test_les_produits_lending_sont_filtres(self) -> None:
        """Le serveur accepte un LENDING en 201 (miroir de FRA-223) : le filtre
        est le notre, et lui seul."""
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        rapport = RapportClients(mode=RunMode.DRY_RUN)
        collect = ex._produits_collect(rapport)
        assert all(p.type_produit is ProductType.COLLECT for p in collect)
        assert len(collect) == 2

    def test_un_corporate_ne_recoit_jamais_un_produit_individual(self) -> None:
        """`OBS-CLI-CROSSCHECK-01` : aucune validation croisee cote serveur —
        « une incoherence visible a l'oeil nu devant un bailleur »."""
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        individual_seul = [
            ProduitSouscriptible(uuid4(), "DEMO_Cotisation", ProductType.COLLECT, "INDIVIDUAL")
        ]
        assert ex._choisir_produit(individual_seul, ClientCategory.CORPORATE) is None
        produit = ex._choisir_produit(individual_seul, ClientCategory.INDIVIDUAL)
        assert produit is not None

    def test_un_catalogue_sans_collect_bloque_et_le_dit(self) -> None:
        """`D-CLI-1` : `product_id` est REQUIS a l'onboarding — sans COLLECT,
        aucun client n'est generable, et le rapport doit le dire."""
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        ex._produits = [
            ProduitSouscriptible(uuid4(), "DEMO_Nano", ProductType.LENDING, "INDIVIDUAL")
        ]
        rapport = RapportClients(mode=RunMode.DRY_RUN)
        assert ex._produits_collect(rapport) == []
        assert any("COLLECT" in a for a in rapport.alertes)


# ---------------------------------------------------------------------------
# UC-13 pt 3 / EF-73 — la dotation du solde initial
# ---------------------------------------------------------------------------


class TestLaDotationDuSoldeInitial:
    """LE DÉFAUT LE PLUS TROMPEUR DU 11/08 : `solde_dote` accumulait
    1,04 Md FCFA et le rapport l'affichait, sans qu'aucun appel à `crediter()`
    existe. Même en RÉEL, les 2000 comptes seraient restés à zéro. Ce n'était
    pas un module muet — c'était un rapport qui affirmait un fait que le code
    ne produisait pas, et `D-01` fait de ce rapport la dernière occasion de
    dire non."""

    async def _reel(self, **kw: Any) -> tuple[RapportClients, FauxComptes, FauxClientService]:
        comptes = kw.pop("comptes", None) or FauxComptes()
        clients = kw.pop("clients", None) or FauxClientService()
        ex = _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("CM",),
            clients=clients,
            comptes=comptes,
            arbre=FauxArbre(_kiosques("CM")),
            **kw,
        )
        return await ex.executer(), comptes, clients

    async def test_chaque_client_cree_recoit_UN_credit(self) -> None:
        rapport, comptes, _ = await self._reel()
        assert len(rapport.crees) == 40
        assert len(comptes.credits) == 40, "UC-13 pt 3 — un dépôt par client, pas zéro"

    async def test_le_solde_compte_ce_que_le_SERVEUR_a_confirme(self) -> None:
        """`FRA-218` : les frais sont retranchés du montant et crédités nulle
        part. Le solde se RELIT, il ne se calcule pas — un compteur qui fait
        confiance au montant émis serait faux, et faux en silence."""
        rapport, comptes, _ = await self._reel()
        demande = sum(c["amount"] for c in comptes.credits)
        assert rapport.solde_dote < demande, "le rapport ne doit PAS compter le montant émis"
        assert rapport.solde_dote == pytest.approx(demande * FauxComptes.FRAIS, rel=1e-6)

    async def test_le_payload_porte_les_trois_valeurs_du_metier(self) -> None:
        """`EF-73` dit « dérivé du montant **Mobile Money** », et le CDC dit
        « il **DÉPOSE** ce montant ». Et jamais `tag=LENDER` : c'est la SEULE
        occurrence du concept de bailleur dans tout l'écosystème FinZuu."""
        _, comptes, _ = await self._reel()
        for credit in comptes.credits:
            assert credit["provider_src"] == "MOMO", "l'origine est le portefeuille mobile"
            assert credit["type"] == "DEPOSIT", "le CDC emploie le mot « dépose »"
            assert credit["tag"] == "SELF", "le client se crédite depuis son propre argent"
            assert credit["tag"] != "LENDER", "LENDER est réservé aux bailleurs"
            # L'argent vient de l'EXTÉRIEUR de FinZuu : aucun compte source
            # n'existe, et le schéma exige pourtant les deux identifiants.
            assert credit["src_account_id"] == credit["dest_account_id"]

    async def test_le_compte_credite_est_celui_de_la_CASCADE(self) -> None:
        """On n'en crée jamais un : `POST /clients/onboard` produit le CHECKING,
        et account-service n'a aucun `DELETE` — un doublon serait définitif."""
        _, comptes, clients = await self._reel()
        rendus = {f["account_id"] for f in clients.fiches}
        credites = {c["dest_account_id"] for c in comptes.credits}
        assert credites == rendus, "chaque crédit vise le compte rendu par la cascade"
        assert len(credites) == 40, "un compte distinct par client, aucun réutilisé"

    async def test_une_dotation_refusee_alerte_sans_annuler_le_client(self) -> None:
        """Le client existe, il est scellé, il est utilisable. Le compter comme
        non créé déséquilibrerait les quotas pour un motif étranger à la
        distribution."""
        rapport, _, _ = await self._reel(comptes=FauxComptes(echouer=True))
        assert len(rapport.crees) == 40, "les clients existent malgré la dotation refusée"
        assert rapport.solde_dote == 0.0, "rien n'est compté sans confirmation serveur"
        assert len(rapport.alertes) >= 40
        assert any("dotation refusee" in a for a in rapport.alertes)

    async def test_un_solde_illisible_n_est_jamais_compte(self) -> None:
        rapport, _, _ = await self._reel(comptes=FauxComptes(solde_illisible=True))
        assert rapport.solde_dote == 0.0
        assert any("FRA-218" in a for a in rapport.alertes)

    async def test_une_cascade_sans_account_id_est_signalee(self) -> None:
        """Si la cascade ne rend pas de compte, on le DIT — on n'invente pas un
        identifiant et on ne crée pas un second compte."""
        rapport, comptes, _ = await self._reel(
            clients=FauxClientService(sans_account_id=True)
        )
        assert comptes.credits == [], "aucun crédit émis à l'aveugle"
        assert any("account_id" in a for a in rapport.alertes)
        assert len(rapport.crees) == 40, "le client reste créé et utilisable"

    async def test_a_blanc_le_montant_PREVU_est_annonce_sans_aucun_credit(self) -> None:
        """`D-01` — le rapport à blanc doit montrer ce que le RÉEL ferait."""
        comptes = FauxComptes()
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=100, comptes=comptes)
        rapport = await ex.executer()
        assert comptes.credits == [], "à blanc, aucune écriture serveur"
        assert rapport.solde_dote > 0, "et pourtant le montant prévu est annoncé"
