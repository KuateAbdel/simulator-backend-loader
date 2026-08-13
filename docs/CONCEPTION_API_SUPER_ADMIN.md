# Conception — l'API de pilotage du Super-Admin du LOADER

> Écrit le 13/08/2026, à partir de la vision exprimée par Yaniv le même jour,
> du CDC (EF-50 → EF-59, CR-05), de `MODELE_UTILISATEURS.md` et de l'existant.
> C'est le **contrat** que le frontend Next.js de Zidane consommera
> (`10_component.puml`) — le backend l'expose, l'écran ne parle qu'à lui.

---

## 0. Les principes, avant les routes

1. **Deux Super-Admin, aucun rapport entre eux.** Celui du LOADER vit dans
   notre MongoDB (`super_admin_accounts`, bootstrap au premier démarrage,
   `must_change_password=True`). Celui de la PLATEFORME est un groupe RBAC de
   user-service. L'API décrite ici authentifie le premier, jamais le second.
2. **Le Loader est tier-2.** L'écran de Zidane → notre API → les 9 services
   FinZuu. Le frontend n'appelle JAMAIS FinZuu directement : toute écriture
   passe par nos exécuteurs, donc par nos invariants, notre registre, notre
   journal. C'est ce qui rend chaque action de l'admin **disciplinée par
   construction** — l'admin ne peut pas contourner `INV-*` même s'il le veut.
3. **Chaque écriture suit le rite `D-01`** : composer → montrer (DRY_RUN) →
   confirmer explicitement → exécuter (REAL) → relire → recette. Le bouton
   « Run » de l'écran est en réalité DEUX actions : « préparer » (à blanc,
   rapport lisible) puis « confirmer » — parce que trois services n'ont pas
   de DELETE, la confirmation n'est jamais un défaut.
4. **Rien à usage unique.** Le CDC : « outil autonome, réutilisable et
   paramétrable » (§349), « 2000 clients **par exécution** » (§360), « actif
   réutilisable pour tous les futurs environnements » (§378). Chaque run est
   idempotent (CR-03), listable, comparable ; la purge par marqueur permet de
   régénérer à volonté ; la v1 est la première version d'un outil qui évoluera
   avec la plateforme.

## 1. Ce qui EXISTE déjà dans le backend (rien à réinventer)

| Capacité | Où elle vit | État |
|---|---|---|
| Compte Super-Admin Loader + hachage + bootstrap | `services/bootstrap.py`, `repositories/super_admin.py` | ✅ |
| Squelette FastAPI + cycle de vie Mongo + `/health` | `app/main.py`, `routes/health.py` | ✅ |
| Verrou d'exécution (EF-55) | `LoaderRunRepository.dernier_en_cours()` | ✅ préparé |
| Configuration en cascade ville→région→pays→CDC | `core/configuration.py` (CFG-01→04) | ✅ |
| Ajout de villes/valeurs SANS toucher au classeur | `surcouche_referentiel.py`, `AdministrationConfigService` (CFG-05/06) | ✅ |
| Orchestrateur 8 modules + reprise + 20 workers | `services/orchestrateur.py` | ✅ |
| Rapports par module + recette CR-01→12 | `services/recette.py` + rapports | ✅ |
| Registre Faker (write-ahead, réconciliation) | `repositories/faker_ledger.py` | ✅ |
| Journal d'audit des intentions | `audit_trail` | ✅ |
| Référentiels riches (géo, telcos, 576 métiers, 195 pays, revenus) | `geographie.py`, `referentiel_statique.py` | ✅ |

**L'API de pilotage est donc une COUCHE MINCE au-dessus d'un moteur déjà
testé (826 tests)** — pas un nouveau système.

## 2. La surface API — par user story du Super-Admin

### 2.1 Session
- `POST /admin/auth/login` — email + mot de passe → jeton de session Loader.
  Premier login : `must_change_password` force `POST /admin/auth/password`.

### 2.2 Configuration & référentiels (EF-50, EF-51)
- `GET /admin/configuration` — l'état résolu complet (défauts CDC + surcharges).
- `PUT /admin/configuration` — volumes (nb clients, companies, branches,
  agences, kiosques, agents par niveau), pays actifs/inactifs, quotas.
- `GET /admin/referentiels/geographie` — l'arbre pays→régions→villes→quartiers
  (51/50/82), avec GPS — la matière des écrans de sélection.
- `POST /admin/referentiels/villes` — ajout d'une ville (CFG-06 : relecture
  des 9 champs avant écriture ; le classeur n'est jamais modifié).
- `GET /admin/referentiels/telcos` — les 12 plans réels, parts de marché.
- `GET /admin/referentiels/catalogue-statique` — 6 industries, 112 secteurs,
  576 professions, 4 profils de revenu, 195 pays, 20 fonctions (lecture).
