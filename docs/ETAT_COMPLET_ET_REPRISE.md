# ÉTAT COMPLET & REPRISE — Loader FinZuu (backend + frontend)

> Écrit le 14/08/2026 sur ordre de Yaniv, pour ne RIEN perdre de la session.
> Versionné sur GitHub (survit à l'extinction de la machine). Détaillé, pas
> un résumé. Deux projets : **backend** (déployé, en ligne) et **frontend**
> (en construction). Tout ce qu'il faut pour reprendre est ici.

---

## 0. LES DEUX PROJETS & LEURS EMPLACEMENTS

| Projet | Local | GitHub | Déploiement |
|---|---|---|---|
| **Backend** (Python/FastAPI) | `/home/yann/simulator-backend` | `github.com/KuateAbdel/simulator-backend-loader` | **EN LIGNE** : `https://simul.api.fintech4esg.com` |
| **Frontend** (Vite/React, design JJB) | `/home/yann/simulator-frontend` | `github.com/KuateAbdel/simulator-frontend` | à venir : `https://simul.fintech4esg.com` |

Utilisateur : Kuate Abdel Yaniv (Tech Lead/DevSecOps). Français phonétique.
Discipline exigée : senior/principal engineer Microsoft, SDET, DBA, DevSecOps.

---

## 1. LE SERVEUR (partagé — NE JAMAIS casser les autres services)

- **IP** : `152.53.118.110` (Netcup, Ubuntu 24.04 **ARM64**, 10 vCPU, 16 Go, pas de swap).
- **Accès** : SSH root par mot de passe `GXHYQyKkZf5VmdT` (donné par Yaniv).
  User de déploiement : **`apps`** (groupes sudo+docker), sous `/home/apps/`.
- **Autres projets sur le serveur (À NE PAS TOUCHER)** : ERPNext CRM
  (`crm.finzuu.com`), Nextcloud Talk/Collabora (`signaling/recording/collabora.finzuu.com`),
  Newsletter de Zidane (`news.fintech4esg.com` + `news.api.fintech4esg.com`).
- **nginx est sur le HOST** (systemd, enabled au boot), route par `server_name`.
- **Port 8000 est PRIS** (finzuu-talk-recording). Le Loader backend = **8003**.
- **Réseau docker `loader-net`** pré-créé par Yaniv, adopté (external).
- **Convention domaines** (comme Newsletter) : nu = frontend, `.api` = backend.
- **CRM cert EXPIRÉ depuis 28/07** (cause : renouvellement `standalone` échoue
  car nginx tient le port 80). Pré-existant, PAS notre fait, PAS notre projet.

## 2. BACKEND — ÉTAT : DÉPLOYÉ, EN LIGNE, v0.5.0

### 2.1 Ce qui tourne sur le serveur (vérifié)
- 2 conteneurs `healthy` : `loader-loader-1` (FastAPI, 127.0.0.1:8003→8000),
  `loader-mongo-1` (Mongo 7, volume `loader_loader_mongo_data`, aucun port publié).
- `https://simul.api.fintech4esg.com/health` → 200 `{"status":"ok"}`.
- `/docs` (Swagger) et `/openapi.json` → 200, PUBLICS (pour Zidane).
- Cert Let's Encrypt `simul.api.fintech4esg.com` valide ~89 j, renouvellement
  auto + **hook de reload nginx posé** (`/etc/letsencrypt/renewal-hooks/deploy/`).
- **MongoDB serveur = VIDE** (aucune donnée métier ; 1 seul compte super-admin
  bootstrap). RIEN n'a été RUN — décision Yaniv : on ne lance aucun palier.

### 2.2 Le code backend (957 tests verts, ruff+mypy propres)
- API Super-Admin ENTIÈRE (lots A→H) : auth JWT + mot de passe forcé, config
  verrouillée EF-55, référentiels (villes, **régions/quartiers sans limite**,
  telcos, permissions), **création pays** (`POST /admin/referentiels/pays`),
  **création monnaie** (`POST /admin/referentiels/devises`), entités à l'unité
  (company/produit/groupe), runs pilotés (rite D-01), dashboard (santé 10
  services, population US-E3, index inverse P-01), purge honnête.
- **Réconciliation ici↔là-bas** : 4 statuts (à_nous/disparu_la_bas/
  marque_mais_inconnu/etranger), DELETE groupe gardé, **adoption A-13**.
- Registres dérivés du journal write-ahead + `lenders_registry` ; index
  structurel `(entity_type, action)`.
- P-01 (index inverse), moteur unifié CLI+API (`pilotage.py`).
- Référentiels statiques JJB (SD-1→6), catalogue CAT 1→11, perimetre_lending.
- `uuid_stable` (id serveur sans format garanti), CORS non applicable backend.

### 2.3 Faits mesurés (recon serveur, lecture seule)
- Les **11 rôles D-09 EXISTENT DÉJÀ** sur user-service (notre empreinte
  antérieure) → à ADOPTER (A-13) sur l'instance hébergée.
- **6 pays** sur config-service (`ca` minuscule hors-ISO + CV en plus des 4
  cibles CM/CI/BF/SN). **5 devises**. **15 telcos** (dont PROBE_TELCO_0317).
- **ANO-PRD-UNIQ-01 CONFIRMÉE** : « Cotisation 20000/mois » en DOUBLE.
- **Auth CENTRALISÉE prouvée** : un token user-service marche sur product/
  company/depositary (200). Le Loader fait UN login ROOT partagé (D-DEP-7).
- config-service EXPOSE `POST /countries/create` et `/currencies/create`
  (c'est ainsi que les 4 pays ont été créés — réf loader-config-service).
- config-service N'A PAS de régions/quartiers (404) → notre richesse reste
  chez nous.

### 2.4 CI/CD backend (fonctionnel, prouvé)
- CI : ruff + mypy strict + 957 tests contre MongoDB de service, sur push/PR.
- CD : après CI verte → SSH `apps@serveur` (clé dédiée), `git merge --ff-only`,
  `docker compose up -d --build` (ARM64 natif), santé /health vérifiée.
- Secrets GitHub posés : `DEPLOY_HOST/USER/SSH_KEY/KNOWN_HOSTS` + var
  `DEPLOY_PATH=/home/apps/loader`. Clé dédiée `github-actions-deploy-loader`
  autorisée pour `apps`. `workflow_dispatch` pour redéploiement manuel.
- Fichiers : `Dockerfile` (python:3.12-slim, PAS ghcr — creds ghcr périmés sur
  le serveur), `.dockerignore` (liste blanche), `docker-compose.yml` (8003,
  loader-net), `.github/workflows/{ci,deploy}.yml`, `docs/DEPLOIEMENT.md`,
  `deploy/nginx/simul-api.conf`, `deploy/letsencrypt/reload-nginx.sh`.
- Version : v0.5.0 taggée + Release GitHub. Branche main protégée.

## 3. FRONTEND — ÉTAT : FONDATION EN COURS

### 3.1 Décisions prises
- **Base = design de JJB** (zip `finzuu-dashobar-simulteur.zip`, projet Vite/
  React 18, PAS le PowerPoint). Le scaffold Next.js de Zidane est ABANDONNÉ
  (il était 100% mock, 0 appel backend, 0% fonctionnel — mesuré).
- **Design system JJB** : violet `#c68cff`/`#a855f7` + vert `#19af58`, surface
  `#faf7ff`, polices Sora/DM Sans/JetBrains Mono, radius 12px, composants
  (Card, SectionHeader, StatusBadge, TabBar, EmptyState), charts recharts,
  i18n FR/EN (`t()`, `translations`), sidebar sombre repliable.
- **On garde de JJB le design system, on JETTE ses pages fintech** (Overview
  clients, Lender, Analytics, Onboarding, Bulk — c'est l'app plateforme, pas
  l'admin Loader). On s'inspire de sa page BackOffice (patterns admin).
- **IA = les 6 épopées du backlog canonique** (Confluence 67665922 /
  `docs/BACKLOG_SUPER_ADMIN.md`), pas improvisée.
- **Principe : le Loader est PLUS RICHE** — l'UI montre l'arbre géo complet,
  la réconciliation 4 statuts, le « ce qui part / ce qui reste ».
- **Repo séparé** (pas un dossier du backend).
- **Bilingue FR/EN** (exigence JJB).
- **Déploiement** : build statique servi par nginx sur `simul.fintech4esg.com`.

### 3.2 Ce qui est DÉJÀ fait
- Repo créé, base JJB adoptée dans le dépôt.
- `src/lib/api.ts` : client API réel (VITE_API_URL=simul.api.fintech4esg.com,
  JWT Bearer, ApiError nommée, panne réseau dite). — À reporter proprement.
- `docs/PLAN_FRONTEND.md` + `docs/CONCEPTION_UX_UI.md` (conception détaillée :
  14 écrans, design system + composants à ajouter, QA/invariants d'interface/
  responsive, 8 phases).

### 3.3 Ce qui RESTE à faire (frontend) — les 8 phases
1. **Fondation** : design system adapté, garde d'auth, i18n Loader, layout +
   nav des 6 épopées (réécrire AppContext sans le fintech, Sidebar, types).
2. **Tableau de bord** (US-E1, santé 10 services) + **Configuration** (US-B1/2/3).
3. **Runs** — le rite D-01 (US-C1→C6) : préparer/confirmer/progression/arrêt/
   historique+recette. Le cœur.
4. **Référentiels** : géographie (arbre riche) + créations pays/monnaie/telco/
   région/ville/quartier (avec CountrySelect ISO, hiérarchie EF-02 imposée).
5. **Entités** (US-D1 company aperçu→confirmer, US-D2 produit 3 policy_types).
6. **Écosystème** (US-E2 arbre) + **Population** (US-E3 dataviz recharts).
7. **Inventaire** (réconciliation 4 statuts + adoption A-13) + **Traçabilité**
   (US-E4) + **Purge** (US-F1/F2 rite 2 temps).
8. **Polish** : responsive (360→1920px), a11y (AA, clavier), états vides,
   tests composants (Vitest), EN complet, CI/CD + déploiement.
- **Composants à créer** (langage JJB) : KpiCard, StatutPill (4 statuts),
  HealthDot, Stepper, DataTable, Tree, CountrySelect, Toast, ConfirmDialog,
  FormField/Select/NumberField.
- **QA/invariants d'interface** : hiérarchie « rien en l'air » (ville désactivée
  sans région), formats (ISO, MSISDN, regex ancrée, parts ≤ 100), verrou EF-55
  en lecture seule, le backend reste l'AUTORITÉ (l'UI double, l'erreur nommée
  s'affiche), TS strict, Error Boundary, 4 états par appel, idempotence UI.

## 4. TÂCHES RESTANTES BACKEND (rien de bloquant sauf arbitrages)

Développement backend COMPLET sauf le module VIE. Il reste :
- **#16 Module VIE (palier 7, EF-67→80)** : 180 jours de collectes/retraits +
  re-scoring Duhamel + P-02 (plafonds KYC) + P-03 (float agent). **BLOQUÉ sur
  3 arbitrages Yaniv** : **A-07** (proportions des 4 profils comportementaux),
  **A-11** (part APPROVED/DECLINED), **A-04** (persistance des prêts — ou
  simplement « VIE MEP1 = collecte seulement, sans crédit »). Dès ces réponses,
  je développe VIE avec le protocole (tests, mutations).
- **#24 A-05** (permissions exactes des 11 rôles) — validation sur pièce, avant
  le palier 5 REAL.
- **EXÉCUTION (après hébergement, sur GO de Yaniv, palier par palier)** :
  paliers REAL 1→6 (rôles→orga→catalogue→dépositaires→staff→clients), second
  run CR-03 (idempotence), recette finale CR-01→12 → v1.0.0. **Ordre** :
  santé E1 → login → **adoption A-13 des 11 rôles** → DRY_RUN depuis le serveur
  → paliers REAL. RIEN ne tourne sans décision explicite de Yaniv.
- **#26** : ajout de PAYS/monnaie = FAIT (14/08). Reste éventuel : formulaire
  guidé côté frontend.

## 5. DÉCISIONS CLÉS (à ne pas ré-litiger)
- Backend uniquement pour le Loader d'origine ; frontend repris car Zidane a
  échoué (mission du boss, 14/08).
- Héberger AVANT de charger (C-0). Machine locale = dev seulement.
- Produits COLLECT seulement (pas de LENDING, sprint 8). Noms réels, marqueur
  dans `short_name`.
- Le Loader = autorité d'unicité (la plateforme n'en a aucune). GET-avant-POST
  partout. NO TRUST in a service. Le Loader compose/envoie/relit/trace.
- Anti-corruption : référentiels riches internes, contrats minimaux aux serveurs.
- Créer un pays le DÉCLARE sur config-service ; ne l'ajoute PAS à la génération
  (EF-05 reste 4 pays).
- Tableau de bord vivant : `docs/TABLEAU_DE_BORD.md` (backend).

## 6. COMMENT REPRENDRE
1. Backend : `git pull` dans `/home/yann/simulator-backend`, `.venv` prêt,
   `.venv/bin/python -m pytest tests/ -q` (957 verts attendus). Mongo local :
   voir mémoire `mongodb-local-sans-sudo`.
2. Frontend : `git pull` dans `/home/yann/simulator-frontend`, lire
   `docs/CONCEPTION_UX_UI.md`, reprendre la **phase 1** (fondation).
3. Serveur : SSH root (mdp ci-dessus) ou `apps` (clé de déploiement dans les
   secrets GitHub). Conteneurs : `docker compose ps` sous `/home/apps/loader`.
4. Le CI/CD déploie tout push vert automatiquement (backend). Frontend : CI/CD
   à poser en phase 8.
