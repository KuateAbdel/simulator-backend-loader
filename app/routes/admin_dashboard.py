"""
app/routes/admin_dashboard.py
=============================
Lot C — la VISUALISATION (`US-E1`, `US-E2`, `US-E4`).

La regle de source, gravee dans le backlog : les compteurs viennent de NOS
collections — jamais vingt requetes paginees vers FinZuu a chaque affichage.
La seule exception est la SANTE des services (`US-E1`), qui est par nature
une question posee a eux : neuf sondes `/health` legeres, en parallele,
plafonnees a 3 s chacune.

`US-E3` (les distributions de population) N'EST PAS ICI — dit franchement :
les attributs des clients (age, metier, solde) ne sont PAS persistes chez
nous, ils partent au serveur. Les servir exigera que le moteur range ses
MESURES structurees avec le run (comme il range deja son rapport texte) —
c'est la tranche suivante, pas un oubli.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Annotated, Any, Final
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.models.enums import NiveauOrganisation
from app.repositories.audit_trail import AuditTrailRepository
from app.repositories.faker_ledger import FakerLedgerRepository
from app.repositories.loader_runs import LoaderRunRepository
from app.repositories.org_hierarchy import OrgHierarchyRepository
from app.routes.dependances import SessionAdmin, admin_complet

router = APIRouter(prefix="/admin/dashboard", tags=["admin — dashboard"])

#: Les neuf services FinZuu + Faker — le perimetre exact du sondage E1.
SERVICES_SONDES: tuple[tuple[str, str], ...] = (
    ("user-service", settings.user_service_base),
    ("config-service", settings.config_service_base),
    ("identity-service", settings.identity_service_base),
    ("account-service", settings.account_service_base),
    ("company-service", settings.company_service_base),
    ("product-service", settings.product_service_base),
    ("depositary-service", settings.depositary_service_base),
    ("client-service", settings.client_service_base),
    ("collect-service", settings.collect_service_base),
    ("faker", settings.faker_base_url),
)


async def _sonder(client: httpx.AsyncClient, nom: str, base: str) -> dict[str, Any]:
    """Une sonde — jamais d'exception propagee : un service mort est une
    DONNEE du tableau de bord, pas une panne du tableau de bord."""
    debut = time.monotonic()
    try:
        reponse = await client.get(f"{base}/health")
        latence = round((time.monotonic() - debut) * 1000)
        return {
            "nom": nom,
            "etat": "up" if reponse.status_code < 500 else "down",
            "http": reponse.status_code,
            "latence_ms": latence,
        }
    except httpx.HTTPError as erreur:
        return {
            "nom": nom,
            "etat": "down",
            "http": None,
            "latence_ms": round((time.monotonic() - debut) * 1000),
            "erreur": type(erreur).__name__,
        }


async def _dernier_run() -> Any:
    runs = await LoaderRunRepository().lister(limite=1)
    return runs[0] if runs else None


#: Combien de runs l'entete de perimetre enumere au plus. L'Observatoire doit
#: rester lisible : au-dela, le compte suffit.
PLAFOND_RUNS_ENUMERES: Final = 50


async def _perimetre(run_id: UUID | None) -> dict[str, Any]:
    """`P-06` — CE QUE L'ECRAN COUVRE, DIT EXPLICITEMENT.

    **Le defaut de conception que cette fonction corrige.** Tout l'Observatoire
    etait cable sur `_dernier_run()`. Un ecran intitule « Ecosysteme »
    n'affichait donc pas l'ecosysteme : il affichait la derniere execution.
    Mesure du 24/08 — le run `7e3f3f83` avait bati BF + CI + CM ; le run
    suivant, `9e2369bf`, n'avait bati que BF (ses IMF ont ete refusees,
    `INV-CPY-02`). L'ecran annoncait 1 pays et 4 Kiosques quand la plateforme
    en portait 49 a nous. L'operateur n'avait AUCUN moyen de voir le reste, et
    aucune mention ne lui disait qu'il regardait une tranche.

    Un ecran qui montre une PARTIE en se presentant comme le TOUT ment, meme
    si chaque chiffre qu'il affiche est exact.

    Regle : **sans `run_id`, le perimetre est TOUT ce que le Loader a bati**,
    tous runs confondus — l'etat reel du systeme. Le `run_id` reste un filtre
    offert (« qu'a fait cette execution ? »), jamais une frontiere imposee.

    L'entete est rendu avec CHAQUE reponse de l'Observatoire pour que l'ecran
    puisse toujours dire ce qu'il couvre, et proposer les autres runs.
    """
    if run_id is not None and await LoaderRunRepository().obtenir(run_id) is None:
        # Un `run_id` EXPLICITE qui ne designe rien est une erreur d'appel, pas
        # un perimetre vide : on repond 404. La nuance compte — « ce run
        # n'existe pas » et « ce perimetre n'a rien produit » sont deux
        # reponses differentes, et les confondre laisse l'operateur croire
        # qu'un run a echoue alors qu'il s'est trompe d'identifiant.
        raise HTTPException(status_code=404, detail=f"run {run_id} inconnu")

    runs = await LoaderRunRepository().lister(limite=PLAFOND_RUNS_ENUMERES)
    connus = [
        {
            "run_id": str(r.id),
            "mode": r.mode.value,
            "statut": r.status.value,
            "cree_le": r.cree_le.isoformat() if r.cree_le else None,
        }
        for r in runs
    ]
    if run_id is None:
        return {
            "run_id": None,
            "portee": "tous",
            "libelle": f"tout le perimetre du Loader — {len(connus)} run(s)",
            "runs_connus": connus,
        }
    return {
        "run_id": str(run_id),
        "portee": "run",
        "libelle": f"run {str(run_id)[:8]} seul",
        "runs_connus": connus,
    }


@router.get("")
async def vue_d_ensemble(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-E1` — l'atterrissage : sante des services, dernier run, compteurs
    et alertes. Tout sauf la sante vient de NOS collections."""
    async with httpx.AsyncClient(timeout=3.0) as sonde:
        services = await asyncio.gather(
            *(_sonder(sonde, nom, base) for nom, base in SERVICES_SONDES)
        )

    run = await _dernier_run()
    compteurs: dict[str, Any] = {}
    alertes: list[str] = []
    if run is not None:
        arbre = OrgHierarchyRepository()
        ledger = FakerLedgerRepository()
        audit = AuditTrailRepository()
        for niveau in NiveauOrganisation:
            compteurs[niveau.value.lower() + "s"] = len(
                await arbre.par_niveau(run.id, niveau)
            )
        compteurs["faker_par_pays"] = await ledger.compter_par_pays(run.id)
        compteurs["ecritures_par_type"] = await audit.compter_par_type(run.id)

        orphelines = await audit.intentions_orphelines(run.id)
        if orphelines:
            alertes.append(
                f"{len(orphelines)} intention(s) orpheline(s) au journal — des "
                "ecritures dont on ignore si le serveur les a appliquees"
            )
        reservations = await ledger.reservations_orphelines(run.id)
        if reservations:
            alertes.append(
                f"{len(reservations)} reservation(s) Faker orpheline(s) — "
                "client revendique, rien produit"
            )
        if run.status.value in ("RUNNING", "PAUSED"):
            alertes.append(f"run {run.id} encore {run.status.value} (verrou EF-55 actif)")

    return {
        "services": list(services),
        "dernier_run": None
        if run is None
        else {
            "run_id": str(run.id),
            "mode": run.mode.value,
            "statut": run.status.value,
            "nb_checkpoints": len(run.checkpoints),
        },
        "compteurs": compteurs,
        "alertes": alertes,
    }


@router.get("/ecosysteme")
async def ecosysteme(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
    run_id: UUID | None = None,
) -> dict[str, Any]:
    """`US-E2` — l'arbre navigable : la structure que la plateforme elle-meme
    ne sait pas montrer, parce que `org_hierarchy` est a nous.

    Quatre lectures par niveau puis assemblage en memoire — jamais une requete
    par noeud : 80 kiosques et 2000 clients tiendraient mal autrement.
    """
    # `P-06` — sans `run_id`, on montre TOUT ce que le Loader a bati. Le repli
    # sur `_dernier_run()` faisait passer une tranche pour le tout.
    perimetre = await _perimetre(run_id)

    arbre = OrgHierarchyRepository()
    par_niveau = {
        niveau: await arbre.par_niveau(run_id, niveau) for niveau in NiveauOrganisation
    }
    if not any(par_niveau.values()):
        # Pas une erreur : un Loader qui n'a encore rien bati est un etat
        # legitime. L'ecran doit le DIRE, pas afficher une erreur technique.
        return {
            **perimetre,
            "pays": [],
            "note": (
                "aucune entite construite sur ce perimetre — "
                "l'arbre se remplit au module DEPOSITAIRES d'un run REEL"
            ),
        }

    enfants_de: dict[UUID | None, list[Any]] = {}
    for noeuds in par_niveau.values():
        for noeud in noeuds:
            enfants_de.setdefault(noeud.parent_id, []).append(noeud)

    # LES IDENTIFIANTS DEVIENNENT DES NOMS.
    #
    # L'ecran rendait `"quartier": "CM-DT-001"`. Pour savoir qu'il s'agit de
    # Bastos, il fallait ouvrir la base. Un ecran qui oblige a aller chercher
    # ailleurs ce qu'il affiche n'a pas fait son travail — et la question
    # « creer un depositaire dans TEL quartier » devenait un exercice de
    # correspondance manuelle.
    from app.repositories.surcouche import SurcoucheRepository
    from app.routes.admin_referentiels import _geo

    surcouche, _meta = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())

    def _nom_region(identifiant: str | None) -> str | None:
        region = referentiel.regions.get(identifiant) if identifiant else None
        return region.name if region else identifiant

    def _nom_ville(identifiant: str | None) -> str | None:
        ville = referentiel.villes.get(identifiant) if identifiant else None
        return ville.name if ville else identifiant

    def _nom_quartier(identifiant: str | None) -> str | None:
        quartier = referentiel.quartier(identifiant) if identifiant else None
        return quartier.name if quartier else identifiant

    def _nom_pays(code: str) -> str:
        fiche = referentiel.pays(code)
        return fiche.nom_fr if fiche else code

    #: Les agregats d'un niveau — TOUJOURS les memes cles, a tous les etages.
    #: Une ligne qui porte ses totaux n'oblige jamais a deplier pour savoir ce
    #: qu'il y a dessous : c'est ce qui separe un arbre lisible d'un arbre
    #: decoratif.
    def _somme(enfants: list[dict[str, Any]]) -> dict[str, int]:
        cles = ("companies", "branches", "agences", "kiosques", "agents", "clients")
        total = dict.fromkeys(cles, 0)
        for enfant in enfants:
            for cle in cles:
                total[cle] += int(enfant["agregats"].get(cle, 0))
        return total

    def _kiosque(noeud: Any) -> dict[str, Any]:
        rattaches = enfants_de.get(noeud.id, [])
        agents = [n for n in rattaches if n.niveau is NiveauOrganisation.AGENT]
        clients = [n for n in rattaches if n.niveau is NiveauOrganisation.CLIENT]
        # ANOMALIES STRUCTURELLES — `UC-09` postcondition : un Agent par
        # Kiosque, sans exception. Un kiosque sans agent n'ouvre pas.
        anomalies = []
        if not agents:
            anomalies.append("aucun agent — UC-09 exige un Agent par Kiosque")
        if noeud.depositary_id is None:
            anomalies.append("aucun depositary_id — le Kiosque n'existe pas la-bas")
        return {
            "id": str(noeud.id),
            "nom": noeud.name,
            "quartier_id": noeud.district_id,
            "quartier": _nom_quartier(noeud.district_id),
            "depositary_id": str(noeud.depositary_id) if noeud.depositary_id else None,
            # CONSERVES : l'ecran actuel et la recette les lisent. Renommer
            # pour renommer casserait un ecran qui marche, sans rien apporter.
            "nb_agents": len(agents),
            "nb_clients": len(clients),
            # `quartier` gardait l'identifiant brut ; il porte le NOM depuis
            # V-03, et `quartier_id` reste disponible pour qui en a besoin.
            "agregats": {
                "companies": 0, "branches": 0, "agences": 0, "kiosques": 1,
                "agents": len(agents), "clients": len(clients),
            },
            "anomalies": anomalies,
        }

    def _agence(noeud: Any) -> dict[str, Any]:
        kiosques = [
            _kiosque(k)
            for k in enfants_de.get(noeud.id, [])
            if k.niveau is NiveauOrganisation.KIOSQUE
        ]
        agregats = _somme(kiosques)
        agregats["agences"] = 1
        return {
            "id": str(noeud.id),
            "nom": noeud.name,
            "ville_id": noeud.city_id,
            "ville": _nom_ville(noeud.city_id),
            "kiosques": kiosques,
            "agregats": agregats,
            "anomalies": [] if kiosques else ["aucun kiosque — agence vide"],
        }

    def _branche(noeud: Any) -> dict[str, Any]:
        agences = [
            _agence(a)
            for a in enfants_de.get(noeud.id, [])
            if a.niveau is NiveauOrganisation.AGENCE
        ]
        agregats = _somme(agences)
        agregats["branches"] = 1
        return {
            "id": str(noeud.id),
            "nom": noeud.name,
            "region_id": noeud.region_id,
            "region": _nom_region(noeud.region_id),
            # Le PAYS voyage avec la branche : dans la liste a plat, une
            # branche « Centre » sans son pays ne se situe nulle part.
            "pays": noeud.country_code,
            "pays_nom": _nom_pays(noeud.country_code),
            "company_id": str(noeud.company_id),
            "company_nom": getattr(noeud, "company_nom", None),
            "agences": agences,
            "agregats": agregats,
            "anomalies": [] if agences else ["aucune agence — branche vide"],
        }

    # --- L'ARBRE A CINQ NIVEAUX : pays > IMF > branche > agence > kiosque ---
    #
    # Il en avait TROIS, et commencait a la Branche. Consequence sur le plan
    # reel : 20 branches a plat, sans pays, et les deux IMF d'un meme pays y
    # apparaissaient en lignes jumelles « Centre » / « Centre », impossibles a
    # distinguer. On ne pouvait pas repondre a « ce reseau est-il celui de
    # quelle institution ».
    branches = [_branche(b) for b in par_niveau[NiveauOrganisation.BRANCHE]]

    par_pays: dict[str, dict[str, list[dict[str, Any]]]] = {}
    noms_imf: dict[str, str | None] = {}
    for noeud, rendu in zip(par_niveau[NiveauOrganisation.BRANCHE], branches, strict=True):
        par_pays.setdefault(noeud.country_code, {}).setdefault(
            str(noeud.company_id), []
        ).append(rendu)
        # Le nom vient du noeud (`V-03`). `None` sur un run anterieur : on le
        # DIT, on n'invente pas une correspondance qu'on n'a pas.
        if getattr(noeud, "company_nom", None):
            noms_imf[str(noeud.company_id)] = noeud.company_nom

    arbre_pays: list[dict[str, Any]] = []
    for code in sorted(par_pays):
        companies: list[dict[str, Any]] = []
        for company_id in sorted(par_pays[code], key=lambda c: noms_imf.get(c) or c):
            ses_branches = par_pays[code][company_id]
            agregats = _somme(ses_branches)
            agregats["companies"] = 1
            companies.append(
                {
                    "id": company_id,
                    "nom": noms_imf.get(company_id),
                    "nom_inconnu": company_id not in noms_imf,
                    "branches": ses_branches,
                    "agregats": agregats,
                }
            )
        arbre_pays.append(
            {
                "iso2": code,
                "nom": _nom_pays(code),
                "companies": companies,
                "agregats": _somme(companies),
            }
        )

    # --- LA COUVERTURE INVERSE : CE QUI MANQUE --------------------------
    #
    # L'ecran montrait ce qui EXISTE. Il ne montrait jamais ce qui MANQUE — et
    # c'est pourtant la question qu'on lui pose : « ou puis-je encore creer un
    # depositaire ? ». `D-03` (un quartier = UN kiosque) rend la reponse
    # exacte et calculable : les quartiers NON pris sont, litteralement, les
    # emplacements disponibles.
    #
    # Sans cela, ouvrir le formulaire US-D3 revenait a deviner un quartier
    # libre dans une liste de plusieurs centaines, puis a se faire refuser.
    pris = {
        k["quartier_id"]
        for p in arbre_pays for c in p["companies"] for b in c["branches"]
        for a in b["agences"] for k in a["kiosques"] if k["quartier_id"]
    }
    libres_par_pays: dict[str, list[dict[str, Any]]] = {}
    for quartier in referentiel.quartiers.values():
        if quartier.district_id in pris:
            continue
        ville = referentiel.villes.get(quartier.city_id)
        if ville is None:
            continue
        libres_par_pays.setdefault(ville.country_iso2, []).append(
            {
                "district_id": quartier.district_id,
                "quartier": quartier.name,
                "ville": ville.name,
                "region": _nom_region(ville.region_id),
            }
        )
    for entree in arbre_pays:
        libres = sorted(
            libres_par_pays.get(str(entree["iso2"]), []),
            key=lambda q: (str(q["region"]), str(q["ville"]), str(q["quartier"])),
        )
        entree["quartiers_libres"] = {
            "compte": len(libres),
            # Bornee : un pays peut en avoir des centaines, et l'ecran n'a pas
            # besoin de les porter tous pour dire « il en reste 137 ».
            "exemples": libres[:25],
        }

    # --- LES TROIS MESURES ------------------------------------------------
    #
    # Un compteur dit COMBIEN. Ces trois-la disent SI C'EST CREDIBLE, et
    # c'est la seule question qui compte devant un bailleur.

    # 1. CONCENTRATION — le CDC veut un reseau reparti. Le defaut mesure au
    #    Senegal le 22/08 : une IMF raflait Pikine, Thies ET Saint-Louis
    #    pendant que l'autre restait confinee a Dakar.
    toutes_imf = [c for p in arbre_pays for c in p["companies"]]
    total_kiosques = sum(c["agregats"]["kiosques"] for c in toutes_imf)
    plus_grosse = max(toutes_imf, key=lambda c: c["agregats"]["kiosques"], default=None)
    part_max = (
        round(100 * plus_grosse["agregats"]["kiosques"] / total_kiosques, 1)
        if plus_grosse and total_kiosques
        else 0.0
    )
    # UN NOMBRE NU NE JUGE RIEN.
    #
    # « 16,7 % » : est-ce bon ou mauvais ? Sans point de comparaison, personne
    # ne peut le dire. On rend donc AUSSI la part ATTENDUE d'un reseau
    # parfaitement reparti (100 / nb_imf), l'ecart a cet equilibre, et un vrai
    # indice de concentration.
    #
    # GINI sur les kiosques par institution : 0 = parfaitement egal, 1 = une
    # seule institution porte tout. C'est la mesure standard de concentration,
    # et elle voit ce que le maximum seul ne voit pas — huit IMF dont sept
    # minuscules et une enorme, ou huit IMF equivalentes, peuvent partager le
    # meme maximum.
    charges = sorted(c["agregats"]["kiosques"] for c in toutes_imf)
    nb = len(charges)
    somme = sum(charges) or 1
    gini = (
        round(
            (2 * sum((i + 1) * v for i, v in enumerate(charges)) - (nb + 1) * somme)
            / (nb * somme),
            3,
        )
        if nb > 1
        else 0.0
    )
    part_attendue = round(100 / nb, 1) if nb else 0.0
    #: Seuils ASSUMES : au-dela de 60 % pour UNE institution, ce n'est plus un
    #: ecosysteme concurrentiel. Le Gini complete — au-dela de 0,4 la
    #: distribution est deja tres inegale meme sans geant unique.
    concentration = {
        "part_max_pourcent": part_max,
        "part_attendue_pourcent": part_attendue,
        "ecart_a_l_equilibre": round(part_max - part_attendue, 1),
        "gini": gini,
        "min_kiosques": charges[0] if charges else 0,
        "max_kiosques": charges[-1] if charges else 0,
        "imf": (plus_grosse or {}).get("nom") or (plus_grosse or {}).get("id"),
        "nb_imf": nb,
        "verdict": "concentre" if part_max > 60 or gini > 0.4 else "reparti",
    }

    # 2. COUVERTURE — un reseau national, ou trois agences ?
    villes_couvertes = {
        a["ville_id"]
        for p in arbre_pays for c in p["companies"] for b in c["branches"] for a in b["agences"]
        if a["ville_id"]
    }
    quartiers_couverts = {
        k["quartier_id"]
        for p in arbre_pays for c in p["companies"] for b in c["branches"]
        for a in b["agences"] for k in a["kiosques"] if k["quartier_id"]
    }
    # LE DENOMINATEUR EST LE PERIMETRE, PAS LE GLOBE.
    #
    # Defaut vu a l'ecran le 24/08 : « 12 villes / 3156 ». Le 3156 etait le
    # referentiel ENTIER (48 pays portes par le Loader), alors que le run n'en
    # touche que quatre. Le ratio ne voulait rien dire, et pire : il faisait
    # passer une couverture correcte pour un echec.
    #
    # On compte donc les villes et les quartiers DES PAYS DE L'ARBRE — le seul
    # perimetre contre lequel une couverture se juge.
    codes_arbre = {str(p["iso2"]) for p in arbre_pays}
    villes_du_perimetre = [
        v for v in referentiel.villes.values() if v.country_iso2 in codes_arbre
    ]
    ids_villes_perimetre = {v.city_id for v in villes_du_perimetre}
    quartiers_du_perimetre = [
        q for q in referentiel.quartiers.values() if q.city_id in ids_villes_perimetre
    ]
    couverture = {
        "pays": len(arbre_pays),
        "regions": len(
            {
                b["region_id"]
                for p in arbre_pays
                for c in p["companies"]
                for b in c["branches"]
            }
        ),
        "villes": len(villes_couvertes),
        "villes_du_referentiel": len(villes_du_perimetre),
        "quartiers": len(quartiers_couverts),
        "quartiers_du_referentiel": len(quartiers_du_perimetre),
        # Ce qui reste a couvrir, tous pays confondus — la reponse a « ou
        # creer le prochain depositaire ».
        "quartiers_libres": sum(
            int(p["quartiers_libres"]["compte"]) for p in arbre_pays
        ),
    }

    # 3. INTEGRITE — l'invariant `EF-18` rendu VISIBLE plutot que suppose.
    tous_kiosques = [
        k for p in arbre_pays for c in p["companies"] for b in c["branches"]
        for a in b["agences"] for k in a["kiosques"]
    ]
    toutes_agences = [
        a for p in arbre_pays for c in p["companies"] for b in c["branches"] for a in b["agences"]
    ]
    toutes_branches = [b for p in arbre_pays for c in p["companies"] for b in c["branches"]]
    integrite: dict[str, int | None] = {
        "kiosques_sans_agent": sum(1 for k in tous_kiosques if k["agregats"]["agents"] == 0),
        "kiosques_sans_depositaire": sum(1 for k in tous_kiosques if not k["depositary_id"]),
        "kiosques_sans_client": sum(1 for k in tous_kiosques if k["agregats"]["clients"] == 0),
        "agences_sans_kiosque": sum(1 for a in toutes_agences if not a["kiosques"]),
        "branches_sans_agence": sum(1 for b in toutes_branches if not b["agences"]),
        "imf_sans_nom": sum(1 for c in toutes_imf if c["nom_inconnu"]),
    }

    # --- L'ARBRE SE CONFRONTE AU REEL -------------------------------------
    #
    # Question de Yaniv (24/08) : « si je purge la base, plus rien ne s'affiche,
    # n'est-ce pas ? » — NON, et c'etait un mensonge par omission.
    #
    # `org_hierarchy` est NOTRE memoire d'un run. La purge n'y touche pas, et
    # la plateforme peut etre videe de son cote : l'arbre continuerait a
    # afficher des kiosques dont le Depositaire n'existe plus, sans le dire.
    #
    # On CONFRONTE donc les kiosques de l'arbre a ce que la plateforme porte
    # VRAIMENT, par la meme reconciliation que l'ecran Inventaire — une seule
    # verite, pas deux implementations. Un kiosque disparu la-bas est nomme.
    #
    # Si la plateforme est MUETTE, on ne conclut pas : `verifie` reste `false`
    # et l'ecran dit « non verifie » plutot qu'un faux « tout va bien ».
    verification: dict[str, Any] = {
        "verifie": False,
        "kiosques_disparus": 0,
        "motif": "non verifie",
    }
    try:
        from app.clients.depositary_service import DepositaryServiceClient
        from app.services.inventaire import classer_depositaires

        client_dep = DepositaryServiceClient()

        async def _reconcilier_depositaires() -> dict[str, Any]:
            # `lister()` — la VRAIE lecture de depositary-service, la meme que
            # l'ecran Inventaire. Aucune donnee simulee ne rentre ici.
            return await classer_depositaires(await client_dep.lister())

        try:
            # BORNE DE TEMPS : un ecran ne doit JAMAIS attendre un service
            # mort. Au-dela de 4 s la verification est abandonnee et l'ecran
            # dit « non verifie » — ce qui est VRAI — au lieu de faire patienter
            # devant une page blanche.
            #
            # L'APPEL EST DANS LA COROUTINE, pas avant : ecrit
            # `wait_for(f(await g()))`, le `await g()` s'evalue AVANT que le
            # delai ne l'enveloppe, et la borne ne protege plus rien. Defaut
            # attrape sur la duree des tests (49 s au lieu de 4).
            classement = await asyncio.wait_for(_reconcilier_depositaires(), timeout=4.0)
        finally:
            await client_dep.fermer()
        disparus = {str(x["id"]) for x in classement.get("disparu_la_bas", [])}
        nos_depositaires = {
            str(k["depositary_id"])
            for p in arbre_pays for c in p["companies"] for b in c["branches"]
            for a in b["agences"] for k in a["kiosques"] if k["depositary_id"]
        }
        manquants = sorted(nos_depositaires & disparus)
        verification = {
            "verifie": True,
            "kiosques_disparus": len(manquants),
            "depositaires_disparus": manquants[:20],
            "motif": (
                "chaque Kiosque de l'arbre existe encore sur la plateforme"
                if not manquants
                else (
                    f"{len(manquants)} Kiosque(s) de cet arbre n'ont PLUS de "
                    "Depositaire sur la plateforme — cet arbre decrit un etat "
                    "PASSE, pas l'etat courant"
                )
            ),
        }
        # L'anomalie remonte AUSSI dans l'integrite : c'en est une.
        integrite["kiosques_disparus_la_bas"] = len(manquants)
    except Exception:
        # Plateforme muette : on ne dit pas « tout va bien », on dit qu'on ne
        # sait pas. Un ecran qui affirme sans avoir mesure est pire que muet.
        integrite["kiosques_disparus_la_bas"] = None

    return {
        **perimetre,
        "comptes": {n.value.lower() + "s": len(v) for n, v in par_niveau.items()},
        "verification": verification,
        # L'arbre a CINQ niveaux, celui qu'on lit.
        "pays": arbre_pays,
        # Conservee pour ne casser aucun appelant existant : la meme matiere,
        # a plat. Un ecran qui migre ne tombe pas en marche.
        "branches": branches,
        "mesures": {
            "concentration": concentration,
            "couverture": couverture,
            "integrite": integrite,
        },
        "note": (
            "les identifiants sont RESOLUS en noms (region, ville, quartier, "
            "IMF) : un ecran qui oblige a ouvrir la base pour savoir ce qu'il "
            "affiche n'a pas fait son travail. Branche et Agence n'existent "
            "QUE chez nous — la plateforme n'a aucune route pour elles"
        ),
    }


