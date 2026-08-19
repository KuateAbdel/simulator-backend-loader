# Service Anatomy — faker-service — Couche 3 · CONTAINERS

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANATOMY-FKR-2026-001 · Couche 3/7 |
| **Service** | faker-service (« ReadyScore Faker API ») |
| **Version** | v1.0 |
| **Date de mesure** | 2026-08-19 (re-mesuré ce jour, NON recopié de la Cartographie de juillet) |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Statut** | APPRENTISSAGE — 0 pytest avant la Couche 7 |
| **Périmètre de la page** | Avec quoi Faker est bâti (stack, persistance, messagerie), sa surface exposée (chemins/familles/schémas), comment ses composants communiquent. PAS le sens des données (→4). |

> **Discipline de qualification.** Chaque affirmation est étiquetée **FACT**
> (preuve mesurée), **DÉDUIT** (inférence logique explicite) ou **HYPOTHÈSE**.
> Rien n'est « bug » ici. Les faits viennent de mesures datées du 19/08/2026,
> lecture seule, `POST /cache/clear` jamais appelé.

---

## 1. La question de la Couche 3

> **De quels composants Faker est-il fait ? Quelle technologie (serveur, cache,
> base, file) ? Quelle surface expose-t-il, et comment ses parties
> communiquent-elles ?**

---

## 2. Méthode de mesure (pourquoi je REFAIS et ne recopie pas)

La Cartographie v1.1 date du 17/07. Un contrat de service peut changer. J'ai
donc **re-mesuré en direct** le 19/08, lecture seule :

| Sonde | Commande | Ce qu'elle établit |
|---|---|---|
| Contrat | `GET /openapi.json` | version OpenAPI, chemins, schémas, paramètres, sécurité |
| Signature serveur | `GET /health` (en-têtes) | `Server:` et `Via:` → la stack réelle |
| État/cache | `GET /v1/faker/cache/health` | présence et version de Redis |

> **Dividende immédiat de la re-mesure (FACT).** Le contrat de juillet listait
> `/v1/faker/client` avec un paramètre `sex`. **Le contrat du 19/08 ne le
> déclare plus** (params réels : `country_code`, `customer_category`, `seed`).
> Conséquence de rigueur : « Faker ignore `sex` » n'est **pas** un bug — le
> paramètre n'est tout simplement pas au contrat, l'ignorer est conforme. Ce
> point, laissé ouvert en Couche 1, est **tranché par la mesure**, pas par l'opinion.

---

## 3. La stack — édition en couches (du bord vers l'application)

| Niveau | Composant | Preuve | Étiquette |
|---|---|---|---|
| Bord (edge) | **Caddy** (reverse-proxy / TLS) | en-tête `Via: 1.1 Caddy` | **FACT** |
| Serveur applicatif | **uvicorn** (serveur ASGI) | en-tête `Server: uvicorn` | **FACT** |
| Framework | **FastAPI + Pydantic** | OpenAPI 3.1.0 auto-généré + schémas `HTTPValidationError`/`ValidationError` (signature exacte de FastAPI) ; validation `literal_error` déjà observée | **DÉDUIT** (forte présomption, non prouvé par une bannière) |
| État | **Redis 7.4.8** (cache) | `cache/health` : `redis_available:true`, `redis_version:"7.4.8"` | **FACT** |
| Base d'entités persistées | *aucune observée* | Faker génère à la volée ; le seul composant à état vu est le cache | **DÉDUIT** (absence de preuve de persistance, pas preuve d'absence) |

- **Identité du service (FACT)** : `title: "ReadyScore Faker API"`,
  `version: "readyscore-faker-api-v1"`, `openapi: 3.1.0`.
- **Sécurité (FACT, reconfirmé 19/08)** : `security: null`, `securitySchemes: null`.
  → renvoyé à `INV-FKR-CTX-03` (Couche 2), qualifié en Couche 6.

---

## 4. Le composant à état — le cache Redis

Mesure `cache/health` du 19/08 (**FACT**) :

```json
{"cache_enabled":true,"redis_available":true,"status":"OK",
 "redis_version":"7.4.8","used_memory_human":"1.12M",
 "db0":{"keys":1,"expires":1,"avg_ttl":582227,"subexpiry":0}}
```

- Redis est **le seul état** de Faker : il mémorise les réponses générées avec
  une **expiration** (`expires`, `avg_ttl`). Le mécanisme précis (clé = jeu de
  paramètres complet) relève du **déroulé**, donc reporté à la **Couche 5 · FLOWS**.
