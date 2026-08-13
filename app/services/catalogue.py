"""
app/services/catalogue.py
=========================
Catalogue Produits — UC-11, EF-69, disciplines D-PRD-1 a D-PRD-9.

Deux catalogues, deux logiques distinctes :

**LENDING** — source `loan_json.json` (Annexe E du CDC). 4 produits au fichier,
**6 creations reelles** : `BNPL` et `ReadyToGo` portent `Category: Any`, valeur
que l'enum serveur refuse (`INV-PRD-04`, HTTP 422). Chacun est donc dedouble en
INDIVIDUAL + CORPORATE (`D-PRD-4`).

Les deux copies portent des noms DISTINCTS — `BNPL Individual` et
`BNPL Corporate`. Elles portaient le meme jusqu'au 11/08, au motif que « le
serveur n'impose aucune unicite de `name` » : c'etait confondre le permis et le
juste. `D-12` l'interdit, et la mesure du 11/08 montre pourquoi — deux
« Cotisation 20000/mois » coexistent en base avec des abonnes sur chacune.

**Les noms sont REELS, sans prefixe** — decision de Yaniv du 13/08 : « il faut
des vrais produits, pas de DEMO_ ». Le marqueur de purge (`CR-07`/`EF-63`)
vit dans `short_name`, comme les produits du serveur le font deja.

Les noms officiels de l'Annexe E — **Nano, Macro, BNPL, ReadyToGo** — sont
respectes a la lettre : `CO-02` a ete tranche par le CDC v1.2, et « Macro » n'est
pas « Micro ». Nano et Macro n'etant pas dedoubles, ils gardent leur nom nu.

**COLLECT** — 6 produits croisant `PolicyType` x `Category`, **dont 2 deja
presents en base** : « Cotisation 20000/mois » et « plastique ». Ils sont
REUTILISES, jamais dupliques (`D-PRD-9`). Les 4 nouveaux portent des noms
metier reels — jamais « Produit Test 1 ».

Trois pieges neutralises ici :

  ANO-PRD-POLICY-01  `policy` est declare OPTIONNEL au contrat mais son absence
                     provoque un HTTP 500. On en fournit toujours une, complete.
  INV-PRD-07         La Policy est une REFERENCE VIVANTE : modifier une Policy
                     modifie retroactivement et silencieusement TOUS les Products
                     qui la referencent. D'ou `D-PRD-7` — une Policy embarquee
                     par Product, JAMAIS un `policy_id` partage.
  EF-35 / CR-01      Le fichier source annonce un taux jusqu'a 25 %, or le
                     plafond d'usure BEAC/COBAC est de 24 % « meme en
                     environnement de test ». Le taux est borne ici.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.clients.contracts import PolicyMeasure, PolicyType, ProductCategory, ProductType
from app.core.cdc import PREFIXE_DONNEES, TAUX_USURE_MAX_ANNUEL_PCT

#: Correspondance segment du fichier -> valeur de l'enum serveur.
SEGMENT_VERS_ENUM: Final[dict[str, str]] = {
    "Very Low": "VERY_LOW",
    "Low": "LOW",
    "Medium": "MEDIUM",
    "High": "HIGH",
    "Very High": "VERY_HIGH",
}

#: Correspondance Category du fichier -> ProductCategory serveur.
#: « Any » n'a PAS d'equivalent : c'est ce qui impose le split D-PRD-4.
CATEGORIE_VERS_ENUM: Final[dict[str, ProductCategory]] = {
    "Individual": ProductCategory.INDIVIDUAL,
    "Business": ProductCategory.CORPORATE,
}


@dataclass(frozen=True, slots=True)
class ProduitCredit:
    """Un produit du fichier source, avant application du split."""

    nom: str
    duree_jours: int
    taux_min: float
    taux_max: float
    categorie_source: str
    montants_par_segment: dict[str, tuple[float, float]]

    @property
    def categories_cibles(self) -> tuple[ProductCategory, ...]:
        """D-PRD-4 — « Any » devient deux creations, jamais une."""
        if self.categorie_source == "Any":
            return (ProductCategory.INDIVIDUAL, ProductCategory.CORPORATE)
        return (CATEGORIE_VERS_ENUM[self.categorie_source],)

    @property
    def montant_min(self) -> float:
        return min(bornes[0] for bornes in self.montants_par_segment.values())

    @property
    def montant_max(self) -> float:
        return max(bornes[1] for bornes in self.montants_par_segment.values())

    @property
    def taux_applique(self) -> float:
        """EF-35 / CR-01 — plafond d'usure BEAC/COBAC, meme en test.

        Le fichier annonce 25 %, ce qui depasse le plafond. On borne, jamais on
        ne reprend la valeur telle quelle : CR-08 verifie ce point en recette.
        """
        return min(self.taux_max, TAUX_USURE_MAX_ANNUEL_PCT)


@dataclass(frozen=True, slots=True)
class ProduitCollecte:
    """Un produit du catalogue COLLECT, avec son statut de reutilisation."""

    nom: str
    policy_type: PolicyType
    categorie: ProductCategory
    measure: PolicyMeasure
    montant_min: float
    montant_max: float
    taux: float
    #: LE TERME D'UN DEPOT A TERME — ajoute le 12/08 sur remarque de Yaniv.
    #:
    #: « CASH_DAT il faut une duree qu'il faut attribuer. » C'est juste, et le
    #: manque etait REEL : mesure de l'OpenAPI vivant de product-service,
    #: `CollectPolicySchema` porte TREIZE champs et aucun n'est une duree —
    #: `LendingPolicySchema` en a quatre (`loan_duration`, `reconduction_day`,
    #: `recovery_day`, `penalty_day`), COLLECT en a ZERO.
    #:
    #: Le terme ne pouvait donc vivre que dans le NOM du produit (« 6 Mois »),
    #: ce qui est illisible par le code. Il est desormais une donnee, et il se
    #: materialise a la souscription dans `CollectSchema.end_date` — le seul
    #: champ temporel que collect-service expose.
    #:
    #: `None` pour `CASH` et `PRODUCT` : une cotisation reguliere et une collecte
    #: en nature n'ont pas de terme. L'invariant est verifie ci-dessous.
    duree_mois: int | None = None
    #: Le CODE COURT du produit — decision de Yaniv du 13/08 : « pas de DEMO_
    #: dans le nom, cherche des vrais produits ». Le nom devient entierement
    #: metier ; la reversibilite (`CR-07`/`EF-63`) passe dans `short_name` via
    #: `marqueur`. Explicite et non derive du nom : deux noms peuvent partager
    #: leurs initiales (« Cotisation Commercants » / « Collecte Cacao »), un
    #: code declare ne collisionne jamais en silence.
    code: str = ""

    def __post_init__(self) -> None:
        """Un `CASH_DAT` sans terme n'est pas un depot a terme, et un `CASH`
        avec terme n'est pas une cotisation. L'incoherence est refusee ICI plutot
        que decouverte a la creation de la premiere Collect — product-service
        n'expose aucun `DELETE`."""
        if (self.policy_type is PolicyType.CASH_DAT) != (self.duree_mois is not None):
            raise ValueError(
                f"{self.nom!r} : policy_type={self.policy_type.value} et "
                f"duree_mois={self.duree_mois!r} sont incoherents. CASH_DAT exige un "
                "terme ; CASH et PRODUCT n'en ont pas."
            )
        if not self.code:
            raise ValueError(
                f"{self.nom!r} : `code` absent — sans lui, `short_name` vaudrait "
                f"« {PREFIXE_DONNEES} » nu et la purge (CR-07/EF-63) perdrait son "
                "critere sur un service sans DELETE."
            )

    @property
    def nom_recherche(self) -> str:
        """Le nom sous lequel chercher en base (`GET`-avant-`POST`).

        LE NOM REEL, SANS PREFIXE — decision de Yaniv du 13/08 : « il faut des
        vrais produits, pas de DEMO_ ». La demo se fait devant des personnes ;
        un catalogue prefixe DEMO_ se lit comme un jeu d'essai, pas comme une
        IMF. Le marqueur technique vit desormais dans `short_name` (`marqueur`),
        exactement comme les produits du serveur le font deja (`plast`,
        `TP_1785841588` — mesure du 12/08). `CR-07`/`EF-63` restent tenus :
        chaque entite generee est identifiable, par son `short_name`."""
        return self.nom

    @property
    def marqueur(self) -> str:
        """Le `short_name` emis — le marqueur de purge (`CR-07`/`EF-63`).

        C'est LUI qui porte le prefixe depuis le 13/08. Sans lui, retirer
        `DEMO_` du nom aurait laisse la purge sans critere sur un service sans
        `DELETE` — le defaut silencieux que la conception §4 nommait deja."""
        return f"{PREFIXE_DONNEES}{self.code}"


