"""
app/services/notifications.py
=============================
Le SERVICE de notification du Loader — la couche qui separe l'EVENEMENT du
CANAL (doctrine « comme Microsoft », 20/08).

  evenement (ce qui s'est passe)
      -> resolution des DESTINATAIRES (par ROLE : les Super-Admins)
          -> livraison sur les CANAUX (in-app toujours ; email si sensible)

Le code metier n'appelle QUE `sur_...(...)` : il ne parle jamais ni de MongoDB
ni de SMTP. Le service resout qui informer et par quels canaux.

REGLE D'OR : une notification ne fait JAMAIS echouer l'action qui la declenche.
Informer est un effet de bord ; si le canal tombe, l'action reste faite. D'ou
le `try/except` qui avale et journalise, jamais ne propage.

RELATION AU RBAC : les destinataires se deduisent des ROLES (on previent les
Super-Admins des gestes sensibles). Voir la matrice FZ-RBAC-LOADER.
"""

from __future__ import annotations

import logging
from typing import Any

from app.clients import mailjet
from app.repositories.notifications import NotificationRepository
from app.repositories.super_admin import SuperAdminRepository

logger = logging.getLogger(__name__)

# -- Types d'evenements (la cle de rendu cote frontend) --------------------
COMPTE_CREE = "compte_cree"
ROLE_CHANGE = "role_change"
COMPTE_DESACTIVE = "compte_desactive"
COMPTE_REACTIVE = "compte_reactive"


async def emails_super_admins(exclure: str | None = None) -> list[str]:
    """Les emails des Super-Admins ACTIFS — l'audience des gestes sensibles.

    `exclure` retire l'auteur du geste : on ne se notifie pas soi-meme."""
    hors = (exclure or "").strip().lower()
    comptes = await SuperAdminRepository().lister()
    return [
        c.email
        for c in comptes
        if c.actif and c.role not in ("admin", "viewer") and c.email != hors
    ]


async def _notifier(
    destinataires: list[str],
    type_: str,
    donnees: dict[str, Any],
    *,
    email_sujet: str | None = None,
    email_corps: str | None = None,
) -> None:
    """Livre une notification a chaque destinataire : IN-APP toujours, EMAIL si
    `email_sujet`/`email_corps` sont fournis. Best-effort, dedoublonne."""
    depot = NotificationRepository()
    vus: set[str] = set()
    for brut in destinataires:
        dest = brut.strip().lower()
        if not dest or dest in vus:
            continue
        vus.add(dest)
        await depot.creer(dest, type_, donnees)
        if email_sujet and email_corps:
            await mailjet.envoyer_email(dest, email_sujet, email_corps)


# -- Points d'entree metier (le code appelle CECI) -------------------------


async def sur_compte_cree(email: str, role: str, acteur: str) -> None:
    """Un compte vient d'etre cree — on previent les autres Super-Admins."""
    try:
        dest = await emails_super_admins(exclure=acteur)
        await _notifier(dest, COMPTE_CREE, {"email": email, "role": role, "acteur": acteur})
    except Exception as erreur:  # informer ne casse JAMAIS l'action
        logger.warning("notification compte_cree ignoree : %s", type(erreur).__name__)


async def sur_role_change(email: str, role: str, acteur: str) -> None:
    """Un role a change — on previent les Super-Admins ET la personne visee."""
    try:
        dest = await emails_super_admins(exclure=acteur)
        await _notifier(
            [*dest, email], ROLE_CHANGE, {"email": email, "role": role, "acteur": acteur}
        )
    except Exception as erreur:  # informer ne casse JAMAIS l'action
        logger.warning("notification role_change ignoree : %s", type(erreur).__name__)


async def sur_compte_desactive(email: str, acteur: str, motif: str) -> None:
    """Desactivation — geste SENSIBLE : in-app ET email aux Super-Admins."""
    try:
        dest = await emails_super_admins(exclure=acteur)
        await _notifier(
            dest,
            COMPTE_DESACTIVE,
            {"email": email, "acteur": acteur, "motif": motif},
            email_sujet="FinZuu Loader — compte désactivé",
            email_corps=(
                f"Le compte {email} a été désactivé par {acteur}.\n"
                f"Motif : {motif}\n\n"
                "Notification automatique du Loader FinZuu."
            ),
        )
    except Exception as erreur:  # informer ne casse JAMAIS l'action
        logger.warning("notification compte_desactive ignoree : %s", type(erreur).__name__)


async def sur_compte_reactive(email: str, acteur: str) -> None:
    """Reactivation — on previent les Super-Admins (in-app)."""
    try:
        dest = await emails_super_admins(exclure=acteur)
        await _notifier(dest, COMPTE_REACTIVE, {"email": email, "acteur": acteur})
    except Exception as erreur:  # informer ne casse JAMAIS l'action
        logger.warning("notification compte_reactive ignoree : %s", type(erreur).__name__)
