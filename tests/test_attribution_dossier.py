"""
tests/test_attribution_dossier.py
=================================
Les preuves de la FACE DOSSIER du tableau de bord d'attribution —
spec FZ-SPEC-DASHATTRIB-2026-001, inventaire FZ-INV-ATTRIB-2026-001.

Ce qui n'existe que si un test le prouve :

  1. LE DOSSIER 360° — chaque bloc porte sa donnee OU sa raison d'absence,
     toujours en HTTP 200 ; une panne d'account-service n'emporte pas
     l'identite qui a repondu (spec §9, resolue bloc par bloc).
  2. LES REGLES D'AFFICHAGE tenues PAR LE SERVEUR : AFF-02 (identity.type
     n'atteint jamais la reponse), AFF-03 (status de fiche exclu par
     construction), AFF-04 (le champ se nomme rattache), AFF-07 (deux noeuds
     pour un meme numero -> le run le plus recent fait foi), AFF-08 (les
     produits viennent de la fiche serveur).
  3. LA VUE DE MASSE RESTE LOCALE : territoire dans la liste sans un seul
     appel plateforme — les doubles COMPTENT leurs appels et le test echoue
     s'il y en a un (ENF-D01 prouve, pas affirme).
  4. LES REFUS 409 laissent trace au journal, reponse inchangee.
  5. LE MECANISME PUBLIC IGNORE l'interlocuteur : un rejeu d'idempotence
     rend le meme corps qu'avant le nommage.

Contre Mongo REEL ; la plateforme est DOUBLEE aux fabriques du routeur —
le meme motif que `_config_service_double` (test_admin_api).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from app.core import database
from app.core.config import settings
from app.main import app
from app.repositories.super_admin import SuperAdminRepository

pytestmark = pytest.mark.asyncio

EMAIL = "pilote-dossier@finzuu.com"
MDP_INITIAL = "initial-bootstrap-6633"
MDP_DURABLE = "boussole-granit-avoine-27aout"

ROUTE_PUBLIQUE = "/api/v1/attribution/attributions"
PROFIL_CM = {"pays": "CM", "genre": "FEMALE", "categorie": "INDIVIDUAL"}

_INDEX_POSES = False


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[httpx.AsyncClient]:
    global _INDEX_POSES
    database.connect()
    settings.mongodb_database = "loader_finzuu_tests_dossier"
    if not _INDEX_POSES:
        await database.ensure_indexes()
        _INDEX_POSES = True
    for nom in (
        database.COLLECTION_ORG_HIERARCHY,
        database.COLLECTION_LOADER_RUNS,
        database.COLLECTION_ATTRIBUTION_BAUX,
        database.COLLECTION_ATTRIBUTION_REGLAGES,
        database.COLLECTION_AUDIT_TRAIL,
        database.COLLECTION_SUPER_ADMIN_ACCOUNTS,
        database.COLLECTION_AUTH_THROTTLE,
    ):
        await database.get_collection(nom).delete_many({})
    await SuperAdminRepository().creer(EMAIL, MDP_INITIAL, role="super_admin")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    database.close()


async def _entetes(client: httpx.AsyncClient) -> dict[str, str]:
    ouverture = await client.post(
        "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": MDP_INITIAL}
    )
    if ouverture.status_code != 200:  # mdp deja durable (fixture rejouee)
        ouverture = await client.post(
            "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": MDP_DURABLE}
        )
        assert ouverture.status_code == 200, ouverture.text
        return {"Authorization": f"Bearer {ouverture.json()['access_token']}"}
    reponse = await client.post(
        "/admin/auth/password",
        json={"ancien": MDP_INITIAL, "nouveau": MDP_DURABLE},
        headers={"Authorization": f"Bearer {ouverture.json()['access_token']}"},
    )
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


# ── Le SEMIS : un arbre complet, branche -> agence -> kiosque -> client ────


async def _semer_arbre(
    msisdn: str,
    *,
    run_id: str | None = None,
    cree_le: datetime | None = None,
    kiosque_nom: str = "Kiosque Akwa Nord",
    city_id: str = "CM-LT-DLA",
) -> str:
    """Seme LA CHAINE complete pour un client — et le run qui la porte,
    date : c'est lui qui departage AFF-07."""
    run = run_id or str(uuid4())
    await database.get_collection(database.COLLECTION_LOADER_RUNS).insert_one(
        {"_id": run, "cree_le": cree_le or datetime.now(UTC), "status": "COMPLETED"}
    )
    arbre = database.get_collection(database.COLLECTION_ORG_HIERARCHY)
    branche_id, agence_id, kiosque_id = str(uuid4()), str(uuid4()), str(uuid4())
    commun = {"run_id": run, "company_id": str(uuid4()), "country_code": "CM"}
    await arbre.insert_many(
        [
            {
                "_id": branche_id, "niveau": "BRANCHE", "parent_id": None,
                "name": "Branche Littoral", "region_id": "CM-LT", **commun,
            },
            {
                "_id": agence_id, "niveau": "AGENCE", "parent_id": branche_id,
                "name": "Agence Douala", "city_id": city_id, **commun,
            },
            {
                "_id": kiosque_id, "niveau": "KIOSQUE", "parent_id": agence_id,
                "name": kiosque_nom, "district_id": "CM-LT-DLA-AKW",
                "depositary_id": str(uuid4()), **commun,
            },
            {
                "_id": str(uuid4()), "niveau": "CLIENT", "parent_id": kiosque_id,
                "name": f"Client {msisdn}", "client_id": str(uuid4()),
                "gender": "FEMALE", "categorie": "INDIVIDUAL",
                "product_ids": ["prd-1"], **commun,
            },
        ]
    )
    return run


