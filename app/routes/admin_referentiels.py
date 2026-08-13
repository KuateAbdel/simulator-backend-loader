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


def _config_admin() -> Any:
    """Fabrique du client d'administration config-service — doublee en test."""
    from app.clients.config_service import AdministrationConfigService

    return AdministrationConfigService()


def _config_lecture() -> Any:
    from app.clients.config_service import ConfigServiceClient

    return ConfigServiceClient()


async def _country_id(pays: str) -> str:
    """Le country_id de config-service pour un code ISO — resolu, jamais code
    en dur : les identifiants appartiennent au serveur."""
    lecture = _config_lecture()
    try:
        for fiche in await lecture.lister_pays():
            if str(fiche.get("iso_name", "")).strip().upper() == pays.upper():
                identifiant = fiche.get("_id") or fiche.get("id")
                if identifiant:
                    return str(identifiant)
    finally:
        await lecture.fermer()
    raise ValueError(f"pays {pays!r} introuvable sur config-service")


async def _envoyer_config_service(action: str, cible_locale: str, operation: Any) -> dict[str, Any]:
    """L'ALLER COMPLET (13/08, Yaniv) : enregistre chez nous PUIS envoye a
    config-service. L'ordre est le write-ahead : notre trace d'abord. Un echec
    d'envoi laisse l'ajout LOCAL en place et se DIT — jamais silencieux, et
    l'intention journalisee sous RUN_ADMIN garde la trace des deux issues."""
    from uuid import NAMESPACE_OID, uuid5

    from app.repositories.audit_trail import AuditTrailRepository
    from app.routes.admin_entites import RUN_ADMIN

    audit = AuditTrailRepository()
    try:
        async with audit.intention(
            RUN_ADMIN,
            entity_type="ConfigService",
            entity_id=uuid5(NAMESPACE_OID, f"{action}:{cible_locale}"),
            operation="UPDATE",
            cible="config-service",
            payload={"action": action, "cible": cible_locale},
        ) as suivi:
            fiche = await operation()
            suivi.reussi({"resultat": "envoye"})
        return {"statut": "envoye", "fiche_pays": bool(fiche)}
    except Exception as erreur:
        return {
            "statut": "echec — l'ajout LOCAL reste en place, renvoyer plus tard",
            "motif": f"{type(erreur).__name__}: {str(erreur)[:160]}",
        }


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

    # L'ALLER COMPLET (13/08) : chez nous PUIS chez eux. Seule la VILLE part —
    # region et quartier restent chez nous, config-service n'a aucun champ
    # pour eux (son `region` est la region CONTINENTALE).
    admin = _config_admin()
    try:
        pays_cible = ville.country_iso2

        async def _envoi() -> Any:
            return await admin.ajouter_ville(await _country_id(pays_cible), ville.name)

        envoi = await _envoyer_config_service("ajouter_ville", ville.name, _envoi)
    finally:
        await admin.fermer()

    # RELECTURE — CFG-06 : ce qui est rendu vient de la BASE, pas de la demande.
    relue, _ = await depot.charger()
    fiche = relue.villes[ville.city_id]
    return {
        "config_service": envoi,
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
    """Les operateurs reels + ceux de la surcouche (US-B7), leurs regex et
    leurs parts de marche (`EF-27`, `INV-18`)."""
    surcouche, _meta = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())
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


class TelcoDemande(BaseModel):
    """`US-B7` — l'ajout d'operateur. `exemple_msisdn` est la PREUVE
    d'utilisabilite, exigee de celui qui ajoute."""

    model_config = ConfigDict(extra="forbid")

    pays: str = Field(min_length=2, max_length=2)
    network_name: str = Field(min_length=2, max_length=60)
    short_name: str = Field(min_length=2, max_length=30)
    regex_msisdn: str = Field(min_length=4, max_length=200)
    part_marche: float = Field(gt=0, le=100)
    exemple_msisdn: str = Field(min_length=6, max_length=20)
    ussd_base_code: str = Field(default="", max_length=20)


@router.post("/telcos", status_code=201)
async def ajouter_telco(
    demande: TelcoDemande,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-B7` — l'ajout d'un operateur, sans toucher au classeur.

    Les invariants vivent dans la surcouche (le meme code que le run) :
    regex compilable ET composable, exemple conforme exige, unicite dans le
    pays, et la SOMME des parts <= 100 (INV-18 etendu a l'ecriture). Verrou
    EF-55, relecture depuis la base — le rite habituel.
    """
    await refuser_si_run_en_cours()

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        telco = surcouche.ajouter_telco(
            _geo(),
            pays=demande.pays,
            network_name=demande.network_name,
            short_name=demande.short_name,
            regex_msisdn=demande.regex_msisdn,
            part_marche=demande.part_marche,
            exemple_msisdn=demande.exemple_msisdn,
            ussd_base_code=demande.ussd_base_code,
        )
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus

    meta = await depot.enregistrer(surcouche, par=session.email)

    # L'ALLER COMPLET (13/08) : le telco est CREE sur config-service (regex
    # ancre exige par le client) PUIS rattache au pays — un telco cree mais
    # non rattache n'appartient a aucun pays, les deux gestes vont ensemble.
    admin = _config_admin()
    try:
        async def _envoi() -> Any:
            fiche_telco, _creee = await admin.creer_telco_si_absent(
                telco.network_name, telco.regex_msisdn
            )
            identifiant = fiche_telco.get("_id") or fiche_telco.get("id")
            return await admin.rattacher_telco_au_pays(
                await _country_id(telco.country_iso2), str(identifiant)
            )

        envoi = await _envoyer_config_service("ajouter_telco", telco.network_name, _envoi)
    finally:
        await admin.fermer()

    relue, _ = await depot.charger()
    fiche = relue.telcos[telco.telco_id]
    fusion = relue.appliquer(_geo())
    somme = sum(t.part_marche for t in fusion.telcos_du_pays(demande.pays.upper()))
    return {
        "config_service": envoi,
        "telco": {
            "id": fiche.telco_id,
            "nom": fiche.network_name,
            "code": fiche.short_name,
            "regex_msisdn": fiche.regex_msisdn,
            "part_marche": fiche.part_marche,
            "pays": fiche.country_iso2,
        },
        "somme_parts_du_pays": somme,
        "surcouche": {"resume": relue.resume(), "version": meta["version"]},
    }


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
