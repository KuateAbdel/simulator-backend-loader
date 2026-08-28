"""
app/routes/attribution_publique.py
==================================
Les QUATRE routes publiques du mecanisme d'attribution USSD — et rien
d'autre. Contrat : `FZ-CONTRAT-ATTRIB-2026-001 v0.3.1`
(docs/CONTRAT_ATTRIBUTION_USSD.md), FIGE. Cette implementation ne le
reinterprete pas : toute divergence remonte au contrat avant d'etre codee.

  GET    /api/v1/attribution/criteres              listes fermees + `libres`
  POST   /api/v1/attribution/attributions          tirage atomique, idempotent
  GET    /api/v1/attribution/attributions/{id}     verification du bail (EF-15, EF-22)
  DELETE /api/v1/attribution/attributions/{id}     liberation (EF-17)

OUVERTES, sans authentification — `ENF-07` l'exige, tranche a la validation
du contrat (§6). Aucune de ces routes ne cree, modifie ou supprime un client,
un pays ou une ecriture de la carte : elles ne touchent QUE `attribution_baux`
et le journal. L'attribution CONSOMME le peuplement, elle n'y participe pas.

LA PROPRIETE STRUCTURELLE DU 409 (contrat §5) : `STOCK_EPUISE` est un
RESULTAT CALCULE — l'ensemble « candidats moins baux actifs » est vide —
JAMAIS une exception attrapee. Aucun `except` de ce module ne produit un 409 ;
un defaut serveur traverse et rend 500. Un bug ne peut donc pas se deguiser
en stock epuise, ni l'inverse — et le test le prouve en provoquant le defaut.
"""

from __future__ import annotations

import logging
from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.core.geoip import pays_de_l_ip
from app.models.enums import NiveauOrganisation
from app.repositories.attribution_baux import (
    ORIGINE_APPAREIL,
    RUN_ADMIN_ATTRIBUTION,
    AttributionBauxRepository,
    normaliser_bail,
)
from app.repositories.attribution_reglages import jours_pour_le_tirage
from app.repositories.audit_trail import AuditTrailRepository
from app.repositories.org_hierarchy import OrgHierarchyRepository
from app.repositories.surcouche import SurcoucheRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/attribution", tags=["attribution USSD — public"])

#: Les referentiels FERMES du profil (`EF-02`, `EF-03`) — valeurs de la
#: plateforme, libelles bilingues embarques COTE SERVEUR : le serveur rend ce
#: qu'il detient, l'application choisit le libelle, elle n'en produit aucun
#: (`INV-SIM-07`).
GENRES: tuple[dict[str, str], ...] = (
    {"code": "MALE", "libelle_fr": "Homme", "libelle_en": "Male"},
    {"code": "FEMALE", "libelle_fr": "Femme", "libelle_en": "Female"},
)
CATEGORIES: tuple[dict[str, str], ...] = (
    {"code": "INDIVIDUAL", "libelle_fr": "Particulier", "libelle_en": "Individual"},
    {"code": "CORPORATE", "libelle_fr": "Entreprise", "libelle_en": "Business"},
)


def _erreur(
    statut: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    """Le corps d'erreur UNIFORME du contrat §5. `code` est la seule valeur
    sur laquelle l'application branche ; `message` et `details` vont au
    journal de l'ecran 8, jamais devant le partenaire."""
    return JSONResponse(
        status_code=statut,
        content={"code": code, "message": message, "details": details or {}},
    )


def _msisdn_du_noeud(nom: str) -> str:
    """Le msisdn vit dans `name` (« Client 226… ») — meme lecture que le
    tableau de bord (`admin_dashboard`), jamais une seconde convention."""
    return nom.removeprefix("Client ").strip()


async def _pool() -> dict[tuple[str, str, str], set[str]]:
    """La POPULATION attribuable : les noeuds CLIENT de la carte, groupes par
    (pays, genre, categorie) → ensembles de msisdn.

    Perimetre CUMULATIF (`P-06`) : tous les runs — un client existe, peu
    importe quelle execution l'a bati. Deduplique par msisdn : deux runs
    peuvent porter le meme client (`D-CLI-11`), ce n'est qu'UN attribuable.

    LECTURE SEULE, et c'est un engagement de la validation : le mecanisme
    n'ecrit JAMAIS dans la population du Loader.
    """
    arbre = OrgHierarchyRepository()
    pool: dict[tuple[str, str, str], set[str]] = {}
    for noeud in await arbre.par_niveau(None, NiveauOrganisation.CLIENT):
        if not (noeud.gender and noeud.categorie and noeud.country_code):
            continue  # noeud d'avant P-04 : profil inconnu, pas attribuable
        cle = (noeud.country_code.upper(), noeud.gender.upper(), noeud.categorie.upper())
        pool.setdefault(cle, set()).add(_msisdn_du_noeud(noeud.name))
    return pool


async def _pays_du_referentiel() -> dict[str, dict[str, str]]:
    """Les fiches pays de la SURCOUCHE — noms bilingues que le Loader detient
    deja (`nom_fr`, `nom_en`). Aucun libelle n'est invente ici."""
    from app.routes.admin_referentiels import _geo

    surcouche, _meta = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())
    return {
        code: {
            "code": code,
            "libelle_fr": fiche.nom_fr or code,
            "libelle_en": fiche.nom_en or fiche.nom_fr or code,
        }
        for code, fiche in referentiel.pays_index.items()
    }


