# Plan de couverture du CDC — Loader FinZuu

**Le CDC v1.2 (FZ-CDC-LOADER-2026-001) est le besoin fonctionnel de la Direction
Technique. Tout ce qu'il spécifie doit être livré.** Ce document est la carte qui
le prouve : chaque exigence, son état, et l'étape qui la porte.

Il se lit dans les deux sens — d'une exigence vers le code, et du code vers
l'exigence. Une exigence sans ligne ici est une exigence oubliée.

| Légende | |
|---|---|
| ✅ | Livré et vérifié |
| 🟡 | Partiel — le socle existe, l'exécution manque |
| ⬜ | À faire |
| 🔴 | Bloqué par un arbitrage (voir `DECISIONS.md`) |
| 🔵 | Frontend — périmètre Zidane |

---

## 1. Objectifs (OBJ-01 → OBJ-06)

| Réf | Objectif | Cible | État |
|---|---|---|---|
| OBJ-01 | Référentiel géographique complet | 51 régions, 50 villes, 82 quartiers | ✅ chargé et validé, 0 orphelin |
| OBJ-02 | Population diversifiée | 2000 clients, 4 pays | 🔴 **A-01** — Faker ne sert que 3 pays |
| OBJ-03 | Lenders réalistes | 12 locaux + 4 institutionnels | 🟡 modèle et registre prêts, création à écrire |
| OBJ-04 | Mise à disposition < 30 min | ENF-01 | ⬜ non mesurable avant l'orchestration complète |
| OBJ-05 | Réversibilité par préfixe | `DEMO_` | 🟡 préfixe figé (`cdc.py`) ; l'outil de purge reste à écrire |
| OBJ-06 | Utilisable par un non-technicien | Interface graphique | 🔵 Zidane + nos routes de pilotage |

---

## 2. Exigences fonctionnelles — 73 au total

### 2.1 Module Géographie — EF-01 → EF-06 · **6 / 6** ✅

| Réf | Exigence | État | Où |
|---|---|---|---|
| EF-01 | Charger le référentiel `Loader_Base` | ✅ | `services/geographie.py` |
| EF-02 | Valider l'intégrité référentielle | ✅ testé | `charger_referentiel()`, `rapport.orphelins` |
| EF-03 | Associer les **coordonnées GPS** à chaque niveau | ✅ testé | `City.latitude/longitude/population` — 50/50 villes ; absent reste `None`, jamais `0.0` |
| EF-04 | Extension à un nouveau pays sans code | ✅ | piloté par fichier |
| EF-05 | Rejeter tout pays hors référentiel | ✅ | `PAYS_CIBLES` + `ConfigServiceClient.verifier()` |
| EF-06 | Rapport de couverture en début d'exécution | ✅ | `RapportGeographique.resume()` |

### 2.2 Module Organisation — EF-10 → EF-19 · **2 / 10**

| Réf | Exigence | État | Note |
|---|---|---|---|
| EF-10 | Companies par pays, distribution des types configurable | 🟡 | planifié, création à écrire |
| EF-11 | Rattacher chaque Company à une Region | 🟡 | plan géographique prêt |
| EF-12 | 3 Lenders locaux/pays + 4 institutionnels | ⬜ | `LENDERS_INSTITUTIONNELS` figé |
| EF-13 | 4 comptes financiers par Lender | ⬜ | mécanisme tranché (**D-01**) : 4 POST explicites |
| EF-14 | Branches par IMF, rattachées à une Region | 🟡 | `PlanBranche` |
| EF-15 | Agences par Branche, rattachées à une Ville | 🟡 | `PlanAgence` |
| EF-16 | Kiosques par Agence, rattachés à un District | 🟡 | `PlanKiosque` |
| EF-17 | Agents par Kiosque | ⬜ | dépend du module Utilisateurs |
| EF-18 | **Rejeter et journaliser toute violation d'emboîtement** | ✅ testé | `planifier()` + `verifier_cr02()` |
| EF-19 | Niveau de rattachement du Lender configurable *(S)* | — | **sans objet** : CO-01 tranché, le Lender est porté par la Company |

