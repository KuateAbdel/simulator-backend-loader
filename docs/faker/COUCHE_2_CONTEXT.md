# Service Anatomy — faker-service — Couche 2 · CONTEXT

| Champ | Valeur |
|---|---|
| **Référence** | FZ-ANATOMY-FKR-2026-001 · Couche 2/7 |
| **Service** | faker-service (« ReadyScore Faker API ») |
| **Version** | v1.0 |
| **Date** | 2026-08-19 |
| **Auteur** | Kuate Abdel Yaniv — QA Lead / SDET Loader FinZuu |
| **Statut** | APPRENTISSAGE — 0 pytest avant la Couche 7 |
| **Périmètre de la page** | Où Faker vit, qui sont ses VOISINS, comment les acteurs externes l'utilisent. PAS la stack (→3), PAS les entités (→4). |
| **Couche amont** | [Couche 1 · PURPOSE](COUCHE_1_PURPOSE.md) |

> **Discipline de qualification.** Page d'APPRENTISSAGE. Faits empiriques =
> OBSERVATION ; confirmés par le contrat/CDC = OBSERVATION VALIDÉE. Aucun « bug »
> ici.

---

## 1. La question de la Couche 2

> **Où se place Faker dans l'écosystème ? Quels sont ses voisins ? Comment les
> acteurs externes l'utilisent-ils, et sur quels canaux ?**

La Couche 1 a dit *pourquoi* Faker existe. La Couche 2 dit *où* il est branché et
*avec qui* il parle — sans encore ouvrir sa mécanique interne (Couche 3).

---

## 2. Position dans l'écosystème — un satellite EXTERNE en amont

Faker n'est **pas** l'un des 9 services FinZuu. C'est un service **externe**,
propriété d'Oti / équipe ReadyScore, déployé hors du périmètre que le Loader
orchestre. Sa place topologique est celle d'une **feuille amont** : une source de
données que l'on lit, qui ne dépend d'aucun service FinZuu pour répondre.

```
        ┌───────────────────────┐
        │   Oti / ReadyScore     │  (propriétaire, hors périmètre FinZuu)
        │  ┌─────────────────┐   │
        │  │  faker-service  │   │  ← CE QU'ON ÉTUDIE
        │  └───────┬─────────┘   │
        └──────────┼─────────────┘
                   │ HTTPS REST (lecture seule, public, sans auth)
         ┌─────────┴──────────┐
         │                    │
   famille A             famille B
   (identité)            (scoring)
         │                    │
         ▼                    ▼
  ┌─────────────┐      ┌────────────────────────┐
  │ Loader      │      │ Harnais de test        │
  │ FinZuu (NOUS)│      │ ReadyScore (Oti)       │
  └──────┬──────┘      └────────────────────────┘
         │ COMPOSE puis ÉCRIT (le Loader fait le pont)
         ▼
  ┌───────────────────────────────────────────────┐
  │ Les 9 services FinZuu                          │
  │ user · config · identity · company · account · │
  │ product · client · depositary · collect        │
  └───────────────────────────────────────────────┘
```

**Lecture du schéma** : Faker ne touche **aucun** des 9 services FinZuu. C'est le
**Loader qui fait le pont** — il LIT Faker (famille A), puis COMPOSE et ÉCRIT
vers les 9 services. Faker et les 9 services **ne se connaissent pas**.

---

## 3. Les voisins — cartographie de contexte

### 3.1 Ses CONSOMMATEURS (qui l'appelle)

| Voisin | Sens | Ce qu'il consomme | Famille | Volume |
|---|---|---|---|---|
| **Loader FinZuu** (nous) | lecture | Identité client (nom, MSISDN, pièce, devise) | **A** | massif (~2000, itéré par `seed`) |
| **Harnais de test ReadyScore** (Oti) | lecture | Payloads de scoring + historique de crédit | **B** | faible (figé au `run_id`) |

### 3.2 Le système ÉMULÉ (sa raison contextuelle)

