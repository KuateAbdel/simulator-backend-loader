"""
app/routes/admin_purge.py
=========================
Lot E — la PURGE (`US-F1`/`US-F2`, `EF-59`/`EF-65`).

CE QUE « PURGEABLE » VEUT DIRE — et la carte est MESURÉE, service par
service (les disciplines D-*) :

  user-service (groupes)   DELETE existe        -> PURGEABLE, le seul
  product-service          deactivate seulement -> semi : jamais effaçable
  client-service           AUCUNE mutation sauf PATCH langue (mesure)
  identity / account       AUCUN DELETE — la piece KYC et les comptes sont
                           definitifs, les mouvements aussi
  depositary-service       AUCUN DELETE (D-DEP-3), et la desactivation
                           n'arrete NI collectes NI retraits (D-DEP-8) —
                           cosmetique, pas une purge
  company-service          AUCUN DELETE (les PROBE_ du 12/08 en temoignent)
  config-service           PARTAGE — on n'y purge jamais (A-08)

La purge honnete fait donc DEUX choses, et les dit toutes les deux :
  1. elle SUPPRIME ce qui est reversible (les groupes DEMO_) ;
  2. elle LISTE les residus marques — jamais caches, avec le verdict et le
     fait mesure qui l'explique.

Le rite en deux temps, comme partout : preparer (l'inventaire, aucune
ecriture) puis confirmer (les suppressions, journalisees sous RUN_ADMIN).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.cdc import PREFIXE_DONNEES
from app.core.database import get_collection
from app.repositories.audit_trail import AuditTrailRepository
from app.routes.admin_entites import RUN_ADMIN
from app.routes.dependances import (
    SessionAdmin,
    admin_complet,
    refuser_si_run_en_cours,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/purge", tags=["admin — purge"])

#: La carte des residus, avec leur verdict MESURE. C'est la reponse a
#: « purgeable, ca veut dire quoi ? » — gravee dans le code.
VERDICTS_RESIDUS: dict[str, str] = {
    "companies": "AUCUN DELETE (company-service) — permanentes, marquees DEMO_",
    "depositaires": (
        "AUCUN DELETE (D-DEP-3), desactivation cosmetique — n'arrete ni "
        "collectes ni retraits (D-DEP-8, FRA-203/204)"
    ),
    "clients": "AUCUNE mutation sauf PATCH langue (mesure) — permanents",
    "identites": "AUCUN DELETE — la piece KYC est definitive",
    "comptes": "AUCUN DELETE, aucun contre-mouvement — soldes definitifs",
    "produits": "AUCUN DELETE, deactivate seulement — jamais effaçables",
}


def _client_users() -> Any:
    """Fabrique du client user-service — doublee dans les tests."""
    from app.clients.user_service import UserServiceClient

    return UserServiceClient()


async def _groupes_marques(client: Any) -> list[dict[str, Any]]:
    groupes = await client.lister_groupes()
    return [
        {"id": str(g.get("_id") or g.get("id")), "nom": str(g.get("name", ""))}
        for g in groupes
        if str(g.get("name", "")).startswith(PREFIXE_DONNEES)
    ]


async def _residus_marques() -> dict[str, Any]:
    """L'inventaire des permanents, depuis NOS collections — le registre des
    Lenders, l'arbre (kiosques = depositaires), le ledger Faker (clients
    confirmes = identites + comptes en cascade), le registre produits admin."""
    lenders = await get_collection("lenders_registry").count_documents({})
    kiosques = await get_collection("org_hierarchy").count_documents(
        {"niveau": "KIOSQUE"}
    )
    clients = await get_collection("faker_consumption_ledger").count_documents(
        {"state": "CONSOMME"}
    )
    document = await get_collection("loader_configuration").find_one(
        {"_id": "produits_admin"}
    )
    produits_admin = len((document or {}).get("produits", []))
    return {
        "companies": {"compte": lenders, "verdict": VERDICTS_RESIDUS["companies"]},
        "depositaires": {"compte": kiosques, "verdict": VERDICTS_RESIDUS["depositaires"]},
        "clients": {"compte": clients, "verdict": VERDICTS_RESIDUS["clients"]},
        "identites": {"compte": clients, "verdict": VERDICTS_RESIDUS["identites"]},
        "comptes": {
            "compte": clients,
            "verdict": VERDICTS_RESIDUS["comptes"],
            "note": "1 CHECKING par client au minimum ; 6 par depositaire souscrit",
        },
        "produits_crees_par_admin": {
            "compte": produits_admin,
            "verdict": VERDICTS_RESIDUS["produits"],
        },
    }


@router.post("/preparer")
async def preparer(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-F1` — l'inventaire, AUCUNE ecriture.

    Deux colonnes, toutes deux chiffrees : le purgeable (groupes DEMO_ releves
    sur le serveur) et les residus marques (nos collections), chacun avec le
    verdict mesure qui l'explique. Rien n'est cache — c'est la condition pour
    decider en connaissance de cause.
    """
    client = _client_users()
    try:
        groupes = await _groupes_marques(client)
    finally:
        await client.fermer()
    return {
        "purgeable": {
            "groupes": groupes,
            "regle": "DELETE /groupes/{id} existe — le seul module reversible",
        },
        "residus_marques": await _residus_marques(),
        "note": (
            "confirmer via POST /admin/purge/confirmer — seuls les groupes "
            "seront supprimes ; les residus restent, marques, et le rapport "
            "les redira"
        ),
    }


class ConfirmationPurge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: L'unique action reversible de la v1 — explicite, jamais implicite.
    supprimer_groupes: bool


@router.post("/confirmer")
async def confirmer(
    demande: ConfirmationPurge,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-F2` — l'execution : seuls les groupes DEMO_ sont supprimes, chaque
    suppression journalisee sous RUN_ADMIN. Le rapport final redit les
    residus — la purge ne les fait pas disparaitre du compte-rendu."""
    await refuser_si_run_en_cours()

    supprimes: list[str] = []
    echecs: list[dict[str, str]] = []
    if demande.supprimer_groupes:
        audit = AuditTrailRepository()
        client = _client_users()
        try:
            for groupe in await _groupes_marques(client):
                try:
                    await client.supprimer_groupe(groupe["id"])
                except Exception as erreur:
                    echecs.append({"groupe": groupe["nom"], "motif": type(erreur).__name__})
                    continue
                supprimes.append(groupe["nom"])
                try:
                    await audit.journaliser(
                        run_id=RUN_ADMIN,
                        entity_type="Group",
                        entity_id=UUID(groupe["id"]),
                        action="DELETE",
                        before={"name": groupe["nom"]},
                    )
                except Exception:  # pragma: no cover — defense d'exploitation
                    logger.exception("journal DELETE %s non ecrit", groupe["nom"])
        finally:
            await client.fermer()

    return {
        "supprimes": supprimes,
        "echecs": echecs,
        "residus_marques": await _residus_marques(),
        "note": "les residus restent sur la plateforme, marques — dit, jamais cache",
    }