### 2.3 Module Identités et Clients — EF-20 → EF-29 · **0 / 10**

| Réf | Exigence | État | Note |
|---|---|---|---|
| EF-20 | Payloads clients complets via Faker | 🟡 | famille A ne fournit ni date de naissance, ni adresse, ni occupation, ni email — **`generateur.py` les compose désormais** |
| EF-21 | Vérifier le pays retourné | ⬜ | |
| EF-22 | 60 % de moins de 25 ans, **2 femmes pour 1 homme** | 🟡 | **aucun paramètre `sex`** chez Faker. L'âge est piloté par `generateur.identite(jeune=…)` ; le quota de genre reste à orchestrer |
| EF-23 | 80 % Individual / 20 % Corporate | ⬜ | quota à forcer (`repartition_clients()`) |
| EF-24 | 20 % des professionnels en agriculture | ⬜ | `sector_assignments` exploitable |
| EF-25 | Unicité des MSISDN | ⬜ | |
| EF-26 | Rattacher chaque client à un Kiosque du pays | ⬜ | `org_hierarchy` le permet |
| EF-27 | Valider le MSISDN contre le regex de l'opérateur | ⬜ | telcos lus en Phase 1 |
| EF-28 | Segment de scoring configurable *(S)* | ⬜ | |
| EF-29 | Timeouts Faker : retry avec repli *(S)* | 🟡 | `base.py` le fait pour FinZuu, pas encore pour Faker |

### 2.4 Module Prêt et Historique — EF-30 → EF-38 · **0 / 9**

Tous ⬜ ou 🔴. `EF-36` (injection via loan-service) est **hors périmètre v1.0.0** —
`CT-02`, le service n'est pas livré. `EF-35` (plafond d'usure 24 %) est déjà figé
dans `cdc.py`, et le fichier source contient 25 % : **borne obligatoire côté Loader**.

### 2.5 Module Cadence opérationnelle — EF-40 → EF-48 · **0 / 9**

Tous ⬜. Constantes figées (`COMPANIES_MIN_PAR_JOUR`, `ENTREES_PAR_JOUR`,
`MOUVEMENTS_PAR_CLIENT_PAR_JOUR`). Dépend de l'étape 6.

### 2.6 Module Interface graphique — EF-50 → EF-58 · **backend à écrire**

🔵 côté écrans (Zidane). Côté Loader, il faut exposer : configuration, lancement,
progression temps réel, journal d'erreurs, réinitialisation par préfixe, et
**`EF-55` — verrou empêchant deux générations simultanées**, déjà préparé par
`LoaderRunRepository.dernier_en_cours()`.

### 2.7 Module Traçabilité et Idempotence — EF-60 → EF-66 · **4 / 7**

| Réf | Exigence | État | Où |
|---|---|---|---|
| EF-60 | Aucune duplication en ré-exécution | 🟡 | index uniques posés ; GET-avant-POST à écrire par service |
| EF-61 | Journal structuré par exécution | ✅ | `audit_trail` + `JournalRequetes` |
| EF-62 | Export du journal | ✅ | `exporter_run()` |
| EF-63 | Préfixe d'identification | ✅ | `PREFIXE_DONNEES = "DEMO_"` |
| EF-64 | `run_id` sur chaque entité créée | ✅ | `audit_trail`, `org_hierarchy` |
| EF-65 | Réversibilité atomique *(S)* | ⬜ | **l'outil de purge n'existe pas** |
| EF-66 | Métriques de progression *(S)* | ⬜ | |

### 2.8 Simulation comportementale — EF-67 → EF-71 · **0 / 5** 🔴

Bloqué par **A-06** : le code source `ready_scoring/` est introuvable. Les poids
50/25/13/12 sont figés dans `cdc.py`, la mécanique reste à écrire.

### 2.9 Alimentation des comptes — EF-73 → EF-75 · **0 / 3**