Faker produit des données « **compatibles avec l'endpoint de scoring
ReadyScore** » (contrat OpenAPI). Il est donc le **doublure de test** du moteur
ReadyScore : il en imite les entrées/sorties pour qu'on n'ait pas à solliciter le
vrai moteur (rappel Couche 1 : c'est le mur EF-80).

### 3.3 Ce que Faker N'A PAS comme voisin

- **Aucun humain** : pas d'UI, pas de back-office. Faker n'est jamais « utilisé »
  par un opérateur — seulement invoqué par des systèmes. *(fait de contexte,
  confirmé Couche 5 sur le déroulé)*
- **Aucun consommateur aval FinZuu** : rien, dans les 9 services, n'appelle
  Faker. Le seul pont est le Loader, et il va dans l'autre sens (il lit Faker,
  il n'est pas lu par Faker).
- **Redis n'est pas un voisin** : c'est un composant **interne** de Faker →
  reporté à la Couche 3 (CONTAINERS). Discipline de périmètre.

---

## 4. Comment les acteurs externes l'utilisent (usage de contexte)

| Acteur | Appel typique (famille) | Intention |
|---|---|---|
| Loader | `GET /v1/faker/client/individual?country_code=CM&seed=N` (A) | Tirer une identité reproductible, itérer `seed` pour la diversité |
| Loader | `GET /v1/faker/client/business?...` (A) | Idem + objet `company` |
| Harnais ReadyScore | `GET /v1/faker/real-scoring-payload/random?run_id=...` (B) | Récupérer un payload scoré complet |

- **Protocole** : HTTPS REST **synchrone** requête/réponse. Base
  `https://faker.fintech4esg.com`. Pas de webhook, pas de flux asynchrone
  observé *(intégration événementielle vérifiée en Couche 3)*.
- **Canal ouvert** : l'accès est **public, sans authentification**
  (`security: null` au contrat). **OBSERVATION VALIDÉE** (le contrat le déclare).
  La *qualification* de ce choix (est-ce une frontière de confiance acceptable
  pour un générateur ?) est **reportée à la Couche 6 · BOUNDARIES** — ici on
  constate le canal, on ne le juge pas.

---

## 5. Les invariants de contexte (INV-FKR-CTX-*)

### INV-FKR-CTX-01 — Découplage total des 9 services FinZuu
| | |
|---|---|
| **Nom** | Faker ne communique avec AUCUN des 9 services FinZuu ; toute intégration à la plateforme passe par le Loader, qui LIT Faker puis compose. |
| **Source** | CDC §321 (deux sources séparées) + recon serveur (Faker hors du réseau des 9 services) |
| **Groupe / Gravité** | ISO (isolation topologique) · MAJEUR |
| **Risque si violé** | Un couplage caché Faker↔service FinZuu fausserait l'isolation du banc de test et brouillerait la provenance des données. |
| **Statut** | FORMULÉ (Couche 2) |

### INV-FKR-CTX-02 — Feuille amont, autoportante
| | |
|---|---|
| **Nom** | Faker ne dépend d'AUCUN service FinZuu pour répondre ; il n'a aucun consommateur aval dans les 9 services. |
| **Source** | Position topologique observée (schéma §2) |
| **Groupe / Gravité** | ISO · MOYEN |
| **Risque si violé** | Une dépendance aval introduirait un point de panne externe dans un service censé être une source autonome. |
| **Statut** | FORMULÉ (Couche 2) |

### INV-FKR-CTX-03 — Canal public sans authentification (fait de contexte)
| | |
|---|---|
| **Nom** | L'accès à Faker se fait sur un canal HTTPS public ne requérant aucun credential. |
| **Source** | Contrat OpenAPI `security: null`, `securitySchemes: {}` |
| **Groupe / Gravité** | SEC · *(gravité à statuer en Couche 6)* |
| **Risque si violé** | *(analyse de frontière de confiance reportée Couche 6 — ne pas juger ici)* |
| **Statut** | OBSERVATION VALIDÉE (contrat) — qualification différée Couche 6 |

---

## 6. HORS PÉRIMÈTRE de cette page — reporté

| Sujet | Couche cible |
|---|---|
| Redis, FastAPI, les 15 chemins / 5 familles, présence/absence de Kafka | **3 · CONTAINERS** |
| Les deux populations disjointes A/B en détail, enum pays, schémas | **4 · DOMAINS** |
| Le déroulé d'un tirage, le cache | **5 · FLOWS** |
| Jugement du canal sans auth, frontière A↔B | **6 · BOUNDARIES** |
| Comportements de panne (timeouts) | **7 · FAILURE MODES** |

---

## 7. Sources écrites mobilisées

1. **Contrat OpenAPI** `readyscore-faker-api-v1` — base URL, `security: null`, description.
2. **CDC Loader** `FZ-CDC-LOADER-2026-001` §321 (deux sources de génération).
3. **Cartographie empirique Faker v1.1** — Confluence `51740675`.
4. **Recon serveur** (lecture seule) — Faker hors du réseau des 9 services FinZuu.

---

*Couche 2/7 close. Prochaine couche : 3 · CONTAINERS — avec quoi Faker est bâti
(FastAPI, Redis comme état), ses 15 chemins en 5 familles, ses composants et leur
communication. Aucun test avant la Couche 7.*
