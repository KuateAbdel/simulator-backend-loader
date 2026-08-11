"""
app/services/clients_execution.py
=================================
Execution du module Clients — `UC-12`, `UC-13`, `EF-20` a `EF-29`, story `S4-01`.

POURQUOI CE MODULE EXISTE MAINTENANT, ET PAS APRES
--------------------------------------------------
`FakerClient` et `clients_composition` etaient ecrits, testes... et appeles par
PERSONNE dans le chemin reel (constat du 11/08 : zero appelant hors tests). Une
chaine de deux modules qui se tiennent la main et ne debouchent nulle part.

C'est le defaut que ce projet a trouve **neuf fois** aujourd'hui — un module
livre, coche, branche a rien. Livrer d'abord la source senegalaise puis le moteur
de quotas en aurait fait quatre. Cet executeur est donc ecrit AVANT eux : il est
le point de terminaison, et ils sont des regles A L'INTERIEUR de lui.

L'ORDRE DES TROIS ECRITURES SUIT L'IRREVERSIBILITE, PAS LES DEPENDANCES
----------------------------------------------------------------------
    1. client-service    le SEUL des trois a exposer un `DELETE`
    2. identity-service  AUCUN `DELETE` — la piece KYC est definitive
    3. account-service   AUCUN `DELETE` — le compte est definitif

En pratique les trois tombent d'un seul `POST /clients/onboard` : client-service
cascade lui-meme vers identity puis account. On ne peut donc pas les etager — ce
qui rend le controle AVANT le reseau d'autant plus important, et c'est
exactement ce que fait `composer()`, qui refuse plutot que de deviner.

LES QUOTAS S'OBTIENNENT PAR TIRAGE-ET-REJET, JAMAIS PAR FILTRE
--------------------------------------------------------------
Un seul filtre Faker est reel :

    `EF-23`  80 % Individual / 20 % Corporate   -> `customer_category` ✅
    `EF-22`  ratio 2 femmes / 1 homme           -> le parametre `sex` est
                                                   SILENCIEUSEMENT IGNORE : testes,
                                                   `sex=male` et `sex=female`
                                                   rendent tous deux `WOMAN`
    `EF-22`  60 % de moins de 25 ans            -> aucun champ d'age en famille A
    `EF-24`  20 % des professionnels en agri.   -> aucun des 16 secteurs mesures
                                                   n'est agricole

D'ou la boucle : on tire, et on garde si le client SERT un quota encore ouvert.

**On n'ecarte QUE sur ce que Faker impose** — la categorie et le genre. L'age et
le secteur, eux, sont DECIDES par nous : ils ne peuvent donc jamais motiver un
rejet, et la boucle converge. Un rejet strict sur quatre criteres aurait pu
tourner indefiniment.

Et la regle qui rend tout cela tenable, `D-FAKER-1` : **un client ecarte pour
raison de quota est LIBERE, jamais consomme.** Sans elle, 2000 demandes
epuiseraient le vivier sans rien creer.

CE QUE LE DRY_RUN DOIT MONTRER
------------------------------
Tout, sauf les ecritures serveur. Il appelle Faker (lecture seule), il compose,
il reserve au registre puis LIBERE — parce que rien n'a ete produit. Il annonce
les comptes attendus.

C'est la lecon du 11/08 sur les Kiosques : le DRY_RUN annoncait « Comptes
attendus : 0 » quand le REEL en aurait cree 354, parce qu'une fonction rendait
`None` a blanc. `D-01` fait du rapport a blanc « la derniere occasion de dire
non » — un rapport qui ne montre pas ce que le reel ferait n'en est pas un.

L'ARBITRAGE `A-09` EST OUVERT, ET ISOLE DANS UNE SEULE FONCTION
---------------------------------------------------------------
`UC-13` pt 2 fait lire le solde initial dans `MOB_MONEY_ACCOUNT_AMOUNT` — absent
de la famille A, nul dans 4 tirages sur 7 en famille B. `solde_initial()`
applique la recommandation du 11/08 en attendant l'arbitrage : une fonction
DETERMINISTE des 11 champs `quick_win` que la famille A porte vraiment, bornee
par les strates de l'Annexe E. Une seule fonction a changer si tu tranches
autrement.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Final
from uuid import NAMESPACE_OID, UUID, uuid5

from app.clients.account_service import AccountServiceClient
from app.clients.base import ErreurService
from app.clients.client_service import (
    ClientServiceClient,
    OnboardingNonConforme,
    valider_produit_client,
)
from app.clients.contracts import ClientCategory, ProductType
from app.clients.faker_service import (
    CategorieClient,
    ClientFaker,
    FakerClient,
    PaysSansSource,
)
from app.core.cdc import (
    PART_CORPORATE,
    PART_CORPORATE_AGRICOLE,
    PART_MOINS_DE_25_ANS,
)
from app.core.configuration import ConfigurationExecution
from app.models.enums import FakerConsumptionType, NiveauOrganisation, RunMode, RunStatus
from app.repositories import FakerLedgerRepository, OrgHierarchyRepository
from app.services.clients_composition import (
    OCCUPATIONS_PAR_SECTEUR,
    ClientCompose,
    CompositionImpossible,
    ancrer_sur_kiosque,
    composer,
    occupation_du_secteur,
)
from app.services.generateur import CLES_PROFIL_INTERNE, Generateur
from app.services.geographie import ReferentielGeo
from app.services.source_interne import (
    SourceIdentites,
    SourceInterne,
    source_pour,
)

if TYPE_CHECKING:
    from app.models.domain import OrgHierarchyNode
    from app.services.depositaires_execution import ProduitSouscriptible

logger = logging.getLogger(__name__)

#: `EF-22` — « ratio deux femmes pour un homme ». Soit deux tiers de femmes.
PART_FEMMES: Final = 2 / 3

#: Annexe E — « montants par segment, de 5 000 (Nano Very Low) a 1 000 000 FCFA
#: (ReadyToGo Very High) ». Les bornes du solde initial s'y adossent : un client
#: doit pouvoir payer la premiere echeance du produit le plus modeste.
SOLDE_INITIAL_MIN: Final = 5_000.0
SOLDE_INITIAL_MAX: Final = 1_000_000.0

#: Les onze cles de `quick_win`, definies UNE FOIS dans le generateur : la
#: source interne les produit, cet executeur en derive le solde. Deux listes
#: paralleles auraient divergé en silence — un solde calcule sur des cles que la
#: source ne pose jamais.
CLES_QUICK_WIN_BINAIRES: Final[tuple[str, ...]] = CLES_PROFIL_INTERNE

#: Taille d'un lot. Assez grand pour saturer les 20 workers du semaphore
#: partage, assez petit pour que l'arbitrage sequentiel des quotas reste court
#: et que le SUR-TIRAGE ne gaspille pas des dizaines de clients Faker.
TAILLE_LOT: Final = 40

#: Nombre de lots consecutifs sans AUCUN client retenu avant d'abandonner un
#: pays. Le vivier Faker est illimite par le `seed`, mais un quota sature ou un
#: Faker muet peut rendre tout un lot inutile. Sans borne, la boucle tournerait
#: indefiniment — et `ENF-01` ne pardonne pas une boucle infinie.
TOURS_INFRUCTUEUX_MAX: Final = 5

def solde_initial(faker: ClientFaker) -> float:
    """Le solde initial du compte — **arbitrage `A-09`, recommandation appliquee**.

    `UC-13` pt 2 le fait lire dans `MOB_MONEY_ACCOUNT_AMOUNT`. Mesure du 11/08 :
    ce champ est ABSENT de la famille A — la seule population capable de fournir
    2000 clients — et vaut 0.0 dans 4 tirages sur 7 en famille B.

    Le CDC interdit par ailleurs « l'invention arbitraire de montants ». Restait
    donc a deriver de ce que la famille A porte VRAIMENT : les 11 champs
    `quick_win`. Un client regulier, equipe d'un smartphone et actif sur la data
    a un profil socio-economique plus solide qu'un client dormant — c'est
    exactement « un patrimoine coherent avec son profil socio-economique », les
    mots du CDC.

    DEUX ETAGES, ET LE SECOND CORRIGE UN DEFAUT QUE MES TESTS ONT TROUVE
    --------------------------------------------------------------------
    La premiere version rendait `MIN + (presents / 9) x (MAX - MIN)`. Neuf
    booleens ne donnent que **DIX montants possibles** : 2000 clients auraient
    partage dix soldes distincts. Un test de la source interne l'a mesure — 8
    valeurs sur 299 clients — et c'est exactement le graphique plat que
    `seconds_per_day` existe pour eviter, reproduit sur l'axe des montants.

    Le solde a donc deux etages :

      1. LA STRATE vient du profil — les neuf signaux de `quick_win` decident
         dans laquelle des dix bandes de l'Annexe E le client tombe. C'est le
         « patrimoine coherent avec son profil socio-economique » du CDC.
      2. LA POSITION DANS LA STRATE vient d'une empreinte stable du
         `client_id`. Deux clients au meme profil n'ont pas le meme solde au
         centime, comme dans la vraie vie.

    **Le second etage n'est PAS un tirage aleatoire** — c'est une fonction pure
    du `client_id` (SHA-256 tronque). Le meme client rend toujours le meme
    solde : `ENF-15` tient, et « sans invention arbitraire de montants » tient
    aussi, parce qu'aucune valeur ne sort d'un generateur de hasard. Le hachage
    n'est pas cryptographique ici, il sert d'etalement deterministe.

    Borne par l'Annexe E : de 5 000 (Nano Very Low) a 1 000 000 FCFA (ReadyToGo
    Very High), bornes incluses.
    """
    presents = sum(1 for cle in CLES_QUICK_WIN_BINAIRES if faker.quick_win.get(cle) == 1)
    nb_strates = len(CLES_QUICK_WIN_BINAIRES) + 1  # de 0 a 9 signaux inclus
    largeur = (SOLDE_INITIAL_MAX - SOLDE_INITIAL_MIN) / nb_strates

    empreinte = sha256(faker.client_id.encode()).digest()
    # 24 bits suffisent a etaler une strate de ~100 000 FCFA au centime pres.
    position = int.from_bytes(empreinte[:3], "big") / 0xFFFFFF

    return round(SOLDE_INITIAL_MIN + (presents + position) * largeur, 2)


@dataclass(frozen=True, slots=True)
class Reservation:
    """Ce qu'un quota a ACCORDE a un tirage — et qu'il faut rendre s'il echoue.

    Immuable : une reservation qu'on pourrait modifier apres coup ne serait pas
    une reservation.
    """

    business: bool
    femme: bool
    jeune: bool
    secteur: str


@dataclass(slots=True)
class QuotaPays:
    """L'etat de la distribution pour UN pays — `EF-22`, `EF-23`, `EF-24`.

    Ce n'est pas un compteur passif : c'est lui qui decide, pour chaque tirage,
    s'il sert encore a quelque chose. Un quota qui se contente de compter APRES
    coup ne garantit aucune distribution.
    """

    pays: str
    cible: int

    corporate_faits: int = 0
    individual_faits: int = 0
    femmes: int = 0
    hommes: int = 0
    jeunes: int = 0
    agricoles: int = 0
    #: Les tirages ecartes, par motif — ils entrent au rapport, jamais au registre.
    ecartes: dict[str, int] = field(default_factory=dict)

    @property
    def faits(self) -> int:
        return self.corporate_faits + self.individual_faits

    @property
    def cible_corporate(self) -> int:
        return round(self.cible * PART_CORPORATE)

    @property
    def cible_individual(self) -> int:
        return self.cible - self.cible_corporate

    @property
    def cible_femmes(self) -> int:
        return round(self.cible * PART_FEMMES)

    @property
    def cible_jeunes(self) -> int:
        return round(self.cible * PART_MOINS_DE_25_ANS)

    @property
    def cible_agricoles(self) -> int:
        return round(self.cible_corporate * PART_CORPORATE_AGRICOLE)

    # NOTE — il n'y a DELIBEREMENT aucun `categorie_ouverte()` ni
    # `genre_ouvert()` ici. Ces deux methodes ont existe, et leur seule existence
    # invitait a « verifier maintenant, compter plus tard » : c'est ce decalage
    # qui a produit `Corp 101/100` et `Femmes 311/333`. Verifier et compter sont
    # le meme geste, et `reserver()` est le seul endroit ou il se fait.

    # ------------------------------------------------------------------
    # RESERVER puis CONFIRMER ou RENDRE — jamais lire dans le concurrent
    # ------------------------------------------------------------------
    #
    # DEFAUT MESURE AU PREMIER ESSAI A BLANC : `<25ans 320/300`, soit **6,7 % de
    # depassement** quand `ENF-13` et `CR-09` exigent ±3 %. La cause : le
    # compteur etait LU dans le temps concurrent, ou vingt appels simultanes
    # voyaient tous « il manque un jeune ».
    #
    # Un quota qui se decide concurremment n'est pas un quota. Le compteur avance
    # donc a la RESERVATION, dans le temps sequentiel, et se defait si le client
    # n'aboutit pas — meme forme que `D-FAKER-1` sur le registre Faker, et pour
    # la meme raison : on ne compte pas ce qui n'existe pas encore, mais on ne
    # laisse pas deux decisions croire qu'elles sont seules.

    def reserver(self, tirage: ClientFaker) -> Reservation | None:
        """Verifie ET incremente les QUATRE quotas d'un coup. `None` si le tirage
        ne sert plus a rien.

        LE DEFAUT QUE CETTE METHODE FERME, mesure en deux passes le 11/08 :

            1re passe  `<25ans 320/300`  -> +6,7 %
            2e passe   `Corp 101/100`, `Femmes 311/333`  -> +1 % et -6,6 %

        La premiere version lisait les compteurs dans le temps CONCURRENT. La
        deuxieme les lisait dans le sequentiel mais ne les incrementait qu'APRES
        l'ecriture : vingt arbitrages passaient donc le meme controle avant que
        le premier ne compte. Deux fois la meme erreur, deux niveaux differents.

        Verifier et incrementer doivent etre le MEME geste. C'est exactement ce
        que `reserver()` fait sur le registre Faker, et pour la meme raison.
        """
        femme = (tirage.genre or "").upper() == "WOMAN"
        business = tirage.est_business

        # `EF-23` — 80/20. Le seul quota que Faker sait filtrer.
        if business and self.corporate_faits >= self.cible_corporate:
            return None
        if not business and self.individual_faits >= self.cible_individual:
            return None
        # `EF-22` — ratio deux femmes pour un homme.
        if femme and self.femmes >= self.cible_femmes:
            return None
        if not femme and self.hommes >= self.cible - self.cible_femmes:
            return None

        # Tout est ouvert : on prend, et on compte DANS LE MEME GESTE.
        if business:
            self.corporate_faits += 1
        else:
            self.individual_faits += 1
        if femme:
            self.femmes += 1
        else:
            self.hommes += 1

        # `EF-22` — 60 % de moins de 25 ans. DECIDE par nous, jamais subi :
        # aucun champ d'age n'existe en famille A.
        jeune = self.jeunes < self.cible_jeunes
        if jeune:
            self.jeunes += 1

        # `EF-24` — 20 % des professionnels en agriculture, les 80 % restants en
        # transports, commerce et services. Quatre familles du CDC, et rien
        # d'autre : aucun des 16 secteurs Faker n'est agricole.
        secteur = ""
        if business:
            if self.agricoles < self.cible_agricoles:
                secteur = "AGRICULTURE"
                self.agricoles += 1
            else:
                autres = [f for f in OCCUPATIONS_PAR_SECTEUR if f != "AGRICULTURE"]
                secteur = autres[self.corporate_faits % len(autres)]

        return Reservation(business=business, femme=femme, jeune=jeune, secteur=secteur)

    def rendre(self, reservation: Reservation) -> None:
        """Le client n'a pas abouti : on defait la reservation en entier.

        Sans cela, la cible se remplirait de clients inexistants et le rapport
        annoncerait une distribution que la base ne porte pas."""
        if reservation.business:
            self.corporate_faits -= 1
            if reservation.secteur == "AGRICULTURE":
                self.agricoles -= 1
        else:
            self.individual_faits -= 1
        if reservation.femme:
            self.femmes -= 1
        else:
            self.hommes -= 1
        if reservation.jeune:
            self.jeunes -= 1

    def ecarter(self, motif: str) -> None:
        self.ecartes[motif] = self.ecartes.get(motif, 0) + 1

    def resume(self) -> str:
        return (
            f"  {self.pays} : {self.faits}/{self.cible} · "
            f"Corp {self.corporate_faits}/{self.cible_corporate} · "
            f"Femmes {self.femmes}/{self.cible_femmes} · "
            f"<25ans {self.jeunes}/{self.cible_jeunes} · "
            f"Agri {self.agricoles}/{self.cible_agricoles}"
        )


@dataclass(slots=True)
class RapportClients:
    """Ce que l'execution a produit, ce qu'elle a ecarte, ce qui l'a genee."""

    mode: RunMode
    quotas: list[QuotaPays] = field(default_factory=list)
    crees: list[str] = field(default_factory=list)
    echoues: list[tuple[str, str]] = field(default_factory=list)
    refuses_avant_reseau: list[tuple[str, str]] = field(default_factory=list)
    alertes: list[str] = field(default_factory=list)
    #: Reservations liberees faute d'avoir produit une entite — `D-FAKER-1`.
    #: C'est un SIGNAL : un quota sature, une composition refusee, un echec
    #: serveur.
    liberes: int = 0
    #: Reservations liberees parce que le mode est A BLANC. Aucune entite n'a ete
    #: creee, donc aucun client n'est consomme — c'est le fonctionnement NORMAL,
    #: pas un signal. Compte a part pour ne pas les confondre.
    liberes_a_blanc: int = 0
    solde_dote: float = 0.0
    #: Ce que le REEL ecrirait, annonce meme a blanc — `D-01`.
    comptes_attendus: int = 0
    #: Les pays servis par la SOURCE INTERNE, et le compte produit. La
    #: provenance doit se lire au rapport (`A-01`) — mais ce n'est PAS une
    #: alerte : un ecart declare et arbitre n'est pas un echec, et le faire
    #: basculer le run en PARTIAL a chaque fois noierait les vraies alertes.
    servis_en_interne: dict[str, int] = field(default_factory=dict)

    @property
    def total_cible(self) -> int:
        return sum(q.cible for q in self.quotas)

    @property
    def statut(self) -> RunStatus:
        """`PARTIAL` est un etat terminal LEGITIME (`UC-07`, cas alternatif)."""
        if not self.echoues and not self.refuses_avant_reseau and not self.alertes:
            return RunStatus.COMPLETED
        if not self.crees:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    def resume(self) -> str:
        lignes = [
            f"Mode           : {self.mode.value}",
            f"Clients cibles : {self.total_cible}",
            f"Clients crees  : {len(self.crees)}",
            f"Comptes attendus : {self.comptes_attendus} (1 CHECKING par client, cascade)",
            *(
                [
                    "Source INTERNE : "
                    + " · ".join(f"{p} {n}" for p, n in sorted(self.servis_en_interne.items()))
                    + "  (Faker ne sert pas ces pays — arbitrage A-01)"
                ]
                if self.servis_en_interne
                else []
            ),
            f"Solde dote     : {self.solde_dote:,.2f} (A-09 — recommandation appliquee)",
            f"Reservations liberees : {self.liberes} (ecartes ou echoues — D-FAKER-1)",
            f"Liberees a blanc      : {self.liberes_a_blanc} (aucune entite creee)",
            f"Refuses avant reseau  : {len(self.refuses_avant_reseau)}",
            f"Echecs serveur        : {len(self.echoues)}",
            f"STATUT : {self.statut.value}",
        ]
        lignes.extend(q.resume() for q in self.quotas)
        for quota in self.quotas:
            if quota.ecartes:
                detail = " · ".join(f"{m} {n}" for m, n in sorted(quota.ecartes.items()))
                lignes.append(f"    {quota.pays} ecartes : {detail}")
        for alerte in self.alertes:
            lignes.append(f"  ⚠ {alerte}")
        for nom, motif in self.refuses_avant_reseau[:10]:
            lignes.append(f"  REFUS {nom} : {motif}")
        for nom, motif in self.echoues[:10]:
            lignes.append(f"  ECHEC {nom} : {motif}")
        return "\n".join(lignes)


