"""Les invariants que le systeme ne pose pas — Sprint 1.

Ces tests ne verifient pas le serveur. Ils verifient que **le Loader n'emet
jamais une donnee qu'un banquier jugerait absurde**.

Chaque regle testee ici correspond a un trou mesure le 09/08/2026 : le systeme
accepte un client de 2 ans, un genre « peu importe », une piece expiree. Rien
de tout cela n'est rattrapable — identity-service, account-service et
depositary-service n'exposent aucun `DELETE`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.core.invariants import (
    AGE_MAXIMUM,
    AGE_MINIMUM,
    InvariantViole,
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
