# Modèle Entités, Géographie et Volumétrie — notre compréhension consolidée

Pendant de `MODELE_UTILISATEURS.md`. **Ce que chaque mot désigne, combien on en
crée, où on les place, et d'où viennent leurs noms.**

Tous les chiffres sont figés dans `app/core/cdc.py` — une seule source, jamais
recopiée ailleurs.

---

## 1. Le vocabulaire — les 6 niveaux du CDC §6

Trois notions étaient « fréquemment confondues », le CDC les sépare explicitement.

| Niveau | Entité | Définition CDC | Existe où ? |
|---|---|---|---|
| 1 | **Company** | Toute **personne morale** utilisant la plateforme : commerçants, IMF, banques, fondations. **7 types.** | company-service — **RÉELLE** |
| 2 | **Lender** | **Rôle métier porté par une Company**, jamais une entité à part. Apporte le capital finançant les prêts. | *rôle* + notre `lenders_registry` |
| 3 | **Branche** | Unité territoriale de la Company, rattachée à une **Region** | `org_hierarchy` — **LOGIQUE** |
| 4 | **Agence** | Déclinaison de la Branche au niveau d'une **Ville** | `org_hierarchy` — **LOGIQUE** |
| 5 | **Kiosque** | Point physique de dépôt et retrait, rattaché à un **Quartier** | `org_hierarchy` + depositary-service — **RÉELLE** |
| 6 | **Agent** | **Personne physique** de terrain, rattachée à un Kiosque | user-service — **RÉELLE** |

### Les trois équations à ne jamais confondre

```
Une IMF          EST    un type particulier de Company
Un Lender        EST    un rôle porté par une Company   (jamais par une Branche — D-02)
Un Kiosque       EST    un Dépositaire                  (glossaire CDC — D-03)
```

* Une IMF **peut** être Lender de ses propres prêts.
* Une fondation institutionnelle **peut** être Lender **sans** être IMF.
* Une simple boutique enregistrée comme Company **ne peut pas** être Lender.

> **Branche et Agence n'existent pas côté serveur** (`D-05`) : company-service
> n'expose aucune route pour elles, et `CompanyType` n'a aucune valeur `BRANCH`.
> Elles vivent chez nous, dans `org_hierarchy`. **Sans cette collection, `CR-02`
> serait invérifiable** — `CreateDepositaireSchema` ne porte **aucun champ
> géographique** (`name`, `currency`, `company_id` seulement).

---

## 2. La volumétrie complète — tous les chiffres, une seule table

| Entité | Volume | Règle | Source |
|---|---:|---|---|
| Pays | **4** | CM, CI, BF, SN — tout autre pays est rejeté | `EF-05` |
| Régions / Villes / Quartiers | **51 / 50 / 82** | référentiel interne, jamais poussé dans config-service | `OBJ-01` |
| **Companies** | **3 à 5 par pays** → **12 à 20** | dont **2 IMF par pays** (paramétrable) | `UC-07` |
| **Lenders locaux** | **3 par pays** → **12** | rôle porté par une Company | `EF-12` |
| **Lenders institutionnels** | **4** | **Nordic Microfinance, IFC, AFD, BAD** — noms fixes, **jamais Faker** | `UC-08` |
| **Comptes par Lender** | **4** | `CAPITAL`, `INTEREST`, `PENALTY`, `TAXE` — **4 POST explicites**, aucune cascade | `EF-13` / `D-01` |
| **Kiosques = Dépositaires** | **10 à 20 par pays** → **40 à 80** | **1 quartier = 1 Kiosque maximum** | `UC-09` / `D-03` |
| Comptes par Dépositaire | **6** | créés par la **souscription**, pas par la création | `D-DEP-2` |
| **Staff** | **15 à 25 par pays** → **60 à 100** | *(Agents compris — lecture à confirmer)* | `UC-09` |
| **Agents** | ≥ 1 par Kiosque | nombre paramétrable | `EF-17` |
| **Clients** | **2 000** | **1 600 INDIVIDUAL / 400 CORPORATE** | `OBJ-02` / `EF-23` |
| Souscriptions par client | **1 à 3** | produits Collecte | `UC-13` |
| **Produits** | **12** dont **10 créations** | voir §4 | `UC-11` |
| Fenêtre | **180 jours** | + 30 jours de marge sur la licence | `ENF-16` |
| Durée max | **30 minutes** | pour les 2 000 clients | `ENF-01` |

### Les quotas clients — imposés par nous, pas par Faker

| Quota | Cible | Pourquoi c'est nous qui l'imposons |
|---|---|---|
| 80 / 20 Individual / Corporate | 1 600 / 400 | Faker tire naturellement **75/25** — le quota est **forcé par tirage et rejet** (`D-04`) |
| 60 % de moins de 25 ans | 1 200 | **Aucun filtre d'âge chez Faker** — re-tirage imposé |
| **2 femmes pour 1 homme** | ~1 333 / 667 | **Aucun paramètre `sex` chez Faker** — et **le serveur ne valide pas `gender`** (`D-IDN-1`) |
| 20 % des professionnels en agriculture | 80 sur 400 | via `sector_assignments` de Faker |

