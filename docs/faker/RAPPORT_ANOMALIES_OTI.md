# Anomalies faker-service — à remonter à Oti

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANOMALIES-FKR-2026-001 |
| **Service** | `faker-service` (« ReadyScore Faker API », `https://faker.fintech4esg.com`) — équipe Oti |
| **Date des mesures** | 2026-08-19 (lecture seule stricte, `POST /cache/clear` JAMAIS appelé) |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Base méthodo** | Service Anatomy `faker-service` (7 couches, dossier `Faker`, réf `FZ-ANATOMY-FKR-2026-001`) |
| **Environnement** | `run_id = 20260620123721` (unique) · pays témoins : CM, CI, BF |

> **Nature du document.** Ce ne sont **pas des bugs confirmés** : faute de spec
> écrite opposable côté Faker, chaque point est une **ANOMALIE reproductible** dont
> l'attente reste à **confirmer par Oti**. Chaque anomalie porte : preuve (commande
> + réponse), témoins 3 pays, résultat attendu à valider. **Aucune donnée réelle,
> aucun effet de bord** (que des GET).

---

## Synthèse — 6 anomalies confirmées (A-4 retirée après re-test), par priorité

| # | Anomalie | Sévérité | Certitude |
|---|---|---|---|
| A-1 | `real-scoring-payload/{client_id}` → 404 pour un client qui EXISTE (récupérable par `by-phone` et `loan-history/{id}`) | **Haute** (incohérence interne) | reproductible + témoins |
| A-2 | Sélecteurs `/random` (payload, loan-history, playground) → 404, sauf `phone/random` | **Haute** (disponibilité) | 3 pays, répété |
| A-3 | Croiser les familles (id « simple » sur endpoint scoring) → **TIMEOUT**, pas un 404 | **Haute** (disponibilité / DoS latent) | témoin : id `RC-` → 404 rapide |
| ~~A-4~~ | **RETIRÉE** — `playground/random` rend 404 rapidement (3/3), timeout transitoire | — | re-test infirmant |
| A-5 | `POST /cache/clear` **non authentifié** sur un cache **partagé** | **Moyenne** (sécurité) | **inféré du contrat, NON testé** |
| A-6 | Famille B : `sim_number` = `external_client_id` (ce n'est PAS le numéro) | **Basse** (qualité) | constant 3/3 |
| A-7 | Famille A : `sim_number` uniformément à 8 chiffres → trop court pour CM (9) et CI (10) | **Basse** (qualité) | 15 clients (5/pays), tous 8 |

---

## A-1 — `real-scoring-payload/{client_id}` mort alors que la donnée existe

**Observé (CM, CI, BF)** : un client obtenu par `phone/random` a bien un payload
(via `by-phone`) ET un historique (via `loan-history/{id}`), mais `payload/{id}`
répond 404 — sur les **4 formats d'identifiant** (`client_id`, `external_client_id`,
`sim_number`, `client_uid`).

```
# le payload EXISTE :
GET /v1/faker/real-scoring-payload/by-phone?mobile_phone=<tel>&run_id=20260620123721   -> 200 (client, features, metadata...)
# l'historique du MÊME client répond :
GET /v1/faker/loan-history/RC-CM-IND-CMC637928?run_id=20260620123721                    -> 200
# mais le payload par id ne résout pas :
GET /v1/faker/real-scoring-payload/RC-CM-IND-CMC637928?run_id=20260620123721            -> 404 "No scoring payload found for this client."
```

**Vérifié** : ce n'est **pas** un effet de cache — appeler `by-phone` (succès) puis
`payload/{id}` laisse toujours 404. Cassure d'index/routage isolée à cet endpoint.
**Attendu à confirmer** : `payload/{client_id}` doit résoudre un `client_id` que
`phone/random` vient de rendre.

## A-2 — Sélecteurs `/random` morts (sauf phone)

**Observé (CM, CI, BF)** :
```
GET /v1/faker/real-scoring-phone/random?run_id=...&country_code=CM     -> 200
GET /v1/faker/real-scoring-payload/random?run_id=...&country_code=CM   -> 404 (bare, + tous filtres)
GET /v1/faker/loan-history/random?run_id=...&country_code=CM           -> 404
```
**Attendu à confirmer** : si `phone/random` rend une population, `payload/random` et
`loan-history/random` devraient en rendre une aussi (ou documenter pourquoi non).

## A-3 — Croisement de familles → TIMEOUT au lieu de 404

