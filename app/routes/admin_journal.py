"""
app/routes/admin_journal.py
===========================
Le JOURNAL d'administration du Loader — « qui a fait quoi, quand » (chantier
audit, demande JJB). Reserve au Super-Admin : voir l'activite d'administration
est une capacite sensible (elle revele les emails et les gestes des autres).

Source : la collection `audit_trail`, journal write-ahead d'intention. Les
actions d'administration (gestion des comptes/roles, creations d'entites hors
run) sont inscrites sous le run SENTINELLE RUN_ADMIN (UUID int=0). On en rend
les dernieres INTENTIONS, les plus recentes d'abord ; la pagination fine se
fait cote UI, comme les autres listes du Loader.

LECTURE SEULE : ce module n'ecrit rien. Il expose ce que les autres ont deja
inscrit — le journal ne se rejoue ni ne se falsifie depuis l'API.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.repositories.attribution_baux import LIBELLE_ORIGINE, ORIGINE_APPAREIL
from app.repositories.audit_trail import AuditTrailRepository
from app.routes.dependances import SessionAdmin, exige_super_admin

router = APIRouter(prefix="/admin/journal", tags=["admin — journal"])

#: Cles de payload qui portent l'AUTEUR d'un geste (selon l'action d'origine).
_CLES_ACTEUR = ("par", "cree_par", "modifie_par")


def _vue(entree: Any, resultat: dict[str, Any] | None) -> dict[str, Any]:
    """La vue publique d'une entree — le « qui/quoi/quand » ET SON ISSUE.

    21/08 : les deux creations refusees du pays GN s'affichaient comme des
    CREATE ordinaires. Une intention sans son issue est une demi-verite —
    l'ecran doit dire si le geste a abouti, et pourquoi sinon."""
    apres = entree.after or {}
    payload = apres.get("payload") or {}
    acteur = next((payload[c] for c in _CLES_ACTEUR if payload.get(c)), None)
    details = {k: v for k, v in payload.items() if k not in _CLES_ACTEUR}
    #: L'ORIGINE du geste, telle qu'elle a ete INSCRITE (27/08). Elle vit dans
    #: le payload pour les gestes d'administration, a la racine d'`after` pour
    #: les traces de la route publique.
    origine = payload.get("origine") or apres.get("origine")
    if entree.entity_type in {"AttributionBail", "AttributionRefus"}:
        # Traces de la route PUBLIQUE d'attribution (élucidation 25/08) :
        # l'acteur est l'application — il n'y a pas d'opérateur derrière —
        # et la cible est le msisdn du bail. Les entrées d'avant ce jour
        # portent le msisdn à la racine de `after`, pas dans un payload.
        #
        # 27/08 — L'ACTEUR SUIT L'ORIGINE ECRITE. Tant qu'un seul chemin
        # existait, « pas d'auteur dans la trace » valait « c'est l'app » ;
        # depuis que l'administration peut revoquer, cette deduction serait un
        # pari. Le repli ne sert donc plus qu'aux traces ANTERIEURES, pour
        # lesquelles il reste vrai : l'administration ne pouvait pas agir.
        acteur = acteur or LIBELLE_ORIGINE.get(
            origine or ORIGINE_APPAREIL, LIBELLE_ORIGINE[ORIGINE_APPAREIL]
        )
        details = details or {
            k: v for k, v in apres.items() if k not in {"operation", "cible"}
        }
    if resultat is None:
        issue, motif = "en_cours", None
    else:
        issue = str(resultat.get("statut", ""))
        motif = resultat.get("motif")
    return {
        "quand": entree.timestamp.isoformat()
        if hasattr(entree.timestamp, "isoformat")
        else str(entree.timestamp),
        "operation": apres.get("operation", entree.action),
        "entite": entree.entity_type,
        "cible": apres.get("cible") or apres.get("msisdn") or "",
        "acteur": acteur,
        #: `appareil` | `administration` | None (geste sans origine — tout ce
        #: qui n'est pas un bail, et les traces d'avant le 27/08).
        "origine": origine,
        #: L'adresse d'ou venait le geste, et son pays — ecrits a la trace
        #: (28/08). None sur les traces anterieures : on n'invente jamais.
        "ip": payload.get("ip") or apres.get("ip"),
        "ip_pays": payload.get("ip_pays") or apres.get("ip_pays"),
        "issue": issue,
        "motif": motif,
        "details": details,
    }


@router.get("")
async def lister_journal(
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """Les dernieres actions d'administration, les plus recentes d'abord."""
    entrees = await AuditTrailRepository().lister_admin(limite)
    return {
        "entrees": [_vue(entree, resultat) for entree, resultat in entrees],
        "total": len(entrees),
        "note": (
            "actions d'administration (gestion des comptes, rôles, entités hors "
            "run) — les plus récentes d'abord, avec l'issue de chaque geste, "
            "lecture seule"
        ),
    }
