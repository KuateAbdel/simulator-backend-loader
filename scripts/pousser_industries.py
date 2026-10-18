"""
scripts/pousser_industries.py
=============================
Pousse le référentiel INDUSTRIES ⊃ SECTEURS de JJB (System of Record :
`docs/reference/static_data/final_company_Industry-Sector.json`, immuable) vers le module
`/industries` de config-service — la même doctrine que les pays : GET-avant-POST à chaque
niveau, re-lançable, ne double rien, et RELIT ce qui a atterri pour le vérifier.

    uv run python scripts/pousser_industries.py            # pousse, puis vérifie
    uv run python scripts/pousser_industries.py --verifier # relecture seule

Le contrat config-service (v1.0.1, lu le 30/09) porte l'industrie comme parent :
`CreateIndustrySchema {name, sectors: [str]}`. C'est l'inverse de la convention du fichier
(le secteur porte ses `industry_ids`), mais la relation n:n survit : un secteur-pont
(Fintech = Finance & Insurance ET Technology) apparaît dans la liste `sectors` de CHACUNE
de ses industries. La vérification finale le contrôle pour les 28 ponts.

LES AJOUTS, ET POURQUOI ILS NE SONT PAS DANS LE CLASSEUR. Le classeur de JJB est immuable —
`referentiel_statique.py` en garde les comptes (112 secteurs) pour détecter un fichier tronqué
ou remplacé, et la surcouche admin (`US-B5+`) pose déjà la règle : base immuable, ajout
réversible. Un secteur demandé par la Direction vit donc dans
`docs/reference/static_data/ajouts_secteurs.json`, et ce script pousse CLASSEUR + AJOUTS : un
nouveau chargement ne perd pas l'ajout, et le retirer tient en une ligne de moins.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

FICHIER = Path("docs/reference/static_data/final_company_Industry-Sector.json")
FICHIER_AJOUTS = Path("docs/reference/static_data/ajouts_secteurs.json")
B = "https://{s}.test.services.fintech4esg.com/api/v1"


def ajouts() -> list[dict[str, Any]]:
    """Les secteurs ajoutes par-dessus le classeur. Absent = aucun ajout, pas une erreur."""
    if not FICHIER_AJOUTS.exists():
        return []
    lus: Any = json.loads(FICHIER_AJOUTS.read_text(encoding="utf-8")).get("ajouts", [])
    return list(lus)


def taxonomie() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """industrie -> secteurs (ordre du fichier), secteur -> industries."""
    d = json.loads(FICHIER.read_text(encoding="utf-8"))
    ind = {i["id"]: i["label"] for i in d["industries"]}
    par_industrie: dict[str, list[str]] = {i["label"]: [] for i in d["industries"]}
    par_secteur: dict[str, list[str]] = collections.defaultdict(list)
    for s in d["sectors"]:
        for i in s["industry_ids"]:
            par_industrie[ind[i]].append(s["label"])
            par_secteur[s["label"]].append(ind[i])
    # LES AJOUTS, APRES le classeur : memes invariants que la surcouche admin — un label unique,
    # et des industries qui EXISTENT deja (on n'ouvre pas une 7e industrie par un secteur).
    for a in ajouts():
        libelle = str(a["label"]).strip()
        if not libelle or libelle in par_secteur:
            raise SystemExit(f"ajout refusé : secteur {libelle!r} vide ou déjà au classeur")
        for nom in a["industries"]:
            if nom not in par_industrie:
                raise SystemExit(f"ajout refusé : industrie {nom!r} inconnue du classeur")
            par_industrie[nom].append(libelle)
            par_secteur[libelle].append(nom)
    return par_industrie, dict(par_secteur)


class Config:
    def __init__(self) -> None:
        self.c = httpx.Client(timeout=90)
        r = self.c.post(
            B.format(s="user-service") + "/auth/login",
            json={"username": settings.root_username, "password": settings.root_password},
        )
        self.h = {"Authorization": "Bearer " + r.json()["data"]["token"]["access"]}

    def appel(self, m: str, chemin: str, **kw: Any) -> tuple[int, dict[str, Any]]:
        r = self.c.request(m, B.format(s="config-service") + chemin, headers=self.h, **kw)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"description": r.text[:200]}

    def toutes(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for page in range(1, 20):
            _, j = self.appel("GET", "/industries/", params={"limit": 200, "page": page})
            lot = j.get("data") or []
            out += lot
            if len(lot) < 200:
                break
        return out


def pousser(cfg: Config, par_industrie: dict[str, list[str]]) -> None:
    existantes = {x["name"]: x for x in cfg.toutes()}
    for nom, secteurs in par_industrie.items():
        deja = existantes.get(nom)
        if deja is None:
            code, j = cfg.appel(
                "POST", "/industries/create", json={"name": nom, "sectors": secteurs}
            )
            print(f"  CRÉÉE   {nom:22} {len(secteurs):3} secteurs → HTTP {code} {j['description']}")
        elif sorted(deja.get("sectors") or []) != sorted(secteurs):
            code, j = cfg.appel(
                "PUT", f"/industries/{deja['_id']}", json={"name": nom, "sectors": secteurs}
            )
            avant = len(deja.get("sectors") or [])
            desc = j.get("description")
            print(f"  MISE À JOUR {nom:18} {avant:3} → {len(secteurs):3} → HTTP {code} {desc}")
        else:
            print(f"  DÉJÀ LÀ {nom:22} {len(secteurs):3} secteurs (identique)")


def verifier(
    cfg: Config, par_industrie: dict[str, list[str]], par_secteur: dict[str, list[str]]
) -> int:
    """Relit config-service et compare au fichier ; rend le nombre d'écarts."""
    la_bas = {x["name"]: x for x in cfg.toutes()}
    ecarts = 0
    print(f"\nRELECTURE : {len(la_bas)} industries sur config-service")
    for nom, secteurs in par_industrie.items():
        x = la_bas.get(nom)
        if x is None:
            print(f"  ✗ {nom} ABSENTE")
            ecarts += 1
            continue
        s = x.get("sectors") or []
        manque = sorted(set(secteurs) - set(s))
        en_trop = sorted(set(s) - set(secteurs))
        doublons = [k for k, v in collections.Counter(s).items() if v > 1]
        ok = not manque and not en_trop and not doublons and x.get("is_active", True)
        ecarts += 0 if ok else 1
        print(
            f"  {'✓' if ok else '✗'} {nom:22} {len(s):3} secteurs · actif={x.get('is_active')}"
            + (f" · MANQUE {manque}" if manque else "")
            + (f" · EN TROP {en_trop}" if en_trop else "")
            + (f" · DOUBLONS {doublons}" if doublons else "")
        )
    en_trop_ind = sorted(set(la_bas) - set(par_industrie))
    if en_trop_ind:
        print(f"  ✗ industries INCONNUES du fichier : {en_trop_ind}")
        ecarts += len(en_trop_ind)
    # Les 28 ponts : chaque secteur multi-industries doit être dans CHAQUE liste.
    ponts_ok = 0
    for secteur, inds in par_secteur.items():
        if len(inds) < 2:
            continue
        portes = [i for i in inds if secteur in (la_bas.get(i) or {}).get("sectors", [])]
        if len(portes) == len(inds):
            ponts_ok += 1
        else:
            ecarts += 1
            print(f"  ✗ pont {secteur} : attendu dans {inds}, trouvé dans {portes}")
    print(
        f"  ponts n:n préservés : {ponts_ok}/{sum(1 for v in par_secteur.values() if len(v) > 1)}"
    )
    # Les routes de lecture que la webapp utilisera.
    for chemin in (
        "/industries/by-name/Technology",
        "/industries/search/fin",
        "/industries/active/i",
    ):
        code, j = cfg.appel("GET", chemin, params={"limit": 50})
        d = j.get("data")
        n = len(d) if isinstance(d, list) else (1 if isinstance(d, dict) else 0)
        print(f"  GET {chemin:34} → HTTP {code} · {n} résultat(s)")
    return ecarts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", action="store_true", help="relecture seule, aucune écriture")
    arg = ap.parse_args()
    par_industrie, par_secteur = taxonomie()
    ajoutes = [str(a["label"]) for a in ajouts()]
    print(
        f"FICHIER : {len(par_industrie)} industries · {len(par_secteur)} secteurs "
        f"({len(par_secteur) - len(ajoutes)} au classeur"
        + (f" + {len(ajoutes)} ajouté(s) : {', '.join(ajoutes)}" if ajoutes else "")
        + f") · {sum(1 for v in par_secteur.values() if len(v) > 1)} ponts"
    )
    cfg = Config()
    if not arg.verifier:
        pousser(cfg, par_industrie)
    ecarts = verifier(cfg, par_industrie, par_secteur)
    print(f"\n{'CONFORME' if ecarts == 0 else f'{ecarts} ÉCART(S)'}")
    sys.exit(0 if ecarts == 0 else 1)


if __name__ == "__main__":
    main()
