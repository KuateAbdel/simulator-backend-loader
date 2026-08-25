"""
tests/test_lenders_registry_completion.py
=========================================
`EF-13`, defaut de second ordre (DRY_RUN 2fe90bec, 25/08) : une ligne de
registre inscrite avec `comptes={}` etait IRREPARABLE — le doublon rendait
None sans rien completer, et aucun run futur ne pouvait la corriger.

Le doublon COMPLETE desormais les identifiants manquants, sans JAMAIS
ecraser un existant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import database
from app.core.config import settings
from app.models.enums import LenderType
from app.repositories.lenders_registry import LendersRegistryRepository

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def registre() -> AsyncIterator[LendersRegistryRepository]:
    database.connect()
    settings.mongodb_database = "loader_finzuu_tests_registre"
    await database.get_database().drop_collection(database.COLLECTION_LENDERS_REGISTRY)
    await database.ensure_indexes()
    yield LendersRegistryRepository()
    database.close()


async def test_une_ligne_vide_se_REPARE_au_passage_suivant(
    registre: LendersRegistryRepository,
) -> None:
    """Le scenario exact du run 71fd97aa : inscrit sans comptes, puis le run
    suivant arrive AVEC les comptes reconnus — la ligne se complete."""
    company = uuid4()
    premier = await registre.enregistrer(
        company_id=company, lender_type=LenderType.LOCAL, country_code="CM", comptes={}
    )
    assert premier is not None

    comptes = {"capital": uuid4(), "interest": uuid4(), "penalty": uuid4(), "taxe": uuid4()}
    second = await registre.enregistrer(
        company_id=company, lender_type=LenderType.LOCAL, country_code="CM", comptes=comptes
    )
    assert second is None, "le role ne doit pas etre duplique"

    document = await database.get_collection(
        database.COLLECTION_LENDERS_REGISTRY
    ).find_one({"company_id": str(company)})
    assert document is not None
    assert document["capital_account_id"] == str(comptes["capital"])
    assert document["taxe_account_id"] == str(comptes["taxe"])


async def test_un_identifiant_EXISTANT_n_est_jamais_ecrase(
    registre: LendersRegistryRepository,
) -> None:
    """`$ifNull` : la valeur en place gagne toujours — un rejeu avec d'autres
    identifiants ne reecrit pas l'histoire."""
    company = uuid4()
    origine = uuid4()
    await registre.enregistrer(
        company_id=company,
        lender_type=LenderType.LOCAL,
        country_code="CM",
        comptes={"capital": origine},
    )
    await registre.enregistrer(
        company_id=company,
        lender_type=LenderType.LOCAL,
        country_code="CM",
        comptes={"capital": uuid4(), "interest": uuid4()},
    )
    document = await database.get_collection(
        database.COLLECTION_LENDERS_REGISTRY
    ).find_one({"company_id": str(company)})
    assert document is not None
    assert document["capital_account_id"] == str(origine), "l'existant a ete ecrase"
    assert document["interest_account_id"] is not None, "le manquant n'a pas ete complete"
