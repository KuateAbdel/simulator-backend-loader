"""
scripts/reinitialiser_admin.py
==============================
`US-A4` — la reinitialisation du mot de passe OUBLIE du Super-Admin du Loader.

POURQUOI UN SCRIPT ET PAS UNE ROUTE HTTP — dit franchement : sans serveur
d'email branche, un « mot de passe oublie » par API serait du theatre de
securite. N'importe qui pourrait le declencher, et le lien de reinitialisation
n'aurait aucun canal sur pour arriver. L'AUTORITE, ici, c'est l'acces au
serveur : celui qui peut executer ce script sur la machine est l'exploitant.
C'est le modele de GitLab (`gitlab-rake`) et de Grafana (`grafana-cli admin
reset-admin-password`). v2 : reset par email via le SendMail voisin de l'hote
(`FZ-INFRA-SIMUL-2026-001`), quand il sera provisionne.

CE QUE LE SCRIPT FAIT, ET RIEN D'AUTRE :
  1. genere un mot de passe INITIAL aleatoire (24 caracteres URL-safe) ;
  2. remplace l'empreinte en base et REPOSE `must_change_password=True` —
     le mot de passe imprime est a usage unique, jamais durable (US-A2) ;
  3. l'imprime UNE FOIS sur la console de l'operateur. Il n'est ni
     journalise, ni persiste en clair, ni renvoye par aucune API.

Usage :
    PYTHONPATH=. .venv/bin/python scripts/reinitialiser_admin.py
"""

from __future__ import annotations

import asyncio
import secrets
import sys

from app.core import database
from app.core.config import settings
from app.core.security import hacher


async def reinitialiser() -> int:
    email = (settings.super_admin_email or "").strip().lower()
    if not email:
        print("SUPER_ADMIN_EMAIL absent de l'environnement — rien a reinitialiser.")
        return 1

    database.connect()
    try:
        collection = database.get_collection(database.COLLECTION_SUPER_ADMIN_ACCOUNTS)
        nouveau = secrets.token_urlsafe(18)  # 24 caracteres
        resultat = await collection.update_one(
            {"email": email},
            {"$set": {"password_hash": hacher(nouveau), "must_change_password": True}},
        )
        if not resultat.matched_count:
            print(f"Aucun compte {email!r} en base — le bootstrap n'a pas encore tourne.")
            return 1
        print(
            f"Mot de passe INITIAL reinitialise pour {email}.\n"
            f"  Mot de passe a usage unique : {nouveau}\n"
            "  Le changement de mot de passe sera EXIGE a la premiere connexion.\n"
            "  Cette valeur n'est affichee qu'ici — elle n'est ni journalisee, "
            "ni recuperable."
        )
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(reinitialiser()))