#: Catalogue COLLECT cible — croisement complet PolicyType x Category (D-PRD-9).
#: Les noms sont REELS : « Collecte Cacao » est un produit d'export camerounais,
#: coherent avec « plastique » deja en base. Jamais « Produit Test 1 ».
CATALOGUE_COLLECT: Final[tuple[ProduitCollecte, ...]] = (
    # NOTRE produit d'entree, et non celui de l'environnement — decision de
    # Yaniv du 12/08 : « on ne peut pas batir un truc pourri comme le service
    # le fait ». Voir `PRODUITS_ENVIRONNEMENT` plus bas pour ce qu'on refuse.
    ProduitCollecte(
        "Cotisation Individuelle 20000/mois",
        PolicyType.CASH,
        ProductCategory.INDIVIDUAL,
        PolicyMeasure.KILOGRAM,
        1000.0,
        1000000.0,
        5.0,
        code="COTIS_IND",
    ),
    ProduitCollecte(
        "Cotisation Commercants",
        PolicyType.CASH,
        ProductCategory.CORPORATE,
        PolicyMeasure.KILOGRAM,
        5000.0,
        2000000.0,
        5.0,
        code="COTIS_CORP",
    ),
    ProduitCollecte(
        "Depot a Terme 6 Mois",
        PolicyType.CASH_DAT,
        ProductCategory.INDIVIDUAL,
        PolicyMeasure.KILOGRAM,
        50000.0,
        5000000.0,
        6.5,
        duree_mois=6,
        code="DAT6_IND",
    ),
    ProduitCollecte(
        "Depot a Terme Entreprise 12 Mois",
        PolicyType.CASH_DAT,
        ProductCategory.CORPORATE,
        PolicyMeasure.KILOGRAM,
        200000.0,
        20000000.0,
        8.0,
        duree_mois=12,
        code="DAT12_CORP",
    ),
    ProduitCollecte(
        "Collecte Plastique",
        PolicyType.PRODUCT,
        # `LITER` et non `KILOGRAM` : le plastique de recuperation se mesure au
        # volume, et c'est aussi ce que porte le produit de l'environnement.
        # `D-PRD-8` — la mesure est un choix metier, jamais un defaut.
        ProductCategory.INDIVIDUAL,
        PolicyMeasure.LITER,
        100.0,
        500000.0,
        0.0,
        code="PLAST_IND",
    ),
    # D-PRD-8 : `measure` toujours choisi explicitement. Le cacao se pese —
    # KILOGRAM est un choix metier, pas la valeur que la WebApp injecte en dur.
    ProduitCollecte(
        "Collecte Cacao",
        PolicyType.PRODUCT,
        ProductCategory.CORPORATE,
        PolicyMeasure.KILOGRAM,
        500.0,
        10000000.0,
        0.0,
        code="CACAO_CORP",
    ),
)


