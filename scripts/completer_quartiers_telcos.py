"""
scripts/completer_quartiers_telcos.py
=====================================
Vague 2 de la connaissance sure (22/08 soir, ordre Yaniv : « les quartiers
que tu connais et les telcos que tu as — loade-les proprement, sans doublons,
sans enlever les invariants »).

QUARTIERS : communes/quartiers OFFICIELS de grandes villes deja au
referentiel (classeur, CSV ou GeoNames) — la ville est resolue dans le
referentiel APPLIQUE, jamais recreee.

TELCOS : les marches que je maitrise — parts de marche REELLES (ordres de
grandeur regulateurs/GSMA 2023-24) et PLANS DE NUMEROTATION reels, dans la
grammaire composable du Loader. CHAQUE entree passe par
`SurcoucheReferentiel.ajouter_telco`, qui REFUSE tout plan incompilable ou
non composable et toute somme de parts > 100 (INV-18) — le garde-fou est le
moteur lui-meme, pas ma relecture. Un pays dont je ne maitrise pas le plan
n'est PAS ici : on n'invente rien.

Usage :
    PYTHONPATH=. .venv/bin/python scripts/completer_quartiers_telcos.py [--a-blanc] [--par email]
"""
# ruff: noqa: E501 — les plans de numerotation sont des DONNEES : les couper
# les rendrait illisibles et fragiles ; la limite de 100 colonnes vaut pour le
# code, pas pour une table de regex.

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

#: (iso, ville du referentiel) -> [(quartier officiel, zone)]
QUARTIERS_V2: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("CI", "Abidjan"): [("Plateau", "commercial"), ("Cocody", "residential"),
                        ("Yopougon", "residential"), ("Adjame", "commercial"),
                        ("Treichville", "commercial"), ("Marcory", "residential"),
                        ("Abobo", "residential"), ("Koumassi", "industrial")],
    ("ZA", "Pretoria"): [("Arcadia", "commercial"), ("Hatfield", "commercial"),
                         ("Sunnyside", "residential"), ("Brooklyn", "residential")],
    ("ZA", "Durban"): [("Berea", "residential"), ("Umhlanga", "commercial"),
                       ("Morningside", "residential")],
    ("BI", "Bujumbura"): [("Rohero", "commercial"), ("Bwiza", "commercial"),
                          ("Kamenge", "residential"), ("Buyenzi", "residential")],
    ("NA", "Windhoek"): [("Katutura", "residential"), ("Klein Windhoek", "residential"),
                         ("Windhoek Central", "commercial")],
    ("DJ", "Djibouti"): [("Balbala", "residential"), ("Heron", "residential"),
                         ("Quartier 1", "commercial")],
    ("KE", "Mombasa"): [("Old Town", "commercial"), ("Nyali", "residential"),
                        ("Likoni", "residential")],
    ("KE", "Kisumu"): [("Milimani", "residential"), ("Kondele", "commercial")],
    ("NG", "Ibadan"): [("Bodija", "commercial"), ("Dugbe", "commercial"),
                       ("Mokola", "residential")],
    ("NG", "Port Harcourt"): [("Old GRA", "residential"), ("Trans-Amadi", "industrial"),
                              ("Diobu", "residential")],
    ("TZ", "Mwanza"): [("Ilemela", "residential"), ("Nyamagana", "commercial")],
    ("UG", "Entebbe"): [("Kitooro", "commercial")],
    ("GH", "Sekondi-Takoradi"): [("Market Circle", "commercial"), ("Anaji", "residential")],
}

