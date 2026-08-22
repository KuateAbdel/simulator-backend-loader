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
from app.core.configuration import ConfigurationExecution
from app.services.geographie import ReferentielGeo


@dataclass(frozen=True, slots=True)
class CompanyPorteuse:
    """Une IMF deja creee, prete a porter une hierarchie.

    Seules les IMF en portent une : UC-09 le precise, et un bailleur de fonds
    n'a pas de guichet de quartier. Le `country_code` n'est pas deduit du nom —
    il est transmis, parce qu'une raison sociale ne dit pas dans quel pays elle
    opere.
    """

    company_id: UUID
    nom: str
    country_code: str
    devise: str
    #: Le RANG DE PLAN de cette IMF dans son pays — la cle qui la relie aux
    #: `PlanBranche.imf_rang` qui lui appartiennent.
    #:
    #: LE CRASH DU 21/08 (premier run REAL en production) : l'executeur des
    #: Depositaires retrouvait la porteuse par `porteuses[imf_rang %
    #: len(porteuses)]`. Quand l'etape Organisation ne cree que 14 IMF sur les
    #: 18 planifiees (collisions d'identite), le modulo REPLIE deux rangs
    #: distincts sur la meme company — deux Branches pour la meme IMF dans la
    #: meme region, `E11000` sur `uniq_branche_par_company_region_run`, run
    #: mort. Le rang est donc porte ICI, par la porteuse elle-meme : une IMF
    #: manquante laisse un rang absent, jamais un rang reattribue.
    imf_rang: int = 0


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
    #: L'IMF PROPRIETAIRE de cette Branche, par son rang dans le pays.
    #:
    #: Il n'existait pas, et l'executeur distribuait les Branches en TOURNIQUET
    #: entre les IMF : `porteuses[rang % len(porteuses)]`. Consequence au
    #: Cameroun — 3 Branches pour 2 IMF : l'IMF n°1 recevait Centre, la n°2
    #: Littoral, la n°1 Nord-Ouest. **Chaque IMF n'operait que dans une ou deux
    #: regions.** Ce n'est pas un reseau, c'est une boutique avec une succursale.
    #:
    #: Le Manuel de Reference dit l'inverse : « **Agence** : point de
    #: commercialisation DISTANT du headquarter de la microfinance ». Une IMF a
    #: plusieurs agences, dans plusieurs villes — c'est ce qui fait un reseau.
    imf_rang: int = 0


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
    #: Ecarts au CDC ASSUMES — le plan reste executable, mais il ne rend pas
    #: exactement ce que le CDC demande, et il le DIT. Un plan qui rabote une
    #: exigence en silence fait croire a une conformite qu'il n'a pas.
    ecarts: list[str] = field(default_factory=list)

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
        if self.ecarts:
            lignes.append("ECARTS AU CDC (assumes, plan executable) :")
            lignes.extend(f"  - {motif}" for motif in self.ecarts)
        if self.blocages:
            lignes.append("BLOCAGES :")
            lignes.extend(f"  - {motif}" for motif in self.blocages)
        return "\n".join(lignes)


