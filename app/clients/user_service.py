"""
app/clients/user_service.py
===========================
Client user-service — Users applicatifs et rôles RBAC.

**Le flow en 3 requêtes est obligatoire, jamais raccourci** (D-CMP-2) :

    POST /auth/register        -> HTTP 201, auth_token (10 min)
    PUT  /auth/password/f/change  -> HTTP 200, is_first_login passe a false
    POST /auth/login           -> access_token (4 h) + refresh_token (7 j)

Pourquoi trois et pas une : `admin_email` sur une Company ne cree AUCUN User —
confirme empiriquement, contrairement a `owner` qui cascade vraiment vers
identity-service. Et un User fraichement enregistre nait avec
`is_first_login=true` : il ne peut pas se connecter normalement tant que le mot
de passe n'a pas ete change. Mesure du 08/08 : **15 users sur 18 sont restes
bloques a cette etape**, precisement parce que le flow n'a jamais ete termine.

Contraintes portees ici :
  - `CreateUserSchema` exige `identity` : une Identity doit exister AVANT le User
  - `INV-USR-19` — anti-brute-force a 3 tentatives : un login echoue n'est
    JAMAIS rejoue automatiquement, `base.py` s'en charge
  - la route des roles est **`/groupes/`**, en francais. `/groups/` repond 404 —
    erreur de sondage commise le 08/08, corrigee
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.clients.contracts import TagGroupe, UserType
from app.core.config import settings


class UserServiceClient:
    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu("user-service", settings.user_service_base, journal=journal)

    async def fermer(self) -> None:
        await self._client.fermer()

    # ----------------------------------------------------------------------
    # Users applicatifs — le flow en 3 requetes
    # ----------------------------------------------------------------------

    async def chercher_par_email(self, email: str) -> dict[str, Any] | None:
        """GET-avant-POST. `INV-USR-02` impose l'unicite de l'email ; on evite le
        HTTP 400 plutot que de le decouvrir."""
        cible = email.strip().lower()
        for utilisateur in await self._client.lister_tout("/api/v1/users/"):
            if str(utilisateur.get("email", "")).strip().lower() == cible:
                return utilisateur
        return None

    async def creer_utilisateur_applicatif(
        self,
        *,
        user_name: str,
        email: str,
        mot_de_passe_initial: str,
        nouveau_mot_de_passe: str,
        identity_id: UUID | str,
        type_user: UserType,
        groupes: list[str] | None = None,
        company_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Execute le flow complet et renvoie les jetons du User cree.

        Les trois etapes sont indissociables : s'arreter apres la premiere
        laisserait un compte a `is_first_login=true`, incapable de se connecter.
        C'est exactement l'etat de 15 des 18 users de l'environnement.
        """
        inscription: dict[str, Any] = {
            "user_name": user_name,
            "email": email,
            "password": mot_de_passe_initial,
            "type_user": type_user.value,
            "identity": str(identity_id),
            "groupes": groupes or [],
        }
        if company_id is not None:
            inscription["company_id"] = str(company_id)

        await self._client.requete("POST", "/api/v1/auth/register", json_body=inscription)

        await self._client.requete(
            "PUT",
            "/api/v1/auth/password/f/change",
            json_body={
                "email": email,
                "password": mot_de_passe_initial,
                "new_password": nouveau_mot_de_passe,
            },
        )

        connexion = await self._client.requete(
            "POST",
            "/api/v1/auth/login",
            json_body={"username": user_name, "password": nouveau_mot_de_passe},
        )
        return connexion.data if isinstance(connexion.data, dict) else {}

    # ----------------------------------------------------------------------
    # Roles RBAC — D-USR-10
    # ----------------------------------------------------------------------

    async def lister_groupes(self) -> list[dict[str, Any]]:
        """Route en FRANCAIS. `/api/v1/groups/` repond 404."""
        return await self._client.lister_tout("/api/v1/groupes/")

    async def chercher_groupe(self, nom: str) -> dict[str, Any] | None:
        cible = nom.strip().lower()
        for groupe in await self.lister_groupes():
            if str(groupe.get("name", "")).strip().lower() == cible:
                return groupe
        return None

    async def creer_groupe(
        self,
        *,
        nom: str,
        description: str,
        tag: TagGroupe,
        permissions: list[str],
        company_id: str = "",
    ) -> dict[str, Any]:
        """Cree un role metier (D-USR-10).

        `company_id` vaut la chaine VIDE pour un role global — c'est ce que
        portent les 4 groupes existants, verifie le 08/08. D'ou 12 groupes au
        total, crees une seule fois, et non 60 a 100 dupliques par Company.

        `description` est REQUISE au contrat. `routes` reste vide, comme sur les
        groupes existants.
        """
        payload = {
            "name": nom,
            "description": description,
            "tag": tag.value,
            "company_id": company_id,
            "permissions": permissions,
        }
        reponse = await self._client.requete("POST", "/api/v1/groupes/create", json_body=payload)
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def supprimer_groupe(self, groupe_id: UUID | str) -> None:
        """`DELETE` existe sur les groupes — rare dans cet ecosysteme, et c'est
        ce qui rend la creation des 12 roles reversible."""
        await self._client.requete("DELETE", f"/api/v1/groupes/{groupe_id}")

    async def lister_permissions(self) -> list[str]:
        """Les 84 permissions, par NOM (jamais par UUID).

        Les 22 permissions `LENDER` sont ecartees : elles relevent du Sprint 5,
        hors perimetre du Loader (D-07). La permission parasite RC169_* aussi.
        """
        noms: list[str] = []
        for permission in await self._client.lister_tout("/api/v1/permissions/"):
            nom = str(permission.get("name", ""))
            if not nom or nom.startswith(("LENDER_", "RC169")):
                continue
            noms.append(nom)
        return sorted(noms)

    @staticmethod
    def identifiant(document: dict[str, Any]) -> str | None:
        return normaliser_id(document)
