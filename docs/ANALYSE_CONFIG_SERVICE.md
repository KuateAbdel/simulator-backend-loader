# config-service — analyse d'architecture, et ce que le Loader en tire

| | |
|---|---|
| **Date** | 9 août 2026 |
| **Nature** | Analyse d'architecture, **pas un rapport de bugs**. Aucun ticket créé. |
| **Périmètre** | Comprendre le service pour concevoir juste. Le corriger n'est pas notre rôle. |
| **Sources** | 7 pages Confluence lues intégralement · OpenAPI · mesures serveur du 9 août |

> **Sur la légitimité de cette analyse.** Corriger config-service n'est pas notre
> périmètre. **Le comprendre l'est** — nous en dépendons pour propager notre
> configuration, et le boss demande de pouvoir agir dessus. On ne conçoit pas une
> intégration sur un service qu'on n'a pas compris. Et ce qu'on y apprend nous
> sert à ne pas répéter les mêmes choix.

---

## 1. Ce que j'avais manqué — aveu de méthode

Je travaillais depuis l'OpenAPI seul. **Sept pages Confluence existent** et je ne
les avais jamais lues, alors que ma propre discipline dit de lire les sources
avant de sonder.

| Page | Espace | Contenu |
|---|---|---|
| `11. Service Config` | FinZuu | Vue métier |
| `00` → `05` | FinZuu | Stratégie, 25 endpoints, ~105 tests, invariants, trace d'exécution |
| `Service Anatomy — config-service` | TST | C4 couches 1-2-3 |
| **`Anomalies config-service — Brill`** | TST | **13 anomalies documentées, 5 tickets `RC-*`** |

**Ce que ça m'a coûté** : j'ai re-découvert seul l'asymétrie écriture/lecture
(`ANO-CFG-ASYM-08`) et le `PUT` à 9 champs (`ANO-CFG-DUP`), documentés depuis
juin. Du temps perdu, et le risque de conclusions divergentes.

---

## 2. Le modèle de données réel — mesuré

### Les trois entités, telles qu'elles sont

```
Country   { _id, iso_name, name_fr, name_en, dial_code, region, continent,
            cities[string], currencies[Currency], telcos[Telco], is_active }

Telco     { _id, name, phone_regex, is_active }                ← AUCUN champ pays
Currency  { _id, iso_name, name_fr, name_en, accepts_decimal, is_active }  ← idem
```

### 🔴 La relation est **unidirectionnelle**

Seul `Country` connaît ses opérateurs et ses devises. **Un opérateur ignore dans
quel pays il opère.**

Conséquence mesurée : **aucune route ne filtre par pays.** Répondre à *« quels
opérateurs au Cameroun ? »* impose de **scanner tous les pays** et de lire leurs
tableaux. Une question fondamentale du métier, en O(n).

### 🔴 Le pays est encodé dans l'expression régulière

```
MTN Cameroon       ^237(67\d{7}|68[0-4]\d{6}|65[0-4]\d{6})$   →  237
Orange (Sonatel)   ^221(77\d{7}|78\d{7})$                     →  221
MTNcongo1          6|333                                      →  INDÉDUCTIBLE
```

Une **donnée métier de premier rang** vit dans une **chaîne de validation**. Dès
qu'un motif est mal formé, l'information **disparaît définitivement**.

### Ce que le partage donne réellement

| Ressource | Référencée par | Cascade possible ? |
|---|---|---|
| `XOF` | **SN, BF, CI** (+ parasite `ca`) | 🔴 **non** — la désactiver casse 3 pays |
| `XAF` | **CM** (+ parasite `CV`) | 🔴 non |
| `Moov Africa CI` | **CI** + parasite `ca` | ⚠️ **piège** — une cascade naïve casserait la Côte d'Ivoire |
| Les 12 autres opérateurs | un seul pays chacun | ✅ oui, après contrôle |

---

## 3. Mon verdict — franc

> **Ce n'est pas « mal conçu ». C'est « conçu à moitié ».**
>
> Et le défaut fondateur est d'avoir appliqué **un modèle unique à deux entités
> de nature opposée.**

| | Nature réelle | Modèle appliqué | Verdict |
|---|---|---|---|
| **Currency** | **globale** — `XOF` est partagée par 8 pays UEMOA dans la réalité | globale | ✅ **juste** |
| **Telco** | **nationale** — MTN Cameroon n'opère qu'au Cameroun | globale | 🔴 **faux** |

