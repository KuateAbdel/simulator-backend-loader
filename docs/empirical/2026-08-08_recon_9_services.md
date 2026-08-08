# Reconnaissance empirique des 9 microservices FinZuu — environnement TEST

| | |
|---|---|
| **Date** | 8 août 2026 |
| **Environnement** | TEST — `*.test.services.fintech4esg.com` (APISIX 3.13.0) |
| **Authentification** | ROOT (`noreply@finzuu.com`) |
| **Nature** | **Lecture seule stricte** — contrats OpenAPI + inventaire. Aucune écriture. |
| **Objet** | Confronter les diagrammes UML et le CDC v1.2 aux **contrats serveur réels**, avant tout développement. |

> **Principe.** Un diagramme décrit une intention ; le contrat OpenAPI décide.
> Là où les deux divergent, c'est le serveur qui gagne — et chaque divergence
> non détectée avant le codage devient un HTTP 422 en pleine génération de
> 2000 clients. Ce document liste ces divergences.

## 0. Vue d'ensemble

| Service | Routes | Schémas | Volumétrie TEST observée |
|---|---:|---:|---|
| user-service | 40 | 20 | 18 users |
| config-service | 25 | 11 | 6 countries, 4 currencies, 14 telcos |
| identity-service | 12 | 13 | 11 identities |
| account-service | 18 | 21 | 42 accounts, 29 transactions |
| company-service | 10 | 14 | 7 companies, 5 licenses |
| product-service | 8 | 20 | 7 products |
| depositary-service | 13 | 10 | 11 dépositaires, 6 souscriptions |
| client-service | 10 | 15 | 3 clients |
| collect-service | 12 | 8 | 13 collectes |

---

## 1. DIVERGENCES BLOQUANTES — provoqueraient un HTTP 422 immédiat

### 1.1 `CompanyType` : trois valeurs du diagramme n'existent pas côté serveur

| `02_class.puml` | Enum serveur réel | Verdict |
|---|---|---|
| `IMF` | `IMF` | ✅ |
| `BANK` | `BANK` | ✅ |
| `FONDATION` | `FONDATION` | ✅ |
| `MERCHANT` | `MERCHANT` | ✅ |
| `AGENCE` | **`AGENCY`** | ❌ 422 |
| `KIOSQUE` | **`KIOSK`** | ❌ 422 |
| `FONDS_INSTITUTIONNEL` | **`FUNDING_PROVIDER`** | ❌ 422 |

Enum serveur complet : `['MERCHANT', 'BANK', 'IMF', 'AGENCY', 'KIOSK', 'FUNDING_PROVIDER', 'FONDATION']`.

**Impact direct :** les 4 Lenders institutionnels (Nordic, IFC, AFD, BAD) relèvent
de `FUNDING_PROVIDER`, jamais de `FONDS_INSTITUTIONNEL`. Le diagramme de classe
doit être corrigé, ou le mapping FR→EN assumé explicitement dans le code.

### 1.2 `CreateCompanySchema` : 3 champs requis absents des diagrammes

Requis réels : `name, short_name, type, industries, sectors, owner, address, admin_email, currency`.

- **`industries`** et **`sectors`** : `array[string]` avec **`minItems: 1`** — un
  tableau vide est rejeté. Aucun diagramme ne les mentionne.
- **`address`** : objet `Address` requis (`address_line_1` + `street_name`
  obligatoires). C'est précisément là que sert le référentiel géo enrichi
  interne du Loader (51 régions / 50 villes / 82 quartiers).
- `company_id` optionnel = l'auto-référence parent/filiale.

### 1.3 `Identity` embarquée dans `CreateCompanySchema` : **`_id` est requis**

Requis : `_id, type, first_name, date_of_birth, gender, nationality, id_number,
id_place, phone, email, occupation, address`.

**C'est le piège le plus contre-intuitif de tout l'écosystème :** l'appelant doit
**fournir lui-même l'`_id`** de l'Identity owner. Le Loader génère donc l'UUID
côté client avant le POST — il ne le reçoit pas du serveur.

À l'inverse, `id_expire_on` est ici **optionnel** (`string | null`), alors que le
`CreateIdentitySchema` d'identity-service le déclare **requis**. La note du
diagramme de classe (« optionnel au contrat, obligatoire en pratique ») est donc
exacte, mais pour une raison plus précise que supposé : **les deux services ne
partagent pas le même contrat pour la même entité.** D-CLI-2 reste impératif —
toujours fournir `id_expire_on`, quel que soit le service visé.

### 1.4 `OnboardClientSchema` : `channel` et `segment` requis, absents du diagramme 05

Requis : `msisdn, channel, segment, category, identity, product_id, currency`.

| Champ | Enum serveur | Présent dans `05_sequence_onboarding.puml` |
|---|---|---|
| `channel` | `USSD, MOBILE, OFFICE` | ❌ non |
| `segment` | `ANY, VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH` | ❌ non |
| `language` | `en, fr` (optionnel) | ❌ non |

