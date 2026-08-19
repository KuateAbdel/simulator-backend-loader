# Service Anatomy — faker-service — Couche 5 · FLOWS

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANATOMY-FKR-2026-001 · Couche 5/7 |
| **Service** | faker-service (« ReadyScore Faker API ») |
| **Version** | v1.0 |
| **Date de mesure** | 2026-08-19 (mécanisme seed/cache re-prouvé en direct) |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Statut** | APPRENTISSAGE — 0 pytest avant la Couche 7 |
| **Périmètre** | Le CHEMIN d'une opération, la séquence, les points de rupture. PAS le jugement des pannes (→7), PAS les frontières de confiance (→6). |

> **Discipline.** **FACT** / **DÉDUIT** / **HYPOTHÈSE**. Le mécanisme du cache et du
> seed est **re-prouvé** ce jour, pas recopié de juillet. Rien n'est « bug » ici.

---

## 1. La question de la Couche 5

> **Quel chemin suit une opération ? Quelle séquence d'étapes ? Où sont les points
> de rupture ?** → Réponse synthétique en §9.

---

## 2. Méthode — interrogation seed/cache du 19/08 (lecture seule, résiliente)

Mesure en arrière-plan (tentatives multiples, car latence variable). Latences
relevées par appel : **1,0 s à 10,2 s**, plus des **timeouts** en cours de lot →
fait de flux consigné (§8). `POST /cache/clear` jamais appelé.

---

## 3. Flux A — Tirage d'un client famille A (le SEUL flux utilisé par le Loader)

**Entrée** : `country_code` (∈ BF/CI/CM) + `seed`. **Sortie** : identité client.

Séquence (étapes internes **DÉDUITES**, effet **mesuré**) :

```
1. Requête GET /client/individual?country_code=X&seed=S
2. [interne] clé de cache = jeu de paramètres COMPLET
3. hit  -> renvoie la copie mémorisée (Redis, avec TTL)
   miss -> génère l'identité, la met en cache, la renvoie
4. Réponse : 11 champs (identité + quick_win)
```

Preuve du déterminisme (**F1, FACT**) : deux appels `CM&seed=7` rendent le **même**
`CM-IND-572544` — et le **même** à 8 jours d'écart (mesure du 11 et du 19/08).

## 4. Le mécanisme du CACHE — PROUVÉ le 19/08

**F3 (FACT)** : 4 appels **identiques** à `real-scoring-phone/random?run_id&country_code=CM`
(pas de `seed`) → **1 seul client distinct** (`RC-CM-IND-CMC380240` les 4 fois),
malgré des latences différentes (6,0 / 10,2 / 1,9 / 3,9 s).

**F4 (FACT)** : changer **un** paramètre change l'entrée — `has_taken_loan=false`
rend un client, `has_taken_loan=true` rend autre chose (ici un **404**, §6).

→ **Conclusion (FACT)** : le cache est **clé sur le jeu de paramètres complet**. Deux
appels aux mêmes params rendent toujours la même chose ; changer n'importe quel
paramètre donne une autre entrée. C'est le mécanisme de juillet, **reconfirmé**.

## 5. Le mécanisme du SEED — déterminisme + diversité

- **F1 déterminisme (FACT)** : `(country, seed)` → toujours le même client.
- **F2 diversité (FACT)** : seeds 1..6 sur CM → **6 clients distincts, 0 collision**
  (`CM-IND-492978`, `840500`, `616605`, `975173`, `522081`, `801102`).
- **F5 défaut (FACT)** : `seed=0` (`CM-IND-897151`) ≠ `seed` absent (`CM-IND-753482`)
  → le comportement par défaut **n'est pas** `seed=0`.

→ **Le flux de diversité du Loader** : pour obtenir N clients distincts et
**reproductibles**, on **fait varier `seed`** (le seul axe qui contourne le cache en
famille A). C'est exactement ce dont dépend CR-03 (idempotence d'un run).

## 6. Observation du 19/08 — `has_taken_loan=true` sans match (CM)

`real-scoring-phone/random?...&country_code=CM&has_taken_loan=true` → **404**, tandis
que `=false` rend un client. **OBSERVATION** : soit aucun client CM « a pris un prêt »
n'est indexé aujourd'hui, soit un filtre sans repli. **Je ne spécule pas la cause** ;
qualification en Couche 7 (possible parent de `AN-FKR-B1`).