@router.get("/tracabilite")
async def tracabilite(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
    run_id: UUID | None = None,
) -> dict[str, Any]:
    """`US-E4` — « d'ou vient cette entite ? » : le registre Faker et le
    journal d'intentions, avec leurs reconciliations."""
    # `P-06` — sans `run_id`, le journal couvre TOUTES les executions.
    perimetre = await _perimetre(run_id)

    ledger = FakerLedgerRepository()
    audit = AuditTrailRepository()
    intentions = await audit.exporter_run(run_id)
    orphelines_audit = await audit.intentions_orphelines(run_id)
    orphelines_faker = await ledger.reservations_orphelines(run_id)

    return {
        **perimetre,
        "registre_faker": {
            "par_pays": await ledger.compter_par_pays(run_id),
            "reservations_orphelines": [
                {"client_id": o.id, "pays": o.country_code, "seed": o.seed}
                for o in orphelines_faker[:50]
            ],
        },
        "journal": {
            "ecritures_par_type": await audit.compter_par_type(run_id),
            "nb_entrees": len(intentions),
            "intentions_orphelines": [
                {
                    "entity_type": e.entity_type,
                    "entity_id": str(e.entity_id),
                    "cible": (e.after or {}).get("cible", "?"),
                }
                for e in orphelines_audit[:50]
            ],
            "dernieres_entrees": [
                {
                    "entity_type": e.entity_type,
                    "action": e.action,
                    "horodatage": e.timestamp.isoformat(),
                }
                for e in intentions[-20:]
            ],
        },
        "reconciliation": (
            "aucune intention orpheline — le journal est clos"
            if not orphelines_audit and not orphelines_faker
            else f"{len(orphelines_audit)} intention(s) et "
            f"{len(orphelines_faker)} reservation(s) a verifier a la main"
        ),
    }



