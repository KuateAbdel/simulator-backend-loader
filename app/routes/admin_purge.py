"""
app/routes/admin_purge.py
=========================
Lot E — la PURGE (`US-F1`/`US-F2`, `EF-59`/`EF-65`).

CE QUE « PURGEABLE » VEUT DIRE — et la carte est MESURÉE, service par
service (les disciplines D-*) :

  user-service (groupes)   DELETE existe        -> PURGEABLE, le seul
  product-service          deactivate seulement -> semi : jamais effaçable
  client-service           AUCUNE mutation sauf PATCH langue (mesure)
  identity / account       AUCUN DELETE — la piece KYC et les comptes sont
                           definitifs, les mouvements aussi
  depositary-service       AUCUN DELETE (D-DEP-3), et la desactivation
                           n'arrete NI collectes NI retraits (D-DEP-8) —
                           cosmetique, pas une purge
  company-service          AUCUN DELETE (les PROBE_ du 12/08 en temoignent)
  config-service           PARTAGE — on n'y purge jamais (A-08)

La purge honnete fait donc DEUX choses, et les dit toutes les deux :
  1. elle SUPPRIME ce qui est reversible (NOS groupes, reconnus par le registre) ;
  2. elle LISTE les residus marques — jamais caches, avec le verdict et le
     fait mesure qui l'explique.

Le rite en deux temps, comme partout : preparer (l'inventaire, aucune
ecriture) puis confirmer (les suppressions, journalisees sous RUN_ADMIN).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.database import (
    COLLECTION_AUDIT_TRAIL,
    COLLECTION_AUTH_THROTTLE,
    COLLECTION_FAKER_CONSUMPTION_LEDGER,
    COLLECTION_LENDERS_REGISTRY,
    COLLECTION_LOADER_CONFIGURATION,
    COLLECTION_LOADER_RUNS,
    COLLECTION_NOTIFICATIONS,
    COLLECTION_ORG_HIERARCHY,
    COLLECTION_SUPER_ADMIN_ACCOUNTS,
    COLLECTION_VERROUS,
    COLLECTION_VERSIONS_SERVICES,
    get_collection,
)
from app.repositories.audit_trail import AuditTrailRepository
from app.routes.admin_entites import RUN_ADMIN
from app.routes.dependances import (
    SessionAdmin,
    exige_super_admin,
    refuser_si_run_en_cours,
)
from app.services.inventaire import STATUT_A_NOUS, classer_groupes, uuid_stable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/purge", tags=["admin — purge"])

#: La carte des residus, avec leur verdict MESURE. C'est la reponse a
#: « purgeable, ca veut dire quoi ? » — gravee dans le code.
VERDICTS_RESIDUS: dict[str, str] = {
    "companies": "AUCUN DELETE (company-service) — permanentes, au registre",
    "depositaires": (
        "AUCUN DELETE (D-DEP-3), desactivation cosmetique — n'arrete ni "
        "collectes ni retraits (D-DEP-8, FRA-203/204)"
    ),
    "clients": "AUCUNE mutation sauf PATCH langue (mesure) — permanents",
    "identites": "AUCUN DELETE — la piece KYC est definitive",
    "comptes": "AUCUN DELETE, aucun contre-mouvement — soldes definitifs",
    "produits": "AUCUN DELETE, deactivate seulement — jamais effaçables",
}


def _client_users() -> Any:
    """Fabrique du client user-service — doublee dans les tests."""
    from app.clients.user_service import UserServiceClient

    return UserServiceClient()


async def _groupes_a_nous(client: Any) -> list[dict[str, Any]]:
    """NOS groupes, reconnus PAR LE REGISTRE — jamais par prefixe.

    Les groupes ne portent AUCUN marqueur (decision Yaniv 13/08 : les noms de
    roles sont fonctionnels — `Super-Admin`, `Admin`...). La premiere version
    de cette fonction filtrait sur `DEMO_` : elle n'aurait JAMAIS rien trouve,
    et la purge aurait ete un mensonge silencieux. La reconnaissance est celle
    de la reconciliation : creations journalisees moins suppressions."""
    classement = await classer_groupes(await client.lister_groupes())
    # `V-04` — la DATE voyage jusqu'a l'ecran de purge. C'est la premiere
    # question qu'on se pose avant de supprimer : « ca date de quand ? ». Un
    # residu de la semaine derniere ne se traite pas comme une entite du run
    # d'aujourd'hui, et on ne supprime pas a l'aveugle sur un ecosysteme ou
    # trois services n'ont AUCUN DELETE.
    return [
        {"id": g["id"], "nom": g["nom"], "cree_le": g.get("cree_le")}
        for g in classement[STATUT_A_NOUS]
    ]


async def _residus_marques() -> dict[str, Any]:
    """L'inventaire des permanents, depuis NOS collections — le registre des
    Lenders, l'arbre (kiosques = depositaires), le ledger Faker (clients
    confirmes = identites + comptes en cascade), le registre produits admin."""
    lenders = await get_collection("lenders_registry").count_documents({})
    kiosques = await get_collection("org_hierarchy").count_documents(
        {"niveau": "KIOSQUE"}
    )
    clients = await get_collection("faker_consumption_ledger").count_documents(
        {"state": "CONSOMME"}
    )
    document = await get_collection("loader_configuration").find_one(
        {"_id": "produits_admin"}
    )
    produits_admin = len((document or {}).get("produits", []))
    return {
        "companies": {"compte": lenders, "verdict": VERDICTS_RESIDUS["companies"]},
        "depositaires": {"compte": kiosques, "verdict": VERDICTS_RESIDUS["depositaires"]},
        "clients": {"compte": clients, "verdict": VERDICTS_RESIDUS["clients"]},
        "identites": {"compte": clients, "verdict": VERDICTS_RESIDUS["identites"]},
        "comptes": {
            "compte": clients,
            "verdict": VERDICTS_RESIDUS["comptes"],
            "note": "1 CHECKING par client au minimum ; 6 par depositaire souscrit",
        },
        "produits_crees_par_admin": {
            "compte": produits_admin,
            "verdict": VERDICTS_RESIDUS["produits"],
        },
    }


#: `US-F3` — LES DEUX CAMPS DE NOTRE BASE, DECLARES UNE FOIS POUR TOUTES.
#:
#: La purge v1 ne visait que FinZuu. Or aucun de leurs services n'expose de
#: `DELETE` en dehors des groupes : attendre qu'ils en ouvrent un, c'est
#: attendre indefiniment. Pendant ce temps, NOTRE base garde la carte
#: d'entites qui n'ont plus rien a voir avec l'etat courant — et l'Observatoire
#: la sert.
#:
#: Ce qu'il faut donc pouvoir vider, c'est NOTRE CARTE. Jamais le referentiel :
#: les pays, regions, villes, quartiers, devises et telcos sont le travail de
#: l'operateur, pas un sous-produit d'execution.
#:
#: Les deux listes sont EXHAUSTIVES et se contredisent : toute collection de
#: `app/core/database.py` figure dans l'une ou dans l'autre. Un test le
#: verifie — une collection ajoutee demain sans decision explicite fait echouer
#: la suite plutot que d'etre effacee par defaut.
COLLECTIONS_NOTRE_CARTE: dict[str, str] = {
    COLLECTION_ORG_HIERARCHY: (
        "l'arbre : branches, agences, kiosques, agents, clients, liens produit"
    ),
    COLLECTION_LOADER_RUNS: "les executions, leurs rapports et leurs mesures",
    COLLECTION_AUDIT_TRAIL: "le journal d'intentions",
    COLLECTION_FAKER_CONSUMPTION_LEDGER: "le registre des identites Faker",
    COLLECTION_LENDERS_REGISTRY: "le role Lender porte par une Company",
}

COLLECTIONS_PROTEGEES: dict[str, str] = {
    COLLECTION_LOADER_CONFIGURATION: (
        "LA SURCOUCHE REFERENTIELLE — pays, regions, villes, quartiers, devises, "
        "telcos, catalogue. Le travail de l'operateur, jamais un sous-produit."
    ),
    COLLECTION_SUPER_ADMIN_ACCOUNTS: "les comptes d'acces au Loader",
    COLLECTION_NOTIFICATIONS: "l'historique d'information — rien ne s'y supprime",
    COLLECTION_AUTH_THROTTLE: "l'anti-brute-force du login (I-AUTH-11)",
    COLLECTION_VERSIONS_SERVICES: "le releve de version des services (V-01)",
    COLLECTION_VERROUS: "les verrous de concurrence (C2)",
}


async def _notre_base() -> dict[str, Any]:
    """`US-F3` — l'inventaire de NOTRE base, les deux camps cote a cote.

    Le compte protege est rendu AUSSI, et c'est le point : l'operateur doit
    voir de ses yeux que ses 48 pays ne sont pas dans la colonne effacable.
    Une garantie qu'on ne peut pas verifier a l'ecran n'est pas une garantie.
    """
    effacable = {
        nom: {"compte": await get_collection(nom).count_documents({}), "contenu": quoi}
        for nom, quoi in COLLECTIONS_NOTRE_CARTE.items()
    }
    protege = {
        nom: {"compte": await get_collection(nom).count_documents({}), "contenu": quoi}
        for nom, quoi in COLLECTIONS_PROTEGEES.items()
    }
    return {
        "effacable": effacable,
        "total_effacable": sum(c["compte"] for c in effacable.values()),
        "protege": protege,
        "regle": (
            "vider NOTRE CARTE n'efface RIEN chez FinZuu et ne touche AUCUNE "
            "collection protegee — le referentiel, les comptes et les "
            "notifications survivent integralement"
        ),
    }


@router.post("/preparer")
async def preparer(
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """`US-F1` — l'inventaire, AUCUNE ecriture.

    Deux colonnes, toutes deux chiffrees : le purgeable (NOS groupes,
    reconnus par le registre) et les residus marques (nos collections), chacun avec le
    verdict mesure qui l'explique. Rien n'est cache — c'est la condition pour
    decider en connaissance de cause.
    """
    # `US-F3` — LA PLATEFORME MUETTE N'EMPORTE PLUS TOUT L'ECRAN.
    #
    # Cet inventaire echouait ENTIEREMENT en HTTP 500 des que user-service
    # etait injoignable. L'operateur perdait alors aussi la vue de NOTRE base
    # — qui ne depend d'aucun service distant. Mesure du 24/08 sur le banc
    # local : `HTTP 500 /admin/inventaire/groupes`, et l'ecran Purge entier
    # vide, section « notre carte » comprise.
    #
    # Un ecran qui cesse de montrer NOS donnees parce qu'une machine DISTANTE
    # ne repond pas est un ecran mal concu. On sert donc ce qu'on sait, et on
    # DIT ce qu'on n'a pas pu lire — jamais un zero qui se ferait passer pour
    # une mesure.
    groupes: list[dict[str, Any]] = []
    lecture_groupes: str | None = None
    client = _client_users()
    try:
        groupes = await _groupes_a_nous(client)
    except Exception as erreur:
        lecture_groupes = (
            f"user-service injoignable ({type(erreur).__name__}) — le compte des "
            "groupes purgeables est INCONNU, pas nul"
        )
        logger.warning("inventaire des groupes indisponible : %s", erreur)
    finally:
        await client.fermer()

    return {
        "purgeable": {
            "groupes": groupes,
            "lecture": lecture_groupes,
            "regle": "DELETE /groupes/{id} existe — le seul module reversible",
        },
        "residus_marques": await _residus_marques(),
        "notre_base": await _notre_base(),
        "note": (
            "confirmer via POST /admin/purge/confirmer. Chez FinZuu, seuls les "
            "groupes sont supprimables ; les residus restent, marques. Vider "
            "NOTRE CARTE (`vider_notre_base`) est une action separee, qui "
            "n'efface rien chez FinZuu et epargne le referentiel."
        ),
    }


class ConfirmationPurge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: L'unique action reversible COTE FINZUU — explicite, jamais implicite.
    supprimer_groupes: bool

    #: `US-F3` — vider NOTRE CARTE (arbre, runs, journal, registres). N'efface
    #: RIEN chez FinZuu, et ne touche AUCUNE collection protegee. Par defaut
    #: `False` : ce geste se demande, il ne s'obtient jamais par omission.
    vider_notre_base: bool = False


@router.post("/confirmer")
async def confirmer(
    demande: ConfirmationPurge,
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """`US-F2` — l'execution : seuls NOS groupes (registre) sont supprimes, chaque
    suppression journalisee sous RUN_ADMIN. Le rapport final redit les
    residus — la purge ne les fait pas disparaitre du compte-rendu."""
    await refuser_si_run_en_cours()

    supprimes: list[str] = []
    echecs: list[dict[str, str]] = []
    if demande.supprimer_groupes:
        audit = AuditTrailRepository()
        client = _client_users()
        try:
            for groupe in await _groupes_a_nous(client):
                try:
                    await client.supprimer_groupe(groupe["id"])
                except Exception as erreur:
                    echecs.append({"groupe": groupe["nom"], "motif": type(erreur).__name__})
                    continue
                supprimes.append(groupe["nom"])
                try:
                    await audit.journaliser(
                        run_id=RUN_ADMIN,
                        entity_type="Group",
                        entity_id=uuid_stable(groupe["id"]),
                        action="DELETE",
                        before={"name": groupe["nom"]},
                    )
                except Exception:  # pragma: no cover — defense d'exploitation
                    logger.exception("journal DELETE %s non ecrit", groupe["nom"])
        finally:
            await client.fermer()

    notre_base: dict[str, Any] | None = None
    if demande.vider_notre_base:
        notre_base = await _vider_notre_carte()

    return {
        "supprimes": supprimes,
        "echecs": echecs,
        "residus_marques": await _residus_marques(),
        "notre_base_videe": notre_base,
        "note": "les residus restent sur la plateforme, marques — dit, jamais cache",
    }


async def _vider_notre_carte() -> dict[str, Any]:
    """`US-F3` — vide NOTRE CARTE, et rien d'autre.

    LA GARDE EST STRUCTURELLE, PAS DECLARATIVE. On n'efface que les
    collections nommees dans `COLLECTIONS_NOTRE_CARTE`, et on VERIFIE avant
    chaque suppression que la cible n'est pas dans `COLLECTIONS_PROTEGEES`.
    Cette verification est redondante avec la boucle — c'est voulu : le jour ou
    quelqu'un ajoute une collection dans la mauvaise liste, elle refuse au lieu
    d'effacer. Un referentiel de six semaines ne se protege pas par un
    commentaire.

    ORDRE DES OPERATIONS. Le journal d'audit fait PARTIE de ce qu'on efface. On
    journalise donc APRES, jamais avant : la premiere entree du journal neuf
    est la purge elle-meme. Sans cela, la trace du geste disparaitrait avec le
    geste — et une purge sans trace est exactement ce qu'un audit reproche.
    """
    videes: dict[str, int] = {}
    for nom in COLLECTIONS_NOTRE_CARTE:
        if nom in COLLECTIONS_PROTEGEES:  # pragma: no cover — garde structurelle
            raise HTTPException(
                status_code=500,
                detail=(
                    f"collection '{nom}' declaree a la fois effacable et protegee — "
                    "purge refusee, la contradiction doit etre tranchee dans le code"
                ),
            )
        resultat = await get_collection(nom).delete_many({})
        videes[nom] = int(resultat.deleted_count)

    epargnees = {
        nom: await get_collection(nom).count_documents({}) for nom in COLLECTIONS_PROTEGEES
    }

    # Le journal renait avec, pour premiere ligne, le geste qui l'a vide.
    try:
        await AuditTrailRepository().journaliser(
            run_id=RUN_ADMIN,
            entity_type="LoaderCarte",
            entity_id=uuid_stable("purge-notre-base"),
            action="DELETE",
            before={"videes": videes},
            after={"epargnees": epargnees},
        )
    except Exception:  # pragma: no cover — defense d'exploitation
        logger.exception("journal DELETE de la purge de notre carte non ecrit")

    return {
        "videes": videes,
        "total": sum(videes.values()),
        "epargnees": epargnees,
        "note": (
            "aucune entite n'a ete supprimee chez FinZuu — elles y restent, et "
            "un prochain run les reconnaitra par GET-avant-POST sans creer de "
            "doublon. Le referentiel est intact."
        ),
    }