Tous les symptômes découlent de là.

### Ce qui est bien conçu — et il faut le dire

| | Pourquoi c'est bon |
|---|---|
| Service dédié aux référentiels | Séparation des responsabilités correcte |
| **`activate`/`deactivate` au lieu de `DELETE`** | **Très bon.** Pour un référentiel, le soft-delete est le bon choix : on ne supprime jamais une devise que des comptes référencent |
| Currency globale | Métier juste |
| Wrapper uniforme, pagination, recherche | Cohérent avec les 8 autres services |
| Authentification réellement appliquée | Vérifié le 9 août |

### Les six défauts, par gravité

| # | Défaut | Portée |
|---|---|---|
| 1 | **Telco sans pays** | Le lien métier n'existe pas. `Moov Africa CI` est rattaché à `CI` **et** au parasite `ca` — sans que rien ne l'empêche |
| 2 | **`City` absente** | Le Document Fonctionnel annonce **4 entités**, 3 sont implémentées. Tout le métier terrain — Kiosques, Dépositaires — a besoin d'une géographie qui **n'existe pas** |
| 3 | **`embed-at-creation` sans invalidation** | **Deux sources de vérité.** La dénormalisation est défendable, mais elle exige une propagation. Sans elle, les copies divergent **silencieusement** |
| 4 | **`Create` == `Update`** | Pas de modification partielle. Combiné au point 3, un envoi maladroit **détruit des références** |
| 5 | **Pas d'index unique** (`RC-182`, `RC-183`) | D'où `cv`, `00`, et le doublon `cm` |
| 6 | **Pas de `re.compile()`** (`RC-184`) | D'où `6\|333` — une validation qui ne valide rien |

### Ce qu'un modèle correct porterait

```
Country ──1─n──► Telco       le Telco PORTE son country_iso2
Country ──n─n──► Currency    vraiment partagée — la table de liaison est juste
Country ──1─n──► City        entité à part entière, avec _id et unicité
                   └─1─n──► District
```

**Trois changements, et les six défauts tombent :** `Telco.country_iso2` ·
`City` promue en entité · la référence soit résolue à la lecture, soit invalidée
à l'écriture — **pas les deux à moitié**.

### 🟢 Une bonne nouvelle vérifiée aujourd'hui

`ANO-CFG-LIFECYCLE-MAJOR` (MAJEURE, juin) affirmait que `PATCH {is_active:false}`
répondait `200` **sans rien appliquer**. **C'est corrigé** : des routes dédiées
`activate/{id}` et `deactivate/{id}` existent et **fonctionnent** — vérifié sur
le pays parasite `ca`, en test entièrement réversible.

> **La demande du boss « activation/désactivation d'un pays » est donc faisable
> aujourd'hui, sans développement serveur.** C'était le risque principal ; il est levé.

---

## 4. Ce que le Loader en tire — la partie utile

### 4.1 Ce que nous faisons **déjà** correctement

| Leçon | Notre situation |
|---|---|
| Telco sans pays | ✅ notre `Telco` **porte `country_iso2`** |
| `City` absente | ✅ `Region`, `City`, `District` sont des entités à part entière |
| Regex non validé | ✅ **`re.compile()` au chargement** — un motif invalide est journalisé en orphelin |
| Pas d'index unique | ✅ nos index portent les invariants : `(company_id, lender_type)` unique · `email` unique · **`(run_id, district_id)` unique** — c'est lui qui rend structurellement impossible d'empiler deux Kiosques dans un quartier |
| `D-FAKER-1` | ✅ porté par la **clé primaire** : `_id` = `client_id` Faker. Aucun index additionnel nécessaire |

**Nous appliquons déjà ce que config-service n'applique pas.** Ce n'est pas une
coïncidence : c'est la doctrine.

### 4.2 Ce que nous **prenons** de leur bonne idée

> **Le soft-delete.** `activate`/`deactivate` plutôt que `DELETE` est le bon
> choix pour un référentiel, et **nous ne l'avons pas**.

Nos collections purgent par préfixe (`OBJ-05`). Mais l'exigence de paramétrage du
boss demande de **désactiver un pays sans perdre sa trace** — pour pouvoir le
réactiver, et pour que le tableau de bord montre *ce qui a été exclu et pourquoi*.

**Décision à porter** : la configuration d'exécution utilise un **état**
(`actif` / `inactif`), jamais une suppression. On garde la trace de ce qu'on a
retiré. C'est directement inspiré de config-service, et c'est leur meilleure idée.

