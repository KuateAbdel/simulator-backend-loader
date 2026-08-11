"""
app/services/clients_composition.py
===================================
La couture entre Faker et notre composeur — `UC-12`, `EF-20` a `EF-27`.

CE MODULE N'INVENTE RIEN ET NE REECRIT RIEN
-------------------------------------------
`Generateur.identite()` existe depuis le Sprint 2 et compose deja une identite
complete : date de naissance porteuse d'`EF-22`, `nationality` en ISO 3166-1
alpha-2 (« Cameroun » rendait HTTP 422), numero de piece alphanumerique
majuscules (`D-CLI-3`), email unique par run, adresse dont les cinq champs sont
TOUJOURS renseignes (`D-IDN-2` : le contrat les declare optionnels et le serveur
les persiste a `null`).

Ce module ne fait qu'une chose : **traduire un client Faker en arguments pour ce
composeur**, en decidant les quelques points ou Faker et la plateforme ne parlent
pas la meme langue. Chacune de ces decisions est adossee a une mesure.

LES CINQ TRADUCTIONS, ET LEUR MESURE
------------------------------------

**1. Le genre.** Faker rend `WOMAN` / `MAN`, la plateforme attend
`MALE` / `FEMALE` (`GENRES_EMIS`). Et `D-IDN-1` a mesure que le serveur
n'applique AUCUN controle : `gender="peu importe"` rend HTTP 201 et persiste tel
quel. Laisser passer `WOMAN` remplirait donc la base de valeurs que le reste du
systeme ne sait pas lire. Nous sommes le seul filtre ; un genre inconnu est
refuse bruyamment.

**2. Le MSISDN — deja tranche le 09/08, et par deux disciplines.**

`valider_msisdn_operateur` porte la mesure : « 18 tirages sur 3 pays, 18 numeros
non attribuables. Appliquer `EF-27` aux numeros de Faker rejetterait **100 % des
2000 clients**. Le Loader compose donc son propre MSISDN depuis le plan de
numerotation. Le `sim_number` de Faker n'est conserve que pour la tracabilite. »

Confirme le 11/08 en detaillant la cause, LUE DANS LES REGEX et non supposee :

    CM  ^237(67\\d{7}|68[0-4]\\d{6}|65[0-4]\\d{6})$   -> 9 chiffres nationaux
    CI  ^225(07\\d{8}|47\\d{8}|57\\d{8})$             -> 10 chiffres
    BF  ^226(0[56]\\d{7}|5[45]\\d{7})$                -> 9 chiffres

Faker emet **8 chiffres nationaux pour les trois pays** : il est trop court
PARTOUT, et ses prefixes (`38`, `10`, `33`) n'appartiennent a aucun operateur.
Un seul numero uniforme pour trois plans de numerotation differents.

`D-CFG-1` dit d'ou vient l'autorite, et ce n'est PAS config-service :

    « EF-27 ne se joue JAMAIS sur les regex de ce service. `MTNcongo1` porte
      `6|333`, SANS ANCRES — il validerait tout numero contenant un 6.
      `geographie.py` porte les 12 plans de numerotation reels, et c'est LUI qui
      fait autorite. Un developpeur qui "ameliorerait" le Loader en lisant le
      regex serveur reintroduirait `6|333` sans s'en apercevoir. »

La regle exacte, pour ne plus s'y tromper : le Loader **obeit** a config-service
sur ce qui EXISTE — quels pays, quelles devises, quels operateurs sont declares,
et il n'injecte rien hors de cela. Il ne lui obeit pas sur la FORME d'un numero,
parce que le motif qu'il publie ne valide rien.

`composer_msisdn()` respecte donc les 12 regex du referentiel ET les parts de
marche reelles (MTN CM 46 %, Orange CM 43 %, Camtel 3 %) — un echantillon ou
chaque operateur pese un tiers ne ressemble a aucun marche africain. Le numero
compose est ensuite repasse par `valider_msisdn_operateur()`, qui n'avait
jusqu'ici **aucun appelant** : la fonction portait `EF-27` et personne ne
l'invoquait.

Aucune perte de tracabilite : le lien vers Faker est le `client_id`, et son
`sim_number` est conserve tel quel dans `ClientCompose.msisdn_faker`. Et
`D-CLI-8` exige `identity.phone == msisdn` — les deux viennent donc de nous,
strictement egaux.

**3. La geographie — DERIVEE DU KIOSQUE, jamais tiree a part.** `EF-26` rattache
chaque client « a un Kiosque existant du pays cible », et le Kiosque vit au
quartier (`EF-16`). L'adresse du client DECOULE donc de son Kiosque :

    kiosque.district_id -> District.city_id -> City(region_id, lat, lon) -> Region

Deux tirages independants — une region ici, une ville la — sont exactement ce qui
a produit « region Adamaoua, ville Yaounde » le 10/08 : deux champs corrects, une
combinaison qui n'existe pas. En derivant, l'incoherence devient
STRUCTURELLEMENT impossible, et non plus rattrapee par un controle. Les
coordonnees GPS de la ville viennent en prime (`EF-03`).

C'est aussi ce que fait un vrai client : il va au kiosque de son quartier.

**4. Le canal.** `IS_SMARTPHONE_USER` du bloc `quick_win` est une donnee MESUREE
de Faker : elle decide `MOBILE` ou `USSD`. `OFFICE` n'est pas emis — nous
n'avons aucune matiere pour le justifier, et l'attribuer au hasard serait
exactement l'invention arbitraire que la strategie de nommage interdit.

**5. Le segment.** `ANY`. La famille A ne porte AUCUNE donnee de scoring : le
`metadata.behavior_segment` que `EF-80` designe vaut 0.0 dans 14 cas sur 15 et
n'appartient qu'a la famille B, inexploitable en volume. Il n'y a donc rien a
traduire, et `ANY` est une valeur legitime de l'enum.

CE QUE CE MODULE NE DECIDE PAS
------------------------------
`jeune` (`EF-22` : 60 % de moins de 25 ans) et `occupation_imposee` (`EF-24` :
20 % des professionnels en agriculture) sont **recus**, jamais decides ici. Seul
l'appelant connait l'etat de sa distribution — c'est le moteur de quotas. Ce
module reste une fonction pure : memes entrees, memes sorties.

La langue est `fr` pour les quatre pays. Consequence a connaitre, mesuree le
09/08 : `language` est IGNORE a l'onboarding — envoye `fr`, rendu `en`. Chaque
client francophone coute donc un `PATCH /clients/language/{id}` supplementaire,
soit 2000 appels de plus sur la campagne. Le cout est assume : un ecosysteme
ouest-africain entierement en anglais serait une donnee fausse devant un
bailleur. Mais il doit etre CONNU, pas decouvert dans le budget `ENF-01`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from typing import Final
from uuid import UUID

from app.clients.contracts import (
    ClientCategory,
    ClientSegment,
    IdentityGender,
    Language,
    SubscriptionChannel,
)
from app.clients.faker_service import ClientFaker
from app.core.invariants import valider_devise_pays, valider_msisdn_operateur
from app.models.domain import OrgHierarchyNode
from app.services.generateur import Generateur, IdentiteGeneree
from app.services.geographie import ReferentielGeo

#: Faker parle `WOMAN`/`MAN`, la plateforme `FEMALE`/`MALE`. Le serveur ne valide
#: rien (`D-IDN-1`) : cette table est le seul filtre du systeme.
GENRE_FAKER: Final[dict[str, IdentityGender]] = {
    "WOMAN": IdentityGender.FEMALE,
    "MAN": IdentityGender.MALE,
}
#: `IdentityGender` porte aussi `ANY`, et `GENRES_EMIS` l'exclut deliberement :
#: une personne physique n'a pas un genre « ANY ». La table ci-dessus ne peut
#: donc jamais y conduire — c'est voulu, pas un oubli.

#: `EF-24` porte sa PROPRE taxonomie de secteurs, et en francais : « rattacher
#: 20 pour cent des professionnels au secteur **agricole** ; les 80 pour cent
#: restants aux secteurs **transports, commerce et services** ». C'est celle-la
#: qui fait foi, pas celle de Faker.
#:
#: POURQUOI ON N'EMPLOIE PAS LES SECTEURS DE FAKER COMME OCCUPATION. Les
#: libelles mesures — `Recycling`, `Shipping`, `3DPrinting`, `Printing`,
#: `Translation`, `Funeral`, `Advertising`, `AR`, `Fashion` — sont des SECTEURS
#: en anglais, pas des metiers. Servis tels quels, ils produisent
#: « occupation: 3DPrinting » dans un ecosysteme ouest-africain entierement
#: francophone. Et aucun des 16 n'est agricole : `EF-24` serait inapplicable.
#:
#: Le libelle Faker n'est donc pas jete — il est conserve dans
#: `ClientCompose.secteur_faker` pour la tracabilite, et l'occupation vient de
#: la taxonomie du CDC. Le choix de la famille appartient au moteur de quotas :
#: seul lui connait l'etat de sa distribution.
OCCUPATIONS_PAR_SECTEUR: Final[dict[str, tuple[str, ...]]] = {
    "AGRICULTURE": (
        "Agriculteur",
        "Eleveur",
        "Maraicher",
        "Producteur de cacao",
        "Membre de cooperative agricole",
    ),
    "TRANSPORTS": (
        "Transporteur",
        "Chauffeur de taxi",
        "Conducteur de moto-taxi",
        "Transitaire",
    ),
    "COMMERCE": (
        "Commercant",
        "Grossiste",
        "Revendeur",
        "Boutiquier",
    ),
    "SERVICES": (
        "Artisan",
        "Coiffeur",
        "Restaurateur",
        "Couturier",
        "Reparateur",
    ),
}

#: Les quatre pays cibles sont francophones (le Cameroun officiellement
#: bilingue, majoritairement francophone). Voir le cout dans l'en-tete.
LANGUE_PAR_DEFAUT: Final = Language.FR


class CompositionImpossible(ValueError):
    """Le client Faker ne peut pas etre compose, et on refuse de deviner.

    Levee AVANT tout appel reseau. Chacun de ces cas produirait une entite
    irreversible et fausse — sur trois services sans `DELETE`, mieux vaut un
    client de moins qu'un client faux.
    """


@dataclass(frozen=True, slots=True)
class AncrageGeographique:
    """La geographie d'un client, DERIVEE de son Kiosque.

    Aucun champ n'est tire independamment : ils descendent tous du
    `district_id` du Kiosque. C'est ce qui rend « region Adamaoua, ville
    Yaounde » impossible a ecrire, plutot que detectable apres coup.
    """

    kiosque_id: UUID
    district_id: str
    quartier: str
    ville: str
    region: str
    pays: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True, slots=True)
class ClientCompose:
    """Un client pret a etre onboarde, et sa tracabilite Faker.

    Rien ici n'a touche le reseau. C'est l'objet que le module CLIENTS pousse,
    et c'est aussi ce qu'un essai a blanc peut afficher AVANT d'ecrire — `D-01`.
    """

    #: Le lien vers Faker, et le seul. Le MSISDN, lui, est le notre.
    faker_client_id: str
    seed: int | None
    identite: IdentiteGeneree
    #: Le NOTRE, compose depuis le plan de numerotation reel et valide par
    #: `valider_msisdn_operateur` (`EF-27`).
    msisdn: str
    #: Celui de Faker, conserve **pour la seule tracabilite** — jamais emis.
    #: Mesure du 09/08 : aucun numero Faker n'est attribuable a un operateur.
    msisdn_faker: str | None
    telco: str
    devise: str
    categorie: ClientCategory
    segment: ClientSegment
    canal: SubscriptionChannel
    langue: Language
    ancrage: AncrageGeographique
    #: Matiere Faker conservee pour la tracabilite — jamais pour nommer.
    secteur_faker: str | None = None
    type_juridique_faker: str | None = None

    @property
    def jeune(self) -> bool:
        """Vrai si le client a moins de 25 ans — `EF-22`, relu depuis la date
        de naissance reellement composee, jamais depuis l'intention."""
        aujourdhui = date.today()
        age = aujourdhui.year - self.identite.date_of_birth.year
        anniversaire_passe = (aujourdhui.month, aujourdhui.day) >= (
            self.identite.date_of_birth.month,
            self.identite.date_of_birth.day,
        )
        return (age - (0 if anniversaire_passe else 1)) < 25


