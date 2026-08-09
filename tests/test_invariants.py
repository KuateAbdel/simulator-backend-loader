"""Les invariants que le systeme ne pose pas — Sprint 1.

Ces tests ne verifient pas le serveur. Ils verifient que **le Loader n'emet
jamais une donnee qu'un banquier jugerait absurde**.

Chaque regle testee ici correspond a un trou mesure le 09/08/2026 : le systeme
accepte un client de 2 ans, un genre « peu importe », une piece expiree. Rien
de tout cela n'est rattrapable — identity-service, account-service et
depositary-service n'exposent aucun `DELETE`.
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import pytest

from app.core.invariants import (
    AGE_MAXIMUM,
    AGE_MINIMUM,
    InvariantViole,
    RegistreUnicite,
    calculer_age,
    exiger_champs_renseignes,
    normaliser_email,
    normaliser_msisdn,
    sans_accents,
    valider_age,
    valider_coherence_matrimoniale,
    valider_devise_pays,
    valider_genre,
    valider_id_number,
    valider_identite_complete,
    valider_msisdn_operateur,
    valider_nationalite,
    valider_piece_identite,
    valider_situation_familiale,
)
from app.services.geographie import charger_referentiel

REF = date(2026, 8, 9)


class TestAge:
    """Le systeme accepte 2 ans et 120 ans. Seule une naissance dans le futur
    est refusee (mesure 09/08)."""

    def test_un_enfant_de_deux_ans_est_refuse(self) -> None:
        """Le cas qui a motive ce module."""
        with pytest.raises(InvariantViole, match="majorite legale"):
            valider_age(date(2024, 1, 1), REF)

    def test_un_mineur_de_dix_sept_ans_est_refuse(self) -> None:
        with pytest.raises(InvariantViole, match="majorite legale"):
            valider_age(date(2009, 1, 1), REF)

    def test_dix_huit_ans_pile_est_accepte(self) -> None:
        assert valider_age(date(2008, 8, 9), REF) == AGE_MINIMUM

    def test_cent_vingt_ans_est_refuse(self) -> None:
        with pytest.raises(InvariantViole, match="credible"):
            valider_age(date(1906, 1, 1), REF)

    def test_naissance_future_refusee(self) -> None:
        with pytest.raises(InvariantViole, match="futur"):
            valider_age(date(2030, 1, 1), REF)

    @pytest.mark.parametrize("annee", [2008, 2001, 1990, 1970, 1952])
    def test_les_ages_plausibles_passent(self, annee: int) -> None:
        age = valider_age(date(annee, 1, 1), REF)
        assert AGE_MINIMUM <= age <= AGE_MAXIMUM

    def test_l_anniversaire_non_atteint_ne_compte_pas(self) -> None:
        """Un client ne de fin decembre n'a pas encore son age en aout."""
        assert calculer_age(date(2008, 12, 31), REF) == 17


class TestPieceIdentite:
    """Aucun service ne verifie qu'une piece est valide — seulement que le
    champ est present (D-CLI-2)."""

    def test_piece_expiree_refusee(self) -> None:
        with pytest.raises(InvariantViole, match="expiree"):
            valider_piece_identite(date(1990, 1, 1), date(2025, 1, 1), REF)

    def test_piece_expirant_demain_acceptee(self) -> None:
        valider_piece_identite(date(1990, 1, 1), date(2026, 8, 10), REF)

    def test_piece_emise_avant_la_majorite_refusee(self) -> None:
        """Une piece expirant en 2030 suppose une emission en 2020 ; un client
        ne en 2008 avait 12 ans a cette date."""
        with pytest.raises(InvariantViole, match="Incoherent"):
            valider_piece_identite(date(2008, 1, 1), date(2030, 1, 1), REF)

    def test_coherence_nominale(self) -> None:
        valider_piece_identite(date(1990, 1, 1), date(2030, 1, 1), REF)


