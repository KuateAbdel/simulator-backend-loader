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
from uuid import NAMESPACE_OID, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.clients.base import ErreurService
from app.clients.contracts import (
    PackageName,
    PolicyMeasure,
    PolicyType,
    ProductCategory,
    ProductType,
)
from app.core.cdc import TAUX_USURE_MAX_ANNUEL_PCT
from app.core.config import settings as _settings
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
            # AUDIT 13/08 : hash() est randomise par processus — l'identifiant
            # du journal n'aurait pas survecu a un redemarrage. uuid5 est la
            # fonction stable du marqueur.
            entity_id=uuid5(NAMESPACE_OID, produit.marqueur),
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
    #: « REGENERER UNE VARIANTE » (16/08) — la reponse propre au besoin
    #: « je veux modifier le genere » : on n'edite pas la composition, on en
    #: tire une AUTRE, tout aussi coherente. La variante entre dans l'ancre :
    #: meme demande + meme variante = meme fiche (CR-03 tenu), variante
    #: suivante = autre patronyme/telephone, memes regles.
    variante: int = Field(default=0, ge=0, le=99)


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
        # Ancre sur le run SENTINELLE + la MEME regle de reference que le
        # moteur (fin de fenetre configuree, sinon aujourd'hui). AUDIT 13/08 :
        # l'idempotence de composition vaut A FENETRE EGALE — comme les runs,
        # dont la fenetre fait partie du perimetre.
        generateur=Generateur(
            RUN_ADMIN, reference=_settings.sim_end_date or date.today()
        ),
        company_client=CompanyServiceClient(),
        user_client=UserServiceClient(),
        account_client=AccountServiceClient(),
        registre_lenders=LendersRegistryRepository(),
        audit=AuditTrailRepository(),
    )


async def _composer_company(
    demande: CompanyDemande, mode: Any
) -> tuple[dict[str, Any] | None, Any, Any]:
    """Le tronc commun apercu/confirmation — seule la valeur de `mode` change,
    et c'est creer_company() qui en tire les consequences (D-01). Rend AUSSI
    l'executeur : la confirmation enchaine la LICENCE (UC-07) avec lui."""
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

    empreinte = (
        f"{demande.pays}:{demande.ville}:{demande.type_company}:{demande.nom}"
        f":{demande.variante}"
    )
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
    return fiche, rapport, executeur


