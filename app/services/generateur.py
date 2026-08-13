"""
app/services/generateur.py
==========================
Generateur d'entites que ni Faker ni les services FinZuu ne fournissent.

**Le principe, deja applique a la geographie des Kiosques** : la ou la source
amont est pauvre, le Loader porte la richesse. depositary-service n'accepte que
`name`, `currency`, `company_id` — le quartier vit donc chez nous
(`org_hierarchy`). Faker ne fournit ni raison sociale credible, ni date de
naissance, ni adresse, ni occupation, ni email — le Loader les compose donc ici.

**Rien n'est invente a partir de rien.** Tout part de matiere reelle :

  - les patronymes viennent de Faker (Kouassi, Kabore, Tamadou, Ouedraogo...)
  - les formes juridiques viennent de Faker (SA, SARL, SAS, Fondation...)
  - les secteurs viennent de Faker (`sector_assignments`)
  - les villes et quartiers viennent de Loader_Base_FinZuu_v1_1.xlsx

Le Loader ne fait que les **assembler** en entites credibles. C'est la difference
entre inventer et composer.

Pourquoi c'est necessaire : Faker renvoie `company_name = "Test Business CM 748"`
(mesure du 08/08, 15 tirages sur 3 pays). Or UC-08 exige « un nom metier
credible », et la demonstration cible Nordic Microfinance, IFC, AFD et BAD, qui
connaissent le terrain africain reel. `DEMO_Test Business CM 748` ne passerait pas.

Reproductibilite (ENF-15) : tout tirage derive du `run_id` et d'un discriminant
stable. Deux executions de meme `run_id` produisent exactement les memes entites.
"""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from typing import Any, Final
from uuid import UUID, uuid4

from app.core.cdc import AGE_SEUIL_JEUNE, PREFIXE_DONNEES
from app.core.invariants import (
    InvariantViole,
    valider_coherence_territoriale,
    valider_coherence_ville_pays,
)
from app.services.referentiel_statique import PAYS_CIBLES_LIBELLES

#: Formes juridiques reellement observees chez Faker, et leur frequence.
#:
#: CORRECTION DU 11/08 — cette table portait `Etablissement`, que Faker ne
#: produit PAS, et il lui MANQUAIT `Entreprise Individuelle` : **la forme la plus
#: frequente, 24 % selon l'Annexe B du CDC**. Nous avions donc invente une forme
#: et perdu la principale.
#:
#: Recampagne du 11/08, 18 tirages sur CM/CI/BF, 6 seeds par pays :
#:   Entreprise Individuelle 5 · SARL 4 · SAS 3 · SA 3 · Fondation 3
#: `Association` n'est pas ressortie sur cet echantillon — le CDC la donne a 7 %,
#: la plus rare des six. Elle est conservee.
#:
#: Distribution du CDC (Annexe B, mesure Faker du 17/07) :
#:   Entreprise Individuelle 24 % · SA 21 % · SARL 19 % · SAS 16 %
#:   Fondation 13 % · Association 7 %
#:
#: C'est de la matiere REELLE, rejouee telle quelle. Ce que nous ne reprenons
#: pas, c'est la RAISON SOCIALE — « Test Business CM 748 » (mesure du 11/08,
#: inchangee depuis le 08/08) ne passe pas devant un bailleur (`A-03`).
FORMES_JURIDIQUES: Final[tuple[str, ...]] = (
    "Entreprise Individuelle",
    "SA",
    "SARL",
    "SAS",
    "Fondation",
    "Association",
)

#: Suffixes commerciaux courants en Afrique de l'Ouest et centrale. Ils rendent
#: la raison sociale credible sans rien inventer sur le fond.
SUFFIXES: Final[tuple[str, ...]] = ("& Fils", "& Freres", "et Cie", "Negoce", "Services", "Group")

#: Occupations coherentes avec les secteurs Faker. EF-24 impose 20 % des
#: professionnels en agriculture ; le reste va au transport, au commerce et aux
#: services, conformement au CDC.
OCCUPATIONS_PAR_SECTEUR: Final[dict[str, str]] = {
    "AGRICULTURE": "Agriculteur",
    "TRANSPORT": "Transporteur",
    "COMMERCE": "Commercant",
    "SERVICES": "Prestataire de services",
}

#: Patronymes REELLEMENT observes chez Faker, par pays (24 tirages, 08/08).
#: Ce n'est pas de l'invention : ce sont ses valeurs, rejouees.
#:
#: **Bouchon assume, et temporaire.** Tant que le client Faker n'est pas ecrit,
#: c'est ici que la matiere vient. Le jour ou il existera, cette table
#: disparaitra au profit d'un tirage reel — et `D-FAKER-1` s'appliquera.
#:
#: Elle doit rester DISTINCTE PAR PAYS : un premier dry-run avait produit la
#: meme raison sociale dans les quatre pays.
PATRONYMES_PAR_PAYS: Final[dict[str, tuple[str, ...]]] = {
    "CM": ("Tamadou", "Kingue", "Ngassa", "Mbarga", "Fotso"),
    "CI": ("Kouassi", "Yao", "Bamba", "Koffi", "Gnahore"),
    "BF": ("Kabore", "Ouedraogo", "Sawadogo", "Zongo", "Compaore"),
    "SN": ("Diallo", "Ndiaye", "Fall", "Sow", "Gueye"),
}

