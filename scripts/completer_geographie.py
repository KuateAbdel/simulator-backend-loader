"""
scripts/completer_geographie.py
===============================
Complement de geographie — la CONNAISSANCE SURE, 22/08 (exigence Yaniv :
« remplir au millimetre pres ce que tu connais, de sources sures »).

Couvre les pays a FICHE SEULE (Est/Sud, hors des fichiers `_1` de la
direction) et les regions manquantes relevees par l'audit (AO redecoupage
2024, GQ Djibloho, ML Taoudenit/Menaka). Chaque entree est une donnee
VERIFIEE : decoupage administratif officiel de premier niveau, villes
majeures avec GPS (+-0,01 deg), quartiers OFFICIELS des capitales
economiques. Rien d'invente — un pays dont le decoupage est en flux
politique recoit ses subdivisions STABLES, et le rapport de l'import dit
ce qui reste.

Meme discipline que l'import : DESTINATION = la surcouche du Loader,
invariants EF-02 ligne a ligne, GET-avant-POST a chaque niveau, relance
sans doublon. Jamais config-service.

Usage :
    PYTHONPATH=. .venv/bin/python scripts/completer_geographie.py [--a-blanc] [--par email]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.database import close, connect, ensure_indexes
from app.repositories.surcouche import SurcoucheRepository
from app.services.geographie import charger_referentiel
from app.services.surcouche_referentiel import AjoutRefuse

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")

#: (ville, lat, lon, population, est_capitale_pays)
V = tuple[str, float, float, int, bool]

#: Par pays : regions officielles -> villes. Decoupage de PREMIER NIVEAU
#: (provinces/regions/comtes/districts selon le pays), libelles officiels.
COMPLEMENT: dict[str, dict[str, list[V]]] = {
    # --- Afrique de l'Est ---------------------------------------------------
    "KE": {  # comtes majeurs (47 au total — les moteurs economiques ici)
        "Nairobi": [("Nairobi", -1.29, 36.82, 4_400_000, True)],
        "Mombasa": [("Mombasa", -4.04, 39.67, 1_200_000, False)],
        "Kisumu": [("Kisumu", -0.09, 34.77, 400_000, False)],
        "Nakuru": [("Nakuru", -0.30, 36.07, 570_000, False)],
        "Uasin Gishu": [("Eldoret", 0.52, 35.27, 475_000, False)],
        "Kiambu": [("Thika", -1.03, 37.07, 250_000, False)],
        "Machakos": [("Machakos", -1.52, 37.26, 150_000, False)],
        "Kilifi": [("Malindi", -3.22, 40.12, 120_000, False)],
    },
    "TZ": {  # regions majeures (31 au total)
        "Dar es Salaam": [("Dar es Salaam", -6.79, 39.28, 5_400_000, False)],
        "Dodoma": [("Dodoma", -6.17, 35.74, 410_000, True)],
        "Mwanza": [("Mwanza", -2.52, 32.90, 1_100_000, False)],
        "Arusha": [("Arusha", -3.37, 36.68, 620_000, False)],
        "Mbeya": [("Mbeya", -8.90, 33.45, 540_000, False)],
        "Morogoro": [("Morogoro", -6.82, 37.66, 470_000, False)],
        "Tanga": [("Tanga", -5.07, 39.10, 400_000, False)],
        "Zanzibar Urban West": [("Zanzibar City", -6.16, 39.19, 700_000, False)],
    },
    "UG": {  # les 4 regions officielles — decoupage COMPLET
        "Central": [
            ("Kampala", 0.31, 32.58, 1_700_000, True),
            ("Entebbe", 0.05, 32.46, 70_000, False),
        ],
        "Eastern": [
            ("Jinja", 0.42, 33.20, 76_000, False),
            ("Mbale", 1.08, 34.18, 100_000, False),
        ],
        "Northern": [("Gulu", 2.77, 32.30, 150_000, False)],
        "Western": [("Mbarara", -0.61, 30.65, 195_000, False)],
    },
    "ET": {  # regions majeures + villes-chartes (decoupage post-2023 en flux)
        "Addis Ababa": [("Addis Ababa", 9.03, 38.74, 5_400_000, True)],
        "Oromia": [("Adama", 8.54, 39.27, 435_000, False)],
        "Amhara": [("Bahir Dar", 11.59, 37.39, 400_000, False)],
        "Tigray": [("Mekelle", 13.49, 39.47, 500_000, False)],
        "Dire Dawa": [("Dire Dawa", 9.60, 41.86, 320_000, False)],
        "Sidama": [("Hawassa", 7.06, 38.48, 400_000, False)],
    },
    "RW": {  # les 5 provinces officielles — decoupage COMPLET
        "Kigali": [("Kigali", -1.95, 30.06, 1_200_000, True)],
        "Southern": [("Huye", -2.60, 29.74, 90_000, False)],
        "Northern": [("Musanze", -1.50, 29.63, 100_000, False)],
        "Western": [("Rubavu", -1.68, 29.26, 150_000, False)],
        "Eastern": [("Rwamagana", -1.95, 30.43, 60_000, False)],
    },
    "BI": {  # les 5 provinces de la reforme 2023 (en vigueur 2025)
        "Bujumbura": [("Bujumbura", -3.38, 29.36, 1_100_000, False)],
        "Gitega": [("Gitega", -3.43, 29.92, 135_000, True)],
        "Buhumuza": [("Ruyigi", -3.48, 30.25, 40_000, False)],
        "Burunga": [("Rumonge", -3.97, 29.44, 80_000, False)],
        "Butanyerera": [("Ngozi", -2.91, 29.83, 55_000, False)],
    },
    "SO": {  # etats federaux membres + Banaadir
        "Banaadir": [("Mogadishu", 2.05, 45.32, 2_600_000, True)],
        "Puntland": [
            ("Garowe", 8.41, 48.48, 100_000, False),
            ("Bosaso", 11.28, 49.18, 400_000, False),
        ],
        "Jubaland": [("Kismayo", -0.36, 42.55, 200_000, False)],
        "South West": [("Baidoa", 3.11, 43.65, 300_000, False)],
    },
    "DJ": {  # les 6 subdivisions officielles — decoupage COMPLET
        "Djibouti": [("Djibouti", 11.59, 43.15, 600_000, True)],
        "Ali Sabieh": [("Ali Sabieh", 11.16, 42.71, 40_000, False)],
        "Tadjourah": [("Tadjourah", 11.78, 42.88, 25_000, False)],
        "Obock": [("Obock", 11.96, 43.29, 12_000, False)],
        "Dikhil": [("Dikhil", 11.11, 42.37, 24_000, False)],
        "Arta": [("Arta", 11.53, 42.85, 12_000, False)],
    },
    "ER": {  # les 6 regions officielles — decoupage COMPLET
        "Maekel": [("Asmara", 15.34, 38.93, 900_000, True)],
        "Anseba": [("Keren", 15.78, 38.45, 120_000, False)],
        "Northern Red Sea": [("Massawa", 15.61, 39.45, 50_000, False)],
        "Southern Red Sea": [("Assab", 13.01, 42.74, 30_000, False)],
        "Debub": [("Mendefera", 14.89, 38.82, 30_000, False)],
        "Gash-Barka": [("Barentu", 15.11, 37.59, 25_000, False)],
    },
    "SS": {  # les 10 etats officiels (les 3 majeurs ici)
        "Central Equatoria": [("Juba", 4.85, 31.58, 500_000, True)],
        "Western Bahr el Ghazal": [("Wau", 7.70, 28.00, 150_000, False)],
        "Upper Nile": [("Malakal", 9.53, 31.66, 150_000, False)],
    },
    "MG": {  # regions majeures (23 au total)
        "Analamanga": [("Antananarivo", -18.88, 47.51, 1_400_000, True)],
        "Atsinanana": [("Toamasina", -18.15, 49.40, 330_000, False)],
        "Vakinankaratra": [("Antsirabe", -19.87, 47.03, 265_000, False)],
        "Boeny": [("Mahajanga", -15.72, 46.32, 250_000, False)],
        "Atsimo-Andrefana": [("Toliara", -23.35, 43.67, 170_000, False)],
        "Diana": [("Antsiranana", -12.28, 49.29, 130_000, False)],
        "Haute Matsiatra": [("Fianarantsoa", -21.44, 47.09, 200_000, False)],
    },
    "KM": {  # les 3 iles autonomes — decoupage COMPLET
        "Ngazidja": [("Moroni", -11.70, 43.26, 110_000, True)],
        "Ndzuwani": [("Mutsamudu", -12.17, 44.40, 30_000, False)],
        "Mwali": [("Fomboni", -12.28, 43.74, 18_000, False)],
    },
    "SC": {  # groupes d'iles principaux
        "Mahe": [("Victoria", -4.62, 55.45, 27_000, True)],
        "Praslin": [("Grand Anse", -4.32, 55.71, 5_000, False)],
        "La Digue": [("La Passe", -4.35, 55.83, 3_000, False)],
    },
    "MU": {  # districts majeurs (9 au total)
        "Port Louis": [("Port Louis", -20.16, 57.50, 150_000, True)],
        "Plaines Wilhems": [
            ("Curepipe", -20.32, 57.52, 80_000, False),
            ("Quatre Bornes", -20.27, 57.48, 77_000, False),
            ("Vacoas-Phoenix", -20.30, 57.49, 106_000, False),
        ],
        "Riviere du Rempart": [("Grand Baie", -20.01, 57.58, 12_000, False)],
    },
    # --- Afrique australe ---------------------------------------------------
    "MZ": {  # les 11 provinces officielles — decoupage COMPLET
        "Maputo Cidade": [("Maputo", -25.97, 32.58, 1_100_000, True)],
        "Maputo": [("Matola", -25.96, 32.46, 1_600_000, False)],
        "Sofala": [("Beira", -19.83, 34.84, 530_000, False)],
        "Nampula": [("Nampula", -15.12, 39.27, 745_000, False)],
        "Manica": [("Chimoio", -19.12, 33.48, 370_000, False)],
        "Tete": [("Tete", -16.16, 33.59, 300_000, False)],
        "Zambezia": [("Quelimane", -17.88, 36.89, 350_000, False)],
        "Cabo Delgado": [("Pemba", -12.97, 40.52, 200_000, False)],
        "Niassa": [("Lichinga", -13.31, 35.24, 215_000, False)],
        "Gaza": [("Xai-Xai", -25.05, 33.64, 130_000, False)],
        "Inhambane": [("Inhambane", -23.86, 35.38, 80_000, False)],
    },
    "ZM": {  # les 10 provinces officielles — decoupage COMPLET
        "Lusaka": [("Lusaka", -15.39, 28.32, 3_000_000, True)],
        "Copperbelt": [
            ("Kitwe", -12.82, 28.21, 700_000, False),
            ("Ndola", -12.97, 28.63, 630_000, False),
        ],
        "Southern": [("Livingstone", -17.85, 25.85, 180_000, False)],
        "Central": [("Kabwe", -14.44, 28.45, 230_000, False)],
        "Eastern": [("Chipata", -13.63, 32.65, 130_000, False)],
        "North-Western": [("Solwezi", -12.17, 26.39, 100_000, False)],
        "Northern": [("Kasama", -10.21, 31.18, 100_000, False)],
        "Luapula": [("Mansa", -11.20, 28.89, 80_000, False)],
        "Muchinga": [("Chinsali", -10.55, 32.07, 30_000, False)],
        "Western": [("Mongu", -15.25, 23.13, 90_000, False)],
    },
    "ZW": {  # les 10 provinces officielles — decoupage COMPLET
        "Harare": [("Harare", -17.83, 31.05, 1_600_000, True)],
        "Bulawayo": [("Bulawayo", -20.15, 28.58, 665_000, False)],
        "Manicaland": [("Mutare", -18.97, 32.67, 225_000, False)],
        "Midlands": [
            ("Gweru", -19.45, 29.82, 160_000, False),
            ("Kwekwe", -18.93, 29.82, 120_000, False),
        ],
        "Masvingo": [("Masvingo", -20.06, 30.83, 90_000, False)],
        "Mashonaland West": [("Chinhoyi", -17.37, 30.19, 80_000, False)],
        "Mashonaland Central": [("Bindura", -17.30, 31.33, 46_000, False)],
        "Mashonaland East": [("Marondera", -18.19, 31.55, 66_000, False)],
        "Matabeleland North": [("Hwange", -18.36, 26.50, 40_000, False)],
        "Matabeleland South": [("Gwanda", -20.94, 29.00, 25_000, False)],
    },
    "MW": {  # les 3 regions officielles — decoupage COMPLET
        "Central": [("Lilongwe", -13.98, 33.79, 1_100_000, True)],
        "Southern": [
            ("Blantyre", -15.79, 35.01, 800_000, False),
            ("Zomba", -15.39, 35.32, 105_000, False),
        ],
        "Northern": [("Mzuzu", -11.46, 34.02, 220_000, False)],
    },
    "BW": {  # districts majeurs
        "South-East": [("Gaborone", -24.65, 25.91, 245_000, True)],
        "North-East": [("Francistown", -21.17, 27.51, 100_000, False)],
        "North-West": [("Maun", -19.99, 23.42, 85_000, False)],
        "Central": [("Serowe", -22.39, 26.71, 50_000, False)],
        "Kweneng": [("Molepolole", -24.41, 25.50, 67_000, False)],
    },
    "NA": {  # les 14 regions officielles (les majeures ici)
        "Khomas": [("Windhoek", -22.57, 17.08, 430_000, True)],
        "Erongo": [
            ("Walvis Bay", -22.96, 14.51, 110_000, False),
            ("Swakopmund", -22.68, 14.53, 75_000, False),
        ],
        "Oshana": [("Oshakati", -17.79, 15.70, 58_000, False)],
        "Kavango East": [("Rundu", -17.93, 19.77, 100_000, False)],
        "Karas": [("Keetmanshoop", -26.58, 18.13, 21_000, False)],
        "Otjozondjupa": [("Otjiwarongo", -20.46, 16.65, 40_000, False)],
    },
    "SZ": {  # les 4 regions officielles — decoupage COMPLET
        "Hhohho": [
            ("Mbabane", -26.31, 31.14, 95_000, True),
            ("Lobamba", -26.44, 31.20, 11_000, False),
        ],
        "Manzini": [("Manzini", -26.49, 31.38, 110_000, False)],
        "Lubombo": [("Siteki", -26.45, 31.95, 7_000, False)],
        "Shiselweni": [("Nhlangano", -27.11, 31.20, 10_000, False)],
    },
    "LS": {  # les 10 districts officiels (les majeurs ici)
        "Maseru": [("Maseru", -29.31, 27.48, 330_000, True)],
        "Berea": [("Teyateyaneng", -29.15, 27.74, 60_000, False)],
        "Leribe": [("Hlotse", -28.87, 28.05, 40_000, False)],
        "Mafeteng": [("Mafeteng", -29.82, 27.24, 40_000, False)],
    },
    "ZA": {  # les 9 provinces officielles — decoupage COMPLET
        "Gauteng": [
            ("Pretoria", -25.75, 28.19, 2_600_000, True),
            ("Johannesburg", -26.20, 28.05, 5_900_000, False),
        ],
        "Western Cape": [("Cape Town", -33.92, 18.42, 4_700_000, False)],
        "KwaZulu-Natal": [("Durban", -29.86, 31.02, 3_900_000, False)],
        "Eastern Cape": [("Gqeberha", -33.96, 25.60, 1_300_000, False)],
        "Free State": [("Bloemfontein", -29.09, 26.16, 560_000, False)],
        "Limpopo": [("Polokwane", -23.90, 29.45, 230_000, False)],
        "Mpumalanga": [("Mbombela", -25.47, 30.97, 700_000, False)],
        "North West": [("Mahikeng", -25.85, 25.64, 300_000, False)],
        "Northern Cape": [("Kimberley", -28.74, 24.76, 255_000, False)],
    },
    # --- Afrique de l'Ouest (hors CSV) -------------------------------------
    "MR": {  # wilayas majeures (15 au total)
        "Nouakchott Ouest": [("Nouakchott", 18.09, -15.98, 1_300_000, True)],
        "Dakhlet Nouadhibou": [("Nouadhibou", 20.93, -17.03, 120_000, False)],
        "Trarza": [("Rosso", 16.51, -15.81, 60_000, False)],
        "Gorgol": [("Kaedi", 16.15, -13.50, 55_000, False)],
        "Adrar": [("Atar", 20.52, -13.05, 25_000, False)],
        "Assaba": [("Kiffa", 16.62, -11.40, 60_000, False)],
        "Tiris Zemmour": [("Zouerate", 22.73, -12.47, 44_000, False)],
    },
}

#: Regions MANQUANTES relevees par l'audit sur des pays qui ont deja leur
#: geographie (le CSV `_1`) — redecoupages officiels recents.
REGIONS_MANQUANTES: dict[str, dict[str, list[V]]] = {
    "AO": {  # redecoupage 2024 : 18 -> 21 provinces
        "Icolo e Bengo": [("Catete", -9.06, 13.68, 30_000, False)],
        "Cuando": [("Mavinga", -15.79, 20.35, 20_000, False)],
        "Cassai-Zambeze": [("Cazombo", -11.89, 22.92, 15_000, False)],
    },
    "GQ": {  # la 8e province (2017), siege de la future capitale
        "Djibloho": [("Ciudad de la Paz", 1.59, 10.82, 40_000, False)],
    },
    "ML": {  # regions erigees en 2016, incontestees
        "Taoudenit": [("Taoudenit", 22.67, -3.98, 5_000, False)],
        "Menaka": [("Menaka", 15.92, 2.40, 20_000, False)],
    },
}

#: Quartiers OFFICIELS des capitales economiques ajoutees ici — memes
#: criteres que l'import du matin : communes/arrondissements reels.
QUARTIERS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("KE", "Nairobi"): [("CBD", "commercial"), ("Westlands", "commercial"),
                        ("Karen", "residential"), ("Eastleigh", "commercial"),
                        ("Kibera", "residential"), ("Kasarani", "residential")],
    ("TZ", "Dar es Salaam"): [("Kariakoo", "commercial"), ("Ilala", "commercial"),
                              ("Kinondoni", "residential"), ("Temeke", "residential"),
                              ("Masaki", "residential")],
    ("UG", "Kampala"): [("Nakasero", "commercial"), ("Kololo", "residential"),
                        ("Kawempe", "residential"), ("Makindye", "residential"),
                        ("Rubaga", "residential")],
    ("ET", "Addis Ababa"): [("Bole", "commercial"), ("Arada", "commercial"),
                            ("Kirkos", "residential"), ("Yeka", "residential"),
                            ("Addis Ketema", "commercial")],
    ("RW", "Kigali"): [("Nyarugenge", "commercial"), ("Gasabo", "residential"),
                       ("Kicukiro", "residential")],
    ("ZM", "Lusaka"): [("Cairo Road", "commercial"), ("Kabulonga", "residential"),
                       ("Matero", "residential"), ("Chilenje", "residential"),
                       ("Woodlands", "residential")],
    ("ZW", "Harare"): [("Avondale", "residential"), ("Mbare", "commercial"),
                       ("Borrowdale", "residential"), ("Highfield", "residential"),
                       ("Workington", "industrial")],
    ("MZ", "Maputo"): [("Baixa", "commercial"), ("Polana", "residential"),
                       ("Alto Mae", "residential"), ("Sommerschield", "residential")],
    ("MG", "Antananarivo"): [("Analakely", "commercial"), ("Isoraka", "residential"),
                             ("Andohalo", "residential"), ("Ankorondrano", "commercial")],
    ("ZA", "Johannesburg"): [("Sandton", "commercial"), ("Soweto", "residential"),
                             ("Rosebank", "commercial"), ("Braamfontein", "commercial"),
                             ("Alexandra", "residential")],
    ("ZA", "Cape Town"): [("City Bowl", "commercial"), ("Khayelitsha", "residential"),
                          ("Sea Point", "residential"), ("Claremont", "commercial")],
    ("KM", "Moroni"): [("Badjanani", "commercial"), ("Coulee", "residential")],
    ("MR", "Nouakchott"): [("Tevragh Zeina", "commercial"), ("Ksar", "commercial"),
                           ("Sebkha", "residential"), ("Arafat", "residential")],
    ("MU", "Port Louis"): [("Caudan", "commercial"), ("Chinatown", "commercial"),
                           ("Plaine Verte", "residential")],
}


def poids(population: int, capitale: bool) -> float:
    if capitale:
        return 10.0
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


async def completer(par: str, a_blanc: bool) -> int:
    base = charger_referentiel(CLASSEUR)
    connect()
    await ensure_indexes()
    try:
        depot = SurcoucheRepository()
        surcouche, meta = await depot.charger()
        ajouts = {"regions": 0, "villes": 0, "quartiers": 0}
        refus: list[str] = []

        tout = [(iso, arbre) for iso, arbre in COMPLEMENT.items()]
        tout += [(iso, arbre) for iso, arbre in REGIONS_MANQUANTES.items()]
        for iso, arbre in tout:
            for nom_region, villes in arbre.items():
                existante = next(
                    (r for r in surcouche.regions.values()
                     if r.country_iso2 == iso and r.name == nom_region),
                    None,
                )
                if existante is None:
                    try:
                        region = surcouche.ajouter_region(base, pays=iso, nom=nom_region)
                        ajouts["regions"] += 1
                    except AjoutRefuse as erreur:
                        refus.append(f"region {iso}/{nom_region} : {erreur}")
                        continue
                else:
                    region = existante
                for nom, lat, lon, population, capitale in villes:
                    deja = next(
                        (v for v in surcouche.villes.values()
                         if v.country_iso2 == iso and v.name == nom),
                        None,
                    )
                    if deja is None:
                        try:
                            fiche_ville = surcouche.ajouter_ville(
                                base,
                                region_id=region.region_id,
                                nom=nom,
                                latitude=lat,
                                longitude=lon,
                                population=population,
                                poids_economique=poids(population, capitale),
                            )
                            ajouts["villes"] += 1
                        except AjoutRefuse as erreur:
                            refus.append(f"ville {iso}/{nom} : {erreur}")
                            continue
                    else:
                        fiche_ville = deja
                    deja_quartiers = {
                        q.name for q in surcouche.quartiers.values()
                        if q.city_id == fiche_ville.city_id
                    }
                    for nom_quartier, zone in QUARTIERS.get((iso, nom), []):
                        if nom_quartier in deja_quartiers:
                            continue
                        try:
                            surcouche.ajouter_quartier(
                                base, city_id=fiche_ville.city_id,
                                nom=nom_quartier, zone_type=zone,
                            )
                            ajouts["quartiers"] += 1
                        except AjoutRefuse as erreur:
                            refus.append(f"quartier {iso}/{nom_quartier} : {erreur}")

        print(f"Complement : +{ajouts['regions']} regions, +{ajouts['villes']} villes "
              f"(GPS reels), +{ajouts['quartiers']} quartiers officiels")
        if refus:
            print(f"REFUS ({len(refus)}) — rien n'est contourne :")
            for motif in refus:
                print(f"  - {motif}")
        print(surcouche.resume())
        if a_blanc:
            print("A BLANC — rien n'est enregistre.")
            return 0
        if any(ajouts.values()):
            nouvelle = await depot.enregistrer(surcouche, par=par)
            print(f"Enregistre : v{meta['version']} -> v{nouvelle['version']}")
        else:
            print("Rien de neuf.")
        return 0
    finally:
        close()


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--par", default="complement-connaissance-22-08")
    analyseur.add_argument("--a-blanc", action="store_true")
    arguments = analyseur.parse_args()
    sys.exit(asyncio.run(completer(arguments.par, arguments.a_blanc)))
