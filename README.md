# simulator-backend — Loader FinZuu (backend)

## Ce qu'est le Loader

> **Le Loader FinZuu est un orchestrateur HTTP qui fabrique un ecosysteme de
> demonstration coherent dans la plateforme FinZuu, en consommant une source de
> donnees et neuf microservices qu'il ne controle pas et dont plusieurs sont
> defaillants.**

Il ne porte **aucune logique metier propre**. Il n'invente rien : il **compose**,
a partir de matiere reelle, ce que ses sources ne fournissent pas — et il refuse
d'emettre ce qu'un banquier jugerait absurde, meme quand le serveur l'accepte.

### Pourquoi il existe

Le CDC v1.2 le dit sans detour : *« les environnements TEST et DEMO ne disposent
d'aucun jeu de donnees representatif. Cette absence bloque trois activites
strategiques : les demonstrations commerciales aupres des prospects
institutionnels (Nordic Microfinance, IFC, AFD, BAD), la validation qualite du
Module Pret, et la formation des utilisateurs finaux. »*

**C'est la premiere de ces trois activites qui commande tout le reste.** Ces
bailleurs connaissent le terrain africain reel. Un jeu de donnees qui ne tient
pas la route devant eux ne sert a rien — il vaudrait mieux ne rien montrer.

### Ce qu'il produit

Un ecosysteme complet sur **4 pays** (CM, CI, BF, SN) et **180 jours** :
**12 a 20 Companies** · **12 Lenders locaux + 4 institutionnels** avec leurs
4 comptes chacun · **40 a 80 Kiosques-Depositaires** ancres dans des quartiers
reels · **60 a 100 personnels** · **2 000 clients** repartis a parts egales, avec
leurs comptes, leurs souscriptions et leur vie financiere.

Le tout **reversible par prefixe** `DEMO_`, **reproductible** a partir d'un
`run_id` et de sa configuration, et **mis a disposition en moins de 30 minutes**.

### Ce qu'il n'est pas

| Il ne fait **jamais** | Pourquoi |
|---|---|
| ecrire directement en base | Tier 2 : il consomme les API, comme n'importe quel client. Ecrire en base court-circuiterait la validation metier et corromprait les invariants |
| passer par Kafka | `ENF-16` l'interdit. De la methodologie du referent loan-simulation on reprend **les fonctions et les profils**, jamais le transport |
| appeler ReadyScore | `EF-80` : les decisions viennent des payloads Faker. Un environnement de TEST ne depend pas d'un service de PRODUCTION |
| calculer un indicateur PAR/DPD | Retire du CDC v1.2 — c'est ReadyScore qui les produit |
| reparer un defaut serveur | Ce n'est pas son role ; c'est celui de l'equipe qui tient le service |
| supprimer quoi que ce soit dans un referentiel partage | Il signale, il ne purge pas |

### Ce qui le rend particulier

Il applique le motif **Anti-Corruption Layer** (Eric Evans, *Domain-Driven
Design*, 2003) :

> **Conformiste sur le transport, anti-corruption sur le modele.**

Il respecte scrupuleusement les contrats HTTP, jusque dans leurs bizarreries —
`POST /identities/create`, `/api/v1/groupes/` en francais, `identity.phone`
strictement egal a `msisdn`. Mais il **refuse d'adopter le modele de donnees
defaillant** que ces contrats vehiculent : un genre libre, une devise hors zone
monetaire, un client de deux ans restent refuses meme quand le serveur les
accepte.

Sa base propre n'est pas une copie du serveur : elle est le **System of Record**
de tout ce que le serveur ne sait pas exprimer — la geographie fine (51 regions,
50 villes, 82 quartiers avec leur type de zone), la zone monetaire d'un pays, le
client Faker consomme, et les ecritures dont on ignore si elles ont abouti.

Il est **rigide a l'execution et souple a la conception** : il echoue
bruyamment sur l'inconnu, et n'evolue que par decision documentee. C'est cette
rigidite qui lui a permis de reveler **onze defauts** du systeme avant meme sa
premiere execution complete.

> Doctrine complete : [`docs/DOCTRINE.md`](docs/DOCTRINE.md)

---

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
