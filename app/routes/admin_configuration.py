"""
app/routes/admin_configuration.py
=================================
`US-B1` / `US-B2` / `US-B3` — la configuration du Loader, lue et editee par le
Super-Admin. (`US-B4`, l'ajout de ville, exige la persistance de la surcouche
referentielle — tranche suivante, dit franchement.)

TROIS REGLES QUI GOUVERNENT TOUTES LES ECRITURES ICI :

1. **Verrou EF-55** — pendant un run (RUNNING/PAUSED), toute ecriture est 409
   avec l'identifiant du run : modifier la configuration sous un run en cours
   rendrait son empreinte D-10 mensongere.
2. **Les quotas contractuels ne sont PAS parametrables en v1.** `part_femmes`
   (EF-22 : deux femmes pour un homme) et `part_corporate` (EF-23 : 80/20)
   sont des exigences EXACTES du CDC, pas des reglages. Les accepter ici
   fabriquerait silencieusement des runs non conformes que la recette
   denoncerait ensuite — le refus arrive AVANT, 422 avec l'exigence citee.
3. **Ce qui est parametrable l'est DANS des bornes dites.** Le CDC dit
   « parametrable » (§349, EF-10, EF-14→17, EF-20) sans donner de nombre ;
   les bornes de vraisemblance sont donc les notres, declarees sur chaque
   champ — jamais un rejet sans regle nommee.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.cdc import NB_CLIENTS, PAYS_CIBLES
from app.core.configuration import (
    DEFAUTS_CDC,
    PART_FEMMES_CDC,
    ConfigurationExecution,
    Surcharge,
)
from app.repositories.configuration import ConfigurationRepository
from app.routes.dependances import SessionAdmin, admin_complet, refuser_si_run_en_cours

router = APIRouter(prefix="/admin/configuration", tags=["admin — configuration"])


# --------------------------------------------------------------------------
# Schemas d'entree — `extra="forbid"` : un champ inconnu est un 422, jamais
# un champ ignore en silence (la lecon des services FinZuu, encore).
# --------------------------------------------------------------------------


class SurchargePaysDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Cible de clients IMPOSEE a ce pays ; les autres se partagent le reste.
    clients: int | None = Field(default=None, ge=0, le=100_000)
    #: Fourchettes (min, max) — EF-10/EF-16/UC-09.
    companies: tuple[int, int] | None = None
    kiosques: tuple[int, int] | None = None
    staff: tuple[int, int] | None = None
    #: Plafonds — EF-14/EF-15/EF-17. None = « la geographie decide ».
    branches: int | None = Field(default=None, ge=1, le=1_000)
    agences: int | None = Field(default=None, ge=1, le=1_000)
    agents: int | None = Field(default=None, ge=1, le=10_000)


class ConfigurationDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nb_clients: int | None = Field(
        default=None,
        ge=1,
        le=100_000,
        description=f"Total global (defaut CDC : {NB_CLIENTS}). Reparti entre pays actifs.",
    )
    pays: dict[str, SurchargePaysDemande] = Field(default_factory=dict)


class EtatPaysDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actif: bool
    motif: str = ""


# --------------------------------------------------------------------------
# Garde-fous
# --------------------------------------------------------------------------


#: Verrou EF-55, partage avec les referentiels — defini dans `dependances`.
_refuser_si_run_en_cours = refuser_si_run_en_cours


def _valider_fourchettes(code: str, demande: SurchargePaysDemande) -> None:
    for nom in ("companies", "kiosques", "staff"):
        bornes = getattr(demande, nom)
        if bornes is None:
            continue
        basse, haute = bornes
        if basse < 1 or haute < basse or haute > 10_000:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{code}.{nom}={list(bornes)} : fourchette invalide — "
                    "attendu 1 <= min <= max <= 10000 (EF-10/EF-16/UC-09, "
                    "« parametrable » ne veut pas dire « invraisemblable »)"
                ),
            )


# --------------------------------------------------------------------------
# Lecture — US-B1
# --------------------------------------------------------------------------


def _vue_resolue(
    configuration: ConfigurationExecution, meta: dict[str, Any]
) -> dict[str, Any]:
    """Chaque valeur AVEC son origine — l'origine fait partie de la donnee."""
    repartition = configuration.repartir_clients()
    pays: dict[str, Any] = {}
    for code, fiche in sorted(configuration.pays.items()):
        quantites: dict[str, Any] = {}
        for nom in ("companies", "kiosques", "staff", "branches", "agences", "agents"):
            impose = fiche.surcharge.valeur(nom)
            quantites[nom] = {
                "valeur": impose if impose is not None else DEFAUTS_CDC.get(nom),
                "origine": "surcharge pays" if impose is not None else "défaut CDC",
            }
        quantites["clients"] = {
            "valeur": repartition.get(code, 0),
            "origine": (
                "surcharge pays"
                if fiche.surcharge.clients is not None
                else (
                    f"défaut CDC ({configuration.nb_clients}"
                    f"/{len(configuration.pays_actifs) or 1})"
                )
            ),
        }
        pays[code] = {
            "actif": fiche.actif,
            "motif_inactivite": fiche.motif_inactivite,
            "quantites": quantites,
            #: Les surcharges plus fines existent (region/ville, CFG-04) mais ne
            #: s'editent pas encore par l'API — montrees telles quelles.
            "surcharges_regions": sorted(fiche.regions),
            "surcharges_villes": sorted(fiche.villes),
        }
    return {
        "nb_clients": {
            "valeur": configuration.nb_clients,
            "origine": "paramétré" if configuration.nb_clients != NB_CLIENTS else "défaut CDC",
        },
        "repartition_clients": repartition,
        "pays": pays,
        "quotas_contractuels": {
            "part_femmes": {"valeur": PART_FEMMES_CDC, "origine": "EF-22 — non paramétrable"},
            "part_corporate": {
                "valeur": DEFAUTS_CDC["part_corporate"],
                "origine": "EF-23 — non paramétrable",
            },
        },
        "conforme_au_cdc": configuration.conforme_au_cdc,
        "ecarts_au_cdc": configuration.ecarts_au_cdc(),
        "version": meta["version"],
        "modifie_par": meta["modifie_par"],
        "modifie_le": meta["modifie_le"],
    }


