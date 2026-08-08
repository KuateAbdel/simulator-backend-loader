"""
app/clients/product_service.py
==============================
Client product-service — catalogue Produits et Policies (UC-11).

**Le serveur n'impose AUCUNE unicite sur `name`** (`ANO-PRD-UNIQ-01`, teste et
reproductible). Ce n'est pas une hypothese : la base contient deja
« Cotisation 20000/mois » **en double**. Le GET-avant-POST est donc la SEULE
protection, et il doit gerer le cas « plusieurs correspondances » — pas
seulement « une ou zero ».

**Ce service n'expose aucun DELETE.** Un produit ne peut qu'etre desactive via
`PATCH /{id}/deactivate`. Toute creation est donc definitive : d'ou le
GET-avant-POST strict, et le mode DRY_RUN.

Trois pieges neutralises :

  ANO-PRD-POLICY-01  `policy` est optionnel au contrat mais son absence provoque
                     un HTTP 500. On en envoie toujours une, complete (D-PRD-1).
  INV-PRD-07         La Policy est une REFERENCE VIVANTE. `policy_id` n'est
                     JAMAIS utilise ici — seulement `policy` en embed (D-PRD-7).
                     Partager un policy_id ferait qu'une modification sur l'un
                     modifierait l'autre, silencieusement.
  INV-PRD-04         `category` n'accepte QUE INDIVIDUAL et CORPORATE. « ANY »
                     provoque un HTTP 422 — d'ou le split D-PRD-4. A ne jamais
                     confondre avec `segment`, ou « ANY » est parfaitement valide.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id, parse_datetime
from app.clients.contracts import ProductType
from app.core.config import settings

logger = logging.getLogger(__name__)

#: Sentinelle de tri : un produit sans `created_at` lisible est traite comme le
#: plus ancien, ce qui est le comportement sur — on ne recree jamais par erreur.
_EPOQUE = datetime(1970, 1, 1, tzinfo=UTC)


class ProductServiceClient:
    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu(
            "product-service", settings.product_service_base, journal=journal
        )

    async def fermer(self) -> None:
        await self._client.fermer()

    async def inventaire(self) -> list[dict[str, Any]]:
        """D-PRD-2 — inventaire complet AVANT toute creation."""
        return await self._client.lister_tout("/api/v1/products/")

    async def chercher_par_nom(self, nom: str) -> dict[str, Any] | None:
        """Retrouve un produit par son nom, en gerant les DOUBLONS.

        Le serveur n'impose aucune unicite (`ANO-PRD-UNIQ-01`) et la base en
        contient deja un : « Cotisation 20000/mois » existe en double. On
        retient donc systematiquement **le plus ancien** — celui qui a le plus
        de chances d'etre le produit de production reference ailleurs — et on
        signale le doublon plutot que de le taire.
        """
        cible = nom.strip().lower()
        correspondances = [
            produit
            for produit in await self.inventaire()
            if str(produit.get("name", "")).strip().lower() == cible
        ]
        if not correspondances:
            return None
        if len(correspondances) > 1:
            logger.warning(
                "Produit %r present %d fois (ANO-PRD-UNIQ-01) — le plus ancien est retenu",
                nom,
                len(correspondances),
            )
        correspondances.sort(key=lambda p: parse_datetime(str(p.get("created_at"))) or _EPOQUE)
        return correspondances[0]

    async def creer_produit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Cree un Product avec sa Policy EMBARQUEE.

        Deux garde-fous appliques avant l'appel, parce que le serveur les punit
        durement : une `policy` absente provoque un HTTP 500, et un `policy_id`
        partage corrompt silencieusement les autres Products.
        """
        if not payload.get("policy"):
            raise ValueError(
                "policy absente : le contrat la declare optionnelle mais son "
                "absence provoque un HTTP 500 (ANO-PRD-POLICY-01, D-PRD-1)"
            )
        if payload.get("policy_id"):
            raise ValueError(
                "policy_id interdit : la Policy est une reference VIVANTE "
                "(INV-PRD-07). La partager modifierait retroactivement les autres "
                "Products. Toujours un embed dedie (D-PRD-7)."
            )
        reponse = await self._client.requete("POST", "/api/v1/products/", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def compter_par_type(self) -> dict[str, int]:
        """Etat du catalogue. Mesure du 08/08 : 0 LENDING, 0 CORPORATE."""
        compte: dict[str, int] = {}
        for produit in await self.inventaire():
            cle = f"{produit.get('type')}/{produit.get('category')}"
            compte[cle] = compte.get(cle, 0) + 1
        return compte

    async def produits_du_type(self, type_produit: ProductType) -> list[dict[str, Any]]:
        return [p for p in await self.inventaire() if str(p.get("type")) == type_produit.value]

    @staticmethod
    def identifiant(produit: dict[str, Any]) -> str | None:
        return normaliser_id(produit)
