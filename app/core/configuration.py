"""
app/core/configuration.py
=========================
Configuration d'execution — l'exigence de parametrage de la Direction Technique.

> *« Il est super important que le Loader soit flexible et parametrable :
> activation et desactivation d'un pays, ajout region/ville, creer nb
> users/company par pays/region/ville, homme versus femme. »*
> — Direction Technique, 9 aout 2026

Analyse d'impact complete : `docs/EXIGENCE_PARAMETRAGE.md`.

**LA CONCEPTION EXISTAIT DEJA.** La feuille `Config_Loader` de
`Loader_Base_FinZuu_v1_1.xlsx` porte 8 sections de parametres, sous-titrees
« Parametres pilotes par le boss (message WhatsApp 16/07/2026) ». Le boss n'a
pas formule une exigence nouvelle le 9 aout : **il a rappele une conception
posee le 16 juillet**, que nous n'avions pas lue.

Ce que cette feuille fixe, et que ce module respecte :

    Distribution par pays        25 % chacun — 4 pays equipoids
    Pourcentage < 25 ans         60 %                          (EF-22)
    Ratio femmes / hommes        2 / 1  =  66,7 % / 33,3 %     (EF-22)
    Societes / individus         20 % / 80 %                   (EF-23)
    Agriculture                  20 % des professionnels       (EF-24)
    Lenders locaux par pays      3  ->  12 au total            (EF-12)
    Societes creees par jour     3 minimum                     (EF-40)
    Entrees par jour             10                            (EF-41)

Le defaut de `repartir_clients()` — parts egales entre pays actifs — n'est donc
pas une invention : c'est la ligne « Distribution par pays : 25 % chacun ».

LES TROIS REGLES QUI GOUVERNENT CE MODULE
------------------------------------------

**1. Le parametrage touche les QUANTITES, jamais les INVARIANTS.**
Que le Super-Admin demande 500 clientes au Cameroun ou 50 au Burkina, chacune
aura toujours un age credible, une devise coherente avec sa zone monetaire, un
numero attribuable a un operateur reel et une adresse complete.
`app/core/invariants.py` ne connait pas ce module et n'en depend jamais.

**2. Sans parametre, le CDC s'applique — exactement.**
Les constantes de `app/core/cdc.py` deviennent des DEFAUTS CONTRACTUELS, elles
ne disparaissent pas. Un lancement nu doit produire ce que le CDC decrit. C'est
la garantie que le parametrage n'affaiblit pas l'exigence.

**3. Un ecart au CDC est AUTORISE mais jamais SILENCIEUX.**
Le Super-Admin peut demander 50/50 la ou `EF-22` exige deux femmes pour un
homme. On l'accepte — c'est sa decision — et le rapport le SIGNALE. Sinon
`CR-09` declarerait conforme une execution qui ne l'est pas.
Tracabilite plutot que rigidite ; jamais le silence.

LA RESOLUTION EN CASCADE
------------------------
Un quota global devient un arbre. Le niveau le plus fin l'emporte ; en son
absence, on remonte. Aucun territoire ne peut se retrouver sans regle.

    defaut CDC  ──►  pays  ──►  region  ──►  ville     (le plus precis gagne)

SOFT-DELETE, PAS SUPPRESSION
----------------------------
Un pays retire de la generation est marque **inactif**, jamais efface. On garde
la trace de ce qui a ete exclu, on peut le reactiver, et le tableau de bord peut
montrer *ce qui a ete retire et pourquoi*.

C'est la meilleure idee de config-service — `activate`/`deactivate` plutot que
`DELETE` — et nous la reprenons telle quelle
(`docs/ANALYSE_CONFIG_SERVICE.md` §4.2).

TENSION AVEC ENF-15 — le point dur
-----------------------------------
Des que la volumetrie devient parametrable, **le `run_id` ne suffit plus** a
reproduire une execution. La configuration doit etre PERSISTEE avec le run.
`empreinte()` produit la forme serialisable qui va dans `loader_runs` ; sans
elle, `ENF-15` est perdue et `CR-04` devient inverifiable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from app.core.cdc import (
    COMPANIES_PAR_PAYS,
    KIOSQUES_PAR_PAYS,
    NB_CLIENTS,
    PART_CORPORATE,
    PAYS_CIBLES,
    RATIO_FEMMES_HOMMES,
    STAFF_PAR_PAYS,
)

#: Les quatre quantites parametrables, avec leur defaut contractuel. Toute
#: nouvelle quantite s'ajoute ICI — elle nait parametrable, jamais figee.
DEFAUTS_CDC: Final[dict[str, Any]] = {
    "companies": COMPANIES_PAR_PAYS,
    "kiosques": KIOSQUES_PAR_PAYS,
    "staff": STAFF_PAR_PAYS,
    "part_corporate": PART_CORPORATE,
}

#: `EF-22` : deux femmes pour un homme. Exprime en part de femmes pour que la
#: comparaison a un parametrage libre soit directe.
PART_FEMMES_CDC: Final = RATIO_FEMMES_HOMMES[0] / sum(RATIO_FEMMES_HOMMES)


@dataclass(slots=True)
class Surcharge:
    """Ce qu'un territoire redefinit. Tout est optionnel — `None` veut dire
    « je ne me prononce pas, remonte au niveau superieur »."""

    companies: tuple[int, int] | None = None
    kiosques: tuple[int, int] | None = None
    staff: tuple[int, int] | None = None
    clients: int | None = None
    part_femmes: float | None = None
    part_corporate: float | None = None

    def valeur(self, quantite: str) -> Any:
        return getattr(self, quantite, None)


@dataclass(slots=True)
class ConfigurationPays:
    """Un pays, son etat, et ses surcharges a trois niveaux.

    `actif` est un **etat**, pas une suppression : un pays retire garde sa
    place dans la configuration, avec le motif de son retrait.
    """

    code: str
    actif: bool = True
    motif_inactivite: str = ""
    surcharge: Surcharge = field(default_factory=Surcharge)
    regions: dict[str, Surcharge] = field(default_factory=dict)
    villes: dict[str, Surcharge] = field(default_factory=dict)

    def desactiver(self, motif: str) -> None:
        """Retire le pays de la generation — **sans rien effacer**.

        N'emet aucun appel reseau. Desactiver un pays *chez nous* et le
        desactiver *sur config-service* sont deux actes distincts (`A-08`) :
        le second touche un referentiel partage par toute l'equipe.
        """
        self.actif = False
        self.motif_inactivite = motif.strip() or "non precise"

    def reactiver(self) -> None:
        self.actif = True
        self.motif_inactivite = ""


@dataclass(slots=True)
class ConfigurationExecution:
    """La configuration complete d'un run — ce qui sera persiste avec lui.

    Construite vide, elle reproduit **exactement** le CDC : les quatre pays
    actifs, les volumetries contractuelles, les quotas d'`EF-22` a `EF-24`.
    """

    pays: dict[str, ConfigurationPays] = field(default_factory=dict)
    nb_clients: int = NB_CLIENTS

    @classmethod
    def defaut_cdc(cls) -> ConfigurationExecution:
        """La configuration que le CDC decrit, sans aucune surcharge."""
        return cls(pays={code: ConfigurationPays(code=code) for code in PAYS_CIBLES})

    # -- Etat du territoire -------------------------------------------------

    @property
    def pays_actifs(self) -> list[str]:
        return sorted(code for code, fiche in self.pays.items() if fiche.actif)

    @property
    def pays_inactifs(self) -> list[str]:
        return sorted(code for code, fiche in self.pays.items() if not fiche.actif)

    def desactiver_pays(self, code: str, motif: str) -> None:
        fiche = self.pays.get(code.strip().upper())
        if fiche is None:
            raise ValueError(f"pays {code!r} absent de la configuration")
        fiche.desactiver(motif)

    # -- Resolution en cascade ---------------------------------------------

    def resoudre(self, quantite: str, pays: str, region: str = "", ville: str = "") -> Any:
        """Rend la valeur applicable au territoire le plus fin renseigne.

        Ordre de priorite : **ville → region → pays → defaut CDC**. Une
        quantite absente partout retombe sur le CDC ; **aucun territoire ne
        peut se retrouver sans regle**.

        ⚠️ **`clients` est refuse ici, volontairement.** C'est une quantite
        GLOBALE : demander « combien de clients au Cameroun » a `resoudre()`
        rendrait le total, et quatre pays feraient 8000 clients. L'erreur est
        rendue impossible plutot que documentee — `repartir_clients()` est le
        seul chemin.
        """
        if quantite == "clients":
            raise ValueError(
                "`clients` est une quantite GLOBALE : utiliser repartir_clients(), qui "
                "alloue le total entre les pays actifs. resoudre() rendrait le total pour "
                "chaque pays — quatre pays feraient quatre fois le volume demande."
            )
        fiche = self.pays.get(pays.strip().upper())
        if fiche is not None:
            for cle, table in ((ville, fiche.villes), (region, fiche.regions)):
                if cle:
                    surcharge = table.get(cle)
                    if surcharge is not None:
                        valeur = surcharge.valeur(quantite)
                        if valeur is not None:
                            return valeur
            valeur = fiche.surcharge.valeur(quantite)
            if valeur is not None:
                return valeur
        if quantite == "part_femmes":
            return PART_FEMMES_CDC
        return DEFAUTS_CDC.get(quantite)

    # -- Repartition — resoudre ne suffit pas, il faut ALLOUER --------------

    def repartir_clients(self) -> dict[str, int]:
        """Repartit le total entre les pays **actifs**, et rend la part de chacun.

        `resoudre()` repond « quelle regle s'applique ici » ; c'est insuffisant
        pour une quantite **globale**. Demander la part du Cameroun ne peut pas
        rendre 2000 — sinon quatre pays feraient 8000 clients.

        Regle : les pays qui portent une surcharge `clients` la gardent ; le
        **reste** se partage a parts egales entre les autres. Le dernier absorbe
        l'arrondi, pour que la somme tombe **exactement** sur le total.

        Un pays desactive recoit **zero** — sans disparaitre du resultat, pour
        que le tableau de bord puisse montrer qu'il a ete exclu.
        """
        parts: dict[str, int] = {code: 0 for code in sorted(self.pays)}
        actifs = self.pays_actifs
        if not actifs:
            return parts

        imposes: dict[str, int] = {}
        for code in actifs:
            impose = self.pays[code].surcharge.clients
            if impose is not None:
                imposes[code] = int(impose)
        libres = [code for code in actifs if code not in imposes]
        parts.update(imposes)

        reste = self.nb_clients - sum(imposes.values())
        if not libres:
            return parts
        if reste < 0:
            # Les surcharges depassent deja le total : on ne complete pas, et
            # `ecarts_au_cdc()` le signalera. On ne corrige jamais en silence.
            return parts

        base, surplus = divmod(reste, len(libres))
        for rang, code in enumerate(libres):
            parts[code] = base + (1 if rang < surplus else 0)
        return parts

    # -- Validation contre le referentiel reel ------------------------------

    def valider_contre_referentiel(self, referentiel: Any) -> list[str]:
        """Refuse toute surcharge portant sur un territoire **inexistant**.

        **Pourquoi ce controle existe.** Nous reprochons a account-service
        d'accepter un `owner_id` qui ne resout nulle part (`FRA-224`), et a
        depositary-service un `company_id` inexistant (`FRA-225`). Une
        configuration qui accepterait `regions["Atlantide"]` commettrait
        exactement la meme faute — sur nos propres donnees.

        Rend la liste des references mortes. Vide = configuration saine.
        """
        problemes: list[str] = []
        for code, fiche in sorted(self.pays.items()):
            if referentiel.pays(code) is None:
                problemes.append(f"pays {code} absent du referentiel geographique")
                continue
            regions = {r.name for r in referentiel.regions_du_pays(code)}
            villes = {
                v.name
                for r in referentiel.regions_du_pays(code)
                for v in referentiel.villes_de_region(r.region_id)
            }
            for nom in sorted(fiche.regions):
                if nom not in regions:
                    problemes.append(f"{code} : region {nom!r} inexistante — surcharge morte")
            for nom in sorted(fiche.villes):
                if nom not in villes:
                    problemes.append(f"{code} : ville {nom!r} inexistante — surcharge morte")
        return problemes

    # -- Ecarts au CDC — autorises, jamais silencieux -----------------------

    def ecarts_au_cdc(self) -> list[str]:
        """Enumere tout ce qui s'ecarte du contrat.

        **Le rapport d'execution DOIT porter cette liste.** Sans elle, `CR-09`
        declarerait conforme un run qui ne l'est pas — par exemple un
        parametrage 50/50 la ou `EF-22` exige deux femmes pour un homme.
        """
        ecarts: list[str] = []

        manquants = [code for code in PAYS_CIBLES if code not in self.pays]
        for code in manquants:
            ecarts.append(f"pays {code} absent de la configuration — OBJ-01 exige les 4 pays")
        for code in self.pays_inactifs:
            motif = self.pays[code].motif_inactivite
            ecarts.append(f"pays {code} desactive ({motif}) — OBJ-01 exige les 4 pays")

        if self.nb_clients != NB_CLIENTS:
            ecarts.append(
                f"{self.nb_clients} clients demandes au lieu de {NB_CLIENTS} — OBJ-02 / EF-77"
            )

        # La somme des parts imposees peut depasser le total. On ne corrige
        # JAMAIS en silence : une repartition qui ne tombe pas juste est une
        # incoherence que le Super-Admin doit voir.
        imposes = sum(
            self.repartir_clients()[code]
            for code in self.pays_actifs
            if self.pays[code].surcharge.clients is not None
        )
        if imposes > self.nb_clients:
            ecarts.append(
                f"les parts imposees totalisent {imposes} clients pour un total de "
                f"{self.nb_clients} — repartition impossible, les pays sans surcharge "
                "recevront zero"
            )
        elif (
            imposes
            and imposes < self.nb_clients
            and not [code for code in self.pays_actifs if self.pays[code].surcharge.clients is None]
        ):
            ecarts.append(
                f"les parts imposees totalisent {imposes} clients pour un total de "
                f"{self.nb_clients} — {self.nb_clients - imposes} clients ne seront pas generes"
            )

        # Une surcharge sur un pays desactive ne sera jamais appliquee. Ce n'est
        # pas une faute, c'est un oubli probable — on le signale.
        for code in self.pays_inactifs:
            fiche = self.pays[code]
            if _serialiser(fiche.surcharge) or fiche.regions or fiche.villes:
                ecarts.append(
                    f"pays {code} desactive mais porte des surcharges — elles resteront sans effet"
                )

        for code, fiche in sorted(self.pays.items()):
            portees: list[tuple[str, Surcharge]] = [(code, fiche.surcharge)]
            portees += [(f"{code}/{n}", s) for n, s in sorted(fiche.regions.items())]
            portees += [(f"{code}/{n}", s) for n, s in sorted(fiche.villes.items())]
            for portee, surcharge in portees:
                if surcharge.part_femmes is not None and not _proche(
                    surcharge.part_femmes, PART_FEMMES_CDC
                ):
                    ecarts.append(
                        f"{portee} : part de femmes {surcharge.part_femmes:.0%} au lieu de "
                        f"{PART_FEMMES_CDC:.0%} — EF-22 exige deux femmes pour un homme"
                    )
                if surcharge.part_corporate is not None and not _proche(
                    surcharge.part_corporate, PART_CORPORATE
                ):
                    ecarts.append(
                        f"{portee} : part corporate {surcharge.part_corporate:.0%} au lieu de "
                        f"{PART_CORPORATE:.0%} — EF-23 exige 80/20"
                    )
        return ecarts

    @property
    def conforme_au_cdc(self) -> bool:
        return not self.ecarts_au_cdc()

    # -- Persistance — prerequis d'ENF-15 -----------------------------------

    def empreinte(self) -> dict[str, Any]:
        """Forme serialisable, a stocker dans `loader_runs`.

        **Rejouer un run, c'est rejouer `run_id` ET sa configuration.** Sans
        cette empreinte, deux executions du meme `run_id` sous des parametres
        differents produiraient des resultats differents — `ENF-15` serait
        perdue et `CR-04` invérifiable.
        """
        return {
            "nb_clients": self.nb_clients,
            "repartition_clients": self.repartir_clients(),
            "pays": {
                code: {
                    "actif": fiche.actif,
                    "motif_inactivite": fiche.motif_inactivite,
                    "surcharge": _serialiser(fiche.surcharge),
                    "regions": {n: _serialiser(s) for n, s in sorted(fiche.regions.items())},
                    "villes": {n: _serialiser(s) for n, s in sorted(fiche.villes.items())},
                }
                for code, fiche in sorted(self.pays.items())
            },
            "ecarts_au_cdc": self.ecarts_au_cdc(),
        }

    def resume(self) -> str:
        lignes = [
            f"Pays actifs   : {', '.join(self.pays_actifs) or 'AUCUN'}",
            f"Pays exclus   : {', '.join(self.pays_inactifs) or 'aucun'}",
            f"Clients       : {self.nb_clients}",
        ]
        ecarts = self.ecarts_au_cdc()
        if ecarts:
            lignes.append(f"ECARTS AU CDC : {len(ecarts)}")
            lignes.extend(f"  - {e}" for e in ecarts)
        else:
            lignes.append("Conforme au CDC : oui")
        return "\n".join(lignes)


def _serialiser(surcharge: Surcharge) -> dict[str, Any]:
    return {
        champ: valeur
        for champ in ("companies", "kiosques", "staff", "clients", "part_femmes", "part_corporate")
        if (valeur := getattr(surcharge, champ)) is not None
    }


def _proche(a: float, b: float, tolerance: float = 1e-9) -> bool:
    return abs(a - b) <= tolerance
