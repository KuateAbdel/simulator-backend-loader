"""
app/routes/admin_journal.py
===========================
Le JOURNAL d'administration du Loader — « qui a fait quoi, quand » (chantier
audit, demande JJB). Reserve au Super-Admin : voir l'activite d'administration
est une capacite sensible (elle revele les emails et les gestes des autres).

Source : la collection `audit_trail`, journal write-ahead d'intention. Les
actions d'administration (gestion des comptes/roles, creations d'entites hors
run) sont inscrites sous le run SENTINELLE RUN_ADMIN (UUID int=0). On en rend
les dernieres INTENTIONS, les plus recentes d'abord ; la pagination fine se
fait cote UI, comme les autres listes du Loader.

LECTURE SEULE : ce module n'ecrit rien. Il expose ce que les autres ont deja
inscrit — le journal ne se rejoue ni ne se falsifie depuis l'API.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.repositories.audit_trail import AuditTrailRepository
from app.routes.dependances import SessionAdmin, exige_super_admin

router = APIRouter(prefix="/admin/journal", tags=["admin — journal"])

#: Cles de payload qui portent l'AUTEUR d'un geste (selon l'action d'origine).
_CLES_ACTEUR = ("par", "cree_par", "modifie_par")


def _vue(entree: Any) -> dict[str, Any]:
    """La vue publique d'une entree — l'essentiel du « qui/quoi/quand »."""
    apres = entree.after or {}
    payload = apres.get("payload") or {}
    acteur = next((payload[c] for c in _CLES_ACTEUR if payload.get(c)), None)
    details = {k: v for k, v in payload.items() if k not in _CLES_ACTEUR}
    return {
        "quand": entree.timestamp.isoformat()
        if hasattr(entree.timestamp, "isoformat")
        else str(entree.timestamp),
        "operation": apres.get("operation", entree.action),
        "entite": entree.entity_type,
        "cible": apres.get("cible", ""),
        "acteur": acteur,
        "details": details,
    }


@router.get("")
async def lister_journal(
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """Les dernieres actions d'administration, les plus recentes d'abord."""
    entrees = await AuditTrailRepository().lister_admin(limite)
    return {
        "entrees": [_vue(e) for e in entrees],
        "total": len(entrees),
        "note": (
            "actions d'administration (gestion des comptes, rôles, entités hors "
            "run) — les plus récentes d'abord, lecture seule"
        ),
    }
