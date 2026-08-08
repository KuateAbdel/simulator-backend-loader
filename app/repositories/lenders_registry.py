"""
app/repositories/lenders_registry.py
====================================
Registre des Lenders — le Lender comme ROLE porte par une Company.

Cette collection existe parce que company-service **ne connait pas ce concept** :
zero occurrence de « lender » dans son contrat. Le Loader porte donc lui-meme
cette logique (CDC §6.3, decision D-02).

L'index unique `(company_id, lender_type)` interdit qu'une Company porte deux
fois le meme role — c'est l'idempotence d'EF-12 rendue structurelle.

Les 4 `*_account_id` sont **optionnels**, et c'est deliberé : aucune cascade
serveur ne les produit (decision D-01, comptage exhaustif du 08/08). Un Lender
partiellement initialise est un etat legitime, prevu par UC-10 en cas d'exception
— pas une donnee invalide a rejeter.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pymongo.errors import DuplicateKeyError

from app.core.database import COLLECTION_LENDERS_REGISTRY
from app.models.domain import LenderRegistryEntry
from app.models.enums import LenderType
from app.repositories.base import RepositoryBase, en_document


class LendersRegistryRepository(RepositoryBase):
    collection_name = COLLECTION_LENDERS_REGISTRY

    async def enregistrer(
        self,
        company_id: UUID,
        lender_type: LenderType,
        country_code: str,
        comptes: dict[str, UUID] | None = None,
    ) -> LenderRegistryEntry | None:
        """Inscrit le role. Renvoie None si la Company le porte deja.

        `comptes` accepte les cles capital / interest / penalty / taxe, chacune
        optionnelle : on enregistre ce qui a reellement ete cree.
        """
        comptes = comptes or {}
        entree = LenderRegistryEntry(
            id=uuid4(),
            company_id=company_id,
            lender_type=lender_type,
            country_code=country_code.upper(),
            capital_account_id=comptes.get("capital"),
            interest_account_id=comptes.get("interest"),
            penalty_account_id=comptes.get("penalty"),
            taxe_account_id=comptes.get("taxe"),
        )
        try:
            await self.collection.insert_one(en_document(entree))
        except DuplicateKeyError:
            return None
        return entree

    async def par_company(
        self, company_id: UUID, lender_type: LenderType
    ) -> LenderRegistryEntry | None:
        return await self._trouver_un(
            LenderRegistryEntry,
            {"company_id": str(company_id), "lender_type": lender_type.value},
        )

    async def compter(self, lender_type: LenderType | None = None) -> int:
        filtre = {"lender_type": lender_type.value} if lender_type else {}
        return await self._compter(filtre)

    async def partiellement_initialises(self) -> list[LenderRegistryEntry]:
        """Lenders auxquels il manque au moins un des 4 comptes (UC-10, exception)."""
        curseur = self.collection.find(
            {
                "$or": [
                    {"capital_account_id": None},
                    {"interest_account_id": None},
                    {"penalty_account_id": None},
                    {"taxe_account_id": None},
                ]
            }
        )
        return [LenderRegistryEntry.model_validate(d) async for d in curseur]
