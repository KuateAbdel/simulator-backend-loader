# Tableau de bord — l'état vivant du backlog

> Reconstruit le 13/08/2026 depuis les plans commités (`PLAN.md`,
> `PLAN_SPRINTS.md`, `PLAN_INTEGRATION_STATIC_DATA.md`,
> `CONCEPTION_CATALOGUE_ET_SOUSCRIPTION.md`, `ORCHESTRATION.md`).
> **Ce fichier est mis à jour à chaque tâche fermée** — c'est lui qui survit aux
> sessions, pas la liste de tâches de l'outil.
>
> Le Loader n'est pas un script : c'est le **backend de pilotage** de la
> plateforme. La cible est v1.0.0 — 2000 clients en 30 minutes, recette
> CR-01→CR-12 tenue, piloté par le Super-Admin sans assistance (CR-05).

## A. Chantier « référentiels statiques de JJB » — 6 lots

| # | Tâche | État |
|---|---|---|
| SD-1 | Chargeur `referentiel_statique.py` (6/112/27/576/21/4/195/20) | ✅ `345171c` |
| SD-2 | Companies : `industries` ≠ `sectors`, Fondation servie, 27 formes | ✅ `7f78fca` |
| SD-3 | Occupations : 18 → 576, règle `bank_stable`, EF-24 visible | ✅ `a2646ba` |
| SD-4 | Dirigeants : « Dirigeant » → 20 fonctions | ✅ `7f78fca` |
| SD-5 | `solde_initial` : heuristique → LogNormal(μ,σ) par profession, borné Annexe E, mesure EF-68 refaite — **A-09 FERMÉ** | ✅ 13/08 |
| SD-6 | Lieu de naissance : 195 pays + 50 villes, `id_place` ≠ résidence *(ancienne tâche #15)* | ✅ 13/08 |
| — | Bilan de chantier ultra-détaillé des 6 lots | ⬜ |

## B. Chantier « catalogue » — les 11 changements du §8

| # | Tâche | État |
|---|---|---|
| CAT 1-2 | **Décidé par Yaniv le 13/08** : produits RÉELS et recherchés — `Tontine Digitale` · `Compte Epargne Entreprise` · `Epargne Bloquee 6 Mois` · `Depot a Terme Entreprise 12 Mois` · `Warrantage Cerealier` · `Collecte Cacao Cooperative` (conception §4 : PAMECAS, warrantage sahélien). Marqueur `DEMO_` dans `short_name`, protocole à deux clés contre `ANO-PRD-UNIQ-01` | ✅ 13/08 |
| CAT 3-5 | Produits environnement constatés · 12 créations | ✅ (12/08, `c53c05d`) |
| CAT 6 | CR-07 par type d'entité | ✅ 13/08 — **par construction** : le nœud PRODUIT porte le MARQUEUR comme `name`, CR-07 vérifie les préfixes sans modification |
| CAT 7-8 | Rattachement Produit→Company + panier de SA Company *(ancienne #29 / A-12)* | ✅ 13/08 — niveau PRODUIT (nœud RACINE, liens n:n, ZÉRO produit créé : 6 produits × 8 porteuses = 48 liens), CR-02 les vérifie, panier STRICT dès que la carte existe (Company hors carte → refus dit), DRY fidèle (ancres planifiées empruntent les companies du rattachement) |
| CAT 9-11 | `perimetre_lending` · `PRODUITS_ATTENDUS` fonction du périmètre · recette « hors périmètre » | ⬜ |

## C-0. DÉCISION du 13/08 (Yaniv) — HÉBERGER AVANT DE CHARGER

Le Loader est déployé sur `simul.api.fintech4esg.com` AVANT tout palier REAL.
Raison de fond : la MongoDB du Loader (registre Faker, org_hierarchy, runs,
configuration) est SA MÉMOIRE — charger depuis la machine de dev puis héberger
donnerait une instance vierge, amputée du registre qui rend CR-03, la reprise,
le dashboard et la purge possibles. La machine locale = développement
uniquement. Protocole chirurgical : déployer → brancher les 9 services (.env)
→ sonde E1 verte sur les 10 → DRY_RUN complet DEPUIS le serveur → paliers.

## C. La séquence REAL — l'ordre topologique d'ORCHESTRATION.md

| Palier | Tâche | État |
|---|---|---|
| 1 | Rôles : 11 `group_id` (seul module réversible) | ⬜ |
| 2 | Organisation : 16 Lenders, licences, Admin Users, 4 comptes (S3-03) | ⏸ paliers 1 + décisions catalogue |
| 3 | Catalogue : 12 créations, noms réels, marqueur `short_name` | ⬜ |
| 4 | Dépositaires : 40-80 nœuds, Agents (S3-06) | ⬜ |
| 5 | Staff & Agents : 60-100 users, 11 rôles | ⏸ **A-05** |
| 6 | Clients : 2000, quotas, EF-26 deux temps | ⬜ SD-3 ✅ prêt |
| — | Second run REAL identique — preuve CR-03 | ⬜ |
| 7 | Vie 180 jours + crédit (EF-67→80) | ⏸ **A-07, A-11, A-04** |
| 8 | Recette : CR-01→12 tous TENUS + mesure 30 min → **v1.0.0** | ⬜ |

## D. Super-Admin — étape 8 du PLAN, Sprint 6

| Tâche | État |
|---|---|
| Routes de pilotage EF-50→EF-59 — conception + backlog canonique (page Confluence 67665922). **Lot A LIVRÉ le 13/08** (sauf US-B4) : auth US-A1/A2/A4 + référentiels lecture US-B5 + configuration US-B1/B2/B3 (vue résolue avec origines, volumes bornés, quotas EF-22/23 verrouillés, verrou EF-55 en 409, pays activables — jamais config-service). **LOTS A ET B COMPLETS (13/08 soir)** : lot A entier + lot B — moteur extrait dans `pilotage.py` (UN moteur CLI+API, identité prouvée au centime), runs pilotés par l'API : préparer (DRY seul, rite D-01 structurel), confirmer (périmètre FIGÉ, 409 si config changée), progression, arrêt v1, historique append-only (DELETE→405), rapport rangé avec le run. **Lot C livré (13/08 nuit)** : dashboard E1 (santé 9 services+Faker, compteurs, alertes), E2 (arbre navigable org_hierarchy), E4 (traçabilité+réconciliation) + **E3 livré** : le moteur range ses mesures structurées avec le run (occupations, tranches de soldes avec frontière 150 000/EF-68, naissances, quotas mesure/cible), servies par GET /admin/dashboard/population. **LOT C COMPLET.** **Lot D : US-D2 livré** (produit à l'unité — aperçu/confirmer, 3 interfaces par policy_type, double clé d'unicité, registre interne, write-ahead sentinelle RUN_ADMIN, fiche relue). **US-D1 livré aussi** (company à l'unité : 3 champs saisis → ~40 composés, territoire résolu avec refus pédagogique, ancre sha256 inter-processus, séquence S3-03 réutilisée). **LOT D COMPLET. LOT E LIVRÉ (purge honnête : groupes supprimables + carte des résidus avec verdicts D-DEP-3/D-DEP-8, verrou EF-55, journal DELETE sous RUN_ADMIN). L'API SUPER-ADMIN v1 EST ENTIÈRE — lots A à E, 20 stories, 62 tests d'API.** | 🟡 en cours |
| Purge par préfixe `DEMO_` + verrou d'exécution (EF-65/66) | ⬜ |
| **LOT G — INVENTAIRE/RÉCONCILIATION (13/08 nuit, vision Yaniv « NOS données là-bas, avec NOS statuts »)** : `app/services/inventaire.py` — 4 statuts par croisement registre × plateforme (`a_nous` / `disparu_la_bas` / `marque_mais_inconnu` / `etranger`), servis par GET /admin/inventaire/{groupes,produits,companies} + **DELETE individuel d'un groupe À NOUS** (403 étranger, 404 inconnu, 409 sous run, 502 si panne OU si le serveur répond sans agir — relecture obligatoire, journal write-ahead sous RUN_ADMIN). **DÉCISION Yaniv : AUCUN préfixe sur les groupes, jamais** — les noms de rôles sont fonctionnels ; la reconnaissance des groupes est PAR REGISTRE (journal). **TROU FERMÉ** : `ExecuteurRoles` ne journalisait pas ses créations (seule écriture non tracée du moteur) → chaque groupe créé en REAL inscrit désormais son `group_id` serveur au registre en write-ahead ; la purge, qui filtrait sur `DEMO_` et n'aurait JAMAIS rien trouvé, reconnaît maintenant par registre. Registres : groupes=journal, produits=journal∪`produits_admin`, companies=`lenders_registry`. 920 tests (+11), 4 mutations attrapées, DRY_RUN 2000 propre. | ✅ |

## D-bis. Configuration avancée (#26) — TELCO livré 13/08

US-B7 ✅ : ajout de telco par l'API — **l'ALLER COMPLET** (surcouche locale
PUIS config-service : création GET-avant-POST + rattachement au pays par
relecture 9 champs), 4 invariants (unicité CROISÉE nom/code, regex compilable
ET composable avec preuve `exemple_msisdn`, somme des parts ≤ 100 = INV-18 à
l'écriture), échec d'envoi jamais silencieux (le local reste + motif),
journalisé sous RUN_ADMIN. La VILLE (US-B4) fait aussi l'aller complet.
Reste de #26 : ajout de PAYS complet (formulaire guidé) — v2.

## E. Backlog S4/S5 restant

| Tâche | État |
|---|---|
| INV-18 — MSISDN pondérés par parts de marché | ✅ 13/08 — le mécanisme existait (EF-27), la GARANTIE mesurée manquait : 4 tests de distribution (CM ±3 pts sur 46/43/3, les 4 pays ±3,5 pts, anti-uniforme, ancrage CR-03), mutation « tirage uniforme » attrapée |
| P-01 — index inverse (client→produit, client→kiosque) | ⬜ |
| P-02 — plafonds KYC BCEAO | ⬜ s'écrit AVEC le module Vie |
| P-03 — float de l'agent | ⬜ s'écrit AVEC le module Vie |

## F. Les arbitrages qui n'appartiennent qu'à Yaniv

`A-05` (permissions 11 rôles) · `A-07` (profils comportementaux) · `A-11`
(proportion APPROVED/DECLINED) · `A-04` (persistance des prêts) · `A-08`
(désactiver un pays) · noms métier du catalogue + marqueur `short_name` ·
Agents compris ou en sus des 15-25 staff/pays. Recommandations écrites dans
`PLAN_SPRINTS.md` §3.4 et `A-05_PERMISSIONS_A_TRANCHER.md`.
