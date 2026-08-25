"""
app/routes/admin_attributions.py
================================
La face ADMINISTRATION du mecanisme d'attribution USSD — lecture seule.

Nee du recensement des baux orphelins (25/08, suite au defaut de sequence
FZ-DIAG-BAIL-2026-001) : aucune route ne listait les baux, l'exploitation
etait aveugle sur ce que la route publique attribuait. Cette liste est la
matiere premiere du futur tableau de bord d'attribution — elle en partage
le cadre d'acces (interface du Loader, roles du Loader, decision QA 25/08).

LECTURE SEULE : liberer un bail reste le geste de l'APPAREIL (DELETE public,
EF-17) ou de l'echeance — jamais un clic d'administration silencieux. Si un
jour l'administration doit liberer, ce sera une route dediee et journalisee.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.repositories.attribution_baux import AttributionBauxRepository, _en_datetime
from app.routes.dependances import SessionAdmin, admin_complet

router = APIRouter(prefix="/admin/attributions", tags=["admin — attributions"])


@router.get("")
async def lister_baux_actifs(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les baux ACTIFS, les plus recents d'abord — le recensement.

    La cle d'idempotence est exposee : deux baux aux cles distinctes viennent
    de deux TENTATIVES distinctes — c'est elle qui separe un rejeu legitime
    d'une re-attribution orpheline."""
    documents = await AttributionBauxRepository().lister_actifs()
    baux = [
        {
            "msisdn": str(d["_id"]),
            "attribution_id": str(d["attribution_id"]),
            "profil": d.get("profil"),
            "attribue_le": _en_datetime(d["attribue_le"]).isoformat(),
            "expire_le": _en_datetime(d["expire_le"]).isoformat(),
            "cle_idempotence": d.get("cle_idempotence"),
        }
        for d in documents
    ]
    return {
        "baux": baux,
        "actifs": len(baux),
        "note": (
            "baux actifs du simulateur USSD, les plus récents d'abord — "
            "lecture seule ; la libération reste le geste de l'appareil "
            "(DELETE public) ou de l'échéance"
        ),
    }