def ancrer_sur_kiosque(
    kiosque: OrgHierarchyNode, referentiel: ReferentielGeo
) -> AncrageGeographique:
    """Derive la geographie complete du client depuis son Kiosque (`EF-26`).

    Refuse plutot que d'inventer : un Kiosque dont le quartier, la ville ou la
    region manquent au referentiel ne peut pas porter d'adresse credible, et
    `EF-04` prevoit d'enrichir le referentiel — c'est la seule vraie reponse a
    un trou de donnees.
    """
    if not kiosque.district_id:
        raise CompositionImpossible(
            f"Kiosque {kiosque.name} sans district_id — EF-26 exige un rattachement "
            "au quartier, et l'adresse du client en decoule."
        )
    quartier = referentiel.quartier(kiosque.district_id)
    if quartier is None:
        raise CompositionImpossible(
            f"district_id {kiosque.district_id!r} absent du referentiel (Kiosque "
            f"{kiosque.name}). Trou de DONNEES, pas regle metier — voir EF-04."
        )
    ville = referentiel.ville(quartier.city_id)
    if ville is None:
        raise CompositionImpossible(
            f"city_id {quartier.city_id!r} absent du referentiel (quartier {quartier.name})."
        )
    region = referentiel.region(ville.region_id)
    if region is None:
        raise CompositionImpossible(
            f"region_id {ville.region_id!r} absent du referentiel (ville {ville.name})."
        )
    # Le pays vient de la VILLE, pas du champ du Kiosque : c'est le referentiel
    # qui fait foi sur la territorialite, et lui seul.
    return AncrageGeographique(
        kiosque_id=kiosque.id,
        district_id=quartier.district_id,
        quartier=quartier.name,
        ville=ville.name,
        region=region.name,
        pays=ville.country_iso2.upper(),
        latitude=ville.latitude,
        longitude=ville.longitude,
    )


