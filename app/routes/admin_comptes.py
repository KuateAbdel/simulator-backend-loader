"""
app/routes/admin_comptes.py
===========================
Gestion des comptes Super-Admin du LOADER — RBAC (decision Yaniv 15/08).

« Super-Admin » est un ROLE, pas une personne : PLUSIEURS comptes le portent,
chacun avec son email REEL (le code de reinitialisation US-A4 part vers
l'email du compte — une boite qui n'existe pas rend le reset impossible),
son propre mot de passe (change librement, sans toucher les autres) et son
propre cycle « premiere connexion -> mot de passe durable » (US-A2).

DOCTRINE :
  - le mot de passe INITIAL est genere (24 caracteres URL-safe), affiche UNE
    FOIS dans la reponse au createur ET envoye par email au nouveau compte
    quand Mailjet le permet — le createur reste le canal de secours, l'envoi
    d'email n'est jamais une condition de reussite (compte Mailjet bloque
    mj-0001, mesure du 15/08) ;
  - un compte ne se SUPPRIME pas, il se DESACTIVE : le journal reste
    attribuable a son auteur. Un compte desactive recoit le MEME 401
    generique que des identifiants faux — rien a enumerer ;
  - gardes anti-lock-out : on ne se desactive pas soi-meme, et le dernier
    compte actif est indesactivable ;
  - chaque geste s'inscrit au journal d'intention sous RUN_ADMIN.
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_OID, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.clients import mailjet
from app.repositories.audit_trail import AuditTrailRepository
from app.repositories.super_admin import SuperAdminRepository
from app.routes.dependances import SessionAdmin, exige_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/comptes", tags=["admin — comptes"])

#: Le run SENTINELLE des actions d'administration hors-run (cf. admin_entites).
RUN_ADMIN = UUID(int=0)


class CompteDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: L'email REEL de la personne — c'est la que partira tout code US-A4.
    email: EmailStr
    #: Role RBAC du Loader. Defaut FAIL-CLOSED = viewer (lecture seule) : on
    #: n'accorde jamais un privilege par omission.
    role: Literal["viewer", "admin", "super_admin"] = "viewer"


class RoleDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["viewer", "admin", "super_admin"]


class EtatDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actif: bool
    motif: str = Field(min_length=3, max_length=200)


def _fiche(compte: Any) -> dict[str, Any]:
    """La vue publique d'un compte — JAMAIS un hash, jamais un code."""
    return {
        "email": compte.email,
        "role": compte.role,
        "actif": compte.actif,
        "must_change_password": compte.must_change_password,
        "cree_par": compte.cree_par,
        "cree_le": compte.cree_le,
    }


@router.get("")
async def lister_comptes(
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """Tous les comptes du role Super-Admin — leur vue publique seulement."""
    comptes = await SuperAdminRepository().lister()
    return {
        "comptes": [_fiche(c) for c in comptes],
        "compte": len(comptes),
        "note": (
            "Super-Admin est un ROLE : chaque personne a SON compte, son "
            "email reel et son mot de passe. Un compte se desactive, jamais "
            "ne se supprime — le journal reste attribuable."
        ),
    }


@router.post("", status_code=201)
async def creer_compte(
    demande: CompteDemande,
    session: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """Cree un compte Super-Admin pour une PERSONNE (email reel).

    Le mot de passe initial est GENERE, montre une fois ici, envoye par
    email si Mailjet le permet ; le changement est EXIGE a la premiere
    connexion (US-A2). 409 si l'email porte deja un compte.
    """
    depot = SuperAdminRepository()
    email = str(demande.email).strip().lower()
    if await depot.par_email(email) is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"un compte existe deja pour {email!r} — le reactiver ou "
                "reinitialiser son mot de passe, jamais le doubler"
            ),
        )

    initial = secrets.token_urlsafe(18)  # 24 caracteres, usage unique
    audit = AuditTrailRepository()
    async with audit.intention(
        RUN_ADMIN,
        entity_type="SuperAdminAccount",
        entity_id=uuid5(NAMESPACE_OID, f"loader-compte:{email}"),
        operation="CREATE",
        cible="loader super_admin_accounts",
        payload={"email": email, "role": demande.role, "cree_par": session.email},
    ) as suivi:
        compte = await depot.creer(email, initial, cree_par=session.email, role=demande.role)
        suivi.reussi({"email": compte.email})

    email_envoye = await mailjet.envoyer_email(
        email,
        "FinZuu Loader — votre compte Super-Admin",
        (
            f"Un compte Super-Admin du Loader FinZuu a ete cree pour vous "
            f"par {session.email}.\n\n"
            f"Adresse de connexion : https://simul.fintech4esg.com\n"
            f"Email : {email}\n"
            f"Mot de passe initial (a usage unique) : {initial}\n\n"
            "Le changement de mot de passe vous sera exige a la premiere "
            "connexion. Ce mot de passe initial n'est valable qu'une fois "
            "change, il ne sera plus jamais affiche."
        ),
    )
    if not email_envoye:
        logger.warning("invitation email non partie pour %s — canal createur", email)
    return {
        "compte": _fiche(compte),
        #: Affiche UNE FOIS — ni persiste en clair, ni rejoue par aucune API.
        "mot_de_passe_initial": initial,
        "email_envoye": email_envoye,
        "note": (
            "mot de passe initial a transmettre a la personne s'il n'est pas "
            "parti par email — le changement sera exige a sa premiere "
            "connexion (US-A2)"
        ),
    }


