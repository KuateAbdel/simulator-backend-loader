# Service Anatomy — faker-service — Couche 6 · BOUNDARIES

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANATOMY-FKR-2026-001 · Couche 6/7 |
| **Service** | faker-service (« ReadyScore Faker API ») |
| **Version** | v1.0 |
| **Date** | 2026-08-19 |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Statut** | APPRENTISSAGE — 0 pytest avant la Couche 7 |
| **Périmètre** | Les frontières de CONFIANCE : qui authentifie, qui autorise, qui audite, où bascule la confiance. PAS le catalogue de pannes (→7). |

> **Discipline.** C'est ici qu'on QUALIFIE le canal sans auth (constaté en Couche 2,
> non jugé). **FACT** / **DÉDUIT**. Les candidats-anomalies restent OBSERVATION —
> leur verdict BUG/ANOMALIE tombe en Couche 7.

---

## 1. La question de la Couche 6

> **Quelles frontières de confiance traverse-t-on ? Qui authentifie ? Qui autorise ?
> Qui audite ? Où l'argent (ou l'irréversible) change de main ?** → Réponse en §7.

---

## 2. Le constat brut — une seule frontière réelle : le transport

| Frontière possible | État mesuré (19/08) | Étiquette |
|---|---|---|
| **Transport (TLS)** | Chiffré, terminé par l'edge `Caddy` (`Via: 1.1 Caddy`) | **FACT** — seule frontière réelle |
| **Authentification** | `security: null`, `securitySchemes: null` ; aucun appel refusé sans en-tête | **FACT** — AUCUNE |
| **Autorisation (rôles)** | Aucun rôle, aucun tenant, aucun scope | **FACT** — AUCUNE |
| **Audit / corrélation** | En-têtes `/health` : `content-type`, `date`, `server`, `via` — **aucun** `x-request-id`/corrélation | **FACT (sur /health)** — aucune trace |

→ La confiance ne bascule **nulle part au niveau applicatif** : tout appelant a le
même droit total. La seule frontière est le chiffrement du canal.

---

## 3. La QUALIFICATION du canal sans authentification

Question senior : **est-ce acceptable ?** On qualifie, on ne s'indigne pas.

- **Ce qui l'atténue (FACT)** : Faker ne sert que des données **fictives** (INV-FKR-CORE-01),
  aucune PII réelle, aucun argent. Pour un générateur de données de test, l'absence
  d'auth en lecture est un **choix défendable** — le risque de divulgation est nul
  (rien de réel n'est exposé).
- **Ce qui reste un vrai point de frontière (le mutateur)** : `POST /v1/faker/cache/clear`
  est **non authentifié** et agit sur un **état PARTAGÉ** (le cache Redis commun à tous
  les consommateurs). N'importe qui peut réinitialiser le cache que le harnais ReadyScore
  et le Loader utilisent. **C'est la seule opération à effet de bord**, et elle est
  ouverte. → candidat-anomalie de frontière, qualifié en Couche 7 (`AN-FKR-BND`).

→ **Verdict de couche** : l'absence d'auth **en lecture** est acceptable (données
fictives) ; l'absence d'auth **sur le mutateur d'état partagé** est le seul vrai
sujet de frontière.

---

## 4. La frontière de DOMAINE — A ↔ B

Au-delà de la sécurité, Faker a une frontière **interne** : la ligne entre les deux
populations. La franchir n'est pas « refusé » proprement — ça **TIMEOUT** (Couche 4).
C'est une frontière **non gardée** : le service ne rejette pas le croisement, il pend.
→ traité comme mode de panne en Couche 7.

---

## 5. Les dimensions de test — verdict d'applicabilité (confirmé)

La Couche 1 anticipait ; la Couche 6 **tranche sur pièce** :

| Dimension | Applicable à Faker ? | Raison (mesurée) |
|---|---|---|
| `@authn` | **NON** | `security:null` — rien à authentifier |
| `@authz` | **NON** | aucun rôle/tenant — pas d'IDOR possible (données fictives publiques) |
| `@audit` | **NON** | aucune trace/corrélation ; pas d'exigence sur un générateur |
| `@atomicity` (financière) | **NON** | aucun argent |
| `@nominal`, `@error`, `@contract`, `@state`(cache) | **OUI** | le cœur de l'effort de test |

→ Écarter `@authn/@authz/@audit/@atomicity` n'est **pas** un oubli : c'est une décision
motivée par la nature du service. (Rappel du piège junior : appliquer les 8 dimensions
partout aveuglément.)

---

## 6. Les invariants de frontière (INV-FKR-BND-*)

- **INV-FKR-BND-01 — Aucune frontière d'auth/autorisation applicative** (SEC · contexte) :
  tout appelant a le même droit ; la seule frontière est le TLS de l'edge. *FACT.*
  Acceptable EN LECTURE (données fictives, CORE-01).
- **INV-FKR-BND-02 — Le mutateur d'état partagé est non gardé** (SEC · MAJEUR, candidat) :
  `cache/clear` (seul effet de bord) est ouvert et affecte tous les consommateurs.
  *OBSERVATION — verdict Couche 7.* Discipline : **jamais appelé** de notre part.
- **INV-FKR-BND-03 — Aucune traçabilité** (AUD · MOYEN) : pas d'en-tête de corrélation ;
  une requête n'est pas attribuable. *FACT (sur /health).*
- **INV-FKR-BND-04 — Frontière de domaine A↔B non gardée** (INT · renvoi DOM-01) :
  le croisement des familles n'est pas refusé, il TIMEOUT. *FACT.*

---

## 7. RÉPONSE DIRECTE à la question de la Couche 6

- **Qui authentifie / autorise / audite ?** — **Personne.** Faker est ouvert, sans rôle,
  sans trace. Seul le TLS (edge Caddy) chiffre le canal.
- **Où bascule l'irréversible ?** — Sur **un seul point** : `POST /cache/clear`, mutateur
  d'état **partagé** et **non authentifié**. C'est la seule frontière à effet, et elle est
  ouverte.
- **Acceptabilité** : lecture sans auth = OK (données fictives) ; mutateur sans auth =
  seul vrai sujet, porté en Couche 7.

---

## 8. HORS PÉRIMÈTRE — reporté

| Sujet | Couche |
|---|---|
| Verdict BUG/ANOMALIE sur `cache/clear` ouvert, timeout inter-familles, `AN-FKR-B1/B2`, `sim_number`, `playground`, latence | **7 · FAILURE MODES** |

---

## 9. Sources & mesures

1. En-têtes `GET /health` du 19/08 (`Server: uvicorn`, `Via: 1.1 Caddy`, aucun en-tête de corrélation).
2. Contrat OpenAPI 19/08 (`security: null`, `securitySchemes: null`, `cache/clear` non authentifié).
3. Frontière A↔B : timeout mesuré (Couche 4).

---

*Couche 6/7 close. Prochaine — et dernière : 7 · FAILURE MODES — le catalogue des
pannes ET la QUALIFICATION (BUG / ANOMALIE / OBSERVATION) de tous les candidats, qui
alimentera le rapport de synthèse à Oti.*
