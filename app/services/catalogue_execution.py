"""
app/services/catalogue_execution.py
===================================
Execution du module Catalogue — `UC-11`, `EF-69`, story `S3-05`.

CE QUI MANQUAIT
---------------
`catalogue.py` composait les payloads — `payloads_lending()`, `payloads_collect()`
— et **rien ne les postait**. Le plan de sprint annonçait « les trois executeurs
deja ecrits » ; il y en avait quatre au total, et le Catalogue n'en faisait pas
partie. Le module etait un generateur sans bras.

LE COMPTE EXACT — 12 PRODUITS, 10 CREATIONS
-------------------------------------------
  LENDING   4 produits au fichier -> **6 creations** : `BNPL` et `ReadyToGo`
            portent `Category: Any`, valeur que l'enum serveur refuse
            (`INV-PRD-04`, HTTP 422). Chacun est dedouble INDIVIDUAL +
            CORPORATE (`D-PRD-4`).
  COLLECT   6 produits cibles -> **4 creations** : « Cotisation 20000/mois » et
            « plastique » existent DEJA en base. Ils sont RETROUVES, jamais
            recrees (`D-PRD-9`).

`10 + 2 = 12`. Un rapport qui annoncerait 12 creations mentirait sur deux
produits qu'il n'a pas faits.

LES QUATRE PIEGES NEUTRALISES
-----------------------------
  ANO-PRD-POLICY-01  `policy` est declaree OPTIONNELLE au contrat, et son
                     absence provoque un HTTP 500. Le client la refuse en amont ;
                     ici on n'en omet jamais.
  INV-PRD-07         La Policy est une REFERENCE VIVANTE : la modifier change
                     retroactivement et silencieusement TOUS les Products qui la
                     referencent. D'ou `D-PRD-7` — un embed par Product, jamais
                     un `policy_id` partage. **Aucun** `policy_id` n'est emis.
  ANO-PRD-UNIQ-01    Aucune unicite serveur sur `name`, et la base contient deja
                     un doublon. Le `GET`-avant-`POST` retient **le plus
                     ancien** et signale la multiplicite plutot que de la taire.
  EF-35 / CR-01      Le fichier source annonce un taux jusqu'a 25 %, le plafond
                     d'usure BEAC/COBAC est de 24 %. Borne appliquee dans
                     `catalogue.py`, verifiee ici avant emission.

CE QUE CET EXECUTEUR PRODUIT POUR LA SUITE
------------------------------------------
La liste des `ProduitSouscriptible` — **l'artefact que le module Depositaires
consomme**. Il porte le `type_produit` EXPLICITE : c'est lui qui declenche
`D-DEP-9`, et un produit dont on ignore le type ne doit pas pouvoir entrer dans
la boucle de souscription.

Cette liste inclut les 2 produits **preexistants** : ils sont souscriptibles
comme les autres. Les exclure priverait les Kiosques de deux produits reels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from app.clients.base import ErreurService
from app.clients.contracts import ProductType
from app.clients.product_service import ProductServiceClient
from app.core.cdc import TAUX_USURE_MAX_ANNUEL_PCT
from app.models.enums import RunMode, RunStatus
from app.repositories import AuditTrailRepository
from app.services.catalogue import (
    PRODUITS_ENVIRONNEMENT,
    charger_loan_json,
    duree_mois_du_produit,
    payloads_collect,
    payloads_lending,
)
from app.services.depositaires_execution import ProduitSouscriptible

logger = logging.getLogger(__name__)

#: Ce que `UC-11` attend au total, une fois le catalogue en place.
PRODUITS_ATTENDUS = 12
#: Ce que le Loader CREE. La difference (2) est deja en base — `D-PRD-9`.
CREATIONS_ATTENDUES = 12


@dataclass(slots=True)
class RapportCatalogue:
    """Ce que l'execution a produit, et ce qu'elle a deliberement saute."""

    mode: RunMode
    crees: list[str] = field(default_factory=list)
    reutilises: list[str] = field(default_factory=list)
    #: Ce que l'environnement porte et que nous n'utilisons PAS — 12/08. Ni cree,
    #: ni reutilise : constate. Un fait tu est un fait perdu.
    constates: list[str] = field(default_factory=list)
    #: 13/08 — un produit ETRANGER occupe un de NOS noms. Ni consomme (la lecon
    #: `A-10` : on n'attache pas 2000 clients a une entite qu'on ne controle
    #: pas), ni double (`D-12` : deux homonymes sont indiscernables a l'ecran,
    #: et `ANO-PRD-UNIQ-01` fait que le serveur laisserait faire). REFUSE avant
    #: reseau, avec le motif — c'est le Loader qui neutralise le bug du service,
    #: jamais l'inverse.
    refuses_avant_reseau: list[tuple[str, str]] = field(default_factory=list)
    echoues: list[tuple[str, str]] = field(default_factory=list)
    #: L'artefact consomme par le module Depositaires.
    souscriptibles: list[ProduitSouscriptible] = field(default_factory=list)
    #: Ecart entre le compte du CDC et ce qui existe reellement.
    ecart_au_cdc: str = ""

    @property
    def statut(self) -> RunStatus:
        """`FAILED` seulement si **rien** n'a abouti.

        Retrouver un produit preexistant n'est pas un accomplissement de CE
        run : si tout a echoue et que seuls les 2 produits deja en base sont
        la, le probleme est systemique — meme raisonnement que `RapportRoles`.
        """
        if not self.echoues:
            return RunStatus.COMPLETED
        if not self.crees:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    def resume(self) -> str:
        lignes = [
            f"Mode        : {self.mode.value}",
            f"Produits crees   : {len(self.crees)} / {CREATIONS_ATTENDUES} attendus",
            *(
                [f"Constate (non utilise) : {c}" for c in self.constates]
                if self.constates
                else []
            ),
            f"Reutilises       : {len(self.reutilises)} ({', '.join(self.reutilises) or '-'})",
            *(
                [
                    f"Refuse avant reseau : {nom} — {motif}"
                    for nom, motif in self.refuses_avant_reseau
                ]
                if self.refuses_avant_reseau
                else []
            ),
            f"Echecs           : {len(self.echoues)}",
            f"Souscriptibles   : {len(self.souscriptibles)} (dont COLLECT pour les Kiosques)",
            f"STATUT : {self.statut.value}",
        ]
        for nom, motif in self.echoues:
            lignes.append(f"  ECHEC {nom} : {motif}")
        if self.ecart_au_cdc:
            lignes.append(f"  ⚠ {self.ecart_au_cdc}")
        return "\n".join(lignes)


class ExecuteurCatalogue:
    """Cree les 10 produits manquants, retrouve les 2 preexistants.

    `DRY_RUN` conserve les LECTURES et supprime les ECRITURES — sans
    l'inventaire, le rapport annoncerait 10 creations alors que deux produits
    sont deja la, et le compte final serait faux.
    """

    def __init__(
        self,
        *,
        run_id: UUID,
        mode: RunMode,
        product_client: ProductServiceClient,
        audit: AuditTrailRepository,
        chemin_loan_json: Path,
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self._produits = product_client
        self._audit = audit
        self._chemin = chemin_loan_json

    @property
    def ecriture_reelle(self) -> bool:
        return self.mode is RunMode.REAL

    async def executer(self) -> RapportCatalogue:
        rapport = RapportCatalogue(mode=self.mode)

        payloads = payloads_lending(charger_loan_json(self._chemin)) + payloads_collect()
        self._verifier_avant_emission(payloads)

        for payload in payloads:
            await self._poser_un_produit(payload, rapport)

        # LES DEUX PRODUITS DE L'ENVIRONNEMENT : CONSTATES, PLUS CONSOMMES.
        #
        # `D-PRD-9` les faisait retrouver et les rendait souscriptibles. La regle
        # etait bonne — ils existaient deja avec des abonnes, et product-service
        # n'a ni unicite ni `DELETE`. Ce qu'elle ignorait, c'est ce qu'ils
        # CONTIENNENT : mesure du 12/08, « Cotisation 20000/mois » porte 99 %
        # d'interet mensuel et « plastique » n'accepte qu'une quantite de
        # exactement 3. Le produit d'ENTREE de 1600 clients, a 99 %.
        #
        # On ne batit pas notre catalogue sur les valeurs de test d'un
        # environnement partage. Ils sont donc SIGNALES et jamais souscrits :
        # l'environnement est un fait qu'on constate, pas une dependance.
        await self._constater_l_environnement(rapport)

        self._verifier_le_compte(rapport)
        return rapport

    # ------------------------------------------------------------------
    # Verifications AVANT le reseau — le Loader anticipe, il ne subit pas
    # ------------------------------------------------------------------

    @staticmethod
    def _verifier_avant_emission(payloads: list[dict[str, Any]]) -> None:
        """Trois controles que le serveur ne ferait pas — ou ferait mal.

        Ils tiennent en memoire, avant tout appel. Un `policy_id` partage ne
        provoque aucune erreur : il corrompt SILENCIEUSEMENT les autres
        Products (`INV-PRD-07`). Le serveur ne nous le dirait jamais.
        """
        for payload in payloads:
            nom = str(payload.get("name", "?"))
            if not payload.get("policy"):
                raise ValueError(f"{nom} : policy absente — HTTP 500 garanti (ANO-PRD-POLICY-01)")
            if payload.get("policy_id"):
                raise ValueError(f"{nom} : policy_id interdit — reference vivante (D-PRD-7)")
            taux = float(payload.get("policy", {}).get("interest_rate", 0) or 0)
            if taux > TAUX_USURE_MAX_ANNUEL_PCT:
                raise ValueError(
                    f"{nom} : taux {taux} % au-dessus du plafond d'usure BEAC/COBAC "
                    f"({TAUX_USURE_MAX_ANNUEL_PCT} %) — EF-35, CR-01"
                )

    # ------------------------------------------------------------------
    # Ecriture
    # ------------------------------------------------------------------

    async def _poser_un_produit(self, payload: dict[str, Any], rapport: RapportCatalogue) -> None:
        nom = str(payload["name"])
        type_produit = ProductType(str(payload["type"]))

        # `D-PRD-2` — inventaire AVANT creation, EN DEUX CLES depuis le 13/08.
        # Aucune unicite serveur (`ANO-PRD-UNIQ-01`), aucun `DELETE` : le
        # doublon serait definitif.
        #
        # PREMIERE CLE — le `short_name`. Depuis que le `name` est entierement
        # metier, le marqueur est la seule identite qui nous appartient : c'est
        # lui qui reconnait NOS produits d'un run anterieur (`CR-03`).
        existant = await self._produits.chercher_par_short_name(
            str(payload.get("short_name") or "")
        )
        if existant is None:
            # SECONDE CLE — le `name`. S'il est occupe alors que notre marqueur
            # est absent, c'est un produit ETRANGER : on refuse avant reseau.
            # Le consommer attacherait nos clients a une entite qu'on ne
            # controle pas (`A-10`) ; creer quand meme fabriquerait deux
            # homonymes indiscernables (`D-12`). Le Loader ne subit pas le bug
            # d'unicite du service — il le neutralise.
            homonyme = await self._produits.chercher_par_nom(nom)
            if homonyme is not None:
                motif = (
                    "nom deja porte par un produit etranger "
                    f"(_id={homonyme.get('_id') or homonyme.get('id')}, "
                    f"short_name={homonyme.get('short_name')!r}) — ni consomme "
                    "(A-10), ni double (D-12/ANO-PRD-UNIQ-01)"
                )
                rapport.refuses_avant_reseau.append((nom, motif))
                logger.warning("produit %s refuse avant reseau : %s", nom, motif)
                return
        if existant is not None:
            identifiant = existant.get("_id") or existant.get("id")
            rapport.reutilises.append(nom)
            if identifiant:
                rapport.souscriptibles.append(
                    ProduitSouscriptible(
                        UUID(str(identifiant)),
                        nom,
                        type_produit,
                        # La categorie vient de la FICHE SERVEUR : c'est elle qui
                        # fait foi sur un produit qu'on n'a pas cree.
                        str(existant.get("category") or "").upper(),
                        # `policy.type`, jamais `type` : mesure du 12/08.
                        str((existant.get("policy") or {}).get("type") or "").upper(),
                        duree_mois_du_produit(nom),
                    )
                )
            return

        if not self.ecriture_reelle:
            rapport.crees.append(f"{nom} [prevu]")
            # DEFAUT TROUVE LE 11/08 PAR LE PREMIER ESSAI A BLANC DU MODULE
            # CLIENTS : le produit prevu n'entrait PAS dans `souscriptibles`. A
            # blanc, seuls les 2 produits preexistants etaient donc visibles en
            # aval — et tous deux sont `INDIVIDUAL`.
            #
            # Consequence mesuree : les 400 clients CORPORATE etaient TOUS
            # refuses (« aucun produit COLLECT compatible »), `EF-23` affichait
            # `Corp 0/100`, et la boucle abandonnait a ~405/500 par epuisement.
            # Trois symptomes, une cause : un essai a blanc qui montrait un
            # catalogue plus pauvre que le reel.
            #
            # C'est la meme famille que le defaut Kiosque du 11/08 (« Comptes
            # attendus : 0 » a blanc, 354 en reel). `D-01` fait du rapport a
            # blanc « la derniere occasion de dire non » : il doit montrer le
            # catalogue que le REEL produirait, pas un sous-ensemble.
            #
            # L'identifiant est local et ne quitte jamais le processus — a blanc,
            # aucune ecriture ne part.
            rapport.souscriptibles.append(
                ProduitSouscriptible(
                    uuid4(),
                    nom,
                    type_produit,
                    str(payload.get("category") or "").upper(),
                    # LE MEME DEFAUT QU'AU-DESSUS, UN CRAN PLUS FIN — 12/08.
                    #
                    # Le produit prevu entrait bien dans `souscriptibles` depuis
                    # le 11/08, mais SANS son `policy_type`. `UC-13` ordonne le
                    # panier par `CASH` -> `CASH_DAT` -> `PRODUCT` : sans cette
                    # valeur, le tri retombait sur le NOM.
                    #
                    # Et il tombait JUSTE PAR COINCIDENCE : « Cotisation » <
                    # « Depot » < « plastique » dans l'ordre alphabetique. Le
                    # rapport a blanc montrait donc un ordre correct pour une
                    # raison fausse — la forme de defaut la plus dangereuse,
                    # parce qu'aucun symptome ne la denonce. Un simple
                    # renommage de produit l'aurait fait apparaitre en REEL.
                    str((payload.get("policy") or {}).get("type") or "").upper(),
                    duree_mois_du_produit(nom),
                )
            )
            return

        # Journal d'intention : `POST /products` cree Product ET Policy. Sans
        # trace prealable, un timeout laisserait une Policy orpheline dont rien
        # ne garderait le souvenir — et product-service n'a pas de `DELETE`.
        entite = uuid4()
        async with self._audit.intention(
            self.run_id,
            entity_type="Product",
            entity_id=entite,
            operation="CREATE",
            cible="product-service",
            payload={"name": nom, "type": type_produit.value},
        ) as suivi:
            try:
                reponse = await self._produits.creer_produit(payload)
            except ErreurService as exc:
                # On ne rejoue pas : un 4xx designe notre payload, le repeter le
                # repeterait. Le detail est tronque — les messages fuient des
                # traces Python (`ANO-CPY-LEAK-07`), on ne les parse jamais.
                motif = f"HTTP {exc.status} : {exc.detail[:160]}"
                suivi.echoue(motif)
                rapport.echoues.append((nom, motif))
                logger.warning("produit %s en echec, poursuite : %s", nom, motif)
                return

            identifiant = reponse.get("_id") or reponse.get("id")
            if not identifiant:
                suivi.echoue("identifiant absent de la reponse")
                rapport.echoues.append((nom, "identifiant absent de la reponse"))
                return

            suivi.reussi({"product_id": str(identifiant)})

        rapport.crees.append(nom)
        rapport.souscriptibles.append(
            ProduitSouscriptible(
                UUID(str(identifiant)),
                nom,
                type_produit,
                str(payload.get("category") or "").upper(),
                str((payload.get("policy") or {}).get("type") or "").upper(),
                duree_mois_du_produit(nom),
            )
        )

    async def _constater_l_environnement(self, rapport: RapportCatalogue) -> None:
        """Dit ce que l'environnement porte, sans jamais s'en servir.

        Ces deux produits ne sont ni crees, ni reutilises, ni souscriptibles. Ils
        sont NOMMES au rapport parce qu'un fait tu est un fait perdu : un lecteur
        qui verrait « Cotisation Individuelle 20000/mois » a cote de
        « Cotisation 20000/mois » dans l'inventaire serveur doit comprendre
        pourquoi les deux coexistent.

        Aucune ecriture, aucun `POST`. La lecture est la seule chose qu'on
        s'autorise sur des entites partagees par toute l'equipe.
        """
        for nom in PRODUITS_ENVIRONNEMENT:
            existant = await self._produits.chercher_par_nom(nom)
            if existant is None:
                continue
            policy = existant.get("policy") or {}
            rapport.constates.append(
                f"« {nom} » present en base (non prefixe, non utilise) — "
                f"interet {policy.get('interest_rate')} %, "
                f"montants {policy.get('amount_min')} -> {policy.get('amount_max')}"
            )

    # ------------------------------------------------------------------
    # Verification APRES — le compte doit tomber juste
    # ------------------------------------------------------------------

    @staticmethod
    def _verifier_le_compte(rapport: RapportCatalogue) -> None:
        """`UC-11` attend 12 produits. On le VERIFIE au lieu de le supposer.

        L'ecart n'est pas une erreur a corriger : c'est un fait a remonter.
        Le Loader constate l'etat de l'environnement, il ne le repare pas.
        """
        total = len(rapport.crees) + len(rapport.reutilises)
        if total != PRODUITS_ATTENDUS and not rapport.ecart_au_cdc:
            rapport.ecart_au_cdc = (
                f"{total} produits au catalogue, {PRODUITS_ATTENDUS} attendus (UC-11) — "
                f"{len(rapport.crees)} crees, {len(rapport.reutilises)} reutilises, "
                f"{len(rapport.refuses_avant_reseau)} refuses avant reseau, "
                f"{len(rapport.echoues)} en echec"
            )
