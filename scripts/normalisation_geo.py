"""
scripts/normalisation_geo.py
============================
LA norme de comparaison des toponymes — partagee par l'ingestion (GeoNames,
fichiers direction) et l'audit. Regle de geographe (22/08, Yaniv) : on
NORMALISE A L'ENTREE — un doublon de traduction ne doit jamais NAITRE, la
fusion n'est que la reparation d'hier.

Cle : sans accents, mots administratifs/directionnels TRADUITS en francais
(la langue canonique du referentiel), mots de liaison retires, ordre trie.
« Far North », « Extreme-Nord » et « Nord Extreme » donnent la meme cle.
"""

from __future__ import annotations

import unicodedata

#: Equivalences OFFICIELLES de toponymie anglais -> francais. Rien d'invente.
TRADUCTIONS = {
    "north": "nord", "south": "sud", "east": "est", "west": "ouest",
    "northern": "nord", "southern": "sud", "eastern": "est", "western": "ouest",
    "far": "extreme", "extreme": "extreme", "upper": "haut", "lower": "bas",
    "central": "centre", "centre": "centre", "center": "centre",
    "autonomous": "autonome", "district": "district", "island": "ile",
    "lake": "lac", "river": "fleuve",
}

#: Mots de liaison et etiquettes generiques, retires avant comparaison.
VIDES = {
    "de", "du", "des", "la", "le", "les", "of", "the", "d", "l",
    "region", "province", "state", "county", "prefecture", "governorate",
    "division", "area", "zone", "city", "municipality", "department",
    "departement", "wilaya", "regional",
}


def _plat(nom: str) -> list[str]:
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", nom) if unicodedata.category(c) != "Mn"
    )
    return sans_accents.lower().replace("-", " ").replace("'", " ").split()


def cle_toponyme(nom: str) -> str:
    """Cle de comparaison normalisee — utilisee par TOUTE ingestion de region."""
    mots = [TRADUCTIONS.get(m, m) for m in _plat(nom) if m not in VIDES]
    return " ".join(sorted(mots)) or " ".join(_plat(nom))


def est_francaise(nom: str) -> bool:
    """Vrai si la forme est deja francaise (aucun mot a traduire)."""
    return all(TRADUCTIONS.get(m, m) == m for m in _plat(nom) if m not in VIDES)
