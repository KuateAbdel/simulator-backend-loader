"""
app/routes/admin_inventaire.py
==============================
La vision de Yaniv (13/08 soir) : « voir ce qui est sur chaque service —
mais SEULEMENT nos donnees, pas tout ce qu'il y a la-bas — avec NOS statuts,
et la tracabilite de ce qui est a nous et de ce qui ne l'est pas. »

Chaque entite relue de la plateforme recoit un des QUATRE statuts de la
reconciliation (`app/services/inventaire.py`) : a_nous, disparu_la_bas,
marque_mais_inconnu, etranger. Les etrangers sont VISIBLES — savoir qu'un
homonyme existe est ce qui evite d'en recreer un — mais l'ecran n'AGIT que
sur le notre.

GROUPES : AUCUN prefixe, jamais (decision Yaniv 13/08). La reconnaissance
est par IDENTIFIANT du registre — le journal write-ahead des creations,
moins les suppressions journalisees. La seule action offerte est le DELETE
individuel d'un groupe A NOUS : 404 s'il n'existe pas, 403 s'il est
etranger, 409 sous run (EF-55), 502 si le serveur echoue OU repond sans
agir (relecture) — chaque issue nommee, rien d'anonyme.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.audit_trail import AuditTrailRepository
from app.routes.admin_entites import RUN_ADMIN
from app.routes.dependances import (
    SessionAdmin,
    admin_complet,
    refuser_si_run_en_cours,
)
from app.services.inventaire import (
    classer_companies,
    classer_depositaires,
    classer_groupes,
    classer_produits,
    registre_groupes,
    uuid_stable,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/inventaire", tags=["admin — inventaire"])


def _client_users() -> Any:
    from app.clients.user_service import UserServiceClient

    return UserServiceClient()


def _client_produits() -> Any:
    from app.clients.product_service import ProductServiceClient

    return ProductServiceClient()


def _client_companies() -> Any:
    from app.clients.company_service import CompanyServiceClient

    return CompanyServiceClient()


@router.get("/groupes")
async def groupes(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Reconciliation des groupes user-service contre notre registre.

    Trois statuts possibles (pas de marqueur sur les groupes) : a_nous,
    disparu_la_bas — un groupe de notre registre supprime cote FinZuu,
    SIGNALE jamais recree en douce — et etranger (CUSTOMER et consorts)."""
    client = _client_users()
    try:
        classement = await classer_groupes(await client.lister_groupes())
    finally:
        await client.fermer()
    classement["note"] = (
        "seuls les groupes a_nous sont supprimables — "
        "DELETE /admin/inventaire/groupes/{id}"
    )
    return classement


@router.delete("/groupes/{groupe_id}")
async def supprimer_groupe(
    groupe_id: Annotated[str, Path(min_length=1, max_length=64)],
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Suppression INDIVIDUELLE d'un de NOS groupes — la seule action.

    L'ordre des gardes est celui du risque : verrou EF-55 (409), existence
    la-bas (404), puis LA garde absolue — un groupe hors registre est
    ETRANGER, 403 quel que soit son nom. Le DELETE n'est tente qu'apres,
    journalise sous RUN_ADMIN, et la relecture PROUVE qu'il a pris.

    `groupe_id` est un `str` VOULU, pas un UUID : le contrat serveur ne
    garantit aucun format d'identifiant (QA 14/08 — en exiger un rendait un
    groupe a id non-UUID visible a l'inventaire mais INSUPPRIMABLE, 422 avant
    la route). L'autorite est le registre ; le journal derive `uuid_stable`."""
    await refuser_si_run_en_cours()

    client = _client_users()
    try:
        cible = next(
            (
                g
                for g in await client.lister_groupes()
                if str(g.get("_id") or g.get("id")) == str(groupe_id)
            ),
            None,
        )
        if cible is None:
            raise HTTPException(status_code=404, detail=f"groupe {groupe_id} inconnu")
        nom = str(cible.get("name", ""))
        if str(groupe_id) not in await registre_groupes():
            raise HTTPException(
                status_code=403,
                detail=(
                    f"le groupe {nom!r} est ETRANGER (absent de notre registre) — "
                    "le Loader ne touche jamais a ce qui n'est pas a lui"
                ),
            )

        audit = AuditTrailRepository()
        async with audit.intention(
            RUN_ADMIN,
            entity_type="Group",
            entity_id=uuid_stable(groupe_id),
            operation="DELETE",
            cible="user-service",
            payload={"name": nom},
        ) as suivi:
            try:
                await client.supprimer_groupe(groupe_id)
            except Exception as erreur:
                suivi.echoue(type(erreur).__name__)
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "user-service a refuse la suppression : "
                        f"{type(erreur).__name__}"
                    ),
                ) from erreur
            suivi.reussi({"supprime": nom, "group_id": str(groupe_id)})

        # RELECTURE — la preuve que la suppression a PRIS, jamais deduite.
        restants = [
            str(g.get("_id") or g.get("id")) for g in await client.lister_groupes()
        ]
        if str(groupe_id) in restants:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"le groupe {nom!r} est TOUJOURS present apres le DELETE — "
                    "le serveur a repondu sans agir, a verifier a la main"
                ),
            )
    finally:
        await client.fermer()
    return {"supprime": nom, "verifie_par_relecture": True}


