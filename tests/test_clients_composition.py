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
    GROUPES_PAR_FAMILLE_CDC,
    OCCUPATIONS_PAR_SECTEUR,
    PROFIL_INTERDIT_AUX_PERSONNES_MORALES,
    AncrageGeographique,
    CompositionImpossible,
    ancrer_sur_kiosque,
    composer,
    langue_de_la_region,
    occupation_du_secteur,
    occupation_reelle,
)
from app.services.generateur import Generateur
from app.services.geographie import charger_referentiel
from app.services.referentiel_statique import PAYS_CIBLES_LIBELLES, charger_statique

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


STATIQUE = charger_statique()


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

    def test_la_langue_est_le_francais_dans_les_regions_francophones(self) -> None:
        assert _composer(_faker()).langue is Language.FR


class TestLaLangueSuitLaRegion:
    """Le Cameroun est officiellement BILINGUE. Poser `fr` sur toute sa carte
    serait une donnee fausse, et visible pour qui connait le pays."""

    @pytest.mark.parametrize("region", ["Nord-Ouest", "Sud-Ouest"])
    def test_les_deux_regions_anglophones_du_cameroun_parlent_anglais(
        self, region: str
    ) -> None:
        """L'ancien Southern Cameroons britannique — Bamenda au Nord-Ouest, Buea
        et Limbe au Sud-Ouest."""
        assert langue_de_la_region("CM", region) is Language.EN

    @pytest.mark.parametrize(
        "region", ["Centre", "Littoral", "Ouest", "Nord", "Sud", "Est", "Adamaoua"]
    )
    def test_les_huit_autres_regions_camerounaises_parlent_francais(self, region: str) -> None:
        assert langue_de_la_region("CM", region) is Language.FR

    @pytest.mark.parametrize("pays", ["CI", "BF", "SN"])
    def test_les_trois_autres_pays_sont_entierement_francophones(self, pays: str) -> None:
        """Y compris pour une region qui porterait le meme nom : `Nord-Ouest`
        n'est anglophone qu'AU CAMEROUN."""
        assert langue_de_la_region(pays, "Nord-Ouest") is Language.FR
        assert langue_de_la_region(pays, "Centre") is Language.FR

    def test_un_client_de_bamenda_est_onboarde_en_anglais(self) -> None:
        """Le test qui compte : la langue est DERIVEE du Kiosque, comme le reste.
        Bamenda est la seule ville anglophone portant des quartiers au
        referentiel — `Commercial Avenue`, `Nkwen`, `Bambili`."""
        bamenda = next(
            v
            for v in REFERENTIEL.villes_porteuses_de_quartiers("CM")
            if v.name == "Bamenda"
        )
        quartier = REFERENTIEL.quartiers_de_ville(bamenda.city_id)[0]
        kiosque = _kiosque("CM").model_copy(update={"district_id": quartier.district_id})
        ancrage = ancrer_sur_kiosque(kiosque, REFERENTIEL)

        assert ancrage.region == "Nord-Ouest"
        compose = composer(
            _faker("CM"), ancrage, _generateur(), REFERENTIEL, random.Random(1), jeune=True
        )
        assert compose.langue is Language.EN

    def test_le_sud_ouest_ne_porte_aucun_quartier_au_referentiel(self) -> None:
        """`EF-04` — Buea et Limbe existent comme VILLES mais sans quartier :
        aucun Kiosque n'y est possible, donc aucun client anglophone n'en
        viendra. Trou de DONNEES, a documenter plutot qu'a masquer. Si le
        referentiel s'enrichit, ce test le dira."""
        sud_ouest = next(r for r in REFERENTIEL.regions_du_pays("CM") if r.name == "Sud-Ouest")
        villes = REFERENTIEL.villes_de_region(sud_ouest.region_id)
        assert [v.name for v in villes] == ["Buea", "Limbe"]
        assert all(not REFERENTIEL.quartiers_de_ville(v.city_id) for v in villes)

    def test_la_langue_anglophone_epargne_le_PATCH(self) -> None:
        """`language` est ignore a l'onboarding et seul `en` est honore. Un
        client anglophone ne coute donc AUCUN appel supplementaire — l'economie
        est marginale, mais elle va dans le bon sens plutot que contre."""
        assert langue_de_la_region("CM", "Nord-Ouest") is Language.EN
        assert Language.EN.value == "en", "le defaut honore par le serveur"


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


