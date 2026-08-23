"""
`V-01` — l'onglet Versions.

Ce qui est verrouille ici : le RELEVE, et surtout la DETECTION du changement.
Afficher une version ne demande aucune action ; apprendre qu'elle a bouge, si.
Le cas le plus grave — des chemins qui changent a version identique — est
invisible sans historique, et c'est celui qu'on teste en premier.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core import database

# Les fixtures partagees viennent du module principal de tests d'API : ce
# depot n'a pas de `conftest.py`, la fixture `client` y est definie.
from tests.test_admin_api import _session_complete
from tests.test_admin_api import client as client


def _openapi(titre: str, version: str, chemins: int, methodes: int = 1) -> dict[str, Any]:
    """Un document OpenAPI minimal mais FIDELE : `info` + `paths`."""
    return {
        "info": {"title": titre, "version": version},
        "paths": {
            f"/api/v1/r{n}": {m: {} for m in ("get", "post")[:methodes]}
            for n in range(chemins)
        },
    }


def _doubler_sonde(monkeypatch: pytest.MonkeyPatch, reponses: dict[str, Any]) -> None:
    """Double `openapi.json` service par service — aucun appel reseau."""
    from app.routes import admin_versions

    async def faux_relever(_client: Any, nom: str, _base: str) -> dict[str, Any]:
        document = reponses.get(nom)
        if document is None:
            return {"joignable": False, "titre": None, "version": None,
                    "chemins": None, "operations": None}
        chemins = document.get("paths") or {}
        operations = sum(len(m) for m in chemins.values())
        info = document.get("info") or {}
        return {
            "joignable": True,
            "titre": info.get("title"),
            "version": info.get("version"),
            "chemins": len(chemins),
            "operations": operations,
        }

    monkeypatch.setattr(admin_versions, "_relever_un", faux_relever)


async def _vider() -> None:
    await database.get_database().drop_collection("service_versions")


class TestV01ReleveDeVersion:
    async def test_le_premier_releve_ne_declare_AUCUN_changement(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On ne compare pas ce qu'on voit pour la premiere fois."""
        await _vider()
        _doubler_sonde(monkeypatch, {"config-service": _openapi("Config Service", "1.0.1", 25)})
        entetes = await _session_complete(client)
        corps = (await client.get("/admin/versions", headers=entetes)).json()
        ligne = next(x for x in corps["services"] if x["service"] == "config-service")
        assert ligne["version"] == "1.0.1"
        assert ligne["chemins"] == 25
        assert ligne["gravite"] == "stable", ligne

    async def test_une_MONTEE_DE_VERSION_est_detectee_et_nommee(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _vider()
        entetes = await _session_complete(client)
        _doubler_sonde(monkeypatch, {"product-service": _openapi("Product Service", "1.0.1", 8)})
        await client.post("/admin/versions/relever", headers=entetes)

        _doubler_sonde(monkeypatch, {"product-service": _openapi("Product Service", "1.1.0", 8)})
        corps = (await client.post("/admin/versions/relever", headers=entetes)).json()
        ligne = next(x for x in corps["services"] if x["service"] == "product-service")
        assert ligne["gravite"] == "changement", ligne
        assert "1.0.1 → 1.1.0" in ligne["commentaire"]
        assert "re-mesurer" in ligne["commentaire"], "le geste a faire est dit"

    async def test_des_CHEMINS_qui_changent_A_VERSION_IDENTIQUE_sont_le_pire_cas(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le contrat a change et le service ne le dit PAS. Invisible sans
        historique — c'est la raison d'etre de cet ecran."""
        await _vider()
        entetes = await _session_complete(client)
        _doubler_sonde(monkeypatch, {"client-service": _openapi("Client Service", "1.0.0", 10)})
        await client.post("/admin/versions/relever", headers=entetes)

        _doubler_sonde(monkeypatch, {"client-service": _openapi("Client Service", "1.0.0", 14)})
        corps = (await client.post("/admin/versions/relever", headers=entetes)).json()
        ligne = next(x for x in corps["services"] if x["service"] == "client-service")
        assert ligne["gravite"] == "changement", ligne
        assert "10 → 14 chemins" in ligne["commentaire"]
        assert "ne le dit pas" in ligne["commentaire"]

    async def test_un_TITRE_INCOHERENT_est_signale(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mesure du 10/08 : `user-service` ET `identity-service` se declarent
        tous les deux « Auth Service ». Deux services sous le meme nom."""
        await _vider()
        _doubler_sonde(monkeypatch, {"identity-service": _openapi("Auth Service", "1.0.1", 12)})
        entetes = await _session_complete(client)
        corps = (await client.get("/admin/versions", headers=entetes)).json()
        ligne = next(x for x in corps["services"] if x["service"] == "identity-service")
        assert ligne["gravite"] == "anomalie", ligne
        assert "Auth Service" in ligne["commentaire"]

    async def test_un_service_MUET_ne_perd_PAS_sa_version(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Correction de conception (23/08) : « injoignable » est deja dit par
        le tableau de bord, en vert et rouge et EN DIRECT. Le repeter ici
        serait une duplication — et une version ne disparait pas parce qu'un
        service redemarre. On garde la derniere connue."""
        await _vider()
        entetes = await _session_complete(client)
        _doubler_sonde(monkeypatch, {"account-service": _openapi("Account Service", "1.0.0", 18)})
        await client.post("/admin/versions/relever", headers=entetes)

        _doubler_sonde(monkeypatch, {})  # plus AUCUN service ne repond
        corps = (await client.post("/admin/versions/relever", headers=entetes)).json()
        ligne = next(x for x in corps["services"] if x["service"] == "account-service")
        assert ligne["version"] == "1.0.0", "la version SURVIT au silence"
        assert ligne["chemins"] == 18
        assert ligne["gravite"] == "stable", "aucune fausse alerte de changement"

    async def test_un_service_JAMAIS_lu_le_dit_sans_crier_a_la_panne(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _vider()
        _doubler_sonde(monkeypatch, {"config-service": _openapi("Config Service", "1.0.1", 25)})
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/versions", headers=entetes)
        assert reponse.status_code == 200, "les neuf autres s'affichent quand meme"
        inconnu = next(x for x in reponse.json()["services"] if x["service"] == "faker")
        assert inconnu["gravite"] == "jamais_lu"
        assert inconnu["commentaire"] == "version jamais lue"

    async def test_ce_qui_demande_une_ACTION_remonte_en_haut(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Jamais l'ordre alphabetique : il noie le changement dans le stable."""
        await _vider()
        entetes = await _session_complete(client)
        stable = {
            "config-service": _openapi("Config Service", "1.0.1", 25),
            "account-service": _openapi("Account Service", "1.0.0", 18),
            "client-service": _openapi("Client Service", "1.0.0", 10),
        }
        _doubler_sonde(monkeypatch, stable)
        await client.post("/admin/versions/relever", headers=entetes)
        _doubler_sonde(
            monkeypatch, {**stable, "client-service": _openapi("Client Service", "2.0.0", 10)}
        )
        corps = (await client.post("/admin/versions/relever", headers=entetes)).json()
        assert corps["services"][0]["service"] == "client-service"
        assert corps["services"][0]["gravite"] == "changement"
        assert corps["a_surveiller"] >= 1

    async def test_le_cache_est_SERVI_sans_re_sonder(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Une lecture sur un cache frais ne doit taper sur AUCUN service."""
        await _vider()
        entetes = await _session_complete(client)
        _doubler_sonde(monkeypatch, {"config-service": _openapi("Config Service", "1.0.1", 25)})
        await client.post("/admin/versions/relever", headers=entetes)

        appels = {"n": 0}
        from app.routes import admin_versions

        async def compter(_c: Any, _nom: str, _base: str) -> dict[str, Any]:
            appels["n"] += 1
            return {"joignable": False, "titre": None, "version": None,
                    "chemins": None, "operations": None}

        monkeypatch.setattr(admin_versions, "_relever_un", compter)
        corps = (await client.get("/admin/versions", headers=entetes)).json()
        assert appels["n"] == 0, "cache frais : aucune sonde"
        assert corps["releve_il_y_a_secondes"] is not None

    async def test_la_FRAICHEUR_voyage_avec_la_reponse(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'ecran affiche « relevé il y a X » — la fraicheur est PROUVEE,
        jamais supposee."""
        await _vider()
        _doubler_sonde(monkeypatch, {"config-service": _openapi("Config Service", "1.0.1", 25)})
        entetes = await _session_complete(client)
        corps = (await client.get("/admin/versions", headers=entetes)).json()
        assert isinstance(corps["releve_il_y_a_secondes"], int)
        assert corps["releve_il_y_a_secondes"] < 60

    async def test_l_historique_n_empile_QUE_les_changements(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vingt lignes identiques ne disent rien et noieraient le changement."""
        await _vider()
        entetes = await _session_complete(client)
        _doubler_sonde(monkeypatch, {"config-service": _openapi("Config Service", "1.0.1", 25)})
        for _ in range(3):
            await client.post("/admin/versions/relever", headers=entetes)
        doc = await database.get_collection("service_versions").find_one({"_id": "config-service"})
        assert doc is not None
        assert len(doc["historique"]) == 1, doc["historique"]

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/admin/versions")).status_code == 401
        assert (await client.post("/admin/versions/relever")).status_code == 401
