"""
scripts/executer_run.py
=======================
CLI du Loader — enveloppe mince du moteur `app/services/pilotage.py`.

    uv run python scripts/executer_run.py            # DRY_RUN — aucune ecriture
    uv run python scripts/executer_run.py --reel     # ECRITURES DEFINITIVES

Le moteur a demenage le 13/08 (lot B de l'API Super-Admin) : le CLI et l'API
partagent desormais le MEME `executer()` — un correctif du moteur sert les
deux chemins d'un coup, et aucun ne peut diverger de l'autre en silence.
Toute la doctrine (D-01, EF-55, reconciliations) vit avec le moteur.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from app.models.enums import RunMode
from app.services.orchestrateur import Etape
from app.services.pilotage import executer


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute un run du Loader FinZuu")
    parser.add_argument(
        "--reel",
        action="store_true",
        help="ECRITURES DEFINITIVES — trois services n'ont aucun DELETE",
    )
    parser.add_argument(
        "--etapes",
        default="",
        help="Limite aux etapes nommees, separees par des virgules (ex : ROLES). "
        "Vide = toutes. Sert au deploiement progressif en mode reel.",
    )
    parser.add_argument(
        "--ignorer-verrou",
        action="store_true",
        help="Passe outre le verrou EF-55. Reserve au cas d'un run interrompu "
        "reste RUNNING — jamais a deux executions volontairement simultanees.",
    )
    args = parser.parse_args()
    choisies = {Etape(n.strip().upper()) for n in args.etapes.split(",") if n.strip()} or None
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s : %(message)s")
    return asyncio.run(
        executer(
            RunMode.REAL if args.reel else RunMode.DRY_RUN,
            choisies,
            ignorer_verrou=args.ignorer_verrou,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
