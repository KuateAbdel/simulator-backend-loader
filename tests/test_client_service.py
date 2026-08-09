"""Invariants client-service, portes cote Loader.

Ces tests ne verifient pas le serveur — ils verifient que **le Loader refuse
d'envoyer ce qui echouerait, ou pire, ce qui laisserait des orphelins**.

L'enjeu est de volumetrie : `POST /onboard` est emprunte **2000 fois** dans une
campagne complete. Une barriere manquante ne coute pas un echec, elle en coute
deux mille. Et rien n'est rattrapable : ni client-service, ni identity-service,
ni account-service n'exposent de DELETE.

Toutes les regles ci-dessous ont ete **rejouees contre le serveur le 09/08/2026**,
pas reprises d'une page de documentation.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.clients.client_service import (
    DEVISES_AUTORISEES,
    SOUSCRIPTIONS_MAX,
    OnboardingNonConforme,
    valider_onboarding,
)


def identite(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "_id": "11111111-1111-1111-1111-111111111111",
        "type": "INDIVIDUAL",
        "first_name": "DEMOQA",
        "last_name": "Kouassi",
        "date_of_birth": "1995-04-12T00:00:00",
        "gender": "FEMALE",
        "nationality": "CM",
        "id_number": "CM12345678",
        "id_place": "Douala",
        "id_expire_on": "2030-01-01T00:00:00",
        "phone": "600000000",
        "email": "demo@finzuu-demo.local",
        "occupation": "Commercante",
        "address": {"address_line_1": "Rue 12", "street_name": "Akwa"},
    }
    base.update(over)
    return base


class TestPhoneEgalMsisdn:
    """D-CLI-8 — invariant DECOUVERT le 09/08, absent de toutes nos sources.

    La page Service Anatomy du 01/08 ne le mentionne pas : ses tests utilisaient
    le meme numero des deux cotes par hasard et n'ont jamais rencontre la
    barriere. Le serveur repond 400 « Identity phone field must match msisdn ».
    """

    def test_le_phone_est_aligne_sur_le_msisdn(self) -> None:
        resultat = valider_onboarding("699111222", identite(phone="600000000"))
        assert resultat["phone"] == "699111222"

    def test_l_identite_de_l_appelant_n_est_jamais_mutee(self) -> None:
        """Le Loader ne modifie pas les donnees qu'on lui confie."""
        source = identite(phone="600000000")
        valider_onboarding("699111222", source)
        assert source["phone"] == "600000000"

    def test_les_espaces_du_msisdn_sont_retires(self) -> None:
        assert valider_onboarding("  699111222  ", identite())["phone"] == "699111222"


class TestIdExpireOn:
    """D-CLI-2 — le champ est OPTIONNEL dans la copie du schema portee par
    client-service, mais REQUIS dans l'original d'identity-service.

    Les deux copies sont desynchronisees. Le serveur accepte le payload, puis
    plante en cascade : 400 « 'NoneType' object has no attribute 'isoformat' ».
    Verifie le 09/08 — le crash est identique a celui du 01/08.
    """

    @pytest.mark.parametrize("valeur", [None, "", 0])
    def test_absence_refusee_avant_envoi(self, valeur: Any) -> None:
        with pytest.raises(OnboardingNonConforme, match="id_expire_on"):
            valider_onboarding("699111222", identite(id_expire_on=valeur))

    def test_le_message_explique_la_desynchronisation_des_schemas(self) -> None:
        """Un futur mainteneur doit comprendre POURQUOI on exige un champ que le
        contrat declare optionnel."""
        with pytest.raises(OnboardingNonConforme) as erreur:
            valider_onboarding("699111222", identite(id_expire_on=None))
        message = str(erreur.value)
        assert "desynchronisees" in message
        assert "isoformat" in message


