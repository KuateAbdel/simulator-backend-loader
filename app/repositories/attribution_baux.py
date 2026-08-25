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
from typing import Any
from uuid import UUID, uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.database import COLLECTION_ATTRIBUTION_BAUX, get_collection

#: La duree du bail — CDC : sept jours, constante nommee et non parametre
#: (arbitrage §10.3 de la conception : un parametre inviterait a la derive
#: sans exigence qui le demande).
BAIL_JOURS = 7


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
            "attribue_le": maintenant,
            "expire_le": maintenant + timedelta(days=BAIL_JOURS),
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


def normaliser_bail(document: dict[str, Any]) -> dict[str, Any]:
    """Le corps de reponse du contrat (§2 et §3) — quatre champs, dates ISO."""
    return {
        "attribution_id": str(document["attribution_id"]),
        "msisdn": str(document["_id"]),
        "attribue_le": _en_datetime(document["attribue_le"]).isoformat(),
        "expire_le": _en_datetime(document["expire_le"]).isoformat(),
    }


RUN_ADMIN_ATTRIBUTION = UUID(int=0)
