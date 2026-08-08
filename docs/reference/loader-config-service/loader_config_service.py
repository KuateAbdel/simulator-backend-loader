#!/usr/bin/env python3
"""
loader_config_service.py
=========================
Loader discipline senior pour config-service (FinZuu).

Arborescence attendue (le script suppose qu'il est lance depuis la racine
du projet, ou que --data-dir pointe vers le bon dossier) :

    loader-config-service/
    |-- loader_config_service.py   <- ce fichier
    |-- data/
    |   |-- currencies.csv
    |   |-- telcos.csv
    |   `-- countries.csv
    |-- state/
    |   `-- uuid_map.json          <- genere automatiquement (UUID captures)
    |-- logs/
    |   `-- loader_YYYYMMDD_HHMMSS.jsonl   <- genere automatiquement (SIEM local)
    `-- .env                       <- genere par toi (voir .env.example)

Pourquoi un seul script et pas 3 :
    Les 3 phases (Currencies -> Telcos -> Countries) partagent un etat en
    memoire (les UUID captures a la creation). Separer en 3 scripts
    obligerait a serialiser cet etat entre deux processus, ce qui casse
    l'atomicite logique du chargement et ajoute un point de fragilite pour
    rien : le volume (18 entites) ne justifie aucune scalabilite qui exigerait
    des processus separes.

Authentification :
    Le script commence TOUJOURS par un POST /auth/login sur user-service
    avec les identifiants ROOT (jamais un token colle en dur ni recycle
    d'une session precedente -- un access_token expire au bout de 4h).
    Le token est ensuite reutilise pour TOUTES les requetes vers
    config-service durant l'execution.

    Rappel empirique documente (Confluence "Service Anatomy user-service",
    ticket Jira FRA-48) : ROOT est cense bypasser toutes les autorisations
    sur tous les services, config-service inclus. A ce jour (27 juillet),
    config-service refuse ROOT avec un 403 -- c'est un bug serveur non
    resolu, pas une erreur de ce script. Le script s'arrete proprement avec
    un message explicite si ce cas se reproduit, plutot que d'echouer en
    silence ou de continuer sur une hypothese fausse.

Discipline appliquee (anomalies config-service neutralisees) :
    - GET avant chaque POST (idempotence manuelle, le serveur ne garantit
      pas l'unicite -- bugs RC-182/RC-183 documentes)
    - Normalisation stricte : booleens JSON reels (pas de string "yes"/"no"),
      iso_name toujours en MAJUSCULES avant envoi et avant comparaison
    - Validation de cardinalite AVANT l'appel HTTP : un Country ne part
      jamais vers l'API si ses currencies[]/telcos[] resolus sont vides
      (anomalie ANO-CFG-VALID-05 : le serveur repond 404 trompeur sinon)
    - Validation de longueur defensive cote client (le serveur n'a pas de
      maxLength -- anomalie ANO-CFG-LIMITS-15)
    - Ordre topologique strict : Currencies -> Telcos -> Countries
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, field_validator

# --------------------------------------------------------------------------
# Configuration (jamais de secret en dur -- toujours via variables d'env)
# --------------------------------------------------------------------------

USER_SERVICE_BASE = os.environ.get(
    "USER_SERVICE_BASE", "https://user-service.test.services.fintech4esg.com"
)
CONFIG_SERVICE_BASE = os.environ.get(
    "CONFIG_SERVICE_BASE", "https://config-service.test.services.fintech4esg.com"
)
ROOT_USERNAME = os.environ.get("ROOT_USERNAME")
ROOT_PASSWORD = os.environ.get("ROOT_PASSWORD")

HTTP_TIMEOUT = 15.0


# --------------------------------------------------------------------------
# Modeles Pydantic v2 -- alignes strictement sur les schemas OpenAPI reels
# --------------------------------------------------------------------------

class CurrencyRow(BaseModel):
    iso_name: str
    name_en: str
    name_fr: str
    accepts_decimal: bool

    @field_validator("iso_name")
    @classmethod
    def _iso_upper_3(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 3:
            raise ValueError(f"iso_name Currency doit faire 3 caracteres (ISO 4217), recu: {v!r}")
        return v

    @field_validator("name_en", "name_fr")
    @classmethod
    def _max_len_name(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError("name_en/name_fr > 100 caracteres refuse cote script (anomalie ANO-CFG-LIMITS-15)")
        return v


class TelcoRow(BaseModel):
    country_iso2: str  # colonne technique -- jamais envoyee a l'API
    name: str
    phone_regex: str

    @field_validator("phone_regex")
    @classmethod
    def _regex_must_compile(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"phone_regex non compilable ({exc}) -- refuse cote script (anomalie RC-184)")
        return v


class CountryRow(BaseModel):
    iso_name: str
    name_en: str
    name_fr: str
    dial_code: str
    region: str
    continent: str
    cities: str  # brut CSV, pipe-separe -- splitte ensuite
    currency_iso: str  # colonne technique -- resolue en UUID
    telco_names: str  # colonne technique, pipe-separee -- resolue en UUID

    @field_validator("iso_name")
    @classmethod
    def _iso_upper_2(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) != 2:
            raise ValueError(f"iso_name Country doit faire 2 caracteres (ISO 3166-1), recu: {v!r}")
        return v

    def cities_list(self) -> list[str]:
        return [c.strip() for c in self.cities.split("|") if c.strip()]

    def telco_names_list(self) -> list[str]:
        return [t.strip() for t in self.telco_names.split("|") if t.strip()]


# --------------------------------------------------------------------------
# Rapport / logging local (SIEM applicatif -- les Logs serveur sont
# inexploitables, cf anomalies H23/A3 documentees)
# --------------------------------------------------------------------------

@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Crees   : {len(self.created)}\n"
            f"Skipped : {len(self.skipped)} (deja existants)\n"
            f"Erreurs : {len(self.errors)}"
        )


class RunLogger:
    def __init__(self, log_path: Path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entity: str, action: str, status: str, detail: str = "") -> None:
        entry = {
            "request_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entity": entity,
            "action": action,
            "status": status,
            "detail": detail,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Authentification -- toujours un login frais, jamais un token recycle
# --------------------------------------------------------------------------

def login_root(client: httpx.Client) -> str:
    if not ROOT_USERNAME or not ROOT_PASSWORD:
        print(
            "ERREUR: variables d'environnement ROOT_USERNAME / ROOT_PASSWORD absentes.\n"
            "Exporte-les avant de lancer le script, par exemple :\n"
            "  export ROOT_USERNAME='noreply@finzuu.com'\n"
            "  export ROOT_PASSWORD='********'\n",
            file=sys.stderr,
        )
        sys.exit(2)

    resp = client.post(
        f"{USER_SERVICE_BASE}/api/v1/auth/login",
        json={"username": ROOT_USERNAME, "password": ROOT_PASSWORD},
    )
    if resp.status_code != 200:
        print(f"ERREUR: login Root a echoue -- HTTP {resp.status_code}\n{resp.text}", file=sys.stderr)
        sys.exit(2)

    data = resp.json()["data"]
    token = data["access_token"]
    print(f"Login Root OK -- user_id={data['user']['id']} (token valide 4h)")
    return token


def assert_config_service_reachable(client: httpx.Client, token: str) -> None:
    """
    Sondage de sante avant de lancer les 3 phases. S'arrete immediatement
    et lisiblement si le 403 documente (FRA-48 / ecart empirique du
    27/07) est toujours present -- pas d'entetement a taper dans le vide.
    """
    resp = client.get(
        f"{CONFIG_SERVICE_BASE}/api/v1/currencies/",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code == 403:
        print(
            "\nBLOQUE -- config-service refuse le token ROOT (HTTP 403).\n"
            "Ceci reproduit le bug documente FRA-48 / ecart empirique du 27/07/2026 :\n"
            "ROOT devrait bypasser toute autorisation (cf ticket FRA-48) mais ne le fait\n"
            "pas sur ce service precisement. Ce n'est PAS un probleme de ce script.\n"
            "Action requise : faire lever ce blocage cote serveur (Brill / Randolph)\n"
            "avant de relancer le loader.\n",
            file=sys.stderr,
        )
        sys.exit(3)
    if resp.status_code != 200:
        print(f"ERREUR inattendue en sondant config-service : HTTP {resp.status_code}\n{resp.text}", file=sys.stderr)
        sys.exit(3)
    print("Sondage config-service OK -- ROOT autorise, on peut proceder.\n")


# --------------------------------------------------------------------------
# Helpers HTTP generiques (GET liste paginee -> index local, POST create)
# --------------------------------------------------------------------------

def fetch_existing_index(client: httpx.Client, token: str, entity_path: str, key_field: str) -> dict[str, dict]:
    """
    Construit un index local {valeur_normalisee(key_field): objet}
    en paginant sur GET /{entity}/. Necessaire car le serveur n'applique
    pas d'unicite reelle (RC-182/RC-183) : c'est au script de la garantir.
    """
    index: dict[str, dict] = {}
    page = 1
    while True:
        resp = client.get(
            f"{CONFIG_SERVICE_BASE}/api/v1/{entity_path}/",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 100, "page": page},
        )
        resp.raise_for_status()
        body = resp.json()
        rows = body.get("data", [])
        for row in rows:
            key = str(row.get(key_field, "")).strip().upper()
            # Normalisation _id -> id (fuite MongoDB VIOL-06.1 documentee)
            # Le serveur config-service renvoie _id (MongoDB brut) au lieu de id
            if "_id" in row and not row.get("id"):
                row["id"] = row["_id"]
            index[key] = row
        paginate = body.get("paginate", {})
        if page >= paginate.get("last_page", 1) or not rows:
            break
        page += 1
    return index


def post_create(
    client: httpx.Client, token: str, entity_path: str, payload: dict, dry_run: bool
) -> tuple[bool, str, str | None]:
    """Retourne (succes, message, id_cree_ou_None)."""
    request_id = str(uuid.uuid4())
    if dry_run:
        fake_id = str(uuid.uuid4())
        return True, f"[DRY-RUN] aurait POST {entity_path}/create avec {payload}", fake_id

    resp = client.post(
        f"{CONFIG_SERVICE_BASE}/api/v1/{entity_path}/create",
        headers={"Authorization": f"Bearer {token}", "X-Request-Id": request_id},
        json=payload,
    )
    if resp.status_code == 201:
        data = resp.json().get("data", {})
        new_id = data.get("id") or data.get("_id")
        if new_id:
            return True, f"HTTP 201 cree, id={new_id}", new_id
        return False, f"HTTP 201 sans id dans data: {resp.text}", None
    return False, f"HTTP {resp.status_code}: {resp.text}", None


def put_update(
    client: httpx.Client, token: str, entity_path: str, entity_id: str, payload: dict, dry_run: bool
) -> tuple[bool, str]:
    """
    Force la mise a jour d'une entite existante deja polluee ou incoherente
    avec le CSV. Retourne (succes, message).
    Utilise pour ecraser les donnees de test manuelles (CDN, Test Telco, etc.)
    """
    request_id = str(uuid.uuid4())
    if dry_run:
        return True, f"[DRY-RUN] aurait PUT {entity_path}/{entity_id} avec {payload}"

    resp = client.put(
        f"{CONFIG_SERVICE_BASE}/api/v1/{entity_path}/{entity_id}",
        headers={"Authorization": f"Bearer {token}", "X-Request-Id": request_id},
        json=payload,
    )
    if resp.status_code in (200, 201):
        return True, f"HTTP {resp.status_code} mis a jour"
    return False, f"HTTP {resp.status_code}: {resp.text}"


# --------------------------------------------------------------------------
# Phase 1 -- Currencies
# --------------------------------------------------------------------------

def phase_currencies(
    client: httpx.Client, token: str, data_dir: Path, dry_run: bool, report: Report, logger: RunLogger,
    force_update: bool
) -> dict[str, str]:
    print("=== Phase 1/3 -- Currencies ===")
    uuid_map: dict[str, str] = {}
    existing = fetch_existing_index(client, token, "currencies", "iso_name")

    with open(data_dir / "currencies.csv", newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = CurrencyRow(
                iso_name=raw["iso_name"],
                name_en=raw["name_en"],
                name_fr=raw["name_fr"],
                accepts_decimal=raw["accepts_decimal"].strip().lower() == "true",
            )
            if row.iso_name in existing:
                existing_row = existing[row.iso_name]
                existing_id = existing_row.get("id")
                # Detection de pollution : le contenu existant matche-t-il le CSV ?
                is_polluted = (
                    existing_row.get("name_en", "").strip() != row.name_en.strip() or
                    existing_row.get("name_fr", "").strip() != row.name_fr.strip() or
                    bool(existing_row.get("accepts_decimal", False)) != row.accepts_decimal
                )

                if is_polluted and force_update and existing_id:
                    # Ecrasement force via PUT
                    ok, msg = put_update(
                        client, token, "currencies", existing_id,
                        {
                            "name_en": row.name_en,
                            "name_fr": row.name_fr,
                            "iso_name": row.iso_name,
                            "accepts_decimal": row.accepts_decimal,
                        },
                        dry_run,
                    )
                    if ok:
                        uuid_map[row.iso_name] = existing_id
                        report.created.append(f"Currency {row.iso_name} (updated)")
                        logger.write("Currency", "update", "success", msg)
                        print(f"  UPDATE {row.iso_name} (etait pollue) -- {msg}")
                    else:
                        report.errors.append(f"Currency {row.iso_name}: {msg}")
                        logger.write("Currency", "update", "error", msg)
                        print(f"  ERROR {row.iso_name} -- {msg}")
                    continue

                if is_polluted and not force_update:
                    detail = f"pollue (existant={existing_row.get('name_en')} vs CSV={row.name_en}), non ecrase (utiliser --force-update-on-mismatch)"
                    print(f"  WARN  {row.iso_name} -- {detail}")
                    if existing_id:
                        uuid_map[row.iso_name] = existing_id
                    report.skipped.append(f"Currency {row.iso_name} (pollue non ecrase)")
                    logger.write("Currency", "create", "skipped_polluted", detail)
                    continue

                # Coherent -> SKIP normal
                if existing_id:
                    uuid_map[row.iso_name] = existing_id
                    detail = f"deja existant coherent id={existing_id}"
                    print(f"  SKIP  {row.iso_name} (coherent, id={existing_id})")
                else:
                    detail = "deja existant sans id dans la reponse GET"
                    print(f"  SKIP  {row.iso_name} (coherent, id absent dans la reponse GET)")
                report.skipped.append(f"Currency {row.iso_name}")
                logger.write("Currency", "create", "skipped", detail)
                continue

            ok, msg, new_id = post_create(
                client, token, "currencies",
                {
                    "name_en": row.name_en,
                    "name_fr": row.name_fr,
                    "iso_name": row.iso_name,
                    "accepts_decimal": row.accepts_decimal,
                },
                dry_run,
            )
            if ok:
                if new_id:
                    uuid_map[row.iso_name] = new_id
                report.created.append(f"Currency {row.iso_name}")
                logger.write("Currency", "create", "success", msg)
                print(f"  OK    {row.iso_name} -- {msg}")
            else:
                report.errors.append(f"Currency {row.iso_name}: {msg}")
                logger.write("Currency", "create", "error", msg)
                print(f"  ERROR {row.iso_name} -- {msg}")

    return uuid_map


# --------------------------------------------------------------------------
# Phase 2 -- Telcos
# --------------------------------------------------------------------------

def phase_telcos(
    client: httpx.Client, token: str, data_dir: Path, dry_run: bool, report: Report, logger: RunLogger,
    force_update: bool
) -> dict[str, str]:
    print("\n=== Phase 2/3 -- Telcos ===")
    uuid_map: dict[str, str] = {}
    existing = fetch_existing_index(client, token, "telcos", "name")

    with open(data_dir / "telcos.csv", newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = TelcoRow(
                country_iso2=raw["country_iso2"],
                name=raw["name"],
                phone_regex=raw["phone_regex"],
            )
            key = row.name.strip().upper()
            if key in existing:
                existing_row = existing[key]
                existing_id = existing_row.get("id")
                is_polluted = (
                    existing_row.get("phone_regex", "").strip() != row.phone_regex.strip()
                )

                if is_polluted and force_update and existing_id:
                    ok, msg = put_update(
                        client, token, "telcos", existing_id,
                        {"name": row.name, "phone_regex": row.phone_regex},
                        dry_run,
                    )
                    if ok:
                        uuid_map[row.name] = existing_id
                        report.created.append(f"Telco {row.name} (updated)")
                        logger.write("Telco", "update", "success", msg)
                        print(f"  UPDATE {row.name} (etait pollue) -- {msg}")
                    else:
                        report.errors.append(f"Telco {row.name}: {msg}")
                        logger.write("Telco", "update", "error", msg)
                        print(f"  ERROR {row.name} -- {msg}")
                    continue

                if is_polluted and not force_update:
                    detail = f"pollue (regex existant={existing_row.get('phone_regex')} vs CSV={row.phone_regex}), non ecrase"
                    print(f"  WARN  {row.name} -- {detail}")
                    if existing_id:
                        uuid_map[row.name] = existing_id
                    report.skipped.append(f"Telco {row.name} (pollue non ecrase)")
                    logger.write("Telco", "create", "skipped_polluted", detail)
                    continue

                if existing_id:
                    uuid_map[row.name] = existing_id
                    detail = f"deja existant coherent id={existing_id}"
                    print(f"  SKIP  {row.name} (coherent, id={existing_id})")
                else:
                    detail = "deja existant sans id dans la reponse GET"
                    print(f"  SKIP  {row.name} (coherent, id absent dans la reponse GET)")
                report.skipped.append(f"Telco {row.name}")
                logger.write("Telco", "create", "skipped", detail)
                continue

            ok, msg, new_id = post_create(
                client, token, "telcos",
                {"name": row.name, "phone_regex": row.phone_regex},
                dry_run,
            )
            if ok:
                if new_id:
                    uuid_map[row.name] = new_id
                report.created.append(f"Telco {row.name}")
                logger.write("Telco", "create", "success", msg)
                print(f"  OK    {row.name} -- {msg}")
            else:
                report.errors.append(f"Telco {row.name}: {msg}")
                logger.write("Telco", "create", "error", msg)
                print(f"  ERROR {row.name} -- {msg}")

    return uuid_map


# --------------------------------------------------------------------------
# Phase 3 -- Countries (depend des UUID Phase 1 + Phase 2)
# --------------------------------------------------------------------------

def phase_countries(
    client: httpx.Client,
    token: str,
    data_dir: Path,
    dry_run: bool,
    report: Report,
    logger: RunLogger,
    currency_uuids: dict[str, str],
    telco_uuids: dict[str, str],
    force_update: bool,
) -> None:
    print("\n=== Phase 3/3 -- Countries ===")
    existing = fetch_existing_index(client, token, "countries", "iso_name")

    with open(data_dir / "countries.csv", newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = CountryRow(**raw)

            if row.iso_name in existing:
                existing_row = existing[row.iso_name]
                existing_id = existing_row.get("id")

                # Pour Country, on doit d'abord resoudre les UUID Currency + Telcos
                # pour construire le payload complet, meme en cas de PUT.
                currency_id = currency_uuids.get(row.currency_iso.strip().upper())
                telco_ids = [telco_uuids[t] for t in row.telco_names_list() if t in telco_uuids]

                # Detection de pollution : comparaison sur name_en + dial_code + nb cities
                is_polluted = (
                    existing_row.get("name_en", "").strip() != row.name_en.strip() or
                    existing_row.get("dial_code", "").strip() != row.dial_code.strip() or
                    len(existing_row.get("cities", []) or []) != len(row.cities_list())
                )

                if is_polluted and force_update and existing_id and currency_id and telco_ids:
                    payload = {
                        "name_en": row.name_en,
                        "name_fr": row.name_fr,
                        "iso_name": row.iso_name,
                        "dial_code": row.dial_code,
                        "region": row.region,
                        "continent": row.continent,
                        "cities": row.cities_list(),
                        "currencies": [currency_id],
                        "telcos": telco_ids,
                    }
                    ok, msg = put_update(client, token, "countries", existing_id, payload, dry_run)
                    if ok:
                        report.created.append(f"Country {row.iso_name} (updated)")
                        logger.write("Country", "update", "success", msg)
                        print(f"  UPDATE {row.iso_name} (etait pollue) -- {msg}")
                    else:
                        report.errors.append(f"Country {row.iso_name}: {msg}")
                        logger.write("Country", "update", "error", msg)
                        print(f"  ERROR {row.iso_name} -- {msg}")
                    continue

                if is_polluted and not force_update:
                    detail = f"pollue (existant={existing_row.get('name_en')} vs CSV={row.name_en}), non ecrase"
                    print(f"  WARN  {row.iso_name} -- {detail}")
                    report.skipped.append(f"Country {row.iso_name} (pollue non ecrase)")
                    logger.write("Country", "create", "skipped_polluted", detail)
                    continue

                if existing_id:
                    detail = f"deja existant coherent id={existing_id}"
                    print(f"  SKIP  {row.iso_name} (coherent, id={existing_id})")
                else:
                    detail = "deja existant sans id dans la reponse GET"
                    print(f"  SKIP  {row.iso_name} (coherent, id absent dans la reponse GET)")
                report.skipped.append(f"Country {row.iso_name}")
                logger.write("Country", "create", "skipped", detail)
                continue

            # Resolution des UUID -- ANOMALIE ANO-CFG-VALID-05 neutralisee ici :
            # on refuse d'envoyer si la resolution echoue, plutot que de
            # laisser le serveur repondre un 404 trompeur sur un array vide.
            currency_id = currency_uuids.get(row.currency_iso.strip().upper())
            if not currency_id:
                msg = f"currency_iso={row.currency_iso!r} introuvable dans les UUID Phase 1 -- refuse cote script"
                report.errors.append(f"Country {row.iso_name}: {msg}")
                logger.write("Country", "create", "error", msg)
                print(f"  ERROR {row.iso_name} -- {msg}")
                continue

            telco_ids = []
            missing_telcos = []
            for tname in row.telco_names_list():
                tid = telco_uuids.get(tname)
                if tid:
                    telco_ids.append(tid)
                else:
                    missing_telcos.append(tname)
            if missing_telcos or not telco_ids:
                msg = f"telcos introuvables dans les UUID Phase 2: {missing_telcos} -- refuse cote script"
                report.errors.append(f"Country {row.iso_name}: {msg}")
                logger.write("Country", "create", "error", msg)
                print(f"  ERROR {row.iso_name} -- {msg}")
                continue

            payload = {
                "name_en": row.name_en,
                "name_fr": row.name_fr,
                "iso_name": row.iso_name,
                "dial_code": row.dial_code,
                "region": row.region,
                "continent": row.continent,
                "cities": row.cities_list(),
                "currencies": [currency_id],
                "telcos": telco_ids,
            }
            ok, msg, new_id = post_create(client, token, "countries", payload, dry_run)
            if ok:
                report.created.append(f"Country {row.iso_name}")
                logger.write("Country", "create", "success", msg)
                print(f"  OK    {row.iso_name} -- {msg}")
            else:
                report.errors.append(f"Country {row.iso_name}: {msg}")
                logger.write("Country", "create", "error", msg)
                print(f"  ERROR {row.iso_name} -- {msg}")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Loader config-service FinZuu -- Currencies -> Telcos -> Countries")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / "data",
                         help="Dossier contenant currencies.csv, telcos.csv, countries.csv (defaut: ./data)")
    parser.add_argument("--execute", action="store_true",
                         help="Execute reellement les POST. Sans ce flag: dry-run (rien n'est ecrit).")
    parser.add_argument("--force-update-on-mismatch", action="store_true",
                         help="Si une entite existe deja avec des donnees differentes du CSV, "
                              "la mettre a jour via PUT au lieu de la skipper. Utile pour ecraser "
                              "les donnees de test manuelles polluees (CDN, Test Telco, GD Guandana).")
    args = parser.parse_args()
    force_update = args.force_update_on_mismatch
    dry_run = not args.execute

    project_root = Path(__file__).parent
    state_dir = project_root / "state"
    logs_dir = project_root / "logs"
    state_dir.mkdir(exist_ok=True)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger = RunLogger(logs_dir / f"loader_{run_ts}.jsonl")
    report = Report()

    mode = "EXECUTE (ecriture reelle)" if args.execute else "DRY-RUN (aucune ecriture)"
    print(f"Loader config-service -- mode: {mode}")
    print(f"Data dir: {args.data_dir}\n")

    with httpx.Client(timeout=HTTP_TIMEOUT, http2=True) as client:
        token = login_root(client)
        assert_config_service_reachable(client, token)

        currency_uuids = phase_currencies(client, token, args.data_dir, dry_run, report, logger, force_update)
        telco_uuids = phase_telcos(client, token, args.data_dir, dry_run, report, logger, force_update)
        phase_countries(client, token, args.data_dir, dry_run, report, logger, currency_uuids, telco_uuids, force_update)

        # Persistance de l'etat pour tracabilite / reprise eventuelle
        uuid_map_path = state_dir / f"uuid_map_{run_ts}.json"
        with open(uuid_map_path, "w", encoding="utf-8") as f:
            json.dump({"currencies": currency_uuids, "telcos": telco_uuids}, f, indent=2, ensure_ascii=False)

    print("\n=== RAPPORT FINAL ===")
    print(report.summary())
    print(f"\nLog detaille : {logger.log_path}")
    print(f"UUID captures : {uuid_map_path}")
    if report.errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
