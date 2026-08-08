"""
app/core/database.py
====================
Acces MongoDB via motor (driver asynchrone officiel, FZ-STACK-LOADER-2026-001 §5.3).

Un seul client motor est cree au demarrage de l'application et partage par
toutes les requetes : ouvrir un client par requete epuiserait le pool de
connexions bien avant les 2000 clients de l'objectif OBJ-02.

Le client motor ne se connecte pas a l'instanciation. Un demarrage sans
MongoDB joignable ne fait donc pas echouer le processus -- c'est voulu : le
squelette doit pouvoir demarrer et repondre sur /health avant que la base ne
soit provisionnee.
"""

from __future__ import annotations

from typing import Any, Final

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.config import settings

#: Type du document renvoye par motor. Les classes de app/models/domain.py
#: valident ces dictionnaires bruts en entree comme en sortie -- aucun
#: document n'est manipule sans passer par elles.
MongoDocument = dict[str, Any]

# --------------------------------------------------------------------------
# Noms des 5 collections proprietaires. Aucune autre collection n'est creee
# par le Loader (cf. app/models/domain.py).
# --------------------------------------------------------------------------
COLLECTION_FAKER_CONSUMPTION_LEDGER: Final = "faker_consumption_ledger"
COLLECTION_LENDERS_REGISTRY: Final = "lenders_registry"
COLLECTION_LOADER_RUNS: Final = "loader_runs"
COLLECTION_AUDIT_TRAIL: Final = "audit_trail"
COLLECTION_SUPER_ADMIN_ACCOUNTS: Final = "super_admin_accounts"
#: Sixieme collection — arbre operationnel Branche/Agence/Kiosque cote Loader.
#: Consequence de la decision (b) du 08/08 : sans elle, CR-02 est invérifiable.
COLLECTION_ORG_HIERARCHY: Final = "org_hierarchy"

_client: AsyncIOMotorClient[MongoDocument] | None = None


def connect() -> AsyncIOMotorClient[MongoDocument]:
    """Ouvre le client motor partage. Idempotent."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongodb_uri, uuidRepresentation="standard")
    return _client


def close() -> None:
    """Ferme le client motor partage. Idempotent."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_database() -> AsyncIOMotorDatabase[MongoDocument]:
    if _client is None:
        raise RuntimeError("Client MongoDB non initialise -- connect() n'a pas ete appele.")
    return _client[settings.mongodb_database]


def get_collection(name: str) -> AsyncIOMotorCollection[MongoDocument]:
    return get_database()[name]


async def ensure_indexes() -> None:
    """Cree les index qui portent les invariants du domaine.

    Ces index ne sont pas une optimisation : ils rendent structurellement
    impossibles des violations que la couche applicative ne peut garantir
    seule sous concurrence.

    - faker_consumption_ledger : `_id` = client_id Faker. L'unicite de la cle
      primaire MongoDB EST le garde-fou D-FAKER-1 -- aucun index additionnel
      n'est requis pour cela. L'index sur (consumed_for, country_code) sert
      les statistiques de fin de run.
    - lenders_registry : un couple (company_id, lender_type) est unique. Une
      Company ne porte pas deux fois le meme role (EF-12, idempotence ENF-04).
    - audit_trail : index sur run_id + timestamp pour l'export du journal
      d'une execution (EF-62).
    - super_admin_accounts : email unique (Phase 1 = Super-Admin unique).
    """
    db = get_database()

    await db[COLLECTION_FAKER_CONSUMPTION_LEDGER].create_index(
        [("consumed_for", 1), ("country_code", 1)],
        name="idx_consumed_for_country",
    )
    await db[COLLECTION_LENDERS_REGISTRY].create_index(
        [("company_id", 1), ("lender_type", 1)],
        name="uniq_company_lender_type",
        unique=True,
    )
    await db[COLLECTION_LENDERS_REGISTRY].create_index(
        [("country_code", 1)],
        name="idx_country_code",
    )
    await db[COLLECTION_LOADER_RUNS].create_index(
        [("status", 1)],
        name="idx_status",
    )
    await db[COLLECTION_AUDIT_TRAIL].create_index(
        [("run_id", 1), ("timestamp", 1)],
        name="idx_run_timestamp",
    )
    await db[COLLECTION_SUPER_ADMIN_ACCOUNTS].create_index(
        [("email", 1)],
        name="uniq_email",
        unique=True,
    )
    # CR-02 : la verification de recette se fait par une seule requete sur
    # (run_id, niveau). L'unicite du district par run garantit qu'aucun quartier
    # n'heberge deux Kiosques du meme run — c'est ce qui rend la repartition
    # geographique credible plutot que concentree (partial : seuls les noeuds
    # KIOSQUE portent un district_id).
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("niveau", 1)],
        name="idx_run_niveau",
    )
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("parent_id", 1)],
        name="idx_parent",
    )
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("district_id", 1)],
        name="uniq_district_par_run",
        unique=True,
        partialFilterExpression={"district_id": {"$type": "string"}},
    )