@router.put("/{email}/etat")
async def changer_etat_compte(
    email: str,
    demande: EtatDemande,
    session: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """Active ou desactive un compte — les gardes anti-lock-out d'abord.

    On ne se desactive pas soi-meme (409), et le DERNIER compte actif est
    indesactivable (409) : le Loader ne peut jamais se retrouver sans
    personne a la barre.
    """
    depot = SuperAdminRepository()
    cible = email.strip().lower()
    compte = await depot.par_email(cible)
    if compte is None:
        raise HTTPException(status_code=404, detail=f"aucun compte pour {cible!r}")

    if not demande.actif:
        if cible == session.email:
            raise HTTPException(
                status_code=409,
                detail="se desactiver soi-meme est refuse — demander a un autre admin",
            )
        est_super = compte.role not in ("admin", "viewer")
        if compte.actif and est_super and await depot.compter_super_admins_actifs() <= 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "dernier Super-Admin actif — indesactivable : le Loader ne "
                    "reste jamais sans Super-Admin a la barre"
                ),
            )

    audit = AuditTrailRepository()
    async with audit.intention(
        RUN_ADMIN,
        entity_type="SuperAdminAccount",
        entity_id=uuid5(NAMESPACE_OID, f"loader-compte:{cible}"),
        operation="UPDATE",
        cible="loader super_admin_accounts",
        payload={"email": cible, "actif": demande.actif, "motif": demande.motif},
    ) as suivi:
        await depot.changer_etat(cible, demande.actif)
        suivi.reussi({"email": cible, "actif": demande.actif})

    relu = await depot.par_email(cible)
    return {
        "compte": _fiche(relu),
        "note": "desactive = 401 generique au login, jamais supprime"
        if not demande.actif
        else "compte reactive — son mot de passe n'a pas change",
    }


@router.put("/{email}/role")
async def changer_role_compte(
    email: str,
    demande: RoleDemande,
    session: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """Change le role RBAC d'un compte du Loader — Super-Admin uniquement.

    Anti-lock-out : retrograder le DERNIER Super-Admin actif est refuse. Le
    nouveau role s'applique au PROCHAIN jeton du compte : sa session en cours
    garde son role jusqu'au re-login (les sessions durent 4 h)."""
    depot = SuperAdminRepository()
    cible = email.strip().lower()
    compte = await depot.par_email(cible)
    if compte is None:
        raise HTTPException(status_code=404, detail=f"aucun compte pour {cible!r}")

    est_super = compte.role not in ("admin", "viewer")
    if est_super and compte.actif and demande.role != "super_admin":
        if await depot.compter_super_admins_actifs() <= 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "retrograder le dernier Super-Admin actif est refuse — "
                    "le Loader garde toujours au moins un Super-Admin"
                ),
            )

    audit = AuditTrailRepository()
    async with audit.intention(
        RUN_ADMIN,
        entity_type="SuperAdminAccount",
        entity_id=uuid5(NAMESPACE_OID, f"loader-compte:{cible}"),
        operation="UPDATE",
        cible="loader super_admin_accounts",
        payload={"email": cible, "role": demande.role, "par": session.email},
    ) as suivi:
        await depot.changer_role(cible, demande.role)
        suivi.reussi({"email": cible, "role": demande.role})

    relu = await depot.par_email(cible)
    return {
        "compte": _fiche(relu),
        "note": (
            f"role change en {demande.role} — effectif au prochain login du "
            "compte (le jeton en cours conserve son role, sessions 4 h)"
        ),
    }
