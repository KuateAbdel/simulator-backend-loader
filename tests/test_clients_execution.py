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

import random
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import NAMESPACE_OID, UUID, uuid4, uuid5

import pytest

from app.clients.account_service import AccountServiceClient
from app.clients.base import ErreurService
from app.clients.client_service import SOUSCRIPTIONS_MAX
from app.clients.contracts import ClientCategory, ClientSegment, ProductType
from app.clients.faker_service import CategorieClient, ClientFaker
from app.core.cdc import PROFILS_COMPORTEMENTAUX, TOLERANCE_DISTRIBUTION_POINTS
from app.core.configuration import ConfigurationExecution
from app.models.enums import EtatConsommationFaker, RunMode, RunStatus
from app.repositories.faker_ledger import ConsommationIncoherente
from app.services.clients_composition import GROUPES_PAR_FAMILLE_CDC
from app.services.clients_execution import (
    CLES_QUICK_WIN_BINAIRES,
    ORDRE_SOUSCRIPTION,
    PANIER_PAR_SEGMENT,
    SEGMENTS_ANNEXE_E,
    SEUIL_MOBILE_MONEY_FCFA,
    SOLDE_INITIAL_MAX,
    SOLDE_INITIAL_MIN,
    ExecuteurClients,
    QuotaPays,
    RapportClients,
    segment_client,
    solde_initial,
)
from app.services.depositaires_execution import ProduitSouscriptible
from app.services.generateur import Generateur
from app.services.geographie import charger_referentiel
from app.services.referentiel_statique import charger_statique
from app.services.source_interne import est_interne

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
STATIQUE = charger_statique()
REFERENTIEL = charger_referentiel(CLASSEUR)
#: Fige : les seeds derivent du run_id, donc tout le deroule est deterministe.
RUN = UUID(int=42)
#: Le `run_id` d'un SECOND run. `CR-03` ne se prouve qu'entre deux executions
#: distinctes : reutiliser `RUN` rendrait tout test de reprise complaisant.
AUTRE_RUN = UUID(int=4242)

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

    def __init__(self, *, replier_sur: int = 0) -> None:
        self.appels = 0
        #: Le cache Faker est DETERMINISTE : deux graines distinctes peuvent
        #: rendre le meme `client_id`, et le CDC §185 prevoit ce cas. `replier_sur`
        #: le reproduit en ramenant les graines modulo N.
        self._replier = replier_sur

    async def tirer_client(self, pays: str, categorie: str, seed: int) -> ClientFaker:
        self.appels += 1
        if self._replier:
            seed = seed % self._replier
        return _tirage(
            # LES NEUF SIGNAUX `quick_win`, VARIES PAR LA GRAINE.
            #
            # Ce double n'en posait qu'UN a 1, donc `segment_client()` rendait
            # `VERY_LOW` pour tous et `solde_initial()` restait dans la strate la
            # plus basse. Defaut trouve le 12/08 par le test « les 2000 clients ne
            # sont plus tous ANY » : le code etait bon, le double appauvri.
            #
            # La famille A est deterministe par graine et porte onze champs
            # `quick_win`, dont neuf binaires. Les bits de la graine les etalent.
            pays,
            quick_win={
                cle: (seed >> i) & 1 for i, cle in enumerate(CLES_QUICK_WIN_BINAIRES)
            },
            genre="WOMAN" if seed % 3 else "MAN",
            business=categorie == CategorieClient.BUSINESS,
            seed=seed,
        )


class FauxLedger:
    """Le registre D-FAKER-1, en memoire, avec les memes regles que le vrai."""

    #: Un run ANTERIEUR, pour que `run_id != self.run_id` distingue la reprise
    #: d'une collision interne au run courant.
    RUN_ANTERIEUR = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

    def __init__(self, deja_consommes: set[str] | None = None) -> None:
        self.reserves: set[str] = set()
        self.confirmes: dict[str, UUID] = {}
        self.liberations = 0
        #: `CR-03` — ce qu'un run precedent a deja transforme en entite. Le vrai
        #: registre est GLOBAL (`_id` = client_id Faker), pas indexe par run :
        #: c'est ce qui rend la reprise possible, et c'est ce que ce double doit
        #: reproduire.
        self._anterieurs = deja_consommes or set()

    async def reserver(self, client_id: str, **_: Any) -> bool:
        if client_id in self.reserves or client_id in self.confirmes:
            return False
        if client_id in self._anterieurs:
            return False
        self.reserves.add(client_id)
        return True

    async def etat(self, client_id: str) -> Any:
        if client_id in self._anterieurs:
            return SimpleNamespace(
                state=EtatConsommationFaker.CONSOMME, run_id=self.RUN_ANTERIEUR
            )
        if client_id in self.confirmes:
            return SimpleNamespace(state=EtatConsommationFaker.CONSOMME, run_id=RUN)
        if client_id in self.reserves:
            return SimpleNamespace(state=EtatConsommationFaker.RESERVE, run_id=RUN)
        return None

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
        #: `EF-26` — les rattachements ecrits. Le vrai depot les rend idempotents
        #: par l'index `uniq_client_par_run` ; ce double reproduit la regle, sinon
        #: un test de reprise verrait deux noeuds pour un client.
        self.rattachements: dict[UUID, UUID] = {}

    async def par_niveau(self, run_id: UUID, niveau: Any) -> list[Any]:
        return list(self.noeuds)

    async def ajouter_client(
        self, *, run_id: UUID, kiosque_id: UUID, company_id: UUID,
        country_code: str, msisdn: str, client_id: UUID,
    ) -> Any:
        self.rattachements[client_id] = kiosque_id
        return SimpleNamespace(
            id=uuid4(), client_id=client_id, parent_id=kiosque_id,
            country_code=country_code, name=f"DEMO_Client {msisdn}",
        )


