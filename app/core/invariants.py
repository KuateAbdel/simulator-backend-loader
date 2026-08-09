"""
app/core/invariants.py
======================
Les invariants que le systeme FinZuu ne pose pas, et que le Loader pose.

**Pourquoi ce module existe.** Le CDC v1.2 est un SRS : il dit QUOI generer.
Il ne dit pas comment garantir qu'une donnee soit *humainement credible*. Or
la mesure du 09/08/2026 a etabli qu'aucun service ne verifie :

    l'age                 un client de 2 ans est accepte (HTTP 201)
    le genre              « peu importe » est accepte et persiste
    la situation famille  « CELIBATAIRE » hors enum est accepte
    la casse              `cm250509274` et `CM250509274` cohabitent
    la coherence des dates  une piece d'identite peut expirer hier

Et Faker ne fournit **aucune date de naissance** — ni en famille A, ni en
famille B (verifie le 09/08 sur les deux). C'est donc le Loader qui compose
l'age, et donc le Loader qui doit le rendre credible.

**Consequence inattendue, et favorable.** `_adjust_weights` du script de
reference (Duhamel) pondere les 4 profils comportementaux par tranche d'age,
en lisant `ctx.get("birth_date")`. Ce champ n'existant dans aucun payload
Faker, cette branche est **du code mort chez lui**. Chez nous elle s'active,
puisque nous fournissons la date. Le Loader est, sur ce point precis, plus
riche que le script dont il reprend la methodologie.

**La regle de conception.** Aucune valeur n'est inventee : chaque borne est
adossee soit a une norme citee, soit a une exigence du CDC, soit a une mesure.
Une regle sans justification n'a pas sa place ici.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Final

from app.core.cdc import AGE_SEUIL_JEUNE, PAYS_CIBLES

# --------------------------------------------------------------------------
# Les bornes, et d'ou elles viennent
# --------------------------------------------------------------------------

#: Majorite legale dans les 4 pays cibles — Cameroun, Cote d'Ivoire, Burkina
#: Faso, Senegal la fixent tous a 18 ans. Aucune institution financiere
#: n'ouvre un compte a un mineur non represente ; le Loader ne genere donc
#: aucun client mineur. C'est la borne la plus dure du module.
AGE_MINIMUM: Final = 18

#: Borne haute. Ce n'est pas une regle legale mais une regle de credibilite :
#: au-dela, un client actif de microfinance devient invraisemblable pour un
#: bailleur qui connait le terrain (Nordic Microfinance, IFC, AFD, BAD — les
#: destinataires de la demonstration, OBJ-04). Le systeme accepte 120 ans ;
#: nous non.
AGE_MAXIMUM: Final = 75

#: EF-22 : « 60 pour cent d'individus de moins de 25 ans ». Le seuil vient de
#: `app/core/cdc.py`, il n'est pas redefini ici.
AGE_JEUNE_MAX: Final = AGE_SEUIL_JEUNE

#: Duree de validite d'une carte nationale d'identite dans la zone. Sert a
#: verifier qu'une piece n'a pas ete emise avant la majorite de son porteur.
DUREE_VALIDITE_PIECE_ANS: Final = 10

#: Genres emis par le Loader. `ANY` existe dans l'enum serveur mais n'est
#: JAMAIS emis : EF-22 exige un ratio deux femmes pour un homme, mesurable.
#: Une valeur « indifferent » rendrait le quota invérifiable — et c'est
#: exactement cette valeur qui a fui dans le champ `currency` d'un compte reel
#: (ANO-ACC-CUR-08 / FRA-222).
GENRES_EMIS: Final[frozenset[str]] = frozenset({"MALE", "FEMALE"})

#: Situations familiales de l'enum serveur. Le serveur ne les valide pas a la
#: creation (mesure du 09/08) ; nous si.
SITUATIONS_FAMILIALES: Final[frozenset[str]] = frozenset(
    {"SINGLE", "MARRIED", "DIVORCED", "WIDOWED"}
)

#: Un `id_number` alphanumerique. Le serveur annonce une contrainte de
#: MAJUSCULES qu'il n'applique pas (FRA-228) ; le Loader s'y conforme pour
#: rester valide si elle est un jour reellement posee.
MOTIF_ID_NUMBER: Final = re.compile(r"^[A-Z0-9]{6,20}$")


class InvariantViole(ValueError):
    """Une donnee violerait une regle de credibilite metier.

    Levee AVANT tout appel reseau. Trois services n'exposent aucun `DELETE` —
    identity, account, depositary : une donnee absurde ecrite y reste a vie.
    """


# --------------------------------------------------------------------------
# Age et coherence des dates
# --------------------------------------------------------------------------


def calculer_age(naissance: date, reference: date | None = None) -> int:
    """Age revolu a la date de reference (aujourd'hui par defaut)."""
    jour = reference or date.today()
    return jour.year - naissance.year - ((jour.month, jour.day) < (naissance.month, naissance.day))


def valider_age(naissance: date, reference: date | None = None) -> int:
    """Verifie qu'un client est majeur et d'un age vraisemblable.

    Le systeme accepte aujourd'hui un client de **2 ans** et un de **120 ans**
    (mesure du 09/08 : seule une naissance dans le futur est refusee). Aucune
    institution financiere n'ouvrirait ces comptes.
    """
    jour = reference or date.today()
    if naissance > jour:
        raise InvariantViole(
            f"date de naissance {naissance.isoformat()} dans le futur — "
            "c'est le seul controle que le serveur applique reellement."
        )
    age = calculer_age(naissance, jour)
    if age < AGE_MINIMUM:
        raise InvariantViole(
            f"age {age} ans — la majorite legale est de {AGE_MINIMUM} ans dans les 4 pays "
            f"cibles ({', '.join(PAYS_CIBLES)}). Aucune institution financiere n'ouvre un "
            "compte a un mineur non represente. Le serveur, lui, accepte 2 ans (mesure 09/08)."
        )
    if age > AGE_MAXIMUM:
        raise InvariantViole(
            f"age {age} ans — au-dela de {AGE_MAXIMUM} ans, un client actif de microfinance "
            "n'est pas credible devant un bailleur qui connait le terrain. Le serveur "
            "accepte 120 ans."
        )
    return age


def valider_piece_identite(
    naissance: date, expiration: date, reference: date | None = None
) -> None:
    """Coherence entre la piece d'identite et son porteur.

    Deux regles qu'aucun service ne verifie :

      1. Une piece **expiree** ne permet aucune ouverture de compte.
      2. Une piece ne peut avoir ete **emise avant la majorite** de son
         porteur — sinon la date d'expiration precede logiquement l'age
         d'obtention.
    """
    jour = reference or date.today()
    if expiration <= jour:
        raise InvariantViole(
            f"piece d'identite expiree le {expiration.isoformat()} — aucune institution "
            "n'ouvre un compte sur une piece perimee. Le serveur ne verifie rien : il exige "
            "seulement que le champ soit present (D-CLI-2), jamais qu'il soit coherent."
        )
    emission_supposee = date(
        expiration.year - DUREE_VALIDITE_PIECE_ANS, expiration.month, expiration.day
    )
    age_a_emission = calculer_age(naissance, emission_supposee)
    if age_a_emission < AGE_MINIMUM:
        raise InvariantViole(
            f"piece expirant en {expiration.year} pour une naissance en {naissance.year} : "
            f"le porteur aurait eu {age_a_emission} ans a l'emission (validite "
            f"{DUREE_VALIDITE_PIECE_ANS} ans). Incoherent."
        )


# --------------------------------------------------------------------------
# Champs d'etat civil que le serveur n'inspecte pas
# --------------------------------------------------------------------------


def valider_genre(genre: str) -> str:
    """`EF-22` exige **deux femmes pour un homme**, donc un quota mesurable.

    Le serveur accepte n'importe quelle chaine — `"peu importe"` a ete
    persiste tel quel le 09/08. Il n'existe aucun filet hors du notre.
    """
    valeur = str(genre).strip().upper()
    if valeur not in GENRES_EMIS:
        raise InvariantViole(
            f"genre '{genre}' — le Loader n'emet que {sorted(GENRES_EMIS)}. `ANY` existe dans "
            "l'enum serveur mais rendrait le quota EF-22 invérifiable. Le serveur, lui, "
            "accepte n'importe quelle chaine (mesure 09/08, « peu importe » -> HTTP 201)."
        )
    return valeur


def valider_situation_familiale(situation: str) -> str:
    valeur = str(situation).strip().upper()
    if valeur not in SITUATIONS_FAMILIALES:
        raise InvariantViole(
            f"situation familiale '{situation}' hors enum {sorted(SITUATIONS_FAMILIALES)}. "
            "Le serveur accepte « CELIBATAIRE » sans broncher (mesure 09/08)."
        )
    return valeur


def valider_nationalite(code: str) -> str:
    """Code ISO 3166-1 alpha-2, en MAJUSCULES, et dans les 4 pays cibles.

    Le serveur valide bien l'ISO — mais **sans tenir compte de la casse** :
    `cm` passe en 201 la ou `ZZ` est refuse (mesure 09/08). La base accumule
    donc `CM` et `cm`. Et rien ne l'empeche d'accepter un 5e pays.
    """
    valeur = str(code).strip().upper()
    if valeur not in PAYS_CIBLES:
        raise InvariantViole(
            f"nationalite '{code}' hors des 4 pays cibles {list(PAYS_CIBLES)} — `EF-05` : "
            "toute operation ciblant un pays absent du referentiel est rejetee."
        )
    return valeur


def valider_id_number(numero: str) -> str:
    """Alphanumerique, majuscules, 6 a 20 caracteres.

    Le message du serveur annonce « expected alphanumeric uppercase only »,
    mais seules les valeurs a caracteres speciaux sont reellement refusees
    (FRA-228). On emet des majuscules pour rester valide si la regle est un
    jour appliquee, et on borne la longueur, que personne ne borne.
    """
    valeur = str(numero).strip().upper()
    if not MOTIF_ID_NUMBER.match(valeur):
        raise InvariantViole(
            f"id_number '{numero}' non conforme — attendu alphanumerique majuscule, 6 a 20 "
            "caracteres. Le serveur n'applique que le refus des caracteres speciaux "
            "(FRA-228) et ne borne aucune longueur."
        )
    return valeur


# --------------------------------------------------------------------------
# Normalisation — la casse, source silencieuse de doublons
# --------------------------------------------------------------------------


#: Ages plancher par situation familiale — coherence humaine, contexte
#: ouest et centre-africain. Aucune de ces bornes n'est une regle legale : ce
#: sont des bornes de VRAISEMBLANCE. Un divorce suppose un mariage puis une
#: procedure ; un veuvage a 19 ans est statistiquement negligeable. Le systeme
#: n'inspecte rien — un client de 18 ans « VEUF » passerait sans broncher.
AGE_PLANCHER_SITUATION: Final[dict[str, int]] = {
    "SINGLE": AGE_MINIMUM,
    "MARRIED": AGE_MINIMUM,
    "DIVORCED": 21,
    "WIDOWED": 30,
}


def valider_coherence_matrimoniale(situation: str, age: int) -> str:
    """Une situation familiale doit etre atteignable a l'age du client.

    Le systeme accepte n'importe quelle combinaison. Devant un bailleur, une
    population ou des clients de 18 ans sont veufs se remarque immediatement.
    """
    valeur = valider_situation_familiale(situation)
    plancher = AGE_PLANCHER_SITUATION[valeur]
    if age < plancher:
        raise InvariantViole(
            f"situation '{valeur}' a {age} ans — invraisemblable avant {plancher} ans. "
            "Ce n'est pas une regle legale mais une borne de credibilite : le systeme "
            "accepterait un veuf de 18 ans sans broncher."
        )
    return valeur


def valider_msisdn_operateur(msisdn: str, pays: str, referentiel: object) -> object:
    """`EF-27` — « valider le format du MSISDN contre le regex de l'operateur
    telco du pays ».

    Le referentiel porte les **12 plans de numerotation reels** depuis le
    depart. Aucun service FinZuu ne les consulte.

    ⚠️ **Mesure du 09/08 : les MSISDN de Faker n'en respectent AUCUN.**
    18 tirages sur 3 pays, 18 numeros non attribuables — Faker produit
    `+23776511256` la ou le Cameroun exige `237` suivi de `67/68/65/69/62` sur
    neuf chiffres. Appliquer `EF-27` aux numeros de Faker rejetterait
    **100 % des 2000 clients**.

    Le Loader **compose donc son propre MSISDN** depuis le plan de
    numerotation, exactement comme il compose deja les raisons sociales, les
    dates de naissance et les adresses. Le `sim_number` de Faker n'est
    conserve que pour la tracabilite.
    """
    numero = normaliser_msisdn(msisdn).lstrip("+")
    trouver = getattr(referentiel, "operateur_du_msisdn", None)
    if trouver is None:
        raise InvariantViole("referentiel sans plan de numerotation — EF-27 inapplicable")
    operateur = trouver(numero, pays)
    if operateur is None:
        raise InvariantViole(
            f"MSISDN '{msisdn}' non attribuable a un operateur de {pays} — EF-27. "
            "Rappel : les numeros de Faker ne respectent aucun plan reel (mesure 09/08), "
            "le Loader compose les siens."
        )
    return operateur


def valider_devise_pays(devise: str, pays: str, referentiel: object) -> str:
    """La devise n'est pas un choix parmi deux — elle est **determinee par la
    zone monetaire du pays**.

    `XAF` = zone CEMAC, banque centrale BEAC -> **Cameroun**.
    `XOF` = zone UEMOA, banque centrale BCEAO -> **Cote d'Ivoire, Burkina
    Faso, Senegal**.

    Emettre `XOF` pour un client camerounais serait aussi faux qu'emettre une
    devise inventee — et aucun service ne le refuserait, puisque `currency`
    n'est validee nulle part et atterrit telle quelle dans le compte
    (`FRA-222`).
    """
    code = str(devise).strip().upper()
    resoudre = getattr(referentiel, "devise_du_pays", None)
    attendue = resoudre(pays) if resoudre else None
    if attendue is None:
        raise InvariantViole(f"aucune devise rattachee au pays {pays!r} dans le referentiel")
    if code != attendue.code:
        raise InvariantViole(
            f"devise '{code}' pour un client de {pays} — la zone monetaire impose "
            f"'{attendue.code}' ({attendue.banque_centrale}). Le serveur accepterait "
            "n'importe quoi, y compris une chaine vide (FRA-222)."
        )
    return code


def exiger_champs_renseignes(donnees: dict[str, object], champs: tuple[str, ...]) -> None:
    """Aucun champ vide, jamais.

    Le contrat serveur declare optionnels `city`, `region`, `country`,
    `latitude`, `longitude`, `place_of_birth`, `marital_status`... et les
    persiste a `null` quand on les omet (mesure 09/08). Une population dont
    les adresses n'ont ni ville ni pays n'est pas demontrable.

    Le Loader dispose du referentiel : il n'a **aucune raison** de laisser un
    champ vide. Ce que le serveur tolere, nous ne le tolerons pas.
    """
    manquants = [c for c in champs if donnees.get(c) in (None, "", [], {})]
    if manquants:
        raise InvariantViole(
            f"champs vides : {', '.join(manquants)}. Le serveur les accepte a null, mais le "
            "Loader dispose du referentiel — un champ vide est une perte de richesse, jamais "
            "une fatalite."
        )


def normaliser_email(email: str) -> str:
    """L'unicite de l'email est imposee par identity-service (mesure 09/08),
    mais sans normalisation : deux casses produisent deux Identities."""
    return str(email).strip().lower()


def normaliser_msisdn(msisdn: str) -> str:
    """Retire espaces et separateurs. `EF-25` exige l'unicite des MSISDN ; une
    difference de formatage la briserait sans que rien ne le signale."""
    return re.sub(r"[\s.\-()]", "", str(msisdn).strip())


def sans_accents(texte: str) -> str:
    """Les patronymes Faker portent des accents ; certains champs serveur ne
    les supportent pas de facon homogene. Utilise pour composer `id_number` et
    les identifiants derives, jamais pour l'affichage."""
    decompose = unicodedata.normalize("NFD", str(texte))
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


# --------------------------------------------------------------------------
# Cohérence d'ensemble — le controle que personne ne fait
# --------------------------------------------------------------------------


def valider_identite_complete(
    *,
    naissance: date | str,
    expiration_piece: date | str,
    genre: str,
    situation_familiale: str,
    nationalite: str,
    id_number: str,
    email: str,
    reference: date | None = None,
) -> dict[str, object]:
    """Applique toutes les regles et renvoie les valeurs **normalisees**.

    C'est le point d'entree unique : un appelant qui oublierait une regle
    isolee ne peut pas oublier celle-ci.
    """
    naiss = _en_date(naissance, "date de naissance")
    exp = _en_date(expiration_piece, "expiration de la piece")

    age = valider_age(naiss, reference)
    valider_piece_identite(naiss, exp, reference)

    return {
        "age": age,
        "jeune": age < AGE_JEUNE_MAX,
        "date_of_birth": naiss,
        "id_expire_on": exp,
        "gender": valider_genre(genre),
        "marital_status": valider_situation_familiale(situation_familiale),
        "nationality": valider_nationalite(nationalite),
        "id_number": valider_id_number(id_number),
        "email": normaliser_email(email),
    }


class RegistreUnicite:
    """Garantit les **trois** unicites imposees par le serveur, avant le reseau.

    `EF-25` n'exige que l'unicite du MSISDN. La mesure du 09/08 en a etabli
    **trois** :

        msisdn      400 « Client already exists »
        id_number   400 « Client already exists »  <- message TROMPEUR : il
                    annonce un doublon de Client alors que le msisdn differait
        email       400 « Identity with this email already exists »

    Le message d'`id_number` est le piege : sans test dedie, on diagnostiquerait
    le mauvais champ — deux mille fois.

    **Pourquoi une memoire de processus suffit.** Une execution est un seul
    processus, borne a 30 minutes (`ENF-01`), et le prefixe `DEMO_` isole nos
    donnees. Le serveur applique de toute facon ses propres unicites : notre
    registre ne les remplace pas, il evite d'aller les decouvrir en 400. Deux
    executions concurrentes sont exclues par le verrou d'execution (`EF-58`).

    La normalisation est appliquee **avant** comparaison : le serveur, lui, ne
    normalise rien — `Demo@x` et `demo@x` y produisent deux Identities.
    """

    __slots__ = ("_emails", "_id_numbers", "_msisdn")

    def __init__(self) -> None:
        self._msisdn: set[str] = set()
        self._id_numbers: set[str] = set()
        self._emails: set[str] = set()

    def reserver(self, *, msisdn: str, id_number: str, email: str) -> tuple[str, str, str]:
        """Reserve les trois valeurs d'un client, ou refuse la premiere en conflit.

        Renvoie le triplet **normalise** — c'est lui qu'il faut emettre, pas
        les valeurs d'origine.
        """
        numero = normaliser_msisdn(msisdn)
        piece = valider_id_number(id_number)
        courriel = normaliser_email(email)

        for valeur, deja_vus, champ in (
            (numero, self._msisdn, "msisdn"),
            (piece, self._id_numbers, "id_number"),
            (courriel, self._emails, "email"),
        ):
            if valeur in deja_vus:
                raise InvariantViole(
                    f"{champ} '{valeur}' deja utilise dans cette execution. Le serveur le "
                    "refuserait en 400 — et pour `id_number` son message annonce « Client "
                    "already exists », ce qui designe le mauvais champ (mesure 09/08)."
                )

        self._msisdn.add(numero)
        self._id_numbers.add(piece)
        self._emails.add(courriel)
        return numero, piece, courriel

    @property
    def effectif(self) -> int:
        """Nombre de clients reserves — doit valoir 2000 en fin d'execution."""
        return len(self._msisdn)

    def resume(self) -> str:
        return (
            f"unicite : {len(self._msisdn)} msisdn · "
            f"{len(self._id_numbers)} id_number · {len(self._emails)} email"
        )


def _en_date(valeur: date | str, libelle: str) -> date:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = str(valeur).strip()
    try:
        return date.fromisoformat(texte[:10])
    except ValueError as erreur:
        raise InvariantViole(f"{libelle} illisible : {valeur!r}") from erreur
