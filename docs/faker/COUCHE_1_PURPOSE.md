# Service Anatomy — faker-service — Couche 1 · PURPOSE

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANATOMY-FKR-2026-001 · Couche 1/7 |
| **Service** | faker-service (« ReadyScore Faker API », `https://faker.fintech4esg.com`) |
| **Propriétaire** | Équipe ReadyScore / Oti (service EXTERNE au périmètre FinZuu) |
| **Version** | v1.0 — première rédaction |
| **Date** | 2026-08-19 |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Méthode** | Service Anatomy (C4 Model + DDD + SRE Production Reviews) |
| **Statut** | APPRENTISSAGE — aucun test écrit à ce stade (R3 : 0 pytest avant la Couche 7) |
| **Périmètre de la page** | La RAISON D'ÊTRE dans l'écosystème, uniquement. Le reste est reporté (voir §6). |

> **Discipline de qualification (rappelée en tête de chaque page).** Cette page
> APPREND, elle ne juge pas. Aucune découverte n'y est étiquetée « bug ». Les
> faits empiriques cités sont des **OBSERVATIONS** ; quand le contrat écrit
> (OpenAPI) ou le CDC les confirme, ils passent **OBSERVATION VALIDÉE**. Rien
> d'autre. Les verdicts viendront après les 7 couches.

---

## 1. La question de la Couche 1

> **À quel besoin RÉEL ce service répond-il dans l'écosystème ? Quelle est sa
> raison d'exister ? Qui l'utilise, et pourquoi son absence bloquerait tout ?**

La Couche 1 ne décrit pas *comment* Faker marche (ça, c'est les Couches 3→7).
Elle établit *pourquoi* il existe, pour qui, et ce qui s'effondre sans lui.

---

## 2. Test R1 — la mission en 3 phrases pour un enfant de 10 ans

> **Faker est une machine qui invente de faux clients de banque africains, avec
> un faux nom, un faux numéro de téléphone et une fausse pièce d'identité, pour
> qu'on puisse tester le système sans jamais toucher à de vraies personnes.**
>
> **Si on lui donne le même petit numéro secret (le « seed »), elle redonne
> toujours exactement le même faux client — comme une photocopieuse, jamais une
> surprise.**
>
> **Et elle sait déjà dire, pour ses faux clients, s'ils mériteraient un crédit
> ou non — pour qu'on n'ait pas besoin de déranger le vrai service qui décide
> des vrais crédits.**

Si je ne peux pas dire ça sans jargon, je n'ai pas compris (R1). Je peux → la
mission est saisie. Les trois phrases nomment déjà les trois raisons d'être :
**fabriquer du faux réaliste**, **le refaire à l'identique**, **remplacer le
scoring réel**.

---

## 3. La raison d'être dans l'ÉCOSYSTÈME (les deux côtés, R1 étendue)

Le PURPOSE n'est pas « un humain appelle Faker au back-office ». Faker n'a pas
d'humain qui l'utilise en écriture : **c'est un générateur en lecture, invoqué
par d'autres systèmes.** Les deux côtés :

### 3.1 Qui le CONSOMME (personne ne l'« écrit » — on le lit)

| Consommateur | Ce qu'il vient chercher | Famille |
|---|---|---|
| **Le Loader FinZuu** (nous) | L'IDENTITÉ de ~2000 clients fictifs (nom, MSISDN, pièce, devise) pour peupler la plateforme de démo | **A** (paramétrable par `seed`, volume illimité) |
| **Le harnais de test ReadyScore** (Oti) | Des payloads de scoring complets + un historique de crédit, pour tester le moteur de décision | **B** (figée au `run_id`) |

> Faker existe donc d'abord **pour d'autres systèmes**, pas pour un opérateur
> humain. C'est la nuance senior de la Couche 1 : sa valeur est en LECTURE, au
> service de consommateurs machine.

### 3.2 Pourquoi son ABSENCE bloquerait tout

- **Sans Faker, le Loader n'a aucune source d'identité clients.** Le CDC §321
  fonde la génération sur DEUX sources : Faker pour les payloads clients, un
  générateur interne pour l'organisationnel. Retirer Faker, c'est amputer la
  moitié « humaine » de la population — les 2000 clients n'ont plus ni nom, ni
  pièce, ni téléphone crédibles.
- **Sans Faker, il n'y a plus de mur d'isolation contre ReadyScore.** Le CDC
  §863 (EF-80) fait de Faker « la source unique et suffisante des décisions de
  scoring », précisément pour que le Loader **n'appelle jamais** le vrai service
  de production ReadyScore. Sans ce mur, tester le Loader toucherait un système
  de prod externe — inacceptable.

### 3.3 L'identité DÉCLARÉE du service (source écrite = contrat OpenAPI)

Le contrat OpenAPI (`readyscore-faker-api-v1`) énonce lui-même sa mission :

> « API de génération de clients et de payloads de test pour ReadyScore. Elle
> sert à créer des données intrinsèques client, Individual ou Business,
> compatibles avec l'endpoint de scoring ReadyScore. »

**OBSERVATION VALIDÉE** : la description officielle confirme les deux rôles —
génération d'identité (Individual/Business) ET compatibilité scoring. La mission
que nous formulons n'est pas déduite : elle est écrite.

---

## 4. Les invariants de niveau PURPOSE (INV-FKR-CORE-\*)

À la Couche 1, on ne formule que les invariants **de mission** — les vérités qui
tiennent quelle que soit l'implémentation. Les invariants structurels (familles,
enum de pays, cache) appartiennent aux Couches 3-4 et sont reportés (§6).

