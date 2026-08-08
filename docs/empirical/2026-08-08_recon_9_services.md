# Réconciliation CDC ↔ Diagrammes UML ↔ Contrats serveur

| | |
|---|---|
| **Date** | 8 août 2026 |
| **Objet** | Aligner le code du Loader sur ce qui est **déjà établi empiriquement**, et arbitrer les divergences de nommage entre les diagrammes UML et les contrats serveur réels. |
| **Sources de vérité** | Confluence — pages Service Anatomy (espace TST) et Cartographie Faker v1.1. Aucun fait n'est re-sondé ici. |
| **Statut** | Document d'arbitrage. Remplace la note de reconnaissance du 8 août, qui re-découvrait à tort des faits déjà documentés. |

## 0. Règle de préséance appliquée

Reprise du Document Maître §0, précisée pour le cas des divergences de nommage :

1. **CDC Loader v1.2 (FZ-CDC-LOADER-2026-001) — autorité suprême sur le métier.** Ce qu'il faut créer, en quelle quantité, sous quelles règles.
2. **Contrat serveur (OpenAPI runtime) — autorité sur le fil.** Valeurs d'enum, champs requis, codes HTTP. Un enum serveur ne se discute pas : tout écart produit un HTTP 422.
3. **Pages Service Anatomy — autorité sur le comportement observé.** 49 disciplines `D-XXX` validées empiriquement, réutilisées telles quelles.
4. **Diagrammes UML — représentation.** Ils se corrigent quand ils divergent du serveur. Leur sémantique métier reste valable.

> **Principe directeur** : un nom qui change ne change pas le métier. Le CDC dit « Fonds institutionnel » ; le serveur écrit `FUNDING_PROVIDER`. C'est la même chose. Le Loader écrit ce que le serveur attend, et garde le vocabulaire du CDC dans ses libellés et ses rapports.

---

## 1. Sources déjà établies — à réutiliser, jamais à re-sonder

| Service | Page Confluence | Disciplines livrées |
|---|---|---|
| user-service | 56360965 | 43 écarts, `D-USR`, flow 3 requêtes, 22 invariants |
| company-service | 59834370 | 22 invariants `INV-CPY`/`INV-LIC`/`INV-CROSS`, `D1`→`D12`, 9 anomalies |
| product-service | 60358657 | `D-PRD-1`→`D-PRD-8`, 9 enums, `INV-PRD-01`→`07`, 5 anomalies |
| client-service | 60555267 | `D-CLI-1`→`D-CLI-7`, schémas bruts intégraux, `INV-CLI-01`→`05` |
| collect-service | 62521348 | `D-COL-16`, `FRA-194`→`FRA-198`, copie figée |
| depositary-service | 63340549 | `D-DEP-1`→`D-DEP-8`, `FRA-199`→`FRA-205`, 12/12 SDET |
| Faker fintech4esg | 51740675 | 15 endpoints, `F-01`→`F-13`, `L-01`→`L-05`, mapping Faker→FinZuu |

**Deux zones sans couverture, à connaître :**

- **account-service** — seul service du périmètre sans page Anatomy. Le Document Maître le note : *« D-ACC-XXX formelle toujours à extraire »*. C'est là que se situe le Trou #2 (§3.1).
- **collect-service et depositary-service** — leurs pages renvoient le détail Q1‑Q8 à l'historique de version, non consulté. Les disciplines et anomalies, elles, sont bien sur la page courante.

---

## 2. Arbitrage des divergences — diagrammes UML vs serveur

### 2.1 `CompanyType` — trois noms à corriger dans `02_class.puml`

| CDC §6.2 (métier) | `02_class.puml` | **Serveur (fait foi)** |
|---|---|---|
| IMF | `IMF` | `IMF` |
| Banque | `BANK` | `BANK` |
| Fondation | `FONDATION` | `FONDATION` |
| Merchant | `MERCHANT` | `MERCHANT` |
| Agence | `AGENCE` | **`AGENCY`** |
| Kiosque | `KIOSQUE` | **`KIOSK`** |
| Fonds institutionnel | `FONDS_INSTITUTIONNEL` | **`FUNDING_PROVIDER`** |

Source : company-service Q2 (7 valeurs) ; l'incohérence `FONDATION` en français est déjà cataloguée `ANO-CPY-NAMING-02`.

**Impact Loader** : les 4 Lenders institutionnels (Nordic Microfinance, IFC, AFD, BAD) portent `type = FUNDING_PROVIDER`. Le vocabulaire CDC est conservé dans les libellés (`name`, rapports), la valeur serveur dans le payload.