async def _attribuer(client: httpx.AsyncClient, cle: str | None = None) -> dict[str, Any]:
    reponse = await client.post(
        ROUTE_PUBLIQUE, json=PROFIL_CM, headers={"Idempotency-Key": cle or str(uuid4())}
    )
    assert reponse.status_code == 201, reponse.text
    return dict(reponse.json())


# ── Les DOUBLES plateforme — ils COMPTENT leurs appels ─────────────────────

FICHE_INES: dict[str, Any] = {
    "_id": "cli-ines", "msisdn": "", "language": "fr", "segment": "MEDIUM",
    "category": "INDIVIDUAL", "account_id": "acc-ines", "status": "PENDING",
    "product": [{"name": "Collecte Journalière", "type": "COLLECT"}],
    "identity": {
        "first_name": "Ines", "last_name": "Kambire", "gender": "FEMALE",
        "marital_status": "MARRIED", "id_number": "CM-2026-0001",
        "type": "CORPORATE",  # LE piege AFF-02 : faux pour un particulier
        "address": {"city": "Douala", "region": "Littoral", "country": "CM",
                     "latitude": 4.048, "longitude": 9.7},
    },
}

COMPTE_INES: dict[str, Any] = {
    "_id": "acc-ines", "balance": 161981.6, "balance_avail": 161981.6,
    "currency": "XAF", "type": "CHECKING", "status": "ACTIVE",
    "account_number": "Z5B3UUZI4HRT", "direct_momo": True,
}


