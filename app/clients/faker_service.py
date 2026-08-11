"""
app/clients/faker_service.py
============================
Le client Faker fintech4esg — **famille A exclusivement**.

CE QUE FAKER EST DANS LE LOADER
-------------------------------
Le CDC ne laisse pas de place au doute. §321 :

    « L'outil combinera DEUX sources de generation : d'une part l'API Faker
    pour les payloads clients et l'historique de credit, d'autre part un
    GENERATEUR INTERNE pour les entites organisationnelles absentes de Faker
    (compagnies, lenders institutionnels, branches, agences, kiosques,
    agents). »

Et §863 en donne la raison d'etre :

    « Faker est la source unique et suffisante des decisions de scoring pour
    le Loader, ce qui preserve l'ISOLATION du Loader vis-a-vis du service
    externe ReadyScore. »

Faker remplace donc ReadyScore : c'est le mur qui nous en isole (`EF-80`).
Il est une source d'IDENTITE, jamais l'autorite sur l'ecosysteme.

POURQUOI CE CLIENT N'HERITE PAS DE `ClientFinZuu`
-------------------------------------------------
Trois differences de protocole, aucune negociable :

  1. **Aucune authentification.** Mesure du 08/08 : `security: null`,
     `securitySchemes: {}`, et aucun appel refuse sans en-tete. La question
     ouverte `Q-02` de la Cartographie — « obtenir une cle x-api-key aupres
     d'Oti » — est SANS OBJET. `ClientFinZuu.requete()` exige un token ROOT
     de user-service : l'imposer ici serait un login inutile de plus, quand
     `INV-USR-19` verrouille le compte a la 3e tentative echouee.
  2. **Aucune enveloppe.** Les neuf services FinZuu repondent
     `{status_code, response_type, description, data}`. Faker rend du JSON
     brut, non type — les schemas `ClientResponse` et `ClientEnrichedItem`
     decrits par certaines analyses N'EXISTENT PAS dans le contrat.
  3. **Un timeout beaucoup plus court.** Voir plus bas : ici le timeout est
     une protection, pas une commodite.

C'est le raisonnement du `10_component.puml` : *« chacun porte ses propres
defauts specifiques, les fusionner effacerait cette realite. »*

LA FAMILLE A, ET RIEN D'AUTRE
-----------------------------
Faker contient **deux populations disjointes**, et le CDC a ete ecrit en
supposant qu'il n'y en avait qu'une. C'est la cause racine unique de trois
exigences inapplicables telles qu'ecrites (`EF-20`, `EF-80`, `UC-13`).

                     famille A            famille B
    `seed`           OUI -> illimite      NON -> figee au run_id
    volume           nos 2000 clients     quelques dizaines
    scoring          absent               present
    geographie       absente              partielle

**Ce client refuse structurellement d'appeler la famille B.** Ce n'est pas
une precaution de style : un identifiant de famille A interroge sur un
endpoint de famille B ne rend pas un 404 propre, il provoque un **TIMEOUT**
(mesure du 08/08). Dans la boucle de vie — 180 jours x 2000 clients — un run
ne terminerait jamais. Le serveur ne protege pas ; nous, si.

LE CACHE, ET POURQUOI LE `seed` EST LE SEUL MOYEN D'ITERER
----------------------------------------------------------
    « `/random` est mis en cache par JEU DE PARAMETRES COMPLET. Deux appels
    aux parametres strictement identiques renvoient toujours le meme
    client. »

45 appels identiques -> 1 seul client distinct. C'est ce piege qui a produit
le faux « 100 % APPROVED » du sondage S2. En famille A, `seed` est le seul
parametre qui perce le cache — 180 seeds ont rendu 180 clients distincts,
zero collision.

Le CDC §185 en tire la consequence exacte : *« Si le client_id est deja
consomme (determinisme du cache Redis Faker), le Loader change le parametre
seed et refait un appel jusqu'a obtenir un nouveau client_id unique. »*

LE SENEGAL
----------
`country_code=SN` rend **HTTP 422** : l'enum du contrat est `BF/CI/CM`. Cela
concerne 500 des 2000 clients, et `OBJ-01`/`EF-05` exigent QUATRE pays — on
ne descend pas a trois. Ce client refuse SN LOCALEMENT, avec le motif, plutot
que d'emettre un appel dont on connait deja l'echec : c'est ce que `CT-04`
demande (« valider les filtres avant chaque appel »). Les clients senegalais
relevent du generateur interne — arbitrage `A-01`.

CE QUE CE CLIENT NE FAIT PAS
----------------------------
  - `POST /v1/faker/cache/clear` : **JAMAIS**. Il reinitialiserait le cache
    Redis partage par toute l'equipe. Il n'est meme pas ecrit ici.
  - aucun endpoint de famille B ni de famille C.
  - aucune ecriture, d'aucune sorte. Faker est en lecture seule stricte.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final, Self

import httpx

from app.clients.base import (
    MAX_TENTATIVES,
    ErreurService,
    JournalRequetes,
    semaphore_partage,
)
from app.core.config import settings

#: Les trois seuls pays de l'enum `country_code` en famille A. `SN` en est
#: absent et rend HTTP 422 — mesure du 08/08, et §5.3 de la Cartographie v1.1
#: (« SN accepte au runtime ») est PERIMEE.
PAYS_FAKER: Final[frozenset[str]] = frozenset({"BF", "CI", "CM"})

#: Le pays cible que Faker ne sert pas. Isole ici pour que le message d'erreur
#: puisse nommer l'arbitrage plutot que de rendre un 422 opaque.
PAYS_SANS_SOURCE: Final = "SN"

#: Timeout COURT, et c'est une protection. Le timeout general
#: (`http_timeout_seconds`, 15 s) vise des services qui repondent ; ici on se
#: protege d'un endpoint qui ne repond PAS — `playground-client` a ete mesure a
#: 90 s le 08/08, contre 25 s en juillet : le probleme s'aggrave.
TIMEOUT_FAKER_S: Final = 8.0

#: Les 6 `company_type` confirmes par 24 tirages a seeds varies, avec leur
#: distribution observee : Entreprise Individuelle 6, SA 6, SARL 4,
#: Fondation 4, SAS 3, Association 1. Le « TVE uniquement » d'un sondage
#: anterieur etait un artefact de cache — il n'y a AUCUNE limitation.
TYPES_COMPANY_FAKER: Final[frozenset[str]] = frozenset(
    {"Entreprise Individuelle", "SA", "SARL", "SAS", "Fondation", "Association"}
)


class CategorieClient:
    """Les deux valeurs de `customer_category`.

    C'est le SEUL filtre de distribution qui fonctionne vraiment chez Faker :
    `EF-23` (80 % Individual / 20 % Corporate) s'obtient par parametre. `EF-22`
    et `EF-24` ne s'obtiennent par aucun filtre — voir le moteur de quotas.
    """

    INDIVIDUAL: Final = "Individual"
    BUSINESS: Final = "Business"


class FamilleInterdite(RuntimeError):
    """Tentative d'appel vers la famille B ou C.

    Existe pour que l'interdit soit une ERREUR DE PROGRAMMATION visible, et
    non un timeout de 90 s decouvert en production.
    """


class PaysSansSource(ValueError):
    """`country_code` hors de l'enum de la famille A — aujourd'hui, `SN`."""


@dataclass(frozen=True, slots=True)
class IdentiteFaker:
    """La piece d'identite, telle que Faker la rend.

    ⚠ `ID_ISSUE_DATE` et `ID_EXPIRY_DATE` sont en **DD/MM/YYYY**, pas en ISO.
    Une piece mesuree le 08/08 expirait dans 11 JOURS : `id_expire_on` doit
    toujours etre verifie avant injection, jamais recopie en confiance.
    """

    type_piece: str | None
    numero: str | None
    emission: date | None
    expiration: date | None

    @property
    def expiree_ou_imminente(self) -> bool:
        """Vraie si la piece expire dans moins de 30 jours (ou est deja expiree)."""
        if self.expiration is None:
            return True
        return (self.expiration - date.today()).days < 30


@dataclass(frozen=True, slots=True)
class CompanyFaker:
    """L'objet `company`, present uniquement sur les clients Business.

    **`nom` est un PLACEHOLDER et ne doit jamais atteindre le serveur.**
    15 tirages sur 3 pays : « Test Business CM 748 », « Test Business CI 200 »,
    « Test Business BF 470 ». Or `UC-08` exige « un nom metier credible », et la
    demo cible Nordic Microfinance, IFC, AFD, BAD.

    Ce qui EST exploitable : `type_juridique` (6 valeurs empiriques) et
    `secteurs`. Le Loader compose la raison sociale a partir de cette matiere
    et du patronyme du client — on assemble, on n'invente pas.
    """

    identifiant: str | None
    #: Conserve pour la tracabilite, JAMAIS pour nommer une entite.
    nom_placeholder: str | None
    type_juridique: str | None
    secteurs: tuple[str, ...] = ()

    @property
    def type_exploitable(self) -> str | None:
        """Le type juridique s'il fait partie des 6 valeurs confirmees."""
        return self.type_juridique if self.type_juridique in TYPES_COMPANY_FAKER else None

    @property
    def secteur_principal(self) -> str | None:
        """`sector_assignments` est ordonne par `rank` — le rang 1 en tete."""
        return self.secteurs[0] if self.secteurs else None


