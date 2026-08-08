# Le chemin de l'argent — 8 août 2026

| | |
|---|---|
| **Objet** | `EF-73/74/75` et `UC-14` exigent d'alimenter des comptes. Le chemin n'avait **jamais** été mesuré. Risque n°1 du Loader. |
| **Question** | Comment amorce-t-on de l'argent dans un système où `credit` exige un compte source ? |
| **Empreinte** | **Nette : zéro.** Les comptes QA sont revenus à 0. 5 transactions restent au journal (aucun DELETE). |

---

## 1. ✅ Le risque n°1 n'en est pas un — `POST /accounts/credit` crée la monnaie

`CreditAccountSchema` exige `src_account_id` **et** `dest_account_id`, ce qui
laissait craindre qu'aucun argent ne puisse entrer sans provenir d'ailleurs.
**Mesure :**

```
POST /accounts/credit  { amount: 1000, src == dest, provider_src: CASH, type: DEPOSIT }
  → HTTP 200 · solde 0 → 1000 · aucune contrepartie débitée
```

Et la contrainte est explicite :

```
src != dest  →  400 « src_account_id must match dest_account_id for credit operations »
```

> **`src_account_id` est une formalité sur `credit` : il doit égaler `dest`.**
> `provider_src` (`CASH`, `MOMO`, `BANK`, `ACCOUNT`) décrit l'**origine externe**
> des fonds. C'est le mécanisme d'amorçage que `EF-73` réclame.

---

## 2. ✅ La masse est conservée sur les transferts

| | TERM_DEPOSIT | CLASSIC | Masse |
|---|---:|---:|---:|
| avant | 1000 | 0 | **1000** |
| après `transfer(300)` | 700 | 300 | **1000** |

Et le découvert est refusé, sur les deux chemins :

```
transfer  au-delà du solde → 400 « Insufficient available balance »
debit     au-delà du solde → 400 « Insufficient available balance »
```

**Aucun solde négatif n'est atteignable.** Le champ exposé est `balance_avail`,
pas `available_balance`.

---

## 3. ✅ `initiate` / `confirm` — un vrai deux-temps, et il est **idempotent**

```
POST /accounts/initiate → 201 · reference DEPOSIT-40004C30… · status PENDING
                             solde INCHANGÉ
POST /accounts/confirm  → 200 · solde 700 → 850
POST /accounts/confirm  (même référence, rejeu)
                        → 400 « This transaction already been approved or canceled? »
                             solde INCHANGÉ
```

> **La `reference` est une clé d'idempotence réelle**, générée par le serveur et
> résolvable : `GET /transactions/r/{reference}` → 200. C'est le mécanisme qui
> permet à `EF-60` (« aucune duplication en ré-exécution ») de tenir sur les
> mouvements d'argent — vérifier avant de rejouer, plutôt que d'espérer.

---

## 4. ✅ Le montant négatif est refusé **sans mutation** — contraste avec `FRA-195`

```
POST /accounts/credit  { amount: -5000 }
  → 422 « body -> amount: Input should be greater than 0 »
  → soldes INCHANGÉS, contre-vérifiés
```

C'est une validation Pydantic, donc **antérieure à toute logique métier**.

> **Contraste majeur.** `FRA-195` établit que collect-service, lui, **mute la
> base sous un rejet apparent**. Deux services du même écosystème, deux niveaux
> de fiabilité opposés. account-service est le service le mieux gardé mesuré à
> ce jour ; collect-service reste celui qui exige nos propres barrières.

---

## 5. 🔴 `ANO-ACC-STATUS-05` — le statut ne dit pas si l'argent a bougé

Quatre chemins ont tous déplacé des fonds. Leurs statuts :

| Chemin | Statut enregistré | Solde appliqué |
|---|---|---|
| `/credit` | `SUCCESS` | ✅ |
| `/transfer` | `SUCCESS` (×2, débit + crédit) | ✅ |
| `initiate` + `confirm` | `APPROVED` | ✅ |
| **`/debit`** | **`PENDING`** | ✅ **oui, quand même** |

Le `WITHDRAWAL` de 850 a ramené le solde à 0 **et est resté `PENDING`** — relu
après 20 secondes, toujours `PENDING`. Ce n'est pas un traitement asynchrone en
cours : c'est un état terminal mal nommé.

> **Règle pour le Loader** : ne jamais vérifier un mouvement de fonds en lisant
> le statut de la transaction. **Toujours relire le solde du compte.** Quatre
> statuts différents (`SUCCESS`, `APPROVED`, `PENDING`) pour un même résultat
> rendent ce champ inexploitable comme preuve.

---

## Ce que cela débloque

`EF-73`, `EF-74`, `EF-75` et `UC-14` sont **applicables** : l'amorçage existe, la
masse est conservée, le rejeu est protégé. La séquence du Loader sera :

1. `credit` avec `src == dest` et `provider_src = CASH` pour l'amorçage initial
2. `transfer` pour tout mouvement entre comptes du système
3. relecture du **solde** — jamais du statut — comme preuve
4. la `reference` conservée en base, comme clé d'idempotence de `EF-60`

---

## À remonter à l'équipe serveur

6. **`ANO-ACC-STATUS-05`** — `/debit` laisse la transaction en `PENDING` alors
   que le solde est appliqué. Quatre statuts pour un même résultat.

---

*12 tests, chacun encadré d'une lecture de solde avant et après. Empreinte
financière nette : zéro.*

