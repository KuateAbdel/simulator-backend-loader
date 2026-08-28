"""
app/core/geoip.py
=================
IP -> PAYS, en lecture LOCALE — demande Direction du 28/08 : « le journal
affiche l'adresse IP de la personne, pour savoir de quel pays elle se
connecte reellement ».

DEUX PRINCIPES, et ils ne se negocient pas :

  1. JAMAIS un service externe. Envoyer l'adresse d'un partenaire a une API
     tierce pour la geolocaliser serait une fuite de donnee — la base est un
     fichier embarque (db-ip.com, « IP to Country Lite », licence CC-BY 4.0,
     attribution : https://db-ip.com), lu sur place.
  2. JAMAIS un echec propage. La geolocalisation est un CONFORT de journal :
     base absente, IP illisible, adresse privee — on rend None et le geste
     continue. Meme doctrine que le champ `appareil` (contrat 0.4a).

La resolution se fait A L'ECRITURE de la trace, pas a l'affichage : le
journal garde le pays tel qu'il etait au moment du geste, meme si la base
change ensuite — une trace ne se reinterprete pas.
"""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: La base embarquee — mise a jour mensuelle possible en remplacant le
#: fichier (aucun code ne change, le format mmdb est auto-descriptif).
_CHEMIN_BASE = Path(__file__).resolve().parent.parent / "data" / "dbip-country-lite.mmdb"

_lecteur: Any | None = None
_ouverture_tentee = False


def _ouvrir() -> Any | None:
    """Ouvre la base UNE fois, paresseusement. Absente ou illisible : None,
    et on ne reessaie pas a chaque appel (le journal n'attend pas)."""
    global _lecteur, _ouverture_tentee
    if _ouverture_tentee:
        return _lecteur
    _ouverture_tentee = True
    try:
        import maxminddb

        _lecteur = maxminddb.open_database(str(_CHEMIN_BASE))
    except Exception:  # pragma: no cover — defense d'exploitation
        logger.exception(
            "base IP->pays indisponible (%s) — le journal rendra l'IP seule",
            _CHEMIN_BASE,
        )
        _lecteur = None
    return _lecteur


def pays_de_l_ip(ip: str | None) -> str | None:
    """Le code ISO-2 du pays de CETTE adresse — ou None, jamais une erreur.

    Une adresse privee (banc local, reseau interne) n'a pas de pays : None
    assume, pas un faux « ZZ »."""
    if not ip:
        return None
    try:
        adresse = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if adresse.is_private or adresse.is_loopback or adresse.is_link_local:
        return None
    lecteur = _ouvrir()
    if lecteur is None:
        return None
    try:
        fiche = lecteur.get(ip) or {}
        code = (fiche.get("country") or {}).get("iso_code")
        return str(code) if code else None
    except Exception:  # pragma: no cover — defense d'exploitation
        return None
