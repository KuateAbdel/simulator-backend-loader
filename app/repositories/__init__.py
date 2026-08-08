"""Acces aux 6 collections MongoDB proprietaires du Loader.

Un repository par collection, aucune autre. Les regles de domaine vivent ici,
pas dans les services : c'est au plus pres de la base que D-FAKER-1, l'unicite
d'un role de Lender ou l'emboitement geographique deviennent infranchissables.
"""

from app.repositories.audit_trail import AuditTrailRepository
from app.repositories.faker_ledger import FakerLedgerRepository
from app.repositories.lenders_registry import LendersRegistryRepository
from app.repositories.loader_runs import LoaderRunRepository, TransitionInterdite
from app.repositories.org_hierarchy import OrgHierarchyRepository
from app.repositories.super_admin import SuperAdminRepository

__all__ = [
    "AuditTrailRepository",
    "FakerLedgerRepository",
    "LendersRegistryRepository",
    "LoaderRunRepository",
    "OrgHierarchyRepository",
    "SuperAdminRepository",
    "TransitionInterdite",
]
