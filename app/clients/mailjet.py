"""
app/clients/mailjet.py
======================
Envoi d'email transactionnel via Mailjet (`US-A4` v2 — reinitialisation du
mot de passe du Super-Admin du Loader).

UN SEUL usage, UNE SEULE fonction : le Loader n'est pas un emetteur de
newsletters. L'API visee est `POST /v3.1/send` (auth basique cle/secret).

La fonction ne leve JAMAIS vers l'appelant : l'echec d'envoi est un booleen
et un warning au journal — la route qui l'appelle repond 202 dans tous les
cas pour ne pas confirmer l'existence d'un compte a un attaquant (le meme
raisonnement que le 401 muet du login).
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_URL_ENVOI = "https://api.mailjet.com/v3.1/send"
#: Repli mesure le 14/08 : le compte Mailjet de Yaniv est « temporarily
#: blocked » sur v3.1 (mj-0001) mais l'endpoint historique v3 ACCEPTE les
#: envois. On tente v3.1 d'abord (l'API supportee), v3 en secours.
_URL_ENVOI_LEGACY = "https://api.mailjet.com/v3/send"


def provisionne() -> bool:
    """Vrai si les trois valeurs MAILJET_* sont posees dans l'environnement."""
    return bool(
        settings.mailjet_api_key
        and settings.mailjet_secret_key
        and settings.mailjet_expediteur
    )


async def envoyer_email(destinataire: str, sujet: str, texte: str) -> bool:
    """Envoie un email texte. Vrai si Mailjet a ACCEPTE le message.

    « Accepte » signifie status HTTP 200 ET statut de message `success` —
    Mailjet peut repondre 200 avec un message rejete unitairement.
    """
    if not provisionne():
        return False
    auth = (str(settings.mailjet_api_key), str(settings.mailjet_secret_key))
    charge_v31 = {
        "Messages": [
            {
                "From": {"Email": settings.mailjet_expediteur, "Name": "FinZuu Loader"},
                "To": [{"Email": destinataire}],
                "Subject": sujet,
                "TextPart": texte,
            }
        ]
    }
    charge_legacy = {
        "FromEmail": settings.mailjet_expediteur,
        "FromName": "FinZuu Loader",
        "Subject": sujet,
        "Text-part": texte,
        "Recipients": [{"Email": destinataire}],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reponse = await client.post(_URL_ENVOI, json=charge_v31, auth=auth)
            if reponse.status_code == 200:
                try:
                    messages = reponse.json().get("Messages", [])
                    if bool(messages) and all(
                        m.get("Status") == "success" for m in messages
                    ):
                        return True
                except ValueError:
                    pass
            logger.warning(
                "mailjet v3.1 a refuse (HTTP %s) — tentative sur l'endpoint v3",
                reponse.status_code,
            )
            secours = await client.post(_URL_ENVOI_LEGACY, json=charge_legacy, auth=auth)
            if secours.status_code == 200:
                try:
                    if secours.json().get("Sent"):
                        return True
                except ValueError:
                    pass
            logger.warning("mailjet v3 a refuse aussi : HTTP %s", secours.status_code)
            return False
    except httpx.HTTPError as erreur:
        logger.warning("mailjet injoignable : %s", type(erreur).__name__)
        return False
