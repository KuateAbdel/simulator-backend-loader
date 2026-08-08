"""Tests du generateur — hors ligne, aucun appel reseau.

Il compose a partir de matiere reelle (patronymes, formes juridiques et
secteurs Faker, villes et quartiers Loader_Base). On verifie ici qu'il produit
des entites credibles ET conformes aux contraintes serveur mesurees.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from app.core.cdc import AGE_SEUIL_JEUNE, PREFIXE_DONNEES
from app.services.generateur import Generateur

RUN_ID = UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def generateur() -> Generateur:
    return Generateur(RUN_ID)


class TestRaisonSociale:
    def test_credible_et_prefixee(self, generateur: Generateur) -> None:
        """UC-08 exige « un nom metier credible ». Faker renvoie
        « Test Business CM 748 » — on compose mieux, a partir de sa matiere."""
        nom = generateur.raison_sociale("Kouassi", "SARL", "Textile")
        assert nom.startswith(PREFIXE_DONNEES)
        assert "Kouassi" in nom and "SARL" in nom
        assert "Test Business" not in nom

    def test_une_fondation_ne_porte_pas_de_suffixe_commercial(self, generateur: Generateur) -> None:
        nom = generateur.raison_sociale("Ouedraogo", "Fondation")
        assert "Fondation" in nom
        assert not any(s in nom for s in ("& Fils", "& Freres", "et Cie", "Negoce"))

    def test_forme_inconnue_retombe_sur_sarl(self, generateur: Generateur) -> None:
        assert "SARL" in generateur.raison_sociale("Tamadou", "FORME_INEXISTANTE")

    def test_le_kiosque_porte_son_quartier(self, generateur: Generateur) -> None:
        """depositary-service n'a AUCUN champ geographique : le nom est le seul
        endroit ou l'ancrage reste visible."""
        assert generateur.nom_kiosque("Bepanda") == f"{PREFIXE_DONNEES}Kiosque Bepanda"

    def test_les_accents_sont_retires(self, generateur: Generateur) -> None:
        assert "é" not in generateur.nom_agence("Bobo-Dioulassé")


class TestIdentite:
    def _identite(self, generateur: Generateur, *, jeune: bool):  # type: ignore[no-untyped-def]
        return generateur.identite(
            first_name="Ines",
            last_name="Tamadou",
            gender="WOMAN",
            country_code="cm",
            ville="Douala",
            region="Littoral",
            quartier="Bepanda",
            telephone="+237612345678",
            jeune=jeune,
        )

    def test_champs_manquants_chez_faker_sont_completes(self, generateur: Generateur) -> None:
        """Faker famille A ne fournit ni date de naissance, ni adresse, ni
        occupation, ni email. Le Loader les compose."""
        i = self._identite(generateur, jeune=True)
        assert i.date_of_birth < date.today()
        assert i.occupation and i.email and i.adresse.address_line_1
        assert i.nationality == "CM", (
            "nationality exige un code ISO 3166-1 alpha-2 — « Cameroun » "
            "provoque un HTTP 422 (mesure du 08/08)"
        )
        assert i.adresse.country == "CM", "le pays est normalise en majuscules"

    def test_id_number_alphanumerique_majuscules(self, generateur: Generateur) -> None:
        """D-CLI-3 : un underscore provoque un HTTP 400 « id_number format invalid »."""
        numero = self._identite(generateur, jeune=True).id_number
        assert numero.isalnum() and numero.isupper()

    def test_id_expire_on_toujours_dans_le_futur(self, generateur: Generateur) -> None:
        """D-CLI-2 / D-DEP-5 / FRA-200 : son absence fait planter le serveur,
        et une piece expiree serait incoherente pour un client actif."""
        assert self._identite(generateur, jeune=True).id_expire_on > date.today()

    def test_quota_des_moins_de_25_ans(self, generateur: Generateur) -> None:
        """EF-22 — Faker n'expose aucun filtre d'age, le quota se pilote ici."""
        jeune = self._identite(generateur, jeune=True)
        age_jeune = (date.today() - jeune.date_of_birth).days // 365
        assert age_jeune < AGE_SEUIL_JEUNE

        ancien = self._identite(generateur, jeune=False)
        age_ancien = (date.today() - ancien.date_of_birth).days // 365
        assert age_ancien >= AGE_SEUIL_JEUNE

    def test_l_adresse_est_ancree_sur_un_quartier_reel(self, generateur: Generateur) -> None:
        i = self._identite(generateur, jeune=True)
        assert "Bepanda" in i.adresse.street_name
        assert i.adresse.city == "Douala"

    def test_le_payload_porte_les_13_champs_requis(self, generateur: Generateur) -> None:
        """Identity embarquee : `_id` REQUIS et fourni par l'appelant."""
        payload = self._identite(generateur, jeune=True).en_payload()
        for champ in (
            "_id",
            "type",
            "first_name",
            "date_of_birth",
            "gender",
            "nationality",
            "id_number",
            "id_place",
            "phone",
            "email",
            "occupation",
            "address",
            "id_expire_on",
        ):
            assert champ in payload, f"{champ} manquant"


class TestUnicite:
    def test_les_emails_ne_collisionnent_jamais(self, generateur: Generateur) -> None:
        """INV-USR-02 : user-service impose l'unicite de l'email. On la garantit
        chez nous plutot que de decouvrir le conflit en HTTP 400."""
        emails = [generateur.email("Ines", "Tamadou") for _ in range(50)]
        assert len(set(emails)) == 50

    def test_le_domaine_n_existe_pas(self, generateur: Generateur) -> None:
        """Aucune adresse generee ne doit pouvoir atteindre une vraie boite."""
        assert generateur.email("Ines", "Tamadou").endswith(".local")


class TestReproductibilite:
    def test_meme_run_id_meme_resultat(self) -> None:
        """ENF-15 : deux executions de meme run_id produisent strictement le
        meme ecosysteme."""
        a = Generateur(RUN_ID)
        b = Generateur(RUN_ID)
        assert a.raison_sociale("Kouassi", "SARL") == b.raison_sociale("Kouassi", "SARL")
        assert a.numero_piece("CM") == b.numero_piece("CM")

    def test_run_id_different_resultat_different(self) -> None:
        autre = Generateur(UUID("99999999-8888-7777-6666-555555555555"))
        reference = Generateur(RUN_ID)
        assert autre.numero_piece("CM") != reference.numero_piece("CM")


def test_mot_de_passe_initial_respecte_une_politique_forte(generateur: Generateur) -> None:
    """Il sera change immediatement par le flow en 3 requetes — il doit
    seulement passer la politique du serveur."""
    mdp = generateur.mot_de_passe_initial()
    assert len(mdp) >= 12
    assert any(c.isupper() for c in mdp) and any(c.isdigit() for c in mdp)
    assert any(not c.isalnum() for c in mdp)