### 2.2 Les 4 comptes du Lender — l'intention du CDC tient, le mécanisme change

`UC-10` / `EF-13` postulent 4 comptes par Lender. `03_sequence_lender.puml` marque une cascade « à vérifier ».

**Arbitrage** : l'intention métier du CDC est **maintenue intégralement** — chaque Lender possède bien ses 4 comptes `CAPITAL`/`INTEREST`/`PENALTY`/`TAXE`. Seul le mécanisme change : **aucune cascade n'existe**, le Loader les crée par 4 `POST /api/v1/accounts/` explicites. Preuve : §3.1.

Corollaire à corriger dans `03_sequence_lender.puml` : remplacer les 4 flèches « [HYPOTHÈSE À VÉRIFIER] » par 4 créations explicites assumées.

### 2.3 Catalogue produits — 4 au CDC, 6 sur le fil

`Annexe E` définit 4 produits LENDING. L'enum serveur `ProductCategory` n'accepte que `INDIVIDUAL`/`CORPORATE` (`INV-PRD-04`, HTTP 422 sur « ANY »).

**Arbitrage déjà tranché par `D-PRD-4`** : BNPL et ReadyToGo sont créés en 2 exemplaires chacun → **6 Products LENDING**, pas 4. Le catalogue métier de l'Annexe E est respecté ; sa matérialisation technique en compte 6.

**Piège à ne pas confondre** (product-service Q2) : `ProductSegment` accepte `ANY`, `ProductCategory` non. Le split ne concerne que `category`. Le `segment` porte la segmentation par risque de l'Annexe E (`VERY_LOW`→`VERY_HIGH`).

### 2.4 Onboarding client — le CDC décrit 2 étapes, le contrat en impose 1

`UC-13` décrit l'onboarding puis la souscription produit comme deux étapes distinctes. `OnboardClientSchema` exige `product_id` **dès le premier appel** (client-service Q2, schéma brut).

**Arbitrage, déjà porté par `D-PRD-6` et `D-CLI-1`** : créer les Products COLLECT en premier → onboarder avec **un** `product_id` déjà choisi → `PUT /clients/subscribe` pour les 2ᵉ et 3ᵉ produits. Le « 1 à 3 produits » du CDC est respecté.

Champs requis absents des diagrammes, à ajouter dans `05_sequence_onboarding.puml` : `channel` (`USSD`/`MOBILE`/`OFFICE`), `segment` (`ANY`…`VERY_HIGH`), `language` (`en`/`fr`, défaut `en`).

### 2.5 Ordre de construction — Document Maître §9 vs `09_activity.puml`

| Source | Ordre |
|---|---|
| Document Maître §9 | `user → config → identity → account → product → company → depositary → client → subscription → transaction` |
| `09_activity.puml` | Phase 2 = Organisation (company), Phase 3 = Produits |

**Arbitrage : le Document Maître §9 l'emporte** — c'est un ordre de **dépendances**, tandis que le diagramme d'activité décrit des **phases de progression** pour l'opérateur. Les contraintes réelles, toutes documentées :

- `depositary` exige `company_id` **et** `product_id` (`D-DEP-1`, product-service Q5 : 404 « Product not found »)
- `client` exige `product_id` dès l'onboarding (`D-PRD-6`)
- `company` n'exige **rien** de `product`

Créer les Products avant les Companies est donc toujours sûr, l'inverse ne l'est pas. `09_activity.puml` reste valable comme vue opérateur, à condition que la Phase 3 soit terminée avant la Phase 4.

### 2.6 Nomenclature crédit — question `Q-01` de la carto Faker, close

La Cartographie Faker v1.1 laissait ouverte la divergence Nano/Macro (Faker) vs Nano/Micro/BNPL/ReadyToGo (documents internes).

**Close par le CDC v1.2, Annexe E** : le catalogue officiel est **Nano / Macro / BNPL / ReadyToGo**. Faker ne *produit* que Nano et Macro dans ses `loan-history` — c'est sa donnée d'historique, pas notre catalogue. Le Loader **crée** les 4 produits de l'Annexe E ; il **lit** ce que Faker lui donne.

### 2.7 `id_expire_on` — une entité, trois contrats

| Service | Schéma | `id_expire_on` | `_id` |
|---|---|---|---|
| identity-service | `CreateIdentitySchema` | **requis**, `date-time` non nullable | absent |
| company-service | `Identity` (embed) | optionnel, `anyOf[date-time, null]` | **requis** |
| client-service | `Identity` (embed) | optionnel, `anyOf[date-time, null]` | **requis** |

