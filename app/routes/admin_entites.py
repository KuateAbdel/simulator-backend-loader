"""
app/routes/admin_entites.py
===========================
Lot D — les entites a l'UNITE : `US-D2` (produit COLLECT) et `US-D1`
(Company). Chacune reutilise le moteur des runs — le catalogue pour l'une,
la sequence S3-03 (`creer_company`) pour l'autre — jamais une copie.

LA STORY, TELLE QUE YANIV L'A PRECISEE LE 13/08 :
  - COLLECT seulement — LENDING est 422, structurellement (sprint 8) ;
  - TROIS interfaces, une par policy_type : la combinaison invalide est
    refusee avec sa regle nommee, jamais devinee ;
  - le Loader est L'AUTORITE D'UNICITE (product-service n'en a aucune —
    ANO-PRD-UNIQ-01) : deux cles, name ET short_name, registre interne ET
    GET-avant-POST ;
  - valide chez nous PUIS pousse, et la fiche rendue est RELUE (FRA-218).

LE RITE EN DEUX TEMPS (D-01) :
  POST /admin/entites/produits/apercu   -> le payload EXACT qui partirait,
                                           AUCUN appel d'ecriture
  POST /admin/entites/produits          -> memes champs, re-valides a
                                           l'identique, puis POST + relecture

JOURNALISATION : les actions d'admin hors-run s'inscrivent au journal
d'intention sous le run sentinelle `RUN_ADMIN` (UUID nul) — le write-ahead
vaut pour une ecriture a l'unite autant que pour 2000.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.clients.base import ErreurService
from app.clients.contracts import PolicyMeasure, PolicyType, ProductCategory, ProductType
from app.core.cdc import TAUX_USURE_MAX_ANNUEL_PCT
from app.core.database import COLLECTION_LOADER_CONFIGURATION, get_collection
from app.repositories.audit_trail import AuditTrailRepository
from app.routes.dependances import (
    SessionAdmin,
    admin_complet,
    refuser_si_run_en_cours,
)
from app.services.catalogue import (
    CATALOGUE_COLLECT,
    PRODUITS_ENVIRONNEMENT,
    ProduitCollecte,
    policy_collect,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/entites", tags=["admin — entites"])

#: Le run SENTINELLE des actions d'administration hors-run. UUID nul,
#: reconnaissable au premier regard dans le journal — jamais confondable avec
#: un vrai run.
RUN_ADMIN = UUID(int=0)

_ID_REGISTRE = "produits_admin"


class ProduitDemande(BaseModel):
    """`US-D2` — le formulaire. `extra="forbid"` : `type=LENDING`, un champ
    inconnu, tout ce qui n'est pas declare ici est un 422."""

    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=3, max_length=80)
    #: Le code court du marqueur — DEMO_<code> part dans short_name (CR-07).
    code: str = Field(min_length=2, max_length=24, pattern=r"^[A-Z0-9_]+$")
    policy_type: Literal["CASH", "CASH_DAT", "PRODUCT"]
    categorie: Literal["INDIVIDUAL", "CORPORATE"]
    montant_min: float = Field(gt=0)
    montant_max: float = Field(gt=0)
    taux: float = Field(default=0.0, ge=0, le=TAUX_USURE_MAX_ANNUEL_PCT)
    #: CASH_DAT seulement — OBLIGATOIRE la, INTERDIT ailleurs.
    duree_mois: int | None = Field(default=None, ge=1, le=120)
    #: PRODUCT seulement — le coeur du formulaire de collecte en nature.
    measure: Literal["KILOGRAM", "LITER"] | None = None
    measure_price: float | None = Field(default=None, ge=0)