def composer(
    faker: ClientFaker,
    ancrage: AncrageGeographique,
    generateur: Generateur,
    referentiel: ReferentielGeo,
    alea: random.Random,
    *,
    jeune: bool,
    occupation_imposee: str | None = None,
) -> ClientCompose:
    """Traduit un client Faker en client onboardable. **Aucun appel reseau.**

    `jeune` et `occupation_imposee` viennent du moteur de quotas : ce module ne
    decide d'aucune distribution, il compose.
    """
    pays = ancrage.pays

    # `EF-21` — le pays du client Faker doit etre celui du Kiosque. Sans ce
    # controle, un Camerounais serait rattache a un kiosque senegalais : les
    # deux champs seraient valides, la combinaison n'existerait pas.
    if faker.pays.upper() != pays:
        raise CompositionImpossible(
            f"{faker.client_id} est du pays {faker.pays}, le Kiosque "
            f"{ancrage.kiosque_id} est en {pays}. EF-26 rattache un client a un "
            "Kiosque de SON pays — jamais Yaounde dans une region du Senegal."
        )

    if not faker.prenom or not faker.nom:
        raise CompositionImpossible(
            f"{faker.client_id} sans prenom ou sans nom : l'identite KYC serait creuse, "
            "et identity-service n'expose aucun DELETE pour la reprendre."
        )

    genre = GENRE_FAKER.get((faker.genre or "").upper())
    if genre is None:
        raise CompositionImpossible(
            f"{faker.client_id} porte gender={faker.genre!r}, hors de la table de "
            f"traduction {sorted(GENRE_FAKER)}. D-IDN-1 : le serveur accepte n'importe "
            "quelle chaine sans broncher — nous sommes le seul filtre."
        )

    # La devise suit le PAYS, jamais Faker — meme quand Faker a raison, et il a
    # raison (XAF pour CM, XOF pour CI et BF, mesure du 11/08). L'accepter de lui
    # serait accepter qu'il decide un jour autrement.
    #
    # `D-CLI-9` : `currency` n'est validee NULLE PART sur ce chemin — elle
    # traverse client-service et atterrit telle quelle dans le compte CHECKING.
    # C'est ainsi qu'un compte reel a fini avec `currency="ANY"` (`FRA-222`).
    #
    # `valider_devise_pays` fait DEUX choses, et c'est pour ca qu'on l'appelle
    # plutot que de lire le classeur : elle confronte le code aux unions
    # monetaires (verite INDEPENDANTE du classeur, donc capable de le
    # contredire), puis verifie que le referentiel concorde. Un classeur faux se
    # voit avant l'ecriture, pas apres.
    devise_ref = referentiel.devise_du_pays(pays)
    if devise_ref is None:
        raise CompositionImpossible(
            f"aucune devise rattachee a {pays!r} dans le referentiel — un compte "
            "porterait une devise vide, et personne ne le refuserait (FRA-222)."
        )
    devise = valider_devise_pays(devise_ref.code, pays, referentiel)

    # Le MSISDN est le NOTRE (`D-CFG-1`). `composer_msisdn` respecte les 12 regex
    # du referentiel et les parts de marche reelles.
    chiffres = "".join(str(alea.randrange(10)) for _ in range(12))
    msisdn, telco = referentiel.composer_msisdn(pays, chiffres, alea)
    # `EF-27` — et cette fonction n'avait AUCUN appelant jusqu'ici. Elle porte
    # l'exigence ; la laisser muette, c'est ne pas l'appliquer. Composer un
    # numero et ne pas le revalider suppose que `composer_msisdn` est sans
    # defaut : on ne se croit pas sur parole a l'echelle de 2000 clients.
    valider_msisdn_operateur(msisdn, pays, referentiel)

    categorie = (
        ClientCategory.CORPORATE if faker.est_business else ClientCategory.INDIVIDUAL
    )
    identite = generateur.identite(
        first_name=faker.prenom,
        last_name=faker.nom,
        gender=genre.value,
        country_code=pays,
        ville=ancrage.ville,
        region=ancrage.region,
        quartier=ancrage.quartier,
        telephone=msisdn,
        jeune=jeune,
        occupation=_occupation(faker, occupation_imposee),
        latitude=ancrage.latitude,
        longitude=ancrage.longitude,
        referentiel=referentiel,
    )

    return ClientCompose(
        faker_client_id=faker.client_id,
        seed=faker.seed,
        identite=identite,
        msisdn=msisdn,
        msisdn_faker=faker.msisdn,
        telco=telco.short_name,
        devise=devise,
        categorie=categorie,
        # La famille A ne porte aucun scoring : il n'y a rien a traduire.
        segment=ClientSegment.ANY,
        canal=_canal(faker),
        langue=LANGUE_PAR_DEFAUT,
        ancrage=ancrage,
        secteur_faker=faker.company.secteur_principal if faker.company else None,
        type_juridique_faker=faker.company.type_exploitable if faker.company else None,
    )