class TestEtatCivil:
    """Trois champs que le serveur accepte tels quels, quelle que soit leur
    valeur (mesure 09/08)."""

    @pytest.mark.parametrize("genre", ["peu importe", "F", "ANY", "", "Femme"])
    def test_genres_hors_referentiel_refuses(self, genre: str) -> None:
        with pytest.raises(InvariantViole, match="genre"):
            valider_genre(genre)

    def test_any_est_explicitement_exclu(self) -> None:
        """`ANY` existe dans l'enum serveur mais rendrait EF-22 invérifiable —
        et c'est cette valeur qui a fui dans le champ currency d'un compte reel
        (FRA-222)."""
        with pytest.raises(InvariantViole) as erreur:
            valider_genre("ANY")
        assert "EF-22" in str(erreur.value)

    @pytest.mark.parametrize("genre,attendu", [("male", "MALE"), (" Female ", "FEMALE")])
    def test_normalisation_du_genre(self, genre: str, attendu: str) -> None:
        assert valider_genre(genre) == attendu

    def test_situation_hors_enum_refusee(self) -> None:
        with pytest.raises(InvariantViole, match="situation familiale"):
            valider_situation_familiale("CELIBATAIRE")

    def test_nationalite_hors_pays_cibles_refusee(self) -> None:
        with pytest.raises(InvariantViole, match="pays cibles"):
            valider_nationalite("FR")

    def test_nationalite_minuscule_normalisee(self) -> None:
        """Le serveur accepte `cm` en 201 la ou `ZZ` est refuse : la validation
        ISO est insensible a la casse, et la base accumule les deux formes."""
        assert valider_nationalite("cm") == "CM"


class TestIdNumber:
    @pytest.mark.parametrize("valeur", ["CM_123456", "CM 123456", "AB1", "A" * 21, ""])
    def test_formats_invalides_refuses(self, valeur: str) -> None:
        with pytest.raises(InvariantViole, match="id_number"):
            valider_id_number(valeur)

    def test_minuscules_normalisees(self) -> None:
        assert valider_id_number("cm250509274") == "CM250509274"

    def test_la_longueur_est_bornee_alors_que_le_serveur_ne_la_borne_pas(self) -> None:
        with pytest.raises(InvariantViole):
            valider_id_number("A" * 50)


class TestNormalisation:
    def test_email_insensible_a_la_casse(self) -> None:
        """identity-service impose l'unicite de l'email mais ne la normalise
        pas : deux casses produisent deux Identities (mesure 09/08)."""
        assert normaliser_email("  Demo.QA@Finzuu.LOCAL ") == "demo.qa@finzuu.local"

    @pytest.mark.parametrize(
        "brut,attendu",
        [
            ("+237 699 11 22 33", "+237699112233"),
            ("699-11-22-33", "699112233"),
            (" 699112233 ", "699112233"),
        ],
    )
    def test_msisdn_debarrasse_des_separateurs(self, brut: str, attendu: str) -> None:
        assert normaliser_msisdn(brut) == attendu

    def test_accents_retires_pour_les_identifiants_derives(self) -> None:
        assert sans_accents("Kouassi Éloïse") == "Kouassi Eloise"


