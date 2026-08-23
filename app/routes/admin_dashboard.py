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
from typing import Annotated, Any
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
    if run_id is None:
        run = await _dernier_run()
        if run is None:
            return {"run_id": None, "branches": [], "note": "aucun run en base"}
        run_id = run.id

    arbre = OrgHierarchyRepository()
    par_niveau = {
        niveau: await arbre.par_niveau(run_id, niveau) for niveau in NiveauOrganisation
    }
    if not any(par_niveau.values()):
        raise HTTPException(status_code=404, detail=f"aucun noeud pour le run {run_id}")

    enfants_de: dict[UUID | None, list[Any]] = {}
    for noeuds in par_niveau.values():
        for noeud in noeuds:
            enfants_de.setdefault(noeud.parent_id, []).append(noeud)

    def _kiosque(noeud: Any) -> dict[str, Any]:
        rattaches = enfants_de.get(noeud.id, [])
        agents = [n for n in rattaches if n.niveau is NiveauOrganisation.AGENT]
        clients = [n for n in rattaches if n.niveau is NiveauOrganisation.CLIENT]
        return {
            "id": str(noeud.id),
            "nom": noeud.name,
            "quartier": noeud.district_id,
            "depositary_id": str(noeud.depositary_id) if noeud.depositary_id else None,
            "nb_agents": len(agents),
            "nb_clients": len(clients),
        }

    def _agence(noeud: Any) -> dict[str, Any]:
        return {
            "id": str(noeud.id),
            "nom": noeud.name,
            "ville": noeud.city_id,
            "kiosques": [
                _kiosque(k)
                for k in enfants_de.get(noeud.id, [])
                if k.niveau is NiveauOrganisation.KIOSQUE
            ],
        }

    branches = [
        {
            "id": str(b.id),
            "nom": b.name,
            "pays": b.country_code,
            "region": b.region_id,
            "company_id": str(b.company_id),
            "agences": [
                _agence(a)
                for a in enfants_de.get(b.id, [])
                if a.niveau is NiveauOrganisation.AGENCE
            ],
        }
        for b in par_niveau[NiveauOrganisation.BRANCHE]
    ]
    return {
        "run_id": str(run_id),
        "comptes": {n.value.lower() + "s": len(v) for n, v in par_niveau.items()},
        "branches": branches,
    }


@router.get("/tracabilite")
async def tracabilite(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
    run_id: UUID | None = None,
) -> dict[str, Any]:
    """`US-E4` — « d'ou vient cette entite ? » : le registre Faker et le
    journal d'intentions, avec leurs reconciliations."""
    if run_id is None:
        run = await _dernier_run()
        if run is None:
            return {"run_id": None, "note": "aucun run en base"}
        run_id = run.id

    ledger = FakerLedgerRepository()
    audit = AuditTrailRepository()
    intentions = await audit.exporter_run(run_id)
    orphelines_audit = await audit.intentions_orphelines(run_id)
    orphelines_faker = await ledger.reservations_orphelines(run_id)

    return {
        "run_id": str(run_id),
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
    if run_id is None:
        run = await _dernier_run()
    else:
        run = await LoaderRunRepository().obtenir(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="aucun run en base")
    if not run.mesures:
        raise HTTPException(
            status_code=404,
            detail=(
                f"le run {run.id} ne porte pas de mesures de population — "
                "anterieur a US-E3, ou son module CLIENTS n'a pas tourne"
            ),
        )
    return {"run_id": str(run.id), "mode": run.mode.value, **run.mesures}


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

    if run_id is None:
        run = await _dernier_run()
        if run is None:
            raise HTTPException(status_code=404, detail="aucun run en base")
        run_id = run.id

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
        "run_id": str(run_id),
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
    if run_id is None:
        run = await _dernier_run()
    else:
        run = await LoaderRunRepository().obtenir(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="aucun run en base")

    arbre = OrgHierarchyRepository()
    par_produit = await arbre.clients_par_produit(run.id)
    par_kiosque = await arbre.clients_par_kiosque(run.id)

    marqueurs = {
        str(noeud.product_id): noeud.name
        for noeud in await arbre.par_niveau(run.id, NiveauOrganisation.PRODUIT)
        if noeud.product_id
    }
    noms_kiosques = {
        str(noeud.id): noeud.name
        for noeud in await arbre.par_niveau(run.id, NiveauOrganisation.KIOSQUE)
    }
    return {
        "run_id": str(run.id),
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
