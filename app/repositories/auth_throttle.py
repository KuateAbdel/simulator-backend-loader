"""
app/repositories/auth_throttle.py
=================================
Anti-brute-force du login — invariant **I-AUTH-11**.

DOCTRINE (Lead QA, 20/08), a rebours du bug plateforme INV-USR-19 :

  On ne VERROUILLE JAMAIS le compte. Verrouiller a la N-ieme tentative, c'est
  offrir a un attaquant anonyme un deni de service sur l'utilisateur legitime
  (CWE-645) : il lui suffit d'echouer volontairement le login de la victime
  pour l'enfermer dehors. C'est la Disponibilite du triptyque CIA qu'on
  sacrifierait. NIST SP 800-63B (§5.2.2) et l'OWASP disent la meme chose :
  throttling + backoff, pas de lockout dur.

  Ici : un compteur d'echecs CONSECUTIFS par IDENTIFIANT soumis, et un cooldown
  a **backoff exponentiel** au-dela d'un seuil. Le cooldown GRANDIT avec les
  echecs mais reste plafonne, et il **s'auto-cicatrise** : un login reussi
  efface le compteur, et l'inactivite le purge par TTL. L'attaquant est ralenti
  jusqu'a l'inutilite ; le proprietaire legitime, lui, retrouve la porte des
  qu'il cesse de se tromper (ou via le reset par email US-A4).

ANTI-ENUMERATION : la cle est l'identifiant SOUMIS, hache — pas le compte. On
compte donc les echecs pour un email qu'il existe OU NON, et le 429 se declenche
a l'identique dans les deux cas. Le throttle ne revele jamais qu'un compte
existe (CWE-204). La cle est hachee : la collection ne stocke pas d'email clair.

PERIMETRE : cette couche protege PAR IDENTIFIANT. Elle n'arrete pas a elle
seule un password-spraying qui balaie mille emails depuis une meme source — ca,
c'est le role de la couche PAR IP (a brancher une fois le `X-Forwarded-For` du
reverse-proxy declare de confiance). Les deux sont complementaires.
"""

from __future__ import annotations

import hashlib
import math
import time
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument

from app.core.database import COLLECTION_AUTH_THROTTLE
from app.repositories.base import RepositoryBase

#: En-deca de ce nombre d'echecs consecutifs, AUCUN delai : la faute de frappe
#: honnete (quelques essais) ne coute rien. C'est un plancher, pas un verrou.
SEUIL_SANS_DELAI = 5

#: Premier cran de cooldown, en secondes, puis doublement a chaque echec.
BASE_SECONDES = 2.0

#: Plafond du cooldown. On borne pour rester du cote de la Disponibilite :
#: meme sous attaque soutenue, l'attente d'un legitime ne depasse pas ce mur,
#: et le reset par email reste toujours ouvert.
PLAFOND_SECONDES = 300.0

#: Inactivite au bout de laquelle un compteur s'efface tout seul (TTL Mongo).
TTL_INACTIVITE_SECONDES = 900


def _cle(identifiant: str) -> str:
    """Hache l'identifiant soumis (email normalise) — pas de clair en base."""
    return hashlib.sha256(identifiant.strip().lower().encode("utf-8")).hexdigest()


def cooldown_pour(echecs: int) -> float:
    """Le cooldown (secondes) pour un nombre d'echecs consecutifs donne.

    0 tant qu'on reste sous le seuil, puis backoff exponentiel plafonne.
    Fonction pure — testable sans base."""
    if echecs <= SEUIL_SANS_DELAI:
        return 0.0
    exposant = echecs - SEUIL_SANS_DELAI - 1
    return min(BASE_SECONDES * (2.0**exposant), PLAFOND_SECONDES)


class AuthThrottleRepository(RepositoryBase):
    collection_name = COLLECTION_AUTH_THROTTLE

    async def etat(self, identifiant: str) -> tuple[bool, int]:
        """(bloque, secondes_a_attendre). `bloque` vrai si un cooldown court
        encore. Ne consulte AUCUN compte — pur throttle."""
        doc = await self.collection.find_one({"_id": _cle(identifiant)})
        if doc is None:
            return (False, 0)
        reste = float(doc.get("cooldown_jusqu", 0.0)) - time.time()
        if reste > 0:
            return (True, math.ceil(reste))
        return (False, 0)

    async def enregistrer_echec(self, identifiant: str) -> None:
        """Incremente les echecs consecutifs et (re)pose le cooldown + le TTL.

        Deux temps : on incremente d'abord pour connaitre le compte a jour, puis
        on en deduit le cooldown. `find_one_and_update` upsert rend le document
        AFTER, donc `echecs` est bien la valeur incrementee."""
        cle = _cle(identifiant)
        maintenant = time.time()
        doc = await self.collection.find_one_and_update(
            {"_id": cle},
            {"$inc": {"echecs": 1}, "$setOnInsert": {"premier_echec": maintenant}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        echecs = int(doc["echecs"])
        await self.collection.update_one(
            {"_id": cle},
            {
                "$set": {
                    "cooldown_jusqu": maintenant + cooldown_pour(echecs),
                    "expire_le": datetime.now(UTC) + timedelta(seconds=TTL_INACTIVITE_SECONDES),
                }
            },
        )

    async def reinitialiser(self, identifiant: str) -> None:
        """Efface le compteur — appele APRES un login reussi. C'est
        l'auto-cicatrisation : la reussite absout les echecs passes."""
        await self.collection.delete_one({"_id": _cle(identifiant)})
