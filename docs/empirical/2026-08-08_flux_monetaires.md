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
