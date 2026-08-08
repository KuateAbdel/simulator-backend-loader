# Faker fintech4esg — Maîtrise complète, état du 8 août 2026

| | |
|---|---|
| **Objet** | Cartographie empirique de l'API Faker, mesurée endpoint par endpoint. Complète et corrige la Cartographie v1.1 (page Confluence 51740675, 17/07/2026). |
| **Nature** | **Lecture seule stricte.** `POST /v1/faker/cache/clear` n'a jamais été appelé — il réinitialiserait le cache partagé. |
| **Base** | `https://faker.fintech4esg.com` · `run_id = 20260620123721` |

---

## 0. La découverte structurante — Faker contient **deux populations disjointes**

Ce point n'apparaît dans aucun document existant, et il conditionne toute la conception du Loader.

| | **Famille A — générateur** | **Famille B — population scorée** |
|---|---|---|
| Endpoints | `/client`, `/client/individual`, `/client/business` | `real-scoring-*`, `loan-history/*`, `playground-client/*` |
| Format d'identifiant | `CM-IND-895367` | `RC-CM-IND-CMC827162` |
| Paramètre **`seed`** | ✅ **oui** | ❌ **non** |
| Volume atteignable | **illimité** — 180 seeds → **180 clients distincts, 0 collision** | **très faible** — figé au `run_id` |
| `country_code` | enum strict `BF/CI/CM` → SN = **422** | libre, mais SN = **404** |
| Décision de scoring | ❌ absente | ✅ présente |
| Historique de crédit | ❌ absent | ✅ 34 champs par prêt |
| Richesse du payload | **12 champs racine** | 17 champs racine, structure **variable** |

### Les deux populations ne communiquent pas

Un `client_id` de famille A interrogé sur les endpoints de famille B ne renvoie pas un 404 propre — il provoque un **timeout** :

```
GET /v1/faker/real-scoring-payload/CM-IND-313226  → TIMEOUT
GET /v1/faker/loan-history/CM-IND-313226          → TIMEOUT
```

Alors qu'un identifiant de famille B répond `200` sous **trois formats** : `client_id`, `external_client_id`, `sim_number` (`client_uid` vaut `None` aujourd'hui — F‑04 partiellement vrai).

**Impact Loader** : ne jamais interroger la famille B avec un identifiant de famille A. Prévoir un timeout client agressif, le serveur ne protège pas.

---

## 1. Le mécanisme du cache, élucidé

La Cartographie v1.1 décrivait un « cache déterministe ». Le mécanisme exact est plus précis, et c'est lui qui a produit tous les faux résultats — les miens comme ceux du sondage S2 :

> **`/random` est mis en cache par jeu de paramètres COMPLET.** Deux appels aux paramètres strictement identiques renvoient toujours le même client. Changer n'importe quel paramètre — y compris `limit` — donne une autre entrée de cache.

Preuves :

| Test | Résultat |
|---|---|
| 45 appels `loan-history/random?run_id&limit=1&include_events=false` | **1 seul client distinct** (45/45 identiques) |
| Les mêmes avec `limit=5` puis `limit=50` | deux clients **différents** |
| 12 appels `real-scoring-payload/random?run_id` | **1 seul client distinct** |
| 24 combinaisons de filtres sur `real-scoring-phone/random` | **6 clients distincts** |
| `GET /v1/faker/cache/health` | Redis 7.4.8, **12 clés**, TTL moyen ~122 s |

**Piège** : un sondage naïf conclut « la distribution est de 100 % APPROVED » alors qu'il a simplement lu 30 fois la même entrée de cache. C'est exactement le diagnostic du Trou #1 du sondage S2, et il est juste.

**Impact Loader** : toute itération sur une population passe par la variation d'un paramètre. En famille A, c'est `seed`. En famille B, il n'existe **aucun** paramètre de pagination ni de curseur.

---

## 2. Surface complète — 15 chemins, 16 opérations, 3 schémas

**Aucun schéma de sécurité déclaré** (`security: null`, `securitySchemes: {}`) et aucun appel refusé sans en-tête. **La question ouverte Q‑02 de la Cartographie — obtenir une clé `x-api-key` auprès d'Oti — est sans objet : aucune clé n'est requise.**

