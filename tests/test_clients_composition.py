"""
tests/test_clients_composition.py
=================================
La couture Faker -> composeur — `UC-12`, `EF-20` a `EF-27`.

**Ce que ces tests protegent** : qu'aucun client irreversible ne naisse avec un
champ faux. Trois services n'exposent aucun `DELETE` : un client mal compose est
definitif. Mieux vaut un client de moins qu'un client faux.

Le test central est `test_la_geographie_est_toujours_coherente...` : il rejoue sur
les quatre pays le defaut « region Adamaoua, ville Yaounde » du 10/08.
"""

# ruff: noqa: S311 — `random.Random` porte ici la REPRODUCTIBILITE (`ENF-15`),
# jamais un secret. Meme justification que `generateur.py` : un tirage
# cryptographique rendrait deux runs de meme `run_id` differents.

from __future__ import annotations

import random
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.clients.contracts import (
    ClientCategory,
    ClientSegment,
    IdentityGender,
    Language,
    SubscriptionChannel,
)
from app.clients.faker_service import ClientFaker, CompanyFaker, IdentiteFaker
from app.core.cdc import PAYS_CIBLES
from app.core.invariants import GENRES_EMIS, InvariantViole
from app.models.domain import OrgHierarchyNode
from app.models.enums import NiveauOrganisation
from app.services.clients_composition import (
    OCCUPATIONS_PAR_SECTEUR,
    AncrageGeographique,
    CompositionImpossible,
    ancrer_sur_kiosque,
    composer,
    occupation_du_secteur,
)
from app.services.generateur import Generateur
from app.services.geographie import charger_referentiel

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
REFERENTIEL = charger_referentiel(CLASSEUR)
RUN = uuid4()


def _generateur() -> Generateur:
    return Generateur(RUN, reference=date(2026, 8, 11))


