# Anomalies découvertes le 8 août 2026 — **toutes ticketées**

| | |
|---|---|
| **Origine** | Campagne d'écriture contrôlée + audit d'intégration + investigation des flux monétaires |
| **Méthode** | Chaque anomalie est **mesurée**, contre-vérifiée, et accompagnée de sa reproduction exacte |
| **Périmètre** | Ce document ne liste **que le nouveau**. Les `FRA-xxx` (invariants Jira) et les anomalies des pages Service Anatomy existent déjà. |
| **Ticketage** | ✅ **Clos le 9 août 2026** — 11 tickets `FRA-218` → `FRA-228` couvrent les 14 anomalies (voir Récapitulatif). |

---

## 🔴 Gravité haute — fausse un raisonnement ou un solde

### 1. `ANO-ACC-FEES-07` — `amount` n'est pas ce qui quitte le compte

```
DEBIT 500, type=TAXE (fees_amount=100)  →  compte 1000 → 600   (−400)
DEBIT 100, type=WITHDRAWAL (fees 0)     →  compte  600 → 500   (−100, exact)
```

Le mouvement réel vaut **`amount − fees`**. Les 100 ne sont crédités **nulle
part** — vérifié sur les 56 comptes, masse totale −400. Le compte `TAXE` reste
à 0 : il ne perçoit rien.

**Impact** : toute comptabilité tenue côté client dérive silencieusement.
**Attendu** : soit `amount` est le montant débité et les frais s'ajoutent, soit
les frais sont reversés à un compte de perception. Actuellement : ni l'un ni
l'autre, l'argent disparaît de l'opération.

---

### 2. `ANO-ACC-STATUS-06` — `change-status` répond **500** et réussit

```
PUT /accounts/change-status/{id}/SUSPENDED → HTTP 500 · statut relu = SUSPENDED
PUT /accounts/change-status/{id}/ACTIVE    → HTTP 500 · statut relu = ACTIVE
```

**Impact** : un client qui traite le 500 comme un échec rejoue indéfiniment une
opération déjà réussie. C'est le miroir exact de `FRA-195` (rejet apparent,
mutation réelle) — ici : **erreur apparente, succès réel**.

---

### 3. `ANO-ACC-OWNER-03` — `owner_type=COMPANY` désigne aussi les Dépositaires

Sur 51 comptes marqués `owner_type=COMPANY` : **42 appartiennent en réalité à un
Depositary**, 8 à une Company, 1 à rien.

`OwnerType` ne comporte que `COMPANY` et `IDENTITY` — **aucune valeur
`DEPOSITARY`**. Le discriminant fiable est le `type` du compte, pas
l'`owner_type`.

**Impact** : toute jointure naïve `owner_id → company-service` échoue à 82 %.

---

### 4. `ANO-ACC-CUR-08` — un compte client porte la devise `ANY`

Un `CHECKING` réel, en base, propriétaire *David Kuate*, `currency: "ANY"`.
`ANY` est une valeur de l'enum **segment** ; ce n'est pas une devise ISO 4217 et
elle n'existe pas au référentiel.

**Impact** : compte inexploitable en agrégation multi-devises.
**Cause probable** : le chemin d'onboarding client — à confirmer.

---

## 🟠 Gravité moyenne — intégrité référentielle

### 5. `ANO-CPY-USER-01` — le `identity` du User cascade pointe vers la Company

Le User créé en cascade par company-service porte le **`company_id`** dans son
champ `identity`. Vérifié sur toute la population :

| Origine | `identity` pointe vers | |
|---|---|---|
| company-service | la **Company** ❌ | **6 / 6** |
| client-service | la vraie Identity ✅ | 5 / 5 |

**Systématique côté company-service, absent côté client-service.**

---

### 6. `ANO-CPY-USER-02` — `company_id` vide sur tous les Users cascade

Le User créé par company-service n'est **rattaché à aucune Company** —
`company_id: ''`. Il est donc inexploitable pour toute logique multi-tenant.

---

### 7. `ANO-DEP-FK-04` — `company_id` non validé à la création d'un Dépositaire

Le Dépositaire `'Testtt'` porte un `company_id` qui répond **404**.

Incohérent **au sein du même service** : sur les souscriptions, `product_id`
inexistant → 404 et `depositary_id` inexistant → 400 sont bien contrôlés.

---

### 8. `ANO-ACC-FK-09` — `POST /accounts/` ne valide aucune référence

Compte créé avec `owner_id`, `external_id` et `account_number` **entièrement
inventés** → **HTTP 201**. Créer un compte orphelin est trivial.

---

### 9. `ANO-DEP-TYPE-02` — aucun contrôle de cohérence de type produit

Souscrire un **Dépositaire** (épargne) à un produit **`LENDING`** (prêt) →
**HTTP 201**. Le prêt se retrouve dans le tableau à côté des produits d'épargne.

```
produits = ['Cotisation 20000/mois' COLLECT, 'plastique' COLLECT,
            'plastique' COLLECT, 'DEMO_QA0808_Nano' LENDING]
```

**Impact** : un kiosque d'épargne peut « vendre » un prêt. Aucun garde-fou.

---

