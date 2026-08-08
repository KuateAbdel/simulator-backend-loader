"""
app/repositories/base.py
========================
Socle commun aux 6 repositories du Loader.

**Choix de serialisation, et sa raison.** Tout document est ecrit en
representation JSON-native (`model_dump(mode="json")`) : les UUID deviennent des
chaines, les dates des chaines ISO-8601. Une seule regle, aucune exception.

Pourquoi : BSON ne sait pas encoder `datetime.date` — or `LoaderRun` porte
`sim_start_date` et `sim_end_date`, qui sont des dates. Une conversion au cas par
cas serait une source d'oubli permanent. La representation JSON-native supprime
le probleme a la racine, evite aussi les subtilites de `uuidRepresentation`, et
rend les documents lisibles tels quels dans un shell Mongo.

Le cout est assume : les comparaisons de dates deviennent lexicographiques —
ce qui reste exact pour de l'ISO-8601 UTC, seul format que nous ecrivons.

En lecture, Pydantic reconstruit les types : les chaines redeviennent UUID et
dates. La frontiere de typage est donc etanche des deux cotes.
"""

from __future__ import annotations

from typing import Any, TypeVar

from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import BaseModel

from app.core.database import MongoDocument, get_collection

T = TypeVar("T", bound=BaseModel)


def en_document(modele: BaseModel) -> MongoDocument:
    """Serialise un modele pour MongoDB : alias `_id`, types JSON-natifs."""
    return dict(modele.model_dump(mode="json", by_alias=True))


class RepositoryBase:
    """Acces a une collection, sans logique metier.

    Les regles de domaine vivent dans les repositories concrets — c'est la que
    D-FAKER-1 ou l'unicite d'un role de Lender sont rendus infranchissables.
    """

    collection_name: str

    @property
    def collection(self) -> AsyncIOMotorCollection[MongoDocument]:
        return get_collection(self.collection_name)

    async def _inserer(self, modele: BaseModel) -> None:
        await self.collection.insert_one(en_document(modele))

    async def _trouver_un(self, modele: type[T], filtre: dict[str, Any]) -> T | None:
        document = await self.collection.find_one(filtre)
        return modele.model_validate(document) if document else None

    async def _compter(self, filtre: dict[str, Any] | None = None) -> int:
        return int(await self.collection.count_documents(filtre or {}))