> 🔴 Le quota de genre est **doublement non protégé** : Faker ne permet pas de le
> demander, et identity-service accepte **n'importe quelle chaîne** dans `gender`
> (mesuré le 09/08 : `"peu importe"` → `201`). **Il n'existe aucun filet hors du nôtre.**

---

## 3. La géographie — comment les Dépositaires se posent sur le territoire

C'est le point le plus réfléchi du modèle, et le plus contraint.

### La règle d'or : un quartier n'héberge qu'un seul Kiosque

> *« Un quartier n'héberge qu'un Kiosque : au-delà, on empilerait plusieurs
> guichets au même endroit, ce qu'un bailleur repérerait. »*

C'est ce qui a fait trancher `D-03` (40-80 Dépositaires, et non 120-200) : avec
**17 à 25 quartiers par pays**, la Côte d'Ivoire aurait dû loger **50 guichets
dans 17 quartiers**, soit 3 empilés au même endroit. Un bailleur institutionnel
qui connaît le terrain l'aurait vu immédiatement.

### Le vrai goulot d'étranglement

Ce n'est **pas** le nombre de villes, mais **le nombre de villes porteuses de
quartiers** — une Agence placée dans une ville sans quartier ne pourrait héberger
aucun Kiosque.

> **Il vaut 2 au Burkina Faso.**

Les 82 quartiers ne couvrent que les grandes villes : Yaoundé, Douala, Abidjan,
Ouagadougou, Bobo-Dioulasso, Dakar, Pikine, Thiès, Saint-Louis.

### L'emboîtement, vérifié AVANT toute écriture

```
Company (IMF)  ──►  Branche (Region)  ──►  Agence (Ville)  ──►  Kiosque (Quartier)  ──►  Agent
```

* Une **Branche par Region distincte** ; deux Agences d'une même région partagent leur Branche.
* Chaque IMF reçoit **au moins une Branche** (postcondition `UC-09`).
* **Seules les Companies IMF portent une hiérarchie.** Un MERCHANT ou un
  FUNDING_PROVIDER n'a ni Branche ni Kiosque — *un bailleur de fonds n'a pas de
  guichet de quartier.*
* Si une ville n'a **aucun quartier**, **aucun Kiosque n'y est créé** et
  l'incident est **journalisé** (`UC-09`, cas alternatif).

> **`organisation.py` ne parle à aucun service.** Il calcule le plan et vérifie sa
> faisabilité **avant le moindre appel HTTP**. C'est la lecture stricte d'`EF-18` :
> rejeter après coup, une fois 40 entités créées **sans possibilité de
> suppression**, n'aurait aucun sens.

**`CR-02`** exige qu'après une génération complète, *« chaque Kiosque ait un
District valide, chaque Agence une Ville valide »*. `verifier_cr02()` le contrôle.

---

## 4. Les produits — 12 au total, 10 créations réelles

| Catalogue | Produits | Créations | Règle |
|---|---:|---:|---|
| **LENDING** | 4 au fichier `loan_json.json` (Annexe E) | **6** | `BNPL` et `ReadyToGo` portent `Category: Any`, **refusée par l'enum serveur** (`422`) → chacun **dédoublé** INDIVIDUAL + CORPORATE (`D-PRD-4`) |
| **COLLECT** | 6 croisant `PolicyType` × `Category` | **4** | **2 sont déjà en base** — « Cotisation 20000/mois » et « plastique » : **RÉUTILISÉS, jamais dupliqués** (`D-PRD-9`) |

**Trois pièges neutralisés dans `catalogue.py`** :

* `policy` est déclarée **optionnelle** au contrat, mais son absence provoque un
  **`HTTP 500`** → on en fournit **toujours** une, complète.
* La Policy est une **référence vivante** : modifier une Policy modifie
  **rétroactivement et silencieusement** tous les Products qui la référencent →
  **une Policy embarquée par Product, jamais un `policy_id` partagé** (`D-PRD-7`).
* Le fichier source annonce un taux jusqu'à **25 %**, or le plafond d'usure
  BEAC/COBAC est de **24 %** *« même en environnement de test »* → **borné** (`EF-35`).

Les 4 nouveaux produits COLLECT portent des **noms métier réels** — jamais
« Produit Test 1 ».

---

## 5. Faker — ce qu'il donne, ce qu'il ne donne pas

### Ce qu'on lui prend

Payloads clients, historique de crédit, scoring, patronymes, formes juridiques,
secteurs d'activité.

### Ce qu'il ne fournit **pas** — et que notre générateur compose

