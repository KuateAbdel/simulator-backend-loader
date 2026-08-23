"""
app/repositories/verrous.py
===========================
`C2` — le verrou par RESSOURCE, contre le doublon en concurrence.

Le probleme mesure : config-service n'applique **aucune unicite** (`RC-182`,
`RC-183`). C'est le Loader qui la tient, par `GET`-avant-`POST`. Or ce patron
n'est sur que **sequentiellement** : deux appels simultanes sur le meme pays
lisent tous les deux « absent », et creent tous les deux. Un double-clic du
frontend, deux onglets ouverts, un retry reseau — et le doublon nait
exactement la ou toute la discipline visait a l'empecher. Il est ensuite
DEFINITIF : aucun DELETE cote serveur.

Ce verrou est volontairement minuscule :

* **une cle par ressource** (`pousser:CM`, `rectifier:CV`) — jamais un verrou
  global : deux pays differents se poussent en parallele sans se genre ;
* **il EXPIRE** (`expire_le` + index TTL Mongo). Un processus qui meurt en
  cours de route ne laisse pas une ressource verrouillee pour toujours —
  c'est la difference entre une protection et une panne ;
* **il ne bloque jamais** : le second appelant recoit un refus IMMEDIAT qui
  dit qui detient le verrou et jusqu'a quand. Attendre en silence donnerait
  l'illusion d'un traitement, puis un timeout sans explication.

Le verrou `EF-55` (aucune ecriture pendant un run) reste au-dessus : il
protege la coherence du run, celui-ci protege l'unicite d'une ressource.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from pymongo.errors import DuplicateKeyError

from app.core.database import COLLECTION_VERROUS, get_collection

#: Duree de vie par defaut. Volontairement LARGE au regard du geste protege
#: (pousser un pays de 181 villes tient en 2 appels depuis `C3`), mais assez
#: courte pour qu'un incident ne gele pas la ressource plus d'une minute.
DUREE_PAR_DEFAUT = 90


class RessourceVerrouillee(RuntimeError):
    """Un autre appel travaille DEJA sur cette ressource — refus immediat."""


class VerrouRepository:
    @property
    def collection(self) -> Any:
        return get_collection(COLLECTION_VERROUS)

    async def prendre(self, cle: str, *, par: str, secondes: int = DUREE_PAR_DEFAUT) -> None:
        """Prend le verrou, ou leve `RessourceVerrouillee` — jamais d'attente.

        Le TTL de Mongo purge en arriere-plan (a la minute) : on ne s'y fie
        donc PAS pour la justesse. Un verrou dont `expire_le` est depasse est
        repris ici meme, immediatement.
        """
        maintenant = datetime.now(UTC)
        expire_le = maintenant + timedelta(seconds=secondes)
        try:
            await self.collection.insert_one(
                {"_id": cle, "par": par, "pris_le": maintenant, "expire_le": expire_le}
            )
            return
        except DuplicateKeyError:
            pass

        # Un verrou existe : est-il PERIME ? (processus mort, TTL pas encore
        # passe). On le reprend par une ecriture conditionnelle — la condition
        # sur `expire_le` rend l'operation atomique : deux repreneurs
        # simultanes, un seul gagnant.
        repris = await self.collection.find_one_and_replace(
            {"_id": cle, "expire_le": {"$lte": maintenant}},
            {"_id": cle, "par": par, "pris_le": maintenant, "expire_le": expire_le},
        )
        if repris is not None:
            return

        detenteur = await self.collection.find_one({"_id": cle}) or {}
        fin = detenteur.get("expire_le")
        reste = ""
        if isinstance(fin, datetime):
            if fin.tzinfo is None:
                fin = fin.replace(tzinfo=UTC)
            reste = f" (encore ~{max(1, int((fin - maintenant).total_seconds()))} s)"
        raise RessourceVerrouillee(
            f"{cle} : un autre geste est DEJA en cours sur cette ressource"
            f"{reste}, demande par {detenteur.get('par', 'inconnu')}. Sans ce "
            "refus, les deux appels creeraient chacun leur exemplaire — la "
            "plateforme n'a aucun index unique (RC-183) et aucun DELETE."
        )

    async def rendre(self, cle: str) -> None:
        """Rend le verrou. Idempotent : rendre deux fois n'est pas une faute."""
        await self.collection.delete_one({"_id": cle})

    @asynccontextmanager
    async def tenu(
        self, cle: str, *, par: str, secondes: int = DUREE_PAR_DEFAUT
    ) -> AsyncIterator[None]:
        """Le verrou pour la duree d'un bloc — rendu meme si le bloc echoue."""
        await self.prendre(cle, par=par, secondes=secondes)
        try:
            yield
        finally:
            await self.rendre(cle)