#: Le terme, retrouvable par NOM — prefixe ou non. `catalogue_execution`
#: construit `ProduitSouscriptible` depuis des payloads et des fiches serveur, ou
#: la duree n'existe pas : product-service ne l'accepte pas. `CATALOGUE_COLLECT`
#: reste donc la source unique, et cette table l'expose sans la dupliquer.
DUREE_MOIS_PAR_NOM: Final[dict[str, int]] = {
    nom: produit.duree_mois
    for produit in CATALOGUE_COLLECT
    if produit.duree_mois is not None
    for nom in (produit.nom, f"{PREFIXE_DONNEES}{produit.nom}")
}


def duree_mois_du_produit(nom: str) -> int | None:
    """Le terme d'un produit, ou `None` s'il n'en a pas.

    Sert a `CollectSchema.end_date` : la Collect d'un `CASH_DAT` arrive a
    echeance `duree_mois` apres sa souscription. C'est la seule facon d'exprimer
    un terme dans FinZuu — le produit n'a pas de champ pour le porter.
    """
    return DUREE_MOIS_PAR_NOM.get(nom)


#: LES DEUX PRODUITS DE L'ENVIRONNEMENT QUE NOUS N'UTILISONS PLUS — 12/08.
#:
#: `D-PRD-9` les faisait RETROUVER plutot que recreer : ils existaient deja avec
#: des abonnes, et product-service n'a ni unicite ni `DELETE`. La regle etait
#: bonne ; ce qu'elle ignorait, c'est ce qu'ils CONTIENNENT.
#:
#: MESURE DU 12/08 sur le serveur TEST :
#:
#:   « Cotisation 20000/mois »   interest_rate = 99,0 %   amount 1 000 -> 100 000
#:   « plastique »               interest_rate = 22,0 %   amount 3,0 -> 3,0
#:
#: Le produit d'ENTREE de nos 1600 clients INDIVIDUAL portait donc 99 % d'interet
#: mensuel, et « plastique » n'acceptait qu'une quantite de EXACTEMENT 3. Aucun
#: des deux ne porte le prefixe `DEMO_`, et « Cotisation 20000/mois » est deja en
#: DOUBLE en base (`ANO-PRD-UNIQ-01`).
#:
#: Trois raisons de ne plus s'en servir, et la troisieme suffit :
#:   1. Presenter 99 % d'interet mensuel a un bailleur decredibilise la demo.
#:   2. Attacher 1600 clients `DEMO_` a un produit NON prefixe casse `CR-07` :
#:      une purge ne les retrouverait pas.
#:   3. Ce sont des entites PARTAGEES. La regle du Loader est de ne jamais
#:      ecrire sur le partage — et une souscription ecrit.
#:
#: Ils restent SIGNALES au rapport, jamais consommes : l'environnement est un
#: fait qu'on constate, pas une dependance qu'on subit.
PRODUITS_ENVIRONNEMENT: Final[tuple[str, ...]] = ("Cotisation 20000/mois", "plastique")


