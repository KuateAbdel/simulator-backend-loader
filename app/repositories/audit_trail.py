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

JOURNAL D'INTENTION — la seule atomicite dont nous disposons
------------------------------------------------------------
`POST /clients/onboard` ecrit dans **trois services**. Il n'existe **aucune
transaction, aucun rollback, et aucun `DELETE`** — ni sur client-service, ni sur
identity-service, ni sur account-service. Une cascade interrompue a mi-chemin
laisse une Identity orpheline et un compte orphelin, **definitifs**.

Aucun mecanisme serveur ne peut nous aider. La seule atomicite possible est
**locale et par ecriture prealable** : on note ce qu'on VA faire avant de le
faire, puis ce qui s'est REELLEMENT passe. C'est le principe du write-ahead log.

Trois etats, et un seul compte vraiment :

    INTENTION   ecrite AVANT l'appel reseau
    RESULTAT    ecrite APRES, qu'il ait reussi ou echoue
    ORPHELINE   une INTENTION sans RESULTAT — le processus est mort entre les
                deux. **On ne sait pas si le serveur a ecrit.**

Ce sont les orphelines qui comptent. Sans elles, une execution interrompue
laisse un environnement dont personne ne peut dire ce qui a ete cree — donc
impossible a purger, meme par prefixe (`OBJ-05`, `CR-07`).

Le schema des 6 collections n'est pas modifie : le cycle vit dans `action` et
dans `after`, qui sont libres par construction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.core.database import COLLECTION_AUDIT_TRAIL
from app.models.domain import AuditTrailEntry
from app.repositories.base import RepositoryBase

#: Les trois valeurs d'`action` qui portent le cycle d'ecriture.
ACTION_INTENTION = "INTENTION"
ACTION_RESULTAT = "RESULTAT"

#: Issues possibles d'une intention resolue.
STATUT_SUCCES = "SUCCES"
STATUT_ECHEC = "ECHEC"