## 7. Flux B et Flux D (renvois)

- **Flux B — Business** : identique à A + objet `company` embarqué (Couche 4).
- **Flux D — Famille B** : `phone/random` → `mobile_phone` → `by-phone` → payload.
  **Deux des trois voies sont rompues** (matrice Couche 4, `AN-FKR-B1/B2`).

## 8. Les POINTS DE RUPTURE des flux (le cœur de la Couche 5)

| # | Rupture | Preuve | Conséquence |
|---|---|---|---|
| R1 | **Latence / timeout** | 1–10 s par appel + timeouts en lot (19/08) | un flux peut PENDRE → timeout client obligatoire, retries |
| R2 | **Piège du cache** | F3 : 4 `/random` identiques → 1 client | échantillonner `/random` mesure le CACHE, pas la distribution (fausse « 100 % APPROVED ») |
| R3 | **Étanchéité inter-familles** | id A sur endpoint B → TIMEOUT (Couche 4) | ne JAMAIS croiser les familles |
| R4 | **Voies B rompues** | matrice Couche 4 | un flux D naïf échoue sur 2 endpoints /3 |

## 9. RÉPONSE DIRECTE à la question de la Couche 5

- **Chemin nominal** : `params → cache (clé = jeu de params complet) → [génération si miss] → réponse`.
- **Séquence de diversité** : varier `seed` (famille A) — le seul axe qui échappe au cache, déterministe et sans collision.
- **Points de rupture** : latence/timeout (R1), piège du cache sur `/random` (R2), étanchéité inter-familles (R3), voies B rompues (R4).

## 10. Les invariants de flux (INV-FKR-FLOW-*)

- **INV-FKR-FLOW-01 — Déterminisme du tirage seedé** (INT · BLOQUANT) : `(country,seed)` → même client, stable dans le temps. *F1, FACT.* (concrétise CORE-03)
- **INV-FKR-FLOW-02 — Diversité sans collision** (INT · MAJEUR) : des seeds distincts rendent des clients distincts. *F2, FACT (6/6).*
- **INV-FKR-FLOW-03 — Cache clé sur jeu de params complet** (TECH · MAJEUR) : mêmes params → même réponse ; un param changé → autre entrée. *F3/F4, FACT.*
- **INV-FKR-FLOW-04 — La distribution ne s'obtient jamais par `/random` naïf** (règle d'usage · MAJEUR) : itérer une population = varier un paramètre ; sinon on relit le cache. *Corollaire de FLOW-03.*

---

## 11. HORS PÉRIMÈTRE — reporté

| Sujet | Couche |
|---|---|
| Qualification de `security:null`, frontière A↔B comme frontière de confiance | **6 · BOUNDARIES** |
| Timeout/latence comme mode de panne, `AN-FKR-B1/B2`, `has_taken_loan=true` 404, `playground` lent | **7 · FAILURE MODES** |

---

## 12. Sources & mesures

1. Interrogation seed/cache du **19/08** (F1–F5), lecture seule, latences relevées.
2. Déterminisme inter-jours (11/08 vs 19/08 : même `seed=7`/CM → `CM-IND-572544`).
3. Matrice des voies d'accès (Couche 4).
4. Cartographie v1.1 — Confluence `51740675` (mécanisme cache **historique**, reconfirmé ici).

---

*Couche 5/7 close. Prochaine : 6 · BOUNDARIES — les frontières de confiance (qui
authentifie, qui autorise), le canal public sans auth qualifié, la frontière A↔B.
0 test avant la Couche 7.*

---

## Addendum — déterminisme robuste (19/08, post-publication)

`INV-FKR-FLOW-01` reposait sur 1 seed / 1 pays. Re-sondé sur **3 paires
supplémentaires**, 2 appels chacune : `CI/individual/seed3` → même
(`CI-IND-858177`), `BF/individual/seed5` → même (`BF-IND-785373`),
`CM/business/seed9` → même (`CM-BIZ-729540`). Le déterminisme tient **à travers
les pays ET les endpoints (individual + business)**. FACT — l'invariant est
désormais sur base solide, plus sur un seul point.