- `POST /v1/faker/cache/clear` existe au contrat mais **n'est JAMAIS appelé** par
  discipline : il réinitialiserait un cache partagé (impact sur les autres
  consommateurs). C'est le seul endpoint mutateur de tout le service.

---

## 5. La surface exposée — 15 chemins · 16 opérations · 5 familles · 3 schémas

Inventaire exact du contrat 19/08 (**FACT**). `scoring-payload` porte GET **et**
POST → 16 opérations pour 15 chemins.

| Fam. | Chemin | Méth. | Paramètres déclarés (au contrat) |
|---|---|---|---|
| **A** | `/v1/faker/client` | GET | `country_code`=[BF,CI,CM], `customer_category`=[Individual,Business], `seed` |
| **A** | `/v1/faker/client/individual` | GET | `country_code`=[BF,CI,CM], `seed` |
| **A** | `/v1/faker/client/business` | GET | `country_code`=[BF,CI,CM], `seed` |
| **B** | `/v1/faker/real-scoring-phone/random` | GET | `run_id`, `country_code`, `customer_category`, `decision_status`, `operator`, `has_taken_loan` |
| **B** | `/v1/faker/real-scoring-payload/random` | GET | `run_id`, `country_code`, `customer_category`, `decision_status`, `has_taken_loan` |
| **B** | `/v1/faker/real-scoring-payload/{client_id}` | GET | `client_id`*, `run_id`, `country_code`, `customer_category`, `decision_status` |
| **B** | `/v1/faker/real-scoring-payload/by-phone` | GET | `mobile_phone`*, `run_id`, `country_code`, `customer_category`, `decision_status` |
| **C** | `/v1/faker/loan-history/random` | GET | `run_id`, `country_code`, `customer_category`, `decision_status`, `has_taken_loan`, `limit`, `include_events`, `event_limit` |
| **C** | `/v1/faker/loan-history/{client_id}` | GET | `client_id`*, `run_id`, `loan_id`, `limit`, `include_events`, `event_limit` |
| **C** | `/v1/faker/playground-client/random` | GET | `run_id`, `country_code`, `customer_category`, `has_taken_loan`, `limit` |
| **C** | `/v1/faker/playground-client/{client_id}` | GET | `client_id`*, `run_id`, `country_code`, `customer_category`, `limit` |
| **D** | `/v1/faker/scoring-payload` | GET | `country_code`=[BF,CI,CM], `customer_category`=[Individual,Business], `seed`, `scoring_date` |
| **D** | `/v1/faker/scoring-payload` | POST | corps `FakerPayloadRequest` |
| **E** | `/v1/faker/cache/health` | GET | — |
| **E** | `/v1/faker/cache/clear` | POST | — *(jamais appelé)* |
| **—** | `/health` | GET | — |

**Les 3 schémas déclarés (FACT)** : `FakerPayloadRequest`, `HTTPValidationError`,
`ValidationError`. **Rien d'autre.** Les payloads clients et scoring **ne sont
adossés à AUCUN schéma OpenAPI** → réponses en JSON dynamique non contraint. Fait
de contrat majeur, à charge de test plus tard.

---

## 6. La partition de surface : `seed` vs `run_id` (structure des familles)

Fait structurel du 19/08 (**FACT**), au niveau de la surface :

- Familles **A** et **D** (`/client*`, `/scoring-payload`) : pilotées par
  **`seed`**, `country_code` en **enum strict [BF,CI,CM]**, **jamais** `run_id`.
- Familles **B** et **C** (`real-scoring-*`, `loan-history`, `playground`) :
  pilotées par **`run_id`**, **jamais** `seed`.

> Ce que cette page NE dit PAS : *pourquoi* ces deux ensembles ne communiquent
> pas, ni qu'ils forment DEUX POPULATIONS DISJOINTES. C'est une propriété de
> **domaine** → reportée à la **Couche 4 · DOMAINS**. Ici, on ne constate que la
> partition des paramètres au contrat.

---

## 7. Communication entre composants

