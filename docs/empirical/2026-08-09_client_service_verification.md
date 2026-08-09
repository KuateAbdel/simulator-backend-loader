# client-service — vérification du 9 août 2026

| | |
|---|---|
| **Motif** | *Verify, don't trust.* La page Service Anatomy (60555267) date du **1er août**. Avant d'écrire le client Loader, ses 7 disciplines ont été **rejouées** contre le serveur d'aujourd'hui. |
| **Méthode** | Contrat OpenAPI relu intégralement, puis 8 vérifications en écriture contrôlée. |
| **Résultat** | **1 discipline caduque · 3 comportements neufs · 5 confirmées.** |
| **Empreinte** | 3 Clients créés, préfixés `DEMOQA0809`. Aucun `DELETE` n'existe. |

---

## 1. Le verdict, discipline par discipline

| Discipline | Affirmé le 01/08 | **Mesuré le 09/08** |
|---|---|---|
| `D-CLI-1` | Produits COLLECT créés en premier | ✅ structurel — `product_id` requis à l'onboarding |
| `D-CLI-2` | Toujours fournir `id_expire_on` | ✅ **CONFIRMÉ** — crash `.isoformat` identique |
| `D-CLI-3` | `id_number` **MAJUSCULES strict** | ❌ **CADUQUE** — `cm<hex>` en minuscules → **201** |
| `D-CLI-4` | `identity.type` écrasé vers `CORPORATE` | ✅ **CONFIRMÉ** — envoyé `INDIVIDUAL`, rendu `CORPORATE` |
| `D-CLI-5` | GET-avant-POST par `msisdn` | ✅ **CONFIRMÉ** — `400 « Client already exists »` |
| `D-CLI-6` | Rattachement Company via collecte seulement | ✅ structurel — aucun `company_id` sur la fiche |
| `D-CLI-7` | `PUT /subscribe` pour les 2ᵉ/3ᵉ produits | ✅ **CONFIRMÉ** — `200`, le tableau passe à 2 |

---

## 2. 🔴 `D-CLI-8` — un invariant que **personne n'avait vu**

```
POST /clients/onboard  avec  identity.phone ≠ msisdn
   → HTTP 400  « Identity phone field must match msisdn »
```

Le serveur exige l'**égalité stricte** entre `msisdn` et `identity.phone`.

**Pourquoi la page du 01/08 ne le mentionne pas** : ses payloads de test
utilisaient le même numéro des deux côtés — `msisdn: "699000005"` et
`phone: "699000005"`. La barrière existait peut-être déjà, elle n'a simplement
**jamais été rencontrée**.

**Ce que ça aurait coûté** : mon premier sondage a construit `phone` et `msisdn`
indépendamment, comme l'aurait fait n'importe quel générateur. **Les trois
premiers appels ont échoué en 400.** Sur une campagne complète, c'est
**2 000 échecs**, et un module d'onboarding déclaré cassé sans qu'on sache pourquoi.

> **Porté dans `valider_onboarding()`** : `identity.phone` est **aligné** sur
> `msisdn`, jamais laissé à l'appelant.

---

## 3. 🔴 `identity._id` est requis au contrat, et **ignoré**

| | Valeur |
|---|---|
| `identity._id` **envoyé** | `c0b2ac68-4a71-4da6-96dd-143946775107` |
| `identity._id` **rendu** | `38f4c5fd-f1fd-49c2-82dd-0fd08987d2a4` |

Le serveur **génère le sien**. Même famille exactement que `ANO-CPY-OWNERID-05`
(`FRA-227`) sur company-service : un champ obligatoire dont la valeur est écartée.

**Conséquence directe** : c'est l'identifiant **rendu** que porte le compte
`CHECKING` créé en cascade (`owner_type=IDENTITY`, `owner_id=<celui-ci>`). Un
Loader qui construirait ses références sur l'UUID envoyé aurait **2 000 jointures
mortes**, sans aucune erreur pour l'avertir.

> 🔴 **Correction UML à porter** : `05_sequence_onboarding.puml` annonce
> *« identity (avec `_id` fourni par le Loader) »*, et la correction n°3 de
> `recon_9_services.md` dit *« `_id` fourni par l'appelant »*. **Les deux sont
> faux.** Le Loader le fournit — le contrat l'exige — mais le serveur l'ignore.

---

## 4. 🔴 `language` est ignoré à l'onboarding