def charger_loan_json(chemin: Path) -> list[ProduitCredit]:
    """Parser tolerant — D-PRD-5. Le fichier n'est PAS du JSON valide.

    Trois malformations confirmees :
      1. accolade racine dupliquee : `{ {...}, {...} }` — ce n'est ni un objet
         ni un tableau
      2. `Individual`, `Business`, `Any` ne sont pas entre guillemets
      3. virgules trainantes dans les blocs BNPL et ReadyToGo

    On normalise plutot que de deviner : le fichier est la source officielle du
    referent loan-simulation, et le CDC anticipait ce cas des UC-11.

    UC-11, exception : si le fichier est introuvable, l'execution s'interrompt
    avec le chemin attendu — aucun pret ne peut etre genere sans catalogue.
    """
    if not chemin.exists():
        raise FileNotFoundError(
            f"loan_json.json introuvable — aucun produit de credit ne peut etre "
            f"genere sans lui (UC-11, exception). Chemin attendu : {chemin.resolve()}"
        )

    brut = chemin.read_text(encoding="utf-8").strip()

    # 1. L'accolade racine enveloppe une SUITE d'objets : c'est un tableau.
    if brut.startswith("{") and brut.endswith("}"):
        brut = "[" + brut[1:-1].strip() + "]"

    # 2. Les valeurs de Category ne sont pas quotees.
    for mot in ("Individual", "Business", "Any"):
        brut = re.sub(rf"(?<![\"\w]){mot}(?![\"\w])", f'"{mot}"', brut)

    # 3. Virgules trainantes avant une fermeture.
    brut = re.sub(r",(\s*[}\]])", r"\1", brut)

    try:
        blocs = json.loads(brut)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"loan_json.json reste illisible apres normalisation ({exc}). "
            f"Le format source a change — le parser doit etre revu."
        ) from exc

    return [_produit_depuis_bloc(bloc) for bloc in blocs if isinstance(bloc, dict)]