class ExecuteurClients:
    """Genere la population client — `UC-12` et `UC-13`."""

    def __init__(
        self,
        *,
        run_id: UUID,
        mode: RunMode,
        configuration: ConfigurationExecution,
        referentiel: ReferentielGeo,
        generateur: Generateur,
        faker: FakerClient,
        client_service: ClientServiceClient,
        account_service: AccountServiceClient,
        interne: SourceIdentites | None = None,
        hierarchie: OrgHierarchyRepository,
        ledger: FakerLedgerRepository,
        produits: list[ProduitSouscriptible],
    ) -> None:
        self.run_id = run_id
        self.mode = mode
        self._configuration = configuration
        self._referentiel = referentiel
        self._generateur = generateur
        self._faker = faker
        self._interne = interne or SourceInterne()
        self._clients = client_service
        self._comptes = account_service
        self._hierarchie = hierarchie
        self._ledger = ledger
        self._produits = produits
        # Le tirage derive du `run_id` : deux executions du meme run produisent
        # les memes seeds, donc les memes clients (`ENF-15`).
        self._alea = random.Random(run_id.int ^ 0xC11E)  # noqa: S311 — reproductibilite

    @property
    def ecriture_reelle(self) -> bool:
        return self.mode is RunMode.REAL

    async def executer(self) -> RapportClients:
        rapport = RapportClients(mode=self.mode)

        kiosques = await self._kiosques_par_pays(rapport)
        collect = self._produits_collect(rapport)
        if not collect:
            return rapport

        for pays, cible in self._configuration.repartir_clients().items():
            # Un pays DESACTIVE arrive ici avec une cible de zero. Lui fabriquer
            # un quota et une alerte « EF-26 inapplicable, 0 clients non
            # generes » serait du bruit — et le rapport a blanc est lu par un
            # humain (`D-01`) : chaque ligne parasite dilue celles qui comptent.
            # Le motif de desactivation vit deja dans l'empreinte de
            # configuration persistee avec le run (`D-10`).
            if cible == 0:
                continue
            quota = QuotaPays(pays=pays, cible=cible)
            rapport.quotas.append(quota)

            if pays not in kiosques:
                # `EF-26` exige un Kiosque du pays cible. Sans arbre, on
                # n'invente pas un rattachement — on le dit.
                rapport.alertes.append(
                    f"{pays} : aucun Kiosque dans l'arbre — EF-26 inapplicable, "
                    f"{cible} clients non generes"
                )
                continue
            # Le SEUL arbitrage de source du module. Faker declare
            # `enum: ["BF","CI","CM"]` — le Senegal releve donc de la source
            # interne (CDC §321, arbitrage `A-01`). Tout le reste du chemin est
            # rigoureusement identique : meme composeur, meme registre, memes
            # quotas, memes controles.
            source = source_pour(pays, self._faker, self._interne)
            avant = quota.faits
            await self._peupler_un_pays(
                pays, quota, kiosques[pays], collect, source, rapport
            )
            # La provenance, comptee sur ce que la source a REELLEMENT produit.
            # Le compteur existait, etait rendu au rapport, et n'etait increments
            # nulle part — le meme defaut que ce projet a trouve dix fois, ici
            # dans du code ecrit dans la minute. Un champ qu'on affiche sans
            # jamais l'alimenter affiche zero, et ce zero a l'air d'un fait.
            if source is not self._faker and (produits := quota.faits - avant):
                rapport.servis_en_interne[pays] = produits

        return rapport

    # ------------------------------------------------------------------
    # Prerequis — lus, jamais supposes
    # ------------------------------------------------------------------

    async def _kiosques_par_pays(
        self, rapport: RapportClients
    ) -> dict[str, list[OrgHierarchyNode]]:
        """`EF-26` — l'arbre operationnel est la source du rattachement.

        DEFAUT TROUVE PAR LE PREMIER ESSAI A BLANC DE CE MODULE, le 11/08 : en
        `DRY_RUN`, DEPOSITAIRES n'ecrit rien dans `org_hierarchy` — logique, il
        n'ecrit rien du tout. L'arbre etait donc VIDE, CLIENTS echouait, et le run
        entier passait de `PARTIAL` a `FAILED`.

        C'est exactement le defaut que l'en-tete de ce module denonce sur les
        Kiosques (« Comptes attendus : 0 » a blanc, 354 en reel). Un rapport a
        blanc qui ne montre pas ce que le reel ferait n'en est pas un — `D-01`.

        La reponse est celle de `planifier_staff()` : quand l'arbre est vide, on
        PLANIFIE les ancres depuis le referentiel, exactement la ou DEPOSITAIRES
        placerait ses Kiosques (au quartier, `EF-16`). Le rapport dit alors que
        les ancres sont PREVUES, jamais qu'elles existent.
        """
        try:
            noeuds = await self._hierarchie.par_niveau(self.run_id, NiveauOrganisation.KIOSQUE)
        except Exception as erreur:  # pragma: no cover — defense d'exploitation
            rapport.alertes.append(f"arbre illisible : {type(erreur).__name__} — {erreur}")
            return {}

        par_pays: dict[str, list[OrgHierarchyNode]] = {}
        for noeud in noeuds:
            par_pays.setdefault(noeud.country_code.upper(), []).append(noeud)
        if par_pays:
            return par_pays

        if self.ecriture_reelle:
            # En REEL, un arbre vide est un VRAI blocage : `EF-26` exige un
            # Kiosque EXISTANT, et on n'invente pas un rattachement vers un
            # Depositaire qui n'a jamais ete cree.
            rapport.alertes.append(
                "aucun Kiosque pour ce run — DEPOSITAIRES doit etre execute en REAL "
                "avant CLIENTS, EF-26 exige un rattachement existant"
            )
            return {}

        rapport.alertes.append(
            "arbre vide (DRY_RUN) — les ancres sont PLANIFIEES depuis le referentiel, "
            "la ou DEPOSITAIRES placerait ses Kiosques. Aucune n'existe cote serveur."
        )
        return self._ancres_planifiees()

    def _ancres_planifiees(self) -> dict[str, list[OrgHierarchyNode]]:
        """Les Kiosques que DEPOSITAIRES CREERAIT — pour un essai a blanc fidele.

        Meme source que lui : les quartiers du referentiel, au pays. Les
        identifiants sont locaux et ne quittent jamais le processus : en `DRY_RUN`
        aucune ecriture ne part, et en REEL cette methode n'est pas appelee.
        """
        from uuid import uuid4

        from app.models.domain import OrgHierarchyNode as Noeud

        planifiees: dict[str, list[Noeud]] = {}
        for pays in self._configuration.pays_actifs:
            _, haut = self._configuration.resoudre("kiosques", pays)
            quartiers = [
                quartier
                for ville in self._referentiel.villes_porteuses_de_quartiers(pays)
                for quartier in self._referentiel.quartiers_de_ville(ville.city_id)
            ]
            if not quartiers:
                continue
            # On plafonne au nombre de quartiers reels : `D-12` interdit deux
            # Kiosques sur le meme quartier, et un essai a blanc qui annoncerait
            # plus de Kiosques que de quartiers mentirait sur le reel.
            nb = min(int(haut), len(quartiers))
            planifiees[pays] = [
                Noeud(
                    id=uuid4(),
                    run_id=self.run_id,
                    niveau=NiveauOrganisation.KIOSQUE,
                    parent_id=uuid4(),
                    company_id=uuid4(),
                    name=f"[prevu] Kiosque {quartiers[i].name}",
                    country_code=pays,
                    district_id=quartiers[i].district_id,
                    depositary_id=uuid4(),
                )
                for i in range(nb)
            ]
        return planifiees

    def _produits_collect(self, rapport: RapportClients) -> list[ProduitSouscriptible]:
        """`UC-13` — un Client ne souscrit qu'a des produits COLLECT.

        Le serveur accepte pourtant un `LENDING` en 201 (miroir exact de
        `FRA-223` cote Depositaire). Le filtre est donc le notre.
        """
        collect = [p for p in self._produits if p.type_produit is ProductType.COLLECT]
        if not collect:
            rapport.alertes.append(
                "aucun produit COLLECT au catalogue — `product_id` est REQUIS a "
                "l'onboarding (D-CLI-1), aucun client n'est generable"
            )
        return collect

    def _choisir_produit(
        self, collect: list[ProduitSouscriptible], categorie: ClientCategory
    ) -> ProduitSouscriptible | None:
        """La coherence Client/Produit est ENTIEREMENT a notre charge.

        `OBS-CLI-CROSSCHECK-01`, mesure du 09/08 : un Client CORPORATE souscrit a
        un produit INDIVIDUAL sans le moindre rejet. « Devant un bailleur qui
        connait le metier, c'est une incoherence visible a l'oeil nu. »
        """
        for produit in collect:
            try:
                valider_produit_client(
                    {"type": produit.type_produit.value, "category": produit.categorie},
                    categorie.value,
                )
            except OnboardingNonConforme:
                continue
            return produit
        return None

    # ------------------------------------------------------------------
    # La boucle de tirage-et-rejet
    # ------------------------------------------------------------------

    async def _peupler_un_pays(
        self,
        pays: str,
        quota: QuotaPays,
        kiosques: list[OrgHierarchyNode],
        collect: list[ProduitSouscriptible],
        source: SourceIdentites,
        rapport: RapportClients,
    ) -> None:
        """Peuple un pays PAR LOTS, en trois temps.

        DEFAUT DE MA PREMIERE VERSION, trouve en la relisant le 11/08 : la boucle
        etait SEQUENTIELLE. `for rang in range(2000): await ...` n'emploie jamais
        le semaphore de 20 workers, pourtant partage et documente. Le calcul :

            2000 x (Faker ~300 ms + onboarding ~976 ms) = **42 minutes**

        Hors budget `ENF-01` a elle seule, pour un module qui doit en occuper une
        fraction. Le plafond de concurrence existait et je ne l'utilisais pas.

        LES TROIS TEMPS, ET POURQUOI DEUX SEULEMENT SONT CONCURRENTS

            1. TIRER      concurrent — Faker est en LECTURE SEULE, aucun etat
                          partage, rien a serialiser.
            2. ARBITRER   **sequentiel, et c'est deliberé.** Les compteurs de
                          quota (`EF-22`, `EF-23`, `EF-24`) sont un etat partage :
                          les mettre a jour concurremment produirait une
                          distribution fausse — deux workers verraient tous deux
                          « il manque une femme » et en creeraient deux. La
                          reservation `D-FAKER-1` passe ici aussi : elle est
                          atomique cote MongoDB, mais l'ordre doit rester lisible.
            3. ECRIRE     concurrent — chaque onboarding est independant, et le
                          semaphore partage plafonne a 20.

        L'enregistrement au quota se fait APRES l'ecriture, sequentiellement, sur
        le resultat reel : un quota mis a jour sur une intention compterait des
        clients qui n'existent pas.
        """
        reste = quota.cible
        tours_infructueux = 0

        while reste > 0 and tours_infructueux < TOURS_INFRUCTUEUX_MAX:
            # On SUR-TIRE : une partie du lot sera ecartee par les quotas, et un
            # lot exactement dimensionne n'en remplirait jamais la cible.
            taille = min(TAILLE_LOT, reste * 2)
            depart = quota.cible - reste

            # --- 1. TIRER, concurremment -----------------------------------
            demandes = [
                (
                    self._alea.randrange(1, 10_000_000),
                    kiosques[(depart + i) % len(kiosques)],
                    self._categorie_a_tirer(quota, depart + i),
                )
                for i in range(taille)
            ]
            tirages = await asyncio.gather(
                *(source.tirer_client(pays, cat, seed) for seed, _, cat in demandes),
                return_exceptions=True,
            )

            # --- 2. ARBITRER, sequentiellement ------------------------------
            retenus: list[tuple[ClientFaker, OrgHierarchyNode, Reservation]] = []
            for (seed, kiosque, _), tirage in zip(demandes, tirages, strict=True):
                if len(retenus) >= reste:
                    break
                if isinstance(tirage, PaysSansSource | ErreurService):
                    rapport.refuses_avant_reseau.append((pays, str(tirage)[:200]))
                    return
                if isinstance(tirage, BaseException) or tirage is None:
                    quota.ecarter("faker muet")
                    continue
                # `EF-22`, `EF-23`, `EF-24` d'un seul geste : verifier ET
                # compter. La categorie et le genre sont les deux SEULS criteres
                # imposes par Faker, donc les deux seuls a pouvoir rejeter ;
                # l'age et le secteur, nous les decidons, et ils ne rejettent
                # jamais — c'est ce qui fait converger la boucle.
                reservation = quota.reserver(tirage)
                if reservation is None:
                    quota.ecarter("quota sature")
                    continue
                # `D-FAKER-1` — la reservation est ecrite AVANT toute ecriture
                # serveur. Un `find_one` prealable rouvrirait la fenetre que
                # `reserver()` existe pour fermer.
                if not await self._ledger.reserver(
                    tirage.client_id,
                    consumed_for=FakerConsumptionType.COLLECT_CLIENT,
                    country_code=pays,
                    run_id=self.run_id,
                    seed=seed,
                ):
                    # Cache deterministe : la collision est prevue par le CDC §185.
                    quota.ecarter("deja consomme")
                    continue
                # DEFAUT MESURE AU PREMIER ESSAI A BLANC : `<25ans 320/300`,
                # soit 6,7 % de DEPASSEMENT quand `ENF-13`/`CR-09` exige ±3 %.
                # `jeune_requis()` etait lu DANS le temps concurrent, ou vingt
                # appels voyaient tous « il manque un jeune ». Ma docstring
                # affirmait « l'ecart maximal est d'un client par lot » : c'etait
                # faux, l'ecart est de tout le lot.
                #
                # La decision remonte donc ICI, dans le temps SEQUENTIEL, et le
                # compteur est incremente a la reservation — pas apres l'ecriture.
                # Un quota qui se decide concurremment n'est pas un quota.
                retenus.append((tirage, kiosque, reservation))

            if not retenus:
                tours_infructueux += 1
                continue

            # --- 3. ECRIRE, concurremment -----------------------------------
            issues = await asyncio.gather(
                *(
                    self._creer(faker, kiosque, reservation, collect, rapport)
                    for faker, kiosque, reservation in retenus
                ),
                return_exceptions=True,
            )

            # L'enregistrement au quota, sequentiel, sur le resultat REEL.
            gagnes = 0
            for (faker, _, reservation), issue in zip(retenus, issues, strict=True):
                if isinstance(issue, BaseException):
                    rapport.echoues.append((faker.client_id, str(issue)[:200]))
                    issue = None
                if issue is not None:
                    gagnes += 1
                    # DEFAUT TROUVE PAR LA RECONCILIATION AU PREMIER ESSAI A
                    # BLANC — 1227 reservations orphelines. Cette methode
                    # documentait la regle (« il reserve puis LIBERE, parce que
                    # rien n'a ete produit ») et ne l'appliquait pas : a blanc,
                    # `_creer` rend un succes, donc rien ne liberait.
                    #
                    # A blanc, aucune entite n'existe : la reservation doit donc
                    # partir, sinon un essai a blanc BRULE 1500 clients Faker
                    # pour un run qui ne cree rien — et `D-FAKER-1` les
                    # interdirait a jamais au run reel qui suit.
                    #
                    # Compte a part : ce n'est pas un rejet de quota, c'est le
                    # fonctionnement normal du mode a blanc.
                    if not self.ecriture_reelle:
                        await self._ledger.liberer(faker.client_id)
                        rapport.liberes_a_blanc += 1
                    continue
                # Rien n'a ete produit : le client n'est donc pas consomme.
                # Le retenir epuiserait le vivier sans rien creer.
                # Le quota avait pre-reserve un jeune et un secteur : ils sont
                # rendus, sinon la cible se remplirait de clients inexistants.
                quota.rendre(reservation)
                await self._ledger.liberer(faker.client_id)
                rapport.liberes += 1

            reste -= gagnes
            tours_infructueux = 0 if gagnes else tours_infructueux + 1

        if reste > 0:
            rapport.alertes.append(
                f"{pays} : {quota.faits}/{quota.cible} clients — abandon apres "
                f"{TOURS_INFRUCTUEUX_MAX} lots sans aucun client retenu"
            )

    def _categorie_a_tirer(self, quota: QuotaPays, rang: int) -> str:
        """`EF-23` — 1 tirage sur 5 en Business, soit les 20 % de professionnels.

        Le seul quota que Faker sait filtrer. On le demande donc plutot que de
        l'esperer, et on cesse de le demander des que la cible est atteinte.
        """
        business = quota.corporate_faits < quota.cible_corporate and (
            quota.individual_faits >= quota.cible_individual or rang % 5 == 4
        )
        return CategorieClient.BUSINESS if business else CategorieClient.INDIVIDUAL

    async def _creer(
        self,
        faker: ClientFaker,
        kiosque: OrgHierarchyNode,
        reservation: Reservation,
        collect: list[ProduitSouscriptible],
        rapport: RapportClients,
    ) -> ClientCompose | None:
        """Compose puis ecrit UN client. Rend ce qu'il faut au quota, ou `None`.

        **Ne consulte AUCUN compteur de quota.** `jeune` et `secteur` sont
        RECUS : ils ont ete decides dans le temps sequentiel. Cette methode tourne
        concurremment, et lire un compteur ici produisait un depassement de 6,7 %
        sur `EF-22` — mesure au premier essai a blanc.
        """
        try:
            ancrage = ancrer_sur_kiosque(kiosque, self._referentiel)
            compose = composer(
                faker,
                ancrage,
                self._generateur,
                self._referentiel,
                self._alea,
                jeune=reservation.jeune,
                occupation_imposee=(
                    occupation_du_secteur(reservation.secteur, self._alea)
                    if reservation.secteur
                    else None
                ),
            )
        except CompositionImpossible as erreur:
            rapport.refuses_avant_reseau.append((faker.client_id, str(erreur)[:200]))
            return None

        produit = self._choisir_produit(collect, compose.categorie)
        if produit is None:
            rapport.refuses_avant_reseau.append(
                (
                    faker.client_id,
                    f"aucun produit COLLECT compatible avec {compose.categorie.value} — "
                    "OBS-CLI-CROSSCHECK-01, la coherence est a notre charge",
                )
            )
            return None

        nom = f"{compose.identite.first_name} {compose.identite.last_name}"

        if not self.ecriture_reelle:
            # Ce que le REEL ecrirait, annonce meme a blanc — `D-01`.
            rapport.comptes_attendus += 1
            rapport.solde_dote += solde_initial(faker)
            rapport.crees.append(f"{nom} [prevu]")
            return compose

        try:
            fiche = await self._clients.onboarder(
                msisdn=compose.msisdn,
                identity=compose.identite.en_payload(),
                product_id=produit.product_id,
                currency=compose.devise,
                category=compose.categorie,
                segment=compose.segment,
                channel=compose.canal,
                language=compose.langue,
            )
        except (OnboardingNonConforme, ErreurService) as erreur:
            rapport.echoues.append((faker.client_id, str(erreur)[:200]))
            return None

        # LE SECOND TEMPS DU WRITE-AHEAD — defaut trouve le 11/08 EN ECRIVANT LES
        # TESTS de ce module : `reserver()` etait appele avant le reseau, et
        # `confirmer()` ne l'etait NULLE PART. En REEL, les 1500 clients seraient
        # tous restes RESERVE. Consequence double : la reconciliation aurait crie
        # 1500 orphelines sur un run REUSSI, et `compter_par_usage()` — qui ne
        # compte que les consommations SCELLEES — aurait affiche ZERO client au
        # rapport. La moitie d'un write-ahead log ne vaut rien ; onzieme
        # occurrence du defaut recurrent, celle-ci dans du code du jour meme.
        await self._sceller(faker.client_id, fiche)

        # `UC-13` points 2-3 / `EF-73` — LE SOLDE INITIAL EST DEPOSE ICI.
        #
        # DEFAUT LE PLUS TROMPEUR DU 11/08 : `solde_dote` accumulait 1,04 Md FCFA
        # et le rapport l'AFFICHAIT — sans qu'aucun appel a `crediter()` existe.
        # Meme en REEL, les 2000 comptes CHECKING seraient restes a zero. Ce
        # n'etait pas un module muet : c'etait un rapport qui affirmait un fait
        # que le code ne produisait pas, et `D-01` fait de ce rapport « la
        # derniere occasion de dire non ». Un rapport qui ment lui retire sa
        # raison d'etre.
        await self._doter(compose, faker, fiche, rapport)

        # Compte APRES l'ecriture : un compteur incremente sur une intention
        # annoncerait des comptes qui n'existent pas.
        rapport.comptes_attendus += 1
        rapport.crees.append(nom)
        return compose

    async def _doter(
        self,
        compose: ClientCompose,
        faker: ClientFaker,
        fiche: dict[str, Any],
        rapport: RapportClients,
    ) -> None:
        """Depose le solde initial sur le compte CHECKING, puis le RELIT.

        LE COMPTE VIENT DE LA CASCADE, jamais de nous. `POST /clients/onboard`
        cree le Client, l'Identity et le compte CHECKING d'un seul geste ; en
        creer un ici produirait un doublon definitif (account-service n'a aucun
        `DELETE`).

        LE SOLDE SE RELIT, IL NE SE CALCULE PAS — `FRA-218` : les frais sont
        retranches du montant et credites nulle part. Un solde deduit du montant
        emis serait FAUX, et faux en silence. `rapport.solde_dote` ne compte donc
        que ce que le serveur a CONFIRME, jamais ce que nous avons demande.

        UNE DOTATION MANQUEE N'EST PAS UN ECHEC DU CLIENT. Le client existe, il
        est scelle au registre, il est utilisable. Un solde a zero est un ecart
        a signaler — pas une raison de le compter comme non cree, ce qui
        desequilibrerait les quotas `EF-22`/`EF-23`/`EF-24` pour un motif
        etranger a la distribution.
        """
        montant = solde_initial(faker)
        nom = f"{compose.identite.first_name} {compose.identite.last_name}"

        if not self.ecriture_reelle:
            # A blanc, on annonce le montant PREVU : c'est precisement ce que
            # `D-01` demande de montrer avant de dire oui.
            rapport.solde_dote += montant
            return

        compte = ClientServiceClient.account_id(fiche)
        if compte is None:
            rapport.alertes.append(
                f"{compose.faker_client_id} : la cascade n'a rendu aucun `account_id` — "
                "solde initial non depose (UC-13 pt 3). Le client existe et reste "
                "utilisable ; son compte est a zero."
            )
            return

        try:
            await self._comptes.crediter(
                self._comptes.payload_solde_initial_client(
                    compte_checking_id=compte, montant=montant, nom_client=nom
                )
            )
            confirme = await self._comptes.solde(compte)
        except ErreurService as erreur:
            rapport.alertes.append(
                f"{compose.faker_client_id} : dotation refusee — {str(erreur)[:150]}"
            )
            return

        if confirme is None:
            rapport.alertes.append(
                f"{compose.faker_client_id} : solde illisible apres dotation — "
                "compte non credite au rapport (FRA-218 : le solde se relit)"
            )
            return
        rapport.solde_dote += confirme

    async def _sceller(self, faker_client_id: str, fiche: dict[str, object]) -> None:
        """Scelle la consommation au registre — la preuve que l'entite existe.

        L'identifiant serveur n'est PAS garanti au format UUID : le contrat de
        client-service ne le declare pas, et l'ecriture reelle de ce module n'a
        jamais eu lieu. Un id illisible ne doit pas faire perdre le lien — on
        derive alors un UUID stable (uuid5 du meme id brut rend toujours le meme
        UUID) et l'id brut est journalise : la tracabilite vit dans le log.

        `ConsommationIncoherente` n'est PAS rattrapee ici, volontairement : elle
        signale qu'une entite irreversible existe hors registre ou en double —
        un defaut de cablage qui doit crier, pas un aleas d'exploitation.
        """
        brut = ClientServiceClient.identifiant(fiche)
        try:
            entite = UUID(str(brut))
        except ValueError:
            entite = uuid5(NAMESPACE_OID, f"finzuu-client:{brut}")
            logger.warning(
                "id serveur %r hors format UUID — consommation scellee sous l'UUID "
                "derive %s (stable : le meme id rend toujours le meme UUID)",
                brut,
                entite,
            )
        await self._ledger.confirmer(faker_client_id, entite)
