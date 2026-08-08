"""
app/services/geographie.py
==========================
Module Geographie — UC-05, EF-01 a EF-06.

Charge et valide le referentiel enrichi a 5 niveaux depuis
`Loader_Base_FinZuu_v1_1.xlsx`. Ce referentiel est PROPRE AU LOADER : il n'est
jamais pousse dans config-service, qui ne connait que Country.cities[] en texte
libre. Il sert uniquement a distribuer geographiquement l'arbre operationnel.

EF-02 impose la validation de l'integrite referentielle : chaque Region a un
Country parent, chaque City une Region, chaque District une City. UC-05, cas
alternatif, precise le traitement : « le Loader journalise l'incoherence et
exclut les entites enfants dependantes » — on n'interrompt donc pas, on ampute
proprement la branche orpheline.

EF-04 : ajouter un pays ne demande aucune modification de code, uniquement des
lignes dans le fichier source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl


@dataclass(frozen=True, slots=True)
class Region:
    region_id: str
    country_iso2: str
    name: str


@dataclass(frozen=True, slots=True)
class City:
    city_id: str
    country_iso2: str
    region_id: str
    name: str
    poids_economique: float


@dataclass(frozen=True, slots=True)
class District:
    district_id: str
    city_id: str
    name: str


@dataclass(slots=True)
class RapportGeographique:
    """Rapport de couverture, exige par EF-06 en debut d'execution."""

    pays: list[str] = field(default_factory=list)
    nb_regions: int = 0
    nb_villes: int = 0
    nb_quartiers: int = 0
    orphelins: list[str] = field(default_factory=list)

    def resume(self) -> str:
        lignes = [
            f"Pays      : {len(self.pays)} ({', '.join(sorted(self.pays))})",
            f"Regions   : {self.nb_regions}",
            f"Villes    : {self.nb_villes}",
            f"Quartiers : {self.nb_quartiers}",
        ]
        if self.orphelins:
            lignes.append(f"Exclus pour rattachement invalide : {len(self.orphelins)}")
            lignes.extend(f"  - {motif}" for motif in self.orphelins)
        return "\n".join(lignes)


class ReferentielGeo:
    """Arbre geographique a 5 niveaux, indexe pour un acces direct (UC-05)."""

    def __init__(
        self,
        regions: dict[str, Region],
        villes: dict[str, City],
        quartiers: dict[str, District],
        rapport: RapportGeographique,
    ) -> None:
        self.regions = regions
        self.villes = villes
        self.quartiers = quartiers
        self.rapport = rapport

    # -- Acces indexes ------------------------------------------------------

    def regions_du_pays(self, pays: str) -> list[Region]:
        return sorted(
            (r for r in self.regions.values() if r.country_iso2 == pays),
            key=lambda r: r.region_id,
        )

    def villes_de_region(self, region_id: str) -> list[City]:
        return sorted(
            (v for v in self.villes.values() if v.region_id == region_id),
            key=lambda v: v.city_id,
        )

    def quartiers_de_ville(self, city_id: str) -> list[District]:
        return sorted(
            (q for q in self.quartiers.values() if q.city_id == city_id),
            key=lambda q: q.district_id,
        )

    def villes_porteuses_de_quartiers(self, pays: str) -> list[City]:
        """Seules villes ou un Kiosque peut exister.

        UC-09, exception : « Si le referentiel geographique ne contient aucun
        district pour une ville, aucun Kiosque n'est cree dans cette ville. »
        C'est donc cette liste, et non la liste complete des villes, qui borne
        le nombre d'Agences utiles d'un pays.
        """
        avec_quartiers = {q.city_id for q in self.quartiers.values()}
        return sorted(
            (
                v
                for v in self.villes.values()
                if v.country_iso2 == pays and v.city_id in avec_quartiers
            ),
            key=lambda v: (-v.poids_economique, v.city_id),
        )

    def nb_quartiers_du_pays(self, pays: str) -> int:
        villes_pays = {v.city_id for v in self.villes.values() if v.country_iso2 == pays}
        return sum(1 for q in self.quartiers.values() if q.city_id in villes_pays)


def charger_referentiel(chemin: Path) -> ReferentielGeo:
    """Lit le classeur et valide l'emboitement (EF-01, EF-02).

    Exception EF-01 / UC-05 : si le fichier est introuvable, l'execution est
    interrompue avec le chemin attendu explicitement journalise — jamais un
    echec silencieux.
    """
    if not chemin.exists():
        raise FileNotFoundError(
            f"Referentiel geographique introuvable. Chemin attendu : {chemin.resolve()}"
        )

    classeur = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    rapport = RapportGeographique()

    pays_connus = {
        str(ligne["country_iso2"]).strip().upper()
        for ligne in _lignes(classeur, "Countries")
        if ligne.get("country_iso2")
    }
    rapport.pays = sorted(pays_connus)

    regions: dict[str, Region] = {}
    for ligne in _lignes(classeur, "Regions"):
        pays = str(ligne.get("country_iso2") or "").strip().upper()
        region_id = str(ligne.get("region_id") or "").strip()
        if not region_id:
            continue
        if pays not in pays_connus:
            rapport.orphelins.append(f"Region {region_id} : pays {pays!r} inconnu")
            continue
        regions[region_id] = Region(region_id, pays, str(ligne.get("region_name") or ""))

    villes: dict[str, City] = {}
    for ligne in _lignes(classeur, "Cities"):
        city_id = str(ligne.get("city_id") or "").strip()
        region_id = str(ligne.get("region_id") or "").strip()
        if not city_id:
            continue
        if region_id not in regions:
            rapport.orphelins.append(f"Ville {city_id} : region {region_id!r} inconnue")
            continue
        villes[city_id] = City(
            city_id=city_id,
            country_iso2=regions[region_id].country_iso2,
            region_id=region_id,
            name=str(ligne.get("city_name") or ""),
            poids_economique=_flottant(ligne.get("weight_economic")),
        )

    quartiers: dict[str, District] = {}
    for ligne in _lignes(classeur, "Districts"):
        district_id = str(ligne.get("district_id") or "").strip()
        city_id = str(ligne.get("city_id") or "").strip()
        if not district_id:
            continue
        if city_id not in villes:
            rapport.orphelins.append(f"Quartier {district_id} : ville {city_id!r} inconnue")
            continue
        quartiers[district_id] = District(
            district_id, city_id, str(ligne.get("district_name") or "")
        )

    classeur.close()

    rapport.nb_regions = len(regions)
    rapport.nb_villes = len(villes)
    rapport.nb_quartiers = len(quartiers)
    return ReferentielGeo(regions, villes, quartiers, rapport)


def _lignes(classeur: Any, feuille: str) -> list[dict[str, Any]]:
    """Lit une feuille en dictionnaires indexes par en-tete."""
    if feuille not in classeur.sheetnames:
        return []
    iterateur = classeur[feuille].iter_rows(values_only=True)
    try:
        entetes = [str(cellule).strip() if cellule else "" for cellule in next(iterateur)]
    except StopIteration:
        return []
    resultat: list[dict[str, Any]] = []
    for ligne in iterateur:
        if all(cellule is None for cellule in ligne):
            continue
        resultat.append(dict(zip(entetes, ligne, strict=False)))
    return resultat


def _flottant(valeur: Any) -> float:
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return 0.0