def _produit_depuis_bloc(bloc: dict[str, Any]) -> ProduitCredit:
    """Le nom du produit est la SEULE cle dont la valeur est un objet."""
    nom = next(
        (cle for cle, valeur in bloc.items() if isinstance(valeur, dict)),
        "",
    )
    segments_bruts = bloc.get(nom, {}) if nom else {}
    montants = {
        segment: (float(bornes[0]), float(bornes[1]))
        for segment, bornes in segments_bruts.items()
        if isinstance(bornes, list) and len(bornes) == 2
    }
    duree = bloc.get("Duration") or [15]
    taux = bloc.get("Interest Rate") or [7, 25]
    categorie = bloc.get("Category") or ["Individual"]

    return ProduitCredit(
        nom=nom,
        duree_jours=int(duree[0]),
        taux_min=float(taux[0]),
        taux_max=float(taux[-1]),
        categorie_source=str(categorie[0]),
        montants_par_segment=montants,
    )


def policy_lending(produit: ProduitCredit, categorie: ProductCategory) -> dict[str, Any]:
    """Policy EMBARQUEE, propre a ce Product — jamais partagee (D-PRD-7).

    `amount_by_segment` porte les 5 fourchettes de l'Annexe E : c'est
    exactement ce pour quoi ce champ existe.
    """
    return {
        "name": f"{PREFIXE_DONNEES}{produit.nom}-{categorie.value}",
        "loan_duration": produit.duree_jours,
        "recovery_day": produit.duree_jours,
        "interest": produit.taux_applique,
        "interest_calculation": "DAILY",
        "interest_application": "CAPITAL",
        "amount_min": produit.montant_min,
        "amount_max": produit.montant_max,
        "penalty_type": "PERCENT",
        "penalty_percent": 2.0,
        "penalty_application": "DEBT",
        "amount_by_segment": {
            SEGMENT_VERS_ENUM[segment]: {"min_amount": bornes[0], "max_amount": bornes[1]}
            for segment, bornes in produit.montants_par_segment.items()
            if segment in SEGMENT_VERS_ENUM
        },
    }


def policy_collect(produit: ProduitCollecte) -> dict[str, Any]:
    """Policy EMBARQUEE d'un produit COLLECT.

    `measure` est TOUJOURS explicite (D-PRD-8) : la WebApp l'injecte en dur a
    KILOGRAM sans que l'operateur le sache, on ne reproduit pas ce defaut.
    """
    return {
        "name": f"{PREFIXE_DONNEES}{produit.nom}",
        "type": produit.policy_type.value,
        "interest_type": "MONTHLY",
        "interest_rate": produit.taux,
        "measure": produit.measure.value,
        "measure_price": 0.0,
        "amount_min": produit.montant_min,
        "amount_max": produit.montant_max,
        "penalty_type": "PERCENT",
        "penalty_percent": 2.0,
    }


