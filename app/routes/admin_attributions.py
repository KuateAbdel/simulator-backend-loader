"""
app/routes/admin_attributions.py
================================
La face ADMINISTRATION du mecanisme d'attribution USSD.

Nee du recensement des baux orphelins (25/08, suite au defaut de sequence
FZ-DIAG-BAIL-2026-001) : aucune route ne listait les baux, l'exploitation
etait aveugle sur ce que la route publique attribuait. Cette liste est la
matiere premiere du tableau de bord d'attribution — elle en partage le cadre
d'acces (interface du Loader, roles du Loader, decision QA 25/08).

**Trois gestes, et la frontiere entre eux est le sujet de ce module :**

- `GET ""` — le RECENSEMENT (lecture seule).
- `GET/PUT "/reglages"` — la DUREE du bail, contrat 0.4 §(b). Un reglage, pas
  une constante de livraison. Il ne touche AUCUN bail existant.
- `DELETE "/{msisdn}"` — la REVOCATION. La version precedente de ce fichier
  s'interdisait d'ecrire et promettait : « si un jour l'administration doit
  liberer, ce sera une route dediee et journalisee ». La voici, et les deux
  conditions de la promesse sont tenues litteralement : elle ne fait QUE cela,
  et elle exige un motif qu'elle inscrit au journal. Un bail se rompt par
  l'appareil (`DELETE` public, `EF-17`), par l'echeance, ou par ce geste-ci —
  jamais par un clic silencieux.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import NAMESPACE_OID, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from app.repositories.attribution_baux import (
    ORIGINE_ADMINISTRATION,
    AttributionBauxRepository,
    _en_datetime,
)
from app.repositories.attribution_reglages import (
    BORNE_MAX,
    BORNE_MIN,
    DureeHorsBornes,
    ReglagesBail,
    ReglagesBailRepository,
    valider_duree,
)
from app.repositories.audit_trail import AuditTrailRepository
from app.routes.dependances import SessionAdmin, admin_complet, exige_super_admin

router = APIRouter(prefix="/admin/attributions", tags=["admin — attributions"])

#: Le run SENTINELLE des gestes d'administration — meme valeur que partout
#: ailleurs dans le Loader (`admin_comptes`, `attribution_publique`).
RUN_ADMIN = UUID(int=0)


# ──────────────────────────────────────────────────────────────────────────
# 1. Le recensement — lecture seule
# ──────────────────────────────────────────────────────────────────────────


@router.get("")
async def lister_baux_actifs(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Les baux ACTIFS, les plus recents d'abord — le recensement.

    La cle d'idempotence est exposee : deux baux aux cles distinctes viennent
    de deux TENTATIVES distinctes — c'est elle qui separe un rejeu legitime
    d'une re-attribution orpheline."""
    depot = AttributionBauxRepository()
    documents = await depot.lister_actifs()
    reglages, _meta = await ReglagesBailRepository().charger()

    baux = []
    for d in documents:
        debut = _en_datetime(d["attribue_le"])
        fin = _en_datetime(d["expire_le"])
        profil = d.get("profil") or {}
        # LA DUREE SOUS LAQUELLE CE BAIL A ETE ACCORDE — relue sur ses deux
        # dates, jamais sur le reglage courant : c'est un FAIT du passe. Et
        # `jours_si_attribue_maintenant` dit ce que le meme profil obtiendrait
        # aujourd'hui. Quand les deux different, l'operateur voit d'un coup
        # d'oeil qu'un bail court encore sous l'ancien reglage — sans quoi la
        # promesse « les baux existants sont inchanges » resterait invisible.
        accorde_pour = round((fin - debut).total_seconds() / 86400)
        courant = reglages.jours_pour(str(profil.get("pays") or ""))
        baux.append(
            {
                "msisdn": str(d["_id"]),
                "attribution_id": str(d["attribution_id"]),
                "profil": d.get("profil"),
                "appareil": d.get("appareil"),
                "attribue_le": debut.isoformat(),
                "expire_le": fin.isoformat(),
                "cle_idempotence": d.get("cle_idempotence"),
                "accorde_pour_jours": accorde_pour,
                "jours_si_attribue_maintenant": courant,
                "sous_ancien_reglage": accorde_pour != courant,
            }
        )

    return {
        "baux": baux,
        "actifs": len(baux),
        "sous_ancien_reglage": sum(1 for b in baux if b["sous_ancien_reglage"]),
        "reglage_courant": reglages.en_vue(),
        "note": (
            "baux actifs du simulateur USSD, les plus récents d'abord — "
            "la libération est le geste de l'appareil (DELETE public), de "
            "l'échéance, ou de la révocation d'administration (DELETE ici, "
            "motif obligatoire)"
        ),
    }


