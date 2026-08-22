"""
app/clients/base.py
===================
Socle HTTP commun a toutes les cibles externes du Loader.

Ce module ne connait aucun metier. Il porte uniquement ce que les 9 services
FinZuu ont en commun — et surtout ce qu'ils ont en commun de DEFAILLANT, chaque
garde-fou ci-dessous neutralisant un ecart empirique documente :

  D-USR-1  concurrence plafonnee a 20, PARTAGEE par les neuf clients — au-dela
           de 20 a 30 requetes simultanees, la degradation est SILENCIEUSE :
           aucun HTTP 429 n'avertit (H14/H15). Le semaphore etait par client
           jusqu'au 09/08 : neuf plafonds de 25 ne plafonnaient rien.
  D-USR-2  retry sur erreur transitoire seulement — l'idempotence serveur est
           confirmee excellente (pattern no-op detection), donc rejouer est sur.
  D-USR-5  pagination cappee a 100 — le serveur accepte limit=9999999999 (H20).
  D-USR-6  X-Request-Id genere ici, et journalise ici : le serveur ignore celui
           du client (H19) et ses propres logs sont pollues a 99 % par les
           kube-probes (H23). Notre SIEM local est la seule tracabilite reelle.
  D-USR-7  parsing du wrapper custom {status_code, response_type, description,
           data} — ce n'est PAS le format natif FastAPI {detail: [...]}.
  D-USR-8  parsing datetime defensif — le suffixe Z est parfois absent (H11).
  D-DEP-7  le token ROOT est le seul utilise en ecriture (FRA-205).

Aucun secret n'est journalise : le SIEM n'ecrit JAMAIS les en-tetes de requete
(donc jamais le Bearer), et masque les champs de mot de passe des corps envoyes.
C'est deliberement plus strict que le serveur, qui lui persiste le JWT en clair
dans ses propres logs pendant 7 jours (VIOL-06.7, CRITIQUE).
"""

from __future__ import annotations

import asyncio
import json
import uuid
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

import httpx
from pydantic import BaseModel

from app.core.config import settings

#: `D-USR-1` — plafond de concurrence. Au-dela, degradation SILENCIEUSE, sans
#: `429` (`H14`/`H15`, mesure du 08/08 : le domaine sûr est 20 a 30 workers).
#:
#: **Valeur corrigee le 09/08 : 25 -> 20.** Deux raisons, et la seconde est la
#: vraie.
#:
#: 1. On prend la BORNE BASSE du domaine mesure. Un service qui repond `429` se
#:    laisse piloter ; un service qui degrade sans le dire transforme la
#:    surcharge en corruption — sur des services sans `DELETE`. Quand la panne
#:    est muette, on ne s'approche pas du bord pour voir ou il est.
#:
#: 2. **Le plafond n'etait pas global.** Chaque client construisait SON propre
#:    semaphore : neuf clients x 25 = jusqu'a **225 requetes simultanees**,
#:    quand la mesure en donne 30 pour maximum. Le plafond existait dans le code
#:    et n'existait pas dans les faits. D'ou `semaphore_partage()` ci-dessous.
MAX_CONCURRENCE: Final = 20

#: Le semaphore est partage par TOUS les clients d'une meme boucle, et cree
#: paresseusement : un semaphore construit hors boucle, ou sur une boucle morte,
#: leve `RuntimeError` a l'acquisition.
#:
#: **`WeakKeyDictionary`, pas `dict[int, ...]` indexe par `id(boucle)`.** CPython
#: reutilise les adresses : une boucle fermee puis une nouvelle creee peuvent
#: partager le meme `id`, et la seconde heriterait alors du semaphore de la
#: premiere — a moitie epuise, sans que rien ne le signale. La reference faible
#: fait disparaitre l'entree avec la boucle.
_SEMAPHORES: Final[weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]] = (
    weakref.WeakKeyDictionary()
)