class TestOccupationsReellesSD3:
    """`SD-3` — 18 metiers inventes remplaces par les 576 de JJB.

    LE DEFAUT QUE CE LOT FERME, mesure du 12/08 sur 500 clients :

        INDIVIDUAL — 400 clients, **1 SEULE occupation distincte**
            Commercant   400  (100,0 %)

    Les 1600 clients individuels de la campagne portaient TOUS « Commercant », le
    defaut code en dur du generateur. C'est le champ qu'un bailleur lit en premier.
    """

    def test_les_quatre_familles_du_CDC_survivent(self) -> None:
        """`EF-24` nomme « agriculture » et « transports, commerce et services ».
        Le vocabulaire du CDC reste le CONTRAT ; le fichier n'est que la MATIERE."""
        assert set(GROUPES_PAR_FAMILLE_CDC) == {
            "AGRICULTURE",
            "TRANSPORTS",
            "COMMERCE",
            "SERVICES",
        }

    def test_chaque_groupe_declare_EXISTE_dans_le_referentiel(self) -> None:
        """Vingt-et-un libelles de groupe sont cites ; si JJB en renomme un, le
        Loader chercherait un groupe inexistant."""
        connus = set(STATIQUE.groupes)
        for famille, groupes in GROUPES_PAR_FAMILLE_CDC.items():
            manquants = [g for g in groupes if g not in connus]
            assert manquants == [], f"{famille} : {manquants}"

    def test_les_VINGT_ET_UN_groupes_sont_couverts_sans_doublon(self) -> None:
        """Un groupe oublie serait 46 professions perdues ; un groupe dans deux
        familles ferait qu'un metier appartient a deux familles du CDC."""
        tous = [g for groupes in GROUPES_PAR_FAMILLE_CDC.values() for g in groupes]
        assert len(tous) == len(set(tous)), "un groupe est dans deux familles"
        assert set(tous) == set(STATIQUE.groupes), "un groupe n'est dans aucune famille"

    def test_l_AGRICULTURE_porte_assez_de_metiers_pour_EF_24(self) -> None:
        metiers = STATIQUE.professions_des_groupes(
            GROUPES_PAR_FAMILLE_CDC["AGRICULTURE"]
        )
        assert len(metiers) >= 100, f"{len(metiers)} metiers agricoles"

    def test_un_INDIVIDUAL_tire_parmi_les_576(self) -> None:
        """`EF-24` parle des « professionnels » : les CORPORATE. Un INDIVIDUAL n'a
        aucun quota d'activite au CDC, donc aucune famille imposee."""
        vus = {occupation_reelle(None, f"CM-IND-{r}", STATIQUE) for r in range(300)}
        assert len(vus) > 150, f"{len(vus)} metiers distincts pour 300 clients"
        assert vus <= set(STATIQUE.professions)

    def test_un_CORPORATE_reste_dans_sa_famille(self) -> None:
        for famille, groupes in GROUPES_PAR_FAMILLE_CDC.items():
            admis = set(STATIQUE.professions_des_groupes(groupes))
            for rang in range(40):
                metier = occupation_reelle(
                    famille, f"CM-BIZ-{famille}-{rang}", STATIQUE, personne_morale=True
                )
                assert metier in admis, (famille, metier)

    def test_une_PERSONNE_MORALE_n_est_JAMAIS_salariee(self) -> None:
        """Le fichier donne la regle dans sa propre definition : `bank_stable` =
        « Regular and predictable SALARY, PENSION or institutional PAYROLL ». Cela
        decrit un salarie, pas une entreprise.

        Mesure du 12/08 avant cette regle : **47 CORPORATE sur 100** recevaient un
        metier de salarie ou de journalier — « Dock labourer paid casually »,
        « Government accountant ».
        """
        for famille in GROUPES_PAR_FAMILLE_CDC:
            for rang in range(60):
                metier = occupation_reelle(
                    famille, f"biz-{famille}-{rang}", STATIQUE, personne_morale=True
                )
                profil = STATIQUE.profil_de_la_profession(metier).nom
                assert profil != PROFIL_INTERDIT_AUX_PERSONNES_MORALES, (metier, profil)

    def test_un_INDIVIDUAL_peut_ETRE_salarie(self) -> None:
        """La regle ne vaut que pour les personnes morales : un particulier
        fonctionnaire est un client de microfinance parfaitement ordinaire."""
        profils = {
            STATIQUE.profil_de_la_profession(
                occupation_reelle(None, f"ind-{r}", STATIQUE)
            ).nom
            for r in range(200)
        }
        assert PROFIL_INTERDIT_AUX_PERSONNES_MORALES in profils

    def test_ANCREE_au_client_jamais_au_run(self) -> None:
        """`CR-03` — une reprise ne doit pas changer le metier d'un client."""
        assert occupation_reelle(None, "CM-IND-42", STATIQUE) == occupation_reelle(
            None, "CM-IND-42", STATIQUE
        )
        assert occupation_reelle("AGRICULTURE", "CM-BIZ-7", STATIQUE) == occupation_reelle(
            "AGRICULTURE", "CM-BIZ-7", STATIQUE
        )

    def test_une_famille_INCONNUE_est_REFUSEE(self) -> None:
        """« transports, commerce et services » n'est pas une liste ouverte."""
        with pytest.raises(CompositionImpossible, match="hors de la taxonomie EF-24"):
            occupation_reelle("PECHE HAUTURIERE", "x", STATIQUE)

    def test_le_defaut_Commercant_a_DISPARU(self) -> None:
        """Il servait 100 % des INDIVIDUAL. Aucun client ne doit plus le recevoir
        par defaut — et « Commercant » n'existe meme pas dans le referentiel, qui
        est en anglais."""
        vus = {occupation_reelle(None, f"c{r}", STATIQUE) for r in range(200)}
        assert "Commercant" not in vus


