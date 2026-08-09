# client-service — campagne SDET exhaustive du 9 août 2026

| | |
|---|---|
| **Motif** | La première vérification s'était arrêtée aux 7 disciplines héritées et à **4 endpoints sur 10**. Insuffisant pour un chemin emprunté **2 000 fois**. |
| **Couverture** | **10 endpoints sur 10** · enums · unicité · pagination · devise · souscriptions · âge · références · cascade |
| **Résultat** | **1 anomalie HAUTE · 3 MOYENNES · l'origine de `FRA-222` identifiée · 1 exigence CDC inapplicable** |
| **Empreinte** | ~25 Clients `DEMOQA0809`. Aucun `DELETE` n'existe sur ce service. |

---

## 1. 🔴 HAUTE — `POST /clients/search` **ignore totalement ses critères**

Sept requêtes, sept critères différents, **le même résultat à chaque fois** : la base entière.

| Critère envoyé | HTTP | Résultats |
|---|---:|---:|
| `{"msisdn": "6C0C97E3"}` — un client précis | 200 | **7** |
| `{"category": "INDIVIDUAL"}` | 200 | **7** |
| `{"status": "PENDING"}` | 200 | **7** |
| `{"segment": "MEDIUM"}` | 200 | **7** |
| `{"identity_id": "47e9e707-…"}` | 200 | **7** |
| **`{"category": "NIMPORTEQUOI"}`** — valeur hors enum | **200** | **7** |
| `{}` — vide | 200 | **7** |

Le endpoint est un `GET /clients/` déguisé. Il n'applique **aucun** filtre, et ne **valide même pas** ses énumérations — `NIMPORTEQUOI` passe en 200 là où l'onboarding rend 422 sur le même champ.

**Impact** : tout consommateur croyant filtrer reçoit **la base entière**. À 2 000 clients, une recherche par segment rendrait 2 000 lignes au lieu de quelques centaines, sans le moindre signal. Un back-office affichant « 3 résultats trouvés » en afficherait 2 000.

> **Parade Loader** : `POST /search` n'est **jamais** utilisé. Les recherches passent par `by-msisdn`, `by-id-number` ou `{msisdn}/{id_number}`, **qui fonctionnent** (vérifiés ci-dessous).

---

## 2. 🔴 L'origine de `FRA-222` est trouvée — la devise traverse sans contrôle

`currency` est **requise** au contrat, **n'apparaît pas** dans la fiche Client rendue, et atterrit **telle quelle** dans le compte `CHECKING` créé en cascade.

| `currency` envoyée | Onboarding | Compte créé |
|---|---:|---|
| `XAF` | 201 | `currency='XAF'` ✅ |
| `XOF` | 201 | `currency='XOF'` ✅ |
| **`ZZZ`** | **201** | **`currency='ZZZ'`** ❌ |
| **`ANY`** | **201** | **`currency='ANY'`** ❌ |
| **`""`** (vide) | **201** | **`currency=''`** ❌ |

**`FRA-222`** documente un compte client réel portant `currency="ANY"`, et sa recommandation n°4 demandait *« d'identifier le chemin d'écriture ayant produit `ANY` et le corriger à la source »*.

> **Le chemin, c'est celui-ci.** `POST /clients/onboard` est le seul parcours créant des comptes `CHECKING` rattachés à une Identity — l'hypothèse formulée dans le ticket est désormais **confirmée par la mesure**.

Trois services se passent le champ sans que **personne** ne le valide : client-service ne le regarde pas, account-service ne le valide pas (`FRA-222`), et config-service ne peut pas servir de garde-fou puisqu'il contient lui-même les entrées parasites `cv` et `00`.

> **`D-CLI-9`** — le Loader valide `currency` contre une **liste close** `{XAF, XOF}`, jamais contre le référentiel serveur. Porté dans `valider_onboarding()`, couvert par 12 tests.

---

## 3. 🔴 `UC-13` « 1 à 3 souscriptions » — le serveur ne borne **rien**

| Souscription | HTTP | Total produits |
|---|---:|---:|
| #3 | 200 | 2 |
| #4 | 200 | 3 |
| **#5** | **200** | **4** |
| **#6** | **200** | **5** |
| **#7** | **200** | **6** |

