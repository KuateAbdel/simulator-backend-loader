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
from dataclasses import dataclass, field, replace
from datetime import date
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Final
from uuid import NAMESPACE_OID, UUID, uuid5

from pymongo.errors import PyMongoError

from app.clients.account_service import AccountServiceClient
from app.clients.base import ErreurService
from app.clients.client_service import (
    SOUSCRIPTIONS_MAX,
    ClientServiceClient,
    OnboardingNonConforme,
    valider_produit_client,
)
from app.clients.contracts import ClientCategory, ClientSegment, ProductType
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
    PROFILS_COMPORTEMENTAUX,
)
from app.core.configuration import ConfigurationExecution
from app.models.enums import (
    EtatConsommationFaker,
    FakerConsumptionType,
    NiveauOrganisation,
    RunMode,
    RunStatus,
)
from app.repositories import FakerLedgerRepository, OrgHierarchyRepository
from app.services.clients_composition import (
    OCCUPATIONS_PAR_SECTEUR,
    ClientCompose,
    CompositionImpossible,
    ancrer_sur_kiosque,
    composer,
    occupation_du_secteur,
)
from app.services.generateur import (
    CLES_PROFIL_INTERNE,
    Generateur,
    date_de_naissance_du_client,
)
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

#: Borne haute des seeds Faker. Le CDC §185 traite `seed` comme un entier libre ;
#: cette borne vient de la mesure du 09/08, ou l'API acceptait sans broncher tout
#: entier positif. Un espace de 10^7 pour 500 tirages laisse la collision
#: negligeable, et le CDC §185 la prevoit de toute facon.
GRAINE_FAKER_MAX: Final = 10_000_000

#: `UC-13` — l'ordre METIER dans lequel un client prend ses produits Collecte.
#: Ce ne sont pas des variantes interchangeables : la cotisation est le produit
#: d'entree, le depot a terme suppose une capacite d'epargne deja constituee, et
#: la collecte en nature est une activite distincte. Le premier de cette liste
#: est celui qui part a l'onboarding, `OnboardClientSchema` exigeant `product_id`
#: des le premier appel.
ORDRE_SOUSCRIPTION: Final[tuple[str, ...]] = ("CASH", "CASH_DAT", "PRODUCT")


def _graine_faker(pays: str, rang: int) -> int:
    """La graine d'un tirage — fonction du PERIMETRE, jamais du run.

    C'est la piece qui rend `CR-03` atteignable. Deux executions du meme
    perimetre parcourent la meme sequence de clients Faker ; le registre
    `D-FAKER-1` reconnait alors ceux qui ont deja produit une entite, au lieu de
    les remplacer par de nouveaux tirages et de doubler l'ecosysteme.

    `sha256` plutot que `hash()` : le hachage des chaines est randomise par
    processus en Python, donc `hash()` changerait d'un demarrage a l'autre — le
    contraire exact de ce qu'on cherche ici.
    """
    empreinte = int(sha256(f"{pays.upper()}:{rang}".encode()).hexdigest()[:12], 16)
    return 1 + empreinte % (GRAINE_FAKER_MAX - 1)


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


#: `A-02` — les cinq strates de l'Annexe E, dans l'ordre croissant. `ANY` n'y
#: figure pas : c'est la valeur « pas de contrainte », pas une strate.
SEGMENTS_ANNEXE_E: Final[tuple[ClientSegment, ...]] = (
    ClientSegment.VERY_LOW,
    ClientSegment.LOW,
    ClientSegment.MEDIUM,
    ClientSegment.HIGH,
    ClientSegment.VERY_HIGH,
)


#: `UC-13` pt 4 — « 1 a 3 produits Collecte SELON SON PROFIL SEGMENTE ».
#:
#: Probabilite de prendre 1, 2 ou 3 produits, par strate. Le CDC fixe la BORNE
#: (1 a 3) et le PRINCIPE (selon le segment) ; les valeurs sont notre lecture,
#: declaree ici plutot que dispersee dans le code : un epargnant aise diversifie,
#: un epargnant fragile a une cotisation et rien d'autre.
#:
#: Chaque ligne somme a 1.0 — verifie par test, parce qu'une ligne mal ajustee
#: deplacerait silencieusement la distribution.
PANIER_PAR_SEGMENT: Final[dict[ClientSegment, tuple[float, float, float]]] = {
    ClientSegment.VERY_LOW: (0.85, 0.15, 0.00),
    ClientSegment.LOW: (0.65, 0.30, 0.05),
    ClientSegment.MEDIUM: (0.45, 0.40, 0.15),
    ClientSegment.HIGH: (0.25, 0.45, 0.30),
    ClientSegment.VERY_HIGH: (0.10, 0.35, 0.55),
    # `ANY` reste possible : un client compose sans segment derive (chemin de
    # repli). On lui donne la mediane plutot qu'un minimum arbitraire.
    ClientSegment.ANY: (0.45, 0.40, 0.15),
}


def _combien_de_produits(segment: ClientSegment, alea: random.Random) -> int:
    """1, 2 ou 3 — tire selon la strate du client. `UC-13` pt 4."""
    parts = PANIER_PAR_SEGMENT[segment]
    tirage, cumul = alea.random(), 0.0
    for combien, part in enumerate(parts, start=1):
        cumul += part
        if tirage < cumul:
            return combien
    return SOUSCRIPTIONS_MAX


#: `EF-67` — les quatre profils, dans l'ordre de l'Annexe D.1. L'ORDRE compte :
#: le tirage pondere parcourt la distribution cumulee dans cet ordre.
PROFILS_ORDONNES: Final[tuple[str, ...]] = (
    "BON_PAYEUR",
    "RETARD_PUIS_PAIEMENT",
    "DEFAUT_PARTIEL",
    "DEFAUT_TOTAL",
)

#: Seuil de l'Annexe D.2, derniere ligne : « Solde Mobile Money superieur a
#: 150 000 FCFA -> renforce le profil bon payeur ».
SEUIL_MOBILE_MONEY_FCFA: Final = 150_000.0


