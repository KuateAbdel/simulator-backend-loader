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
from uuid import UUID, uuid4

from app.clients.account_service import AccountServiceClient
from app.clients.client_service import ClientServiceClient
from app.clients.company_service import CompanyServiceClient
from app.clients.depositary_service import DepositaryServiceClient
from app.clients.faker_service import FakerClient
from app.clients.identity_service import IdentityServiceClient
from app.clients.product_service import ProductServiceClient
from app.clients.user_service import UserServiceClient
from app.core.cdc import FENETRE_JOURS, PAYS_CIBLES
from app.core.config import settings
from app.core.configuration import ConfigurationExecution
from app.core.database import close, connect, ensure_indexes
from app.core.temps import ModeCompression, TempsSimulation
from app.models.enums import RunMode, RunStatus
from app.repositories import (
    AuditTrailRepository,
    FakerLedgerRepository,
    LendersRegistryRepository,
    LoaderRunRepository,
    OrgHierarchyRepository,
)
from app.services import organisation
from app.services.catalogue_execution import ExecuteurCatalogue
from app.services.clients_execution import ExecuteurClients, RapportClients
from app.services.depositaires_execution import ExecuteurDepositaires, ProduitSouscriptible
from app.services.generateur import Generateur
from app.services.geographie import charger_referentiel
from app.services.orchestrateur import Etape, Orchestrateur, RapportEtape, Travail
from app.services.organisation import CompanyPorteuse
from app.services.organisation_execution import ExecuteurOrganisation
from app.services.recette import ControleRecette
from app.services.roles_execution import ExecuteurRoles
from app.services.staff_execution import ExecuteurStaff

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
LOAN_JSON = Path("docs/reference/loan_json.json")