@dataclass(frozen=True, slots=True)
class ClientFaker:
    """Un client de famille A — **12 champs racine, et c'est tout**.

    SONT ABSENTS, et mesures absents : `region`, `city`, `district`, `sector`,
    `postal_code`, `residency`, `operator`, `age`, `birth_date`,
    `place_of_birth`, `civility`, `email`, `occupation`, `address`.

    > Certaines analyses affirment que « Faker fournit region + city +
    > district + sector + postal_code par client — pas besoin de tout
    > inventer ». **C'est faux pour la famille A**, la seule capable de fournir
    > nos 2000 clients.

    Tout ce qui manque vient de NOTRE referentiel et de notre generateur : la
    geographie tiree du pays, la date de naissance, l'adresse, l'occupation.
    C'est le composeur hybride, pas ce client.
    """

    client_id: str
    pays: str
    devise: str
    categorie: str
    msisdn: str | None
    prenom: str | None
    nom: str | None
    nom_complet: str | None
    #: `WOMAN` / `MAN` chez Faker. La traduction vers l'enum serveur appartient
    #: au composeur : ce client ne deforme pas ce qu'il recoit.
    genre: str | None
    identite: IdentiteFaker | None
    company: CompanyFaker | None
    #: Les 11 cles reellement portees : IS_RGS_1/7/30/90, IS_DATA_RGS1/7/30/90,
    #: IS_SMARTPHONE_USER, LAST_EVENT_DATE, LAST_EVENT_TYPE. AUCUN montant —
    #: `MOB_MONEY_ACCOUNT_AMOUNT` n'existe pas ici (arbitrage `A-09`).
    quick_win: dict[str, Any] = field(default_factory=dict)
    #: Le `seed` qui l'a produit. Necessaire a `ENF-15` : rejouer un run doit
    #: rejouer les memes tirages.
    seed: int | None = None

    @property
    def est_business(self) -> bool:
        return self.categorie == CategorieClient.BUSINESS

    @property
    def patronyme(self) -> str | None:
        """Le nom de famille — matiere premiere des raisons sociales.

        ⚠ Les patronymes forment un POOL COMMUN aux pays : `Ngwa` est sorti au
        Burkina, `Some` au Cameroun (mesure du 11/08). Faker ne garantit donc
        AUCUNE distinction nationale des noms ; c'est le composeur qui ancre au
        pays, via le referentiel.
        """
        return self.nom