@router.post("/companies/apercu")
async def apercu_company(
    demande: CompanyDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-D1` etape 1 — la fiche COMPLETE composee, sans aucune ecriture :
    `creer_company()` en DRY_RUN valide tout et n'emet rien."""
    from app.models.enums import RunMode

    fiche, rapport, _executeur = await _composer_company(demande, RunMode.DRY_RUN)
    return {
        "fiche": fiche,
        "admin_annonce": rapport.admins_crees[0] if rapport.admins_crees else None,
        "licence_annonce": "ALL — validite fenetre de simulation + 30 j (UC-07)",
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
    fiche, rapport, executeur = await _composer_company(demande, RunMode.REAL)
    if fiche is None:
        motif = (
            rapport.companies_echouees[-1][1]
            if rapport.companies_echouees
            else "echec sans motif rapporte"
        )
        raise HTTPException(status_code=502, detail=f"creation refusee : {motif}")

    # UC-07 (trou ferme le 16/08, attrape par la question de Yaniv) : le RUN
    # cree chaque company AVEC sa licence — la route a l'unite s'arretait a
    # l'Admin User, laissant une company au catalogue FERME (la licence
    # conditionne UC-11). Meme geste que le run : package ALL, fenetre de
    # simulation (ou 180 jours par defaut, ENF-16), garde anti-doublon
    # `a_une_licence` dans creer_licence, echec RAPPORTE jamais avale.
    from datetime import date, timedelta

    company_id = str(fiche.get("_id") or fiche.get("id") or "")
    licence_creee = False
    licence_detail = "identifiant company absent — licence non tentee"
    if company_id:
        debut = _settings.sim_start_date or date.today()
        fin = _settings.sim_end_date or (debut + timedelta(days=180))
        avant = len(rapport.licences_creees)
        await executeur.creer_licence(
            company_id, [PackageName.ALL], debut, fin, rapport
        )
        licence_creee = len(rapport.licences_creees) > avant
        licence_detail = (
            f"ALL [{debut.isoformat()} -> {fin.isoformat()} +30 j]"
            if licence_creee
            else (
                rapport.companies_echouees[-1][1]
                if rapport.companies_echouees
                and rapport.companies_echouees[-1][0].startswith("licence")
                else "deja licenciee — rien a recreer (garde UC-07)"
            )
        )

    return {
        "fiche": fiche,
        "admins_crees": rapport.admins_crees,
        "cascade_owner_verifiee": rapport.cascades_identity_verifiees == 1,
        "licence_creee": licence_creee,
        "licence_detail": licence_detail,
        "note": "sequence S3-03 executee + licence UC-07 — fiche relue du serveur",
    }


# ---------------------------------------------------------------------------
# GROUPE a l'unite (decision Yaniv 14/08) — le seul module REVERSIBLE
# ---------------------------------------------------------------------------


def _client_users() -> Any:
    """Fabrique du client user-service — doublee dans les tests."""
    from app.clients.user_service import UserServiceClient

    return UserServiceClient()


class GroupeDemande(BaseModel):
    """Creer un groupe, avec TOUT ce que ca implique (D-06/D-09/A4) :
    description REQUISE au contrat, tag jamais ROOT en ecriture (persiste en
    base mais absent de l'enumeration), company_id chaine vide = role GLOBAL
    (ce que portent les groupes existants), permissions par NOM parmi celles
    que user-service expose."""

    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=2, max_length=60)
    description: str = Field(min_length=3, max_length=200)
    tag: Literal["STAFF", "COMPANY", "CUSTOMER"]
    permissions: list[str] = Field(default_factory=list, max_length=120)
    company_id: str = Field(default="", max_length=60)


@router.post("/groupes", status_code=201)
async def creer_groupe(
    demande: GroupeDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Creation d'un groupe a l'unite — et le Loader SAIT quoi envoyer.

    Le GET-avant-POST a TROIS issues, parce que le serveur n'a AUCUNE unicite
    sur `name` (mesure) et que l'unicite, c'est NOUS :
      - homonyme A NOUS (registre)  -> 409 avec son id : reutiliser, jamais doubler ;
      - homonyme ETRANGER           -> 409 : ni consomme ni recree (A-10), autre nom ;
      - absent                      -> creation, write-ahead, RELECTURE, registre.

    Les permissions sont validees contre la liste VIVANTE de user-service —
    un nom inconnu est un 422 qui le nomme, avant tout POST. Le RESULTAT
    `SUCCES` porte le `group_id` serveur : c'est la ligne qui rend le groupe
    reconnaissable a la reconciliation (aucun prefixe sur les groupes) et
    supprimable par DELETE /admin/inventaire/groupes/{id}.
    """
    from app.clients.contracts import TagGroupe
    from app.services.inventaire import registre_groupes

    await refuser_si_run_en_cours()

    client = _client_users()
    try:
        disponibles = set(await client.lister_permissions())
        inconnues = sorted(set(demande.permissions) - disponibles)
        if inconnues:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"permissions inconnues de user-service : {inconnues} — "
                    "la liste vivante est GET /admin/referentiels/permissions"
                ),
            )

        existant = await client.chercher_groupe(demande.nom)
        if existant is not None:
            gid = str(existant.get("_id") or existant.get("id"))
            if gid in await registre_groupes():
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"le groupe {demande.nom!r} existe deja et il est A NOUS "
                        f"(id {gid}) — reutiliser, jamais doubler (le serveur "
                        "accepterait le doublon, c'est NOUS l'unicite)"
                    ),
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"homonyme ETRANGER {demande.nom!r} (id {gid}) sur la "
                    "plateforme — ni consomme (A-10) ni recree ; choisir un autre nom"
                ),
            )

        audit = AuditTrailRepository()
        entite = uuid5(NAMESPACE_OID, f"finzuu-groupe:{demande.nom}")
        async with audit.intention(
            RUN_ADMIN,
            entity_type="Group",
            entity_id=entite,
            operation="CREATE",
            cible="user-service POST /api/v1/groupes/create",
            payload={"name": demande.nom, "tag": demande.tag},
        ) as suivi:
            try:
                reponse = await client.creer_groupe(
                    nom=demande.nom,
                    description=demande.description,
                    tag=TagGroupe(demande.tag),
                    permissions=sorted(set(demande.permissions)),
                    company_id=demande.company_id,
                )
            except Exception as erreur:
                suivi.echoue(type(erreur).__name__)
                raise HTTPException(
                    status_code=502,
                    detail=f"user-service a refuse la creation : {type(erreur).__name__}",
                ) from erreur
            gid = str(reponse.get("_id") or reponse.get("id") or "")
            if not gid:
                suivi.echoue("identifiant absent de la reponse serveur")
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "user-service a repondu sans identifiant — groupe "
                        "peut-etre cree mais INTRACABLE, a verifier a la main"
                    ),
                )
            suivi.reussi({"group_id": gid, "name": demande.nom})

        # RELECTURE — la preuve vient de la liste, jamais de l'echo du POST.
        fiche = await client.chercher_groupe(demande.nom)
        if fiche is None:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"le groupe {demande.nom!r} n'apparait PAS a la relecture — "
                    "le serveur a repondu sans agir, a verifier a la main"
                ),
            )
    finally:
        await client.fermer()

    return {
        "groupe": {
            "id": gid,
            "nom": str(fiche.get("name", "")),
            "tag": str(fiche.get("tag", "")),
            "permissions": len(fiche.get("permissions") or []),
        },
        "statut": "a_nous",
        "au_registre": True,
        "note": (
            "reconnaissable a la reconciliation et supprimable via "
            "DELETE /admin/inventaire/groupes/{id} — seul module reversible"
        ),
    }


# ---------------------------------------------------------------------------
# US-D3 (16/08, demande Yaniv) — le DEPOSITAIRE a l'unite. Le meme rite que
# le produit et la company : apercu (aucune ecriture) puis confirmation.
# Contrat serveur maitrise : POST /api/v1/depositaries/create — 3 champs
# {name, currency, company_id}, pas un de plus ; le Depositaire nait ACTIF.
# ---------------------------------------------------------------------------


def _client_depositaires_unite() -> Any:
    """Fabrique du client depositary-service — doublee dans les tests."""
    from app.clients.depositary_service import DepositaryServiceClient

    return DepositaryServiceClient()


def _client_companies_unite() -> Any:
    """Fabrique du client company-service — doublee dans les tests."""
    from app.clients.company_service import CompanyServiceClient

    return CompanyServiceClient()


class DepositaireDemande(BaseModel):
    """DEUX champs saisis — le reste est COMPOSE, c'est notre conception
    (refonte 16/08, exigence Yaniv) : un depositaire n'existe jamais « en
    l'air ». Il naît d'un QUARTIER (CR-02 : chaque Kiosque a un District
    valide) et d'une company A NOUS. Le nom devient `DEMO_Kiosque <Quartier>`
    (EF-63, comme au run) et la devise est DERIVEE du pays — jamais saisie
    (D-DEP-6/FRA-201 : le serveur accepterait n'importe quoi, PAS NOUS)."""

    model_config = ConfigDict(extra="forbid")

    quartier_id: str = Field(min_length=1, max_length=64)
    company_id: str = Field(min_length=1, max_length=64)


async def _composer_depositaire(
    demande: DepositaireDemande, client_depositaires: Any, client_companies: Any
) -> dict[str, Any]:
    """Les gardes ET la composition, communes apercu/creation.

    COHERENCE (exigence Yaniv 16/08) : pas de kiosque a Douala pour une
    company de Dakar. La devise du depositaire = la devise du pays du
    quartier = la devise de la company — verifiee sur la meilleure source
    disponible (currency de la fiche, sinon pays de l'adresse ; FRA-199
    peut faire perdre currency a la persistance, et on DIT sur quoi la
    verification a porte).
    """
    from app.repositories.surcouche import SurcoucheRepository
    from app.routes.admin_referentiels import _geo
    from app.services.inventaire import registre_companies

    # 1) La company : A NOUS (403), et RELUE la-bas (404 si disparue).
    if demande.company_id not in await registre_companies():
        raise HTTPException(
            status_code=403,
            detail=(
                f"company {demande.company_id!r} absente de NOTRE registre — le "
                "Loader n'accroche jamais un depositaire a une company etrangere"
            ),
        )
    fiche_company = await client_companies.obtenir_company(demande.company_id)
    if fiche_company is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"company {demande.company_id!r} au registre mais ABSENTE de "
                "company-service — anomalie a investiguer (disparu_la_bas)"
            ),
        )

    # 2) Le quartier : existant (EF-02) et LIBRE (un quartier = UN kiosque).
    surcouche, _ = await SurcoucheRepository().charger()
    referentiel = surcouche.appliquer(_geo())
    quartier = referentiel.quartier(demande.quartier_id)
    if quartier is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"quartier {demande.quartier_id!r} inconnu du referentiel (EF-02) "
                "— l'ecran Geographie porte l'arbre complet et ses identifiants"
            ),
        )
    ville = referentiel.ville(quartier.city_id)
    if ville is None:  # pragma: no cover — un referentiel incoherent
        raise HTTPException(
            status_code=422,
            detail=f"quartier {quartier.name!r} orphelin de ville — referentiel a verifier",
        )
    from app.core.database import COLLECTION_ORG_HIERARCHY

    occupe = await get_collection(COLLECTION_ORG_HIERARCHY).count_documents(
        {"niveau": "KIOSQUE", "district_id": demande.quartier_id}
    )
    if occupe:
        raise HTTPException(
            status_code=409,
            detail=(
                f"le quartier {quartier.name!r} heberge deja un Kiosque — un "
                "quartier n'en porte qu'UN (UC-09), un second entrerait en "
                "collision avec les runs"
            ),
        )

    # 3) La devise : DECLAREE par le pays du quartier — jamais un choix.
    pays = ville.country_iso2
    devise = referentiel.devise_du_pays(pays)
    if devise is None:
        raise HTTPException(
            status_code=422,
            detail=f"aucune devise rattachee au pays {pays!r} dans le referentiel",
        )

    # 4) COHERENCE company <-> quartier, sur la meilleure source disponible.
    devise_company = str(fiche_company.get("currency") or "")
    adresse_company = fiche_company.get("address") or {}
    pays_company = str(
        (adresse_company.get("country") or "") if isinstance(adresse_company, dict) else ""
    )
    if devise_company and devise_company != devise.code:
        raise HTTPException(
            status_code=422,
            detail=(
                f"INCOHERENCE : la company opere en {devise_company} mais le "
                f"quartier {quartier.name!r} est en zone {devise.code} ({pays}) — "
                "pas de kiosque a Douala pour une company de Dakar"
            ),
        )
    if pays_company and pays_company != pays:
        raise HTTPException(
            status_code=422,
            detail=(
                f"INCOHERENCE : la company est en {pays_company}, le quartier "
                f"{quartier.name!r} en {pays} — le depositaire vit dans le pays "
                "de sa company"
            ),
        )
    coherence = (
        "devise de la company"
        if devise_company
        else (
            "pays de l'adresse company"
            if pays_company
            else "referentiel seul — FRA-199 : la fiche company ne rend ni currency ni pays"
        )
    )

    # 5) Le nom COMPOSE (EF-63, comme au run) + GET-avant-POST (D-DEP-3 :
    #    AUCUNE unicite serveur mesuree, AUCUN DELETE — un doublon serait
    #    permanent).
    marqueur = f"DEMO_Kiosque {quartier.name}"
    existant = await client_depositaires.chercher_par_nom(marqueur)
    if existant is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"le depositaire {marqueur!r} existe deja "
                f"(_id={existant.get('_id') or existant.get('id')}) — aucun DELETE "
                "n'existe (D-DEP-3), un doublon serait permanent"
            ),
        )
    return {
        "marqueur": marqueur,
        "devise": devise.code,
        "pays": pays,
        "ville": ville.name,
        "quartier": quartier.name,
        "zone_type": quartier.zone_type,
        "coherence_verifiee_par": coherence,
        "company_nom": str(fiche_company.get("name", "")),
    }


@router.post("/depositaires/apercu")
async def apercu_depositaire(
    demande: DepositaireDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-D3` etape 1 — la COMPOSITION complete, AUCUNE ecriture."""
    client = _client_depositaires_unite()
    client_cies = _client_companies_unite()
    try:
        composition = await _composer_depositaire(demande, client, client_cies)
    finally:
        await client.fermer()
        await client_cies.fermer()
    return {
        "payload": {
            "name": composition["marqueur"],
            "currency": composition["devise"],
            "company_id": demande.company_id,
        },
        "composition": composition,
        "marqueur": composition["marqueur"],
        "note": (
            "apercu seulement — aucune ecriture n'est partie. Le Depositaire "
            "naitra ACTIF (mesure). Confirmer via POST /admin/entites/depositaires."
        ),
    }


@router.post("/depositaires", status_code=201)
async def creer_depositaire(
    demande: DepositaireDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """`US-D3` etape 2 — gardes re-jouees, write-ahead, POST, RELECTURE.

    Le depositaire cree ici s'inscrit au REGISTRE par le journal (RESULTAT
    `SUCCES` portant `depositary_id`) : il est `a_nous` a la reconciliation
    des sa naissance — sans attendre qu'un run lui donne un noeud Kiosque.
    """
    await refuser_si_run_en_cours()

    client = _client_depositaires_unite()
    client_cies = _client_companies_unite()
    try:
        composition = await _composer_depositaire(demande, client, client_cies)
        marqueur = composition["marqueur"]

        audit = AuditTrailRepository()
        async with audit.intention(
            RUN_ADMIN,
            entity_type="Depositary",
            entity_id=uuid5(NAMESPACE_OID, f"finzuu-depositaire:{marqueur}"),
            operation="CREATE",
            cible="depositary-service POST /api/v1/depositaries/create",
            payload={"name": marqueur, "company_id": demande.company_id},
        ) as suivi:
            try:
                reponse = await client.creer(
                    marqueur, composition["devise"], demande.company_id
                )
            except ErreurService as erreur:
                suivi.echoue(f"HTTP {erreur.status}")
                raise HTTPException(
                    status_code=502,
                    detail=f"depositary-service a refuse : HTTP {erreur.status}",
                ) from erreur
            identifiant = str(reponse.get("_id") or reponse.get("id") or "")
            suivi.reussi({"depositary_id": identifiant, "name": marqueur})

        # RELECTURE — la preuve vient de la liste, jamais de l'echo du POST.
        fiche = await client.chercher_par_nom(marqueur)
        if fiche is None:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"le depositaire {marqueur!r} n'apparait PAS a la relecture — "
                    "le serveur a repondu sans agir, a verifier a la main"
                ),
            )
    finally:
        await client.fermer()
        await client_cies.fermer()

    return {
        "depositary_id": identifiant,
        "fiche_relue": fiche,
        "composition": composition,
        "marqueur": marqueur,
        "statut": "a_nous",
        "note": (
            "au registre par le journal — visible a_nous a l'inventaire ; "
            "ACTIF des la naissance ; aucun DELETE n'existe (D-DEP-3). Le "
            "noeud d'arbre est DIFFERE : le prochain run rattache (les "
            "kiosques deja presents sont SAUTES par nom, jamais recrees)"
        ),
    }


# ---------------------------------------------------------------------------
# LICENCES a l'unite (16/08, demande Yaniv) — voir et ATTRIBUER une licence
# a une company A NOUS. UC-07 : la licence conditionne le catalogue (UC-11).
# ---------------------------------------------------------------------------


class LicenceDemande(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: READY_CASH = credit, READY_COLLECTE = collecte, ALL = les deux (UC-07).
    packages: list[Literal["ALL", "READY_CASH", "READY_COLLECTE"]] = Field(
        min_length=1, max_length=3
    )


async def _garder_company_a_nous(company_id: str) -> None:
    from app.services.inventaire import registre_companies

    if company_id not in await registre_companies():
        raise HTTPException(
            status_code=403,
            detail=(
                f"company {company_id!r} absente de NOTRE registre — le Loader "
                "ne licencie jamais une company etrangere"
            ),
        )


@router.get("/companies/{company_id}/licences")
async def licences_de_company(
    company_id: str,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les licences RELUES de company-service pour une company A NOUS."""
    await _garder_company_a_nous(company_id)
    client = _client_companies_unite()
    try:
        licences = await client.licences_de_company(company_id)
    finally:
        await client.fermer()
    return {
        "company_id": company_id,
        "licences": licences,
        "compte": len(licences),
        "note": (
            "la licence conditionne le catalogue (UC-11) : READY_CASH credit, "
            "READY_COLLECTE collecte, ALL les deux — une company sans licence "
            "a un catalogue FERME"
        ),
    }


