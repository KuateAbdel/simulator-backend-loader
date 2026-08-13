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
    return SessionAdmin(email=claims["email"], portee=claims["portee"])


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