@router.get("")
async def lire_configuration(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-B1` — l'etat resolu complet : chaque valeur avec son origine."""
    configuration, meta = await ConfigurationRepository().charger()
    return _vue_resolue(configuration, meta)


# --------------------------------------------------------------------------
# Ecritures — US-B2 / US-B3
# --------------------------------------------------------------------------


@router.put("")
async def modifier_configuration(
    demande: ConfigurationDemande,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-B2` — volumes et surcharges par pays.

    Persistee puis RELUE : la reponse est la vue resolue issue de la base,
    jamais un echo de la demande (FRA-218, applique a nous-memes).
    """
    await _refuser_si_run_en_cours()

    depot = ConfigurationRepository()
    configuration, _ = await depot.charger()

    if demande.nb_clients is not None:
        configuration.nb_clients = demande.nb_clients

    for code_brut, surcharge in demande.pays.items():
        code = code_brut.strip().upper()
        if code not in configuration.pays:
            raise HTTPException(
                status_code=422,
                detail=f"pays {code!r} hors des cibles {sorted(PAYS_CIBLES)} (EF-05)",
            )
        _valider_fourchettes(code, surcharge)
        fiche = configuration.pays[code]
        actuel = fiche.surcharge
        fiche.surcharge = Surcharge(
            clients=surcharge.clients if surcharge.clients is not None else actuel.clients,
            companies=surcharge.companies or actuel.companies,
            kiosques=surcharge.kiosques or actuel.kiosques,
            staff=surcharge.staff or actuel.staff,
            branches=surcharge.branches or actuel.branches,
            agences=surcharge.agences or actuel.agences,
            agents=surcharge.agents or actuel.agents,
            # EF-22/EF-23 : contractuels, jamais surcharges par l'API (v1).
            part_femmes=actuel.part_femmes,
            part_corporate=actuel.part_corporate,
        )

    imposes = sum(
        fiche.surcharge.clients or 0
        for code, fiche in configuration.pays.items()
        if fiche.actif and fiche.surcharge.clients is not None
    )
    if imposes > configuration.nb_clients:
        raise HTTPException(
            status_code=422,
            detail=(
                f"les cibles par pays ({imposes}) depassent le total "
                f"({configuration.nb_clients}) — rien n'est corrige en silence"
            ),
        )

    meta = await depot.enregistrer(configuration, par=session.email)
    return _vue_resolue(configuration, meta)


@router.put("/pays/{code}")
async def changer_etat_pays(
    code: str,
    demande: EtatPaysDemande,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-B3` — activer/desactiver un pays COTE LOADER.

    AUCUN appel ne part vers config-service : desactiver chez nous et
    desactiver sur le referentiel partage sont deux actes distincts (A-08),
    et le second n'existe pas encore dans cette API — volontairement.
    """
    await _refuser_si_run_en_cours()

    depot = ConfigurationRepository()
    configuration, _ = await depot.charger()
    cible = code.strip().upper()
    if cible not in configuration.pays:
        raise HTTPException(status_code=404, detail=f"pays {cible!r} inconnu")

    if demande.actif:
        configuration.pays[cible].reactiver()
    else:
        restants = [p for p in configuration.pays_actifs if p != cible]
        if not restants:
            raise HTTPException(
                status_code=422,
                detail=(
                    "impossible de desactiver le dernier pays actif — un run "
                    "sans aucun pays n'a pas de sens (EF-05)"
                ),
            )
        configuration.desactiver_pays(cible, demande.motif)

    meta = await depot.enregistrer(configuration, par=session.email)
    return _vue_resolue(configuration, meta)


# ---------------------------------------------------------------------------
# SCENARIOS NOMMES (16/08, recommandation validee par Yaniv) — des presets de
# configuration REJOUABLES : « Demo client 200 », « Recette 2000 »... Un
# scenario est UNE ConfigurationDemande nommee ; l'appliquer passe par le
# MEME chemin que le PUT (gardes comprises) — jamais un chemin parallele.
# ---------------------------------------------------------------------------

_ID_SCENARIOS = "scenarios_admin"


class ScenarioDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=3, max_length=60)
    demande: ConfigurationDemande


