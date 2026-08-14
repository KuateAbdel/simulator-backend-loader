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

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

#: VOIE PRINCIPALE (decision Yaniv 14/08) : le RELAIS SMTP de Mailjet.
#: Mesure du meme soir : le compte est « temporarily blocked » (mj-0001) sur
#: l'API HTTP v3.1, mais le relais SMTP ACCEPTE les envois — identifiants =
#: la paire cle/secret API. smtplib est synchrone : il tourne dans un thread.
_SMTP_HOTE = "in-v3.mailjet.com"
_SMTP_PORT = 587

_URL_ENVOI = "https://api.mailjet.com/v3.1/send"
#: Second secours : l'endpoint HTTP v3 historique accepte aussi.
_URL_ENVOI_LEGACY = "https://api.mailjet.com/v3/send"


def _envoyer_smtp(destinataire: str, sujet: str, texte: str) -> bool:
    """Envoi par le relais SMTP — synchrone, appele via asyncio.to_thread."""
    try:
        message = MIMEText(texte, _charset="utf-8")
        message["Subject"] = sujet
        message["From"] = f"FinZuu Loader <{settings.mailjet_expediteur}>"
        message["To"] = destinataire
        with smtplib.SMTP(_SMTP_HOTE, _SMTP_PORT, timeout=20) as relais:
            relais.starttls()
            relais.login(str(settings.mailjet_api_key), str(settings.mailjet_secret_key))
            relais.sendmail(str(settings.mailjet_expediteur), [destinataire], message.as_string())
        return True
    except (smtplib.SMTPException, OSError) as erreur:
        logger.warning("relais SMTP mailjet a refuse : %s", type(erreur).__name__)
        return False


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

    # 1) Le relais SMTP — la voie demandee par Yaniv, et la seule que le
    #    blocage de compte n'atteint pas (mesure du 14/08).
    if await asyncio.to_thread(_envoyer_smtp, destinataire, sujet, texte):
        return True
    logger.warning("relais SMTP indisponible — tentative par l'API HTTP")

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
