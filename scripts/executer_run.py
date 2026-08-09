"""
scripts/executer_run.py
=======================
Le cablage — `S3-01`. Ce que l'orchestrateur ne fait PAS lui-meme.

L'orchestrateur ne construit aucun executeur : il les recoit deja cables. Un
orchestrateur qui instancie ses dependances devient le point ou tout se couple,
et n'est plus testable sans reseau. Le cablage vit donc ici.

    uv run python scripts/executer_run.py            # DRY_RUN — aucune ecriture
    uv run python scripts/executer_run.py --reel     # ECRITURES DEFINITIVES

**Trois services n'exposent aucun `DELETE`.** `--reel` doit toujours etre
precede d'un `DRY_RUN` lu par un humain — c'est `D-01`, et le rapport a blanc
est la derniere occasion de dire non.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from app.clients.account_service import AccountServiceClient
from app.clients.company_service import CompanyServiceClient
from app.clients.depositary_service import DepositaryServiceClient
from app.clients.identity_service import IdentityServiceClient
from app.clients.product_service import ProductServiceClient
from app.clients.user_service import UserServiceClient
from app.core.cdc import FENETRE_JOURS
from app.core.config import settings
from app.core.configuration import ConfigurationExecution
from app.core.database import close, connect, ensure_indexes
from app.models.enums import RunMode
from app.repositories import (
    AuditTrailRepository,
    LendersRegistryRepository,
    OrgHierarchyRepository,
)
from app.services import organisation
from app.services.catalogue_execution import ExecuteurCatalogue
from app.services.depositaires_execution import ExecuteurDepositaires
from app.services.generateur import Generateur
from app.services.geographie import charger_referentiel
from app.services.orchestrateur import Etape, Orchestrateur
from app.services.organisation_execution import ExecuteurOrganisation
from app.services.roles_execution import ExecuteurRoles
from app.services.staff_execution import ExecuteurStaff

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
LOAN_JSON = Path("docs/reference/loan_json.json")


async def executer(mode: RunMode, etapes: set[Etape] | None = None) -> int:
    # DEFAUT TROUVE LE 09/08 PAR LA PREMIERE ECRITURE REELLE : ce cablage
    # n'ouvrait jamais MongoDB. Le `DRY_RUN` passait — il n'ecrit rien chez
    # nous — et le `REAL` mourait a la premiere ecriture locale, APRES avoir
    # deja pousse les entites vers le serveur. Quatre comptes Lender avaient
    # ete crees sans que le registre les enregistre : exactement l'ecart que le
    # journal d'intention existe pour rendre visible.
    #
    # Un essai a blanc qui n'exerce pas les memes dependances que le reel n'est
    # pas un essai a blanc.
    connect()
    await ensure_indexes()
    run_id = uuid4()
    referentiel = charger_referentiel(CLASSEUR)
    generateur = Generateur(run_id)
    configuration = ConfigurationExecution.defaut_cdc()
    plan = organisation.planifier(referentiel, run_id)

    users = UserServiceClient()
    companies = CompanyServiceClient()
    comptes = AccountServiceClient()
    produits_client = ProductServiceClient()
    depositaires = DepositaryServiceClient()
    identites = IdentityServiceClient()

    audit = AuditTrailRepository()
    registre = LendersRegistryRepository()
    hierarchie = OrgHierarchyRepository()

    ex_org = ExecuteurOrganisation(
        run_id=run_id,
        mode=mode,
        referentiel=referentiel,
        generateur=generateur,
        company_client=companies,
        user_client=users,
        account_client=comptes,
        registre_lenders=registre,
        audit=audit,
    )
    ex_cat = ExecuteurCatalogue(
        run_id=run_id,
        mode=mode,
        product_client=produits_client,
        audit=audit,
        chemin_loan_json=LOAN_JSON,
    )
    ex_dep = ExecuteurDepositaires(
        run_id=run_id,
        mode=mode,
        referentiel=referentiel,
        generateur=generateur,
        depositary_client=depositaires,
        hierarchie=hierarchie,
        audit=audit,
    )

    # Les artefacts circulent d'une etape a l'autre — c'est la seule raison
    # pour laquelle le cablage vit ici et pas dans l'orchestrateur.
    porte: dict[str, object] = {}

    async def _roles() -> object:
        return await ExecuteurRoles(mode=mode, user_client=users).executer()

    async def _organisation() -> object:
        # `ENF-16` — fenetre de 180 jours. `sim_start_date` la surcharge si
        # elle est definie ; sinon elle se termine aujourd'hui.
        fin = settings.sim_end_date or date.today()
        debut = settings.sim_start_date or (fin - timedelta(days=FENETRE_JOURS))
        rapport = await ex_org.executer(plan, debut, fin)
        porte["porteuses"] = rapport.porteuses
        return rapport

    async def _catalogue() -> object:
        rapport = await ex_cat.executer()
        porte["produits"] = rapport.souscriptibles
        return rapport

    async def _depositaires() -> object:
        porteuses = porte.get("porteuses") or []
        par_pays: dict[str, list] = {}
        for p in porteuses:  # type: ignore[union-attr]
            par_pays.setdefault(p.country_code, []).append(p)
        return await ex_dep.executer(plan, par_pays, porte.get("produits") or [])  # type: ignore[arg-type]

    async def _staff() -> object:
        return await ExecuteurStaff(
            run_id=run_id,
            mode=mode,
            configuration=configuration,
            referentiel=referentiel,
            identity_client=identites,
            user_client=users,
        ).executer()

    tous = {
        Etape.ROLES: _roles,  # type: ignore[dict-item]
        Etape.ORGANISATION: _organisation,  # type: ignore[dict-item]
        Etape.CATALOGUE: _catalogue,  # type: ignore[dict-item]
        Etape.DEPOSITAIRES: _depositaires,  # type: ignore[dict-item]
        Etape.STAFF: _staff,  # type: ignore[dict-item]
    }
    # Deploiement PAR ETAPE — la seule facon responsable d'aborder des services
    # sans `DELETE`. On passe en reel un module a la fois, en commencant par le
    # seul reversible (`ROLES`), et on verifie avant d'aller plus loin.
    travaux = {e: t for e, t in tous.items() if etapes is None or e in etapes}

    orchestrateur = Orchestrateur(run_id=run_id, mode=mode, travaux=travaux)

    try:
        rapport = await orchestrateur.executer()
    finally:
        for client in (users, companies, comptes, produits_client, depositaires, identites):
            await client.fermer()
        close()

    print(rapport.resume())
    return 0 if rapport.statut.value != "FAILED" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute un run du Loader FinZuu")
    parser.add_argument(
        "--reel",
        action="store_true",
        help="ECRITURES DEFINITIVES — trois services n'ont aucun DELETE",
    )
    parser.add_argument(
        "--etapes",
        default="",
        help="Limite aux etapes nommees, separees par des virgules (ex : ROLES). "
        "Vide = toutes. Sert au deploiement progressif en mode reel.",
    )
    args = parser.parse_args()
    choisies = {Etape(n.strip().upper()) for n in args.etapes.split(",") if n.strip()} or None
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s : %(message)s")
    return asyncio.run(executer(RunMode.REAL if args.reel else RunMode.DRY_RUN, choisies))


if __name__ == "__main__":
    raise SystemExit(main())