def planifier(
    referentiel: ReferentielGeo,
    run_id: UUID,
    *,
    nb_imf_par_pays: int = 2,
    configuration: ConfigurationExecution | None = None,
) -> PlanOrganisation:
    """Construit le plan complet et verifie sa faisabilite.

    `nb_imf_par_pays` est parametrable (EF-10 : « distribution des types
    configurable ») : seules les Companies de type IMF portent une hierarchie,
    UC-09 le precise explicitement. Un MERCHANT ou un FUNDING_PROVIDER n'a ni
    Branche ni Kiosque — un bailleur de fonds n'a pas de guichet de quartier.

    Le tirage est deterministe pour un run_id donne (ENF-15).

    UNE SEULE SOURCE POUR LES QUANTITES
    -----------------------------------
    `configuration` est OPTIONNELLE et sans elle **le comportement est
    identique** : les defauts de `ConfigurationExecution` sont les constantes du
    CDC. Elle existe parce que les quantites avaient DEUX sources qui se
    seraient contredites au premier parametrage :

        ici                       ->  `cdc.KIOSQUES_PAR_PAYS`
        `staff_execution.py:175`  ->  `configuration.resoudre("kiosques", pays)`

    Aujourd'hui les deux rendent (10, 20). Le jour ou un pays est surcharge, le
    planificateur aurait ignore la surcharge et le Staff l'aurait honoree : des
    Agents dimensionnes pour des Kiosques que le plan n'a jamais produits.
    La repartition geographique, elle, ne change pas d'un iota.
    """
    plan = PlanOrganisation(run_id=run_id)
    alea = random.Random(run_id.int)  # noqa: S311 — reproductibilite, pas de cryptographie

    kiosques_min, kiosques_max = KIOSQUES_PAR_PAYS
    companies_min, companies_max = COMPANIES_PAR_PAYS
    # L'ORDRE DE PARCOURS EST CELUI DU CDC, TOUJOURS.
    #
    # DEFAUT TROUVE LE 11/08 EN VERIFIANT MA PROPRE AFFIRMATION : ce filtre
    # s'ecrivait `tuple(configuration.pays_actifs)`, et `pays_actifs` rend une
    # liste TRIEE — donc `BF, CI, CM, SN` au lieu de `CM, CI, BF, SN`. Le
    # generateur aleatoire etant consomme pays par pays, changer l'ordre change
    # TOUS les tirages : 14 Companies sans configuration, 18 avec la
    # configuration par DEFAUT. Le docstring promettait « comportement
    # identique » ; il ne l'etait pas.
    #
    # `PAYS_CIBLES` fixe l'ordre, la configuration ne fait que FILTRER. Un pays
    # desactive disparait ; les autres gardent leur rang, donc leurs tirages.
    if configuration is None:
        pays_a_planifier = PAYS_CIBLES
    else:
        actifs = set(configuration.pays_actifs)
        # 22/08 (Yaniv) : les 4 cibles etaient le PREMIER USAGE, pas une borne.
        # Un pays admis par la porte d'activation (US-B3 : fiche + EN OPERATION
        # + matiere generable) entre dans le plan — APRES les cibles CDC, en
        # ordre alphabetique : les rangs des 4 ne bougent pas, leurs tirages
        # non plus (ENF-15, la lecon du 11/08 reste tenue).
        pays_a_planifier = tuple(code for code in PAYS_CIBLES if code in actifs) + tuple(
            sorted(actifs - set(PAYS_CIBLES))
        )

    for pays in pays_a_planifier:
        if configuration is not None:
            kiosques_min, kiosques_max = configuration.resoudre("kiosques", pays)
            companies_min, companies_max = configuration.resoudre("companies", pays)

        villes_utiles = referentiel.villes_porteuses_de_quartiers(pays)
        quartiers_dispo = referentiel.nb_quartiers_du_pays(pays)

        if not villes_utiles:
            plan.blocages.append(
                f"{pays} : aucune ville porteuse de quartier — aucun Kiosque possible (UC-09)"
            )
            continue

        # `D-03` — un quartier n'heberge qu'UN Kiosque. La geographie plafonne
        # donc la demande, elle ne la subit pas.
        #
        # DEFAUT TROUVE PAR LE PREMIER DRY_RUN REEL, le 09/08 : le tirage se
        # faisait dans `[10, 20]` puis BLOQUAIT le pays si le referentiel ne
        # suivait pas. La Cote d'Ivoire n'a que 17 quartiers ; un tirage a 19
        # supprimait le pays entier du run — 25 % de l'ecosysteme perdu par un
        # coup de des.
        #
        #   CM 25 quartiers · CI 17 · BF 18 · SN 22   (mesure du 09/08)
        #
        # Le plancher du CDC est 10 : les quatre pays le tiennent largement. Ce
        # n'etait donc jamais une impossibilite, seulement une demande mal
        # bornee. On borne AVANT de tirer.
        plafond = min(kiosques_max, quartiers_dispo)
        if plafond < kiosques_min:
            # La, c'est un vrai blocage : le referentiel ne peut pas honorer le
            # PLANCHER du CDC. On le dit, on ne rabote pas l'exigence en silence.
            plan.blocages.append(
                f"{pays} : {quartiers_dispo} quartiers disponibles pour un plancher CDC de "
                f"{kiosques_min} Kiosques (UC-09) — le referentiel ne peut pas l'honorer"
            )
            continue

        nb_kiosques = alea.randint(kiosques_min, plafond)
        if plafond < kiosques_max:
            # Ecart au CDC : signale, jamais tu. `EF-04` prevoit d'enrichir le
            # referentiel — c'est la reponse, pas un Kiosque en double.
            plan.ecarts.append(
                f"{pays} : plafonne a {plafond} Kiosques ({quartiers_dispo} quartiers) "
                f"au lieu des {kiosques_max} du CDC — `D-03`, un quartier = un Kiosque"
            )

        nb_companies = alea.randint(companies_min, companies_max)
        nb_imf = min(nb_imf_par_pays, nb_companies)
        if nb_imf < 1:
            plan.blocages.append(
                f"{pays} : aucune Company IMF — aucune hierarchie possible (UC-09)"
            )
            continue

        # `EF-15` — « un nombre PARAMETRABLE d'Agences par Branche, rattachees a
        # une Ville de la Region ». Une Agence par ville porteuse de quartiers :
        # c'est le defaut, et il est impose par le referentiel, pas choisi. Une
        # Agence placee dans une ville sans quartier ne pourrait heberger aucun
        # Kiosque (`UC-09`, exception).
        #
        # Le plafond `agences` ne fait que BORNER ce que la geographie offre. Il
        # n'invente jamais une ville : `EF-04` prevoit d'enrichir le referentiel,
        # c'est la seule facon d'en avoir davantage.
        nb_agences = min(len(villes_utiles), max(nb_imf, len(villes_utiles)))
        if configuration is not None:
            plafond_agences = configuration.resoudre("agences", pays)
            if plafond_agences is not None:
                nb_agences = min(nb_agences, int(plafond_agences))
        villes_retenues = villes_utiles[:nb_agences]

        # `EF-14` — « un nombre PARAMETRABLE de Branches par IMF, rattachees a
        # une Region ». Une Branche par Region distincte des villes retenues :
        # deux Agences d'une meme region partagent leur Branche, comme dans la
        # realite d'un reseau territorial.
        agences_par_region: dict[str, list[str]] = {}
        for ville in villes_retenues:
            agences_par_region.setdefault(ville.region_id, []).append(ville.city_id)

        if configuration is not None:
            plafond_branches = configuration.resoudre("branches", pays)
            if plafond_branches is not None and len(agences_par_region) > int(plafond_branches):
                # On retire les regions les MOINS pourvues en villes : plafonner
                # doit couter le moins de couverture geographique possible.
                gardees = sorted(
                    agences_par_region.items(), key=lambda kv: (-len(kv[1]), kv[0])
                )[: int(plafond_branches)]
                retirees = len(agences_par_region) - len(gardees)
                agences_par_region = dict(gardees)
                villes_gardees = {c for _, ids in gardees for c in ids}
                villes_retenues = [v for v in villes_retenues if v.city_id in villes_gardees]
                plan.ecarts.append(
                    f"{pays} : {retirees} Region(s) ecartee(s) par le plafond de "
                    f"{plafond_branches} Branches — `EF-14` parametrable, la "
                    f"couverture geographique en paie le prix"
                )

        # `EF-16` — « un nombre PARAMETRABLE de Kiosques par Agence, rattaches a
        # un District de la Ville ». Le nombre TOTAL par pays vient de
        # `configuration.resoudre("kiosques")` ; sa repartition entre les Agences
        # se fait au prorata des quartiers reellement disponibles dans chaque
        # ville — jamais a parts egales : Dakar (15 quartiers) doit peser plus
        # que Thies (2). Et `D-03` tient : un quartier n'heberge qu'UN Kiosque,
        # donc `_repartir` ne depasse jamais la capacite d'une ville.
        capacites = {
            ville.city_id: len(referentiel.quartiers_de_ville(ville.city_id))
            for ville in villes_retenues
        }
        attribution = _repartir(nb_kiosques, capacites, alea)

        # LA PARTITION SE FAIT AU QUARTIER, JAMAIS A LA VILLE
        # ----------------------------------------------------
        # Si l'on partage les VILLES entre les IMF, chacune reste enfermee dans
        # les siennes. Si l'on partage les QUARTIERS de chaque ville, alors
        # chaque IMF a une Agence dans chaque ville ou elle opere — et son
        # reseau devient national. C'est la seule lecture compatible avec le
        # Manuel (« Agence : point distant du headquarter ») et avec la vraie vie
        # (deux IMF concurrentes ont chacune leur agence a Douala).
        #
        # La ressource finie est le quartier — `D-03`, un quartier = un Kiosque.
        # Les quartiers d'une ville sont donc distribues en tourniquet entre les
        # IMF : l'unicite globale du quartier reste garantie, et chaque IMF
        # recoit une part de CHAQUE ville.
        #
        # Le cout est nul : Branche et Agence sont des niveaux LOGIQUES (`D-05`),
        # ils vivent dans `org_hierarchy`. Zero ecriture serveur, zero Company
        # consommee sur le budget de `UC-07`, zero appel HTTP. Le nombre de
        # Kiosques — donc de Depositaires REELS — ne change pas d'une unite.
        #
        # `arbres[rang][region_id][city_id] = [district_id, ...]`
        arbres: list[dict[str, dict[str, list[str]]]] = [{} for _ in range(nb_imf)]
        # LE TOURNIQUET EST CONTINU D'UNE VILLE A L'AUTRE, ET C'EST DELIBERE.
        #
        # Premiere version : le compteur repartait de zero a chaque ville. Biais
        # systematique — toute ville n'ayant qu'UN Kiosque le donnait a l'IMF n°1.
        # Mesure au Senegal : l'IMF n°1 raflait Pikine, Thies ET Saint-Louis,
        # l'IMF n°2 restait confinee a Dakar (1 Branche contre 3).
        #
        # Un compteur qui traverse les villes fait alterner les petites villes.
        # Aucune IMF n'herite structurellement de la province.
        position = 0
        for ville in villes_retenues:
            quartiers = referentiel.quartiers_de_ville(ville.city_id)
            alea.shuffle(quartiers)
            retenus = quartiers[: attribution.get(ville.city_id, 0)]
            for quartier in retenus:
                rang = position % nb_imf
                arbres[rang].setdefault(ville.region_id, {}).setdefault(
                    ville.city_id, []
                ).append(quartier.district_id)
                position += 1

        branches: list[PlanBranche] = []
        for rang, arbre in enumerate(arbres):
            for region_id, villes_ids in sorted(arbre.items()):
                agences = [
                    PlanAgence(
                        city_id=city_id,
                        kiosques=tuple(PlanKiosque(d, city_id) for d in districts),
                    )
                    for city_id, districts in sorted(villes_ids.items())
                ]
                branches.append(
                    PlanBranche(region_id=region_id, agences=tuple(agences), imf_rang=rang)
                )

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