**Trois schémas seulement** : `FakerPayloadRequest`, `HTTPValidationError`, `ValidationError`. Les schémas `ClientResponse` et `ClientEnrichedItem`, décrits dans certaines analyses, **n'existent pas dans le contrat** — tout le reste est du JSON dynamique non typé.

| Famille | Endpoint | Paramètres réels |
|---|---|---|
| **A** | `GET /v1/faker/client` | `country_code` (enum BF/CI/CM, défaut CI), `customer_category` (enum Individual/Business), `seed` |
| **A** | `GET /v1/faker/client/individual` | `country_code` (enum), `seed` |
| **A** | `GET /v1/faker/client/business` | `country_code` (enum), `seed` |
| **B** | `GET /v1/faker/real-scoring-phone/random` | `run_id`, `country_code`, `customer_category`, `decision_status`, `operator`, `has_taken_loan` |
| **B** | `GET /v1/faker/real-scoring-payload/random` | `run_id`, `country_code`, `customer_category`, `decision_status`, `has_taken_loan` |
| **B** | `GET /v1/faker/real-scoring-payload/{client_id}` | `client_id` (requis), `run_id`, `country_code`, `customer_category`, `decision_status` |
| **B** | `GET /v1/faker/real-scoring-payload/by-phone` | `mobile_phone` (requis), `run_id`, `country_code` |
| **C** | `GET /v1/faker/loan-history/random` | `run_id`, `country_code`, `customer_category`, `decision_status`, `has_taken_loan`, `limit`=50, `include_events`=true, `event_limit`=500 |
| **C** | `GET /v1/faker/loan-history/{client_id}` | `client_id` (requis), `run_id`, `loan_id`, `limit`, `include_events`, `event_limit` |
| **C** | `GET /v1/faker/playground-client/random` | `run_id`, `country_code`, `customer_category`, `has_taken_loan`, `limit`=200 |
| **C** | `GET /v1/faker/playground-client/{client_id}` | `client_id` (requis), `run_id`, `country_code`, `customer_category`, `limit` |
| **D** | `GET /v1/faker/scoring-payload` | `country_code` (enum), `customer_category` (enum), `seed`, `scoring_date` |
| **D** | `POST /v1/faker/scoring-payload` | corps `FakerPayloadRequest` (mêmes 4 champs) |
| **E** | `GET /v1/faker/cache/health` | — |
| **E** | `POST /v1/faker/cache/clear` | ⛔ **jamais appelé** — réinitialise le cache partagé |
| — | `GET /health` | — |

**Important** : `limit` sur `loan-history` porte sur le **nombre de prêts d'un client**, jamais sur un nombre de clients. `limit=50` a renvoyé un client possédant 42 prêts.

---

## 3. Contenu réel des payloads

### Famille A — Individual : **12 champs racine, et c'est tout**

```json
{
  "client_id": "CM-IND-895367",
  "sim_number": "+23712814207",
  "country_code": "CM",
  "customer_category": "Individual",
  "currency": "XAF",
  "first_name": "Ines",  "last_name": "Tamadou",  "full_name": "Ines Tamadou",
  "gender": "WOMAN",
  "identity":  { "ID_TYPE": "CNI", "ID_NUMBER": "483502292668444",
                 "ID_ISSUE_DATE": "23/04/2020", "ID_EXPIRY_DATE": "21/04/2030" },
  "quick_win": { "IS_RGS_1": 1, "IS_RGS_7": 1, "IS_RGS_30": 1, "IS_RGS_90": 1,
                 "IS_SMARTPHONE_USER": 1, "LAST_EVENT_DATE": "2026-06-24",
                 "LAST_EVENT_TYPE": "Debit", "IS_DATA_RGS1": 0, ... }
}
```

**Sont ABSENTS** : `region`, `city`, `district`, `sector`, `postal_code`, `residency`, `operator`, `mnc`, `age`, `birth_date`, `place_of_birth`, `civility`, `email`, `occupation`, `address`.

> ⚠️ **Correction d'une croyance répandue.** Certaines analyses affirment que « Faker fournit `region` + `city` + `district` + `sector` + `postal_code` par client — pas besoin de tout inventer ». **C'est faux pour la famille A**, la seule capable de fournir nos 2000 clients. Ces champs existent partiellement en famille B (`contact`, `geolocation`), qui est inexploitable en volume.

### Famille A — Business : identique + un objet `company`