class TestIdentiteComplete:
    """Le point d'entree unique — un appelant ne peut pas oublier une regle."""

    def test_identite_nominale(self) -> None:
        resultat = valider_identite_complete(
            naissance="1995-04-12",
            expiration_piece="2030-01-01",
            genre="female",
            situation_familiale="single",
            nationalite="cm",
            id_number="cm250509274",
            email="  Demo@FinZuu.local ",
            reference=REF,
        )
        assert resultat["age"] == 31
        assert resultat["jeune"] is False
        assert resultat["gender"] == "FEMALE"
        assert resultat["nationality"] == "CM"
        assert resultat["id_number"] == "CM250509274"
        assert resultat["email"] == "demo@finzuu.local"

    def test_le_drapeau_jeune_sert_le_quota_ef22(self) -> None:
        """EF-22 : 60 % de moins de 25 ans. Le drapeau est calcule ici, une
        seule fois, plutot que recalcule a chaque usage."""
        resultat = valider_identite_complete(
            naissance="2005-01-01",
            expiration_piece="2033-01-01",
            genre="MALE",
            situation_familiale="SINGLE",
            nationalite="CI",
            id_number="CI123456",
            email="a@b.local",
            reference=REF,
        )
        assert resultat["age"] == 21
        assert resultat["jeune"] is True

    def test_une_date_illisible_est_nommee(self) -> None:
        with pytest.raises(InvariantViole, match="date de naissance illisible"):
            valider_identite_complete(
                naissance="pas une date",
                expiration_piece="2030-01-01",
                genre="MALE",
                situation_familiale="SINGLE",
                nationalite="CM",
                id_number="CM123456",
                email="a@b.local",
                reference=REF,
            )


class TestCoherenceMatrimoniale:
    """Le systeme accepte n'importe quelle combinaison age x situation."""

    @pytest.mark.parametrize("situation,age", [("WIDOWED", 19), ("DIVORCED", 19)])
    def test_situations_invraisemblables_refusees(self, situation: str, age: int) -> None:
        with pytest.raises(InvariantViole, match="invraisemblable"):
            valider_coherence_matrimoniale(situation, age)

    @pytest.mark.parametrize(
        "situation,age", [("SINGLE", 18), ("MARRIED", 22), ("DIVORCED", 30), ("WIDOWED", 55)]
    )
    def test_combinaisons_credibles_acceptees(self, situation: str, age: int) -> None:
        assert valider_coherence_matrimoniale(situation, age) == situation

    def test_le_message_dit_que_ce_n_est_pas_une_regle_legale(self) -> None:
        with pytest.raises(InvariantViole) as erreur:
            valider_coherence_matrimoniale("WIDOWED", 20)
        assert "credibilite" in str(erreur.value)


def graine(valeur: int) -> random.Random:
    """Generateur seme — reproductibilite ENF-15, jamais de cryptographie."""
    return random.Random(valeur)  # noqa: S311


@pytest.fixture(scope="module")
def referentiel() -> object:
    """Le referentiel reel — 51 regions, 50 villes, 82 quartiers, 12 telcos,
    2 devises. Charge une fois pour tout le module."""
    return charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))


class TestCoherenceTerritoriale:
    """MSISDN, operateur et devise doivent s'accorder avec le pays. Aucun
    service FinZuu ne le verifie ; le referentiel, lui, porte la matiere."""

    def test_msisdn_conforme_identifie_son_operateur(self, referentiel: object) -> None:
        operateur = valider_msisdn_operateur("237699112233", "CM", referentiel)
        assert operateur.network_name == "Orange Cameroon"  # type: ignore[attr-defined]

    def test_msisdn_de_faker_est_rejete(self, referentiel: object) -> None:
        """Mesure du 09/08 : 18 tirages sur 3 pays, 18 numeros non
        attribuables. Faker ne respecte aucun plan de numerotation reel."""
        with pytest.raises(InvariantViole, match="non attribuable"):
            valider_msisdn_operateur("23776511256", "CM", referentiel)

    def test_msisdn_d_un_autre_pays_est_rejete(self, referentiel: object) -> None:
        with pytest.raises(InvariantViole, match="non attribuable"):
            valider_msisdn_operateur("237699112233", "SN", referentiel)

    @pytest.mark.parametrize(
        "pays,devise", [("CM", "XAF"), ("CI", "XOF"), ("BF", "XOF"), ("SN", "XOF")]
    )
    def test_la_zone_monetaire_determine_la_devise(
        self, referentiel: object, pays: str, devise: str
    ) -> None:
        assert valider_devise_pays(devise, pays, referentiel) == devise

    def test_xof_pour_un_camerounais_est_refuse(self, referentiel: object) -> None:
        """CM est en zone CEMAC (BEAC). XOF y est aussi faux qu'une devise
        inventee — et le serveur accepterait les deux (FRA-222)."""
        with pytest.raises(InvariantViole, match="zone monetaire"):
            valider_devise_pays("XOF", "CM", referentiel)

    def test_les_douze_operateurs_sont_charges(self, referentiel: object) -> None:
        assert len(referentiel.telcos) == 12  # type: ignore[attr-defined]
        for pays in ("CM", "CI", "BF", "SN"):
            assert len(referentiel.telcos_du_pays(pays)) == 3  # type: ignore[attr-defined]


