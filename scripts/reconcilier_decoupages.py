"""
scripts/reconcilier_decoupages.py
=================================
RECONCILIATION des decoupages administratifs contre les listes OFFICIELLES
(22/08 — discipline de geographe senior exigee par Yaniv : verifier soi-meme,
completer de source sure, jamais subir la donnee).

Quatre familles d'actions, chacune LISTEE a blanc avant toute ecriture :

  RENOMMAGES  etiquettes sales ou variantes -> libelle officiel
              (« Marakwet District » -> « Elgeyo-Marakwet », « County » colle,
              « Hodh Ech Chargi » -> « Hodh Ech Chargui »...)
  FUSIONS     doublons d'orthographe que la cle traduite ne voit pas
              (« Atacora/Atakora », « Couffo/Kouffo », « FCT », « Luanda
              Norte » = Lunda Norte, « Kwanza Sul » = Cuanza Sul...)
  NIVEAUX     Somalie : mes 3 etats federaux (Puntland, Jubaland, South West)
              redescendus — les villes re-rattachees a leur REGION officielle
              (Garowe->Nugaal, Bosaso->Bari, Kismayo->Lower Juba, Baidoa->Bay)
  AJOUTS      les manquants des listes officielles : Bomet (47e comte du
              Kenya), Tagant + Nouakchott Sud (15 wilayas), Kavango West +
              Kunene + Omusati (14 regions namibiennes), Bakool (18 regions
              somaliennes), Kgalagadi + Chobe (districts du Botswana),
              chefs-lieux avec GPS reels.

Declares SANS action (pas des erreurs) : CI 14 (source classeur, decoupage 33
a arbitrer avec la direction), ML 11 (19 regions decretees en 2023 non
operationnelles), CF 19 (reforme 2020 en cours), BW villes-districts (statut
administratif reel), GM en nomenclature LGA.

Usage :
    PYTHONPATH=. .venv/bin/python scripts/reconcilier_decoupages.py [--a-blanc] [--par email]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace
from pathlib import Path

from app.core.database import close, connect, ensure_indexes
from app.repositories.surcouche import SurcoucheRepository
from app.services.geographie import Region, charger_referentiel
from app.services.surcouche_referentiel import AjoutRefuse

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")

#: (iso, libelle actuel) -> libelle OFFICIEL
RENOMMAGES: list[tuple[str, str, str]] = [
    ("KE", "Marakwet District", "Elgeyo-Marakwet"),
    ("KE", "Murang'A", "Murang'a"),
    ("KE", "Tharaka - Nithi", "Tharaka-Nithi"),
    ("KE", "Taita Taveta", "Taita-Taveta"),
    ("MR", "Hodh Ech Chargi", "Hodh Ech Chargui"),
    ("MR", "Nouakchott North", "Nouakchott Nord"),
    ("SO", "Middle Shabele", "Middle Shabelle"),
    ("AO", "Cuando Cubango", "Cubango"),  # redecoupage 2024 : Cubango + Cuando
]

#: (iso, doublon a retirer) -> canonique (les villes sont re-rattachees)
FUSIONS: list[tuple[str, str, str]] = [
    ("NG", "FCT", "Territoire de la Capitale Federale"),
    ("AO", "Luanda Norte", "Lunda Norte"),
    ("AO", "Kwanza Sul", "Cuanza Sul"),
    ("BJ", "Atakora", "Atacora"),
    ("BJ", "Kouffo", "Couffo"),
    ("MG", "Upper Matsiatra", "Haute Matsiatra"),
    ("GM", "Western", "West Coast"),  # meme LGA, ancien nom
]

#: Somalie — les etats federaux redescendus : region a retirer -> re-rattachement
#: de CHAQUE ville a sa region officielle.
NIVEAUX_SO: dict[str, dict[str, str]] = {
    "Puntland": {"Garowe": "Nugaal", "Bosaso": "Bari"},
    "Jubaland": {"Kismayo": "Lower Juba"},
    "South West": {"Baidoa": "Bay"},
}

#: Les MANQUANTS des listes officielles : (iso, region, [(ville, lat, lon, pop)])
AJOUTS: list[tuple[str, str, list[tuple[str, float, float, int]]]] = [
    ("KE", "Bomet", [("Bomet", -0.78, 35.34, 40_000)]),
    ("MR", "Tagant", [("Tidjikja", 18.55, -11.42, 20_000)]),
    ("MR", "Nouakchott Sud", []),
    ("NA", "Kavango West", [("Nkurenkuru", -17.62, 18.61, 10_000)]),
    ("NA", "Kunene", [("Opuwo", -18.06, 13.84, 20_000)]),
    ("NA", "Omusati", [("Outapi", -17.50, 15.00, 30_000)]),
    ("SO", "Bakool", [("Xuddur", 4.12, 43.89, 60_000)]),
    ("BW", "Kgalagadi", [("Tsabong", -26.02, 22.40, 10_000)]),
    ("BW", "Chobe", [("Kasane", -17.80, 25.15, 10_000)]),
]

#: Etiquettes a nettoyer par SUFFIXE (KE/NA/MG) — libelle officiel sans le mot
#: administratif colle.
SUFFIXES_SALES = (" County", " county", " Region", " region")

#: Attendus officiels apres reconciliation — la VERIFICATION finale.
ATTENDUS = {"KE": 47, "MR": 15, "NA": 14, "NG": 37, "AO": 21, "BJ": 12,
            "MG": 23, "SO": 18, "GM": 7, "BW": 13, "CM": 10}


async def executer(par: str, a_blanc: bool) -> int:
    base = charger_referentiel(CLASSEUR)
    connect()
    await ensure_indexes()
    try:
        depot = SurcoucheRepository()
        surcouche, meta = await depot.charger()

        def region_de(iso: str, nom: str) -> Region | None:
            return next(
                (r for r in surcouche.regions.values()
                 if r.country_iso2 == iso and r.name == nom),
                None,
            )

        actions = 0
        problemes: list[str] = []

        # 1) RENOMMAGES (surcouche seulement — le classeur est immuable)
        for iso, actuel, officiel in RENOMMAGES:
            cible = region_de(iso, actuel)
            if cible is None:
                continue
            print(f"RENOMME {iso} : {actuel!r} -> {officiel!r}")
            actions += 1
            if not a_blanc:
                surcouche.regions[cible.region_id] = replace(cible, name=officiel)
                surcouche.journal.append(f"region {actuel!r} renommee {officiel!r} ({iso})")

        #    + suffixes sales
        for rid, region in list(surcouche.regions.items()):
            if region.country_iso2 in ("KE", "NA", "MG"):
                propre = region.name
                for suffixe in SUFFIXES_SALES:
                    propre = propre.removesuffix(suffixe)
                if propre != region.name:
                    print(f"RENOMME {region.country_iso2} : {region.name!r} -> {propre!r}")
                    actions += 1
                    if not a_blanc:
                        surcouche.regions[rid] = replace(region, name=propre)

        # 2) FUSIONS d'orthographe — villes re-rattachees, doublon retire
        for iso, doublon_nom, canonique_nom in FUSIONS:
            doublon = region_de(iso, doublon_nom)
            canonique = region_de(iso, canonique_nom) or next(
                (r for r in charger_referentiel(CLASSEUR).regions.values()
                 if r.country_iso2 == iso and r.name == canonique_nom), None)
            if doublon is None:
                continue
            if canonique is None:
                problemes.append(f"{iso} : canonique {canonique_nom!r} introuvable")
                continue
            enfants = [v for v in surcouche.villes.values() if v.region_id == doublon.region_id]
            print(f"FUSION {iso} : {doublon_nom!r} -> {canonique_nom!r} ({len(enfants)} ville(s))")
            actions += 1
            if not a_blanc:
                for ville in enfants:
                    surcouche.villes[ville.city_id] = replace(
                        ville, region_id=canonique.region_id)
                del surcouche.regions[doublon.region_id]
                surcouche.journal.append(
                    f"region {doublon_nom!r} fusionnee dans {canonique_nom!r} ({iso})")

        # 3) NIVEAUX — Somalie : etats federaux redescendus
        for etat, rattachements in NIVEAUX_SO.items():
            cible = region_de("SO", etat)
            if cible is None:
                continue
            print(f"NIVEAU SO : etat {etat!r} retire, villes -> {rattachements}")
            actions += 1
            if not a_blanc:
                for v in [x for x in surcouche.villes.values() if x.region_id == cible.region_id]:
                    destination_nom = rattachements.get(v.name)
                    destination = region_de("SO", destination_nom) if destination_nom else None
                    if destination is None:
                        problemes.append(f"SO : {v.name} sans region de destination — NON retire")
                        break
                else:
                    for v in [x for x in surcouche.villes.values()
                              if x.region_id == cible.region_id]:
                        destination = region_de("SO", rattachements[v.name])
                        assert destination is not None  # pre-verifie ci-dessus
                        surcouche.villes[v.city_id] = replace(
                            v, region_id=destination.region_id)
                    del surcouche.regions[cible.region_id]
                    surcouche.journal.append(
                        f"etat federal {etat!r} redescendu — villes aux regions officielles (SO)")

        # 4) AJOUTS des manquants officiels
        for iso, nom_region, villes in AJOUTS:
            if region_de(iso, nom_region) is not None:
                continue
            print(f"AJOUT {iso} : region {nom_region!r} + {len(villes)} chef(s)-lieu(x)")
            actions += 1
            if a_blanc:
                continue
            try:
                nouvelle = surcouche.ajouter_region(base, pays=iso, nom=nom_region)
                for nom_ville, lat, lon, pop in villes:
                    deja = any(v.country_iso2 == iso and v.name == nom_ville
                               for v in surcouche.villes.values())
                    if not deja:
                        surcouche.ajouter_ville(
                            base, region_id=nouvelle.region_id, nom=nom_ville,
                            latitude=lat, longitude=lon, population=pop,
                            poids_economique=3.0)
            except AjoutRefuse as erreur:
                problemes.append(f"{iso}/{nom_region} : {erreur}")

        print(f"\n{actions} action(s).")
        for motif in problemes:
            print(f"⚠ {motif}")
        if a_blanc:
            print("A BLANC — rien n'est enregistre.")
            return 0
        nouvelle_meta = await depot.enregistrer(surcouche, par=par)
        print(f"Enregistre : v{meta['version']} -> v{nouvelle_meta['version']}")

        # VERIFICATION contre les decomptes OFFICIELS
        relue, _ = await depot.charger()
        verif = relue.appliquer(base)
        ecarts = []
        for iso, attendu in sorted(ATTENDUS.items()):
            reel = len(verif.regions_du_pays(iso))
            marque = "OK " if reel == attendu else "ECART"
            if reel != attendu:
                ecarts.append(iso)
            print(f"[{marque}] {iso} : {reel} regions (officiel {attendu})")
        orphelines = [v.name for v in verif.villes.values() if v.region_id not in verif.regions]
        print(f"villes orphelines : {len(orphelines)}")
        return 1 if (ecarts or orphelines or problemes) else 0
    finally:
        close()


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--par", default="reconciliation-decoupages-22-08")
    analyseur.add_argument("--a-blanc", action="store_true")
    arguments = analyseur.parse_args()
    sys.exit(asyncio.run(executer(arguments.par, arguments.a_blanc)))