def _somme_paire(cible: dict[str, Any], ajout: Any) -> None:
    """Additionne un couple `{mesure, cible}` en place, en ignorant le reste.

    Les mesures sont des COMPTES : deux runs qui ont peuple le meme pays ont
    cree deux populations distinctes, et leur somme est la population reelle.
    Rien n'est moyenne, rien n'est interpole.
    """
    if not isinstance(ajout, dict):
        return
    for cle in ("mesure", "cible"):
        valeur = ajout.get(cle)
        if isinstance(valeur, int):
            cible[cle] = cible.get(cle, 0) + valeur


def _fusionner_mesures(runs: list[Any]) -> dict[str, Any]:
    """`P-06` — LES MESURES DE TOUS LES RUNS, ADDITIONNEES.

    On ne fusionne que des comptes deja enregistres. Aucune valeur n'est
    recalculee, aucune n'est deduite : ce que le rapport de chaque run a
    juge reste ce qui est servi, seule la SOMME est nouvelle.

    Les runs sont pris du plus ancien au plus recent pour que `top` des
    metiers reste stable d'un appel a l'autre.
    """
    QUOTAS = ("clients", "corporate", "femmes", "jeunes", "agricoles")

    pays: dict[str, dict[str, Any]] = {}
    occupations: Counter[str] = Counter()
    occupations_total = 0
    occupations_distinctes = 0
    tranches: Counter[str] = Counter()
    total_dote = 0.0
    naissances = {"a_l_etranger": 0, "au_pays": 0}

    for run in reversed(runs):
        mesures = run.mesures or {}
        for ligne in mesures.get("quotas_par_pays", []):
            code = str(ligne.get("pays", "")).upper()
            if not code:
                continue
            cumul = pays.setdefault(
                code,
                {"pays": code, **{q: {} for q in QUOTAS}, "profils": {}, "runs": []},
            )
            for quota in QUOTAS:
                _somme_paire(cumul[quota], ligne.get(quota))
            for nom, paire in (ligne.get("profils") or {}).items():
                _somme_paire(cumul["profils"].setdefault(nom, {}), paire)
            cumul["runs"].append(str(run.id))

        occ = mesures.get("occupations") or {}
        occupations_total += int(occ.get("total") or 0)
        # `distinctes` est un CARDINAL mesure par le run sur les 576 metiers,
        # pas un compte sommable : deux runs peuvent avoir tire les memes.
        # On garde le plus grand — un PLANCHER honnete. Le recomposer depuis
        # `top` (20 entrees) l'aurait fait chuter de 300 a 20 : une donnee
        # exacte remplacee par un artefact d'affichage.
        occupations_distinctes = max(occupations_distinctes, int(occ.get("distinctes") or 0))
        for nom, compte in (occ.get("top") or {}).items():
            occupations[str(nom)] += int(compte or 0)

        sol = mesures.get("soldes") or {}
        for borne, compte in (sol.get("tranches") or {}).items():
            tranches[str(borne)] += int(compte or 0)
        total_dote += float(sol.get("total_dote") or 0)

        nai = mesures.get("naissances") or {}
        for cle in naissances:
            naissances[cle] += int(nai.get(cle) or 0)

    return {
        "quotas_par_pays": sorted(pays.values(), key=lambda ligne: ligne["pays"]),
        "occupations": {
            "distinctes": occupations_distinctes,
            "total": occupations_total,
            "top": dict(occupations.most_common(20)),
        },
        "soldes": {"tranches": dict(tranches), "total_dote": round(total_dote, 2)},
        "naissances": naissances,
    }


