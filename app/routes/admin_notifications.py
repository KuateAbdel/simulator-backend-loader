"""
app/routes/admin_notifications.py
=================================
La BOITE de notifications du compte connecte — canal in-app du systeme de
notification. Chaque compte ne lit et ne marque QUE les SIENNES : la boite est
bornee a `session.email`, jamais celle d'un autre.

Accessible a TOUT compte authentifie (admin_complet = Viewer+) : recevoir des
notifications n'est pas un privilege — c'est le canal, pas la capacite. Ce qui
DECLENCHE une notification, lui, depend du role (cf. services/notifications.py).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.repositories.notifications import NotificationRepository
from app.routes.dependances import SessionAdmin, admin_complet

router = APIRouter(prefix="/admin/notifications", tags=["admin — notifications"])


def _vue(n: Any) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "type": n.type,
        "donnees": n.donnees,
        "lu": n.lu,
        "quand": n.cree_le.isoformat() if hasattr(n.cree_le, "isoformat") else str(n.cree_le),
    }


@router.get("")
async def lister_notifications(
    session: Annotated[SessionAdmin, Depends(admin_complet)],
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    """Mes notifications, les plus recentes d'abord."""
    depot = NotificationRepository()
    notifs = await depot.lister(session.email, limite)
    return {
        "notifications": [_vue(n) for n in notifs],
        "non_lues": await depot.compter_non_lues(session.email),
    }


@router.get("/non-lues")
async def compter_non_lues(
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, int]:
    """Le compteur de la cloche — leger, sonde souvent."""
    return {"non_lues": await NotificationRepository().compter_non_lues(session.email)}


@router.put("/{notif_id}/lu")
async def marquer_lu(
    notif_id: str,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Marque UNE notification lue — la mienne uniquement (404 sinon)."""
    ok = await NotificationRepository().marquer_lu(notif_id, session.email)
    if not ok:
        raise HTTPException(status_code=404, detail="notification introuvable")
    return {"lu": True}


@router.put("/tout-lu")
async def marquer_tout_lu(
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, int]:
    """Marque toute ma boite comme lue."""
    return {"marquees": await NotificationRepository().marquer_tout_lu(session.email)}