```json
"company": {
  "company_id": "cmp_cm_2651",
  "company_name": "Test Business CM 158",
  "company_type": "Entreprise Individuelle",
  "sector_assignments": [ {"sector_label": "Advertising", "rank": 1},
                          {"sector_label": "AR", "rank": 2},
                          {"sector_label": "Fashion", "rank": 3} ],
  "metadata": { "source": "faker-api", "generated_at": "..." }
}
```

**Les 6 `company_type` sont confirmés** (24 tirages, seeds variés, 24 identifiants distincts) :
Entreprise Individuelle 6 · SA 6 · SARL 4 · Fondation 4 · SAS 3 · Association 1.
Le « TVE uniquement » rapporté par un sondage antérieur était un artefact de cache — il n'y a **pas** de limitation.

> ⚠️ **Mais les noms d'entreprise sont des placeholders.** 15 tirages sur 3 pays :
> `Test Business CM 748`, `Test Business CI 200`, `Test Business BF 470`…
> Or `UC-08` exige que chaque Lender local porte *« un nom métier crédible »*, et la démo cible Nordic Microfinance, IFC, AFD et BAD. **`DEMO_Test Business CM 748` ne passera pas.** Le Loader devra générer lui-même les raisons sociales, en réutilisant au besoin `company_type` et `sector_assignments`, qui sont exploitables.

### Famille B — structure **variable d'un client à l'autre**

Certains clients portent `identity`, `contact`, `birth_date`, `first_name`, `nationality` ; d'autres ont `identity: null` et `contact: null`. **Parsing défensif obligatoire** : aucun champ de famille B ne peut être supposé présent.

Sections de premier niveau : `client`, `features` (95 clés), `metadata` (31 clés), `request_id`, `scoring_date`, `transactions`, `source_system` (`lifecycle-v31-redpanda`), `loan_behavior_source` (`live_from_loan_accounts`).

---

## 4. La décision de scoring — où elle est vraiment

`EF-80` prescrit d'extraire `decision.decision_status`, `decision.selected_product`, `decision.selected_amount` et `metadata.behavior_segment`. Mesuré :

| Champ prescrit par EF‑80 | Réalité |
|---|---|
| `decision.decision_status` | **absent** — aucune section `decision` dans le payload |
| `decision.selected_product` | **absent partout** |
| `decision.selected_amount` | **absent partout** |
| `metadata.behavior_segment` | présent mais vaut **`0.0`** dans 14 cas sur 15 |

**Où se trouve réellement l'information :**

- `decision_status` est un **filtre de requête** et il fonctionne parfaitement : 12 demandes APPROVED → 12 APPROVED ; 12 demandes DECLINED → 12 DECLINED.
- `decision_status` est aussi un **champ de réponse de `/real-scoring-phone/random`** :
  ```json
  { "client_id": "RC-CM-IND-CMC598776", "decision_status": "DECLINED",
    "has_taken_loan": false, "operator": "Nexttel CM", "scoring_date": "2026-05-01" }
  ```
- Le **vrai segment de risque** est `features.__precomputed_scores.segment`, en clair :
  `Very High` · `High` · `Medium` · `Low` · `Very Low` — **exactement les 5 segments de l'Annexe E du CDC**.
  Sur 15 tirages : Medium 5, High 4, Very High 3, Very Low 2, Low 1.

**Conséquence majeure** : les 2000 clients viennent nécessairement de la famille A, qui **ne porte aucune décision de scoring**. `EF-80` n'est donc pas applicable tel qu'écrit à la population du Loader.

---

## 5. Historique de crédit — structure exacte

`GET /v1/faker/loan-history/{client_id}` renvoie :

```
{ run_id, client_id, requested_client_id, summary, loans_count, loans[], source_tables }
```

Chaque prêt porte **34 champs**. Valeurs observées :

| Champ | Observation |
|---|---|
| `product` | **Nano** sur 420 prêts d'un même client ; `Macro` observé sur un autre |
| `status` | FINISHED 410 / ONGOING 10 |
| `duration_days` | **15** sur la totalité |
| `loan_amount` | 128 000 observé |
| `segment_at_origination`, `score_at_origination` | **`None`** — les snapshots ne sont pas renseignés |

Un client peut porter **jusqu'à 42 prêts**. Les champs comptables sont séparés : `paid_capital`, `paid_interest`, `paid_penalty`, `paid_taxes`, `reimbursement_ratio`.

