# Service Anatomy — faker-service — Couche 7 · FAILURE MODES

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANATOMY-FKR-2026-001 · Couche 7/7 |
| **Service** | faker-service (« ReadyScore Faker API ») |
| **Version** | v1.0 |
| **Date** | 2026-08-19 |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Statut** | APPRENTISSAGE COMPLET — les 7 couches closes. C'est ICI que tombe la QUALIFICATION. |
| **Périmètre** | Comment Faker casse, les classes de bugs, le pire scénario, ET le verdict BUG/ANOMALIE/OBSERVATION de chaque candidat. |

> **Discipline de qualification (appliquée à la lettre).** Un candidat n'est un
> **BUG** que si les 3 éléments sont réunis : preuve reproductible + spec écrite
> identifiée + contradiction explicite. Sinon : **ANOMALIE** (spec muette, à
> clarifier avec Oti) ou **OBSERVATION**. On ne crie pas « bug » — c'est le piège
> junior. Tous les faits ci-dessous sont mesurés le 19/08, lecture seule,
> `cache/clear` JAMAIS appelé.

---

## 1. La question de la Couche 7

> **Comment ce service peut-il CASSER ? Quelles classes de bugs attendre ? Quel est
> le pire scénario ?** → Réponse + qualification en §3 et §4.

---

## 2. Le catalogue des modes de panne (FM-FKR-*)

| # | Mode de panne | Preuve mesurée 19/08 |
|---|---|---|
| **FM-1** | **Croisement de familles → le service PEND** | id famille A sur `payload/{id}` → TIMEOUT 12 s, 0 octet |
| **FM-2** | **`playground-client` inutilisable** | `playground/random` CM → TIMEOUT 35 s, 0 octet |
| **FM-3** | **Sélecteurs `/random` morts (sauf phone)** | `payload/random` & `loan-history/random` → 404 (3 pays témoins) |
| **FM-4** | **`payload/{client_id}` mort alors que la donnée existe** | 404 sur 4 formats d'id, pendant que `by-phone` ET `loan-history/{id}` rendent 200 pour le même client |
| **FM-5** | **Mutateur d'état partagé non gardé** | `POST /cache/clear` non authentifié (contrat) — **non testé par discipline** |
| **FM-6** | **`sim_number` n'est pas un numéro** | famille B : `sim_number == external_client_id` (`CMC293057`), pas le téléphone |
| **FM-7** | **`has_taken_loan=true` sans repli (CM)** | `phone/random?...&has_taken_loan=true` → 404 ; `=false` → client |
| **FM-8** | **Latence variable / timeouts** | 1–10 s par appel + timeouts SSL en lot |
| **FM-9** | **Piège du cache** | 4 `/random` identiques → 1 client (mesure Couche 5) |

---

## 3. LA QUALIFICATION — arbre de décision appliqué à chaque candidat

Colonnes : Preuve reproductible ? · Spec écrite consultée ? · Contradiction explicite ?

