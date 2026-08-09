"""
app/services/organisation_execution.py
======================================
Execution du module Organisation — UC-07, UC-08, UC-10.

**Le Loader anticipe les anomalies, il ne les subit pas — et il ne les repare
jamais.** Corriger un bug serveur n'est pas son role ; c'est celui de l'equipe
qui tient le service. Le Loader neutralise l'effet chez lui, journalise, et
poursuit. Cette distinction est ce qui le garde dans son cadre.

Les anomalies anticipees ici, une par une :

  ANO-CPY-BUG-06   La creation d'une Company peut echouer en HTTP 400
                   (`'NoneType' object has no attribute 'email'`). On ne rejoue
                   PAS — un 4xx signale notre payload, le rejouer le repeterait.
                   On journalise et on passe a la Company suivante, exactement
                   comme UC-07 le prescrit : « le Loader journalise l'erreur et
                   poursuit avec la Company suivante ». D'ou PARTIAL, etat
                   terminal LEGITIME et non un echec.
  FRA-199          `currency` est perdue a la persistance — le Loader garde sa
                   propre trace, dans le rapport et dans `lenders_registry`.
  D-CMP-2          Corrige le 08/08 par mesure directe : creer une Company
                   cascade vers TROIS services — identity, account ET user.
                   Mais le User cascade est inutilisable (mot de passe
                   inconnu, company_id vide, `identity` pointant vers la
                   Company). Le Loader cree donc son propre Admin.
  admin_email      Ne cree RIEN. Le User cascade porte `owner.email`.
                   Verifie deux fois, y compris en differe.
  owner._id        Exige au contrat mais IGNORE : le serveur genere le sien.
                   Toujours relire l'identifiant RENDU.
  INV-CPY-01       GET-avant-POST par `short_name`.
  Aucun DELETE     Ni sur account-service, ni sur company-service. D'ou le mode
                   DRY_RUN, qui deroule toute la chaine sans rien ecrire.
  ANO-CPY-LEAK-07  Les messages d'erreur fuient des traces Python — on les
                   tronque avant de les journaliser, jamais on ne les parse.

**Perimetre strict** : Companies, Licences, Admin Users, Lenders et leurs
comptes. Ni produits, ni depositaires, ni clients — ils ont leurs propres etapes.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from app.clients.account_service import AccountServiceClient
from app.clients.base import ErreurService
from app.clients.company_service import CompanyServiceClient
from app.clients.contracts import CompanyType, PackageName, UserType
from app.clients.user_service import UserServiceClient
from app.core.cdc import (
    COMPTES_LENDER,
    LENDERS_INSTITUTIONNELS,
    LENDERS_LOCAUX_PAR_PAYS,
    LICENCE_MARGE_FUTURE_JOURS,
)
from app.models.enums import LenderType, RunMode, RunStatus
from app.repositories import AuditTrailRepository, LendersRegistryRepository
from app.services.generateur import Generateur
from app.services.generateur import patronyme as _patronyme_bouchon
from app.services.geographie import ReferentielGeo
from app.services.organisation import PlanOrganisation

logger = logging.getLogger(__name__)

# SOURCE UNIQUE DES PATRONYMES — `app/services/generateur.py`.
#
# Cette table vivait ici en double de celle de l'executeur Staff. Deux tables
# paralleles divergent toujours : celle-ci se serait enrichie sans l'autre.
# L'alias conserve le nom local (« bouchon ») qui dit ce que c'est vraiment —
# de la matiere Faker REJOUEE, en attendant son client.


@dataclass(slots=True)
class RapportOrganisation:
    """Ce que l'execution a reellement produit, et ce qu'elle a rate.

    Le rapport distingue toujours le **prevu** du **realise** : c'est lui qui
    permet de decider entre COMPLETED et PARTIAL sans deviner.
    """

    mode: RunMode
    companies_creees: list[str] = field(default_factory=list)
    companies_echouees: list[tuple[str, str]] = field(default_factory=list)
    licences_creees: list[str] = field(default_factory=list)
    admins_crees: list[str] = field(default_factory=list)
    admins_echoues: list[tuple[str, str]] = field(default_factory=list)
    lenders_enregistres: list[str] = field(default_factory=list)
    comptes_crees: int = 0
    comptes_echoues: list[tuple[str, str]] = field(default_factory=list)
    cascades_identity_verifiees: int = 0
    cascades_identity_manquantes: list[str] = field(default_factory=list)

    @property
    def statut(self) -> RunStatus:
        """PARTIAL est un etat terminal LEGITIME (UC-07/UC-08, cas alternatif).

        FAILED est reserve au cas ou rien n'a abouti : c'est alors un probleme
        systemique, pas une entite recalcitrante.
        """
        echecs = (
            self.companies_echouees
            + self.admins_echoues
            + self.comptes_echoues
            + [(x, "cascade Identity absente") for x in self.cascades_identity_manquantes]
        )
        if not echecs:
            return RunStatus.COMPLETED
        if not self.companies_creees:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    def resume(self) -> str:
        lignes = [
            f"Mode : {self.mode.value}",
            f"Companies  : {len(self.companies_creees)} creees, "
            f"{len(self.companies_echouees)} en echec",
            f"Licences   : {len(self.licences_creees)}",
            f"Admin Users: {len(self.admins_crees)} crees, {len(self.admins_echoues)} en echec",
            f"Lenders    : {len(self.lenders_enregistres)} enregistres",
            f"Comptes    : {self.comptes_crees} crees, {len(self.comptes_echoues)} en echec",
            f"Cascade Identity verifiee : {self.cascades_identity_verifiees}",
            f"STATUT : {self.statut.value}",
        ]
        for nom, motif in self.companies_echouees + self.admins_echoues + self.comptes_echoues:
            lignes.append(f"  ECHEC {nom} : {motif}")
        return "\n".join(lignes)


class ExecuteurOrganisation:
    """Deroule UC-07, UC-08 et UC-10 a partir d'un plan deja verifie.

    `DRY_RUN` n'emet aucune **ECRITURE**. Les LECTURES sont conservees, et c'est
    volontaire : elles rendent le rapport exact en revelant ce qui existe deja et
    serait donc saute. Un dry-run aveugle annoncerait des creations qui
    n'auraient jamais lieu.

    C'est la seule facon responsable d'aborder des services qui n'exposent aucun
    DELETE : on voit tout ce qui serait ecrit avant que quoi que ce soit le soit.
    """

    def __init__(
        self,
        *,
        run_id: UUID,
        mode: RunMode,
        referentiel: ReferentielGeo,
        generateur: Generateur,
        company_client: CompanyServiceClient,
        user_client: UserServiceClient,
        account_client: AccountServiceClient,
        registre_lenders: LendersRegistryRepository,
        audit: AuditTrailRepository,
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self._referentiel = referentiel
        self._generateur = generateur
        self._companies = company_client
        self._users = user_client
        self._comptes = account_client
        self._registre = registre_lenders
        self._audit = audit

    @property
    def ecriture_reelle(self) -> bool:
        return self.mode is RunMode.REAL

    # ----------------------------------------------------------------------
    # Coherence territoriale — croisement avec le Sprint 1
    # ----------------------------------------------------------------------

    def _telephone_du_pays(self, pays: str, index: int) -> str:
        """Numero du dirigeant, **conforme au plan de numerotation du pays**.

        Corrige un defaut reel de la premiere version : `f"+237{600000000 +
        index}"` codait l'indicatif camerounais en dur **pour les quatre
        pays** — une Company senegalaise recevait un numero camerounais. Et
        `600000001` n'etait meme pas valide au Cameroun : aucun operateur n'y
        utilise le prefixe `60` (ils emploient 62, 65, 67, 68, 69).

        Le referentiel porte les 12 plans reels et les parts de marche
        (`EF-27`, Sprint 1). On les utilise, avec un tirage derive du `run_id`
        pour rester reproductible (`ENF-15`).
        """
        alea = random.Random(f"{self.run_id}-telephone-{pays}-{index}")  # noqa: S311
        numero, _ = self._referentiel.composer_msisdn(pays, f"{index:08d}", alea)
        return f"+{numero}"

    def _devise_du_pays(self, pays: str) -> str:
        """La devise vient du referentiel, jamais d'une table codee en dur.

        `XAF` est la zone CEMAC (Cameroun), `XOF` la zone UEMOA (Cote
        d'Ivoire, Burkina Faso, Senegal). `FRA-199` fait perdre `currency` a la
        persistance — raison de plus pour que **notre** trace soit juste.
        """
        devise = self._referentiel.devise_du_pays(pays)
        if devise is None:
            raise ValueError(f"aucune devise rattachee au pays {pays!r} dans le referentiel")
        return devise.code

    # ----------------------------------------------------------------------
    # UC-07 — Companies et licences
    # ----------------------------------------------------------------------

    async def creer_company(
        self,
        *,
        pays: str,
        patronyme: str,
        forme_juridique: str,
        secteur: str,
        type_company: CompanyType,
        region: str,
        ville: str,
        quartier: str,
        telephone: str,
        rapport: RapportOrganisation,
    ) -> dict[str, Any] | None:
        """Cree une Company, sa licence et son Admin User.

        Renvoie None si la creation echoue — l'appelant poursuit avec la
        suivante, conformement a UC-07.
        """
        raison = self._generateur.raison_sociale(patronyme, forme_juridique, secteur, pays)
        court = self._generateur.nom_court(raison)

        # INV-CPY-01 — GET-avant-POST. Une Company deja presente n'est jamais
        # recreee : company-service n'expose aucun DELETE.
        existante = await self._companies.chercher_par_short_name(court)
        if existante is not None:
            logger.info("Company %s deja presente, reutilisee", court)
            return existante

        ville_ref = next((v for v in self._referentiel.villes.values() if v.name == ville), None)
        adresse = self._generateur.adresse(
            quartier,
            ville,
            region,
            pays,
            ville_ref.latitude if ville_ref else None,
            ville_ref.longitude if ville_ref else None,
        )
        owner = self._generateur.identite(
            first_name=patronyme,
            last_name=patronyme,
            gender="MALE",
            country_code=pays,
            ville=ville,
            region=region,
            quartier=quartier,
            telephone=telephone,
            jeune=False,
            occupation="Dirigeant",
            latitude=adresse.latitude,
            longitude=adresse.longitude,
        )
        devise = self._devise_du_pays(pays)

        if not self.ecriture_reelle:
            rapport.companies_creees.append(raison)
            # L'Admin User serait cree juste apres, en 3 requetes — on l'annonce
            # pour que le rapport de dry-run soit complet.
            rapport.admins_crees.append(owner.email)
            logger.info("[DRY_RUN] Company %s (%s, %s) — payload valide", raison, pays, devise)
            return {"_id": str(uuid4()), "name": raison, "short_name": court, "_dry_run": True}

        try:
            company = await self._companies.creer_company(
                name=raison,
                short_name=court,
                type_company=type_company,
                owner=owner,
                adresse=adresse,
                admin_email=owner.email,
                currency=devise,
                industries=[secteur],
                sectors=[secteur],
            )
        except ErreurService as exc:
            # ANO-CPY-BUG-06 et consorts : on journalise et on poursuit.
            # Le detail serveur est tronque — il fuit des traces Python.
            motif = f"HTTP {exc.status} : {exc.detail[:160]}"
            rapport.companies_echouees.append((raison, motif))
            logger.warning("Company %s en echec, poursuite : %s", raison, motif)
            return None

        company_id = self._companies.identifiant(company)
        if company_id is None:
            rapport.companies_echouees.append((raison, "reponse sans identifiant"))
            return None

        rapport.companies_creees.append(raison)

        # D-CMP-2 verifie APRES coup, jamais presume.
        if self._companies.identifiant_owner(company):
            rapport.cascades_identity_verifiees += 1
        else:
            rapport.cascades_identity_manquantes.append(raison)

        await self._audit.journaliser(
            run_id=self.run_id,
            entity_type="Company",
            entity_id=UUID(company_id),
            action="CREATE",
            after={"name": raison, "short_name": court, "currency": devise, "pays": pays},
        )

        # L'Identity reelle est celle que le SERVEUR a generee, pas celle que
        # nous avons envoyee : `owner._id` est exige au contrat mais IGNORE —
        # mesure du 08/08, l'UUID envoye n'est jamais celui rendu.
        identity_reelle = self._companies.identifiant_owner(company) or str(owner.identity_id)

        # L'adresse de l'Admin doit differer de `owner.email` : la cascade a
        # deja cree un User portant l'email de l'owner, et `INV-USR-02` impose
        # l'unicite. Reutiliser la meme adresse produirait un HTTP 400.
        await self._creer_admin(
            company_id, court, UUID(identity_reelle), f"admin.{owner.email}", rapport
        )
        return company

    async def _creer_admin(
        self,
        company_id: str,
        short_name: str,
        identity_id: UUID,
        email: str,
        rapport: RapportOrganisation,
    ) -> None:
        """Cree l'Admin User de la Company — explicitement, en 3 requetes.

        **Pourquoi cette etape reste indispensable alors qu'une cascade existe.**
        Mesure du 08/08 : creer une Company cascade vers TROIS services —
        identity (+1), account (+1) et **user (+1)**. Un User EST donc cree.
        Mais il est inutilisable :

          - il porte `owner.email`, jamais `admin_email` (qui ne sert a rien)
          - son nom est auto-genere (`user-<hex>`), donc imprevisible
          - **nous ne connaissons pas son mot de passe** — il reste bloque a
            `is_first_login=true`, incapable de se connecter
          - son `company_id` est VIDE : il n'est pas rattache a sa Company
          - son champ `identity` pointe vers la **Company**, pas vers l'Identity
            (defaut referentiel, 6 cas sur 6 cote company-service)

        Le Loader cree donc son PROPRE Admin, dont il maitrise le mot de passe
        et le rattachement.
        """
        initial = self._generateur.mot_de_passe_initial()
        durable = self._generateur.mot_de_passe_initial()
        try:
            await self._users.creer_utilisateur_applicatif(
                user_name=short_name,
                email=email,
                mot_de_passe_initial=initial,
                nouveau_mot_de_passe=durable,
                identity_id=identity_id,
                type_user=self.TYPE_ADMIN,
                groupes=["COMPANY"],
                company_id=company_id,
            )
        except ErreurService as exc:
            rapport.admins_echoues.append((short_name, f"HTTP {exc.status} : {exc.detail[:160]}"))
            return
        rapport.admins_crees.append(email)

    async def creer_licence(
        self,
        company_id: str,
        packages: list[PackageName],
        sim_start: Any,
        sim_end: Any,
        rapport: RapportOrganisation,
    ) -> None:
        """UC-07 — validite couvrant « 180 jours plus 30 jours a venir »."""
        debut = sim_start.isoformat()
        fin = (sim_end + timedelta(days=LICENCE_MARGE_FUTURE_JOURS)).isoformat()

        if not self.ecriture_reelle:
            rapport.licences_creees.append(f"{company_id} [{debut} -> {fin}]")
            return

        if await self._companies.a_une_licence(company_id):
            return
        try:
            await self._companies.creer_licence(company_id, packages, debut, fin)
            rapport.licences_creees.append(company_id)
        except ErreurService as exc:
            rapport.companies_echouees.append((f"licence {company_id}", exc.detail[:160]))

    # ----------------------------------------------------------------------
    # UC-08 et UC-10 — Lenders et leurs 4 comptes
    # ----------------------------------------------------------------------

    async def enregistrer_lender(
        self,
        *,
        company_id: str,
        nom: str,
        lender_type: LenderType,
        pays: str,
        rapport: RapportOrganisation,
    ) -> None:
        """UC-10 — cree les 4 comptes puis inscrit le role au registre.

        Un Lender partiellement initialise est un etat LEGITIME (UC-10, cas
        d'exception) : on inscrit ce qui existe, on signale ce qui manque.
        """
        devise = self._devise_du_pays(pays)
        payloads = self._comptes.payloads_des_4_comptes_lender(company_id, nom, devise)
        comptes: dict[str, UUID] = {}

        if not self.ecriture_reelle:
            rapport.comptes_crees += len(payloads)
            rapport.lenders_enregistres.append(f"{nom} [{lender_type.value}]")
            logger.info("[DRY_RUN] %s — %d comptes prets : %s", nom, len(payloads), COMPTES_LENDER)
            return

        # Aucun DELETE sur account-service : on ne recree jamais un compte
        # existant. GET-avant-POST strict.
        deja = self._comptes.types_presents(await self._comptes.comptes_du_proprietaire(company_id))

        for role, payload in payloads.items():
            if str(payload["type"]) in deja:
                continue
            try:
                cree = await self._comptes.creer_compte(payload)
            except ErreurService as exc:
                rapport.comptes_echoues.append((f"{nom}/{role}", exc.detail[:160]))
                continue
            identifiant = self._comptes.identifiant(cree)
            if identifiant:
                comptes[role] = UUID(identifiant)
                rapport.comptes_crees += 1

        entree = await self._registre.enregistrer(
            company_id=UUID(company_id),
            lender_type=lender_type,
            country_code=pays,
            comptes=comptes,
        )
        if entree is None:
            logger.info("Lender %s deja inscrit au registre, aucune duplication", nom)
            return

        rapport.lenders_enregistres.append(nom)
        await self._audit.journaliser(
            run_id=self.run_id,
            entity_type="Lender",
            entity_id=entree.id,
            action="CREATE",
            after={"nom": nom, "type": lender_type.value, "comptes": sorted(comptes)},
        )

    # ----------------------------------------------------------------------
    # Orchestration
    # ----------------------------------------------------------------------

    async def executer(
        self,
        plan: PlanOrganisation,
        sim_start: Any,
        sim_end: Any,
        source_patronymes: Callable[[str, int], str] | None = None,
    ) -> RapportOrganisation:
        """Deroule le plan. Une entite en echec n'interrompt jamais le run.

        `source_patronymes(pays, index) -> patronyme` est la **couture avec
        Faker**. Les patronymes reels (Kouassi, Kabore, Tamadou...) viennent des
        clients Business de Faker ; tant que ce client n'est pas ecrit, un
        bouchon fournit des valeurs distinctes PAR PAYS.

        Pourquoi cette couture existe : un premier dry-run a montre qu'un
        patronyme indexe sans le pays produisait la MEME raison sociale dans les
        4 pays — ce qui violerait l'unicite de `short_name` (INV-CPY-01) et se
        verrait immediatement en demonstration.
        """
        rapport = RapportOrganisation(mode=self.mode)
        if not plan.realisable:
            for motif in plan.blocages:
                rapport.companies_echouees.append(("plan", motif))
            return rapport

        for plan_pays in plan.pays:
            pays = plan_pays.country_code
            for index in range(plan_pays.nb_companies):
                region = self._referentiel.regions_du_pays(pays)[index % 10]
                villes = self._referentiel.villes_porteuses_de_quartiers(pays)
                ville = villes[index % len(villes)]
                quartiers = self._referentiel.quartiers_de_ville(ville.city_id)
                quartier = quartiers[index % len(quartiers)].name

                est_imf = index < plan_pays.nb_imf
                patronyme = (
                    source_patronymes(pays, index)
                    if source_patronymes
                    else _patronyme_bouchon(pays, index)
                )
                company = await self.creer_company(
                    pays=pays,
                    patronyme=patronyme,
                    forme_juridique="SARL" if est_imf else "SA",
                    secteur="MicroFinance" if est_imf else "Commerce",
                    type_company=CompanyType.IMF if est_imf else CompanyType.BANK,
                    region=region.name,
                    ville=ville.name,
                    quartier=quartier,
                    telephone=self._telephone_du_pays(pays, index),
                    rapport=rapport,
                )
                if company is None:
                    continue

                company_id = self._companies.identifiant(company)
                if company_id:
                    await self.creer_licence(
                        company_id, [PackageName.ALL], sim_start, sim_end, rapport
                    )
                    if index < LENDERS_LOCAUX_PAR_PAYS:
                        await self.enregistrer_lender(
                            company_id=company_id,
                            nom=str(company.get("name", "")),
                            lender_type=LenderType.LOCAL,
                            pays=pays,
                            rapport=rapport,
                        )

        # UC-08 — les 4 institutionnels, noms fixes, jamais issus de Faker.
        for nom_institutionnel in LENDERS_INSTITUTIONNELS:
            rapport.lenders_enregistres.append(f"{nom_institutionnel} [INSTITUTIONNEL, prevu]")

        return rapport

    # Le type_user des Admin Users est expose ici pour que l'appelant n'ait pas
    # a connaitre l'enum serveur : un Admin de Company est de type COMPANY.
    TYPE_ADMIN: UserType = UserType.COMPANY