#: Prenoms observes chez Faker, par genre. Meme statut : matiere reelle,
#: rejouee tant que le client n'existe pas.
PRENOMS_PAR_GENRE: Final[dict[str, tuple[str, ...]]] = {
    "FEMALE": ("Ines", "Aissatou", "Mariam", "Fatou", "Adjoa", "Nadege"),
    "MALE": ("Serge", "Ibrahim", "Kwame", "Moussa", "Cedric", "Amadou"),
}


def patronyme(pays: str, index: int) -> str:
    """Nom de famille, tire de la matiere reelle de Faker.

    Source unique pour TOUS les executeurs — Organisation, Staff, Clients.
    Deux tables paralleles divergeraient tot ou tard.

    **Leve sur un pays inconnu.** Le repli silencieux vers le Senegal a ete
    retire le 09/08 : `patronyme("ZZ", 0)` rendait « Diallo » sans rien
    signaler, et un pays fautif se serait peuple de noms senegalais sans
    qu'aucun rapport ne le mentionne. La doctrine dit l'inverse — *« rigide a
    l'execution : le Loader echoue bruyamment sur l'inconnu »* — et `EF-05`
    borne le perimetre a quatre pays.
    """
    noms = PATRONYMES_PAR_PAYS.get(pays.upper())
    if noms is None:
        raise ValueError(
            f"pays '{pays}' hors des 4 cibles {list(PATRONYMES_PAR_PAYS)} — `EF-05`. "
            "Aucun repli : un pays inconnu doit arreter le run, pas se peupler "
            "en silence de patronymes empruntes a un autre."
        )
    return noms[index % len(noms)]


def prenom(genre: str, index: int) -> str:
    """Prenom coherent avec le genre — `EF-22` se joue sur ce champ.

    **Leve sur un genre inconnu**, pour la meme raison et une de plus : le
    serveur ne valide PAS `gender` (`D-IDN-1`). Un repli vers FEMALE aurait
    fausse le quota « deux femmes pour un homme » sans laisser de trace, et
    personne en aval ne l'aurait rattrape.
    """
    liste = PRENOMS_PAR_GENRE.get(genre.upper())
    if liste is None:
        raise ValueError(
            f"genre '{genre}' inconnu — attendu MALE ou FEMALE, jamais ANY "
            "(`D-IDN-1` : le serveur ne valide pas ce champ, nous le validons)."
        )
    return liste[index % len(liste)]


#: `SD-6` — la part de la population nee A L'ETRANGER. Le CDC ne fixe aucune
#: proportion ; l'ONU (UN DESA 2020) situe la part de population nee a
#: l'etranger entre ~2 % (SN, CM, BF) et ~10 % (CI). Borne haute regionale,
#: en constante documentee — jamais un quota du CDC.
PART_NAISSANCES_ETRANGERES: Final = 0.10

#: Les onze cles du bloc `quick_win` de Faker (famille A), mesurees
#: exhaustivement le 11/08. Elles decrivent la regularite d'usage, l'usage data,
#: l'equipement et la derniere activite — le seul profil socio-economique que la
#: famille A porte reellement, et donc la seule matiere dont `solde_initial()`
#: puisse deriver un patrimoine sans invention arbitraire (`A-09`).
#:
#: Declarees ICI, dans le generateur, parce que DEUX modules en dependent : la
#: source interne les produit, et l'executeur CLIENTS en derive le solde. Deux
#: listes paralleles auraient divergé — et la divergence aurait ete SILENCIEUSE,
#: un solde calcule sur des cles que la source ne pose jamais.
CLES_PROFIL_INTERNE: Final[tuple[str, ...]] = (
    "IS_RGS_1",
    "IS_RGS_7",
    "IS_RGS_30",
    "IS_RGS_90",
    "IS_DATA_RGS1",
    "IS_DATA_RGS7",
    "IS_DATA_RGS30",
    "IS_DATA_RGS90",
    "IS_SMARTPHONE_USER",
)

#: Longueur minimale d'un corps de numero exploitable. Faker en fournit huit
#: (mesure du 11/08, uniformement sur les trois pays qu'il sert). En-dessous, la
#: matiere est trop courte pour etaler quoi que ce soit — un `client_id` comme
#: `INTERNE-SN-IND-42` ne porte que deux chiffres, repetes cycliquement ils
#: donneraient `4242424...` et collisionneraient d'emblee. On derive alors par
#: hachage de la chaine ENTIERE, qui reste propre au client.
#: Pas d'escalade quand le registre refuse un numero. Premier avec 10^8 (impair,
#: non divisible par 5), donc l'addition modulaire fait varier les HUIT chiffres
#: du corps — pas seulement ceux de poids faible, qui sont precisement ceux que
#: `composer_msisdn` tronque.
PAS_ESCALADE_MSISDN: Final = 7_777_777

#: Plafond de tentatives pour obtenir un MSISDN inedit (`EF-25`). Genereux :
#: l'espace utile d'un operateur dominant tourne autour de 10^7, et l'escalade
#: est deterministe — atteindre ce plafond signale un vivier reellement epuise,
#: pas un tirage malheureux.
TENTATIVES_MSISDN_MAX: Final = 24


