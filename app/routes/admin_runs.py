"""
app/routes/admin_runs.py
========================
Lot B — les RUNS pilotes par l'API (`US-C1` a `US-C6`).

Backend pur : ces routes rendent du JSON que l'ecran de Zidane consomme.
« Le bouton Run » du backlog est SA partie ; la notre est ici — le moteur
`app/services/pilotage.py`, LE MEME que le CLI, lance en tache de fond.

LE RITE D-01, RENDU STRUCTUREL PAR LES ROUTES :

    POST /admin/runs                    -> PREPARATION (DRY_RUN, toujours)
    POST /admin/runs/{id}/confirmer     -> le REAL, sur le perimetre FIGE de
                                           cette preparation — et 409 si la
                                           configuration a change entre les
                                           deux : « re-preparer »

Il n'existe AUCUNE route qui lance un REAL sans preparation prealable. Ce
n'est pas une consigne d'ecran, c'est l'absence structurelle du chemin.

TACHES DE FOND : un run dure plusieurs minutes — la requete repond 202
immediatement, l'execution continue dans le processus (asyncio), et la
progression se lit dans `loader_runs` (checkpoints poses par l'orchestrateur).
Le registre des taches est LOCAL au processus : c'est suffisant parce que
EF-55 est aussi un index unique Mongo — deux processus ne pourraient de toute
facon pas courir deux runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.configuration import ConfigurationExecution
from app.models.domain import LoaderRun
from app.models.enums import RunMode, RunStatus
from app.repositories.configuration import ConfigurationRepository
from app.repositories.loader_runs import LoaderRunRepository
from app.routes.admin_dashboard import SERVICES_SONDES, _sonder
from app.routes.dependances import (
    SessionAdmin,
    admin_complet,
    exige_super_admin,
    refuser_si_run_en_cours,
)
from app.services.pilotage import executer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/runs", tags=["admin — runs"])

#: Les taches de fond du PROCESSUS. EF-55 (index unique Mongo) garantit
#: l'unicite inter-processus ; ce registre sert l'arret cooperatif local.
_taches: dict[str, asyncio.Task[int]] = {}


class LancementDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Seul DRY_RUN est accepte ici — le REAL passe par /confirmer, toujours.
    mode: str = "DRY_RUN"


def _normaliser(empreinte: dict[str, Any]) -> dict[str, Any]:
    """Mongo rend des listes la ou Python avait des tuples : la comparaison
    d'empreintes passe par JSON pour comparer des VALEURS, pas des types."""
    return dict(json.loads(json.dumps(empreinte, default=str)))


async def _executer_en_fond(
    run_id: UUID, mode: RunMode, configuration: ConfigurationExecution | None
) -> int:
    """Le moteur, cerne de ses obligations de fin : rapport range avec le run,
    tache retiree du registre, echec journalise — jamais silencieux."""
    lignes: list[str] = []
    depot = LoaderRunRepository()
    try:
        code = await executer(
            mode,
            run_id=run_id,
            configuration=configuration,
            sortie=lignes.append,
            gerer_connexion=False,
        )
        return code
    except asyncio.CancelledError:
        lignes.append(
            "ARRET DEMANDE PAR LE SUPER-ADMIN — le run est clos en FAILED : "
            "un etat terminal et VRAI. Les reconciliations du prochain run "
            "diront ce qui reste a verifier."
        )
        raise
    except Exception:
        logger.exception("run %s : echec du moteur", run_id)
        raise
    finally:
        try:
            await depot.attacher_rapport(run_id, "\n".join(lignes))
        except Exception:  # pragma: no cover — defense d'exploitation
            logger.exception("run %s : rapport non persiste", run_id)
        _taches.pop(str(run_id), None)


def _fiche(run: LoaderRun) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "mode": run.mode.value,
        "statut": run.status.value,
        "sim_start_date": run.sim_start_date.isoformat(),
        "sim_end_date": run.sim_end_date.isoformat(),
        "nb_checkpoints": len(run.checkpoints),
        "configuration": run.configuration,
    }