async def executer(
    mode: RunMode, etapes: set[Etape] | None = None, ignorer_verrou: bool = False
) -> int:
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
    configuration = ConfigurationExecution.defaut_cdc()

    # `ENF-16` — fenetre de 180 jours, calculee ICI : elle fait partie de ce que
    # le run FIGE, et elle est l'ancre temporelle du generateur (`ENF-15`).
    fin = settings.sim_end_date or date.today()
    debut = settings.sim_start_date or (fin - timedelta(days=FENETRE_JOURS))

    # `EF-76` — la fenetre cesse d'etre deux dates nues. `TempsSimulation` porte
    # la conversion jour de simulation <-> horodatage reel, et il REFUSE au
    # lancement ce qui n'a pas de sens : fenetre inversee, compression hors des
    # bornes de l'Annexe D.3. Mieux vaut echouer ici qu'a la 1 400e transaction.
    #
    # Il est construit maintenant, avant toute ecriture, pour deux raisons :
    #   1. son `resume()` entre dans le rapport d'essai a blanc — `D-01` fait de
    #      ce rapport « la derniere occasion de dire non », et un operateur ne
    #      peut pas dire non a une fenetre qu'on ne lui montre pas ;
    #   2. un ecart a `ENF-16` (fenetre != 180 jours) devient VISIBLE au lieu
    #      d'etre decouvert dans les graphiques du bailleur.
    temps = TempsSimulation(
        debut=debut,
        fin=fin,
        mode=ModeCompression(settings.sim_mode_compression),
        secondes_par_jour_accelere=settings.sim_secondes_par_jour,
    )

    # `ENF-15` — le generateur tirait ses dates de naissance depuis
    # `date.today()`. Le meme `run_id` rejoue un autre jour produisait d'autres
    # entites. Il s'ancre desormais sur la fin de fenetre du run.
    generateur = Generateur(run_id, reference=fin)
    plan = organisation.planifier(referentiel, run_id, configuration=configuration)

    # DEFAUT TROUVE LE 11/08 EN RELISANT CE CABLAGE : `LoaderRunRepository`
    # n'etait instancie NULLE PART. Les six collections existaient, leurs index
    # etaient poses, le repository etait teste unitairement — et le chemin reel
    # ne l'appelait jamais. Consequence mesuree : apres un DRY_RUN complet des
    # huit modules, `loader_runs` contenait ZERO document.
    #
    # Ce n'etait pas une commodite manquante. Quatre exigences etaient muettes :
    #   `D-10`   la configuration figee au lancement n'etait jamais persistee,
    #            donc `ENF-15` (reproductibilite) et `CR-04` invérifiables ;
    #   `EF-64`  le `run_id` mourait avec le process ;
    #   `EF-55`  le verrou anti-double-execution n'etait jamais interroge ;
    #   reprise  `Orchestrateur.etapes_acquises()` est ecrit et teste, mais
    #            aucun run n'ecrivait les checkpoints qui l'alimentent.
    depot_runs = LoaderRunRepository()
    # Le registre Faker : instancie ICI parce que la reconciliation de fin de
    # run doit le lire. Un `reserver()` sans lecture des orphelines refait le
    # defaut que ce module vient de corriger.
    ledger_faker = FakerLedgerRepository()

    # `EF-55` — deux generations simultanees sont interdites, et depuis le 11/08
    # l'interdit est STRUCTUREL : un index unique partiel sur `status ==
    # "RUNNING"` rend le second run impossible au niveau du moteur.
    #
    # CONSEQUENCE SUR L'ECHAPPATOIRE : `--ignorer-verrou` ne peut plus « passer
    # outre » — un index ne se contourne pas. Il fait donc la seule chose
    # correcte : il **CLOT** le run bloque en `FAILED`, un etat terminal et vrai,
    # puis il laisse la place. C'est mieux que l'ancien contournement, qui aurait
    # laisse deux runs se croire actifs.
    en_cours = await depot_runs.dernier_en_cours()
    if en_cours is not None:
        if not ignorer_verrou:
            print(
                f"REFUS (EF-55) — le run {en_cours.id} est {en_cours.status.value}.\n"
                f"  Deux generations simultanees sont interdites.\n"
                f"  S'il s'agit d'un run interrompu, relancer avec --ignorer-verrou :\n"
                f"  il sera clos en FAILED, jamais laisse en suspens."
            )
            close()
            return 2
        if en_cours.status is RunStatus.RUNNING:
            await depot_runs.changer_statut(en_cours.id, RunStatus.FAILED)
            print(f"VERROU LIBERE — run {en_cours.id} clos en FAILED (etait RUNNING).")

    run = await depot_runs.creer(
        sim_start_date=debut,
        sim_end_date=fin,
        mode=mode,
        run_id=run_id,
        configuration=configuration.empreinte(),
    )
    # `PENDING -> RUNNING` : la machine d'etat de `06_state.puml` refuse
    # `PENDING -> PARTIAL`. Sans cette transition, la cloture du run leverait
    # `TransitionInterdite` a la derniere ligne d'une campagne de 30 minutes.
    await depot_runs.changer_statut(run.id, RunStatus.RUNNING)

    users = UserServiceClient()
    # Faker est en LECTURE SEULE et sans authentification : il n'entre pas dans
    # la session ROOT partagee des neuf services FinZuu.
    faker = FakerClient()
    clients_finaux = ClientServiceClient()
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
    # pour laquelle le cablage vit ici et pas dans l'orchestrateur. Ils sont
    # TYPES : c'etait un `dict[str, object]` que trois `type: ignore` rendaient
    # silencieux, alors que ce passage de main est precisement l'endroit ou une
    # erreur de type couterait une campagne.
    porteuses: list[CompanyPorteuse] = []
    produits: list[ProduitSouscriptible] = []
    # Le rapport CLIENTS est conserve pour etre rendu EN ENTIER : l'orchestrateur
    # n'en garde qu'une ligne, et la table des quotas (`EF-22`, `EF-23`, `EF-24`)
    # est precisement ce qu'un operateur doit lire avant de dire oui (`D-01`).
    rapports_clients: list[RapportClients] = []

    async def _roles() -> RapportEtape:
        return await ExecuteurRoles(mode=mode, user_client=users).executer()

    async def _organisation() -> RapportEtape:
        # La fenetre vient du run, pas d'un recalcul local : elle est FIGEE au
        # lancement (`D-10`). Deux sources auraient pu diverger d'un jour a
        # minuit — un run reproductible ne se permet pas ca.
        rapport = await ex_org.executer(plan, debut, fin)
        porteuses.extend(rapport.porteuses)
        return rapport

    async def _catalogue() -> RapportEtape:
        rapport = await ex_cat.executer()
        produits.extend(rapport.souscriptibles)
        return rapport

    async def _depositaires() -> RapportEtape:
        par_pays: dict[str, list[CompanyPorteuse]] = {}
        for porteuse in porteuses:
            par_pays.setdefault(porteuse.country_code, []).append(porteuse)
        return await ex_dep.executer(plan, par_pays, produits)

    async def _clients() -> RapportEtape:
        """L'etape qui FERME la chaine Faker.

        `FakerClient` et `clients_composition` etaient ecrits, testes, et
        appeles par personne : c'est ici que la chaine termine. Le rapport
        d'essai a blanc annonce desormais ce que le REEL ecrirait — 2000
        clients, leurs comptes CHECKING et leur dotation.
        """
        rapport_clients = await ExecuteurClients(
            run_id=run_id,
            mode=mode,
            configuration=configuration,
            referentiel=referentiel,
            generateur=generateur,
            faker=faker,
            client_service=clients_finaux,
            hierarchie=hierarchie,
            ledger=ledger_faker,
            produits=produits,
        ).executer()
        rapports_clients.append(rapport_clients)
        return rapport_clients

    async def _recette() -> RapportEtape:
        """MODULE 8 — le verdict sur ce que ce run vient de construire.

        `verifier_cr02()`, `kiosques_sans_agent()`, `partiellement_initialises()`
        et `compter_par_type()` etaient ecrits, testes, et appeles NULLE PART.
        `CR-02` — « aucune incoherence geo-organisationnelle apres une generation
        complete » — n'etait donc jamais verifie.

        Pour une demonstration devant Nordic Microfinance, l'IFC, l'AFD et la BAD,
        c'est le defaut le plus couteux : **une generation dont on ne peut rien
        prouver n'est pas une demonstration, c'est une affirmation.**

        Il tourne en DERNIER et il ne fait que LIRE — il peut donc etre relance
        sans rien modifier de ce qu'il mesure.
        """
        return await ControleRecette(
            run_id=run_id, hierarchie=hierarchie, registre=registre, audit=audit
        ).executer()

    async def _staff() -> RapportEtape:
        return await ExecuteurStaff(
            run_id=run_id,
            mode=mode,
            configuration=configuration,
            referentiel=referentiel,
            identity_client=identites,
            user_client=users,
        ).executer()

    tous: dict[Etape, Travail] = {
        Etape.ROLES: _roles,
        Etape.ORGANISATION: _organisation,
        Etape.CATALOGUE: _catalogue,
        Etape.DEPOSITAIRES: _depositaires,
        Etape.STAFF: _staff,
        Etape.CLIENTS: _clients,
        Etape.RECETTE: _recette,
    }
    # Deploiement PAR ETAPE — la seule facon responsable d'aborder des services
    # sans `DELETE`. On passe en reel un module a la fois, en commencant par le
    # seul reversible (`ROLES`), et on verifie avant d'aller plus loin.
    travaux = {e: t for e, t in tous.items() if etapes is None or e in etapes}

    orchestrateur = Orchestrateur(run_id=run_id, mode=mode, travaux=travaux, runs=depot_runs)

    try:
        rapport = await orchestrateur.executer()
    except BaseException:
        # Une exception qui traverse l'orchestrateur laisserait le run `RUNNING`
        # pour toujours — et le verrou `EF-55` bloquerait tous les suivants. Le
        # run est clos en `FAILED` : c'est un etat terminal, et il est VRAI.
        try:
            await depot_runs.changer_statut(run_id, RunStatus.FAILED)
        except Exception:
            # On ne masque JAMAIS l'erreur d'origine : elle est relancee plus bas.
            logging.getLogger(__name__).exception("cloture du run %s impossible", run_id)
        raise
    else:
        # La reconciliation LIT MongoDB : elle doit avoir lieu avant `close()`.
        # Placee apres le `finally`, elle rendait « Client MongoDB non
        # initialise » — le journal d'intention restait muet au moment precis ou
        # il sert.
        reconciliation = await _reconcilier(audit, run_id)
        registre_faker = await _reconcilier_faker(ledger_faker, run_id)
        # Le resume de l'orchestrateur tronque le detail de chaque etape a une
        # ligne — utile pour lire huit modules d'un coup, inutilisable pour un
        # rapport de recette. Il est donc rendu EN ENTIER, parce que c'est lui
        # qui prouve la generation devant un bailleur.
        verdict = await ControleRecette(
            run_id=run_id, hierarchie=hierarchie, registre=registre, audit=audit
        ).executer()
    finally:
        for client in (
            users, companies, comptes, produits_client, depositaires, identites,
            clients_finaux, faker,
        ):
            await client.fermer()
        close()

    print(temps.resume())
    print()
    print(rapport.resume())
    print()
    for rapport_clients in rapports_clients:
        print()
        print(rapport_clients.resume())
    print()
    print(verdict.resume())
    print(reconciliation)
    print(registre_faker)
    return 0 if rapport.statut.value != "FAILED" else 1


