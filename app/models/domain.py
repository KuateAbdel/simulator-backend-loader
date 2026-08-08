"""
app/models/domain.py
====================
Les 5 documents MongoDB proprietaires du Loader, package "Domaine Loader"
de docs/reference/uml_diagrams/02_class.puml.

Regle de nommage stricte : chaque classe ci-dessous porte EXACTEMENT les
champs du diagramme de classe et de docs/CONTEXT.md, sans champ invente et
sans champ omis. Un champ absent du diagramme n'a pas sa place ici ; s'il
devient necessaire, il passe d'abord par une mise a jour du diagramme.

Le champ MongoDB `_id` est expose sous l'alias Python `id` (populate_by_name
actif) : la serialisation vers motor utilise systematiquement by_alias=True.

Frontiere a ne jamais franchir : ces 5 collections sont la SEULE persistance
du Loader. Toute entite FinZuu (Company, Client, Product, Account, Identity,
Kiosque...) vit dans son service amont et n'est jamais dupliquee ici -- seuls
ses identifiants sont references.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    FakerConsumptionType,
    LenderType,
    NiveauOrganisation,
    RunMode,
    RunStatus,
)


class LoaderDocument(BaseModel):
    """Base commune : alias _id, validation stricte, pas de champ surnumeraire."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        use_enum_values=False,
    )


class FakerConsumptionLedger(LoaderDocument):
    """Collection `faker_consumption_ledger` -- support technique de D-FAKER-1.

    `_id` EST le client_id Faker : c'est l'unicite MongoDB elle-meme qui
    garantit qu'un client Faker ne peut pas etre consomme deux fois. La
    verification applicative (find_one avant tirage) et cette contrainte
    d'unicite sont redondantes VOLONTAIREMENT -- la premiere donne un message
    lisible, la seconde rend la violation structurellement impossible en cas
    de concurrence.
    """

    id: str = Field(alias="_id", description="client_id Faker -- cle naturelle")
    consumed_at: datetime
    consumed_for: FakerConsumptionType
    resulting_entity_id: UUID
    country_code: str = Field(min_length=2, max_length=2)


class LenderRegistryEntry(LoaderDocument):
    """Collection `lenders_registry` -- le Lender comme ROLE porte par une Company.

    Les 4 comptes financiers (CAPITAL / INTEREST / PENALTY / TAXE, UC-10 et
    EF-13) sont declares optionnels ici, et c'est deliberé : leur cascade de
    creation cote account-service est un TROU CONFIRME (Trou #2, diagramme
    03_sequence_lender) -- jamais verifiee empiriquement, contrairement aux 6
    comptes du Depositaire. Un Lender partiellement initialise est un etat
    legitime a representer, pas une donnee invalide a rejeter.
    """

    id: UUID = Field(alias="_id")
    company_id: UUID = Field(description="Reference vers la Company porteuse du role")
    lender_type: LenderType
    country_code: str = Field(min_length=2, max_length=2)
    capital_account_id: UUID | None = None
    interest_account_id: UUID | None = None
    penalty_account_id: UUID | None = None
    taxe_account_id: UUID | None = None


class LoaderRun(LoaderDocument):
    """Collection `loader_runs` -- etat de simulation d'une execution.

    `_id` est le run_id PROPRE au Loader. Il ne doit jamais etre confondu avec
    le run_id de partition Faker (20260620123721), qui appartient a un autre
    systeme et n'a pas la meme semantique.
    """

    id: UUID = Field(alias="_id", description="run_id Loader -- distinct du run_id Faker")
    sim_start_date: date
    sim_end_date: date
    status: RunStatus = RunStatus.PENDING
    mode: RunMode = RunMode.DRY_RUN
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)


class AuditTrailEntry(LoaderDocument):
    """Collection `audit_trail` -- SIEM applicatif interne (EF-61 a EF-64).

    `before` / `after` portent l'etat de l'entite de part et d'autre de
    l'action. `before` est None a la creation, `after` est None a la
    suppression -- les deux ne sont jamais None simultanement.
    """

    id: UUID = Field(alias="_id")
    run_id: UUID = Field(description="Reference vers LoaderRun._id")
    entity_type: str
    entity_id: UUID
    action: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    timestamp: datetime


class OrgHierarchyNode(LoaderDocument):
    """Collection `org_hierarchy` -- arbre operationnel cote Loader (niveaux 3 a 5).

    SIXIEME collection, ajoutee le 08/08/2026 en consequence directe de la
    decision (b) sur Branche/Agence. Elle n'est pas un confort : sans elle,
    CR-02 devient invérifiable -- ce critere de recette exige de controler que
    « chaque Kiosque a un District valide, chaque Agence une Ville valide ».

    Un seul document par noeud, les trois niveaux dans la meme collection :
    l'arbre se relit alors par une seule requete, et la verification de
    recette porte sur une seule source.

    Invariant structurel (EF-18) : un noeud ne peut exister sans son superieur.
    - BRANCHE : parent_id = None, region_id renseigne
    - AGENCE  : parent_id = une BRANCHE, city_id renseigne
    - KIOSQUE : parent_id = une AGENCE, district_id ET depositary_id renseignes

    `depositary_id` est la SEULE reference vers une entite reellement creee
    cote serveur (depositary-service). Les niveaux BRANCHE et AGENCE n'ont
    aucune contrepartie distante -- c'est tout l'objet de la decision (b).
    """

    id: UUID = Field(alias="_id")
    run_id: UUID = Field(description="Reference vers LoaderRun._id (EF-64)")
    niveau: NiveauOrganisation
    parent_id: UUID | None = Field(
        default=None, description="None pour BRANCHE, sinon le noeud du niveau superieur"
    )
    company_id: UUID = Field(description="IMF racine — porte toute la descendance")
    name: str
    country_code: str = Field(min_length=2, max_length=2)
    region_id: str | None = None
    city_id: str | None = None
    district_id: str | None = None
    depositary_id: UUID | None = Field(
        default=None, description="Renseigne au niveau KIOSQUE uniquement (depositary-service)"
    )


class SuperAdminAccount(LoaderDocument):
    """Collection `super_admin_accounts` -- authentification propre au Loader.

    Distincte de user-service (cf. 10_component.puml) : ce compte pilote le
    Loader, il n'a aucune existence dans l'ecosysteme FinZuu. Bootstrap au
    premier demarrage via SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD_INITIAL.

    Seul le hash est persiste. Le mot de passe initial n'est jamais ecrit en
    base, ni journalise, ni renvoye par l'API.
    """

    id: UUID = Field(alias="_id")
    email: str
    password_hash: str
    must_change_password: bool = True
