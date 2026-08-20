# Changelog — Loader FinZuu (backend)

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ·
Versionnage : [SemVer](https://semver.org/lang/fr/), règle du
`docs/PLAN_SPRINTS.md` §5 — un numéro n'est posé que sur un incrément dont la
définition de terminé est atteinte, jamais sur une intention.
`1.0.0` = première livraison couvrant la recette `CR-01` → `CR-12`.

## [0.6.0] — 2026-08-20

**L'API d'administration devient multi-comptes, gouvernée et traçante** —
tout ce qui a suivi la v0.5.0 hébergée : RBAC, audit, notifications.

### Ajouté
- **RBAC 3 rôles** (viewer / admin / super_admin) : rôle porté par le JWT,
  gardes `exige_admin` / `exige_super_admin` appliquées à TOUTES les
  écritures (matrice FZ-RBAC-LOADER, prouvée par `TestMatriceRBAC`) ;
  comptes multi-personnes (création avec rôle fail-closed viewer,
  changement de rôle, désactivation motivée réversible, anti-lock-out).
- **Journal d'administration** : `GET /admin/journal` (qui a fait quoi,
  quand — intentions sous RUN_ADMIN, Super-Admin seulement) + **traçabilité
  des connexions** (`derniere_connexion` posée au login, ligne
  `Session/LOGIN` au Journal ; tracer ne bloque jamais le login).
- **Système de notification** (doctrine événement → destinataires par RÔLE →
  canaux) : in-app (`GET/PUT /admin/notifications`, chacun ne voit que les
  siennes) + email pour les gestes sensibles ; 4 événements
  (compte_cree, role_change, compte_desactive, compte_reactive) — informer
  ne casse jamais l'action.
- **US-A4 v2 opérationnelle en prod** : reset par email via le relais SMTP
  Mailjet (port 2525, replis 587 puis API) ; **le CD provisionne les
  secrets `MAILJET_*` du serveur** à chaque déploiement (empreinte sha256
  au log — plus de dérive secrets/serveur).
- Créations à l'unité : company US-D1 avec licence UC-07, dépositaire
  US-D3 (quartier + company à nous), diff payload↔relecture sur les 4
  créations ; US-B6 (refus pédagogique pays), Lot H (régions/quartiers
  sans limite, groupes à l'unité, permissions vivantes).

### Sécurité
- I-AUTH-9 (politique de mot de passe) · I-AUTH-11 (anti-brute-force à
  double clé identifiant+IP, sans verrouillage de compte) · 401/202
  anti-énumération partout · fix d'escalade (rôle REPORTÉ au changement de
  mot de passe et au reset — jamais de retombée sur le défaut super_admin).

1 038 tests (990 à la v0.5.0 → +90), mutations attrapées à chaque lot.

## [0.5.0] — 2026-08-14

Le CODE de tous les modules jusqu'à la Population client est complet et
prouvé (DRY_RUN 2000 de bout en bout, 948 tests, mutations attrapées à
chaque lot). Premier tag du dépôt — les jalons antérieurs sont documentés
ci-dessous mais n'avaient pas été taggés à l'époque, dit honnêtement.

### Ajouté
- **API Super-Admin entière** (lots A→H) : auth JWT + mot de passe forcé,
  configuration verrouillée (EF-55 structurel), référentiels (villes,
  **régions/quartiers sans limite**, telcos aller complet, permissions,
  demande de pays US-B6), entités à l'unité (company ~40 champs composés,
  produit 3 interfaces, **groupe** avec unicité chez nous), runs pilotés par
  l'API (rite D-01 : préparer → confirmer sur empreinte figée), dashboard
  (santé 10 sondes, population US-E3, traçabilité, **index inverse P-01**),
  purge honnête.
- **Réconciliation ici↔là-bas** : 4 statuts (`a_nous`/`disparu_la_bas`/
  `marque_mais_inconnu`/`etranger`) par croisement registre × plateforme ;
  DELETE individuel gardé ; **adoption A-13** des 11 rôles préexistants.
- **Registres dérivés du journal** write-ahead (groupes, produits) +
  `lenders_registry` (companies) ; index structurel `(entity_type, action)`.
- **P-01** : lien client→produit écrit À L'ÉCRITURE, servi en 2 agrégations.
- **Référentiels statiques JJB** (SD-1→6) : 576 professions, LogNormal par
  métier (SD-5), lieux de naissance (SD-6), industries≠secteurs, dirigeants.
- **Catalogue CAT 1→11** : noms réels (marqueur dans `short_name`),
  rattachement Produit→Company (A-12, liens n:n + index unique),
  `perimetre_lending` dans l'empreinte, verdict HORS_PERIMETRE.
- **Chaîne CI/CD** : CI (ruff/mypy/tests + MongoDB de service) ; CD SSH vers
  le serveur ARM64 après CI verte, santé vérifiée ; Dockerfile non-root,
  `.dockerignore` liste blanche (les tests ne sont JAMAIS déployés) ;
  compose avec la MongoDB-mémoire en volume non exposé.

### Corrigé (défauts réels attrapés par les portes)
- `_toutes_regions` ignorait la surcouche : doublon de région écrasé en
  silence.
- `ExecuteurRoles` ne journalisait pas ses créations : groupes invisibles à
  la réconciliation, purge aveugle (filtrait un préfixe qui n'existe pas).
- Identifiants serveur sans format garanti : DELETE insupprimable sur id
  legacy, trace de purge avalée — `uuid_stable` partout (QA-UUID).

### Mesuré (recon passive du 14/08 — lectures seules)
- Les 11 rôles D-09 déjà en base (notre écriture antérieure) → adoption.
- 6 pays (dont `ca` hors ISO), doublon produit vivant (ANO-PRD-UNIQ-01),
  61 permissions filtrées (compte exact D-07), réseau dev disqualifié
  (4-6 s/health) → C-0 « héberger avant de charger » validée par la mesure.

## [0.4.0] — jalon (non taggé à l'époque)
Organisation (16 Lenders, licences, EF-13 vérifié en écriture), Catalogue,
Dépositaires (arbre Branche→Agence→Kiosque→Agent, D-05/D-11, index uniques
par portée métier), moteur unifié CLI+API (`pilotage.py`, AU-5).

## [0.3.0] — jalon (non taggé à l'époque)
Module Utilisateurs : 11 rôles D-09 (+ CUSTOMER réutilisé), permissions par
domaine (proposition A-05), la seule écriture réversible de l'écosystème.

## [0.2.0] — jalon (non taggé à l'époque)
Invariants et cohérence humaine : journal d'intention write-ahead, registre
Faker D-FAKER-1, ancres CR-03 (sha256/uuid5, jamais `hash()`), verrou EF-55
structurel.

## [0.1.0] — jalon (non taggé à l'époque)
Socle : FastAPI + motor, 6 repositories, bootstrap Super-Admin, référentiel
géographique 51/50/82, 9 services sondés, 8 clients HTTP, 11 anomalies
ticketées.
