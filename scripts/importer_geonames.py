"""
scripts/importer_geonames.py
============================
Import GeoNames — LA source de verite de la geographie africaine (22/08,
exigence Yaniv : « une source sure, au millimetre »).

GeoNames (geonames.org, licence CC-BY) est le gazetier mondial de reference :
`admin1CodesASCII.txt` porte les subdivisions officielles de premier niveau,
`cities15000.txt` toutes les villes de plus de 15 000 habitants avec GPS et
population. On en tire, pour CHAQUE pays du Loader (les 44 de la surcouche ET
les 4 du classeur — US-B4 les enrichit sans toucher au classeur) :

  - les regions admin1 : REUTILISEES si deja chez nous (correspondance de nom
    NORMALISE — accents, casse, suffixes « Region/Province/State » —, jamais
    un doublon), creees sinon ;
  - les villes >= 15 000 hab : GET-avant-POST par nom normalise contre tout
    l'existant (classeur + surcouche), GPS et population GeoNames.

Meme discipline que les autres imports : surcouche du Loader UNIQUEMENT,
invariants EF-02 ligne a ligne, relance sans doublon, trous DITS.

Usage :
    PYTHONPATH=. .venv/bin/python scripts/importer_geonames.py \
        <cities15000.txt> <admin1CodesASCII.txt> [--a-blanc] [--par email]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import unicodedata
from pathlib import Path

from app.core.database import close, connect, ensure_indexes
from app.repositories.surcouche import SurcoucheRepository
from app.services.geographie import charger_referentiel
from app.services.surcouche_referentiel import AjoutRefuse

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")

#: Mots generiques que GeoNames accole aux subdivisions et que nos libelles
#: n'ont pas — retires AVANT comparaison, jamais des libelles stockes.
MOTS_GENERIQUES = {
    "region", "province", "district", "state", "county", "prefecture",
    "governorate", "division", "area", "zone", "city", "municipality",
    "department", "departement", "wilaya", "regional", "de", "du",
    "la", "le", "of", "the",
}


def normaliser(nom: str) -> str:
    """Cle de comparaison : sans accents, sans casse, sans mots generiques."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", nom) if unicodedata.category(c) != "Mn"
    )
    mots = [m for m in sans_accents.lower().replace("-", " ").split() if m not in MOTS_GENERIQUES]
    return " ".join(mots) or sans_accents.lower().strip()


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


async def importer(villes_txt: Path, admin1_txt: Path, par: str, a_blanc: bool) -> int:
    base = charger_referentiel(CLASSEUR)
    connect()
    await ensure_indexes()
    try:
        depot = SurcoucheRepository()
        surcouche, meta = await depot.charger()
        referentiel = surcouche.appliquer(base)
        pays_du_loader = set(referentiel.pays_index)

        # admin1 : (pays, code) -> libelle ASCII officiel
        admin1: dict[tuple[str, str], str] = {}
        lignes_admin1 = admin1_txt.read_text(encoding="utf-8").splitlines()  # noqa: ASYNC240 — script CLI, aucune boucle evenementielle concurrente
        for ligne in lignes_admin1:
            champs = ligne.split("\t")
            if len(champs) < 3 or "." not in champs[0]:
                continue
            cc, code = champs[0].split(".", 1)
            if cc in pays_du_loader:
                admin1[(cc, code)] = champs[2] or champs[1]

        # index de l'existant, par nom normalise
        from app.services.geographie import Region

        regions_existantes: dict[tuple[str, str], Region] = {}
        for region in referentiel.regions.values():
            regions_existantes[(region.country_iso2, normaliser(region.name))] = region
        villes_existantes: dict[tuple[str, str], bool] = {}
        for ville in referentiel.villes.values():
            villes_existantes[(ville.country_iso2, normaliser(ville.name))] = True

        stats = {"regions": 0, "villes": 0, "reprises": 0, "deja": 0}
        refus: list[str] = []
        par_pays: dict[str, int] = {}

        lignes_villes = villes_txt.read_text(encoding="utf-8").splitlines()  # noqa: ASYNC240 — idem
        for ligne in lignes_villes:
            champs = ligne.split("\t")
            if len(champs) < 15:
                continue
            cc = champs[8]
            if cc not in pays_du_loader:
                continue
            nom = champs[2] or champs[1]  # asciiname, coherent avec nos libelles
            cle_ville = (cc, normaliser(nom))
            if villes_existantes.get(cle_ville):
                stats["deja"] += 1
                continue
            capitale = champs[7] == "PPLC"
            lat, lon = round(float(champs[4]), 3), round(float(champs[5]), 3)
            population = int(champs[14] or 0)

            nom_region = admin1.get((cc, champs[10]))
            if not nom_region:
                refus.append(f"{cc}/{nom} : admin1 {champs[10]!r} inconnu — ville sautee")
                continue
            region: Region | None = regions_existantes.get((cc, normaliser(nom_region)))
            if region is not None:
                stats["reprises"] += 1
            else:
                try:
                    region = surcouche.ajouter_region(base, pays=cc, nom=nom_region)
                    regions_existantes[(cc, normaliser(nom_region))] = region
                    stats["regions"] += 1
                except AjoutRefuse as erreur:
                    refus.append(f"region {cc}/{nom_region} : {erreur}")
                    continue
            try:
                surcouche.ajouter_ville(
                    base,
                    region_id=region.region_id,
                    nom=nom,
                    latitude=lat,
                    longitude=lon,
                    population=population or None,
                    poids_economique=poids(population, capitale),
                )
                villes_existantes[cle_ville] = True
                stats["villes"] += 1
                par_pays[cc] = par_pays.get(cc, 0) + 1
            except AjoutRefuse as erreur:
                refus.append(f"ville {cc}/{nom} : {erreur}")

        print(
            f"GeoNames : +{stats['regions']} regions creees, "
            f"{stats['reprises']} correspondances de region reutilisees, "
            f"+{stats['villes']} villes (GPS/population GeoNames), "
            f"{stats['deja']} deja presentes"
        )
        print("Par pays : " + " · ".join(f"{p} +{n}" for p, n in sorted(par_pays.items())))
        if refus:
            print(f"REFUS/SAUTS ({len(refus)}) :")
            for motif in refus[:20]:
                print(f"  - {motif}")
            if len(refus) > 20:
                print(f"  ... et {len(refus) - 20} autres")
        print(surcouche.resume())
        if a_blanc:
            print("A BLANC — rien n'est enregistre.")
            return 0
        if stats["villes"] or stats["regions"]:
            nouvelle = await depot.enregistrer(surcouche, par=par)
            print(f"Enregistre : v{meta['version']} -> v{nouvelle['version']}")
        else:
            print("Rien de neuf.")
        return 0
    finally:
        close()


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("villes", type=Path)
    analyseur.add_argument("admin1", type=Path)
    analyseur.add_argument("--par", default="import-geonames-22-08")
    analyseur.add_argument("--a-blanc", action="store_true")
    arguments = analyseur.parse_args()
    sys.exit(
        asyncio.run(importer(arguments.villes, arguments.admin1, arguments.par, arguments.a_blanc))
    )