**Six produits attachés à un seul client**, sans le moindre rejet. Le plafond du CDC est **entièrement à notre charge**.

> **Porté** : `SOUSCRIPTIONS_MAX = 3`, contrôlé par relecture avant chaque `PUT /subscribe`.

**Le doublon, lui, est refusé** — et c'est un invariant qu'aucune de nos sources ne documentait :

```
PUT /subscribe (même produit) → 400
« A customer cannot subscribe to the same products twice »
```

---

## 4. 🔴 Trois contraintes d'unicité, pas une

`INV-CLI-01` ne documentait que le `msisdn`. La mesure en révèle **trois** :

| Champ | Rejeu | Message serveur |
|---|---|---|
| `msisdn` | **400** | `Client already exists` |
| **`id_number`** | **400** | `Client already exists` ⚠️ *message trompeur* |
| **`email`** | **400** | `Identity with this email already exists` *(fuite de la cascade)* |

**Le message de `id_number` est trompeur** : il annonce un doublon de Client alors que le `msisdn` était différent. Sans test dédié, on conclurait à tort que c'est le numéro qui est en cause.

**Impact volumétrie** : le générateur doit garantir l'unicité de **trois** champs sur 2 000 clients, pas d'un seul. `EF-25` n'en cite qu'un.

---

## 5. Ce que la campagne a validé — le service fait bien son travail

### Les 5 endpoints de lecture jamais testés — tous corrects

| Endpoint | Existant | Inexistant |
|---|---|---|
| `GET /clients/{client_id}` | 200, bon client | **404** propre |
| `GET /clients/by-id-number/{n}` | 200, bon client | **404** propre |
| `GET /clients/{msisdn}/{id_number}` | 200, bon client | — |
| `GET /clients/by-msisdn/{m}` | 200 | **404** *(traité `vide_si_404`)* |

### Les énumérations sont réellement validées

`segment`, `category`, `channel`, `language` hors énumération → **422** systématique.
**Seule `currency` échappe au contrôle** — voir §2.

### La pagination est juste

```json
{"total": 7, "per_page": 2, "current_page": 1, "last_page": 4}
```

`limit=1000` → 200 avec les 7 éléments. `page=9999` → **200 avec liste vide**, pas d'erreur.
Le socle du Loader borne `limit` à 100 (`H20`) et suit `last_page`, jamais une heuristique sur la taille du lot.

### `PATCH /clients/language` fonctionne, contrairement au champ d'onboarding

`fr` → 200 (`'fr'`) · `en` → 200 (`'en'`) · `es` → **422** *« Input should be 'en' or 'fr' »*.
C'est bien le **seul** chemin qui modifie la langue — et la **seule mutation** exposée par ce service.

### `PUT /subscribe` valide ses références

`msisdn` inconnu → **404** `Client not found` · `product_id` inconnu → **404** `Product not found`.
Contraste net avec account-service, qui n'en valide aucune (`FRA-224`).

### Les validations de l'Identity embarquée tiennent

| Test | Résultat |
|---|---|
| `date_of_birth` dans le futur | **400** *« date_of_birth cannot be in the future »* ✅ |
| `nationality = "Cameroun"` | **400** ISO 3166-1 alpha-2 exigé ✅ |
| `nationality = "ZZ"` | **400** ✅ |
| `product_id` inexistant | **404** ✅ |

---

## 6. 🟠 Deux trous que le CDC nous oblige à combler nous-mêmes

### `EF-22` — l'âge n'est contrôlé que sur le futur

| Âge simulé | Résultat |
|---|---|
| Naissance future | **400** refusé ✅ |
| **2 ans** | **201 ACCEPTÉ** ❌ |
| **120 ans** | **201 ACCEPTÉ** ❌ |