async def _reconcilier(audit: AuditTrailRepository, run_id: UUID) -> str:
    """LA BOUCLE D'ATOMICITE, FERMEE — 11/08.

    `audit_trail` porte un journal d'intention write-ahead : on note ce qu'on VA
    ecrire, puis ce qui s'est REELLEMENT passe. Une INTENTION sans RESULTAT est
    **orpheline** : le processus est mort entre les deux, et **on ne sait pas si
    le serveur a ecrit**.

    `intentions_orphelines()` etait ecrit, teste, documente comme « le vrai
    livrable de ce module »... et appele NULLE PART. Le journal d'intention
    detectait donc des orphelines que personne ne lisait — la moitie d'un
    write-ahead log ne vaut rien.

    Sur trois services sans `DELETE`, cette liste est la seule facon de garder
    `OBJ-05` (reversibilite) tenable apres une interruption : elle nomme
    exactement les ecritures a aller verifier a la main.

    Une base injoignable ne doit pas masquer le rapport du run : on le dit et on
    rend la main.
    """
    try:
        orphelines = await audit.intentions_orphelines(run_id)
    except Exception as erreur:  # pragma: no cover — defense d'exploitation
        return f"\nRECONCILIATION IMPOSSIBLE : {type(erreur).__name__} — {erreur}"

    if not orphelines:
        return "\nRECONCILIATION : aucune intention orpheline — le journal est clos."

    lignes = [
        f"\nRECONCILIATION : {len(orphelines)} INTENTION(S) ORPHELINE(S) — a verifier a la main.",
        "  Chacune designe une ecriture dont on IGNORE si le serveur l'a appliquee.",
    ]
    for entree in orphelines[:20]:
        cible = (entree.after or {}).get("cible", "?")
        lignes.append(f"    {entree.entity_type:<12} {entree.entity_id} -> {cible}")
    if len(orphelines) > 20:
        lignes.append(f"    … et {len(orphelines) - 20} autres (journal complet : exporter_run)")
    return "\n".join(lignes)