class ServiceInterdit:
    """client-service qui refuse d'etre appele — la preuve du DRY_RUN."""

    async def onboarder(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("DRY_RUN ne doit JAMAIS appeler client-service")

    async def chercher_par_msisdn(self, _msisdn: str) -> dict[str, Any] | None:
        raise AssertionError("DRY_RUN ne lit meme pas — aucun appel reseau")


class FauxClientService:
    """client-service simule ; `echouer_1_sur` fait echouer un appel sur N."""

    def __init__(
        self,
        echouer_1_sur: int = 0,
        *,
        sans_account_id: bool = False,
        msisdns_existants: set[str] | None = None,
        refuser_souscriptions: bool = False,
    ) -> None:
        self.onboardes: list[dict[str, Any]] = []
        #: `UC-13` / `D-CLI-7` — les `PUT /clients/subscribe` recus.
        self.souscriptions: list[tuple[str, Any]] = []
        self._refuser_souscriptions = refuser_souscriptions
        self.fiches: list[dict[str, Any]] = []
        self.recherches: list[str] = []
        self._echouer = echouer_1_sur
        self._sans_account = sans_account_id
        #: `D-CLI-5` — ce que le serveur porte DEJA. Vide par defaut : un double
        #: qui rendrait une fiche pour tout msisdn ferait croire que rien ne se
        #: cree jamais.
        self._existants = msisdns_existants or set()
        self._n = 0

    async def souscrire(self, msisdn: str, product_id: Any) -> dict[str, Any]:
        """`D-CLI-7` — HTTP 200, le tableau `product` s'allonge (mesure 09/08).

        Le vrai service refuse le DOUBLON : `400 « A customer cannot subscribe to
        the same products twice »`. Ce double le reproduit, sinon un panier qui
        repeterait un produit passerait ici sans que rien ne le signale.
        """
        if self._refuser_souscriptions:
            raise ErreurService(
                "client-service", "PUT", "/subscribe", 500, "panne simulee", "-"
            )
        if (msisdn, product_id) in self.souscriptions:
            raise ErreurService(
                "client-service", "PUT", "/subscribe", 400,
                "A customer cannot subscribe to the same products twice", "-",
            )
        self.souscriptions.append((msisdn, product_id))
        return {"msisdn": msisdn}

    async def chercher_par_msisdn(self, msisdn: str) -> dict[str, Any] | None:
        """Le vrai service rend `404` — donc `None` — quand le client n'existe
        pas (mesure du 09/08, traite par `vide_si_404`). Un double qui omettait
        cette methode a fait echouer neuf tests sans qu'aucun defaut du code soit
        en cause : c'est le double qui ne ressemblait pas au service."""
        self.recherches.append(msisdn)
        if msisdn not in self._existants:
            return None
        return {"_id": str(uuid4()), "msisdn": msisdn, "identity": {"_id": str(uuid4())},
                "account_id": str(uuid4())}

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
    """LE CATALOGUE REEL — six COLLECT, trois par categorie, un par PolicyType.

    Cette fixture n'en portait que DEUX (un par categorie) et aucun
    `policy_type`. Consequence trouvee le 12/08 : l'executeur ne pouvait
    composer qu'un panier d'UN produit, donc `UC-13` restait a une souscription —
    et les tests de panier, qui s'appuyaient sur un catalogue synthetique a trois
    produits, passaient quand meme. Un double appauvri rend un test complaisant.

    Noms et `PolicyType` conformes a `app/services/catalogue.py`.
    """
    return [
        ProduitSouscriptible(
            uuid4(), "DEMO_Cotisation 20000/mois", ProductType.COLLECT, "INDIVIDUAL", "CASH"
        ),
        ProduitSouscriptible(
            uuid4(), "DEMO_Depot a Terme 6 Mois", ProductType.COLLECT, "INDIVIDUAL", "CASH_DAT"
        ),
        ProduitSouscriptible(
            uuid4(), "DEMO_plastique", ProductType.COLLECT, "INDIVIDUAL", "PRODUCT"
        ),
        ProduitSouscriptible(
            uuid4(), "DEMO_Cotisation Commercants", ProductType.COLLECT, "CORPORATE", "CASH"
        ),
        ProduitSouscriptible(
            uuid4(),
            "DEMO_Depot a Terme Entreprise 12 Mois",
            ProductType.COLLECT,
            "CORPORATE",
            "CASH_DAT",
        ),
        ProduitSouscriptible(
            uuid4(), "DEMO_Collecte Cacao", ProductType.COLLECT, "CORPORATE", "PRODUCT"
        ),
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
    #: Un vrai second run porte un AUTRE `run_id`. Le figer a `RUN` rendait le
    #: test de reprise aveugle : `self._alea` produisait la meme suite dans les
    #: deux executions, donc les memes clients Faker meme quand la graine venait
    #: du run. Le test de mutation l'a montre — il passait avec le defaut remis.
    run_id: UUID = RUN,
) -> ExecuteurClients:
    configuration = ConfigurationExecution.defaut_cdc()
    configuration.nb_clients = nb_clients
    for code in ("CM", "CI", "BF", "SN"):
        if code not in pays_actifs:
            configuration.desactiver_pays(code, "hors de ce test")
    return ExecuteurClients(
        run_id=run_id,
        mode=mode,
        configuration=configuration,
        referentiel=REFERENTIEL,
        # `SD-3` — le vrai catalogue de JJB, jamais un double. Les 576
        # professions qu'il porte partent REELLEMENT dans `identity.occupation`.
        statique=STATIQUE,
        generateur=Generateur(run_id, reference=date(2026, 8, 11)),
        faker=faker or FauxFaker(),
        client_service=clients or ServiceInterdit(),
        account_service=comptes or FauxComptes(),
        hierarchie=arbre or FauxArbre(),
        ledger=ledger or FauxLedger(),
        produits=_produits(),
    )


# ---------------------------------------------------------------------------
# solde_initial — A-09 FERME (SD-5) : le modele de revenu par profession
# ---------------------------------------------------------------------------


class TestSoldeInitial:
    """`SD-5` — profession -> profil de revenu -> LogNormal(mu, sigma), borne.

    L'HEURISTIQUE REMPLACEE : neuf signaux `quick_win` -> dix strates -> une
    position hachee. Elle mesurait l'EQUIPEMENT (smartphone, data), pas le
    REVENU. Le modele de JJB attache chaque profession a un profil de revenu
    documente — « un patrimoine coherent avec son profil socio-economique »
    devient litteral, et `A-09` se ferme.

    Deux professions-temoins, verifiees dans `test_referentiel_statique` :
    « Public hospital doctor » est `bank_stable` (mu 12,15 — mediane 189 094),
    « Traditional healer » est `micro_informal` (mu 11,65 — mediane 114 691).
    """

    def test_le_solde_est_DETERMINISTE(self) -> None:
        """`ENF-15` : le meme client, le meme metier -> le meme solde au
        centime, a chaque appel, sur chaque machine."""
        a = solde_initial("CM-IND-42", "Public hospital doctor", STATIQUE)
        b = solde_initial("CM-IND-42", "Public hospital doctor", STATIQUE)
        assert a == b

    def test_ANCRE_au_client_la_signature_ne_connait_PAS_le_run(self) -> None:
        """`CR-03` par construction : la fonction ne recoit ni `run_id` ni
        graine de run — elle NE PEUT PAS en dependre. Deux clients distincts,
        eux, different."""
        assert solde_initial(
            "CM-IND-1", "Traditional healer", STATIQUE
        ) != solde_initial("CM-IND-2", "Traditional healer", STATIQUE)

    def test_les_bornes_de_l_annexe_E_TIENNENT_meme_en_queue_lognormale(self) -> None:
        """sigma 0,70 (`agri_seasonal`) produit des queues en millions ; le CDC
        borne, donc on borne — [5 000, 1 000 000], bornes incluses, sur 2000
        tirages du profil le plus disperse."""
        for rang in range(2000):
            solde = solde_initial(f"CM-AGRI-{rang}", "Cocoa farmer", STATIQUE)
            assert SOLDE_INITIAL_MIN <= solde <= SOLDE_INITIAL_MAX

    def test_les_bornes_ECRETENT_reellement_deux_clients_temoins(self) -> None:
        """Trouve par MUTATION le 13/08 : retirer l'ecretage ne faisait tomber
        AUCUN test — sur 2000 tirages, aucune queue ne depassait les bornes par
        hasard. Un garde-fou que rien n'exerce n'est pas un garde-fou.

        Deux clients-temoins, trouves par recherche dans l'espace des ancres :
        le tirage BRUT de `CM-AGRI-2904` vaut 1 301 591 FCFA (> MAX), celui de
        `CM-AGRI-55219` vaut 4 161 FCFA (< MIN). L'ecretage doit les ramener
        EXACTEMENT aux bornes de l'Annexe E."""
        assert solde_initial("CM-AGRI-2904", "Cocoa farmer", STATIQUE) == SOLDE_INITIAL_MAX
        assert solde_initial("CM-AGRI-55219", "Cocoa farmer", STATIQUE) == SOLDE_INITIAL_MIN

    def test_chaque_client_a_SON_solde(self) -> None:
        """Le defaut historique de l'heuristique — dix paliers partages — ne
        doit pas revenir : 500 clients du MEME metier, 500 soldes distincts."""
        soldes = {
            solde_initial(f"CM-IND-{r}", "Traditional healer", STATIQUE)
            for r in range(500)
        }
        assert len(soldes) == 500

    def test_la_MEDIANE_du_modele_est_respectee(self) -> None:
        """La mediane d'une LogNormal(mu, sigma) est e^mu — 189 094 FCFA pour
        `bank_stable`. Si la mesure s'en ecarte, le modele n'est pas celui que
        le fichier documente. Tolerance : 5 % sur 1000 clients figes."""
        soldes = sorted(
            solde_initial(f"CM-IND-{r}", "Public hospital doctor", STATIQUE)
            for r in range(1000)
        )
        mediane = (soldes[499] + soldes[500]) / 2
        assert abs(mediane - 189_094) / 189_094 < 0.05, f"mediane {mediane:.0f}"

    def test_un_medecin_est_mieux_dote_qu_un_guerisseur(self) -> None:
        """La hierarchie des profils doit etre VISIBLE dans les montants — en
        mediane, jamais client par client : une distribution qui ne chevauche
        pas ne serait pas lognormale."""
        docteurs = sorted(
            solde_initial(f"a-{r}", "Public hospital doctor", STATIQUE)
            for r in range(500)
        )
        guerisseurs = sorted(
            solde_initial(f"a-{r}", "Traditional healer", STATIQUE)
            for r in range(500)
        )
        assert docteurs[250] > guerisseurs[250]

    def test_EF_68_le_seuil_de_150_000_partage_VRAIMENT_la_population(self) -> None:
        """`EF-68` pese `MOB_MONEY_ACCOUNT_AMOUNT` au seuil de 150 000 FCFA. Un
        modele qui mettrait tout le monde du meme cote rendrait la regle morte.
        Sens attendu : majorite d'un salaire stable AU-DESSUS, majorite d'un
        revenu agricole saisonnier EN DESSOUS."""
        stables = [
            solde_initial(f"b-{r}", "Public hospital doctor", STATIQUE)
            for r in range(500)
        ]
        agricoles = [
            solde_initial(f"b-{r}", "Cocoa farmer", STATIQUE) for r in range(500)
        ]
        part_stables = sum(s >= SEUIL_MOBILE_MONEY_FCFA for s in stables) / 500
        part_agricoles = sum(s >= SEUIL_MOBILE_MONEY_FCFA for s in agricoles) / 500
        assert part_stables > 0.5, f"salaries au-dessus du seuil : {part_stables:.0%}"
        assert part_agricoles < 0.5, f"agricoles au-dessus du seuil : {part_agricoles:.0%}"
        assert part_agricoles > 0.0, "un cote entierement vide rendrait EF-68 mort"


# ---------------------------------------------------------------------------
# QuotaPays — verifier et compter sont LE MEME GESTE
# ---------------------------------------------------------------------------


class TestQuotaPays:
    def test_les_cibles_decoulent_du_cdc(self) -> None:
        quota = QuotaPays(pays="CM", cible=500, statique=STATIQUE)
        assert quota.cible_corporate == 100  # EF-23 : 20 %
        assert quota.cible_individual == 400
        assert quota.cible_femmes == 333  # EF-22 : 2 femmes / 1 homme
        assert quota.cible_jeunes == 300  # EF-22 : 60 % de moins de 25 ans
        assert quota.cible_agricoles == 20  # EF-24 : 20 % des professionnels

    def test_reserver_verifie_ET_compte_dans_le_meme_geste(self) -> None:
        """LE defaut mesure en deux passes : verifier sans compter laissait
        vingt arbitrages passer le meme controle. `Corp 101/100`,
        `Femmes 311/333`, `<25ans 320/300` — tous la meme cause."""
        quota = QuotaPays(pays="CM", cible=25, statique=STATIQUE)
        reservation = quota.reserver(_tirage(genre="WOMAN", business=True))
        assert reservation is not None
        assert quota.femmes == 1, "compte immediatement, pas apres l'ecriture"
        assert quota.corporate_faits == 1

    def test_la_categorie_saturee_rejette(self) -> None:
        quota = QuotaPays(pays="CM", cible=25, statique=STATIQUE)  # corp cible = 5
        for seed in range(5):
            assert quota.reserver(_tirage(genre="MAN", business=True, seed=seed)) is not None
        assert quota.reserver(_tirage(genre="MAN", business=True, seed=99)) is None
        assert quota.corporate_faits == 5, "le rejet ne compte pas"

    def test_le_genre_sature_rejette(self) -> None:
        # cible 6 -> corp 1, individual 5, femmes 4, hommes 2. Quatre femmes
        # passent en INDIVIDUAL (4 < 5) ; la cinquieme est rejetee par le GENRE,
        # pas par la categorie — c'est precisement ce que le test doit isoler.
        quota = QuotaPays(pays="CM", cible=6, statique=STATIQUE)
        for seed in range(1, 5):
            assert quota.reserver(_tirage(genre="WOMAN", seed=seed)) is not None
        assert quota.reserver(_tirage(genre="WOMAN", seed=5)) is None, "femmes saturees"
        assert quota.reserver(_tirage(genre="MAN", seed=6)) is not None

    def test_les_jeunes_sont_ENTRELACES_et_non_servis_en_bloc(self) -> None:
        """`EF-22` — le compte exact ne suffit pas : l'ORDRE compte aussi.

        Ce test exigeait `[True, True, True]` en tete, c'est-a-dire l'artefact
        lui-meme. Sur 1000 clients, cela faisait des 600 PREMIERS clients de
        chaque pays des moins de 25 ans, et des 400 suivants des plus ages —
        visible sur n'importe quel inventaire trie par date de creation.

        Et l'artefact en a produit un second, bien plus grave : le quota des
        profils comportementaux etant glouton, les 600 jeunes vidaient le stock de
        `BON_PAYEUR` avant qu'un seul client age n'arrive. Mesure du 12/08 : moins
        de 25 ans -> 83,3 % de BON_PAYEUR et 0 % de DEFAUT_TOTAL, quand l'Annexe
        D.2 dit l'exact contraire. L'ajustement de Duhamel etait INVERSE par un
        ordonnancement.

        La suite de Bresenham rend exactement `cible_jeunes` positifs sur `cible`
        rangs, repartis.
        """
        quota = QuotaPays(pays="CM", cible=100, statique=STATIQUE)  # jeunes 60, corp 20, femmes 67
        jeunes = [
            r.jeune
            for seed in range(200)
            if (
                r := quota.reserver(
                    _tirage(
                        genre="WOMAN" if seed % 3 else "MAN",
                        business=seed % 5 == 0,
                        seed=seed,
                    )
                )
            )
        ]
        assert quota.jeunes == quota.cible_jeunes == 60, "le compte reste EXACT"

        # LA PROPRIETE QUI COMPTE : les jeunes sont REPARTIS. Sur le premier
        # tiers de la sequence on doit en trouver environ un tiers — jamais la
        # totalite, ce que faisait la version en bloc.
        tiers = len(jeunes) // 3
        dans_le_premier_tiers = jeunes[:tiers].count(True)
        # Une repartition parfaite en donne UN TIERS. Mes premieres bornes
        # (0,40-0,45) etaient fausses : la mesure rendait 0,333, soit exactement
        # le tiers attendu. Le code avait raison, l'assertion avait tort.
        assert 0.28 <= dans_le_premier_tiers / 60 <= 0.40, (
            f"{dans_le_premier_tiers}/60 jeunes dans le premier tiers — la version "
            "en bloc en mettait 60/60, et le quota des profils comportementaux "
            "s'en trouvait fausse (mesure du 12/08 : <25 ans -> 0 % DEFAUT_TOTAL)"
        )

    def test_l_agriculture_est_servie_en_premier_puis_les_trois_autres_familles(self) -> None:
        """`EF-24` : 20 % agricole, le reste en transports/commerce/services."""
        quota = QuotaPays(pays="CM", cible=25, statique=STATIQUE)  # corp 5, agri 1
        secteurs = [
            r.secteur
            for seed in range(5)
            if (r := quota.reserver(_tirage(genre="MAN", business=True, seed=seed)))
        ]
        assert secteurs[0] == "AGRICULTURE"
        assert "AGRICULTURE" not in secteurs[1:]
        assert all(s in ("TRANSPORTS", "COMMERCE", "SERVICES") for s in secteurs[1:])

    def test_un_individual_n_a_pas_de_secteur(self) -> None:
        quota = QuotaPays(pays="CM", cible=25, statique=STATIQUE)
        reservation = quota.reserver(_tirage(genre="WOMAN", business=False))
        assert reservation is not None and reservation.secteur == ""

    def test_rendre_defait_la_reservation_EN_ENTIER(self) -> None:
        """Un client qui echoue ne compte pas — sinon la cible se remplit de
        clients inexistants et le rapport ment sur la distribution."""
        quota = QuotaPays(pays="CM", cible=25, statique=STATIQUE)
        reservation = quota.reserver(_tirage(genre="WOMAN", business=True))
        assert reservation is not None
        quota.rendre(reservation)
        assert (quota.faits, quota.femmes, quota.jeunes, quota.agricoles) == (0, 0, 0, 0)

    def test_la_reservation_est_immuable(self) -> None:
        quota = QuotaPays(pays="CM", cible=25, statique=STATIQUE)
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


def _compose_pour(kiosque: Any, seed: int = 1) -> Any:
    """Un client compose sur ce Kiosque — geographie DERIVEE, comme en vrai."""
    from app.services.clients_composition import ancrer_sur_kiosque, composer

    return composer(
        _tirage("CM", seed=seed),
        ancrer_sur_kiosque(kiosque, REFERENTIEL),
        Generateur(RUN, reference=date(2026, 8, 11)),
        REFERENTIEL,
        random.Random(seed),  # noqa: S311
        jeune=True,
    )


class TestSceller:
    async def test_un_id_serveur_uuid_est_scelle_tel_quel(self) -> None:
        ledger, arbre = FauxLedger(), FauxArbre()
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=ledger, arbre=arbre)
        entite, kiosque = uuid4(), _kiosques("CM")[0]
        await ledger.reserver("TEST-CM-IND-1")
        await ex._sceller(
            "TEST-CM-IND-1", {"_id": str(entite)}, kiosque,
            _compose_pour(kiosque), RapportClients(mode=RunMode.REAL),
        )
        assert ledger.confirmes["TEST-CM-IND-1"] == entite

    async def test_un_id_serveur_hors_uuid_est_scelle_sous_un_uuid_STABLE(self) -> None:
        """Le contrat de client-service ne garantit pas le format de `_id`, et
        l'ecriture reelle n'a jamais eu lieu. Un id illisible ne perd pas le
        lien : uuid5 est deterministe, et l'id brut vit dans le log."""
        ledger, kiosque = FauxLedger(), _kiosques("CM")[0]
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=ledger, arbre=FauxArbre())
        await ledger.reserver("TEST-CM-IND-2")
        await ex._sceller(
            "TEST-CM-IND-2", {"_id": "68c0ffee00b1ec7"}, kiosque,
            _compose_pour(kiosque), RapportClients(mode=RunMode.REAL),
        )
        attendu = uuid5(NAMESPACE_OID, "finzuu-client:68c0ffee00b1ec7")
        assert ledger.confirmes["TEST-CM-IND-2"] == attendu

    async def test_sceller_sans_reservation_CRIE(self) -> None:
        """Une entite irreversible hors registre est un defaut de cablage —
        jamais un aleas d'exploitation a rattraper en silence."""
        kiosque = _kiosques("CM")[0]
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=FauxLedger(), arbre=FauxArbre())
        with pytest.raises(ConsommationIncoherente):
            await ex._sceller(
                "TEST-JAMAIS-RESERVE", {"_id": str(uuid4())}, kiosque,
                _compose_pour(kiosque), RapportClients(mode=RunMode.REAL),
            )

    async def test_le_scellement_ECRIT_le_rattachement_EF_26(self) -> None:
        """`EF-26` — le rattachement Client -> Kiosque n'existe NULLE PART cote
        serveur a la creation : la fiche rendue porte quinze cles et aucune ne
        rattache. Ce noeud est notre seule trace jusqu'a la premiere collecte, et
        sans lui `CR-02` reste non verifiable."""
        ledger, arbre = FauxLedger(), FauxArbre()
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=ledger, arbre=arbre)
        entite, kiosque = uuid4(), _kiosques("CM")[0]
        rapport = RapportClients(mode=RunMode.REAL)
        await ledger.reserver("TEST-CM-IND-3")
        await ex._sceller(
            "TEST-CM-IND-3", {"_id": str(entite)}, kiosque, _compose_pour(kiosque), rapport
        )
        assert arbre.rattachements == {entite: kiosque.id}
        assert rapport.rattaches == 1, "un compteur non incremente est un rapport qui ment"

    async def test_le_pays_ecrit_est_celui_du_CLIENT_pas_du_KIOSQUE(self) -> None:
        """Sinon `CR-02` deviendrait DECORATIF.

        Le controle du depot compare le pays du noeud a celui de son parent. Si
        l'executeur ecrivait `kiosque.country_code`, il comparerait une valeur a
        elle-meme et ne pourrait JAMAIS echouer — le defaut qu'il existe pour
        attraper serait exactement celui qu'il ne verrait pas.

        On apparie ici volontairement un client compose sur un Kiosque camerounais
        avec un Kiosque senegalais. `ancrer_sur_kiosque()` rend ce cas impossible
        en exploitation ; c'est precisement pourquoi il faut le fabriquer pour
        verifier que la trace resterait denoncable.
        """

        class ArbreQuiNote(FauxArbre):
            def __init__(self) -> None:
                super().__init__()
                self.pays_ecrits: list[str] = []

            async def ajouter_client(self, **kwargs: Any) -> Any:
                self.pays_ecrits.append(kwargs["country_code"])
                return await super().ajouter_client(**kwargs)

        arbre, ledger = ArbreQuiNote(), FauxLedger()
        ex = _executeur(mode=RunMode.REAL, nb_clients=40, ledger=ledger, arbre=arbre)
        compose_cm = _compose_pour(_kiosques("CM")[0])
        kiosque_sn = _kiosques("SN")[0]
        await ledger.reserver("TEST-CM-IND-5")
        await ex._sceller(
            "TEST-CM-IND-5", {"_id": str(uuid4())}, kiosque_sn, compose_cm,
            RapportClients(mode=RunMode.REAL),
        )
        assert arbre.pays_ecrits == ["CM"], (
            "le pays ecrit doit etre celui du client (CM), pas celui du Kiosque "
            f"auquel on l'a mal apparie (SN) — obtenu {arbre.pays_ecrits}"
        )

    async def test_un_rattachement_impossible_ALERTE_sans_perdre_le_client(self) -> None:
        """Le client existe cote serveur, definitivement : l'annuler est
        impossible. Mais l'absence de rattachement doit CRIER, sinon `CR-02`
        devient non verifiable en silence."""

        class ArbreQuiRefuse(FauxArbre):
            async def ajouter_client(self, **_: Any) -> Any:
                raise ValueError("Kiosque introuvable — emboitement viole (EF-18)")

        ledger, kiosque = FauxLedger(), _kiosques("CM")[0]
        ex = _executeur(
            mode=RunMode.REAL, nb_clients=40, ledger=ledger, arbre=ArbreQuiRefuse()
        )
        rapport = RapportClients(mode=RunMode.REAL)
        await ledger.reserver("TEST-CM-IND-4")
        await ex._sceller(
            "TEST-CM-IND-4", {"_id": str(uuid4())}, kiosque, _compose_pour(kiosque), rapport
        )
        assert rapport.rattaches == 0
        assert any("NON RATTACHE" in a and "EF-26" in a for a in rapport.alertes)
        assert ledger.confirmes, "la consommation reste scellee : l'entite existe bel et bien"


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
        assert len(collect) == 6, "trois par categorie, un par PolicyType — le catalogue reel"

    def test_un_corporate_ne_recoit_jamais_un_produit_individual(self) -> None:
        """`OBS-CLI-CROSSCHECK-01` : aucune validation croisee cote serveur —
        « une incoherence visible a l'oeil nu devant un bailleur »."""
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        individual_seul = [
            ProduitSouscriptible(uuid4(), "DEMO_Cotisation", ProductType.COLLECT, "INDIVIDUAL")
        ]
        assert ex._produits_compatibles(individual_seul, ClientCategory.CORPORATE) == []
        assert (
            ex._produits_compatibles(individual_seul, ClientCategory.INDIVIDUAL)
            == individual_seul
        )

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