**Observé** : un identifiant « simple » (type `CM-IND-572544`, sans préfixe `RC`) sur
un endpoint de scoring ne rend pas une erreur — il **pend**.
```
GET /v1/faker/real-scoring-payload/CM-IND-572544   -> TIMEOUT (12 s, 0 octet)
```
**Attendu à confirmer** : un identifiant invalide/hors-population doit rendre un
**4xx borné**, jamais un timeout (risque de déni de service pour un consommateur).

## A-4 — RETIRÉE après re-test (19/08)

Au premier appel, `playground-client/random` avait timeout à 35 s. **Re-testé 3 fois :
404 en < 1,5 s à chaque fois.** Le timeout initial était donc **transitoire** (latence),
pas un défaut stable. Le **404** rejoint **A-2** ; le timeout ponctuel rejoint l'observation
« latence variable ». **Aucune anomalie distincte ici.** *(Leçon SDET : ne jamais conclure
sur un seul échantillon — c'est ce re-test qui a fait tomber le point.)*

## A-5 — Mutateur d'état partagé non authentifié

**Constat (contrat, NON exécuté par discipline)** : `POST /v1/faker/cache/clear` n'exige
aucune authentification (`security: null`), alors qu'il réinitialise le **cache Redis
partagé** par tous les consommateurs (harnais ReadyScore + Loader).
**Attendu à confirmer** : protéger le seul endpoint à effet de bord, ou confirmer que
l'ouverture est intentionnelle et sans risque.

## A-6 — Famille B : `sim_number` n'est pas un numéro de téléphone

**Observé (famille B, CM/CI/BF — constant 3/3)** : `sim_number` vaut la MÊME valeur que
`external_client_id` (`CMC668650`, `CIC441894`, `BFC1024510`), pas le numéro — le vrai
numéro est dans `mobile_phone`.
**Attendu à confirmer** : `sim_number` devrait porter un MSISDN, ou être renommé.

## A-7 — Famille A : `sim_number` de longueur invalide (CM, CI)

**Observé (famille A, 15 clients — 5 par pays, 15/15 identiques)** : le `sim_number` est
**uniformément à 8 chiffres** (partie nationale) quel que soit le pays, alors que le plan
national exige 9 pour CM et 10 pour CI (BF = 8, correct).
```
CM: +237 03924260 / +237 29054531  -> 8 chiffres (attendu 9)
CI: +225 96337708 / +225 10071533  -> 8 chiffres (attendu 10)
BF: +226 81649674 / +226 15649420  -> 8 chiffres (correct)
```
À comparer à la famille B `mobile_phone`, qui respecte la longueur nationale
(CM 9 / CI 10 / BF 8). **Attendu à confirmer** : le `sim_number` famille A doit respecter
le plan de numérotation national (E.164) par pays.

---

## Observations (NON anomalies — pour contexte, aucune action attendue)

- **`has_taken_loan=true` sans match (CM, CI, BF — 3/3)** : `phone/random?...&has_taken_loan=true`
  → 404 sur les 3 pays, `=false` → client. Indisponibilité systématique de données, pas un défaut.
- **`playground-client/random`** : rend 404 rapidement (3/3), avec un timeout transitoire vu une
  fois — cf. A-2 (404) et latence.
- **Latence variable** : 1–10 s par appel sur les endpoints légers, timeouts intermittents.
- **Cache déterministe** : deux appels aux mêmes paramètres rendent le même résultat —
  **comportement voulu** (le consommateur itère en variant un paramètre).

---

## Ce qui est confirmé côté conception (aucune action)

- **Un seul `run_id`** (`20260620123721`) : tout autre → 404 ; sans paramètre, la valeur
  est renvoyée quand même. La diversité vient du `seed` (famille A).
- **Payload scoring ≈ 270 champs** : mesuré 274 feuilles / 286 clés.
- **`company_type` = 6 valeurs** : EI, SA, SARL, SAS, Fondation, Association — vues sur
  les **3 pays** (CM + CI + BF), devise **XOF** correcte pour CI/BF.
- **Pays hors périmètre REJETÉ (bug juillet corrigé)** : `country_code=ZZ` → 422 (famille A)
  / 404 (famille B). L'ancien comportement « ZZ rend un client au hasard » (Cartographie
  F-11) **n'est plus reproductible** — Faker valide désormais l'enum au runtime
  (sensible à la casse : `cm` minuscule → 422).

---

*Toutes les mesures sont reproductibles en lecture seule. Le détail par couche est dans
le dossier Confluence `Faker` (Service Anatomy `faker-service`, 7 couches).*
