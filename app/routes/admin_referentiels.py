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

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.surcouche import SurcoucheRepository
from app.routes.dependances import (
    SessionAdmin,
    admin_complet,
    exige_admin,
    refuser_si_run_en_cours,
)
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.referentiel_statique import ReferentielStatique, charger_statique
from app.services.surcouche_referentiel import AjoutRefuse, SurcoucheReferentiel

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


@asynccontextmanager
async def _verrou(cle: str, par: str) -> AsyncIterator[None]:
    """`C2` — un geste a la fois par ressource, refus IMMEDIAT sinon (409).

    Le `GET`-avant-`POST` qui tient l'unicite n'est sur que sequentiellement :
    deux appels simultanes sur le meme pays lisent tous les deux « absent »
    et creent tous les deux. Le doublon serait DEFINITIF (aucun DELETE
    cote plateforme).
    """
    from app.repositories.verrous import RessourceVerrouillee, VerrouRepository

    depot = VerrouRepository()
    try:
        await depot.prendre(cle, par=par)
    except RessourceVerrouillee as occupe:
        raise HTTPException(status_code=409, detail=str(occupe)) from occupe
    try:
        yield
    finally:
        await depot.rendre(cle)


def _relayer(erreur: Exception) -> HTTPException:
    """Traduit une panne de la PLATEFORME en reponse HONNETE.

    Mesure du 23/08 : le compte ROOT partage s'est retrouve VERROUILLE
    (`HTTP 423`), le disjoncteur `INV-USR-19` a fait son travail — refuser de
    retenter pour ne pas aggraver le verrouillage — et nos ecrans ont rendu
    un **500 muet**. Le diagnostic exact existait dans les logs du conteneur
    pendant que l'utilisateur voyait « Internal Server Error » : c'est le
    contraire de ce que ce systeme promet.

    Le statut de la plateforme VOYAGE (423 reste 423 : le frontend peut
    afficher « compte verrouille » et non « bug »), le reste devient 502.
    """
    from app.clients.base import ErreurService

    if isinstance(erreur, ErreurService):
        statut = erreur.status if erreur.status in (401, 403, 423, 429) else 502
        return HTTPException(
            status_code=statut,
            detail=f"config-service : HTTP {erreur.status} — {str(erreur.detail)[:600]}",
        )
    return HTTPException(
        status_code=502,
        detail=f"config-service injoignable : {type(erreur).__name__}: {str(erreur)[:400]}",
    )


async def _identifiant_pays_ou_none(code: str) -> tuple[str | None, bool]:
    """`(country_id, plateforme_joignable)` — jamais d'exception.

    L'ABSENCE d'un pays et le SILENCE de la plateforme sont deux faits
    differents ; confondre les deux ferait dire « pas en operation » a un
    simple incident reseau. Le second ne s'invente pas (zero-trust).
    """
    lecture = _config_lecture()
    try:
        for fiche in await lecture.lister_pays():
            if str(fiche.get("iso_name", "")).strip().upper() == code.strip().upper():
                identifiant = fiche.get("_id") or fiche.get("id")
                if identifiant:
                    return str(identifiant), True
        return None, True
    except Exception:
        return None, False
    finally:
        await lecture.fermer()


async def _aller_si_en_operation(
    code_pays: str,
    action: str,
    cible: str,
    operation: Callable[[str], Awaitable[Any]],
    *,
    par: str,
) -> dict[str, Any]:
    """`I-CFG-SYNC` (23/08, Yaniv) — la matiere suit l'ETAT du pays.

    Le Loader est le System of Record : la matiere est DEJA ecrite chez nous
    quand cette porte s'ouvre. Ce qui part la-bas depend d'un seul fait,
    mesure EN DIRECT :

    * **pays EN OPERATION** -> l'ajout part IMMEDIATEMENT. Les deux cotes
      restent synchrones sans geste supplementaire : c'est la promesse.
    * **pays PAS en operation** -> RIEN ne part, et ce n'est PAS un echec :
      la matiere partira ENTIERE au `pousser`. Statut `differe` — nommer ca
      « echec » affole l'ecran et pousse a re-tenter pour rien.
    * **plateforme MUETTE** -> `indetermine`. On ne conclut pas d'un silence.

    Mesure du 23/08 qui a impose cette porte : ajouter un telco a un pays
    ABSENT creait quand meme l'operateur la-bas (`creer_telco_si_absent`
    partait AVANT la resolution du pays), puis le rattachement echouait —
    un orphelin de plus dans le referentiel PARTAGE, qu'aucun DELETE ne
    permet de retirer. La porte s'ouvre desormais AVANT le premier octet.
    """
    identifiant, joignable = await _identifiant_pays_ou_none(code_pays)
    if not joignable:
        return {
            "statut": "indetermine",
            "raison": (
                "config-service est muet — impossible de savoir si "
                f"{code_pays.upper()} est en operation. L'ajout LOCAL est en "
                "place ; relancer plus tard, rien n'a ete envoye."
            ),
        }
    if identifiant is None:
        return {
            "statut": "differe",
            "raison": (
                f"{code_pays.upper()} n'est PAS en operation — la matiere "
                "reste chez nous et partira ENTIERE a la mise en operation "
                f"(POST /admin/referentiels/pays/{code_pays.upper()}/pousser). "
                "Rien n'est envoye : un telco ou une ville sans pays serait "
                "un orphelin dans le referentiel PARTAGE."
            ),
        }
    return await _envoyer_config_service(
        action, cible, lambda: operation(identifiant), par=par
    )