class TestAucunChampVide:
    """Le serveur persiste `city`, `region`, `country` a null quand on les
    omet. Le Loader dispose du referentiel : il n'a aucune raison de le faire."""

    def test_champs_vides_detectes(self) -> None:
        with pytest.raises(InvariantViole, match="city, country"):
            exiger_champs_renseignes(
                {"city": None, "region": "Littoral", "country": ""},
                ("city", "region", "country"),
            )

    def test_adresse_complete_passe(self) -> None:
        exiger_champs_renseignes(
            {"city": "Douala", "region": "Littoral", "country": "CM", "latitude": 4.05},
            ("city", "region", "country", "latitude"),
        )


class TestCompositionMsisdn:
    """La doctrine du Loader appliquee a un cinquieme champ.

    Faker donne huit chiffres — le corps du numero — mais jamais le prefixe
    operateur, implicite pour un habitant du pays : au Cameroun tout mobile
    commence par `6`, en Cote d'Ivoire par `01`/`05`/`07`, au Burkina par `0`.
    Sans lui, AUCUN numero de Faker n'est attribuable a un reseau reel
    (mesure du 09/08, 18 tirages sur 3 pays).

    Le Loader ajoute le prefixe. La matiere reste celle de Faker.
    """

    def test_les_douze_plans_sont_exploitables(self, referentiel: object) -> None:
        """Cameroun en plages `[0-4]`, Burkina en enumerations `[56]` : les
        deux formes doivent etre couvertes."""
        alea = graine(1)
        for pays in ("CM", "CI", "BF", "SN"):
            for telco in referentiel.telcos_du_pays(pays):  # type: ignore[attr-defined]
                numero = telco.composer_msisdn("12345678", alea)
                assert telco.accepte(numero), f"{telco.telco_id} : '{numero}' non conforme"

    @pytest.mark.parametrize(
        "pays,chiffres",
        [("CM", "45126951"), ("CM", "08770918"), ("CI", "17839505"), ("BF", "03828183")],
    )
    def test_les_vrais_chiffres_faker_donnent_un_numero_valide(
        self, referentiel: object, pays: str, chiffres: str
    ) -> None:
        """Ces quatre valeurs viennent de tirages Faker reels du 09/08. Aucune
        n'etait attribuable telle quelle."""
        numero, operateur = referentiel.composer_msisdn(pays, chiffres, graine(20260809))  # type: ignore[attr-defined]
        assert referentiel.operateur_du_msisdn(numero, pays) is not None  # type: ignore[attr-defined]
        assert operateur.country_iso2 == pays

    def test_le_corps_du_numero_reste_celui_de_faker(self, referentiel: object) -> None:
        """Seul le prefixe est ajoute : la tracabilite vers le client Faker est
        preservee.

        Le corps est consomme dans l'ordre et **tronque a la place disponible**
        dans le plan. Le Senegal n'offre que sept chiffres apres le prefixe
        `77`, la ou Faker en fournit huit : le huitieme est perdu, et c'est
        normal — le plan de numerotation prime sur la matiere.
        """
        numero, _ = referentiel.composer_msisdn("SN", "12345678", graine(3))  # type: ignore[attr-defined]
        assert numero.endswith("1234567")
        assert len(numero) == len("221") + 2 + 7

    def test_determinisme_enf15(self, referentiel: object) -> None:
        """Deux executions de meme graine produisent le meme numero."""
        premier = [referentiel.composer_msisdn("CM", "53263354", graine(7))[0] for _ in range(3)]  # type: ignore[attr-defined]
        second = [referentiel.composer_msisdn("CM", "53263354", graine(7))[0] for _ in range(3)]  # type: ignore[attr-defined]
        assert premier == second

    def test_la_repartition_suit_les_parts_de_marche_reelles(self, referentiel: object) -> None:
        """Repartir 2000 clients uniformement entre trois operateurs ne
        ressemblerait a aucun marche africain."""
        alea = graine(42)
        comptes: dict[str, int] = {}
        for i in range(2000):
            _, operateur = referentiel.composer_msisdn("SN", f"{i:08d}", alea)  # type: ignore[attr-defined]
            comptes[operateur.short_name] = comptes.get(operateur.short_name, 0) + 1
        # Orange Senegal pese 55 % du marche reel.
        assert comptes["Orange SN"] / 2000 > 0.50
        assert comptes["Orange SN"] > comptes["Free SN"] > comptes["Expresso SN"]