@router.get("/population")
async def population(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
    run_id: UUID | None = None,
) -> dict[str, Any]:
    """`US-E3` — les distributions de la population, MESURE ET CIBLE cote a
    cote : quotas EF-22/23/24 par pays, profils CR-09, les 576 metiers (top),
    l'histogramme des soldes (frontiere a 150 000 — le seuil EF-68), les
    naissances a l'etranger.

    Servies depuis `LoaderRun.mesures`, rangees par le moteur a la fin du
    run — identiques a ce que la recette a juge, JAMAIS recalculees ici et
    jamais demandees a FinZuu.
    """
    perimetre = await _perimetre(run_id)

    if run_id is not None:
        run = await LoaderRunRepository().obtenir(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"run {run_id} inconnu")
        if not run.mesures:
            # Un run EXPLICITEMENT demande qui ne porte pas de mesures : on
            # explique pourquoi plutot que de rendre un ecran vide. La nuance
            # avec le cas cumulatif ci-dessous tient : ici l'operateur a
            # designe CE run, il a droit a la raison.
            raise HTTPException(
                status_code=404,
                detail=(
                    f"le run {run.id} ne porte pas de mesures de population — "
                    "anterieur a US-E3, ou son module CLIENTS n'a pas tourne"
                ),
            )
        porteurs = [run]
    else:
        # `P-06` — LA POPULATION ACTUELLE, C'EST TOUT CE QUI A ETE PEUPLE.
        #
        # Cette route ne servait que `_dernier_run().mesures`. Le run
        # `9e2369bf` n'ayant peuple que le Burkina, l'ecran affichait CI, CM
        # et SN **a zero** — alors que le run `7e3f3f83` y avait bel et bien
        # cree des clients. Trois pays effaces de l'ecran par le seul fait
        # qu'une execution plus recente ne les avait pas touches.
        porteurs = [r for r in await LoaderRunRepository().lister(limite=200) if r.mesures]

    if not porteurs:
        return {
            **perimetre,
            "quotas_par_pays": [],
            "note": (
                "aucun run ne porte de mesures de population sur ce perimetre — "
                "elles sont rangees a la fin du module CLIENTS d'un run REEL"
            ),
        }

    fusion = _fusionner_mesures(porteurs)

    # `P-06` — LE RECOUPEMENT QUI INTERDIT DE MENTIR. Les mesures sont un
    # instantane range a la fin du run ; les noeuds clients sont l'etat reel de
    # la base MAINTENANT. Si les deux divergent, on le DIT au lieu de servir le
    # chiffre le plus flatteur.
    reels = await OrgHierarchyRepository().clients_par_pays(run_id)
    for ligne in fusion["quotas_par_pays"]:
        constate = reels.get(ligne["pays"], 0)
        ligne["clients"]["en_base"] = constate
        if constate != ligne["clients"]["mesure"]:
            ligne["clients"]["ecart"] = (
                f"{ligne['clients']['mesure']} mesure(s) au run, "
                f"{constate} noeud(s) en base"
            )

    return {
        **perimetre,
        "modes": sorted({r.mode.value for r in porteurs}),
        "runs_mesures": [str(r.id) for r in porteurs],
        **fusion,
    }


