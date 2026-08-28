"""
app/repositories/attribution_baux.py
====================================
Les BAUX d'attribution du simulateur USSD — la face serveur du contrat
`FZ-CONTRAT-ATTRIB-2026-001 v0.3.1` (docs/CONTRAT_ATTRIBUTION_USSD.md), selon
la conception validee `docs/CONCEPTION_ATTRIBUTION_USSD.md`.

Un bail = UN msisdn attribue a UN appareil pour sept jours. La collection est
`_id = msisdn` : l'unicite d'`INV-SIM-01` n'est pas un algorithme, c'est
l'index primaire de Mongo — le marquage EST le tirage, celui dont l'insertion
passe a tire. Aucune fenetre lecture/ecriture n'existe, quel que soit le
nombre d'appareils simultanes (`CR-06`).

L'EXPIRATION EST PASSIVE (§5 de la conception) : `expire_le < now` EST l'etat
libre. Aucun code ne s'execute a l'echeance, aucun drapeau ne bascule — la
verite est calculee a chaque lecture, et l'horloge du SERVEUR est la seule
autorite. Le TTL Mongo (30 jours apres l'echeance) reste un concierge qui
ramasse les documents morts, jamais un arbitre — mot pour mot la doctrine de
`verrous.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.database import COLLECTION_ATTRIBUTION_BAUX, get_collection
from app.repositories.attribution_reglages import BAIL_JOURS_DEFAUT

#: La duree du bail — SEPT JOURS RESTE LE DEFAUT, plus la loi. L'arbitrage
#: §10.3 de la conception (« un parametre inviterait a la derive sans exigence
#: qui le demande ») a ete LEVE par la revision 0.4 du contrat : l'exigence
#: existe desormais, l'exploitation doit pouvoir raccourcir un bail sans
#: livraison. La valeur applicable est resolue AU TIRAGE par
#: `ReglagesBail.jours_pour(pays)` et passee a `acquerir` ; ce defaut ne sert
#: que lorsque l'appelant n'en fournit aucune.
BAIL_JOURS = BAIL_JOURS_DEFAUT


def _maintenant() -> datetime:
    """L'horloge du serveur, TRONQUEE A LA MILLISECONDE — la precision de
    Mongo. Sans cela, le 201 d'origine (memoire, microsecondes) et son rejeu
    (relu de la base, millisecondes) different d'un cheveu, et « la meme
    reponse » du contrat §2 devient fausse au sens strict."""
    maintenant = datetime.now(UTC)
    return maintenant.replace(microsecond=(maintenant.microsecond // 1000) * 1000)


def _en_datetime(valeur: Any) -> datetime:
    """Mongo rend des datetimes naifs UTC — on les re-qualifie, jamais on ne
    compare un naif a un conscient."""
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(valeur))


class AttributionBauxRepository:
    @property
    def collection(self) -> Any:
        return get_collection(COLLECTION_ATTRIBUTION_BAUX)

    # ── Lectures ───────────────────────────────────────────────────────────

    async def par_cle_idempotence(self, cle: str) -> dict[str, Any] | None:
        """Le REJEU (contrat §2) : une cle deja vue rend le bail d'origine,
        sans second tirage. C'est la moitie de la reponse au trou de
        l'attribution perdue — l'autre moitie est cote application, qui
        persiste sa cle des l'emission (revision 0.3.1)."""
        document: dict[str, Any] | None = await self.collection.find_one(
            {"cle_idempotence": cle}
        )
        return document

    async def par_attribution_id(self, attribution_id: str) -> dict[str, Any] | None:
        document: dict[str, Any] | None = await self.collection.find_one(
            {"attribution_id": attribution_id}
        )
        return document

    async def actifs_parmi(self, msisdns: list[str]) -> set[str]:
        """Les msisdn OCCUPES maintenant — expiration passive : un bail echu
        n'apparait pas ici, donc il est libre, sans qu'aucun code ne l'ait
        « libere »."""
        if not msisdns:
            return set()
        curseur = self.collection.find(
            {"_id": {"$in": msisdns}, "expire_le": {"$gt": _maintenant()}},
            {"_id": 1},
        )
        return {str(d["_id"]) async for d in curseur}

    async def actifs_par_profil(self) -> dict[tuple[str, str, str], int]:
        """Compte des baux actifs par (pays, genre, categorie) — sert la
        colonne `libres` de `GET /criteres`."""
        pipeline = [
            {"$match": {"expire_le": {"$gt": _maintenant()}}},
            {
                "$group": {
                    "_id": {
                        "pays": "$profil.pays",
                        "genre": "$profil.genre",
                        "categorie": "$profil.categorie",
                    },
                    "n": {"$sum": 1},
                }
            },
        ]
        comptes: dict[tuple[str, str, str], int] = {}
        async for d in self.collection.aggregate(pipeline):
            cle = (d["_id"]["pays"], d["_id"]["genre"], d["_id"]["categorie"])
            comptes[cle] = int(d["n"])
        return comptes

    async def lister_actifs(self) -> list[dict[str, Any]]:
        """Les baux ACTIFS, les plus recents d'abord — le recensement
        d'exploitation (25/08 : chasse aux baux orphelins nes du defaut de
        sequence FZ-DIAG-BAIL-2026-001). Rend les documents complets, cle
        d'idempotence comprise : c'est elle qui dit si deux baux viennent de
        deux TENTATIVES distinctes du meme appareil."""
        curseur = self.collection.find({"expire_le": {"$gt": _maintenant()}}).sort(
            "attribue_le", -1
        )
        return [d async for d in curseur]

    async def par_msisdn(self, msisdn: str) -> dict[str, Any] | None:
        """Le bail de CE numero, actif OU echu — la cle d'entree du dossier
        client (FZ-INV-ATTRIB §8 : « une seule cle d'entree, le msisdn »).
        Un bail echu reste lisible 30 jours (TTL) : le dossier d'un numero
        rendu hier se consulte encore — c'est l'echelle de la campagne."""
        document: dict[str, Any] | None = await self.collection.find_one({"_id": msisdn})
        return document

    async def lister(self, etat: str = "actifs") -> list[dict[str, Any]]:
        """Le recensement, par ETAT — `actifs` (l'existant), `echus` (les
        baux morts que le TTL n'a pas encore ramasses, la matiere de
        l'historique), ou `tous`. Les plus recents d'abord, comme
        `lister_actifs` — dont le comportement ne bouge pas d'un octet."""
        if etat == "actifs":
            return await self.lister_actifs()
        filtre: dict[str, Any] = {}
        if etat == "echus":
            filtre = {"expire_le": {"$lte": _maintenant()}}
        curseur = self.collection.find(filtre).sort("attribue_le", -1)
        return [d async for d in curseur]

    async def nommer_interlocuteur(
        self, msisdn: str, interlocuteur: str | None
    ) -> dict[str, Any] | None:
        """Pose (ou efface) le LIBELLE LIBRE de l'operateur — « le bail de
        M. Diallo » (spec §5.2, colonne Interlocuteur ; §7, la recherche la
        plus frequente d'une campagne).

        CHAMP ADDITIF, ecrit par la seule administration : le mecanisme
        public ne le lit ni ne l'ecrit jamais — `acquerir` n'en connait pas
        l'existence, un rejeu d'idempotence le laisse intact (le rejeu relit
        le document, il ne le reecrit pas). Rend le document a jour, ou None
        si aucun bail (meme echu) ne porte ce numero."""
        document: dict[str, Any] | None = await self.collection.find_one_and_update(
            {"_id": msisdn},
            {"$set": {"interlocuteur": interlocuteur}},
            return_document=ReturnDocument.AFTER,
        )
        return document

    async def etat_pour_purge(self) -> dict[str, Any]:
        """`§1.5` de la conception — ce que la garde de purge doit dire :
        combien de baux actifs, et jusqu'a quand court le plus long. Jamais
        un refus muet."""
        actifs = 0
        plus_longue: datetime | None = None
        async for d in self.collection.find(
            {"expire_le": {"$gt": _maintenant()}}, {"expire_le": 1}
        ):
            actifs += 1
            echeance = _en_datetime(d["expire_le"])
            if plus_longue is None or echeance > plus_longue:
                plus_longue = echeance
        return {
            "actifs": actifs,
            "plus_longue_echeance": plus_longue.isoformat() if plus_longue else None,
        }

    # ── L'acquisition — le geste atomique ─────────────────────────────────

    async def acquerir(
        self,
        msisdn: str,
        *,
        cle_idempotence: str,
        profil: dict[str, str],
        appareil: str | None = None,
        jours: int | None = None,
        os: str | None = None,
    ) -> dict[str, Any] | None:
        """Tente de prendre CE msisdn. Rend le bail, ou None s'il est occupe.

        LE MARQUAGE EST LE TIRAGE (§3 de la conception). Deux appareils sur le
        meme msisdn : un seul `insert_one` passe, l'autre recoit
        `DuplicateKeyError` et l'appelant essaie le candidat suivant — jamais
        d'attente, jamais deux gagnants. Sur un bail ECHU, le
        `find_one_and_update` filtre sur l'echeance : lui aussi est indivisible
        cote Mongo, et deux voleurs de bail echu n'en font qu'un.
        """
        maintenant = _maintenant()
        bail = {
            "_id": msisdn,
            "attribution_id": str(uuid4()),
            "cle_idempotence": cle_idempotence,
            "profil": dict(profil),
            # Contrat 0.4 — etiquette d'exploitation (« Redmi Note 13 »),
            # optionnelle, JAMAIS un identifiant : deux telephones identiques
            # portent la meme valeur.
            "appareil": appareil,
            # Le TYPE d'OS (28/08, Direction) — DEDUIT du User-Agent par le
            # serveur, jamais demande a l'application : android / ios / None.
            # Une metadonnee de connexion, pas un identifiant (contrat 0.4a).
            "os": os,
            "attribue_le": maintenant,
            # Contrat 0.4 §(b) — la duree est RESOLUE AU TIRAGE et FIGEE ici.
            # Ce que ce champ porte est une promesse datee : aucun reglage
            # ulterieur ne la relira (option 1 de la revision).
            "expire_le": maintenant + timedelta(days=jours or BAIL_JOURS_DEFAUT),
        }
        try:
            await self.collection.insert_one(bail)
            return bail
        except DuplicateKeyError:
            pris: dict[str, Any] | None = await self.collection.find_one_and_update(
                {"_id": msisdn, "expire_le": {"$lt": maintenant}},  # ECHU seulement
                {"$set": {k: v for k, v in bail.items() if k != "_id"}},
                return_document=ReturnDocument.AFTER,
            )
            return pris  # None = bail ACTIF : candidat suivant

    # ── La liberation — EF-17, contrat §4 ─────────────────────────────────

    async def liberer(self, attribution_id: str) -> dict[str, Any] | None:
        """Rompt le bail par sa poignee. Rend le document supprime s'il etait
        encore ACTIF, None sinon — le contrat fait du 404 un succes
        fonctionnel, c'est l'appelant qui traduit."""
        document: dict[str, Any] | None = await self.collection.find_one_and_delete(
            {"attribution_id": attribution_id}
        )
        if document is None:
            return None
        if _en_datetime(document["expire_le"]) <= _maintenant():
            return None  # deja echu : fonctionnellement, il n'existait plus
        return document

    # ── La REVOCATION — le geste de l'administration ──────────────────────

    async def revoquer(self, msisdn: str) -> dict[str, Any] | None:
        """Rompt le bail par son MSISDN — la poignee de l'administration.

        Deux differences deliberees avec `liberer` (le geste de l'appareil) :

        1. **La cle est le msisdn**, pas l'`attribution_id`. L'operateur voit
           un numero dans le recensement ; exiger la poignee de l'appareil le
           forcerait a la deviner. C'est exactement ce qui a bloque la chasse
           au bail orphelin du 25/08.
        2. **Le filtre porte sur l'echeance** : seul un bail ACTIF se revoque.
           Un bail echu est deja libre — le supprimer ne changerait rien et
           ferait mentir le journal, qui inscrirait une revocation la ou il
           ne s'est rien passe. Le `find_one_and_delete` reste indivisible :
           deux operateurs sur le meme bail, un seul obtient le document.

        L'appareil n'est pas prevenu — aucune notification n'existe (`ENF-05`,
        et le contrat n'ouvre aucun canal descendant). Il le decouvre a sa
        prochaine verification (`GET /attributions/{id}` -> 404), et sa
        conduite est celle de l'expiration : ecran 13, retour a la
        composition. C'est le meme chemin, deja prouve.
        """
        document: dict[str, Any] | None = await self.collection.find_one_and_delete(
            {"_id": msisdn, "expire_le": {"$gt": _maintenant()}}
        )
        return document


