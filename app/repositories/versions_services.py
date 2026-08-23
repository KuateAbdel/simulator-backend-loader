"""
app/repositories/versions_services.py
=====================================
`V-01` — le RELEVE DE VERSION des services avec lesquels le Loader travaille.

Afficher une version ne sert pas a grand-chose. Ce qui sert, c'est de savoir
qu'elle a CHANGE : nos neuf clients sont ecrits contre des contrats MESURES
(les audits `docs/empirical/`). Le jour ou `client-service` gagne quatre
chemins, quelque chose a bouge dans le contrat — et on doit l'apprendre AVANT
un run, pas pendant.

D'ou l'historique. Sans lui, on ne peut dire que « voila la version » ; avec
lui, on peut dire « elle a monte depuis le dernier passage », ce qui est la
seule information qui demande une action.

DEUX CAS SE RESSEMBLENT ET N'ONT PAS LA MEME GRAVITE
----------------------------------------------------
  version qui monte          le contrat a change, et le service le DIT
  chemins qui changent       le contrat a change, et le service ne le dit
  a version identique        PAS — c'est le pire des deux, et personne ne
                             l'aurait vu sans ce relevé

Un document par service, son relevé courant et son historique borne. On lit
les dix d'un coup pour l'ecran : un document par service est la forme qui
rend cette lecture directe.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.core.database import COLLECTION_VERSIONS_SERVICES, get_collection

#: Profondeur d'historique gardee par service. Vingt relevés a trois heures
#: couvrent deux jours et demi — assez pour dire « ca a change hier soir »,
#: assez peu pour que le document reste petit.
PROFONDEUR_HISTORIQUE = 20


class VersionsServicesRepository:
    @property
    def collection(self) -> Any:
        return get_collection(COLLECTION_VERSIONS_SERVICES)

    async def dernier_releve(self) -> dict[str, dict[str, Any]]:
        """{service: document} — une seule lecture pour les dix services."""
        curseur = self.collection.find({})
        return {str(doc["_id"]): doc async for doc in curseur}

    async def age_du_cache(self) -> float | None:
        """Age du relevé le plus ANCIEN, en secondes. `None` si jamais releve.

        Le plus ancien, pas le plus recent : un tableau n'est frais que si sa
        ligne la plus vieille l'est.
        """
        vieux: datetime | None = None
        async for doc in self.collection.find({}, {"releve_le": 1}):
            quand = doc.get("releve_le")
            if not isinstance(quand, datetime):
                return None
            if quand.tzinfo is None:
                quand = quand.replace(tzinfo=UTC)
            if vieux is None or quand < vieux:
                vieux = quand
        if vieux is None:
            return None
        return (datetime.now(UTC) - vieux).total_seconds()

    async def enregistrer(self, service: str, releve: dict[str, Any]) -> dict[str, Any]:
        """Range un relevé et rend le PRECEDENT — c'est lui qui permet la
        comparaison. Le premier relevé d'un service n'a pas de precedent, et
        ce n'est pas une anomalie : on ne compare pas ce qu'on voit pour la
        premiere fois.
        """
        maintenant = datetime.now(UTC)
        existant = await self.collection.find_one({"_id": service}) or {}
        precedent = {
            cle: existant.get(cle)
            for cle in ("version", "titre", "chemins", "operations")
            if cle in existant
        }

        # UN SERVICE MUET N'EFFACE PAS SA VERSION.
        #
        # Correction de conception (Yaniv, 23/08) : « injoignable » est deja
        # dit par le tableau de bord, en vert et rouge, et en DIRECT. Le
        # repeter ici serait une duplication — et surtout, une version ne
        # disparait pas parce que le service redemarre. On garde donc la
        # derniere valeur CONNUE, et seule sa DATE vieillit : c'est la
        # fraicheur qui se degrade, pas l'information.
        if not releve.get("joignable") and existant.get("version"):
            releve = {
                cle: existant.get(cle)
                for cle in ("titre", "version", "chemins", "operations")
            }
            releve["joignable"] = True
            document = {
                **existant,
                **releve,
                "derniere_tentative": maintenant,
            }
            await self.collection.replace_one({"_id": service}, document, upsert=True)
            return precedent

        historique = list(existant.get("historique") or [])
        change = bool(precedent) and any(
            precedent.get(cle) != releve.get(cle)
            for cle in ("version", "chemins", "operations")
        )
        if change or not historique:
            # On n'empile QUE les relevés qui apportent une information : vingt
            # lignes identiques ne disent rien, et noieraient le changement.
            historique.append({**releve, "releve_le": maintenant})
            historique = historique[-PROFONDEUR_HISTORIQUE:]

        document = {
            "_id": service,
            **releve,
            "releve_le": maintenant,
            "derniere_tentative": maintenant,
            "vu_stable_depuis": (
                existant.get("vu_stable_depuis", maintenant) if not change else maintenant
            ),
            "historique": historique,
        }
        await self.collection.replace_one({"_id": service}, document, upsert=True)
        return precedent