## 🟡 Gravité basse — contrat trompeur

### 10. `ANO-ACC-STATUS-05` — le statut ne dit pas si l'argent a bougé

| Chemin | Statut | Argent bougé |
|---|---|---|
| `/credit`, `/transfer` | `SUCCESS` | ✅ |
| `initiate`+`confirm` | `APPROVED` | ✅ |
| **`/debit`** | **`PENDING`** | ✅ |

Le `WITHDRAWAL` reste `PENDING` indéfiniment (relu après 20 s) alors que le
solde est appliqué. **État terminal mal nommé**, pas un asynchrone en cours.

---

### 11. `ANO-CPY-ADMIN-03` — `admin_email` est requis, accepté, et sans effet

Aucun User n'est créé avec cette adresse ; le User cascade porte `owner.email`.
Relecture de la Company : `admin_email` → **`None`**. Champ **write-only et
perdu**, comme `currency` (`FRA-199`).

---

### 12. `ANO-CPY-OWNERID-05` — `owner._id` est requis au contrat mais ignoré

L'UUID envoyé n'est jamais celui rendu : le serveur génère le sien. Il faut le
fournir pour passer la validation, et **toujours relire celui qui est rendu**.

---

### 13. `ANO-CLI-IDNUM-06` — message d'erreur qui annonce une contrainte non appliquée

Le message dit *« expected alphanumeric **uppercase** only »*, mais
`cm250509274` en minuscules est **accepté** (201). Seuls les caractères spéciaux
sont réellement refusés.

---

### 14. `ANO-CFG-CUR-10` — le référentiel des devises contient des déchets

Sur 4 devises déclarées, **2 sont des entrées de test** : `iso_name` = `"cv"` et
`"00"`. Un client validant « contre le référentiel » accepterait `00` comme
devise.

---

## ✅ Une bonne nouvelle à consigner

**`ANO-CPY-BUG-06` est corrigé.** La page Service Anatomy le décrivait comme
bloquant (*« le bug NoneType.email empêche empiriquement la création de nouvelles
Companies »*). Mesure du 08/08 : `POST /companies/` → **HTTP 201**. Le blocage
n'existe plus, l'étape Organisation est débloquée.

---

## Récapitulatif

| Code | Service | Gravité | Ticket | Épique | Priorité |
|---|---|---|---|---|---|
| `ANO-ACC-FEES-07` | account | 🔴 | `FRA-218` | FRA-173 Paiement | Highest |
| `ANO-ACC-STATUS-06` | account | 🔴 | `FRA-219` | FRA-173 Paiement | Highest |
| `ANO-ACC-OWNER-03` | account | 🔴 | `FRA-220` | FRA-173 Paiement | Highest |
| `ANO-ACC-CUR-08` | account | 🔴 | `FRA-222` | FRA-173 Paiement | High |
| `ANO-CPY-USER-01` | company | 🟠 | `FRA-221` | FRA-175 Administration | High |
| `ANO-CPY-USER-02` | company | 🟠 | `FRA-221` | FRA-175 Administration | High |
| `ANO-DEP-FK-04` | depositary | 🟠 | `FRA-225` | FRA-178 Collecte | Medium |
| `ANO-ACC-FK-09` | account | 🟠 | `FRA-224` | FRA-173 Paiement | Medium |
| `ANO-DEP-TYPE-02` | depositary | 🟠 | `FRA-223` | FRA-178 Collecte | High |
| `ANO-ACC-STATUS-05` | account | 🟡 | `FRA-226` | FRA-173 Paiement | Low |
| `ANO-CPY-ADMIN-03` | company | 🟡 | `FRA-221` | FRA-175 Administration | High |
| `ANO-CPY-OWNERID-05` | company | 🟡 | `FRA-227` | FRA-175 Administration | Low |
| `ANO-CLI-IDNUM-06` | client | 🟡 | `FRA-228` | FRA-175 Administration | Low |
| `ANO-CFG-CUR-10` | config | 🟡 | `FRA-222` | FRA-173 Paiement | High |

**14 anomalies, 4 hautes — toutes ticketées** en 11 tickets (`FRA-218` → `FRA-228`).
Deux tickets couvrent plusieurs anomalies : `FRA-221` en regroupe 3 (une seule et
même cascade de création d'une Company), `FRA-222` en regroupe 2 (la devise
invalide et le référentiel pollué qui aurait dû l'arrêter).

**Règle de rattachement aux épiques** — établie et vérifiée le 9 août 2026 :

| Service | Épique |
|---|---|
| account-service | `FRA-173` Module de paiement (Mifos) |
| depositary-service, collect-service | `FRA-178` Module Collecte |
| company-service, user-service, client-service, config-service | `FRA-175` Module Administration (Central) |

**Toutes sont neutralisées côté Loader** — aucune ne bloque le développement.
Le Loader ne répare rien côté serveur : il neutralise l'effet chez lui,
journalise, et poursuit.

---

*Chaque anomalie ci-dessus est reproductible à partir des relevés joints
(`2026-08-08_campagne_ecriture.md`, `2026-08-08_integration_inter_services.md`,
`2026-08-08_flux_monetaires.md`).*
