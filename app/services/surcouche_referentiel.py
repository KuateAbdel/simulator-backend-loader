"""
app/services/surcouche_referentiel.py
=====================================
Surcouche referentielle — `CFG-03`, exigence de parametrage du 9 aout 2026.

> *« Ajout region/ville »* — Direction Technique

**Le classeur reste la source de reference, et n'est JAMAIS modifie.** Les
ajouts du Super-Admin vivent dans une couche distincte, tracee et reversible.
Appliquer la surcouche produit un **nouveau** `ReferentielGeo` ; l'original
reste intact.

POURQUOI CETTE FORME
--------------------
Trois raisons, dans l'ordre :

1. **`ENF-15`.** Un referentiel mute en place rendrait deux executions du meme
   `run_id` differentes selon l'ordre des ajouts. Une surcouche immuable,
   appliquee en une fois, ne le peut pas.
2. **Reversibilite.** Retirer un ajout est immediat et sans trace residuelle —
   on n'a jamais touche au fichier.
3. **Tracabilite.** `ajouts()` dit exactement ce qui a ete ajoute et par quel
   chemin. C'est ce que le tableau de bord montrera.

LES INVARIANTS `EF-02` S'APPLIQUENT AUX AJOUTS
-----------------------------------------------
Exactement comme au chargement : *« chaque Region a un Country parent, chaque
City une Region, chaque District une City »*. Une ville sans region valide est
**refusee**, pas journalisee et acceptee.

C'est la difference avec le comportement du chargement, et elle est voulue :
au chargement, une ligne orpheline du fichier est **journalisee puis exclue**
(`UC-05`, cas alternatif) — on n'interrompt pas une lecture pour une ligne
fautive. Ici, l'ajout est un **acte deliebere du Super-Admin** : le refuser
immediatement lui dit ou est son erreur.

CE QUI RESTE CHEZ NOUS, ET NE PARTIRA JAMAIS
---------------------------------------------
Une **region** ajoutee ici n'ira jamais sur config-service : ce service n'a
**aucune notion** de region administrative — son champ `region` designe la
region *continentale* (« Middle Africa »). Une **ville** peut, elle, etre
propagee via `AdministrationConfigService.ajouter_ville()`.

C'est le *System of Record* dans sa forme la plus nette : nous portons une
dimension que le serveur n'a pas de champ pour porter.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.geographie import (
    City,
    District,
    RapportGeographique,
    ReferentielGeo,
    Region,
    Telco,
)

#: Prefixe des identifiants generes par la surcouche. Il rend un ajout
#: reconnaissable a l'oeil dans n'importe quel export, et impossible a
#: confondre avec une ligne du classeur (`CM-01`, `CM-CT-01`, `CM-DT-001`).
PREFIXE_SURCOUCHE = "SC"


class AjoutRefuse(ValueError):
    """L'ajout violerait un invariant `EF-02` — refuse immediatement.

    Un ajout est un acte delibere : le refuser sur-le-champ dit au Super-Admin
    ou est son erreur, plutot que de la journaliser et de la subir au 500e
    onboarding.
    """


@dataclass(slots=True)
class SurcoucheReferentiel:
    """Les ajouts du Super-Admin, au-dessus du classeur.

    Construite vide, elle ne change rien : `appliquer()` rend alors un
    referentiel identique a l'original.
    """

    regions: dict[str, Region] = field(default_factory=dict)
    villes: dict[str, City] = field(default_factory=dict)
    quartiers: dict[str, District] = field(default_factory=dict)
    #: `US-B7` (13/08) — les operateurs ajoutes par le Super-Admin. Meme
    #: doctrine que les villes : le classeur est immuable, la surcouche est
    #: reversible, et chaque ajout passe les invariants AVANT d'exister.
    telcos: dict[str, Telco] = field(default_factory=dict)
    #: `US-B5+` — les secteurs d'activite ajoutes par le Super-Admin, par-dessus
    #: les 112 du classeur. Meme doctrine : base immuable, surcouche reversible.
    #: Un secteur ne se rattache qu'a des industries EXISTANTES (les 6) — on
    #: n'ouvre pas une 7e industrie par la porte d'un secteur. label -> industries.
    secteurs: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: `US-B5+` — LIAISON GENERATIVE d'un secteur ajoute : les types d'entreprise
    #: (CompanyType) pour lesquels il est un secteur connexe admissible. C'est ce
    #: qui le fait TIRER au run (pas seulement s'afficher). Metier, declare a
    #: l'ajout, jamais calcule. label -> (types d'entreprise).
    secteurs_types: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: `US-B5+` — les industries ajoutees par le Super-Admin, par-dessus les 6 du
    #: classeur. Le niveau HAUT de la taxonomie : rare, stable, mais possible.
    industries_ajoutees: list[str] = field(default_factory=list)
    #: `US-B5+` — formes juridiques ajoutees (labels). Simple : un label unique.
    formes_juridiques: list[str] = field(default_factory=list)
    #: `US-B5+` — fonctions dirigeant ajoutees : {rang, francais, anglais, abreviation}.
    fonctions_dirigeant: list[dict[str, Any]] = field(default_factory=list)
    #: `US-B5+` — professions ajoutees, PAR groupe metier existant : groupe -> [professions].
    professions: dict[str, list[str]] = field(default_factory=dict)
    #: Journal des ajouts, dans l'ordre — c'est ce que le tableau de bord montre.
    journal: list[str] = field(default_factory=list)

    # -- Ajouts, avec les invariants EF-02 -----------------------------------

    def ajouter_region(
        self,
        base: ReferentielGeo,
        *,
        pays: str,
        nom: str,
        capitale: str = "",
        population: int | None = None,
    ) -> Region:
        """`EF-02` : le pays parent doit exister.

        Une region ajoutee ici **ne partira jamais** vers config-service, qui
        n'a aucune notion de region administrative.
        """
        code = str(pays).strip().upper()
        if base.pays(code) is None:
            raise AjoutRefuse(
                f"region {nom!r} : pays {code!r} absent du referentiel — EF-02 exige un "
                "Country parent. Ajouter un pays est une autre operation."
            )
        libelle = str(nom).strip()
        if not libelle:
            raise AjoutRefuse("region sans nom — refuse")
        if any(r.name == libelle and r.country_iso2 == code for r in self._toutes_regions(base)):
            raise AjoutRefuse(f"region {libelle!r} existe deja pour {code}")

        region = Region(
            region_id=self._identifiant("REG", code, libelle),
            country_iso2=code,
            name=libelle,
            capitale=str(capitale).strip(),
            population=population,
        )
        self.regions[region.region_id] = region
        self.journal.append(f"region {libelle!r} ajoutee a {code} ({region.region_id})")
        return region

    def ajouter_ville(
        self,
        base: ReferentielGeo,
        *,
        region_id: str,
        nom: str,
        latitude: float | None = None,
        longitude: float | None = None,
        population: int | None = None,
        poids_economique: float = 1.0,
    ) -> City:
        """`EF-02` : la region parente doit exister — dans le classeur **ou**
        dans la surcouche.

        `D-IDN-2` s'applique par ricochet : une ville sans coordonnees produira
        des adresses sans GPS. On les accepte `None` — le referentiel d'origine
        en a aussi — mais le generateur devra le savoir.
        """
        parent = base.region(region_id) or self.regions.get(region_id)
        if parent is None:
            raise AjoutRefuse(
                f"ville {nom!r} : region {region_id!r} inexistante — EF-02 exige une Region "
                "parente. Creer la region d'abord."
            )
        libelle = str(nom).strip()
        if not libelle:
            raise AjoutRefuse("ville sans nom — refuse")
        if any(v.name == libelle for v in self._toutes_villes(base, parent.country_iso2)):
            raise AjoutRefuse(f"ville {libelle!r} existe deja pour {parent.country_iso2}")

        ville = City(
            city_id=self._identifiant("CT", parent.country_iso2, libelle),
            country_iso2=parent.country_iso2,
            region_id=region_id,
            name=libelle,
            poids_economique=poids_economique,
            latitude=latitude,
            longitude=longitude,
            population=population,
            est_capitale_pays=False,
            est_capitale_region=False,
        )
        self.villes[ville.city_id] = ville
        self.journal.append(f"ville {libelle!r} ajoutee a {region_id} ({ville.city_id})")
        return ville

    def ajouter_secteur(
        self,
        base_statique: Any,
        *,
        label: str,
        industries: list[str],
        types: list[str] | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        """`US-B5+` — un secteur d'activite, avec ses invariants.

        DEUX INVARIANTS, la meme doctrine que les telcos et les villes :

        1. Le label est NON VIDE et UNIQUE — classeur (112) ET surcouche. Un
           doublon rendrait `industrie_du_secteur` ambigu : deux industries
           principales possibles pour un meme nom.
        2. Au moins une industrie, et CHAQUE industrie doit EXISTER dans le
           classeur (les 6). On n'invente pas une 7e industrie par la porte
           d'un secteur — la relation n:n reste fermee sur les 6 industries.

        Le rattachement est trie : l'industrie principale (premiere par ordre
        alphabetique) est ainsi deterministe, comme cote generateur.
        """
        libelle = str(label).strip()
        if not libelle:
            raise AjoutRefuse("secteur sans nom — refuse")
        connus = set(base_statique.secteurs) | set(self.secteurs)
        if libelle in connus:
            raise AjoutRefuse(
                f"secteur {libelle!r} existe deja (classeur ou surcouche) — "
                "un nom de secteur est unique."
            )
        valides = set(base_statique.industries.values()) | set(self.industries_ajoutees)
        propres: list[str] = []
        for ind in industries:
            nom = str(ind).strip()
            if nom not in valides:
                raise AjoutRefuse(
                    f"industrie {nom!r} inconnue — un secteur ne se rattache qu'aux "
                    f"industries du classeur : {sorted(valides)}."
                )
            if nom not in propres:
                propres.append(nom)
        if not propres:
            raise AjoutRefuse(
                f"secteur {libelle!r} : au moins une industrie de rattachement est requise."
            )
        rattache = tuple(sorted(propres))
        self.secteurs[libelle] = rattache
        if types:
            propres_types = tuple(dict.fromkeys(t.strip() for t in types if t.strip()))
            if propres_types:
                self.secteurs_types[libelle] = propres_types
        self.journal.append(f"secteur {libelle!r} ajoute ({', '.join(rattache)})")
        return libelle, rattache

    def connexes_par_type(self) -> dict[str, tuple[str, ...]]:
        """Inverse de `secteurs_types` : type d'entreprise -> secteurs ajoutes
        qui lui sont declares connexes. C'est ce que le generateur fusionne dans
        `SECTEURS_PAR_TYPE` pour que ces secteurs soient reellement tires."""
        par_type: dict[str, list[str]] = {}
        for secteur, types in self.secteurs_types.items():
            for t in types:
                par_type.setdefault(t, []).append(secteur)
        return {t: tuple(sorted(secs)) for t, secs in par_type.items()}

    def ajouter_industrie(self, base_statique: Any, *, label: str) -> str:
        """`US-B5+` — une industrie (le niveau HAUT). Rare, mais possible.

        Un seul invariant : label NON VIDE et UNIQUE — classeur (6) ET surcouche.
        Le niveau haut d'une taxonomie (GICS/ICB) est stable ; on l'ouvre donc
        avec prudence, mais la base reste immuable et l'ajout est reversible.
        """
        libelle = str(label).strip()
        if not libelle:
            raise AjoutRefuse("industrie sans nom — refuse")
        connues = set(base_statique.industries.values()) | set(self.industries_ajoutees)
        if libelle in connues:
            raise AjoutRefuse(f"industrie {libelle!r} existe deja — un nom d'industrie est unique.")
        self.industries_ajoutees.append(libelle)
        self.journal.append(f"industrie {libelle!r} ajoutee")
        return libelle

    def retirer_secteur(self, *, label: str) -> None:
        """Retire un secteur AJOUTE (surcouche). Le classeur est intouchable :
        seul un ajout de la surcouche peut etre retire — c'est la reversibilite
        promise (le classeur des 112 n'est jamais amputable)."""
        libelle = str(label).strip()
        if libelle not in self.secteurs:
            raise AjoutRefuse(
                f"secteur {libelle!r} n'est pas un ajout de la surcouche — "
                "le classeur est immuable, rien a retirer."
            )
        del self.secteurs[libelle]
        self.secteurs_types.pop(libelle, None)
        self.journal.append(f"secteur {libelle!r} retire")

    def retirer_industrie(self, *, label: str) -> None:
        """Retire une industrie AJOUTEE (surcouche). Les 6 du classeur sont
        immuables. GARDE anti-orphelin : on refuse tant qu'un secteur (ajoute)
        s'y rattache — sinon `industrie_du_secteur` pointerait vers le vide."""
        libelle = str(label).strip()
        if libelle not in self.industries_ajoutees:
            raise AjoutRefuse(
                f"industrie {libelle!r} n'est pas un ajout de la surcouche — "
                "les 6 industries du classeur sont immuables."
            )
        rattaches = sorted(s for s, inds in self.secteurs.items() if libelle in inds)
        if rattaches:
            raise AjoutRefuse(
                f"industrie {libelle!r} porte encore {len(rattaches)} secteur(s) "
                f"({', '.join(rattaches)}) — retirez-les d'abord."
            )
        self.industries_ajoutees.remove(libelle)
        self.journal.append(f"industrie {libelle!r} retiree")

    # -- Formes juridiques (le plus simple : un label unique) ---------------

    def ajouter_forme(self, base_statique: Any, *, label: str) -> str:
        libelle = str(label).strip()
        if not libelle:
            raise AjoutRefuse("forme juridique sans nom — refuse")
        connues = set(base_statique.formes_juridiques) | set(self.formes_juridiques)
        if libelle in connues:
            raise AjoutRefuse(f"forme juridique {libelle!r} existe deja.")
        self.formes_juridiques.append(libelle)
        self.journal.append(f"forme juridique {libelle!r} ajoutee")
        return libelle

    def retirer_forme(self, *, label: str) -> None:
        libelle = str(label).strip()
        if libelle not in self.formes_juridiques:
            raise AjoutRefuse(f"forme juridique {libelle!r} n'est pas un ajout de la surcouche.")
        self.formes_juridiques.remove(libelle)
        self.journal.append(f"forme juridique {libelle!r} retiree")

    # -- Fonctions dirigeant ({rang, fr, en, abreviation}) ------------------

    def ajouter_dirigeant(
        self, base_statique: Any, *, rang: int, francais: str, anglais: str, abreviation: str
    ) -> dict[str, Any]:
        fr = str(francais).strip()
        en = str(anglais).strip()
        abr = str(abreviation).strip()
        if not fr or not en:
            raise AjoutRefuse("fonction dirigeant : libelles FR et EN requis.")
        rangs = {f.rang for f in base_statique.fonctions_dirigeant} | {
            d["rang"] for d in self.fonctions_dirigeant
        }
        if rang in rangs:
            raise AjoutRefuse(f"rang {rang} deja utilise — un rang de dirigeant est unique.")
        noms = {f.francais for f in base_statique.fonctions_dirigeant} | {
            d["francais"] for d in self.fonctions_dirigeant
        }
        if fr in noms:
            raise AjoutRefuse(f"fonction dirigeant {fr!r} existe deja.")
        fonction = {"rang": rang, "francais": fr, "anglais": en, "abreviation": abr}
        self.fonctions_dirigeant.append(fonction)
        self.journal.append(f"dirigeant {fr!r} (rang {rang}) ajoute")
        return fonction

    def retirer_dirigeant(self, *, rang: int) -> None:
        avant = len(self.fonctions_dirigeant)
        self.fonctions_dirigeant = [d for d in self.fonctions_dirigeant if d["rang"] != rang]
        if len(self.fonctions_dirigeant) == avant:
            raise AjoutRefuse(f"aucun dirigeant de rang {rang} dans la surcouche.")
        self.journal.append(f"dirigeant rang {rang} retire")

    # -- Professions (rattachees a un groupe metier EXISTANT) ---------------

    def ajouter_profession(self, base_statique: Any, *, groupe: str, label: str) -> tuple[str, str]:
        grp = str(groupe).strip()
        libelle = str(label).strip()
        if grp not in base_statique.groupes:
            raise AjoutRefuse(
                f"groupe metier {grp!r} inconnu — une profession se rattache a un groupe existant."
            )
        if not libelle:
            raise AjoutRefuse("profession sans nom — refuse")
        connues = set(base_statique.professions) | {
            p for ps in self.professions.values() for p in ps
        }
        if libelle in connues:
            raise AjoutRefuse(f"profession {libelle!r} existe deja.")
        self.professions.setdefault(grp, []).append(libelle)
        self.journal.append(f"profession {libelle!r} ajoutee a {grp!r}")
        return grp, libelle

    def retirer_profession(self, *, label: str) -> None:
        for grp, ps in list(self.professions.items()):
            if label in ps:
                ps.remove(label)
                if not ps:
                    del self.professions[grp]
                self.journal.append(f"profession {label!r} retiree")
                return
        raise AjoutRefuse(f"profession {label!r} n'est pas un ajout de la surcouche.")

    def ajouter_telco(
        self,
        base: ReferentielGeo,
        *,
        pays: str,
        network_name: str,
        short_name: str,
        regex_msisdn: str,
        part_marche: float,
        exemple_msisdn: str,
        ussd_base_code: str = "",
    ) -> Telco:
        """`US-B7` — un operateur, avec les invariants qui manquaient.

        QUATRE INVARIANTS, dont deux que PERSONNE ne verifiait :

        1. Le pays est une cible (EF-05) et les noms sont uniques dans le pays
           — deux operateurs homonymes rendraient `operateur_du_msisdn`
           ambigu.
        2. La regex COMPILE — un plan illisible est refuse a l'ajout, pas
           decouvert au 500e client.
        3. `exemple_msisdn` DOIT matcher la regex : la preuve que le plan est
           utilisable, fournie par celui qui l'ajoute. Et le plan doit etre
           COMPOSABLE : on compose un numero d'essai et on verifie qu'il
           s'accepte lui-meme — sinon `composer_msisdn` produirait des numeros
           que `valider_msisdn_operateur` refuserait, 2000 fois.
        4. La SOMME des parts de marche du pays reste <= 100 — l'invariant
           INV-18 etendu a l'ecriture : un marche a 130 % n'existe pas.
        """
        code = str(pays).strip().upper()
        if base.pays(code) is None:
            raise AjoutRefuse(f"telco {network_name!r} : pays {code!r} hors des cibles — EF-05.")
        nom = str(network_name).strip()
        court = str(short_name).strip()
        if not nom or not court:
            raise AjoutRefuse("telco sans nom ou sans code court — refuse")
        existants = [
            t for t in (*base.telcos.values(), *self.telcos.values()) if t.country_iso2 == code
        ]
        # Collision CROISEE comprise : un nouveau nom egal au CODE d'un
        # existant (ou l'inverse) est aussi ambigu — « MTN CM » est le code de
        # « MTN Cameroon », un operateur NOMME « MTN CM » semerait le doute.
        for telco in existants:
            libelles_existants = {telco.network_name, telco.short_name}
            if {nom, court} & libelles_existants:
                raise AjoutRefuse(
                    f"telco {nom!r}/{court!r} : {telco.network_name!r} "
                    f"({telco.short_name}) existe deja pour {code} — deux "
                    "operateurs aux libelles croises rendraient l'attribution ambigue"
                )

        try:
            motif = re.compile(regex_msisdn)
        except re.error as erreur:
            raise AjoutRefuse(
                f"telco {nom!r} : regex incompilable ({erreur}) — un plan "
                "illisible se refuse a l'ajout, pas au 500e client"
            ) from erreur
        if not motif.fullmatch(str(exemple_msisdn).strip()):
            raise AjoutRefuse(
                f"telco {nom!r} : l'exemple {exemple_msisdn!r} ne matche pas le "
                "plan — la preuve d'utilisabilite est exigee de celui qui ajoute"
            )

        if not 0 < part_marche <= 100:
            raise AjoutRefuse(f"telco {nom!r} : part de marche {part_marche} hors de ]0, 100]")
        somme = sum(t.part_marche for t in existants)
        if somme + part_marche > 100:
            raise AjoutRefuse(
                f"telco {nom!r} : {somme:.1f} % deja attribues sur {code}, "
                f"ajouter {part_marche:.1f} % depasserait 100 — un marche a "
                f"{somme + part_marche:.1f} % n'existe pas (INV-18)"
            )

        telco = Telco(
            telco_id=self._identifiant("TL", code, nom),
            network_name=nom,
            short_name=court,
            ussd_base_code=str(ussd_base_code).strip(),
            regex_msisdn=regex_msisdn,
            part_marche=float(part_marche),
            country_iso2=code,
        )
        # COMPOSABLE, pas seulement compilable : le composeur doit produire un
        # numero que le plan accepte — l'aller-retour complet, prouve ICI.
        # TROU DE GESTION D'ERREUR trouve par le test du 13/08 : le composeur
        # leve ValueError sur un dialecte qu'il ne sait pas parser — sans ce
        # rattrapage, l'ajout partait en 500 au lieu d'un refus explique.
        try:
            essai = telco.composer_msisdn("38101955", random.Random(0))  # noqa: S311
        except ValueError as erreur:
            raise AjoutRefuse(
                f"telco {nom!r} : le plan compile mais n'est pas COMPOSABLE "
                f"({erreur}) — la forme attendue est celle des plans reels, "
                "ex. ^237(66\\d{7})$ : prefixe pays puis groupe de variantes"
            ) from erreur
        if not telco.accepte(essai):
            raise AjoutRefuse(
                f"telco {nom!r} : le plan compile mais n'est pas COMPOSABLE — "
                f"le numero d'essai {essai!r} ne s'accepte pas lui-meme"
            )
        self.telcos[telco.telco_id] = telco
        self.journal.append(
            f"telco {nom!r} ajoute a {code} ({telco.telco_id}, {part_marche:.1f} %)"
        )
        return telco

    def ajouter_quartier(
        self,
        base: ReferentielGeo,
        *,
        city_id: str,
        nom: str,
        zone_type: str = "residential",
        population: int | None = None,
    ) -> District:
        """`EF-02` : la ville parente doit exister.

        Un quartier compte doublement : c'est lui qui porte un Kiosque, et
        l'index `(run_id, district_id)` unique garantit qu'un quartier n'en
        heberge **qu'un seul** (`D-03`). Ajouter un quartier, c'est donc
        augmenter la capacite d'accueil du pays.
        """
        parent = base.ville(city_id) or self.villes.get(city_id)
        if parent is None:
            raise AjoutRefuse(
                f"quartier {nom!r} : ville {city_id!r} inexistante — EF-02 exige une City parente."
            )
        libelle = str(nom).strip()
        if not libelle:
            raise AjoutRefuse("quartier sans nom — refuse")
        deja = {q.name for q in base.quartiers_de_ville(city_id)}
        deja |= {q.name for q in self.quartiers.values() if q.city_id == city_id}
        if libelle in deja:
            raise AjoutRefuse(f"quartier {libelle!r} existe deja dans {city_id}")

        quartier = District(
            district_id=self._identifiant("DT", parent.country_iso2, libelle),
            city_id=city_id,
            name=libelle,
            zone_type=str(zone_type).strip().lower() or "residential",
            population=population,
        )
        self.quartiers[quartier.district_id] = quartier
        self.journal.append(f"quartier {libelle!r} ajoute a {city_id} ({quartier.district_id})")
        return quartier

    # -- Retrait — la reversibilite promise ---------------------------------

    def retirer(self, identifiant: str) -> bool:
        """Retire un ajout. Le classeur n'ayant jamais ete touche, il ne reste
        aucune trace residuelle.

        Refuse de retirer une region ou une ville qui porte encore des enfants
        **dans la surcouche** — meme discipline que les references inverses de
        `AdministrationConfigService`.
        """
        if identifiant in self.regions:
            enfants = [v.city_id for v in self.villes.values() if v.region_id == identifiant]
            if enfants:
                raise AjoutRefuse(
                    f"region {identifiant} porte encore {len(enfants)} ville(s) ajoutee(s) — "
                    "retirer les enfants d'abord"
                )
            del self.regions[identifiant]
        elif identifiant in self.villes:
            enfants = [q.district_id for q in self.quartiers.values() if q.city_id == identifiant]
            if enfants:
                raise AjoutRefuse(
                    f"ville {identifiant} porte encore {len(enfants)} quartier(s) ajoute(s) — "
                    "retirer les enfants d'abord"
                )
            del self.villes[identifiant]
        elif identifiant in self.quartiers:
            del self.quartiers[identifiant]
        else:
            return False
        self.journal.append(f"retrait de {identifiant}")
        return True

    # -- Application — un NOUVEAU referentiel, l'original intact -------------

    def appliquer(self, base: ReferentielGeo) -> ReferentielGeo:
        """Rend un referentiel fusionne. **`base` n'est jamais mute.**

        Le rapport de couverture (`EF-06`) est recalcule et porte le nombre
        d'ajouts, pour que le decompte affiche en debut d'execution dise la
        verite.
        """
        rapport = RapportGeographique(
            pays=list(base.rapport.pays),
            nb_regions=len(base.regions) + len(self.regions),
            nb_villes=len(base.villes) + len(self.villes),
            nb_quartiers=len(base.quartiers) + len(self.quartiers),
            nb_telcos=base.rapport.nb_telcos + len(self.telcos),
            nb_devises=base.rapport.nb_devises,
            orphelins=list(base.rapport.orphelins),
        )
        return ReferentielGeo(
            regions={**base.regions, **self.regions},
            villes={**base.villes, **self.villes},
            quartiers={**base.quartiers, **self.quartiers},
            rapport=rapport,
            telcos={**base.telcos, **self.telcos},
            devises=base.devises,
            pays_index=base.pays_index,
        )

    # -- Tracabilite --------------------------------------------------------

    @property
    def vide(self) -> bool:
        return not (
            self.regions
            or self.villes
            or self.quartiers
            or self.telcos
            or self.secteurs
            or self.industries_ajoutees
            or self.formes_juridiques
            or self.fonctions_dirigeant
            or self.professions
        )

    def ajouts(self) -> dict[str, Any]:
        """Forme serialisable — a joindre a l'empreinte du run (`ENF-15`).

        Sans elle, rejouer un `run_id` sur un referentiel surcharge donnerait
        un resultat different. La surcouche fait partie de la configuration.
        """
        return {
            "regions": {i: r.name for i, r in sorted(self.regions.items())},
            "villes": {i: v.name for i, v in sorted(self.villes.items())},
            "quartiers": {i: q.name for i, q in sorted(self.quartiers.items())},
            "telcos": {i: t.network_name for i, t in sorted(self.telcos.items())},
            "secteurs": {nom: list(inds) for nom, inds in sorted(self.secteurs.items())},
            "secteurs_types": {nom: list(ts) for nom, ts in sorted(self.secteurs_types.items())},
            "industries_ajoutees": sorted(self.industries_ajoutees),
            "formes_juridiques": sorted(self.formes_juridiques),
            "fonctions_dirigeant": sorted(self.fonctions_dirigeant, key=lambda d: d["rang"]),
            "professions": {g: sorted(ps) for g, ps in sorted(self.professions.items())},
            "journal": list(self.journal),
        }

    def resume(self) -> str:
        if self.vide:
            return "Surcouche : aucun ajout — le referentiel est celui du classeur"
        return (
            f"Surcouche : {len(self.regions)} region(s) · {len(self.villes)} ville(s) · "
            f"{len(self.quartiers)} quartier(s) · {len(self.telcos)} telco(s) — "
            "le classeur n'a pas ete modifie"
        )

    # -- Interne ------------------------------------------------------------

    @staticmethod
    def _identifiant(genre: str, pays: str, libelle: str) -> str:
        """Identifiant reconnaissable a l'oeil, stable pour un meme libelle.

        `SC-CM-CT-DOUALA-NORD` ne peut pas etre confondu avec `CM-CT-01` du
        classeur. La stabilite sert `ENF-15` : rejouer le meme ajout produit le
        meme identifiant.
        """
        base = "".join(c if c.isalnum() else "-" for c in libelle.upper()).strip("-")
        return f"{PREFIXE_SURCOUCHE}-{pays}-{genre}-{base}"

    def _toutes_regions(self, base: ReferentielGeo) -> list[Region]:
        """Classeur ET surcouche — comme `_toutes_villes` le fait deja.

        DEFAUT du 14/08, attrape par le test d'invariants de la route : cette
        methode ne regardait QUE le classeur. Une region ajoutee deux fois
        n'etait donc jamais refusee — le second ajout ECRASAIT la premiere en
        silence (l'identifiant est deterministe). La non-duplication promise
        etait trouee precisement la ou l'ecran vient d'ouvrir la porte."""
        return list(base.regions.values()) + list(self.regions.values())

    def _toutes_villes(self, base: ReferentielGeo, pays: str) -> list[City]:
        villes = [v for v in base.villes.values() if v.country_iso2 == pays]
        villes += [v for v in self.villes.values() if v.country_iso2 == pays]
        return villes
