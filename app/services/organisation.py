"""
app/services/organisation.py
============================
Module Organisation — planification de l'arbre operationnel (UC-07 a UC-09).

Ce module ne parle a AUCUN service. Il calcule le plan de generation et en
verifie la faisabilite AVANT le moindre appel HTTP. C'est la lecture stricte
d'EF-18 : « le Loader DOIT rejeter et journaliser toute tentative de creation
violant l'emboitement geographique ». Rejeter apres coup, une fois 40 entites
creees sans possibilite de suppression, n'aurait aucun sens.

Arbre materialise, suite a la decision (b) du 08/08 :

    Company (IMF)          -> company-service, REELLE
      +- Branche (Region)   -> org_hierarchy, LOGIQUE
          +- Agence (Ville) -> org_hierarchy, LOGIQUE
              +- Kiosque    -> org_hierarchy + depositary-service, REELLE
                              (company_id = l'IMF racine)

Le goulot d'etranglement n'est pas le nombre de villes, mais le nombre de
villes PORTEUSES DE QUARTIERS : une Agence placee ailleurs ne pourrait heberger
aucun Kiosque (UC-09, exception). Il vaut 2 au Burkina Faso.

Reproductibilite (ENF-15) : tout tirage passe par un generateur derive du
run_id. Deux executions de meme run_id produisent strictement le meme plan.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from uuid import UUID

from app.core.cdc import COMPANIES_PAR_PAYS, KIOSQUES_PAR_PAYS, PAYS_CIBLES
from app.services.geographie import ReferentielGeo


@dataclass(frozen=True, slots=True)
class PlanKiosque:
    district_id: str
    city_id: str


@dataclass(frozen=True, slots=True)
class PlanAgence:
    city_id: str
    kiosques: tuple[PlanKiosque, ...]


@dataclass(frozen=True, slots=True)
class PlanBranche:
    region_id: str
    agences: tuple[PlanAgence, ...]


@dataclass(frozen=True, slots=True)
class PlanPays:
    country_code: str
    nb_companies: int
    nb_imf: int
    branches: tuple[PlanBranche, ...]

    @property
    def nb_kiosques(self) -> int:
        return sum(len(a.kiosques) for b in self.branches for a in b.agences)

    @property
    def nb_agences(self) -> int:
        return sum(len(b.agences) for b in self.branches)


@dataclass(slots=True)
class PlanOrganisation:
    """Plan complet, verifiable avant toute ecriture."""

    run_id: UUID
    pays: list[PlanPays] = field(default_factory=list)
    blocages: list[str] = field(default_factory=list)

    @property
    def realisable(self) -> bool:
        return not self.blocages

    @property
    def totaux(self) -> dict[str, int]:
        return {
            "companies": sum(p.nb_companies for p in self.pays),
            "imf": sum(p.nb_imf for p in self.pays),
            "branches": sum(len(p.branches) for p in self.pays),
            "agences": sum(p.nb_agences for p in self.pays),
            "kiosques": sum(p.nb_kiosques for p in self.pays),
            "agents": sum(p.nb_kiosques for p in self.pays),
        }

    def resume(self) -> str:
        lignes = ["Plan Organisation — par pays :"]
        for plan in self.pays:
            lignes.append(
                f"  {plan.country_code} : {plan.nb_companies} Companies "
                f"(dont {plan.nb_imf} IMF) | {len(plan.branches)} Branches | "
                f"{plan.nb_agences} Agences | {plan.nb_kiosques} Kiosques"
            )
        totaux = self.totaux
        lignes.append(
            "  TOTAL : " + " | ".join(f"{cle} {valeur}" for cle, valeur in totaux.items())
        )
        if self.blocages:
            lignes.append("BLOCAGES :")
            lignes.extend(f"  - {motif}" for motif in self.blocages)
        return "\n".join(lignes)


def planifier(
    referentiel: ReferentielGeo,
    run_id: UUID,
    *,
    nb_imf_par_pays: int = 2,
) -> PlanOrganisation:
    """Construit le plan complet et verifie sa faisabilite.

    `nb_imf_par_pays` est parametrable (EF-10 : « distribution des types
    configurable ») : seules les Companies de type IMF portent une hierarchie,
    UC-09 le precise explicitement. Un MERCHANT ou un FUNDING_PROVIDER n'a ni
    Branche ni Kiosque — un bailleur de fonds n'a pas de guichet de quartier.

    Le tirage est deterministe pour un run_id donne (ENF-15).
    """
    plan = PlanOrganisation(run_id=run_id)
    alea = random.Random(run_id.int)  # noqa: S311 — reproductibilite, pas de cryptographie

    kiosques_min, kiosques_max = KIOSQUES_PAR_PAYS
    companies_min, companies_max = COMPANIES_PAR_PAYS

    for pays in PAYS_CIBLES:
        villes_utiles = referentiel.villes_porteuses_de_quartiers(pays)
        quartiers_dispo = referentiel.nb_quartiers_du_pays(pays)

        if not villes_utiles:
            plan.blocages.append(
                f"{pays} : aucune ville porteuse de quartier — aucun Kiosque possible (UC-09)"
            )
            continue

        nb_kiosques = alea.randint(kiosques_min, kiosques_max)
        if nb_kiosques > quartiers_dispo:
            # Un quartier n'heberge qu'un Kiosque : au-dela, on empilerait
            # plusieurs guichets au meme endroit, ce qu'un bailleur reperait.
            plan.blocages.append(
                f"{pays} : {nb_kiosques} Kiosques demandes pour {quartiers_dispo} quartiers "
                f"disponibles — repartition impossible sans doublon geographique"
            )
            continue

        nb_companies = alea.randint(companies_min, companies_max)
        nb_imf = min(nb_imf_par_pays, nb_companies)
        if nb_imf < 1:
            plan.blocages.append(
                f"{pays} : aucune Company IMF — aucune hierarchie possible (UC-09)"
            )
            continue

        # Une Agence par ville utile, plafonnee par le referentiel. Chaque IMF
        # recoit au moins une Branche (UC-09, postcondition).
        nb_agences = min(len(villes_utiles), max(nb_imf, len(villes_utiles)))
        villes_retenues = villes_utiles[:nb_agences]

        # Repartition des Agences sur les Branches, une Branche par Region
        # distincte (EF-14). Deux Agences d'une meme region partagent leur Branche.
        agences_par_region: dict[str, list[str]] = {}
        for ville in villes_retenues:
            agences_par_region.setdefault(ville.region_id, []).append(ville.city_id)

        # Repartition des Kiosques sur les Agences, au prorata des quartiers
        # reellement disponibles dans chaque ville — jamais a parts egales :
        # Dakar (15 quartiers) doit peser plus que Thies (2).
        capacites = {
            ville.city_id: len(referentiel.quartiers_de_ville(ville.city_id))
            for ville in villes_retenues
        }
        attribution = _repartir(nb_kiosques, capacites, alea)

        branches: list[PlanBranche] = []
        for region_id, villes_ids in sorted(agences_par_region.items()):
            agences: list[PlanAgence] = []
            for city_id in villes_ids:
                quartiers = referentiel.quartiers_de_ville(city_id)
                alea.shuffle(quartiers)
                retenus = quartiers[: attribution.get(city_id, 0)]
                agences.append(
                    PlanAgence(
                        city_id=city_id,
                        kiosques=tuple(PlanKiosque(q.district_id, city_id) for q in retenus),
                    )
                )
            branches.append(PlanBranche(region_id=region_id, agences=tuple(agences)))

        plan.pays.append(
            PlanPays(
                country_code=pays,
                nb_companies=nb_companies,
                nb_imf=nb_imf,
                branches=tuple(branches),
            )
        )

    return plan


def _repartir(total: int, capacites: dict[str, int], alea: random.Random) -> dict[str, int]:
    """Repartit `total` Kiosques au prorata des capacites, sans jamais depasser.

    Le reste est distribue sur les villes qui ont encore de la place, dans un
    ordre tire de facon deterministe.
    """
    somme = sum(capacites.values())
    if somme == 0:
        return {}

    attribution = {ville: min(cap, total * cap // somme) for ville, cap in capacites.items()}
    restant = total - sum(attribution.values())

    candidats = [ville for ville, cap in capacites.items() if attribution[ville] < cap]
    alea.shuffle(candidats)
    index = 0
    while restant > 0 and candidats:
        ville = candidats[index % len(candidats)]
        if attribution[ville] < capacites[ville]:
            attribution[ville] += 1
            restant -= 1
        else:
            candidats.remove(ville)
            continue
        index += 1
    return attribution