def _canal(faker: ClientFaker) -> SubscriptionChannel:
    """`MOBILE` si Faker declare un smartphone, `USSD` sinon.

    `IS_SMARTPHONE_USER` est une donnee MESUREE du bloc `quick_win`. `OFFICE`
    n'est jamais emis : nous n'avons aucune matiere pour le justifier, et
    l'attribuer au hasard serait l'invention arbitraire que la strategie de
    nommage interdit.
    """
    return (
        SubscriptionChannel.MOBILE
        if faker.quick_win.get("IS_SMARTPHONE_USER") == 1
        else SubscriptionChannel.USSD
    )


def occupation_du_secteur(secteur: str, alea: random.Random) -> str:
    """Un metier tire dans la famille de secteurs du CDC (`EF-24`).

    Le moteur de quotas choisit la FAMILLE — c'est lui qui porte les 20 % en
    agriculture ; ce module rend le libelle. Une famille inconnue est refusee :
    inventer un metier hors taxonomie contredirait `EF-24`.
    """
    famille = secteur.strip().upper()
    metiers = OCCUPATIONS_PAR_SECTEUR.get(famille)
    if not metiers:
        raise CompositionImpossible(
            f"secteur {secteur!r} hors de la taxonomie EF-24 "
            f"{sorted(OCCUPATIONS_PAR_SECTEUR)} — le CDC nomme quatre familles, "
            "et « transports, commerce et services » n'est pas une liste ouverte."
        )
    return alea.choice(metiers)


def _occupation(faker: ClientFaker, imposee: str | None) -> str | None:
    """L'occupation imposee par le moteur de quotas, ou le defaut du generateur.

    **On n'emploie JAMAIS `sector_assignments` comme occupation.** Ces libelles
    sont des secteurs en anglais — `Recycling`, `Shipping`, `3DPrinting` — et
    servis tels quels ils produisaient « occupation: 3DPrinting » dans un
    ecosysteme francophone. Le libelle reste conserve dans
    `ClientCompose.secteur_faker` : trace, pas donnee emise.
    """
    return imposee or None