**Ni** Company IMF · **ni** Lender institutionnel · **ni** hiérarchie
Branche/Agence/Kiosque/Agent · **ni** Dépositaire · **ni** Produit · **ni** compte
financier · **ni** date de naissance · **ni** adresse · **ni** occupation · **ni** email.

### Les 4 règles d'usage

| Règle | Détail |
|---|---|
| **`D-FAKER-1`** | **Jamais réutiliser un `client_id` déjà consommé** — vérifier `faker_consumption_ledger` avant **chaque** tirage |
| `seed` variable **obligatoire** | Le cache Redis est **déterministe** et **clé par jeu de paramètres complet** — 24 appels sans varier un paramètre rendent **24 fois le même client** |
| **Un seul `run_id` valide** | `20260620123721` |
| Valider les filtres **avant** l'appel | `country_code=ZZ` retourne **un client au hasard** au lieu d'une erreur |

> 🔴 **Le Sénégal est absent de Faker** — testé sur les deux familles, `404` des
> deux côtés. **500 clients concernés.** C'est l'arbitrage `A-01`, toujours ouvert.

---

## 6. Les noms — composer, jamais inventer, jamais de données de test

C'est la règle que vous aviez posée, et elle a un fondement mesuré.

**Faker rend `company_name = "Test Business CM 748"`** (15 tirages sur 3 pays,
08/08). Or `UC-08` exige *« un nom métier crédible »*, et la démonstration cible
**Nordic Microfinance, IFC, AFD et BAD**, qui connaissent le terrain africain réel.
`DEMO_Test Business CM 748` ne passerait pas.

### Le principe : **rien n'est inventé à partir de rien**

| Matière | Provenance — **réelle** |
|---|---|
| Patronymes | Faker (Kouassi, Kabore, Tamadou, Ouedraogo…) |
| Formes juridiques | Faker (SA, SARL, SAS, Établissement, Fondation, Association) |
| Secteurs | Faker (`sector_assignments`) |
| Villes et quartiers | `Loader_Base_FinZuu_v1.1.xlsx` |

Le Loader ne fait que les **assembler** :

```
"Test Business CI 200"      ->      "DEMO_SARL Kouassi Textile"
```

> **C'est la différence entre inventer et composer.** Là où la source amont est
> pauvre, le Loader porte la richesse — exactement comme pour la géographie des
> Kiosques, que depositary-service ne sait pas stocker.

**Le préfixe `DEMO_`** est porté par **chaque** donnée générée (`EF-63`, `OBJ-05`).
Ce n'est pas un confort de nommage : **trois services n'ont aucun `DELETE`**
(identity, account, depositary). Le préfixe est **notre seule réversibilité**.

**Reproductibilité (`ENF-15`)** : tout tirage dérive du `run_id`. Deux exécutions
de même `run_id` produisent **exactement les mêmes entités**.

---

## 7. L'unicité — quatre règles, quatre raisons différentes

| Champ | Règle | Pourquoi |
|---|---|---|
| **`client_id` Faker** | Jamais consommé deux fois | `D-FAKER-1` — `faker_consumption_ledger` |
| **MSISDN** | Unique sur les 2 000 clients | `EF-25`, exigence CDC |
| **email** | Unique côté user-service | `INV-USR-02` — et le User cascade **consomme l'unicité** de l'adresse du dirigeant |
| **`name`** (Product, Dépositaire) | ⚠️ **Aucune unicité serveur** | `ANO-PRD-UNIQ-01` — gérer le cas **plusieurs correspondances**, retenir **la plus ancienne** |

**`GET`-avant-`POST` systématique**, sur tous les services (`D-PRD-2`, `D-DEP-3`,
`D-CLI-5`, `D5`). On évite le `HTTP 400` plutôt que de le découvrir — d'autant que
`ANO-CPY-BUG-06` a montré qu'un `4xx` ne doit **jamais** être rejoué : il signale
notre payload, le rejouer le répéterait.

---

## 8. Ce qui reste ouvert

| # | Question | Nature |
|---|---|---|
| `A-01` | **Sénégal absent de Faker** — 500 clients | **Arbitrage** — Yaniv |
| `A-05` | Permissions par rôle | **Arbitrage produit** — Yaniv |
| — | Agents compris ou en sus des 15-25 staff/pays | **Lecture du CDC** — Yaniv |
| `A-04` | Où persister les ~700 prêts simulés | 7ᵉ collection ? |

---

*Sources : CDC v1.2 §6, `UC-07` à `UC-13`, `EF-05`/`12`/`13`/`17`/`23`/`25`/`35`/`63` ·
`D-01` à `D-09` · `app/core/cdc.py` · `app/services/{organisation,generateur,catalogue}.py` ·
`docs/empirical/2026-08-08_faker_maitrise_complete.md` · mesures serveur des 8 et 9 août 2026.*