### 4.3 Ce que nous devons **vérifier chez nous** — la dénormalisation

Le défaut n°3 — *embed sans invalidation* — est le plus insidieux. **Avons-nous
le même risque ?**

| Notre collection | Stocke | Verdict |
|---|---|---|
| `lenders_registry` | des **références** (`company_id`, `*_account_id`) | ✅ pas de copie |
| `org_hierarchy` | des **références** (`company_id`, `depositary_id`) | ✅ |
| `faker_consumption_ledger` | des références | ✅ |
| `audit_trail` | des **instantanés** `before`/`after` | ✅ **voulu** — un journal d'audit *doit* figer l'état. Ce n'est pas de la dénormalisation, c'est de l'histoire |

**Nous n'avons pas le problème.** Mais il faut que ça reste vrai : **règle à
tenir — nos collections stockent des références, jamais des copies, sauf
`audit_trail` où l'immuabilité est le but.**

### 4.4 🆕 Ce que l'analyse **nous apprend de neuf** — les relations inverses

Le défaut n°1 se manifeste par une impossibilité : *« quels opérateurs au
Cameroun ? »* n'a pas de réponse directe.

**Posons-nous la même question sur nos propres données**, en pensant au tableau de
bord que M. JJB regardera :

| Question qu'il posera | Avons-nous la relation inverse ? |
|---|---|
| Quels opérateurs dans ce pays ? | ✅ `telcos_du_pays()` |
| Quels quartiers dans cette ville ? | ✅ `quartiers_de_ville()` |
| **Quels Kiosques dans ce quartier ?** | ⚠️ `org_hierarchy` indexé sur `(run_id, district_id)` — **possible**, à exposer |
| **Quels clients rattachés à ce Kiosque ?** | 🟠 **rien côté serveur** — mais `org_hierarchy.clients_du_kiosque()` y répond depuis le 12/08 (niveau `CLIENT`, `EF-26` 1er temps) |
| **Quel client Faker a produit cette entité ?** | ✅ `faker_consumption_ledger.resulting_entity_id` |
| **Quelles intentions non résolues ?** | ✅ `intentions_orphelines()` |

> **Conclusion actionnable** : le rattachement **Client → Kiosque** doit être
> persisté chez nous **dès l'onboarding**, avec son index. Sinon nous
> reproduirions exactement le défaut que nous venons de critiquer — une relation
> métier qui n'existe dans aucun modèle et qu'il faut reconstituer par balayage.

**C'est le vrai gain de cette analyse.** Elle nous a fait voir un trou dans notre
propre conception, avant qu'il ne coûte.

---

## 5. Ce qui reste hors de notre périmètre

| | |
|---|---|
| **Corriger** config-service | Non. C'est l'équipe qui le tient |
| **Purger** les 6 parasites | Non. Référentiel partagé |
| **Ticketer** ces défauts | Pas maintenant — décision de Yaniv du 9 août. `RC-181` à `RC-185` couvrent déjà une partie |
| **Comprendre** le service | **Oui, et c'était nécessaire** |
| **En tirer des règles** pour nous | **Oui — §4** |

> ⚠️ **Sur `ANO-CFG-TELCO-01` (le motif `6\|333`)** : `RC-184` couvre les regex
> **non compilables**. `6|333` **est compilable** — il est simplement **sans
> ancres**. Défaut voisin mais distinct. Si nous le remontons un jour, ce sera
> **en référençant `RC-184`**, jamais en doublon.

---

## 6. Les cinq règles que cette analyse ajoute à notre doctrine

1. **Aucune donnée métier dans une chaîne technique.** Le pays d'un opérateur est un champ, pas un préfixe de regex.
2. **Toute relation métier a son inverse interrogeable.** Si une question du métier exige un balayage, le modèle est incomplet.
3. **Références, jamais copies** — sauf dans `audit_trail`, où figer l'état *est* le but.
4. **Soft-delete plutôt que suppression** dans tout ce qui tient lieu de référentiel.
5. **Une entité promise doit exister.** `City` manque depuis le Document Fonctionnel ; chez nous, `Region`, `City` et `District` sont des entités réelles.

---

*Analyse conduite le 9 août 2026. Aucun ticket créé, aucune écriture sur
config-service hormis un test d'activation/désactivation entièrement réversible
sur une entité parasite.*