def _kiosque(pays: str, n: int = 0) -> OrgHierarchyNode:
    """Un Kiosque tel que le module DEPOSITAIRES en produit."""
    villes = REFERENTIEL.villes_porteuses_de_quartiers(pays)
    ville = villes[n % len(villes)]
    quartiers = REFERENTIEL.quartiers_de_ville(ville.city_id)
    quartier = quartiers[n % len(quartiers)]
    return OrgHierarchyNode(
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


def _faker(
    pays: str = "CM",
    *,
    genre: str | None = "WOMAN",
    business: bool = False,
    smartphone: int = 1,
    prenom: str | None = "Ines",
    nom: str | None = "Tamadou",
    devise: str = "XAF",
) -> ClientFaker:
    company = (
        CompanyFaker(
            identifiant="cmp_1",
            nom_placeholder=f"Test Business {pays} 748",
            type_juridique="SARL",
            secteurs=("Recycling", "AR"),
        )
        if business
        else None
    )
    return ClientFaker(
        client_id=f"{pays}-{'BIZ' if business else 'IND'}-1",
        pays=pays,
        devise=devise,
        categorie="Business" if business else "Individual",
        msisdn=f"+{REFERENTIEL.indicatif(pays)}38101955",
        prenom=prenom,
        nom=nom,
        nom_complet=f"{prenom} {nom}",
        genre=genre,
        identite=IdentiteFaker("CNI", "483502292668444", date(2020, 4, 23), date(2030, 4, 21)),
        company=company,
        quick_win={"IS_SMARTPHONE_USER": smartphone},
        seed=7,
    )


def _composer(faker: ClientFaker, pays_kiosque: str | None = None, **kwargs: Any) -> Any:
    ancrage = ancrer_sur_kiosque(_kiosque(pays_kiosque or faker.pays), REFERENTIEL)
    kwargs.setdefault("jeune", True)
    alea = random.Random(1)
    return composer(faker, ancrage, _generateur(), REFERENTIEL, alea, **kwargs)


class TestLaGeographieDeriveDuKiosque:
    """`EF-26` — et la coherence devient structurelle au lieu d'etre controlee."""

    @pytest.mark.parametrize("pays", PAYS_CIBLES)
    def test_la_geographie_est_toujours_coherente_dans_les_quatre_pays(self, pays: str) -> None:
        """Le defaut du 10/08 : « region Adamaoua, ville Yaounde » — deux champs
        corrects, une combinaison qui n'existe pas. En derivant du Kiosque, elle
        devient impossible a ECRIRE."""
        ancrage = ancrer_sur_kiosque(_kiosque(pays), REFERENTIEL)
        quartier = REFERENTIEL.quartier(ancrage.district_id)
        assert quartier is not None
        ville = REFERENTIEL.ville(quartier.city_id)
        assert ville is not None and ville.name == ancrage.ville
        region = REFERENTIEL.region(ville.region_id)
        assert region is not None and region.name == ancrage.region
        assert ancrage.pays == pays, "le pays vient de la VILLE — le referentiel fait foi"

    @pytest.mark.parametrize("pays", PAYS_CIBLES)
    def test_les_coordonnees_gps_de_la_ville_suivent(self, pays: str) -> None:
        """`EF-03` — « coordonnees GPS lorsqu'elles sont disponibles ». Elles
        viennent en prime de la derivation, sans tirage supplementaire."""
        ancrage = ancrer_sur_kiosque(_kiosque(pays), REFERENTIEL)
        quartier = REFERENTIEL.quartier(ancrage.district_id)
        assert quartier is not None
        ville = REFERENTIEL.ville(quartier.city_id)
        assert ville is not None
        assert (ancrage.latitude, ancrage.longitude) == (ville.latitude, ville.longitude)

    def test_un_kiosque_sans_district_est_refuse(self) -> None:
        kiosque = _kiosque("CM").model_copy(update={"district_id": None})
        with pytest.raises(CompositionImpossible, match="EF-26"):
            ancrer_sur_kiosque(kiosque, REFERENTIEL)

    def test_un_district_inconnu_du_referentiel_est_refuse(self) -> None:
        """Trou de DONNEES, pas regle metier — `EF-04` prevoit d'enrichir le
        referentiel, et c'est la seule vraie reponse."""
        kiosque = _kiosque("CM").model_copy(update={"district_id": "CM-NULLE-PART"})
        with pytest.raises(CompositionImpossible, match="EF-04"):
            ancrer_sur_kiosque(kiosque, REFERENTIEL)


class TestLeRattachementAuBonPays:
    def test_un_client_ne_peut_pas_etre_rattache_au_kiosque_d_un_autre_pays(self) -> None:
        """« Je ne veux pas voir Yaounde dans une region du Senegal. » Les deux
        champs seraient valides ; la combinaison n'existerait pas."""
        with pytest.raises(CompositionImpossible, match="EF-26"):
            _composer(_faker("CM"), pays_kiosque="SN")

    @pytest.mark.parametrize("pays", ["CM", "CI", "BF"])
    def test_le_meme_pays_passe(self, pays: str) -> None:
        assert _composer(_faker(pays, devise="")).ancrage.pays == pays


class TestLeGenre:
    """`D-IDN-1` : le serveur accepte n'importe quelle chaine. Nous sommes le
    seul filtre du systeme."""

    @pytest.mark.parametrize(
        ("faker_genre", "attendu"),
        [
            ("WOMAN", IdentityGender.FEMALE),
            ("MAN", IdentityGender.MALE),
            ("man", IdentityGender.MALE),
        ],
    )
    def test_la_traduction_est_appliquee(
        self, faker_genre: str, attendu: IdentityGender
    ) -> None:
        assert _composer(_faker(genre=faker_genre)).identite.gender == attendu.value

    @pytest.mark.parametrize("inconnu", ["OTHER", "peu importe", "", None, "F", "FEMALE_X"])
    def test_un_genre_hors_table_est_refuse_bruyamment(self, inconnu: str | None) -> None:
        with pytest.raises(CompositionImpossible, match="D-IDN-1"):
            _composer(_faker(genre=inconnu))

    def test_le_genre_emis_est_toujours_dans_GENRES_EMIS(self) -> None:
        """`IdentityGender` porte aussi `ANY` — une personne physique n'en a pas.
        La table de traduction ne peut jamais y conduire."""
        for genre in ("WOMAN", "MAN"):
            assert _composer(_faker(genre=genre)).identite.gender in GENRES_EMIS
        assert IdentityGender.ANY.value not in GENRES_EMIS


class TestLeMsisdn:
    """Tranche le 09/08 : aucun numero Faker n'est attribuable a un operateur."""

    @pytest.mark.parametrize("pays", ["CM", "CI", "BF"])
    def test_le_msisdn_emis_est_le_NOTRE_et_il_est_valide(self, pays: str) -> None:
        compose = _composer(_faker(pays, devise=""))
        assert compose.msisdn != compose.msisdn_faker
        operateur = REFERENTIEL.operateur_du_msisdn(compose.msisdn, pays)
        assert operateur is not None, f"EF-27 viole : {compose.msisdn} sans operateur"
        assert compose.telco == operateur.short_name

    @pytest.mark.parametrize("pays", ["CM", "CI", "BF"])
    def test_le_numero_faker_n_est_jamais_attribuable(self, pays: str) -> None:
        """La mesure elle-meme, figee en test : si Faker corrige un jour son plan
        de numerotation, ce test le dira."""
        faker = _faker(pays, devise="")
        assert faker.msisdn is not None
        assert REFERENTIEL.operateur_du_msisdn(faker.msisdn.lstrip("+"), pays) is None

    def test_le_numero_faker_reste_conserve_pour_la_tracabilite(self) -> None:
        compose = _composer(_faker("CM"))
        assert compose.msisdn_faker is not None
        assert compose.faker_client_id == "CM-IND-1"

    def test_identity_phone_est_STRICTEMENT_egal_au_msisdn(self) -> None:
        """`D-CLI-8` — sinon HTTP 400 « Identity phone field must match msisdn »,
        2000 fois."""
        compose = _composer(_faker("CM"))
        assert compose.identite.phone == compose.msisdn


class TestLaDeviseSuitLePays:
    """`D-CLI-9` — `currency` n'est validee NULLE PART et atterrit telle quelle
    dans le compte CHECKING. C'est ainsi qu'un compte reel a fini en `ANY`."""

    @pytest.mark.parametrize(("pays", "attendue"), [("CM", "XAF"), ("CI", "XOF"), ("BF", "XOF")])
    def test_la_zone_monetaire_commande(self, pays: str, attendue: str) -> None:
        assert _composer(_faker(pays, devise="")).devise == attendue

    def test_la_devise_de_faker_est_IGNOREE_meme_quand_elle_est_juste(self) -> None:
        """L'accepter de Faker serait accepter qu'il decide un jour autrement."""
        assert _composer(_faker("CM", devise="XOF")).devise == "XAF"
        assert _composer(_faker("CM", devise="EUR")).devise == "XAF"
        assert _composer(_faker("CM", devise="ANY")).devise == "XAF"


class TestLeCanalEtLeSegment:
    @pytest.mark.parametrize(
        ("smartphone", "attendu"),
        [(1, SubscriptionChannel.MOBILE), (0, SubscriptionChannel.USSD)],
    )
    def test_le_canal_vient_du_flag_smartphone_mesure(
        self, smartphone: int, attendu: SubscriptionChannel
    ) -> None:
        assert _composer(_faker(smartphone=smartphone)).canal is attendu

    def test_OFFICE_n_est_jamais_emis(self) -> None:
        """Aucune matiere ne le justifie ; l'attribuer au hasard serait
        l'invention arbitraire que la strategie de nommage interdit."""
        for smartphone in (0, 1):
            assert _composer(_faker(smartphone=smartphone)).canal is not SubscriptionChannel.OFFICE

    def test_le_segment_est_ANY(self) -> None:
        """La famille A ne porte AUCUNE donnee de scoring : `EF-80` n'est pas
        applicable tel qu'ecrit a cette population."""
        assert _composer(_faker()).segment is ClientSegment.ANY

    def test_la_langue_est_le_francais(self) -> None:
        assert _composer(_faker()).langue is Language.FR


class TestLOccupationEtLaTaxonomieEF24:
    def test_un_libelle_de_secteur_faker_n_est_JAMAIS_emis_comme_occupation(self) -> None:
        """`Recycling`, `Shipping`, `3DPrinting` sont des SECTEURS en anglais.
        Servis tels quels, ils produisaient « occupation: 3DPrinting » dans un
        ecosysteme francophone."""
        compose = _composer(_faker(business=True))
        assert compose.identite.occupation != "Recycling"
        assert compose.secteur_faker == "Recycling", "conserve en TRACE, jamais emis"

    @pytest.mark.parametrize("famille", sorted(OCCUPATIONS_PAR_SECTEUR))
    def test_les_quatre_familles_du_CDC_rendent_un_metier_francophone(
        self, famille: str
    ) -> None:
        metier = occupation_du_secteur(famille, random.Random(3))
        assert metier in OCCUPATIONS_PAR_SECTEUR[famille]

    def test_la_taxonomie_porte_exactement_les_familles_de_EF24(self) -> None:
        """« 20 % au secteur agricole ; les 80 % restants aux secteurs
        transports, commerce et services. » Quatre familles, pas une liste
        ouverte."""
        assert set(OCCUPATIONS_PAR_SECTEUR) == {
            "AGRICULTURE",
            "TRANSPORTS",
            "COMMERCE",
            "SERVICES",
        }

    @pytest.mark.parametrize("hors", ["Recycling", "Printing", "AGRO", ""])
    def test_une_famille_hors_taxonomie_est_refusee(self, hors: str) -> None:
        with pytest.raises(CompositionImpossible, match="EF-24"):
            occupation_du_secteur(hors, random.Random(1))

    def test_l_occupation_imposee_par_le_quota_est_respectee(self) -> None:
        compose = _composer(_faker(business=True), occupation_imposee="Producteur de cacao")
        assert compose.identite.occupation == "Producteur de cacao"


class TestLIdentiteComplete:
    """`D-IDN-2` — le contrat declare les champs d'adresse optionnels et le
    serveur les persiste a `null`. Le Loader les remplit TOUJOURS."""

    def test_les_cinq_champs_d_adresse_sont_renseignes(self) -> None:
        adresse = _composer(_faker()).identite.adresse
        for champ in ("address_line_1", "street_name", "city", "region", "country"):
            assert getattr(adresse, champ), f"{champ} vide — D-IDN-2"

    def test_la_nationalite_est_un_code_ISO_alpha2(self) -> None:
        """« Cameroun » rendait HTTP 422 « nationality must be a valid ISO
        3166-1 alpha-2 country code »."""
        identite = _composer(_faker("CM")).identite
        assert identite.nationality == "CM"

    def test_le_numero_de_piece_est_alphanumerique_majuscules(self) -> None:
        """`D-CLI-3` — un underscore ou un tiret provoque un HTTP 400."""
        numero = _composer(_faker()).identite.id_number
        assert numero.isalnum() and numero == numero.upper()

    def test_la_piece_porte_toujours_une_date_d_expiration(self) -> None:
        """`D-CLI-2` — son absence fait planter la cascade en 400
        « 'NoneType' object has no attribute 'isoformat' »."""
        assert _composer(_faker()).identite.id_expire_on is not None

    def test_la_ville_de_delivrance_est_celle_de_residence(self) -> None:
        """« Une piece senegalaise ne peut plus etre delivree a Douala. »"""
        compose = _composer(_faker("CM"))
        assert compose.identite.id_place.lower() == compose.ancrage.ville.lower()

    @pytest.mark.parametrize(("prenom", "nom"), [(None, "Tamadou"), ("Ines", None), (None, None)])
    def test_un_client_sans_nom_est_refuse(self, prenom: str | None, nom: str | None) -> None:
        """Une identite KYC creuse, et identity-service n'expose aucun DELETE."""
        with pytest.raises(CompositionImpossible, match="DELETE"):
            _composer(_faker(prenom=prenom, nom=nom))


class TestEF22EtLaReproductibilite:
    @pytest.mark.parametrize("jeune", [True, False])
    def test_le_drapeau_jeune_est_relu_depuis_la_date_reellement_composee(
        self, jeune: bool
    ) -> None:
        """`EF-22` — la propriete relit la date de naissance, jamais l'intention.
        Un quota se verifie sur ce qui a ete ecrit."""
        assert _composer(_faker(), jeune=jeune).jeune is jeune

    def test_deux_compositions_du_meme_run_et_du_meme_seed_sont_identiques(self) -> None:
        """`ENF-15` — « deux executions avec les memes parametres et le meme
        run_id DOIVENT produire strictement le meme ecosysteme »."""
        faker = _faker("CM")
        ancrage = ancrer_sur_kiosque(_kiosque("CM"), REFERENTIEL)
        a = composer(faker, ancrage, _generateur(), REFERENTIEL, random.Random(9), jeune=True)
        b = composer(faker, ancrage, _generateur(), REFERENTIEL, random.Random(9), jeune=True)
        assert a.msisdn == b.msisdn
        assert a.identite.date_of_birth == b.identite.date_of_birth
        assert a.identite.id_number == b.identite.id_number
        assert a.identite.email == b.identite.email

    def test_la_categorie_suit_la_categorie_faker(self) -> None:
        """`EF-23` — 80 % Individual / 20 % Corporate, seul filtre reel de Faker."""
        assert _composer(_faker(business=False)).categorie is ClientCategory.INDIVIDUAL
        assert _composer(_faker(business=True)).categorie is ClientCategory.CORPORATE


class TestLesGarantiesDeStructure:
    def test_le_client_compose_est_immuable(self) -> None:
        compose = _composer(_faker())
        with pytest.raises(AttributeError):
            compose.msisdn = "autre"  # type: ignore[misc]

    def test_l_ancrage_est_immuable(self) -> None:
        ancrage = ancrer_sur_kiosque(_kiosque("CM"), REFERENTIEL)
        with pytest.raises(AttributeError):
            ancrage.ville = "Nulle part"  # type: ignore[misc]

    def test_l_ancrage_porte_l_identifiant_du_kiosque(self) -> None:
        """`EF-26` doit rester tracable jusqu'a `org_hierarchy`."""
        kiosque = _kiosque("CM")
        ancrage = ancrer_sur_kiosque(kiosque, REFERENTIEL)
        assert ancrage.kiosque_id == kiosque.id
        assert isinstance(ancrage, AncrageGeographique)

    def test_une_devise_incoherente_au_classeur_leverait_un_invariant(self) -> None:
        """Garde-fou du garde-fou : `valider_devise_pays` confronte le code aux
        unions monetaires ET au classeur. Si le classeur diverge un jour, la
        composition s'arrete au lieu d'ecrire."""
        with pytest.raises((InvariantViole, CompositionImpossible)):
            composer(
                _faker("CM"),
                AncrageGeographique(
                    kiosque_id=uuid4(),
                    district_id="X",
                    quartier="X",
                    ville="X",
                    region="X",
                    pays="ZZ",
                ),
                _generateur(),
                REFERENTIEL,
                random.Random(1),
                jeune=True,
            )
