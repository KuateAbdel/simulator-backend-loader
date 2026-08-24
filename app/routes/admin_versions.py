"""
app/routes/admin_versions.py
============================
`V-01` — l'onglet « Versions » de l'administration.

CE QUE CET ECRAN REPOND, ET QU'AUCUN AUTRE NE REPONDAIT
-------------------------------------------------------
Le tableau de bord dit si un service est VIVANT. Il ne dit rien de ce qu'il
PORTE. Or nos neuf clients sont ecrits contre des contrats **mesures** (les
audits de `docs/empirical/`, releves les 8, 9 et 10 aout) : le jour ou un
service change, nos appels parlent a un contrat qui n'existe plus.

DEUX CHANGEMENTS, DEUX GRAVITES
-------------------------------
  version qui monte              le contrat a change, et le service le DIT
  chemins qui bougent a version  le contrat a change et le service ne le dit
  identique                      PAS — le pire des deux, invisible sans ce
                                 releve

POURQUOI PAS DE TACHE DE FOND
-----------------------------
Un minuteur toutes les trois heures redemarre a zero a chaque redemarrage du
conteneur, et se duplique avec le nombre de workers. Ici, la FRAICHEUR EST
UNE DONNEE : le relevé porte sa date, l'ecran l'affiche, et une lecture sur
un cache perime declenche le relevé. Rien a surveiller, et la fraicheur est
PROUVEE au lieu d'etre supposee.

Le verrou `C2` couvre le cas de deux lectures simultanees sur un cache
perime : une seule sonde les dix services, l'autre recoit le cache. Sans lui,
ouvrir l'ecran a deux taperait vingt fois sur la plateforme pour rien.

CE QUE L'ECRAN MONTRE, ET CE QU'IL CACHE
----------------------------------------
Il montre : le service, sa version, ses chemins, et UNE PHRASE qui dit s'il
faut agir. Il cache : le TTL, l'age du cache en secondes, le verrou, les
codes HTTP, la latence — de la plomberie, et la latence a deja son ecran.

**C'est ce module qui calcule le verdict et la gravite**, jamais le frontend :
deux ecrans qui refont la comparaison chacun de leur cote finissent par ne
plus dire la meme chose.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends

from app.repositories.versions_services import VersionsServicesRepository
from app.routes.admin_dashboard import SERVICES_SONDES
from app.routes.dependances import SessionAdmin, admin_complet, exige_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/versions", tags=["admin — versions"])

#: Trois heures, la cadence demandee. La lecture qui trouve le cache plus
#: vieux que ca le rafraichit ; les autres sont servies telles quelles.
FRAICHEUR_SECONDES = 3 * 3600

#: Court : `openapi.json` est un document statique. Un service qui met plus de
#: cinq secondes a le rendre est un service dont on ne veut pas attendre la
#: reponse pour afficher les neuf autres.
DELAI_SONDE = 5.0

#: L'ordre d'affichage : ce qui demande une action d'abord. Jamais l'ordre
#: alphabetique — il noie le changement au milieu du stable.
#:
#: `injoignable` N'EST PAS une gravite de cet ecran (correction Yaniv, 23/08) :
#: l'etat vivant/mort est deja dit par le tableau de bord, en vert et rouge et
#: EN DIRECT. Le repeter ici serait une duplication, et une version ne
#: disparait pas parce qu'un service redemarre — on garde la derniere connue,
#: seule sa date vieillit.
GRAVITES = {"changement": 0, "anomalie": 1, "stable": 2, "jamais_lu": 3}



#: `V-06` — LA DATE D'EXPOSITION, ET POURQUOI ELLE VIENT DE LA.
#:
#: Le boss veut savoir DEPUIS QUAND chaque service est deploye sur l'instance
#: de test. La plateforme ne le publie nulle part : mesure du 24/08 sur les
#: 12 services — `/health` rend `{"status":"ok"}` et rien d'autre, `/info`,
#: `/version`, `/actuator/info` et `/metrics` rendent tous 404, et le seul
#: en-tete non trivial est `server: APISIX/3.13.0`, la passerelle.
#:
#: Le certificat TLS courant ne repond pas non plus a la question : Let's
#: Encrypt renouvelle tous les ~60 jours, et les dates lues (juillet-aout)
#: sont des RENOUVELLEMENTS — Yaniv l'a confirme, ces services tournent
#: depuis deux mois et plus.
#:
#: Les JOURNAUX DE TRANSPARENCE DES CERTIFICATS, eux, gardent TOUTES les
#: emissions jamais faites pour un domaine. La PREMIERE donne le jour ou
#: l'hote est apparu publiquement — c'est-a-dire sa mise en service. Mesure
#: du 24/08 : client-service et config-service au 27/05, ussd-service au
#: 05/07, notification-service au 21/08. Cette liste a d'ailleurs REVELE deux
#: services que le Loader ignorait.
#:
#: CE QUE CETTE DATE N'EST PAS : la date du dernier deploiement de code. Un
#: service redeploye aujourd'hui garde sa date de mai. La colonne porte donc
#: « expose depuis le », jamais « deploye le » — et le changement de version
#: (`V-01`) reste ce qui dit qu'un service a BOUGE.
SOURCE_TRANSPARENCE = "https://api.certspotter.com/v1/issuances"
DOMAINE_PLATEFORME = "test.services.fintech4esg.com"

#: La premiere emission d'un certificat est IMMUABLE : une fois relevee, elle
#: ne changera jamais. On la relit une fois par jour, pas toutes les trois
#: heures — et seulement pour capter un service NOUVEAU.
FRAICHEUR_EXPOSITION_SECONDES = 24 * 3600


async def _dates_exposition() -> dict[str, str | None]:
    """La date de premiere exposition de chaque hote, par les journaux CT.

    **Ne rend JAMAIS une date approchee.** Source muette ou hote absent des
    journaux : la valeur est `None`, et l'ecran affiche « non relevé ». Une
    date inventee sur cet ecran serait pire que pas de date du tout — c'est
    exactement ce qu'on a refuse de faire avec le certificat courant.
    """
    parametres = {
        "domain": DOMAINE_PLATEFORME,
        "include_subdomains": "true",
        "expand": "dns_names",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            reponse = await client.get(SOURCE_TRANSPARENCE, params=parametres)
            reponse.raise_for_status()
            emissions = reponse.json()
    except Exception as erreur:
        logger.warning("journaux de transparence indisponibles : %s", erreur)
        return {}

    if not isinstance(emissions, list):
        return {}

    premieres: dict[str, str] = {}
    for emission in emissions:
        jour = str(emission.get("not_before", ""))[:10]
        if not jour:
            continue
        for hote in emission.get("dns_names") or []:
            nom = str(hote)
            if nom.startswith("*."):
                continue
            if nom not in premieres or jour < premieres[nom]:
                premieres[nom] = jour
    return dict(premieres)


def _hote_du_service(nom: str, base: str) -> str:
    """L'hote d'un service, tel qu'il apparait dans les journaux CT."""
    return str(base).split("://")[-1].split("/")[0].split(":")[0]


