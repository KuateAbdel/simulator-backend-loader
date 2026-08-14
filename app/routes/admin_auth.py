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

LE MOT DE PASSE OUBLIE (`US-A4`) — deux niveaux, dits franchement :

1. **Par email (v2, LIVRE le 14/08)** : `POST /mot-de-passe-oublie` envoie un
   CODE a 8 chiffres via Mailjet (cles fournies par Yaniv), valide 15 min,
   5 essais maximum. `POST /reinitialiser` le consomme avec le nouveau mot
   de passe. La reponse du premier est TOUJOURS 202 quand le service est
   provisionne — confirmer qu'un email existe serait offrir l'enumeration
   des comptes a un attaquant (meme doctrine que le 401 muet du login).
   Si les cles MAILJET_* ne sont pas posees : 503 NOMME, jamais un envoi
   silencieusement perdu.
2. **Sur le serveur (v1, conserve)** : `scripts/reinitialiser_admin.py`,
   execute par l'operateur — l'acces au serveur est la preuve d'autorite
   (modele GitLab `gitlab-rake`). Reste le recours si Mailjet est mort.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.clients import mailjet
from app.core.security import emettre_jeton_admin
from app.repositories.super_admin import SuperAdminRepository
from app.routes.dependances import SessionAdmin, session_admin

router = APIRouter(prefix="/admin/auth", tags=["admin — session"])

#: Longueur minimale du mot de passe durable. 12 est le plancher NIST/ANSSI
#: pour un compte a privilege unique ; la complexite par classes de caracteres
#: n'est PAS exigee — c'est la longueur qui protege, pas les `@`.
LONGUEUR_MDP_MIN = 12

#: Le code de reinitialisation : 8 chiffres, 15 minutes, 5 essais. Un code
#: court est acceptable PARCE QUE la fenetre est courte et les essais bornes.
CODE_RESET_VALIDITE_SECONDES = 15 * 60
CODE_RESET_ESSAIS_MAX = 5


def _hacher_code(code: str) -> str:
    """SHA-256 suffit : le code a 15 min de vie et 5 essais — le cout d'un
    bcrypt ne protegerait rien de plus ici."""
    return hashlib.sha256(code.encode()).hexdigest()


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


# --------------------------------------------------------------------------
# `US-A4` v2 — reinitialisation par email (Mailjet)
# --------------------------------------------------------------------------


class DemandeMotDePasseOublie(BaseModel):
    email: EmailStr


class DemandeReinitialisation(BaseModel):
    email: EmailStr
    code: str = Field(min_length=1)
    nouveau: str = Field(min_length=LONGUEUR_MDP_MIN)


@router.post("/mot-de-passe-oublie", status_code=202)
async def mot_de_passe_oublie(demande: DemandeMotDePasseOublie) -> dict[str, object]:
    """`US-A4` v2 — envoie un code de reinitialisation par email.

    202 TOUJOURS quand le service est provisionne, que le compte existe ou
    non : confirmer l'existence d'un email offrirait l'enumeration des
    comptes (meme doctrine que le 401 muet du login). L'echec d'ENVOI est
    journalise en warning mais ne change pas la reponse, pour la meme raison.
    """
    if not mailjet.provisionne():
        raise HTTPException(
            status_code=503,
            detail=(
                "reinitialisation par email non provisionnee — poser "
                "MAILJET_API_KEY, MAILJET_SECRET_KEY et MAILJET_EXPEDITEUR ; "
                "recours : scripts/reinitialiser_admin.py sur le serveur"
            ),
        )

    depot = SuperAdminRepository()
    email = str(demande.email).strip().lower()
    compte = await depot.par_email(email)
    if compte is not None:
        code = f"{secrets.randbelow(10**8):08d}"
        await depot.poser_code_reinitialisation(
            email, _hacher_code(code), time.time() + CODE_RESET_VALIDITE_SECONDES
        )
        await mailjet.envoyer_email(
            email,
            "FinZuu Loader — code de réinitialisation",
            (
                f"Votre code de réinitialisation : {code}\n\n"
                f"Il expire dans {CODE_RESET_VALIDITE_SECONDES // 60} minutes "
                f"({CODE_RESET_ESSAIS_MAX} essais maximum).\n"
                "Si vous n'êtes pas à l'origine de cette demande, ignorez ce "
                "message — votre mot de passe actuel reste valable."
            ),
        )
    return {
        "detail": "si un compte existe pour cet email, un code a été envoyé",
        "validite_minutes": CODE_RESET_VALIDITE_SECONDES // 60,
    }


@router.post("/reinitialiser", response_model=ReponseSession)
async def reinitialiser_par_code(demande: DemandeReinitialisation) -> ReponseSession:
    """`US-A4` v2 — consomme le code et pose le nouveau mot de passe.

    Le refus est GENERIQUE (401, un seul message) : distinguer « email
    inconnu » / « code faux » / « code expire » renseignerait un attaquant.
    Le mot de passe qui en sort est DURABLE (choisi par son proprietaire) —
    la session repart pleine, comme apres `US-A2`.
    """
    refus = HTTPException(status_code=401, detail="code invalide ou expiré")
    depot = SuperAdminRepository()
    email = str(demande.email).strip().lower()
    compte = await depot.par_email(email)
    if compte is None or compte.code_reset_hash is None or compte.code_reset_expire is None:
        raise refus
    if time.time() > compte.code_reset_expire:
        raise refus
    if compte.code_reset_essais >= CODE_RESET_ESSAIS_MAX:
        raise refus
    if not hmac.compare_digest(compte.code_reset_hash, _hacher_code(demande.code)):
        # L'essai rate CONSOMME — 5 echecs tuent le code, meme encore valide.
        await depot.incrementer_essais_reset(email)
        raise refus
    if demande.nouveau == demande.code:
        raise HTTPException(
            status_code=422, detail="le mot de passe ne peut pas être le code lui-même"
        )

    await depot.changer_mot_de_passe(email, demande.nouveau)
    await depot.effacer_code_reinitialisation(email)
    jeton, duree = emettre_jeton_admin(email, portee="admin")
    return ReponseSession(access_token=jeton, expires_in=duree, must_change_password=False)
