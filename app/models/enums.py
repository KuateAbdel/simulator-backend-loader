"""
app/models/enums.py
===================
Enumerations du package "Domaine Loader" (02_class.puml) et du diagramme
d'etat (06_state.puml). Ces valeurs sont propriete du Loader : elles ne sont
JAMAIS negociees avec un service FinZuu amont.
"""

from __future__ import annotations

from enum import StrEnum


class LenderType(StrEnum):
    """Type de Lender. Rappel : Lender = ROLE porte par une Company.

    company-service ne connait PAS ce concept nativement (0 occurrence
    "lender" dans son contrat) -- le Loader porte cette logique lui-meme,
    via la collection lenders_registry.
    """

    LOCAL = "LOCAL"
    INSTITUTIONNEL = "INSTITUTIONNEL"


class FakerConsumptionType(StrEnum):
    """Usage pour lequel un client Faker a ete consomme (D-FAKER-1)."""

    DEPOSITARY = "DEPOSITARY"
    LENDER_LOCAL = "LENDER_LOCAL"
    COLLECT_CLIENT = "COLLECT_CLIENT"


class NiveauOrganisation(StrEnum):
    """Niveaux 3 a 5 de l'arbre operationnel (CDC §6.2), cote Loader.

    Decision d'architecture du 08/08 (option b) : Branche et Agence ne sont
    JAMAIS persistees cote serveur. company-service n'expose aucune route pour
    elles, et son enum CompanyType ne comporte aucune valeur BRANCH — les
    materialiser en Companies filles ferait exploser le budget de 12-20
    Companies fixe par UC-07, sans aucun benefice.

    Elles restent donc des niveaux LOGIQUES, dont l'unique role est de
    distribuer geographiquement : Branche -> Region, Agence -> Ville,
    Kiosque -> Quartier. La coherence exigee par EF-11/14/15/16/18 est
    integralement preservee, puisque c'est le Loader qui choisit ces trois
    niveaux AVANT d'appeler depositary-service.

    Seul le niveau KIOSQUE a une contrepartie serveur : le Depositaire, cree
    avec company_id = l'IMF racine.
    """

    BRANCHE = "BRANCHE"
    AGENCE = "AGENCE"
    KIOSQUE = "KIOSQUE"


class RunMode(StrEnum):
    """Mode d'execution d'un run.

    DRY_RUN est le mode par defaut : aucune ecriture n'est emise vers les
    services FinZuu. Le passage en REAL est toujours une action explicite du
    Super-Admin.
    """

    DRY_RUN = "DRY_RUN"
    REAL = "REAL"


class RunStatus(StrEnum):
    """Machine d'etat de LoaderRun.status (06_state.puml).

    PARTIAL est un etat terminal legitime, pas une erreur : le CDC prevoit
    qu'une entite en echec soit journalisee et que l'execution se poursuive
    (UC-07 / UC-08, cas alternatif).
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
