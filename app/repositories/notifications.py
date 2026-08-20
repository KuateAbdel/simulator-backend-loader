"""
app/repositories/notifications.py
=================================
Le canal IN-APP du systeme de notification — persistance des notifications
destinees a un compte. Chaque compte ne lit QUE les siennes (`destinataire`),
les plus recentes d'abord ; le compteur de non-lues alimente la cloche.

Rien ne se supprime : une notification lue reste (elle grise). L'historique
d'information est aussi une trace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.database import COLLECTION_NOTIFICATIONS
from app.models.domain import Notification
from app.repositories.base import RepositoryBase


class NotificationRepository(RepositoryBase):
    collection_name = COLLECTION_NOTIFICATIONS

    async def creer(
        self, destinataire: str, type_: str, donnees: dict[str, Any]
    ) -> Notification:
        notif = Notification(
            id=uuid4(),
            destinataire=destinataire.strip().lower(),
            type=type_,
            donnees=donnees,
            lu=False,
            cree_le=datetime.now(tz=UTC),
        )
        await self._inserer(notif)
        return notif

    async def lister(self, destinataire: str, limite: int = 50) -> list[Notification]:
        curseur = (
            self.collection.find({"destinataire": destinataire.strip().lower()})
            .sort("cree_le", -1)
            .limit(limite)
        )
        return [Notification.model_validate(d) async for d in curseur]

    async def compter_non_lues(self, destinataire: str) -> int:
        return int(
            await self.collection.count_documents(
                {"destinataire": destinataire.strip().lower(), "lu": {"$ne": True}}
            )
        )

    async def marquer_lu(self, notif_id: str, destinataire: str) -> bool:
        """Marque UNE notification lue — bornee au proprietaire : on ne touche
        jamais la boite d'un autre."""
        resultat = await self.collection.update_one(
            {"_id": notif_id, "destinataire": destinataire.strip().lower()},
            {"$set": {"lu": True}},
        )
        return bool(resultat.matched_count)

    async def marquer_tout_lu(self, destinataire: str) -> int:
        resultat = await self.collection.update_many(
            {"destinataire": destinataire.strip().lower(), "lu": {"$ne": True}},
            {"$set": {"lu": True}},
        )
        return int(resultat.modified_count)
