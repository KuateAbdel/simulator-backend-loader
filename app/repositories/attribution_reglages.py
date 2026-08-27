"""
app/repositories/attribution_reglages.py
========================================
Le REGLAGE de la duree du bail — contrat `FZ-CONTRAT-ATTRIB-2026-001` v0.4
§(b) : « les sept jours cessent d'etre une constante gravee pour devenir un
REGLAGE d'administration — valeur globale, surchargeable par pays, bornee 1 a
30 jours, resolue AU MOMENT du tirage ».

UN document singleton (`_id="courant"`) dans SA PROPRE collection,
`attribution_reglages`. Le rangement est le sujet : **ce reglage n'a rien a
voir avec le Loader qui execute.** Il ne vit pas dans `loader_configuration`,
ou dorment la configuration d'un run (`_id="courante"`,
`ConfigurationExecution`), la surcouche referentielle et le registre produits.
Un bail ne decide d'aucune population, d'aucun rattachement, d'aucun quota, et
aucun run ne le lit. Deux sujets, deux collections.

Elle est declaree PROTEGEE de la purge (`admin_purge.COLLECTIONS_PROTEGEES`) :
un reglage est le travail de l'operateur, jamais un sous-produit d'execution —
et l'ecran de purge doit le MONTRER dans la colonne protegee, comme il montre
deja les 48 pays.

En l'absence de document, la valeur est celle du CDC (sept jours), version 0 :
l'etat initial n'est pas un cas d'erreur, c'est le contrat — doctrine mot pour
mot de `ConfigurationRepository.charger`.

**CE QUE CE MODULE NE FERA JAMAIS : toucher a un bail existant.** Un bail est
une PROMESSE DATEE (revision 0.4, option 1 tranchee a la redaction du
contrat) : son `expire_le` est ecrit au tirage et ne se relit pas a la lumiere
d'un reglage change apres coup. Ramener la duree a un jour ne raccourcit aucun
bail en cours — le reglage vaut pour les tirages SUIVANTS. C'est aussi ce qui
rend le geste sans danger pour les appareils en main de l'equipe QA.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from app.core.database import COLLECTION_ATTRIBUTION_REGLAGES, get_collection

logger = logging.getLogger(__name__)

#: La duree du CDC — desormais un DEFAUT et non plus une constante gravee.
BAIL_JOURS_DEFAUT: Final = 7

#: Les bornes du contrat 0.4 §(b), inclusives. En deca d'un jour un bail
#: n'aurait pas le temps de servir ; au dela de trente il immobilise le pool
#: plus longtemps que ne dure une recette.
BORNE_MIN: Final = 1
BORNE_MAX: Final = 30

_ID_SINGLETON: Final = "courant"


class DureeHorsBornes(ValueError):
    """Une duree refusee — la route la traduit en 422 avec son message."""


def valider_duree(jours: Any, *, ou: str) -> int:
    """Rend la duree en entier, ou refuse. `ou` nomme l'endroit du refus
    (« la valeur globale », « la surcharge du pays BF ») : un message qui ne
    dit pas OU l'operateur s'est trompe le laisse chercher."""
    if isinstance(jours, bool) or not isinstance(jours, int):
        raise DureeHorsBornes(f"{ou} doit être un nombre entier de jours")
    if not BORNE_MIN <= jours <= BORNE_MAX:
        raise DureeHorsBornes(
            f"{ou} vaut {jours} — la durée d'un bail est bornée de "
            f"{BORNE_MIN} à {BORNE_MAX} jours (contrat 0.4 §b)"
        )
    return int(jours)


@dataclass(frozen=True)
class ReglagesBail:
    """La valeur globale et ses surcharges par pays."""

    jours_defaut: int = BAIL_JOURS_DEFAUT
    par_pays: dict[str, int] = field(default_factory=dict)

    def jours_pour(self, pays: str) -> int:
        """LA RESOLUTION DU CONTRAT (§b) : la surcharge du pays si elle
        existe, sinon la valeur globale. Appelee AU MOMENT DU TIRAGE — jamais
        mise en cache : un reglage change entre deux attributions doit valoir
        des l'attribution suivante, sans redemarrage."""
        return int(self.par_pays.get(pays.strip().upper(), self.jours_defaut))

    def en_vue(self) -> dict[str, Any]:
        return {
            "jours_defaut": self.jours_defaut,
            "par_pays": dict(sorted(self.par_pays.items())),
        }