async def _scenarios() -> list[dict[str, Any]]:
    from app.core.database import COLLECTION_LOADER_CONFIGURATION, get_collection

    document = await get_collection(COLLECTION_LOADER_CONFIGURATION).find_one(
        {"_id": _ID_SCENARIOS}
    )
    return list((document or {}).get("scenarios", []))


@router.get("/scenarios")
async def lister_scenarios(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    scenarios = await _scenarios()
    return {
        "scenarios": scenarios,
        "compte": len(scenarios),
        "note": (
            "un scenario est une DEMANDE de configuration nommee — l'appliquer "
            "passe par le meme chemin que le PUT, gardes comprises (EF-55, "
            "bornes, quotas verrouilles)"
        ),
    }


@router.post("/scenarios", status_code=201)
async def sauver_scenario(
    demande: ScenarioDemande,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Sauve un preset — 409 si le nom existe (remplacer = supprimer PUIS
    sauver : jamais d'ecrasement silencieux)."""
    from datetime import UTC, datetime

    from app.core.database import COLLECTION_LOADER_CONFIGURATION, get_collection

    nom = demande.nom.strip()
    if any(s.get("nom") == nom for s in await _scenarios()):
        raise HTTPException(
            status_code=409,
            detail=(
                f"le scenario {nom!r} existe deja — le supprimer d'abord, "
                "jamais d'ecrasement silencieux"
            ),
        )
    fiche = {
        "nom": nom,
        "demande": demande.demande.model_dump(exclude_none=True),
        "cree_par": session.email,
        "cree_le": datetime.now(tz=UTC).isoformat(),
    }
    await get_collection(COLLECTION_LOADER_CONFIGURATION).update_one(
        {"_id": _ID_SCENARIOS}, {"$push": {"scenarios": fiche}}, upsert=True
    )
    return {"scenario": fiche, "note": "applicable via POST /scenarios/{nom}/appliquer"}


@router.delete("/scenarios/{nom}")
async def supprimer_scenario(
    nom: str,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    from app.core.database import COLLECTION_LOADER_CONFIGURATION, get_collection

    resultat = await get_collection(COLLECTION_LOADER_CONFIGURATION).update_one(
        {"_id": _ID_SCENARIOS}, {"$pull": {"scenarios": {"nom": nom.strip()}}}
    )
    if not resultat.modified_count:
        raise HTTPException(status_code=404, detail=f"scenario {nom!r} inconnu")
    return {"supprime": nom.strip()}


@router.post("/scenarios/{nom}/appliquer")
async def appliquer_scenario(
    nom: str,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Applique le preset PAR le chemin du PUT — les gardes valent (EF-55,
    bornes, pays hors cibles, totaux) et la reponse est la vue RELUE."""
    cible = next((s for s in await _scenarios() if s.get("nom") == nom.strip()), None)
    if cible is None:
        raise HTTPException(status_code=404, detail=f"scenario {nom!r} inconnu")
    demande = ConfigurationDemande.model_validate(cible.get("demande") or {})
    return await modifier_configuration(demande, session)
