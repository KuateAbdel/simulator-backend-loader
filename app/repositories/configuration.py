"""
app/repositories/configuration.py
=================================
La configuration COURANTE du Loader — celle que le Super-Admin edite
(`US-B1`/`US-B2`/`US-B3`) et que le prochain run lance par l'API utilisera.

UN document singleton (`_id="courante"`), VERSIONNE : chaque `PUT` incremente
`version` et trace qui a modifie, quand. Ce n'est pas un journal complet —
l'historique fige vit dans `LoaderRun.configuration` (D-10), run par run. La
collection porte l'INTENTION courante ; le run, le FAIT execute.

En l'absence de document, la configuration est celle du CDC (`defaut_cdc()`),
version 0 : l'etat initial n'est pas un cas d'erreur, c'est le contrat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.configuration import ConfigurationExecution
from app.core.database import COLLECTION_LOADER_CONFIGURATION, get_collection

_ID_SINGLETON = "courante"


class ConfigurationRepository:
    @property
    def collection(self) -> Any:
        return get_collection(COLLECTION_LOADER_CONFIGURATION)

    async def charger(self) -> tuple[ConfigurationExecution, dict[str, Any]]:
        """Rend (configuration, meta). Sans document : le defaut CDC, version 0."""
        document = await self.collection.find_one({"_id": _ID_SINGLETON})
        if document is None:
            return ConfigurationExecution.defaut_cdc(), {
                "version": 0,
                "modifie_par": None,
                "modifie_le": None,
            }
        configuration = ConfigurationExecution.depuis_empreinte(document["empreinte"])
        return configuration, {
            "version": int(document.get("version", 0)),
            "modifie_par": document.get("modifie_par"),
            "modifie_le": document.get("modifie_le"),
        }

    async def enregistrer(
        self, configuration: ConfigurationExecution, *, par: str
    ) -> dict[str, Any]:
        """Persiste et rend les nouvelles meta. `$inc` rend la version atomique."""
        maintenant = datetime.now(tz=UTC).isoformat()
        await self.collection.update_one(
            {"_id": _ID_SINGLETON},
            {
                "$set": {
                    "empreinte": configuration.empreinte(),
                    "modifie_par": par,
                    "modifie_le": maintenant,
                },
                "$inc": {"version": 1},
            },
            upsert=True,
        )
        document = await self.collection.find_one({"_id": _ID_SINGLETON})
        return {
            "version": int(document["version"]) if document else 1,
            "modifie_par": par,
            "modifie_le": maintenant,
        }
