"""
app/repositories/loader_runs.py
===============================
Etat de simulation d'une execution — machine d'etat de `06_state.puml`.

`_id` est le run_id **du Loader**, jamais celui de Faker. Le run_id Faker
(`20260620123721`) appartient a un autre systeme et n'a pas la meme semantique :
c'est une cle de partition de leur base, pas l'identifiant de notre execution.

`PARTIAL` est un etat terminal **legitime**, pas un echec : le CDC prevoit
qu'une entite en erreur soit journalisee et que l'execution se poursuive
(UC-07 / UC-08, cas alternatif).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from app.core.database import COLLECTION_LOADER_RUNS
from app.models.domain import LoaderRun
from app.models.enums import RunMode, RunStatus
from app.repositories.base import RepositoryBase, en_document

#: Transitions autorisees (06_state.puml). Toute autre est refusee ici, pour
#: qu'un bug de sequencement ne produise pas un etat incoherent en base.
_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.PARTIAL, RunStatus.FAILED}
    ),
    RunStatus.PAUSED: frozenset({RunStatus.RUNNING}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.PARTIAL: frozenset(),
}


class TransitionInterdite(Exception):
    """Transition non prevue par la machine d'etat du CDC."""


class LoaderRunRepository(RepositoryBase):
    collection_name = COLLECTION_LOADER_RUNS

    async def creer(
        self,
        sim_start_date: date,
        sim_end_date: date,
        mode: RunMode = RunMode.DRY_RUN,
        run_id: UUID | None = None,
        configuration: dict[str, Any] | None = None,
    ) -> LoaderRun:
        """Cree un run en PENDING. Mode DRY_RUN par defaut : passer en REEL est
        toujours une action explicite du Super-Admin, jamais un defaut.

        `configuration` est l'empreinte produite par
        `ConfigurationExecution.empreinte()`, jointe a celle de la surcouche
        referentielle. Elle est **figee au lancement** et ne bouge plus.

        **Sans elle, `ENF-15` est perdue** (`D-10`) : deux executions du meme
        `run_id` sous des parametres differents produiraient des resultats
        differents, et `CR-04` deviendrait invérifiable. Un run cree sans
        configuration reproduit le CDC par defaut — c'est le cas nominal, et
        l'empreinte vide le dit.
        """
        run = LoaderRun(
            id=run_id or uuid4(),
            sim_start_date=sim_start_date,
            sim_end_date=sim_end_date,
            status=RunStatus.PENDING,
            mode=mode,
            checkpoints=[],
            configuration=dict(configuration or {}),
        )
        await self._inserer(run)
        return run

    async def obtenir(self, run_id: UUID) -> LoaderRun | None:
        return await self._trouver_un(LoaderRun, {"_id": str(run_id)})

    async def changer_statut(self, run_id: UUID, nouveau: RunStatus) -> LoaderRun:
        run = await self.obtenir(run_id)
        if run is None:
            raise TransitionInterdite(f"Run {run_id} introuvable")
        if nouveau not in _TRANSITIONS[run.status]:
            raise TransitionInterdite(
                f"Transition {run.status.value} -> {nouveau.value} interdite "
                f"(06_state.puml). Autorisees : "
                f"{sorted(s.value for s in _TRANSITIONS[run.status]) or 'aucune, etat terminal'}"
            )
        await self.collection.update_one({"_id": str(run_id)}, {"$set": {"status": nouveau.value}})
        run.status = nouveau
        return run

    async def ajouter_checkpoint(self, run_id: UUID, phase: str, detail: dict[str, Any]) -> None:
        """Journalise la fin d'une phase (geo, organisation, produits, ...).

        Ces checkpoints portent la reprise apres interruption (UC-05,
        declencheur « reprise apres interruption »).
        """
        checkpoint = {
            "phase": phase,
            "horodatage": datetime.now(UTC).isoformat(),
            "detail": detail,
        }
        await self.collection.update_one(
            {"_id": str(run_id)}, {"$push": {"checkpoints": checkpoint}}
        )

    async def dernier_en_cours(self) -> LoaderRun | None:
        """Sert le verrou d'execution : EF-55 interdit deux generations
        simultanees sur le meme environnement."""
        document = await self.collection.find_one(
            {"status": {"$in": [RunStatus.RUNNING.value, RunStatus.PAUSED.value]}}
        )
        return LoaderRun.model_validate(document) if document else None

    async def remplacer(self, run: LoaderRun) -> None:
        await self.collection.replace_one({"_id": str(run.id)}, en_document(run), upsert=True)