Chacun suit le format canonique : phrase déclarative universelle, source citée,
risque si violé. Le champ « Protégé par » sera rempli quand on écrira les tests
(après la Couche 7).

### INV-FKR-CORE-01 — Fictionnalité totale
| | |
|---|---|
| **Nom** | Pour TOUTE donnée servie par Faker, cette donnée est fictive ; Faker ne crée, ne lit ni ne modifie JAMAIS une entité réelle de la plateforme FinZuu. |
| **Source** | Description OpenAPI (« données de test ») + CDC purpose du Loader |
| **Groupe / Gravité** | COH (cohérence de périmètre) · **CRITIQUE** |
| **Risque si violé** | Contamination de données réelles ; fuite de PII d'une vraie personne sous couvert de « test ». |
| **Protégé par** | *(à définir après Couche 7)* |
| **Statut** | FORMULÉ (Couche 1) |

### INV-FKR-CORE-02 — Isolation de ReadyScore (le mur EF-80)
| | |
|---|---|
| **Nom** | Pour TOUT besoin de décision de scoring du Loader, Faker est la source unique et suffisante ; le Loader n'appelle JAMAIS le service ReadyScore de production. |
| **Source** | CDC §863 · exigence **EF-80** |
| **Groupe / Gravité** | SEC/ISO (isolation) · **CRITIQUE** |
| **Risque si violé** | Couplage du banc de test à un système de production externe ; effets de bord sur ReadyScore réel. |
| **Protégé par** | *(à définir après Couche 7)* |
| **Statut** | FORMULÉ (Couche 1) |

