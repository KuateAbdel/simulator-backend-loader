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

LES DISCIPLINES DE CE SERVICE — `D-ACC-1` a `D-ACC-4`
-----------------------------------------------------
Elles ont ete etablies par l'audit monetaire du 08/08 (19 tests) et vivaient
jusqu'au 09/08 dans `docs/empirical/2026-08-08_flux_monetaires.md` SEULEMENT.
Une connaissance qui reste dans un rapport ne protege rien.

  D-ACC-1  **Ne JAMAIS presumer qu'un solde a bouge de `amount`.**
           `ANO-ACC-FEES-07`, mesure encadree d'un instantane des 56 comptes :
           un DEBIT de 500 sur un type a 100 de frais retire **400**. Ni 500,
           ni 600. Les frais ne sont ni ajoutes au debit, ni reverses a un
           compte de perception — ils sont RETRANCHES du montant demande, et
           credites NULLE PART (verifie sur les 56 comptes ; le compte `TAXE`
           du Kiosque reste a zero). Un Loader qui tiendrait sa propre
           comptabilite deriverait silencieusement. **Toujours relire le
           solde.**

  D-ACC-2  **Ne JAMAIS lire le statut pour savoir si l'argent a bouge.**
           `ANO-ACC-STATUS-05` : quatre chemins ont tous deplace des fonds, et
           rendu quatre statuts differents — `SUCCESS`, `SUCCESS`, `APPROVED`
           et **`PENDING`**. Le `WITHDRAWAL` de 850 a ramene le solde a zero
           et est reste `PENDING`, relu 20 secondes plus tard. Ce n'est pas un
           traitement asynchrone : c'est un statut qui ne signifie rien.

  D-ACC-3  **Lire `transaction-configs` AVANT toute campagne**, et n'emettre
           que des types dont les frais sont verifies a **0**. Cette table est
           modifiable par API — `TAXE` l'a ete le 28/07. Ce qui etait sans
           frais hier peut ne plus l'etre aujourd'hui. C'est la parade retenue
           par l'audit, portee ici par `verifier_frais_nuls()`.

  D-ACC-4  **Aucun `DELETE`.** Un compte cree ne peut qu'etre passe `CLOSED`.

CE QUI EST FIABLE ICI, ET IL FAUT LE DIRE AUSSI
-----------------------------------------------
account-service est **le service le mieux garde** mesure a ce jour : masse
conservee sur `transfer`, decouvert impossible, montant negatif refuse **sans
mutation**, idempotence reelle par `reference`, `SUSPENDED` bloquant vraiment.

