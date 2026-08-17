"""
app/services/referentiel_statique.py
====================================
Le referentiel statique du Loader — industries, secteurs, professions, pays,
fonctions de dirigeant.

**Un CATALOGUE, pas une injection.** Le Loader le charge en memoire et
**selectionne** dedans. Rien de tout cela n'est ecrit en base comme referentiel :
aucun des neuf services vivants n'expose de route pour un secteur, une industrie
ou une occupation. Mesure du 12/08 sur les cinq OpenAPI concernes — identity 12
routes, config 25, user 40, client 10, company 10 : **zero referentiel de ce
type**.

Ce que le serveur accepte, lui, ce sont des CHAINES LIBRES :

    CreateIdentitySchema.occupation   string, 1-200 caracteres, REQUIS
    CreateCompanySchema.industries    array of string, minItems 1, REQUIS
    CreateCompanySchema.sectors       array of string, minItems 1, REQUIS

C'est donc au Loader de porter la richesse, et de n'envoyer que des valeurs
justes. Exactement le patron deja prouve par la geographie : config-service ne
porte ni region, ni ville, ni quartier, et `Loader_Base_FinZuu_v1_1.xlsx` en porte
51 / 50 / 82.

PROVENANCE
----------
`1_Static_Data.zip`, produit par JJ Bwanga, transmis par Yaniv le 12/08/2026.
Quatre fichiers, dans `docs/reference/static_data/` :

    final_company_Industry-Sector.json  27 formes juridiques · 6 industries ·
                                        112 secteurs avec `industry_ids`
    Occupation.json                     21 groupes · 576 professions ·
                                        4 profils de revenu lognormaux
    Lieu2Nationalite.csv                195 pays, EN et FR
    Fonction_Compagnie_Dirigeants.csv   20 fonctions de dirigeant

CE QUE CE MODULE FAIT, ET CE QU'IL NE FAIT PAS
----------------------------------------------
Il charge, il valide, il expose. **Il n'appelle rien et ne decide rien.** Les
regles de selection — quel secteur pour quel type de Company, quelle profession
pour quelle famille `EF-24` — vivent chez leurs appelants, avec les quotas dont
elles dependent.

C'est deliberé : si le chargeur est faux, tout ce qui s'appuie sur lui est faux.
Le separer le rend mesurable sans toucher une ligne d'execution.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

#: Racine des fichiers de JJB. Le chemin est explicite dans les erreurs : un
#: referentiel introuvable interrompt l'execution, jamais en silence (`EF-01`
#: applique le meme principe a la geographie).
DOSSIER_DEFAUT: Final = Path("docs/reference/static_data")

FICHIER_SECTEURS: Final = "final_company_Industry-Sector.json"
FICHIER_OCCUPATIONS: Final = "Occupation.json"
FICHIER_PAYS: Final = "Lieu2Nationalite.csv"
FICHIER_FONCTIONS: Final = "Fonction_Compagnie_Dirigeants.csv"

#: Comptes attendus, mesures le 12/08 sur les fichiers livres. Ils ne sont pas
#: decoratifs : un fichier tronque ou remplace se detecte ici, avant que 20
#: Companies ou 2000 clients ne partent sur des services sans `DELETE`.
COMPTES_ATTENDUS: Final[dict[str, int]] = {
    "industries": 6,
    "secteurs": 112,
    "formes_juridiques": 27,
    "groupes": 21,
    "professions": 576,
    "profils_revenu": 4,
    "pays": 195,
    "fonctions_dirigeant": 20,
}


#: Nos quatre pays cibles, tels que `Lieu2Nationalite.csv` les NOMME. Mesure du
#: 12/08, et elle reserve deux surprises :
#:
#:   - la Cote d'Ivoire s'y appelle « Côte d'Ivoire », **pas** « Ivory Coast ».
#:     Chercher le libelle anglais attendu ne rend rien.
#:   - le libelle anglais porte l'apostrophe DROITE (`'`) et le francais
#:     l'apostrophe TYPOGRAPHIQUE (U+2019). Comparer les deux naivement echoue.
#:
#: Cette table est la seule facon fiable de relier un code ISO — le vocabulaire du
#: CDC — au libelle du fichier. La tache du lieu de naissance en depend.
PAYS_CIBLES_LIBELLES: Final[dict[str, str]] = {
    "CM": "Cameroon",
    "CI": "Côte d'Ivoire",
    "BF": "Burkina Faso",
    "SN": "Senegal",
}


class ReferentielIncoherent(ValueError):
    """Le referentiel ne tient pas debout — on refuse de demarrer.

    Jamais rattrapee : un referentiel incoherent produirait des entites
    incoherentes, et trois services n'exposent aucun `DELETE`.
    """


@dataclass(frozen=True, slots=True)
class ProfilRevenu:
    """Un profil de revenu lognormal — `LogNormal(mu, sigma)`.

    Les quatre profils du fichier, avec leur mediane implicite `exp(mu)` :

        bank_stable      mu 12,15  sigma 0,28  ->  189 094 FCFA
        sme_formal       mu 12,05  sigma 0,40  ->  171 099
        micro_informal   mu 11,65  sigma 0,55  ->  114 691
        agri_seasonal    mu 11,50  sigma 0,70  ->   98 716

    C'est ce modele qui remplacera l'heuristique `quick_win` de `solde_initial`
    (`A-09`) — un montant derive d'un revenu documente n'est plus une invention.
    """

    nom: str
    mu: float
    sigma: float
    definition: str


@dataclass(frozen=True, slots=True)
class GroupeProfessions:
    """Un groupe de professions et son profil de revenu par defaut.

    `variants` porte les exceptions du fichier : « Traditional healer » est dans
    le groupe *Health and social services* dont le defaut est `bank_stable`, mais
    son propre profil est `micro_informal`. Les ignorer classerait un guerisseur
    traditionnel au revenu d'un medecin hospitalier.
    """

    secteur: str
    profil_defaut: str
    professions: tuple[str, ...]
    variants: dict[str, str]

    def profil_de(self, profession: str) -> str:
        """Le profil d'une profession : sa variante si elle en a une, sinon le
        defaut du groupe."""
        return self.variants.get(profession, self.profil_defaut)


@dataclass(frozen=True, slots=True)
class FonctionDirigeant:
    """Une fonction de dirigeant, en trois formes. Le serveur ne veut qu'une
    chaine dans `occupation` ; nous gardons les trois pour choisir la bonne selon
    la langue de la region (`EF-` langue, `langue_de_la_region`)."""

    rang: int
    francais: str
    anglais: str
    abreviation: str


@dataclass(frozen=True, slots=True)
class ReferentielStatique:
    """Le catalogue complet, charge et valide. **Immuable.**

    Un referentiel qu'on pourrait modifier apres chargement ne serait pas un
    referentiel : deux appelants verraient deux verites.
    """

    #: id -> label. Six industries.
    industries: dict[int, str]
    #: label de secteur -> les industries auxquelles il appartient. Relation n:n :
    #: 28 des 112 secteurs en ont plusieurs (`Fintech` est Finance ET Technology).
    secteurs: dict[str, tuple[str, ...]]
    #: Les 27 formes juridiques, dans l'ordre du fichier.
    formes_juridiques: tuple[str, ...]
    #: Les 21 groupes de professions, par leur libelle de secteur.
    groupes: dict[str, GroupeProfessions]
    #: profession -> le groupe qui la porte. 576 entrees, sans doublon.
    professions: dict[str, str]
    #: nom -> profil. Quatre profils lognormaux.
    profils_revenu: dict[str, ProfilRevenu]
    #: libelle anglais -> libelle francais. 195 pays.
    pays: dict[str, str]
    #: Les 20 fonctions de dirigeant, par rang.
    fonctions_dirigeant: tuple[FonctionDirigeant, ...]
    #: Les alias de normalisation du fichier : 38 entrees, brut -> canonique.
    alias: dict[str, str]

    # ------------------------------------------------------------------
    # Lectures — c'est ce que les appelants utilisent
    # ------------------------------------------------------------------

    def industrie_du_secteur(self, secteur: str) -> str:
        """L'industrie d'un secteur. **Une seule**, deterministe.

        Un secteur peut appartenir a plusieurs industries — 28 sur 112. Une
        Company, elle, a UNE industrie principale : c'est ainsi qu'une entreprise
        se classe (une activite principale, des activites secondaires). Rendre
        l'union produirait des absurdites, et c'est mesure : une fondation
        caritative tombait en « Technology » parce que `Health` appartient a la
        fois a Commerce et a Technology.

        Le choix est la premiere par ordre alphabetique — arbitraire mais STABLE,
        donc reproductible (`ENF-15`).
        """
        industries = self.secteurs.get(secteur)
        if not industries:
            raise ReferentielIncoherent(
                f"secteur inconnu : {secteur!r}. Les libelles admis viennent de "
                f"{FICHIER_SECTEURS} ; en inventer un enverrait au serveur une "
                "valeur qui n'existe dans aucune source."
            )
        return min(industries)

    def secteurs_de_l_industrie(self, industrie: str) -> tuple[str, ...]:
        """Tous les secteurs d'une industrie, tries. Sert a verifier qu'un
        secteur connexe declare partage bien l'industrie de son principal."""
        return tuple(sorted(s for s, inds in self.secteurs.items() if industrie in inds))

    def groupe_de_la_profession(self, profession: str) -> GroupeProfessions:
        cle = self.professions.get(profession)
        if cle is None:
            raise ReferentielIncoherent(f"profession inconnue : {profession!r}")
        return self.groupes[cle]

    def profil_de_la_profession(self, profession: str) -> ProfilRevenu:
        """Le profil de revenu d'une profession — variante comprise."""
        groupe = self.groupe_de_la_profession(profession)
        return self.profils_revenu[groupe.profil_de(profession)]

    def professions_des_groupes(self, secteurs: tuple[str, ...]) -> tuple[str, ...]:
        """Toutes les professions de plusieurs groupes, triees et sans doublon.

        Sert a la table de correspondance des quatre familles du CDC (`EF-24`) :
        `AGRICULTURE` reunit quatre groupes, `SERVICES` en reunit quatorze.
        """
        vues: set[str] = set()
        for secteur in secteurs:
            groupe = self.groupes.get(secteur)
            if groupe is None:
                raise ReferentielIncoherent(f"groupe inconnu : {secteur!r}")
            vues.update(groupe.professions)
        return tuple(sorted(vues))

    def nom_du_pays(self, code_iso: str, *, en_francais: bool = True) -> str:
        """Le nom d'un de nos quatre pays cibles, depuis son code ISO.

        `nationality` exige l'alpha-2 (mesure du 08/08 : « Cameroun » rend un
        HTTP 422), mais un LIEU de naissance s'ecrit en clair. Les deux formes
        cohabitent donc, et cette methode fait le pont.
        """
        libelle = PAYS_CIBLES_LIBELLES.get(code_iso.upper())
        if libelle is None:
            raise ReferentielIncoherent(
                f"pays hors perimetre : {code_iso!r}. Les quatre cibles du CDC sont "
                f"{sorted(PAYS_CIBLES_LIBELLES)}."
            )
        return self.pays[libelle] if en_francais else libelle

    def normaliser(self, brut: str) -> str:
        """Applique les alias du fichier. Rend l'entree inchangee si aucun alias
        ne s'applique — un alias absent n'est pas une erreur."""
        return self.alias.get(brut, brut)