- **Ajout d'un PAYS** : exposé mais gardé — `EF-05` borne à 4 pays cibles ;
  un 5ᵉ pays exige sa matière (régions, villes, telcos, patronymes). L'API
  refuse avec un message qui LISTE ce qui manque — refus pédagogique, pas mur.

### 2.3 Runs (EF-52 → EF-56 — le « bouton Run »)
- `POST /admin/runs` `{mode: DRY_RUN}` — prépare et exécute À BLANC ;
  rend le rapport complet (quotas prévus, solde doté, catalogue, écarts).
- `POST /admin/runs/{id}/confirmer` — le passage en REAL, action explicite
  (jamais un défaut) ; refuse si un run est en cours (verrou EF-55).
- `GET /admin/runs/{id}/progression` — temps réel (SSE ou polling) : palier
  en cours, compteurs par pays, erreurs au fil de l'eau.
- `GET /admin/runs` / `GET /admin/runs/{id}` — historique, rapport, recette
  CR-01→12 avec les trois verdicts, journal d'erreurs (EF-56), réconciliation
  Faker (suivi complet : réservé/confirmé/libéré par client Faker).
- `POST /admin/runs/{id}/arreter` — arrêt propre : fin de lot, réconciliation.

### 2.4 Entités à l'unité (la richesse côté Loader)
Le même moteur que les runs, à l'échelle 1 — composer chez nous, montrer,
confirmer, pousser :
- `POST /admin/entites/companies` — formulaire riche (type, pays, ville…) ;
  le Loader complète TOUT le reste (secteur+industrie JJB, forme juridique,
  dirigeant avec fonction et lieu de naissance, licences, adresse GPS) et rend
  l'aperçu ; `/confirmer` exécute la séquence exacte de `S3-03` sur la
  plateforme (company → licences → admin user → comptes).
- `POST /admin/entites/produits` — même rite ; le produit est créé côté
  plateforme avec policy embarquée, taux borné 24 %, marqueur `short_name`,
  protocole à deux clés contre `ANO-PRD-UNIQ-01`.
- (v2 : dépositaires, clients à l'unité — même patron, déjà outillé.)

### 2.5 Dashboard (EF-57/58 — « voir tout l'écosystème »)
- `GET /admin/dashboard` — les comptes vivants : entités par type et par pays,
  quotas mesurés vs cibles, distribution des 4 profils comportementaux
  (CR-09), soldes (médiane, part ≥ 150 000), arbre org_hierarchy navigable,
  état de santé des 9 services FinZuu (le sondage `/health` de chacun).
  Source : NOS collections (l'index que P-01 renforcera), jamais 20 requêtes
  paginées vers FinZuu à chaque affichage.

### 2.6 Purge (EF-59 / EF-65)
- `POST /admin/purge/preparer` — liste ce que le marqueur retrouve
  (`DEMO_` sur les noms, `short_name` sur les produits — CR-07 par type
  d'entité), et dit ce qui n'est PAS purgeable (identity/account/depositary
  sans DELETE : listés, marqués, jamais cachés).
- `POST /admin/purge/confirmer` — exécute ce qui est réversible, rapporte le
  reste. La purge est un RUN comme un autre : journalisée, réconciliée.

## 3. L'ordre d'implémentation (S6, backend)

```
Lot A  auth + configuration + référentiels (lecture)   ── débloque Zidane
Lot B  runs : préparer/confirmer/progression/historique ── le bouton Run
Lot C  dashboard                                        ── lecture de nos collections
Lot D  entités à l'unité (company, produit)             ── réutilise S3-03/S3-05
Lot E  purge par marqueur                               ── EF-65, après CR-07 par type
```

Contrat d'abord : le schéma OpenAPI de chaque lot est publié sur `/docs` dès
le lot A — Zidane maquette sur le contrat, pas sur des promesses.

## 4. Ce que ça garantit (les « n'est-ce pas » de Yaniv, en engagements)

- L'admin **voit tout depuis le Loader** et n'écrit que par lui → chaque
  écriture passe par les invariants, le registre anti-doublon, le journal.
- Le Loader **connaît quoi remplir** : l'admin donne 4 champs, le référentiel
  complète les 40 autres — plus riche chez nous, conforme chez eux.
- **Aucun bug de la plateforme n'est subi** : unicité produits, casse,
  language ignoré, FRA-218… chaque parade vit dans les clients HTTP que
  l'API réutilise.
- **Qualité de service en QA senior** : chaque action rend un rapport relu
  (jamais déduit), la recette juge chaque run, le DRY_RUN précède chaque REAL.
- **Duhamel** : la méthodologie (poids ajustés Annexe D.2, cycle de vie) est
  intégrée dans le moteur (EF-67/68) et sera visible au dashboard (CR-09).