@router.post("", status_code=202)
async def preparer(
    demande: LancementDemande,
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """`US-C1` — la PREPARATION : un DRY_RUN complet sur l'intention persistee.

    202 immediat avec le `run_id` ; le rapport se lit ensuite sur
    GET /admin/runs/{id}. AUCUNE ecriture ne part vers FinZuu — c'est la
    definition du mode, pas une promesse.
    """
    if demande.mode != "DRY_RUN":
        raise HTTPException(
            status_code=422,
            detail=(
                "seul DRY_RUN se lance ici — le REAL passe par "
                "POST /admin/runs/{id}/confirmer, sur une preparation LUE (D-01)"
            ),
        )
    await refuser_si_run_en_cours()

    run_id = uuid4()
    _taches[str(run_id)] = asyncio.create_task(
        _executer_en_fond(run_id, RunMode.DRY_RUN, None)
    )
    return {"run_id": str(run_id), "mode": "DRY_RUN", "statut": "PENDING"}


def _pays_du_perimetre(preparation: Any) -> list[str]:
    """Les codes ISO2 que le run va REELLEMENT toucher.

    Lus dans l'empreinte FIGEE (`ConfigurationExecution.empreinte()`, cle
    `pays`), et filtres sur `actif` : un pays desactive dans la configuration
    ne recevra aucune ecriture, sa derive eventuelle ne doit donc pas bloquer
    le run. Jamais une liste codee en dur — le perimetre est parametrable
    depuis le 22/08 (plus aucun verrou statique).
    """
    fiches = (preparation.configuration or {}).get("pays") or {}
    if not isinstance(fiches, dict):
        return []
    return [
        str(code).strip().upper()
        for code, fiche in fiches.items()
        if str(code).strip() and (not isinstance(fiche, dict) or fiche.get("actif", True))
    ]


async def _derive_du_perimetre(codes: list[str]) -> list[str]:
    """Les derives MESUREES sur les pays du perimetre, en clair.

    Silencieuse par construction si la mesure est impossible : un pre-vol qui
    bloque un run parce qu'il n'a PAS pu mesurer serait pire que le mal — le
    pre-vol de vie (10 sondes) a deja refuse ce cas juste avant.
    """
    if not codes:
        return []
    from app.routes.admin_referentiels import _mesurer_pays_config

    try:
        mesure = await _mesurer_pays_config()
    except Exception:
        return []
    motifs: list[str] = []
    # LE CAS QUI COMPTE LE PLUS : un pays du perimetre TOTALEMENT ABSENT de la
    # plateforme. Il n'apparait dans aucune mesure d'ecart — il n'y a rien a
    # comparer — et serait donc passe entre les mailles. C'est pourtant le pire
    # etat possible : base fraiche, referentiel jamais pousse, et un REAL qui
    # part creer des Companies dans un pays que la plateforme ne connait pas.
    presents = {str(ligne["iso2"]) for ligne in mesure["pays"]}
    for code in codes:
        if code not in presents:
            motifs.append(
                f"{code} : ABSENT de la plateforme — le pays n'est pas en "
                f"operation (POST /admin/referentiels/pays/{code}/pousser)"
            )
    for ligne in mesure["pays"]:
        if str(ligne["iso2"]) not in codes:
            continue
        ecarts = ligne["ecarts"]
        if ecarts["villes_absentes"]:
            motifs.append(
                f"{ligne['iso2']} : {len(ecarts['villes_absentes'])} ville(s) "
                "du Loader absentes de la plateforme"
            )
        if ecarts["telcos_absents"]:
            motifs.append(
                f"{ligne['iso2']} : telco(s) non rattache(s) — "
                f"{', '.join(ecarts['telcos_absents'])}"
            )
        attendue = ecarts["devise_attendue"]
        if attendue and attendue not in ecarts["devise_portee"]:
            motifs.append(
                f"{ligne['iso2']} : devise {attendue} attendue, "
                f"{ecarts['devise_portee']} portee(s)"
            )
    return motifs


#: `RBAC` — LES RUNS SONT UNE ACTION DE SUPER-ADMIN.
#:
#: Les trois routes qui AGISSENT sur un run — preparer, confirmer, arreter —
#: portaient `exige_admin`. `docs/MODELE_UTILISATEURS.md` dit pourtant
#: l'inverse, sans ambiguite :
#:
#:   « Le passage du mode DRY_RUN a REAL est toujours une action explicite du
#:     Super-Admin du Loader, jamais un defaut. »
#:
#: Le code divergeait donc de la conception sur le geste le plus lourd du
#: systeme : celui qui ecrit definitivement chez FinZuu, ou aucun service
#: n'expose de DELETE. Les routes de LECTURE restent ouvertes a tous les roles
#: (`admin_complet`) : observer n'est pas agir.
@router.post("/{run_id}/confirmer", status_code=202)
async def confirmer(
    run_id: UUID,
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """`US-C2` — le REAL, sur le perimetre FIGE de la preparation.

    Quatre refus, chacun structurel :
      404  preparation inconnue ;
      409  la preparation n'est pas terminee, ou n'est pas un DRY_RUN ;
      409  la configuration a CHANGE depuis la preparation — « le rapport lu
           ne decrit plus ce qui va s'executer : re-preparer » (D-01) ;
      503  PRE-VOL refuse (21/08, exigence Yaniv) : un ou plusieurs des 10
           services est injoignable A L'INSTANT de la confirmation — rien
           n'est parti, les services en panne sont NOMMES. On ne lance pas
           des ecritures quasi permanentes vers des services dont on n'a pas
           la preuve de vie ; le retry D-USR-2 couvre le transitoire EN VOL,
           pas un service deja mort AVANT le depart.
    """
    depot = LoaderRunRepository()
    preparation = await depot.obtenir(run_id)
    if preparation is None:
        raise HTTPException(status_code=404, detail=f"preparation {run_id} inconnue")
    if preparation.mode is not RunMode.DRY_RUN:
        raise HTTPException(
            status_code=409,
            detail=f"le run {run_id} est {preparation.mode.value}, pas une preparation",
        )
    if preparation.status in (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PAUSED):
        raise HTTPException(
            status_code=409,
            detail=(
                f"la preparation {run_id} est {preparation.status.value} — on ne "
                "confirme qu'un rapport TERMINE et lu (D-01)"
            ),
        )

    configuration_courante, _meta = await ConfigurationRepository().charger()
    if _normaliser(configuration_courante.empreinte()) != _normaliser(
        preparation.configuration
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "le perimetre a change depuis la preparation — le rapport lu ne "
                "decrit plus ce qui va s'executer : re-preparer (D-01)"
            ),
        )

    await refuser_si_run_en_cours()

    # --- PRE-VOL (21/08) : la preuve de vie des 10 sondes AVANT la premiere
    # ecriture. La meme sonde que le tableau de bord E1 — une seule verite.
    async with httpx.AsyncClient(timeout=3.0) as sonde:
        etats = await asyncio.gather(
            *(_sonder(sonde, nom, base) for nom, base in SERVICES_SONDES)
        )
    en_panne = [str(e["nom"]) for e in etats if e["etat"] != "up"]
    if en_panne:
        raise HTTPException(
            status_code=503,
            detail=(
                "pré-vol refusé — service(s) injoignable(s) : "
                f"{', '.join(en_panne)}. RIEN n'est parti. Relancer la "
                "confirmation quand le tableau de bord est entièrement vert."
            ),
        )

    # --- PRE-VOL DE COHERENCE (`C4`, 23/08) : la preuve de vie ne suffit
    # pas. Un service peut etre UP et porter un referentiel DESYNCHRONISE :
    # le 23/08, les 4 pays du CDC portaient 12 a 14 villes la-bas contre 70 a
    # 181 chez nous — un REAL aurait compose des adresses dans des villes que
    # la plateforme ne connait pas. On ne part pas sur une derive connue.
    derive = await _derive_du_perimetre(figee_perimetre := _pays_du_perimetre(preparation))
    if derive:
        raise HTTPException(
            status_code=409,
            detail=(
                "pré-vol de cohérence refusé — la plateforme ne porte pas ce "
                f"que le run suppose : {'; '.join(derive)}. RIEN n'est parti. "
                "Un pays ABSENT se pousse (POST /admin/referentiels/pays/"
                "{iso}/pousser) ; une dérive se ferme d'un geste (POST "
                "/admin/referentiels/synchroniser). Puis re-confirmer. "
                f"Périmètre vérifié : {', '.join(figee_perimetre) or 'aucun pays'}."
            ),
        )

    # Le REAL s'execute sur l'empreinte FIGEE de la preparation — pas sur la
    # configuration courante, meme si les deux sont identiques a cet instant :
    # c'est l'empreinte qui a ete LUE, c'est elle qui s'execute.
    figee = ConfigurationExecution.depuis_empreinte(preparation.configuration)
    reel_id = uuid4()
    _taches[str(reel_id)] = asyncio.create_task(
        _executer_en_fond(reel_id, RunMode.REAL, figee)
    )
    return {
        "run_id": str(reel_id),
        "mode": "REAL",
        "statut": "PENDING",
        "preparation_id": str(run_id),
    }


@router.get("")
async def historique(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-C6` — l'historique, append-only : aucune route de suppression
    n'existe, et c'est verifiable dans ce module meme."""
    runs = await LoaderRunRepository().lister()
    return {"runs": [_fiche(r) for r in runs]}


@router.get("/{run_id}")
async def detail(
    run_id: UUID,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-C6` — le run complet : fiche, checkpoints, et le RAPPORT integral
    (celui que le CLI imprime, range avec le run)."""
    run = await LoaderRunRepository().obtenir(run_id)
    if run is None:
        if str(run_id) in _taches:
            return {"run_id": str(run_id), "statut": "PENDING", "rapport": ""}
        raise HTTPException(status_code=404, detail=f"run {run_id} inconnu")
    fiche = _fiche(run)
    fiche["checkpoints"] = run.checkpoints
    fiche["rapport"] = run.rapport
    return fiche


@router.get("/{run_id}/progression")
async def progression(
    run_id: UUID,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-C3` — ou en est le run : les checkpoints poses par l'orchestrateur,
    du plus recent au premier. Du JSON que l'ecran rafraichit — le temps reel
    est un choix de polling cote frontend, pas un etat de plus cote backend."""
    run = await LoaderRunRepository().obtenir(run_id)
    if run is None:
        if str(run_id) in _taches:
            return {"run_id": str(run_id), "statut": "PENDING", "paliers": []}
        raise HTTPException(status_code=404, detail=f"run {run_id} inconnu")
    return {
        "run_id": str(run.id),
        "statut": run.status.value,
        "mode": run.mode.value,
        "paliers": list(reversed(run.checkpoints)),
        "en_cours_dans_ce_processus": str(run_id) in _taches,
    }


@router.post("/{run_id}/arreter")
async def arreter(
    run_id: UUID,
    _: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """`US-C4` — l'arret. Dit avec exactitude ce qu'il fait en v1 : la tache
    est annulee, le moteur clot le run en FAILED — un etat terminal et VRAI,
    jamais un RUNNING fantome qui bloquerait EF-55. L'arret « fin de lot puis
    reconciliation » est l'affinage prevu de cette story, pas son etat actuel.
    """
    tache = _taches.get(str(run_id))
    if tache is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"aucune tache locale pour {run_id} — le run n'est pas en cours "
                "dans ce processus (deja termine, ou lance par le CLI)"
            ),
        )
    tache.cancel()
    return {
        "run_id": str(run_id),
        "action": "arret demande",
        "consequence": "le run sera clos en FAILED — etat terminal, jamais un RUNNING fantome",
    }
