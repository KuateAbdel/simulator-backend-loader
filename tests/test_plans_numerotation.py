"""
tests/test_plans_numerotation.py
================================
`EF-27` — LES 12 PLANS DE NUMEROTATION, JUGES PAR UNE AUTORITE EXTERNE.

**Pourquoi ce fichier existe** (25/08/2026). `test_invariants.py` verifiait
deja que chaque numero compose est accepte par `telco.accepte(...)` — c'est
a dire par LA REGEX QUI VIENT DE LE PRODUIRE. Le test etait circulaire : un
plan faux passait vert. La mesure du 25/08 l'a prouve — 0/12 des numeros
burkinabe et 4/12 des ivoiriens etaient inattribuables dans la vraie vie :

    BF  le classeur composait NEUF chiffres nationaux, le plan en a HUIT
    CI  les series 4X et 5X du classeur ne sont attribuees a aucun operateur
        depuis la migration a dix chiffres de 2021

L'autorite est ici `libphonenumber` (Google), qui porte les plans publies par
les regulateurs — `ART` au Cameroun, `ARTCI` en Cote d'Ivoire, `ARCEP` au
Burkina, `ARTP` au Senegal. Elle est en dependance de TEST uniquement : le
Loader ne l'embarque pas, il compose depuis le referentiel comme avant. Rien
de la conception ne change ; c'est le JUGE qui devient exterieur.

La distinction qui porte tout le sujet :

    is_possible_number   la LONGUEUR est plausible     (Faker la respecte)
    is_valid_number      le PREFIXE existe VRAIMENT    (Faker ne le sait pas)

Un numero « complet » n'est pas un numero valide.
"""

from __future__ import annotations

import random
from pathlib import Path

import phonenumbers
import pytest
from phonenumbers import PhoneNumberType, is_possible_number, is_valid_number, number_type

from app.services.geographie import ReferentielGeo, charger_referentiel

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")

#: Longueur NATIONALE exacte, par pays — publiee par chaque regulateur.
LONGUEURS = {"CM": 9, "CI": 10, "BF": 8, "SN": 9}

#: Les operateurs attendus, pour que la repartition reste lisible en revue.
OPERATEURS = {"CM": 3, "CI": 3, "BF": 3, "SN": 3}


@pytest.fixture(scope="module")
def referentiel() -> ReferentielGeo:
    return charger_referentiel(CLASSEUR)


def _juger(numero: str) -> phonenumbers.PhoneNumber:
    return phonenumbers.parse("+" + numero, None)


class TestLesPlansDuReferentiel:
    """Le referentiel lui-meme, avant toute composition."""

    @pytest.mark.parametrize("pays", sorted(LONGUEURS))
    def test_chaque_pays_a_ses_operateurs(self, referentiel: ReferentielGeo, pays: str) -> None:
        telcos = referentiel.telcos_du_pays(pays)
        assert len(telcos) == OPERATEURS[pays], f"{pays} : {len(telcos)} operateurs"
        assert all(t.regex_msisdn for t in telcos), f"{pays} : un plan est vide — EF-27 impossible"


