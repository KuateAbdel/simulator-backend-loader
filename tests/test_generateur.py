"""Tests du generateur — hors ligne, aucun appel reseau.

Il compose a partir de matiere reelle (patronymes, formes juridiques et
secteurs Faker, villes et quartiers Loader_Base). On verifie ici qu'il produit
des entites credibles ET conformes aux contraintes serveur mesurees.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from app.core.cdc import AGE_SEUIL_JEUNE
from app.services.generateur import Generateur

RUN_ID = UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture
def generateur() -> Generateur:
    return Generateur(RUN_ID)


class TestRaisonSociale:
    def test_credible_et_sans_prefixe(self, generateur: Generateur) -> None:
        """UC-08 exige « un nom metier credible ». Faker renvoie
        « Test Business CM 748 » — on compose mieux, a partir de sa matiere.
        SANS prefixe (decision direction 20/08) : le nom est entierement
        metier, la reconnaissance est au REGISTRE."""
        nom = generateur.raison_sociale("Kouassi", "SARL", "Textile")
        assert not nom.startswith("DEMO_")
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
        assert generateur.nom_kiosque("Bepanda") == "Kiosque Bepanda"

    def test_les_accents_sont_retires(self, generateur: Generateur) -> None:
        assert "é" not in generateur.nom_agence("Bobo-Dioulassé")


class TestIdentite:
    def _identite(self, generateur: Generateur, *, jeune: bool, ancre: str = "CM-IND-1"):  # type: ignore[no-untyped-def]
        return generateur.identite(
            # `CR-03`, 12/08 : la date de naissance est ancree au CLIENT, plus au
            # run. Elle tirait dans `self._alea`, seme par le `run_id` — une
            # reprise donnait donc une AUTRE date de naissance au meme client.
            ancre_client=ancre,
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


class TestAucunRepliSilencieux:
    """Doctrine — *« rigide a l'execution : le Loader echoue bruyamment sur
    l'inconnu »*.

    Deux replis silencieux vivaient dans `generateur.py` jusqu'au 09/08 :
    un pays inconnu devenait senegalais, un genre inconnu devenait feminin.
    Ni l'un ni l'autre n'aurait laisse la moindre trace dans un rapport.
    """

    def test_un_pays_hors_perimetre_leve_au_lieu_de_devenir_senegalais(self) -> None:
        """`patronyme("ZZ", 0)` rendait « Diallo ». `EF-05` borne a 4 pays."""
        from app.services.generateur import patronyme

        with pytest.raises(ValueError, match="hors des 4 cibles"):
            patronyme("ZZ", 0)

    def test_les_quatre_pays_du_cdc_passent(self) -> None:
        from app.core.cdc import PAYS_CIBLES
        from app.services.generateur import patronyme

        assert all(patronyme(p, 0) for p in PAYS_CIBLES)

    def test_un_genre_inconnu_leve_au_lieu_de_devenir_feminin(self) -> None:
        """Le serveur ne valide PAS `gender` (`D-IDN-1`). Un repli aurait
        fausse le quota « deux femmes pour un homme » sans trace."""
        from app.services.generateur import prenom

        with pytest.raises(ValueError, match="genre 'ANY' inconnu"):
            prenom("ANY", 0)

    def test_male_et_female_donnent_des_prenoms_distincts(self) -> None:
        from app.services.generateur import prenom

        assert prenom("MALE", 0) != prenom("FEMALE", 0)


class TestMsisdnUnicite:
    """`EF-25` — « unicite des MSISDN generes au sein d'une meme execution ».

    Ces trois tests scellent un defaut que **la suite n'avait pas attrape** : je
    l'ai trouve en mesurant 2000 clients a la main. Le corps etait pris
    litteralement chez Faker, or un `sim_number` depouille commence par
    l'indicatif pays et `composer_msisdn` consomme le corps depuis la position 0
    — le Cameroun brulait ses sept chiffres sur `2373810` sans jamais atteindre
    la partie distinctive. Echec au HUITIEME client.

    Le premier test rejoue exactement cette matiere : des numeros qui ne
    divergent que dans leurs chiffres de poids faible, c'est-a-dire le cas que
    le plan de numerotation tronque.
    """

    @pytest.fixture
    def referentiel(self):  # type: ignore[no-untyped-def]
        from pathlib import Path

        from app.services.geographie import charger_referentiel

        return charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))

    @pytest.mark.parametrize("pays", ["CM", "CI", "BF", "SN"])
    def test_cinq_cents_numeros_a_suffixe_variable_restent_distincts(
        self, generateur: Generateur, referentiel, pays: str  # type: ignore[no-untyped-def]
    ) -> None:
        indicatif = referentiel.indicatif(pays)
        emis = {
            generateur.msisdn(pays, referentiel, f"+{indicatif}{38000000 + rang}")[0]
            for rang in range(500)
        }
        assert len(emis) == 500, f"{pays} : {500 - len(emis)} collisions"

    def test_tous_conformes_au_plan_de_numerotation(
        self, generateur: Generateur, referentiel  # type: ignore[no-untyped-def]
    ) -> None:
        """`EF-27` — l'unicite ne doit pas s'acheter en sortant du plan reel."""
        for rang in range(200):
            numero, operateur = generateur.msisdn(
                "CM", referentiel, f"+237{38000000 + rang}"
            )
            assert referentiel.operateur_du_msisdn(numero, "CM") is not None
            assert operateur is not None

    def test_le_meme_client_rend_le_meme_numero(self, referentiel) -> None:  # type: ignore[no-untyped-def]
        """`ENF-15` — l'ancrage au client survit a la dispersion. Deux
        generateurs du meme run, meme matiere, meme numero."""
        a = Generateur(RUN_ID).msisdn("CM", referentiel, "+23738101955")[0]
        b = Generateur(RUN_ID).msisdn("CM", referentiel, "+23738101955")[0]
        assert a == b

    def test_le_registre_refuse_de_rendre_un_doublon(
        self, generateur: Generateur, referentiel  # type: ignore[no-untyped-def]
    ) -> None:
        """Deux clients DIFFERENTS ne partagent jamais un numero, meme si la
        matiere de l'un est identique a celle de l'autre — cas reel : deux
        Senegalais sans `sim_number` retombent sur le meme repli."""
        premier = generateur.msisdn("CM", referentiel, "meme-matiere")[0]
        second = generateur.msisdn("CM", referentiel, "meme-matiere")[0]
        assert premier != second


class TestDateDeNaissanceAncreeAuClient:
    """`CR-03` — la date de naissance est fonction du CLIENT, jamais du run.

    Elle tirait dans `self._alea`, seme par le `run_id` : une reprise donnait donc
    une AUTRE date de naissance au meme client. Meme famille exacte que le defaut
    msisdn (`D-CLI-11`), et meme consequence — un client dont l'identite change
    d'un run a l'autre n'est pas le meme client.

    **Defaut trouve par MUTATION le 12/08**, pas par relecture : remettre
    `random.Random()` sans graine ne faisait echouer AUCUN test.

    Cette correction en debloque une seconde : l'age devient calculable avant la
    composition, donc le profil comportemental (`EF-67`) peut se decider dans le
    temps sequentiel, ou les quotas se tiennent.
    """

    REFERENCE = date(2026, 8, 12)

    def test_le_meme_client_rend_TOUJOURS_la_meme_date(self) -> None:
        from app.services.generateur import date_de_naissance_du_client

        a = date_de_naissance_du_client("CM-IND-42", jeune=True, reference=self.REFERENCE)
        b = date_de_naissance_du_client("CM-IND-42", jeune=True, reference=self.REFERENCE)
        assert a == b

    def test_deux_clients_DIFFERENTS_ont_des_dates_differentes(self) -> None:
        from app.services.generateur import date_de_naissance_du_client

        dates = {
            date_de_naissance_du_client(f"CM-IND-{r}", jeune=True, reference=self.REFERENCE)
            for r in range(500)
        }
        assert len(dates) > 400, (
            f"{len(dates)} dates pour 500 clients — une population dont les ages "
            "se repetent n'est pas credible"
        )

    def test_deux_RUNS_rendent_la_meme_date_pour_le_meme_client(self) -> None:
        """LA propriete que la mutation a revelee non testee."""
        a = Generateur(UUID(int=1), reference=self.REFERENCE)
        b = Generateur(UUID(int=999), reference=self.REFERENCE)
        commun = {
            "first_name": "Aya", "last_name": "Tamadou", "gender": "WOMAN",
            "country_code": "CM", "ville": "Douala", "region": "Littoral",
            "quartier": "Bepanda", "telephone": "+237612345678",
            "jeune": True, "ancre_client": "CM-IND-7",
        }
        assert a.identite(**commun).date_of_birth == b.identite(**commun).date_of_birth

    def test_EF_22_les_deux_tranches_sont_respectees(self) -> None:
        from app.core.cdc import AGE_SEUIL_JEUNE
        from app.services.clients_execution import age_revolu
        from app.services.generateur import date_de_naissance_du_client

        for rang in range(300):
            jeune = date_de_naissance_du_client(
                f"CM-IND-{rang}", jeune=True, reference=self.REFERENCE
            )
            age_jeune = age_revolu(jeune, self.REFERENCE)
            assert 18 <= age_jeune < AGE_SEUIL_JEUNE, age_jeune

            age = age_revolu(
                date_de_naissance_du_client(
                    f"CM-IND-{rang}", jeune=False, reference=self.REFERENCE
                ),
                self.REFERENCE,
            )
            assert AGE_SEUIL_JEUNE <= age <= 65, age
