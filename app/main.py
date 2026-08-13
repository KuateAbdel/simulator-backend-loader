"""
app/main.py
===========
Point d'entree du backend Loader FinZuu.

Perimetre de CE MODULE : demarrage de l'application, cycle de vie du client
MongoDB, et exposition de /health.

Les paquets `app/services`, `app/clients` et `app/repositories` portent
aujourd'hui 29 modules — 9 clients FinZuu, 6 repositories, 5 executeurs et
l'orchestrateur. Ils ne sont PAS branches sur cette API : le Loader s'execute
par `scripts/executer_run.py`. Les routes de pilotage (`EF-50` a `EF-58`) sont
le Sprint 6 ; d'ici la, `/health` est la seule surface HTTP, et c'est assume.

(Cet en-tete affirmait « paquets volontairement vides » jusqu'au 11/08 : c'etait
l'etat du Sprint 0, laisse en place pendant six sprints.)

Le contrat OpenAPI publie ici est celui que consomme le frontend Next.js de
Zidane (10_component.puml).

CIBLE DE DEPLOIEMENT -- source : `FZ-INFRA-SIMUL-2026-001` (Confluence TST
52330498), la documentation d'exploitation du serveur.

    domaine        `simul.fintech4esg.com`  (API sous `simul.api.*`)
    serveur        NetCup, ARM64, 6 vCPU / 8 Go / 256 Go, `152.53.53.139`
    OS             Debian 13 Trixie minimal
    reverse proxy  **Traefik** (ADR-02 -- Nginx explicitement REJETE)
    voisins        Newsletter et SendMail, sur le meme hote
    statut         **vierge, non provisionne** au 18/07/2026

Aucun reverse proxy applicatif n'est ajoute par le Loader : Traefik decouvre le
service par ses labels Docker et gere Let's Encrypt.

> **Corrige le 11/08.** Cet en-tete annoncait « le Nginx deja en place sur
> 152.53.118.110 » : ni cette IP ni Nginx n'apparaissent dans la documentation
> d'infrastructure, et le serveur cible n'est meme pas provisionne. Trois autres
> domaines existent et ne sont PAS le notre : `faker.fintech4esg.com` (Faker) et
> les `<service>.test.services.fintech4esg.com` (les 9 microservices FinZuu et
> leur Swagger).

Le CDC ecrit `loader.fintech4esg.com` (§268, `ENF-11`, `H-04`) : ce lien est
INCORRECT, arbitrage du 11/08. Le domaine provisionne est `simul.*`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import database
from app.core.config import settings
from app.routes import (
    admin_auth,
    admin_configuration,
    admin_dashboard,
    admin_entites,
    admin_inventaire,
    admin_purge,
    admin_referentiels,
    admin_runs,
    health,
)
from app.services.bootstrap import amorcer_super_admin

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ouvre la persistance, pose les index, amorce le Super-Admin.

    Aucune de ces trois etapes n'est fatale : une base injoignable doit laisser
    l'application demarrer et repondre sur /health. Un processus qui refuse de
    demarrer ne dit RIEN a l'exploitant, alors qu'une sonde vivante avec une
    base absente est immediatement diagnosticable.
    """
    database.connect()
    try:
        await database.ensure_indexes()
        await amorcer_super_admin()
    except Exception:
        logger.exception(
            "Initialisation MongoDB incomplete : index et/ou bootstrap Super-Admin "
            "non appliques. L'API demarre malgre tout."
        )
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
# Lot A de l'API Super-Admin (US-A1..A4, US-B5) — le contrat OpenAPI que le
# frontend de Zidane consomme est publie sur /docs des ce lot.
app.include_router(admin_auth.router)
app.include_router(admin_configuration.router)
app.include_router(admin_referentiels.router)
app.include_router(admin_dashboard.router)
app.include_router(admin_entites.router)
app.include_router(admin_inventaire.router)
app.include_router(admin_purge.router)
app.include_router(admin_runs.router)