Mouvements **réels** dans account-service. Vérifiés en recette par `CR-12`.

### 2.10 Vie commune et re-scoring — EF-76 → EF-80 · **0 / 5**

`EF-76` 🔴 **A-06** — les 4 fonctions de dates sont le squelette temporel de toute
la simulation, pas seulement du crédit. `EF-80` 🔴 **A-02** — les champs qu'il
nomme n'existent pas chez Faker.

---

## 3. Exigences non fonctionnelles — ENF-01 → ENF-16 · **8 / 16**

| Réf | Exigence | État |
|---|---|---|
| ENF-01 | 2000 clients en < 30 min | ⬜ |
| ENF-02 | Interface réactive | 🔵 |
| ENF-03 | Résilience, retry avec repli | ✅ `base.py` |
| ENF-04 | Idempotence, aucun doublon | 🟡 |
| ENF-05 | Traçabilité et réversibilité | 🟡 |
| ENF-06 | Ergonomie non-technique | 🔵 |
| ENF-07 | Nouveau pays sans modification de code | ✅ |
| ENF-08 | Modules remplaçables indépendamment | ✅ structure `app/{core,clients,services,repositories}` |
| ENF-09 | Aucune donnée personnelle réelle | ✅ |
| ENF-10 | Aucune modification des contrats FinZuu | ✅ |
| ENF-11 | Déployé avec authentification | 🟡 vhost API manquant |
| ENF-12 | Logs structurés | ✅ SIEM JSONL |
| ENF-13 | Réalisme statistique ±3 % | ⬜ |
| ENF-14 | PAR30 ≤ 15 %, PAR90 ≤ 8 %, recouvrement ≥ 85 % | ⬜ |
| ENF-15 | **Reproductibilité stricte** | ✅ testé — tirage dérivé du `run_id` |
| ENF-16 | Fenêtre 180 j, **isolation totale** — pas de ReadyScore, **pas de Kafka**, TEST/DEMO seulement | 🟡 garde-fous en place, boucle à écrire |

---

## 4. Cas d'utilisation — UC-01 → UC-17

| UC | Objet | État |
|---|---|---|
| UC-01 → UC-04 | Profil comportemental, prêt, remboursement, alimentation | 🔴 **A-06** |
| UC-05 | Référentiel géographique | ✅ |
| UC-06 | Devises et opérateurs telco | ✅ lecture seule |
| UC-07 | Companies typées avec licences | ⬜ **étape 2** |
| UC-08 | Lenders locaux et institutionnels | ⬜ **étape 2** |
| UC-09 | Hiérarchie Branche→Agence→Kiosque→Agent | 🟡 planifiée, exécution étape 4 |
| UC-10 | 4 comptes financiers des Lenders | ⬜ mécanisme tranché **D-01** |
| UC-11 | Catalogue Produits | ⬜ **étape 3** |
| UC-12 | Consommation Faker + cohérence pays/opérateur | 🟡 `D-FAKER-1` structurellement garanti |
| UC-13 | Onboarding client + KYC + Kiosque | ⬜ **étape 5** |
| UC-14 | Compte financier client + solde initial | ⬜ **étape 5** |
| UC-15 | Vie commune journalière | 🔴 **A-06** |
| UC-16 | Vie sans crédit (DECLINED / NOT SCORED) | 🔴 **A-06** |
| UC-17 | Re-scoring périodique | 🔴 **A-06** |

---

## 5. Critères de recette — la cible finale

| Réf | Critère | Vérifiable aujourd'hui ? |
|---|---|---|
| CR-01 | Géographie complète et échantillonnable | ✅ |
| CR-02 | **Aucune incohérence géo-organisationnelle** | ✅ `verifier_cr02()` |
| CR-03 | Idempotence, aucun doublon | 🟡 |
| CR-04 | 2000 clients en < 30 min | ⬜ |
| CR-05 | Utilisable sans assistance | 🔵 |
| CR-06 | Journal exploitable | ✅ |
| CR-07 | Réversibilité complète | ⬜ outil de purge |
| CR-08 | Plafond d'usure et regex MSISDN | 🟡 borne figée |
| CR-09 | Distribution comportementale ±3 % | 🔴 |
| CR-10 | 100 séquences fidèles au profil | 🔴 **A-04** — nulle part où les relire |
| CR-12 | Solde = initial + décaissements − remboursements | 🔴 |

