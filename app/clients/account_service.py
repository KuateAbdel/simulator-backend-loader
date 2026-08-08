"""
app/clients/account_service.py
==============================
Client account-service — comptes financiers (UC-10, EF-13).

**Ce service n'expose AUCUN endpoint DELETE.** Un compte cree ne peut qu'etre
passe en `CLOSED`. Toute ecriture y est donc definitive, ce qui justifie a lui
seul le mode DRY_RUN : on deroule la chaine complete et on inspecte les payloads
avant la premiere ecriture reelle.

Les 4 comptes du Lender (`CAPITAL`, `INTEREST`, `PENALTY`, `TAXE`) sont crees
**explicitement**, un par un. Aucune cascade ne les produit — etabli par
comptage exhaustif le 08/08 : les 42 comptes de l'environnement s'expliquent
integralement par 3 cascades connues, zero residuel, et 0 Company sur 7 ne
portait ces 4 types.

`external_id` est TOUJOURS renseigne ici. Les 7 comptes `OPERATION` issus de la
cascade Company le laissent vide alors que le champ est requis au contrat — on
ne reproduit pas ce defaut.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.clients.contracts import AccountType, OwnerType
from app.core.cdc import COMPTES_LENDER
from app.core.config import settings

#: Classe d'entite proprietaire, telle que le serveur la nomme pour les comptes
#: adosses a une Company (observe sur les 38 comptes owner_type=COMPANY).
EXTERNAL_CLASS_COMPANY: str = "COMPANY_SERVICE"


class AccountServiceClient:
    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu(
            "account-service", settings.account_service_base, journal=journal
        )

    async def fermer(self) -> None:
        await self._client.fermer()

    async def comptes_du_proprietaire(self, owner_id: UUID | str) -> list[dict[str, Any]]:
        """Sert le GET-avant-POST : on ne recree jamais un compte existant,
        puisqu'on ne pourrait pas le supprimer."""
        reponse = await self._client.get(f"/api/v1/accounts/owner/{owner_id}", vide_si_404=True)
        data = reponse.data
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return [data] if isinstance(data, dict) else []

    def payload_compte(
        self,
        *,
        type_compte: AccountType,
        owner_id: UUID | str,
        owner_name: str,
        currency: str,
    ) -> dict[str, Any]:
        """Construit le payload sans l'emettre — utilisable en DRY_RUN.

        `account_number` part a None : le serveur le genere lui-meme (format
        observe : `04YSYAAUQI4V`). Le champ est requis mais nullable.
        """
        return {
            "account_number": None,
            "type": type_compte.value,
            "external_id": str(owner_id),
            "external_class": EXTERNAL_CLASS_COMPANY,
            "owner_type": OwnerType.COMPANY.value,
            "owner_id": str(owner_id),
            "owner_name": owner_name,
            "currency": currency,
        }

    async def creer_compte(self, payload: dict[str, Any]) -> dict[str, Any]:
        reponse = await self._client.requete("POST", "/api/v1/accounts/", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    def payloads_des_4_comptes_lender(
        self, company_id: UUID | str, owner_name: str, currency: str
    ) -> dict[str, dict[str, Any]]:
        """UC-10 / EF-13 — les 4 comptes, indexes par leur role metier.

        L'ordre suit celui du CDC : CAPITAL, INTEREST, PENALTY, TAXE. Seul
        CAPITAL sera dote ; les trois autres demarrent a zero.
        """
        return {
            nom.lower(): self.payload_compte(
                type_compte=AccountType(nom),
                owner_id=company_id,
                owner_name=owner_name,
                currency=currency,
            )
            for nom in COMPTES_LENDER
        }

    @staticmethod
    def identifiant(compte: dict[str, Any]) -> str | None:
        return normaliser_id(compte)

    @staticmethod
    def types_presents(comptes: list[dict[str, Any]]) -> set[str]:
        return {str(c.get("type")) for c in comptes if c.get("type")}