class TestGraineDeterministe:
    """`CR-03` — la population est fonction du PERIMETRE, jamais du run.

    Mesure du 12/08 : la graine venait de `self._alea`, seme par le `run_id`. Un
    second run reel tirait donc 2000 clients Faker entierement differents, le
    registre `D-FAKER-1` ne reconnaissait rien, et 2000 clients se doublaient sur
    des services sans `DELETE`.
    """

    def test_stable_pour_un_meme_rang(self) -> None:
        from app.services.clients_execution import _graine_faker

        assert _graine_faker("CM", 7) == _graine_faker("CM", 7)

    def test_distincte_par_rang_et_par_pays(self) -> None:
        from app.services.clients_execution import _graine_faker

        graines = [_graine_faker("CM", r) for r in range(500)]
        assert len(set(graines)) == 500, "500 rangs doivent donner 500 graines"
        assert _graine_faker("CM", 3) != _graine_faker("CI", 3)

    def test_stable_D_UN_PROCESSUS_A_L_AUTRE(self) -> None:
        """`hash()` des chaines est randomise par processus : l'utiliser aurait
        fait deriver la population a chaque redemarrage du Loader, ce qui est
        exactement le defaut qu'on corrige. Valeur figee ici pour le prouver."""
        import subprocess
        import sys

        code = (
            "from app.services.clients_execution import _graine_faker;"
            "print(_graine_faker('CM', 42))"
        )
        sortie = subprocess.run(  # noqa: S603
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        )
        from app.services.clients_execution import _graine_faker

        assert int(sortie.stdout.strip()) == _graine_faker("CM", 42)

    def test_dans_les_bornes_admises_par_faker(self) -> None:
        from app.services.clients_execution import GRAINE_FAKER_MAX, _graine_faker

        for rang in range(0, 2000, 7):
            assert 1 <= _graine_faker("SN", rang) < GRAINE_FAKER_MAX