`EF-22` exige **60 % de moins de 25 ans**. Un client de 2 ans passerait sans broncher. Le contrôle d'âge est **entièrement à notre charge** — et il s'ajoute au quota de genre, déjà non protégé (`gender` n'est pas validé par identity-service, `D-IDN-1`).

### `nationality` en minuscules est acceptée

`"cm"` → **201**, alors que `"ZZ"` → 400. La validation ISO est **insensible à la casse** : la base accumulera `CM` et `cm`. Même famille que `id_number` (`FRA-228`).

> **Parade** : le Loader émet **toujours** l'alpha-2 en majuscules, depuis `Loader_Base`.

---

## 7. 🔴 `EF-26` est **inapplicable tel qu'écrit**

> *« Le Loader DOIT rattacher chaque client à un Kiosque existant du pays cible. »*

**Le contrat de client-service ne porte aucun champ permettant ce rattachement.** La fiche Client rendue contient exactement 15 clés :

```
_id · created_at · updated_at · msisdn · language · channel · segment
category · identity · is_active · product · account_id
subscription_fees · subscription_date · status
```

Ni `depositary_id`, ni `kiosque_id`, ni `company_id`. **Le rattachement Client → Kiosque n'existe nulle part côté serveur à la création.**

Il ne peut se matérialiser que par une **collecte** — `CollectSchema` porte `client_id` **et** `depositary_id` — ce qui est exactement `D-CLI-6`.

> **Conséquence** : `EF-26` est satisfaite en **deux temps**. Le Loader persiste le rattachement dans `org_hierarchy` **dès l'onboarding** (c'est notre seule trace), puis le matérialise côté serveur **à la première collecte simulée**. Sans `org_hierarchy`, l'exigence serait invérifiable — exactement l'argument de `D-05` pour `CR-02`.

---

## 8. La relation Faker → client-service, champ par champ

`EF-20` exige des *« payloads clients complets incluant identité KYC et coordonnées géographiques »*. Voici ce que Faker **famille A** — la seule capable de servir 2 000 clients — fournit réellement.

### Les 7 champs requis de `OnboardClientSchema`

| Champ | Source | Détail |
|---|---|---|
| `msisdn` | **Faker** `sim_number` | ✅ direct |
| `channel` | **Loader** | Faker n'a pas la notion — tirage sur `{USSD, MOBILE, OFFICE}` |
| `segment` | **Faker** `metadata.behavior_segment` | point de jonction `EF-80` |
| `category` | **Faker** `customer_category` | `Individual`/`Business` → `INDIVIDUAL`/`CORPORATE` |
| `identity` | **mixte** — voir ci-dessous | |
| `product_id` | **Loader** | catalogue créé en amont (`D-CLI-1`) |
| `currency` | **Faker** `currency` — ⚠️ **à revalider** | Faker le fournit, mais rien ne le contrôle en aval (`D-CLI-9`) |

### Les 12 champs requis de l'`Identity` embarquée