def nom_lending(produit: ProduitCredit, categorie: ProductCategory) -> str:
    """Le nom emis pour un produit de credit — `D-PRD-4` croise `D-12`.

    LE DEFAUT, TROUVE LE 11/08
    --------------------------
    Le split `D-PRD-4` dedouble `BNPL` et `ReadyToGo` (`Category: Any` refuse par
    l'enum serveur). Les deux creations portaient **le meme nom** : deux
    `DEMO_BNPL` en base, ne differant que par un `category` INVISIBLE dans une
    interface. Le docstring du module s'en justifiait ainsi : « rendu possible
    sans conflit puisque le serveur n'impose aucune unicite de `name` ».

    **Possible n'est pas juste.** `D-12` dit l'inverse, et pour la raison exacte
    que nous avons mesuree le 11/08 : « Cotisation 20000/mois » existe deux fois
    en base, avec des abonnes SUR LES DEUX COPIES (3 et 2 clients). Deux produits
    homonymes sont strictement indiscernables a l'ecran — le defaut meme que nous
    reprochons a config-service.

    La Policy, elle, etait DEJA desambiguisee (`policy_lending` suffixe la
    categorie). Le Produit ne l'etait pas : c'est cette asymetrie qui trahissait
    l'oubli.

    La strategie de levee est celle de `D-12` : le nom tel quel quand il est
    libre — Nano et Macro ne sont pas dedoubles, ils gardent leur nom officiel
    de l'Annexe E — et un discriminant PORTEUR DE SENS la ou l'ambiguite existe.

    SANS PREFIXE depuis le 13/08 (decision de Yaniv) : le nom est celui de
    l'Annexe E, tel qu'un bailleur doit le lire. Le marqueur de purge vit dans
    `short_name` — voir `marqueur_lending`.
    """
    if len(produit.categories_cibles) == 1:
        return produit.nom
    return f"{produit.nom} {categorie.value.capitalize()}"


def marqueur_lending(produit: ProduitCredit, categorie: ProductCategory) -> str:
    """Le `short_name` d'un produit de credit — le marqueur `CR-07`/`EF-63`.

    Derive du nom OFFICIEL de l'Annexe E (quatre noms courts, sans espace ni
    homonymie : Nano, Macro, BNPL, ReadyToGo), suffixe de la categorie quand le
    split `D-PRD-4` dedouble — la meme desambiguation que `nom_lending`, sur
    l'axe technique."""
    base = f"{PREFIXE_DONNEES}{produit.nom.upper()}"
    if len(produit.categories_cibles) == 1:
        return base
    return f"{base}_{categorie.value[:4]}"


def payloads_lending(produits: list[ProduitCredit]) -> list[dict[str, Any]]:
    """Applique le split D-PRD-4 : 4 produits sources -> 6 creations."""
    payloads: list[dict[str, Any]] = []
    for produit in produits:
        for categorie in produit.categories_cibles:
            payloads.append(
                {
                    "type": ProductType.LENDING.value,
                    "name": nom_lending(produit, categorie),
                    # Le marqueur de purge — `CR-07`/`EF-63`. C'est lui qui porte
                    # `DEMO_` depuis que le nom est entierement metier (13/08).
                    "short_name": marqueur_lending(produit, categorie),
                    "category": categorie.value,
                    "segment": "ANY",
                    "description": (
                        f"Jeu de donnees DEMO Loader FinZuu — produit de credit "
                        f"{produit.nom}, {produit.duree_jours} jours, "
                        f"taux {produit.taux_applique} %"
                    ),
                    "policy": policy_lending(produit, categorie),
                    "subscription_fees": 0.0,
                }
            )
    return payloads


def payloads_collect() -> list[dict[str, Any]]:
    """Les SIX produits COLLECT a creer — croisement complet PolicyType x Category.

    Ils etaient quatre jusqu'au 12/08 : deux venaient de l'environnement
    (`D-PRD-9`). Mesure du jour : ces deux-la portent 99 % d'interet mensuel et
    une fourchette de 3 a 3. Voir `PRODUITS_ENVIRONNEMENT`.
    """
    return [
        {
            "type": ProductType.COLLECT.value,
            "name": produit.nom_recherche,
            # Le marqueur de purge — `CR-07`/`EF-63`. C'est lui qui porte
            # `DEMO_` depuis que le nom est entierement metier (13/08).
            "short_name": produit.marqueur,
            "category": produit.categorie.value,
            "segment": "ANY",
            "description": (
                f"Jeu de donnees DEMO Loader FinZuu — produit de collecte {produit.nom}"
            ),
            "policy": policy_collect(produit),
            "subscription_fees": 0.0,
        }
        for produit in CATALOGUE_COLLECT
    ]
