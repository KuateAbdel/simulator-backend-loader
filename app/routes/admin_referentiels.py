"""
app/routes/admin_referentiels.py
================================
`US-B5` — les referentiels du Loader, en LECTURE, pour l'ecran de Zidane.

Trois surfaces, une par source de verite :

  /admin/referentiels/geographie          Loader_Base_FinZuu_v1_1.xlsx
  /admin/referentiels/telcos              les 12 plans de numerotation reels
  /admin/referentiels/catalogue-statique  les fichiers de JJB (SD-1)

AUCUNE ecriture ici — un referentiel se remplace par LIVRAISON de fichier
versionnee, jamais par edition de cellules (`US-B5`, « ne peut pas »).
L'ajout de ville (`US-B4`) vit dans la surcouche d'administration, pas ici.

Les deux chargeurs sont des lectures de fichiers validees a l'ouverture
(echec bruyant) ; le resultat est immuable, donc mis en cache PROCESSUS —
le premier appel paie la lecture, les suivants servent la memoire.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.surcouche import SurcoucheRepository
from app.routes.dependances import (
    SessionAdmin,
    admin_complet,
    refuser_si_run_en_cours,
)
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.referentiel_statique import ReferentielStatique, charger_statique
from app.services.surcouche_referentiel import AjoutRefuse

router = APIRouter(prefix="/admin/referentiels", tags=["admin — referentiels"])

CLASSEUR_GEO = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")


@lru_cache(maxsize=1)
def _geo() -> ReferentielGeo:
    return charger_referentiel(CLASSEUR_GEO)


@lru_cache(maxsize=1)
def _statique() -> ReferentielStatique:
    return charger_statique()


@router.get("/geographie")
async def geographie(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """L'arbre complet pays -> regions -> villes (GPS) -> quartiers.

    C'est la matiere des ecrans de selection — 51 regions, 50 villes,
    82 quartiers du classeur, PLUS les ajouts de la surcouche (`US-B4`) :
    l'ecran voit exactement le referentiel que le prochain run utilisera.
    """
    surcouche, meta = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())
    arbre: list[dict[str, Any]] = []
    for pays in sorted({r.country_iso2 for r in referentiel.regions.values()}):
        regions = []
        for region in sorted(referentiel.regions_du_pays(pays), key=lambda r: r.name):
            villes = []
            for ville in sorted(
                referentiel.villes_de_region(region.region_id), key=lambda v: v.name
            ):
                villes.append(
                    {
                        "id": ville.city_id,
                        "nom": ville.name,
                        "latitude": ville.latitude,
                        "longitude": ville.longitude,
                        "quartiers": sorted(
                            q.name for q in referentiel.quartiers_de_ville(ville.city_id)
                        ),
                    }
                )
            regions.append(
                {
                    "id": region.region_id,
                    "nom": region.name,
                    "capitale": region.capitale,
                    "villes": villes,
                }
            )
        arbre.append({"pays": pays, "regions": regions})
    return {
        "pays": arbre,
        "surcouche": {
            "resume": surcouche.resume(),
            "journal": list(surcouche.journal),
            "version": meta["version"],
        },
    }


class VilleDemande(BaseModel):
    """`US-B4` — les champs d'une ville. `extra="forbid"` : un champ inconnu
    est un 422, jamais un champ ignore en silence."""

    model_config = ConfigDict(extra="forbid")

    region_id: str = Field(min_length=1)
    nom: str = Field(min_length=1, max_length=80)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    population: int | None = Field(default=None, ge=1)
    poids_economique: float = Field(default=1.0, gt=0, le=100)


@router.post("/villes", status_code=201)
async def ajouter_ville(
    demande: VilleDemande,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-B4` — l'ajout d'une ville, SANS toucher au classeur (CFG-03/05).

    Le rite habituel : valider chez nous (`EF-02` — la region parente doit
    exister, le nom etre unique dans son pays), persister, puis RELIRE depuis
    la base — la reponse est la ville telle que le prochain run la verra,
    jamais un echo de la demande.

    Verrou `EF-55` : pas d'ajout pendant un run — une ville apparue en cours
    de generation rendrait l'empreinte D-10 mensongere.
    """
    await refuser_si_run_en_cours()

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        ville = surcouche.ajouter_ville(
            _geo(),
            region_id=demande.region_id.strip(),
            nom=demande.nom,
            latitude=demande.latitude,
            longitude=demande.longitude,
            population=demande.population,
            poids_economique=demande.poids_economique,
        )
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus

    meta = await depot.enregistrer(surcouche, par=session.email)

    # RELECTURE — CFG-06 : ce qui est rendu vient de la BASE, pas de la demande.
    relue, _ = await depot.charger()
    fiche = relue.villes[ville.city_id]
    return {
        "ville": {
            "id": fiche.city_id,
            "nom": fiche.name,
            "region_id": fiche.region_id,
            "pays": fiche.country_iso2,
            "latitude": fiche.latitude,
            "longitude": fiche.longitude,
            "population": fiche.population,
            "poids_economique": fiche.poids_economique,
        },
        "surcouche": {
            "resume": relue.resume(),
            "version": meta["version"],
        },
        "avertissements": (
            []
            if fiche.latitude is not None and fiche.longitude is not None
            else [
                "ville sans coordonnees GPS : les adresses derivees n'en auront "
                "pas non plus (EF-03) — le referentiel d'origine en a aussi, "
                "mais autant le savoir maintenant"
            ]
        ),
    }


