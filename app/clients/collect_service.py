"""
app/clients/collect_service.py
==============================
Client collect-service — epargne et collecte (UC-15, EF-77).

⚠️ **L'anomalie la plus dangereuse de tout l'ecosysteme est ici.**

`FRA-195` — **ecriture fantome** : un montant negatif ou nul produit un **rejet
HTTP apparent** mais une **mutation REELLE et silencieuse** en base. Le serveur
dit non et fait quand meme. Aucune reponse HTTP ne permet de detecter la
corruption : elle ne se voit qu'en relisant la Collecte plus tard.

C'est pourquoi `valider_montant()` leve **avant** tout appel reseau. Ce n'est
pas une precaution de confort — c'est la seule barriere existante. Le CDC en
fait une discipline non negociable (`D-COL-9`).

Les autres disciplines portees ici :

  D-COL-1   Souscription Depositaire<->Produit AVANT toute collecte.
  D-COL-2   Nouvelle epargne : `client_id` + `product_id` + `depositary_id` ensemble.
  D-COL-3   Contribution suivante : `collect_id` + `amount` seuls.
  D-COL-4   Ne JAMAIS s'attendre a voir le compte CHECKING bouger lors d'une
            collecte. Epargne et compte courant sont deux flux distincts —
            collect-service gere l'epargne, account-service les paiements.

            **OU VA L'ARGENT, formule positivement** (mesure du 11/08, preuve
            avant/apres sur notre propre mutation) : il credite **UNIQUEMENT le
            compte `CLASSIC` du Depositaire** — l'institution partenaire. Jamais
            le compte du client.

            Dire ou l'argent NE VA PAS ne suffit pas : pour verifier qu'une
            collecte a reellement abouti (`CR-12`), il faut relire le `CLASSIC`
            du Depositaire. La forme de la transaction est un `DEPOSIT` ou
            **`src_account == dest_account`** : le compte du Depositaire
            s'auto-credite.
  D-COL-10  Respecter `amount_min` de la Policy. Le message de plafond est
            trompeur (`FRA-198`), on se fie a la Policy, jamais au message.
  D-COL-11  Ne JAMAIS simuler de cloture : elle est bloquee (`FRA-196`) et
            aucun bouton n'existe cote UI. Aucune methode ici.
  D-COL-12  `collect_quantity` obligatoire pour un produit PRODUCT (`FRA-197`).
  D-COL-13  Ne PAS simuler de collectes PRODUCT tant que `FRA-197` n'est pas
            corrige — le garde-fou est dans `valider_collecte()`.
  D-COL-14  ⚠️ **DECLASSEE LE 11/08.** Cette discipline affirmait que
            l'atomicite du Retrait etait « confirmee FIABLE » et « l'un des
            rares comportements sur lesquels on peut s'appuyer ».

            **Aucune mesure de retrait n'existe dans nos documents
            empiriques** — verifie le 11/08. Le grand livre invoque est
            probablement la transaction du 31/07 que nous avons convenu de
            mettre de cote.

            Ce que le contrat garantit, et rien de plus : `WithdrawalSchema`
            exige `amount` + `collect_id`.

            Le simuler au Sprint 5 sans le mesurer d'abord ferait echouer
            `CR-12` — « solde = initial + decaissements - remboursements » —
            sans qu'on sache pourquoi. **Une certitude emprunte est plus
            dangereuse qu'une inconnue declaree.**
  D-COL-16  Les Produits doivent etre corrects AVANT toute Collecte : le Product
            embarque dans une Collecte est une **copie figee**, jamais
            resynchronisee. Une correction ulterieure ne se repercute pas.
QUI A LE DROIT DE COLLECTER — ET NOUS N'EN FAISONS PAS PARTIE
-------------------------------------------------------------
La matrice RBAC du Document Fonctionnel est nette : **`COMPANY` et `CUSTOMER`**
collectent. **Jamais `ROOT`, jamais `STAFF`.** Le Staff **confirme** un depot au
Dashboard apres remise du cash physique ; il ne l'initie pas.

Or le Loader ecrit **exclusivement en ROOT** (`D-DEP-7`, `FRA-205`). Chaque
collecte que nous simulerons sera donc **hors matrice**, exactement comme nos
ecritures sur depositary-service.

**Ce n'est pas un contournement, c'est un ecart ASSUME et DECLARE.** `EF-77`
nous impose de simuler l'epargne des 2 000 clients ; aucun autre jeton ne nous
est disponible. L'ecart doit figurer dans le rapport de run, jamais etre tu —
sinon nous affirmerions une conformite RBAC que nous n'avons pas.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.clients.contracts import PolicyType
from app.core.config import settings


class MontantInvalide(ValueError):
    """Montant refuse AVANT l'appel — FRA-195, ecriture fantome."""


class CollecteNonSimulable(ValueError):
    """Type de collecte bloque cote serveur — on ne le simule pas."""


