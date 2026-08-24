"""
app/services/pilotage.py
========================
LE MOTEUR d'execution d'un run — extrait de `scripts/executer_run.py` le 13/08
pour que le CLI et l'API Super-Admin (lot B) partagent UN SEUL moteur, jamais
deux copies qui divergeraient.

Trois parametrages, et rien d'autre n'a change :

  `run_id`           l'API le pre-alloue pour repondre immediatement ;
  `configuration`    None = l'INTENTION persistee du Super-Admin (US-B2),
                     qui retombe sur le CDC sans document ;
  `sortie`           le rapport va a la console (CLI) ou dans un tampon que
                     l'API range avec le run ;
  `gerer_connexion`  le CLI possede sa connexion Mongo, l'API la partage.

La SURCOUCHE referentielle persistee (US-B4) est appliquee au chargement :
une ville ajoutee par l'API participe au run suivant, exactement comme
l'ecran l'annonce.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.clients.account_service import AccountServiceClient
from app.clients.client_service import ClientServiceClient
from app.clients.company_service import CompanyServiceClient
from app.clients.contracts import ProductType
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
from app.repositories.configuration import ConfigurationRepository
from app.repositories.surcouche import SurcoucheRepository
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
from app.services.referentiel_statique import charger_statique, referentiel_effectif
from app.services.roles_execution import ExecuteurRoles
from app.services.staff_execution import ExecuteurStaff

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
LOAN_JSON = Path("docs/reference/loan_json.json")


@dataclass(slots=True)
class ClientsHTTP:
    """Les huit surfaces HTTP du moteur — INJECTABLES (audit AU-5).

    Le defaut (fabrique reelle) est celui de la production ; les tests
    d'assemblage injectent des doubles et prouvent le moteur ENTIER a vide,
    ce que seuls les DRY_RUN manuels prouvaient jusqu'ici."""

    users: Any
    faker: Any
    clients: Any
    companies: Any
    comptes: Any
    produits: Any
    depositaires: Any
    identites: Any

    @classmethod
    def reels(cls) -> ClientsHTTP:
        return cls(
            users=UserServiceClient(),
            # Faker est en LECTURE SEULE et sans authentification : il n'entre
            # pas dans la session ROOT partagee des neuf services FinZuu.
            faker=FakerClient(),
            clients=ClientServiceClient(),
            companies=CompanyServiceClient(),
            comptes=AccountServiceClient(),
            produits=ProductServiceClient(),
            depositaires=DepositaryServiceClient(),
            identites=IdentityServiceClient(),
        )