def ajuster_poids_profil(
    genre: str,
    age: int | None,
    segment: ClientSegment,
    mobile_money: float,
) -> dict[str, float]:
    """`EF-68` — l'ajustement contextuel de l'Annexe D.2, porte depuis Duhamel.

    SEPT DES NEUF REGLES, ET LES DEUX AUTRES SONT IGNOREES A DESSEIN
    ---------------------------------------------------------------
    L'Annexe D.2 pondere les quatre profils selon neuf regles. Mesure du 12/08 :

      OUI  genre feminin / masculin        `faker.genre`
      OUI  age < 22 / entre 35 et 65       date de naissance — que NOUS composons
      OUI  segment Very High / Very Low    `segment_client()` (`A-02`)
      OUI  solde Mobile Money > 150 000    `solde_initial()` (`A-09`)
      NON  historique de remboursement     absent de la famille A, et sans objet
      NON  retard maximum                  absent de la famille A, et sans objet

    Les deux dernieres exigent un historique de credit que la famille A ne porte
    pas — et qui n'aurait aucun sens ici, puisque **le Loader ne fait pas de
    prets** (`D-PRET-0`). `UC-01` prescrit exactement cette conduite : « Si une
    caracteristique est absente du payload, la regle de ponderation
    correspondante est **ignoree sans erreur** ».

    LE LOADER SERT CETTE METHODE MIEUX QUE LE SCRIPT DONT IL LA REPREND
    ------------------------------------------------------------------
    Les deux regles d'age s'appliquent CHEZ NOUS. Chez Duhamel,
    `_adjust_weights` lit `ctx.get("birth_date")` — champ qui n'existe dans AUCUN
    payload Faker, ni famille A ni famille B (verifie le 09/08). Cette branche est
    donc **du code mort dans son script**, et vivante dans le notre, parce que
    nous composons la date de naissance.

    LE PIEGE DE VOCABULAIRE, ET IL EST GRAVE
    ----------------------------------------
    `Very High` designe la **QUALITE** du client, pas son risque de defaut.
    L'Annexe D.2 dit « Segment de risque Very High -> renforce le profil BON
    PAYEUR », et le code de Duhamel le groupe avec `risk == "A"`, la meilleure
    classe. Inverser ce sens produirait une population ou les MEILLEURS clients
    font defaut — visible au premier tableau de bord.

    Les coefficients sont ceux de `_adjust_weights`, valeur par valeur.
    """
    poids = {nom: float(PROFILS_COMPORTEMENTAUX[nom]) for nom in PROFILS_ORDONNES}

    g = genre.strip().lower()
    if g in ("f", "female", "femme", "woman", "w"):
        poids["BON_PAYEUR"] *= 1.22
        poids["RETARD_PUIS_PAIEMENT"] *= 1.10
        poids["DEFAUT_PARTIEL"] *= 0.88
        poids["DEFAUT_TOTAL"] *= 0.72
    elif g in ("m", "male", "homme", "man"):
        poids["BON_PAYEUR"] *= 0.94
        poids["DEFAUT_TOTAL"] *= 1.08

    if age is not None:
        if age < 22:
            poids["DEFAUT_PARTIEL"] *= 1.15
            poids["DEFAUT_TOTAL"] *= 1.12
            poids["BON_PAYEUR"] *= 0.92
        elif age < 35:
            poids["BON_PAYEUR"] *= 1.08
            poids["RETARD_PUIS_PAIEMENT"] *= 1.05
        elif age < 50:
            poids["BON_PAYEUR"] *= 1.04
        elif age < 65:
            poids["BON_PAYEUR"] *= 1.10
            poids["DEFAUT_TOTAL"] *= 0.85
        else:
            poids["BON_PAYEUR"] *= 1.06
            poids["DEFAUT_PARTIEL"] *= 0.90

    if segment is ClientSegment.VERY_HIGH:
        poids["BON_PAYEUR"] *= 1.12
        poids["DEFAUT_TOTAL"] *= 0.82
    elif segment is ClientSegment.VERY_LOW:
        poids["DEFAUT_TOTAL"] *= 1.18
        poids["BON_PAYEUR"] *= 0.88

    if mobile_money >= SEUIL_MOBILE_MONEY_FCFA:
        poids["BON_PAYEUR"] *= 1.06
    elif 0 < mobile_money < 20_000:
        poids["DEFAUT_PARTIEL"] *= 1.05

    total = sum(poids.values()) or 1.0
    return {nom: poids[nom] / total for nom in PROFILS_ORDONNES}


def age_revolu(naissance: date, reference: date | None = None) -> int:
    """L'age en annees revolues — celui que l'Annexe D.2 pese.

    Duhamel le derive de `scoring_year - birth_year`, une soustraction d'annees
    qui se trompe de un an pour tout client dont l'anniversaire n'est pas encore
    passe. On calcule l'age REEL : sur 2000 clients, l'approximation deplacerait
    environ la moitie des cas limites d'une tranche a l'autre.
    """
    aujourd_hui = reference or date.today()
    return (
        aujourd_hui.year
        - naissance.year
        - ((aujourd_hui.month, aujourd_hui.day) < (naissance.month, naissance.day))
    )


def profil_comportemental(
    faker: ClientFaker, segment: ClientSegment, age: int | None
) -> str:
    """`EF-67` / `UC-01` — le profil de CHAQUE client genere, a sa creation.

    « Le Loader DOIT attribuer a **chaque client genere** un profil comportemental
    de remboursement parmi quatre valeurs » — pas a chaque APPROVED, pas a chaque
    pret. Le profil est une propriete du CLIENT ; un pret ne fait que la reveler.

    ANCRE AU CLIENT, JAMAIS AU RUN. Meme lecon que `D-CLI-11` et `D-CLI-12` :
    ancre sur `self._alea`, une reprise attribuerait un AUTRE profil au meme
    client, et `CR-09` mesurerait une distribution qui change d'un run a l'autre.
    """
    poids = ajuster_poids_profil(
        genre=faker.genre or "",
        age=age,
        segment=segment,
        mobile_money=solde_initial(faker),
    )
    de_ce_client = random.Random(f"profil:{faker.client_id}")  # noqa: S311
    tirage, cumul = de_ce_client.random(), 0.0
    for nom in PROFILS_ORDONNES:
        cumul += poids[nom]
        if tirage <= cumul:
            return nom
    return PROFILS_ORDONNES[-1]