class TestLieuDeNaissanceSD6:
    """`SD-6` (tache #15) — le lieu de naissance, et `id_place` libere.

    LE DEFAUT FERME : `place_of_birth` restait a `null` sur le serveur
    (mesure du 09/08 — champ accepte, jamais envoye), et `id_place` etait la
    ville de residence pour 2000 clients sur 2000. Une population entiere nee
    exactement la ou elle habite n'existe dans aucun pays reel.
    """

    @staticmethod
    def _identite(ancre: str, ville: str = "Douala", region: str = "Littoral") -> Any:
        return Generateur(uuid4(), reference=date(2026, 8, 13)).identite(
            first_name="Salif",
            last_name="Tamadou",
            gender="MALE",
            country_code="CM",
            ville=ville,
            region=region,
            quartier="Bepanda",
            telephone="+237650000001",
            jeune=False,
            ancre_client=ancre,
            occupation="Cocoa farmer",
            referentiel=REFERENTIEL,
            statique=STATIQUE,
        )

    def _population(self, n: int = 400) -> list[Any]:
        return [self._identite(f"CM-IND-{r}") for r in range(n)]

    def test_place_of_birth_n_est_JAMAIS_vide(self) -> None:
        """Le serveur le persiste a null quand on l'omet — plus jamais."""
        assert all(i.place_of_birth for i in self._population(100))

    def test_ANCRE_au_client_jamais_au_run(self) -> None:
        """`CR-03` — deux runs differents (deux Generateur, deux run_id), le
        meme client : le meme lieu de naissance."""
        assert (
            self._identite("CM-IND-42").place_of_birth
            == self._identite("CM-IND-42").place_of_birth
        )

    def test_la_MAJORITE_est_nee_dans_une_ville_du_pays(self) -> None:
        villes_cm = {
            v.name.title()
            for r in REFERENTIEL.regions_du_pays("CM")
            for v in REFERENTIEL.villes_de_region(r.region_id)
        }
        population = self._population()
        locaux = [i for i in population if i.place_of_birth in villes_cm]
        assert len(locaux) / len(population) > 0.8

    def test_la_MIGRATION_INTERNE_existe_sans_quota(self) -> None:
        """Avec ~12 villes par pays, la plupart des clients ne doivent pas
        etre nes dans leur ville de residence — mecaniquement, sans quota."""
        population = self._population()
        ailleurs = [i for i in population if i.place_of_birth != "Douala"]
        assert len(ailleurs) / len(population) > 0.5

    def test_la_MINORITE_nait_a_l_etranger_dans_les_195_pays(self) -> None:
        """~10 % (UN DESA 2020, borne haute regionale CI). Le libelle est le
        FRANCAIS de `Lieu2Nationalite.csv` — l'ecosysteme est francophone —
        et jamais un des quatre pays cibles."""
        pays_fr = set(STATIQUE.pays.values())
        villes_cm = {
            v.name.title()
            for r in REFERENTIEL.regions_du_pays("CM")
            for v in REFERENTIEL.villes_de_region(r.region_id)
        }
        population = self._population()
        etrangers = [i for i in population if i.place_of_birth not in villes_cm]
        assert 0.04 < len(etrangers) / len(population) < 0.18
        # Les libelles des quatre cibles DERIVES du referentiel, jamais en dur —
        # le fichier ecrit ses apostrophes et accents a sa facon (mesure 12/08).
        cibles_fr = {STATIQUE.pays[libelle_en] for libelle_en in PAYS_CIBLES_LIBELLES.values()}
        for identite in etrangers:
            assert identite.place_of_birth in pays_fr, identite.place_of_birth
            assert identite.place_of_birth not in cibles_fr

    def test_id_place_suit_la_naissance_pour_les_locaux(self) -> None:
        """La piece est delivree pres du lieu de naissance — et donc `id_place`
        n'est PLUS mecaniquement la ville de residence."""
        villes_cm = {
            v.name.title()
            for r in REFERENTIEL.regions_du_pays("CM")
            for v in REFERENTIEL.villes_de_region(r.region_id)
        }
        for identite in self._population(200):
            if identite.place_of_birth in villes_cm:
                assert identite.id_place == identite.place_of_birth
            else:
                # Ne a l'etranger, nationalite locale : la piece est delivree
                # ou il reside. JAMAIS dans un pays sans referentiel.
                assert identite.id_place == "Douala"

    def test_la_NATIONALITE_reste_celle_du_pays_de_residence(self) -> None:
        """Choix declare du lot : la minorite nee a l'etranger est la diaspora
        de retour, pas des nationaux etrangers — une nationalite etrangere
        entrainerait piece, msisdn et devise d'un pays sans referentiel."""
        assert all(i.nationality == "CM" for i in self._population(150))

    def test_le_payload_PORTE_le_champ(self) -> None:
        identite = self._identite("CM-IND-7")
        assert identite.en_payload()["place_of_birth"] == identite.place_of_birth

    def test_sans_referentiel_statique_le_comportement_historique_demeure(self) -> None:
        """Les appelants d'avant SD-6 (sans `statique`) restent valides : ne
        la ou il reside — aucun champ vide, aucune surprise."""
        identite = Generateur(uuid4(), reference=date(2026, 8, 13)).identite(
            first_name="Salif",
            last_name="Tamadou",
            gender="MALE",
            country_code="CM",
            ville="Douala",
            region="Littoral",
            quartier="Bepanda",
            telephone="+237650000002",
            jeune=False,
            ancre_client="CM-IND-1",
            referentiel=REFERENTIEL,
        )
        assert identite.place_of_birth == "Douala"
        assert identite.id_place == "Douala"


