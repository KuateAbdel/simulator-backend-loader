"""
app/services/depositaires_execution.py
======================================
Execution du module Depositaires — UC-09, et la verification de recette CR-02.

Un Kiosque est la seule entite du Loader qui vit **a cheval sur deux mondes** :

  - cote serveur, un Depositaire : `name`, `currency`, `company_id`. Rien d'autre.
  - cote Loader, un noeud d'`org_hierarchy` qui porte le quartier, la ville, la
    region et la Branche — parce que `CreateDepositaireSchema` **n'a aucun champ
    geographique** (decision D-05).

Si nous n'ecrivions pas les deux, l'implantation geographique n'existerait
nulle part : ni dans le serveur qui l'ignore, ni chez nous. C'est exactement ce
que CR-02 verifie — « chaque Kiosque a un District valide, chaque Agence une
Ville valide ». **Le NOM du Kiosque est le seul endroit ou le quartier devient
visible dans l'interface** : `DEMO_Kiosque Bonapriso`. C'est pourquoi il n'est
pas decoratif.

Les faits mesures le 08/08 qui gouvernent cet ordre d'operations :

  D-DEP-1  Creer d'abord, souscrire ENSUITE. La creation seule ne cree **aucun
           compte** (+0), et le Depositaire nait **actif** : aucun `PATCH
           status/true` n'est necessaire.
  D-DEP-2  Les 6 comptes naissent a la **premiere** souscription, par Depositaire
           et non par produit : 1re souscription -> +6, 2e -> **+0**. D'ou
           `comptes_attendus`, qui compte 6 par Kiosque **souscrit**, jamais 6
           par souscription.
  D-DEP-3  Aucune unicite de nom serveur, et **aucun DELETE** : GET-avant-POST
           sur le nom, sinon un second run duplique tout l'ecosysteme sans
           aucun moyen de revenir en arriere.
  D-DEP-6  `currency` accepte n'importe quelle chaine (`FRA-201`) — la devise
           vient de la table pays du Loader, jamais d'une supposition.
  D-DEP-9  Le serveur accepte de souscrire un Depositaire a un produit
           **LENDING** (HTTP 201, `ANO-DEP-TYPE-02`). Le catalogue est donc
           filtre **avant** la boucle, et `souscrire()` revalide de son cote.
  FRA-202  Une souscription dupliquee est acceptee en 201 — d'ou
           `a_deja_souscrit()` avant chaque POST.

**Un quartier n'heberge qu'un seul Kiosque.** La garantie est double : l'index
unique `(run_id, district_id)` cote Mongo, et un ensemble en memoire ici — ce
dernier fonctionne aussi en `DRY_RUN`, ou rien n'est ecrit.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.clients.base import ErreurService
from app.clients.contracts import ProductType
from app.clients.depositary_service import COMPTES_DEPOSITAIRE, DepositaryServiceClient
from app.models.enums import RunMode, RunStatus
from app.repositories import AuditTrailRepository, OrgHierarchyRepository
from app.services.generateur import Generateur
from app.services.geographie import ReferentielGeo
from app.services.organisation import CompanyPorteuse, PlanOrganisation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProduitSouscriptible:
    """Un produit du catalogue, avec son type EXPLICITE.

    Le type est porte ici et non deduit, parce que c'est lui qui declenche
    `D-DEP-9`. Un produit dont on ignore le type ne doit pas pouvoir entrer
    dans la boucle de souscription.
    """

    product_id: UUID
    nom: str
    type_produit: ProductType
    #: AJOUT DU 11/08 — `valider_produit_client()` en a besoin, et sans elle la
    #: coherence Client/Produit n'est pas verifiable. `OBS-CLI-CROSSCHECK-01`,
    #: mesure du 09/08 : un Client CORPORATE souscrit a un produit INDIVIDUAL
    #: sans le moindre rejet serveur. « Devant un bailleur qui connait le metier,
    #: c'est une incoherence visible a l'oeil nu. » La coherence est donc
    #: entierement a notre charge, EN AMONT, dans la selection du produit —
    #: ce qui exige de connaitre sa categorie ici.
    #:
    #: `""` quand le serveur ne la declare pas : `valider_produit_client` traite
    #: la chaine vide comme « pas de contrainte », au meme titre qu'`ANY`.
    categorie: str = ""
    #: AJOUT DU 12/08, meme argument que `categorie` la veille : un produit dont
    #: on ignore le `PolicyType` ne doit pas pouvoir entrer dans la boucle de
    #: souscription. `UC-13` autorise 1 a 3 produits, et l'ORDRE dans lequel un
    #: client les prend n'est pas indifferent — `CASH` est le produit d'entree
    #: (la cotisation), `CASH_DAT` suppose une capacite d'epargne, `PRODUCT` est
    #: une collecte en nature. Un client dont le seul produit serait
    #: « plastique » n'est pas un client d'epargne.
    #:
    #: MESURE DU 12/08 : cette valeur vit dans `policy.type` de la fiche serveur,
    #: PAS au premier niveau — le `type` de premier niveau est le `ProductType`
    #: (COLLECT/LENDING). Confondre les deux donnerait `COLLECT` partout.
    policy_type: str = ""
    #: AJOUT DU 12/08 — le TERME d'un `CASH_DAT`, en mois. `None` sinon.
    #:
    #: Il ne vient PAS du serveur : `CollectPolicySchema` n'a aucun champ de
    #: duree (mesure de l'OpenAPI vivant, treize champs, zero terme). Il vient de
    #: `CATALOGUE_COLLECT`, notre source unique, via `duree_mois_du_produit()`.
    #:
    #: Son usage est en aval : la Collect d'un depot a terme porte
    #: `end_date = souscription + duree_mois` — `CollectSchema.end_date` est le
    #: seul champ temporel que collect-service expose. Sans cette valeur, un
    #: depot a terme serait un depot sans terme.
    duree_mois: int | None = None


@dataclass(slots=True)
class RapportDepositaires:
    """Le prevu et le realise, toujours distingues.

    `kiosques_sautes` n'est **pas** un echec : c'est un Kiosque qui existait
    deja (D-DEP-3) ou dont le quartier etait deja pris. Les confondre ferait
    passer un run parfaitement idempotent pour un run degrade.
    """

    mode: RunMode
    branches_creees: list[str] = field(default_factory=list)
    agences_creees: list[str] = field(default_factory=list)
    kiosques_crees: list[str] = field(default_factory=list)
    kiosques_sautes: list[tuple[str, str]] = field(default_factory=list)
    kiosques_echoues: list[tuple[str, str]] = field(default_factory=list)
    souscriptions_creees: int = 0
    souscriptions_sautees: int = 0
    souscriptions_echouees: list[tuple[str, str]] = field(default_factory=list)
    produits_ecartes: list[tuple[str, str]] = field(default_factory=list)
    kiosques_souscrits: int = 0

    @property
    def comptes_attendus(self) -> int:
        """D-DEP-2 — 6 comptes par Kiosque **souscrit**, pas par souscription.

        C'est la difference entre annoncer 54 comptes et en annoncer 324. Le
        chiffre a ete verifie : 2e souscription -> +0 compte.
        """
        return self.kiosques_souscrits * len(COMPTES_DEPOSITAIRE)

    @property
    def statut(self) -> RunStatus:
        """PARTIAL est un etat terminal legitime — un Kiosque recalcitrant
        n'invalide pas le reseau. FAILED n'est prononce que si **rien** n'a
        abouti alors que le plan prevoyait quelque chose : c'est alors
        systemique, pas anecdotique.
        """
        echecs = self.kiosques_echoues + self.souscriptions_echouees
        if not echecs:
            return RunStatus.COMPLETED
        if not self.kiosques_crees:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    def resume(self) -> str:
        lignes = [
            f"Mode : {self.mode.value}",
            f"Branches : {len(self.branches_creees)}",
            f"Agences  : {len(self.agences_creees)}",
            f"Kiosques : {len(self.kiosques_crees)} crees, "
            f"{len(self.kiosques_sautes)} sautes, {len(self.kiosques_echoues)} en echec",
            f"Souscriptions : {self.souscriptions_creees} creees, "
            f"{self.souscriptions_sautees} deja presentes, "
            f"{len(self.souscriptions_echouees)} en echec",
            f"Comptes attendus : {self.comptes_attendus} "
            f"({self.kiosques_souscrits} Kiosques x {len(COMPTES_DEPOSITAIRE)})",
            f"STATUT : {self.statut.value}",
        ]
        for nom, motif in self.produits_ecartes:
            lignes.append(f"  ECARTE {nom} : {motif}")
        for nom, motif in self.kiosques_sautes:
            lignes.append(f"  SAUTE  {nom} : {motif}")
        for nom, motif in self.kiosques_echoues + self.souscriptions_echouees:
            lignes.append(f"  ECHEC  {nom} : {motif}")
        return "\n".join(lignes)


class ExecuteurDepositaires:
    """Deroule UC-09 a partir d'un plan deja verifie.

    `DRY_RUN` n'emet **aucune ecriture** — ni vers depositary-service, ni vers
    `org_hierarchy`. Ecrire la hierarchie sans les Depositaires produirait des
    noeuds pointant vers un `depositary_id` inexistant : une base incoherente
    au premier essai a blanc, ce qui est le contraire du but recherche.

    Les LECTURES sont conservees en `DRY_RUN`, et c'est delibere : elles seules
    revelent ce qui existe deja et serait donc saute. Un essai a blanc aveugle
    annoncerait des creations qui n'auraient jamais lieu.
    """

    def __init__(
        self,
        *,
        run_id: UUID,
        mode: RunMode,
        referentiel: ReferentielGeo,
        generateur: Generateur,
        depositary_client: DepositaryServiceClient,
        hierarchie: OrgHierarchyRepository,
        audit: AuditTrailRepository,
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self._referentiel = referentiel
        self._generateur = generateur
        self._depositaires = depositary_client
        self._hierarchie = hierarchie
        self._audit = audit
        #: Garantit « un Kiosque par quartier » y compris en DRY_RUN, ou
        #: l'index unique Mongo ne joue pas.
        self._quartiers_pris: set[str] = set()

    @property
    def ecriture_reelle(self) -> bool:
        return self.mode is RunMode.REAL

    @property
    def quartiers_occupes(self) -> frozenset[str]:
        """Les quartiers deja pourvus dans ce run — vue en LECTURE SEULE.

        Exposee parce qu'en `DRY_RUN` l'index unique Mongo ne joue pas : c'est
        le seul moyen de verifier « un quartier, un Kiosque » sans ecrire. Le
        `frozenset` interdit qu'un appelant vienne le modifier.
        """
        return frozenset(self._quartiers_pris)

    # ----------------------------------------------------------------------
    # Filtrage du catalogue — D-DEP-9, avant toute boucle
    # ----------------------------------------------------------------------

    def filtrer_catalogue(
        self, produits: Sequence[ProduitSouscriptible], rapport: RapportDepositaires
    ) -> list[ProduitSouscriptible]:
        """Ne garde que les produits `COLLECT`, et dit pourquoi il ecarte.

        Le filtre est place **avant** la boucle plutot que dedans : un produit
        LENDING ecarte une fois doit l'etre une fois, pas 54 fois. Et le rapport
        porte la trace de l'ecartement, sinon un catalogue mal constitue
        passerait inapercu.
        """
        retenus: list[ProduitSouscriptible] = []
        for produit in produits:
            if produit.type_produit is ProductType.COLLECT:
                retenus.append(produit)
                continue
            rapport.produits_ecartes.append(
                (
                    produit.nom,
                    f"type {produit.type_produit.value} — D-DEP-9, un Kiosque est epargne",
                )
            )
        return retenus

    # ----------------------------------------------------------------------
    # UC-09 — un Kiosque, son quartier, ses souscriptions
    # ----------------------------------------------------------------------

    async def creer_kiosque(
        self,
        *,
        company: CompanyPorteuse,
        agence_id: UUID,
        district_id: str,
        pays: str,
        rapport: RapportDepositaires,
    ) -> tuple[UUID, str] | None:
        """Cree le Depositaire, puis son noeud `org_hierarchy`.

        Renvoie `(depositary_id, nom)` — **le nom voyage avec l'identifiant**.

        `D-12` : le registre d'unicite ne rend un nom qu'UNE fois. L'appelant
        recomposait le sien pour l'etiquette du rapport ; le registre lui aurait
        alors donne un nom DIFFERENT de celui reellement ecrit sur le serveur.
        Un nom se calcule une seule fois, au moment ou il est pose.

        Renvoie `None` si le Kiosque a ete saute — ce qui n'est pas un echec.
        L'ordre est impose : le noeud reference le `depositary_id`, il ne peut
        donc pas exister avant lui.
        """
        quartier = self._referentiel.quartier(district_id)
        if quartier is None:
            rapport.kiosques_echoues.append((district_id, "quartier absent du referentiel"))
            return None

        if district_id in self._quartiers_pris:
            rapport.kiosques_sautes.append((quartier.name, "quartier deja pourvu dans ce run"))
            return None

        nom = self._generateur.nom_kiosque(quartier.name, pays)

        # D-DEP-3 — aucune unicite serveur, aucun DELETE : le doublon serait
        # definitif. La lecture est faite AUSSI en DRY_RUN, c'est elle qui rend
        # l'essai a blanc honnete.
        existant = await self._depositaires.chercher_par_nom(nom)
        if existant is not None:
            self._quartiers_pris.add(district_id)
            rapport.kiosques_sautes.append((nom, "deja present cote serveur"))
            identifiant = self._depositaires.identifiant(existant)
            return (UUID(identifiant), nom) if identifiant else None

        if not self.ecriture_reelle:
            self._quartiers_pris.add(district_id)
            rapport.kiosques_crees.append(f"{nom} [prevu]")
            # IDENTIFIANT FICTIF — DEFAUT CORRIGE LE 11/08.
            #
            # Cette branche rendait `None`, et l'appelant enchainait sur
            # `if cree is None: continue`. **La souscription n'etait donc JAMAIS
            # exercee en DRY_RUN**, et le rapport annoncait
            # « Comptes attendus : 0 » quand le run reel en creerait 6 par
            # Kiosque — 354 comptes pour 59 Kiosques, definitifs, sur un service
            # sans `DELETE`.
            #
            # `D-01` fait de ce rapport « la derniere occasion de dire non ». Un
            # humain lisant zero aurait dit oui a 354 ecritures. Le defaut etait
            # donc DANS le mecanisme de securite, pas a cote.
            #
            # Le module Organisation applique deja ce motif, et pour la meme
            # raison ecrite noir sur blanc : « en DRY_RUN les Depositaires ne
            # doivent RIEN ecrire, mais ils doivent pouvoir derouler leur plan
            # pour que le rapport a blanc soit complet. »
            #
            # Regle du 09/08 : un essai a blanc qui n'exerce pas les MEMES
            # DEPENDANCES que le reel n'est pas un essai a blanc.
            return uuid4(), nom

        try:
            depositaire = await self._depositaires.creer(nom, company.devise, company.company_id)
        except ErreurService as exc:
            # On ne rejoue pas : un 4xx designe notre payload, le repeter le
            # repeterait. Le detail serveur est tronque — il fuit des traces
            # Python (ANO-CPY-LEAK-07), on ne le parse jamais.
            motif = f"HTTP {exc.status} : {exc.detail[:160]}"
            rapport.kiosques_echoues.append((nom, motif))
            logger.warning("Kiosque %s en echec, poursuite : %s", nom, motif)
            return None

        identifiant = self._depositaires.identifiant(depositaire)
        if identifiant is None:
            rapport.kiosques_echoues.append((nom, "identifiant absent de la reponse"))
            return None
        depositary_id = UUID(identifiant)

        noeud = await self._hierarchie.ajouter_kiosque(
            run_id=self.run_id,
            agence_id=agence_id,
            company_id=company.company_id,
            name=nom,
            country_code=company.country_code,
            district_id=district_id,
            depositary_id=depositary_id,
        )
        if noeud is None:
            # L'index unique a tranche : un autre Kiosque occupe deja ce
            # quartier. Le Depositaire existe deja cote serveur et ne peut pas
            # etre supprime — on le signale sans pretendre l'avoir efface.
            rapport.kiosques_sautes.append(
                (nom, "quartier deja pourvu (index unique) — Depositaire cree, non rattache")
            )
        self._quartiers_pris.add(district_id)
        rapport.kiosques_crees.append(nom)
        await self._audit.journaliser(
            run_id=self.run_id,
            entity_type="Depositary",
            entity_id=depositary_id,
            action="CREATE",
            after={
                "name": nom,
                "currency": company.devise,
                "company_id": str(company.company_id),
                "district_id": district_id,
                "country_code": company.country_code,
            },
        )
        return depositary_id, nom

    async def souscrire_kiosque(
        self,
        *,
        depositary_id: UUID,
        nom_kiosque: str,
        produits: Sequence[ProduitSouscriptible],
        rapport: RapportDepositaires,
    ) -> None:
        """D-DEP-2 — la premiere souscription reussie cree les 6 comptes.

        `kiosques_souscrits` n'est incremente qu'**une fois par Kiosque**, a la
        premiere souscription effective : c'est ce compteur, et non le nombre de
        souscriptions, qui donne le nombre de comptes.
        """
        if not self.ecriture_reelle:
            # On ANNONCE, on n'interroge pas : le `depositary_id` est fictif en
            # DRY_RUN, demander au serveur « a-t-il deja souscrit ? » n'aurait
            # aucun sens. Le catalogue est deja filtre COLLECT par l'appelant
            # (`D-DEP-9`), donc chaque produit compte.
            rapport.souscriptions_creees += len(produits)
            if produits:
                # `D-DEP-2` — 6 comptes par Kiosque SOUSCRIT, pas par
                # souscription. C'est ce compteur qui rend `comptes_attendus`
                # honnete : 6 x Kiosques, jamais 6 x souscriptions.
                rapport.kiosques_souscrits += 1
            logger.info(
                "[DRY_RUN] %s — %d souscription(s) prete(s), %d comptes en cascade",
                nom_kiosque,
                len(produits),
                len(COMPTES_DEPOSITAIRE),
            )
            return

        premier_succes = False
        for produit in produits:
            if await self._depositaires.a_deja_souscrit(depositary_id, produit.product_id):
                rapport.souscriptions_sautees += 1
                premier_succes = True
                continue
            try:
                await self._depositaires.souscrire(
                    depositary_id, produit.product_id, type_produit=produit.type_produit
                )
            except ErreurService as exc:
                motif = f"HTTP {exc.status} : {exc.detail[:160]}"
                rapport.souscriptions_echouees.append((f"{nom_kiosque} -> {produit.nom}", motif))
                continue
            except ValueError as exc:
                # D-DEP-9 leve AVANT le reseau. Si on arrive ici, c'est que le
                # filtre du catalogue a ete contourne — anomalie de notre cote,
                # jamais du serveur.
                rapport.souscriptions_echouees.append((f"{nom_kiosque} -> {produit.nom}", str(exc)))
                continue
            rapport.souscriptions_creees += 1
            premier_succes = True
        if premier_succes:
            rapport.kiosques_souscrits += 1

    # ----------------------------------------------------------------------
    # Deroule complet
    # ----------------------------------------------------------------------

    async def executer(
        self,
        plan: PlanOrganisation,
        companies_par_pays: Mapping[str, Sequence[CompanyPorteuse]],
        produits: Sequence[ProduitSouscriptible],
    ) -> RapportDepositaires:
        """Deroule Branche -> Agence -> Kiosque -> souscriptions, pays par pays.

        Un pays sans IMF creee est **saute sans echec** : la hierarchie de UC-09
        repose sur les IMF, et si l'etape Organisation n'en a produit aucune, ce
        n'est pas ici que le probleme doit etre signale.
        """
        rapport = RapportDepositaires(mode=self.mode)
        catalogue = self.filtrer_catalogue(produits, rapport)
        if not catalogue:
            logger.warning("Aucun produit COLLECT — les Kiosques naitront sans compte (D-DEP-2)")

        for plan_pays in plan.pays:
            porteuses = list(companies_par_pays.get(plan_pays.country_code, ()))
            if not porteuses:
                rapport.kiosques_sautes.append(
                    (plan_pays.country_code, "aucune IMF creee — hierarchie sans porteur (UC-09)")
                )
                continue

            for plan_branche in plan_pays.branches:
                # LE PLAN DIT DESORMAIS A QUI APPARTIENT CHAQUE BRANCHE.
                #
                # Avant : `porteuses[rang % len(porteuses)]` — un tourniquet, qui
                # donnait a chaque IMF une ou deux regions et pas un reseau. Le
                # plan partitionne maintenant les QUARTIERS entre les IMF, et
                # chaque Branche porte son `imf_rang`. Chaque IMF a donc une
                # Branche par region ou elle opere et une Agence par ville —
                # exactement ce que le Manuel decrit d'une Agence, « point de
                # commercialisation distant du headquarter ».
                #
                # Le modulo protege le cas ou l'etape Organisation aurait produit
                # moins d'IMF que le plan n'en prevoyait (UC-07, cas alternatif :
                # une Company en echec ne stoppe pas le run).
                company = porteuses[plan_branche.imf_rang % len(porteuses)]
                region = self._referentiel.region(plan_branche.region_id)
                nom_region = region.name if region else plan_branche.region_id
                nom_branche = self._generateur.nom_branche(nom_region, plan_pays.country_code)

                branche_id: UUID | None = None
                if self.ecriture_reelle:
                    branche = await self._hierarchie.ajouter_branche(
                        run_id=self.run_id,
                        company_id=company.company_id,
                        name=nom_branche,
                        country_code=plan_pays.country_code,
                        region_id=plan_branche.region_id,
                    )
                    branche_id = branche.id
                rapport.branches_creees.append(nom_branche)

                for plan_agence in plan_branche.agences:
                    ville = self._referentiel.ville(plan_agence.city_id)
                    nom_ville = ville.name if ville else plan_agence.city_id
                    nom_agence = self._generateur.nom_agence(nom_ville, plan_pays.country_code)

                    agence_id: UUID | None = None
                    if self.ecriture_reelle and branche_id is not None:
                        agence = await self._hierarchie.ajouter_agence(
                            run_id=self.run_id,
                            branche_id=branche_id,
                            company_id=company.company_id,
                            name=nom_agence,
                            country_code=plan_pays.country_code,
                            city_id=plan_agence.city_id,
                        )
                        agence_id = agence.id
                    rapport.agences_creees.append(nom_agence)

                    for plan_kiosque in plan_agence.kiosques:
                        cree = await self.creer_kiosque(
                            company=company,
                            # En DRY_RUN aucun noeud n'existe ; la branche
                            # n'est jamais atteinte puisque creer_kiosque
                            # rend None avant d'ecrire.
                            agence_id=agence_id or self.run_id,
                            district_id=plan_kiosque.district_id,
                            pays=plan_pays.country_code,
                            rapport=rapport,
                        )
                        if cree is None or not catalogue:
                            continue
                        depositary_id, nom_du_kiosque = cree
                        await self.souscrire_kiosque(
                            depositary_id=depositary_id,
                            nom_kiosque=nom_du_kiosque,
                            produits=catalogue,
                            rapport=rapport,
                        )

        return rapport