class ReglagesBailRepository:
    @property
    def collection(self) -> Any:
        return get_collection(COLLECTION_ATTRIBUTION_REGLAGES)

    async def charger(self) -> tuple[ReglagesBail, dict[str, Any]]:
        """Rend (reglages, meta). Sans document : le defaut CDC, version 0.

        LECTURE DEFENSIVE. La route `PUT` valide tout ce qui passe par elle,
        mais elle n'est pas le seul chemin vers ce document : une correction
        a la main dans Mongo, une restauration de sauvegarde, une migration
        ratee, et le document porte `"sept"` ou `-3`. Le tirage lit alors une
        valeur que personne n'a validee.

        Une valeur illisible ou hors bornes est donc IGNOREE, jamais
        propagee : la globale retombe sur le defaut du CDC, la surcharge
        fautive disparait (le pays suit la globale). On journalise l'anomalie
        — un reglage silencieusement ignore serait pire que le mauvais
        reglage lui-meme.
        """
        document = await self.collection.find_one({"_id": _ID_SINGLETON})
        if document is None:
            return ReglagesBail(), {
                "version": 0,
                "modifie_par": None,
                "modifie_le": None,
            }

        brut_defaut = document.get("jours_defaut", BAIL_JOURS_DEFAUT)
        try:
            jours_defaut = valider_duree(brut_defaut, ou="la valeur globale")
        except DureeHorsBornes as anomalie:
            logger.warning(
                "reglage de bail illisible en base (%r) — retour au defaut "
                "du CDC (%d j) : %s",
                brut_defaut,
                BAIL_JOURS_DEFAUT,
                anomalie,
            )
            jours_defaut = BAIL_JOURS_DEFAUT

        par_pays: dict[str, int] = {}
        for code, brut in (document.get("par_pays") or {}).items():
            pays = str(code).strip().upper()
            try:
                par_pays[pays] = valider_duree(brut, ou=f"la surcharge du pays {pays}")
            except DureeHorsBornes as anomalie:
                logger.warning(
                    "surcharge de bail illisible pour %s (%r) — le pays suit "
                    "la valeur globale : %s",
                    pays,
                    brut,
                    anomalie,
                )

        reglages = ReglagesBail(jours_defaut=jours_defaut, par_pays=par_pays)
        return reglages, {
            "version": int(document.get("version", 0)),
            "modifie_par": document.get("modifie_par"),
            "modifie_le": document.get("modifie_le"),
        }

    async def enregistrer(self, reglages: ReglagesBail, *, par: str) -> dict[str, Any]:
        """Persiste et rend les nouvelles meta. `$inc` rend la version
        atomique — deux operateurs qui enregistrent en meme temps produisent
        deux versions distinctes, jamais une version perdue."""
        maintenant = datetime.now(tz=UTC).isoformat()
        await self.collection.update_one(
            {"_id": _ID_SINGLETON},
            {
                "$set": {
                    "jours_defaut": reglages.jours_defaut,
                    "par_pays": dict(reglages.par_pays),
                    "modifie_par": par,
                    "modifie_le": maintenant,
                },
                "$inc": {"version": 1},
            },
            upsert=True,
        )
        document = await self.collection.find_one({"_id": _ID_SINGLETON})
        return {
            "version": int((document or {}).get("version", 1)),
            "modifie_par": par,
            "modifie_le": maintenant,
        }


async def jours_pour_le_tirage(pays: str) -> int:
    """La duree applicable a CE tirage — **et cette fonction ne leve JAMAIS**.

    C'est le fail-safe du mecanisme. La duree du bail est un REGLAGE DE
    CONFORT : elle rend le bail plus court ou plus long, elle ne decide de
    rien d'essentiel. Le tirage, lui, est le coeur — c'est lui qui donne un
    numero a un partenaire qui attend, ecran allume.

    Laisser une base momentanement injoignable, un document illisible ou une
    collection absente faire echouer une ATTRIBUTION reviendrait a couper le
    service pour proteger un detail. On applique donc mot pour mot la doctrine
    deja ecrite pour le champ `appareil` au contrat 0.4 : « un champ de confort
    ne doit jamais faire echouer une attribution ». En cas de doute, sept
    jours — la valeur du CDC, celle qui a tourne en production jusqu'ici.
    """
    try:
        reglages, _meta = await ReglagesBailRepository().charger()
        return reglages.jours_pour(pays)
    except Exception:
        logger.exception(
            "reglage de duree illisible — le tirage continue avec le defaut "
            "du CDC (%d jours)",
            BAIL_JOURS_DEFAUT,
        )
        return BAIL_JOURS_DEFAUT