class TestReprise:
    """`CR-03` — « idempotence, aucun doublon ». Deux lignes de defense.

    La premiere est le registre `D-FAKER-1` : il sait quels clients Faker ont
    deja produit une entite. La seconde est `D-CLI-5`, le `GET`-avant-`POST`, qui
    couvre le cas ou NOTRE MongoDB serait perdue alors que les clients, eux,
    resteraient sur un service sans `DELETE`.
    """

    async def test_un_client_consomme_par_un_run_ANTERIEUR_est_reconnu_pas_recree(
        self,
    ) -> None:
        clients = FauxClientService()
        ledger = FauxLedger()
        ex = _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("CM",),
            ledger=ledger,
            clients=clients,
            arbre=FauxArbre(_kiosques("CM")),
        )
        # On rejoue le meme perimetre : les graines etant deterministes, ce sont
        # exactement les memes clients Faker que le run precedent aurait pris.
        premier = await ex.executer()
        assert len(premier.crees) == 40

        rejoue = _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("CM",),
            ledger=FauxLedger(deja_consommes=set(ledger.confirmes)),
            clients=FauxClientService(),
            arbre=FauxArbre(_kiosques("CM")),
            run_id=AUTRE_RUN,
        )
        second = await rejoue.executer()

        assert len(second.deja_presents) == 40, "les 40 doivent etre RECONNUS"
        assert second.crees == [], "et AUCUN ne doit etre recree — CR-03"
        quota = next(q for q in second.quotas if q.pays == "CM")
        assert quota.faits == 40, (
            "un client reconnu compte dans la cible : sans cela la boucle "
            "continuerait et creerait 40 doublons"
        )

    async def test_un_run_de_pure_reprise_n_est_pas_declare_FAILED(self) -> None:
        """Il ne cree rien parce que tout existe deja — c'est une REUSSITE, et
        c'est meme la demonstration de `CR-03`."""
        ledger = FauxLedger()
        ex = _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=ledger, clients=FauxClientService(), arbre=FauxArbre(_kiosques("CM")),
        )
        premier = await ex.executer()
        rejoue = _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=FauxLedger(deja_consommes=set(ledger.confirmes)),
            clients=FauxClientService(), arbre=FauxArbre(_kiosques("CM")),
            run_id=AUTRE_RUN,
        )
        second = await rejoue.executer()

        assert second.crees == []
        assert second.statut is not RunStatus.FAILED
        # Trouve par MUTATION : retirer le `reste -= 1` du chemin de reprise ne
        # cree aucun doublon — le quota s'en charge — mais fait tourner cinq lots
        # a vide et termine sur une fausse alerte d'abandon. Un run de reprise
        # parfaite ne doit pas se declarer degrade.
        assert second.alertes == [], f"reprise parfaite, alertes parasites : {second.alertes}"
        assert second.statut is RunStatus.COMPLETED
        # LA PROPRIETE QUI COMPTE, et mon premier jet l'avait ratee en exigeant
        # zero ecart : la boucle SUR-TIRE par conception, donc quelques tirages
        # sont ecartes par saturation de sous-quota — dans le premier run comme
        # dans le second. Ce qu'il faut prouver n'est pas l'absence d'ecarts,
        # c'est que la sequence est rejouee A L'IDENTIQUE : memes rangs, memes
        # decisions, memes ecarts. C'est cela que la graine deterministe achete.
        assert (
            next(q for q in second.quotas if q.pays == "CM").ecartes
            == next(q for q in premier.quotas if q.pays == "CM").ecartes
        ), "le second run doit rejouer exactement le chemin du premier"

    async def test_D_CLI_5_un_msisdn_deja_present_n_est_PAS_recredite(self) -> None:
        """LE VRAI ENJEU, plus que le HTTP 400.

        Un doublon de client se voit. Un solde credite deux fois se lit comme une
        donnee legitime — et `account-service` n'expose aucun moyen de defaire un
        mouvement. On mesure donc d'abord les msisdn que le Loader produit, puis
        on rejoue en les declarant deja presents cote serveur.
        """
        comptes = FauxComptes()
        ex = _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=FauxClientService(),
            comptes=comptes, arbre=FauxArbre(_kiosques("CM")),
        )
        premier = await ex.executer()
        deja = {o["msisdn"] for o in ex._clients.onboardes}  # type: ignore[attr-defined]
        assert len(deja) == 40 and len(comptes.credits) == 40

        comptes_2 = FauxComptes()
        clients_2 = FauxClientService(msisdns_existants=deja)
        rejoue = _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            # Registre VIDE : on isole `D-CLI-5`, comme si notre MongoDB avait
            # ete perdue et le serveur, lui, avait garde ses 40 clients.
            ledger=FauxLedger(), clients=clients_2,
            comptes=comptes_2, arbre=FauxArbre(_kiosques("CM")),
            run_id=AUTRE_RUN,
        )
        second = await rejoue.executer()

        assert clients_2.onboardes == [], "aucun POST : le GET a trouve le client"
        assert comptes_2.credits == [], "AUCUN second credit — le solde doublerait"
        assert len(second.deja_presents) == 40
        assert premier.solde_dote > 0 and second.solde_dote == 0.0, (
            "le rapport ne doit pas annoncer une dotation qui n'a pas eu lieu"
        )

    async def test_le_msisdn_ne_depend_PAS_du_run(self) -> None:
        """Sans cette propriete le `GET` de `D-CLI-5` ne trouverait jamais rien,
        et le controle serait purement decoratif."""
        msisdns = []
        for run in (UUID(int=1), UUID(int=2)):
            ex = _executeur(
                mode=RunMode.REAL, nb_clients=20, pays_actifs=("CM",),
                ledger=FauxLedger(), clients=FauxClientService(),
                arbre=FauxArbre(_kiosques("CM")), run_id=run,
            )
            await ex.executer()
            msisdns.append({o["msisdn"] for o in ex._clients.onboardes})  # type: ignore[attr-defined]
        assert msisdns[0] == msisdns[1], (
            "deux runs du meme perimetre doivent produire les MEMES msisdn"
        )


    async def test_une_collision_DANS_le_run_rend_la_reservation_de_quota(self) -> None:
        """Defaut latent trouve par MUTATION le 12/08 : le chemin « deja
        consomme » appelait `ecarter()` sans `rendre()`, alors que
        `quota.reserver()` avait deja incremente. La cible se remplissait de
        clients inexistants — invisible a blanc, ou le registre est vide a chaque
        essai, donc ce chemin ne se declenchait jamais.

        On force ici de VRAIES collisions internes au run : le cache Faker replie
        les graines sur un vivier de 30 `client_id` pour une cible de 40, donc au
        moins dix tirages retombent sur un client deja reserve.
        """
        rapport = await _executeur(
            mode=RunMode.REAL,
            nb_clients=40,
            pays_actifs=("CM",),
            faker=FauxFaker(replier_sur=30),
            ledger=FauxLedger(),
            clients=FauxClientService(),
            arbre=FauxArbre(_kiosques("CM")),
        ).executer()

        quota = next(q for q in rapport.quotas if q.pays == "CM")
        assert "deja consomme" in quota.ecartes, (
            "le test ne prouve rien si aucune collision ne s'est produite"
        )
        assert quota.faits == len(rapport.crees), (
            "le quota doit compter le REEL : sans `rendre()` il compterait les "
            "collisions comme des clients crees"
        )
        assert quota.femmes + quota.hommes == len(rapport.crees)