@router.get("/telcos")
async def telcos(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les operateurs reels, leurs regex de numerotation et leurs parts de
    marche (`EF-27`, `INV-18`)."""
    referentiel = _geo()
    par_pays: dict[str, list[dict[str, Any]]] = {}
    for pays in sorted({r.country_iso2 for r in referentiel.regions.values()}):
        par_pays[pays] = [
            {
                "nom": t.network_name,
                "code": t.short_name,
                "regex_msisdn": t.regex_msisdn,
                "part_marche": t.part_marche,
            }
            for t in referentiel.telcos_du_pays(pays)
        ]
    return {"telcos": par_pays}


@router.get("/catalogue-statique")
async def catalogue_statique(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Le referentiel de JJB (SD-1) : la matiere dont chaque entite est
    composee. Les comptes exacts — 6/112/27/576/21/4/195/20 — sont ceux que
    les tests du chargeur verifient ; ils sont AUSSI dans la reponse, pour que
    l'ecran puisse les afficher et que la recette puisse les comparer."""
    statique = _statique()
    return {
        "comptes": {
            "industries": len(statique.industries),
            "secteurs": len(statique.secteurs),
            "formes_juridiques": len(statique.formes_juridiques),
            "professions": len(statique.professions),
            "groupes": len(statique.groupes),
            "profils_revenu": len(statique.profils_revenu),
            "pays": len(statique.pays),
            "fonctions_dirigeant": len(statique.fonctions_dirigeant),
        },
        "industries": statique.industries,
        "secteurs": {nom: list(inds) for nom, inds in statique.secteurs.items()},
        "formes_juridiques": list(statique.formes_juridiques),
        "groupes": {
            nom: {
                "profil_defaut": groupe.profil_defaut,
                "professions": list(groupe.professions),
                "variants": groupe.variants,
            }
            for nom, groupe in statique.groupes.items()
        },
        "profils_revenu": {
            nom: {"mu": p.mu, "sigma": p.sigma, "definition": p.definition}
            for nom, p in statique.profils_revenu.items()
        },
        "pays": statique.pays,
        "fonctions_dirigeant": [
            {"rang": f.rang, "francais": f.francais, "anglais": f.anglais,
             "abreviation": f.abreviation}
            for f in statique.fonctions_dirigeant
        ],
    }
