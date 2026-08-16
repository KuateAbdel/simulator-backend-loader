"""
app/clients/config_service.py
=============================
Client config-service — DEUX surfaces, volontairement separees.

  `ConfigServiceClient`            LECTURE SEULE — utilisee pendant la generation
  `AdministrationConfigService`    ECRITURE — actions explicites du Super-Admin

Les melanger exposerait une ecriture a portee de main dans un chemin qui ne
doit jamais en faire.

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

import re
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
    #: `D-CFG-2` — le total inclut les parasites, l'exploitable non. Les deux
    #: sont dits : cacher l'ecart reviendrait a nier l'etat de l'environnement.
    nb_telcos_exploitables: int = 0
    telcos_ecartes: list[str] = field(default_factory=list)

    @property
    def complet(self) -> bool:
        return not self.pays_manquants and not self.pays_incomplets

    def resume(self) -> str:
        lignes = [
            f"Pays cibles trouves : {len(self.pays_trouves)}/{len(PAYS_CIBLES)}",
            f"Devises : {self.nb_devises} | Telcos : {self.nb_telcos} "
            f"(dont {self.nb_telcos_exploitables} exploitables)",
        ]
        if self.pays_manquants:
            lignes.append(f"MANQUANTS : {', '.join(self.pays_manquants)}")
        if self.pays_incomplets:
            details = ", ".join(f"{iso} ({motif})" for iso, motif in self.pays_incomplets.items())
            lignes.append(f"INCOMPLETS : {details}")
        if self.telcos_ecartes:
            lignes.append(
                f"Telcos ecartes (regex inexploitable, `D-CFG-1`) : "
                f"{', '.join(self.telcos_ecartes)}"
            )
        if self.entrees_ignorees:
            lignes.append(
                f"Entrees hors perimetre ignorees : {len(self.entrees_ignorees)} "
                f"({', '.join(self.entrees_ignorees)})"
            )
        return "\n".join(lignes)


def regex_exploitable(motif: str) -> bool:
    """`D-CFG-1` — un motif de numerotation sans ancres ne valide RIEN.

    `MTNcongo1` porte `6|333` : sans `^` ni `$`, ce motif accepte tout numero
    contenant un `6` ou la sequence `333`. C'est une validation en apparence,
    et le plus grave des six parasites de l'environnement.

    **Le Loader ne le corrige pas — il ne le consomme pas.** Nous ne sommes pas
    la pour reparer config-service ; nous sommes la pour n'etre pas atteints
    par ses defauts.
    """
    if not motif or "^" not in motif or "$" not in motif:
        return False
    try:
        re.compile(motif)
    except re.error:
        return False
    return True


class ConfigServiceClient:
    """Acces en LECTURE au referentiel geographique et monetaire.

    `D-CFG-1` — **`EF-27` ne se joue JAMAIS sur les regex de ce service.**

    Le CDC dit « valider le MSISDN contre le regex de l'operateur telco du
    pays ». Lu naivement, cela designe config-service. Nous ne le faisons pas,
    et ce refus est une DECISION, pas un oubli :

      - `MTNcongo1` porte `6|333`, **sans ancres** — il validerait tout ;
      - `cm` est un doublon exact d'Expresso Senegal ;
      - `Moov Africa CI` est partage entre `CI` et le pays parasite `ca`.

    `app/services/geographie.py` porte les **12 plans de numerotation reels**
    depuis le depart, et c'est LUI qui fait autorite (`valider_msisdn_operateur`).
    Un developpeur qui « ameliorerait » le Loader en lisant le regex serveur
    reintroduirait `6|333` sans s'en apercevoir — d'ou cette note ici, au point
    ou la tentation se presente.

    `D-CFG-2` — **aucun comptage brut.** L'environnement porte 6 entrees
    parasites sur 24 (2 devises, 2 pays, 2 operateurs). Annoncer « 14 telcos »
    serait exact et trompeur. Chaque lecture distingue donc le TOTAL de
    l'EXPLOITABLE, et le rapport montre les deux.
    """

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
        telcos = await self.lister_telcos()
        rapport.nb_telcos = len(telcos)
        for telco in telcos:
            # Le champ s'appelle `phone_regex`. Ma premiere version lisait
            # `regex` puis `pattern` — deux champs qui N'EXISTENT PAS. Elle
            # aurait declare les QUATORZE operateurs inexploitables : une garde
            # qui condamne tout au lieu de proteger. Trouve le 10/08 en
            # comparant notre referentiel au serveur, jamais par un test — la
            # methode n'est appelee nulle part (ecart #4).
            motif = str(telco.get("phone_regex") or "")
            if regex_exploitable(motif):
                rapport.nb_telcos_exploitables += 1
            else:
                rapport.telcos_ecartes.append(str(telco.get("name") or "(sans nom)"))

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


# ==========================================================================
# ADMINISTRATION — surface SEPAREE, et c'est volontaire
# ==========================================================================


class ReferenceInverse(RuntimeError):
    """Une ressource est encore referencee par un ou plusieurs pays.

    Levee AVANT toute desactivation. La mesure du 09/08 a montre pourquoi :
    `Moov Africa CI` est reference par la Cote d'Ivoire **et** par le pays
    parasite `ca`. Une cascade naive, ecrite de bonne foi, aurait desactive un
    operateur reel en croyant nettoyer un dechet.
    """


class AdministrationConfigService:
    """Actions du Super-Admin sur le referentiel PARTAGE.

    **Pourquoi une classe a part.** `ConfigServiceClient` est en lecture seule,
    et le reste : pendant la generation, le referentiel est STABLE, on le lit
    pour valider, jamais on ne le reecrit. Melanger les deux exposerait une
    ecriture a portee de main dans un chemin qui ne doit jamais en faire.

    Ici, le cas d'usage est different : la Direction Technique demande que le
    Super-Admin puisse **activer/desactiver un pays** et **ajouter une ville ou
    un operateur**. C'est de l'ADMINISTRATION, pas de la generation — et ca
    touche un referentiel partage par TOUTE L'EQUIPE.

    LES CINQ REGLES, toutes issues de mesures du 09/08
    ---------------------------------------------------
    1. **Jamais de suppression.** Aucun `DELETE` n'est appele, meme quand il
       existerait. On active, on desactive, on ajoute.
    2. **References inverses avant toute desactivation.** Voir `ReferenceInverse`.
    3. **Les devises ne se desactivent JAMAIS en cascade.** `XOF` est
       referencee par le Senegal, le Burkina ET la Cote d'Ivoire ; `XAF` par le
       Cameroun. **100 % des devises sont partagees.** Un seul geste casserait
       trois pays.
    4. **Relecture integrale avant toute mise a jour.** `UpdateCountrySchema`
       exige les **9 champs** (`ANO-CFG-DUP`) : un envoi partiel perdrait la
       devise, les operateurs et l'indicatif.
    5. **`GET`-avant-`POST`.** Aucun index unique n'existe (`RC-182`, `RC-183`)
       — c'est ainsi que `cv`, `00` et le doublon `cm` sont entres en base.

    ⚠️ **L'asymetrie ecriture/lecture** (`ANO-CFG-ASYM-08`) : on ECRIT
    `currencies: ["uuid"]` et on LIT `currencies: [{objet complet}]`. La
    conversion se fait ici, une seule fois.
    """

    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu("config-service", settings.config_service_base, journal=journal)

    async def fermer(self) -> None:
        await self._client.fermer()

    # -- Le controle qui evite de casser le voisin --------------------------

    async def references_inverses(self, ressource_id: str, famille: str) -> list[str]:
        """Quels pays referencent cette ressource ?

        `famille` vaut `"telcos"` ou `"currencies"`. Aucune route ne repond a
        cette question — il faut scanner tous les pays. C'est exactement le
        defaut d'architecture releve dans `docs/ANALYSE_CONFIG_SERVICE.md` :
        la relation est unidirectionnelle.
        """
        pays = await self._client.lister_tout("/api/v1/countries/")
        porteurs: list[str] = []
        for fiche in pays:
            for element in fiche.get(famille) or []:
                identifiant = normaliser_id(element) if isinstance(element, dict) else str(element)
                if identifiant == str(ressource_id):
                    porteurs.append(str(fiche.get("iso_name")))
                    break
        return sorted(porteurs)

    # -- Cycle de vie — verifie fonctionnel le 09/08 ------------------------

    async def activer_pays(self, country_id: str) -> dict[str, Any]:
        """`PATCH /countries/activate/{id}` — mesure du 09/08 : **appliquee**.

        L'anomalie `ANO-CFG-LIFECYCLE-MAJOR` de juin — `200` sans effet en
        base — portait sur l'ancien `PATCH /{id}` a corps. Les routes dediees
        fonctionnent, verifiees dans les deux sens.
        """
        reponse = await self._client.requete("PATCH", f"/api/v1/countries/activate/{country_id}")
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def desactiver_pays(self, country_id: str) -> dict[str, Any]:
        """Desactive un pays **sur le referentiel partage**.

        ⚠️ **Ce n'est PAS la meme chose que le desactiver dans notre
        configuration** (`ConfigurationExecution.desactiver_pays`). Le second
        n'emet aucun appel et n'affecte que notre generation ; celui-ci est
        visible par **tous les services et toutes les equipes**. Arbitrage
        `A-08` : deux actions, deux gestes, jamais un seul bouton.

        Aucune cascade n'est faite : le serveur n'en fait pas, et nous ne
        pouvons pas en faire une sans risque — voir `desactiver_telco`.
        """
        reponse = await self._client.requete("PATCH", f"/api/v1/countries/deactivate/{country_id}")
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def activer_telco(self, telco_id: str) -> dict[str, Any]:
        """`PATCH /telcos/activate/{id}` — le symetrique mesure de deactivate.

        Aucune garde de reference inverse necessaire : REACTIVER un operateur
        ne casse aucun pays — c'est la desactivation qui ampute.
        """
        reponse = await self._client.requete("PATCH", f"/api/v1/telcos/activate/{telco_id}")
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def desactiver_telco(self, telco_id: str, *, pays_attendu: str) -> dict[str, Any]:
        """Desactive un operateur — **apres controle des references inverses**.

        Refuse si un autre pays que `pays_attendu` le reference encore. Sans ce
        controle, desactiver les operateurs du pays parasite `ca` desactiverait
        `Moov Africa CI` et casserait la Cote d'Ivoire (mesure du 09/08).
        """
        porteurs = await self.references_inverses(telco_id, "telcos")
        autres = [code for code in porteurs if code != pays_attendu]
        if autres:
            raise ReferenceInverse(
                f"operateur {telco_id} encore reference par {autres} — desactivation refusee. "
                "Un seul geste casserait ces pays. La relation etant unidirectionnelle cote "
                "serveur, ce controle est le seul garde-fou existant."
            )
        reponse = await self._client.requete("PATCH", f"/api/v1/telcos/deactivate/{telco_id}")
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def desactiver_devise(self, devise_id: str) -> dict[str, Any]:
        """**Toujours refuse.** Conserve pour que le refus soit explicite.

        `XOF` est referencee par le Senegal, le Burkina et la Cote d'Ivoire ;
        `XAF` par le Cameroun. **100 % des devises sont partagees** (mesure du
        09/08). Il n'existe aucun cas ou desactiver une devise ne casse pas au
        moins un pays.
        """
        porteurs = await self.references_inverses(devise_id, "currencies")
        raise ReferenceInverse(
            f"devise {devise_id} referencee par {porteurs} — desactivation TOUJOURS refusee. "
            "100 % des devises sont partagees entre pays : aucun cas ne permet de la retirer "
            "sans casser une zone monetaire entiere."
        )

    # -- Creation — GET avant POST, toujours --------------------------------

    async def creer_telco_si_absent(
        self, nom: str, phone_regex: str
    ) -> tuple[dict[str, Any], bool]:
        """Cree un operateur, ou rend celui qui porte deja ce nom.

        Deux garde-fous que le serveur n'a pas :

        * **`GET`-avant-`POST`** — aucun index unique sur `name` (`RC-183`),
          d'ou le doublon `cm` deja en base.
        * **Le motif est compile ET ancre** avant l'envoi. `RC-184` documente
          l'absence de `re.compile()` cote serveur ; nous ajoutons l'exigence
          d'ancrage, que `6|333` ne respecte pas — un motif sans `^` ni `$`
          accepte quasiment tout numero.
        """
        motif = str(phone_regex).strip()
        if not (motif.startswith("^") and motif.endswith("$")):
            raise ValueError(
                f"motif {motif!r} non ancre — un regex sans ^ ni $ accepte toute chaine le "
                "contenant. C'est le defaut de `MTNcongo1` (`6|333`), qui valide tout en "
                "donnant l'apparence d'un controle."
            )
        try:
            re.compile(motif)
        except re.error as erreur:
            raise ValueError(f"motif {motif!r} non compilable : {erreur}") from erreur

        for existant in await self._client.lister_tout("/api/v1/telcos/"):
            if str(existant.get("name", "")).strip() == nom.strip():
                return existant, False

        reponse = await self._client.requete(
            "POST", "/api/v1/telcos/create", json_body={"name": nom, "phone_regex": motif}
        )
        return (reponse.data if isinstance(reponse.data, dict) else {}), True

    async def creer_devise_si_absent(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Cree une devise sur config-service, ou rend celle qui porte deja cet
        `iso_name`. MEME doctrine que pays/telco : aucune unicite serveur
        (`RC-182`/`RC-183`), c'est NOUS l'autorite — `GET`-avant-`POST` sur
        `iso_name` normalise. `POST /currencies/create` attend
        `{name_en, name_fr, iso_name, accepts_decimal}`. Rend `(fiche, cree?)`."""
        cible = str(payload.get("iso_name", "")).strip().upper()
        for existant in await self._client.lister_tout("/api/v1/currencies/"):
            if str(existant.get("iso_name", "")).strip().upper() == cible:
                if "_id" in existant and not existant.get("id"):
                    existant["id"] = existant["_id"]
                return existant, False
        reponse = await self._client.requete(
            "POST", "/api/v1/currencies/create", json_body=payload
        )
        fiche = reponse.data if isinstance(reponse.data, dict) else {}
        return fiche, True

    async def resoudre_devise(self, code_iso: str) -> str | None:
        """L'UUID d'une devise a partir de son code ISO (`XOF`, `XAF`...).
        Rend None si le code est inconnu de config-service — l'appelant
        refuse alors AVANT d'ecrire, jamais un pays sans devise valide."""
        cible = code_iso.strip().upper()
        for devise in await self._client.lister_tout("/api/v1/currencies/"):
            for champ in ("iso_code", "code", "iso_name", "name"):
                if str(devise.get(champ, "")).strip().upper() == cible:
                    identifiant = devise.get("_id") or devise.get("id")
                    if identifiant:
                        return str(identifiant)
        return None

    async def creer_pays_si_absent(
        self, payload: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Cree un pays sur config-service, ou rend celui qui porte deja cet
        `iso_name`.

        MEME doctrine que `creer_telco_si_absent` : le serveur n'applique
        AUCUNE unicite (`RC-182`/`RC-183`, la recon du 14/08 l'a reprouve avec
        `ca` et `CV` en base). C'est NOUS l'autorite — `GET`-avant-`POST` sur
        `iso_name`, normalise en majuscules. Rend `(fiche, cree?)` : si le pays
        existait, `cree=False` et on ne fabrique pas de doublon.

        `POST /countries/create` attend les 9 champs (comme la relecture des
        villes/telcos) : identite + `cities[]` (noms) + `currencies[uuid]` +
        `telcos[uuid]`. L'appelant a deja resolu la devise et les telcos.
        """
        cible = str(payload.get("iso_name", "")).strip().upper()
        for existant in await self._client.lister_tout("/api/v1/countries/"):
            if str(existant.get("iso_name", "")).strip().upper() == cible:
                if "_id" in existant and not existant.get("id"):
                    existant["id"] = existant["_id"]
                return existant, False

        reponse = await self._client.requete(
            "POST", "/api/v1/countries/create", json_body=payload
        )
        fiche = reponse.data if isinstance(reponse.data, dict) else {}
        return fiche, True

    async def rattacher_telco_au_pays(
        self, country_id: str, telco_id: str
    ) -> dict[str, Any]:
        """Ajoute un operateur a `Country.telcos[]` — par relecture integrale.

        MEME patron que `ajouter_ville` et pour la meme raison (`ANO-CFG-DUP`,
        `ANO-CFG-ASYM-08`) : `UpdateCountrySchema` exige les 9 champs, et la
        conversion objets -> identifiants est faite ici. Un telco cree mais
        non rattache n'appartient a aucun pays — les deux gestes vont
        ensemble (`US-B7`).
        """
        reponse = await self._client.get(f"/api/v1/countries/{country_id}")
        fiche = reponse.data if isinstance(reponse.data, dict) else {}
        if not fiche:
            raise ValueError(f"pays {country_id} introuvable — rien n'est ecrit")

        telcos = _identifiants(fiche.get("telcos"))
        if str(telco_id) in telcos:
            return fiche
        telcos.append(str(telco_id))

        corps = {
            "name_en": fiche.get("name_en", ""),
            "name_fr": fiche.get("name_fr", ""),
            "iso_name": fiche.get("iso_name", ""),
            "dial_code": fiche.get("dial_code", ""),
            "region": fiche.get("region", ""),
            "continent": fiche.get("continent", ""),
            "cities": [str(v) for v in (fiche.get("cities") or [])],
            "currencies": _identifiants(fiche.get("currencies")),
            "telcos": telcos,
        }
        maj = await self._client.requete("PUT", f"/api/v1/countries/{country_id}", json_body=corps)
        return maj.data if isinstance(maj.data, dict) else {}

    async def ajouter_ville(self, country_id: str, ville: str) -> dict[str, Any]:
        """Ajoute une ville a `Country.cities[]` — **par relecture integrale**.

        `UpdateCountrySchema` exige les **9 champs** (`ANO-CFG-DUP`). Un envoi
        partiel perdrait la devise, les operateurs et l'indicatif. On relit
        donc le pays entier, on ajoute la ville, on renvoie tout.

        La conversion lecture -> ecriture est faite ici : le serveur REND
        `currencies: [{objet}]` mais ATTEND `currencies: ["uuid"]`
        (`ANO-CFG-ASYM-08`).

        ⚠️ Seule la **ville** part. La **region** et le **quartier** restent
        chez nous : config-service n'a aucun champ pour eux, et son propre
        champ `region` designe la region **continentale** (« Middle Africa »).
        """
        reponse = await self._client.get(f"/api/v1/countries/{country_id}")
        fiche = reponse.data if isinstance(reponse.data, dict) else {}
        if not fiche:
            raise ValueError(f"pays {country_id} introuvable — rien n'est ecrit")

        villes = [str(v) for v in (fiche.get("cities") or [])]
        if ville.strip() in villes:
            return fiche
        villes.append(ville.strip())

        corps = {
            "name_en": fiche.get("name_en", ""),
            "name_fr": fiche.get("name_fr", ""),
            "iso_name": fiche.get("iso_name", ""),
            "dial_code": fiche.get("dial_code", ""),
            "region": fiche.get("region", ""),
            "continent": fiche.get("continent", ""),
            "cities": villes,
            "currencies": _identifiants(fiche.get("currencies")),
            "telcos": _identifiants(fiche.get("telcos")),
        }
        maj = await self._client.requete("PUT", f"/api/v1/countries/{country_id}", json_body=corps)
        return maj.data if isinstance(maj.data, dict) else {}


def _identifiants(valeurs: Any) -> list[str]:
    """Convertit la forme LUE en forme ECRITE — `ANO-CFG-ASYM-08`.

    Le serveur rend des objets complets et attend des chaines UUID. C'est
    asymetrique, c'est documente depuis juin, et la conversion se fait ici.
    """
    resultat: list[str] = []
    for valeur in valeurs or []:
        identifiant = normaliser_id(valeur) if isinstance(valeur, dict) else str(valeur)
        if identifiant:
            resultat.append(identifiant)
    return resultat