def semaphore_partage() -> asyncio.Semaphore:
    """Le plafond de concurrence COMMUN aux neuf clients.

    Un plafond par client ne plafonne rien : ce sont les services FinZuu qui
    degradent, pas chaque route prise isolement. La contrainte est globale,
    le garde-fou doit l'etre aussi.
    """
    boucle = asyncio.get_running_loop()
    semaphore = _SEMAPHORES.get(boucle)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENCE)
        _SEMAPHORES[boucle] = semaphore
    return semaphore


#: D-USR-5 — le serveur ne borne pas `limit`, le client s'en charge.
LIMITE_PAGE_MAX: Final = 100

#: D-USR-2 — nombre total de tentatives sur erreur transitoire.
MAX_TENTATIVES: Final = 3

#: Marge de renouvellement du token : l'access_token vit 4 h (INV-USR-07), on
#: le renouvelle avant, jamais au moment ou il expire en pleine campagne.
MARGE_RENOUVELLEMENT: Final = timedelta(minutes=10)

#: Duree de vie mesuree le 08/08 — `access` 4 h, `refresh` 7 j, `auth` 10 min.
DUREE_ACCESS: Final = timedelta(hours=4)
DUREE_REFRESH: Final = timedelta(days=7)


@dataclass
class SessionAuth:
    """L'authentification du Loader — **une seule pour les neuf clients**.

    POURQUOI ELLE EST PARTAGEE
    --------------------------
    Chaque client tenait SON token et faisait DONC son propre `/auth/login` :
    neuf logins pour une campagne. Or `INV-USR-19` impose un anti-brute-force
    **a 3 tentatives** sur le compte. Neuf ouvertures de session pour un seul
    utilisateur ROOT, c'est deja une anomalie de securite ; au moindre echec
    reseau, c'est un verrouillage de compte en pleine campagne.

    POURQUOI LE VERROU
    ------------------
    **C'est le point le plus dangereux.** Sans lui, 20 workers qui rencontrent
    un token expire au meme instant lancent **20 `/auth/login` simultanes**. Le
    seuil anti-brute-force est a 3. Le verrou fait qu'un seul renouvelle et que
    les dix-neuf autres attendent son resultat.

    POURQUOI `/auth/refresh` — `ECART-38`
    -------------------------------------
    Le Loader se reloguait a chaque expiration, alors qu'un `refresh_token`
    valide 7 jours est rendu des le premier login. La WebApp ignore cette route ;
    le CDC nous impose de l'implementer. Un `refresh` n'est pas une tentative
    d'authentification : il ne compte pas dans les 3 essais.
    """

    access: str | None = None
    refresh: str | None = None
    access_expire_le: datetime | None = None
    refresh_expire_le: datetime | None = None
    verrou: asyncio.Lock = field(default_factory=asyncio.Lock)

    def access_utilisable(self) -> bool:
        return (
            self.access is not None
            and self.access_expire_le is not None
            and datetime.now(UTC) + MARGE_RENOUVELLEMENT < self.access_expire_le
        )

    def refresh_utilisable(self) -> bool:
        return (
            self.refresh is not None
            and self.refresh_expire_le is not None
            and datetime.now(UTC) + MARGE_RENOUVELLEMENT < self.refresh_expire_le
        )

    def enregistrer(self, donnees: Mapping[str, Any]) -> str:
        """Retient ce que le serveur vient de rendre.

        Le JWT porte son `exp`, mais on ne le decode pas pour en deduire un
        droit (`ECART-39`) — seulement pour cadencer le renouvellement, et
        encore : on prefere les durees MESUREES, un JWT pouvant etre modifie
        sans que sa duree annoncee le soit.
        """
        access = donnees.get("access_token")
        if not access:
            raise ValueError("access_token absent de la reponse")
        maintenant = datetime.now(UTC)
        self.access = str(access)
        self.access_expire_le = maintenant + DUREE_ACCESS
        if refresh := donnees.get("refresh_token"):
            self.refresh = str(refresh)
            self.refresh_expire_le = maintenant + DUREE_REFRESH
        return self.access