def _corps_msisdn(ancre: str, tentative: int) -> str:
    """Huit chiffres ou les HUIT varient avec l'ancre. Deterministe.

    Deux proprietes de `composer_msisdn` rendent obligatoire cette dispersion,
    et `staff_execution._reserver_identifiants` les avait deja documentees le
    10/08 — je ne les avais pas reportees ici :

    1. Le composeur consomme le corps **depuis la position 0** et le plan
       tronque a la place disponible. Le Senegal n'offre que sept chiffres apres
       son prefixe : le huitieme saute. Un corps qui ne varie qu'en position
       basse produit donc des numeros identiques.
    2. Une classe restreinte replie dix chiffres sur deux — `0[56]` mappe tout
       chiffre source sur `5` ou `6`. Une seule position variable ne suffit
       jamais.

    Mesure du 11/08 sur 2000 clients, avec le corps pris litteralement chez
    Faker : echec au HUITIEME client, « 24 tentatives sans MSISDN inedit — 7
    deja emis ». La cause : `sim_number` depouille commence par l'indicatif
    pays, et le Cameroun consommant sept chiffres, le composeur brulait
    `2373810` sans jamais atteindre la partie distinctive.
    """
    empreinte = int(sha256(ancre.encode()).hexdigest()[:16], 16)
    return f"{(empreinte + tentative * PAS_ESCALADE_MSISDN) % 100_000_000:08d}"


def _chiffres_de(graine: str) -> str:
    """Un corps de numero derive d'une chaine, par CALCUL et non par tirage.

    Sert quand le client n'a pas de `sim_number` — la source interne. Le meme
    client rend toujours le meme corps : `ENF-15` tient, et le numero reste une
    fonction du client plutot que du hasard.
    """
    return f"{int(sha256(graine.encode()).hexdigest()[:12], 16):012d}"


#: Voies types. Le nom precis de la voie n'a aucune portee metier — seul compte
#: le rattachement au quartier, qui lui vient du referentiel reel.
TYPES_DE_VOIE: Final[tuple[str, ...]] = ("Rue", "Avenue", "Boulevard", "Carrefour")

#: Domaine de courriel des entites generees. Jamais un domaine reel : ces
#: adresses ne doivent atteindre aucune boite aux lettres existante.
DOMAINE_EMAIL: Final = "demo.fintech4esg.local"

