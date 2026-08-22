"""
scripts/auditer_fusionner_regions.py
====================================
AUDIT D'INTEGRITE des regions + fusion des doublons de TRADUCTION (22/08).

LE DEFAUT (attrape par Yaniv a l'ecran : « le Cameroun a 17 regions ?! ») :
GeoNames livre certaines subdivisions en ANGLAIS (« Far North »,
« North-West », « Abidjan Autonomous District ») la ou notre referentiel
porte le francais officiel (« Extreme-Nord », « Nord-Ouest », « District
Autonome d'Abidjan »). Ma cle de fusion normalisait accents/casse/suffixes
mais NE TRADUISAIT PAS — l'import a donc cree des doublons anglais.

LA METHODE (rien d'invente) :
  1. AUDIT des 48 pays : cle de comparaison traduite (nord/sud/est/ouest,
     extreme/haut/bas, district autonome...) et insensible a l'ordre des mots.
  2. FUSION par groupe de doublons : le CANONIQUE est la region du CLASSEUR
     si elle existe, sinon la forme FRANCAISE ; les villes des doublons sont
     RE-RATTACHEES au canonique (EF-02 tenu — aucune ville en l'air) ; le
     doublon (toujours un ajout SC-*) est retire. Le classeur n'est jamais
     touche.
  3. Chaque fusion est LISTEE a blanc avant toute ecriture.

Usage :
    PYTHONPATH=. .venv/bin/python scripts/auditer_fusionner_regions.py [--a-blanc] [--par email]
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
from scripts.normalisation_geo import cle_toponyme as cle
from scripts.normalisation_geo import est_francaise

CLASSEUR = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")

async def executer(par: str, a_blanc: bool) -> int:
    base = charger_referentiel(CLASSEUR)
    connect()
    await ensure_indexes()
    try:
        depot = SurcoucheRepository()
        surcouche, meta = await depot.charger()
        referentiel = surcouche.appliquer(base)

        # 1) AUDIT : groupes de regions partageant la meme cle traduite
        groupes: dict[tuple[str, str], list[Region]] = {}
        for region in referentiel.regions.values():
            groupes.setdefault((region.country_iso2, cle(region.name)), []).append(region)

        fusions: list[tuple[Region, list[Region]]] = []
        for (pays, _cle_commune), membres in sorted(groupes.items()):
            if len(membres) < 2:
                continue
            # canonique : classeur d'abord (id sans prefixe SC-), sinon francais
            canonique = next(
                (m for m in membres if not m.region_id.startswith("SC-")),
                None,
            ) or next((m for m in membres if est_francaise(m.name)), membres[0])
            doublons = [m for m in membres if m.region_id != canonique.region_id]
            if any(not d.region_id.startswith("SC-") for d in doublons):
                print(f"⚠ {pays} : doublon DANS LE CLASSEUR ({[m.name for m in membres]}) "
                      "— hors perimetre de ce script, a arbitrer a la main")
                continue
            fusions.append((canonique, doublons))

        if not fusions:
            print("AUDIT : aucun doublon de region sur les 48 pays — rien a faire.")
            return 0

        villes_reparentees = 0
        for canonique, doublons in fusions:
            noms = " + ".join(f"{d.name!r}" for d in doublons)
            enfants = [
                v for v in surcouche.villes.values()
                if v.region_id in {d.region_id for d in doublons}
            ]
            print(f"FUSION {canonique.country_iso2} : {noms} -> {canonique.name!r} "
                  f"({len(enfants)} ville(s) re-rattachee(s))")
            if a_blanc:
                villes_reparentees += len(enfants)
                continue
            for ville in enfants:
                surcouche.villes[ville.city_id] = replace(
                    ville, region_id=canonique.region_id
                )
                villes_reparentees += 1
            for doublon in doublons:
                del surcouche.regions[doublon.region_id]
                surcouche.journal.append(
                    f"region {doublon.name!r} ({doublon.region_id}) fusionnee dans "
                    f"{canonique.name!r} — doublon de traduction GeoNames"
                )

        print(f"\nBILAN : {sum(len(d) for _, d in fusions)} region(s) doublonnee(s) "
              f"sur {len({c.country_iso2 for c, _ in fusions})} pays, "
              f"{villes_reparentees} ville(s) re-rattachee(s) — EF-02 tenu.")
        if a_blanc:
            print("A BLANC — rien n'est enregistre.")
            return 0
        nouvelle = await depot.enregistrer(surcouche, par=par)
        print(f"Enregistre : v{meta['version']} -> v{nouvelle['version']}")
        # VERIFICATION apres ecriture : plus aucun groupe > 1
        relue, _ = await depot.charger()
        verif = relue.appliquer(base)
        restants: dict[tuple[str, str], list[str]] = {}
        for region in verif.regions.values():
            restants.setdefault((region.country_iso2, cle(region.name)), []).append(region.name)
        doublons_restants = {k: v for k, v in restants.items() if len(v) > 1}
        if doublons_restants:
            print(f"⚠ VERIF : il RESTE des doublons : {doublons_restants}")
            return 1
        print("VERIF post-ecriture : 0 doublon sur les 48 pays. "
              f"CM = {len(verif.regions_du_pays('CM'))} regions.")
        return 0
    finally:
        close()


if __name__ == "__main__":
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--par", default="audit-fusion-regions-22-08")
    analyseur.add_argument("--a-blanc", action="store_true")
    arguments = analyseur.parse_args()
    sys.exit(asyncio.run(executer(arguments.par, arguments.a_blanc)))
