"""
app/clients/config_service.py
=============================
Client config-service — LECTURE SEULE, sans aucune exception.

Principe architectural (09_activity.puml, Phase 1) : le referentiel
(4 pays, devises, telcos) est STABLE. Il a ete peuple une seule fois par
`loader_config_service.py`. A chaque execution du Loader, il est LU pour
valider la coherence de ce qu'on cree ailleurs — jamais reecrit. Le
repeupler a chaque run n'aurait aucun sens : ce sont des donnees statiques.

Ce module n'expose donc aucune methode d'ecriture. Ce n'est pas un oubli.

Ce que config-service contient REELLEMENT (Confluence « Anomalies
config-service », 06/06/2026) : 3 entites seulement — Country, Currency,
Telco. `Country.cities[]` est un simple tableau de TEXTE LIBRE. Aucune entite
Region/City/District n'existe ici. L'arbre enrichi du Loader (51 regions,
50 villes, 82 quartiers) vit dans Loader_Base_FinZuu_v1_1.xlsx et n'est
JAMAIS pousse ici.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.core.cdc import PAYS_CIBLES
from app.core.config import settings


@dataclass(slots=True)
class RapportReferentiel:
    """Resultat de la verification Phase 1.

    `complet` vaut True si les 4 pays CIBLES sont presents et exploitables.
    La presence d'autres pays n'est jamais un motif d'echec — voir la note
    sur les entrees polluees dans `verifier`.
    """

    pays_trouves: dict[str, str] = field(default_factory=dict)
    pays_manquants: list[str] = field(default_factory=list)
    pays_incomplets: dict[str, str] = field(default_factory=dict)
    entrees_ignorees: list[str] = field(default_factory=list)
    nb_devises: int = 0
    nb_telcos: int = 0

    @property
    def complet(self) -> bool:
        return not self.pays_manquants and not self.pays_incomplets

    def resume(self) -> str:
        lignes = [
            f"Pays cibles trouves : {len(self.pays_trouves)}/{len(PAYS_CIBLES)}",
            f"Devises : {self.nb_devises} | Telcos : {self.nb_telcos}",
        ]
        if self.pays_manquants:
            lignes.append(f"MANQUANTS : {', '.join(self.pays_manquants)}")
        if self.pays_incomplets:
            details = ", ".join(f"{iso} ({motif})" for iso, motif in self.pays_incomplets.items())
            lignes.append(f"INCOMPLETS : {details}")
        if self.entrees_ignorees:
            lignes.append(
                f"Entrees hors perimetre ignorees : {len(self.entrees_ignorees)} "
                f"({', '.join(self.entrees_ignorees)})"
            )
        return "\n".join(lignes)


class ConfigServiceClient:
    """Acces en lecture au referentiel geographique et monetaire."""

    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu("config-service", settings.config_service_base, journal=journal)

    async def fermer(self) -> None:
        await self._client.fermer()

    async def lister_pays(self) -> list[dict[str, Any]]:
        return await self._client.lister_tout("/api/v1/countries/")

    async def lister_devises(self) -> list[dict[str, Any]]:
        return await self._client.lister_tout("/api/v1/currencies/")

    async def lister_telcos(self) -> list[dict[str, Any]]:
        return await self._client.lister_tout("/api/v1/telcos/")

    async def verifier(self) -> RapportReferentiel:
        """Phase 1 — verifie que le referentiel permet la generation.

        Regle centrale, et elle est contre-intuitive : on valide que **les 4
        pays CIBLES sont presents**, jamais qu'il y a *exactement* 4 pays.
        L'environnement TEST contient des entrees parasites issues de tests
        anterieurs (iso_name en minuscules, noms incoherents). Un controle par
        comptage echouerait dessus alors que le referentiel est parfaitement
        exploitable. Ces entrees sont ignorees, et signalees dans le rapport.

        Un pays cible est « complet » s'il porte au moins une devise et au
        moins un telco : sans telco, EF-27 (validation du MSISDN contre le
        regex de l'operateur) devient impossible, et le CDC bloque alors la
        generation de clients dans ce pays.
        """
        rapport = RapportReferentiel()
        pays = await self.lister_pays()
        rapport.nb_devises = len(await self.lister_devises())
        rapport.nb_telcos = len(await self.lister_telcos())

        cibles = set(PAYS_CIBLES)
        for entree in pays:
            iso_brut = str(entree.get("iso_name") or "")
            iso = iso_brut.strip().upper()
            if iso not in cibles:
                rapport.entrees_ignorees.append(iso_brut or "(vide)")
                continue

            identifiant = normaliser_id(entree)
            rapport.pays_trouves[iso] = identifiant or ""

            devises = entree.get("currencies") or []
            telcos = entree.get("telcos") or []
            if not devises:
                rapport.pays_incomplets[iso] = "aucune devise"
            elif not telcos:
                rapport.pays_incomplets[iso] = "aucun telco"

        rapport.pays_manquants = [iso for iso in PAYS_CIBLES if iso not in rapport.pays_trouves]
        return rapport