@dataclass(frozen=True, slots=True)
class Adresse:
    """`Address` au sens des contrats FinZuu — 2 champs requis, le reste optionnel."""

    address_line_1: str
    street_name: str
    city: str
    region: str
    country: str
    latitude: float | None = None
    longitude: float | None = None

    def en_payload(self) -> dict[str, object]:
        return {
            "address_line_1": self.address_line_1,
            "street_name": self.street_name,
            "city": self.city,
            "region": self.region,
            "country": self.country,
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


@dataclass(frozen=True, slots=True)
class IdentiteGeneree:
    """Identity complete, prete pour company-service comme pour client-service.

    `_id` est genere ICI : le schema embarque l'exige fourni par l'appelant.
    `id_expire_on` est TOUJOURS renseigne (D-CLI-2, D-DEP-5, FRA-200) — son
    absence fait planter le serveur, alors que les deux embeds le declarent
    nullable.
    """

    identity_id: UUID
    first_name: str
    last_name: str
    date_of_birth: date
    gender: str
    nationality: str
    id_number: str
    id_place: str
    #: `SD-6` (tache #15) — le lieu de naissance. Le contrat serveur porte
    #: `place_of_birth` et le persistait a `null` (mesure du 09/08) : un champ
    #: que le referentiel sait remplir ne reste pas vide.
    place_of_birth: str
    id_expire_on: date
    phone: str
    email: str
    occupation: str
    adresse: Adresse
    type_identite: str = "INDIVIDUAL"

    def en_payload(self) -> dict[str, object]:
        """D-CLI-4 : `type` est ignore par client-service, qui l'ecrase vers
        CORPORATE. On l'envoie quand meme, le champ etant requis au contrat."""
        return {
            "_id": str(self.identity_id),
            "type": self.type_identite,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth.isoformat(),
            "gender": self.gender,
            "nationality": self.nationality,
            "id_number": self.id_number,
            "id_place": self.id_place,
            "place_of_birth": self.place_of_birth,
            "id_expire_on": self.id_expire_on.isoformat(),
            "phone": self.phone,
            "email": self.email,
            "occupation": self.occupation,
            "address": self.adresse.en_payload(),
        }


class Generateur:
    """Compose des entites credibles a partir de matiere reelle.

    Une instance par run : le generateur aleatoire derive du `run_id`, ce qui
    rend l'ecosysteme strictement reproductible (ENF-15).
    """

    def __init__(self, run_id: UUID, reference: date | None = None) -> None:
        self._run_id = run_id
        self._alea = random.Random(run_id.int)  # noqa: S311 — reproductibilite, pas de crypto
        self._emails_emis: set[str] = set()
        self._noms_emis: set[str] = set()
        # `INV-09` parle d'unicite TRIPLE — msisdn, id_number, email. Seul
        # l'email l'avait. Les deux registres manquants sont ici, au meme
        # endroit et avec la meme portee : UN run (`EF-25` dit « au sein d'une
        # meme execution »), ce qui est exactement la duree de vie de cet objet.
        self._msisdns_emis: set[str] = set()
        self._numeros_piece_emis: set[str] = set()
        # Graine de secours pour le corps d'un MSISDN quand le client n'a pas de
        # `sim_number` — la source interne senegalaise. Derivee du `run_id`, donc
        # reproductible, et distincte par run.
        self._graine_secours = f"{run_id.int:039d}"
        # `ENF-15` — L'ANCRE TEMPORELLE FAIT PARTIE DE LA REPRODUCTIBILITE.
        #
        # Le tirage derivait bien du `run_id`, mais les dates etaient calculees
        # depuis `date.today()`. Le meme `run_id` rejoue un autre jour produisait
        # donc d'AUTRES dates de naissance et d'AUTRES dates d'expiration : la
        # promesse « deux executions de meme run_id produisent exactement les
        # memes entites » etait fausse, cassee par le calendrier.
        #
        # `reference` doit etre la `sim_end_date` du run — celle que `D-10`
        # persiste dans `loader_runs`. Rejouer un run, c'est rejouer son
        # `run_id` ET sa fenetre.
        self._reference = reference or date.today()

    # ----------------------------------------------------------------------
    # Unicite des noms — D-12
    # ----------------------------------------------------------------------

    def _nom_unique(self, nom: str, pays: str | None = None) -> str:
        """Rend `nom` unique pour toute la duree du run.

        POURQUOI CE REGISTRE EXISTE
        ---------------------------
        **Aucun service n'impose l'unicite de `name`** — ni company-service, ni
        depositary-service, ni product-service (`ANO-PRD-UNIQ-01`). Un doublon
        n'est pas rejete : il est *cree*, en silence. Et trois services
        n'exposent aucun `DELETE`.

        Mesure du 09/08 sur le referentiel reel :

          - `Plateau`  est un quartier de DEUX pays -> 2 « DEMO_Kiosque Plateau »
          - `Centre`, `Est`, `Nord`, `Sud-Ouest` sont des regions partagees
            -> 4 branches en doublon sur 51

        Le Kiosque est le cas grave : **depositary-service n'a aucun champ
        geographique**, le nom est le seul ancrage visible. Deux
        « DEMO_Kiosque Plateau » sont strictement indiscernables dans
        l'interface — exactement le defaut que nous reprochons a config-service.

        LA STRATEGIE DE LEVEE
        ---------------------
        1. le nom tel quel, s'il est libre — le cas de 95 % des noms
        2. sinon le code pays, **discriminant porteur de sens** : c'est ainsi
           qu'un groupe panafricain reel distingue ses agences homonymes
        3. en dernier recours seulement, un rang numerique

        On ne prefixe PAS tous les noms du pays : « DEMO_Agence Douala CM »
        alourdit 50 noms pour en desambiguiser zero. Le discriminant apparait
        la ou l'ambiguite existe — et nulle part ailleurs.
        """
        if nom not in self._noms_emis:
            self._noms_emis.add(nom)
            return nom

        if pays:
            candidat = f"{nom} {pays.upper()}"
            if candidat not in self._noms_emis:
                self._noms_emis.add(candidat)
                return candidat

        # Deux homonymes DANS le meme pays : le referentiel n'en contient pas
        # aujourd'hui, mais la surcouche `CFG-03` permet d'en ajouter.
        rang = 2
        while f"{nom} {rang}" in self._noms_emis:
            rang += 1
        final = f"{nom} {rang}"
        self._noms_emis.add(final)
        return final

    # ----------------------------------------------------------------------
    # Raisons sociales — UC-07, UC-08
    # ----------------------------------------------------------------------

    def raison_sociale(
        self,
        patronyme: str,
        forme_juridique: str,
        secteur: str | None = None,
        pays: str | None = None,
    ) -> str:
        """Compose une raison sociale credible, prefixee DEMO_ (EF-63).

        `patronyme` et `forme_juridique` viennent de Faker, `secteur` aussi.
        On assemble ; on n'invente pas.
        """
        forme = forme_juridique if forme_juridique in FORMES_JURIDIQUES else "SARL"
        base = _sans_accents(patronyme).title()

        if forme in ("Fondation", "Association"):
            # Une fondation ne porte pas un suffixe commercial.
            noyau = f"{forme} {base}"
        elif secteur:
            noyau = f"{forme} {base} {_sans_accents(secteur).title()}"
        else:
            noyau = f"{forme} {base} {self._alea.choice(SUFFIXES)}"

        # `D-12` — 5 patronymes par pays, et le CDC autorise 3 a 5 companies.
        # La marge est NULLE au plafond, et le parametrage du boss permet d'en
        # demander davantage : a 8 companies, 3 raisons sociales etaient
        # rigoureusement identiques (mesure du 09/08).
        #
        # Le code pays, bon discriminant pour une BRANCHE, n'en est pas un ici :
        # « SARL Tamadou Textile » et « SARL Tamadou Textile CM » sont toutes
        # deux camerounaises. On leve d'abord par le SUFFIXE COMMERCIAL — deux
        # maisons du meme patronyme se distinguent ainsi dans la vraie vie,
        # « Tamadou & Fils » et « Tamadou Negoce ».
        candidat = f"{PREFIXE_DONNEES}{noyau}"
        if candidat in self._noms_emis and forme not in ("Fondation", "Association"):
            for suffixe in SUFFIXES:
                autre = f"{PREFIXE_DONNEES}{noyau} {suffixe}"
                if autre not in self._noms_emis:
                    candidat = autre
                    break
        return self._nom_unique(candidat, pays)

    def nom_court(self, raison_sociale: str) -> str:
        """`short_name` — declare unique par company-service (INV-CPY-01).

        On y adjoint un discriminant court derive du run pour eviter toute
        collision entre executions, sans rendre le nom illisible.
        """
        lettres = "".join(m[0] for m in raison_sociale.replace(PREFIXE_DONNEES, "").split()[:3])
        return f"{PREFIXE_DONNEES}{lettres.upper()}{self._alea.randrange(100, 999)}"

    def nom_kiosque(self, quartier: str, pays: str | None = None) -> str:
        """Le Kiosque porte son quartier dans son nom.

        depositary-service n'a AUCUN champ geographique : le nom est le seul
        endroit ou l'ancrage reste visible dans l'interface. C'est aussi ce
        qu'on lit sur une devanture reelle.
        """
        return self._nom_unique(f"{PREFIXE_DONNEES}Kiosque {_sans_accents(quartier).title()}", pays)

    def nom_branche(self, region: str, pays: str | None = None) -> str:
        """`Centre`, `Est`, `Nord` et `Sud-Ouest` sont des regions de PLUSIEURS
        pays — 4 doublons sur 51 branches, mesures le 09/08. `D-12`."""
        return self._nom_unique(f"{PREFIXE_DONNEES}Branche {_sans_accents(region).title()}", pays)

    def nom_agence(self, ville: str, pays: str | None = None) -> str:
        """Les 50 villes du referentiel ont des noms distincts — aucun doublon
        aujourd'hui. Le registre passe quand meme : la surcouche `CFG-03`
        autorise l'ajout de villes, et rien ne garantit leur unicite."""
        return self._nom_unique(f"{PREFIXE_DONNEES}Agence {_sans_accents(ville).title()}", pays)

    # ----------------------------------------------------------------------
    # Identites — ce que Faker ne fournit pas
    # ----------------------------------------------------------------------

    def identite(
        self,
        first_name: str,
        last_name: str,
        gender: str,
        country_code: str,
        ville: str,
        region: str,
        #: `None` quand la ville ne porte aucun quartier au referentiel. L'adresse
        #: s'ancre alors sur la ville — `EF-11` n'en demande pas plus pour une
        #: Company, et le contrat `Address` ne porte aucun champ quartier.
        quartier: str | None,
        telephone: str,
        *,
        jeune: bool,
        ancre_client: str,
        occupation: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        referentiel: object | None = None,
        statique: object | None = None,
    ) -> IdentiteGeneree:
        """Complete une identite Faker avec ce qui lui manque.

        `jeune` porte EF-22 : 60 % des individus ont moins de 25 ans. Le quota
        est decide par l'appelant, qui seul connait l'etat de sa distribution.
        """
        pays = country_code.upper()
        naissance_lieu, delivrance = self._lieu_de_naissance(
            pays,
            ville,
            ancre=ancre_client,
            referentiel=referentiel,
            statique=statique,
        )
        return IdentiteGeneree(
            identity_id=uuid4(),
            first_name=first_name,
            last_name=last_name,
            date_of_birth=self._date_de_naissance(jeune=jeune, ancre=ancre_client),
            gender=gender.upper(),
            # `nationality` exige un code ISO 3166-1 alpha-2, JAMAIS le libelle
            # du pays. Mesure du 08/08 : « Cameroun » -> HTTP 422
            # « nationality must be a valid ISO 3166-1 alpha-2 country code ».
            # Defaut trouve par la campagne d'ecriture, invisible hors ligne.
            nationality=pays,
            id_number=self.numero_piece(pays),
            # `SD-6` — `id_place` n'est PLUS la ville de residence : la piece
            # est delivree pres du lieu de naissance pour ceux nes au pays, et
            # a la residence pour la minorite nee a l'etranger. Dans les deux
            # cas c'est une ville DU pays de nationalite — « une piece
            # senegalaise ne peut pas etre delivree a Douala » reste garanti.
            id_place=delivrance,
            place_of_birth=naissance_lieu,
            id_expire_on=self._expiration_piece(),
            phone=telephone,
            email=self.email(first_name, last_name),
            occupation=occupation or "Commercant",
            adresse=self.adresse(quartier, ville, region, pays, latitude, longitude, referentiel),
        )

    def _lieu_de_naissance(
        self,
        pays: str,
        ville_residence: str,
        *,
        ancre: str,
        referentiel: object | None,
        statique: object | None,
    ) -> tuple[str, str]:
        """`SD-6` (tache #15) — le couple (`place_of_birth`, `id_place`).

        LE DEFAUT FERME : `place_of_birth` restait a `null` sur le serveur, et
        `id_place` etait la ville de residence pour 2000 clients sur 2000 —
        une population entiere nee exactement la ou elle habite, ce qui
        n'existe dans aucun pays reel.

        DEUX SOUS-POPULATIONS, ANCREES AU CLIENT (`CR-03`)
        --------------------------------------------------
        - **Majorite, nee AU pays** : une ville tiree parmi TOUTES les villes
          du pays au referentiel. La migration interne en decoule
          mecaniquement — avec ~12 villes par pays, la plupart des clients
          n'habitent pas leur ville natale, sans qu'aucun quota l'impose.
          La piece est delivree pres du lieu de naissance : `id_place` = la
          ville natale.
        - **Minorite (10 %), nee A L'ETRANGER** : un pays tire parmi les 195
          de `Lieu2Nationalite.csv` (libelle francais — l'ecosysteme est
          francophone), hors des quatre pays cibles. La NATIONALITE reste
          celle de la residence : c'est la diaspora de retour, et sa piece
          nationale est delivree la ou elle reside — `id_place` = la ville de
          residence. La coherence piece <-> nationalite est donc structurelle
          dans les deux branches.

        LES 10 % : l'ONU (UN DESA 2020) situe la part de population nee a
        l'etranger entre ~2 % (SN, CM, BF) et ~10 % (CI, l'un des premiers
        pays d'immigration d'Afrique de l'Ouest). Le CDC ne fixe rien : on
        retient la borne haute regionale, en constante documentee — un chiffre
        visible dans une demo, jamais un quota du CDC.

        CE QUI EST DELIBEREMENT HORS CHAMP, ET DECLARE : les nationalites
        ETRANGERES. Un Malien residant a Abidjan existe dans la vraie vie,
        mais le CDC definit une population des quatre pays cibles, et une
        nationalite etrangere entrainerait piece, msisdn et devise d'un pays
        sans referentiel. On ne l'invente pas.

        Sans `referentiel` ou `statique` (appelants d'avant `SD-6`), le
        comportement historique demeure : ne la ou il reside.
        """
        residence = _sans_accents(ville_residence).title()
        regions_du_pays = getattr(referentiel, "regions_du_pays", None)
        villes_de_region = getattr(referentiel, "villes_de_region", None)
        pays_connus = getattr(statique, "pays", None)
        if regions_du_pays is None or villes_de_region is None or not pays_connus:
            return residence, residence

        de_ce_client = random.Random(f"naissance:{ancre}")  # noqa: S311
        if de_ce_client.random() < PART_NAISSANCES_ETRANGERES:
            locaux = set(PAYS_CIBLES_LIBELLES.values())
            etrangers = sorted(
                libelle_fr
                for libelle_en, libelle_fr in pays_connus.items()
                if libelle_en not in locaux
            )
            return de_ce_client.choice(etrangers), residence

        villes = sorted(
            ville.name
            for region in regions_du_pays(pays)
            for ville in villes_de_region(region.region_id)
        )
        if not villes:
            return residence, residence
        naissance = _sans_accents(de_ce_client.choice(villes)).title()
        return naissance, naissance

    def numero_piece(self, country_code: str) -> str:
        """D-CLI-3 : alphanumerique MAJUSCULES strict, et UNIQUE (`INV-09`).

        Un underscore ou un tiret provoque un HTTP 400 « id_number format
        invalid (expected alphanumeric uppercase only) ».

        L'UNICITE EST LA NOTRE. `INV-09` parle d'unicite TRIPLE — `msisdn`,
        `id_number`, `email` — et le serveur l'impose sur les trois. Deux
        personnes ne partagent pas un numero de piece d'identite : dans la vraie
        vie c'est l'objet meme du document. Une collision ne produirait donc pas
        un doublon, elle produirait un HTTP 400, donc un client PERDU.

        L'espace est vaste (10^9 par pays) et le registre ne coute rien. Le seul
        cout reel serait de s'en passer et de perdre un client sur un tirage
        malheureux — un cout asymetrique.
        """
        prefixe = country_code.upper()
        while True:
            candidat = f"{prefixe}{self._alea.randrange(10**8, 10**9)}"
            if candidat not in self._numeros_piece_emis:
                self._numeros_piece_emis.add(candidat)
                return candidat

    def msisdn(
        self, pays: str, referentiel: Any, matiere: str | None = None
    ) -> tuple[str, Any]:
        """`EF-27` + `EF-25` — un numero conforme au plan reel, et UNIQUE au run.

        DEUX EXIGENCES DISTINCTES, LONGTEMPS CONFONDUES
        -----------------------------------------------
        `EF-27` demande que le numero respecte le regex de l'operateur telco du
        pays. C'est fait depuis le 09/08 : `composer_msisdn()` porte les 12 plans
        de numerotation reels, ponderes par les parts de marche (MTN CM 46 %,
        Orange CM 43 %, Camtel 3 %) — un echantillon ou chaque operateur pese un
        tiers ne ressemble a aucun marche africain.

        `EF-25` demande « l'unicite des MSISDN generes AU SEIN D'UNE MEME
        EXECUTION ». C'est une exigence SEPAREE, et elle etait absente : aucun
        registre n'existait. Le calcul du 11/08 : pour un operateur dominant,
        l'espace utile tourne autour de 10^7 ; a 500 clients par pays, la
        probabilite de collision est d'environ 1,25 % par pays, soit ~5 % sur une
        campagne de quatre pays. Une chance sur vingt de perdre un client par
        campagne — pas negligeable, et le serveur ne pardonne pas : `INV-CLI-01`
        rend un HTTP 400 « Client already exists ».

        CE QUI RESTE DE FAKER, EXACTEMENT
        ---------------------------------
        `matiere` est le `sim_number` de Faker, et le numero produit en est une
        FONCTION DETERMINISTE — meme client, meme numero — sans en etre une
        reprise chiffre pour chiffre. La nuance n'est pas cosmetique, et j'ai mis
        deux versions a l'admettre : `composer_msisdn` reecrit de toute facon le
        numero dans le plan de l'operateur (`237` + `67` + sept chiffres), donc
        les chiffres de Faker ne survivent JAMAIS litteralement. Pretendre le
        contraire m'a fait passer un corps prefixe par l'indicatif pays, que le
        composeur tronquait avant d'atteindre la partie distinctive.

        L'ancrage qui compte est la reproductibilite par client (`ENF-15`), et
        elle est preservee. Ce qui se perd est une fidelite qui n'existait pas.

        Quand la matiere manque — la source interne senegalaise n'a pas de
        `sim_number`, et fabriquer un faux serait l'invention arbitraire que le
        CDC interdit — l'ancre est le `client_id`, transmis par l'appelant. Le
        numero reste une fonction du client, jamais d'un hasard.

        L'OPERATEUR AUSSI EST ANCRE AU CLIENT — CORRECTION DU 12/08
        -----------------------------------------------------------
        La version precedente tirait l'operateur dans `self._alea`, seme par le
        `run_id`. Mesure : la MEME matiere client rendait `237679614504` au run 1
        et `237699614504` au run 2 — un seul chiffre d'ecart, celui de la
        variante de prefixe, et cela suffisait a rendre le msisdn INUTILISABLE
        comme cle de reprise. Or `D-CLI-5` en fait la cle du `GET`-avant-`POST`,
        et `CR-03` exige « idempotence, aucun doublon » : un second run n'aurait
        reconnu AUCUN des 2000 clients du premier, et en aurait cree 2000 de
        plus, sur des services sans `DELETE`.

        L'operateur est donc tire dans un generateur seme par le CLIENT. La
        ponderation par parts de marche est intacte — chaque client tire encore
        uniformement, donc `EF-27` garde sa distribution (MTN CM 46 %, Orange
        43 %, Camtel 3 %) — mais le resultat ne bouge plus d'un run a l'autre.

        Rien n'est perdu : `ENF-15` demandait la reproductibilite par run, et un
        numero fonction du client la satisfait a plus forte raison. Ce que la
        version d'avant offrait n'etait pas une garantie, c'etait un obstacle.
        """
        # DEFAUT DE MA PREMIERE VERSION, attrape par les tests dans la minute :
        # le repli derivait du RUN (`_graine_secours`) et non du CLIENT. Les 500
        # Senegalais — la source interne n'a pas de `sim_number` — partageaient
        # donc la MEME base, et le registre les rejetait tous : `SN 4/25`,
        # « quota sature : 62 ». Un repli doit rester une fonction du client,
        # sinon il n'ancre rien et il collisionne par construction.
        ancre = str(matiere or self._graine_secours)
        # Seme par le CLIENT, pas par le run — voir la docstring. `Random` accepte
        # une chaine comme graine et la hache lui-meme, de facon stable.
        de_ce_client = random.Random(f"{pays}:{ancre}")  # noqa: S311
        for tentative in range(TENTATIVES_MSISDN_MAX):
            # Escalade DETERMINISTE : le meme client au meme rang de tentative
            # rend toujours le meme corps. Pas un nouveau tirage au hasard.
            numero, operateur = referentiel.composer_msisdn(
                pays, _corps_msisdn(ancre, tentative), de_ce_client
            )
            if numero not in self._msisdns_emis:
                self._msisdns_emis.add(numero)
                return numero, operateur
        raise InvariantViole(
            f"{pays} : {TENTATIVES_MSISDN_MAX} tentatives sans MSISDN inedit — "
            f"{len(self._msisdns_emis)} deja emis. EF-25 exige l'unicite au sein de "
            "l'execution ; emettre un doublon rendrait un HTTP 400 et perdrait le client."
        )

    def email(self, first_name: str, last_name: str) -> str:
        """Adresse unique par run, sur un domaine qui n'existe pas.

        L'unicite est garantie ici et non deleguee au serveur : user-service ne
        valide pas le format des courriels (INV-USR-22) mais impose leur unicite
        (INV-USR-02).
        """
        base = f"{_slug(first_name)}.{_slug(last_name)}"
        candidat = f"{base}@{DOMAINE_EMAIL}"
        suffixe = 1
        while candidat in self._emails_emis:
            suffixe += 1
            candidat = f"{base}{suffixe}@{DOMAINE_EMAIL}"
        self._emails_emis.add(candidat)
        return candidat

    def adresse(
        self,
        quartier: str | None,
        ville: str,
        region: str,
        country_code: str,
        latitude: float | None = None,
        longitude: float | None = None,
        referentiel: object | None = None,
    ) -> Adresse:
        """L'adresse est ancree sur du reel — a la granularite de l'entite.

        **Quartier fourni** : chaine complete `quartier -> ville -> region ->
        pays` (`D-13`, controle du 10/08). Sans lui, une Senegalaise domiciliee a
        Douala franchissait tous les invariants : chaque champ correct, la
        combinaison absurde. C'est le cas du Kiosque, que `EF-16` ancre sur un
        District.

        **Quartier `None`** : chaine `ville -> region -> pays`. C'est le cas de la
        **Company**, que `EF-11` ancre sur une **Region** — et le contrat
        `Address` ne porte aucun champ quartier de toute facon. Exiger un quartier
        a cet etage confinait les Companies aux 12 villes qui en portent, sur les
        50 du referentiel : 2 regions sur 13 au Burkina (mesure du 11/08).

        `referentiel` reste optionnel pour les appelants qui composent une adresse
        hors contexte, mais tout chemin de generation reelle le fournit.
        """
        if referentiel is not None:
            if quartier:
                valider_coherence_territoriale(
                    pays=country_code,
                    region=region,
                    ville=ville,
                    quartier=quartier,
                    referentiel=referentiel,
                )
            else:
                valider_coherence_ville_pays(
                    pays=country_code,
                    region=region,
                    ville=ville,
                    referentiel=referentiel,
                )
        # Le nom de voie s'appuie sur l'ancrage le plus fin disponible.
        ancrage = quartier or ville
        voie = f"{self._alea.choice(TYPES_DE_VOIE)} {_sans_accents(ancrage).title()}"
        return Adresse(
            address_line_1=f"{self._alea.randrange(1, 300)} {voie}",
            street_name=voie,
            city=_sans_accents(ville).title(),
            region=_sans_accents(region).title(),
            country=country_code.upper(),
            latitude=latitude,
            longitude=longitude,
        )

    def occupation_pour_secteur(self, secteur: str) -> str:
        return OCCUPATIONS_PAR_SECTEUR.get(secteur.upper(), "Commercant")

    def mot_de_passe_initial(self) -> str:
        """Mot de passe de premiere connexion d'un User applicatif.

        Il sera immediatement change par le flow en 3 requetes
        (register -> password/f/change -> login). Il n'a donc pas vocation a
        etre durable, seulement a satisfaire la politique du serveur.
        """
        corps = "".join(self._alea.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(10))
        return f"Dm{corps.capitalize()}!7"

    # ----------------------------------------------------------------------
    # Interne
    # ----------------------------------------------------------------------

    def _date_de_naissance(self, *, jeune: bool, ancre: str) -> date:
        """EF-22 : 60 % de moins de 25 ans.

        Faker n'expose aucun filtre d'age et sa famille A ne renvoie meme pas de
        date de naissance — le quota se pilote donc entierement ici.

        ANCREE AU CLIENT, PLUS AU RUN — correction du 12/08, et c'est un `CR-03`.
        Elle tirait dans `self._alea`, seme par le `run_id` : une reprise donnait
        donc une AUTRE date de naissance au meme client. Meme famille exacte que
        le defaut msisdn (`D-CLI-11`), et meme consequence — un client dont
        l'identite change d'un run a l'autre n'est pas le meme client.

        Cette correction en debloque une seconde : l'age devient calculable AVANT
        la composition, donc le profil comportemental (`EF-67`) peut se decider
        dans le temps sequentiel, ou les quotas se tiennent.
        """
        return date_de_naissance_du_client(ancre, jeune=jeune, reference=self._reference)

    @staticmethod
    def _expiration_piece_ancree(ancre: str, reference: date) -> date:  # pragma: no cover
        """Reserve : meme raison que la date de naissance, non encore cablee."""
        return reference + timedelta(days=random.Random(ancre).randrange(365, 3650))  # noqa: S311

    def _expiration_piece(self) -> date:
        """Toujours dans le futur DE LA REFERENCE DU RUN, jamais du jour de la
        machine. AUDIT DU 13/08 : ce champ etait le DERNIER a deriver de
        `date.today()` — deux executions du meme `run_id` a deux jours
        d'intervalle rendaient des `id_expire_on` differents, une entaille a
        `ENF-15` que la date de naissance avait deja corrigee et que
        l'expiration avait echappee. La piece reste future d'au moins un an
        par rapport a la fenetre du run (D-CLI-2, INV-11 valide contre la
        MEME reference)."""
        return self._reference + timedelta(days=self._alea.randrange(365, 3650))


def date_de_naissance_du_client(
    ancre: str, *, jeune: bool, reference: date
) -> date:
    """La date de naissance d'un client — fonction de LUI, jamais du run.

    Publique et pure, pour que l'age soit calculable partout ou on en a besoin :
    par le composeur qui l'emet au serveur, et par le moteur de quotas qui doit
    ponderer les profils comportementaux (`EF-68`) AVANT la composition.

    `EF-22` borne les deux tranches : moins de `AGE_SEUIL_JEUNE` ans, ou de
    `AGE_SEUIL_JEUNE` a 65 ans inclus.
    """
    de_ce_client = random.Random(f"naissance:{ancre}")  # noqa: S311
    age = (
        de_ce_client.randrange(18, AGE_SEUIL_JEUNE)
        if jeune
        else de_ce_client.randrange(AGE_SEUIL_JEUNE, 66)
    )
    # DEFAUT PREEXISTANT, revele le 12/08 par un test d'age EXACT : la formule
    # etait `reference - (age * 365 + jour)`. Sur dix-huit ans, les jours
    # bissextiles font perdre quatre a cinq jours, et l'age REVOLU tombe a 17.
    # Le Loader pouvait donc emettre un client MINEUR — inacceptable pour un
    # client financier, et invisible tant que l'age n'etait pas calcule
    # exactement.
    #
    # On ancre desormais sur l'anniversaire : `debut` est la date ou le client a
    # exactement `age` ans revolus, et le decalage de 0 a 364 jours le maintient
    # dans sa `age`-ieme annee sans jamais la quitter.
    try:
        debut = reference.replace(year=reference.year - age)
    except ValueError:  # 29 fevrier — l'annee cible n'est pas bissextile
        debut = reference.replace(year=reference.year - age, day=28)
    return debut - timedelta(days=de_ce_client.randrange(365))


def _sans_accents(texte: str) -> str:
    """Les services FinZuu n'imposent aucun encodage, mais les identifiants
    restent plus surs sans diacritiques."""
    normalise = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in normalise if not unicodedata.combining(c))


def _slug(texte: str) -> str:
    return "".join(c for c in _sans_accents(texte).lower() if c.isalnum()) or "x"
