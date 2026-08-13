"""
tests/test_admin_api.py
=======================
Lot A de l'API Super-Admin — `US-A1`, `US-A2`, `US-A4`, `US-B5`.

Chaque test reprend un critere Gherkin du backlog (`BACKLOG_SUPER_ADMIN.md`,
page Confluence 67665922) — un critere = un test nomme. La Definition of Done
exige les comportements d'erreur : 401, 403 et 422 sont testes au meme titre
que les succes.

Base de donnees : une base MongoDB DEDIEE (`loader_finzuu_tests_api`), nettoyee
a chaque session de test — jamais la base de developpement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.core import database
from app.core.config import settings
from app.main import app
from app.repositories.super_admin import SuperAdminRepository

#: Un domaine PLAUSIBLE : email-validator refuse les TLD reserves (.test,
#: .example) — et c'est exactement la rigueur demandee. Aucun mail ne part.
EMAIL = "pilote-tests@finzuu.com"
MDP_INITIAL = "initial-bootstrap-9911"
MDP_DURABLE = "un-mot-de-passe-durable-13aout"


@pytest_asyncio.fixture()
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """API + base dediee + compte bootstrap frais (must_change_password=True)."""
    monkeypatch.setattr(settings, "mongodb_database", "loader_finzuu_tests_api")
    database.connect()
    await database.get_database().drop_collection(
        database.COLLECTION_SUPER_ADMIN_ACCOUNTS
    )
    await SuperAdminRepository().creer(EMAIL, MDP_INITIAL)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    database.close()


async def _login(client: httpx.AsyncClient, mdp: str = MDP_INITIAL) -> dict[str, Any]:
    reponse = await client.post(
        "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": mdp}
    )
    assert reponse.status_code == 200, reponse.text
    return dict(reponse.json())


async def _session_complete(client: httpx.AsyncClient) -> dict[str, str]:
    """Login initial + changement de mot de passe force -> jeton plein."""
    initial = await _login(client)
    reponse = await client.post(
        "/admin/auth/password",
        json={"ancien": MDP_INITIAL, "nouveau": MDP_DURABLE},
        headers={"Authorization": f"Bearer {initial['access_token']}"},
    )
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


class TestUSA1Connexion:
    async def test_login_valide_rend_un_jeton_a_duree_limitee(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        assert session["token_type"] == "bearer"  # noqa: S105 — un type, pas un secret
        assert 0 < session["expires_in"] <= 24 * 3600
        assert session["must_change_password"] is True
        assert MDP_INITIAL not in str(session), "le mot de passe ne sort JAMAIS"

    async def test_mot_de_passe_errone_401_sans_dire_quel_champ(
        self, client: httpx.AsyncClient
    ) -> None:
        reponse = await client.post(
            "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": "faux"}
        )
        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "identifiants invalides"

    async def test_email_inconnu_rend_le_MEME_401(self, client: httpx.AsyncClient) -> None:
        """Dire « email inconnu » confirmerait l'existence des comptes."""
        reponse = await client.post(
            "/admin/auth/login",
            json={"email": "autre-inconnu@finzuu.com", "mot_de_passe": MDP_INITIAL},
        )
        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "identifiants invalides"

    async def test_un_email_INVALIDE_est_un_422_pas_un_string_accepte(
        self, client: httpx.AsyncClient
    ) -> None:
        """Exigence de Yaniv du 13/08 — la lecon des bugs de la plateforme :
        elle accepte n'importe quoi dans ses champs, PAS NOUS. Un email est un
        email (RFC), jamais un string libre."""
        for invalide in ("pas-un-email", "a@b", "@finzuu.com", "yaniv@", ""):
            reponse = await client.post(
                "/admin/auth/login",
                json={"email": invalide, "mot_de_passe": "peu importe"},
            )
            assert reponse.status_code == 422, f"{invalide!r} accepte comme email"


class TestUSA2MotDePasseForce:
    async def test_toute_route_est_403_tant_que_le_mdp_initial_survit(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        reponse = await client.get(
            "/admin/referentiels/catalogue-statique",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert reponse.status_code == 403
        assert "POST /admin/auth/password" in reponse.json()["detail"], (
            "le 403 doit indiquer le chemin de sortie"
        )

    async def test_le_changement_leve_l_obligation_DEFINITIVEMENT(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        assert (
            await client.get("/admin/referentiels/catalogue-statique", headers=entetes)
        ).status_code == 200
        # Un nouveau login n'exige plus le changement.
        session = await _login(client, MDP_DURABLE)
        assert session["must_change_password"] is False

    async def test_un_jeton_vole_ne_suffit_pas_l_ancien_mdp_est_reverifie(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        reponse = await client.post(
            "/admin/auth/password",
            json={"ancien": "pas-le-bon", "nouveau": MDP_DURABLE},
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert reponse.status_code == 401

    async def test_un_mot_de_passe_court_ou_identique_est_refuse(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        entetes = {"Authorization": f"Bearer {session['access_token']}"}
        court = await client.post(
            "/admin/auth/password",
            json={"ancien": MDP_INITIAL, "nouveau": "court"},
            headers=entetes,
        )
        assert court.status_code == 422
        identique = await client.post(
            "/admin/auth/password",
            json={"ancien": MDP_INITIAL, "nouveau": MDP_INITIAL},
            headers=entetes,
        )
        assert identique.status_code == 422


class TestSessionRequise:
    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.get("/admin/referentiels/catalogue-statique")
        assert reponse.status_code == 401

    async def test_jeton_falsifie_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.get(
            "/admin/referentiels/geographie",
            headers={"Authorization": "Bearer pas.un.jeton"},
        )
        assert reponse.status_code == 401


class TestUSB5Referentiels:
    async def test_le_catalogue_statique_porte_les_comptes_EXACTS(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.get(
            "/admin/referentiels/catalogue-statique", headers=entetes
        )
        assert reponse.status_code == 200
        assert reponse.json()["comptes"] == {
            "industries": 6,
            "secteurs": 112,
            "formes_juridiques": 27,
            "professions": 576,
            "groupes": 21,
            "profils_revenu": 4,
            "pays": 195,
            "fonctions_dirigeant": 20,
        }
        profils = reponse.json()["profils_revenu"]
        assert profils["bank_stable"]["mu"] == 12.15

    async def test_la_geographie_rend_l_arbre_complet(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/referentiels/geographie", headers=entetes)
        assert reponse.status_code == 200
        arbre = reponse.json()["pays"]
        assert {p["pays"] for p in arbre} == {"CM", "CI", "BF", "SN"}
        nb_regions = sum(len(p["regions"]) for p in arbre)
        nb_villes = sum(len(r["villes"]) for p in arbre for r in p["regions"])
        nb_quartiers = sum(
            len(v["quartiers"]) for p in arbre for r in p["regions"] for v in r["villes"]
        )
        assert (nb_regions, nb_villes, nb_quartiers) == (51, 50, 82), (
            "les comptes CR-01 du referentiel doivent arriver ENTIERS a l'ecran"
        )

    async def test_les_telcos_portent_les_parts_de_marche(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/referentiels/telcos", headers=entetes)
        assert reponse.status_code == 200
        telcos = reponse.json()["telcos"]
        assert len(telcos["CM"]) >= 3
        assert all(t["regex_msisdn"] for pays in telcos.values() for t in pays)
