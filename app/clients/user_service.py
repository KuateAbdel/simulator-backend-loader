"""
app/clients/user_service.py
===========================
Client user-service — Users applicatifs et rôles RBAC.

**Le flow, et ce qui y engage vraiment** (D-CMP-2), revise le 15/09/2026 :

    POST /auth/register           -> 201, data.user + auth_token ("auth", 10 min)
                                     ENGAGEMENT — le User EXISTE, irreversible
    PUT  /auth/password/f/change  -> 200, avec le AUTH_TOKEN, pas le token ROOT
                                     FINITION  — sort le compte de is_first_login

Les deux etapes ne sont **plus liees**. Une finition ratee est une anomalie
consignee, jamais un User perdu : il est cree, user-service n'a aucun `DELETE`,
et le nier dans le rapport ne le fait pas disparaitre de la plateforme. Le run
REAL `56f28cf0` (14/09) l'a paye — « Staff cree : 0 » pour 81 Users bien reels.

Le `POST /auth/login` qui terminait le flow est **supprime** : aucun appelant ne
lisait son jeton, l'identifiant du User est deja dans `data.user.id`, et il
coutait un login par compte cree sur un service qui verrouille a la troisieme
tentative (`INV-USR-19`).

⚠️ **Ce flow ne peut plus aboutir — mesure du 15/09/2026.** `register` **ignore**
le `password` qu'on lui envoie, en genere un autre, et ne le communique **que par
courriel**. La reponse 201 ne le restitue pas (verifie : ni la valeur envoyee, ni
aucune cle autre que le booleen `password_expired`). Et l'etape 2 **verifie
l'ancien mot de passe** — `401 Current password is incorrect`.

Consequence : nos adresses generees etant fictives, personne ne recoit ce
courriel, et les comptes restent definitivement a `is_first_login=true`. C'est
la vraie cause de l'etat de l'environnement, et **non** la subtilite du token
ci-dessous. Bloquant remonte en **FRA-247**.

⚠️ **L'etape 2 refuse le token ROOT** : « Type de token invalide. Attendu: auth ».
Elle n'accepte que l'`auth_token` rendu par `register`. Vrai, mesure le 08/08,
mais ce n'est pas ce qui bloque aujourd'hui.

Autre detail mesure : tant que `is_first_login=true`, `access_token` est present
dans la reponse mais **VIDE** — la cle existe, la valeur non.

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

from app.clients.base import ClientFinZuu, ErreurService, JournalRequetes, normaliser_id
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

    async def lister_emails(self) -> set[str]:
        """TOUTES les adresses deja prises sur user-service, normalisees.

        `INV-USR-02` est GLOBAL a la plateforme, pas local au run : le premier
        run REAL (21/08) est mort d'avoir regenere `mbarga.mbarga@...` — une
        adresse posee par une company d'un chargement anterieur, invisible du
        registre. Une seule lecture au lancement, et le generateur ne peut
        plus emettre une adresse deja prise ou que ce soit.
        """
        return {
            adresse
            for utilisateur in await self._client.lister_tout("/api/v1/users/")
            if (adresse := str(utilisateur.get("email", "")).strip().lower())
        }

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
        """Cree le User et tente de le rendre utilisable. **Ne leve JAMAIS pour
        une finition ratee.**

        ⚠️ **L'etape 2 echoue par conception depuis le 15/09/2026** : le mot de
        passe reel est celui que le service a genere, pas `mot_de_passe_initial`,
        et il n'est connu que du destinataire du courriel. Voir FRA-247. Le code
        reste en place tel quel : il redeviendra correct des que `register`
        honorera le mot de passe fourni, sans autre changement ici.

        CE QUI A CHANGE LE 15/09/2026, ET POURQUOI
        ------------------------------------------
        Le flow valait TOUT OU RIEN : une etape 2 refusee levait, et l'appelant
        comptait l'agent en echec **alors que le User venait d'etre cree**. Le
        run REAL `56f28cf0` l'a paye au prix fort : rapport « Staff cree : 0 »,
        phase `FAILED`, run arrete — et **81 Users bel et bien presents** sur
        user-service, sans noeud chez nous ni rattachement Agent -> Kiosque
        (`UC-09`). Le Loader perdait l'Agent pour preserver son mot de passe.

        L'arbitrage est inverse, et c'est le meme que celui deja tranche pour
        `_identifiant_user` : **l'etape 1 est l'engagement**. Le User existe des
        qu'elle rend `201` ; tout ce qui suit est de la FINITION. Une finition
        ratee est une ANOMALIE CONSIGNEE, jamais un agent perdu.

        L'etape 3 (`POST /auth/login` sur le compte fraichement cree) est
        **supprimee**. Verifie le 15/09 : aucun appelant ne lisait le jeton
        qu'elle rendait, et l'identifiant du User dont le Loader a besoin est
        deja dans la reponse de `register` (`data.user.id`). C'etait une
        verification sans consommateur — et 81 logins inutiles sur un service
        qui verrouille a la troisieme tentative (`INV-USR-19`).

        Renvoie le User rendu par `register`, augmente de `finition` :
        `{"aboutie": bool, "motif": str}`.
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

        enregistrement = await self._client.requete(
            "POST", "/api/v1/auth/register", json_body=inscription
        )

        # ETAPE 1 ACQUISE — a partir d'ici, le User EXISTE chez FinZuu, et
        # user-service n'a aucun DELETE. Plus rien en dessous n'a le droit de
        # faire disparaitre ce fait du rapport.
        rendu = enregistrement.data if isinstance(enregistrement.data, dict) else {}
        interne = rendu.get("user")
        # `register` range le User sous `data.user` ; d'autres endpoints le
        # rendent a plat (`D1`). On accepte les deux, sans rien deviner de plus.
        utilisateur: dict[str, Any] = dict(interne) if isinstance(interne, dict) else dict(rendu)

        # L'etape 2 refuse le token ROOT : « Type de token invalide. Attendu: auth ».
        # Elle n'accepte QUE l'auth_token rendu par register, valide 10 minutes.
        # Mesure du 08/08 — et c'est exactement ce qui a laisse 15 users sur 18
        # bloques a is_first_login=true dans l'environnement.
        auth_token = rendu.get("auth_token")
        if not auth_token:
            utilisateur["finition"] = {
                "aboutie": False,
                "motif": (
                    "auth_token absent de la reponse de register — l'etape 2 est "
                    "impossible, le compte reste a is_first_login=true"
                ),
            }
            return utilisateur

        try:
            await self._client.requete(
                "PUT",
                "/api/v1/auth/password/f/change",
                json_body={
                    "email": email,
                    "password": mot_de_passe_initial,
                    "new_password": nouveau_mot_de_passe,
                },
                token_alternatif=str(auth_token),
            )
        except ErreurService as erreur:
            # `FRA-247` — cas connu et attendu tant que `register` genere son
            # propre mot de passe : « Current password is incorrect ». Le compte
            # reste a `is_first_login=true`, donc inutilisable par son porteur —
            # mais il EXISTE, il est rattachable, et le run continue.
            utilisateur["finition"] = {
                "aboutie": False,
                "motif": (
                    f"HTTP {erreur.status} sur /auth/password/f/change : {erreur.detail[:200]}"
                ),
            }
            return utilisateur

        utilisateur["finition"] = {"aboutie": True, "motif": ""}
        return utilisateur

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