async def _relever_un(client: httpx.AsyncClient, nom: str, base: str) -> dict[str, Any]:
    """Le relevé d'un service — jamais d'exception : un service muet est une
    DONNEE de l'ecran, pas une panne de l'ecran.

    `openapi.json` est public sur ces services (`/health`, `/docs`,
    `/openapi.json` en 200 sans jeton, mesure du 08/08).
    """
    try:
        reponse = await client.get(f"{base}/openapi.json")
        reponse.raise_for_status()
        document = reponse.json()
    except Exception:
        return {"joignable": False, "titre": None, "version": None,
                "chemins": None, "operations": None}

    chemins = document.get("paths") or {}
    operations = sum(
        1
        for methodes in chemins.values()
        if isinstance(methodes, dict)
        for cle in methodes
        if cle.lower() in {"get", "post", "put", "patch", "delete"}
    )
    info = document.get("info") or {}
    return {
        "joignable": True,
        "titre": str(info.get("title") or "").strip() or None,
        "version": str(info.get("version") or "").strip() or None,
        "chemins": len(chemins),
        "operations": operations,
    }


def _verdict(nom: str, courant: dict[str, Any], precedent: dict[str, Any]) -> dict[str, str]:
    """La phrase et la gravite — calculees ici, pas dans l'ecran."""
    if not courant.get("version"):
        # Jamais lu avec succes : on ne sait pas, et on le dit. On n'ecrit
        # PAS « injoignable » — l'etat vivant/mort est l'affaire du tableau
        # de bord, pas celle de cet ecran.
        return {"gravite": "jamais_lu", "commentaire": "version jamais lue"}

    if precedent:
        avant_v, apres_v = precedent.get("version"), courant["version"]
        if avant_v and apres_v and avant_v != apres_v:
            return {
                "gravite": "changement",
                "commentaire": (
                    f"version {avant_v} → {apres_v} — nos appels sont ecrits "
                    f"contre {avant_v}, le contrat est a re-mesurer"
                ),
            }
        avant_c, apres_c = precedent.get("chemins"), courant["chemins"]
        if avant_c is not None and apres_c is not None and avant_c != apres_c:
            return {
                "gravite": "changement",
                "commentaire": (
                    f"{avant_c} → {apres_c} chemins SANS montee de version — "
                    "le contrat a change et le service ne le dit pas"
                ),
            }
        avant_o, apres_o = precedent.get("operations"), courant["operations"]
        if avant_o is not None and apres_o is not None and avant_o != apres_o:
            return {
                "gravite": "changement",
                "commentaire": (
                    f"{avant_o} → {apres_o} operations a chemins constants — "
                    "une methode a ete ajoutee ou retiree"
                ),
            }

    # Le titre est compare au NOM du service : `user-service` et
    # `identity-service` se declarent tous les deux « Auth Service » (mesure
    # du 10/08). Deux services differents sous le meme nom.
    titre = (courant.get("titre") or "").lower().replace("-", " ").replace("service", "").strip()
    attendu = nom.lower().replace("-", " ").replace("service", "").strip()
    if titre and attendu and titre != attendu:
        return {
            "gravite": "anomalie",
            "commentaire": f"se declare « {courant['titre']} » — titre incoherent",
        }

    return {"gravite": "stable", "commentaire": "inchange"}