```
envoyé  language: "fr"      →  rendu  language: "en"
envoyé  segment:  "MEDIUM"  →  rendu  segment:  "MEDIUM"   ✅
```

Le champ `language` du `OnboardClientSchema` est **accepté et écarté**, alors que
`segment`, dans le même payload, est correctement honoré. Le défaut est donc
localisé, pas général.

**Le seul chemin qui fonctionne** est `PATCH /clients/language/{client_id}` —
qui est par ailleurs **la seule mutation** exposée par ce service.

> **Porté dans `onboarder()`** : si la langue cible n'est pas `en`, le Loader
> **repasse automatiquement** par le `PATCH` et relit la fiche. Le contrat ment,
> notre code ne ment pas.

---

## 5. Ce que la vérification a confirmé sans surprise

* **`D-CLI-3` est bien caduque** — `id_number` en minuscules passe en `201`.
  Cohérent avec `ANO-CLI-IDNUM-06` / `FRA-228` mesuré le 08/08. **Seuls les
  caractères spéciaux sont refusés.** Le Loader continue d'émettre des
  majuscules — se conformer au message reste le choix sûr si la règle est un
  jour réellement appliquée — mais il ne **rejette** que ce qui est réellement
  rejeté.
* **`OBS-CLI-CROSSCHECK-01`** — un Client `CORPORATE` souscrit sans broncher à
  un produit `INDIVIDUAL` → `201`. **Aucune validation croisée.** La cohérence
  est entièrement à notre charge, en amont, dans la sélection du produit.
* **`OBS-CLI-STATUS-01`** — les 3 Clients pré-existants sont tous à `PENDING`,
  et les nouveaux naissent `PENDING`. **Aucun endpoint de transition n'existe.**
  Le statut ne bouge jamais.
* **`OBS-CLI-TYPO-01`** — `GET /clients/` annonce toujours
  *« Campaign data retrieved successfully »*. Le champ `description` du wrapper
  n'est jamais utilisé pour décider quoi que ce soit.
* **`GET /clients/by-msisdn/{msisdn}` inexistant → `404`**, là où un `200` avec
  corps vide serait attendu. Traité par `vide_si_404`, jamais comme une panne.
* **`address.country`, `city`, `region` sont correctement persistés** ici,
  contrairement à un appel direct sur identity-service où leur omission les
  laisse à `null` (`D-IDN-2`).

---

## 6. La cascade, reconfirmée

```
POST /api/v1/clients/onboard
     ├─► identity-service   +1 Identity   (_id GÉNÉRÉ par le serveur)
     └─► account-service    +1 CHECKING   owner_type=IDENTITY
                                          external_class=CLIENT_SERVICE
```

Le contrat OpenAPI de client-service ne déclare **aucune dépendance** — zéro
occurrence de « identity », « account » ou « product » dans tout le document.
**Ces deux cascades ne sont connues que par la mesure.** C'est précisément
pourquoi le Loader relit systématiquement ce qu'il vient de créer.

---

## 7. Ce qui a été livré

| Fichier | Rôle |
|---|---|
| `app/clients/client_service.py` | Client complet, **8 disciplines** + 3 pièges neutralisés |
| `tests/test_client_service.py` | **15 tests** sur les barrières préalables au réseau |

**Preuves d'exécution** : `ruff check` ✅ · `ruff format` ✅ · `mypy` ✅ 40 fichiers ·
`pytest` ✅ **112 tests**.

### Un défaut corrigé au passage

`.env.example` livrait `SIM_START_DATE=` et `SIM_END_DATE=` **vides**, alors que
son propre commentaire dit de le copier en `.env`. Une chaîne vide fait échouer
la validation Pydantic : **suivre la documentation cassait le démarrage.** Les
deux lignes sont désormais commentées, avec l'explication.

---

## 8. Deux anomalies à ticketer

| Code | Constat | Gravité |
|---|---|---|
| `ANO-CLI-IDIGNORED-01` | `identity._id` requis au contrat, ignoré par le serveur — même famille que `FRA-227` | 🟡 basse |
| `ANO-CLI-LANG-01` | `language` accepté et écarté à l'onboarding, alors que `segment` est honoré | 🟡 basse |

*Vérification exécutée le 9 août 2026 par Kuate Abdel Yaniv (SDET/QA Lead).
Toutes les entités créées portent le préfixe `DEMOQA0809`.*
