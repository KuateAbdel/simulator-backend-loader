"""
app/repositories/faker_ledger.py
================================
Registre de consommation Faker — support de **D-FAKER-1**, la discipline la
plus stricte du projet.

    « Une fois qu'un client Faker a ete consomme pour UN usage — Depositaire,
      Lender local, OU CollectClient — ce meme client_id ne doit plus jamais
      etre reutilise pour un autre usage. »

Le garde-fou est **structurel**, pas seulement applicatif : `_id` EST le
`client_id` Faker. Une seconde consommation leve `DuplicateKeyError` au niveau
du moteur — aucune fenetre de concurrence ne peut la laisser passer.

`est_consomme()` existe pour la lisibilite des journaux et pour eviter un aller-
retour inutile, mais ce n'est **pas** lui qui garantit l'invariant. Ne jamais
s'appuyer sur la seule verification prealable : entre le `find_one` et
l'`insert_one`, un autre worker peut passer. C'est `marquer_consomme()` qui
tranche, et son echec est un resultat normal, pas une erreur.

Un client ecarte pour raison de quota (mauvais pays, mauvais sexe, mauvaise
tranche d'age) n'est PAS consomme : il n'entre au registre que s'il a
reellement produit une entite. `resulting_entity_id` en est la preuve.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pymongo.errors import DuplicateKeyError

from app.core.database import COLLECTION_FAKER_CONSUMPTION_LEDGER
from app.models.domain import FakerConsumptionLedger
from app.models.enums import FakerConsumptionType
from app.repositories.base import RepositoryBase, en_document


class FakerLedgerRepository(RepositoryBase):
    collection_name = COLLECTION_FAKER_CONSUMPTION_LEDGER

    async def est_consomme(self, client_id: str) -> bool:
        """Verification prealable — lisibilite, jamais la garantie."""
        return await self.collection.find_one({"_id": client_id}) is not None

    async def marquer_consomme(
        self,
        client_id: str,
        consumed_for: FakerConsumptionType,
        resulting_entity_id: UUID,
        country_code: str,
    ) -> bool:
        """Enregistre la consommation. Renvoie False si deja consomme.

        Le False n'est pas une erreur : c'est le signal qu'il faut re-tirer
        avec un `seed` different, exactement ce que prescrit D-FAKER-1.
        """
        entree = FakerConsumptionLedger(
            id=client_id,
            consumed_at=datetime.now(UTC),
            consumed_for=consumed_for,
            resulting_entity_id=resulting_entity_id,
            country_code=country_code.upper(),
        )
        try:
            await self.collection.insert_one(en_document(entree))
        except DuplicateKeyError:
            return False
        return True

    async def obtenir(self, client_id: str) -> FakerConsumptionLedger | None:
        return await self._trouver_un(FakerConsumptionLedger, {"_id": client_id})

    async def compter_par_usage(self, consumed_for: FakerConsumptionType) -> int:
        return await self._compter({"consumed_for": consumed_for.value})

    async def total(self) -> int:
        return await self._compter()
