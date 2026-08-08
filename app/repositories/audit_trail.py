"""
app/repositories/audit_trail.py
===============================
SIEM applicatif interne — EF-61 a EF-64.

Il ne double pas les logs serveur : il les remplace. Ceux de user-service sont
pollues a 99 % par les sondes Kubernetes (308 844 entrees, dont 50/50 sur
/health au dernier releve) et aucun en-tete de correlation n'est renvoye. Notre
journal est la seule tracabilite exploitable.

`before` est None a la creation, `after` est None a la suppression. Les deux ne
sont jamais None simultanement — un evenement sans avant ni apres ne decrit rien.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.core.database import COLLECTION_AUDIT_TRAIL
from app.models.domain import AuditTrailEntry
from app.repositories.base import RepositoryBase


class AuditTrailRepository(RepositoryBase):
    collection_name = COLLECTION_AUDIT_TRAIL

    async def journaliser(
        self,
        run_id: UUID,
        entity_type: str,
        entity_id: UUID,
        action: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> AuditTrailEntry:
        if before is None and after is None:
            raise ValueError(
                "audit_trail : 'before' et 'after' ne peuvent etre None ensemble — "
                "une entree sans etat ne decrit aucun changement"
            )
        entree = AuditTrailEntry(
            id=uuid4(),
            run_id=run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            timestamp=datetime.now(UTC),
        )
        await self._inserer(entree)
        return entree

    async def exporter_run(self, run_id: UUID) -> list[AuditTrailEntry]:
        """EF-62 : export du journal d'une execution, ordonne chronologiquement."""
        curseur = self.collection.find({"run_id": str(run_id)}).sort("timestamp", 1)
        return [AuditTrailEntry.model_validate(d) async for d in curseur]

    async def compter_par_type(self, run_id: UUID) -> dict[str, int]:
        """Statistiques de fin d'execution (EF-61)."""
        pipeline: list[dict[str, Any]] = [
            {"$match": {"run_id": str(run_id)}},
            {"$group": {"_id": "$entity_type", "n": {"$sum": 1}}},
        ]
        return {str(d["_id"]): int(d["n"]) async for d in self.collection.aggregate(pipeline)}
