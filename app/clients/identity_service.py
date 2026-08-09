"""
app/clients/identity_service.py
===============================
Client identity-service — le 9e et dernier client du perimetre.

**A quoi il sert exactement, et a quoi il ne sert PAS.**

Il ne sert **pas** a l'onboarding des 2000 clients : `POST /clients/onboard`
cascade lui-meme vers identity-service. Creer l'Identity en amont produirait une
Identity **orpheline**, que rien ne rattacherait au Client — et ce service
n'expose **aucun DELETE**.

Il sert aux Users que le Loader cree **explicitement** : les 60 a 100 agents de
terrain et personnels d'IMF (`UC-09`), et l'Admin de chaque Company (`D-CMP-2`).
`CreateUserSchema.identity` est **requis** : une Identity doit exister AVANT le
User. La sequence n'est pas un choix.

Tout ce qui suit vient de l'audit du 09/08/2026
(`docs/empirical/2026-08-09_identity_service_audit.md`), contrat lu
integralement puis mesure.

CE QUE CE SERVICE FAIT BIEN
---------------------------
**Son authentification est reellement appliquee** — `401` sur toutes les routes
metier, seul `/health` est ouvert. C'est le **premier service du perimetre dont
la securite declaree n'est pas dementie par la mesure**, en contraste net avec
`FRA-205`.

LES QUATRE DISCIPLINES
----------------------
  D-IDN-1  **Valider les enums COTE LOADER.** `gender` et `marital_status` sont
           des `string` LIBRES dans `CreateIdentitySchema`, alors qu'ils sont
           des enums strictes en mise a jour et en recherche. **Le seul schema
           qui ecrit la donnee est le seul qui ne la valide pas.** Mesure du
           09/08 : `gender="peu importe"` -> HTTP 201, persiste tel quel.
           `EF-22` (deux femmes pour un homme) repose entierement sur ce champ.
           `ANY` existe dans l'enum serveur et n'est JAMAIS emis.
  D-IDN-2  **Toujours renseigner la geographie.** `Address.country`, `city`,
           `region` et les coordonnees sont OPTIONNELS et persistes a `null`
           quand on les omet — alors que `nationality` est requise. Le Loader
           les renseigne tous, depuis `Loader_Base`.
  D-IDN-3  **Paginer.** `limit` vaut **10** par defaut, sans que rien ne
           signale la troncature. Tout inventaire passe par le socle.
  D-IDN-4  **Ne jamais appeler `/ocr/*`.** Trois routes de reconnaissance de
           caracteres, hors perimetre : elles supposent un document reel, nous
           n'en produisons aucun.

TROIS PIEGES DE PLUS
--------------------
  convention   `POST /api/v1/identities/**create**` — les huit autres services
               creent par `POST /<ressource>/`. Une transposition mecanique
               donnerait 404 ou 405.
  nationalite  l'ISO 3166-1 alpha-2 est bien validee (`ZZ` -> 422), mais
               **sans tenir compte de la casse** : `cm` passe en 201. La base
               accumule donc `CM` et `cm`. Le Loader emet des majuscules.
  aucun DELETE Troisieme service dans ce cas avec account et depositary. Le
               prefixe `DEMO_` est notre SEULE reversibilite.

DEUX ZONES VOLONTAIREMENT NON EXPLOREES
---------------------------------------
`POST /identities/{id}/validate` — un endpoint de validation KYC **sans corps**,
absent de toutes nos sources. Semantique inconnue : bascule-t-il un statut ?
Est-il idempotent ? **Non teste, parce que c'est une ecriture.**

Et le service se declare **« Auth Service » v1.0.1** — mal etiquete. Sans
consequence, mais deroutant pour qui inspecte le contrat.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.clients.contracts import IdentityType
from app.core.config import settings
from app.core.invariants import InvariantViole, exiger_champs_renseignes, valider_identite_complete

#: `D-IDN-2` — les champs d'adresse que le Loader renseigne TOUJOURS, alors que
#: le contrat les declare optionnels et les persiste a `null`.
CHAMPS_ADRESSE_OBLIGATOIRES: tuple[str, ...] = (
    "address_line_1",
    "street_name",
    "city",
    "region",
    "country",
)


class IdentityServiceClient:
    """Identites d'etat civil — le referentiel KYC de la plateforme.

    Ne pas confondre avec user-service : celui-ci porte **qui est la personne**,
    celui-la **ce qu'elle a le droit de faire**. Le lien est unidirectionnel :
    `User.identity` pointe ici, jamais l'inverse.
    """

    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu(
            "identity-service", settings.identity_service_base, journal=journal
        )

    async def fermer(self) -> None:
        await self._client.fermer()

    # ----------------------------------------------------------------------
    # Lecture — D-IDN-3 : paginer, toujours
    # ----------------------------------------------------------------------

    async def lister(self) -> list[dict[str, Any]]:
        """Inventaire complet. `limit` vaut **10** par defaut cote serveur, sans
        aucun signal de troncature — le socle le borne a 100 et suit
        `last_page`."""
        return await self._client.lister_tout("/api/v1/identities/")

    async def chercher_par_email(self, email: str) -> dict[str, Any] | None:
        """`GET`-avant-`POST`. identity-service impose l'unicite de l'email —
        mesure du 09/08 via la cascade client : « Identity with this email
        already exists ». Mais **il ne normalise pas** : `Demo@x` et `demo@x` y
        produisent deux Identities. On interroge donc en minuscules."""
        reponse = await self._client.get(
            f"/api/v1/identities/by-email/{email.strip().lower()}", vide_si_404=True
        )
        return reponse.data if isinstance(reponse.data, dict) else None

    async def chercher_par_telephone(self, telephone: str) -> dict[str, Any] | None:
        reponse = await self._client.get(
            f"/api/v1/identities/by-phone/{telephone.strip()}", vide_si_404=True
        )
        return reponse.data if isinstance(reponse.data, dict) else None

    async def lire(self, identity_id: UUID | str) -> dict[str, Any] | None:
        reponse = await self._client.get(f"/api/v1/identities/{identity_id}", vide_si_404=True)
        return reponse.data if isinstance(reponse.data, dict) else None

    # ----------------------------------------------------------------------
    # Ecriture — la seule, et elle est definitive
    # ----------------------------------------------------------------------

    async def creer(
        self,
        *,
        first_name: str,
        last_name: str,
        date_of_birth: str,
        gender: str,
        nationality: str,
        marital_status: str,
        id_number: str,
        id_place: str,
        id_expire_on: str,
        phone: str,
        email: str,
        occupation: str,
        address: dict[str, Any],
        place_of_birth: str = "",
        type_identite: IdentityType = IdentityType.INDIVIDUAL,
    ) -> dict[str, Any]:
        """Cree une Identity et renvoie **ce que le serveur a rendu**.

        Toutes les regles de `app/core/invariants.py` sont appliquees AVANT
        l'appel. Ce n'est pas du zele : ce service n'expose **aucun DELETE**,
        une Identity absurde y resterait a vie.

        `type` est le seul des trois champs enumeres reellement valide par le
        serveur (`422` sur une valeur hors enum). `gender` et `marital_status`
        ne le sont pas — c'est nous, et nous seuls (`D-IDN-1`).
        """
        controle = valider_identite_complete(
            naissance=date_of_birth,
            expiration_piece=id_expire_on,
            genre=gender,
            situation_familiale=marital_status,
            nationalite=nationality,
            id_number=id_number,
            email=email,
        )

        # D-IDN-2 — le contrat declare ces champs optionnels et les persiste a
        # `null`. Nous disposons du referentiel : un champ vide serait une perte
        # de richesse, jamais une fatalite.
        exiger_champs_renseignes(address, CHAMPS_ADRESSE_OBLIGATOIRES)

        corps: dict[str, Any] = {
            "type": type_identite.value,
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": _en_datetime(controle["date_of_birth"]),
            "place_of_birth": place_of_birth,
            "gender": controle["gender"],
            "nationality": controle["nationality"],
            "marital_status": controle["marital_status"],
            "id_number": controle["id_number"],
            "id_place": id_place,
            "id_expire_on": _en_datetime(controle["id_expire_on"]),
            "phone": str(phone).strip(),
            "email": controle["email"],
            "occupation": occupation,
            "address": dict(address),
        }

        # Convention divergente : `create` en suffixe, contrairement aux huit
        # autres services. Une transposition mecanique donnerait 404 ou 405.
        reponse = await self._client.requete("POST", "/api/v1/identities/create", json_body=corps)
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def creer_si_absente(self, **champs: Any) -> tuple[dict[str, Any], bool]:
        """`GET`-avant-`POST` sur l'email. Renvoie `(identite, creee)`.

        L'idempotence est ici **irremplacable** : sans elle, un rejeu laisserait
        des Identities orphelines qu'aucun `DELETE` ne pourrait retirer.
        """
        existante = await self.chercher_par_email(str(champs.get("email", "")))
        if existante is not None:
            return existante, False
        return await self.creer(**champs), True

    # ----------------------------------------------------------------------
    # Ce que le Loader n'appelle jamais
    # ----------------------------------------------------------------------

    @staticmethod
    def identifiant(identite: dict[str, Any]) -> str | None:
        """L'identifiant **rendu par le serveur** — le seul qui fasse foi.

        Sur company-service, `owner._id` est requis au contrat puis ignore
        (`FRA-227`) ; sur client-service, `identity._id` subit le meme sort. Ici
        le champ n'est meme pas au schema de creation. Dans les trois cas la
        regle est identique : **relire ce qui est rendu**.
        """
        return normaliser_id(identite)


def _en_datetime(valeur: Any) -> str:
    """Le contrat attend un `date-time`, pas une `date`.

    `date_of_birth` et `id_expire_on` sont declares `format: date-time`. Nos
    invariants manipulent des `date` — la conversion se fait ici, une seule
    fois, plutot que chez chaque appelant.
    """
    texte = str(valeur)
    return texte if "T" in texte else f"{texte}T00:00:00"


__all__ = [
    "CHAMPS_ADRESSE_OBLIGATOIRES",
    "IdentityServiceClient",
    "InvariantViole",
]
