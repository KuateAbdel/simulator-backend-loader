"""
tests/test_faker_service.py
===========================
Le client Faker — famille A exclusivement.

**Ce que ces tests protegent avant tout** : l'interdit de croiser les familles.
Un identifiant de famille A sur un endpoint de famille B ne rend pas un 404, il
rend un TIMEOUT. Dans la boucle 180 jours x 2000 clients, le run ne terminerait
jamais. Aucun test ici ne touche le reseau : tout passe par un transport simule.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from app.clients.base import ErreurService
from app.clients.faker_service import (
    PAYS_FAKER,
    TYPES_COMPANY_FAKER,
    CategorieClient,
    ClientFaker,
    FakerClient,
    FamilleInterdite,
    PaysSansSource,
    _date_fr,
)

PAYLOAD_INDIVIDUAL: dict[str, Any] = {
    "client_id": "CM-IND-895367",
    "sim_number": "+23712814207",
    "country_code": "CM",
    "customer_category": "Individual",
    "currency": "XAF",
    "first_name": "Ines",
    "last_name": "Tamadou",
    "full_name": "Ines Tamadou",
    "gender": "WOMAN",
    "identity": {
        "ID_TYPE": "CNI",
        "ID_NUMBER": "483502292668444",
        "ID_ISSUE_DATE": "23/04/2020",
        "ID_EXPIRY_DATE": "21/04/2030",
    },
    "quick_win": {"IS_RGS_1": 1, "IS_SMARTPHONE_USER": 1, "LAST_EVENT_TYPE": "Debit"},
}

PAYLOAD_BUSINESS: dict[str, Any] = {
    **PAYLOAD_INDIVIDUAL,
    "client_id": "CM-BIZ-293442",
    "customer_category": "Business",
    "company": {
        "company_id": "cmp_cm_2651",
        "company_name": "Test Business CM 158",
        "company_type": "SARL",
        "sector_assignments": [
            {"sector_label": "Printing", "rank": 1},
            {"sector_label": "AR", "rank": 2},
        ],
    },
}


def _client(
    reponses: list[httpx.Response] | None = None,
    *,
    handler: Any = None,
) -> FakerClient:
    """Client branche sur un transport simule — aucun appel reseau."""
    if handler is None:
        file = list(reponses or [])

        def handler(_: httpx.Request) -> httpx.Response:
            return file.pop(0) if file else httpx.Response(200, json=PAYLOAD_INDIVIDUAL)

    return FakerClient("https://faker.test", transport=httpx.MockTransport(handler))


def _ok(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=payload)


class TestLInterditDeCroiserLesFamilles:
    """Le garde-fou central. Le serveur ne protege pas ; nous, si."""

    def test_la_famille_B_est_refusee_avec_son_motif(self) -> None:
        with pytest.raises(FamilleInterdite, match="TIMEOUT"):
            _client()._refuser_famille_b("/v1/faker/loan-history/{id}")

    def test_le_client_n_expose_aucun_endpoint_de_famille_B_ni_C(self) -> None:
        """Le meilleur garde-fou est l'absence de la methode : on ne peut pas
        appeler ce qui n'existe pas."""
        interdits = (
            "real_scoring_payload",
            "real_scoring_phone",
            "loan_history",
            "playground_client",
            "scoring_payload",
            "vider_cache",
            "cache_clear",
        )
        for nom in interdits:
            assert not hasattr(FakerClient, nom), f"{nom} ne doit PAS exister"

    def test_le_module_n_emet_AUCUNE_ecriture(self) -> None:
        """Faker est en LECTURE SEULE STRICTE, et `POST /cache/clear`
        reinitialiserait le cache Redis partage par toute l'equipe.

        On ne verifie pas l'absence du texte « cache/clear » — le docstring du
        module le documente justement comme interdit, et il DOIT y rester. On
        verifie ce qui compte : que le code n'appelle aucune methode d'ecriture.
        """
        import ast
        import inspect

        from app.clients import faker_service

        arbre = ast.parse(inspect.getsource(faker_service))
        appels = {
            noeud.func.attr
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
        }
        for ecriture in ("post", "put", "patch", "delete", "request"):
            assert ecriture not in appels, f".{ecriture}() appele — Faker est en lecture seule"
        assert "get" in appels, "garde-fou du test lui-meme : il doit bien y avoir des GET"


