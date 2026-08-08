"""
app/clients/base.py
===================
Socle HTTP commun a toutes les cibles externes du Loader.

Ce module ne connait aucun metier. Il porte uniquement ce que les 9 services
FinZuu ont en commun — et surtout ce qu'ils ont en commun de DEFAILLANT, chaque
garde-fou ci-dessous neutralisant un ecart empirique documente :

  D-USR-1  concurrence plafonnee  — au-dela de 25 requetes simultanees, la
           degradation est SILENCIEUSE : aucun HTTP 429 n'avertit (H14/H15).
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
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

import httpx
from pydantic import BaseModel

from app.core.config import settings

#: D-USR-1 — plafond de concurrence. Au-dela, degradation silencieuse.
MAX_CONCURRENCE: Final = 25

#: D-USR-5 — le serveur ne borne pas `limit`, le client s'en charge.
LIMITE_PAGE_MAX: Final = 100

#: D-USR-2 — nombre total de tentatives sur erreur transitoire.
MAX_TENTATIVES: Final = 3

#: Marge de renouvellement du token : l'access_token vit 4 h (INV-USR-07), on
#: le renouvelle avant, jamais au moment ou il expire en pleine campagne.
MARGE_RENOUVELLEMENT: Final = timedelta(minutes=10)

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
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self.nom_service = nom_service
        self.base_url = base_url.rstrip("/")
        self._journal = journal or JournalRequetes()
        self._semaphore = semaphore or asyncio.Semaphore(MAX_CONCURRENCE)
        self._client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            http2=True,
            follow_redirects=True,
        )
        self._token: str | None = None
        self._token_expire_le: datetime | None = None

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
        """Renvoie un access_token frais, en le renouvelant avant expiration.

        Jamais de token colle en dur ni recycle d'une session precedente.
        """
        maintenant = datetime.now(UTC)
        if (
            self._token is not None
            and self._token_expire_le is not None
            and maintenant + MARGE_RENOUVELLEMENT < self._token_expire_le
        ):
            return self._token

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
        # INV-USR-19 : un login echoue n'est jamais rejoue automatiquement.
        if reponse.status_code != 200:
            raise ErreurService(
                "user-service",
                "POST",
                "/auth/login",
                reponse.status_code,
                reponse.text[:300],
                request_id,
            )

        donnees = reponse.json().get("data", {})
        token = donnees.get("access_token")
        if not token:
            raise ErreurService(
                "user-service",
                "POST",
                "/auth/login",
                200,
                "access_token absent de la reponse",
                request_id,
            )

        self._token = str(token)
        # Le JWT porte son exp, mais on ne le decode pas pour en deduire un
        # droit (ECART-39) — uniquement pour cadencer le renouvellement.
        self._token_expire_le = datetime.now(UTC) + timedelta(hours=4)
        self._journal.ecrire(
            service="user-service", action="login", statut="succes", request_id=request_id
        )
        return self._token

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
                async with self._semaphore:
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