def _date_fr(valeur: Any) -> date | None:
    """Parse une date Faker. **DD/MM/YYYY**, jamais ISO — et defensivement.

    `EF-32` : « gerer les cas d'absence par une entree neutre, SANS interrompre
    l'execution globale ». Une piece illisible ne fait pas echouer 2000 clients.
    """
    if not isinstance(valeur, str) or not valeur.strip():
        return None
    for motif in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valeur.strip(), motif).date()
        except ValueError:
            continue
    return None


def _texte(valeur: Any) -> str | None:
    return valeur.strip() or None if isinstance(valeur, str) else None


class FakerClient:
    """Client HTTP vers Faker fintech4esg — famille A, lecture seule."""

    NOM: Final = "faker"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        journal: JournalRequetes | None = None,
        semaphore: asyncio.Semaphore | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.faker_base_url).rstrip("/")
        self._journal = journal or JournalRequetes()
        # Le semaphore est PARTAGE avec les neuf clients FinZuu, et c'est
        # volontaire : le plafond `H14/H15` de 20 appels concurrents porte sur
        # NOTRE machine et sur notre reseau, pas sur un serveur en particulier.
        # Un semaphore propre a Faker ferait 20 + 20 = 40.
        self._semaphore = semaphore
        self._client = httpx.AsyncClient(
            timeout=TIMEOUT_FAKER_S,
            follow_redirects=True,
            transport=transport,
        )
        # `EF-29` / CDC §187 — « si l'API Faker retourne une erreur ou un
        # timeout, le Loader applique une strategie de repli sur un cache local
        # des payloads recemment recuperes ». Le voici. Il ne se substitue jamais
        # a un tirage neuf : il sert quand Faker ne repond plus, pour qu'une
        # campagne de 2000 clients ne meure pas sur une panne tierce.
        self._repli: dict[tuple[str, str, int], ClientFaker] = {}

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.fermer()

    async def fermer(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Famille A — les trois seuls endpoints que ce client connait
    # ------------------------------------------------------------------

    async def tirer_client(
        self, pays: str, categorie: str, seed: int
    ) -> ClientFaker | None:
        """Tire UN client de famille A. `None` si Faker ne repond pas.

        `seed` est obligatoire, et ce n'est pas un detail : sans lui, le cache
        rend indefiniment le meme client. Il est aussi ce qui rend `ENF-15`
        tenable — rejouer un run, c'est rejouer ses seeds.

        Rend `None` plutot que de lever quand Faker est en panne : `EF-32` et le
        risque `R-...` « Faker devient indisponible pendant une execution »
        demandent que l'execution globale ne s'interrompe pas. L'appelant decide
        — et le journal d'intention garde la trace.
        """
        self._valider_pays(pays)
        chemin = (
            "/v1/faker/client/business"
            if categorie == CategorieClient.BUSINESS
            else "/v1/faker/client/individual"
        )
        brut = await self._get(chemin, {"country_code": pays, "seed": seed})
        if brut is None:
            # Repli sur le cache local : le meme (pays, categorie, seed) a
            # peut-etre deja repondu plus tot dans ce run.
            return self._repli.get((pays, categorie, seed))

        client = self._parser_client(brut, seed)
        if client is None:
            return None

        # `EF-21` — « verifier que le pays retourne par Faker correspond au pays
        # demande AVANT TOUTE INJECTION ». Le controle a de nouveau un sens
        # depuis que Faker valide ses filtres (`CT-04` est perime : `ZZ` rend 422
        # au lieu d'un client au hasard), mais un service tiers peut regresser.
        if client.pays != pays:
            self._journal.ecrire(
                service=self.NOM,
                methode="GET",
                url=chemin,
                statut="incoherence",
                detail=f"EF-21 : demande {pays}, recu {client.pays} — client ecarte",
            )
            return None

        self._repli[(pays, categorie, seed)] = client
        return client

    async def sante(self) -> bool:
        """`GET /health`. Utile au controle de prevol, avant d'ecrire quoi que ce soit."""
        return await self._get("/health", None) is not None

    # ------------------------------------------------------------------
    # Les interdits, rendus explicites
    # ------------------------------------------------------------------

    def _refuser_famille_b(self, endpoint: str) -> None:
        """Jamais appele en interne — existe pour documenter et pour tester l'interdit."""
        raise FamilleInterdite(
            f"{endpoint} appartient a la famille B ou C. Nos 2000 clients sont de "
            "famille A, et croiser les deux ne rend pas un 404 mais un TIMEOUT "
            "(mesure du 08/08). Dans la boucle 180 jours x 2000 clients, le run "
            "ne terminerait jamais."
        )

    def _valider_pays(self, pays: str) -> None:
        if pays in PAYS_FAKER:
            return
        if pays == PAYS_SANS_SOURCE:
            raise PaysSansSource(
                "SN rend HTTP 422 — l'enum de la famille A est BF/CI/CM. Les 500 "
                "clients senegalais relevent du generateur interne, comme les "
                "Companies et les Depositaires que Faker ne fournit pas non plus "
                "(CDC §321). Arbitrage A-01."
            )
        raise PaysSansSource(
            f"country_code={pays!r} n'est pas dans l'enum de la famille A "
            f"{sorted(PAYS_FAKER)}. CT-04 impose de valider le filtre avant l'appel."
        )

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    async def _get(self, chemin: str, params: dict[str, Any] | None) -> Any | None:
        """GET sans authentification, avec rejeu du transitoire seulement.

        `D-USR-2` — un 4xx est une erreur de NOTRE requete : le rejouer ne ferait
        que la repeter. Seuls le reseau et les 5xx sont rejoues.
        """
        url = f"{self.base_url}{chemin}"
        for tentative in range(1, MAX_TENTATIVES + 1):
            request_id = str(uuid.uuid4())
            try:
                async with self._semaphore or semaphore_partage():
                    reponse = await self._client.get(
                        url, params=params, headers={"X-Request-Id": request_id}
                    )
            except httpx.HTTPError as exc:
                self._journal.ecrire(
                    service=self.NOM,
                    methode="GET",
                    url=url,
                    statut="reseau",
                    detail=f"{type(exc).__name__}: {exc}",
                    tentative=tentative,
                    request_id=request_id,
                )
                if tentative < MAX_TENTATIVES:
                    await asyncio.sleep(2 ** (tentative - 1))
                    continue
                return None

            self._journal.ecrire(
                service=self.NOM,
                methode="GET",
                url=url,
                statut=reponse.status_code,
                params=params or {},
                request_id=request_id,
            )
            if 200 <= reponse.status_code < 300:
                try:
                    return reponse.json()
                except ValueError:
                    return None
            if reponse.status_code < 500 or tentative == MAX_TENTATIVES:
                # Un 422 est defintif et informatif : il signale un filtre que
                # Faker refuse. On le leve, il ne se rejoue pas.
                raise ErreurService(
                    self.NOM, "GET", url, reponse.status_code, reponse.text[:300], request_id
                )
            await asyncio.sleep(2 ** (tentative - 1))
        return None

    # ------------------------------------------------------------------
    # Parsing — defensif de bout en bout
    # ------------------------------------------------------------------

    def _parser_client(self, brut: Any, seed: int) -> ClientFaker | None:
        """Traduit le JSON brut. Tout est optionnel sauf ce qui identifie.

        Le contrat ne declare que trois schemas (`FakerPayloadRequest`,
        `HTTPValidationError`, `ValidationError`) : le payload client est du JSON
        dynamique non type. On ne suppose donc AUCUN champ present, hormis
        `client_id`, `country_code` et `currency` — sans eux le client n'est pas
        exploitable et il est ecarte.
        """
        if not isinstance(brut, dict):
            return None
        client_id = _texte(brut.get("client_id"))
        pays = _texte(brut.get("country_code"))
        devise = _texte(brut.get("currency"))
        if not (client_id and pays and devise):
            return None

        identite = None
        bloc = brut.get("identity")
        if isinstance(bloc, dict):
            identite = IdentiteFaker(
                type_piece=_texte(bloc.get("ID_TYPE")),
                numero=_texte(bloc.get("ID_NUMBER")),
                emission=_date_fr(bloc.get("ID_ISSUE_DATE")),
                expiration=_date_fr(bloc.get("ID_EXPIRY_DATE")),
            )

        company = None
        bloc_cmp = brut.get("company")
        if isinstance(bloc_cmp, dict):
            secteurs = tuple(
                libelle
                for assignation in bloc_cmp.get("sector_assignments") or []
                if isinstance(assignation, dict)
                and (libelle := _texte(assignation.get("sector_label")))
            )
            company = CompanyFaker(
                identifiant=_texte(bloc_cmp.get("company_id")),
                nom_placeholder=_texte(bloc_cmp.get("company_name")),
                type_juridique=_texte(bloc_cmp.get("company_type")),
                secteurs=secteurs,
            )

        qw = brut.get("quick_win")
        return ClientFaker(
            client_id=client_id,
            pays=pays,
            devise=devise,
            categorie=_texte(brut.get("customer_category")) or CategorieClient.INDIVIDUAL,
            msisdn=_texte(brut.get("sim_number")),
            prenom=_texte(brut.get("first_name")),
            nom=_texte(brut.get("last_name")),
            nom_complet=_texte(brut.get("full_name")),
            genre=_texte(brut.get("gender")),
            identite=identite,
            company=company,
            quick_win=dict(qw) if isinstance(qw, dict) else {},
            seed=seed,
        )
