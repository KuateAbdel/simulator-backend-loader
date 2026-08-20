"""
app/core/politique_mot_de_passe.py
==================================
Politique de mot de passe du Loader — invariant **I-AUTH-9**.

Un mot de passe DURABLE (choisi par la personne : changement US-A2, reset
US-A4) est refuse s'il est trivialement devinable : trop court, mono-caractere,
suite de touches, ou bati sur un mot banni (mot courant FR/EN, marche-clavier,
nom du produit, morceau de son email).

CE QU'ON NE FAIT PAS, ET POURQUOI (decision Lead QA, 20/08) :
  on ne verifie JAMAIS qu'un mot de passe est deja utilise par un AUTRE
  compte. C'est impossible (l'empreinte scrypt est salee PAR mot de passe ->
  deux mots de passe egaux ont deux empreintes) ET ce serait un oracle :
  repondre « deja pris » apprendrait a un attaquant le mot de passe d'autrui.
  NIST 800-63B l'interdit. Le bon critere, celui de Microsoft (Azure AD
  Password Protection) et de la NIST, est « compromis / trop courant », JAMAIS
  « unique entre utilisateurs ».

Le modele est celui d'Azure AD Password Protection : une liste de TOKENS
bannis compares en SOUS-CHAINE sur une forme normalisee (minuscules + repli
leet), plus quelques regles de structure. C'est plus robuste qu'une liste
d'egalites exactes quand un plancher de 12 caracteres exclut deja « password »
ou « 123456 » tout court : ce qu'on veut attraper, c'est « P@ssw0rd-2026 ».

La fonction `evaluer` est PURE : elle ne depend que du mot de passe et,
optionnellement, de l'email de son proprietaire. Elle ne consulte AUCUN autre
compte — c'est ce qui la rend exposable telle quelle a un validateur temps
reel (UX interactive) sans creer d'oracle.
"""

from __future__ import annotations

from itertools import pairwise

#: Plancher NIST/ANSSI pour un compte a privilege. C'est la LONGUEUR qui
#: protege, pas la complexite par classes de caracteres (pas d'exigence de
#: « au moins un chiffre et une majuscule » : c'est du theatre de securite).
LONGUEUR_MDP_MIN = 12

#: Tokens bannis : si l'un apparait en SOUS-CHAINE du mot de passe normalise,
#: le mot de passe est refuse. Bases courantes FR/EN, marches-clavier, et
#: identite du produit (« FinZuuLoader1! » est devinable de l'interieur).
_TOKENS_BANNIS: frozenset[str] = frozenset(
    {
        "password",
        "motdepasse",
        "passe",
        "secret",
        "admin",
        "administrateur",
        "administrator",
        "superadmin",
        "welcome",
        "bienvenue",
        "letmein",
        "iloveyou",
        "jetaime",
        "changeme",
        "default",
        "connexion",
        "qwerty",
        "azerty",
        "qwertz",
        "asdfgh",
        "zxcvbn",
        "123456",
        "12345678",
        "123456789",
        "000000",
        "111111",
        "abcdef",
        "monkey",
        "dragon",
        "football",
        "superman",
        "trustno1",
        "finzuu",
        "loader",
        "fintech",
        "simulateur",
        "simulator",
    }
)

#: Repli « leet » : plusieurs graphies d'un meme mot doivent tomber sur le
#: meme token (« P@ssw0rd » -> « password », « 4zerty » -> « azerty »).
_REPLI_LEET = str.maketrans(
    {
        "@": "a", "4": "a", "3": "e", "1": "i", "!": "i",
        "|": "i", "0": "o", "5": "s", "$": "s", "7": "t",
    }
)


def _normaliser(mot_de_passe: str) -> str:
    return mot_de_passe.strip().lower().translate(_REPLI_LEET)


def _est_mono_caractere(mot_de_passe: str) -> bool:
    """« aaaaaaaaaaaa », « 000000000000 » : une seule touche repetee."""
    return len(set(mot_de_passe)) <= 1


def _est_sequence(norme: str) -> bool:
    """Suite strictement croissante ou decroissante de codes de caracteres
    (« abcdefghijkl », « 9876543210 »). On travaille sur la forme normalisee."""
    if len(norme) < 4:
        return False
    pas = {ord(b) - ord(a) for a, b in pairwise(norme)}
    return pas in ({1}, {-1})


def evaluer(mot_de_passe: str, *, email: str | None = None) -> list[str]:
    """Renvoie la LISTE des raisons de refus (liste vide = mot de passe accepte).

    Chaque raison est un libelle court, pret a etre affiche a l'utilisateur —
    le validateur temps reel comme l'erreur 422 s'en servent tels quels.
    """
    raisons: list[str] = []
    norme = _normaliser(mot_de_passe)

    if len(mot_de_passe) < LONGUEUR_MDP_MIN:
        raisons.append(f"au moins {LONGUEUR_MDP_MIN} caracteres")
    if mot_de_passe and _est_mono_caractere(mot_de_passe):
        raisons.append("pas un seul caractere repete")
    if _est_sequence(norme):
        raisons.append("pas une suite de touches (abcdef, 123456...)")
    if any(token in norme for token in _TOKENS_BANNIS):
        raisons.append(
            "trop courant ou devinable (evitez les mots communs, le nom du "
            "produit, un marche-clavier)"
        )
    if email:
        local = email.split("@", 1)[0].strip().lower()
        if len(local) >= 3 and local in norme:
            raisons.append("ne doit pas contenir votre adresse email")

    return raisons


def est_acceptable(mot_de_passe: str, *, email: str | None = None) -> bool:
    """Vrai si aucune raison de refus — le pendant booleen de `evaluer`."""
    return not evaluer(mot_de_passe, email=email)
