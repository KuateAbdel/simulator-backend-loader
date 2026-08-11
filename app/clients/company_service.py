"""
app/clients/company_service.py
==============================
Client company-service — Companies et Licences (UC-07, UC-08).

Disciplines portees ici, toutes issues de mesures ou de la page Service Anatomy :

  D1  `_id` et `id` sont incoherents ENTRE les endpoints de ce service meme
      (`ANO-CPY-CONTRAT-12`) — on passe systematiquement par `normaliser_id()`.
  D5  GET-avant-POST par `short_name`, declare unique (`INV-CPY-01`) : on ne
      decouvre pas un doublon en HTTP 400, on l'evite.
  D6  `GET /companies/{company_name}` est du CODE MORT — la route est interceptee
      par `{company_id}` (`ANO-CPY-ROUTE-01`). Elle n'est pas exposee ici.
  D10 `self_sharing` n'est pas documente au contrat et porte des valeurs
      incoherentes (0 vs null) — ignore.
  D-CMP-2  `owner` declenche une VRAIE cascade vers identity-service.
      `admin_email` n'en declenche AUCUNE : l'Admin User se cree explicitement,
      via `user_service.creer_utilisateur_applicatif()`.
  FRA-199  `currency` est write-only et PERDU a la persistance — le Loader garde
      sa propre trace de la devise de chaque Company.

`industries` et `sectors` exigent `minItems: 1` (`INV-CPY-03`/`04`) : un tableau
vide provoque un HTTP 422. La validation est faite ici, avant l'appel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.clients.contracts import CompanyType, PackageName
from app.core.config import settings

if TYPE_CHECKING:
    # SEULE INVERSION DE COUCHE DU PROJET, retiree de l'execution le 11/08.
    # Un client (transport) importait un service (metier) : la dependance allait
    # a contresens de `ENF-08`. Sous `TYPE_CHECKING`, le typage reste complet et
    # plus aucune importation ne se produit au chargement du module.
    from app.services.generateur import Adresse, IdentiteGeneree


class CompanyServiceClient:
    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu(
            "company-service", settings.company_service_base, journal=journal
        )

    async def fermer(self) -> None:
        await self._client.fermer()

    # ----------------------------------------------------------------------
    # Companies
    # ----------------------------------------------------------------------

    async def lister_companies(self) -> list[dict[str, Any]]:
        return await self._client.lister_tout("/api/v1/companies/")

    async def chercher_par_short_name(self, short_name: str) -> dict[str, Any] | None:
        """GET-avant-POST (D5). `short_name` est declare unique (INV-CPY-01).

        On parcourt la liste plutot que d'utiliser `GET /companies/{name}` :
        cette route est du code mort, interceptee par `{company_id}`.
        """
        cible = short_name.strip().lower()
        for company in await self.lister_companies():
            if str(company.get("short_name", "")).strip().lower() == cible:
                return company
        return None

    async def obtenir_company(self, company_id: UUID | str) -> dict[str, Any] | None:
        reponse = await self._client.get(f"/api/v1/companies/{company_id}", vide_si_404=True)
        return reponse.data if isinstance(reponse.data, dict) else None

    async def creer_company(
        self,
        *,
        name: str,
        short_name: str,
        type_company: CompanyType,
        owner: IdentiteGeneree,
        adresse: Adresse,
        admin_email: str,
        currency: str,
        industries: list[str],
        sectors: list[str],
        parent_company_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Cree une Company. La cascade Identity part avec `owner` (D-CMP-2).

        Ce qui NE part PAS en cascade : l'Admin User. `admin_email` est
        write-only et ne cree rien — il faut appeler user-service ensuite.
        """
        if not industries or not sectors:
            raise ValueError(
                "industries et sectors exigent minItems=1 (INV-CPY-03/04) — "
                "un tableau vide provoque un HTTP 422"
            )

        payload: dict[str, Any] = {
            "name": name,
            "short_name": short_name,
            "type": type_company.value,
            "industries": industries,
            "sectors": sectors,
            "owner": owner.en_payload(),
            "address": adresse.en_payload(),
            "admin_email": admin_email,
            "currency": currency,
        }
        # Auto-reference parent/filiale. Le parent doit exister, sinon le serveur
        # repond « Parent company not found » (INV-CPY-09).
        if parent_company_id is not None:
            payload["company_id"] = str(parent_company_id)

        reponse = await self._client.requete("POST", "/api/v1/companies/", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    @staticmethod
    def identifiant(company: dict[str, Any]) -> str | None:
        """D1 — `_id` ou `id` selon l'endpoint interroge."""
        return normaliser_id(company)

    @staticmethod
    def identifiant_owner(company: dict[str, Any]) -> str | None:
        """Verification de la cascade D-CMP-2 : l'Identity a-t-elle bien ete creee ?"""
        owner = company.get("owner")
        return normaliser_id(owner) if isinstance(owner, dict) else None

    # ----------------------------------------------------------------------
    # Licences — UC-07
    # ----------------------------------------------------------------------

    async def licences_de_company(self, company_id: UUID | str) -> list[dict[str, Any]]:
        reponse = await self._client.get(f"/api/v1/licenses/company/{company_id}", vide_si_404=True)
        data = reponse.data
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        return [data] if isinstance(data, dict) else []

    async def creer_licence(
        self,
        company_id: UUID | str,
        packages: list[PackageName],
        date_debut: str,
        date_fin: str,
    ) -> dict[str, Any]:
        """Cree la licence. AUCUNE cascade : elle se cree explicitement apres la
        Company (`INV-CROSS-05`).

        UC-07 impose une validite couvrant « la fenetre historique 180 jours plus
        30 jours a venir » — l'appelant fournit les deux bornes, calculees depuis
        SIM_START_DATE.

        La licence conditionne le catalogue (UC-11) : READY_CASH pour le credit,
        READY_COLLECTE pour la collecte, ALL pour les deux. Une Company qui
        heberge des Kiosques sans READY_COLLECTE serait incoherente.
        """
        if not packages:
            raise ValueError("packages exige minItems=1 (INV-LIC-02)")

        payload = {
            "company_id": str(company_id),
            "packages": [p.value for p in packages],
            "start_date": date_debut,
            "end_date": date_fin,
        }
        reponse = await self._client.requete("POST", "/api/v1/licenses/", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def a_une_licence(self, company_id: UUID | str) -> bool:
        """Une Company peut exister sans licence (`INV-CROSS-04`, observe) — mais
        UC-07 exige qu'elle en ait une. On verifie avant de creer."""
        return bool(await self.licences_de_company(company_id))
