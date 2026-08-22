"""
scripts/importer_referentiel_pays.py
====================================
Import des fichiers de la direction dans le REFERENTIEL DU LOADER — `C1`, 22/08.

Deux fichiers, remis par la direction et TRAITES au prealable (anomalies
corrigees : MCC UIT, accents, devises multi-valeurs, TVA et fuseaux combles) :

  1. `Import_pays_TRAITE.xlsx`  — 48 fiches pays (devise, indicatif, TVA, fuseau)
  2. `afrique_ouest_centrale_pays_villes_1.csv` — regions + villes de 24 pays

DESTINATION : la SURCOUCHE (Mongo `loader_configuration`, doc `surcouche`) —
c'est-a-dire le Loader lui-meme, JAMAIS config-service. Le Loader est le
System of Record : il est plus riche que config-service (regions, quartiers,
TVA, fuseaux — autant de champs que le serveur n'a pas de champ pour porter).
Pousser un pays vers config-service reste le geste VOLONTAIRE du Super-Admin
(`US-B6`, POST /admin/referentiels/pays).

CHAQUE ligne passe par les invariants de `SurcoucheReferentiel` (EF-02,
INV-18) — l'import ne contourne rien : ce qui est refuse est DIT et compte.
Les 4 pays cibles (CM/CI/BF/SN) ne sont pas importes : le classeur
`Loader_Base_FinZuu_v1_1.xlsx` reste leur source, deja prouvee en production.

Relance sans risque : un pays deja present est saute (GET-avant-POST local).

Usage :
    PYTHONPATH=. .venv/bin/python scripts/importer_referentiel_pays.py \
        <Import_pays_TRAITE.xlsx> <afrique_ouest_centrale_pays_villes_1.csv> \
        [--par email] [--a-blanc]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openpyxl

from app.core.database import close, connect, ensure_indexes
from app.repositories.surcouche import SurcoucheRepository
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.surcouche_referentiel import AjoutRefuse, SurcoucheReferentiel

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")


@dataclass(slots=True)
class RapportImport:
    """Ce que l'import a fait, saute, refuse — et les trous qu'il DIT."""

    pays: int = 0
    regions: int = 0
    villes: int = 0
    quartiers: int = 0
    gps: int = 0
    sautes: list[str] = field(default_factory=list)
    refus: list[str] = field(default_factory=list)
    trous: list[str] = field(default_factory=list)

#: Les 4 cibles historiques — leur source est le classeur, jamais l'import.
PAYS_DU_CLASSEUR = {"CM", "CI", "BF", "SN"}

#: Banques centrales connues des zones monetaires du fichier. Vide = inconnu,
#: on n'invente pas.
BANQUES_CENTRALES = {
    "XOF": "BCEAO", "XAF": "BEAC", "GNF": "BCRG", "NGN": "CBN", "GHS": "BoG",
    "CDF": "BCC", "KES": "CBK", "TZS": "BoT", "UGX": "BoU", "RWF": "BNR",
    "ETB": "NBE", "ZAR": "SARB", "MGA": "BFM", "AOA": "BNA", "MZN": "BM",
}

#: Regulateurs REELS, seulement ceux connus avec certitude — les autres restent
#: vides plutot qu'inventes (le systeme doit etre VRAI, exigence du 22/08).
#: finance : superviseur bancaire de la zone. telco : autorite nationale.
REGULATEURS_FINANCE = {
    "XOF": "BCEAO", "XAF": "COBAC", "GNF": "BCRG", "NGN": "CBN", "GHS": "BoG",
    "CDF": "BCC", "KES": "CBK", "TZS": "BoT", "UGX": "BoU", "RWF": "BNR",
    "ETB": "NBE", "ZAR": "SARB", "AOA": "BNA", "MZN": "BM", "MGA": "CSBF",
    "GMD": "CBG", "SLE": "BSL", "LRD": "CBL", "MRU": "BCM", "CVE": "BCV",
    "STN": "BCSTP", "BWP": "BoB", "ZMW": "BoZ", "ZWG": "RBZ", "MWK": "RBM",
    "NAD": "BoN", "LSL": "CBL-LS", "SZL": "CBE", "MUR": "BoM", "SCR": "CBS",
    "BIF": "BRB", "DJF": "BCD", "KMF": "BCC-KM", "SSP": "BoSS", "ERN": "BoE",
    "SOS": "CBS-SO",
}
REGULATEURS_TELCO = {
    "BJ": "ARCEP-BJ", "TG": "ARCEP-TG", "NE": "ARCEP-NE", "ML": "AMRTP",
    "GN": "ARPT", "NG": "NCC", "GH": "NCA", "CD": "ARPTC", "CG": "ARPCE",
    "GA": "ARCEP-GA", "TD": "ARCEP-TD", "KE": "CA-KE", "TZ": "TCRA",
    "UG": "UCC", "RW": "RURA", "ET": "ECA", "ZA": "ICASA", "MZ": "INCM",
    "MG": "ARTEC", "ZM": "ZICTA", "ZW": "POTRAZ", "MW": "MACRA",
    "BW": "BOCRA", "NA": "CRAN", "MU": "ICTA", "GM": "PURA", "SL": "NATCOM",
    "LR": "LTA", "BI": "ARCT", "CV": "ARME", "ST": "AGER",
}

#: Poids economique sur l'ECHELLE DU CLASSEUR (mesuree : 2.0 a 10.0,
#: Yaounde/Douala 10, Bamenda 6, Maroua 5) — derive de la population.
def poids_economique(population: int | None, est_capitale: bool) -> float:
    if est_capitale:
        return 10.0
    if population is None:
        return 2.0
    if population >= 1_000_000:
        return 8.0
    if population >= 500_000:
        return 6.0
    if population >= 200_000:
        return 5.0
    if population >= 100_000:
        return 4.0
    if population >= 50_000:
        return 3.0
    return 2.0


#: Coordonnees GPS REELLES (lat, lon), au centieme de degre, pour les villes
#: connues avec certitude. Une ville absente d'ici reste sans GPS (`None`,
#: tolere par le modele et le classeur — D-IDN-2) : on ne place JAMAIS une
#: ville au hasard sur la carte.
COORDONNEES: dict[tuple[str, str], tuple[float, float]] = {
    # --- Benin
    ("BJ", "cotonou"): (6.37, 2.39), ("BJ", "porto-novo"): (6.50, 2.60),
    ("BJ", "abomey-calavi"): (6.45, 2.35), ("BJ", "parakou"): (9.34, 2.63),
    ("BJ", "djougou"): (9.71, 1.67), ("BJ", "bohicon"): (7.18, 2.07),
    ("BJ", "kandi"): (11.13, 2.94), ("BJ", "lokossa"): (6.64, 1.72),
    ("BJ", "natitingou"): (10.30, 1.38), ("BJ", "nikki"): (9.94, 3.21),
    ("BJ", "ouidah"): (6.36, 2.09), ("BJ", "abomey"): (7.18, 1.99),
    ("BJ", "malanville"): (11.87, 3.38), ("BJ", "pobe"): (6.98, 2.66),
    # --- Angola
    ("AO", "luanda"): (-8.84, 13.23), ("AO", "lubango"): (-14.92, 13.49),
    ("AO", "huambo"): (-12.78, 15.74), ("AO", "benguela"): (-12.58, 13.41),
    ("AO", "lobito"): (-12.36, 13.53), ("AO", "cabinda"): (-5.55, 12.19),
    ("AO", "malanje"): (-9.54, 16.34), ("AO", "namibe"): (-15.19, 12.15),
    ("AO", "soyo"): (-6.13, 12.37), ("AO", "kuito"): (-12.38, 16.94),
    ("AO", "uige"): (-7.61, 15.06), ("AO", "menongue"): (-14.66, 17.69),
    # --- RD Congo
    ("CD", "kinshasa"): (-4.32, 15.31), ("CD", "lubumbashi"): (-11.66, 27.48),
    ("CD", "mbuji-mayi"): (-6.15, 23.60), ("CD", "kananga"): (-5.90, 22.42),
    ("CD", "kisangani"): (0.52, 25.20), ("CD", "bukavu"): (-2.49, 28.84),
    ("CD", "goma"): (-1.66, 29.22), ("CD", "likasi"): (-10.98, 26.73),
    ("CD", "kolwezi"): (-10.71, 25.47), ("CD", "tshikapa"): (-6.42, 20.80),
    ("CD", "matadi"): (-5.82, 13.46), ("CD", "uvira"): (-3.40, 29.14),
    ("CD", "bunia"): (1.56, 30.25), ("CD", "mbandaka"): (0.05, 18.26),
    ("CD", "kikwit"): (-5.04, 18.82), ("CD", "boma"): (-5.85, 13.06),
    # --- Centrafrique
    ("CF", "bangui"): (4.36, 18.55), ("CF", "bimbo"): (4.31, 18.52),
    ("CF", "berberati"): (4.26, 15.79), ("CF", "bouar"): (5.94, 15.60),
    ("CF", "bambari"): (5.77, 20.67), ("CF", "bossangoa"): (6.49, 17.45),
    ("CF", "carnot"): (4.94, 15.87), ("CF", "kaga-bandoro"): (7.00, 19.18),
    ("CF", "sibut"): (5.72, 19.08), ("CF", "mbaiki"): (3.87, 18.00),
    ("CF", "bangassou"): (4.74, 22.82), ("CF", "bria"): (6.54, 21.99),
    # --- Congo
    ("CG", "brazzaville"): (-4.27, 15.28), ("CG", "pointe-noire"): (-4.79, 11.86),
    ("CG", "dolisie"): (-4.20, 12.67), ("CG", "nkayi"): (-4.18, 13.29),
    ("CG", "ouesso"): (1.61, 16.05), ("CG", "owando"): (-0.48, 15.90),
    ("CG", "impfondo"): (1.64, 18.06), ("CG", "sibiti"): (-3.68, 13.35),
    ("CG", "madingou"): (-4.15, 13.55), ("CG", "kinkala"): (-4.36, 14.76),
    ("CG", "djambala"): (-2.55, 14.75), ("CG", "gamboma"): (-1.88, 15.86),
    # --- Cabo Verde
    ("CV", "praia"): (14.93, -23.51), ("CV", "mindelo"): (16.89, -24.98),
    ("CV", "santa maria"): (16.60, -22.90), ("CV", "assomada"): (15.10, -23.67),
    ("CV", "espargos"): (16.76, -22.95), ("CV", "sao filipe"): (14.90, -24.50),
    ("CV", "tarrafal"): (15.28, -23.75),
    # --- Gabon
    ("GA", "libreville"): (0.39, 9.45), ("GA", "port-gentil"): (-0.72, 8.78),
    ("GA", "franceville"): (-1.63, 13.58), ("GA", "oyem"): (1.60, 11.58),
    ("GA", "moanda"): (-1.57, 13.20), ("GA", "mouila"): (-1.87, 11.06),
    ("GA", "lambarene"): (-0.70, 10.24), ("GA", "tchibanga"): (-2.85, 11.02),
    ("GA", "koulamoutou"): (-1.14, 12.48), ("GA", "makokou"): (0.57, 12.86),
    ("GA", "bitam"): (2.08, 11.49),
    # --- Ghana
    ("GH", "accra"): (5.56, -0.20), ("GH", "kumasi"): (6.69, -1.62),
    ("GH", "tamale"): (9.40, -0.84), ("GH", "sekondi-takoradi"): (4.93, -1.71),
    ("GH", "sunyani"): (7.34, -2.33), ("GH", "cape coast"): (5.11, -1.25),
    ("GH", "obuasi"): (6.20, -1.66), ("GH", "tema"): (5.67, -0.02),
    ("GH", "koforidua"): (6.09, -0.26), ("GH", "ho"): (6.60, 0.47),
    ("GH", "wa"): (10.06, -2.50), ("GH", "bolgatanga"): (10.79, -0.85),
    ("GH", "techiman"): (7.59, -1.94), ("GH", "ashaiman"): (5.70, -0.03),
    # --- Gambie
    ("GM", "banjul"): (13.45, -16.58), ("GM", "serekunda"): (13.44, -16.68),
    ("GM", "brikama"): (13.27, -16.65), ("GM", "bakau"): (13.48, -16.68),
    ("GM", "farafenni"): (13.57, -15.60), ("GM", "basse santa su"): (13.31, -14.22),
    ("GM", "lamin"): (13.35, -16.65),
    # --- Guinee
    ("GN", "conakry"): (9.64, -13.58), ("GN", "nzerekore"): (7.76, -8.82),
    ("GN", "kankan"): (10.39, -9.31), ("GN", "kindia"): (10.06, -12.86),
    ("GN", "labe"): (11.32, -12.29), ("GN", "mamou"): (10.38, -12.09),
    ("GN", "boke"): (10.94, -14.30), ("GN", "kissidougou"): (9.19, -10.10),
    ("GN", "gueckedou"): (8.57, -10.13), ("GN", "siguiri"): (11.42, -9.17),
    ("GN", "faranah"): (10.04, -10.74), ("GN", "macenta"): (8.54, -9.47),
    ("GN", "kamsar"): (10.65, -14.61), ("GN", "fria"): (10.45, -13.54),
    ("GN", "dabola"): (10.75, -11.11),
    # --- Guinee equatoriale
    ("GQ", "malabo"): (3.75, 8.78), ("GQ", "bata"): (1.86, 9.77),
    ("GQ", "ebebiyin"): (2.15, 11.34), ("GQ", "mongomo"): (1.63, 11.32),
    ("GQ", "evinayong"): (1.44, 10.55), ("GQ", "luba"): (3.46, 8.55),
    # --- Guinee-Bissau
    ("GW", "bissau"): (11.86, -15.60), ("GW", "bafata"): (12.17, -14.66),
    ("GW", "gabu"): (12.28, -14.22), ("GW", "cacheu"): (12.27, -16.17),
    ("GW", "canchungo"): (12.07, -16.03), ("GW", "farim"): (12.48, -15.22),
    ("GW", "bolama"): (11.58, -15.48), ("GW", "buba"): (11.59, -14.99),
    # --- Liberia
    ("LR", "monrovia"): (6.30, -10.80), ("LR", "gbarnga"): (6.99, -9.47),
    ("LR", "buchanan"): (5.88, -10.05), ("LR", "kakata"): (6.53, -10.35),
    ("LR", "zwedru"): (6.07, -8.13), ("LR", "harper"): (4.38, -7.72),
    ("LR", "voinjama"): (8.42, -9.75), ("LR", "ganta"): (7.24, -8.98),
    ("LR", "robertsport"): (6.75, -11.37), ("LR", "sanniquellie"): (7.36, -8.71),
    # --- Mali
    ("ML", "bamako"): (12.64, -8.00), ("ML", "sikasso"): (11.32, -5.67),
    ("ML", "segou"): (13.43, -6.27), ("ML", "mopti"): (14.49, -4.18),
    ("ML", "koutiala"): (12.39, -5.46), ("ML", "kayes"): (14.44, -11.44),
    ("ML", "gao"): (16.27, -0.04), ("ML", "tombouctou"): (16.77, -3.01),
    ("ML", "kati"): (12.75, -8.07), ("ML", "san"): (13.30, -4.90),
    ("ML", "kidal"): (18.44, 1.41), ("ML", "bougouni"): (11.42, -7.48),
    # --- Niger
    ("NE", "niamey"): (13.51, 2.11), ("NE", "zinder"): (13.80, 8.99),
    ("NE", "maradi"): (13.49, 7.10), ("NE", "agadez"): (16.97, 7.99),
    ("NE", "tahoua"): (14.89, 5.26), ("NE", "dosso"): (13.05, 3.19),
    ("NE", "diffa"): (13.32, 12.61), ("NE", "tillaberi"): (14.21, 1.45),
    ("NE", "arlit"): (18.74, 7.39), ("NE", "birni n'konni"): (13.80, 5.25),
    # --- Nigeria
    ("NG", "lagos"): (6.52, 3.38), ("NG", "abuja"): (9.06, 7.49),
    ("NG", "kano"): (12.00, 8.52), ("NG", "ibadan"): (7.38, 3.90),
    ("NG", "port harcourt"): (4.82, 7.03), ("NG", "benin city"): (6.34, 5.63),
    ("NG", "kaduna"): (10.52, 7.44), ("NG", "enugu"): (6.44, 7.49),
    ("NG", "aba"): (5.11, 7.37), ("NG", "jos"): (9.90, 8.86),
    ("NG", "ilorin"): (8.50, 4.55), ("NG", "onitsha"): (6.17, 6.79),
    ("NG", "abeokuta"): (7.15, 3.35), ("NG", "owerri"): (5.48, 7.03),
    ("NG", "maiduguri"): (11.85, 13.16), ("NG", "zaria"): (11.08, 7.70),
    ("NG", "warri"): (5.52, 5.75), ("NG", "sokoto"): (13.06, 5.24),
    ("NG", "calabar"): (4.98, 8.33), ("NG", "uyo"): (5.04, 7.92),
    ("NG", "katsina"): (12.99, 7.60), ("NG", "akure"): (7.25, 5.20),
    ("NG", "bauchi"): (10.31, 9.84), ("NG", "minna"): (9.61, 6.55),
    ("NG", "makurdi"): (7.73, 8.53), ("NG", "yola"): (9.21, 12.48),
    ("NG", "osogbo"): (7.77, 4.56), ("NG", "lokoja"): (7.80, 6.74),
    ("NG", "abakaliki"): (6.32, 8.11), ("NG", "asaba"): (6.20, 6.73),
    # --- Sierra Leone
    ("SL", "freetown"): (8.48, -13.23), ("SL", "bo"): (7.96, -11.74),
    ("SL", "kenema"): (7.88, -11.19), ("SL", "makeni"): (8.88, -12.04),
    ("SL", "koidu"): (8.64, -10.97), ("SL", "port loko"): (8.77, -12.79),
    ("SL", "waterloo"): (8.34, -13.07),
    # --- Sao Tome-et-Principe
    ("ST", "sao tome"): (0.34, 6.73), ("ST", "trindade"): (0.30, 6.68),
    ("ST", "neves"): (0.36, 6.55), ("ST", "santana"): (0.26, 6.74),
    ("ST", "santo antonio"): (1.64, 7.42), ("ST", "guadalupe"): (0.38, 6.64),
    # --- Tchad
    ("TD", "n'djamena"): (12.11, 15.05), ("TD", "moundou"): (8.57, 16.08),
    ("TD", "sarh"): (9.14, 18.39), ("TD", "abeche"): (13.83, 20.83),
    ("TD", "kelo"): (9.31, 15.81), ("TD", "koumra"): (8.91, 17.55),
    ("TD", "pala"): (9.36, 14.90), ("TD", "am timan"): (11.03, 20.28),
    ("TD", "bongor"): (10.28, 15.37), ("TD", "mongo"): (12.19, 18.69),
    ("TD", "doba"): (8.66, 16.85), ("TD", "ati"): (13.22, 18.34),
    ("TD", "faya-largeau"): (17.93, 19.10), ("TD", "mao"): (14.12, 15.31),
    # --- Togo
    ("TG", "lome"): (6.13, 1.22), ("TG", "sokode"): (8.98, 1.13),
    ("TG", "kara"): (9.55, 1.19), ("TG", "kpalime"): (6.90, 0.63),
    ("TG", "atakpame"): (7.53, 1.13), ("TG", "dapaong"): (10.86, 0.21),
    ("TG", "tsevie"): (6.43, 1.21), ("TG", "aneho"): (6.23, 1.60),
    ("TG", "notse"): (6.95, 1.17), ("TG", "sotouboua"): (8.56, 0.98),
    ("TG", "bassar"): (9.25, 0.78), ("TG", "mango"): (10.36, 0.47),
    ("TG", "niamtougou"): (9.77, 1.10),
}


def gps(iso: str, nom: str) -> tuple[float | None, float | None]:
    couple = COORDONNEES.get((iso, nom.lower()))
    return couple if couple else (None, None)


#: QUARTIERS REELS des grandes villes — communes et arrondissements OFFICIELS
#: (Conakry a 5 communes, Kinshasa ses communes de Gombe a Masina, Brazzaville
#: ses arrondissements...). C'est la que les kiosques se concentreront
#: (poids 8-10). Une ville absente d'ici reste SANS quartier et le rapport le
#: dit : un quartier invente serait un mensonge visible par quiconque connait
#: la ville. zone_type : commercial / residential / industrial.
QUARTIERS_REELS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("GN", "conakry"): [("Kaloum", "commercial"), ("Dixinn", "residential"),
                        ("Matam", "residential"), ("Ratoma", "residential"),
                        ("Matoto", "residential")],
    ("BJ", "cotonou"): [("Ganhi", "commercial"), ("Akpakpa", "residential"),
                        ("Cadjehoun", "residential"), ("Fidjrosse", "residential"),
                        ("Gbegamey", "residential"), ("Zongo", "commercial")],
    ("BJ", "porto-novo"): [("Ouando", "residential"), ("Tokpota", "residential"),
                           ("Houinme", "commercial")],
    ("TG", "lome"): [("Be", "residential"), ("Tokoin", "residential"),
                     ("Nyekonakpoe", "residential"), ("Adidogome", "residential"),
                     ("Agoe", "residential"), ("Hedzranawoe", "commercial")],
    ("NE", "niamey"): [("Plateau", "commercial"), ("Yantala", "residential"),
                       ("Gamkalle", "residential"), ("Lamorde", "residential"),
                       ("Talladje", "residential")],
    ("ML", "bamako"): [("Niarela", "commercial"), ("ACI 2000", "commercial"),
                       ("Hamdallaye", "residential"), ("Badalabougou", "residential"),
                       ("Lafiabougou", "residential"), ("Magnambougou", "residential")],
    ("NG", "lagos"): [("Victoria Island", "commercial"), ("Ikeja", "commercial"),
                      ("Ikoyi", "residential"), ("Surulere", "residential"),
                      ("Yaba", "residential"), ("Lekki", "residential"),
                      ("Apapa", "industrial"), ("Agege", "residential")],
    ("NG", "abuja"): [("Wuse", "commercial"), ("Garki", "commercial"),
                      ("Maitama", "residential"), ("Asokoro", "residential"),
                      ("Gwarinpa", "residential")],
    ("NG", "kano"): [("Fagge", "commercial"), ("Sabon Gari", "commercial"),
                     ("Nassarawa", "residential")],
    ("GH", "accra"): [("Osu", "commercial"), ("Adabraka", "commercial"),
                      ("Dansoman", "residential"), ("Madina", "residential"),
                      ("Labone", "residential"), ("Nima", "residential"),
                      ("Achimota", "residential")],
    ("GH", "kumasi"): [("Adum", "commercial"), ("Asafo", "commercial"),
                       ("Bantama", "residential"), ("Suame", "industrial")],
    ("CD", "kinshasa"): [("Gombe", "commercial"), ("Limete", "industrial"),
                         ("Ngaliema", "residential"), ("Masina", "residential"),
                         ("Lemba", "residential"), ("Matete", "residential"),
                         ("Kalamu", "residential"), ("Bandalungwa", "residential")],
    ("CD", "lubumbashi"): [("Kampemba", "residential"), ("Katuba", "residential"),
                           ("Kenya", "residential"), ("Ruashi", "industrial")],
    ("CG", "brazzaville"): [("Poto-Poto", "commercial"), ("Bacongo", "residential"),
                            ("Moungali", "commercial"), ("Ouenze", "residential"),
                            ("Talangai", "residential"), ("Makelekele", "residential")],
    ("CG", "pointe-noire"): [("Lumumba", "commercial"), ("Mvou-Mvou", "residential"),
                             ("Tie-Tie", "residential"), ("Loandjili", "residential")],
    ("GA", "libreville"): [("Louis", "commercial"), ("Glass", "residential"),
                           ("Nombakele", "commercial"), ("Akebe", "residential"),
                           ("Lalala", "residential"), ("Nzeng-Ayong", "residential")],
    ("CF", "bangui"): [("Centre-ville", "commercial"), ("PK5", "commercial"),
                       ("Lakouanga", "residential"), ("Miskine", "residential"),
                       ("Boy-Rabe", "residential"), ("Fatima", "residential")],
    ("TD", "n'djamena"): [("Dembe", "commercial"), ("Klemat", "residential"),
                          ("Moursal", "residential"), ("Chagoua", "residential"),
                          ("Farcha", "industrial"), ("Diguel", "residential")],
    ("GW", "bissau"): [("Bandim", "commercial"), ("Bairro Militar", "residential"),
                       ("Antula", "residential"), ("Ajuda", "residential")],
    ("SL", "freetown"): [("Aberdeen", "residential"), ("Kissy", "residential"),
                         ("Wellington", "industrial"), ("Hill Station", "residential"),
                         ("Congo Town", "residential"), ("Lumley", "residential")],
    ("LR", "monrovia"): [("Central Monrovia", "commercial"), ("Sinkor", "residential"),
                         ("Congo Town", "residential"), ("Mamba Point", "residential"),
                         ("New Kru Town", "residential"), ("Gardnersville", "residential")],
    ("GM", "serekunda"): [("Latrikunda", "residential"), ("Bundung", "residential"),
                          ("Dippa Kunda", "residential")],
    ("AO", "luanda"): [("Ingombota", "commercial"), ("Maianga", "residential"),
                       ("Rangel", "residential"), ("Sambizanga", "residential"),
                       ("Viana", "industrial"), ("Talatona", "residential"),
                       ("Cazenga", "residential")],
    ("CV", "praia"): [("Plateau", "commercial"), ("Achada Santo Antonio", "residential"),
                      ("Palmarejo", "residential"), ("Fazenda", "residential")],
}


def _texte(valeur: object) -> str:
    if valeur is None:
        return ""
    return re.sub(r"\s{2,}", " ", str(valeur).replace("\xa0", " ").replace("\t", " ")).strip()


def lire_fiches_pays(chemin: Path) -> list[dict[str, Any]]:
    """CountryList du fichier TRAITE — TVA et fuseau y sont deja combles."""
    feuille = openpyxl.load_workbook(chemin, data_only=True)["CountryList"]
    fiches: list[dict[str, Any]] = []
    for ligne in feuille.iter_rows(min_row=2, values_only=True):
        iso = _texte(ligne[13]).upper()
        if not iso:
            continue
        fiches.append(
            {
                "iso2": iso,
                "dial_code": _texte(ligne[0]),
                "nom_en": _texte(ligne[1]),
                "nom_fr": _texte(ligne[2]),
                "capitale": _texte(ligne[3]),
                "devise_iso": _texte(ligne[14]).upper(),
                "devise_decimales": int(ligne[15] or 0),
                "devise_nom": _texte(ligne[16]),
                "region_africa": _texte(ligne[17]),
                "timezone": _texte(ligne[18]),
                "tva_percent": float(ligne[19] or 0.0),
            }
        )
    return fiches


def lire_geographie(chemin: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """CSV regions+villes -> {iso: {region_fr: [villes]}}. Le marqueur
    « (capitale) » du fichier devient le drapeau `est_capitale_pays`."""
    arbre: dict[str, dict[str, list[dict[str, Any]]]] = {}
    with chemin.open(encoding="utf-8") as source:
        for ligne in csv.DictReader(source):
            iso = _texte(ligne["Country_ISO"]).upper()
            region = _texte(ligne["Region_FR"])
            nom_brut = _texte(ligne["Ville_FR"])
            capitale = "(capitale" in nom_brut.lower()
            nom = re.sub(r"\s*\((capitale|capital)\)\s*", "", nom_brut, flags=re.I).strip()
            population = ligne.get("Population_Estimee_Ville", "").strip()
            arbre.setdefault(iso, {}).setdefault(region, []).append(
                {
                    "nom": nom,
                    "population": int(population) if population.isdigit() else None,
                    "est_capitale_pays": capitale,
                }
            )
    return arbre


async def importer(fiches: Path, geographie: Path, par: str, a_blanc: bool) -> int:
    base = charger_referentiel(CLASSEUR)
    connect()
    await ensure_indexes()
    try:
        depot = SurcoucheRepository()
        surcouche, meta = await depot.charger()
        rapport = executer(base, fiches, geographie, surcouche)
        if a_blanc:
            print("\nA BLANC — rien n'est enregistre.")
            return 0
        if rapport.pays or rapport.regions or rapport.villes:
            nouvelle = await depot.enregistrer(surcouche, par=par)
            print(
                f"\nEnregistre : surcouche v{meta['version']} -> v{nouvelle['version']} "
                f"({nouvelle['modifie_le']})"
            )
            relue, _ = await depot.charger()
            assert len(relue.pays) == len(surcouche.pays), "relecture differente de l'ecriture"
            print(f"Relecture : {relue.resume()}")
        else:
            print("\nRien de neuf a enregistrer.")
        return 0
    finally:
        close()


def executer(
    base: ReferentielGeo,
    chemin_fiches: Path,
    chemin_geo: Path,
    surcouche: SurcoucheReferentiel,
) -> RapportImport:
    fiches = lire_fiches_pays(chemin_fiches)
    arbre = lire_geographie(chemin_geo)
    rapport = RapportImport()

    for fiche in fiches:
        iso = fiche["iso2"]
        if iso in PAYS_DU_CLASSEUR:
            rapport.sautes.append(f"{iso} : source classeur, jamais importe")
            continue
        if iso in surcouche.pays:
            rapport.sautes.append(f"{iso} : deja dans la surcouche")
        else:
            try:
                surcouche.ajouter_pays(
                    base,
                    iso2=iso,
                    nom_fr=fiche["nom_fr"],
                    nom_en=fiche["nom_en"],
                    capitale=fiche["capitale"],
                    dial_code=fiche["dial_code"],
                    devise_iso=fiche["devise_iso"],
                    tva_percent=fiche["tva_percent"],
                    timezone=fiche["timezone"],
                    region_africa=fiche["region_africa"],
                    regulateur_telco=REGULATEURS_TELCO.get(iso, ""),
                    regulateur_finance=REGULATEURS_FINANCE.get(fiche["devise_iso"], ""),
                    devise_nom=fiche["devise_nom"],
                    devise_decimales=fiche["devise_decimales"],
                    banque_centrale=BANQUES_CENTRALES.get(fiche["devise_iso"], ""),
                )
                rapport.pays += 1
            except AjoutRefuse as refus:
                rapport.refus.append(f"pays {iso} : {refus}")
                continue

        for nom_region, villes in arbre.get(iso, {}).items():
            # GET-avant-POST a chaque niveau : un fichier futur (`_2`...) peut
            # COMPLETER un pays deja importe sans que l'existant crie au refus.
            existante = next(
                (r for r in surcouche.regions.values()
                 if r.country_iso2 == iso and r.name == nom_region),
                None,
            )
            if existante is not None:
                region = existante
            else:
                try:
                    region = surcouche.ajouter_region(base, pays=iso, nom=nom_region)
                    rapport.regions += 1
                except AjoutRefuse as refus:
                    rapport.refus.append(f"region {iso}/{nom_region} : {refus}")
                    continue
            for ville in villes:
                deja_la = next(
                    (v for v in surcouche.villes.values()
                     if v.country_iso2 == iso and v.name == ville["nom"]),
                    None,
                )
                if deja_la is not None:
                    fiche_ville = deja_la
                else:
                    latitude, longitude = gps(iso, ville["nom"])
                    if latitude is not None:
                        rapport.gps += 1
                    try:
                        fiche_ville = surcouche.ajouter_ville(
                            base,
                            region_id=region.region_id,
                            nom=ville["nom"],
                            latitude=latitude,
                            longitude=longitude,
                            population=ville["population"],
                            poids_economique=poids_economique(
                                ville["population"], ville["est_capitale_pays"]
                            ),
                        )
                        rapport.villes += 1
                    except AjoutRefuse as refus:
                        rapport.refus.append(f"ville {iso}/{ville['nom']} : {refus}")
                        continue
                quartiers_existants = {
                    q.name for q in surcouche.quartiers.values()
                    if q.city_id == fiche_ville.city_id
                }
                for nom_quartier, zone in QUARTIERS_REELS.get(
                    (iso, ville["nom"].lower()), []
                ):
                    if nom_quartier in quartiers_existants:
                        continue
                    try:
                        surcouche.ajouter_quartier(
                            base,
                            city_id=fiche_ville.city_id,
                            nom=nom_quartier,
                            zone_type=zone,
                        )
                        rapport.quartiers += 1
                    except AjoutRefuse as refus:
                        rapport.refus.append(f"quartier {iso}/{nom_quartier} : {refus}")

    hors_fichier = sorted(set(arbre) - {f["iso2"] for f in fiches})
    for iso in hors_fichier:
        rapport.refus.append(f"{iso} : geographie sans fiche pays — ligne CSV ignoree")

    # LES TROUS SONT DITS, jamais combles au hasard (exigence du 22/08) :
    # un pays sans geographie, une ville sans quartier — chacun nomme.
    fiches_importees = {f["iso2"] for f in fiches} - PAYS_DU_CLASSEUR
    for iso in sorted(fiches_importees - set(arbre)):
        rapport.trous.append(f"{iso} : fiche pays SANS regions ni villes (hors CSV)")
    for iso in sorted(set(arbre) & fiches_importees):
        sans_quartier = [
            v["nom"]
            for villes in arbre[iso].values()
            for v in villes
            if (iso, v["nom"].lower()) not in QUARTIERS_REELS
        ]
        if sans_quartier:
            rapport.trous.append(
                f"{iso} : {len(sans_quartier)} ville(s) sans quartier reel connu "
                f"(a completer via US-B4)"
            )

    print(f"Importes : {rapport.pays} pays, {rapport.regions} regions, "
          f"{rapport.villes} villes ({rapport.gps} avec GPS reel), "
          f"{rapport.quartiers} quartiers reels")
    print(f"Sautes ({len(rapport.sautes)}) :")
    for motif in rapport.sautes:
        print(f"  - {motif}")
    if rapport.refus:
        print(f"REFUS des invariants ({len(rapport.refus)}) — rien n'est contourne :")
        for motif in rapport.refus:
            print(f"  - {motif}")
    if rapport.trous:
        print(f"TROUS declares ({len(rapport.trous)}) — a completer, jamais inventes :")
        for motif in rapport.trous:
            print(f"  - {motif}")
    print(surcouche.resume())
    return rapport


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("fiches", type=Path)
    analyseur.add_argument("geographie", type=Path)
    analyseur.add_argument("--par", default="import-fichiers-direction")
    analyseur.add_argument("--a-blanc", action="store_true")
    arguments = analyseur.parse_args()
    sys.exit(asyncio.run(importer(arguments.fiches, arguments.geographie,
                                  arguments.par, arguments.a_blanc)))
