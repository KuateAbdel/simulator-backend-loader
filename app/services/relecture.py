"""
app/services/relecture.py
=========================
Le DIFF payload <-> relecture — troisieme recommandation validee par Yaniv le
16/08 (avec la variante d'apercu et les scenarios nommes).

CE QUE LA RELECTURE PROUVAIT, ET CE QU'ELLE NE PROUVAIT PAS. Depuis FRA-218,
chaque creation a l'unite RELIT l'entite sur la plateforme : la fiche rendue
vient de la-bas, jamais de l'echo du POST. Mais cette relecture ne prouvait
que l'EXISTENCE. Un serveur qui normalise une valeur, tronque une chaine ou
PERD un champ a la persistance (FRA-199 : `currency` disparait de la fiche
Depositaire relue) passait inapercu — la fiche etait rendue telle quelle et
l'admin devait comparer a l'oeil.

LE PRINCIPE : l'apercu (rite D-01, etape 1) montre le payload EXACT qui
partira. Apres confirmation, la reponse doit PROUVER, champ par champ, que la
plateforme a tenu la promesse. Chaque champ ENVOYE est confronte a la fiche
RELUE :

  - meme valeur       -> fidele ;
  - valeur differente -> DIVERGENCE, dite avec les deux valeurs en face ;
  - champ absent      -> ABSENT de la relecture (le cas FRA-199).

UNE VERITE, JAMAIS UNE ERREUR : l'entite EXISTE (la relecture l'a prouve),
le POST a reussi. Une divergence n'invalide pas la creation — elle dit ce que
la plateforme a fait de notre matiere. Le verdict voyage dans la reponse 201 ;
c'est l'ecran (et la recette) qui decide quoi en faire.

CE QU'ON COMPARE : les champs ENVOYES, seulement. La plateforme ajoute les
siens (`_id`, timestamps, defauts serveur) — ils ne sont pas des divergences,
ils sont sa contribution normale. Le diff est donc ORIENTE : payload -> relu.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _aplatir(document: Mapping[str, Any], prefixe: str = "") -> dict[str, Any]:
    """Les dictionnaires imbriques deviennent des chemins pointes
    (`owner.email`) : un diff a plat se lit champ par champ, la ou un `!=`
    global dirait seulement « quelque chose differe »."""
    plat: dict[str, Any] = {}
    for cle, valeur in document.items():
        chemin = f"{prefixe}.{cle}" if prefixe else str(cle)
        if isinstance(valeur, Mapping):
            plat.update(_aplatir(valeur, chemin))
        else:
            plat[chemin] = valeur
    return plat


def _normaliser(valeur: Any) -> Any:
    """Egalite de VALEUR, pas de type — la meme lecon que l'empreinte D-10
    (admin_runs) : le serveur rend `3.0` pour un `3` envoye, et ce n'est pas
    une divergence. Pour les nombres, `==` de Python le garantit deja
    (`3 == 3.0`) — le banc le fige. `bool` seul se MARQUE : bool est un int
    en Python (`True == 1`), or un serveur qui rend `1` pour `true` a change
    la NATURE du champ — ca se dit. Les listes de scalaires se comparent
    TRIEES : l'ordre des `permissions` ou des `sectors` appartient au
    serveur, leur contenu nous appartient."""
    if isinstance(valeur, bool):
        return ("bool", valeur)
    if isinstance(valeur, list):
        normalisees = [_normaliser(v) for v in valeur]
        if all(not isinstance(v, (dict, list)) for v in normalisees):
            return sorted(normalisees, key=repr)
        return normalisees
    return valeur


def comparer_payload_relecture(
    envoye: Mapping[str, Any], relu: Mapping[str, Any]
) -> dict[str, Any]:
    """Le verdict structurel : `fidele` seulement quand CHAQUE champ envoye
    se relit a l'identique. Rendu tel quel dans la reponse de creation."""
    plats_envoye = _aplatir(envoye)
    plats_relu = _aplatir(relu)

    divergences: dict[str, dict[str, Any]] = {}
    absents: list[str] = []
    for chemin, valeur in plats_envoye.items():
        if chemin not in plats_relu:
            absents.append(chemin)
        elif _normaliser(plats_relu[chemin]) != _normaliser(valeur):
            divergences[chemin] = {"envoye": valeur, "relu": plats_relu[chemin]}

    fidele = not divergences and not absents
    return {
        "fidele": fidele,
        "champs_compares": len(plats_envoye),
        "divergences": divergences,
        "absents_de_la_relecture": sorted(absents),
        "verdict": (
            "la plateforme a persiste chaque champ envoye a l'identique"
            if fidele
            else (
                "la plateforme n'a PAS restitue la matiere a l'identique — "
                "l'entite EXISTE, les ecarts sont dits ci-dessus"
            )
        ),
    }