---

## 6. Les étapes — ordonnées par dépendance, pas par confort

### ✅ Étape 0 — Fondations · *terminée*
Socle technique, 6 collections, paramètres CDC figés, contrats serveur figés,
11 diagrammes alignés et compilés, journal des décisions.

### ✅ Étape 1 — Socle d'orchestration et référentiel · *terminée*
Client HTTP mutualisé (7 disciplines neutralisées), config-service en lecture
seule, module Géographie, planification de l'Organisation, 6 repositories,
hachage, bootstrap. **27 tests.**

### ⬜ Étape 2 — Organisation · *prochaine, aucun blocage*
`UC-07`, `UC-08`, `UC-10` · EF-10 à EF-13
Clients `company-service` et `user-service`. Companies avec `owner` (Identity
générée côté Loader), licences explicites, Admin User en 3 requêtes, 16 Lenders,
4 comptes explicites par Lender, registre.
**Prérequis levé** : mécanisme des comptes tranché (D-01).

### ⬜ Étape 3 — Catalogue Produits
`UC-11` · EF-69 · D-PRD-1 à D-PRD-9
6 LENDING (split « Any ») + 6 COLLECT (2 réutilisés). Parser tolérant, Policy
embarquée par produit, **taux borné à 24 %**.
**Doit précéder les étapes 4 et 5** (souscription et onboarding exigent un `product_id`).

### ⬜ Étape 4 — Dépositaires et hiérarchie
`UC-09` · EF-14 à EF-18
40‑80 Dépositaires, souscription déclenchant les 6 comptes, `org_hierarchy`
peuplé, `verifier_cr02()` passant. Agents.

### ⬜ Étape 5 — Clients · 🔴 *partiellement bloquée par A-01*
`UC-12` à `UC-14` · EF-20 à EF-29
Onboarding des 2000 clients, quotas forcés par tirage et rejet, comptes et soldes
initiaux. **Le Sénégal exige une source alternative.**

### 🔴 Étape 6 — Vie commune 180 jours
`UC-15` · EF-76, EF-77 · Bloquée par **A-06**

### 🔴 Étape 7 — Crédit et comportement
`UC-01` à `UC-04`, `UC-16`, `UC-17` · EF-67 à EF-75 · Bloquée par **A-06** et **A-04**

### ⬜ Étape 8 — Pilotage Super-Admin
EF-50 à EF-58, EF-65, EF-66 · Routes de configuration, lancement, progression,
journal, purge par préfixe, verrou d'exécution.

### ⬜ Étape 9 — Recette
CR-01 à CR-12 · Mesure des 30 minutes, contrôles statistiques, indicateurs PAR.

---

## 7. Où nous en sommes — le compte honnête

| | Livré | Total | |
|---|---:|---:|---|
| **Exigences fonctionnelles** | **12** | 73 | 16 % |
| **Exigences non fonctionnelles** | **8** | 16 | 50 % |
| **Cas d'utilisation** | **2** | 17 | 12 % |
| **Étapes** | **2** | 10 | 20 % |

Les ENF sont en avance sur les EF, et c'est voulu : résilience, reproductibilité,
traçabilité, modularité et isolation sont des propriétés **structurelles**. Les
poser après coup coûte une réécriture ; les poser d'abord rend chaque étape
suivante plus rapide.

**Six arbitrages bloquent 4 des 10 étapes** — tous nommés dans `DECISIONS.md`.
Deux méritent d'être traités en priorité, car ils bloquent des modules entiers :
**A-01** (Sénégal) et **A-06** (code source Duhamel).

---

*Ce plan se met à jour à chaque étape franchie. Une exigence absente de ce
document est une exigence oubliée.*