@router.get("/clients")
async def clients(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
    run_id: UUID | None = None,
    pays: str | None = None,
    genre: str | None = None,
    profession: str | None = None,
    categorie: str | None = None,
    page: int = 1,
    taille: int = 50,
) -> dict[str, Any]:
    """`P-04` — LA LISTE DES CLIENTS, filtrable par pays, sexe et profession.

    Le dashboard rendait des DISTRIBUTIONS (`US-E3`) : combien de femmes,
    quels metiers, quelles tranches de solde. Il ne rendait aucun CLIENT.
    « Montre-moi les femmes agricultrices du Cameroun » n'avait pas de reponse.

    Servie depuis NOTRE base, en deux requetes, sans un seul appel a FinZuu.
    C'est ce que `P-04` a rendu possible en rangeant le profil (genre,
    profession, categorie) avec le noeud du client au moment de l'ecriture :
    ces trois valeurs sont NOS decisions de quota (`EF-22`, `EF-23`, `EF-24`),
    pas des donnees de la plateforme — rien ne peut donc diverger.

    Chaque ligne porte le client ET sa geographie complete, remontee par son
    Kiosque : quartier, ville, region, IMF. La reponse porte aussi les
    FACETTES — combien de clients par pays, par genre, par categorie, par
    metier, sur le perimetre deja filtre. Un ecran qui propose un filtre doit
    dire ce qu'il reste derriere, sinon on clique a l'aveugle.
    """
    from app.routes.admin_referentiels import _geo

    # `P-06` — sans `run_id`, la liste couvre TOUS les clients du Loader.
    perimetre = await _perimetre(run_id)

    depot = OrgHierarchyRepository()
    taille = max(1, min(int(taille), 200))
    lignes, total, facettes = await depot.clients_filtres(
        run_id,
        pays=pays,
        genre=genre,
        profession=profession,
        categorie=categorie,
        page=page,
        taille=taille,
    )

    # La geographie d'un client est DERIVEE de son Kiosque — jamais dupliquee
    # sur son noeud (elle pourrait diverger). On la remonte donc ici, en une
    # seule lecture des Kiosques du run plutot qu'une par client.
    kiosques = {
        noeud.id: noeud
        for noeud in await depot.par_niveau(run_id, NiveauOrganisation.KIOSQUE)
    }
    referentiel = _geo()

    resultats = []
    for noeud in lignes:
        kiosque = kiosques.get(noeud.parent_id) if noeud.parent_id else None
        quartier = (
            referentiel.quartier(kiosque.district_id)
            if kiosque and kiosque.district_id
            else None
        )
        ville = referentiel.villes.get(kiosque.city_id) if kiosque and kiosque.city_id else None
        region = referentiel.regions.get(ville.region_id) if ville else None
        resultats.append(
            {
                "client_id": str(noeud.client_id) if noeud.client_id else None,
                "msisdn": noeud.name.removeprefix("Client ").strip(),
                "pays": noeud.country_code,
                "genre": noeud.gender,
                "profession": noeud.occupation,
                "categorie": noeud.categorie,
                "produits": len(noeud.product_ids),
                "kiosque": kiosque.name if kiosque else None,
                "quartier": quartier.name if quartier else None,
                "ville": ville.name if ville else None,
                "region": region.name if region else None,
                "company_id": str(noeud.company_id),
            }
        )

    pages = (total + taille - 1) // taille
    return {
        **perimetre,
        "filtres": {
            "pays": pays,
            "genre": genre,
            "profession": profession,
            "categorie": categorie,
        },
        "total": total,
        "page": page,
        "pages": pages,
        "taille": taille,
        "clients": resultats,
        "facettes": facettes,
        "note": (
            "servi depuis la base du Loader, ZERO appel a FinZuu. Le genre, la "
            "profession et la categorie sont nos decisions de quota (EF-22/23/24) "
            "rangees a l'ecriture ; la geographie est DERIVEE du Kiosque, jamais "
            "dupliquee — un client ne peut pas etre dans une autre ville que son "
            "Kiosque"
        ),
    }


