"""
app/routes/dependances.py
=========================
Dependances FastAPI transverses de l'API d'administration.

Le controle central : TOUTE route `/admin/*` (hors `/admin/auth/login`) exige
un jeton Bearer valide. La portee `password_only` — emise tant que
`must_change_password` est vrai — n'ouvre QUE le changement de mot de passe :
c'est le mecanisme qui rend `US-A2` infranchissable, pas une consigne d'ecran.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import verifier_jeton_admin

#: `auto_error=False` : l'absence d'en-tete doit rendre NOTRE 401 homogene,
#: pas le 403 par defaut de FastAPI.
_porteur = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class SessionAdmin:
    email: str
    portee: str
    #: Role RBAC du Loader ('viewer' < 'admin' < 'super_admin'). Defaut
    #: 'super_admin' pour un jeton anterieur au RBAC (retro-compatibilite).
    role: str = "super_admin"


async def session_admin(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_porteur)],
) -> SessionAdmin:
    """Session authentifiee, QUELLE QUE SOIT la portee.

    Sert la route de changement de mot de passe — la seule que la portee
    `password_only` a le droit d'atteindre.
    """
    if creds is None:
        raise HTTPException(status_code=401, detail="jeton de session requis")
    claims = verifier_jeton_admin(creds.credentials)
    if claims is None:
        raise HTTPException(status_code=401, detail="session invalide ou expiree")
    return SessionAdmin(
        email=claims["email"],
        portee=claims["portee"],
        role=claims.get("role", "super_admin"),
    )


async def refuser_si_run_en_cours() -> None:
    """Verrou `EF-55` — configuration ET referentiels sont FIGES pendant un
    run : les modifier sous une generation en cours rendrait son empreinte
    D-10 mensongere. 409 avec l'identifiant du run qui verrouille."""
    from app.repositories.loader_runs import LoaderRunRepository

    en_cours = await LoaderRunRepository().dernier_en_cours()
    if en_cours is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"run {en_cours.id} a l'etat {en_cours.status.value} — "
                "ecriture verrouillee pendant une generation (EF-55)"
            ),
        )


async def admin_complet(
    session: Annotated[SessionAdmin, Depends(session_admin)],
) -> SessionAdmin:
    """Session a portee COMPLETE — toute route d'administration ordinaire.

    `US-A2` : tant que le mot de passe initial n'est pas change, 403 avec le
    chemin de sortie dans le message.
    """
    if session.portee != "admin":
        raise HTTPException(
            status_code=403,
            detail=(
                "changement de mot de passe requis avant tout acces — "
                "POST /admin/auth/password"
            ),
        )
    return session


#: Hierarchie des roles RBAC du Loader (matrice FZ-RBAC-LOADER). Un rang plus
#: eleve possede toutes les capacites des rangs inferieurs.
RANG_ROLE = {"viewer": 0, "admin": 1, "super_admin": 2}


async def exige_admin(
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> SessionAdmin:
    """Garde d'OPERATION : role >= admin. Un `viewer` (lecture seule) est
    refuse en 403 au niveau de l'API — l'UI ne fait que le refleter."""
    if RANG_ROLE.get(session.role, 0) < RANG_ROLE["admin"]:
        raise HTTPException(
            status_code=403,
            detail="operation reservee aux roles Admin et Super-Admin (lecture seule)",
        )
    return session


async def exige_super_admin(
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> SessionAdmin:
    """Garde des ACTIONS SENSIBLES : purge, suppressions destructives, gestion
    des comptes et des roles. Reservee au `super_admin`."""
    if session.role != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="action reservee au Super-Admin",
        )
    return session