class TestINV18RepartitionParOperateur:
    """`INV-18` — la population reproduit le MARCHE, pas une loterie uniforme.

    Le mecanisme (roue ponderee par `part_marche`, ancree au client) est livre
    depuis EF-27/S4-01 — mais AUCUN test ne mesurait la distribution : une
    garantie que rien n'exerce n'est pas une garantie. Ces tests la fixent.
    """

    @staticmethod
    def _distribution(pays: str, n: int = 2000) -> dict[str, float]:
        generateur = Generateur(uuid4(), reference=date(2026, 8, 13))
        comptes: dict[str, int] = {}
        for i in range(n):
            msisdn, telco = generateur.msisdn(pays, REFERENTIEL, f"{pays}-INV18-{i}")
            comptes[telco.short_name] = comptes.get(telco.short_name, 0) + 1
        return {nom: c / n for nom, c in comptes.items()}

    def test_le_Cameroun_ressemble_au_marche_camerounais(self) -> None:
        """MTN 46 · Orange 43 · Blue 3 (somme 92) -> parts normalisees
        attendues ~50,0 / 46,7 / 3,3 %. Tolerance 3 points — le tirage est
        DETERMINISTE (ancres figees), l'ecart mesure ne bouge jamais."""
        operateurs = {t.short_name: t.part_marche for t in REFERENTIEL.telcos_du_pays("CM")}
        total = sum(operateurs.values())
        mesure = self._distribution("CM")
        for nom, part in operateurs.items():
            attendu = part / total
            assert abs(mesure.get(nom, 0.0) - attendu) < 0.03, (
                f"{nom} : {mesure.get(nom, 0.0):.1%} mesure pour {attendu:.1%} "
                "attendu — la roue ponderee ne suit plus le marche"
            )

    def test_le_petit_operateur_EXISTE_sans_peser_un_tiers(self) -> None:
        """L'anti-uniforme : Blue CM (3 % du marche) doit apparaitre — le
        marche entier compte — mais JAMAIS peser ~33 % comme dans une loterie
        uniforme. C'est le test que la mutation « tirage uniforme » fait
        tomber."""
        mesure = self._distribution("CM")
        petit = min(mesure.values())
        assert 0.0 < petit < 0.10, (
            f"le plus petit operateur pese {petit:.1%} — un tiers signifierait "
            "un tirage uniforme, zero signifierait un marche ampute"
        )

    def test_les_QUATRE_pays_suivent_leur_marche(self) -> None:
        """La fidelite des PARTS, pays par pays — et pas la « dominance » :
        quand le marche est serre (MTN 46 vs Orange 43 au CM), le premier d'un
        echantillon fini peut legitimement s'inverser ; les parts, elles,
        doivent coller. Premiere version de ce test ecrite sur la dominance,
        tombee pour cette raison exacte — le test etait faux, pas le code."""
        for pays in ("CM", "CI", "BF", "SN"):
            operateurs = {
                t.short_name: t.part_marche for t in REFERENTIEL.telcos_du_pays(pays)
            }
            total = sum(operateurs.values())
            mesure = self._distribution(pays, n=1500)
            for nom, part in operateurs.items():
                attendu = part / total
                assert abs(mesure.get(nom, 0.0) - attendu) < 0.035, (
                    f"{pays}/{nom} : {mesure.get(nom, 0.0):.1%} pour {attendu:.1%}"
                )

    def test_l_operateur_est_ANCRE_au_client(self) -> None:
        """CR-03 (correction du 12/08) : meme matiere client, meme operateur,
        meme numero — sur DEUX runs differents."""
        a = Generateur(uuid4(), reference=date(2026, 8, 13)).msisdn(
            "CM", REFERENTIEL, "CM-INV18-ancre"
        )
        b = Generateur(uuid4(), reference=date(2026, 8, 13)).msisdn(
            "CM", REFERENTIEL, "CM-INV18-ancre"
        )
        assert a[0] == b[0] and a[1].short_name == b[1].short_name