- **Vers l'extérieur** : HTTPS REST **synchrone** requête/réponse. **0 endpoint
  asynchrone ou événementiel** déclaré au contrat (aucun webhook, aucune trace
  d'API de souscription). **FACT** (les 15 chemins sont tous des GET/POST directs).
- **En interne** : uvicorn (app) ↔ Redis (cache). Le lien app↔Redis est
  **DÉDUIT** de `cache/health` (l'app interroge et rapporte l'état Redis).
- **Absence de file de messages (Kafka, etc.)** : aucune preuve au contrat →
  **DÉDUIT** (absence de signal, pas preuve d'absence).

---

## 8. Caractéristique de latence mesurée (fait de composant)

Mesures du 19/08 (**FACT**) :

| Appel | Poids | Temps |
|---|---|---|
| `GET /openapi.json` | 16 082 octets | **~14 s** (et un **timeout à 20 s** au 1ᵉʳ essai) |
| `GET /v1/faker/cache/health` | ~200 octets | rapide (< 2 s) |
| `GET /health` | minime | rapide |

→ Faker est **lent sur les charges non triviales**, avec une latence variable
(un même petit contrat a mis 20 s puis 14 s). C'est une **caractéristique de
composant** ici ; l'**analyse en mode de panne** (timeouts inter-familles,
`playground` lent) est reportée à la **Couche 7 · FAILURE MODES**.

---

## 9. Les invariants techniques (INV-FKR-TECH-*)

### INV-FKR-TECH-01 — Le cache Redis est le seul état
| | |
|---|---|
| **Nom** | Le seul composant à état de Faker est un cache Redis à expiration ; Faker ne persiste aucune entité en base — il génère à la demande. |
| **Source** | `cache/health` (Redis présent) + nature générative ; **DÉDUIT** pour l'absence de base |
| **Groupe / Gravité** | TECH · MOYEN |
| **Risque si violé** | Un état persistant caché rendrait la reproductibilité par `seed` insuffisante à décrire le comportement. |
| **Statut** | FORMULÉ (Couche 3) |

### INV-FKR-TECH-02 — Surface majoritairement non typée
| | |
|---|---|
| **Nom** | Seuls 3 schémas sont déclarés au contrat ; les payloads clients et scoring sont du JSON dynamique non contraint par OpenAPI. |
| **Source** | `openapi.json` `components.schemas` (3) — **FACT** |
| **Groupe / Gravité** | CONTRAT · MAJEUR |
| **Risque si violé** | Un contrat faible autorise une dérive silencieuse de structure entre versions ; le consommateur doit parser défensivement (charge de test réelle). |
| **Statut** | FORMULÉ (Couche 3) |

### INV-FKR-TECH-03 — Communication synchrone REST uniquement
| | |
|---|---|
| **Nom** | Faker n'expose que des opérations HTTP synchrones ; aucun canal asynchrone/événementiel n'est déclaré. |
| **Source** | `openapi.json` (15 chemins, tous GET/POST directs) — **FACT** |
| **Groupe / Gravité** | TECH · MOYEN |
| **Risque si violé** | Une intégration événementielle non documentée créerait un couplage invisible. |
| **Statut** | FORMULÉ (Couche 3) |

*(La sécurité de transport `security:null` est portée par `INV-FKR-CTX-03`,
Couche 2 ; non dupliquée ici.)*

---

## 10. HORS PÉRIMÈTRE de cette page — reporté

| Sujet | Couche cible |
|---|---|
| Les deux populations disjointes A/B, sens des champs, enum pays, contenu des payloads | **4 · DOMAINS** |
| Mécanisme du cache (clé = jeu de params), déroulé d'un tirage | **5 · FLOWS** |
| Jugement de `security:null`, frontière A↔B | **6 · BOUNDARIES** |
| Timeouts, `playground` lent, comportements dégradés | **7 · FAILURE MODES** |

---

## 11. Sources écrites & mesures (traçabilité)

1. **Contrat OpenAPI** capturé le 19/08 → `scratchpad/faker_openapi.json` (openapi 3.1.0, 15 chemins, 3 schémas, `security:null`).
2. **En-têtes `GET /health`** du 19/08 → `Server: uvicorn`, `Via: 1.1 Caddy`.
3. **`GET /v1/faker/cache/health`** du 19/08 → Redis 7.4.8.
4. **Cartographie empirique Faker v1.1** — Confluence `51740675` (référence historique, **corrigée** ici sur le point `sex`).

---

*Couche 3/7 close. Prochaine couche : 4 · DOMAINS — les entités que Faker
manipule, les DEUX populations disjointes, les enums, et les invariants
structurels de la donnée. Aucun test avant la Couche 7.*

---

## Addendum — clarifications du 19/08 (post-publication)

- **Enum pays appliqué au RUNTIME (re-confirmé ce jour)** : `country_code=ZZ` → 422,
  `country_code=cm` (minuscule) → 422 → l'enum est **sensible à la casse**. FACT.
- **Validation `seed` LAXE (asymétrie de contrat)** : `seed=-1` → 200, `seed=abc`
  (non entier) → 200. Contrairement à `country_code` (strict), **`seed` n'est pas
  validé**. FACT — observation `@contract`.
- **Correction cosmétique** : dans INV-FKR-TECH-02, lire `openapi.json` /
  `components.schemas` (deux `code` accolés au rendu).