async def _envoyer_config_service(
    action: str, cible_locale: str, operation: Any, par: str | None = None
) -> dict[str, Any]:
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
            payload={"action": action, "cible": cible_locale, "par": par},
        ) as suivi:
            fiche = await operation()
            suivi.reussi({"resultat": "envoye"})
        return {"statut": "envoye", "fiche_pays": bool(fiche)}
    except Exception as erreur:
        return {
            "statut": "echec — l'ajout LOCAL reste en place, renvoyer plus tard",
            "motif": f"{type(erreur).__name__}: {str(erreur)[:600]}",
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
    # BUG-C1-03 (22/08) : deduire les pays des REGIONS rendait invisible tout
    # pays dont la geographie n'est pas encore saisie — l'ecran affichait 24
    # pays quand le referentiel en portait 48. Un pays sans region s'affiche
    # desormais avec `regions: []` : le Super-Admin VOIT le trou au lieu de
    # l'ignorer.
    codes = set(referentiel.pays_index) | {r.country_iso2 for r in referentiel.regions.values()}
    for pays in sorted(codes):
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
                        # ADDITIF (16/08, US-D3) : l'ecran Depositaire choisit
                        # un quartier PAR IDENTIFIANT — les noms seuls ne
                        # suffisent plus. L'ancien champ reste tel quel.
                        "quartiers_detail": sorted(
                            (
                                {
                                    "id": q.district_id,
                                    "nom": q.name,
                                    "zone_type": q.zone_type,
                                }
                                for q in referentiel.quartiers_de_ville(ville.city_id)
                            ),
                            key=lambda q: q["nom"],
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
    session: Annotated[SessionAdmin, Depends(exige_admin)],
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
        async def _envoi(country_id: str) -> Any:
            return await admin.ajouter_ville(country_id, ville.name)

        # C2 : la cle est le PAYS, pas la ville — l'ecriture est un PUT qui
        # reecrit `cities[]` ENTIER. Deux ajouts simultanes de deux villes
        # differentes se liraient l'un l'autre avant modification : le second
        # PUT effacerait la ville du premier.
        async with _verrou(f"pousser:{ville.country_iso2}", session.email):
            envoi = await _aller_si_en_operation(
                ville.country_iso2, "ajouter_ville", ville.name, _envoi, par=session.email
            )
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
    # Les pays SANS region mais AVEC operateurs etaient invisibles ici (bug du
    # 23/08, meme famille que celui corrige sur /geographie le 22/08) : un
    # telco ajoute a un pays neuf disparaissait de l'ecran qui vient de le
    # creer. L'union des deux sources, jamais une seule.
    codes = {r.country_iso2 for r in referentiel.regions.values()}
    codes |= {t.country_iso2 for t in referentiel.telcos.values()}
    for pays in sorted(codes):
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
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`US-B7` — l'ajout d'un operateur, sans toucher au classeur.

    Les invariants vivent dans la surcouche (le meme code que le run) :
    regex compilable ET composable, exemple conforme exige, unicite dans le
    pays, et la SOMME des parts <= 100 (INV-18 etendu a l'ecriture). Verrou
    EF-55, relecture depuis la base — le rite habituel.
    """
    from app.clients.config_service import cle_comparaison

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

        async def _envoi(country_id: str) -> Any:
            fiche_telco, _creee = await admin.creer_telco_si_absent(
                telco.network_name, telco.regex_msisdn
            )
            identifiant = fiche_telco.get("_id") or fiche_telco.get("id")
            return await admin.rattacher_telco_au_pays(country_id, str(identifiant))

        # C2 : la cle est le NOM de l'operateur — c'est lui qui porte
        # l'unicite la-bas, et deux ajouts simultanes du meme nom (double-clic)
        # creeraient deux telcos indistinguables et ineffacables.
        async with _verrou(f"telco:{cle_comparaison(telco.network_name)}", session.email):
            envoi = await _aller_si_en_operation(
                telco.country_iso2,
                "ajouter_telco",
                telco.network_name,
                _envoi,
                par=session.email,
            )
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
    surcouche, _meta = await SurcoucheRepository().charger()
    # Base immuable (le classeur) + secteurs ajoutes par le Super-Admin
    # (surcouche, reversible). Les industries restent 6 : un secteur ajoute
    # ne peut se rattacher qu'a une industrie EXISTANTE.
    industries = list(statique.industries.values()) + list(surcouche.industries_ajoutees)
    secteurs = {nom: list(inds) for nom, inds in statique.secteurs.items()}
    for label, inds in surcouche.secteurs.items():
        secteurs[label] = list(inds)
    formes = list(statique.formes_juridiques) + list(surcouche.formes_juridiques)
    professions_surcouche = sorted(p for ps in surcouche.professions.values() for p in ps)
    groupes = {
        nom: {
            "profil_defaut": groupe.profil_defaut,
            "professions": list(groupe.professions) + list(surcouche.professions.get(nom, [])),
            "variants": groupe.variants,
        }
        for nom, groupe in statique.groupes.items()
    }
    dirigeants = [
        {"rang": f.rang, "francais": f.francais, "anglais": f.anglais, "abreviation": f.abreviation}
        for f in statique.fonctions_dirigeant
    ] + [dict(d) for d in surcouche.fonctions_dirigeant]
    dirigeants.sort(key=lambda d: d["rang"])
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
        "industries": industries,
        "industries_surcouche": sorted(surcouche.industries_ajoutees),
        "secteurs": secteurs,
        "secteurs_surcouche": sorted(surcouche.secteurs.keys()),
        "formes_juridiques": formes,
        "formes_surcouche": sorted(surcouche.formes_juridiques),
        "groupes": groupes,
        "professions_surcouche": professions_surcouche,
        "profils_revenu": {
            nom: {"mu": p.mu, "sigma": p.sigma, "definition": p.definition}
            for nom, p in statique.profils_revenu.items()
        },
        "pays": statique.pays,
        "fonctions_dirigeant": dirigeants,
        "dirigeants_surcouche": sorted(d["rang"] for d in surcouche.fonctions_dirigeant),
    }


class SecteurDemande(BaseModel):
    """`US-B5+` — l'ajout d'un secteur d'activite par le Super-Admin."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=60)
    industries: list[str] = Field(min_length=1)
    #: Liaison generative : types d'entreprise pour lesquels ce secteur est un
    #: connexe admissible. Vide = le secteur existe au referentiel mais n'est
    #: (encore) tire par aucun type au run.
    types: list[str] = Field(default_factory=list)


@router.post("/secteurs", status_code=201)
async def ajouter_secteur(
    demande: SecteurDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`US-B5+` — un secteur d'activite, SANS toucher au classeur.

    Meme rite que la ville (`US-B4`) : on valide chez nous (label unique cote
    classeur ET surcouche, chaque industrie de rattachement doit exister parmi
    les 6), on persiste dans la surcouche reversible, puis on RELIT depuis la
    base — la reponse est le secteur tel que le prochain run le verra.

    Le referentiel industries/secteurs est PROPRE au Loader : config-service
    n'en porte pas (recon 14/08). Aucun aller vers un service tiers, donc.

    Verrou `EF-55` : pas d'ajout pendant un run — le referentiel changerait
    sous l'empreinte D-10 en cours.
    """
    await refuser_si_run_en_cours()

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        label, _rattache = surcouche.ajouter_secteur(
            _statique(), label=demande.label, industries=demande.industries, types=demande.types
        )
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus

    meta = await depot.enregistrer(surcouche, par=session.email)

    # RELECTURE — CFG-06 : ce qui est rendu vient de la BASE, pas de la demande.
    relue, _ = await depot.charger()
    return {
        "secteur": {"label": label, "industries": list(relue.secteurs[label])},
        "surcouche": {"resume": relue.resume(), "version": meta["version"]},
    }


class IndustrieDemande(BaseModel):
    """`US-B5+` — l'ajout d'une industrie (le niveau haut de la taxonomie)."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=2, max_length=60)


@router.post("/industries", status_code=201)
async def ajouter_industrie(
    demande: IndustrieDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`US-B5+` — une industrie, SANS toucher au classeur. Le niveau haut est
    stable par nature : on l'ouvre avec prudence (label unique), la base des 6
    reste immuable et l'ajout vit dans la surcouche réversible."""
    await refuser_si_run_en_cours()
    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        label = surcouche.ajouter_industrie(_statique(), label=demande.label)
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus
    meta = await depot.enregistrer(surcouche, par=session.email)
    relue, _ = await depot.charger()
    return {"industrie": label, "surcouche": {"resume": relue.resume(), "version": meta["version"]}}


@router.delete("/secteurs/{label}")
async def retirer_secteur(
    label: str,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """Retire un secteur AJOUTE (surcouche) — la réversibilité promise. Le
    classeur des 112 est intouchable : seul un ajout peut être retiré."""
    await refuser_si_run_en_cours()
    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        surcouche.retirer_secteur(label=label)
    except AjoutRefuse as refus:
        raise HTTPException(status_code=404, detail=str(refus)) from refus
    meta = await depot.enregistrer(surcouche, par=session.email)
    relue, _ = await depot.charger()
    return {"retire": label, "surcouche": {"resume": relue.resume(), "version": meta["version"]}}


@router.delete("/industries/{label}")
async def retirer_industrie(
    label: str,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """Retire une industrie AJOUTÉE (surcouche). Refuse (409) tant qu'un secteur
    y est rattaché — garde anti-orphelin. Les 6 du classeur sont intouchables."""
    await refuser_si_run_en_cours()
    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        surcouche.retirer_industrie(label=label)
    except AjoutRefuse as refus:
        raise HTTPException(status_code=409, detail=str(refus)) from refus
    meta = await depot.enregistrer(surcouche, par=session.email)
    relue, _ = await depot.charger()
    return {"retire": label, "surcouche": {"resume": relue.resume(), "version": meta["version"]}}


# --- US-B5+ : ajout/retrait des autres dimensions du catalogue --------------


async def _appliquer_surcouche(
    action: Callable[[SurcoucheReferentiel], Any], *, par: str
) -> dict[str, Any]:
    """Petit rite commun : charger, agir, persister, relire. `action(surcouche)`
    mute la surcouche et lève `AjoutRefuse` si l'invariant casse."""
    await refuser_si_run_en_cours()
    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        resultat = action(surcouche)
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus
    meta = await depot.enregistrer(surcouche, par=par)
    relue, _ = await depot.charger()
    return {
        "resultat": resultat,
        "surcouche": {"resume": relue.resume(), "version": meta["version"]},
    }


class FormeDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=40)


@router.post("/formes", status_code=201)
async def ajouter_forme(
    demande: FormeDemande, session: Annotated[SessionAdmin, Depends(exige_admin)]
) -> dict[str, Any]:
    """`US-B5+` — une forme juridique (le plus simple : un label unique)."""
    return await _appliquer_surcouche(
        lambda s: s.ajouter_forme(_statique(), label=demande.label), par=session.email
    )


@router.delete("/formes/{label}")
async def retirer_forme(
    label: str, session: Annotated[SessionAdmin, Depends(exige_admin)]
) -> dict[str, Any]:
    return await _appliquer_surcouche(lambda s: s.retirer_forme(label=label), par=session.email)


class DirigeantDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rang: int = Field(ge=1, le=999)
    francais: str = Field(min_length=2, max_length=60)
    anglais: str = Field(min_length=2, max_length=60)
    abreviation: str = Field(default="", max_length=20)


@router.post("/dirigeants", status_code=201)
async def ajouter_dirigeant(
    demande: DirigeantDemande, session: Annotated[SessionAdmin, Depends(exige_admin)]
) -> dict[str, Any]:
    """`US-B5+` — une fonction dirigeant : rang unique + libellés FR/EN."""
    return await _appliquer_surcouche(
        lambda s: s.ajouter_dirigeant(
            _statique(),
            rang=demande.rang,
            francais=demande.francais,
            anglais=demande.anglais,
            abreviation=demande.abreviation,
        ),
        par=session.email,
    )


@router.delete("/dirigeants/{rang}")
async def retirer_dirigeant(
    rang: int, session: Annotated[SessionAdmin, Depends(exige_admin)]
) -> dict[str, Any]:
    return await _appliquer_surcouche(lambda s: s.retirer_dirigeant(rang=rang), par=session.email)


class ProfessionDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groupe: str = Field(min_length=2, max_length=120)
    label: str = Field(min_length=2, max_length=80)


@router.post("/professions", status_code=201)
async def ajouter_profession(
    demande: ProfessionDemande, session: Annotated[SessionAdmin, Depends(exige_admin)]
) -> dict[str, Any]:
    """`US-B5+` — une profession, rattachée à un groupe métier EXISTANT."""
    return await _appliquer_surcouche(
        lambda s: s.ajouter_profession(_statique(), groupe=demande.groupe, label=demande.label),
        par=session.email,
    )


@router.delete("/professions/{label}")
async def retirer_profession(
    label: str, session: Annotated[SessionAdmin, Depends(exige_admin)]
) -> dict[str, Any]:
    return await _appliquer_surcouche(
        lambda s: s.retirer_profession(label=label), par=session.email
    )


@router.get("/produits-catalogue")
async def produits_catalogue(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Le catalogue PRODUITS du Loader (`catalogue.py`, UC-11) — l'offre a
    laquelle une entite souscrit, en lecture.

    Deux logiques distinctes :
    - **LENDING** (Annexe E, `loan_json.json`) : chaque produit de credit se
      decline en INDIVIDUAL et/ou CORPORATE (`D-PRD-4`), sous des noms distincts.
    - **COLLECT** (`CATALOGUE_COLLECT`) : produits d'epargne, deja categorises.

    Rendu tel que le generateur les creerait — les comptes 6 (lending) et
    len(COLLECT) sont ceux du chargeur, jamais un echo d'ecran.
    """
    from app.services.catalogue import (
        CATALOGUE_COLLECT,
        charger_loan_json,
        nom_lending,
    )
    from app.services.pilotage import LOAN_JSON

    lending: list[dict[str, Any]] = []
    for produit in charger_loan_json(LOAN_JSON):
        for categorie in produit.categories_cibles:
            lending.append(
                {
                    "nom": nom_lending(produit, categorie),
                    "type": "LENDING",
                    "categorie": categorie.value,
                    "duree_jours": produit.duree_jours,
                    "montant_min": produit.montant_min,
                    "montant_max": produit.montant_max,
                }
            )
    collect = [
        {
            "nom": p.nom,
            "type": "COLLECT",
            "categorie": p.categorie.value,
            "policy_type": p.policy_type.value,
            "code": p.code,
        }
        for p in CATALOGUE_COLLECT
    ]
    return {
        "lending": lending,
        "collect": collect,
        "comptes": {"lending": len(lending), "collect": len(collect)},
    }


# ---------------------------------------------------------------------------
# C1 (22/08) — le pays DANS LE LOADER : lister, creer, retirer
# ---------------------------------------------------------------------------
# Les quatre bugs de conception releves par l'audit prod du 22/08 :
#   BUG-C1-01  POST /pays poussait vers config-service sans que le Loader
#              connaisse le pays — l'admin croyait « creer », le Loader ignorait.
#   BUG-C1-02  `ajouter_pays` n'etait joignable que par script — aucun ecran.
#   BUG-C1-03  aucun GET des fiches : 22 pays invisibles, autocompletion
#              impossible (corrige aussi dans /geographie).
#   BUG-C1-04  la reversibilite CFG-03 n'avait aucun DELETE.
# Tout est ADDITIF : POST /pays (US-B6, le push volontaire) est inchange.


# DECISION DIRECTION 22/08 : PAS de creation manuelle de pays a l'ecran —
# « ce n'est pas de l'automatisation, ca rend les choses lourdes ». Les
# pays entrent dans la base du Loader UNIQUEMENT par le backend :
# fichiers traites -> scripts/importer_referentiel_pays.py (versionne,
# re-lancable, invariants EF-02/INV-18 appliques ligne a ligne). L'ecran
# garde : VOIR (GET /pays), METTRE EN OPERATION (POST /pays/{iso}/pousser),
# RETIRER (DELETE /surcouche/{id}) et ACTIVER au perimetre (US-B3).
# L'ajout de regions/villes/quartiers/telcos sur un pays EXISTANT reste
# intact (US-B4/US-B7) — la structure geographique ne bouge pas.


@router.get("/pays")
async def lister_fiches_pays(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`C1` — TOUTES les fiches pays du Loader, avec leur COMPLETUDE.

    C'est la matiere de l'ecran « Pays » et du globe : chaque fiche complete
    (devise, TVA, fuseau, regulateurs), les compteurs de matiere, et
    `sur_config_service` verifie EN DIRECT — un pays present des deux cotes
    est EN OPERATION (le point clignotant du globe). config-service muet ->
    `null`, jamais un faux « non ».
    """
    surcouche, meta = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())

    presents: set[str] | None = None
    lecture = _config_lecture()
    try:
        presents = {
            str(p.get("iso_name") or "").upper() for p in await lecture.lister_pays()
        }
    except Exception:
        presents = None
    finally:
        await lecture.fermer()

    quartiers_par_ville: dict[str, int] = {}
    for quartier in referentiel.quartiers.values():
        quartiers_par_ville[quartier.city_id] = quartiers_par_ville.get(quartier.city_id, 0) + 1

    fiches = []
    for code in sorted(referentiel.pays_index):
        fiche = referentiel.pays_index[code]
        villes = [v for v in referentiel.villes.values() if v.country_iso2 == code]
        fiches.append(
            {
                "iso2": code,
                "nom_fr": fiche.nom_fr,
                "nom_en": fiche.nom_en,
                "capitale": fiche.capitale,
                "dial_code": fiche.dial_code,
                "devise_iso": fiche.devise_iso,
                "tva_percent": fiche.tva_percent,
                "timezone": fiche.timezone,
                "region_africa": fiche.region_africa,
                "regulateur_telco": fiche.regulateur_telco,
                "regulateur_finance": fiche.regulateur_finance,
                "origine": "classeur" if _geo().pays(code) else "surcouche",
                "completude": {
                    "regions": len(referentiel.regions_du_pays(code)),
                    "villes": len(villes),
                    "quartiers": sum(
                        quartiers_par_ville.get(v.city_id, 0) for v in villes
                    ),
                    "telcos": len(referentiel.telcos_du_pays(code)),
                },
                "sur_config_service": (code in presents) if presents is not None else None,
                # `V-02` (23/08) — L'ECRAN NE DEVINE PLUS. Il affichait un
                # bouton « Pousser » cliquable sur des pays que la porte
                # refusait ensuite en 422 : un clic pour une erreur. La regle
                # est ici, la MEME que celle de la porte (`_porte_d_operation`),
                # et `manques` donne l'infobulle qui dit pourquoi.
                **{
                    cle: valeur
                    for cle, valeur in _porte_d_operation(referentiel, code).items()
                    if cle != "villes"
                },
            }
        )
    return {
        "pays": fiches,
        # Le 4e etat de la machine (conception 22/08) : present LA-BAS mais
        # inconnu du Loader — une ANOMALIE a montrer, jamais a cacher (la
        # recon du 14/08 avait vu un « ca » minuscule qui traine). Meme appel
        # config-service que `presents`, zero cout supplementaire.
        "hors_loader": (
            sorted(code for code in presents if code and code not in referentiel.pays_index)
            if presents is not None
            else None
        ),
        "surcouche": {"resume": surcouche.resume(), "version": meta["version"]},
    }


def _porte_d_operation(referentiel: Any, code: str) -> dict[str, Any]:
    """LA REGLE, ecrite UNE fois : ce pays est-il POUSSABLE, et sinon quoi ?

    Elle sert deux appelants qui devaient jusqu'ici la deviner chacun de leur
    cote : `POST /pays/{iso}/pousser`, qui refuse en 422, et `GET /pays`, qui
    dit a l'ecran s'il peut proposer le bouton. Deux implementations d'une
    meme regle finissent toujours par diverger — et c'est arrive : l'ecran
    affichait un bouton « Pousser » cliquable sur des pays que la porte
    refusait, donc un clic pour une erreur (signale par Yaniv, 23/08).

    Trois matieres, et la raison de chacune :

      devise   sans elle le pays n'a pas de zone monetaire — mais elle est
               garantie par l'ingestion (`ajouter_pays` refuse une devise
               orpheline), on la verifie quand meme, une garantie non
               verifiee n'en est pas une ;
      villes   un pays sans ville n'heberge aucun client, aucune agence,
               aucun depositaire ;
      telcos   un pays sans operateur ne compose AUCUN numero (`EF-27`) —
               ni client, ni agent, ni dirigeant.

    Les AVERTISSEMENTS ne bloquent pas : un marche a un seul operateur opere,
    il ne ressemble simplement a aucun marche africain.
    """
    fiche = referentiel.pays(code)
    if fiche is None:
        return {
            "poussable": False,
            "manques": ["fiche inconnue du Loader"],
            "avertissements": [],
            "villes": [],
        }

    villes = sorted(
        v.name for v in referentiel.villes.values() if v.country_iso2 == code
    ) or [fiche.capitale]
    villes = [nom for nom in villes if str(nom).strip()]
    telcos = referentiel.telcos_du_pays(code)

    manques: list[str] = []
    if not villes:
        manques.append("AUCUNE ville ni capitale")
    if not telcos:
        manques.append("AUCUN operateur telecom")
    if not str(fiche.devise_iso or "").strip():
        manques.append("AUCUNE devise")

    avertissements: list[str] = []
    if telcos and len(telcos) < 2:
        avertissements.append(
            f"{code} : un seul operateur au referentiel — marche peu credible, "
            "completer la matiere telco des que possible"
        )
    somme = sum(t.part_marche for t in telcos)
    if telcos and somme < 50:
        avertissements.append(
            f"{code} : parts de marche cumulees {somme:.0f} % < 50 % — "
            "la distribution des clients par operateur sera peu realiste"
        )
    return {
        "poussable": not manques,
        "manques": manques,
        "avertissements": avertissements,
        "villes": villes,
    }


@router.post("/pays/{iso}/pousser")
async def pousser_pays_en_operation(
    iso: str,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`C1`/`US-B6` — mettre un pays du Loader EN OPERATION sur la plateforme.

    L'ALLER COMPLET, DANS L'ORDRE QUE LE CONTRAT DE config-service IMPOSE
    (on le maitrise — 9 services audites) :

      1. la DEVISE : resolue par code ISO la-bas, CREEE depuis NOTRE fiche si
         absente (une devise n'est jamais orpheline, ni ici ni la-bas) ;
      2. les TELCOS du pays : crees si absents (motif ancre + compile,
         RC-184) — AVANT le pays, car le payload du pays les reference par
         UUID, exactement comme la devise ;
      3. le PAYS : cree avec ses 9 champs, ses villes, sa devise et ses
         telcos ; deja present -> ADOPTE (GET-avant-POST, jamais un doublon) ;
      4. les VILLES manquantes : cas adoption — la relecture integrale du
         client (ANO-CFG-DUP : les 9 champs) complete `cities[]` sans doublon ;
      5. le RATTACHEMENT des telcos : cas adoption uniquement — a la creation
         le payload les portait deja. « Un telco cree mais non rattache
         n'appartient a aucun pays » (US-B7).

    Regions, quartiers, GPS, TVA, parts de marche RESTENT chez nous — la
    plateforme n'a aucun champ pour eux. Chaque echec partiel est DIT et
    n'interrompt pas le reste ; le refus complet voyage (21/08). Idempotent :
    re-pousser complete ce qui manque et ne double rien.
    """
    from uuid import NAMESPACE_OID, uuid5

    from app.clients.base import ErreurService
    from app.clients.config_service import cle_comparaison
    from app.repositories.audit_trail import AuditTrailRepository
    from app.routes.admin_entites import RUN_ADMIN

    await refuser_si_run_en_cours()

    code = iso.strip().upper()
    surcouche, _ = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())
    fiche = referentiel.pays(code)
    if fiche is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"pays {code!r} inconnu du Loader — on ne met en operation que "
                "ce que le Loader porte : l'importer d'abord "
                "(scripts/importer_referentiel_pays.py), puis le pousser."
            ),
        )
    # LA REGLE vit dans `_porte_d_operation` — la meme que celle qui decide si
    # l'ecran affiche le bouton. Une seule ecriture, donc aucune divergence
    # possible entre ce que l'ecran propose et ce que la porte accepte.
    porte = _porte_d_operation(referentiel, code)
    villes = list(porte["villes"])
    fiche_devise = referentiel.devises.get(fiche.devise_iso)
    telcos_locaux = referentiel.telcos_du_pays(code)
    # PORTE DE COMPLETUDE (22/08, recommandation QA validee par Yaniv) :
    # EN OPERATION veut dire UTILISABLE. Un pays sans operateur ne compose
    # aucun numero (EF-27) et n'onboarde personne — on ne pousse pas une
    # coquille vide. Minimum viable : devise (garantie plus bas) + >= 1
    # ville + >= 1 telco au plan composable.
    if not porte["poussable"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"pays {code} : {', '.join(porte['manques'])}. EN OPERATION "
                "veut dire UTILISABLE — sans ville le pays n'heberge personne, "
                "sans operateur il ne compose aucun numero (EF-27). Charger sa "
                "matiere d'abord (US-B7)."
            ),
        )

    echecs: list[str] = []
    admin = _config_admin()
    # C2 : un seul aller a la fois sur CE pays. Deux appels simultanes
    # creeraient chacun leur exemplaire — la plateforme n'a aucun index
    # unique (RC-183) et aucun DELETE.
    async with _verrou(f"pousser:{code}", session.email):
        try:
            audit = AuditTrailRepository()
            entite = uuid5(NAMESPACE_OID, f"finzuu-pays:{code}")
            async with audit.intention(
                RUN_ADMIN,
                entity_type="Country",
                entity_id=entite,
                operation="CREATE",
                cible="config-service POST /countries/create",
                payload={"iso_name": code, "depuis": "fiche Loader", "par": session.email},
            ) as suivi:
                # Ce qui a DEJA ete cree la-bas quand un echec survient plus
                # loin : mesure du 23/08 — `AOA` et `GNF` trainaient sur
                # config-service sans aucun pays, nees d'un aller interrompu et
                # jamais dites. Un residu tu est un residu qu'on ne nettoie pas.
                residus: list[str] = []
                try:
                    # 1. LA DEVISE — d'abord, le pays la reference par UUID
                    devise_id = await admin.resoudre_devise(fiche.devise_iso)
                    devise_statut = "deja_en_operation"
                    if devise_id is None:
                        fiche_dev, cree_devise = await admin.creer_devise_si_absent(
                            {
                                "name_en": fiche_devise.nom if fiche_devise else fiche.devise_iso,
                                "name_fr": fiche_devise.nom if fiche_devise else fiche.devise_iso,
                                "iso_name": fiche.devise_iso,
                                "accepts_decimal": bool(
                                    fiche_devise and fiche_devise.decimales > 0
                                ),
                            }
                        )
                        devise_id = str(fiche_dev.get("id") or fiche_dev.get("_id") or "")
                        devise_statut = "mise_en_operation" if cree_devise else "deja_en_operation"
                        if cree_devise:
                            residus.append(f"devise {fiche.devise_iso}")

                    # 2. LES TELCOS — AVANT le pays (l'ordre du contrat,
                    #    rappele par Yaniv) : le payload de creation du pays les
                    #    reference par UUID, comme la devise. Crees si absents
                    #    (motif ancre + compile, RC-184), ids collectes.
                    telcos_statuts = []
                    telco_ids: list[str] = []
                    for telco in telcos_locaux:
                        fiche_telco, telco_cree = await admin.creer_telco_si_absent(
                            telco.network_name, telco.regex_msisdn
                        )
                        telco_id = str(fiche_telco.get("id") or fiche_telco.get("_id") or "")
                        if telco_id:
                            telco_ids.append(telco_id)
                        if telco_cree:
                            residus.append(f"telco {telco.network_name!r}")
                        telcos_statuts.append(
                            {
                                "nom": telco.network_name,
                                "statut": "mis_en_operation" if telco_cree else "deja_en_operation",
                                "rattache": bool(telco_id),
                            }
                        )

                    # 3. LE PAYS — TOUS les champs du contrat (les 9), devise et
                    #    telcos references par UUID ; present -> adopte
                    fiche_pays, cree = await admin.creer_pays_si_absent(
                        {
                            "name_en": fiche.nom_en,
                            "name_fr": fiche.nom_fr,
                            "iso_name": code,
                            "dial_code": fiche.dial_code,
                            "region": fiche.region_africa or "Africa",
                            "continent": "Africa",
                            "cities": villes,
                            "currencies": [devise_id] if devise_id else [],
                            "telcos": telco_ids,
                        }
                    )
                except ErreurService as exc:
                    # Le REFUS COMPLET voyage (21/08, pays GN) — jamais un 502 muet.
                    suivi.echoue(f"HTTP {exc.status} : {exc.detail[:600]}")
                    reste = (
                        " ATTENTION, l'aller s'est arrete en chemin : "
                        f"{', '.join(residus)} ont ete crees la-bas et restent "
                        f"SANS pays. Re-pousser {code} les reutilisera (aucun "
                        "doublon) ; abandonner laisse un residu dans le "
                        "referentiel PARTAGE."
                        if residus
                        else ""
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            f"config-service a refuse : HTTP {exc.status} — "
                            f"{exc.detail[:600]}.{reste}"
                        ),
                    ) from exc
                identifiant = str(fiche_pays.get("id") or fiche_pays.get("_id") or "")
                suivi.reussi({"country_id": identifiant, "cree": cree})

            # 4. LES VILLES MANQUANTES — cas adoption : completer, jamais doubler.
            villes_completees = 0
            if not cree and identifiant:
                # Comparaison NORMALISEE (C1, 23/08) : « Yaounde » et « Yaoundé »
                # sont la meme ville. Une comparaison exacte aurait rajoute un
                # doublon a CHAQUE re-poussee, sans jamais pouvoir le retirer.
                deja_labas = {
                    cle_comparaison(str(v)) for v in (fiche_pays.get("cities") or [])
                }
                manquantes = [
                    nom for nom in villes if cle_comparaison(nom) not in deja_labas
                ]
                if manquantes:
                    try:
                        # UN aller-retour pour toutes (C3) : la Cote d'Ivoire
                        # passait par 338 appels et depassait 60 s.
                        _fiche, ajoutees = await admin.ajouter_villes(
                            identifiant, manquantes
                        )
                        villes_completees = len(ajoutees)
                    except Exception as erreur:  # tout ou rien — et DIT
                        echecs.append(
                            f"{len(manquantes)} ville(s) non envoyee(s) : "
                            f"{type(erreur).__name__}: {str(erreur)[:120]} — "
                            "re-pousser reprend exactement la ou on s'est arrete"
                        )

            # 5. Cas ADOPTION : les telcos deja crees (etape 2) sont RATTACHES au
            #    pays existant — « un telco cree mais non rattache n'appartient a
            #    aucun pays » (US-B7). A la creation, le payload les portait deja.
            if not cree and identifiant:
                for statut_telco, telco_id in zip(telcos_statuts, telco_ids, strict=False):
                    try:
                        await admin.rattacher_telco_au_pays(identifiant, telco_id)
                    except Exception as erreur:  # echec PARTIEL, dit — jamais muet
                        statut_telco["rattache"] = False
                        echecs.append(
                            f"telco {statut_telco['nom']} : "
                            f"{type(erreur).__name__}: {str(erreur)[:120]}"
                        )
        finally:
            await admin.fermer()

    # AVERTISSEMENTS de credibilite — NON bloquants, toujours DITS (calibrage
    # 22/08) : un seul operateur ou des parts sommant sous 50 % operent, mais
    # ne ressemblent a aucun marche africain — un bailleur le verrait.
    avertissements: list[str] = list(porte["avertissements"])

    return {
        "pays": {"iso2": code, "id": identifiant, "nom_fr": fiche.nom_fr},
        "statut": "mis_en_operation" if cree else "deja_en_operation",
        "devise": {"code": fiche.devise_iso, "statut": devise_statut},
        "avertissements": avertissements,
        "villes_envoyees": len(villes) if cree else villes_completees,
        "telcos": telcos_statuts,
        "echecs": echecs,
        "note": (
            "l'aller COMPLET : devise -> pays+villes -> villes manquantes -> "
            "telcos crees et rattaches. Regions, quartiers, GPS, TVA et parts "
            "de marche restent la richesse du Loader — la plateforme n'a "
            "aucun champ pour elles"
        ),
    }


class RectificationDemande(BaseModel):
    """`C6` — la rectification se CONFIRME. Sans confirmation, on ne rend que
    l'ecart : le referentiel est PARTAGE, on ne le reecrit pas par surprise."""

    model_config = ConfigDict(extra="forbid")

    confirmer: bool = False
    motif: str = Field(default="", max_length=280)


@router.post("/pays/{iso}/rectifier")
async def rectifier_pays_en_operation(
    iso: str,
    demande: RectificationDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`C6` — RECTIFIER la fiche d'un pays DEJA en operation.

    Le manque mesure le 23/08 : `CV` opere avec la devise `XAF` la ou notre
    fiche dit `CVE`, et son `dial_code` est vide. `pousser` ne pouvait rien
    y faire — il ADOPTE un pays existant, il ne le corrige pas. Un pays en
    operation mentait donc sur sa zone monetaire, et tout prix cree dessus
    en heritait.

    Le geste, dans **l'ORDRE DU POUSSER** (il n'y en a pas deux) :

      1. la DEVISE de notre fiche, resolue la-bas, CREEE si absente ;
      2. les TELCOS de notre referentiel, crees si absents ;
      3. le PAYS reecrit ENTIER (`PUT`, les 9 champs) depuis notre fiche.

    Trois protections, parce qu'un `PUT` ecrase tout ce qu'il n'envoie pas :

    * **fusion, jamais ecrasement** — les villes et les telcos presents
      la-bas et inconnus de nous sont CONSERVES : le referentiel est
      partage, une autre equipe a le droit d'y avoir ajoute quelque chose ;
    * **la devise, elle, est REMPLACEE** — c'est tout l'objet du geste, et
      notre fiche fait autorite (System of Record) ;
    * **apercu par defaut** — sans `confirmer: true`, rien n'est ecrit : on
      rend l'ECART champ par champ, avant/apres.
    """
    from uuid import NAMESPACE_OID, uuid5

    from app.clients.base import ErreurService
    from app.clients.config_service import cle_comparaison
    from app.repositories.audit_trail import AuditTrailRepository
    from app.routes.admin_entites import RUN_ADMIN

    await refuser_si_run_en_cours()

    code = iso.strip().upper()
    surcouche, _ = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())
    fiche = referentiel.pays(code)
    if fiche is None:
        raise HTTPException(
            status_code=422,
            detail=f"pays {code!r} inconnu du Loader — rien a rectifier depuis quoi.",
        )

    # C2 : la rectification et l'aller se disputent LA MEME ressource —
    # meme cle de verrou, donc jamais les deux a la fois sur un pays.
    async with _verrou(f"pousser:{code}", session.email):
        lecture = _config_lecture()
        admin = _config_admin()
        try:
            distants = await lecture.lister_pays()
            distant = next(
                (d for d in distants if str(d.get("iso_name", "")).strip().upper() == code),
                None,
            )
            if distant is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{code} n'est PAS en operation — il n'y a rien a rectifier "
                        f"la-bas. C'est un POST /pays/{code}/pousser qu'il faut."
                    ),
                )
            identifiant = str(distant.get("_id") or distant.get("id") or "")

            # --- 1. LA DEVISE (l'ordre du pousser) ---------------------------
            # L'APERCU NE CREE RIEN. Defaut attrape sur la prod le 23/08 : cette
            # etape creait la devise `CVE` AVANT le test de `confirmer` — un
            # apercu qui ecrit n'est pas un apercu. On RESOUT (lecture) toujours,
            # on CREE seulement sur confirmation.
            devise_id = await admin.resoudre_devise(fiche.devise_iso)
            fiche_devise = referentiel.devises.get(fiche.devise_iso)
            devise_creee = False
            devise_a_creer = devise_id is None
            if devise_a_creer and demande.confirmer:
                fiche_dev, devise_creee = await admin.creer_devise_si_absent(
                    {
                        "name_en": fiche_devise.nom if fiche_devise else fiche.devise_iso,
                        "name_fr": fiche_devise.nom if fiche_devise else fiche.devise_iso,
                        "iso_name": fiche.devise_iso,
                        "accepts_decimal": bool(fiche_devise and fiche_devise.decimales > 0),
                    }
                )
                devise_id = str(fiche_dev.get("id") or fiche_dev.get("_id") or "")

            # --- 2. LES TELCOS — meme regle : reconnaitre, puis creer SI confirme
            deja_la_bas = {
                cle_comparaison(str(t.get("network_name") or t.get("name") or "")): str(
                    t.get("_id") or t.get("id") or ""
                )
                for t in await lecture.lister_telcos()
            }
            telco_ids: list[str] = []
            telcos_a_creer: list[str] = []
            for telco in referentiel.telcos_du_pays(code):
                connu = deja_la_bas.get(cle_comparaison(telco.network_name))
                if connu:
                    telco_ids.append(connu)
                    continue
                if not demande.confirmer:
                    telcos_a_creer.append(telco.network_name)
                    continue
                fiche_telco, _cree = await admin.creer_telco_si_absent(
                    telco.network_name, telco.regex_msisdn
                )
                telco_id = str(fiche_telco.get("id") or fiche_telco.get("_id") or "")
                if telco_id:
                    telco_ids.append(telco_id)
            # FUSION : ce qui est deja rattache la-bas et qu'on ne connait pas
            # RESTE rattache — un PUT n'est pas une occasion de faire le menage
            # chez les autres.
            for existant in _references(distant.get("telcos")):
                if existant not in telco_ids:
                    telco_ids.append(existant)

            # --- 3. LES VILLES : union normalisee ------------------------------
            nos_villes = sorted(
                v.name for v in referentiel.villes.values() if v.country_iso2 == code
            ) or ([fiche.capitale] if fiche.capitale.strip() else [])
            villes_labas = [str(v).strip() for v in (distant.get("cities") or []) if str(v).strip()]
            fusion_villes = list(villes_labas)
            connues = {cle_comparaison(v) for v in villes_labas}
            for nom in nos_villes:
                if cle_comparaison(nom) not in connues:
                    connues.add(cle_comparaison(nom))
                    fusion_villes.append(nom)

            cible = {
                "name_en": fiche.nom_en,
                "name_fr": fiche.nom_fr,
                "iso_name": code,
                "dial_code": fiche.dial_code,
                "region": fiche.region_africa or "Africa",
                "continent": "Africa",
                "cities": fusion_villes,
                "currencies": [devise_id],
                "telcos": telco_ids,
            }

            # --- L'ECART, champ par champ -------------------------------------
            ecart: dict[str, Any] = {}
            for champ in ("name_en", "name_fr", "dial_code", "region", "continent"):
                avant = str(distant.get(champ) or "")
                if avant != str(cible[champ]):
                    ecart[champ] = {"avant": avant, "apres": cible[champ]}
            devises_avant = _references(distant.get("currencies"))
            if devises_avant != ([devise_id] if devise_id else []):
                ecart["devise"] = {
                    "avant": devises_avant,
                    "apres": [devise_id] if devise_id else [],
                    "iso_attendu": fiche.devise_iso,
                    "a_creer_la_bas": devise_a_creer,
                }
            if telcos_a_creer:
                ecart["telcos_a_creer"] = telcos_a_creer
            if len(fusion_villes) != len(villes_labas):
                ecart["villes"] = {
                    "avant": len(villes_labas),
                    "apres": len(fusion_villes),
                    "ajoutees": len(fusion_villes) - len(villes_labas),
                }
            telcos_avant = _references(distant.get("telcos"))
            if sorted(telcos_avant) != sorted(telco_ids):
                ecart["telcos"] = {"avant": len(telcos_avant), "apres": len(telco_ids)}

            if not demande.confirmer:
                return {
                    "pays": code,
                    "statut": "apercu",
                    "ecart": ecart,
                    "rien_a_rectifier": not ecart,
                    "note": (
                        "AUCUNE ecriture — ni le pays, ni la devise, ni les "
                        "telcos : l'apercu LIT, il ne prepare rien la-bas. "
                        "Relancer avec `confirmer: true` pour appliquer. Le "
                        "referentiel est PARTAGE : la reecriture complete (le "
                        "serveur n'a que des PUT) se confirme."
                    ),
                }
            if not ecart:
                return {
                    "pays": code,
                    "statut": "deja_conforme",
                    "ecart": {},
                    "note": "la fiche la-bas est deja celle du Loader — rien n'a ete envoye",
                }

            audit = AuditTrailRepository()
            async with audit.intention(
                RUN_ADMIN,
                entity_type="Country",
                entity_id=uuid5(NAMESPACE_OID, f"finzuu-pays:{code}"),
                operation="UPDATE",
                cible="config-service PUT /countries/{id}",
                payload={
                    "iso_name": code,
                    "ecart": ecart,
                    "motif": demande.motif,
                    "par": session.email,
                },
            ) as suivi:
                try:
                    await admin.remplacer_pays(identifiant, cible)
                except ErreurService as exc:
                    suivi.echoue(f"HTTP {exc.status} : {exc.detail[:600]}")
                    raise HTTPException(
                        status_code=502,
                        detail=f"config-service a refuse : HTTP {exc.status} — {exc.detail[:600]}",
                    ) from exc
                suivi.reussi({"country_id": identifiant, "champs": sorted(ecart)})

            # RELECTURE — l'etat d'APRES, mesure et non suppose.
            relus = await lecture.lister_pays()
            relu: dict[str, Any] = next(
                (d for d in relus if str(d.get("iso_name", "")).strip().upper() == code),
                {},
            )
        except HTTPException:
            raise  # nos refus pedagogiques passent intacts
        except Exception as erreur:  # la panne de la PLATEFORME est DITE, pas 500
            raise _relayer(erreur) from erreur
        finally:
            await lecture.fermer()
            await admin.fermer()

    return {
        "pays": code,
        "statut": "rectifie",
        "ecart": ecart,
        "devise_mise_en_operation": devise_creee,
        "relu": {
            "name_fr": relu.get("name_fr"),
            "dial_code": relu.get("dial_code"),
            "villes": len(relu.get("cities") or []),
            "devises": _references(relu.get("currencies")),
            "telcos": len(_references(relu.get("telcos"))),
        },
        "note": (
            "reecriture COMPLETE (le serveur n'a aucun PATCH) dans l'ordre du "
            "pousser : devise -> telcos -> pays. Villes et telcos d'autres "
            "equipes CONSERVES ; la devise, elle, suit notre fiche"
        ),
    }


@router.patch("/pays/{iso}/etat")
async def changer_etat_pays_en_operation(
    iso: str,
    demande: EtatRessourceDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`C7` / `A-08` — SORTIR un pays d'operation, et l'y remettre.

    Le verbe qui manquait : `activer_pays` et `desactiver_pays` existaient
    dans le client depuis la mesure du 09/08, mais aucune route ne les
    exposait. L'aller etait donc SANS RETOUR — une mise en operation par
    erreur devenait definitive.

    Une garde, mesuree et non theorique : **on ne desactive pas un pays que
    NOTRE configuration compte generer**. Le run le viserait, la plateforme
    le refuserait, et l'echec arriverait a la 1500e ecriture au lieu d'ici.
    Le retirer d'abord de la configuration (`US-B1`), puis le desactiver.

    Aucune suppression : `is_active` est un ETAT, reversible dans les deux
    sens — c'est ce qui distingue ce geste de la devise, dont la reactivation
    n'a JAMAIS ete mesuree et dont la desactivation reste donc refusee.

    RELECTURE obligatoire : l'etat rendu est celui mesure APRES le geste, pas
    celui qu'on a demande (`ANO-CFG-LIFECYCLE` : un serveur qui repond sans
    agir existe, on l'a vu).
    """
    from uuid import NAMESPACE_OID, uuid5

    from app.repositories.audit_trail import AuditTrailRepository
    from app.repositories.configuration import ConfigurationRepository
    from app.routes.admin_entites import RUN_ADMIN

    await refuser_si_run_en_cours()
    code = iso.strip().upper()

    if not demande.actif:
        configuration, _meta = await ConfigurationRepository().charger()
        fiche_config = configuration.pays.get(code)
        if fiche_config is not None and fiche_config.actif:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{code} est ACTIF dans la configuration du Loader : le "
                    "prochain run le viserait et echouerait sur une plateforme "
                    "qui ne l'accepte plus. Le desactiver d'abord dans la "
                    "configuration (US-B1), puis ici."
                ),
            )

    async with _verrou(f"pousser:{code}", session.email):
        lecture = _config_lecture()
        admin = _config_admin()
        try:
            distants = await lecture.lister_pays()
            distant = next(
                (d for d in distants if str(d.get("iso_name", "")).strip().upper() == code),
                None,
            )
            if distant is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"{code} n'est pas sur la plateforme — il n'y a pas "
                        f"d'etat a changer. Le pousser d'abord "
                        f"(POST /pays/{code}/pousser)."
                    ),
                )
            identifiant = str(distant.get("_id") or distant.get("id") or "")
            avant = distant.get("is_active")

            audit = AuditTrailRepository()
            async with audit.intention(
                RUN_ADMIN,
                entity_type="Country",
                entity_id=uuid5(NAMESPACE_OID, f"finzuu-pays:{code}"),
                operation="UPDATE",
                cible="config-service PATCH /countries/(de)activate",
                payload={
                    "iso_name": code,
                    "actif": demande.actif,
                    "motif": demande.motif,
                    "par": session.email,
                },
            ) as suivi:
                try:
                    if demande.actif:
                        await admin.activer_pays(identifiant)
                    else:
                        await admin.desactiver_pays(identifiant)
                except Exception as erreur:
                    suivi.echoue(type(erreur).__name__)
                    raise _relayer(erreur) from erreur
                suivi.reussi({"country_id": identifiant, "actif": demande.actif})

            relus = await lecture.lister_pays()
            relu_pays: dict[str, Any] = next(
                (d for d in relus if str(d.get("iso_name", "")).strip().upper() == code),
                {},
            )
            etat_relu = relu_pays.get("is_active")
            if isinstance(etat_relu, bool) and etat_relu is not demande.actif:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"l'etat de {code} n'a PAS change a la relecture — le "
                        "serveur a repondu sans agir (signature exacte de "
                        "l'ANO-CFG-LIFECYCLE de juin)"
                    ),
                )
        except HTTPException:
            raise
        except Exception as erreur:
            raise _relayer(erreur) from erreur
        finally:
            await lecture.fermer()
            await admin.fermer()

    return {
        "pays": code,
        "avant": avant,
        "actif": demande.actif,
        "etat_relu": etat_relu,
        "motif": demande.motif,
        "note": (
            "referentiel PARTAGE modifie — visible par toutes les equipes. "
            "L'etat est REVERSIBLE dans les deux sens (contrairement a la "
            "devise, dont la reactivation n'a jamais ete mesuree) ; la fiche "
            "et ses villes restent la-bas, seul l'etat change"
        ),
    }


@router.delete("/surcouche/{identifiant}")
async def retirer_ajout_surcouche(
    identifiant: str,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`C1` / `CFG-03` — la reversibilite promise, enfin exposee (BUG-C1-04).

    Retire UN ajout de la surcouche : pays (code ISO2), region, ville,
    quartier (identifiants `SC-...`). Le classeur est intouchable — retirer
    une ligne du classeur repond 404, pas un retrait silencieux. Les gardes
    anti-orphelin du service s'appliquent (un pays qui porte encore des
    ajouts, une region qui porte des villes -> 422 explique).
    """
    await refuser_si_run_en_cours()

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        retire = surcouche.retirer(identifiant.strip())
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus
    if not retire:
        raise HTTPException(
            status_code=404,
            detail=(
                f"{identifiant!r} n'est pas un ajout de la surcouche — le "
                "classeur est immuable, rien a retirer."
            ),
        )
    meta = await depot.enregistrer(surcouche, par=session.email)
    return {
        "retire": identifiant,
        "surcouche": {"resume": surcouche.resume(), "version": meta["version"]},
    }


# ---------------------------------------------------------------------------
# US-B6 — demander un nouveau pays : le REFUS PEDAGOGIQUE (EF-05)
# ---------------------------------------------------------------------------

#: La matiere qu'un 5e pays exigerait, chaque manque NOMME avec sa raison —
#: c'est la story elle-meme : « la liste exacte de la matiere manquante,
#: afin de preparer une future extension au lieu de me heurter a un mur ».
MATIERE_REQUISE_PAYS: list[dict[str, str]] = [
    {
        "matiere": "regions",
        "pourquoi": "chaque Branche s'ancre dans une region (arbre CR-02)",
    },
    {
        "matiere": "villes",
        "pourquoi": "chaque Agence se place dans une ville (unicite par company)",
    },
    {
        "matiere": "quartiers",
        "pourquoi": "chaque Kiosque habite un quartier — un seul par run (CR-02)",
    },
    {
        "matiere": "plan de numerotation telco",
        "pourquoi": "sans regex COMPOSABLE, aucun MSISDN generable (US-B7)",
    },
    {
        "matiere": "parts de marche des telcos",
        "pourquoi": "le tirage des operateurs exige des parts sommant a 100 (INV-18)",
    },
    {
        "matiere": "patronymes et prenoms",
        "pourquoi": "le generateur n'a aucun corpus de noms pour ce pays",
    },
    {
        "matiere": "profils de revenus par profession",
        "pourquoi": "le solde initial est un LogNormal par metier ET par pays (SD-5)",
    },
    {
        "matiere": "quota clients",
        "pourquoi": "la repartition EF-22 est definie par pays — sans quota, part nulle",
    },
]


# L'ancienne route POST /pays (US-B6, payload complet ressaisi vers
# config-service) a ete CONSOLIDEE le 22/08 : creer = POST /pays (dans le
# Loader), mettre en operation = POST /pays/{iso}/pousser (depuis NOTRE
# fiche, rien a ressaisir). Un seul sens par verbe.


# DECISION 22/08 (Yaniv, recensement de l'inutile) : la creation MANUELLE
# de monnaie est SUPPRIMEE — redondante depuis la consolidation pays :
# POST /pays/{iso}/pousser cree la devise sur config-service depuis NOTRE
# fiche quand elle y manque (GET-avant-POST, jamais un doublon). Les 34
# devises du Loader viennent des imports backend, comme les pays.


# ---------------------------------------------------------------------------
# Regions et quartiers — SANS AUCUNE LIMITE DE NOMBRE (decision Yaniv 14/08)
# ---------------------------------------------------------------------------
# La regle est celle qu'il a posee : « le nombre que l'on veut, pas de
# barrieres fixes — juste la consistance et la non-duplication. » Les seuls
# refus possibles sont donc des INVARIANTS : parent inexistant (EF-02), nom
# vide, doublon. Jamais un plafond.
#
# ET LE LOADER SAIT QUOI ENVOYER : la VILLE part a config-service (il connait
# Country.cities[]) ; la REGION et le QUARTIER restent CHEZ NOUS — le systeme
# n'a aucun champ pour eux (mesure : CreateDepositaireSchema ne porte aucune
# geographie, le `region` de config-service est la region CONTINENTALE).
# Les envoyer serait inventer un contrat qui n'existe pas.


class RegionDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ISO 3166-1 alpha-2 STRICT — majuscules au contrat, comme US-B6.
    #: Accepter `cm` puis corriger en silence serait une tolerance, pas un
    #: format ; le 422 dit la regle, l'ecran l'applique.
    pays: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")
    nom: str = Field(min_length=1, max_length=80)
    capitale: str = Field(default="", max_length=80)
    population: int | None = Field(default=None, ge=1)


@router.post("/regions", status_code=201)
async def ajouter_region(
    demande: RegionDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """L'ajout d'une region — invariants seulement, jamais de plafond.

    Meme rite que la ville : valider chez nous, persister, RELIRE de la base.
    `config_service.envoye = False` est DIT avec sa raison — un champ absent
    serait un silence, et le silence est le defaut qu'on ne commet pas."""
    await refuser_si_run_en_cours()

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        region = surcouche.ajouter_region(
            _geo(),
            pays=demande.pays,
            nom=demande.nom,
            capitale=demande.capitale,
            population=demande.population,
        )
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus

    meta = await depot.enregistrer(surcouche, par=session.email)
    relue, _ = await depot.charger()
    fiche = relue.regions[region.region_id]
    return {
        "config_service": {
            "envoye": False,
            "raison": (
                "config-service n'a aucune notion de region administrative — "
                "son champ `region` est la region CONTINENTALE ; la region vit "
                "chez nous (anti-corruption), seules les VILLES partent la-bas"
            ),
        },
        "region": {
            "id": fiche.region_id,
            "nom": fiche.name,
            "pays": fiche.country_iso2,
            "capitale": fiche.capitale,
            "population": fiche.population,
        },
        "surcouche": {"resume": relue.resume(), "version": meta["version"]},
    }


class QuartierDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city_id: str = Field(min_length=1)
    nom: str = Field(min_length=1, max_length=80)
    zone_type: str = Field(default="residential", max_length=30)
    population: int | None = Field(default=None, ge=1)


@router.post("/quartiers", status_code=201)
async def ajouter_quartier(
    demande: QuartierDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """L'ajout d'un quartier — c'est de la CAPACITE : le quartier porte un
    Kiosque, et l'index unique `(run_id, district_id)` n'en admet qu'un par
    quartier (D-03). Plus de quartiers = plus de Kiosques possibles.
    Invariants seulement (ville parente, non-duplication) — aucun plafond."""
    await refuser_si_run_en_cours()

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    try:
        quartier = surcouche.ajouter_quartier(
            _geo(),
            city_id=demande.city_id.strip(),
            nom=demande.nom,
            zone_type=demande.zone_type,
            population=demande.population,
        )
    except AjoutRefuse as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus

    meta = await depot.enregistrer(surcouche, par=session.email)
    relue, _ = await depot.charger()
    fiche = relue.quartiers[quartier.district_id]
    return {
        "config_service": {
            "envoye": False,
            "raison": (
                "le quartier n'existe dans AUCUN contrat serveur (mesure : "
                "CreateDepositaireSchema ne porte aucune geographie) — il vit "
                "chez nous, c'est lui qui donne son adresse au Kiosque"
            ),
        },
        "quartier": {
            "id": fiche.district_id,
            "nom": fiche.name,
            "ville": fiche.city_id,
            "zone_type": fiche.zone_type,
            "population": fiche.population,
        },
        "surcouche": {"resume": relue.resume(), "version": meta["version"]},
    }


# ---------------------------------------------------------------------------
# Permissions — la LECTURE depuis l'ecran (decision Yaniv 14/08)
# ---------------------------------------------------------------------------


def _client_users() -> Any:
    """Fabrique du client user-service — doublee dans les tests."""
    from app.clients.user_service import UserServiceClient

    return UserServiceClient()


@router.get("/permissions")
async def permissions(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les permissions RELUES de user-service, telles que l'ecran de creation
    de groupe doit les proposer. Les 22 `LENDER_*` (sprint 5, hors perimetre
    D-07) et la parasite RC169 sont ecartees par le client — dit ici pour que
    l'ecran n'aille pas les chercher ailleurs."""
    client = _client_users()
    try:
        noms = await client.lister_permissions()
    finally:
        await client.fermer()
    return {
        "permissions": noms,
        "compte": len(noms),
        "note": "les 22 LENDER_* et RC169_* sont ecartees (D-07) — hors perimetre v1",
    }


# ---------------------------------------------------------------------------
# ETATS sur le referentiel PARTAGE (16/08, demande Yaniv) — telcos et devises
# TELS QUE config-service les porte, avec activation/desactivation REELLE
# la-bas. Deux verites toujours dites : (1) c'est le referentiel de TOUTES
# les equipes ; (2) la garde des references inverses est le SEUL garde-fou
# existant (la relation est unidirectionnelle cote serveur — mesure 09/08).
# ---------------------------------------------------------------------------


class EtatRessourceDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actif: bool
    motif: str = Field(min_length=3, max_length=200)


async def _porteurs_par_ressource(lecture: Any, famille: str) -> dict[str, list[str]]:
    """{ressource_id: [codes pays]} en UNE passe sur les pays — jamais un
    scan par ressource."""
    porteurs: dict[str, list[str]] = {}
    for fiche in await lecture.lister_pays():
        code = str(fiche.get("iso_name", "?"))
        for element in fiche.get(famille) or []:
            identifiant = (
                str(element.get("_id") or element.get("id"))
                if isinstance(element, dict)
                else str(element)
            )
            porteurs.setdefault(identifiant, []).append(code)
    return porteurs


def _references(element_liste: Any) -> list[str]:
    """Les identifiants d'une liste de references — dicts ou chaines nues.

    config-service rend tantot `["<uuid>"]`, tantot `[{"_id": "<uuid>"}]`
    selon la route : une seule lecture pour les deux formes.
    """
    identifiants = []
    for element in element_liste or []:
        if isinstance(element, dict):
            identifiants.append(str(element.get("_id") or element.get("id") or ""))
        else:
            identifiants.append(str(element))
    return [i for i in identifiants if i]


@router.get("/pays-config")
async def pays_config(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les pays TELS QUE config-service les porte — la RELECTURE qui manquait.

    Le pendant de `/telcos-config` et `/devises-config`, ecrit le 23/08 apres
    une campagne QA sur la prod : on pouvait POUSSER un pays (`US-B6`) sans
    jamais pouvoir RELIRE ce qui avait atterri la-bas. Un aller sans retour
    n'est pas verifiable — donc pas livrable.

    Pour chaque pays present sur la plateforme : ses 9 champs, ses villes,
    sa devise et ses operateurs RESOLUS PAR NOM (jamais des UUID nus), et
    les ECARTS mesures contre notre fiche :

    * `champs_vides`    — un champ du contrat rendu vide la-bas ;
    * `villes_absentes` — villes du Loader qui ne sont PAS la-bas ;
    * `villes_fantomes` — chaines vides ou doublons dans `cities[]` ;
    * `telcos_absents`  — operateurs du Loader non rattaches la-bas ;
    * `devise`          — celle portee la-bas contre celle de notre fiche ;
    * `hors_loader`     — pays present la-bas et inconnu de nous (le 4e etat).

    Aucune ecriture : c'est l'oeil, pas la main.
    """
    return await _mesurer_pays_config()


async def _mesurer_pays_config() -> dict[str, Any]:
    """La mesure brute, partagee par `/pays-config`, `/coherence` et
    `/synchroniser` — une seule verite, calculee a un seul endroit."""
    from app.clients.config_service import cle_comparaison

    lecture = _config_lecture()
    try:
        distants = await lecture.lister_pays()
        noms_telcos = {
            str(t.get("_id") or t.get("id")): str(
                t.get("network_name") or t.get("name") or ""
            )
            for t in await lecture.lister_telcos()
        }
        iso_devises = {
            str(d.get("_id") or d.get("id")): str(d.get("iso_name") or "")
            for d in await lecture.lister_devises()
        }
    except Exception as erreur:
        raise _relayer(erreur) from erreur
    finally:
        await lecture.fermer()

    surcouche, _meta = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())

    lignes: list[dict[str, Any]] = []
    for distant in distants:
        code = str(distant.get("iso_name") or "").strip().upper()
        brutes = [str(v) for v in (distant.get("cities") or [])]
        villes_labas = [v.strip() for v in brutes if v.strip()]
        telcos_labas = [
            noms_telcos.get(i, f"(inconnu {i[:8]})") for i in _references(distant.get("telcos"))
        ]
        devises_labas = [
            iso_devises.get(i, f"(inconnue {i[:8]})")
            for i in _references(distant.get("currencies"))
        ]

        fiche = referentiel.pays(code) if code else None
        villes_ici = sorted(
            v.name for v in referentiel.villes.values() if v.country_iso2 == code
        )
        telcos_ici = [t.network_name for t in referentiel.telcos_du_pays(code)]

        champs_vides = [
            champ
            for champ in ("name_en", "name_fr", "iso_name", "dial_code", "region", "continent")
            if not str(distant.get(champ) or "").strip()
        ]
        fantomes = len(brutes) - len(villes_labas)
        doublons = len(villes_labas) - len({cle_comparaison(v) for v in villes_labas})
        lignes.append(
            {
                "iso2": code,
                "id": str(distant.get("_id") or distant.get("id") or ""),
                "connu_du_loader": fiche is not None,
                "champs": {
                    champ: distant.get(champ)
                    for champ in (
                        "name_en",
                        "name_fr",
                        "iso_name",
                        "dial_code",
                        "region",
                        "continent",
                        "is_active",
                    )
                },
                "villes": {"compte_la_bas": len(villes_labas), "compte_loader": len(villes_ici)},
                "devises": devises_labas,
                "telcos": sorted(telcos_labas),
                "ecarts": {
                    "champs_vides": champs_vides,
                    "villes_absentes": sorted(
                        nom
                        for nom in villes_ici
                        if cle_comparaison(nom)
                        not in {cle_comparaison(v) for v in villes_labas}
                    ),
                    "villes_fantomes": fantomes + doublons,
                    "telcos_absents": sorted(set(telcos_ici) - set(telcos_labas)),
                    "devise_attendue": fiche.devise_iso if fiche else None,
                    "devise_portee": devises_labas,
                    "hors_loader": fiche is None,
                },
            }
        )

    complets = [
        ligne
        for ligne in lignes
        if not any(
            [
                ligne["ecarts"]["champs_vides"],
                ligne["ecarts"]["villes_absentes"],
                ligne["ecarts"]["villes_fantomes"],
                ligne["ecarts"]["telcos_absents"],
                ligne["ecarts"]["hors_loader"],
            ]
        )
    ]
    return {
        "pays": sorted(lignes, key=lambda ligne: str(ligne["iso2"])),
        "compte": len(lignes),
        "sans_ecart": len(complets),
        "note": (
            "la RELECTURE de l'aller US-B6 : ce que la plateforme porte "
            "vraiment, resolu par nom. Un ecart n'est pas forcement une "
            "faute — regions, quartiers, GPS, TVA et parts de marche n'ont "
            "AUCUN champ la-bas et restent la richesse du Loader"
        ),
    }


@router.get("/coherence")
async def coherence_referentiel(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`C4` — le VERDICT : le Loader et la plateforme disent-ils la meme chose ?

    `/pays-config` montre les ecarts a qui va les lire. Ce n'est pas suffisant :
    c'est ainsi que 361 villes manquantes sont restees invisibles dix jours,
    alors qu'un run REAL aurait plante sur la premiere ville inconnue. Une
    derive qui attend qu'on ouvre un ecran n'est pas surveillee.

    Cette route rend donc un VERDICT, pas une liste :

    * `coherent` — rien a faire ;
    * `derive`   — reparable par le geste normal : il MANQUE des villes ou des
      telcos la-bas. `POST /referentiels/synchroniser` ferme l'ecart ;
    * `anomalie` — quelque chose ne se repare pas tout seul : un pays hors
      Loader, des champs vides, des villes fantomes, une devise divergente.
      Cela demande une DECISION (rectifier, ou assumer).

    Le pire verdict l'emporte : un systeme qui annonce « coherent » avec une
    anomalie en cours ment plus qu'il n'informe.
    """
    mesure = await _mesurer_pays_config()
    derives: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for ligne in mesure["pays"]:
        ecarts = ligne["ecarts"]
        motifs_anomalie = []
        if ecarts["hors_loader"]:
            motifs_anomalie.append("pays inconnu du Loader")
        if ecarts["champs_vides"]:
            motifs_anomalie.append(f"champs vides : {', '.join(ecarts['champs_vides'])}")
        if ecarts["villes_fantomes"]:
            motifs_anomalie.append(f"{ecarts['villes_fantomes']} ville(s) fantome(s)")
        attendue = ecarts["devise_attendue"]
        if attendue and attendue not in ecarts["devise_portee"]:
            motifs_anomalie.append(
                f"devise {attendue} attendue, {ecarts['devise_portee']} portee(s)"
            )
        motifs_derive = []
        if ecarts["villes_absentes"]:
            motifs_derive.append(f"{len(ecarts['villes_absentes'])} ville(s) manquante(s)")
        if ecarts["telcos_absents"]:
            motifs_derive.append(
                f"telco(s) non rattache(s) : {', '.join(ecarts['telcos_absents'])}"
            )

        if motifs_anomalie:
            anomalies.append({"iso2": ligne["iso2"], "motifs": motifs_anomalie})
        if motifs_derive:
            derives.append({"iso2": ligne["iso2"], "motifs": motifs_derive})

    verdict = "anomalie" if anomalies else ("derive" if derives else "coherent")
    return {
        "verdict": verdict,
        "pays_mesures": mesure["compte"],
        "pays_sans_ecart": mesure["sans_ecart"],
        "derive": derives,
        "anomalies": anomalies,
        "geste": {
            "coherent": "rien a faire",
            "derive": "POST /admin/referentiels/synchroniser ferme l'ecart (idempotent)",
            "anomalie": (
                "POST /admin/referentiels/pays/{iso}/rectifier — apercu d'abord ; "
                "une anomalie demande une decision, pas un automatisme"
            ),
        }[verdict],
    }


class SynchronisationDemande(BaseModel):
    """`C5` — la synchronisation se confirme, comme la rectification."""

    model_config = ConfigDict(extra="forbid")

    confirmer: bool = False


@router.post("/synchroniser")
async def synchroniser_les_pays_en_operation(
    demande: SynchronisationDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """`C5` — fermer la derive de TOUS les pays en operation, d'un geste.

    `pousser` repare deja un pays : il complete les villes manquantes et
    rattache les telcos absents, sans jamais doubler. Mais il fallait le
    lancer pays par pays — donc y penser, donc l'oublier. Ici la boucle est
    faite, **uniquement sur les pays EN OPERATION** (`I-CFG-SYNC` : un pays
    hors operation n'a rien a synchroniser, sa matiere l'attend).

    Apercu par defaut : la liste de ce qui SERA envoye. Rien ne part sans
    `confirmer: true`. Un pays qui refuse n'interrompt pas les autres.
    """
    await refuser_si_run_en_cours()

    mesure = await _mesurer_pays_config()
    a_faire = [
        {
            "iso2": ligne["iso2"],
            "villes_manquantes": len(ligne["ecarts"]["villes_absentes"]),
            "telcos_absents": ligne["ecarts"]["telcos_absents"],
        }
        for ligne in mesure["pays"]
        if not ligne["ecarts"]["hors_loader"]
        and (ligne["ecarts"]["villes_absentes"] or ligne["ecarts"]["telcos_absents"])
    ]

    if not demande.confirmer:
        return {
            "statut": "apercu",
            "a_synchroniser": a_faire,
            "compte": len(a_faire),
            "note": (
                "AUCUNE ecriture. Relancer avec `confirmer: true`. Seuls les "
                "pays EN OPERATION sont concernes — la matiere d'un pays qui "
                "n'y est pas partira ENTIERE a sa mise en operation."
            ),
        }

    rapport: list[dict[str, Any]] = []
    for cible in a_faire:
        try:
            resultat = await pousser_pays_en_operation(str(cible["iso2"]), session)
            rapport.append(
                {
                    "iso2": cible["iso2"],
                    "statut": resultat["statut"],
                    "villes_envoyees": resultat["villes_envoyees"],
                    "telcos": [t["nom"] for t in resultat["telcos"] if t["rattache"]],
                    "echecs": resultat["echecs"],
                }
            )
        except HTTPException as refus:
            # Un pays qui refuse n'interrompt pas les autres — et son refus
            # est rendu tel quel, jamais avale.
            rapport.append(
                {
                    "iso2": cible["iso2"],
                    "statut": f"refuse ({refus.status_code})",
                    "detail": str(refus.detail)[:300],
                }
            )

    return {
        "statut": "synchronise",
        "rapport": rapport,
        "compte": len(rapport),
        "note": (
            "idempotent : relancer ne double rien. Ce qui reste apres ce geste "
            "est une ANOMALIE (voir GET /coherence), pas une derive"
        ),
    }


@router.get("/telcos-config")
async def telcos_config(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les operateurs TELS QUE config-service les porte — id, etat, et les
    pays qui les referencent (la matiere de la garde)."""
    lecture = _config_lecture()
    try:
        telcos = await lecture.lister_telcos()
        porteurs = await _porteurs_par_ressource(lecture, "telcos")
    except Exception as erreur:  # la panne de la plateforme est DITE
        raise _relayer(erreur) from erreur
    finally:
        await lecture.fermer()
    lignes = [
        {
            "id": str(t.get("_id") or t.get("id")),
            "nom": str(t.get("network_name") or t.get("name") or ""),
            "code": str(t.get("short_name") or ""),
            "actif": t.get("is_active"),
            "porteurs": porteurs.get(str(t.get("_id") or t.get("id")), []),
        }
        for t in telcos
    ]
    return {
        "telcos": sorted(lignes, key=lambda ligne: str(ligne["nom"])),
        "compte": len(lignes),
        "note": (
            "referentiel PARTAGE (toutes les equipes) — desactiver passe par la "
            "garde des references inverses ; la GENERATION du Loader suit le "
            "classeur+surcouche (INV-18), pas cet etat : deux choses, deux verites"
        ),
    }


@router.patch("/telcos-config/{telco_id}/etat")
async def changer_etat_telco(
    telco_id: Annotated[str, Path(min_length=1, max_length=64)],
    demande: EtatRessourceDemande,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """Active/desactive un operateur LA-BAS — la garde parle avant le reseau.

    Desactivation : refusee (409, message MESURE de la garde) si un AUTRE
    pays reference encore l'operateur — sans ce controle, desactiver les
    telcos du pays parasite `ca` casserait la Cote d'Ivoire (09/08).
    Activation : aucun risque, aucune garde. Write-ahead + RELECTURE.
    """
    from app.clients.config_service import ReferenceInverse
    from app.repositories.audit_trail import AuditTrailRepository
    from app.routes.admin_entites import RUN_ADMIN
    from app.services.inventaire import uuid_stable

    await refuser_si_run_en_cours()

    lecture = _config_lecture()
    admin = _config_admin()
    try:
        telcos = {str(t.get("_id") or t.get("id")): t for t in await lecture.lister_telcos()}
        cible = telcos.get(str(telco_id))
        if cible is None:
            raise HTTPException(
                status_code=404, detail=f"operateur {telco_id} inconnu de config-service"
            )
        nom = str(cible.get("network_name") or cible.get("name") or "")
        porteurs = (await _porteurs_par_ressource(lecture, "telcos")).get(str(telco_id), [])

        audit = AuditTrailRepository()
        async with audit.intention(
            RUN_ADMIN,
            entity_type="Telco",
            entity_id=uuid_stable(telco_id),
            operation="UPDATE",
            cible="config-service PATCH /telcos/(de)activate",
            payload={
                "name": nom,
                "actif": demande.actif,
                "motif": demande.motif,
                "par": session.email,
            },
        ) as suivi:
            try:
                if demande.actif:
                    await admin.activer_telco(telco_id)
                else:
                    await admin.desactiver_telco(
                        telco_id, pays_attendu=porteurs[0] if porteurs else ""
                    )
            except ReferenceInverse as garde:
                suivi.echoue("ReferenceInverse")
                raise HTTPException(status_code=409, detail=str(garde)) from garde
            except Exception as erreur:
                suivi.echoue(type(erreur).__name__)
                raise HTTPException(
                    status_code=502,
                    detail=f"config-service a refuse : {type(erreur).__name__}",
                ) from erreur
            suivi.reussi({"telco_id": str(telco_id), "actif": demande.actif})

        # RELECTURE — l'etat d'APRES.
        relu = next(
            (
                t
                for t in await lecture.lister_telcos()
                if str(t.get("_id") or t.get("id")) == str(telco_id)
            ),
            None,
        )
        etat_relu = relu.get("is_active") if relu else None
        if isinstance(etat_relu, bool) and etat_relu is not demande.actif:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"l'etat de {nom!r} n'a PAS change a la relecture — le "
                    "serveur a repondu sans agir (l'ANO-CFG-LIFECYCLE de juin "
                    "portait exactement cette signature)"
                ),
            )
    finally:
        await lecture.fermer()
        await admin.fermer()

    return {
        "id": str(telco_id),
        "nom": nom,
        "actif": demande.actif,
        "etat_relu": etat_relu,
        "porteurs": porteurs,
        "note": (
            "referentiel PARTAGE modifie — visible par toutes les equipes. La "
            "generation du Loader (INV-18) suit le classeur+surcouche : exclure "
            "cet operateur des tirages est un GESTE SEPARE, arbitrage a "
            "trancher (il modifie les parts de marche du CDC)"
        ),
    }


@router.patch("/devises-config/{devise_id}/etat")
async def changer_etat_devise(
    devise_id: Annotated[str, Path(min_length=1, max_length=64)],
    demande: EtatRessourceDemande,
    _: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """La desactivation d'une devise est TOUJOURS refusee — par MESURE.

    100 % des devises sont partagees (09/08) : XOF porte le Senegal, le
    Burkina et la Cote d'Ivoire ; XAF le Cameroun. Il n'existe AUCUN cas ou
    desactiver une devise ne casse pas au moins un pays. La route existe
    pour que le refus soit EXPLICITE et porte sa preuve — jamais un bouton
    absent sans explication.
    """
    from app.clients.config_service import ReferenceInverse

    if demande.actif:
        raise HTTPException(
            status_code=422,
            detail=(
                "aucun contrat d'ACTIVATION de devise n'a ete mesure sur "
                "config-service — seul le refus de desactivation est etabli"
            ),
        )
    admin = _config_admin()
    try:
        await admin.desactiver_devise(devise_id)
    except ReferenceInverse as garde:
        raise HTTPException(status_code=409, detail=str(garde)) from garde
    finally:
        await admin.fermer()
    # desactiver_devise leve TOUJOURS — arriver ici signifierait que la
    # mesure du 09/08 n'est plus vraie : on le dirait plutot que le cacher.
    return {  # pragma: no cover
        "id": str(devise_id),
        "note": "desactivation ACCEPTEE — la mesure du 09/08 est PERIMEE, a re-auditer",
    }


@router.get("/devises-config")
async def devises_config(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les devises TELLES QUE config-service les porte — avec leurs PORTEURS.

    La matiere du refus : 100 % des devises sont partagees (mesure 09/08),
    c'est pour CA que la desactivation est toujours refusee — l'ecran montre
    les porteurs, le refus se comprend d'un regard."""
    lecture = _config_lecture()
    try:
        devises = await lecture.lister_devises()
        porteurs = await _porteurs_par_ressource(lecture, "currencies")
    except Exception as erreur:
        raise _relayer(erreur) from erreur
    finally:
        await lecture.fermer()
    lignes = [
        {
            "id": str(d.get("_id") or d.get("id")),
            "iso": str(d.get("iso_name") or ""),
            "nom": str(d.get("name_fr") or d.get("name_en") or ""),
            "actif": d.get("is_active"),
            "porteurs": porteurs.get(str(d.get("_id") or d.get("id")), []),
        }
        for d in devises
    ]
    return {
        "devises": sorted(lignes, key=lambda ligne: str(ligne["iso"])),
        "compte": len(lignes),
        "note": (
            "100 % des devises sont PARTAGEES (mesure 09/08) — la desactivation "
            "est toujours refusee, et le refus porte sa preuve"
        ),
    }