| Champ | Faker fournit ? | Qui le produit |
|---|---|---|
| `_id` | — | Loader *(et le serveur l'ignore)* |
| `type` | — | Loader *(et le serveur l'écrase en `CORPORATE`)* |
| `first_name` / `last_name` | ✅ | Faker |
| `gender` | ✅ `WOMAN`/`MAN` | Faker → mapping vers `FEMALE`/`MALE` |
| `nationality` | ✅ `country_code` | Faker, en majuscules |
| `id_number` | ✅ `identity.ID_NUMBER` | Faker |
| `id_place` | ❌ | **Loader** — depuis `Loader_Base` |
| `id_expire_on` | ✅ `identity.ID_EXPIRY_DATE` | Faker, format `JJ/MM/AAAA` → **conversion obligatoire** |
| `phone` | ✅ `sim_number` | **doit égaler `msisdn`** (`D-CLI-8`) |
| **`date_of_birth`** | ❌ | **Loader** — Faker ne fournit **aucune** date de naissance |
| **`email`** | ❌ | **Loader** — composé |
| **`occupation`** | ❌ | **Loader** — depuis `sector_assignments` |
| **`address`** | ❌ | **Loader** — depuis `Loader_Base` |

> **Verdict sur `EF-20`** : l'exigence dit *« payloads complets incluant identité KYC **et coordonnées géographiques** »*. **Faker famille A ne fournit ni adresse, ni région, ni ville, ni quartier, ni date de naissance, ni email, ni occupation.** Cinq des douze champs requis sont **absents**. L'exigence n'est satisfaisable que parce que le Loader **compose** — c'est tout l'objet de `generateur.py`, et la justification de `A-03`.

### Les 4 règles d'interaction avec Faker

| Règle | Détail |
|---|---|
| **`D-FAKER-1`** | Jamais deux fois le même `client_id` — `faker_consumption_ledger` consulté **avant chaque tirage** |
| **`EF-21`** | Vérifier que `country_code` **rendu** correspond au pays demandé — `country_code=ZZ` rend **un client au hasard**, pas une erreur |
| **cache** | Déterministe et **clé par jeu de paramètres complet** : sans `seed` variable, 24 appels rendent 24 fois le même client |
| **`EF-29`** | `playground-client/random` peut expirer à **25 s** — repli obligatoire |

> 🔴 **`A-01` reste ouvert** : le **Sénégal est absent de Faker**, testé sur les deux familles, `404` des deux côtés. **500 clients** sans source.

---

## 9. Verdict `EF-20` → `EF-29`

| Réf | Exigence | Verdict |
|---|---|---|
| `EF-20` | Payloads complets KYC + géo | 🟠 **5 champs sur 12 absents de Faker** — composés par le Loader |
| `EF-21` | Vérifier le pays rendu | ✅ faisable, `country_code` présent |
| `EF-22` | 60 % < 25 ans, 2 femmes / 1 homme | 🔴 **aucun filet serveur** — `gender` non validé, âge non contrôlé |
| `EF-23` | 80/20 Individual/Corporate | 🟠 Faker tire 75/25 — quota forcé par tirage et rejet |
| `EF-24` | 20 % des pros en agriculture | ✅ via `sector_assignments` |
| `EF-25` | Unicité MSISDN | 🟠 **insuffisant** — le serveur impose aussi `id_number` **et** `email` |
| `EF-26` | Rattacher chaque client à un Kiosque | 🔴 **inapplicable à la création** — aucun champ. Deux temps via `org_hierarchy` + collecte |
| `EF-27` | Valider le MSISDN contre le regex telco | ⬜ **non couvert** — `telcos.csv` disponible, contrôle à écrire |
| `EF-28` | Segment de scoring configurable | ✅ `Segment` validé serveur-side |
| `EF-29` | Timeouts Faker, retry et repli | ✅ porté par le socle HTTP |

---

## 10. Ce qui a été livré et durci

| | |
|---|---|
| `app/clients/client_service.py` | **9 disciplines** + plafond `SOUSCRIPTIONS_MAX` + liste close `DEVISES_AUTORISEES` |
| `tests/test_client_service.py` | **30 tests** — dont 12 sur la devise, l'origine de `FRA-222` |

**Preuves** : `ruff` ✅ · `mypy` ✅ 40 fichiers · `pytest` ✅ **127 tests**.

## 11. Anomalies à ticketer

| Code | Constat | Gravité |
|---|---|---|
| **`ANO-CLI-SEARCH-01`** | `POST /search` ignore tous ses critères et ne valide pas ses enums | 🔴 **HAUTE** |
| `ANO-CLI-CUR-02` | `currency` non validée, propagée au compte — **origine de `FRA-222`** | 🟠 moyenne |
| `ANO-CLI-SUBMAX-03` | Aucun plafond de souscriptions — 6 produits acceptés | 🟠 moyenne |
| `ANO-CLI-UNIQMSG-04` | Doublon d'`id_number` rapporté comme « Client already exists » | 🟠 moyenne |
| `ANO-CLI-IDIGNORED-01` | `identity._id` requis au contrat, ignoré | 🟡 basse |
| `ANO-CLI-LANG-01` | `language` accepté et écarté à l'onboarding | 🟡 basse |
| `ANO-CLI-NATCASE-05` | `nationality` en minuscules acceptée | 🟡 basse |

*Campagne exécutée le 9 août 2026 par Kuate Abdel Yaniv (SDET/QA Lead).
Toutes les entités créées portent le préfixe `DEMOQA0809`.*