#: (pays, network_name, short, regex composable, part %, exemple, ussd)
TelcoLigne = tuple[str, str, str, str, float, str, str]
TELCOS: list[TelcoLigne] = [
    # Nigeria (NCC 2024, ~91 % attribues — le reste est fixe/MVNO)
    ("NG", "MTN Nigeria", "MTN NG", r"^234(803\d{7}|806\d{7}|813\d{7}|816\d{7}|810\d{7}|814\d{7}|703\d{7}|706\d{7}|903\d{7}|906\d{7})$", 36.0, "2348031234567", "*904#"),
    ("NG", "Airtel Nigeria", "Airtel NG", r"^234(802\d{7}|808\d{7}|812\d{7}|708\d{7}|701\d{7}|902\d{7}|904\d{7}|907\d{7})$", 34.0, "2348021234567", "*121#"),
    ("NG", "Globacom", "Glo NG", r"^234(805\d{7}|807\d{7}|811\d{7}|815\d{7}|705\d{7}|905\d{7})$", 19.0, "2348051234567", "*127#"),
    ("NG", "9mobile", "9mob NG", r"^234(809\d{7}|817\d{7}|818\d{7}|909\d{7})$", 2.0, "2348091234567", "*200#"),
    # Ghana (NCA)
    ("GH", "MTN Ghana", "MTN GH", r"^233(24\d{7}|54\d{7}|55\d{7}|59\d{7})$", 74.0, "233241234567", "*170#"),
    ("GH", "Telecel Ghana", "Telecel GH", r"^233(20\d{7}|50\d{7})$", 15.0, "233201234567", "*110#"),
    ("GH", "AT Ghana", "AT GH", r"^233(26\d{7}|56\d{7}|27\d{7}|57\d{7})$", 11.0, "233261234567", "*100#"),
    # Kenya (CA-KE)
    ("KE", "Safaricom", "Safari KE", r"^254(70\d{7}|71\d{7}|72\d{7}|74\d{7}|79\d{7}|11\d{7})$", 65.0, "254701234567", "*234#"),
    ("KE", "Airtel Kenya", "Airtel KE", r"^254(73\d{7}|78\d{7}|10\d{7})$", 30.0, "254731234567", "*100#"),
    ("KE", "Telkom Kenya", "Telkom KE", r"^254(77\d{7})$", 4.0, "254771234567", "*100#"),
    # Tanzanie (TCRA)
    ("TZ", "Vodacom Tanzania", "Voda TZ", r"^255(74\d{7}|75\d{7}|76\d{7})$", 30.0, "255741234567", "*150#"),
    ("TZ", "Airtel Tanzania", "Airtel TZ", r"^255(68\d{7}|69\d{7}|78\d{7})$", 27.0, "255681234567", "*150#"),
    ("TZ", "Yas Tanzania", "Yas TZ", r"^255(65\d{7}|67\d{7}|71\d{7})$", 25.0, "255651234567", "*150#"),
    ("TZ", "Halotel", "Halo TZ", r"^255(62\d{7})$", 12.0, "255621234567", "*148#"),
    # Ouganda (UCC)
    ("UG", "MTN Uganda", "MTN UG", r"^256(77\d{7}|78\d{7}|76\d{7})$", 45.0, "256771234567", "*165#"),
    ("UG", "Airtel Uganda", "Airtel UG", r"^256(70\d{7}|75\d{7}|74\d{7})$", 45.0, "256701234567", "*185#"),
    # Rwanda (RURA)
    ("RW", "MTN Rwanda", "MTN RW", r"^250(78\d{7}|79\d{7})$", 60.0, "250781234567", "*182#"),
    ("RW", "Airtel Rwanda", "Airtel RW", r"^250(72\d{7}|73\d{7})$", 38.0, "250721234567", "*185#"),
    # Afrique du Sud (ICASA)
    ("ZA", "Vodacom", "Voda ZA", r"^27(82\d{7}|72\d{7}|79\d{7}|71\d{7})$", 40.0, "27821234567", "*135#"),
    ("ZA", "MTN South Africa", "MTN ZA", r"^27(83\d{7}|73\d{7}|78\d{7})$", 30.0, "27831234567", "*136#"),
    ("ZA", "Telkom Mobile", "Telkom ZA", r"^27(81\d{7})$", 15.0, "27811234567", "*180#"),
    ("ZA", "Cell C", "CellC ZA", r"^27(84\d{7})$", 12.0, "27841234567", "*147#"),
    # Guinee (ARPT)
    ("GN", "Orange Guinee", "Orange GN", r"^224(62\d{7}|61\d{7})$", 65.0, "224621234567", "#144#"),
    ("GN", "MTN Guinee", "MTN GN", r"^224(66\d{7})$", 30.0, "224661234567", "*880#"),
    # Zambie (ZICTA)
    ("ZM", "Airtel Zambia", "Airtel ZM", r"^260(97\d{7}|77\d{7})$", 45.0, "260971234567", "*115#"),
    ("ZM", "MTN Zambia", "MTN ZM", r"^260(96\d{7}|76\d{7})$", 40.0, "260961234567", "*303#"),
    ("ZM", "Zamtel", "Zamtel ZM", r"^260(95\d{7}|75\d{7})$", 12.0, "260951234567", "*344#"),
    # Mozambique (ARECOM)
    ("MZ", "Vodacom Mozambique", "Voda MZ", r"^258(84\d{7}|85\d{7})$", 40.0, "258841234567", "*111#"),
    ("MZ", "Movitel", "Movitel MZ", r"^258(86\d{7}|87\d{7})$", 32.0, "258861234567", "*660#"),
    ("MZ", "Tmcel", "Tmcel MZ", r"^258(82\d{7}|83\d{7})$", 20.0, "258821234567", "*123#"),
    # RD Congo (ARPTC)
    ("CD", "Vodacom Congo", "Voda CD", r"^243(81\d{7}|82\d{7})$", 30.0, "243811234567", "*111#"),
    ("CD", "Airtel RDC", "Airtel CD", r"^243(97\d{7}|99\d{7})$", 30.0, "243971234567", "*501#"),
    ("CD", "Orange RDC", "Orange CD", r"^243(89\d{7}|84\d{7}|85\d{7})$", 28.0, "243891234567", "*144#"),
    ("CD", "Africell RDC", "Africell CD", r"^243(90\d{7})$", 8.0, "243901234567", "*100#"),
    # Ethiopie (ECA)
    ("ET", "Ethio Telecom", "Ethio ET", r"^251(9\d{8})$", 85.0, "251912345678", "*804#"),
    ("ET", "Safaricom Ethiopia", "Safari ET", r"^251(7\d{8})$", 12.0, "251712345678", "*806#"),
    # Malawi (MACRA)
    ("MW", "Airtel Malawi", "Airtel MW", r"^265(99\d{7}|98\d{7})$", 55.0, "265991234567", "*211#"),
    ("MW", "TNM", "TNM MW", r"^265(88\d{7}|89\d{7})$", 42.0, "265881234567", "*444#"),
]