class TestIdNumber:
    """D-CLI-3 — la discipline heritee du 01/08 disait « alphanumerique
    MAJUSCULES strict ». **Elle est caduque** : verifie le 09/08, une valeur en
    minuscules passe en HTTP 201.

    Seuls les caracteres speciaux sont reellement refuses. Le message d'erreur
    du serveur annonce une contrainte qu'il n'applique pas (FRA-228). Le Loader
    emet des majuscules par prudence — pour rester valide si la regle est un
    jour reellement posee — mais ne rejette que ce qui est reellement rejete.
    """

    @pytest.mark.parametrize("piece", ["QA_0808_BAD", "CM-123", "CM 123", "CM#1", ""])
    def test_caracteres_speciaux_refuses(self, piece: str) -> None:
        with pytest.raises(OnboardingNonConforme, match="id_number"):
            valider_onboarding("699111222", identite(id_number=piece))

    def test_les_minuscules_sont_normalisees_pas_rejetees(self) -> None:
        """Le serveur les accepte ; on les met en majuscules sans echouer."""
        resultat = valider_onboarding("699111222", identite(id_number="cm250509274"))
        assert resultat["id_number"] == "CM250509274"

    def test_le_message_dit_que_la_casse_n_est_pas_appliquee(self) -> None:
        with pytest.raises(OnboardingNonConforme) as erreur:
            valider_onboarding("699111222", identite(id_number="CM#1"))
        assert "FRA-228" in str(erreur.value)


class TestPayloadNominal:
    def test_une_identite_conforme_passe_sans_modification_de_fond(self) -> None:
        resultat = valider_onboarding("699111222", identite())
        assert resultat["id_number"] == "CM12345678"
        assert resultat["id_expire_on"] == "2030-01-01T00:00:00"
        assert resultat["address"] == {"address_line_1": "Rue 12", "street_name": "Akwa"}


class TestDevise:
    """D-CLI-9 — le trou le plus grave du chemin d'onboarding.

    `currency` est requise au contrat, n'apparait PAS dans la fiche Client
    rendue, et atterrit telle quelle dans le compte CHECKING cree en cascade.
    Mesure du 09/08 : `ZZZ`, `ANY` et la chaine vide produisent chacun un compte
    porteur de cette valeur.

    **C'est l'origine de FRA-222** — le compte client reel portant
    `currency="ANY"`. La recommandation n°4 de ce ticket demandait d'identifier
    le chemin d'ecriture fautif : c'est celui-ci.
    """

    @pytest.mark.parametrize("devise", ["ZZZ", "ANY", "", "cv", "00", "EUR", "USD"])
    def test_devise_hors_zone_refusee_avant_envoi(self, devise: str) -> None:
        with pytest.raises(OnboardingNonConforme, match="currency"):
            valider_onboarding("699111222", identite(), devise)

    @pytest.mark.parametrize("devise", ["XAF", "XOF", "xaf", " xof "])
    def test_les_deux_devises_des_4_pays_passent(self, devise: str) -> None:
        assert valider_onboarding("699111222", identite(), devise)["phone"] == "699111222"

    def test_sans_devise_fournie_la_barriere_ne_se_declenche_pas(self) -> None:
        """`currency=None` laisse la validation aux appelants qui ne la portent
        pas — la souscription, par exemple."""
        assert valider_onboarding("699111222", identite(), None)["id_number"] == "CM12345678"

    def test_le_message_nomme_le_ticket_et_explique_le_chemin(self) -> None:
        with pytest.raises(OnboardingNonConforme) as erreur:
            valider_onboarding("699111222", identite(), "ANY")
        message = str(erreur.value)
        assert "FRA-222" in message
        assert "compte CHECKING" in message

    def test_le_referentiel_serveur_n_est_pas_la_source_de_verite(self) -> None:
        """config-service contient lui-meme `cv` et `00` (FRA-222). La liste
        close du Loader est la seule reference fiable."""
        assert DEVISES_AUTORISEES == {"XAF", "XOF"}


class TestPlafondSouscriptions:
    """UC-13 — « 1 a 3 souscriptions a des produits Collecte ».

    Le serveur ne borne RIEN : mesure du 09/08, **6 produits** ont ete attaches
    a un meme client sans le moindre rejet. Le plafond du CDC est entierement a
    notre charge.
    """

    def test_le_plafond_du_cdc_est_de_trois(self) -> None:
        assert SOUSCRIPTIONS_MAX == 3