# --------------------------------------------------------------------------
# Le chargement — il valide autant qu'il lit
# --------------------------------------------------------------------------


def _lire_json(chemin: Path) -> Any:
    if not chemin.exists():
        raise FileNotFoundError(
            f"Referentiel statique introuvable. Chemin attendu : {chemin.resolve()}"
        )
    return json.loads(chemin.read_text(encoding="utf-8"))


def _lire_csv(chemin: Path) -> list[dict[str, str]]:
    if not chemin.exists():
        raise FileNotFoundError(
            f"Referentiel statique introuvable. Chemin attendu : {chemin.resolve()}"
        )
    # `utf-8-sig` : les deux CSV portent un BOM. Sans cela, la premiere colonne
    # s'appelle « ﻿Country_EN » et aucune lecture par nom ne fonctionne.
    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        return list(csv.DictReader(fichier))


def _charger_secteurs(
    dossier: Path,
) -> tuple[dict[int, str], dict[str, tuple[str, ...]], tuple[str, ...]]:
    brut = _lire_json(dossier / FICHIER_SECTEURS)
    industries = {int(i["id"]): str(i["label"]) for i in brut["industries"]}

    secteurs: dict[str, tuple[str, ...]] = {}
    for entree in brut["sectors"]:
        label = str(entree["label"])
        ids = [int(i) for i in entree["industry_ids"]]
        inconnus = [i for i in ids if i not in industries]
        if inconnus:
            raise ReferentielIncoherent(
                f"secteur {label!r} rattache aux industries {inconnus} qui "
                f"n'existent pas. {FICHIER_SECTEURS} est incoherent avec lui-meme."
            )
        secteurs[label] = tuple(sorted(industries[i] for i in ids))

    formes = tuple(str(f) for f in brut["company_types"])
    return industries, secteurs, formes


