"""
app/services/bootstrap.py
=========================
Amorcage du compte Super-Admin **du Loader**, au premier demarrage.

Rappel de perimetre : ce compte pilote NOTRE outil. Il n'a aucune existence
dans l'ecosysteme FinZuu, et n'a rien a voir avec le role metier « Super-Admin »
de la plateforme, qui vit dans les groupes de user-service.

Phase 1 du CDC = Super-Admin UNIQUEMENT. Le modele Admin multi-tenant est
reporte en Phase 2 (01_use_case.puml).

Le mot de passe initial arrive par variable d'environnement, il est hache
immediatement, et le compte nait avec `must_change_password=True` : ce n'est
jamais un mot de passe durable. Le clair n'est ni journalise ni conserve.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.repositories.super_admin import SuperAdminRepository

logger = logging.getLogger(__name__)


async def amorcer_super_admin() -> str:
    """Cree le compte s'il est absent. Renvoie un motif, pour journalisation.

    Ne leve jamais : un demarrage sans variables d'environnement doit laisser
    l'application repondre sur /health, pas la faire tomber. L'absence de
    compte est signalee, elle n'est pas fatale.
    """
    if not settings.super_admin_email or not settings.super_admin_password_initial:
        logger.warning(
            "Bootstrap Super-Admin ignore : SUPER_ADMIN_EMAIL et/ou "
            "SUPER_ADMIN_PASSWORD_INITIAL absents de l'environnement."
        )
        return "ignore_variables_absentes"

    depot = SuperAdminRepository()
    existant = await depot.par_email(settings.super_admin_email)
    if existant is not None:
        logger.info("Bootstrap Super-Admin : compte deja present, aucune action.")
        return "deja_present"

    compte = await depot.creer(
        settings.super_admin_email,
        settings.super_admin_password_initial,
        role="super_admin",
    )
    logger.info(
        "Bootstrap Super-Admin : compte cree (%s), changement de mot de passe requis.",
        compte.email,
    )
    return "cree"
