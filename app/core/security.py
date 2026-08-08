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
import secrets
from typing import Final

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