> ⚠️ Ces prêts **ne sont pas injectables** : aucun des 9 services FinZuu ne peut héberger un prêt, `loan-service` n'étant pas livré (`CT-02`). Une analyse antérieure concluait qu'« on peut directement injecter ces loans en base FinZuu » — c'est impossible.

---

## 6. Ce qui a changé depuis la Cartographie v1.1 (17/07)

| Point v1.1 | État au 08/08 |
|---|---|
| **F‑03** un seul `run_id` valide | ✅ confirmé — `404 "No matching client phone found"` sur tout autre |
| **F‑05** cache déterministe | ✅ confirmé, **et précisé** : clé = jeu de paramètres complet |
| **F‑06** `seed` contourne le cache | ✅ confirmé — **famille A uniquement** |
| **F‑07** aucun rate limit | ✅ confirmé (45 appels consécutifs) |
| **F‑04** 4 formats d'id | ⚠️ **3 sur 4** — `client_uid` vaut `None` |
| **Q‑02** obtenir la clé `x-api-key` | ✅ **SANS OBJET** — aucune sécurité déclarée |
| **§5.3** « SN accepté au runtime » | ❌ **PÉRIMÉ** — 422 (famille A), **404** (famille B) |
| **§5.6** 25 % par pays dont SN | ❌ **PÉRIMÉ** — SN absent ; et 5 tirages par pays est un échantillonnage **stratifié**, pas une distribution observée |
| **§5.6** 35 % APPROVED / 65 % DECLINED | ⚠️ non reproductible par tirage naïf (cache) |
| **§5.7** Nano 95 % / Macro 5 % | ⚠️ 420 prêts d'un client = **Nano 100 %** ; Macro existe ailleurs |
| **F‑11 / CT‑04** « Faker ne rejette pas les filtres invalides » | ❌ **PÉRIMÉ — et c'est une amélioration** : `ZZ` → **422** (A) / **404** (B). Faker **valide** désormais |
| **L‑04** playground timeout à 25 s | ❌ **AGGRAVÉ** — timeout à **90 s**, endpoint inutilisable |
| **Trou #1** « business = TVE uniquement » | ✅ **REFERMÉ** — 6 `company_type`, c'était le cache |

---

## 7. Les deux blocages à remonter

### 🔴 SN indisponible — 500 clients concernés

`OBJ-01` et `EF-05` exigent 4 pays. Faker n'en sert que 3.

```
famille A  /client/individual?country_code=SN   → HTTP 422
famille B  /real-scoring-phone/random?…&SN      → HTTP 404
famille B  /loan-history/random?…&SN            → HTTP 404
```

Trois voies possibles : générateur interne pour SN (comme pour les Companies, Lenders institutionnels et Dépositaires, que Faker ne fournit pas non plus), demande à Oti d'ajouter SN au `run_id`, ou réduction à 3 pays — ce qui contredirait le CDC.

### 🟠 Trois distributions du CDC ne sont obtenables par aucun filtre

| Exigence | Filtre Faker ? |
|---|---|
| `EF-23` — 80 % Individual / 20 % Corporate | ✅ `customer_category` |
| `EF-22` — **ratio 2 femmes / 1 homme** | ❌ **aucun paramètre `sex`**. Testé : `sex=male` et `sex=female` renvoient tous deux `gender: WOMAN`. Le paramètre est **silencieusement ignoré** |
| `EF-22` — 60 % de moins de 25 ans | ❌ aucun champ d'âge en famille A |
| `EF-24` — 20 % des professionnels en agriculture | ⚠️ `sector_assignments` exploitable, mais pas filtrable |

**Conséquence** : ces distributions s'obtiennent par **tirage et rejet** côté Loader, jamais par filtre. Un client écarté pour raison de quota n'est pas « consommé » au sens `D-FAKER-1` — il n'entre au registre que s'il a réellement produit une entité.

---

## 8. Ce que Faker ne fournit pas — inchangé et confirmé

Company IMF autonome · Lender institutionnel (Nordic, IFC, AFD, BAD) · Branche, Agence, Kiosque, Agent · Dépositaire · Produit Collecte ou Prêt · Compte financier · **raison sociale crédible** · **adresse, date de naissance, occupation, email**.

Tout cela relève du générateur interne du Loader.

---

*Sondage exécuté en lecture seule le 8 août 2026. Chaque affirmation est adossée à une mesure reproductible.*