class TestUC13Souscriptions:
    """`UC-13` — « 1 a 3 souscriptions a des produits Collecte ».

    TROIS FAITS MESURES, ET LE SERVEUR N'EN PORTE QU'UN
    ---------------------------------------------------
    - Le plafond n'est PAS porte : six produits attaches a un meme client sans
      le moindre rejet (09/08). `SOUSCRIPTIONS_MAX = 3` est a nous.
    - Le doublon EST refuse : `400 « A customer cannot subscribe to the same
      products twice »` — invariant qu'aucune de nos sources ne documentait.
    - La categorie n'est PAS verifiee (`OBS-CLI-CROSSCHECK-01`).
    """

    def _catalogue(self, categorie: str = "INDIVIDUAL") -> list[Any]:
        """Les trois COLLECT d'une categorie, un par PolicyType — le catalogue
        reel. Volontairement dans le DESORDRE, pour que le tri se voie."""
        return [
            ProduitSouscriptible(
                uuid4(), "DEMO_plastique", ProductType.COLLECT, categorie, "PRODUCT"
            ),
            ProduitSouscriptible(
                uuid4(), "DEMO_DAT 6 Mois", ProductType.COLLECT, categorie, "CASH_DAT"
            ),
            ProduitSouscriptible(
                uuid4(), "DEMO_Cotisation", ProductType.COLLECT, categorie, "CASH"
            ),
        ]

    def _paniers(self, nb: int = 400) -> list[list[Any]]:
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        catalogue = self._catalogue()
        return [
            ex._panier(catalogue, _compose_pour(_kiosques("CM")[0], seed=graine))
            for graine in range(1, nb + 1)
        ]

    def test_le_PREMIER_produit_est_TOUJOURS_le_CASH(self) -> None:
        """Le produit d'entree part a l'onboarding, `OnboardClientSchema` exigeant
        `product_id` des le premier appel. Mon premier jet tirait un
        `random.sample()` : il pouvait mettre « plastique » en premier et produire
        un client d'epargne dont l'unique produit est une collecte de dechets."""
        for panier in self._paniers(200):
            assert panier, "un client sans produit ne serait pas onboardable"
            assert panier[0].policy_type == "CASH", (
                f"produit d'entree {panier[0].nom} ({panier[0].policy_type}) — "
                "la cotisation est la porte d'entree, pas la collecte en nature"
            )

    def test_l_ordre_metier_est_respecte_dans_tout_le_panier(self) -> None:
        for panier in self._paniers(200):
            rangs = [ORDRE_SOUSCRIPTION.index(p.policy_type) for p in panier]
            assert rangs == sorted(rangs), [p.nom for p in panier]

    def test_jamais_de_doublon_le_serveur_le_refuserait(self) -> None:
        """`400 « A customer cannot subscribe to the same products twice »`."""
        for panier in self._paniers():
            identifiants = [p.product_id for p in panier]
            assert len(identifiants) == len(set(identifiants))

    def test_entre_UN_et_TROIS_jamais_au_dela(self) -> None:
        tailles = {len(p) for p in self._paniers()}
        assert tailles <= {1, 2, 3}, tailles
        assert tailles == {1, 2, 3}, (
            f"les trois tailles doivent apparaitre, sinon « 1 a 3 » n'est qu'un "
            f"chiffre unique deguise — obtenu {sorted(tailles)}"
        )

    def test_chaque_ligne_de_distribution_somme_a_UN(self) -> None:
        """Une ligne mal ajustee deplacerait la distribution en silence : le
        dernier palier absorberait le reste sans que rien ne le signale."""
        for segment, parts in PANIER_PAR_SEGMENT.items():
            assert abs(sum(parts) - 1.0) < 1e-9, f"{segment.value} : {sum(parts)}"
            assert len(parts) == SOUSCRIPTIONS_MAX

    def test_la_distribution_de_CHAQUE_segment_est_celle_qui_est_declaree(self) -> None:
        """`UC-13` pt 4 : « 1 a 3 produits Collecte SELON SON PROFIL SEGMENTE ».
        Les valeurs sont notre lecture du CDC — donc elles doivent se mesurer."""
        from collections import Counter

        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        catalogue = self._catalogue()
        kiosque = _kiosques("CM")[0]
        for segment, attendus in PANIER_PAR_SEGMENT.items():
            parts = Counter()
            for graine in range(1, 1201):
                compose = _compose_pour(kiosque, seed=graine)
                object.__setattr__(compose, "segment", segment)
                parts[len(ex._panier(catalogue, compose))] += 1
            for combien, attendu in enumerate(attendus, start=1):
                obtenu = parts[combien] / 1200
                assert abs(obtenu - attendu) < 0.05, (
                    f"{segment.value} · {combien} produit(s) : {obtenu:.1%} "
                    f"pour {attendu:.0%} declares"
                )

    def test_un_segment_plus_HAUT_prend_plus_de_produits(self) -> None:
        """La propriete metier, et celle que le CDC vise : un epargnant aise
        diversifie, un epargnant fragile a une cotisation et rien d'autre."""
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        catalogue = self._catalogue()
        kiosque = _kiosques("CM")[0]
        moyennes = []
        for segment in SEGMENTS_ANNEXE_E:
            tailles = []
            for graine in range(1, 601):
                compose = _compose_pour(kiosque, seed=graine)
                object.__setattr__(compose, "segment", segment)
                tailles.append(len(ex._panier(catalogue, compose)))
            moyennes.append(sum(tailles) / len(tailles))
        detail = dict(zip([s.value for s in SEGMENTS_ANNEXE_E], moyennes, strict=True))
        assert moyennes == sorted(moyennes), f"la moyenne doit croitre : {detail}"
        assert moyennes[-1] > moyennes[0] + 0.8, "l'ecart doit etre VISIBLE, pas symbolique"

    def test_le_panier_est_ANCRE_au_client_pas_au_run(self) -> None:
        """`CR-03` — sinon une reprise attacherait d'AUTRES produits au meme
        client, et `PUT /subscribe` n'a pas de `DELETE` : il finirait avec cinq
        produits pour un plafond de trois."""
        # SUR CINQUANTE CLIENTS, pas un seul : le panier est une TRANCHE d'une
        # liste ordonnee, donc deux runs peuvent coincider par hasard sur un
        # client isole. Le test de mutation du 12/08 l'a montre — il passait avec
        # l'ancrage au run remis.
        catalogue = self._catalogue()
        kiosque = _kiosques("CM")[0]
        a = _executeur(mode=RunMode.DRY_RUN, nb_clients=40, run_id=UUID(int=1))
        b = _executeur(mode=RunMode.DRY_RUN, nb_clients=40, run_id=UUID(int=999))
        for graine in range(1, 51):
            compose = _compose_pour(kiosque, seed=graine)
            assert [p.product_id for p in a._panier(catalogue, compose)] == [
                p.product_id for p in b._panier(catalogue, compose)
            ], f"le client {compose.msisdn} change de panier d'un run a l'autre"

    def test_un_CORPORATE_ne_recoit_que_des_produits_CORPORATE(self) -> None:
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        melange = self._catalogue("INDIVIDUAL") + self._catalogue("CORPORATE")
        compose = _compose_pour(_kiosques("CM")[0], seed=3)
        object.__setattr__(compose, "categorie", ClientCategory.CORPORATE)
        panier = ex._panier(melange, compose)
        assert panier
        assert all(p.categorie == "CORPORATE" for p in panier), [p.nom for p in panier]

    def test_un_policy_type_inconnu_ne_devient_JAMAIS_produit_d_entree(self) -> None:
        """Le serveur peut ne pas declarer le `PolicyType` — il vit dans
        `policy.type`, pas au premier niveau. Un tel produit reste souscriptible,
        mais jamais en porte d'entree."""
        ex = _executeur(mode=RunMode.DRY_RUN, nb_clients=40)
        catalogue = [
            ProduitSouscriptible(
                uuid4(), "DEMO_Sans policy", ProductType.COLLECT, "INDIVIDUAL", ""
            ),
            ProduitSouscriptible(
                uuid4(), "DEMO_Cotisation", ProductType.COLLECT, "INDIVIDUAL", "CASH"
            ),
        ]
        for graine in range(1, 60):
            panier = ex._panier(catalogue, _compose_pour(_kiosques("CM")[0], seed=graine))
            assert panier[0].policy_type == "CASH", panier[0].nom


