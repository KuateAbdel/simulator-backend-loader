"""
app/routes/admin_entites.py
===========================
Lot D — les entites a l'UNITE. Cette tranche : `US-D2`, le produit COLLECT.
(`US-D1`, la Company, suit — elle reutilisera la sequence S3-03 comme cette
route reutilise le catalogue.)

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