@pytest.fixture()
def _plateforme_double(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from app.routes import admin_attributions

    traces: dict[str, Any] = {"appels": [], "panne_comptes": False, "fiche": None}

    class _Clients:
        async def chercher_par_msisdn(self, msisdn: str) -> dict[str, Any] | None:
            traces["appels"].append(("clients", msisdn))
            fiche = traces["fiche"]
            if fiche is None:
                return None
            return {**fiche, "msisdn": msisdn}

        async def fermer(self) -> None:
            return None

    class _Comptes:
        async def compte(self, account_id: str) -> dict[str, Any] | None:
            traces["appels"].append(("comptes", account_id))
            if traces["panne_comptes"]:
                raise RuntimeError("account-service injoignable")
            return dict(COMPTE_INES)

        async def transactions_du_compte(self, account_id: str) -> list[dict[str, Any]]:
            traces["appels"].append(("transactions", account_id))
            return [
                {
                    "reference": "DEPOSIT-0001", "type": "DEPOSIT", "sens": "CREDIT",
                    "amount": 161981.6, "fees": 0,
                    "label": "Solde initial — Ines Kambire", "status": "SUCCESS",
                }
            ]

        async def fermer(self) -> None:
            return None

    class _Collectes:
        async def collectes_du_client(self, client_id: str) -> list[dict[str, Any]]:
            traces["appels"].append(("collectes", client_id))
            return []  # mesure du 25/08 : 0 — le module VIE n'existe pas

        async def fermer(self) -> None:
            return None

    traces["fiche"] = dict(FICHE_INES)
    monkeypatch.setattr(admin_attributions, "_client_clients", lambda: _Clients())
    monkeypatch.setattr(admin_attributions, "_client_comptes", lambda: _Comptes())
    monkeypatch.setattr(admin_attributions, "_client_collectes", lambda: _Collectes())
    return traces


# ══════════════════════════════════════════════════════════════════════════
# 1. LA VUE DE MASSE — locale, prouvee locale
# ══════════════════════════════════════════════════════════════════════════


class TestVueDeMasse:
    async def test_la_liste_porte_le_territoire_SANS_un_seul_appel_plateforme(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        """ENF-D01 prouve : le double compte les appels, il doit en rester ZERO."""
        await _semer_arbre("237600000001")
        entetes = await _entetes(client)
        bail = await _attribuer(client)

        reponse = await client.get("/admin/attributions", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        ligne = next(b for b in reponse.json()["baux"] if b["msisdn"] == bail["msisdn"])

        assert ligne["territoire"]["rattache_au_kiosque"] == "Kiosque Akwa Nord"
        assert ligne["territoire"]["pays"] == "CM"
        assert ligne["etat"] == "actif"
        assert "releve_le" in reponse.json(), "l'horloge serveur manque au releve"
        assert _plateforme_double["appels"] == [], (
            "la liste a appele la plateforme — ENF-D01 violee"
        )

    async def test_AFF07_le_rattachement_du_run_le_plus_recent_fait_foi(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        """Deux runs, deux kiosques pour le MEME numero : sans regle, deux
        ecrans montreraient deux kiosques. La derniere decision du Loader
        gagne."""
        msisdn = "237600000002"
        ancien = datetime.now(UTC) - timedelta(days=10)
        await _semer_arbre(msisdn, cree_le=ancien, kiosque_nom="Kiosque Ancien")
        await _semer_arbre(msisdn, kiosque_nom="Kiosque Recent")
        entetes = await _entetes(client)
        bail = await _attribuer(client)

        reponse = await client.get("/admin/attributions", headers=entetes)
        ligne = next(b for b in reponse.json()["baux"] if b["msisdn"] == bail["msisdn"])
        assert ligne["territoire"]["rattache_au_kiosque"] == "Kiosque Recent"

    async def test_un_viewer_ne_voit_pas_le_recensement(
        self, client: httpx.AsyncClient
    ) -> None:
        """Arbitrage RBAC 27/08 : lecture = admin minimum — le tableau montre
        du KYC, un role lecteur n'y accede pas."""
        await SuperAdminRepository().creer(
            "lecteur@finzuu.com", "initial-bootstrap-1199", role="viewer"
        )
        ouverture = await client.post(
            "/admin/auth/login",
            json={"email": "lecteur@finzuu.com", "mot_de_passe": "initial-bootstrap-1199"},
        )
        jeton = ouverture.json()["access_token"]
        reponse = await client.post(
            "/admin/auth/password",
            json={"ancien": "initial-bootstrap-1199", "nouveau": "sentier-ecorce-lagune-27a"},
            headers={"Authorization": f"Bearer {jeton}"},
        )
        entetes = {"Authorization": f"Bearer {reponse.json()['access_token']}"}
        assert (await client.get("/admin/attributions", headers=entetes)).status_code == 403


# ══════════════════════════════════════════════════════════════════════════
# 2. LE DOSSIER 360°
# ══════════════════════════════════════════════════════════════════════════


class TestDossier:
    async def test_le_dossier_complet_et_les_regles_d_affichage(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        await _semer_arbre("237600000003")
        entetes = await _entetes(client)
        bail = await _attribuer(client)

        reponse = await client.get(
            f"/admin/attributions/{bail['msisdn']}/dossier", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        dossier = reponse.json()

        # L'en-tete : langue et segment viennent de la FICHE (FZ-INV §1).
        assert dossier["entete"]["langue"] == "fr"
        assert dossier["entete"]["segment"] == "MEDIUM"
        assert dossier["entete"]["etat"] == "actif"

        # AFF-02 : identity.type n'atteint JAMAIS la reponse.
        assert dossier["identite"]["present"] is True
        assert "type" not in dossier["identite"]
        assert dossier["identite"]["marital_status"] == "MARRIED"

        # AFF-03 : le status de la fiche est exclu par construction.
        assert "status" not in dossier["entete"]

        # AFF-04 : le champ se NOMME rattache.
        assert (
            dossier["territoire"]["rattachement"]["rattache_au_kiosque"]
            == "Kiosque Akwa Nord"
        )
        assert dossier["territoire"]["adresse"]["city"] == "Douala"

        # AFF-01 : le solde est celui du compte RELU.
        assert dossier["compte"]["present"] is True
        assert dossier["compte"]["balance"] == 161981.6
        assert dossier["compte"]["status"] == "ACTIVE"

        # AFF-08 : les produits viennent de la fiche serveur.
        assert dossier["produits"]["souscrits"][0]["name"] == "Collecte Journalière"

        # Spec §3.3 : l'epargne vide est EXPLIQUEE.
        assert dossier["epargne"]["present"] is True
        assert dossier["epargne"]["collectes"] == []
        assert "module de vie" in dossier["epargne"]["note"]

        # Le releve ne s'est PAS charge avec le dossier.
        assert dossier["releve"]["disponible"] is True
        assert ("transactions", "acc-ines") not in _plateforme_double["appels"]

    async def test_une_panne_de_comptes_n_emporte_pas_le_reste(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        """Spec §9 resolue BLOC PAR BLOC : account-service en panne, et
        l'identite, le territoire, les produits restent servis — HTTP 200."""
        await _semer_arbre("237600000004")
        entetes = await _entetes(client)
        bail = await _attribuer(client)
        _plateforme_double["panne_comptes"] = True

        reponse = await client.get(
            f"/admin/attributions/{bail['msisdn']}/dossier", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        dossier = reponse.json()
        assert dossier["compte"]["present"] is False
        assert "ne répond pas" in dossier["compte"]["raison"]
        assert dossier["identite"]["present"] is True
        assert dossier["territoire"]["present"] is True

    async def test_un_numero_sans_bail_n_a_pas_de_dossier(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        """Spec §1.3 : seuls les porteurs d'un bail sont visibles — un client
        jamais attribue n'apparait nulle part."""
        entetes = await _entetes(client)
        reponse = await client.get(
            "/admin/attributions/237699999999/dossier", headers=entetes
        )
        assert reponse.status_code == 404

    async def test_le_releve_se_charge_a_la_demande(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        await _semer_arbre("237600000005")
        entetes = await _entetes(client)
        bail = await _attribuer(client)

        reponse = await client.get(
            f"/admin/attributions/{bail['msisdn']}/releve", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        operations = reponse.json()["operations"]
        assert operations["total"] == 1
        assert operations["lignes"][0]["label"] == "Solde initial — Ines Kambire"
        assert ("transactions", "acc-ines") in _plateforme_double["appels"]


# ══════════════════════════════════════════════════════════════════════════
# 3. L'INTERLOCUTEUR — et le mecanisme qui l'ignore
# ══════════════════════════════════════════════════════════════════════════


class TestInterlocuteur:
    async def test_nomme_visible_efface(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        await _semer_arbre("237600000006")
        entetes = await _entetes(client)
        bail = await _attribuer(client)

        pose = await client.put(
            f"/admin/attributions/{bail['msisdn']}/interlocuteur",
            json={"interlocuteur": "M. Diallo — table du fond"},
            headers=entetes,
        )
        assert pose.status_code == 200, pose.text

        liste = await client.get("/admin/attributions", headers=entetes)
        ligne = next(b for b in liste.json()["baux"] if b["msisdn"] == bail["msisdn"])
        assert ligne["interlocuteur"] == "M. Diallo — table du fond"

        efface = await client.put(
            f"/admin/attributions/{bail['msisdn']}/interlocuteur",
            json={"interlocuteur": "  "},
            headers=entetes,
        )
        assert efface.json()["interlocuteur"] is None

    async def test_le_rejeu_d_idempotence_ignore_l_interlocuteur(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        """LE test de non-regression du mecanisme : nommer un interlocuteur
        puis REJOUER la cle d'origine rend LE MEME corps qu'au premier 201 —
        le mecanisme public ne connait pas le champ."""
        await _semer_arbre("237600000007")
        entetes = await _entetes(client)
        cle = str(uuid4())
        premier = await _attribuer(client, cle)

        await client.put(
            f"/admin/attributions/{premier['msisdn']}/interlocuteur",
            json={"interlocuteur": "Mme Ndiaye"},
            headers=entetes,
        )
        rejeu = await client.post(
            ROUTE_PUBLIQUE, json=PROFIL_CM, headers={"Idempotency-Key": cle}
        )
        assert rejeu.status_code == 201
        assert rejeu.json() == premier, "le rejeu a change — le mecanisme a bouge"


# ══════════════════════════════════════════════════════════════════════════
# 4. POPULATION, REFUS, LOT
# ══════════════════════════════════════════════════════════════════════════


class TestPopulationEtJournal:
    async def test_population_derivee_et_coherente(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        await _semer_arbre("237600000008")
        await _semer_arbre("237600000009")
        entetes = await _entetes(client)
        await _attribuer(client)

        reponse = await client.get("/admin/attributions/population", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        # UN pays seme -> 4 combinaisons, jamais « seize » en dur.
        assert len(corps["combinaisons"]) == 4
        cm = next(
            ligne
            for ligne in corps["combinaisons"]
            if (ligne["genre"], ligne["categorie"]) == ("FEMALE", "INDIVIDUAL")
        )
        assert cm["total"] == 2
        assert cm["attribues"] == 1
        assert cm["libres"] == 1
        assert corps["combinaisons_epuisees"] == 3  # les 3 profils a zero

    async def test_le_refus_409_laisse_trace_et_reponse_inchangee(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        entetes = await _entetes(client)
        refus = await client.post(
            ROUTE_PUBLIQUE,
            json={"pays": "CM", "genre": "MALE", "categorie": "CORPORATE"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert refus.status_code == 409
        assert refus.json()["code"] == "STOCK_EPUISE"

        journal = await client.get("/admin/journal", headers=entetes)
        ligne = next(
            e for e in journal.json()["entrees"] if e["operation"] == "REFUS"
        )
        assert ligne["cible"] == "CM/MALE/CORPORATE"
        assert ligne["origine"] == "appareil"

    async def test_l_adresse_et_son_pays_entrent_a_la_trace(
        self,
        client: httpx.AsyncClient,
        _plateforme_double: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Demande Direction 28/08 : le journal dit D'OU venait le geste.
        L'adresse est relevee du chemin reseau (X-Forwarded-For, premier
        maillon) et le pays est resolu A L'ECRITURE, en local."""
        from app.core.config import settings as reglages

        # La discipline I-AUTH-11 : X-Forwarded-For n'est cru QUE derriere un
        # proxy declare de confiance — c'est le cas de la production (nginx).
        monkeypatch.setattr(reglages, "faire_confiance_proxy", True)
        await _semer_arbre("237600000012")
        entetes = await _entetes(client)
        reponse = await client.post(
            ROUTE_PUBLIQUE,
            json=PROFIL_CM,
            headers={
                "Idempotency-Key": str(uuid4()),
                # Une adresse camerounaise reelle, avec un second maillon de
                # proxy : seul le PREMIER compte.
                "X-Forwarded-For": "154.72.153.10, 10.0.0.7",
            },
        )
        assert reponse.status_code == 201, reponse.text

        journal = await client.get("/admin/attributions/journal", headers=entetes)
        creation = next(
            e
            for e in journal.json()["entrees"]
            if e["operation"] == "CREATE" and e["cible"] == reponse.json()["msisdn"]
        )
        assert creation["ip"] == "154.72.153.10"
        assert creation["ip_pays"] == "CM"

    async def test_une_adresse_privee_n_a_pas_de_pays(
        self,
        client: httpx.AsyncClient,
        _plateforme_double: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Le banc local n'a pas de pays : None assume, jamais un faux code —
        et le geste ABOUTIT, la geolocalisation est un confort de journal."""
        from app.core.config import settings as reglages

        monkeypatch.setattr(reglages, "faire_confiance_proxy", True)
        await _semer_arbre("237600000013")
        entetes = await _entetes(client)
        reponse = await client.post(
            ROUTE_PUBLIQUE,
            json=PROFIL_CM,
            headers={"Idempotency-Key": str(uuid4()), "X-Forwarded-For": "192.168.1.44"},
        )
        assert reponse.status_code == 201, reponse.text
        journal = await client.get("/admin/attributions/journal", headers=entetes)
        creation = next(
            e
            for e in journal.json()["entrees"]
            if e["operation"] == "CREATE" and e["cible"] == reponse.json()["msisdn"]
        )
        assert creation["ip"] == "192.168.1.44"
        assert creation["ip_pays"] is None

    async def test_la_revocation_en_lot_rend_une_issue_par_numero(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        await _semer_arbre("237600000010")
        entetes = await _entetes(client)
        bail = await _attribuer(client)

        reponse = await client.post(
            "/admin/attributions/revocations",
            json={"msisdns": [bail["msisdn"], "237611111111"], "motif": "fin d'étape"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["revoques"] == 1
        assert corps["sans_bail"] == 1
        issues = {issue["msisdn"]: issue["issue"] for issue in corps["issues"]}
        assert issues[bail["msisdn"]] == "revoque"
        assert issues["237611111111"] == "aucun_bail_actif"

    async def test_le_journal_d_attribution_ne_montre_QUE_son_domaine(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        """La frontiere du role admin : les evenements d'attribution, RIEN
        d'autre — pas la gestion des comptes, pas les gestes referentiels.
        Et l'ORIGINE y est, c'est elle que l'ecran Journal affiche."""
        await _semer_arbre("237600000011")
        entetes = await _entetes(client)
        bail = await _attribuer(client)
        # Un geste HORS domaine, au meme journal sentinelle : la creation du
        # compte lecteur ci-dessous passe par l'API des comptes.
        await client.post(
            "/admin/comptes",
            json={"email": "temoin-journal@finzuu.com", "role": "viewer"},
            headers=entetes,
        )

        journal = await client.get("/admin/attributions/journal", headers=entetes)
        assert journal.status_code == 200, journal.text
        entrees = journal.json()["entrees"]
        assert any(
            e["operation"] == "CREATE" and e["cible"] == bail["msisdn"] for e in entrees
        )
        assert all(e["entite"].startswith("Attribution") for e in entrees), (
            "un geste hors domaine a fui dans le journal d'attribution"
        )
        creation = next(e for e in entrees if e["cible"] == bail["msisdn"])
        assert creation["origine"] == "appareil"

        #: ...et le journal GENERAL, lui, reste inchange : il voit TOUT.
        general = await client.get("/admin/journal", headers=entetes)
        assert any(
            e["entite"] == "SuperAdminAccount" for e in general.json()["entrees"]
        )

    async def test_les_echus_se_listent(
        self, client: httpx.AsyncClient, _plateforme_double: dict[str, Any]
    ) -> None:
        """Spec §3.1 : actif OU echu depuis moins de trente jours — la
        matiere de l'historique existe par etat=echus."""
        entetes = await _entetes(client)
        maintenant = datetime.now(UTC)
        await database.get_collection(database.COLLECTION_ATTRIBUTION_BAUX).insert_one(
            {
                "_id": "237622222222",
                "attribution_id": str(uuid4()),
                "cle_idempotence": str(uuid4()),
                "profil": dict(PROFIL_CM),
                "appareil": None,
                "attribue_le": maintenant - timedelta(days=9),
                "expire_le": maintenant - timedelta(days=2),
            }
        )
        reponse = await client.get(
            "/admin/attributions", params={"etat": "echus"}, headers=entetes
        )
        corps = reponse.json()
        assert [b["msisdn"] for b in corps["baux"]] == ["237622222222"]
        assert corps["baux"][0]["etat"] == "echu"
        assert corps["actifs"] == 0