### INV-FKR-CORE-03 — Reproductibilité déterministe par seed
| | |
|---|---|
| **Nom** | Pour TOUT triplet (endpoint famille A, `country_code`, `seed`), l'appel rend TOUJOURS le même client, de façon stable dans le temps. |
| **Source** | CDC §185 (stratégie seed) + Cartographie v1.1 faits F-05/F-06 |
| **Groupe / Gravité** | INT (intégrité) · **BLOQUANT** |
| **Risque si violé** | Un run REAL du Loader n'est plus reproductible → **CR-03 (idempotence) devient invérifiable.** La reproductibilité de Faker est une pré-condition de la nôtre. |
| **Protégé par** | *(à définir après Couche 7)* |
| **Statut** | FORMULÉ (Couche 1) — appui empirique du 19/08 (même `seed=7`/CM rend `CM-IND-572544` à 8 jours d'écart) noté comme **OBSERVATION**, à ériger en cas de test plus tard. |

### INV-FKR-CORE-04 — Complémentarité des sources (contrat de périmètre)
| | |
|---|---|
| **Nom** | Faker fournit l'IDENTITÉ client (Individual / Business) et RIEN de l'organisationnel FinZuu (Company IMF autonome, Lender institutionnel, Dépositaire, Produit, Compte financier). |
| **Source** | CDC §321 + Cartographie v1.1 §2 et §8 |
| **Groupe / Gravité** | COH (périmètre) · **MAJEUR** |
| **Risque si violé** | Attendre de Faker ce qu'il ne fait pas → génération incomplète, ou pire, faux positifs (« Faker fournit la géo » — croyance déjà démentie pour la famille A). |
| **Protégé par** | *(à définir après Couche 7)* |
| **Statut** | FORMULÉ (Couche 1) |

---

## 5. Ce que la Couche 1 fixe pour la suite

- Faker est un **service externe, en lecture, au service de consommateurs
  machine** — pas un CRUD humain. Cela oriente déjà les dimensions de test qui
  auront un objet : `@contract` (le cœur), `@nominal`, `@error` ; et écarte a
  priori `@authn`/`@authz`/`@audit`/`@atomicity`-financière — **à confirmer**
  couche par couche, jamais à décréter ici.
- Les 4 invariants CORE sont les **garanties de mission**. Tout test futur qui
  ne se rattache à aucun invariant (CORE ou d'une couche ultérieure) ne sera pas
  écrit (règle d'or B.6).

---

## 6. HORS PÉRIMÈTRE de cette page — reporté, pour discipline

Pour prouver que je reste dans le périmètre PURPOSE, voici ce que je **refuse
d'aborder ici** et où ça ira :

| Sujet | Couche cible |
|---|---|
| Voisins précis, canaux, qui appelle quoi | **2 · CONTEXT** |
| Stack (FastAPI), Redis comme état, les 15 chemins / 5 familles | **3 · CONTAINERS** |
| Les DEUX populations disjointes (A/B), l'enum `{BF,CI,CM}`, schémas des payloads, champs | **4 · DOMAINS** |
| Le déroulé d'un tirage, le cache clé sur jeu de params complet | **5 · FLOWS** |
| Absence de sécurité (`security:null`), frontière A↔B | **6 · BOUNDARIES** |
| Timeout inter-familles, `playground` 90 s, `MOB_MONEY` creux, `sex` ignoré | **7 · FAILURE MODES** |

> Note de rigueur sur `sex` ignoré : **ne PAS le pré-qualifier bug.** La question
> préalable (Couche 4/7) est « `sex` est-il un paramètre DÉCLARÉ dans le contrat
> OpenAPI courant ? ». S'il n'est pas déclaré, l'ignorer est conforme. Tant que
> ce n'est pas tranché sur pièce, statut = OBSERVATION.

---

## 7. Sources écrites mobilisées (traçabilité)

1. **Contrat OpenAPI** `readyscore-faker-api-v1` — description officielle du service.
2. **CDC Loader** `FZ-CDC-LOADER-2026-001` — §321 (deux sources), §863/EF-80 (isolation), §185 (seed).
3. **Cartographie empirique Faker v1.1** — Confluence `51740675` (`FZ-DOC-FAKER-2026-001`, verrouillée 17/07/2026).
4. **Dossiers empiriques Loader** — `docs/empirical/2026-08-08_faker_maitrise_complete.md`, `2026-08-11_faker_solde_initial.md`, `2026-08-11_faker_senegal_confirme_absent.md`.

---

*Couche 1/7 close. Prochaine couche : 2 · CONTEXT — où Faker vit, avec qui il
parle, sur quels canaux. Aucun test n'est écrit tant que la Couche 7 n'est pas
atteinte.*