def segment_client(faker: ClientFaker) -> ClientSegment:
    """Le `segment` emis a l'onboarding — `A-02`, recommandation appliquee.

    POURQUOI CE N'EST PAS « SUIVRE FAKER », ET POURQUOI ON NE PEUT PAS
    -----------------------------------------------------------------
    La doctrine du Loader est de composer a partir de la matiere de Faker. Sur
    cet axe c'est impossible, et c'est MESURE : les deux champs de segment que
    Faker porte — `metadata.behavior_segment` et
    `features.__precomputed_scores.segment` — n'appartiennent qu'a la FAMILLE B,
    et `behavior_segment` vaut 0.0 dans quatorze cas sur quinze. Nos 2000 clients
    viennent necessairement de la famille A, qui n'en porte aucun. `EF-80` est
    inapplicable tel qu'ecrit — c'est l'arbitrage `A-02`.

    Le Loader emettait donc `ANY` pour les 2000. Valeur legitime, mais elle
    aplatit un axe de six valeurs et prive la demonstration d'un relief que le
    serveur sait porter.

    LA MEME STRATE QUE LE SOLDE, PAS UNE SECONDE INVENTION
    ------------------------------------------------------
    `solde_initial()` derive deja une strate par client des onze signaux binaires
    `quick_win` que la famille A porte REELLEMENT, bornee par l'Annexe E
    (`A-09`, recommandation appliquee). Le segment est CETTE strate, projetee sur
    les cinq valeurs de l'enum serveur.

    Consequence : un client dont les signaux le placent haut a un solde eleve ET
    un segment eleve. Une seule decision coherente au lieu de deux deconnectees —
    et rien de neuf n'est invente, c'est le meme signal mesure.

    AUCUN CONFLIT AVEC LES PRODUITS N'EST POSSIBLE
    ----------------------------------------------
    Mesure du 12/08 : les huit produits du serveur portent `segment: ANY`, et
    notre propre catalogue l'emet en dur. `ANY` signifie « ouvert a tous les
    segments » : un client `VERY_HIGH` peut donc souscrire a chacun d'eux. Le
    jour ou un produit ciblerait une strate, `_produits_compatibles()` serait
    l'endroit ou l'ajouter — la coherence est deja centralisee la.
    """
    presents = sum(1 for cle in CLES_QUICK_WIN_BINAIRES if faker.quick_win.get(cle) == 1)
    total = len(CLES_QUICK_WIN_BINAIRES)
    # `presents` va de 0 a `total` inclus : la projection couvre les cinq strates
    # sans jamais deborder, y compris au maximum.
    rang = presents * len(SEGMENTS_ANNEXE_E) // (total + 1)
    return SEGMENTS_ANNEXE_E[rang]


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
    #: `EF-67` — le profil comportemental, DECIDE dans le temps sequentiel comme
    #: `jeune` et `secteur`, pour la meme raison : c'est un quota.
    profil: str = ""


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
    #: `EF-67` / `CR-09` — le compte par profil comportemental. Un dict et non
    #: quatre champs : les quatre profils sont une distribution, pas quatre
    #: proprietes independantes.
    profils_faits: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(PROFILS_ORDONNES, 0)
    )
    #: La reference d'age du run. `EF-68` pese l'age, et l'age depend d'une date
    #: de reference : la figer ici rend le profil reproductible meme si le run
    #: traverse minuit.
    reference_age: date = field(default_factory=date.today)
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

    @property
    def cible_profils(self) -> dict[str, int]:
        """`CR-09` — les quatre cibles, et leur somme vaut EXACTEMENT `cible`.

        Les poids du CDC sont des pourcentages entiers dont la somme fait 100 ;
        arrondir chacun separement peut neanmoins perdre ou gagner une unite. Le
        dernier profil absorbe donc le reste, ce qui garantit que la somme des
        cibles egale la cible du pays — sans quoi le dernier client ne trouverait
        aucun quota ouvert.
        """
        cibles: dict[str, int] = {}
        attribue = 0
        for nom in PROFILS_ORDONNES[:-1]:
            cibles[nom] = round(self.cible * PROFILS_COMPORTEMENTAUX[nom] / 100)
            attribue += cibles[nom]
        cibles[PROFILS_ORDONNES[-1]] = self.cible - attribue
        return cibles

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
        #
        # ENTRELACE, PLUS EN BLOC — correction du 12/08, et le defaut etait
        # double.
        #
        # La version precedente ecrivait `jeune = self.jeunes < self.cible_jeunes`.
        # Le compte final etait exact, mais l'ORDRE etait un artefact : les 600
        # premiers clients de chaque pays etaient TOUS des moins de 25 ans, et les
        # 400 suivants TOUS plus ages. Visible sur n'importe quel inventaire trie
        # par date de creation — et invisible dans un rapport qui ne compte que
        # des totaux.
        #
        # Le second defaut est celui qui l'a fait decouvrir. Le profil
        # comportemental est un quota GLOUTON : il sert le mieux note d'abord.
        # Avec une population ordonnee par age, les 600 jeunes vidaient le stock
        # de `BON_PAYEUR` avant que le premier client age n'arrive. Mesure :
        # moins de 25 ans -> 83,3 % de BON_PAYEUR et 0 % de DEFAUT_TOTAL, quand
        # l'Annexe D.2 dit « age < 22 renforce le defaut total ». L'ajustement de
        # Duhamel etait donc INVERSE par un artefact d'ordonnancement.
        #
        # La suite de Bresenham repartit les jeunes sur toute la sequence et rend
        # EXACTEMENT `cible_jeunes` positifs sur `cible` rangs — propriete des
        # suites de Beatty. Le plafond reste, en garde-fou : si des clients
        # echouent et que les rangs sont rejoues, il empeche tout depassement.
        rang = max(self.faits - 1, 0)
        jeune = (
            self.jeunes < self.cible_jeunes
            and (rang * self.cible_jeunes) % self.cible < self.cible_jeunes
        )
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

        # `EF-67` + `EF-68` + `CR-09` — LE PROFIL COMPORTEMENTAL, ICI ET PAS
        # AILLEURS.
        #
        # POURQUOI UN QUOTA ET NON UNE CALIBRATION. Mesure du 12/08 : en tirant le
        # profil par simple ponderation, `BON_PAYEUR` sortait a 54,2 % pour une
        # borne `CR-09` de 47-53 %. La cause n'est pas un defaut de code — c'est
        # l'arithmetique de DEUX exigences qui se composent : `EF-22` fait une
        # population aux deux tiers feminine, et `EF-68` donne aux femmes
        # `BON_PAYEUR x 1,22`. L'agregat depasse mecaniquement.
        #
        # `CR-09` donne des bornes EXACTES et nous savons deja tenir des comptes
        # exacts : c'est un quota, comme `EF-22` et `EF-23`. Le quota decide le
        # COMBIEN ; l'ajustement de Duhamel decide le QUI. Un client bien note
        # prend `BON_PAYEUR` s'il en reste ; sinon il descend d'un cran.
        #
        # Rien de la methodologie n'est trahi : les coefficients de
        # `_adjust_weights` restent intacts, valeur par valeur. Ils cessent
        # seulement d'etre une loterie pour devenir un ORDRE DE PREFERENCE.
        profil = self._attribuer_profil(tirage, femme=femme, jeune=jeune)
        return Reservation(
            business=business, femme=femme, jeune=jeune, secteur=secteur, profil=profil
        )

    def _attribuer_profil(self, tirage: ClientFaker, *, femme: bool, jeune: bool) -> str:
        """Le profil du client : son rang de preference, borne par le quota.

        L'age vient de `date_de_naissance_du_client()`, desormais ancree au client
        et donc calculable ICI, avant la composition. C'est cette correction
        (`CR-03`, 12/08) qui rend les cinq tranches d'age de l'Annexe D.2
        accessibles au moteur de quotas, la ou `reservation.jeune` n'en aurait
        offert que deux.
        """
        naissance = date_de_naissance_du_client(
            tirage.client_id, jeune=jeune, reference=self.reference_age
        )
        poids = ajuster_poids_profil(
            genre="WOMAN" if femme else "MAN",
            age=age_revolu(naissance, self.reference_age),
            segment=segment_client(tirage),
            mobile_money=solde_initial(tirage),
        )
        # TIRAGE PONDERE PARMI LES PROFILS ENCORE OUVERTS — et non « le mieux
        # note d'abord ». La difference est tout, et la mesure l'a montree.
        #
        # PREMIERE VERSION : preference stricte, le profil de poids maximal
        # d'abord. Elle donnait des totaux exacts et un `EF-68` MORT : mesure sur
        # 1000 clients, moins de 25 ans et 25 ans et plus obtenaient
        # rigoureusement 50,0 % de `BON_PAYEUR` et 12,0 % de `DEFAUT_TOTAL`.
        #
        # La raison est arithmetique. Les coefficients de l'Annexe D.2 vont de
        # x0,72 a x1,22, face a des poids de base 50/25/13/12. `BON_PAYEUR` reste
        # donc PREMIER pour la quasi-totalite des clients : l'ORDRE de preference
        # ne change presque jamais, et le quota glouton degenere en « premier
        # arrive, premier servi ». L'ajustement existait sans rien decider.
        #
        # Le tirage pondere, lui, transmet l'ecart : un client dont `BON_PAYEUR`
        # pese 61 % au lieu de 50 % a reellement plus de chances de l'obtenir, et
        # le plafond de quota garantit malgre tout le total exact. On tient les
        # deux exigences a la fois : `CR-09` par le plafond, `EF-68` par le poids.
        ouverts = [n for n in PROFILS_ORDONNES if self.profils_faits[n] < self.cible_profils[n]]
        if ouverts:
            total = sum(poids[n] for n in ouverts) or 1.0
            # Ancre au CLIENT, jamais au run — meme lecon que `D-CLI-11`.
            tirage_alea = random.Random(f"profil:{tirage.client_id}").random()  # noqa: S311
            cumul = 0.0
            for nom in ouverts:
                cumul += poids[nom] / total
                if tirage_alea <= cumul:
                    self.profils_faits[nom] += 1
                    return nom
            self.profils_faits[ouverts[-1]] += 1
            return ouverts[-1]
        # Tous les quotas atteints : impossible tant que la somme des cibles egale
        # la cible du pays, ce qu'un test scelle.
        self.profils_faits[PROFILS_ORDONNES[-1]] += 1
        return PROFILS_ORDONNES[-1]

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
        if reservation.profil:
            self.profils_faits[reservation.profil] -= 1

    def ecarter(self, motif: str) -> None:
        self.ecartes[motif] = self.ecartes.get(motif, 0) + 1

    def resume(self) -> str:
        return (
            f"  {self.pays} : {self.faits}/{self.cible} · "
            f"Corp {self.corporate_faits}/{self.cible_corporate} · "
            f"Femmes {self.femmes}/{self.cible_femmes} · "
            f"<25ans {self.jeunes}/{self.cible_jeunes} · "
            f"Agri {self.agricoles}/{self.cible_agricoles}\n"
            # `EF-67` / `CR-09` — la distribution comportementale, RENDUE. Un
            # compteur exact que le rapport ne montre pas ne prouve rien : `D-01`
            # fait de ce rapport « la derniere occasion de dire non ».
            + "        profils : "
            + " · ".join(
                f"{nom.replace('_', ' ').lower()} {n}/{self.cible_profils[nom]}"
                for nom, n in self.profils_faits.items()
            )
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
    #: `CR-03` — les clients Faker qu'un run ANTERIEUR a deja transformes en
    #: entites. Ils ne sont ni crees ni echoues : ils sont RECONNUS, et comptes
    #: dans la cible. Un second run du meme perimetre devrait n'afficher presque
    #: que ceux-la — c'est la forme observable de l'idempotence.
    deja_presents: list[str] = field(default_factory=list)
    #: `EF-26` — les rattachements Client -> Kiosque effectivement ecrits dans
    #: `org_hierarchy`. Compte APRES l'insertion, jamais sur l'intention : le
    #: rapport ne doit pas affirmer un lien que la base ne porte pas.
    rattaches: int = 0
    #: `UC-13` — les souscriptions SUPPLEMENTAIRES effectivement ecrites par
    #: `PUT /subscribe`. La premiere est faite a l'onboarding et compte dans
    #: `crees` : additionner les deux donnerait deux fois le meme fait.
    souscriptions: int = 0
    #: Ce que le REEL attacherait, annonce meme a blanc — `D-01`. Compte le
    #: panier ENTIER, premiere souscription comprise.
    souscriptions_prevues: int = 0

    @property
    def moyenne_souscriptions(self) -> float:
        """`UC-13` — le nombre moyen de produits par client. Doit tomber dans
        [1, 3] ; c'est la forme la plus lisible du respect de l'exigence."""
        return self.souscriptions_prevues / max(len(self.crees), 1)

    @property
    def total_cible(self) -> int:
        return sum(q.cible for q in self.quotas)

    @property
    def statut(self) -> RunStatus:
        """`PARTIAL` est un etat terminal LEGITIME (`UC-07`, cas alternatif)."""
        if not self.echoues and not self.refuses_avant_reseau and not self.alertes:
            return RunStatus.COMPLETED
        # `deja_presents` compte autant que `crees` ICI, et pas par elegance : un
        # second run du meme perimetre ne cree RIEN — tout est deja la. Sans
        # cette lecture il serait declare FAILED alors qu'il vient precisement de
        # DEMONTRER `CR-03`. « Le permis n'est pas le juste » a un pendant : un
        # run qui n'ecrit rien parce que tout existe est un run reussi.
        if not self.crees and not self.deja_presents:
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
            # LE COMPTEUR NE COMPTE QUE DES ECRITURES REELLES, jamais des
            # intentions — lecon du 11/08, ou `solde_dote` annonçait 1,04 Md FCFA
            # que rien ne creditait. Mais un « 0 » nu ferait croire le module
            # decable : le mode est donc dit explicitement.
            "Souscriptions UC-13   : "
            + (
                f"{len(self.crees) + self.souscriptions} "
                f"({len(self.crees)} a l'onboarding + {self.souscriptions} par PUT/subscribe)"
                if self.mode is RunMode.REAL
                else (
                    f"{self.souscriptions_prevues} prevues pour {len(self.crees)} clients "
                    f"(moyenne {self.moyenne_souscriptions:.2f} — UC-13 : 1 a 3)"
                )
            ),
            f"Rattaches EF-26       : {self.rattaches} "
            + (
                "(Client -> Kiosque dans org_hierarchy — 1er temps, CR-02)"
                if self.mode is RunMode.REAL
                else f"(aucune ecriture a blanc — {len(self.crees)} prevus en REEL)"
            ),
            f"Deja presents         : {len(self.deja_presents)} "
            "(reconnus d'un run anterieur — CR-03, aucun doublon cree)",
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

    def _produits_compatibles(
        self, collect: list[ProduitSouscriptible], categorie: ClientCategory
    ) -> list[ProduitSouscriptible]:
        """Tous les produits qu'un client de cette categorie peut souscrire.

        La coherence Client/Produit est ENTIEREMENT a notre charge.
        `OBS-CLI-CROSSCHECK-01`, mesure du 09/08 : un Client CORPORATE souscrit a
        un produit INDIVIDUAL sans le moindre rejet. « Devant un bailleur qui
        connait le metier, c'est une incoherence visible a l'oeil nu. »

        Rendait le PREMIER compatible jusqu'au 12/08. Consequence : les mille
        clients INDIVIDUAL d'un pays souscrivaient tous au meme produit, alors
        que le catalogue leur en ouvre trois (`Cotisation 20000/mois`, `Depot a
        Terme 6 Mois`, `plastique`). Un catalogue de dix produits dont un seul
        est consomme par categorie ne ressemble a aucune institution reelle.
        """
        compatibles = []
        for produit in collect:
            try:
                valider_produit_client(
                    {"type": produit.type_produit.value, "category": produit.categorie},
                    categorie.value,
                )
            except OnboardingNonConforme:
                continue
            compatibles.append(produit)
        return compatibles

    def _panier(
        self, collect: list[ProduitSouscriptible], compose: ClientCompose
    ) -> list[ProduitSouscriptible]:
        """`UC-13` — de UN a TROIS produits Collecte, DISTINCTS et ordonnes.

        TROIS CONTRAINTES MESUREES, ET AUCUNE N'EST PORTEE PAR LE SERVEUR
        ----------------------------------------------------------------
        1. Le plafond. Mesure du 09/08 : **six** produits attaches a un meme
           client, sans le moindre rejet. `SOUSCRIPTIONS_MAX = 3` est a nous.
        2. Le doublon, lui, EST refuse : `PUT /subscribe` du meme produit rend
           `400 « A customer cannot subscribe to the same products twice »`.
           Le panier doit donc etre sans repetition — un invariant qu'aucune de
           nos sources ne documentait avant le sondage.
        3. La categorie. Le serveur ne verifie rien (`OBS-CLI-CROSSCHECK-01`) ;
           `_produits_compatibles()` s'en charge en amont.

        LE TIRAGE EST ANCRE AU CLIENT, JAMAIS AU RUN
        --------------------------------------------
        C'est la lecon du 12/08, et elle s'applique ici mot pour mot. Ancre sur
        `self._alea`, une reprise attacherait d'AUTRES produits au meme client :
        le premier run lui donnerait `Cotisation` + `plastique`, le second
        `Depot a Terme` — et comme `PUT /subscribe` n'a pas de `DELETE`, le
        client finirait avec cinq produits pour un plafond de trois. Le msisdn
        est stable depuis `D-CLI-11` : il sert d'ancre.

        L'ORDRE N'EST PAS INDIFFERENT — CORRECTION DU 12/08
        ---------------------------------------------------
        Ma premiere version tirait `random.sample()` parmi les compatibles. Elle
        respectait la lettre de `UC-13` et manquait le metier : elle pouvait
        placer « plastique » EN PREMIER, donc a l'onboarding, et produire un
        client dont l'unique produit est une collecte de dechets plastiques. Ce
        n'est pas un client d'epargne — c'est du desordre.

        Les trois `PolicyType` du catalogue COLLECT ne sont pas interchangeables,
        et le CDC les distingue :

          `CASH`      la cotisation reguliere — LE PRODUIT D'ENTREE
          `CASH_DAT`  le depot a terme — suppose une capacite d'epargne
          `PRODUCT`   la collecte en nature — une activite distincte

        Le panier suit donc cet ordre, toujours. Le premier produit — celui de
        l'onboarding, `OnboardClientSchema` exigeant `product_id` des le premier
        appel — est le `CASH` du client. Les 2e et 3e s'ajoutent par
        `PUT /subscribe` dans l'ordre du metier.

        LE COMBIEN — « SELON SON PROFIL SEGMENTE », et c'est le CDC qui le dit
        ---------------------------------------------------------------------
        Correction du 12/08, apres lecture DIRECTE du CDC (question de Yaniv sur
        les produits de credit). `UC-13` point 4, mot pour mot :

            « Il souscrit le client a 1 a 3 produits Collecte
              (CASH, CASH_DAT, PRODUCT) SELON SON PROFIL SEGMENTE. »

        Ma premiere version tirait 50 / 30 / 20 sur le msisdn — deterministe et
        documente, mais AVEUGLE au segment. Le CDC ne laisse pas ce choix libre :
        le nombre de produits depend du profil. Et c'est aussi ce que la vie
        reelle dit — un epargnant `VERY_HIGH` diversifie, un `VERY_LOW` a une
        cotisation et rien d'autre.

        Le segment vient de `segment_client()` : la meme strate que
        `solde_initial()`, derivee des onze signaux `quick_win` de la famille A
        (`A-02`). Un client mieux dote prend donc plus de produits, ce qui rend
        `CR-12` (« solde = initial + decaissements - remboursements ») coherent
        avec sa capacite d'epargne au lieu de la contredire.

        La part de hasard qui reste — ancree au client, jamais au run — ne sert
        qu'a eviter que tous les clients d'un meme segment soient identiques.
        """
        compatibles = self._produits_compatibles(collect, compose.categorie)
        if not compatibles:
            return []

        # L'ordre du metier. Un produit dont le serveur ne declare pas le
        # `PolicyType` tombe en fin de liste plutot que d'etre ecarte : il reste
        # souscriptible, simplement jamais en produit d'entree.
        rang = {p: i for i, p in enumerate(ORDRE_SOUSCRIPTION)}
        ordonnes = sorted(
            compatibles, key=lambda p: (rang.get(p.policy_type, len(rang)), p.nom)
        )

        de_ce_client = random.Random(f"panier:{compose.msisdn}")  # noqa: S311
        combien = _combien_de_produits(compose.segment, de_ce_client)
        # Le doublon est refuse par le serveur — `400 « A customer cannot
        # subscribe to the same products twice »`. Une tranche d'une liste sans
        # repetition ne peut pas en produire.
        return ordonnes[: min(combien, len(ordonnes), SOUSCRIPTIONS_MAX)]

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
        #: Position dans la sequence de tirage du pays. Strictement croissante.
        rang_tirage = 0

        while reste > 0 and tours_infructueux < TOURS_INFRUCTUEUX_MAX:
            # On SUR-TIRE : une partie du lot sera ecartee par les quotas, et un
            # lot exactement dimensionne n'en remplirait jamais la cible.
            taille = min(TAILLE_LOT, reste * 2)
            depart = quota.cible - reste

            # --- 1. TIRER, concurremment -----------------------------------
            # `CR-03` — LA GRAINE NE VIENT PLUS DU RUN. Mesure du 12/08 : elle
            # etait tiree dans `self._alea`, seme par le `run_id`, donc un second
            # run reel tirait 2000 clients Faker ENTIEREMENT DIFFERENTS. Le
            # registre `D-FAKER-1` ne pouvait alors rien reconnaitre, et les 2000
            # clients du premier run se doublaient — sur des services sans
            # `DELETE`. « Idempotence, aucun doublon » echouait totalement, et en
            # silence.
            #
            # La graine est desormais fonction du PERIMETRE — pays et rang dans
            # la sequence de tirage — jamais du run. Le second run parcourt la
            # MEME sequence, retrouve les memes clients Faker, et le registre les
            # reconnait un a un. `ENF-15` demandait la reproductibilite par run :
            # un tirage fonction du perimetre la satisfait a plus forte raison.
            #
            # Le rang n'est pas `depart + i` : il ne doit JAMAIS reculer, sinon
            # un rang ecarte serait retire a l'identique a chaque tour et la
            # boucle piocherait indefiniment le meme client. Il avance a chaque
            # tirage, gagnant ou perdant.
            demandes = [
                (
                    _graine_faker(pays, rang_tirage + i),
                    kiosques[(depart + i) % len(kiosques)],
                    self._categorie_a_tirer(quota, depart + i),
                )
                for i in range(taille)
            ]
            rang_tirage += taille
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
                    # UN REFUS A TROIS CAUSES, ET LES CONFONDRE COUTAIT `CR-03`.
                    entree = await self._ledger.etat(tirage.client_id)
                    if (
                        entree is not None
                        and entree.state is EtatConsommationFaker.CONSOMME
                        and entree.run_id != self.run_id
                    ):
                        # REPRISE — une entite existe deja, nee de ce client
                        # Faker par un run anterieur. Elle fait partie de
                        # l'ecosysteme cible : on la COMPTE.
                        #
                        # CE QUI EMPECHE REELLEMENT LE DOUBLON, verifie par
                        # mutation le 12/08 : la RESERVATION DE QUOTA CONSERVEE.
                        # Ce client est bien une femme, un corporate ou un jeune
                        # deja present ; `quota.faits` atteint donc sa cible et
                        # tout tirage suivant est ecarte « quota sature ». Ma
                        # premiere redaction attribuait ce role au `reste -= 1`
                        # ci-dessous — c'etait faux, et le retirer ne creait
                        # aucun doublon.
                        #
                        # `reste -= 1` sert a autre chose, et ce n'est pas
                        # cosmetique : sans lui la boucle tourne cinq lots a vide
                        # et le run se termine sur l'alerte « abandon apres 5
                        # lots sans aucun client retenu », donc en PARTIAL. Un
                        # run de reprise parfaite serait signale comme degrade
                        # alors qu'il vient de DEMONTRER `CR-03`.
                        rapport.deja_presents.append(tirage.client_id)
                        reste -= 1
                        continue
                    # Cache deterministe : la collision est prevue par le CDC §185
                    # — mais uniquement DANS le run courant. Rendre la reservation
                    # est obligatoire : `quota.reserver()` a deja incremente.
                    #
                    # DEFAUT LATENT TROUVE EN LISANT CE CHEMIN LE 12/08 : le
                    # `rendre()` manquait. La cible se serait remplie de clients
                    # inexistants — invisible a blanc, ou le registre est vide a
                    # chaque essai, donc jamais declenche jusqu'ici.
                    quota.rendre(reservation)
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
        segment = segment_client(faker)
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
                segment=segment,
            )
        except CompositionImpossible as erreur:
            rapport.refuses_avant_reseau.append((faker.client_id, str(erreur)[:200]))
            return None

        # `EF-67` / `UC-01` — le profil vient de la RESERVATION, pas d'un tirage
        # ici. Il a ete decide dans le temps SEQUENTIEL, ou les quotas se
        # tiennent : la meme lecon que `jeune` et `secteur`, et pour la meme
        # raison. Un profil tire dans le temps concurrent aurait produit sur
        # `CR-09` l'ecart de 6,7 % que `EF-22` a connu au premier essai a blanc.
        compose = replace(compose, profil_comportemental=reservation.profil)

        panier = self._panier(collect, compose)
        if not panier:
            rapport.refuses_avant_reseau.append(
                (
                    faker.client_id,
                    f"aucun produit COLLECT compatible avec {compose.categorie.value} — "
                    "OBS-CLI-CROSSCHECK-01, la coherence est a notre charge",
                )
            )
            return None
        produit, *suivants = panier

        nom = f"{compose.identite.first_name} {compose.identite.last_name}"

        if not self.ecriture_reelle:
            # Ce que le REEL ecrirait, annonce meme a blanc — `D-01`.
            rapport.comptes_attendus += 1
            rapport.solde_dote += solde_initial(faker)
            rapport.souscriptions_prevues += len(panier)
            rapport.crees.append(f"{nom} [prevu]")
            return compose

        # `D-CLI-5` — LE `GET` AVANT LE `POST`, SECONDE LIGNE DE DEFENSE.
        #
        # Le registre `D-FAKER-1` est la premiere, et la meilleure : il connait
        # les clients Faker deja consommes. Mais il vit dans NOTRE MongoDB, que
        # rien n'empeche d'etre reinitialisee — alors que les 2000 clients, eux,
        # resteront sur un service sans `DELETE`. Le jour ou notre base est
        # perdue et pas la leur, ce `GET` est tout ce qui separe la reprise du
        # doublon.
        #
        # Il n'est devenu utile qu'aujourd'hui : le msisdn tirait son operateur
        # du `run_id`, donc la cle de recherche changeait a chaque run et cette
        # lecture n'aurait JAMAIS trouve personne. Poser le controle sans
        # stabiliser la cle aurait produit un controle decoratif — la quinzieme
        # occurrence du meme defaut.
        deja = await self._clients.chercher_par_msisdn(compose.msisdn)
        if deja is not None:
            # PAS DE SECOND CREDIT. C'est le vrai enjeu, plus que le HTTP 400 :
            # `_doter()` deposerait a nouveau le solde initial sur un compte qui
            # le porte deja, et `account-service` n'expose aucun moyen de
            # defaire un mouvement. Un doublon de client se voit ; un solde
            # double se lit comme une donnee legitime.
            # Le rattachement est REJOUE sur ce chemin. Si notre MongoDB a ete
            # perdue et que le serveur a garde ses clients, c'est la seule
            # occasion de reconstruire `org_hierarchy` — et l'index
            # `uniq_client_par_run` rend l'operation sans effet quand elle
            # existe deja.
            await self._sceller(faker.client_id, deja, kiosque, compose, rapport)
            rapport.deja_presents.append(faker.client_id)
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
        # APRES CE POINT, LE CLIENT EXISTE. RIEN NE DOIT PLUS LEVER.
        #
        # DEFAUT TROUVE LE 12/08, ET IL NE VENAIT PAS DE `UC-13` — mon panier n'a
        # fait que le reveler. Une exception imprevue dans cette phase remontait
        # jusqu'a `asyncio.gather(return_exceptions=True)`, qui la comptait en
        # ECHEC. La boucle rendait alors le quota ET liberait la reservation
        # `D-FAKER-1`, donc elle RETIRAIT un client et en creait un SECOND — sur
        # client-service, identity-service et account-service, qui n'exposent
        # aucun `DELETE`. Mesure : 84 comptes credites pour une cible de 40.
        #
        # Le POST d'onboarding est l'acte irreversible. Des qu'il a reussi, le
        # client est un succes, quoi qu'il advienne ensuite : le scellement, la
        # dotation et les souscriptions sont des enrichissements. Les manquer
        # degrade l'ecosysteme ; relacher la reservation le CORROMPT.
        #
        # `ConsommationIncoherente` est incluse volontairement. Elle signale un
        # defaut de cablage et doit crier — mais la laisser remonter ICI
        # fabriquerait le doublon qu'elle denonce. Elle crie donc au rapport, ce
        # qui suffit a faire basculer le run en PARTIAL.
        # Trois enrichissements, dans l'ordre :
        #
        #   `_sceller`            le registre `D-FAKER-1` et le rattachement `EF-26`
        #   `_doter`              `UC-13` pt 2-3 / `EF-73`. Defaut le plus trompeur
        #                         du 11/08 : `solde_dote` accumulait 1,04 Md FCFA
        #                         que le rapport AFFICHAIT sans qu'aucun appel a
        #                         `crediter()` existe. Un rapport qui ment perd sa
        #                         raison d'etre — `D-01` en fait « la derniere
        #                         occasion de dire non ».
        #   `_souscrire_le_reste` `UC-13` / `D-CLI-7`. `OnboardClientSchema` exige
        #                         `product_id` des le premier appel, donc la 1re
        #                         souscription est faite ci-dessus ; les 2e et 3e
        #                         n'ont que `PUT /clients/subscribe`. Jusqu'au
        #                         12/08 le Loader s'arretait a la premiere.
        try:
            await self._sceller(faker.client_id, fiche, kiosque, compose, rapport)
            await self._doter(compose, faker, fiche, rapport)
            await self._souscrire_le_reste(compose, suivants, rapport)
        except Exception as erreur:
            logger.exception("apres-onboarding de %s", compose.msisdn)
            rapport.alertes.append(
                f"{compose.msisdn} : client CREE, mais la suite a echoue — "
                f"{type(erreur).__name__} : {str(erreur)[:140]}. Le client est "
                "conserve : le relacher ferait recreer un DOUBLON irreversible."
            )

        # Compte APRES l'ecriture : un compteur incremente sur une intention
        # annoncerait des comptes qui n'existent pas.
        rapport.comptes_attendus += 1
        rapport.crees.append(nom)
        return compose

    async def _souscrire_le_reste(
        self,
        compose: ClientCompose,
        suivants: list[ProduitSouscriptible],
        rapport: RapportClients,
    ) -> None:
        """Attache les produits 2 et 3. Un echec n'annule JAMAIS le client.

        Meme raison que pour la dotation : le Client existe cote serveur,
        definitivement, et aucun des trois services de la cascade n'expose de
        `DELETE`. Une souscription manquante degrade la richesse de l'ecosysteme ;
        annuler le client detruirait une entite irreversible pour un motif
        secondaire. L'alerte, en revanche, est obligatoire — `UC-13` est une
        exigence, et un manquement silencieux la rendrait invisible.

        `souscrire()` relit la fiche avant chaque `PUT` et refuse au-dela de
        `SOUSCRIPTIONS_MAX` : le plafond tient meme si ce panier se trompait.
        """
        for produit in suivants:
            try:
                await self._clients.souscrire(compose.msisdn, produit.product_id)
            except (OnboardingNonConforme, ErreurService) as erreur:
                rapport.alertes.append(
                    f"{compose.msisdn} : souscription a {produit.nom} refusee — "
                    f"{type(erreur).__name__} : {str(erreur)[:120]}. UC-13 prevoit "
                    "1 a 3 produits ; le client reste valide avec ce qu'il a."
                )
                continue
            rapport.souscriptions += 1

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

    async def _sceller(
        self,
        faker_client_id: str,
        fiche: dict[str, object],
        kiosque: OrgHierarchyNode,
        compose: ClientCompose,
        rapport: RapportClients,
    ) -> None:
        """Scelle le client : registre `D-FAKER-1` ET rattachement `EF-26`.

        LES DEUX TRACES SONT INDISSOCIABLES, et les separer aurait ete l'erreur.
        Le registre dit *« ce client Faker a produit une entite »* ; le
        rattachement dit *« cette entite appartient a ce Kiosque »*. La seconde
        n'existe NULLE PART cote serveur a la creation — mesure du 09/08, la
        fiche Client rendue porte quinze cles et aucune ne rattache. `EF-26` se
        satisfait donc en deux temps, et celui-ci est le premier.

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

        # `EF-26` — LE RATTACHEMENT. Un echec ici ne perd pas le client : il
        # existe cote serveur, definitivement, et l'annuler est impossible. Mais
        # il doit CRIER, parce que sans ce noeud `CR-02` reste non verifiable et
        # la question « quels clients dans ce Kiosque ? » n'a plus de reponse.
        try:
            await self._hierarchie.ajouter_client(
                run_id=self.run_id,
                kiosque_id=kiosque.id,
                company_id=kiosque.company_id,
                # LE PAYS VIENT DU CLIENT, pas du Kiosque. Passer
                # `kiosque.country_code` rendrait le controle `CR-02`
                # tautologique — il comparerait une valeur a elle-meme et ne
                # pourrait JAMAIS echouer. C'est l'adresse de residence du
                # client, derivee de sa geographie, qui doit etre confrontee a
                # celle de son Kiosque.
                country_code=compose.identite.adresse.country,
                msisdn=compose.msisdn,
                client_id=entite,
            )
        except (ValueError, PyMongoError) as erreur:
            rapport.alertes.append(
                f"{compose.msisdn} cree mais NON RATTACHE a {kiosque.name} — "
                f"{type(erreur).__name__} : {erreur}. EF-26 exige ce lien, et il "
                "n'existe nulle part cote serveur : sans lui CR-02 reste non verifiable."
            )
            return
        rapport.rattaches += 1