# ──────────────────────────────────────────────────────────────────────────
# 1. GET /criteres — contrat §1
# ──────────────────────────────────────────────────────────────────────────


@router.get("/criteres")
async def criteres() -> dict[str, Any]:
    """Les trois listes fermees (`EF-01` a `EF-03`) et la disponibilite REELLE.

    `disponibilite` est EXHAUSTIVE sur les combinaisons du perimetre peuple :
    une combinaison a zero APPARAIT avec `libres: 0`, jamais masquee —
    l'application la grise, elle ne la cache pas (tranche a la validation,
    contrat §8). C'est une PHOTOGRAPHIE, jamais une reservation : la seule
    verite est le tirage.
    """
    pool = await _pool()
    fiches = await _pays_du_referentiel()
    baux = AttributionBauxRepository()
    occupes = await baux.actifs_par_profil()

    pays_du_pool = sorted({cle[0] for cle in pool})
    disponibilite = []
    for pays in pays_du_pool:
        for genre in ("MALE", "FEMALE"):
            for categorie in ("INDIVIDUAL", "CORPORATE"):
                cle = (pays, genre, categorie)
                total = len(pool.get(cle, set()))
                libres = max(0, total - occupes.get(cle, 0))
                disponibilite.append(
                    {"pays": pays, "genre": genre, "categorie": categorie, "libres": libres}
                )

    from datetime import UTC, datetime

    return {
        "pays": [
            fiches.get(p, {"code": p, "libelle_fr": p, "libelle_en": p})
            for p in pays_du_pool
        ],
        "genres": list(GENRES),
        "categories": list(CATEGORIES),
        "disponibilite": disponibilite,
        "releve_le": datetime.now(UTC).isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────
# 2. POST /attributions — contrat §2
# ──────────────────────────────────────────────────────────────────────────


class DemandeAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pays: str
    genre: str
    categorie: str
    #: Contrat 0.4 — marque + modele, OPTIONNEL. Pas une cle, pas un
    #: identifiant : une etiquette de lecture pour l'exploitation. Le serveur
    #: la normalise (strip, 64 caracteres max) plutot que de refuser — un
    #: champ de confort ne doit jamais faire echouer une attribution.
    appareil: str | None = None


@router.post("/attributions", status_code=201)
async def attribuer(
    demande: DemandeAttribution,
    requete: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    """Le tirage atomique — `EF-04`, `INV-SIM-01`, `CR-05`, `CR-06`."""
    # Cle d'idempotence OBLIGATOIRE (contrat §2) — sans elle, une reponse
    # perdue laisse un client marque que personne ne detient.
    if not idempotency_key or not idempotency_key.strip():
        return _erreur(
            400,
            "CLE_IDEMPOTENCE_REQUISE",
            "l'en-tete Idempotency-Key est obligatoire — contrat §2",
        )
    cle = idempotency_key.strip()

    baux = AttributionBauxRepository()

    # 1. REJEU ? Une cle deja vue rejoue le 201 d'origine, sans tirage.
    existant = await baux.par_cle_idempotence(cle)
    if existant is not None:
        return JSONResponse(status_code=201, content=normaliser_bail(existant))

    # 2. Criteres valides ? Hors referentiel -> 422, defaut APPLICATIF.
    pays = demande.pays.strip().upper()
    genre = demande.genre.strip().upper()
    categorie = demande.categorie.strip().upper()
    fiches = await _pays_du_referentiel()
    invalide = None
    if genre not in {g["code"] for g in GENRES}:
        invalide = f"genre '{demande.genre}' hors referentiel"
    elif categorie not in {c["code"] for c in CATEGORIES}:
        invalide = f"categorie '{demande.categorie}' hors referentiel"
    elif pays not in fiches:
        invalide = f"pays '{demande.pays}' hors referentiel"
    if invalide is not None:
        return _erreur(422, "CRITERE_INVALIDE", invalide)

    profil = {"pays": pays, "genre": genre, "categorie": categorie}
    appareil = (demande.appareil or "").strip()[:64] or None

    # 3-4. Candidats moins baux actifs. LE 409 EST UN RESULTAT CALCULE :
    # ensemble vide -> stock epuise. Aucune exception ne mene ici.
    pool = await _pool()
    candidats = pool.get((pays, genre, categorie), set())
    if candidats:
        occupes = await baux.actifs_parmi(sorted(candidats))
        libres = sorted(candidats - occupes)
    else:
        libres = []
    if not libres:
        await _journaliser_refus(profil, "STOCK_EPUISE", _ip_du_client(requete))
        return _erreur(
            409,
            "STOCK_EPUISE",
            f"Aucun client libre pour le profil {pays} / {genre} / {categorie}",
            {"pays": pays, "genre": genre, "categorie": categorie, "libres": 0},
        )

    # 5. Ordre de tirage : aleatoire en pratique, reproductible exactement —
    # seme par la cle d'idempotence (§6 de la conception, motif ENF-15). Deux
    # appareils ont deux cles, donc deux ordres : ils ne convergent presque
    # jamais sur le meme candidat.
    ordre = sorted(libres, key=lambda m: sha256(f"{cle}:{m}".encode()).hexdigest())

    # 6. La DUREE applicable, resolue MAINTENANT (contrat 0.4 §b) : surcharge
    # du pays si elle existe, sinon la valeur globale. Lue a chaque demande et
    # jamais mise en cache — un reglage change vaut des l'attribution
    # suivante, sans redemarrage du service.
    #
    # FAIL-SAFE : cet appel ne leve jamais. Un reglage illisible rend sept
    # jours et le tirage continue — on ne coupe pas le service pour proteger
    # un detail de confort (meme doctrine que le champ `appareil`, §0.4a).
    jours = await jours_pour_le_tirage(pays)

    # 7. Acquisition atomique, candidat par candidat. La concurrence ne
    # produit jamais un double — au pire un detour vers le suivant.
    for msisdn in ordre:
        bail = await baux.acquerir(
            msisdn, cle_idempotence=cle, profil=profil, appareil=appareil, jours=jours
        )
        if bail is not None:
            await _journaliser("CREATE", bail, _ip_du_client(requete))
            return JSONResponse(status_code=201, content=normaliser_bail(bail))

    # 8. Tous les candidats pris pendant la boucle (concurrence extreme sur un
    # pool presque vide) : au moment du dernier essai, rien n'etait libre.
    await _journaliser_refus(profil, "STOCK_EPUISE", _ip_du_client(requete))
    return _erreur(
        409,
        "STOCK_EPUISE",
        f"Aucun client libre pour le profil {pays} / {genre} / {categorie}",
        {"pays": pays, "genre": genre, "categorie": categorie, "libres": 0},
    )


# ──────────────────────────────────────────────────────────────────────────
# 3. GET /attributions/{id} — contrat §3 (v0.3), EF-15 / EF-22
# ──────────────────────────────────────────────────────────────────────────


@router.get("/attributions/{attribution_id}")
async def verifier(attribution_id: str) -> Any:
    """La verification du bail — ce qui rend l'autorite serveur EXERCABLE.

    Un bail echu rend 404, pas un 200 decore d'un drapeau : `expire_le < now`
    EST l'etat libre (§5 de la conception), il n'y a pas d'etat intermediaire
    a exposer. D'ou que vienne la perte (expiration, liberation,
    reinitialisation), la conduite de l'application est identique — ecran 13,
    phase 1.
    """
    from datetime import UTC, datetime

    baux = AttributionBauxRepository()
    document = await baux.par_attribution_id(attribution_id)
    if document is None:
        return _erreur(404, "BAIL_INCONNU", "bail inconnu ou echu")
    expire = document["expire_le"]
    if not isinstance(expire, datetime):
        expire = datetime.fromisoformat(str(expire))
    if expire.tzinfo is None:
        expire = expire.replace(tzinfo=UTC)
    if expire <= datetime.now(UTC):
        return _erreur(404, "BAIL_INCONNU", "bail inconnu ou echu")
    return normaliser_bail(document)


# ──────────────────────────────────────────────────────────────────────────
# 4. DELETE /attributions/{id} — contrat §4, EF-17
# ──────────────────────────────────────────────────────────────────────────


@router.delete("/attributions/{attribution_id}", status_code=204)
async def liberer(attribution_id: str, requete: Request) -> Response:
    """La rupture de liaison — rend le client au pool COTE SERVEUR. Sans
    cela, chaque test de la recette fuirait un numero pour sept jours et
    `INV-SIM-01` s'eroderait (contrat §4).

    404 = succes fonctionnel : le bail n'existe plus, le but est atteint.
    """
    baux = AttributionBauxRepository()
    document = await baux.liberer(attribution_id)
    if document is None:
        return _erreur(404, "BAIL_INCONNU", "bail inconnu ou deja echu")
    await _journaliser("DELETE", document, _ip_du_client(requete))
    return Response(status_code=204)


# ──────────────────────────────────────────────────────────────────────────


def _ip_du_client(requete: Request) -> str | None:
    """L'adresse d'ou vient CE geste — demande Direction du 28/08.

    MEME DISCIPLINE que `_ip_client` de l'auth (I-AUTH-11) : l'en-tete
    `X-Forwarded-For` n'est cru QUE si `faire_confiance_proxy` est pose —
    sans cette confiance explicite, n'importe quel appelant le forgerait et
    s'inventerait un pays. C'est une INDICATION D'EXPLOITATION, pas une
    preuve d'identite, et jamais un identifiant d'appareil (contrat 0.4a :
    l'IP decrit une connexion, pas UN terminal). Elle n'est ecrite QUE dans
    le journal, reserve aux roles du Loader — aucune route publique ne la
    rend."""
    from app.core.config import settings

    if settings.faire_confiance_proxy:
        transmis = requete.headers.get("x-forwarded-for", "")
        premier = transmis.split(",")[0].strip()
        if premier:
            return premier
    client = requete.client
    return client.host if client else None


async def _journaliser_refus(
    profil: dict[str, str], code: str, ip: str | None = None
) -> None:
    """La trace d'un REFUS (409) — spec §12.5 et conception §8.1 : « si le
    pool se vide, on saura par qui et quand ». Un refus repete sur un profil
    signale une tension AVANT que la combinaison ne tombe a zero — sans
    cette trace, l'epuisement se decouvre au moment ou il prive un
    partenaire.

    TRACE PURE : la reponse 409 etait deja calculee, elle part identique a
    l'octet pres — le mecanisme ne change pas. Et comme toute trace d'ici,
    elle ne fait jamais echouer le geste qu'elle documente.
    """
    try:
        from uuid import uuid4 as _uuid4

        await AuditTrailRepository().journaliser(
            run_id=RUN_ADMIN_ATTRIBUTION,
            entity_type="AttributionRefus",
            entity_id=_uuid4(),
            action="REFUS",
            after={
                "cible": f"{profil['pays']}/{profil['genre']}/{profil['categorie']}",
                "code": code,
                "profil": dict(profil),
                "origine": ORIGINE_APPAREIL,
                "ip": ip,
                "ip_pays": pays_de_l_ip(ip),
            },
        )
    except Exception:  # pragma: no cover — defense d'exploitation
        logger.exception("trace de refus non ecrite (%s)", code)


async def _journaliser(
    action: str, bail: dict[str, Any], ip: str | None = None
) -> None:
    """Chaque attribution et chaque liberation laisse une trace (`§8.1` de la
    conception) : si le pool se vide, on saura par qui et quand. La trace ne
    doit jamais faire echouer le geste qu'elle documente."""
    try:
        from uuid import UUID as _UUID

        await AuditTrailRepository().journaliser(
            run_id=RUN_ADMIN_ATTRIBUTION,
            entity_type="AttributionBail",
            entity_id=_UUID(str(bail["attribution_id"])),
            action=action,
            after={
                "msisdn": str(bail["_id"]),
                "profil": bail.get("profil"),
                "expire_le": str(bail.get("expire_le")),
                # L'ORIGINE, ECRITE et non deduite (27/08). Une liberation
                # `EF-17` et une revocation d'administration effacent le meme
                # bail ; seule cette ligne dit LEQUEL des deux s'est produit.
                "origine": ORIGINE_APPAREIL,
                # L'ADRESSE et son pays (28/08) — resolus A L'ECRITURE : la
                # trace garde le pays du moment du geste, elle ne se
                # reinterprete pas.
                "ip": ip,
                "ip_pays": pays_de_l_ip(ip),
            },
        )
    except Exception:  # pragma: no cover — defense d'exploitation
        logger.exception("trace d'attribution non ecrite (%s)", action)
