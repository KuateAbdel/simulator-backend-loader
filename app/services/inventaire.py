"""
app/services/inventaire.py
==========================
La RECONCILIATION ici <-> la-bas — la famille 5 des scenarios d'erreur
(validee par Yaniv le 13/08 soir).

Un objet vu sur la plateforme se juge sur DEUX axes : est-il dans NOS
registres ? porte-t-il NOTRE marqueur ? Le croisement donne exactement
quatre statuts — pas un de plus :

    a_nous               dans nos registres ET present la-bas
    disparu_la_bas       dans nos registres, ABSENT la-bas — quelqu'un l'a
                         supprime cote FinZuu ; on le SIGNALE, on ne le
                         recree jamais en douce
    marque_mais_inconnu  marque DEMO_ la-bas mais absent de nos registres —
                         un autre outil ou un vieux run l'a pose ; constate
    etranger             la-bas, ni enregistre ni marque — VISIBLE, etiquete,
                         JAMAIS touche

LES REGISTRES, par service (le cote « chez nous » de la reconciliation) :

    groupes    le JOURNAL (audit_trail, entity_type="Group") — decision
               Yaniv 13/08 : AUCUN prefixe sur les groupes, jamais ; les
               noms des roles sont fonctionnels (`Super-Admin`, `Admin`...).
               La reconnaissance est donc PAR IDENTIFIANT du registre,
               creations write-ahead moins suppressions journalisees.
    produits   le journal (entity_type="Product") + le registre interne
               `produits_admin` ; le marqueur vit dans `short_name` (CR-07,
               decision CAT-1/2).
    companies  `lenders_registry` (toute company creee par nous y porte au
               moins un role de Lender) ; marqueur dans `short_name`.

Ce module ne fait AUCUNE ecriture : il lit nos collections, recoit les
documents releves sur la plateforme, et rend le classement. Les clients HTTP
restent dans les routes — la reconciliation se teste sans reseau.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_OID, UUID, uuid5

from app.core.cdc import PREFIXE_DONNEES
from app.core.database import (
    COLLECTION_AUDIT_TRAIL,
    COLLECTION_LENDERS_REGISTRY,
    COLLECTION_LOADER_CONFIGURATION,
    get_collection,
)


def uuid_stable(brut: str) -> UUID:
    """L'identifiant serveur n'est PAS garanti au format UUID — aucun contrat
    ne le promet, et `_sceller` a deja du le gerer pour les clients. Un id
    illisible ne doit jamais perdre le lien : uuid5 du meme id brut rend
    toujours le meme UUID (QA 14/08 — la purge perdait sa trace de journal
    sur un id non-UUID, l'exception etant avalee par la defense du journal)."""
    try:
        return UUID(str(brut))
    except ValueError:
        return uuid5(NAMESPACE_OID, f"finzuu-id:{brut}")


STATUT_A_NOUS = "a_nous"
STATUT_DISPARU = "disparu_la_bas"
STATUT_MARQUE_INCONNU = "marque_mais_inconnu"
STATUT_ETRANGER = "etranger"


def _normaliser_id(document: dict[str, Any]) -> str:
    return str(document.get("_id") or document.get("id") or "")


async def _registre_journal(entity_type: str, cle_id: str) -> tuple[dict[str, str], set[str]]:
    """(crees id -> nom, supprimes ids) relus du journal pour un type d'entite.

    Le journal porte trois formes d'entrees, toutes traitees :
      - INTENTION/RESULTAT en write-ahead : le RESULTAT `SUCCES` porte
        l'identifiant serveur (`group_id`/`product_id`), l'INTENTION jointe
        par `intention_id` porte l'operation et le nom du payload ;
      - `DELETE` a plat (style purge, `journaliser`) : `entity_id` suffit ;
      - `CREATE` a plat (style organisation) : `entity_id` + `after.name`.
    """
    intentions: dict[str, dict[str, Any]] = {}
    faits: list[dict[str, Any]] = []
    curseur = get_collection(COLLECTION_AUDIT_TRAIL).find({"entity_type": entity_type})
    async for document in curseur:
        if document.get("action") == "INTENTION":
            intentions[_normaliser_id(document)] = dict(document.get("after") or {})
        else:
            faits.append(document)

    crees: dict[str, str] = {}
    supprimes: set[str] = set()
    for document in faits:
        action = str(document.get("action"))
        apres = dict(document.get("after") or {})
        if action == "DELETE":
            supprimes.add(str(document.get("entity_id", "")))
        elif action == "CREATE":
            crees[str(document.get("entity_id", ""))] = str(apres.get("name", ""))
        elif action == "RESULTAT" and apres.get("statut") == "SUCCES":
            reference = str((document.get("before") or {}).get("intention_id"))
            intention = intentions.get(reference, {})
            if str(intention.get("operation", "")) == "DELETE":
                supprimes.add(str(document.get("entity_id", "")))
                continue
            identifiant = str(apres.get(cle_id) or "")
            if identifiant:
                nom = str(
                    (intention.get("payload") or {}).get("name")
                    or apres.get("name")
                    or ""
                )
                crees[identifiant] = nom
    return crees, supprimes


async def registre_groupes() -> dict[str, str]:
    """Les groupes A NOUS encore vivants : crees par nous, jamais supprimes
    par nous. C'est LA source de reconnaissance — pas de prefixe, jamais."""
    crees, supprimes = await _registre_journal("Group", "group_id")
    return {gid: nom for gid, nom in crees.items() if gid not in supprimes}


async def classer_groupes(plateforme: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconciliation des groupes — SANS marqueur, le registre seul fait foi.
    Trois statuts possibles (marque_mais_inconnu n'existe pas ici)."""
    registre = await registre_groupes()
    presents: set[str] = set()
    a_nous: list[dict[str, Any]] = []
    etrangers: list[dict[str, Any]] = []
    for groupe in plateforme:
        gid = _normaliser_id(groupe)
        presents.add(gid)
        fiche = {"id": gid, "nom": str(groupe.get("name", ""))}
        if gid in registre:
            a_nous.append({**fiche, "statut": STATUT_A_NOUS})
        else:
            etrangers.append({**fiche, "statut": STATUT_ETRANGER})
    disparus = [
        {"id": gid, "nom": registre[gid], "statut": STATUT_DISPARU}
        for gid in sorted(set(registre) - presents)
    ]
    return _bilan(a_nous=a_nous, etrangers=etrangers, disparus=disparus, inconnus=[])


async def registre_produits() -> dict[str, str]:
    """Produits crees par nous : le journal (catalogue des runs + creations
    admin) ET le registre interne `produits_admin` — l'union, jamais l'un
    sans l'autre."""
    crees, supprimes = await _registre_journal("Product", "product_id")
    document = await get_collection(COLLECTION_LOADER_CONFIGURATION).find_one(
        {"_id": "produits_admin"}
    )
    for entree in (document or {}).get("produits", []):
        identifiant = str(entree.get("product_id") or "")
        if identifiant:
            crees.setdefault(identifiant, str(entree.get("name", "")))
    # product-service n'a AUCUN DELETE (mesure) : `supprimes` devrait etre
    # vide a jamais ; on l'honore quand meme — le code ne presume pas.
    return {pid: nom for pid, nom in crees.items() if pid not in supprimes}


async def classer_produits(plateforme: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconciliation des produits — registre PAR IDENTIFIANT, marqueur dans
    `short_name` (CR-07). Les quatre statuts sont possibles ici."""
    registre = await registre_produits()
    return await _classer_par_marqueur(
        plateforme, registre, champ_marqueur="short_name"
    )


async def registre_companies() -> set[str]:
    """Les company_id A NOUS : toute company creee par le Loader porte au
    moins un role dans `lenders_registry` (EF-12) — y compris celles creees
    a l'unite par l'admin (US-D1 rejoue la sequence S3-03)."""
    curseur = get_collection(COLLECTION_LENDERS_REGISTRY).find({}, {"company_id": 1})
    return {str(document.get("company_id")) async for document in curseur}


async def classer_companies(plateforme: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconciliation des companies — registre `lenders_registry`, marqueur
    dans `short_name`. Un disparu ici est GRAVE : company-service n'a aucun
    DELETE, une company du registre absente la-bas ne devrait pas exister."""
    registre = {cid: "" for cid in await registre_companies()}
    return await _classer_par_marqueur(
        plateforme, registre, champ_marqueur="short_name"
    )


async def _classer_par_marqueur(
    plateforme: list[dict[str, Any]],
    registre: dict[str, str],
    *,
    champ_marqueur: str,
) -> dict[str, Any]:
    presents: set[str] = set()
    a_nous: list[dict[str, Any]] = []
    etrangers: list[dict[str, Any]] = []
    inconnus: list[dict[str, Any]] = []
    for objet in plateforme:
        identifiant = _normaliser_id(objet)
        presents.add(identifiant)
        marque = str(objet.get(champ_marqueur) or "")
        fiche = {
            "id": identifiant,
            "nom": str(objet.get("name", "")),
            champ_marqueur: marque,
        }
        if identifiant in registre:
            a_nous.append({**fiche, "statut": STATUT_A_NOUS})
        elif marque.startswith(PREFIXE_DONNEES):
            inconnus.append({**fiche, "statut": STATUT_MARQUE_INCONNU})
        else:
            etrangers.append({**fiche, "statut": STATUT_ETRANGER})
    disparus = [
        {"id": identifiant, "nom": registre[identifiant], "statut": STATUT_DISPARU}
        for identifiant in sorted(set(registre) - presents)
    ]
    return _bilan(a_nous=a_nous, etrangers=etrangers, disparus=disparus, inconnus=inconnus)


def _bilan(
    *,
    a_nous: list[dict[str, Any]],
    etrangers: list[dict[str, Any]],
    disparus: list[dict[str, Any]],
    inconnus: list[dict[str, Any]],
) -> dict[str, Any]:
    """La forme unique rendue a l'ecran — les quatre colonnes TOUJOURS
    presentes (vides s'il le faut) : une anomalie absente de la reponse
    serait une anomalie cachee."""
    return {
        STATUT_A_NOUS: a_nous,
        STATUT_DISPARU: disparus,
        STATUT_MARQUE_INCONNU: inconnus,
        STATUT_ETRANGER: etrangers,
        "comptes": {
            STATUT_A_NOUS: len(a_nous),
            STATUT_DISPARU: len(disparus),
            STATUT_MARQUE_INCONNU: len(inconnus),
            STATUT_ETRANGER: len(etrangers),
        },
        "anomalies": len(disparus) + len(inconnus),
    }