Le contraste avec collect-service est majeur — `FRA-195` y etablit une mutation
reelle **sous un rejet apparent**. Deux services du meme ecosysteme, deux
niveaux de fiabilite opposes. C'est pourquoi les disciplines ne se generalisent
jamais d'un service a l'autre : elles se mesurent, service par service.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.clients.contracts import (
    AccountType,
    OwnerType,
    ProviderSource,
    TransactionTag,
    TransactionType,
)
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

    def payload_dotation_capital(
        self, *, compte_capital_id: UUID | str, montant: float, nom_lender: str
    ) -> dict[str, Any]:
        """`UC-10` point 2 — la dotation initiale du compte CAPITAL d'un Lender.

        POURQUOI `src == dest`
        ----------------------
        `CreditAccountSchema` exige **les deux** identifiants, meme pour un
        credit. Or cet argent vient de l'EXTERIEUR du systeme : c'est
        l'apport du bailleur, il ne sort d'aucun compte FinZuu. Le motif est
        celui que nous avons mesure sur une collecte — un `DEPOSIT` ou
        `src_account == dest_account`, le compte s'auto-credite — et
        `provider_src` porte l'origine reelle.

        LES TROIS VALEURS D'ENUM, ET POURQUOI CELLES-LA
        -----------------------------------------------
        `provider_src=BANK` : le capital d'un Lender arrive par virement
        bancaire. Ni `CASH` (ce n'est pas du liquide de guichet), ni `MOMO`
        (ce n'est pas du mobile money), ni `ACCOUNT` (aucun compte FinZuu
        source).

        `tag=LENDER` : **c'est le champ fait pour ca.** `TransactionTag.LENDER`
        est la SEULE occurrence du concept « lender » dans tout l'ecosysteme
        FinZuu — account-service sait TAGUER une transaction de bailleur sans
        connaitre l'entite. Ne pas l'utiliser ici serait laisser vide le seul
        endroit ou le serveur reconnait ce metier.

        `type=INVESTMENT` : le Manuel de Reference attribue au profil CO
        « l'initiation et la validation des investissements ». Doter un Lender
        EST un investissement — pas un depot, pas un transfert.
        """
        return {
            "amount": montant,
            "label": f"Dotation capital initial — {nom_lender}",
            "src_account_id": str(compte_capital_id),
            "dest_account_id": str(compte_capital_id),
            "provider_src": ProviderSource.BANK.value,
            "tag": TransactionTag.LENDER.value,
            "type": TransactionType.INVESTMENT.value,
        }

    async def crediter(self, payload: dict[str, Any]) -> dict[str, Any]:
        """`POST /accounts/credit`.

        **On ne deduit jamais le solde resultant** — `FRA-218` : les frais sont
        retranches du montant et credites nulle part. Le solde se RELIT, il ne se
        calcule pas.
        """
        reponse = await self._client.requete("POST", "/api/v1/accounts/credit", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def solde(self, account_id: UUID | str) -> float | None:
        """Relit le solde reel. La seule facon honnete de le connaitre (`FRA-218`)."""
        reponse = await self._client.get(f"/api/v1/accounts/{account_id}", vide_si_404=True)
        donnees = reponse.data if isinstance(reponse.data, dict) else {}
        valeur = donnees.get("balance")
        return float(valeur) if isinstance(valeur, int | float) else None

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

    # ------------------------------------------------------------------
    # `D-ACC-3` — la parade de l'audit monetaire, enfin executable
    # ------------------------------------------------------------------

    async def frais_par_type(self) -> dict[str, float]:
        """Lit `transaction-configs` — la table des frais, modifiable par API.

        Elle l'a ete le 28/07 pour `TAXE`. Ce qui etait sans frais hier peut ne
        plus l'etre : cette lecture est donc faite AU DEMARRAGE de chaque
        campagne, jamais mise en cache d'un run a l'autre.
        """
        reponse = await self._client.get("/api/v1/transaction-configs", vide_si_404=True)
        data = reponse.data
        lignes = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        frais: dict[str, float] = {}
        for ligne in lignes:
            if not isinstance(ligne, dict):
                continue
            type_transaction = str(ligne.get("type") or ligne.get("transaction_type") or "").upper()
            if not type_transaction:
                continue
            montant = ligne.get("fees", ligne.get("amount", 0))
            try:
                frais[type_transaction] = float(montant or 0)
            except (TypeError, ValueError):
                # Un montant illisible n'est pas « zero » : c'est un inconnu, et
                # `D-ACC-1` interdit de presumer. On le marque prohibitif pour
                # que `verifier_frais_nuls` le refuse.
                frais[type_transaction] = float("inf")
        return frais

    async def verifier_frais_nuls(self, types: list[str]) -> None:
        """`D-ACC-3` — refuse d'operer sur un type porteur de frais.

        Le Loader n'a aucune raison de simuler des frais : ils ne sont credites
        nulle part (`ANO-ACC-FEES-07`), donc la masse monetaire generee serait
        fausse sans qu'aucun compte ne porte la difference. Mieux vaut refuser
        que produire un grand livre qui ne s'equilibre pas.
        """
        table = await self.frais_par_type()
        fautifs = {t: table[t] for t in types if table.get(t.upper(), 0.0) != 0.0}
        if fautifs:
            raise ValueError(
                f"types a frais non nuls, refuses (`D-ACC-3`, `ANO-ACC-FEES-07`) : {fautifs}. "
                "Les frais sont retranches du montant demande et credites nulle part — "
                "la masse monetaire generee serait fausse."
            )

    @staticmethod
    def identifiant(compte: dict[str, Any]) -> str | None:
        return normaliser_id(compte)

    @staticmethod
    def types_presents(comptes: list[dict[str, Any]]) -> set[str]:
        return {str(c.get("type")) for c in comptes if c.get("type")}
