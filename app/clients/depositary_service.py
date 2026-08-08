"""
app/clients/depositary_service.py
=================================
Client depositary-service — Kiosques et souscriptions (UC-09).

⚠️ **Ce service n'applique AUCUNE restriction RBAC** (`FRA-205`, `ANO-DEP-RBAC-01`,
la decouverte la plus grave de toute l'investigation). Un token CUSTOMER y
dispose des memes pouvoirs que ROOT : lire, creer, desactiver n'importe quel
Depositaire. **`D-DEP-7` : le Loader n'utilise que ROOT pour toute ecriture
ici**, jamais un token de moindre privilege — meme si le serveur l'accepterait.

Le contrat est minimal : `name`, `currency`, `company_id`. **Aucun champ
geographique.** Le quartier d'un Kiosque n'existe donc nulle part cote serveur —
c'est `org_hierarchy` qui le porte, et le NOM du Kiosque qui le rend visible
dans l'interface.

Disciplines portees ici :

  D-DEP-1  Creer le Depositaire d'abord, souscrire ENSUITE. **Mesure du 08/08** :
           la creation seule ne cree AUCUN compte (delta +0). Le Depositaire nait
           **actif** — aucun `PATCH status/true` n'est necessaire.
  D-DEP-2  Les 6 comptes naissent a la PREMIERE souscription, par Depositaire et
           non par produit. **Verifie de bout en bout le 08/08** : 1re
           souscription -> +6 comptes (CAPITAL, CLASSIC, INTEREST, PENALTY, TAXE,
           TERM_DEPOSIT, tous a 0 dans la devise du Depositaire) ; 2e
           souscription -> **+0 compte**, les memes sont reutilises.

  **Modele reel de la souscription** (mesure du 08/08, non documente ailleurs) :
  il n'existe qu'**UNE SEULE souscription par Depositaire**, dont le champ
  `product` est un **TABLEAU**. Souscrire n'en cree pas une nouvelle : cela
  AJOUTE le produit au tableau. Un doublon s'y accumule donc silencieusement —
  d'ou `a_deja_souscrit()`, qui parcourt le tableau avant tout POST.
  D-DEP-3  GET-avant-POST : aucune unicite de nom cote serveur, et aucun DELETE.
  D-DEP-6  Ne jamais presumer une coherence de devise Company <-> Depositaire :
           `currency` accepte n'importe quelle chaine (`FRA-201`, « ZZZ_INVENTE »
           a ete accepte). Le Loader valide lui-meme contre config-service.
  D-DEP-8  Desactiver un Depositaire **n'arrete NI les collectes NI les retraits**
           sur les souscriptions existantes (`FRA-203`), et desactiver la Company
           parente n'a aucun effet en cascade (`FRA-204`). Ne jamais concevoir de
           logique supposant le contraire — d'ou l'absence deliberee de toute
           methode de « fermeture » ici.

Un 404 sur les souscriptions signifie « aucune souscription », pas une erreur.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.core.config import settings

#: Les 6 comptes crees par la premiere souscription. Le Loader ne les cree
#: jamais lui-meme : il les CONSTATE (D-DEP-2).
COMPTES_DEPOSITAIRE: tuple[str, ...] = (
    "CAPITAL",
    "INTEREST",
    "PENALTY",
    "TAXE",
    "CLASSIC",
    "TERM_DEPOSIT",
)


class DepositaryServiceClient:
    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu(
            "depositary-service", settings.depositary_service_base, journal=journal
        )

    async def fermer(self) -> None:
        await self._client.fermer()

    async def lister(self) -> list[dict[str, Any]]:
        return await self._client.lister_tout("/api/v1/depositaries/")

    async def chercher_par_nom(self, nom: str) -> dict[str, Any] | None:
        """D-DEP-3 — aucune unicite serveur, et aucun DELETE : on verifie avant.

        Un doublon de nom a ete accepte en HTTP 201 lors des tests d'invariants —
        le serveur ne protege rien.
        """
        cible = nom.strip().lower()
        for depositaire in await self.lister():
            if str(depositaire.get("name", "")).strip().lower() == cible:
                return depositaire
        return None

    async def creer(self, nom: str, devise: str, company_id: UUID | str) -> dict[str, Any]:
        """3 champs, pas un de plus. Le Depositaire naît **ACTIF par defaut** :
        aucun `PATCH status/true` n'est necessaire, contrairement a ce que
        laissait croire une premiere lecture du contrat.

        `D-DEP-6` : la devise doit avoir ete validee par l'appelant contre
        config-service. Le serveur accepte n'importe quoi (`FRA-201`).
        """
        payload = {"name": nom, "currency": devise, "company_id": str(company_id)}
        reponse = await self._client.requete(
            "POST", "/api/v1/depositaries/create", json_body=payload
        )
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def souscriptions_du_depositaire(self, depositary_id: UUID | str) -> list[dict[str, Any]]:
        """Un HTTP 404 signifie « aucune souscription », pas une erreur.

        Comportement confirme sur 3 depositaires sans souscription — la ou un
        200 avec liste vide serait attendu.
        """
        reponse = await self._client.get(
            f"/api/v1/depositaries/subscriptions/depositary/{depositary_id}", vide_si_404=True
        )
        data = reponse.data
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return [data] if isinstance(data, dict) else []

    async def souscrire(self, depositary_id: UUID | str, product_id: UUID | str) -> dict[str, Any]:
        """D-DEP-1 et D-DEP-2 — c'est CETTE operation qui cree les 6 comptes.

        Elle ne les cree qu'UNE FOIS, par Depositaire. Souscrire a un second
        produit reutilise exactement les memes 6 comptes : verifie
        empiriquement, et c'est pour ca que le Loader ne les compte qu'une fois.

        Validations serveur reelles : `product_id` inexistant -> HTTP 404
        « Product not found » ; `depositary_id` inexistant -> HTTP 400
        « Depositary not found ». Deux codes differents pour deux references
        manquantes — incoherence notee, sans impact fonctionnel.
        """
        payload = {"product_id": str(product_id), "depositary_id": str(depositary_id)}
        reponse = await self._client.requete(
            "POST", "/api/v1/depositaries/subscriptions/create", json_body=payload
        )
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def a_deja_souscrit(self, depositary_id: UUID | str, product_id: UUID | str) -> bool:
        """D-DEP-3 — GET-avant-POST sur les souscriptions.

        Une souscription dupliquee est acceptee par le serveur (`FRA-202`), il
        faut donc verifier soi-meme.
        """
        cible = str(product_id)
        for souscription in await self.souscriptions_du_depositaire(depositary_id):
            produits = souscription.get("product")
            candidats = produits if isinstance(produits, list) else [produits]
            for produit in candidats:
                if isinstance(produit, dict) and normaliser_id(produit) == cible:
                    return True
        return False

    @staticmethod
    def identifiant(depositaire: dict[str, Any]) -> str | None:
        return normaliser_id(depositaire)

    # Aucune methode de desactivation n'est exposee, et c'est DELIBERE.
    # `PATCH /{id}/status/{bool}` modifie bien le champ `is_active`, mais
    # n'arrete ni les collectes ni les retraits sur les souscriptions
    # existantes (FRA-203). Exposer une « fermeture » qui ne ferme rien
    # inviterait a construire une logique fausse.