async def _relever_tout() -> None:
    """Sonde les dix services EN PARALLELE et range les relevés."""
    depot = VersionsServicesRepository()
    async with httpx.AsyncClient(timeout=DELAI_SONDE) as client:
        releves = await asyncio.gather(
            *(_relever_un(client, nom, base) for nom, base in SERVICES_SONDES)
        )
    for (nom, _base), releve in zip(SERVICES_SONDES, releves, strict=True):
        await depot.enregistrer(nom, releve)


async def _completer_exposition(depot: VersionsServicesRepository) -> dict[str, str]:
    """`V-06` — les dates d'exposition, en interrogeant la source LE MOINS
    POSSIBLE.

    La date est immuable (voir `SOURCE_TRANSPARENCE`). On lit donc d'abord ce
    qu'on a deja grave, et on n'appelle les journaux CT que s'il MANQUE au
    moins un service — c'est-a-dire a la toute premiere lecture, puis
    uniquement quand un service nouveau apparait dans `SERVICES_SONDES`.

    Faker est hors du domaine de la plateforme : son absence des journaux
    n'est pas un trou, c'est normal, et sa date reste `None`.
    """
    connues = await depot.exposition_connue()
    manquants = [nom for nom, _ in SERVICES_SONDES if nom not in connues]
    if not manquants:
        return connues

    premieres = await _dates_exposition()
    if not premieres:
        return connues

    for nom, base in SERVICES_SONDES:
        if nom in connues:
            continue
        jour = premieres.get(_hote_du_service(nom, base))
        if jour:
            await depot.graver_exposition(nom, jour)
            connues[nom] = jour
    return connues


