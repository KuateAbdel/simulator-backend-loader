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

import logging
from typing import Annotated, Any
from uuid import NAMESPACE_OID, UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Path, Query
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
from app.routes.dependances import (
    SessionAdmin,
    exige_admin,
    exige_super_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/attributions", tags=["admin — attributions"])

#: Le run SENTINELLE des gestes d'administration — meme valeur que partout
#: ailleurs dans le Loader (`admin_comptes`, `attribution_publique`).
RUN_ADMIN = UUID(int=0)


def _horloge_serveur() -> Any:
    """L'horloge du SERVEUR, tronquee comme celle du mecanisme — la seule
    autorite de temps (contrat §3). Le tableau de bord s'y cale."""
    from app.repositories.attribution_baux import _maintenant

    return _maintenant()


async def _territoires(msisdns: list[str]) -> dict[str, dict[str, Any]]:
    """La chaine territoriale de CHAQUE numero — msisdn → noeud CLIENT →
    kiosque → agence → branche — jointe EN UN LOT pour toute la liste.

    ENTIEREMENT LOCALE (FZ-INV-ATTRIB §6) : la carte et le referentiel sont
    a nous, aucun appel plateforme — c'est ce qui tient `ENF-D01` (« aucun
    appel par ligne ») et l'etat limite « service indisponible » de la spec
    §9 : meme plateforme muette, la vue de masse reste entiere.

    `AFF-07` — LA DEDUPLICATION PAR NUMERO : un client a UN noeud PAR RUN
    (D-CLI-11), et deux runs peuvent l'avoir rattache a deux kiosques. Sans
    regle, deux ecrans montreraient deux kiosques pour le meme bail. La
    regle : LE RATTACHEMENT DU RUN LE PLUS RECENT fait foi — c'est la
    derniere decision du Loader, exactement comme la reconnaissance retient
    l'etat le plus recent d'un client.
    """
    if not msisdns:
        return {}
    from app.core.database import (
        COLLECTION_LOADER_RUNS,
        COLLECTION_ORG_HIERARCHY,
        get_collection,
    )
    from app.repositories.surcouche import SurcoucheRepository
    from app.routes.admin_referentiels import _geo

    arbre = get_collection(COLLECTION_ORG_HIERARCHY)
    noms = [f"Client {m}" for m in msisdns]
    candidats: dict[str, list[dict[str, Any]]] = {}
    async for noeud in arbre.find({"niveau": "CLIENT", "name": {"$in": noms}}):
        candidats.setdefault(str(noeud["name"]).removeprefix("Client ").strip(), []).append(
            noeud
        )

    # Les dates des runs concernes — une seule requete, pour l'arbitrage AFF-07.
    run_ids = {str(n["run_id"]) for lst in candidats.values() for n in lst}
    dates_runs: dict[str, Any] = {}
    if run_ids:
        async for run in get_collection(COLLECTION_LOADER_RUNS).find(
            {"_id": {"$in": sorted(run_ids)}}, {"cree_le": 1}
        ):
            dates_runs[str(run["_id"])] = run.get("cree_le")

    retenus: dict[str, dict[str, Any]] = {}
    for msisdn, noeuds in candidats.items():
        retenus[msisdn] = max(
            noeuds,
            key=lambda n: (
                dates_runs.get(str(n["run_id"])) is not None,
                dates_runs.get(str(n["run_id"])) or "",
            ),
        )

    # La chaine parentale, en trois requetes de lot — jamais une par ligne.
    async def _par_ids(ids: set[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        return {
            str(d["_id"]): d
            async for d in arbre.find({"_id": {"$in": sorted(ids)}})
        }

    kiosques = await _par_ids(
        {str(n["parent_id"]) for n in retenus.values() if n.get("parent_id")}
    )
    agences = await _par_ids(
        {str(k["parent_id"]) for k in kiosques.values() if k.get("parent_id")}
    )
    branches = await _par_ids(
        {str(a["parent_id"]) for a in agences.values() if a.get("parent_id")}
    )

    surcouche, _m = await SurcoucheRepository().charger()
    geo = surcouche.appliquer(_geo())

    territoires: dict[str, dict[str, Any]] = {}
    for msisdn, noeud in retenus.items():
        kiosque = kiosques.get(str(noeud.get("parent_id")))
        agence = (
            agences.get(str(kiosque["parent_id"]))
            if kiosque and kiosque.get("parent_id")
            else None
        )
        branche = (
            branches.get(str(agence["parent_id"]))
            if agence and agence.get("parent_id")
            else None
        )
        ville = (
            geo.ville(str(agence.get("city_id")))
            if agence and agence.get("city_id")
            else None
        )
        quartier = (
            geo.quartier(str(kiosque.get("district_id")))
            if kiosque and kiosque.get("district_id")
            else None
        )
        region = (
            geo.region(str(branche.get("region_id")))
            if branche and branche.get("region_id")
            else None
        )
        territoires[msisdn] = {
            # AFF-04 — c'est un RATTACHEMENT (decision du run, EF-26), jamais
            # une activite : le lien d'activite n'existera qu'a la premiere
            # collecte. Le nom du champ porte la regle.
            "rattache_au_kiosque": kiosque.get("name") if kiosque else None,
            "quartier": quartier.name if quartier else None,
            "ville": ville.name if ville else None,
            "region": region.name if region else None,
            "pays": noeud.get("country_code"),
        }
    return territoires


# ──────────────────────────────────────────────────────────────────────────
# 1. Le recensement — lecture seule
# ──────────────────────────────────────────────────────────────────────────


@router.get("")
async def lister_baux_actifs(
    _: Annotated[SessionAdmin, Depends(exige_admin)],
    etat: Annotated[str, Query(pattern="^(actifs|echus|tous)$")] = "actifs",
) -> dict[str, Any]:
    """Les baux ACTIFS, les plus recents d'abord — le recensement.

    La cle d'idempotence est exposee : deux baux aux cles distinctes viennent
    de deux TENTATIVES distinctes — c'est elle qui separe un rejeu legitime
    d'une re-attribution orpheline."""
    depot = AttributionBauxRepository()
    documents = await depot.lister(etat)
    reglages, _meta = await ReglagesBailRepository().charger()
    territoires = await _territoires([str(d["_id"]) for d in documents])
    horloge = _horloge_serveur()

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
                "os": d.get("os"),
                "attribue_le": debut.isoformat(),
                "expire_le": fin.isoformat(),
                "cle_idempotence": d.get("cle_idempotence"),
                "accorde_pour_jours": accorde_pour,
                "jours_si_attribue_maintenant": courant,
                "sous_ancien_reglage": accorde_pour != courant,
                # Le libelle libre de l'operateur (spec §5.2) — vide tant
                # qu'il n'est pas renseigne, jamais silencieusement omis.
                "interlocuteur": d.get("interlocuteur"),
                # La chaine territoriale, JOINTE LOCALEMENT en un lot pour
                # toute la liste (ENF-D01 : aucun appel par ligne, et aucun
                # appel du tout — la carte et le referentiel sont a nous).
                "territoire": territoires.get(str(d["_id"])),
                # actif/echu — un bail mort reste lisible 30 jours (TTL).
                "etat": "actif" if fin > horloge else "echu",
            }
        )

    return {
        "baux": baux,
        "actifs": sum(1 for b in baux if b["etat"] == "actif"),
        "sous_ancien_reglage": sum(1 for b in baux if b["sous_ancien_reglage"]),
        "reglage_courant": reglages.en_vue(),
        # L'HORLOGE DU SERVEUR au moment du releve — le compte a rebours du
        # tableau de bord se cale sur ELLE, jamais sur le poste de
        # l'operateur : la seule autorite d'horloge du mecanisme est le
        # serveur (contrat §3), et un compte a rebours calcule sur une
        # horloge locale derivante mentirait devant un partenaire.
        "releve_le": horloge.isoformat(),
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
    _: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """La duree en vigueur. Sans document enregistre : le defaut du CDC (sept
    jours), version 0 — l'etat initial n'est pas un cas d'erreur."""
    reglages, meta = await ReglagesBailRepository().charger()
    return _vue_reglages(reglages, meta)


@router.put("/reglages")
async def regler_duree(
    demande: ReglagesEnEntree,
    session: Annotated[SessionAdmin, Depends(exige_super_admin)],
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


# ──────────────────────────────────────────────────────────────────────────
# 4. La population — libres, attribues, total par combinaison
# ──────────────────────────────────────────────────────────────────────────


@router.get("/population")
async def population(
    _: Annotated[SessionAdmin, Depends(exige_admin)],
) -> dict[str, Any]:
    """L'ecran Population du tableau de bord (spec §5.4) : pour chaque
    combinaison, le total, les attribues et les libres — groupes par pays,
    la dimension selon laquelle la campagne se deplace.

    POURQUOI ICI ET PAS DANS `/criteres` : `/criteres` est la route PUBLIQUE
    du contrat (§1), consommee par l'application, et elle ne rend que ce que
    l'application a besoin de savoir — les libres. Le total et les attribues
    sont de l'EXPLOITATION : ils vivent sous `/admin`, sous les roles du
    Loader, hors de la surface du contrat. Le mecanisme public ne bouge pas.

    LA GRILLE EST DERIVEE, jamais figee : pays du pool x genres x categories.
    Seize combinaisons aujourd'hui parce que quatre pays sont peuples — un
    cinquieme pays peuple en fera vingt, sans changement ici.
    """
    from app.routes.attribution_publique import (
        CATEGORIES,
        GENRES,
        _pays_du_referentiel,
        _pool,
    )

    pool = await _pool()
    occupes = await AttributionBauxRepository().actifs_par_profil()
    fiches = await _pays_du_referentiel()

    lignes = []
    for pays in sorted({cle[0] for cle in pool}):
        for genre in (g["code"] for g in GENRES):
            for categorie in (c["code"] for c in CATEGORIES):
                cle = (pays, genre, categorie)
                total = len(pool.get(cle, set()))
                attribues = min(occupes.get(cle, 0), total)
                lignes.append(
                    {
                        "pays": pays,
                        "pays_libelle": fiches.get(pays, {}).get("libelle_fr", pays),
                        "genre": genre,
                        "categorie": categorie,
                        "total": total,
                        "attribues": attribues,
                        "libres": max(0, total - attribues),
                    }
                )

    return {
        "combinaisons": lignes,
        "total_clients": sum(ligne["total"] for ligne in lignes),
        "total_attribues": sum(ligne["attribues"] for ligne in lignes),
        "total_libres": sum(ligne["libres"] for ligne in lignes),
        # L'indicateur qui doit alerter (spec §5.1) : une combinaison a zero
        # signifie qu'un interlocuteur de ce profil ne sera pas servi.
        "combinaisons_epuisees": sum(1 for ligne in lignes if ligne["libres"] == 0),
        "releve_le": _horloge_serveur().isoformat(),
    }


# ──────────────────────────────────────────────────────────────────────────
# 5. L'interlocuteur — le libelle libre de la campagne
# ──────────────────────────────────────────────────────────────────────────


class DemandeInterlocuteur(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Le libelle libre — « M. Diallo », « table du fond ». Vide = EFFACER :
    #: retirer un nom est un geste aussi legitime que le poser.
    interlocuteur: str = Field(max_length=80)


@router.put("/{msisdn}/interlocuteur")
async def nommer_interlocuteur(
    demande: DemandeInterlocuteur,
    session: Annotated[SessionAdmin, Depends(exige_admin)],
    msisdn: Annotated[str, Path(min_length=6, max_length=20)],
) -> dict[str, Any]:
    """Nomme (ou renomme, ou efface) l'interlocuteur d'un bail — spec §7 :
    « le bail de M. Diallo » est la recherche la plus frequente d'une
    campagne, et elle est impossible tant que le bail ne porte qu'un numero.

    Champ ADDITIF sur le bail, ecrit par la seule administration : le
    mecanisme public n'en connait pas l'existence. Un bail echu se nomme
    aussi — retrouver « qui detenait quoi » vaut pour l'historique.
    Role `admin` : c'est une ecriture de campagne, pas un geste destructif.
    """
    numero = msisdn.strip()
    libelle = demande.interlocuteur.strip() or None
    document = await AttributionBauxRepository().nommer_interlocuteur(numero, libelle)
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"aucun bail (même échu) ne porte le numéro {numero}",
        )
    await AuditTrailRepository().journaliser(
        run_id=RUN_ADMIN,
        entity_type="AttributionBail",
        entity_id=uuid5(NAMESPACE_OID, f"loader-bail:{numero}"),
        action="UPDATE",
        after={
            "operation": "INTERLOCUTEUR",
            "cible": numero,
            "payload": {"interlocuteur": libelle, "par": session.email},
        },
    )
    return {
        "msisdn": numero,
        "interlocuteur": libelle,
        "note": "libellé de campagne — visible dans le recensement et le dossier",
    }


# ──────────────────────────────────────────────────────────────────────────
# 6. Le dossier client 360° — FZ-INV-ATTRIB §8, le modele de jointure
# ──────────────────────────────────────────────────────────────────────────
#
# POURQUOI CETTE ROUTE EXISTE : le tableau de bord ne parle qu'au Loader —
# le CORS de la plateforme ne connait que notre origine, et les identifiants
# ROOT partages n'ont RIEN a faire dans un navigateur. C'est donc le Loader
# qui fait les appels, avec les clients qu'il possede deja pour ses runs
# (client-service, account-service, collect-service) : la meme connaissance,
# les memes disciplines (D-ACC-1, D-CLI-4...), aucun client nouveau.
#
# Les fabriques ci-dessous sont le POINT DE DOUBLURE des tests — meme motif
# que `_config_admin` dans admin_referentiels : le chemin de production
# construit les vrais clients, les tests y substituent leurs doubles.


def _client_clients() -> Any:
    from app.clients.client_service import ClientServiceClient

    return ClientServiceClient()


def _client_comptes() -> Any:
    from app.clients.account_service import AccountServiceClient

    return AccountServiceClient()


def _client_collectes() -> Any:
    from app.clients.collect_service import CollectServiceClient

    return CollectServiceClient()


def _bloc_absent(raison: str) -> dict[str, Any]:
    """`AFF-06` applique au transport : une donnee absente est EXPLIQUEE,
    jamais silencieuse — et jamais un code technique (`AFF-05`)."""
    return {"present": False, "raison": raison}


#: Ce que la fiche serveur ne doit JAMAIS colporter jusqu'a l'ecran :
#: `identity.type` rend « entreprise » pour un particulier (AFF-02, D-CLI-4).
#: Retire A LA SOURCE — une regle d'affichage tenue par le serveur ne depend
#: plus de la discipline de chaque ecran. Le `status` de la fiche (AFF-03,
#: « en attente » sur un client operationnel) est exclu PAR CONSTRUCTION :
#: la fiche n'est jamais rendue brute, seuls des champs nommes en sortent.
_CHAMPS_IDENTITE_PROSCRITS = frozenset({"type"})


@router.get("/{msisdn}/dossier")
async def dossier_client(
    _: Annotated[SessionAdmin, Depends(exige_admin)],
    msisdn: Annotated[str, Path(min_length=6, max_length=20)],
) -> dict[str, Any]:
    """Le dossier complet d'un client ATTRIBUE — panneau lateral du tableau
    de bord (spec §5.3). Une seule cle d'entree : le msisdn du bail.

    TOUJOURS HTTP 200, ET CHAQUE BLOC PORTE SA PROPRE VERITE : sa donnee, ou
    sa raison d'absence. Un account-service en panne n'emporte pas
    l'identite qui a repondu — c'est l'etat limite « service indisponible »
    de la spec §9, resolu bloc par bloc et non ecran par ecran. Le seul 404
    de cette route : aucun bail (meme echu) ne porte ce numero — il n'y a
    alors PAS de dossier, par principe (spec §1.3 : seuls les clients
    porteurs d'un bail sont visibles).
    """
    import asyncio

    numero = msisdn.strip()
    bail = await AttributionBauxRepository().par_msisdn(numero)
    if bail is None:
        raise HTTPException(
            status_code=404,
            detail=f"aucun bail (même échu) ne porte le numéro {numero}",
        )

    horloge = _horloge_serveur()
    territoire_local = (await _territoires([numero])).get(numero)

    # ── Bloc A — le Loader, zero reseau : disponible IMMEDIATEMENT ────────
    fin = _en_datetime(bail["expire_le"])
    entete = {
        "msisdn": numero,
        "interlocuteur": bail.get("interlocuteur"),
        "profil": bail.get("profil"),
        "appareil": bail.get("appareil"),
        "os": bail.get("os"),
        "attribue_le": _en_datetime(bail["attribue_le"]).isoformat(),
        "expire_le": fin.isoformat(),
        "etat": "actif" if fin > horloge else "echu",
        "releve_le": horloge.isoformat(),
    }

    # ── Bloc B — la fiche client-service : la clef des blocs C, D et E ────
    fiche: dict[str, Any] | None = None
    raison_fiche: str | None = None
    clients = _client_clients()
    try:
        fiche = await clients.chercher_par_msisdn(numero)
        if fiche is None:
            raison_fiche = "la plateforme ne connaît pas ce numéro"
    except Exception:
        logger.exception("dossier %s : fiche client illisible", numero)
        raison_fiche = "le service des clients ne répond pas"
    finally:
        await clients.fermer()

    identite: dict[str, Any]
    territoire: dict[str, Any]
    produits: dict[str, Any]
    if fiche is None:
        identite = _bloc_absent(raison_fiche or "fiche indisponible")
        adresse = None
        produits = _bloc_absent(raison_fiche or "fiche indisponible")
        langue = None
        segment = None
        account_id = None
        client_id = None
    else:
        brute = dict(fiche.get("identity") or {})
        adresse = brute.pop("address", None)
        identite = {
            "present": True,
            **{k: v for k, v in brute.items() if k not in _CHAMPS_IDENTITE_PROSCRITS},
        }
        # AFF-08 — les produits se lisent depuis la FICHE SERVEUR, jamais
        # depuis le noeud local (vide sur une reprise, D-CLI-5).
        produits = {"present": True, "souscrits": fiche.get("product") or []}
        langue = fiche.get("language")
        segment = fiche.get("segment")
        account_id = fiche.get("account_id")
        client_id = fiche.get("_id")

    entete["langue"] = langue
    entete["segment"] = segment
    territoire = {
        "present": True,
        # AFF-04 dans le nom meme du champ : rattache, jamais « actif chez ».
        "rattachement": territoire_local,
        "adresse": adresse,
    }

    # ── Blocs C et E — compte et epargne, EN PARALLELE ────────────────────
    async def _bloc_compte() -> dict[str, Any]:
        if fiche is None:
            return _bloc_absent(raison_fiche or "fiche indisponible")
        if not account_id:
            return _bloc_absent("la fiche ne référence aucun compte")
        comptes = _client_comptes()
        try:
            document = await comptes.compte(account_id)
            if document is None:
                return _bloc_absent("le compte référencé est introuvable")
            # AFF-01 — le solde AFFICHE est celui-ci, RELU : jamais une somme
            # d'operations (les frais sont retranches et credites nulle part).
            return {"present": True, **document}
        except Exception:
            logger.exception("dossier %s : compte illisible", numero)
            return _bloc_absent("le service des comptes ne répond pas")
        finally:
            await comptes.fermer()

    async def _bloc_epargne() -> dict[str, Any]:
        if fiche is None or not client_id:
            return _bloc_absent(raison_fiche or "fiche indisponible")
        collectes = _client_collectes()
        try:
            lignes = await collectes.collectes_du_client(client_id)
            return {
                "present": True,
                "collectes": lignes,
                # Spec §3.3 — l'absence est EXPLIQUEE : une section vide sans
                # raison laisse croire a un defaut.
                "note": (
                    "aucune épargne : les collectes et versements arriveront "
                    "avec le module de vie financière"
                )
                if not lignes
                else None,
            }
        except Exception:
            logger.exception("dossier %s : collectes illisibles", numero)
            return _bloc_absent("le service des collectes ne répond pas")
        finally:
            await collectes.fermer()

    compte, epargne = await asyncio.gather(_bloc_compte(), _bloc_epargne())

    return {
        "entete": entete,
        "identite": identite,
        "territoire": territoire,
        "compte": compte,
        "produits": produits,
        "epargne": epargne,
        # Le releve ne se charge PAS avec le dossier (spec §5.3) : une ligne
        # aujourd'hui, des dizaines avec le module de vie — il se demande.
        "releve": {"disponible": bool(account_id), "route": f"/admin/attributions/{numero}/releve"},
    }


@router.get("/{msisdn}/releve")
async def releve_du_client(
    _: Annotated[SessionAdmin, Depends(exige_admin)],
    msisdn: Annotated[str, Path(min_length=6, max_length=20)],
) -> dict[str, Any]:
    """L'historique des operations du compte — source D de l'inventaire,
    `GET /accounts/{id}/transactions`, A LA DEMANDE (spec §5.3 : le releve
    ne se charge pas avec le dossier).

    Les lignes sont rendues TELLES QUELLES — montant, frais, libelle humain,
    statut. Jamais leur somme : `AFF-01`, le solde est ailleurs et il est
    RELU.
    """
    numero = msisdn.strip()
    bail = await AttributionBauxRepository().par_msisdn(numero)
    if bail is None:
        raise HTTPException(
            status_code=404,
            detail=f"aucun bail (même échu) ne porte le numéro {numero}",
        )

    clients = _client_clients()
    try:
        fiche = await clients.chercher_par_msisdn(numero)
    finally:
        await clients.fermer()
    if fiche is None or not fiche.get("account_id"):
        return {"operations": _bloc_absent("la plateforme ne référence aucun compte")}

    comptes = _client_comptes()
    try:
        lignes = await comptes.transactions_du_compte(str(fiche["account_id"]))
    except Exception:
        logger.exception("releve %s : transactions illisibles", numero)
        return {"operations": _bloc_absent("le service des comptes ne répond pas")}
    finally:
        await comptes.fermer()

    return {
        "operations": {"present": True, "lignes": lignes, "total": len(lignes)},
        "note": "solde affiché ailleurs, RELU du compte — jamais une somme de ces lignes (AFF-01)",
    }


# ──────────────────────────────────────────────────────────────────────────
# 7. La revocation MULTIPLE — spec §8, la fin d'etape de campagne
# ──────────────────────────────────────────────────────────────────────────


class DemandeRevocations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    msisdns: list[str] = Field(min_length=1, max_length=100)
    motif: str = Field(min_length=3, max_length=280)


@router.post("/revocations")
async def revoquer_plusieurs(
    demande: DemandeRevocations,
    session: Annotated[SessionAdmin, Depends(exige_super_admin)],
) -> dict[str, Any]:
    """Rompt PLUSIEURS baux d'un geste — la fin d'etape de campagne (spec
    §8 : sans elle, l'operateur libere un par un, finit par ne plus le
    faire, et les numeros restent immobilises sept jours pour rien).

    ISSUE PAR NUMERO, jamais un echec global muet — le motif exact de
    l'adoption A-13 : `revoque` ou `aucun_bail_actif`, chacun journalise
    individuellement. Un numero introuvable n'empeche pas les autres de
    partir. Meme garde que la revocation unitaire : `super_admin`, motif
    obligatoire, et le meme chemin de repository — `revoquer()`, atomique
    par numero.
    """
    motif = demande.motif.strip()
    depot = AttributionBauxRepository()
    audit = AuditTrailRepository()
    issues: list[dict[str, Any]] = []
    for brut in demande.msisdns:
        numero = brut.strip()
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
                "origine": ORIGINE_ADMINISTRATION,
                "lot": len(demande.msisdns),
            },
        ) as suivi:
            document = await depot.revoquer(numero)
            if document is None:
                suivi.echoue("aucun bail actif sur ce numéro")
                issues.append({"msisdn": numero, "issue": "aucun_bail_actif"})
            else:
                suivi.reussi({"attribution_id": str(document["attribution_id"])})
                issues.append(
                    {
                        "msisdn": numero,
                        "issue": "revoque",
                        "attribution_id": str(document["attribution_id"]),
                    }
                )

    revoques = sum(1 for issue in issues if issue["issue"] == "revoque")
    return {
        "issues": issues,
        "revoques": revoques,
        "sans_bail": len(issues) - revoques,
        "note": (
            "issue par numéro — un numéro sans bail actif n'empêche pas les "
            "autres de partir ; chaque geste est journalisé individuellement"
        ),
    }


# ──────────────────────────────────────────────────────────────────────────
# 8. Le journal d'attribution — les événements du domaine, rôle admin
# ──────────────────────────────────────────────────────────────────────────


@router.get("/journal")
async def journal_attribution(
    _: Annotated[SessionAdmin, Depends(exige_admin)],
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """Les evenements d'ATTRIBUTION seulement — attributions, liberations
    (avec leur ORIGINE : rendu par l'appareil / repris depuis
    l'administration), refus, nommages (spec §5.5).

    POURQUOI PAS `/admin/journal` : il est reserve au super_admin — voir
    l'activite d'administration ENTIERE (comptes, roles) est une capacite
    sensible — et il melange tous les gestes. Le tableau de bord
    d'attribution est en lecture `admin` (arbitrage 27/08) et n'a besoin
    QUE de son domaine : ce filtre par entite EST la frontiere de ce que ce
    role peut voir. Meme vue ligne a ligne que le journal general — jamais
    une seconde convention d'affichage.
    """
    from app.routes.admin_journal import _vue

    entrees = await AuditTrailRepository().lister_admin(
        limite, entites={"AttributionBail", "AttributionRefus"}
    )
    return {
        "entrees": [_vue(entree, resultat) for entree, resultat in entrees],
        "total": len(entrees),
        "note": (
            "événements d'attribution seulement — attributions, libérations "
            "avec leur origine, refus ; lecture seule, 30 jours de rétention"
        ),
    }