def _charger_occupations(
    dossier: Path,
) -> tuple[dict[str, GroupeProfessions], dict[str, str], dict[str, ProfilRevenu], dict[str, str]]:
    brut = _lire_json(dossier / FICHIER_OCCUPATIONS)

    profils = {
        nom: ProfilRevenu(
            nom=nom,
            mu=float(p["mu"]),
            sigma=float(p["sigma"]),
            definition=str(p["definition"]),
        )
        for nom, p in brut["income_profiles"].items()
    }

    groupes: dict[str, GroupeProfessions] = {}
    professions: dict[str, str] = {}
    for entree in brut["profession_groups"]:
        secteur = str(entree["sector"])
        defaut = str(entree["default_profile"])
        if defaut not in profils:
            raise ReferentielIncoherent(
                f"groupe {secteur!r} : profil par defaut {defaut!r} inconnu"
            )
        variants = {str(k): str(v) for k, v in (entree.get("variants") or {}).items()}
        inconnus = sorted({v for v in variants.values() if v not in profils})
        if inconnus:
            raise ReferentielIncoherent(
                f"groupe {secteur!r} : variantes vers des profils inconnus {inconnus}"
            )
        metiers = tuple(str(p) for p in entree["professions"])
        groupes[secteur] = GroupeProfessions(
            secteur=secteur,
            profil_defaut=defaut,
            professions=metiers,
            variants=variants,
        )
        # Une profession presente dans DEUX groupes serait ambigue : son profil de
        # revenu dependrait de l'ordre de lecture. On le refuse.
        for metier in metiers:
            if metier in professions:
                raise ReferentielIncoherent(
                    f"profession {metier!r} presente dans {professions[metier]!r} "
                    f"ET {secteur!r} — son profil de revenu serait ambigu"
                )
            professions[metier] = secteur

    alias = {str(k): str(v) for k, v in (brut.get("normalization_aliases") or {}).items()}
    return groupes, professions, profils, alias


