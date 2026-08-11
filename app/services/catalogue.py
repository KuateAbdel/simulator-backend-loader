"""
app/services/catalogue.py
=========================
Catalogue Produits — UC-11, EF-69, disciplines D-PRD-1 a D-PRD-9.

Deux catalogues, deux logiques distinctes :

**LENDING** — source `loan_json.json` (Annexe E du CDC). 4 produits au fichier,
**6 creations reelles** : `BNPL` et `ReadyToGo` portent `Category: Any`, valeur
que l'enum serveur refuse (`INV-PRD-04`, HTTP 422). Chacun est donc dedouble en
INDIVIDUAL + CORPORATE (`D-PRD-4`). Rendu possible sans conflit puisque le
serveur n'impose aucune unicite de `name`.

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
    #: True pour les 2 produits deja presents en base : ils sont RETROUVES,
    #: jamais recrees, et gardent donc leur nom d'origine sans prefixe.
    preexistant: bool = False

    @property
    def nom_recherche(self) -> str:
        """Le nom sous lequel chercher en base (GET-avant-POST)."""
        return self.nom if self.preexistant else f"{PREFIXE_DONNEES}{self.nom}"


#: Catalogue COLLECT cible — croisement complet PolicyType x Category (D-PRD-9).
#: Les noms sont REELS : « Collecte Cacao » est un produit d'export camerounais,
#: coherent avec « plastique » deja en base. Jamais « Produit Test 1 ».
CATALOGUE_COLLECT: Final[tuple[ProduitCollecte, ...]] = (
    ProduitCollecte(
        "Cotisation 20000/mois",
        PolicyType.CASH,
        ProductCategory.INDIVIDUAL,
        PolicyMeasure.KILOGRAM,
        1000.0,
        1000000.0,
        5.0,
        preexistant=True,
    ),
    ProduitCollecte(
        "Cotisation Commercants",
        PolicyType.CASH,
        ProductCategory.CORPORATE,
        PolicyMeasure.KILOGRAM,
        5000.0,
        2000000.0,
        5.0,
    ),
    ProduitCollecte(
        "Depot a Terme 6 Mois",
        PolicyType.CASH_DAT,
        ProductCategory.INDIVIDUAL,
        PolicyMeasure.KILOGRAM,
        50000.0,
        5000000.0,
        6.5,
    ),
    ProduitCollecte(
        "Depot a Terme Entreprise 12 Mois",
        PolicyType.CASH_DAT,
        ProductCategory.CORPORATE,
        PolicyMeasure.KILOGRAM,
        200000.0,
        20000000.0,
        8.0,
    ),
    ProduitCollecte(
        "plastique",
        PolicyType.PRODUCT,
        ProductCategory.INDIVIDUAL,
        PolicyMeasure.KILOGRAM,
        100.0,
        500000.0,
        0.0,
        preexistant=True,
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
    ),
)


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


def payloads_lending(produits: list[ProduitCredit]) -> list[dict[str, Any]]:
    """Applique le split D-PRD-4 : 4 produits sources -> 6 creations."""
    payloads: list[dict[str, Any]] = []
    for produit in produits:
        for categorie in produit.categories_cibles:
            payloads.append(
                {
                    "type": ProductType.LENDING.value,
                    "name": f"{PREFIXE_DONNEES}{produit.nom}",
                    "category": categorie.value,
                    "segment": "ANY",
                    "description": (
                        f"Produit de credit {produit.nom} — {produit.duree_jours} jours, "
                        f"taux {produit.taux_applique} %"
                    ),
                    "policy": policy_lending(produit, categorie),
                    "subscription_fees": 0.0,
                }
            )
    return payloads


def payloads_collect() -> list[dict[str, Any]]:
    """Les 4 produits COLLECT a creer. Les 2 preexistants sont exclus."""
    return [
        {
            "type": ProductType.COLLECT.value,
            "name": produit.nom_recherche,
            "category": produit.categorie.value,
            "segment": "ANY",
            "description": f"Produit de collecte {produit.nom}",
            "policy": policy_collect(produit),
            "subscription_fees": 0.0,
        }
        for produit in CATALOGUE_COLLECT
        if not produit.preexistant
    ]