def normaliser_bail(document: dict[str, Any]) -> dict[str, Any]:
    """Le corps de reponse du contrat (§2 et §3) — quatre champs, dates ISO."""
    return {
        "attribution_id": str(document["attribution_id"]),
        "msisdn": str(document["_id"]),
        "attribue_le": _en_datetime(document["attribue_le"]).isoformat(),
        "expire_le": _en_datetime(document["expire_le"]).isoformat(),
    }


RUN_ADMIN_ATTRIBUTION = UUID(int=0)

# ── L'ORIGINE d'un geste sur un bail ──────────────────────────────────────
#
# Liberation par l'appareil (`EF-17`) et revocation par l'administration font
# la MEME CHOSE au bail : il disparait, le client retourne au pool. Ce n'est
# pas un doublon — c'est le meme effet par deux VOLONTES differentes, et au
# journal cette difference est l'information : « le partenaire a rendu le
# numero » et « on le lui a repris » ne se lisent pas pareil.
#
# L'origine est donc ECRITE, jamais deduite. Avant le 27/08 elle etait
# INFEREE a l'affichage (« pas d'auteur dans la trace, donc c'est l'app »),
# ce qui tenait tant qu'un seul chemin existait. Des lors que l'administration
# peut agir, une deduction devient un pari.
ORIGINE_APPAREIL: Final = "appareil"
ORIGINE_ADMINISTRATION: Final = "administration"

#: Les libelles d'affichage — le journal parle a un exploitant, pas a un code.
LIBELLE_ORIGINE: Final = {
    ORIGINE_APPAREIL: "simulateur USSD (route publique)",
    ORIGINE_ADMINISTRATION: "administration du Loader",
}
