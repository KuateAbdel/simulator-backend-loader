"""
app/repositories/surcouche.py
=============================
Persistance de la SURCOUCHE referentielle — le prealable d'`US-B4`.

La `SurcoucheReferentiel` (CFG-03/CFG-05) validait et fusionnait, mais vivait
EN MEMOIRE : une ville ajoutee mourait avec le processus. L'exposer par l'API
sans la persister aurait fabrique un ecran menteur — le Super-Admin aurait
« ajoute » des villes que le prochain redemarrage oubliait.

Elle vit dans la MEME collection que la configuration (`loader_configuration`,
document `_id="surcouche"`) : les deux sont la meme chose — l'INTENTION
courante du Super-Admin, versionnee, que le prochain run fige dans son
empreinte (D-10/ENF-15). Pas de 8e collection pour un second singleton de
meme nature.

La serialisation est COMPLETE (tous les champs des dataclasses `Region`,
`City`, `District`) — `ajouts()` ne garde que les noms pour l'empreinte du
run, ce qui ne suffit pas a reconstruire. Ici, l'inverse exact existe :
`charger()` rend une surcouche identique a celle qui a ete enregistree.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from app.core.database import COLLECTION_LOADER_CONFIGURATION, get_collection
from app.services.geographie import City, Devise, District, Pays, Region, Telco
from app.services.surcouche_referentiel import SurcoucheReferentiel

_ID_SINGLETON = "surcouche"


class SurcoucheRepository:
    @property
    def collection(self) -> Any:
        return get_collection(COLLECTION_LOADER_CONFIGURATION)

    async def charger(self) -> tuple[SurcoucheReferentiel, dict[str, Any]]:
        """Rend (surcouche, meta). Sans document : une surcouche VIDE, version
        0 — le referentiel est alors exactement celui du classeur."""
        document = await self.collection.find_one({"_id": _ID_SINGLETON})
        if document is None:
            return SurcoucheReferentiel(), {
                "version": 0,
                "modifie_par": None,
                "modifie_le": None,
            }
        surcouche = SurcoucheReferentiel(
            pays={i: Pays(**p) for i, p in (document.get("pays") or {}).items()},
            # `pays` d'une Devise est un frozenset — Mongo le stocke en liste,
            # l'inverse exact est refait ici (meme promesse que le docstring).
            devises={
                i: Devise(**{**d, "pays": frozenset(d.get("pays") or ())})
                for i, d in (document.get("devises") or {}).items()
            },
            regions={i: Region(**r) for i, r in (document.get("regions") or {}).items()},
            villes={i: City(**v) for i, v in (document.get("villes") or {}).items()},
            quartiers={i: District(**q) for i, q in (document.get("quartiers") or {}).items()},
            telcos={i: Telco(**t) for i, t in (document.get("telcos") or {}).items()},
            secteurs={nom: tuple(inds) for nom, inds in (document.get("secteurs") or {}).items()},
            secteurs_types={
                nom: tuple(ts) for nom, ts in (document.get("secteurs_types") or {}).items()
            },
            industries_ajoutees=list(document.get("industries_ajoutees") or []),
            formes_juridiques=list(document.get("formes_juridiques") or []),
            fonctions_dirigeant=list(document.get("fonctions_dirigeant") or []),
            professions={g: list(ps) for g, ps in (document.get("professions") or {}).items()},
            journal=list(document.get("journal") or []),
        )
        return surcouche, {
            "version": int(document.get("version", 0)),
            "modifie_par": document.get("modifie_par"),
            "modifie_le": document.get("modifie_le"),
        }

    async def enregistrer(self, surcouche: SurcoucheReferentiel, *, par: str) -> dict[str, Any]:
        maintenant = datetime.now(tz=UTC).isoformat()
        await self.collection.update_one(
            {"_id": _ID_SINGLETON},
            {
                "$set": {
                    "pays": {i: asdict(p) for i, p in surcouche.pays.items()},
                    "devises": {
                        i: {**asdict(d), "pays": sorted(d.pays)}
                        for i, d in surcouche.devises.items()
                    },
                    "regions": {i: asdict(r) for i, r in surcouche.regions.items()},
                    "villes": {i: asdict(v) for i, v in surcouche.villes.items()},
                    "quartiers": {i: asdict(q) for i, q in surcouche.quartiers.items()},
                    "telcos": {i: asdict(t) for i, t in surcouche.telcos.items()},
                    "secteurs": {nom: list(inds) for nom, inds in surcouche.secteurs.items()},
                    "secteurs_types": {
                        nom: list(ts) for nom, ts in surcouche.secteurs_types.items()
                    },
                    "industries_ajoutees": list(surcouche.industries_ajoutees),
                    "formes_juridiques": list(surcouche.formes_juridiques),
                    "fonctions_dirigeant": [dict(d) for d in surcouche.fonctions_dirigeant],
                    "professions": {g: list(ps) for g, ps in surcouche.professions.items()},
                    "journal": list(surcouche.journal),
                    "modifie_par": par,
                    "modifie_le": maintenant,
                },
                "$inc": {"version": 1},
            },
            upsert=True,
        )
        document = await self.collection.find_one({"_id": _ID_SINGLETON})
        return {
            "version": int(document["version"]) if document else 1,
            "modifie_par": par,
            "modifie_le": maintenant,
        }