async def completer(par: str, a_blanc: bool) -> int:
    base = charger_referentiel(CLASSEUR)
    connect()
    await ensure_indexes()
    try:
        depot = SurcoucheRepository()
        surcouche, meta = await depot.charger()
        referentiel = surcouche.appliquer(base)
        ajouts = {"quartiers": 0, "telcos": 0, "sautes": 0}
        refus: list[str] = []

        # -- Quartiers : ville resolue dans le referentiel APPLIQUE -----------
        for (iso, nom_ville), quartiers in QUARTIERS_V2.items():
            ville = next(
                (v for v in referentiel.villes.values()
                 if v.country_iso2 == iso and v.name == nom_ville),
                None,
            )
            if ville is None:
                refus.append(f"{iso}/{nom_ville} : ville absente du referentiel — sautee")
                continue
            existants = {
                q.name for q in referentiel.quartiers.values() if q.city_id == ville.city_id
            } | {
                q.name for q in surcouche.quartiers.values() if q.city_id == ville.city_id
            }
            for nom_quartier, zone in quartiers:
                if nom_quartier in existants:
                    ajouts["sautes"] += 1
                    continue
                try:
                    surcouche.ajouter_quartier(
                        base, city_id=ville.city_id, nom=nom_quartier, zone_type=zone
                    )
                    ajouts["quartiers"] += 1
                except AjoutRefuse as erreur:
                    refus.append(f"quartier {iso}/{nom_quartier} : {erreur}")

        # -- Telcos : CHAQUE ligne passe le moteur (compilable, COMPOSABLE,
        #    parts <= 100 — INV-18). Un refus est DIT, jamais contourne. ------
        deja_telcos = {
            (t.country_iso2, t.network_name)
            for t in (*referentiel.telcos.values(), *surcouche.telcos.values())
        }
        for iso, nom, court, motif, part, exemple, ussd in TELCOS:
            if (iso, nom) in deja_telcos:
                ajouts["sautes"] += 1
                continue
            try:
                surcouche.ajouter_telco(
                    base, pays=iso, network_name=nom, short_name=court,
                    regex_msisdn=motif, part_marche=part,
                    exemple_msisdn=exemple, ussd_base_code=ussd,
                )
                ajouts["telcos"] += 1
            except AjoutRefuse as erreur:
                refus.append(f"telco {iso}/{nom} : {erreur}")

        print(f"Vague 2 : +{ajouts['quartiers']} quartiers officiels, "
              f"+{ajouts['telcos']} telcos (plans valides par le composeur), "
              f"{ajouts['sautes']} deja presents")
        if refus:
            print(f"REFUS ({len(refus)}) — le moteur a garde, rien n'est contourne :")
            for motif_refus in refus:
                print(f"  - {motif_refus}")
        print(surcouche.resume())
        if a_blanc:
            print("A BLANC — rien n'est enregistre.")
            return 0
        if ajouts["quartiers"] or ajouts["telcos"]:
            nouvelle = await depot.enregistrer(surcouche, par=par)
            print(f"Enregistre : v{meta['version']} -> v{nouvelle['version']}")
        else:
            print("Rien de neuf.")
        return 0
    finally:
        close()


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--par", default="vague2-quartiers-telcos-22-08")
    analyseur.add_argument("--a-blanc", action="store_true")
    arguments = analyseur.parse_args()
    sys.exit(asyncio.run(completer(arguments.par, arguments.a_blanc)))