def _composer(demande: ProduitDemande) -> tuple[ProduitCollecte, dict[str, Any]]:
    """Valide la COMBINAISON (les trois interfaces) et compose le payload
    exact. Chaque refus porte sa regle nommee — jamais un rejet muet."""
    fautes: list[str] = []
    if demande.montant_min >= demande.montant_max:
        fautes.append(
            f"montant_min={demande.montant_min} >= montant_max={demande.montant_max} "
            "— attendu 0 < min < max (la plateforme accepte min=max=3, PAS NOUS)"
        )
    if demande.policy_type == "CASH_DAT" and demande.duree_mois is None:
        fautes.append(
            "duree_mois absent — un depot a terme SANS terme n'est pas un depot a "
            "terme. Le serveur ne porte pas la duree : c'est le Loader qui la garde "
            "et la materialise dans CollectSchema.end_date"
        )
    if demande.policy_type != "CASH_DAT" and demande.duree_mois is not None:
        fautes.append(
            f"duree_mois={demande.duree_mois} sur {demande.policy_type} — une "
            "cotisation reguliere ou une collecte en nature n'expire pas (422)"
        )
    if demande.policy_type == "PRODUCT" and demande.measure is None:
        fautes.append(
            "measure absente — la mesure est un choix METIER (D-PRD-8) : le mil se "
            "pese (KILOGRAM), le lait se mesure (LITER). Jamais un defaut"
        )
    if demande.policy_type != "PRODUCT" and demande.measure is not None:
        fautes.append(
            f"measure={demande.measure} sur {demande.policy_type} — la mesure "
            "n'a de sens qu'en collecte en nature (PRODUCT) ; elle est emise "
            "neutre ailleurs, jamais saisie"
        )
    nom = demande.nom.strip()
    if nom in PRODUITS_ENVIRONNEMENT:
        fautes.append(
            f"{nom!r} est un produit de l'ENVIRONNEMENT partage — constate, jamais "
            "consomme ni recree (decision du 12/08)"
        )
    for produit in CATALOGUE_COLLECT:
        if produit.nom == nom or produit.code == demande.code:
            fautes.append(
                f"{nom!r}/{demande.code!r} entre en collision avec le produit du "
                f"catalogue {produit.nom!r} ({produit.code}) — l'unicite est la "
                "NOTRE (ANO-PRD-UNIQ-01 : le serveur n'en a aucune)"
            )
            break
    if fautes:
        raise HTTPException(status_code=422, detail=fautes)

    try:
        produit = ProduitCollecte(
            nom,
            PolicyType(demande.policy_type),
            ProductCategory(demande.categorie),
            PolicyMeasure(demande.measure or "KILOGRAM"),
            demande.montant_min,
            demande.montant_max,
            demande.taux,
            duree_mois=demande.duree_mois,
            code=demande.code,
        )
    except ValueError as erreur:
        raise HTTPException(status_code=422, detail=[str(erreur)]) from erreur

    policy = policy_collect(produit)
    if demande.measure_price is not None:
        policy["measure_price"] = demande.measure_price
    payload = {
        "type": ProductType.COLLECT.value,
        "name": produit.nom_recherche,
        "short_name": produit.marqueur,
        "category": produit.categorie.value,
        "segment": "ANY",
        "description": (
            f"Jeu de donnees DEMO Loader FinZuu — produit de collecte {produit.nom}"
        ),
        "policy": policy,
        "subscription_fees": 0.0,
    }
    return produit, payload


async def _registre_contient(nom: str, code: str) -> dict[str, Any] | None:
    document = await get_collection(COLLECTION_LOADER_CONFIGURATION).find_one(
        {"_id": _ID_REGISTRE}
    )
    for entree in (document or {}).get("produits", []):
        if entree.get("name") == nom or entree.get("code") == code:
            return dict(entree)
    return None


def _client_produits() -> Any:
    """Fabrique du client product-service — doublee dans les tests."""
    from app.clients.product_service import ProductServiceClient

    return ProductServiceClient()