def _charger_pays(dossier: Path) -> dict[str, str]:
    lignes = _lire_csv(dossier / FICHIER_PAYS)
    return {str(ligne["Country_EN"]).strip(): str(ligne["Pays_FR"]).strip() for ligne in lignes}


def _charger_fonctions(dossier: Path) -> tuple[FonctionDirigeant, ...]:
    lignes = _lire_csv(dossier / FICHIER_FONCTIONS)
    return tuple(
        FonctionDirigeant(
            rang=int(ligne["N"]),
            francais=str(ligne["Fonction (Français)"]).strip(),
            anglais=str(ligne["Function (English)"]).strip(),
            abreviation=str(ligne["Abréviation"]).strip(),
        )
        for ligne in lignes
    )


def charger_statique(dossier: Path | None = None) -> ReferentielStatique:
    """Charge et valide le catalogue de JJB. **Echoue bruyamment.**

    Deux familles de controles, et les deux comptent :

    1. **La coherence interne** — aucun `industry_id` orphelin, aucun profil de
       revenu inconnu, aucune profession dans deux groupes, aucun libelle vide.
    2. **Les comptes attendus** — 6 / 112 / 27 / 21 / 576 / 4 / 195 / 20, mesures
       le 12/08. Un fichier tronque ou remplace se detecte ICI, avant que 20
       Companies ou 2000 clients ne partent sur des services sans `DELETE`.

    Le second controle est le plus important en exploitation. Si JJB livre une
    version 2 du fichier, le chargement echoue et l'ecart se lit dans le message —
    plutot que de decouvrir apres coup que 2000 clients portent une occupation
    disparue.
    """
    dossier = dossier or DOSSIER_DEFAUT
    industries, secteurs, formes = _charger_secteurs(dossier)
    groupes, professions, profils, alias = _charger_occupations(dossier)

    referentiel = ReferentielStatique(
        industries=industries,
        secteurs=secteurs,
        formes_juridiques=formes,
        groupes=groupes,
        professions=professions,
        profils_revenu=profils,
        pays=_charger_pays(dossier),
        fonctions_dirigeant=_charger_fonctions(dossier),
        alias=alias,
    )
    _valider(referentiel)
    return referentiel