async def _servir(depot: VersionsServicesRepository) -> dict[str, Any]:
    documents = await depot.dernier_releve()
    exposition = await _completer_exposition(depot)
    lignes: list[dict[str, Any]] = []
    for nom, _base in SERVICES_SONDES:
        doc = documents.get(nom)
        if doc is None:
            lignes.append(
                {
                    "service": nom,
                    "version": None,
                    "titre": None,
                    "chemins": None,
                    "operations": None,
                    "gravite": "jamais_lu",
                    "commentaire": "version jamais lue",
                    "releve_le": None,
                    "stable_depuis": None,
                    "expose_depuis": exposition.get(nom),
                }
            )
            continue

        historique = doc.get("historique") or []
        precedent = historique[-2] if len(historique) >= 2 else {}
        verdict = _verdict(nom, doc, precedent)
        lignes.append(
            {
                "service": nom,
                "version": doc.get("version"),
                "titre": doc.get("titre"),
                "chemins": doc.get("chemins"),
                "operations": doc.get("operations"),
                **verdict,
                "releve_le": _horodatage(doc.get("releve_le")),
                "stable_depuis": _horodatage(doc.get("vu_stable_depuis")),
                # `V-06` — le jour ou l'hote est apparu publiquement. `None`
                # quand les journaux ne le portent pas : « non relevé », jamais
                # une date approchee.
                "expose_depuis": exposition.get(nom),
            }
        )

    lignes.sort(key=lambda ligne: (GRAVITES.get(str(ligne["gravite"]), 9), ligne["service"]))
    age = await depot.age_du_cache()
    return {
        "services": lignes,
        "compte": len(lignes),
        "a_surveiller": sum(1 for ligne in lignes if ligne["gravite"] != "stable"),
        "releve_il_y_a_secondes": None if age is None else int(age),
        "note": (
            "un service peut etre VIVANT et porter un contrat different de "
            "celui contre lequel nos clients sont ecrits — c'est ce que cet "
            "ecran surveille, le tableau de bord surveille l'autre moitie"
        ),
    }


def _horodatage(valeur: Any) -> str | None:
    if not isinstance(valeur, datetime):
        return None
    if valeur.tzinfo is None:
        valeur = valeur.replace(tzinfo=UTC)
    return str(valeur.isoformat())


@router.get("")
async def versions(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`V-01` — les versions des dix services, triees par ce qui demande une
    action.

    Le cache est rafraichi par CETTE lecture s'il a plus de trois heures. La
    fraicheur voyage avec la reponse (`releve_il_y_a_secondes`) : l'ecran
    affiche « relevé il y a 12 min » et personne n'a besoin de savoir
    pourquoi c'est frais.
    """
    from app.routes.admin_referentiels import _verrou

    depot = VersionsServicesRepository()
    age = await depot.age_du_cache()
    if age is None or age > FRAICHEUR_SECONDES:
        # Deux lectures simultanees sur un cache perime sonderaient vingt fois
        # pour rien. La seconde sert le cache — l'ecran le dit par sa date.
        with contextlib.suppress(Exception):
            async with _verrou("versions:relever", "cache"):
                await _relever_tout()
    return await _servir(depot)


@router.post("/relever")
async def relever(
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """Le bouton « relever maintenant » — quand on veut la preuve devant
    quelqu'un plutot que la promesse d'un cache."""
    from app.routes.admin_referentiels import _verrou

    async with _verrou("versions:relever", session.email):
        await _relever_tout()
    return await _servir(VersionsServicesRepository())