#: Une session par boucle, pour la meme raison que le semaphore : les tests en
#: ouvrent plusieurs, et `asyncio.Lock` se lie a la boucle qui l'utilise.
_SESSIONS: Final[weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, SessionAuth]] = (
    weakref.WeakKeyDictionary()
)


def session_partagee() -> SessionAuth:
    """La session d'authentification COMMUNE aux neuf clients."""
    boucle = asyncio.get_running_loop()
    session = _SESSIONS.get(boucle)
    if session is None:
        session = SessionAuth()
        _SESSIONS[boucle] = session
    return session


#: Champs masques avant journalisation. INV-USR-19 impose par ailleurs qu'un
#: login echoue ne soit JAMAIS rejoue automatiquement (anti-brute-force a
#: 3 tentatives) — c'est pourquoi `_token_valide` leve au premier echec au lieu
#: d'entrer dans la boucle de retry.
_CHAMPS_MASQUES: Final = frozenset({"password", "new_password", "old_password"})


class ReponseServeur(BaseModel):
    """Wrapper de reponse commun aux 9 services (D-USR-7).

    `paginate` n'est present que sur les endpoints de liste. Il porte
    {total, per_page, current_page, last_page} — c'est `last_page` qui borne
    le parcours, jamais une heuristique sur la taille du lot recu.
    """

    status_code: int
    response_type: str
    description: str
    data: Any = None
    paginate: dict[str, Any] | None = None


class ErreurService(Exception):
    """Echec d'un appel a un service FinZuu, avec son contexte complet.

    Porte le request_id genere localement : c'est le seul identifiant de
    correlation existant, le serveur n'en fournit aucun (H18).
    """

    def __init__(
        self,
        service: str,
        methode: str,
        url: str,
        status: int,
        detail: str,
        request_id: str,
    ) -> None:
        self.service = service
        self.methode = methode
        self.url = url
        self.status = status
        self.detail = detail
        self.request_id = request_id
        super().__init__(
            f"[{service}] {methode} {url} -> HTTP {status} : {detail} (req={request_id})"
        )


def parse_datetime(valeur: str | None) -> datetime | None:
    """Parse defensif — le suffixe Z est present ou absent selon l'endpoint (H11).

    Retourne None plutot que de lever : une date illisible ne doit jamais
    interrompre une campagne de generation.
    """
    if not valeur:
        return None
    brut = valeur.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(brut)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def normaliser_id(document: Mapping[str, Any]) -> str | None:
    """Renvoie l'identifiant, quel que soit le champ utilise par l'endpoint.

    Les services exposent tantot `_id` (fuite MongoDB, VIOL-06.1) tantot `id`,
    et company-service est incoherent entre ses propres endpoints
    (ANO-CPY-CONTRAT-12).
    """
    for cle in ("_id", "id"):
        valeur = document.get(cle)
        if valeur:
            return str(valeur)
    return None


def _masquer(donnees: Any) -> Any:
    """Retire les secrets avant journalisation."""
    if isinstance(donnees, dict):
        return {
            cle: ("***" if str(cle).lower() in _CHAMPS_MASQUES else _masquer(valeur))
            for cle, valeur in donnees.items()
        }
    if isinstance(donnees, list):
        return [_masquer(element) for element in donnees]
    return donnees