class TestLesNumerosComposes:
    """Ce que le Loader FABRIQUE — la seule chose qui compte pour la vraie vie."""

    @pytest.mark.parametrize("pays", sorted(LONGUEURS))
    def test_tout_numero_compose_est_un_MOBILE_REELLEMENT_ATTRIBUABLE(
        self, referentiel: ReferentielGeo, pays: str
    ) -> None:
        """LE test de la vraie vie : chaque operateur, 25 corps differents.

        Un echec ici veut dire qu'un client du Loader porte un numero qu'aucun
        reseau du pays ne pourrait router.
        """
        alea = random.Random(f"plans:{pays}")  # noqa: S311 — tirage de test, pas de cryptographie
        for telco in referentiel.telcos_du_pays(pays):
            for _ in range(25):
                corps = f"{alea.randrange(10**8):08d}"
                numero = telco.composer_msisdn(corps, alea)
                juge = _juger(numero)
                assert is_possible_number(juge), (
                    f"{telco.telco_id} : '{numero}' n'a pas une longueur plausible "
                    f"(attendu {LONGUEURS[pays]} chiffres nationaux)"
                )
                assert is_valid_number(juge), (
                    f"{telco.telco_id} : '{numero}' a la bonne longueur mais son "
                    f"prefixe n'est attribue a aucun operateur — c'est le defaut "
                    f"mesure chez Faker, il ne doit jamais exister chez nous"
                )
                assert number_type(juge) == PhoneNumberType.MOBILE, (
                    f"{telco.telco_id} : '{numero}' n'est pas un mobile — un client "
                    f"de collecte ne se joint pas sur une ligne fixe"
                )
                # La longueur se mesure sur la CHAINE composee, apres
                # l'indicatif : `national_number` est un entier, il perd le
                # zero initial des plans burkinabe et ivoirien (le juge le
                # range dans `italian_leading_zero`).
                national = numero[len(str(juge.country_code)) :]
                assert len(national) == LONGUEURS[pays], (
                    f"{telco.telco_id} : '{numero}' porte {len(national)} chiffres "
                    f"nationaux, le plan {pays} en compte {LONGUEURS[pays]}"
                )

    @pytest.mark.parametrize(
        "pays,chiffres",
        [("CM", "45126951"), ("CM", "08770918"), ("CI", "17839505"), ("BF", "03828183")],
    )
    def test_les_vrais_tirages_faker_deviennent_attribuables(
        self, referentiel: ReferentielGeo, pays: str, chiffres: str
    ) -> None:
        """Les quatre corps du 09/08, inattribuables chez Faker, le deviennent
        une fois le prefixe pose. C'est la raison d'etre de `composer_msisdn`."""
        numero, operateur = referentiel.composer_msisdn(pays, chiffres, random.Random(20260809))  # noqa: S311
        assert operateur.country_iso2 == pays
        assert is_valid_number(_juger(numero)), f"{pays} : '{numero}' toujours inattribuable"

    def test_le_corps_de_faker_est_conserve_la_ou_le_plan_le_permet(
        self, referentiel: ReferentielGeo
    ) -> None:
        """La correction des plans ne doit PAS abimer la tracabilite (ENF-15) :
        deux compositions du meme corps, meme graine, donnent le meme numero."""
        for pays in sorted(LONGUEURS):
            a = referentiel.composer_msisdn(pays, "53263354", random.Random(7))[0]  # noqa: S311
            b = referentiel.composer_msisdn(pays, "53263354", random.Random(7))[0]  # noqa: S311
            assert a == b, f"{pays} : composition non deterministe ({a} != {b})"


class TestLaNonRegressionDuDefautMesure:
    """Les valeurs EXACTES du 25/08 — pour qu'elles ne reviennent jamais."""

    def test_le_burkina_ne_compose_plus_neuf_chiffres(self, referentiel: ReferentielGeo) -> None:
        alea = random.Random("bf")  # noqa: S311
        for telco in referentiel.telcos_du_pays("BF"):
            numero = telco.composer_msisdn("12345678", alea)
            national = numero[3:]  # apres l'indicatif 226
            assert len(national) == 8, (
                f"{telco.telco_id} : {len(national)} chiffres nationaux — le plan "
                f"burkinabe en compte HUIT (defaut mesure le 25/08 : il en composait NEUF)"
            )

    def test_la_cote_d_ivoire_n_utilise_plus_les_series_4X_et_5X(
        self, referentiel: ReferentielGeo
    ) -> None:
        for telco in referentiel.telcos_du_pays("CI"):
            assert "4" != telco.regex_msisdn[5], telco.regex_msisdn
            for serie in ("|4", "|5"):
                assert serie not in telco.regex_msisdn, (
                    f"{telco.telco_id} : serie non attribuee reintroduite dans "
                    f"{telco.regex_msisdn} — la migration de 2021 ne garde que 01/05/07"
                )