@router.get("/index-inverse")
async def index_inverse(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
    run_id: UUID | None = None,
) -> dict[str, Any]:
    """`P-01` — l'index inverse COMME UN SERVICE : « combien de clients par
    produit ? par kiosque ? » repondues depuis NOS noeuds, en deux
    agregations — jamais 20 requetes paginees vers FinZuu.

    Le lien est enregistre A L'ECRITURE (produit d'entree au rattachement,
    puis chaque PUT /subscribe) ; cette route ne fait que LIRE. Les noms
    viennent des noeuds du meme run : le marqueur pour le produit (CAT 6),
    le nom du Kiosque pour le kiosque.
    """
    # `P-06` — sans `run_id`, l'index couvre TOUS les clients du Loader.
    perimetre = await _perimetre(run_id)

    arbre = OrgHierarchyRepository()
    par_produit = await arbre.clients_par_produit(run_id)
    par_kiosque = await arbre.clients_par_kiosque(run_id)

    marqueurs = {
        str(noeud.product_id): noeud.name
        for noeud in await arbre.par_niveau(run_id, NiveauOrganisation.PRODUIT)
        if noeud.product_id
    }
    noms_kiosques = {
        str(noeud.id): noeud.name
        for noeud in await arbre.par_niveau(run_id, NiveauOrganisation.KIOSQUE)
    }
    return {
        **perimetre,
        "clients_par_produit": sorted(
            (
                {
                    "product_id": pid,
                    "marqueur": marqueurs.get(pid, "(hors rattachement A-12)"),
                    "clients": compte,
                }
                for pid, compte in par_produit.items()
            ),
            key=lambda ligne: (-int(ligne["clients"]), str(ligne["product_id"])),
        ),
        "clients_par_kiosque": sorted(
            (
                {
                    "kiosque_id": kid,
                    "nom": noms_kiosques.get(kid, "(noeud absent)"),
                    "clients": compte,
                }
                for kid, compte in par_kiosque.items()
            ),
            key=lambda ligne: (-int(ligne["clients"]), str(ligne["kiosque_id"])),
        ),
        "note": (
            "liens enregistres a l'ecriture (P-01) ; une reprise D-CLI-5 laisse "
            "product_ids vide — le serveur ne porte pas la reference inverse, "
            "rien n'est invente"
        ),
    }
