# Service Anatomy — faker-service — Couche 4 · DOMAINS

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANATOMY-FKR-2026-001 · Couche 4/7 |
| **Service** | faker-service (« ReadyScore Faker API ») |
| **Version** | v1.1 (corrigée après interrogation famille B) |
| **Date de mesure** | 2026-08-19 (payloads + campagne d'interrogation capturés en direct) |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Statut** | APPRENTISSAGE — 0 pytest avant la Couche 7 |
| **Périmètre** | Les ENTITÉS, leurs RELATIONS, les INVARIANTS de la donnée. PAS le déroulé (→5), PAS le jugement des pannes (→7). |

> **Discipline.** **FACT** (mesuré, daté) / **DÉDUIT** (inférence explicite) /
> **HYPOTHÈSE**. Une donnée de juillet non reconfirmée aujourd'hui = *observation
> historique*, marquée. Rien n'est « bug » ici — les candidats-anomalies restent
> OBSERVATION jusqu'à qualification en Couche 7.
>
> **Correction assumée (rigueur).** Une v1.0 de cette page concluait « la
> population scorée est indisponible aujourd'hui ». **C'était FAUX** : conclusion
> tirée sur 2 voies d'accès, réfutée par une 3ᵉ (`by-phone`). Corrigé ci-dessous.
> La leçon : interroger plusieurs chemins avec témoins AVANT de conclure.

---

## 1. La question de la Couche 4 (à laquelle cette page RÉPOND)

> **Quelles ENTITÉS métier Faker manipule-t-il ? Quelles relations entre elles ?
> Quels INVARIANTS protègent la donnée ?** → Réponse synthétique en §10.

---

## 2. Méthode — captures + interrogation du 19/08 (lecture seule)

| Sonde | Résultat |
|---|---|
| `client/individual` CM/CI seed=7 | payload complet ✅ (devise XAF/XOF) |
| `client/business` CM seed=7 | payload + objet `company` ✅ |
| `real-scoring-phone/random` CM/CI/BF | enregistrement B ✅ (APPROVED & DECLINED vus) |
| `real-scoring-payload/by-phone` CM/CI/BF | **payload complet ✅ (déterministe)** |
| `real-scoring-payload/random` (bare + tous filtres) | **404** ❌ |
| `real-scoring-payload/{id}` (4 formats d'id) | **404** ❌ |
| `loan-history/{client_id}` (client B valide) | **200 ✅** |
| `loan-history/random` | **404** ❌ |

---

## 3. Le catalogue des entités (6)

### 3.1 E-A1 — Client Individuel (famille A) — 11 champs racine (FACT 19/08)

```json
{ "client_id":"CM-IND-572544","sim_number":"+23713047541","country_code":"CM",
  "customer_category":"Individual","currency":"XAF","first_name":"Olivier",
  "last_name":"Kambire","full_name":"Olivier Kambire","gender":"MAN",
  "identity":{"ID_TYPE":"CNI","ID_NUMBER":"986345949468302",
              "ID_ISSUE_DATE":"07/11/2016","ID_EXPIRY_DATE":"05/11/2026"},
  "quick_win":{"IS_RGS_1":0,...,"LAST_EVENT_TYPE":"Debit","IS_DATA_RGS90":1} }
```

- Blocs : 9 champs racine + `identity` (4) + `quick_win` (11 clés socio-comportementales).
- **ABSENTS (FACT re-mesuré)** : `region`, `city`, `district`, `sector`, `postal_code`,
  `age`, `birth_date`, `email`, `occupation`, `address`. → « Faker fournit la géo »
  reste **FAUX pour la famille A**.

### 3.2 E-A2 — Client Business (famille A) — E-A1 + `company`

- **`client_id` token `BIZ`** : `CM-BIZ-769727` (fait neuf 19/08).
- `identity.ID_TYPE` peut valoir `Passport`.

### 3.3 E-A3 — Company (sous-entité de E-A2)

```json
"company":{"company_id":"cmp_cm_1469","company_name":"Test Business CM 406",
  "company_type":"Association",
  "sector_assignments":[{"sector_label":"Accounting","rank":1}, ...],
  "metadata":{"source":"faker-api","generated_at":"2026-08-19T..."}}
```

- **`company_name` = PLACEHOLDER** (`Test Business CM 406`) — FACT, pas une raison sociale.
- `sector_assignments` ordonnés par `rank`.

### 3.4 E-B1 — Client Scoré (famille B), index — via `phone/random` (FACT 19/08)

```json
{ "client_id":"RC-CM-IND-CMC293057","external_client_id":"CMC293057",
  "sim_number":"CMC293057","operator":"MTN CM","mobile_phone":"+237 76 047 4780",
  "decision_status":"DECLINED","has_taken_loan":false,"run_id":"20260620123721" }
```

- Id de format DISTINCT `RC-…` (préfixe ReadyCash).
- ⚠ **`sim_number` = `external_client_id`, PAS le téléphone** (le vrai numéro est
  `mobile_phone`) — incohérence de nommage OBSERVÉE (→ Couche 7).

### 3.5 E-B2 — Scoring Payload (famille B) — **DISPONIBLE via `by-phone` uniquement** (FACT 19/08)

Structure complète capturée par `by-phone` (déterministe) :

| Section | Taille | Contenu clé |
|---|---|---|
| `client` | **30 clés** | inclut `address`, `city_of_residence`, `city_of_birth`, `latitude`, `longitude`, `birth_date`, `nationality`, `geolocation`, `language`, `client_uid`, `individual_profile` — **exactement ce que la famille A N'A PAS** |
| `features` | **95 clés** | dont `__precomputed_scores.segment` = **`High`** (vrai segment, Annexe E) ; 10 champs `*MOB_MONEY*` dont **`MOB_MONEY_ACCOUNT_AMOUNT`=3135.52** |
| `metadata` | **31 clés** | dont `behavior_segment` = **`0.0`** (le champ que le CDC cite à tort) |
| `transactions` | list[2] | historiques |
| autres | — | `request_id`, `scoring_date`, `source_system: lifecycle-v31-redpanda`, `loan_behavior_source: live_from_loan_accounts` |

> **La donnée riche (géo, âge, solde Mobile Money, segment) vit ICI, en famille B.**
> Et famille B est inexploitable en volume (pas de `seed`, figée au `run_id`,
> **atteignable seulement par `by-phone`**). C'est la preuve vivante de pourquoi le
> Loader compose lui-même géo/solde et n'utilise QUE la famille A.

### 3.6 E-C1 — Loan History (famille C) — `/{client_id}` répond (FACT 19/08)

- `loan-history/{client_id}` (et `/{external}`) → **200**, sections `run_id`,
  `client_id`, `requested_client_id`, `summary`, `loans`…
- `loan-history/random` → **404**.
- **Observation historique (juillet)** : 34 champs/prêt, jusqu'à 42 prêts/client,
  `product` Nano/Macro, `duration_days` 15. Prêts **non injectables** (loan-service
  non livré). Détail des `loans[]` non re-dumpé aujourd'hui.

---

## 4. La MATRICE des voies d'accès famille B/C (le fait d'interrogation, FACT 19/08)

| Ressource | `/random` | `/{client_id}` | `/by-phone` |
|---|---|---|---|
| `real-scoring-phone` | **200 ✅** | — | — |
| `real-scoring-payload` | 404 ❌ | 404 ❌ | **200 ✅** |
| `loan-history` | 404 ❌ | **200 ✅** | — |

**Deux candidats-anomalies isolés (OBSERVATION — qualification Couche 7) :**
- **AN-FKR-B1** : tous les sélecteurs `/random` (payload, loan-history) → 404, alors
  que `phone/random` fonctionne et que la donnée existe (récupérable autrement).
- **AN-FKR-B2** : `real-scoring-payload/{client_id}` → 404 pour un client dont le
  payload sort par `by-phone` ET dont l'historique sort par `loan-history/{client_id}`.
  Cassure **isolée** à cet endpoint précis.

Preuves : 4 formats d'id testés (tous 404 sur payload/{id}), 3 pays témoins (CM/CI/BF
identiques), `by-phone` déterministe (2 appels → même client, même segment). **Cause
interne NON spéculée** (index/routage ? — hors de ma visibilité, à confronter à Oti).

---

## 5. Formats d'identifiant & enums (mesurés 19/08)

**Id** : `{CC}-IND-{N}` (indiv A), `{CC}-BIZ-{N}` (biz A), `cmp_{cc}_{n}` (company),
`RC-{CC}-IND-{N}` (client B), `external_client_id={CCC}{N}`. Le préfixe `RC` =
discriminant de famille lisible.

| Enum | Valeurs | Étiquette |
|---|---|---|
| `country_code` | `BF`, `CI`, `CM` | FACT (contrat) |
| `customer_category` | `Individual`, `Business` | FACT |
| `gender` | `MAN`, `WOMAN` | FACT (les deux vus) |
| `currency` | `XAF`(CM), `XOF`(CI/BF) | FACT (CM,CI mesurés) |
| `identity.ID_TYPE` | `CNI`, `Passport` | FACT (les deux vus) |
| `decision_status` | `APPROVED`, `DECLINED` | FACT (les deux vus) |
| `operator` | `MTN CM`, `Nexttel CM`… | FACT partiel |
| `__precomputed_scores.segment` | `Very High`…`Very Low` (`High` vu) | FACT (Annexe E) |
| `company_type` | `Association` vu ; les 6 : EI/SA/SARL/Fondation/SAS/Association | mixte FACT/historique |

---

## 6. Les relations entre entités

- **Business `1—1` Company** (embarquée) · **Company `1—N` sector_assignments** (rangés).
- **Individuel** : sans sous-entité.
- **Famille A `⟂` Famille B** : aucune relation — populations disjointes (§7).

---

## 7. Le fait de domaine CENTRAL — deux populations DISJOINTES et étanches

Preuves convergentes du 19/08 : (1) id `CM-IND-…` (A) vs `RC-CM-IND-…` (B) ;
(2) axes de params disjoints (`seed` vs `run_id`) ; (3) **étanchéité prouvée** — un
id famille A sur endpoint B **ne rend pas un 404 propre, il TIMEOUT** (12 s, 0 octet).
→ Croiser les familles est une **erreur de domaine**, pas une requête valide. À quoi
s'ajoute une **incohérence interne** à la famille B (matrice §4).

---

## 8. Les invariants de domaine (INV-FKR-DOM-*)

- **INV-FKR-DOM-01 — Disjonction étanche des familles** (INT · CRITIQUE) : un id d'une
  famille n'est JAMAIS résoluble par un endpoint de l'autre ; le croisement TIMEOUT.
  *Source : id + params + timeout mesuré. FACT.*
- **INV-FKR-DOM-02 — Cohérence devise↔pays** (COH · MOYEN) : `currency` déterminée
  par `country_code`. *FACT (CM→XAF, CI→XOF).*
- **INV-FKR-DOM-03 — Complétude bornée famille A** (COH · MAJEUR) : 11 champs racine
  + `identity` + `quick_win`, AUCUN champ géo/âge/contact. *FACT.* (lié CORE-04)
- **INV-FKR-DOM-04 — Business embarque une company structurée** (COH · MOYEN) :
  `company_type` ∈ enum, `sector_assignments` rangés. *FACT.*
- **INV-FKR-DOM-05 — Raisons sociales = placeholders** (COH · MAJEUR) : `company_name`
  générique → le Loader compose les vrais noms (UC-08). *FACT.*
- **INV-FKR-DOM-06 — Cohérence des voies de récupération B/C** *(candidat, observation
  ouverte)* : une donnée famille B/C existante doit être récupérable par ses endpoints
  déclarés (`/random`, `/{client_id}`), pas seulement `by-phone`. *Source : matrice §4.
  OBSERVATION — qualification Couche 7.*

---

## 9. RÉPONSE DIRECTE à la question de la Couche 4

- **Entités (6)** : Client Individuel (A), Client Business (A), Company (sous-entité),
  Client Scoré (B, index par téléphone), Scoring Payload (B, via `by-phone`), Loan
  History (C, via `/{client_id}`).
- **Relations** : Business 1—1 Company ; Company 1—N sector_assignments ; A ⟂ B
  (disjonction étanche).
- **Invariants** : DOM-01 (disjonction) → DOM-05 formulés ; DOM-06 en observation
  ouverte (voies de récupération B/C).

---

## 10. HORS PÉRIMÈTRE — reporté

| Sujet | Couche |
|---|---|
| Déroulé d'un tirage, cache clé sur params, itération seed | **5 · FLOWS** |
| Jugement du canal sans auth, frontière A↔B de confiance | **6 · BOUNDARIES** |
| Timeout inter-familles, matrice §4 comme défaut, `sim_number`=external, `playground` | **7 · FAILURE MODES** |

---

## 11. Sources & mesures

1. Captures payloads A + interrogation B/C du **19/08** (lecture seule, `cache/clear` jamais appelé).
2. Matrice des voies d'accès §4 (3 pays témoins, 4 formats d'id, déterminisme vérifié).
3. Contrat OpenAPI 19/08 (enums).
4. Cartographie v1.1 — Confluence `51740675` (structures **historiques** famille B/C).

---

*Couche 4/7 close. Prochaine : 5 · FLOWS — chemin d'un tirage famille A, mécanisme du
cache (clé = jeu de params), itération par seed, points de rupture. 0 test avant la Couche 7.*

---

## Addendum — vérification du doc Loader §7 (19/08, empirique)

Trois affirmations du §7 du doc Loader confrontées au réel — **toutes CONFIRMÉES** :

- **« scoring ≈ 270 champs »** : payload `by-phone` mesuré = **274 feuilles / 286 clés**
  (client 30 + features 95 + metadata 31 + transactions + 4 racines). FACT — le « 270 »
  du doc est exact à ~1,5 % près.
- **« un seul run_id »** : `run_id=99999999999999` → **404** ; SANS `run_id` → **200**
  avec `run_id=20260620123721` renvoyé quand même ; `metadata.run_id` = valeur fixe.
  La famille A n'a **aucun** `run_id`. FACT — l'interprétation du doc est confirmée.
- **« company_type = 6 valeurs »** : 10 business seeds → **les 6 apparaissent** (EI, SA,
  SARL, SAS, Fondation, Association). FACT — l'enum est réel (lève ma réserve « seul
  Association vu le 19/08 » de §5). Genres sur 10 : WOMAN 4 / MAN 6.