---

# Partie II — account-service terminé (T13 → T19)

## 6. La table des frais — `transaction-configs`

12 configurations, une par `TransactionType`. **Onze sont à zéro. Une ne l'est pas :**

| Type | `fees_type` | Montant |
|---|---|---:|
| `TAXE` | **`AMOUNT`** | **100** |
| les 11 autres | `PERCENT` | 0 |

`TAXE` a été modifiée le **28/07** — elle n'était pas à 100 à l'origine.

> **Conséquence pour le Loader** : une transaction de type `TAXE` coûte 100
> unités de plus que le montant envoyé. Le solde ne correspondra pas au montant.
> Le Loader **n'émettra jamais de `TAXE`** ; s'il devait le faire, il lirait
> cette table d'abord. Elle est modifiable par API — donc elle peut changer sans
> nous prévenir. **On la lit au démarrage, on ne la présume pas.**

---

## 7. 🔴 `ANO-ACC-STATUS-06` — `change-status` répond **500** et **fonctionne**

```
PUT /accounts/change-status/{id}/SUSPENDED → HTTP 500 · statut relu = SUSPENDED ✅
PUT /accounts/change-status/{id}/ACTIVE    → HTTP 500 · statut relu = ACTIVE    ✅
```

**C'est le piège exactement inverse de `FRA-195`.** Là-bas, un rejet apparent
cachait une mutation. Ici, une **erreur apparente cache un succès**.

> **Règle** : sur `change-status`, ne jamais se fier au code HTTP. **Relire le
> statut.** Un Loader qui traiterait ce 500 comme un échec rejouerait
> indéfiniment une opération déjà réussie.

Bonne nouvelle : **l'opération est réversible**, vérifié dans les deux sens avant
toute utilisation réelle.

---

## 8. ✅ `SUSPENDED` bloque réellement les opérations

```
credit sur un compte SUSPENDED
  → 400 « Only active accounts can be credited or debited » · solde inchangé
```

> **Contraste avec `FRA-203`** : désactiver un Dépositaire n'arrête ni les
> collectes ni les retraits. Ici, suspendre un compte bloque vraiment.
> **Le même geste métier n'a pas le même effet selon le service.** C'est
> précisément le genre de dissymétrie qui produit de mauvaises surprises.

---

## 9. 🔴 `POST /accounts/` n'valide **aucune** de ses références

Compte créé avec un `owner_id`, un `external_id` et un `account_number`
**entièrement inventés** :

```
POST /accounts/  { owner_id: <UUID au hasard>, external_id: <UUID au hasard>, … }
  → HTTP 201
```

Même famille que `ANO-DEP-FK-04`. **Créer un compte orphelin est trivial.** Le
Loader ne crée donc jamais un compte en direct sans avoir lu l'entité
propriétaire au préalable — et de toute façon, les comptes naissent en cascade.

---

## 10. 🟠 Transfert entre devises : accepté 1:1, **sans conversion**

```
600 XOF → transfert de 200 vers un compte XAF
  → HTTP 200 · XOF 600 → 400 · XAF 0 → 200
```

**Je ne conclus pas à une corruption**, et voici pourquoi : le référentiel
déclare `XAF` = *CFA Franc BEAC* et `XOF` = *CFA Franc BCEAO*. Ce sont deux
francs CFA, **arrimés à l'euro au même taux — ils sont réellement à parité**.
Pour ce couple précis, 1:1 est **économiquement juste**.

**Le vrai problème est ailleurs** : le serveur ne fait **aucun contrôle de
devise**, et le référentiel **ne porte aucun taux de change**. N'importe quel
couple passerait à 1:1 — y compris un couple qui ne serait pas à parité.

> **Pour le Loader** : les 4 pays n'utilisent que `XAF` et `XOF`, à parité.
> Le risque est donc nul **par chance, pas par conception**. On ne transfère
> jamais entre devises différentes, et on ne s'appuie sur aucune conversion
> serveur — il n'y en a pas.

---

## 11. 🟠 Le référentiel des devises contient des **entrées parasites**

Sur 4 devises déclarées, **2 sont des déchets de test** :

| `iso_name` | `name_fr` | |
|---|---|---|
| `XAF` | Franc CFA (BEAC) | ✅ |
| `XOF` | Franc CFA (BCEAO) | ✅ |
| `cv` | CD | ❌ |
| `00` | 00 | ❌ |

> **`D-DEP-6` est à durcir.** « Valider la devise contre config-service » ne
> suffit pas : le référentiel accepterait `00`. Le Loader valide contre la liste
> **ISO 4217** *et* contre `is_active`, jamais contre le seul contenu du
> référentiel.

---

## Bilan account-service — 19 tests, service **terminé**

| Ce qui est fiable | Ce qui ne l'est pas |
|---|---|
| Conservation de la masse sur `transfer` | Le **statut** de transaction (4 valeurs pour un même résultat) |
| Découvert impossible (`debit` et `transfer`) | Le **code HTTP** de `change-status` (500 = succès) |
| Montant négatif refusé sans mutation | Les **références** à la création (aucune validation) |
| Idempotence réelle par `reference` | Le **contrôle de devise** (inexistant) |
| `SUSPENDED` bloque vraiment | Le **référentiel des devises** (2 entrées parasites) |

**Empreinte** : 1 compte XOF créé (aucun `DELETE` sur ce service), soldes tous
revenus à **zéro**.
