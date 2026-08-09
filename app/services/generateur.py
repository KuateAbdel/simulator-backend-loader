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
from typing import Final
from uuid import UUID, uuid4

from app.core.cdc import AGE_SEUIL_JEUNE, PREFIXE_DONNEES

#: Formes juridiques reellement observees chez Faker (24 tirages, 08/08).
#: On les reutilise telles quelles — c'est de la matiere reelle.
FORMES_JURIDIQUES: Final[tuple[str, ...]] = (
    "SA",
    "SARL",
    "SAS",
    "Etablissement",
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
    """
    noms = PATRONYMES_PAR_PAYS.get(pays.upper(), PATRONYMES_PAR_PAYS["SN"])
    return noms[index % len(noms)]


def prenom(genre: str, index: int) -> str:
    """Prenom coherent avec le genre — `EF-22` se joue sur ce champ."""
    liste = PRENOMS_PAR_GENRE.get(genre.upper(), PRENOMS_PAR_GENRE["FEMALE"])
    return liste[index % len(liste)]


#: Voies types. Le nom precis de la voie n'a aucune portee metier — seul compte
#: le rattachement au quartier, qui lui vient du referentiel reel.
TYPES_DE_VOIE: Final[tuple[str, ...]] = ("Rue", "Avenue", "Boulevard", "Carrefour")

#: Domaine de courriel des entites generees. Jamais un domaine reel : ces
#: adresses ne doivent atteindre aucune boite aux lettres existante.
DOMAINE_EMAIL: Final = "demo.fintech4esg.local"

#: Libelles des pays, pour les rapports et les journaux UNIQUEMENT.
#: `Identity.nationality` n'accepte PAS ces libelles — voir plus bas.
LIBELLES_PAYS: Final[dict[str, str]] = {
    "CM": "Cameroun",
    "CI": "Cote d'Ivoire",
    "BF": "Burkina Faso",
    "SN": "Senegal",
}


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

    def __init__(self, run_id: UUID) -> None:
        self._run_id = run_id
        self._alea = random.Random(run_id.int)  # noqa: S311 — reproductibilite, pas de crypto
        self._emails_emis: set[str] = set()

    # ----------------------------------------------------------------------
    # Raisons sociales — UC-07, UC-08
    # ----------------------------------------------------------------------

    def raison_sociale(
        self, patronyme: str, forme_juridique: str, secteur: str | None = None
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

        return f"{PREFIXE_DONNEES}{noyau}"

    def nom_court(self, raison_sociale: str) -> str:
        """`short_name` — declare unique par company-service (INV-CPY-01).

        On y adjoint un discriminant court derive du run pour eviter toute
        collision entre executions, sans rendre le nom illisible.
        """
        lettres = "".join(m[0] for m in raison_sociale.replace(PREFIXE_DONNEES, "").split()[:3])
        return f"{PREFIXE_DONNEES}{lettres.upper()}{self._alea.randrange(100, 999)}"

    def nom_kiosque(self, quartier: str) -> str:
        """Le Kiosque porte son quartier dans son nom.

        depositary-service n'a AUCUN champ geographique : le nom est le seul
        endroit ou l'ancrage reste visible dans l'interface. C'est aussi ce
        qu'on lit sur une devanture reelle.
        """
        return f"{PREFIXE_DONNEES}Kiosque {_sans_accents(quartier).title()}"

    def nom_branche(self, region: str) -> str:
        return f"{PREFIXE_DONNEES}Branche {_sans_accents(region).title()}"

    def nom_agence(self, ville: str) -> str:
        return f"{PREFIXE_DONNEES}Agence {_sans_accents(ville).title()}"

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
        quartier: str,
        telephone: str,
        *,
        jeune: bool,
        occupation: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> IdentiteGeneree:
        """Complete une identite Faker avec ce qui lui manque.

        `jeune` porte EF-22 : 60 % des individus ont moins de 25 ans. Le quota
        est decide par l'appelant, qui seul connait l'etat de sa distribution.
        """
        pays = country_code.upper()
        return IdentiteGeneree(
            identity_id=uuid4(),
            first_name=first_name,
            last_name=last_name,
            date_of_birth=self._date_de_naissance(jeune=jeune),
            gender=gender.upper(),
            # `nationality` exige un code ISO 3166-1 alpha-2, JAMAIS le libelle
            # du pays. Mesure du 08/08 : « Cameroun » -> HTTP 422
            # « nationality must be a valid ISO 3166-1 alpha-2 country code ».
            # Defaut trouve par la campagne d'ecriture, invisible hors ligne.
            nationality=pays,
            id_number=self.numero_piece(pays),
            id_place=_sans_accents(ville).title(),
            id_expire_on=self._expiration_piece(),
            phone=telephone,
            email=self.email(first_name, last_name),
            occupation=occupation or "Commercant",
            adresse=self.adresse(quartier, ville, region, pays, latitude, longitude),
        )

    def numero_piece(self, country_code: str) -> str:
        """D-CLI-3 : alphanumerique MAJUSCULES strict.

        Un underscore ou un tiret provoque un HTTP 400 « id_number format
        invalid (expected alphanumeric uppercase only) ».
        """
        chiffres = "".join(str(self._alea.randrange(10)) for _ in range(9))
        return f"{country_code.upper()}{chiffres}"

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
        quartier: str,
        ville: str,
        region: str,
        country_code: str,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> Adresse:
        """L'adresse est ancree sur un quartier REEL du referentiel."""
        voie = f"{self._alea.choice(TYPES_DE_VOIE)} {_sans_accents(quartier).title()}"
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

    def _date_de_naissance(self, *, jeune: bool) -> date:
        """EF-22 : 60 % de moins de 25 ans.

        Faker n'expose aucun filtre d'age et sa famille A ne renvoie meme pas de
        date de naissance — le quota se pilote donc entierement ici.
        """
        aujourdhui = date.today()
        age = (
            self._alea.randrange(18, AGE_SEUIL_JEUNE)
            if jeune
            else self._alea.randrange(AGE_SEUIL_JEUNE, 66)
        )
        jour = self._alea.randrange(365)
        return aujourdhui - timedelta(days=age * 365 + jour)

    def _expiration_piece(self) -> date:
        """Toujours dans le futur : une piece expiree serait incoherente pour un
        client actif, et `id_expire_on` est de toute facon obligatoire en
        pratique (D-CLI-2)."""
        return date.today() + timedelta(days=self._alea.randrange(365, 3650))


def _sans_accents(texte: str) -> str:
    """Les services FinZuu n'imposent aucun encodage, mais les identifiants
    restent plus surs sans diacritiques."""
    normalise = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in normalise if not unicodedata.combining(c))


def _slug(texte: str) -> str:
    return "".join(c for c in _sans_accents(texte).lower() if c.isalnum()) or "x"