class TestUC13Ecriture:
    async def test_les_2e_et_3e_produits_passent_par_PUT_subscribe(self) -> None:
        """`D-CLI-7` — `OnboardClientSchema` exige `product_id` des le premier
        appel, donc la 1re souscription est faite a l'onboarding ; les suivantes
        n'ont QUE ce chemin. Jusqu'au 12/08 le Loader s'arretait a la premiere :
        « 1 a 3 » etait toujours 1."""
        clients = FauxClientService()
        rapport = await _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, arbre=FauxArbre(_kiosques("CM")),
        ).executer()

        assert len(clients.onboardes) == 40
        assert clients.souscriptions, "aucun PUT /subscribe — UC-13 resterait a 1 produit"
        assert rapport.souscriptions == len(clients.souscriptions)
        total = len(rapport.crees) + rapport.souscriptions
        assert 40 < total <= 40 * SOUSCRIPTIONS_MAX
        for msisdn, _ in clients.souscriptions:
            assert msisdn in {o["msisdn"] for o in clients.onboardes}

    async def test_une_souscription_refusee_ALERTE_sans_annuler_le_client(self) -> None:
        """Le Client existe cote serveur, definitivement : aucun des trois
        services de la cascade n'expose de `DELETE`. Une souscription manquante
        degrade l'ecosysteme ; annuler le client detruirait une entite
        irreversible pour un motif secondaire."""
        clients = FauxClientService(refuser_souscriptions=True)
        rapport = await _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, arbre=FauxArbre(_kiosques("CM")),
        ).executer()

        assert len(rapport.crees) == 40, "les 40 clients existent malgre les refus"
        assert rapport.souscriptions == 0
        assert any("souscription" in a and "UC-13" in a for a in rapport.alertes)

    async def test_a_blanc_rien_n_est_souscrit_mais_tout_est_ANNONCE(self) -> None:
        """`D-01` — le rapport a blanc est « la derniere occasion de dire non »."""
        rapport = await _executeur(
            mode=RunMode.DRY_RUN, nb_clients=200, pays_actifs=("CM",),
            ledger=FauxLedger(), arbre=FauxArbre(_kiosques("CM")),
        ).executer()

        assert rapport.souscriptions == 0, "aucune ecriture a blanc"
        assert rapport.souscriptions_prevues > len(rapport.crees), (
            "le panier moyen doit depasser un produit par client"
        )
        assert 1.0 <= rapport.moyenne_souscriptions <= 3.0
        assert "Souscriptions UC-13" in rapport.resume()


class TestSegmentA02:
    """`A-02` — le `segment` emis a l'onboarding, recommandation appliquee.

    `EF-80` est inapplicable tel qu'ecrit : les deux champs de segment de Faker
    sont de FAMILLE B, et `behavior_segment` vaut 0.0 dans quatorze cas sur
    quinze. Nos 2000 clients viennent de la famille A, qui n'en porte aucun.

    Le Loader emettait donc `ANY` pour les 2000 — legitime, mais cela aplatit un
    axe de six valeurs. La strate vient des onze signaux `quick_win` que la
    famille A porte vraiment — l'axe de l'USAGE, distinct depuis `SD-5` de
    l'axe du REVENU qui fixe le solde initial.
    """

    def _faker(self, signaux: int, rang: int = 1) -> Any:
        """Un client de la famille A avec `signaux` signaux `quick_win` a 1.
        `rang` devient le `client_id` (`CM-IND-<rang>`) : c'est lui qui etale le
        solde DANS la strate, donc deux clients de meme strate en diffèrent."""
        return _tirage(
            "CM",
            seed=rang,
            quick_win={
                cle: (1 if i < signaux else 0)
                for i, cle in enumerate(CLES_QUICK_WIN_BINAIRES)
            },
        )

    def test_le_segment_est_MONOTONE_avec_les_signaux(self) -> None:
        """Un client plus actif ne peut pas tomber dans un segment plus bas.

        Jusqu'a `SD-5` ce test verifiait aussi la monotonie du SOLDE sur les
        memes signaux — propriete retiree A DESSEIN : le solde derive desormais
        du metier (profil de revenu), plus de l'equipement. Les deux axes sont
        distincts, et c'est documente dans `segment_client()`."""
        precedent_seg = -1
        for signaux in range(len(CLES_QUICK_WIN_BINAIRES) + 1):
            faker = self._faker(signaux, signaux + 1)
            rang = SEGMENTS_ANNEXE_E.index(segment_client(faker))
            assert rang >= precedent_seg, f"{signaux} signaux : segment en recul"
            precedent_seg = rang

    def test_les_cinq_strates_de_l_annexe_E_sont_toutes_atteignables(self) -> None:
        atteints = {
            segment_client(self._faker(n, n + 1))
            for n in range(len(CLES_QUICK_WIN_BINAIRES) + 1)
        }
        assert atteints == set(SEGMENTS_ANNEXE_E), (
            f"une strate inatteignable rendrait l'axe partiellement mort : {atteints}"
        )

    def test_jamais_ANY_ni_hors_enum(self) -> None:
        """`ANY` n'est pas une strate, c'est « pas de contrainte »."""
        for n in range(len(CLES_QUICK_WIN_BINAIRES) + 1):
            segment = segment_client(self._faker(n, n + 1))
            assert segment is not ClientSegment.ANY
            assert segment in SEGMENTS_ANNEXE_E

    def test_zero_et_maximum_de_signaux_ne_debordent_pas(self) -> None:
        """La projection `presents * 5 // (total + 1)` doit tenir aux deux bouts —
        un `IndexError` au maximum ferait tomber le client entier."""
        assert segment_client(self._faker(0)) is ClientSegment.VERY_LOW
        assert (
            segment_client(self._faker(len(CLES_QUICK_WIN_BINAIRES)))
            is ClientSegment.VERY_HIGH
        )

    def test_le_meme_client_rend_TOUJOURS_le_meme_segment(self) -> None:
        """`ENF-15`, et `CR-03` : une reprise ne doit pas changer le segment."""
        faker = self._faker(4, 42)
        assert segment_client(faker) is segment_client(faker)

    def test_le_segment_arrive_DANS_le_payload_envoye_au_serveur(self) -> None:
        """Un segment derive mais non transmis serait la seizieme occurrence du
        defaut recurrent : calcule, teste, coche, cable a rien."""
        from app.services.clients_composition import ancrer_sur_kiosque, composer

        faker = self._faker(len(CLES_QUICK_WIN_BINAIRES), 7)
        compose = composer(
            faker,
            ancrer_sur_kiosque(_kiosques("CM")[0], REFERENTIEL),
            Generateur(RUN, reference=date(2026, 8, 11)),
            REFERENTIEL,
            random.Random(7),  # noqa: S311
            jeune=True,
            segment=segment_client(faker),
        )
        assert compose.segment is ClientSegment.VERY_HIGH

    async def test_les_2000_clients_ne_sont_plus_TOUS_ANY(self) -> None:
        """La mesure qui justifie le changement : l'axe etait plat."""
        clients = FauxClientService()
        await _executeur(
            mode=RunMode.REAL, nb_clients=200, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, arbre=FauxArbre(_kiosques("CM")),
        ).executer()
        segments = {o["segment"] for o in clients.onboardes}
        assert len(segments) > 1, f"axe toujours plat : {segments}"
        assert "ANY" not in segments