class TestRegistreUnicite:
    """S1-04 — EF-25 n'exige que le MSISDN ; le serveur en impose TROIS.

    Et le message du doublon d'`id_number` designe le mauvais champ : il
    annonce « Client already exists » alors que le msisdn differait. Sans test
    dedie, on diagnostiquerait a cote — deux mille fois.
    """

    def test_un_client_conforme_est_reserve(self) -> None:
        registre = RegistreUnicite()
        numero, piece, courriel = registre.reserver(
            msisdn="+237 699 11 22 33", id_number="cm250509274", email="  Demo@X.local "
        )
        assert (numero, piece, courriel) == ("+237699112233", "CM250509274", "demo@x.local")
        assert registre.effectif == 1

    def test_msisdn_en_doublon_refuse(self) -> None:
        registre = RegistreUnicite()
        registre.reserver(msisdn="237699112233", id_number="CM111111", email="a@x.local")
        with pytest.raises(InvariantViole, match="msisdn"):
            registre.reserver(msisdn="237699112233", id_number="CM222222", email="b@x.local")

    def test_id_number_en_doublon_refuse_et_le_message_denonce_le_piege(self) -> None:
        registre = RegistreUnicite()
        registre.reserver(msisdn="237699112233", id_number="CM111111", email="a@x.local")
        with pytest.raises(InvariantViole) as erreur:
            registre.reserver(msisdn="237699112244", id_number="CM111111", email="b@x.local")
        message = str(erreur.value)
        assert "id_number" in message
        assert "mauvais champ" in message

    def test_email_en_doublon_refuse_malgre_la_casse(self) -> None:
        """Le serveur ne normalise pas : `Demo@x` et `demo@x` y produisent deux
        Identities. Nous, si."""
        registre = RegistreUnicite()
        registre.reserver(msisdn="237699112233", id_number="CM111111", email="Demo@X.local")
        with pytest.raises(InvariantViole, match="email"):
            registre.reserver(msisdn="237699112244", id_number="CM222222", email="demo@x.local")

    def test_le_formatage_du_msisdn_ne_cree_pas_de_faux_unique(self) -> None:
        """`699-11-22-33` et `699112233` sont le meme numero."""
        registre = RegistreUnicite()
        registre.reserver(msisdn="237-699-11-22-33", id_number="CM111111", email="a@x.local")
        with pytest.raises(InvariantViole, match="msisdn"):
            registre.reserver(msisdn="237699112233", id_number="CM222222", email="b@x.local")

    def test_deux_mille_clients_distincts_passent(self) -> None:
        registre = RegistreUnicite()
        for i in range(2000):
            registre.reserver(
                msisdn=f"2376991{i:05d}", id_number=f"CM{i:06d}", email=f"c{i}@x.local"
            )
        assert registre.effectif == 2000
        assert "2000 msisdn" in registre.resume()