| Candidat | Preuve | Spec écrite | Contradiction | **VERDICT** | Destination |
|---|---|---|---|---|---|
| FM-4 (`payload/{id}` mort, donnée existante) | ✅ | OpenAPI déclare l'endpoint + réponse 200 ; 404 aussi documenté | **partielle** (incohérence inter-endpoints prouvée, pas de phrase de spec « doit résoudre ») | **ANOMALIE (forte — la plus proche d'un bug)** | Rapport Oti |
| FM-3 (`/random` morts sauf phone) | ✅ (3 pays) | OpenAPI déclare `/random` | spec muette sur la garantie de données | **ANOMALIE** | Rapport Oti |
| FM-1 (croisement familles → hang) | ✅ | HTTP implique 4xx, pas un hang ; pas de spec FinZuu | spec muette | **ANOMALIE (dispo)** | Rapport Oti |
| FM-2 (`playground` timeout 35 s) | ✅ | endpoint déclaré | pas de SLA écrit | **ANOMALIE (dispo)** | Rapport Oti |
| FM-5 (`cache/clear` non gardé) | contrat (non testé) | pas de politique écrite | principe général seulement | **ANOMALIE (sécu état partagé)** | Rapport Oti |
| FM-6 (`sim_number` = external) | ✅ | famille B non typée (0 schéma) | contre-intuitif, pas de spec | **ANOMALIE (qualité de données)** | Rapport Oti |
| FM-7 (`has_taken_loan=true` 404) | ✅ | pas de spec sur la dispo des données | — | **OBSERVATION** | Clarif. Oti (lié FM-3) |
| FM-8 (latence/timeouts) | ✅ | pas de SLA | — | **OBSERVATION** | Surveillance |
| FM-9 (piège du cache) | ✅ | cache déterministe = **comportement voulu** | aucune | **OBSERVATION VALIDÉE** (correct, piège d'USAGE) | Aucune — géré par INV-FKR-FLOW-04 |

---

## 4. LE MÉTA-RÉSULTAT (et pourquoi c'est un résultat de senior)

- **0 BUG confirmé.** Aucun candidat ne réunit les 3 éléments : il n'existe pas de
  **spec écrite FinZuu** que le comportement contredise frontalement (Faker est un
  service Oti, sans CDC FinZuu opposable ; son OpenAPI déclare les endpoints mais
  documente aussi le 404). **Crier « bug » ici serait le réflexe junior** — celui qui
  m'a fait annoncer « 4 bugs » sur company-service quand il y en avait 1.
- **6 ANOMALIES** (FM-1 à FM-6) — reproductibles, contraires à l'attente raisonnable,
  mais sans spec écrite pour trancher → **à clarifier avec Oti**. FM-4 est la plus
  proche d'un bug (incohérence interne prouvée) : elle deviendra **BUG** si Oti confirme
  que `payload/{client_id}` doit résoudre un id que `phone/random` rend.
- **3 OBSERVATIONS** (FM-7/8/9), dont une **OBSERVATION VALIDÉE** (le cache marche comme
  prévu ; c'est un piège d'usage, pas un défaut).

> **Le pire scénario** (SRE) : un consommateur naïf de la famille B enchaîne
> `payload/random` (404) puis `payload/{id}` (404) puis croise une famille (hang 12 s+)
> — il conclut « Faker est vide/cassé » alors que la donnée est là, derrière `by-phone`.
> C'est exactement l'erreur que j'ai faite avant d'interroger avec témoins.

---

## 5. Ce qui alimente le RAPPORT DE SYNTHÈSE à Oti (prochaine étape)

Les 6 anomalies ci-dessus constituent la matière du document unique
« **Anomalies Faker à remonter à Oti** » (canal choisi). Chacune y ira avec :
preuve reproductible (commande + réponse), 3 pays témoins, et l'attente à confirmer.
**Priorité** : FM-4 (incohérence interne) > FM-3/FM-1/FM-2 (disponibilité) > FM-5/FM-6.

---

## 6. Les invariants de résilience (INV-FKR-FAIL-*)

- **INV-FKR-FAIL-01 — Un refus doit être un code, pas un hang** (DISPO · MAJEUR, *candidat*) :
  une requête invalide (croisement de familles) doit rendre un 4xx borné, jamais un
  timeout. *Violé de fait (FM-1) — ANOMALIE.*
- **INV-FKR-FAIL-02 — Une donnée existante doit être récupérable par ses endpoints
  déclarés** (INT · MAJEUR, *candidat*) : cf. FM-3/FM-4. *ANOMALIE, à confirmer Oti.*
- **INV-FKR-FAIL-03 — Le cache est un comportement, pas une panne** (USAGE) : itérer =
  varier un paramètre (INV-FKR-FLOW-04). *Tenu côté Loader.*

---

## 7. RÉPONSE DIRECTE à la question de la Couche 7

- **Comment ça casse** : ça **pend** (croisement de familles, `playground`, latence),
  ça **ment par 404** (voies `/random` et `payload/{id}` alors que la donnée existe),
  et ça **expose un mutateur d'état partagé** sans garde.
- **Classes de bugs attendues** : disponibilité (hangs), cohérence inter-endpoints
  (404 sur donnée existante), qualité de données (`sim_number`), sécurité d'état partagé.
- **Verdict discipliné** : **0 bug confirmé, 6 anomalies (Oti), 3 observations.**

---

## 8. Sources & mesures

1. Toutes les mesures des Couches 3→6 (contrat, payloads, matrice d'accès, seed/cache, en-têtes).
2. `playground/random` CM → TIMEOUT 35 s (19/08).
3. Croisement de familles → TIMEOUT 12 s (19/08).
4. Cartographie v1.1 — Confluence `51740675` (`playground` lent = L-04 historique, **reconfirmé aggravé**).

---

*Les 7 couches sont closes. **L'apprentissage de faker-service est complet.** Étape
suivante (hors de cette page) : (a) les Test Scenarios `TS-FKR-*` adossés aux invariants
`INV-FKR-*`, désormais autorisés (R3 satisfaite) ; (b) le rapport de synthèse « Anomalies
Faker à remonter à Oti ».*

---

## Addendum — nature de FM-4 clarifiée (19/08, post-publication)

Question laissée ouverte à la publication : FM-4 (`payload/{client_id}` → 404)
est-il une **cassure d'index** ou une **dépendance au cache** ? Test décisif :
`by-phone` (qui rend le payload) PUIS `payload/{même client_id}` → **toujours 404**.
Donc `by-phone` ne « réchauffe » pas l'index de la voie `/{id}` : **FM-4 est une
cassure d'index/routage GÉNUINE, indépendante de l'état du cache** (DÉDUIT
renforcé). → Priorité de FM-4 dans le rapport Oti **confirmée**.
