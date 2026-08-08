"""
app/main.py
===========
Point d'entree du backend Loader FinZuu.

Perimetre de ce squelette : demarrage de l'application, cycle de vie du client
MongoDB, et exposition de /health. Aucune logique metier n'est encore branchee
-- les paquets app/services, app/clients et app/repositories sont volontairement
vides a ce stade.

Le contrat OpenAPI publie ici est celui que consomme le frontend Next.js de
Zidane (10_component.puml). Il est servi derriere le Nginx deja en place sur
152.53.118.110, sous simul.api.fintech4esg.com -- aucun reverse proxy
applicatif n'est ajoute par le Loader.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import database
from app.core.config import settings
from app.routes import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database.connect()
    yield
    database.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "API interne du Loader FinZuu — orchestrateur HTTP des 9 microservices "
        "FinZuu et de l'API Faker fintech4esg (FZ-CDC-LOADER-2026-001 v1.2)."
    ),
    lifespan=lifespan,
)

app.include_router(health.router)
