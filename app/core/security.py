"""
app/core/security.py
====================
Hachage des mots de passe du Super-Admin du Loader.

Choix de scrypt : il est dans la bibliotheque standard. Aucune dependance
native supplementaire, donc aucun risque de roue manquante en linux_aarch64
sur le serveur cible (contrainte ARM64 de la Stack Technique). bcrypt et
argon2 auraient impose une extension compilee pour un gain nul a notre
echelle — un seul compte, une verification par session.

Format stocke : scrypt$n$r$p$sel_hex$empreinte_hex — auto-descriptif, donc les
parametres peuvent evoluer sans invalider les empreintes existantes.

Le mot de passe en clair n'est jamais journalise, jamais renvoye, jamais
persiste. Seule l'empreinte entre en base.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time as _time
from typing import Final

import jwt as _jwt

from app.core.config import settings as _settings

#: Parametres scrypt. n=2^14 tient largement le facteur de travail attendu
#: pour un compte d'outillage interne, sans penaliser le demarrage.
_N: Final = 16384
_R: Final = 8
_P: Final = 1
_LONGUEUR_SEL: Final = 16
_LONGUEUR_EMPREINTE: Final = 32


def hacher(mot_de_passe: str) -> str:
    """Produit une empreinte auto-descriptive, avec un sel aleatoire."""
    sel = secrets.token_bytes(_LONGUEUR_SEL)
    empreinte = hashlib.scrypt(
        mot_de_passe.encode("utf-8"), salt=sel, n=_N, r=_R, p=_P, dklen=_LONGUEUR_EMPREINTE
    )
    return f"scrypt${_N}${_R}${_P}${sel.hex()}${empreinte.hex()}"


def verifier(mot_de_passe: str, empreinte_stockee: str) -> bool:
    """Compare en temps constant. Une empreinte illisible renvoie False.

    Jamais d'exception propagee : un format inattendu en base ne doit pas
    faire tomber l'authentification en erreur serveur, il doit simplement
    refuser l'acces.
    """
    try:
        algo, n, r, p, sel_hex, attendu_hex = empreinte_stockee.split("$")
        if algo != "scrypt":
            return False
        calcule = hashlib.scrypt(
            mot_de_passe.encode("utf-8"),
            salt=bytes.fromhex(sel_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(bytes.fromhex(attendu_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calcule.hex(), attendu_hex)


# --------------------------------------------------------------------------
# Jetons de session du Super-Admin du Loader (US-A1..A3)
# --------------------------------------------------------------------------
#
# JWT HS256 via pyjwt — la dependance etait declaree des le squelette. Le jeton
# est STATELESS : la deconnexion (US-A3) est le rejet du jeton cote client, et
# l'expiration fait le reste (4 h, alignee sur la plateforme). Un denylist
# serveur serait de la sur-ingenierie pour UN compte : si le jeton doit etre
# revoque en urgence, changer le secret invalide tout.
#
# Deux PORTEES, et c'est ce qui rend US-A2 infranchissable :
#   "admin"          — acces complet
#   "password_only"  — emise quand must_change_password est vrai : la SEULE
#                      route acceptee est le changement de mot de passe.

_SECRET_EPHEMERE: str | None = None


def _secret_session() -> str:
    """Le secret de signature — configure, ou ephemere avec avertissement."""
    global _SECRET_EPHEMERE
    if _settings.admin_jwt_secret:
        return _settings.admin_jwt_secret
    if _SECRET_EPHEMERE is None:
        _SECRET_EPHEMERE = secrets.token_urlsafe(32)
        logging.getLogger(__name__).warning(
            "ADMIN_JWT_SECRET absent : secret de session EPHEMERE genere — "
            "les sessions ne survivront pas a un redemarrage du processus."
        )
    return _SECRET_EPHEMERE


def emettre_jeton_admin(email: str, *, portee: str) -> tuple[str, int]:
    """Emet le jeton de session. Rend (jeton, duree_en_secondes)."""
    duree = _settings.admin_session_duree_heures * 3600
    maintenant = int(_time.time())
    jeton = _jwt.encode(
        {"sub": email, "scope": portee, "iat": maintenant, "exp": maintenant + duree},
        _secret_session(),
        algorithm="HS256",
    )
    return jeton, duree


def verifier_jeton_admin(jeton: str) -> dict[str, str] | None:
    """Rend les claims du jeton, ou None. Jamais d'exception propagee :
    un jeton illisible, expire ou signe autrement REFUSE, il ne plante pas."""
    try:
        claims = _jwt.decode(jeton, _secret_session(), algorithms=["HS256"])
    except _jwt.PyJWTError:
        return None
    if not isinstance(claims.get("sub"), str) or claims.get("scope") not in (
        "admin",
        "password_only",
    ):
        return None
    return {"email": claims["sub"], "portee": claims["scope"]}
