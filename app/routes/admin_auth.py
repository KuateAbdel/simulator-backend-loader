"""
app/routes/admin_auth.py
========================
Session du Super-Admin du LOADER — `US-A1` a `US-A4` du backlog
(`docs/BACKLOG_SUPER_ADMIN.md`, page Confluence 67665922).

A ne JAMAIS confondre avec le Super-Admin de la plateforme FinZuu : celui-ci
vit dans NOTRE MongoDB (`super_admin_accounts`), celui-la est un groupe RBAC
de user-service (`MODELE_UTILISATEURS.md` §1).

L'EMAIL EST VALIDE, PAS UN STRING — exigence de Yaniv du 13/08, et c'est la
doctrine du projet appliquee a nous-memes : la plateforme accepte n'importe
quoi dans ses champs (`D-IDN-1`, `FRA-222`...), et le Loader valide ce que le
serveur ne valide pas. On ne va pas etre plus laxiste avec notre propre porte
d'entree que nous le sommes avec les leurs — `EmailStr` (email-validator),
normalise en minuscules, ou 422.

LE MOT DE PASSE OUBLIE (`US-A4`) n'a PAS de route HTTP en v1 — choix de
conception, documente : sans serveur d'email branche, un « lien de reset » par
API serait du theatre de securite (n'importe qui pourrait le demander, et le
lien n'aurait nulle part ou aller). La reinitialisation passe par
`scripts/reinitialiser_admin.py`, execute par l'operateur SUR le serveur —
l'acces au serveur est la preuve d'autorite, exactement le modele de GitLab
(`gitlab-rake`). Le script regenere un mot de passe initial a usage unique et
repose `must_change_password=True`. v2 : reset par email via le SendMail
voisin de l'hote (`FZ-INFRA-SIMUL-2026-001`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.core.security import emettre_jeton_admin
from app.repositories.super_admin import SuperAdminRepository
from app.routes.dependances import SessionAdmin, session_admin

router = APIRouter(prefix="/admin/auth", tags=["admin — session"])

#: Longueur minimale du mot de passe durable. 12 est le plancher NIST/ANSSI
#: pour un compte a privilege unique ; la complexite par classes de caracteres
#: n'est PAS exigee — c'est la longueur qui protege, pas les `@`.
LONGUEUR_MDP_MIN = 12


class DemandeConnexion(BaseModel):
    """`US-A1` — l'email est un EMAIL (RFC), jamais un string libre."""

    email: EmailStr
    mot_de_passe: str = Field(min_length=1)


class ReponseSession(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — le TYPE du jeton OAuth2, pas un secret
    expires_in: int
    #: `US-A2` — quand vrai, la seule route ouverte est /admin/auth/password.
    must_change_password: bool


class DemandeChangementMdp(BaseModel):
    ancien: str = Field(min_length=1)
    nouveau: str = Field(min_length=LONGUEUR_MDP_MIN)


@router.post("/login", response_model=ReponseSession)
async def login(demande: DemandeConnexion) -> ReponseSession:
    """`US-A1` — la connexion.

    Le refus est VOLONTAIREMENT muet sur sa cause : dire « email inconnu »
    confirmerait l'existence des comptes a un attaquant. 401, un seul message.
    """
    compte = await SuperAdminRepository().authentifier(
        str(demande.email), demande.mot_de_passe
    )
    if compte is None:
        raise HTTPException(status_code=401, detail="identifiants invalides")

    portee = "password_only" if compte.must_change_password else "admin"
    jeton, duree = emettre_jeton_admin(compte.email, portee=portee)
    return ReponseSession(
        access_token=jeton,
        expires_in=duree,
        must_change_password=compte.must_change_password,
    )


@router.post("/password", response_model=ReponseSession)
async def changer_mot_de_passe(
    demande: DemandeChangementMdp,
    session: Annotated[SessionAdmin, Depends(session_admin)],
) -> ReponseSession:
    """`US-A2` — le changement de mot de passe.

    Accessible aux DEUX portees : c'est precisement la route que la portee
    `password_only` existe pour atteindre. L'ancien mot de passe est re-verifie
    — un jeton vole ne suffit pas a changer le mot de passe.
    """
    depot = SuperAdminRepository()
    compte = await depot.authentifier(session.email, demande.ancien)
    if compte is None:
        raise HTTPException(status_code=401, detail="ancien mot de passe invalide")
    if demande.nouveau == demande.ancien:
        raise HTTPException(
            status_code=422,
            detail="le nouveau mot de passe doit differer de l'ancien",
        )

    await depot.changer_mot_de_passe(session.email, demande.nouveau)
    # La session repart PLEINE : l'obligation est levee, le jeton l'atteste.
    jeton, duree = emettre_jeton_admin(session.email, portee="admin")
    return ReponseSession(access_token=jeton, expires_in=duree, must_change_password=False)