class TestApresOnboardingRienNeLeve:
    """LE DEFAUT LE PLUS GRAVE DU 12/08, et il ne venait pas de `UC-13`.

    Mon panier n'a fait que le reveler : une exception IMPREVUE apres le POST
    d'onboarding remontait jusqu'a `asyncio.gather(return_exceptions=True)`, qui
    la comptait en ECHEC. La boucle rendait alors le quota ET liberait la
    reservation `D-FAKER-1` — donc elle RETIRAIT un client qui existait deja et en
    creait un SECOND. Sur client-service, identity-service et account-service,
    qui n'exposent aucun `DELETE`.

    Mesure au moment de la decouverte : **84 comptes credites pour une cible de
    40**. Le doublon n'etait pas theorique.

    Le POST d'onboarding est l'acte irreversible. Des qu'il a reussi, le client
    est un succes quoi qu'il advienne ensuite.
    """

    async def _run(self, arbre: Any, comptes: Any = None) -> tuple[Any, Any]:
        clients = FauxClientService()
        rapport = await _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, comptes=comptes,
            arbre=arbre,
        ).executer()
        return rapport, clients

    async def test_une_panne_du_rattachement_ne_cree_AUCUN_doublon(self) -> None:
        class ArbreQuiExplose(FauxArbre):
            async def ajouter_client(self, **_: Any) -> Any:
                raise RuntimeError("panne imprevue, pas une ValueError")

        rapport, clients = await self._run(ArbreQuiExplose(_kiosques("CM")))

        assert len(clients.onboardes) == 40, (
            f"{len(clients.onboardes)} onboardings pour une cible de 40 — chaque "
            "client en trop est IRREVERSIBLE"
        )
        assert len({o["msisdn"] for o in clients.onboardes}) == 40
        assert len(rapport.crees) == 40
        assert rapport.echoues == [], "un client cree n'est pas un echec"
        assert any("client CREE" in a and "DOUBLON" in a for a in rapport.alertes)

    async def test_une_panne_de_la_dotation_ne_cree_AUCUN_doublon(self) -> None:
        class ComptesQuiExplosent(FauxComptes):
            async def crediter(self, *_: Any, **__: Any) -> Any:
                raise RuntimeError("panne imprevue du service de comptes")

        rapport, clients = await self._run(
            FauxArbre(_kiosques("CM")), ComptesQuiExplosent()
        )

        assert len(clients.onboardes) == 40
        assert len(rapport.crees) == 40
        assert rapport.solde_dote == 0.0, "aucun solde confirme : rien ne doit etre compte"

    async def test_le_registre_reste_COHERENT_malgre_la_panne(self) -> None:
        """`D-FAKER-1` — un client Faker consomme ne doit pas etre libere sous
        pretexte qu'un enrichissement a echoue : il a bien produit une entite."""

        class ArbreQuiExplose(FauxArbre):
            async def ajouter_client(self, **_: Any) -> Any:
                raise RuntimeError("panne imprevue")

        ledger, clients = FauxLedger(), FauxClientService()
        await _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=ledger, clients=clients, arbre=ArbreQuiExplose(_kiosques("CM")),
        ).executer()

        assert len(ledger.confirmes) == 40, "chaque entite creee reste scellee"
        assert ledger.reserves == set()
        assert ledger.liberations == 0, (
            "aucune liberation : liberer ferait retirer un client existant du "
            "vivier et en faire creer un second"
        )

    async def test_le_quota_reste_EXACT_malgre_la_panne(self) -> None:
        class ArbreQuiExplose(FauxArbre):
            async def ajouter_client(self, **_: Any) -> Any:
                raise RuntimeError("panne imprevue")

        rapport, _ = await self._run(ArbreQuiExplose(_kiosques("CM")))
        quota = next(q for q in rapport.quotas if q.pays == "CM")
        assert quota.faits == 40 == len(rapport.crees)
        assert quota.corporate_faits == quota.cible_corporate
        assert quota.femmes == quota.cible_femmes


class TestProfilComportementalEF67:
    """`EF-67` + `EF-68` + `CR-09` — l'integration de la methodologie Duhamel.

    « Le Loader DOIT attribuer a **chaque client genere** un profil comportemental
    de remboursement parmi quatre valeurs » — pas a chaque APPROVED, pas a chaque
    pret. `D-PRET-0` : le Loader ne fait AUCUN pret ; le profil dit comment ce
    client REMBOURSERAIT, il ne rembourse rien.
    """

    async def _run(self, cible: int = 1000) -> Any:
        return await _executeur(
            mode=RunMode.REAL, nb_clients=cible, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=FauxClientService(),
            arbre=FauxArbre(_kiosques("CM")),
        ).executer()

    def test_les_cibles_somment_EXACTEMENT_a_la_cible_du_pays(self) -> None:
        """Sans cela, le dernier client ne trouverait aucun quota ouvert. Les
        poids du CDC sont des entiers dont la somme fait 100, mais arrondir
        chacun separement peut perdre une unite."""
        for cible in (1, 7, 100, 333, 500, 1000, 2000):
            quota = QuotaPays(pays="CM", cible=cible, statique=STATIQUE)
            assert sum(quota.cible_profils.values()) == cible, cible

    async def test_CR_09_la_distribution_est_EXACTE(self) -> None:
        """`CR-09` : « bon payeur entre 47 et 53 %, retard 22-28, defaut partiel
        10-16, defaut total 9-15 ». Tenu par QUOTA, pas par calibration.

        Un tirage pondere simple donnait `BON_PAYEUR` a 54,2 % — hors borne. La
        cause n'etait pas un defaut de code mais l'arithmetique de DEUX exigences
        qui se composent : `EF-22` fait une population aux deux tiers feminine, et
        `EF-68` donne aux femmes `BON_PAYEUR x 1,22`.
        """
        rapport = await self._run()
        quota = rapport.quotas[0]
        total = sum(quota.profils_faits.values())
        assert total == quota.cible
        for nom, attendu in PROFILS_COMPORTEMENTAUX.items():
            obtenu = quota.profils_faits[nom] / total * 100
            assert abs(obtenu - attendu) <= TOLERANCE_DISTRIBUTION_POINTS, (
                f"{nom} : {obtenu:.1f} % pour {attendu} % — hors des bornes CR-09"
            )

    async def test_EF_68_les_femmes_obtiennent_de_MEILLEURS_profils(self) -> None:
        """Annexe D.2 : « Genre feminin -> renforce le profil bon payeur, reduit
        le defaut total ». Le quota ne doit pas ECRASER cette discrimination.

        Une premiere version le faisait : par preference stricte, `BON_PAYEUR`
        restait premier pour presque tout le monde (les coefficients vont de x0,72
        a x1,22 face a des poids 50/25/13/12), donc l'ordre ne changeait jamais et
        le quota degenerait en « premier arrive, premier servi ». Mesure : moins de
        25 ans et 25 ans et plus obtenaient RIGOUREUSEMENT le meme 50,0 %.
        """
        vus = self._capturer(await self._run())
        femmes = [p for femme, _, p in vus if femme]
        hommes = [p for femme, _, p in vus if not femme]
        assert _part(femmes, "BON_PAYEUR") > _part(hommes, "BON_PAYEUR")
        assert _part(femmes, "DEFAUT_TOTAL") < _part(hommes, "DEFAUT_TOTAL")

    async def test_EF_68_les_moins_de_25_ans_defaillent_DAVANTAGE(self) -> None:
        """Annexe D.2 : « Age inferieur a 22 ans -> renforce le defaut total » et
        « Age entre 35 et 65 ans -> renforce le profil bon payeur ».

        Ce test a echoue dans les DEUX sens avant d'etre juste : d'abord inverse
        (83,3 % de BON_PAYEUR chez les jeunes, a cause du quota d'age servi en
        BLOC), puis nul (50,0 % partout, a cause de la preference stricte).
        """
        vus = self._capturer(await self._run())
        jeunes = [p for _, jeune, p in vus if jeune]
        ages = [p for _, jeune, p in vus if not jeune]
        assert _part(jeunes, "BON_PAYEUR") < _part(ages, "BON_PAYEUR"), (
            "un moins de 25 ans ne doit pas etre MEILLEUR payeur qu'un client "
            "de 35-65 ans — l'Annexe D.2 dit l'inverse"
        )

    def test_le_profil_est_ANCRE_au_client_pas_au_run(self) -> None:
        """`CR-03` — sinon une reprise changerait le profil du meme client, et
        `CR-09` mesurerait une distribution differente a chaque run."""
        tirage = _tirage("CM", seed=7)
        a = QuotaPays(pays="CM", cible=1000, statique=STATIQUE, reference_age=date(2026, 8, 12))
        b = QuotaPays(pays="CM", cible=1000, statique=STATIQUE, reference_age=date(2026, 8, 12))
        assert a.reserver(tirage).profil == b.reserver(tirage).profil  # type: ignore[union-attr]

    def test_aucun_profil_hors_des_quatre_valeurs_officielles(self) -> None:
        quota = QuotaPays(pays="CM", cible=200, statique=STATIQUE)
        for seed in range(400):
            r = quota.reserver(_tirage(genre="WOMAN" if seed % 3 else "MAN", seed=seed))
            if r is not None:
                assert r.profil in PROFILS_COMPORTEMENTAUX, r.profil

    def test_rendre_defait_AUSSI_le_profil(self) -> None:
        """Sans cela, un client echoue laisserait son profil compte, et `CR-09`
        annoncerait une distribution que la base ne porte pas."""
        quota = QuotaPays(pays="CM", cible=100, statique=STATIQUE)
        reservation = quota.reserver(_tirage("CM", seed=1))
        assert reservation is not None
        avant = dict(quota.profils_faits)
        quota.rendre(reservation)
        assert quota.profils_faits[reservation.profil] == avant[reservation.profil] - 1

    async def test_le_profil_ARRIVE_sur_le_client_compose(self) -> None:
        """Un profil calcule mais non porte serait la dix-septieme occurrence du
        defaut recurrent : ecrit, teste, coche, cable a rien."""
        ex = _executeur(
            mode=RunMode.REAL, nb_clients=40, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=FauxClientService(),
            arbre=FauxArbre(_kiosques("CM")),
        )
        vus: list[str | None] = []
        origine = ex._sceller

        async def espion(cid: str, fiche: Any, k: Any, compose: Any, rap: Any) -> None:
            vus.append(compose.profil_comportemental)
            await origine(cid, fiche, k, compose, rap)

        ex._sceller = espion  # type: ignore[method-assign]
        await ex.executer()
        assert len(vus) == 40
        assert all(p in PROFILS_COMPORTEMENTAUX for p in vus), vus

    @staticmethod
    def _capturer(_rapport: Any) -> list[tuple[bool, bool, str]]:
        """Rejoue les reservations pour lire genre / age / profil ensemble."""
        quota = QuotaPays(pays="CM", cible=1000, statique=STATIQUE, reference_age=date(2026, 8, 12))
        vus = []
        for seed in range(3000):
            if quota.faits >= quota.cible:
                break
            r = quota.reserver(
                _tirage(genre="WOMAN" if seed % 3 else "MAN", business=seed % 5 == 0, seed=seed)
            )
            if r is not None:
                vus.append((r.femme, r.jeune, r.profil))
        return vus