class JournalRequetes:
    """SIEM applicatif local, une ligne JSONL par requete.

    Indispensable : les logs serveur sont inexploitables (H23, 99 % de bruit
    kube-probe) et aucun en-tete de correlation n'est renvoye (H18).
    """

    def __init__(self, chemin: Path | None = None) -> None:
        horodatage = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        self.chemin = chemin or Path("logs") / f"loader_{horodatage}.jsonl"
        self.chemin.parent.mkdir(parents=True, exist_ok=True)

    def ecrire(self, **champs: Any) -> None:
        entree = {"timestamp": datetime.now(UTC).isoformat(), **_masquer(champs)}
        with self.chemin.open("a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(entree, ensure_ascii=False, default=str) + "\n")


class ClientFinZuu:
    """Client HTTP mutualise vers un service FinZuu.

    Une instance par service — jamais un client generique unique : chaque
    service porte ses propres ecarts, les fusionner effacerait cette realite
    (10_component.puml).
    """

    def __init__(
        self,
        nom_service: str,
        base_url: str,
        *,
        journal: JournalRequetes | None = None,
        #: Injectable pour les tests. En production il reste `None` et le
        #: semaphore PARTAGE s'applique — c'est le seul plafond qui plafonne.
        semaphore: asyncio.Semaphore | None = None,
        #: Injectable pour les tests. `None` en production : la session
        #: PARTAGEE s'applique, et c'est elle qui evite les neuf logins.
        session: SessionAuth | None = None,
    ) -> None:
        self.nom_service = nom_service
        self.base_url = base_url.rstrip("/")
        self._journal = journal or JournalRequetes()
        # `D-USR-1` — semaphore PARTAGE, jamais un par client. Un plafond de 20
        # applique neuf fois n'est pas un plafond de 20 : c'est 180. Il est
        # resolu a l'usage, pas ici : `__init__` n'est pas toujours appele
        # depuis une boucle en cours d'execution.
        self._semaphore = semaphore
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            http2=True,
            follow_redirects=True,
        )
        # `ECART-38` — la session est PARTAGEE par les neuf clients. Un token
        # par client, c'etait neuf `/auth/login` pour une campagne, quand
        # `INV-USR-19` verrouille le compte a la 3e tentative echouee.
        # Resolue a l'usage : `__init__` n'est pas toujours appele depuis une
        # boucle en cours d'execution.
        self._session: SessionAuth | None = session

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.fermer()

    async def fermer(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------------------
    # Authentification — D-DEP-7 : ROOT exclusivement
    # ----------------------------------------------------------------------

    async def _token_valide(self) -> str:
        """Renvoie un access_token frais, partage par les neuf clients.

        Jamais de token colle en dur ni recycle d'une session precedente.

        Le VERROU est le coeur de cette methode. Sans lui, 20 workers qui
        rencontrent un token expire au meme instant lancent 20 `/auth/login`
        simultanes, et `INV-USR-19` verrouille le compte a la 3e tentative.
        Un seul renouvelle, les autres attendent son resultat — et la double
        verification apres acquisition evite qu'ils renouvellent a leur tour.
        """
        session = self._session or session_partagee()
        if session.access_utilisable() and session.access is not None:
            return session.access

        async with session.verrou:
            # Deuxieme lecture : un autre worker a peut-etre renouvele pendant
            # qu'on attendait le verrou. Sans elle, le verrou serialiserait les
            # renouvellements au lieu de les eviter.
            if session.access_utilisable() and session.access is not None:
                return session.access

            if session.refresh_utilisable():
                # `ECART-38` — la route que la WebApp ignore. Un refresh n'est
                # PAS une tentative d'authentification : il ne compte pas dans
                # les 3 essais d'`INV-USR-19`.
                try:
                    return await self._rafraichir(session)
                except ErreurService as erreur:
                    # Le refresh a ete refuse : on retombe sur le login, qui
                    # est legitime ici. On le DIT, parce qu'un refresh refuse
                    # avant terme est un fait a remonter.
                    self._journal.ecrire(
                        service="user-service",
                        action="refresh",
                        statut="refuse",
                        detail={"motif": erreur.detail[:600]},
                    )
                    session.refresh = None
                    session.refresh_expire_le = None

            return await self._ouvrir_session(session)

    async def _rafraichir(self, session: SessionAuth) -> str:
        """`POST /auth/refresh` — `ECART-38`, absent de la WebApp."""
        request_id = str(uuid.uuid4())
        reponse = await self._client.post(
            f"{settings.user_service_base}/api/v1/auth/refresh",
            json={"refresh_token": session.refresh},
            headers={"X-Request-Id": request_id},
        )
        if reponse.status_code != 200:
            raise ErreurService(
                "user-service",
                "POST",
                "/auth/refresh",
                reponse.status_code,
                reponse.text[:300],
                request_id,
            )
        try:
            token = session.enregistrer(reponse.json().get("data", {}))
        except ValueError as erreur:
            raise ErreurService(
                "user-service", "POST", "/auth/refresh", 200, str(erreur), request_id
            ) from erreur
        self._journal.ecrire(
            service="user-service", action="refresh", statut="succes", request_id=request_id
        )
        return token

    async def _ouvrir_session(self, session: SessionAuth) -> str:
        """`POST /auth/login` — la seule voie qui compte dans les 3 tentatives."""
        if not settings.root_username or not settings.root_password:
            raise ErreurService(
                self.nom_service,
                "POST",
                "/auth/login",
                0,
                "ROOT_USERNAME / ROOT_PASSWORD absents de l'environnement",
                "-",
            )

        request_id = str(uuid.uuid4())
        reponse = await self._client.post(
            f"{settings.user_service_base}/api/v1/auth/login",
            json={"username": settings.root_username, "password": settings.root_password},
            headers={"X-Request-Id": request_id},
        )
        # INV-USR-19 : un login echoue n'est JAMAIS rejoue automatiquement.
        if reponse.status_code != 200:
            raise ErreurService(
                "user-service",
                "POST",
                "/auth/login",
                reponse.status_code,
                reponse.text[:300],
                request_id,
            )

        try:
            token = session.enregistrer(reponse.json().get("data", {}))
        except ValueError as erreur:
            raise ErreurService(
                "user-service", "POST", "/auth/login", 200, str(erreur), request_id
            ) from erreur
        self._journal.ecrire(
            service="user-service", action="login", statut="succes", request_id=request_id
        )
        return token

    # ----------------------------------------------------------------------
    # Appel HTTP
    # ----------------------------------------------------------------------

    async def requete(
        self,
        methode: str,
        chemin: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        vide_si_404: bool = False,
        token_alternatif: str | None = None,
    ) -> ReponseServeur:
        """Emet une requete authentifiee et renvoie le wrapper serveur parse.

        `vide_si_404` traite un HTTP 404 comme un resultat vide plutot que comme
        une erreur — necessaire par exemple sur les souscriptions d'un
        Depositaire qui n'en a aucune, ou le serveur repond 404 la ou un 200
        avec liste vide serait attendu.

        `token_alternatif` remplace le token ROOT pour CET appel. Un seul cas
        l'exige, mais il est imperatif : `PUT /auth/password/f/change` refuse le
        token ROOT avec « Type de token invalide. Attendu: auth » et n'accepte
        que l'`auth_token` rendu par `register` (mesure du 08/08). C'est
        precisement ce qui a laisse 15 users sur 18 bloques a
        `is_first_login=true` dans l'environnement.
        """
        token = token_alternatif or await self._token_valide()
        url = f"{self.base_url}{chemin}"
        params_bornes = self._borner_pagination(params)
        derniere_erreur: str = ""
        statut = 0

        for tentative in range(1, MAX_TENTATIVES + 1):
            request_id = str(uuid.uuid4())
            entetes = {"Authorization": f"Bearer {token}", "X-Request-Id": request_id}
            try:
                async with self._semaphore or semaphore_partage():
                    reponse = await self._client.request(
                        methode, url, params=params_bornes, json=json_body, headers=entetes
                    )
            except httpx.HTTPError as exc:
                derniere_erreur = f"{type(exc).__name__}: {exc}"
                statut = 0
                self._journal.ecrire(
                    service=self.nom_service,
                    methode=methode,
                    url=url,
                    statut="reseau",
                    detail=derniere_erreur,
                    tentative=tentative,
                    request_id=request_id,
                )
                if tentative < MAX_TENTATIVES:
                    await asyncio.sleep(2 ** (tentative - 1))
                    continue
                break

            statut = reponse.status_code
            self._journal.ecrire(
                service=self.nom_service,
                methode=methode,
                url=url,
                statut=statut,
                params=dict(params_bornes or {}),
                body=json_body,
                request_id=request_id,
            )

            if statut == 404 and vide_si_404:
                return ReponseServeur(
                    status_code=404,
                    response_type="Not Found",
                    description="aucun resultat",
                    data=[],
                )
            if 200 <= statut < 300:
                return self._parser(reponse, request_id)

            derniere_erreur = reponse.text[:300]
            # D-USR-2 : on ne rejoue que le transitoire. Un 4xx est une erreur
            # de notre payload — le rejouer ne ferait que la repeter.
            if statut < 500 or tentative == MAX_TENTATIVES:
                break
            await asyncio.sleep(2 ** (tentative - 1))

        raise ErreurService(self.nom_service, methode, url, statut, derniere_erreur, "-")

    async def get(
        self,
        chemin: str,
        *,
        params: Mapping[str, Any] | None = None,
        vide_si_404: bool = False,
    ) -> ReponseServeur:
        return await self.requete("GET", chemin, params=params, vide_si_404=vide_si_404)

    async def lister_tout(
        self, chemin: str, *, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Parcourt toutes les pages et renvoie les documents agreges.

        Pagination `?limit=<N>&page=<P>`, 1-based, avec `paginate.last_page`
        en borne — jamais `?skip=&take=`, que les services ne connaissent pas.
        """
        agrege: list[dict[str, Any]] = []
        page = 1
        while True:
            base = dict(params or {})
            base.update({"limit": LIMITE_PAGE_MAX, "page": page})
            reponse = await self.get(chemin, params=base, vide_si_404=True)
            lot: list[Any] = reponse.data if isinstance(reponse.data, list) else []
            agrege.extend(element for element in lot if isinstance(element, dict))
            derniere_page = page
            if reponse.paginate:
                try:
                    derniere_page = int(reponse.paginate.get("last_page", page))
                except (TypeError, ValueError):
                    derniere_page = page
            if not lot or page >= derniere_page:
                break
            page += 1
        return agrege

    # ----------------------------------------------------------------------
    # Interne
    # ----------------------------------------------------------------------

    @staticmethod
    def _borner_pagination(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
        """D-USR-5 — `limit` cappe cote client, le serveur ne le borne pas."""
        if params is None:
            return None
        bornes = dict(params)
        if "limit" in bornes:
            try:
                bornes["limit"] = min(int(bornes["limit"]), LIMITE_PAGE_MAX)
            except (TypeError, ValueError):
                bornes["limit"] = LIMITE_PAGE_MAX
        return bornes

    def _parser(self, reponse: httpx.Response, request_id: str) -> ReponseServeur:
        """D-USR-7 — wrapper custom, jamais le format natif FastAPI."""
        try:
            charge = reponse.json()
        except ValueError as exc:
            raise ErreurService(
                self.nom_service,
                str(reponse.request.method),
                str(reponse.request.url),
                reponse.status_code,
                f"reponse non JSON ({exc})",
                request_id,
            ) from exc

        if not isinstance(charge, dict) or "status_code" not in charge:
            # Certains endpoints repondent hors wrapper : on encapsule nous-memes
            # plutot que d'echouer, la donnee restant exploitable.
            return ReponseServeur(
                status_code=reponse.status_code,
                response_type="Success",
                description="reponse hors wrapper",
                data=charge,
            )

        return ReponseServeur.model_validate(charge)