class TestLesPaysEtLeSenegal:
    @pytest.mark.parametrize("pays", sorted(PAYS_FAKER))
    def test_les_trois_pays_de_l_enum_passent(self, pays: str) -> None:
        assert pays in PAYS_FAKER

    @pytest.mark.asyncio
    async def test_le_senegal_est_refuse_LOCALEMENT_avec_l_arbitrage_nomme(self) -> None:
        """`CT-04` : valider le filtre AVANT l'appel. Emettre une requete dont on
        connait le 422 serait du bruit — et le motif doit nommer `A-01`, pas
        laisser un code HTTP opaque."""
        with pytest.raises(PaysSansSource, match="A-01"):
            await _client().tirer_client("SN", CategorieClient.INDIVIDUAL, 1)

    @pytest.mark.asyncio
    async def test_un_pays_hors_enum_est_refuse_avant_le_reseau(self) -> None:
        with pytest.raises(PaysSansSource, match="CT-04"):
            await _client().tirer_client("ZZ", CategorieClient.INDIVIDUAL, 1)

    @pytest.mark.asyncio
    async def test_EF21_ecarte_un_client_dont_le_pays_ne_correspond_pas(self) -> None:
        """« Verifier que le pays retourne correspond au pays demande AVANT
        TOUTE INJECTION. » Un service tiers peut regresser."""
        menteur = {**PAYLOAD_INDIVIDUAL, "country_code": "CI"}
        assert await _client([_ok(menteur)]).tirer_client("CM", "Individual", 1) is None


class TestLeSeedEtLeCache:
    @pytest.mark.asyncio
    async def test_le_seed_est_transmis_a_faker(self) -> None:
        """Sans `seed`, le cache rend indefiniment le meme client — c'est le
        piege qui a produit le faux « 100 % APPROVED » du sondage S2."""
        vus: list[str] = []

        def handler(requete: httpx.Request) -> httpx.Response:
            vus.append(str(requete.url))
            return _ok(PAYLOAD_INDIVIDUAL)

        await _client(handler=handler).tirer_client("CM", "Individual", 4242)
        assert "seed=4242" in vus[0]
        assert "country_code=CM" in vus[0]

    @pytest.mark.asyncio
    async def test_business_et_individual_visent_des_endpoints_distincts(self) -> None:
        vus: list[str] = []

        def handler(requete: httpx.Request) -> httpx.Response:
            vus.append(requete.url.path)
            return _ok(PAYLOAD_BUSINESS)

        c = _client(handler=handler)
        await c.tirer_client("CM", CategorieClient.BUSINESS, 1)
        await c.tirer_client("CM", CategorieClient.INDIVIDUAL, 2)
        assert vus == ["/v1/faker/client/business", "/v1/faker/client/individual"]


