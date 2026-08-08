"""
app/routes/health.py
====================
Sonde de disponibilite du backend Loader.

Volontairement minimale : elle atteste que le processus FastAPI est vivant et
sert des requetes, rien de plus. Elle ne teste ni MongoDB, ni Faker, ni les 9
microservices FinZuu -- une sonde qui echoue parce qu'une dependance externe
est indisponible ferait redemarrer un processus parfaitement sain.

La verification de sante de Faker (UC "Verifier la sante de Faker") et le
sondage du referentiel config-service (Phase 1 du diagramme d'activite) sont
des endpoints distincts, a ajouter separement.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse, summary="Sonde de disponibilite")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