def _valider(r: ReferentielStatique) -> None:
    """Les controles qui refusent un referentiel inutilisable."""
    reels = {
        "industries": len(r.industries),
        "secteurs": len(r.secteurs),
        "formes_juridiques": len(r.formes_juridiques),
        "groupes": len(r.groupes),
        "professions": len(r.professions),
        "profils_revenu": len(r.profils_revenu),
        "pays": len(r.pays),
        "fonctions_dirigeant": len(r.fonctions_dirigeant),
    }
    ecarts = {
        cle: (attendu, reels[cle])
        for cle, attendu in COMPTES_ATTENDUS.items()
        if reels[cle] != attendu
    }
    if ecarts:
        detail = " · ".join(
            f"{cle} : {reel} au lieu de {attendu}" for cle, (attendu, reel) in ecarts.items()
        )
        raise ReferentielIncoherent(
            f"Les comptes du referentiel statique ont change — {detail}. "
            "Mesures du 12/08 sur les fichiers de JJB. Si la livraison a evolue, "
            "mettre COMPTES_ATTENDUS a jour APRES avoir verifie ce qui a change : "
            "20 Companies et 2000 clients en dependent, sur des services sans DELETE."
        )

    # Aucun libelle vide, nulle part. `INV-CPY-03/04` exige `minItems: 1` sur
    # `industries` et `sectors` — mais une liste de UNE chaine vide passe ce
    # controle sans rien signifier. C'est exactement le defaut mesure le 12/08 sur
    # nos Fondations, qui recevaient `sectors=[""]`.
    vides: list[str] = []
    if any(not label.strip() for label in r.industries.values()):
        vides.append("industries")
    if any(not s.strip() for s in r.secteurs):
        vides.append("secteurs")
    if any(not f.strip() for f in r.formes_juridiques):
        vides.append("formes_juridiques")
    if any(not p.strip() for p in r.professions):
        vides.append("professions")
    if any(not fr.strip() or not en.strip() for en, fr in r.pays.items()):
        vides.append("pays")
    if any(not f.francais.strip() or not f.anglais.strip() for f in r.fonctions_dirigeant):
        vides.append("fonctions_dirigeant")
    if vides:
        raise ReferentielIncoherent(
            f"libelles vides dans : {', '.join(vides)}. Une chaine vide passe le "
            "minItems=1 du serveur sans rien signifier — c'est un doublon de "
            "defaut, pas une valeur."
        )


def referentiel_effectif(
    base: ReferentielStatique,
    *,
    secteurs_ajoutes: dict[str, tuple[str, ...]] | None = None,
    industries_ajoutees: list[str] | None = None,
) -> ReferentielStatique:
    """Le referentiel EFFECTIF qu'un run consomme : la base (classeur immuable)
    FUSIONNEE avec les ajouts de la surcouche.

    C'est LUI, pas la base seule, qui doit nourrir le generateur ET l'ecran.
    Sans cette fusion, un secteur ajoute est un mensonge a l'ecran : le run lit
    `charger_statique()` (la base), donc ne le voit jamais, et
    `industrie_du_secteur()` LEVE dessus. Ici, l'industrie d'un secteur ajoute se
    resout naturellement (il est dans `secteurs`), et la structure ne casse plus.

    L'immuabilite porte sur le FICHIER de JJB, pas sur le referentiel de run : ce
    dernier est COMPOSE. L'original reste intact (frozen) — on rend une copie.
    """
    secteurs_ajoutes = secteurs_ajoutes or {}
    industries_ajoutees = industries_ajoutees or []
    if not secteurs_ajoutes and not industries_ajoutees:
        return base
    secteurs = {**base.secteurs, **{s: tuple(i) for s, i in secteurs_ajoutes.items()}}
    industries = dict(base.industries)
    connues = set(industries.values())
    prochain = (max(industries) + 1) if industries else 1
    for label in industries_ajoutees:
        if label not in connues:
            industries[prochain] = label
            connues.add(label)
            prochain += 1
    return replace(base, secteurs=secteurs, industries=industries)