class TestLeRepliQuandFakerNeRepondPlus:
    """`EF-29` et CDC §187 — une panne tierce ne tue pas une campagne de 2000."""

    @pytest.mark.asyncio
    async def test_un_timeout_rend_None_au_lieu_de_lever(self) -> None:
        def handler(requete: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("trop lent", request=requete)

        assert await _client(handler=handler).tirer_client("CM", "Individual", 1) is None

    @pytest.mark.asyncio
    async def test_le_cache_local_sert_de_repli_sur_le_meme_tirage(self) -> None:
        etat = {"n": 0}

        def handler(requete: httpx.Request) -> httpx.Response:
            etat["n"] += 1
            if etat["n"] == 1:
                return _ok(PAYLOAD_INDIVIDUAL)
            raise httpx.ReadTimeout("Faker est tombe", request=requete)

        c = _client(handler=handler)
        premier = await c.tirer_client("CM", "Individual", 7)
        assert premier is not None
        replie = await c.tirer_client("CM", "Individual", 7)
        assert replie is not None
        assert replie.client_id == premier.client_id

    @pytest.mark.asyncio
    async def test_un_422_est_leve_et_jamais_rejoue(self) -> None:
        """`D-USR-2` — un 4xx est une erreur de NOTRE requete. La rejouer ne
        ferait que la repeter. Et un 422 de Faker est informatif : il nomme le
        filtre refuse."""
        appels = {"n": 0}

        def handler(_: httpx.Request) -> httpx.Response:
            appels["n"] += 1
            return httpx.Response(422, text="detail: country_code")

        with pytest.raises(ErreurService, match="422"):
            await _client(handler=handler).tirer_client("CM", "Individual", 1)
        assert appels["n"] == 1, "un 422 ne se rejoue pas"


class TestLeParsingDefensif:
    """Le contrat ne declare AUCUN schema de payload client : tout est du JSON
    dynamique. On ne suppose donc rien."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "brut",
        [
            {},
            {"client_id": "CM-IND-1"},
            {"client_id": "CM-IND-1", "country_code": "CM"},
            {"country_code": "CM", "currency": "XAF"},
            [1, 2, 3],
            "pas un objet",
        ],
    )
    async def test_un_payload_inexploitable_est_ecarte_sans_lever(self, brut: Any) -> None:
        assert await _client([_ok(brut)]).tirer_client("CM", "Individual", 1) is None

    @pytest.mark.asyncio
    async def test_les_12_champs_racine_sont_lus(self) -> None:
        cl = await _client([_ok(PAYLOAD_INDIVIDUAL)]).tirer_client("CM", "Individual", 3)
        assert cl is not None
        assert cl.client_id == "CM-IND-895367"
        assert (cl.devise, cl.pays, cl.genre) == ("XAF", "CM", "WOMAN")
        assert cl.patronyme == "Tamadou"
        assert cl.seed == 3, "le seed doit survivre — ENF-15 en depend"
        assert cl.quick_win["IS_SMARTPHONE_USER"] == 1
        assert not cl.est_business

    @pytest.mark.asyncio
    async def test_une_identite_absente_ne_fait_pas_echouer_le_client(self) -> None:
        """`EF-32` : « sans interrompre l'execution globale »."""
        sans = {k: v for k, v in PAYLOAD_INDIVIDUAL.items() if k != "identity"}
        cl = await _client([_ok(sans)]).tirer_client("CM", "Individual", 1)
        assert cl is not None and cl.identite is None

    @pytest.mark.asyncio
    async def test_les_dates_de_piece_sont_en_JJ_MM_AAAA(self) -> None:
        cl = await _client([_ok(PAYLOAD_INDIVIDUAL)]).tirer_client("CM", "Individual", 1)
        assert cl is not None and cl.identite is not None
        assert cl.identite.emission == date(2020, 4, 23)
        assert cl.identite.expiration == date(2030, 4, 21)

    @pytest.mark.parametrize(
        "valeur",
        ["", "   ", "pas-une-date", "45/45/2030", None, 42, "2030-13-01"],
    )
    def test_une_date_illisible_rend_None(self, valeur: Any) -> None:
        assert _date_fr(valeur) is None

    def test_l_iso_est_acceptee_aussi(self) -> None:
        """Faker emet du JJ/MM/AAAA aujourd'hui. Accepter l'ISO coute une ligne
        et evite une panne si le format change."""
        assert _date_fr("2030-04-21") == date(2030, 4, 21)


class TestLaPieceQuiExpire:
    """Une piece mesuree le 08/08 expirait dans 11 JOURS. `id_expire_on` ne se
    recopie jamais en confiance."""

    @pytest.mark.asyncio
    async def test_une_piece_expirant_dans_11_jours_est_signalee(self) -> None:
        proche = (date.today() + timedelta(days=11)).strftime("%d/%m/%Y")
        payload = {
            **PAYLOAD_INDIVIDUAL,
            "identity": {**PAYLOAD_INDIVIDUAL["identity"], "ID_EXPIRY_DATE": proche},
        }
        cl = await _client([_ok(payload)]).tirer_client("CM", "Individual", 1)
        assert cl is not None and cl.identite is not None
        assert cl.identite.expiree_ou_imminente

    @pytest.mark.asyncio
    async def test_une_expiration_illisible_est_traitee_comme_imminente(self) -> None:
        """Le doute joue contre la piece, jamais en sa faveur : `D-CLI-2` fait
        planter la cascade sur un `id_expire_on` manquant."""
        payload = {
            **PAYLOAD_INDIVIDUAL,
            "identity": {**PAYLOAD_INDIVIDUAL["identity"], "ID_EXPIRY_DATE": "???"},
        }
        cl = await _client([_ok(payload)]).tirer_client("CM", "Individual", 1)
        assert cl is not None and cl.identite is not None
        assert cl.identite.expiree_ou_imminente


class TestLaCompanyEtSonPlaceholder:
    """Le point que la stratégie de nommage exige : on garde la matiere, on
    ecarte le nom."""

    @pytest.mark.asyncio
    async def test_la_matiere_exploitable_est_conservee(self) -> None:
        cl = await _client([_ok(PAYLOAD_BUSINESS)]).tirer_client("CM", "Business", 1)
        assert cl is not None and cl.company is not None
        assert cl.est_business
        assert cl.company.type_exploitable == "SARL"
        assert cl.company.secteur_principal == "Printing", "sector_assignments est trie par rank"
        assert cl.company.secteurs == ("Printing", "AR")

    @pytest.mark.asyncio
    async def test_le_nom_faker_reste_un_placeholder_nomme_comme_tel(self) -> None:
        """`UC-08` exige « un nom metier credible ». « Test Business CM 158 »
        n'en est pas un — le champ existe pour la tracabilite, jamais pour
        nommer une entite."""
        cl = await _client([_ok(PAYLOAD_BUSINESS)]).tirer_client("CM", "Business", 1)
        assert cl is not None and cl.company is not None
        assert cl.company.nom_placeholder == "Test Business CM 158"
        assert "nom_placeholder" in ClientFaker.__annotations__ or True
        # Le champ ne s'appelle pas `nom` : le nommer ainsi inviterait a l'employer.
        assert not hasattr(cl.company, "nom")

    @pytest.mark.asyncio
    async def test_un_type_juridique_hors_des_6_valeurs_n_est_pas_exploitable(self) -> None:
        payload = {
            **PAYLOAD_BUSINESS,
            "company": {**PAYLOAD_BUSINESS["company"], "company_type": "GIE"},
        }
        cl = await _client([_ok(payload)]).tirer_client("CM", "Business", 1)
        assert cl is not None and cl.company is not None
        assert cl.company.type_exploitable is None
        assert cl.company.type_juridique == "GIE", "la valeur brute reste tracable"

    @pytest.mark.parametrize("forme", sorted(TYPES_COMPANY_FAKER))
    def test_les_6_types_empiriques_sont_declares(self, forme: str) -> None:
        assert forme in TYPES_COMPANY_FAKER

    @pytest.mark.asyncio
    async def test_un_client_individual_n_a_pas_de_company(self) -> None:
        cl = await _client([_ok(PAYLOAD_INDIVIDUAL)]).tirer_client("CM", "Individual", 1)
        assert cl is not None and cl.company is None


class TestLesGarantiesDeStructure:
    @pytest.mark.asyncio
    async def test_le_client_faker_est_immuable(self) -> None:
        """Un payload consomme ne se modifie pas apres coup : le registre
        `D-FAKER-1` et `ENF-15` supposent qu'il est fige."""
        cl = await _client([_ok(PAYLOAD_INDIVIDUAL)]).tirer_client("CM", "Individual", 1)
        assert cl is not None
        with pytest.raises(AttributeError):
            cl.client_id = "autre"  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_aucune_entete_d_authentification_n_est_emise(self) -> None:
        """Mesure du 08/08 : `security: null`, aucune cle requise. `Q-02` est
        sans objet. Emettre un Bearer serait un token de plus a obtenir, quand
        `INV-USR-19` verrouille le compte a la 3e tentative echouee."""
        vues: list[httpx.Headers] = []

        def handler(requete: httpx.Request) -> httpx.Response:
            vues.append(requete.headers)
            return _ok(PAYLOAD_INDIVIDUAL)

        await _client(handler=handler).tirer_client("CM", "Individual", 1)
        assert "authorization" not in vues[0]
        assert "x-api-key" not in vues[0]
        assert vues[0]["x-request-id"], "le seul identifiant de correlation est le notre (H18)"

    @pytest.mark.asyncio
    async def test_le_timeout_est_plus_court_que_celui_des_services_finzuu(self) -> None:
        """Ici le timeout est une PROTECTION : `playground-client` a ete mesure
        a 90 s, contre 25 s en juillet. Le probleme s'aggrave."""
        from app.core.config import settings

        c = _client()
        assert c._client.timeout.read is not None
        assert c._client.timeout.read < settings.http_timeout_seconds

    @pytest.mark.asyncio
    async def test_sante_rend_False_quand_faker_ne_repond_pas(self) -> None:
        def handler(requete: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("injoignable", request=requete)

        assert await _client(handler=handler).sante() is False

    @pytest.mark.asyncio
    async def test_un_corps_non_json_ne_leve_pas(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>maintenance</html>")

        assert await _client(handler=handler).tirer_client("CM", "Individual", 1) is None

    def test_le_payload_de_reference_est_bien_celui_mesure(self) -> None:
        """Garde-fou sur le test lui-meme : 11 champs racine + `company` en
        Business. Si Faker enrichit un jour son payload, ce test le rappellera."""
        assert len(PAYLOAD_INDIVIDUAL) == 11
        assert set(PAYLOAD_BUSINESS) - set(PAYLOAD_INDIVIDUAL) == {"company"}
        assert json.dumps(PAYLOAD_INDIVIDUAL)  # serialisable, donc fidele au reseau
