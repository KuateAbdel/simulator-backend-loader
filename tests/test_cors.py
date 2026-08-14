"""CORS — le contrat qui permet au frontend de Zidane (autre domaine) d'appeler
cette API. Le piege du split frontend/backend : sans ces en-tetes, le
navigateur bloque, silencieusement, chaque requete cross-origin.

On teste les DEUX etats, par une app CONSTRUITE avec la configuration voulue —
`add_middleware` se fige au demarrage, on ne peut pas le basculer a chaud.
"""

from __future__ import annotations

import httpx

from app.core.config import settings

ORIGINE_FRONTEND = "https://simul.fintech4esg.com"


def _app_avec_origines(origines: str):  # type: ignore[no-untyped-def]
    """Reconstruit l'app avec CORS_ALLOW_ORIGINS voulu — l'import de app.main
    lit `settings` a la construction, donc on force la valeur puis on recharge."""
    import importlib

    settings.cors_allow_origins = origines
    import app.main as main

    return importlib.reload(main).app


async def test_une_origine_autorisee_recoit_l_en_tete_cors() -> None:
    app = _app_avec_origines(ORIGINE_FRONTEND)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            reponse = await c.get("/health", headers={"Origin": ORIGINE_FRONTEND})
        assert reponse.headers.get("access-control-allow-origin") == ORIGINE_FRONTEND, (
            "sans cet en-tete, le navigateur du frontend bloque l'appel"
        )
    finally:
        settings.cors_allow_origins = ""


async def test_une_origine_ETRANGERE_ne_recoit_rien() -> None:
    app = _app_avec_origines(ORIGINE_FRONTEND)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            reponse = await c.get("/health", headers={"Origin": "https://pirate.example"})
        assert "access-control-allow-origin" not in reponse.headers, (
            "une origine hors liste n'est JAMAIS autorisee — pas de `*`"
        )
    finally:
        settings.cors_allow_origins = ""


async def test_sans_configuration_aucun_cors_ne_fuit() -> None:
    app = _app_avec_origines("")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        reponse = await c.get("/health", headers={"Origin": ORIGINE_FRONTEND})
    assert "access-control-allow-origin" not in reponse.headers, (
        "vide par defaut : aucune origine croisee, le choix est explicite en prod"
    )