async def executer(
    mode: RunMode,
    etapes: set[Etape] | None = None,
    ignorer_verrou: bool = False,
    *,
    run_id: UUID | None = None,
    configuration: ConfigurationExecution | None = None,
    sortie: Callable[[str], None] = print,
    gerer_connexion: bool = True,
    clients_http: ClientsHTTP | None = None,
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
    if gerer_connexion:
        # Le CLI possede sa connexion ; sous l'API, le cycle de vie FastAPI la
        # possede deja — fermer le client partage tuerait l'application.
        connect()
        await ensure_indexes()
    run_id = run_id or uuid4()
    referentiel = charger_referentiel(CLASSEUR)
    # `SD-1` — le catalogue de JJB, charge AVANT toute ecriture. Un referentiel
    # incoherent doit interrompre le lancement, jamais laisser partir 20 Companies
    # avec des secteurs disparus sur un service sans `DELETE`.
    statique = charger_statique()
    # `US-B2` / `US-B4` (13/08) — le run execute l'INTENTION persistee du
    # Super-Admin : la configuration courante et la surcouche referentielle.
    # Sans document en base, les deux retombent sur le CDC et le classeur —
    # l'etat initial est le contrat, pas un cas d'erreur. C'est ce qui rend
    # vrais les criteres Gherkin « le DRY_RUN suivant annonce 1000 clients »
    # et « l'ecran voit le referentiel que le prochain run utilisera ».
    if configuration is None:
        configuration, _meta = await ConfigurationRepository().charger()
    surcouche, _meta_surcouche = await SurcoucheRepository().charger()
    if not surcouche.vide:
        referentiel = surcouche.appliquer(referentiel)
        sortie(surcouche.resume())
    # `US-B5+` — le referentiel EFFECTIF : la base FUSIONNEE avec les secteurs et
    # industries ajoutes. C'est LUI que le generateur consomme (plus la base
    # seule) — sinon un secteur ajoute reste invisible au run et
    # `industrie_du_secteur` leverait dessus. Les secteurs DECLARES connexes pour
    # un type d'entreprise entrent dans le tirage (`connexes_sup`).
    statique = referentiel_effectif(
        statique,
        secteurs_ajoutes=dict(surcouche.secteurs),
        industries_ajoutees=list(surcouche.industries_ajoutees),
    )
    connexes_sup = surcouche.connexes_par_type()

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
            sortie(
                f"REFUS (EF-55) — le run {en_cours.id} est {en_cours.status.value}.\n"
                f"  Deux generations simultanees sont interdites.\n"
                f"  S'il s'agit d'un run interrompu, relancer avec --ignorer-verrou :\n"
                f"  il sera clos en FAILED, jamais laisse en suspens."
            )
            if gerer_connexion:
                close()
            return 2
        if en_cours.status is RunStatus.RUNNING:
            await depot_runs.changer_statut(en_cours.id, RunStatus.FAILED)
            sortie(f"VERROU LIBERE — run {en_cours.id} clos en FAILED (etait RUNNING).")

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

    # AU-5 — les clients viennent du paquet injectable ; None = la production.
    paquet = clients_http or ClientsHTTP.reels()
    users = paquet.users
    faker = paquet.faker
    clients_finaux = paquet.clients
    companies = paquet.companies
    comptes = paquet.comptes
    produits_client = paquet.produits
    depositaires = paquet.depositaires
    identites = paquet.identites

    # `INV-USR-02` EST GLOBAL, PAS LOCAL AU RUN — la lecon du 21/08.
    #
    # Le premier run REAL est mort d'avoir regenere `mbarga.mbarga@...`, une
    # adresse posee par un chargement ANTERIEUR au registre : le generateur ne
    # garantissait l'unicite des emails qu'en memoire du run. On seme donc ici,
    # avant toute emission, la totalite des adresses deja prises sur
    # user-service — une seule lecture, et owners, staff comme clients heritent
    # du meme suffixe deterministe en cas de collision. Lecture faite AUSSI en
    # DRY_RUN : un essai a blanc qui n'exerce pas les memes dependances que le
    # reel n'est pas un essai a blanc (regle du 09/08) — et son rapport doit
    # annoncer les adresses que le REAL emettra vraiment.
    generateur.reserver_emails(await users.lister_emails())

    audit = AuditTrailRepository()
    registre = LendersRegistryRepository()
    hierarchie = OrgHierarchyRepository()

    ex_org = ExecuteurOrganisation(
        run_id=run_id,
        mode=mode,
        referentiel=referentiel,
        statique=statique,
        generateur=generateur,
        company_client=companies,
        user_client=users,
        account_client=comptes,
        registre_lenders=registre,
        audit=audit,
        connexes_sup=connexes_sup,
    )
    ex_cat = ExecuteurCatalogue(
        run_id=run_id,
        mode=mode,
        product_client=produits_client,
        audit=audit,
        chemin_loan_json=LOAN_JSON,
        # `CAT 9` — le perimetre vient de la configuration, figee D-10.
        perimetre_lending=configuration.perimetre_lending,
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
    #: `A-12` — la carte des rattachements, remplie par CATALOGUE, consommee
    #: par CLIENTS (le panier de SA Company).
    produits_par_company: dict[UUID, set[UUID]] = {}
    # Le rapport CLIENTS est conserve pour etre rendu EN ENTIER : l'orchestrateur
    # n'en garde qu'une ligne, et la table des quotas (`EF-22`, `EF-23`, `EF-24`)
    # est precisement ce qu'un operateur doit lire avant de dire oui (`D-01`).
    rapports_clients: list[RapportClients] = []

    async def _roles() -> RapportEtape:
        return await ExecuteurRoles(
            mode=mode, user_client=users, audit=audit, run_id=run_id
        ).executer()

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
        # `CAT 7` / `A-12` — le rattachement Produit -> Company (UC-11 pt 3).
        # ZERO produit supplementaire : des LIENS dans NOTRE org_hierarchy,
        # un par (produit COLLECT x IMF porteuse). Les porteuses ont le
        # package ALL, qui autorise la collecte. En DRY_RUN la carte vit en
        # memoire (le panier s'exerce a blanc comme en reel — D-01) ; en REEL
        # les noeuds sont persistes et CR-02 les verifie.
        for porteuse in porteuses:
            for produit in rapport.souscriptibles:
                if produit.type_produit is not ProductType.COLLECT:
                    continue
                produits_par_company.setdefault(porteuse.company_id, set()).add(produit.product_id)
                if mode is RunMode.REAL:
                    await hierarchie.ajouter_produit(
                        run_id=run_id,
                        company_id=porteuse.company_id,
                        product_id=produit.product_id,
                        marqueur=produit.nom,
                        package="ALL",
                        country_code=porteuse.country_code,
                    )
        if produits_par_company:
            liens = sum(len(v) for v in produits_par_company.values())
            sortie(
                f"Rattachements A-12 : {liens} lien(s) produit x company "
                f"({len(produits_par_company)} porteuse(s)) — des LIENS chez "
                "nous, zero produit supplementaire"
            )
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
            statique=statique,
            produits_par_company=produits_par_company or None,
            generateur=generateur,
            faker=faker,
            client_service=clients_finaux,
            account_service=comptes,
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
            run_id=run_id,
            hierarchie=hierarchie,
            registre=registre,
            audit=audit,
            perimetre_lending=configuration.perimetre_lending,
            rapport_geo=referentiel.rapport,
        ).executer()

    async def _staff() -> RapportEtape:
        return await ExecuteurStaff(
            run_id=run_id,
            mode=mode,
            configuration=configuration,
            referentiel=referentiel,
            identity_client=identites,
            user_client=users,
            # `UC-09` — le Staff tourne APRES les Depositaires : l'arbre porte
            # les Kiosques reels sur lesquels compter et affilier ses Agents.
            arbre=hierarchie,
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
            run_id=run_id,
            hierarchie=hierarchie,
            registre=registre,
            audit=audit,
            perimetre_lending=configuration.perimetre_lending,
            rapport_geo=referentiel.rapport,
        ).executer()
        # `US-E3` — les mesures structurees partent avec le run, comme le
        # rapport texte : le dashboard les sert sans requeter FinZuu.
        mesures = _mesures_population(rapports_clients)
        if mesures:
            await depot_runs.attacher_mesures(run_id, mesures)
    finally:
        for client in (
            users,
            companies,
            comptes,
            produits_client,
            depositaires,
            identites,
            clients_finaux,
            faker,
        ):
            await client.fermer()
        if gerer_connexion:
            close()

    sortie(temps.resume())
    sortie("")
    sortie(rapport.resume())
    sortie("")
    for rapport_clients in rapports_clients:
        sortie("")
        sortie(rapport_clients.resume())
    sortie("")
    sortie(verdict.resume())
    sortie(reconciliation)
    sortie(registre_faker)
    return 0 if rapport.statut.value != "FAILED" else 1


def _mesures_population(rapports: list[RapportClients]) -> dict[str, Any]:
    """`US-E3` — l'agregat structure des mesures de population.

    MESURE ET CIBLE COTE A COTE, jamais l'une sans l'autre : c'est le critere
    Gherkin de la story, et c'est ce qui permet a l'ecran de colorer un ecart
    sans refaire le calcul du CDC.
    """
    if not rapports:
        return {}
    quotas: list[dict[str, Any]] = []
    occupations: dict[str, int] = {}
    tranches: dict[str, int] = {}
    etrangers = 0
    solde_total = 0.0
    for rapport in rapports:
        for q in rapport.quotas:
            quotas.append(
                {
                    "pays": q.pays,
                    "clients": {"mesure": q.faits, "cible": q.cible},
                    "corporate": {"mesure": q.corporate_faits, "cible": q.cible_corporate},
                    "femmes": {"mesure": q.femmes, "cible": q.cible_femmes},
                    "jeunes": {"mesure": q.jeunes, "cible": q.cible_jeunes},
                    "agricoles": {"mesure": q.agricoles, "cible": q.cible_agricoles},
                    "profils": {
                        nom: {"mesure": q.profils_faits.get(nom, 0), "cible": cible}
                        for nom, cible in q.cible_profils.items()
                    },
                }
            )
        for nom, n in rapport.occupations.items():
            occupations[nom] = occupations.get(nom, 0) + n
        for nom, n in rapport.soldes_tranches.items():
            tranches[nom] = tranches.get(nom, 0) + n
        etrangers += rapport.nes_a_l_etranger
        solde_total += rapport.solde_dote
    total = sum(occupations.values())
    return {
        "quotas_par_pays": quotas,
        "occupations": {
            "distinctes": len(occupations),
            "total": total,
            "top": dict(sorted(occupations.items(), key=lambda kv: -kv[1])[:30]),
        },
        "soldes": {"tranches": tranches, "total_dote": round(solde_total, 2)},
        "naissances": {
            "a_l_etranger": etrangers,
            "au_pays": max(total - etrangers, 0),
        },
    }


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