@router.get("/produits")
async def produits(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Reconciliation des produits — registre par identifiant (journal +
    `produits_admin`), marqueur dans `short_name`. Les quatre statuts sont
    possibles ; aucun produit n'est supprimable (aucun DELETE, mesure)."""
    client = _client_produits()
    try:
        classement = await classer_produits(await client.inventaire())
    finally:
        await client.fermer()
    classement["note"] = (
        "aucun produit n'est supprimable — product-service n'a pas de DELETE ; "
        "les etrangers sont constates, jamais consommes (A-10) ni recrees"
    )
    return classement


@router.get("/companies")
async def companies(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Reconciliation des companies — registre `lenders_registry`, marqueur
    dans `short_name`. Un disparu ici est GRAVE : company-service n'a aucun
    DELETE, une company du registre absente la-bas ne devrait pas pouvoir
    exister — c'est une anomalie a investiguer, pas a corriger en douce."""
    client = _client_companies()
    try:
        classement = await classer_companies(await client.lister_companies())
    finally:
        await client.fermer()
    classement["note"] = (
        "aucune company n'est supprimable — company-service n'a pas de DELETE ; "
        "les notres restent marquees DEMO_ dans short_name"
    )
    return classement


def _client_depositaires() -> Any:
    from app.clients.depositary_service import DepositaryServiceClient

    return DepositaryServiceClient()


@router.get("/depositaires")
async def depositaires(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Reconciliation des depositaires (16/08) — registre = les depositary_id
    des Kiosques d'org_hierarchy (UC-09), marqueur DEMO_ dans `name`. AUCUN
    n'est supprimable : depositary-service n'a pas de DELETE (D-DEP-3), et la
    desactivation est cosmetique — elle n'arrete ni collectes ni retraits
    (D-DEP-8, FRA-203/204)."""
    client = _client_depositaires()
    try:
        classement = await classer_depositaires(await client.lister())
    finally:
        await client.fermer()
    classement["note"] = (
        "aucun depositaire n'est supprimable — pas de DELETE (D-DEP-3), "
        "desactivation cosmetique (D-DEP-8) ; les notres viennent des "
        "Kiosques d'org_hierarchy (UC-09)"
    )
    return classement


# ---------------------------------------------------------------------------
# ADOPTION (A-13, tranche par Yaniv le 14/08) — « c'est nous qui les avons
# crees la-bas », avant que le journal des groupes n'existe (13/08). La recon
# passive du 14/08 les a retrouves : 11 roles D-09, notre empreinte exacte,
# mais un registre vide — donc classes ETRANGERS, invisibles a la purge,
# interdits au DELETE. L'adoption les fait NOTRES : explicite, journalisée,
# JAMAIS automatique — adopter d'office ce qui nous ressemble referait le
# defaut de confiance que toute la reconciliation combat.
# ---------------------------------------------------------------------------

class DemandeAdoption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Les identifiants TELS QUE la plateforme les porte (str — aucun format
    #: garanti, QA du 14/08).
    groupe_ids: list[str] = Field(min_length=1, max_length=50)


@router.post("/groupes/adoption")
async def adopter_groupes(
    demande: DemandeAdoption,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Adopte au registre des groupes DEJA presents sur user-service.

    Chaque identifiant recoit SON issue — jamais un echec global muet :
      adopte            present la-bas, absent du registre -> inscrit
      deja_au_registre  rien a faire, dit tel quel
      introuvable       absent de la plateforme -> on n'adopte pas un fantome

    L'inscription est une intention ADOPTION journalisee sous RUN_ADMIN dont
    le RESULTAT porte le group_id : la ligne EXACTE qu'aurait ecrite la
    creation si le journal avait existe a l'epoque. Apres adoption, le groupe
    est `a_nous` partout : inventaire, DELETE individuel, purge.
    """
    await refuser_si_run_en_cours()

    client = _client_users()
    try:
        presents = {
            str(g.get("_id") or g.get("id")): str(g.get("name", ""))
            for g in await client.lister_groupes()
        }
    finally:
        await client.fermer()

    registre = await registre_groupes()
    audit = AuditTrailRepository()
    issues: list[dict[str, str]] = []
    for gid in dict.fromkeys(demande.groupe_ids):  # dedoublonne, ordre garde
        if gid in registre:
            issues.append({"id": gid, "nom": registre[gid], "issue": "deja_au_registre"})
            continue
        if gid not in presents:
            issues.append({"id": gid, "issue": "introuvable"})
            continue
        nom = presents[gid]
        async with audit.intention(
            RUN_ADMIN,
            entity_type="Group",
            entity_id=uuid_stable(gid),
            operation="ADOPTION",
            cible="registre Loader — groupe preexistant reconnu notre",
            payload={"name": nom},
        ) as suivi:
            suivi.reussi({"group_id": gid, "name": nom})
        issues.append({"id": gid, "nom": nom, "issue": "adopte"})

    # RELECTURE — le registre d'APRES, jamais deduit de la boucle.
    apres = await registre_groupes()
    return {
        "issues": issues,
        "comptes": {
            "adoptes": sum(1 for i in issues if i["issue"] == "adopte"),
            "deja_au_registre": sum(1 for i in issues if i["issue"] == "deja_au_registre"),
            "introuvables": sum(1 for i in issues if i["issue"] == "introuvable"),
        },
        "registre_apres": len(apres),
        "note": (
            "les adoptes sont desormais a_nous PARTOUT — inventaire, "
            "DELETE /admin/inventaire/groupes/{id}, purge"
        ),
    }