`segment` est le point de jonction avec le `metadata.behavior_segment` de Faker
(EF-80) et avec la segmentation par risque de l'Annexe E. Il n'était identifié
nulle part dans nos documents.

### 1.5 `CreateIdentitySchema` : 3 champs requis supplémentaires

Requis : `first_name, date_of_birth, nationality, id_number, id_place,
id_expire_on, phone, email, occupation, address`.

`nationality`, `id_place` et `occupation` n'apparaissent dans aucun diagramme.

---

## 2. DÉCOUVERTES QUI CHANGENT LA CONCEPTION

### 2.1 `ProductSegment` existe — et ne doit pas être confondu avec `ProductCategory`

```
ProductCategory : ['INDIVIDUAL', 'CORPORATE']              <- "ANY" INTERDIT (D-PRD-4)
ProductSegment  : ['ANY', 'VERY_LOW', 'LOW', 'MEDIUM', 'HIGH', 'VERY_HIGH']   <- "ANY" AUTORISE
```

Deux champs distincts, deux traitements opposés de la valeur `ANY`. Le split
obligatoire de D-PRD-4 concerne **exclusivement `category`**. Le `segment`
accepte `ANY` sans difficulté, et porte la segmentation par risque de l'Annexe E
(Very High → Very Low). Confondre les deux produirait soit un 422, soit un
catalogue dupliqué sans raison.

### 2.2 `CreateProductSchema` accepte **`policy` ET `policy_id`** — le danger D-PRD-7 est réel et à portée de main

Propriétés : `type, name, short_name, description, category, segment, policy_id, policy, subscription_fees`.
Requis : `type, name, category` seulement.

Le champ `policy_id` étant directement exposé, un développeur pressé peut
réutiliser un `policy_id` existant en toute bonne foi — et déclencher exactement
la corruption rétroactive décrite par INV-PRD-07. **Règle absolue du Loader :
toujours `policy` (embed inline), jamais `policy_id`.**

Routes policies réelles : `/api/v1/policies/{type}` et
`/api/v1/policies/{type}/{policy_id}`. `GET /api/v1/policies/` répond 404 —
ce n'est pas un bug, la route exige le path param `type`.

### 2.3 Le catalogue COLLECT existant est déjà pollué et **contient un doublon**

| Nom | Type | Catégorie | Segment | Policy |
|---|---|---|---|---|
| `plastique` | COLLECT | INDIVIDUAL | ANY | PRODUCT |
| `Cotisation 20000/mois` | COLLECT | INDIVIDUAL | ANY | CASH |
| **`Cotisation 20000/mois`** | COLLECT | INDIVIDUAL | ANY | CASH | ← **doublon** |
| `Test_Produit_1785841588` | COLLECT | INDIVIDUAL | ANY | CASH |
| `PROBE_CASQUETTE5_…` ×3 | COLLECT | INDIVIDUAL | ANY | CASH |

**ANO-PRD-UNIQ-01 confirmé en direct :** aucune contrainte d'unicité sur `name`.
Conséquence pour D-PRD-2 : le GET-avant-POST du Loader doit gérer le cas
**« plusieurs correspondances »**, pas seulement « une ou zéro ». Retenir
systématiquement la plus ancienne, et journaliser le doublon.

Constat complémentaire : **0 produit LENDING** et **0 produit CORPORATE** en
base. Tout le catalogue Prêt de l'Annexe E est à créer.

### 2.4 config-service : référentiel conforme, mais 2 entrées polluées

| ISO | Nom | Région | Villes | Devises | Telcos |
|---|---|---|---|---:|---:|
| `CM` | Cameroun | Middle Africa | 12 | 1 | 3 |
| `CI` | Cote d'Ivoire | Western Africa | 12 | 1 | 3 |
| `BF` | Burkina Faso | Western Africa | 12 | 1 | 3 |
| `SN` | Senegal | Western Africa | 14 | 1 | 3 |
| `CV` | **`cm`** | `cm` | 0 | 1 | 1 | ← pollué |
| `ca` | **`cmer`** | `cm` | 0 | 1 | 1 | ← pollué (iso minuscule) |

Les **4 pays cibles sont présents et complets** — 12+12+12+14 = **50 villes**,
conforme à OBJ-01. La Phase 1 du diagramme d'activité (vérification en lecture
seule) est donc satisfaisable dès aujourd'hui.

Deux points de vigilance :
1. **La validation Phase 1 doit ignorer les entrées polluées, pas échouer dessus.**
   Un contrôle « exactement 4 pays » planterait ; le bon contrôle est
   « les 4 pays cibles sont présents et complets ».