def _part(profils: list[str], nom: str) -> float:
    return profils.count(nom) / (len(profils) or 1)


class TestOccupationsCableesSD3:
    """`SD-3` au niveau de l'EXECUTEUR — le cablage, pas la fonction.

    Trouve par MUTATION le 12/08 : passer `personne_morale=False` dans
    `_creer` ne faisait echouer AUCUN test, parce que tous appelaient
    `occupation_reelle()` directement. Une garantie testee sur la fonction et non
    sur son appel n'est pas une garantie.
    """

    async def _onboardes(self, cible: int = 500) -> list[dict[str, Any]]:
        clients = FauxClientService()
        await _executeur(
            mode=RunMode.REAL, nb_clients=cible, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, arbre=FauxArbre(_kiosques("CM")),
        ).executer()
        return clients.onboardes

    @staticmethod
    def _par_categorie(onboardes: list[dict[str, Any]]) -> dict[str, list[str]]:
        par: dict[str, list[str]] = {"INDIVIDUAL": [], "CORPORATE": []}
        for o in onboardes:
            cat = o["category"]
            par[cat.value if hasattr(cat, "value") else str(cat)].append(
                o["identity"]["occupation"]
            )
        return par

    async def test_aucun_CORPORATE_n_est_SALARIE(self) -> None:
        """LA mutation non attrapee. Mesure du 12/08 avant la regle : 47 CORPORATE
        sur 100 portaient un metier de salarie ou de journalier."""
        par = self._par_categorie(await self._onboardes())
        salaries = [
            m
            for m in par["CORPORATE"]
            if STATIQUE.profil_de_la_profession(m).nom == "bank_stable"
        ]
        assert salaries == [], (
            f"{len(salaries)} personnes morales salariees : {salaries[:4]} — "
            "le fichier definit `bank_stable` comme « salary, pension or "
            "institutional payroll », ce qu'une entreprise ne touche pas"
        )

    async def test_les_INDIVIDUAL_ne_sont_plus_TOUS_Commercant(self) -> None:
        """Le defaut mesure : 400 clients, UNE occupation distincte."""
        par = self._par_categorie(await self._onboardes())
        individuels = par["INDIVIDUAL"]
        assert len(set(individuels)) > 150, (
            f"{len(set(individuels))} metiers distincts pour {len(individuels)} "
            "clients — la fiche que le bailleur lit en premier"
        )
        assert "Commercant" not in individuels

    async def test_chaque_client_porte_un_metier_DU_REFERENTIEL(self) -> None:
        """`occupation` est un champ libre de 200 caracteres qu'aucun service ne
        valide. La seule barriere est la notre."""
        for o in await self._onboardes(200):
            metier = o["identity"]["occupation"]
            assert metier in STATIQUE.professions, metier

    async def test_EF_24_tient_toujours(self) -> None:
        """Le quota agricole ne doit pas avoir bouge : la famille reste decidee
        par le moteur de quotas, seule la profession concrete change."""
        clients = FauxClientService()
        rapport = await _executeur(
            mode=RunMode.REAL, nb_clients=500, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, arbre=FauxArbre(_kiosques("CM")),
        ).executer()
        quota = rapport.quotas[0]
        assert quota.agricoles == quota.cible_agricoles
        assert quota.corporate_faits == quota.cible_corporate

    async def test_EF_24_est_VISIBLE_sur_les_fiches(self) -> None:
        """Trouve par MUTATION le 13/08 : ne plus passer `reservation.secteur` a
        `occupation_reelle` ne faisait echouer AUCUN test. Le quota agricole
        restait exact au rapport — mais plus un seul CORPORATE ne portait un
        metier agricole. `EF-24` aurait ete tenu en METADONNEE et invisible sur
        les fiches, celles que le bailleur lit.

        Le compte des metiers agricoles parmi les CORPORATE doit EGALER le quota :
        les quatre familles sont disjointes, donc un CORPORATE hors AGRICULTURE ne
        peut pas porter un metier agricole par accident."""
        clients = FauxClientService()
        rapport = await _executeur(
            mode=RunMode.REAL, nb_clients=500, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, arbre=FauxArbre(_kiosques("CM")),
        ).executer()
        agricoles = set(
            STATIQUE.professions_des_groupes(GROUPES_PAR_FAMILLE_CDC["AGRICULTURE"])
        )
        par = self._par_categorie(clients.onboardes)
        portes = [m for m in par["CORPORATE"] if m in agricoles]
        assert len(portes) == rapport.quotas[0].cible_agricoles, (
            f"{len(portes)} CORPORATE portent un metier agricole pour un quota "
            f"de {rapport.quotas[0].cible_agricoles} — EF-24 n'est plus visible"
        )


class TestSoldeCableSD5:
    """`SD-5` au niveau de l'EXECUTEUR — le cablage du solde, pas la fonction.

    Meme lecon que `SD-3` : une garantie testee sur la fonction et non sur son
    appel n'est pas une garantie. Le solde est calcule a DEUX endroits — le
    rapport a blanc dans `_creer` (via `reservation.occupation`) et le depot
    reel dans `_doter` (via `compose.identite.occupation`). Ces trois tests
    verrouillent : leur egalite (`D-01`), l'ancrage au client (`CR-03`), et le
    lien metier -> montant (le coeur du lot).
    """

    async def test_D_01_le_DRY_RUN_annonce_EXACTEMENT_ce_que_le_REAL_depose(
        self,
    ) -> None:
        """« La derniere occasion de dire non » n'en est une que si le rapport a
        blanc dit VRAI. Meme perimetre : la somme annoncee a blanc doit egaler
        la somme des montants REELLEMENT demandes en credit — au centime.

        Ce test attrape toute divergence entre les deux chemins de calcul :
        une occupation lue differemment, un arrondi different, un ancrage
        different."""
        rapport_blanc = await _executeur(
            mode=RunMode.DRY_RUN, nb_clients=200, pays_actifs=("CM",),
            ledger=FauxLedger(), arbre=FauxArbre(),
        ).executer()

        comptes = FauxComptes()
        await _executeur(
            mode=RunMode.REAL, nb_clients=200, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=FauxClientService(), comptes=comptes,
            arbre=FauxArbre(_kiosques("CM")),
        ).executer()
        demande_reel = sum(p["amount"] for p in comptes.credits)

        assert rapport_blanc.solde_dote == pytest.approx(demande_reel), (
            f"a blanc {rapport_blanc.solde_dote:.2f} != reel {demande_reel:.2f} — "
            "le rapport a blanc ment, D-01 est mort"
        )

    async def test_CR_03_le_meme_perimetre_redonne_les_MEMES_montants(self) -> None:
        """Deux runs REAL, deux `run_id` differents, meme perimetre : chaque
        client doit recevoir LE MEME solde. Un montant ancre au run changerait
        a la reprise — et un compte sans DELETE garderait la trace du mensonge."""
        montants: list[list[float]] = []
        for run in (UUID(int=7001), UUID(int=7002)):
            comptes = FauxComptes()
            await _executeur(
                mode=RunMode.REAL, run_id=run, nb_clients=150, pays_actifs=("CM",),
                ledger=FauxLedger(), clients=FauxClientService(), comptes=comptes,
                arbre=FauxArbre(_kiosques("CM")),
            ).executer()
            montants.append(sorted(p["amount"] for p in comptes.credits))
        assert montants[0] == montants[1]

    async def test_le_montant_SUIT_le_metier_du_client(self) -> None:
        """LE coeur du lot : un salaire stable dote mieux qu'un revenu agricole
        saisonnier — EN MEDIANE, dans les montants REELLEMENT credites.

        Jointure EXACTE credit -> fiche -> onboarding : le credit porte le
        `dest_account_id`, la fiche relie ce compte a son `msisdn`, et le
        msisdn — unique par `INV-09` — retrouve l'occupation onboardee. (La
        jointure par NOM a ete essayee et jetee : le vivier de patronymes du
        faux Faker rend les homonymes majoritaires.) Si `_doter` cessait de
        lire la VRAIE occupation, les deux medianes convergeraient."""
        clients = FauxClientService()
        comptes = FauxComptes()
        await _executeur(
            mode=RunMode.REAL, nb_clients=500, pays_actifs=("CM",),
            ledger=FauxLedger(), clients=clients, comptes=comptes,
            arbre=FauxArbre(_kiosques("CM")),
        ).executer()

        msisdn_par_compte = {f["account_id"]: f["msisdn"] for f in clients.fiches}
        occupation_par_msisdn = {
            o["msisdn"]: o["identity"]["occupation"] for o in clients.onboardes
        }
        par_profil: dict[str, list[float]] = {}
        for credit in comptes.credits:
            msisdn = msisdn_par_compte[credit["dest_account_id"]]
            occupation = occupation_par_msisdn[msisdn]
            profil = STATIQUE.profil_de_la_profession(occupation).nom
            par_profil.setdefault(profil, []).append(credit["amount"])

        stables = sorted(par_profil.get("bank_stable", []))
        saisonniers = sorted(par_profil.get("agri_seasonal", []))
        assert len(stables) >= 30, f"{len(stables)} salaries joints — jointure cassee ?"
        assert len(saisonniers) >= 30, f"{len(saisonniers)} agricoles joints"
        assert stables[len(stables) // 2] > saisonniers[len(saisonniers) // 2], (
            "la mediane des salaries ne depasse pas celle des agricoles — "
            "le metier n'atteint plus le montant depose"
        )