@router.post("/companies/{company_id}/licences", status_code=201)
async def creer_licence_company(
    company_id: str,
    demande: LicenceDemande,
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Attribue une licence a une company A NOUS — le geste exact du run.

    Fenetre UC-07 : la fenetre de simulation configuree (ou 180 jours par
    defaut, ENF-16) PLUS 30 jours a venir. 409 si la company est deja
    licenciee — une licence active suffit, jamais d'empilement silencieux.
    """
    from datetime import date, timedelta

    from app.clients.contracts import PackageName as _Pkg
    from app.core.cdc import LICENCE_MARGE_FUTURE_JOURS

    await refuser_si_run_en_cours()
    await _garder_company_a_nous(company_id)

    client = _client_companies_unite()
    try:
        if await client.a_une_licence(company_id):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"la company {company_id!r} est DEJA licenciee — une licence "
                    "active suffit (UC-07), rien n'est empile"
                ),
            )
        debut = _settings.sim_start_date or date.today()
        fin = (_settings.sim_end_date or (debut + timedelta(days=180))) + timedelta(
            days=LICENCE_MARGE_FUTURE_JOURS
        )
        audit = AuditTrailRepository()
        async with audit.intention(
            RUN_ADMIN,
            entity_type="License",
            entity_id=uuid5(NAMESPACE_OID, f"finzuu-licence:{company_id}"),
            operation="CREATE",
            cible="company-service POST /api/v1/licenses/",
            payload={"company_id": company_id, "packages": list(demande.packages)},
        ) as suivi:
            try:
                await client.creer_licence(
                    company_id,
                    [_Pkg(p) for p in demande.packages],
                    debut.isoformat(),
                    fin.isoformat(),
                )
            except ErreurService as erreur:
                suivi.echoue(f"HTTP {erreur.status}")
                raise HTTPException(
                    status_code=502,
                    detail=f"company-service a refuse la licence : HTTP {erreur.status}",
                ) from erreur
            suivi.reussi({"company_id": company_id, "packages": list(demande.packages)})

        # RELECTURE — les licences d'APRES, jamais l'echo du POST.
        licences = await client.licences_de_company(company_id)
    finally:
        await client.fermer()

    return {
        "company_id": company_id,
        "licences": licences,
        "fenetre": {"debut": debut.isoformat(), "fin": fin.isoformat()},
        "note": "licence attribuee — le catalogue (UC-11) s'ouvre selon les packages",
    }