def valider_montant(montant: float, amount_min: float | None = None) -> None:
    """Barriere unique contre l'ecriture fantome (`FRA-195`, `D-COL-9`).

    Un montant negatif ou nul est rejete en apparence par le serveur, mais
    mute la base pour de vrai. Le rejet doit donc arriver AVANT le reseau —
    aucune verification post-appel ne pourrait rattraper la corruption.

    `amount_min` vient de la Policy du produit (`D-COL-10`). On ne se fie
    jamais au message d'erreur serveur, qui annonce un plafond faux
    (`FRA-198`).
    """
    if montant <= 0:
        raise MontantInvalide(
            f"montant={montant} refuse AVANT envoi. FRA-195 : collect-service "
            f"rejette en apparence mais mute la base silencieusement. "
            f"Aucune correction n'est possible apres coup."
        )
    if amount_min is not None and montant < amount_min:
        raise MontantInvalide(
            f"montant={montant} sous l'amount_min de la Policy ({amount_min}) — D-COL-10"
        )


def valider_collecte(policy_type: PolicyType, collect_quantity: float | None) -> None:
    """Refuse ce que le serveur ne sait pas encore traiter.

    Deux regles distinctes, dans cet ordre volontaire :

    1. `D-COL-12` — un produit PRODUCT exige `collect_quantity`. C'est une regle
       de CONTRAT, durable : elle restera vraie apres correction du serveur.
    2. `D-COL-13` / `FRA-197` — les collectes PRODUCT sont **bloquees
       structurellement** aujourd'hui. C'est une limitation TEMPORAIRE.

    L'ordre compte : en verifiant le contrat avant la limitation, la regle
    durable reste vivante et testee. Le jour ou `FRA-197` sera corrige, il
    suffira de retirer le second bloc — le premier sera deja en place.

    On peut parfaitement SOUSCRIRE a un produit PRODUCT : le catalogue doit
    rester complet (`D-PRD-9`). Souscrire n'est pas collecter.
    """
    if policy_type is PolicyType.PRODUCT and collect_quantity is None:
        raise MontantInvalide("collect_quantity obligatoire pour un produit PRODUCT (D-COL-12)")
    if policy_type is PolicyType.PRODUCT:
        raise CollecteNonSimulable(
            "collecte PRODUCT bloquee cote serveur (FRA-197, D-COL-13). "
            "La souscription reste possible, la collecte non."
        )


class CollectServiceClient:
    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu(
            "collect-service", settings.collect_service_base, journal=journal
        )

    async def fermer(self) -> None:
        await self._client.fermer()

    async def lister(self) -> list[dict[str, Any]]:
        return await self._client.lister_tout("/api/v1/collects/")

    async def collectes_du_client(self, client_id: UUID | str) -> list[dict[str, Any]]:
        cible = str(client_id)
        return [
            collecte
            for collecte in await self.lister()
            if str(collecte.get("client_id") or normaliser_id(collecte.get("client") or {}))
            == cible
        ]

    async def ouvrir_epargne(
        self,
        *,
        client_id: UUID | str,
        product_id: UUID | str,
        depositary_id: UUID | str,
        montant: float,
        policy_type: PolicyType,
        amount_min: float | None = None,
        collect_quantity: float | None = None,
    ) -> dict[str, Any]:
        """D-COL-2 — les trois references partent ENSEMBLE a l'ouverture.

        Prerequis non negociable (`D-COL-1`) : le Depositaire doit avoir
        souscrit au produit AVANT. Sinon la collecte n'a aucun sens metier.
        """
        valider_collecte(policy_type, collect_quantity)
        valider_montant(montant, amount_min)

        payload: dict[str, Any] = {
            "client_id": str(client_id),
            "product_id": str(product_id),
            "depositary_id": str(depositary_id),
            "amount": montant,
        }
        if collect_quantity is not None:
            payload["collect_quantity"] = collect_quantity

        reponse = await self._client.requete("POST", "/api/v1/collects/collect", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def ajouter_contribution(
        self, collect_id: UUID | str, montant: float, amount_min: float | None = None
    ) -> dict[str, Any]:
        """D-COL-3 — une contribution suivante ne porte que `collect_id` et
        `amount`. Renvoyer les trois references ouvrirait une seconde epargne."""
        valider_montant(montant, amount_min)
        payload = {"collect_id": str(collect_id), "amount": montant}
        reponse = await self._client.requete("POST", "/api/v1/collects/collect", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    @staticmethod
    def identifiant(collecte: dict[str, Any]) -> str | None:
        return normaliser_id(collecte)

    # Aucune methode de cloture n'est exposee — DELIBERE.
    # FRA-196 : la cloture est bloquee cote serveur, et aucun bouton n'existe
    # dans l'UI. D-COL-11 l'exclut du perimetre : simuler une cloture qui
    # n'aboutit pas produirait un ecosysteme mensonger.