async def _reconcilier_faker(ledger: FakerLedgerRepository, run_id: UUID) -> str:
    """Le second write-ahead a reconcilier — le registre de consommation Faker.

    Meme forme, meme raison que les intentions orphelines ci-dessus, sur un objet
    different : une RESERVATION qui survit a la fin du run dit qu'un client Faker
    a ete revendique sans rien produire.

    Deux causes, et il faut les distinguer a la main :

      - un worker est mort entre la reservation et la creation. Le client est
        perdu pour `D-FAKER-1`, mais rien d'irreversible n'a ete ecrit ;
      - un chemin de code oublie d'appeler `confirmer()`. Alors une entite
        IRREVERSIBLE existe sans que le registre la relie a son client Faker, et
        c'est le cas grave.

    Ecrire `reserver()` sans lire ce rapport, ce serait refaire exactement le
    defaut que ce module vient de corriger : la moitie d'un write-ahead log ne
    vaut rien.
    """
    try:
        orphelines = await ledger.reservations_orphelines(run_id)
        par_pays = await ledger.compter_par_pays(run_id)
    except Exception as erreur:  # pragma: no cover — defense d'exploitation
        return f"\nREGISTRE FAKER : reconciliation impossible — {type(erreur).__name__} : {erreur}"

    total = sum(par_pays.values())
    lignes = [f"\nREGISTRE FAKER : {total} client(s) consomme(s) sur ce run."]
    if par_pays:
        # `OBJ-01` exige les 4 pays. `SN` restera absent tant que ses clients
        # viennent du generateur interne (Faker rend 422 — arbitrage `A-01`), et
        # cette absence doit se VOIR plutot que se deviner.
        detail = " · ".join(f"{pays} {n}" for pays, n in sorted(par_pays.items()))
        lignes.append(f"  Repartition : {detail}")
        for pays in PAYS_CIBLES:
            if pays not in par_pays:
                lignes.append(f"  ⚠ {pays} : aucun client consomme chez Faker sur ce run.")

    if not orphelines:
        lignes.append("  Aucune reservation orpheline — le registre est clos.")
        return "\n".join(lignes)

    lignes.append(
        f"  ⚠ {len(orphelines)} RESERVATION(S) ORPHELINE(S) — client revendique, rien produit."
    )
    for entree in orphelines[:20]:
        lignes.append(
            f"    {entree.id:<24} {entree.country_code} {entree.consumed_for.value:<14}"
            f" seed={entree.seed}"
        )
    if len(orphelines) > 20:
        lignes.append(f"    … et {len(orphelines) - 20} autres.")
    lignes.append(
        "  Si une entite existe pour l'une d'elles, `confirmer()` a ete oublie : "
        "l'entite est irreversible et son origine Faker n'est pas tracee."
    )
    return "\n".join(lignes)


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
    parser.add_argument(
        "--ignorer-verrou",
        action="store_true",
        help="Passe outre le verrou EF-55. Reserve au cas d'un run interrompu "
        "reste RUNNING — jamais a deux executions volontairement simultanees.",
    )
    args = parser.parse_args()
    choisies = {Etape(n.strip().upper()) for n in args.etapes.split(",") if n.strip()} or None
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s : %(message)s")
    return asyncio.run(
        executer(
            RunMode.REAL if args.reel else RunMode.DRY_RUN,
            choisies,
            ignorer_verrou=args.ignorer_verrou,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