@dataclass(slots=True)
class SuiviIntention:
    """Poignee rendue par `intention()` — sert a declarer l'issue.

    Si personne ne l'a marquee au sortir du bloc, elle l'est automatiquement :
    en `ECHEC` si une exception a traverse, en `SUCCES` sinon. Une intention
    ne peut donc pas rester silencieusement ouverte du fait d'un oubli — seule
    une mort du processus la laisse orpheline, et c'est precisement le cas
    qu'on veut pouvoir detecter.
    """

    intention_id: UUID
    entity_id: UUID
    statut: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def reussi(self, rendu: dict[str, Any] | None = None) -> None:
        self.statut = STATUT_SUCCES
        if rendu:
            self.detail = dict(rendu)

    def echoue(self, motif: str) -> None:
        self.statut = STATUT_ECHEC
        self.detail = {"motif": motif[:500]}


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

    # ----------------------------------------------------------------------
    # Journal d'intention — write-ahead, la seule atomicite disponible
    # ----------------------------------------------------------------------

    async def ouvrir_intention(
        self,
        run_id: UUID,
        entity_type: str,
        entity_id: UUID,
        operation: str,
        cible: str,
        payload: dict[str, Any] | None = None,
    ) -> SuiviIntention:
        """Note ce qu'on VA faire, **avant** de le faire.

        `cible` est le service et la route vises — c'est ce qui permet, en
        reconciliation, d'aller verifier si l'ecriture a eu lieu.
        """
        entree = AuditTrailEntry(
            id=uuid4(),
            run_id=run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=ACTION_INTENTION,
            before=None,
            after={"operation": operation, "cible": cible, "payload": payload or {}},
            timestamp=datetime.now(UTC),
        )
        await self._inserer(entree)
        return SuiviIntention(intention_id=entree.id, entity_id=entity_id)

    async def resoudre_intention(
        self, run_id: UUID, entity_type: str, suivi: SuiviIntention
    ) -> None:
        """Note ce qui s'est REELLEMENT passe. Toujours appelee, meme en echec."""
        await self._inserer(
            AuditTrailEntry(
                id=uuid4(),
                run_id=run_id,
                entity_type=entity_type,
                entity_id=suivi.entity_id,
                action=ACTION_RESULTAT,
                before={"intention_id": str(suivi.intention_id)},
                after={"statut": suivi.statut or STATUT_ECHEC, **suivi.detail},
                timestamp=datetime.now(UTC),
            )
        )

    @asynccontextmanager
    async def intention(
        self,
        run_id: UUID,
        entity_type: str,
        entity_id: UUID,
        operation: str,
        cible: str,
        payload: dict[str, Any] | None = None,
    ) -> AsyncIterator[SuiviIntention]:
        """Encadre une ecriture distante par son journal.

            async with journal.intention(run, "client", cid, "onboard",
                                         "client-service POST /clients/onboard",
                                         payload) as suivi:
                fiche = await client.onboarder(...)
                suivi.reussi({"client_id": fiche["_id"]})

        L'issue est ecrite dans tous les cas — succes, echec metier, ou
        exception. Seule une mort du processus laisse l'intention orpheline,
        et c'est exactement ce qu'on veut pouvoir retrouver ensuite.
        """
        suivi = await self.ouvrir_intention(
            run_id, entity_type, entity_id, operation, cible, payload
        )
        try:
            yield suivi
        except Exception as erreur:
            suivi.echoue(f"{type(erreur).__name__}: {erreur}")
            await self.resoudre_intention(run_id, entity_type, suivi)
            raise
        else:
            if suivi.statut is None:
                suivi.reussi()
            await self.resoudre_intention(run_id, entity_type, suivi)

    async def intentions_orphelines(self, run_id: UUID) -> list[AuditTrailEntry]:
        """Les intentions restees sans resultat — **le vrai livrable de ce module**.

        Chacune designe une ecriture dont on ignore si le serveur l'a
        appliquee. C'est la liste exacte des points a reconcilier avant de
        declarer une execution close, et la seule facon de garder `OBJ-05`
        (reversibilite) tenable apres une interruption.
        """
        resolues = {
            str((document.get("before") or {}).get("intention_id"))
            async for document in self.collection.find(
                {"run_id": str(run_id), "action": ACTION_RESULTAT}, {"before": 1}
            )
        }
        curseur = self.collection.find({"run_id": str(run_id), "action": ACTION_INTENTION}).sort(
            "timestamp", 1
        )
        return [
            AuditTrailEntry.model_validate(document)
            async for document in curseur
            if str(document.get("_id")) not in resolues
        ]

    async def exporter_run(self, run_id: UUID) -> list[AuditTrailEntry]:
        """EF-62 : export du journal d'une execution, ordonne chronologiquement."""
        curseur = self.collection.find({"run_id": str(run_id)}).sort("timestamp", 1)
        return [AuditTrailEntry.model_validate(d) async for d in curseur]

    async def lister_admin(self, limite: int = 200) -> list[AuditTrailEntry]:
        """Le journal « qui a fait quoi, quand » des actions d'ADMINISTRATION :
        les dernieres INTENTIONS sous le run sentinelle RUN_ADMIN (UUID int=0),
        les plus recentes d'abord. Borne a `limite` — la pagination fine est
        cote UI (comme les autres listes du Loader)."""
        curseur = (
            self.collection.find(
                {"run_id": str(UUID(int=0)), "action": ACTION_INTENTION}
            )
            .sort("timestamp", -1)
            .limit(limite)
        )
        return [AuditTrailEntry.model_validate(d) async for d in curseur]

    async def compter_par_type(self, run_id: UUID) -> dict[str, int]:
        """Statistiques de fin d'execution (EF-61)."""
        pipeline: list[dict[str, Any]] = [
            {"$match": {"run_id": str(run_id)}},
            {"$group": {"_id": "$entity_type", "n": {"$sum": 1}}},
        ]
        return {str(d["_id"]): int(d["n"]) async for d in self.collection.aggregate(pipeline)}
