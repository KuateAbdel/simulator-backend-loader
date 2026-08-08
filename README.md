# simulator-backend — Loader FinZuu (backend)

Backend du Loader FinZuu : orchestrateur HTTP qui consomme l'API Faker
fintech4esg en amont et injecte les entites generees dans les 9 microservices
FinZuu en aval (environnements TEST et DEMO exclusivement).

Le frontend (Next.js / TypeScript, Zidane) est hors perimetre de ce depot ; il
consomme le contrat OpenAPI expose ici.

## Documents de reference

| Document | Reference | Emplacement |
|---|---|---|
| Cahier des charges v1.2 | FZ-CDC-LOADER-2026-001 | `docs/reference/` |
| Stack technique v1.0 | FZ-STACK-LOADER-2026-001 | `docs/reference/` |
| Diagrammes UML (7 types, 11 fichiers) | — | `docs/reference/uml_diagrams/` |
| Contexte projet condense | — | `docs/CONTEXT.md` |

## Stack (verrouillee par FZ-STACK-LOADER-2026-001 §8)

Python 3.12 · FastAPI · Pydantic v2 · httpx (async, HTTP/2) · MongoDB via motor
· PyJWT · uv · ruff · mypy · pytest + pytest-asyncio.

Contrainte serveur : toute dependance native doit disposer d'une roue
`linux_aarch64` (cible 152.53.118.110, Ubuntu 24.04 ARM64).

## Structure

```
app/
├── core/           configuration, persistance MongoDB, disciplines defensives
├── routes/         endpoints FastAPI exposes au frontend
├── services/       orchestration metier (UC-05 a UC-17)     — a venir
├── clients/        clients HTTP sortants, un par cible externe — a venir
├── models/         documents MongoDB proprietaires + enumerations
└── repositories/   acces aux 5 collections                   — a venir
```

## Demarrage

```bash
uv sync                       # cree .venv (Python 3.12) et installe les deps
cp .env.example .env          # renseigner les vraies valeurs
uv run uvicorn app.main:app --reload
```

- Sonde : `GET /health` → `{"status": "ok"}`
- Contrat OpenAPI : `/docs`

## Qualite

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest
```

## Les 5 collections MongoDB proprietaires

Ce sont les **seules** collections ecrites par le Loader. Toute entite FinZuu
(Company, Client, Product, Account, Identity, Kiosque) vit dans son service
amont et n'est jamais dupliquee ici — seuls ses identifiants sont references.

| Collection | Role |
|---|---|
| `faker_consumption_ledger` | Registre de consommation Faker — support de D-FAKER-1 (`_id` = client_id Faker) |
| `lenders_registry` | Le Lender comme **role** porte par une Company (concept inconnu de company-service) |
| `loader_runs` | Etat de simulation : run_id, fenetre 180 j, statut, mode, checkpoints |
| `audit_trail` | SIEM applicatif interne (EF-61 a EF-64) |
| `super_admin_accounts` | Authentification propre au Loader, distincte de user-service |

Definition normative : `app/models/domain.py`, alignee sur le package
« Domaine Loader » de `docs/reference/uml_diagrams/02_class.puml`.

## Les 5 disciplines defensives — NON NEGOCIABLES

Texte de reference : `app/core/disciplines.py`. Chacune neutralise un ecart
empirique **confirme** d'un service amont ; aucune ne releve d'une preference
de style.

1. **D-FAKER-1** — un client_id Faker n'est jamais consomme deux fois ;
   verification contre `faker_consumption_ledger` avant chaque tirage.
2. **D-CMP-2** — la cascade Identity est reelle, la cascade User ne l'est
   pas : l'Admin User est cree explicitement (register → password/f/change → login).
3. **D-DEP-7 (FRA-205)** — depositary-service n'a aucune RBAC reelle : token
   ROOT exclusivement pour toute ecriture.
4. **D-PRD-4 / D-PRD-9** — categorie « Any » splittee en 2 creations
   (INDIVIDUAL + CORPORATE) ; GET avant POST, jamais de duplication ; une
   Policy par Product (reference vivante).
5. **D-COL (montants)** — jamais de montant negatif ou nul vers
   collect-service : rejet HTTP apparent, mutation reelle silencieuse.

## Perimetre du commit initial

Squelette uniquement : demarrage FastAPI, cycle de vie du client MongoDB,
`/health`, modeles des 5 collections, index portant les invariants. Les
paquets `services/`, `clients/` et `repositories/` sont volontairement vides.