# ──────────────────────────────────────────────────────────────────────────
# 2. La duree du bail — contrat 0.4 §(b)
# ──────────────────────────────────────────────────────────────────────────


class ReglagesEnEntree(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: La valeur GLOBALE, bornee 1 a 30 jours.
    jours_defaut: int
    #: Les SURCHARGES par pays — `{"BF": 3, "CI": 14}`. Un pays absent suit la
    #: valeur globale. Le dictionnaire remplace l'ancien EN ENTIER : retirer
    #: une surcharge, c'est ne pas la renvoyer (pas d'effacement implicite a
    #: deviner cote client).
    par_pays: dict[str, int] = Field(default_factory=dict)


def _vue_reglages(reglages: ReglagesBail, meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "reglages": reglages.en_vue(),
        "bornes": {"min": BORNE_MIN, "max": BORNE_MAX},
        **meta,
        "note": (
            "durée du bail d'attribution (contrat 0.4 §b) — résolue au moment "
            "du tirage ; les baux DÉJÀ attribués gardent l'échéance qu'ils "
            "portent, un bail est une promesse datée"
        ),
    }


@router.get("/reglages")
async def lire_reglages(
    _: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """La duree en vigueur. Sans document enregistre : le defaut du CDC (sept
    jours), version 0 — l'etat initial n'est pas un cas d'erreur."""
    reglages, meta = await ReglagesBailRepository().charger()
    return _vue_reglages(reglages, meta)


@router.put("/reglages")
async def regler_duree(
    demande: ReglagesEnEntree,
    session: Annotated[SessionAdmin, Depends(admin_complet)],
) -> dict[str, Any]:
    """Regle la duree du bail — globale, et par pays.

    REFUS AVANT ECRITURE, et toujours en disant OU : une valeur hors bornes,
    ou un pays que le referentiel ne connait pas. Le second refus n'est pas du
    zele : une surcharge sur un code mal frappe est un reglage qui ne
    s'applique jamais, et rien ne le signalerait — l'operateur croirait avoir
    regle ce pays.
    """
    depot = ReglagesBailRepository()
    avant, meta_avant = await depot.charger()

    try:
        jours_defaut = valider_duree(demande.jours_defaut, ou="la valeur globale")
        par_pays = {}
        for code, jours in demande.par_pays.items():
            pays = str(code).strip().upper()
            par_pays[pays] = valider_duree(jours, ou=f"la surcharge du pays {pays}")
    except DureeHorsBornes as refus:
        raise HTTPException(status_code=422, detail=str(refus)) from refus

    if par_pays:
        from app.routes.attribution_publique import _pays_du_referentiel

        connus = await _pays_du_referentiel()
        inconnus = sorted(p for p in par_pays if p not in connus)
        if inconnus:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"pays hors référentiel : {', '.join(inconnus)} — une "
                    "surcharge sur un pays inconnu ne s'appliquerait jamais"
                ),
            )

    apres = ReglagesBail(jours_defaut=jours_defaut, par_pays=par_pays)
    audit = AuditTrailRepository()
    async with audit.intention(
        RUN_ADMIN,
        entity_type="ReglageBailAttribution",
        entity_id=uuid5(NAMESPACE_OID, "loader-reglage:attribution_bail"),
        operation="UPDATE",
        cible="durée du bail d'attribution",
        payload={
            "avant": avant.en_vue(),
            "apres": apres.en_vue(),
            "modifie_par": session.email,
        },
    ) as suivi:
        meta = await depot.enregistrer(apres, par=session.email)
        suivi.reussi({"version": meta["version"]})

    # CE QUE CE GESTE NE TOUCHE PAS, EN CHIFFRES. « Les baux existants sont
    # inchanges » est une promesse ; tant qu'elle n'est pas chiffree, elle
    # n'est pas verifiable a l'ecran. On rend donc le nombre de baux qui
    # gardent leur echeance et jusqu'a quand court le plus long : l'operateur
    # qui raccourcit la duree voit immediatement combien de temps l'ancienne
    # continue de courir.
    encours = await AttributionBauxRepository().etat_pour_purge()
    return {
        **_vue_reglages(apres, meta),
        "version_precedente": meta_avant["version"],
        "baux_existants": {
            "actifs_inchanges": encours["actifs"],
            "plus_longue_echeance": encours["plus_longue_echeance"],
            "regle": (
                "inchangés — leur échéance a été fixée à leur tirage (option 1 "
                "de la révision 0.4) ; le nouveau réglage vaut pour les "
                "tirages suivants"
            ),
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# 3. La revocation — le geste dedie et journalise
# ──────────────────────────────────────────────────────────────────────────


class DemandeRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: OBLIGATOIRE, et non vide. C'est la moitie de la promesse faite par la
    #: version lecture seule de ce module : une revocation sans motif est le
    #: « clic d'administration silencieux » qu'elle s'interdisait.
    motif: str = Field(min_length=3, max_length=280)


@router.delete("/{msisdn}")
async def revoquer_bail(
    demande: DemandeRevocation,
    session: Annotated[SessionAdmin, Depends(exige_super_admin)],
    msisdn: Annotated[str, Path(min_length=6, max_length=20)],
) -> dict[str, Any]:
    """Rompt un bail ACTIF depuis l'administration — `super_admin` seulement.

    Reserve au `super_admin` comme la purge et les suppressions : ce geste
    coupe un APPAREIL EXTERNE, la seule chose du Loader dont un tiers depend
    en ce moment meme (arbitrage Yaniv 24/08, repris de la garde de purge).

    404 sur un bail absent OU echu : dans les deux cas il n'y a rien a
    revoquer. On ne rend pas 204 « par confort » — l'operateur qui revoque un
    numero doit savoir s'il a coupe quelque chose ou frappe dans le vide.

    L'appareil n'est pas prevenu : aucun canal descendant n'existe (`ENF-05`).
    Il le decouvre a sa prochaine verification de bail (404) et retourne a la
    composition — le chemin de l'expiration, deja prouve.
    """
    numero = msisdn.strip()
    motif = demande.motif.strip()
    depot = AttributionBauxRepository()

    audit = AuditTrailRepository()
    async with audit.intention(
        RUN_ADMIN,
        entity_type="AttributionBail",
        entity_id=uuid5(NAMESPACE_OID, f"loader-bail:{numero}"),
        operation="REVOKE",
        cible=numero,
        payload={
            "msisdn": numero,
            "motif": motif,
            "par": session.email,
            # Le pendant exact de la trace `EF-17` : meme effet sur le bail,
            # volonte differente. Le journal du tableau de bord doit pouvoir
            # separer « rendu par le partenaire » de « repris ici ».
            "origine": ORIGINE_ADMINISTRATION,
        },
    ) as suivi:
        document = await depot.revoquer(numero)
        if document is None:
            suivi.echoue("aucun bail actif sur ce numéro")
            raise HTTPException(
                status_code=404,
                detail=(f"aucun bail actif sur {numero} — il n'existe pas, ou il est déjà échu"),
            )
        suivi.reussi(
            {
                "attribution_id": str(document["attribution_id"]),
                "appareil": document.get("appareil"),
                "expirait_le": _en_datetime(document["expire_le"]).isoformat(),
            }
        )

    return {
        "msisdn": numero,
        "attribution_id": str(document["attribution_id"]),
        "profil": document.get("profil"),
        "appareil": document.get("appareil"),
        "attribue_le": _en_datetime(document["attribue_le"]).isoformat(),
        "expirait_le": _en_datetime(document["expire_le"]).isoformat(),
        "revoque_par": session.email,
        "motif": motif,
        "note": (
            "bail rompu — le client retourne au pool immédiatement ; "
            "l'appareil le découvrira à sa prochaine vérification (404) et "
            "reviendra à la composition"
        ),
    }