@router.post("/produits/apercu")
async def apercu_produit(
    demande: ProduitDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-D2` etape 1 — le payload EXACT qui partirait, policy embarquee
    comprise. AUCUN appel d'ecriture ne part d'ici."""
    produit, payload = _composer(demande)
    deja = await _registre_contient(produit.nom, produit.code)
    if deja is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{produit.nom!r}/{produit.code!r} existe deja dans NOTRE registre "
                f"(cree par {deja.get('cree_par')}, product_id={deja.get('product_id')})"
            ),
        )
    return {
        "payload": payload,
        "marqueur": produit.marqueur,
        "duree_mois": produit.duree_mois,
        "note": (
            "apercu seulement — aucune ecriture n'est partie. Confirmer via "
            "POST /admin/entites/produits avec les MEMES champs."
        ),
    }


@router.post("/produits", status_code=201)
async def creer_produit(
    demande: ProduitDemande,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-D2` etape 2 — la creation, avec le protocole a deux cles.

    Ordre exact : verrou EF-55 -> composition (les memes refus que l'apercu)
    -> registre interne -> GET-avant-POST par short_name PUIS par name ->
    intention write-ahead -> POST -> RELECTURE -> registre mis a jour.
    """
    await refuser_si_run_en_cours()
    produit, payload = _composer(demande)

    deja = await _registre_contient(produit.nom, produit.code)
    if deja is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{produit.nom!r} existe deja dans notre registre",
        )

    client = _client_produits()
    try:
        # PREMIERE CLE — notre marqueur : deja present = deja cree (409, pas
        # une re-creation silencieuse).
        existant = await client.chercher_par_short_name(produit.marqueur)
        if existant is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"le marqueur {produit.marqueur!r} existe deja sur la plateforme "
                    f"(_id={existant.get('_id')}) — produit deja cree"
                ),
            )
        # SECONDE CLE — le nom : occupe par un ETRANGER = refus avant POST.
        homonyme = await client.chercher_par_nom(produit.nom)
        if homonyme is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"nom {produit.nom!r} deja porte par un produit etranger "
                    f"(_id={homonyme.get('_id')}, short_name="
                    f"{homonyme.get('short_name')!r}) — ni consomme (A-10), ni "
                    "double (D-12/ANO-PRD-UNIQ-01)"
                ),
            )

        audit = AuditTrailRepository()
        async with audit.intention(
            RUN_ADMIN,
            entity_type="Product",
            entity_id=UUID(int=abs(hash(produit.marqueur)) % (2**63)),
            operation="CREATE",
            cible="product-service",
            payload={"name": produit.nom, "short_name": produit.marqueur},
        ) as suivi:
            try:
                reponse = await client.creer_produit(payload)
            except ErreurService as erreur:
                suivi.echoue(f"HTTP {erreur.status}")
                raise HTTPException(
                    status_code=502,
                    detail=f"product-service a refuse : HTTP {erreur.status}",
                ) from erreur
            identifiant = reponse.get("_id") or reponse.get("id")
            suivi.reussi({"product_id": str(identifiant)})

        # RELECTURE (FRA-218) — la fiche rendue vient de la plateforme.
        fiche = await client.chercher_par_short_name(produit.marqueur)
    finally:
        await client.fermer()

    await get_collection(COLLECTION_LOADER_CONFIGURATION).update_one(
        {"_id": _ID_REGISTRE},
        {
            "$push": {
                "produits": {
                    "name": produit.nom,
                    "code": produit.code,
                    "short_name": produit.marqueur,
                    "product_id": str(identifiant),
                    "cree_par": session.email,
                    "cree_le": datetime.now(tz=UTC).isoformat(),
                }
            }
        },
        upsert=True,
    )
    return {
        "product_id": str(identifiant),
        "fiche_relue": fiche,
        "marqueur": produit.marqueur,
        "note": "souscriptible au prochain run — Loader et plateforme coherents",
    }


# ---------------------------------------------------------------------------
# US-D1 — la Company a l'unite. La route DELEGUE a creer_company() : la
# sequence S3-03 (Company -> cascade owner -> Admin User) est l'unite deja
# couverte par les tests d'organisation ; ici on teste le CABLAGE.
# ---------------------------------------------------------------------------


class CompanyDemande(BaseModel):
    """`US-D1` — 3-4 champs saisis, ~40 composes par le Loader."""

    model_config = ConfigDict(extra="forbid")

    type_company: Literal["IMF", "BANK", "MERCHANT", "FONDATION"]
    pays: Literal["CM", "CI", "BF", "SN"]
    ville: str = Field(min_length=2, max_length=80)
    #: Raison sociale imposee — sinon le Loader la compose (patronyme reel +
    #: forme + secteur), exactement comme dans un run.
    nom: str | None = Field(default=None, min_length=3, max_length=80)


async def _resoudre_territoire(pays: str, ville: str) -> tuple[str, str, str | None]:
    """(region, ville, quartier|None) — depuis le referentiel FUSIONNE avec la
    surcouche : une ville ajoutee par US-B4 est immediatement utilisable ici.
    Refus pedagogique : la liste des villes du pays accompagne le 422."""
    from app.core.invariants import sans_accents
    from app.repositories.surcouche import SurcoucheRepository
    from app.routes.admin_referentiels import _geo

    surcouche, _ = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())
    cible = sans_accents(ville).strip().lower()
    for v in referentiel.villes.values():
        if v.country_iso2 == pays and sans_accents(v.name).strip().lower() == cible:
            region = referentiel.region(v.region_id)
            quartiers = referentiel.quartiers_de_ville(v.city_id)
            return (
                region.name if region else "",
                v.name,
                quartiers[0].name if quartiers else None,
            )
    disponibles = sorted(
        v.name for v in referentiel.villes.values() if v.country_iso2 == pays
    )
    raise HTTPException(
        status_code=422,
        detail=(
            f"ville {ville!r} inconnue pour {pays} (EF-02). Villes du "
            f"referentiel : {', '.join(disponibles)}"
        ),
    )


def _executeur_organisation(mode: Any) -> Any:
    """Fabrique de l'executeur Organisation — doublee dans les tests."""
    from datetime import date

    from app.clients.account_service import AccountServiceClient
    from app.clients.company_service import CompanyServiceClient
    from app.clients.user_service import UserServiceClient
    from app.repositories.lenders_registry import LendersRegistryRepository
    from app.routes.admin_referentiels import _geo, _statique
    from app.services.generateur import Generateur
    from app.services.organisation_execution import ExecuteurOrganisation

    return ExecuteurOrganisation(
        run_id=RUN_ADMIN,
        mode=mode,
        referentiel=_geo(),
        statique=_statique(),
        # Ancre sur le run SENTINELLE : la meme demande recompose la meme
        # Company — l'idempotence de CR-03, appliquee a l'unite.
        generateur=Generateur(RUN_ADMIN, reference=date.today()),
        company_client=CompanyServiceClient(),
        user_client=UserServiceClient(),
        account_client=AccountServiceClient(),
        registre_lenders=LendersRegistryRepository(),
        audit=AuditTrailRepository(),
    )


async def _composer_company(
    demande: CompanyDemande, mode: Any
) -> tuple[dict[str, Any] | None, Any]:
    """Le tronc commun apercu/confirmation — seule la valeur de `mode` change,
    et c'est creer_company() qui en tire les consequences (D-01)."""
    from app.clients.contracts import CompanyType
    from app.services.generateur import patronyme
    from app.services.organisation_execution import (
        FORME_PAR_TYPE,
        SECTEURS_PAR_TYPE,
        RapportOrganisation,
    )

    region, ville, quartier = await _resoudre_territoire(demande.pays, demande.ville)
    type_company = CompanyType[demande.type_company]
    est_imf = type_company is CompanyType.IMF
    secteur = "MicroFinance" if est_imf else SECTEURS_PAR_TYPE[type_company][0]
    # Ancre stable INTER-PROCESSUS : sha256, jamais hash() — le hachage des
    # chaines est randomise par processus en Python, et l'ancre doit survivre
    # a un redemarrage (la meme lecon que _graine_faker, CR-03).
    from hashlib import sha256

    empreinte = f"{demande.pays}:{demande.ville}:{demande.type_company}:{demande.nom}"
    ancre = int(sha256(empreinte.encode()).hexdigest()[:8], 16)

    executeur = _executeur_organisation(mode)
    rapport = RapportOrganisation(mode=mode)
    fiche = await executeur.creer_company(
        pays=demande.pays,
        patronyme=patronyme(demande.pays, ancre),
        forme_juridique=FORME_PAR_TYPE[type_company],
        secteur=secteur,
        type_company=type_company,
        region=region,
        ville=ville,
        quartier=quartier,
        telephone=executeur._telephone_du_pays(demande.pays, ancre % 90),
        rapport=rapport,
        est_imf=est_imf,
        raison_imposee=demande.nom,
    )
    return fiche, rapport


@router.post("/companies/apercu")
async def apercu_company(
    demande: CompanyDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-D1` etape 1 — la fiche COMPLETE composee, sans aucune ecriture :
    `creer_company()` en DRY_RUN valide tout et n'emet rien."""
    from app.models.enums import RunMode

    fiche, rapport = await _composer_company(demande, RunMode.DRY_RUN)
    return {
        "fiche": fiche,
        "admin_annonce": rapport.admins_crees[0] if rapport.admins_crees else None,
        "note": (
            "apercu seulement — aucune ecriture n'est partie. Confirmer via "
            "POST /admin/entites/companies avec les MEMES champs."
        ),
    }


@router.post("/companies", status_code=201)
async def creer_company_unite(
    demande: CompanyDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-D1` etape 2 — la sequence S3-03 reelle : Company (GET-avant-POST
    par short_name, INV-CPY-01), cascade owner verifiee (D-CMP-2), Admin User
    en 3 requetes. La fiche rendue est celle du SERVEUR (FRA-227/218)."""
    from app.models.enums import RunMode

    await refuser_si_run_en_cours()
    fiche, rapport = await _composer_company(demande, RunMode.REAL)
    if fiche is None:
        motif = (
            rapport.companies_echouees[-1][1]
            if rapport.companies_echouees
            else "echec sans motif rapporte"
        )
        raise HTTPException(status_code=502, detail=f"creation refusee : {motif}")
    return {
        "fiche": fiche,
        "admins_crees": rapport.admins_crees,
        "cascade_owner_verifiee": rapport.cascades_identity_verifiees == 1,
        "note": "sequence S3-03 executee — fiche relue du serveur",
    }