Les deux embeds sont des copies désynchronisées du schéma d'identity-service, qui lui l'exige. L'omettre fait planter le serveur : `'NoneType' object has no attribute 'isoformat'` (`ANO-CLI-IDENTITY-01`, HAUTE — preuve Q3.3 vs Q3.4).

**`D-CLI-2` et `D-DEP-5` ne sont donc pas des précautions : c'est la seule lecture correcte du contrat amont.** Toujours fournir `id_expire_on`, quel que soit le service visé. Et toujours fournir `_id` dans un embed Identity.

### 2.8 Autres écarts UML déjà couverts par les disciplines

| Point | Discipline existante |
|---|---|
| `identity.type` envoyé, écrasé en `CORPORATE` par le serveur | `D-CLI-4` |
| `id_number` alphanumérique majuscules strict | `D-CLI-3` |
| `Client.status` figé à `PENDING` | `D-CLI-8` / `OBS-CLI-STATUS-01` |
| 6 comptes Dépositaire, par Dépositaire et non par produit | `D-DEP-2` / `OBS-DEP-ACCOUNTS-SCOPE-01` |
| Statut Dépositaire inefficace sur collectes et retraits | `D-DEP-8` / `FRA-203` |
| Aucune RBAC sur depositary-service → ROOT exclusif | `D-DEP-7` / `FRA-205` |
| Policy = référence vivante, jamais partagée | `D-PRD-7` / `INV-PRD-07` |
| `measure` toujours choisi explicitement | `D-PRD-8` |
| `Collect.product/client/depositary` = copie figée | `D-COL-16` |
| Aucun montant négatif ou nul vers collect-service | `FRA-195` |
| `Company.currency` perdu à la persistance | `D-DEP-4` / `FRA-199` |

---

## 3. Les trois seuls points réellement nouveaux

### 3.1 Trou #2 — les 4 comptes du Lender : **aucune cascade n'existe**

Sondage lecture seule du 8 août. Comptage exhaustif des 42 comptes de l'environnement TEST :

```
 7 OPERATION   = cascade création Company   (7 companies × 1)
30 (6 types)   = cascade Dépositaire        (5 souscriptions × 6)
 5 CHECKING    = cascade onboarding Client  (client-service)
──
42  ✓  aucun compte résiduel
```

**0 Company sur 7** porte les 4 comptes Lender. La totalité des comptes s'explique par trois cascades déjà documentées — aucune cascade Lender ne peut se cacher là‑dedans. company-service n'expose par ailleurs aucune route liée aux comptes.

Détail complet : `2026-08-08_TROU-2_comptes_financiers_lender.md`.

