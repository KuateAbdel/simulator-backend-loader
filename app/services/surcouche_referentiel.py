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

from dataclasses import dataclass, field
from typing import Any

from app.services.geographie import City, District, RapportGeographique, ReferentielGeo, Region

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
            nb_telcos=base.rapport.nb_telcos,
            nb_devises=base.rapport.nb_devises,
            orphelins=list(base.rapport.orphelins),
        )
        return ReferentielGeo(
            regions={**base.regions, **self.regions},
            villes={**base.villes, **self.villes},
            quartiers={**base.quartiers, **self.quartiers},
            rapport=rapport,
            telcos=base.telcos,
            devises=base.devises,
            pays_index=base.pays_index,
        )

    # -- Tracabilite --------------------------------------------------------

    @property
    def vide(self) -> bool:
        return not (self.regions or self.villes or self.quartiers)

    def ajouts(self) -> dict[str, Any]:
        """Forme serialisable — a joindre a l'empreinte du run (`ENF-15`).

        Sans elle, rejouer un `run_id` sur un referentiel surcharge donnerait
        un resultat different. La surcouche fait partie de la configuration.
        """
        return {
            "regions": {i: r.name for i, r in sorted(self.regions.items())},
            "villes": {i: v.name for i, v in sorted(self.villes.items())},
            "quartiers": {i: q.name for i, q in sorted(self.quartiers.items())},
            "journal": list(self.journal),
        }

    def resume(self) -> str:
        if self.vide:
            return "Surcouche : aucun ajout — le referentiel est celui du classeur"
        return (
            f"Surcouche : {len(self.regions)} region(s) · {len(self.villes)} ville(s) · "
            f"{len(self.quartiers)} quartier(s) — le classeur n'a pas ete modifie"
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

    @staticmethod
    def _toutes_regions(base: ReferentielGeo) -> list[Region]:
        return list(base.regions.values())

    def _toutes_villes(self, base: ReferentielGeo, pays: str) -> list[City]:
        villes = [v for v in base.villes.values() if v.country_iso2 == pays]
        villes += [v for v in self.villes.values() if v.country_iso2 == pays]
        return villes