2. `region` vaut `Middle Africa` / `Western Africa` : sous-région **continentale**,
   jamais une division administrative — la note du diagramme de classe est
   confirmée en données réelles.

### 2.5 Le blocage FRA-48 sur config-service n'existe plus

Le script de référence `loader_config_service.py` s'arrête sur un HTTP 403
documenté (ROOT refusé par config-service, écart du 27/07/2026). **Ce 403 n'est
plus reproductible :** toutes les lectures ROOT sur config-service répondent
HTTP 200. Le blocage a été levé côté serveur entre-temps.

### 2.6 `TransactionTag` contient `LENDER`

`['COMPANY', 'LENDER', 'SAVING', 'TO_SHARE', 'SELF']`.

Seule occurrence du mot « lender » dans tout l'écosystème : account-service sait
**taguer** une transaction comme relevant d'un Lender, sans pour autant connaître
l'entité. Cohérent avec « Lender = rôle porté par une Company » (CDC §6.3), et
utile pour tracer les flux de financement.

### 2.7 `TagGroupe` n'a que 3 valeurs, contre 5 rôles supposés

`UserType = ['COMPANY', 'CUSTOMER', 'GUEST', 'ROOT', 'STAFF']` (5, conforme à H-05)
mais `TagGroupe = ['STAFF', 'COMPANY', 'CUSTOMER']` (3). `GET /api/v1/groups/`
répond **404** — la route n'existe pas sous ce chemin.

`CreateUserSchema` requiert `user_name, type_user, identity, email, password` :
**une Identity est exigée à la création d'un User**, ce qu'aucun diagramme ne dit.

---

## 3. PIÈGES TECHNIQUES MINEURS

- **404 signifiant « zéro résultat ».**
  `GET /depositaries/subscriptions/depositary/{id}` répond 404 quand le
  dépositaire n'a aucune souscription (observé sur 3 cas). Le client httpx doit
  traiter ce 404 comme une liste vide, jamais comme une erreur.
- **Collision de noms dans le contrat depositary-service.** Deux schémas portent
  le même nom de classe : `app__schemas__depositary_schema__CreateDepositaireSchema`
  (`name, currency, company_id`) et
  `app__schemas__depositary_subscription_schema__CreateDepositaireSchema`
  (`product_id, depositary_id`). Toute génération automatique de client se
  tromperait de schéma.
- **`external_id` vide.** Les 7 comptes OPERATION issus de la cascade Company ont
  `external_id=""` alors que le champ est requis à la création. Le Loader
  renseignera toujours ce champ.
- **Aucun DELETE sur account-service.** Un compte créé ne peut être que passé en
  `CLOSED` (`PUT /accounts/change-status/{id}/{status}`). Toute écriture y est
  définitive — cela conditionne la stratégie de réversibilité (CR-07 / EF-65).

---

## 4. Ce qui est CONFIRMÉ conforme aux diagrammes

- `PolicyType = ['CASH', 'CASH_DAT', 'PRODUCT']` ✅ ; `PolicyMeasure = ['KILOGRAM', 'LITER']` ✅
- `ProductType = ['COLLECT', 'LENDING']` ✅ ; `ProductCategory = ['INDIVIDUAL', 'CORPORATE']` ✅ (D-PRD-4 fondé)
- `IdentityType = ['CORPORATE', 'INDIVIDUAL']` ✅
- `OwnerType = ['COMPANY', 'IDENTITY']` ✅
- `AccountType` contient bien `CAPITAL, INTEREST, PENALTY, TAXE` ✅ (mais aucune cascade Lender — cf. document Trou #2)
- `PackageName = ['ALL', 'READY_CASH', 'READY_COLLECTE', 'BULK']` ✅ conforme à UC-07
- Cascade Dépositaire : 6 comptes à la souscription ✅ (D-DEP-2, re-confirmé)

---

## 5. Actions qui en découlent

| # | Action | Urgence |
|---|---|---|
| 1 | Corriger `CompanyType` dans `02_class.puml` (AGENCY / KIOSK / FUNDING_PROVIDER) | Avant module Organisation |
| 2 | Compléter `05_sequence_onboarding.puml` avec `channel`, `segment`, `language` | Avant module Client |
| 3 | Acter que le Loader génère lui-même l'`_id` de l'Identity owner | Avant module Organisation |
| 4 | Prévoir `industries` / `sectors` (minItems 1) dans le générateur de Company | Avant module Organisation |
| 5 | D-PRD-2 étendu : gérer le cas « plusieurs correspondances » (doublon existant) | Avant module Produits |
| 6 | Phase 1 : valider « les 4 pays cibles présents », jamais « exactement 4 pays » | Avant module Référentiel |
| 7 | Mettre à jour le statut de FRA-48 (blocage levé) | Documentaire |

---

*Reconnaissance exécutée en lecture seule, avant tout développement de module,
pour éliminer les mauvaises surprises en cours d'implémentation.*