**Impact** : `LenderRegistryEntry.*_account_id` reste `UUID | None` — un Lender partiellement initialisé est un état légitime (`UC-10`, cas d'exception). Contrat de création relevé : `account_number, type, external_id, external_class, owner_type, owner_id, owner_name`, avec `owner_type=COMPANY`, `external_class=COMPANY_SERVICE`.

**Reste non vérifié** : que la création explicite aboutisse. account-service n'expose **aucun DELETE** — toute écriture y est définitive. Décision Super-Admin requise avant de tester.

### 3.2 Nginx — le vhost API est le seul manquant

État au 8 août 03:23 UTC :

| Hôte | DNS | Certificat | HTTP |
|---|---|---|---|
| `simul.fintech4esg.com` | ✅ | ✅ `CN=simul.fintech4esg.com` → 18/10/2026 | 503 |
| `simul.api.fintech4esg.com` | ✅ | ❌ vhost par défaut `CN=collabora.finzuu.com` | 000 |

Le Document Maître §2 dit *« ni DNS complet, ni Nginx configuré »* : **deux fois trop pessimiste**. Le DNS est complet pour les deux, le vhost frontend existe déjà avec son certificat — son 503 signifie seulement que le Next.js n'est pas déployé. L'action A3 se réduit à créer le vhost `simul.api.fintech4esg.com` + certificat.

### 3.3 `FRA-48` / `ÉCART-43` — le blocage config-service est levé

`ÉCART-43` (user-service, Casquette 5, 27/07) relevait HTTP 403 pour ROOT sur config-service, et le script `loader_config_service.py` s'arrête encore sur ce cas. **Ce 403 n'est plus reproductible** : toutes les lectures ROOT sur config-service répondent 200, et les 4 pays cibles sont lisibles.

La seconde moitié d'`ÉCART-43` (HTTP 401 code 4013 sur product-service) n'a pas été re-testée — à ne pas considérer comme levée.

---

## 4. Impacts consolidés sur la conception du Loader

Repris tels quels des pages Anatomy, sans reformulation.

**Séquencement**

1. Products (catalogue global, création unique) avant Depositaries et Clients — `D-PRD-3`
2. Company → License (aucune cascade, création explicite) — `INV-CROSS-05`
3. Dépositaire créé, **puis** souscription : c'est la souscription qui crée les 6 comptes — `D-DEP-1`, `D-DEP-2`
4. Client onboardé avec un `product_id` en main, 2ᵉ/3ᵉ produit via `PUT /clients/subscribe` — `D-CLI-1`, `D-CLI-7`

**Idempotence et écriture**

- GET-avant-POST systématique — `D-PRD-2`, `D-DEP-3`, `D-CLI-5`, `D5` (company)
- Aucune unicité serveur sur `name` (Product, Dépositaire) → gérer le cas **plusieurs correspondances**, retenir la plus ancienne — `ANO-PRD-UNIQ-01`
- Retry sûr : idempotence excellente côté user-service, pattern « no-op detection » — Casquette 3 SRE
- Ne jamais partager un `policy_id` — `D-PRD-7`

**Résilience et volumétrie**

- Concurrence **limitée à 20‑30 workers asyncio** — au‑delà, dégradation silencieuse sans 429 (`H14`/`H15`)
- Pagination `?limit=<N>&page=<P>` 1‑based, `limit` cappé à 100 côté Loader — `H20`
- Anti‑brute‑force : jamais plus de 3 tentatives de login — `INV-USR-19`
- Coût estimé : **10 000 à 15 000 requêtes user-service** sur la campagne complète (3 requêtes par User)
- Tokens : access 4 h, refresh 7 j, auth 10 min. **Le Loader doit implémenter `/auth/refresh`**, que la WebApp ignore — `ÉCART-38`

**Parsing et journalisation**

- Wrapper de réponse custom `{status_code, response_type, description, data}` — **pas** le format FastAPI natif
- Datetime défensif : suffixe `Z` parfois absent — `H11`
- Normaliser `_id` vs `id` selon l'endpoint — `ANO-CPY-CONTRAT-12`, `VIOL-06.1`
- Générer ses propres `X-Request-Id` UUIDv4 : le serveur ignore ceux du client — `H18`/`H19`
- **SIEM local obligatoire** : les Logs backend sont pollués à 99 % par les kube-probes — `H23`

**Sécurité**

- ROOT exclusif sur depositary-service — `D-DEP-7`
- Ne pas présumer ROOT omnipotent partout ; prévoir un repli — `ÉCART-43`
- Ne jamais décoder le JWT côté client pour déduire des droits : il ne porte aucune permission — `ÉCART-39`

**Faker**

- `seed` variable obligatoire, le cache Redis est déterministe — `L-01`, `F-05`, `F-06`
- Un seul `run_id` valide : `20260620123721` — `F-03`, `L-02`
- Valider les filtres **avant** l'appel : `country_code=ZZ` retourne un client au hasard — `F-11`, `CT-04`
- `playground-client/random` peut expirer à 25 s — prévoir un repli — `L-04`
- Faker ne fournit **ni** Company IMF, **ni** Lender institutionnel, **ni** hiérarchie Branche/Agence/Kiosque/Agent, **ni** Dépositaire, **ni** Produit, **ni** compte financier : générateur interne pour tout cela — §7 carto

**Périmètre à porter par le Loader, hors UML**

- **12 rôles métier à créer** (Super-Admin, Admin, Marketing, Compliance, Collecte, Comptable, Branche, Employé/IT, Marchand, Kiosque, Agent, Client), mappés vers les 5 `UserType` techniques — Gap 1, user-service Casquette 5

---

## 5. Corrections à porter aux diagrammes

| # | Fichier | Correction |
|---|---|---|
| 1 | `02_class.puml` | `AGENCE`→`AGENCY`, `KIOSQUE`→`KIOSK`, `FONDS_INSTITUTIONNEL`→`FUNDING_PROVIDER` |
| 2 | `02_class.puml` | `CreateCompanySchema` : ajouter `industries`, `sectors` (minItems 1), `address` |
| 3 | `02_class.puml` | `Identity` embarquée : `_id` fourni par l'appelant |
| 4 | `03_sequence_lender.puml` | Les 4 comptes deviennent 4 créations explicites — l'hypothèse est levée |
| 5 | `05_sequence_onboarding.puml` | Ajouter `channel`, `segment`, `language` |
| 6 | `09_activity.puml` | Noter que la Phase 3 (Produits) doit précéder la Phase 4 (Dépositaires) |
| 7 | `11_deployment.puml` | Écart Nginx : seul le vhost API manque |

---

*Document d'arbitrage — aucun fait re-sondé, chaque impact rattaché à sa source Confluence.*
