# Campagne d'écriture contrôlée — 8 août 2026

| | |
|---|---|
| **Objet** | Transformer en faits les 8 chemins d'écriture que le Loader n'avait jamais exécutés. |
| **Autorisation** | Donnée explicitement par le Tech Lead. |
| **Environnement** | TEST — `*.test.services.fintech4esg.com` |
| **Marqueur** | `DEMO_QA0808_` — reconnaissable et purgeable par préfixe |
| **Méthode** | Ordre par réversibilité : ce qui a un `DELETE` d'abord, l'irréversible ensuite. Une entité par hypothèse, jamais un lot. Chaque conclusion contre‑vérifiée avant d'être écrite ici. |

## Un test volontairement NON exécuté

> **Le montant négatif sur collect-service.** `FRA-195` établit qu'un rejet HTTP
> apparent masque une mutation réelle. Le tester, c'est corrompre la base sans
> pouvoir revenir en arrière. La barrière `valider_montant()` est écrite et
> testée hors ligne ; elle n'a pas besoin d'être éprouvée en production de test.

---

## Empreinte laissée

| Entité | Créées | Supprimées | Reste |
|---|---:|---:|---|
| Groupes | 1 | **1** | 0 — `DELETE` fonctionne |
| Identities | 3 | 0 | 3 — **aucun DELETE sur ce service** |
| Users | 2 | 0 | 2 — dont 1 par cascade |
| Companies | 1 | 0 | 1 — **aucun DELETE** |
| Accounts | 1 | 0 | 1 — cascade, **aucun DELETE** |

Toutes portent le préfixe `DEMO_QA0808_`, sauf les entités créées par cascade,
dont le serveur choisit lui-même le nom.

---

## 1. ✅ `ANO-CPY-BUG-06` est CORRIGÉ

La page Service Anatomy le décrivait comme **bloquant** : *« le bug NoneType.email
empêche empiriquement la création de nouvelles Companies via l'API. À corriger
côté serveur avant démarrage réel du Loader. »*

**Mesure : `POST /api/v1/companies/` → HTTP 201.** Le blocage n'existe plus.
L'étape Organisation est débloquée.

---

## 2. 🔴 La cascade Company touche **TROIS** services, pas un

Compteurs avant / après une seule création :

| Service | Avant | Après | Delta |
|---|---:|---:|---|
| identity-service | 13 | 14 | **+1** |
| company-service | 7 | 8 | +1 |
| account-service | 48 | 49 | **+1** |
| **user-service** | 19 | 20 | **+1** |

`D-CMP-2` disait « `owner` cascade vers identity-service ». C'est vrai, mais
**incomplet** : la création d'une Company crée aussi un **Account** (`OPERATION`,
`XAF`, solde 0, `owner_type=COMPANY`) **et un User**.

### Mais le User créé est inutilisable

| Attribut | Valeur mesurée | Conséquence |
|---|---|---|
| `user_name` | `user-6968ee7960c84a229e96512ca61b5ceb` | auto-généré, imprévisible |
| `email` | **`owner.email`** — jamais `admin_email` | |
| mot de passe | **inconnu de nous** | le compte ne peut pas se connecter |
| `is_first_login` | `true` | bloqué au premier palier |
| `company_id` | **`''`** | **pas rattaché à sa propre Company** |
| `identity` | **le `company_id`** | défaut référentiel, voir §4 |

**Le Loader doit donc toujours créer son propre Admin User**, dont il maîtrise le
mot de passe — avec une adresse **distincte** de `owner.email`, puisque `INV-USR-02`
impose l'unicité et que la cascade a déjà consommé celle-là.

---

## 3. 🔴 `admin_email` ne crée **rien** — double vérification

J'ai envoyé `admin_email = qa0808.admincompany@…` et `owner.email = qa0808.dirigeant@…`.

- Le User créé porte **`owner.email`**
- **Zéro** User portant `admin_email`
- Recompté plusieurs minutes plus tard : toujours zéro — **la cascade n'est pas asynchrone**
- Relecture de la Company : `admin_email` renvoie **`None`**

`admin_email` est **write‑only et perdu**, exactement comme `currency`.

---

## 4. 🔴 Défaut référentiel non documenté — le `identity` du User cascade

Le champ `identity` du User créé par company-service pointe vers le **`company_id`**,
pas vers l'Identity.

Vérifié sur les **11 Users** au format `user-<hex>` de l'environnement :

| Origine de la cascade | `identity` pointe vers | Occurrences |
|---|---|---|
| **company-service** | la **Company** ❌ | **6 / 6** |
| client-service | la vraie Identity ✅ | 5 / 5 |
| — | référence fantôme | 0 |

> **Le défaut est systématique sur company-service, et absent de client-service.**
> Aucune référence morte : le bug est une confusion d'identifiant, pas une perte.

**À remonter en ticket.** Sans impact direct sur le Loader, qui crée son propre
Admin correctement référencé.

---

## 5. 🔴 `owner._id` est exigé au contrat mais **ignoré**

| | |
|---|---|
| UUID envoyé | `4915f9bd-…` |
| UUID rendu | `54dc7bb9-…` |

Le schéma déclare `_id` **requis** dans l'`Identity` embarquée, mais le serveur
**génère le sien**. Il faut le fournir pour passer la validation, et **toujours
relire celui qui est rendu**.

> ⚠️ **Le Document Maître §4 est à corriger** : *« `Company.owner._id` doit être
> généré côté client (Loader), pas par le serveur »* — c'est l'inverse. Le Loader
> le fournit, le serveur l'ignore.

---

## 6. ✅ `FRA-199` confirmé — mais la devise est **récupérable**

Relecture de la Company : `currency` → **`None`**. Perdue, comme documenté.

**Mais elle survit sur le compte `OPERATION` créé en cascade** : `currency: 'XAF'`.
Le Loader dispose donc d'un chemin de récupération, en plus de sa propre trace.

---

## 7. 🔴 Le flow en 3 requêtes — l'étape 2 refuse le token ROOT

```
PUT /auth/password/f/change  avec le token ROOT
  → HTTP 401 « Type de token invalide. Attendu: auth »

PUT /auth/password/f/change  avec l'auth_token de register
  → HTTP 200 « Password changed »
```

Aucune documentation ne précisait **quel** token utiliser à l'étape 2.

> **C'est l'explication de l'état de l'environnement.** 15 users sur 18 sont
> bloqués à `is_first_login=true` : le flow n'a jamais pu aboutir parce que le
> mauvais token était employé.

Séquence validée de bout en bout :

| Étape | Token | Résultat |
|---|---|---|
| `POST /auth/register` | ROOT | 201 · `auth_token` type `auth`, **600 s** |
| `PUT /auth/password/f/change` | **`auth_token`** | 200 · `is_first_login` → `false` |
| `POST /auth/login` | — | 200 · `access_token` **4 h** + `refresh_token` **168 h** |

Détail mesuré : tant que `is_first_login=true`, `access_token` est **présent mais
vide** — la clé existe, la valeur non.

---

## 8. 🟠 `D-CLI-3` est plus permissive que son message

| `id_number` | Résultat |
|---|---|
| `CM250509273` | 201 ✅ |
| `QA_0808_BAD` (underscore) | 422 ✅ refusé |
| **`cm250509274` (minuscules)** | **201 — ACCEPTÉ** |

Le message annonce *« expected alphanumeric **uppercase** only »*, mais les
minuscules passent. La règle réelle est **« alphanumérique, sans caractère
spécial »**. Le Loader continue d'envoyer des majuscules — se conformer au message
reste le choix sûr.

---

## 9. 🔴 `nationality` exige un code ISO 3166‑1 alpha‑2

```
nationality: "Cameroun"  → 422 « must be a valid ISO 3166-1 alpha-2 country code »
nationality: "CM"        → 201
```

**Bug trouvé dans notre propre code.** `generateur.identite()` produisait le libellé
du pays. Aucun test hors ligne ne pouvait le détecter — seule une écriture réelle
le pouvait. Corrigé, et le test dit désormais pourquoi.

---

## 10. Autres champs validés à la création d'Identity

| Champ omis | Résultat |
|---|---|
| `id_expire_on` | 422 « Field required » — `D-CLI-2` confirmé au contrat |
| `occupation` | 422 « Field required » |
| `address` | 422 « Field required » |

Et la route est **`POST /identities/create`**, pas `POST /identities/` (405).
La convention est **incohérente d'un service à l'autre** :

| Avec `/create` | Sans `/create` |
|---|---|
| identity · config · depositary · groupes | company · product · account |

Enfin : une Identity créée **directement** rend `type: INDIVIDUAL` par défaut.
L'écrasement vers `CORPORATE` de `D-CLI-4` est **propre à client-service**.

---

## 11. ✅ product-service — trois invariants confirmés en écriture

| Test | Résultat |
|---|---|
| `category = "ANY"` | **422** — *« Input should be 'INDIVIDUAL' or 'CORPORATE' »* · `INV-PRD-04` |
| `policy` omise | **500** + fuite Python `LendingPolicySchema() argument after ** must be a mapping` · `ANO-PRD-POLICY-01`. **Aucun orphelin** : le compteur n'a pas bougé |
| Payload complet du catalogue | **201** · Policy dédiée `52d02e5a…` · `interest = 24.0` · `amount_by_segment` **intégralement préservé** avec les 5 segments |

**Premier produit LENDING de l'environnement** : 0 → 1. Le module `catalogue.py`
est validé contre le serveur réel, pas seulement hors ligne.

## 12. ✅ `D-DEP-2` confirmé de bout en bout

| Étape | Comptes | Delta |
|---|---:|---|
| Création du Dépositaire seule | 49 → 49 | **+0** |
| **1re souscription** | 49 → 55 | **+6** |
| 2e souscription (autre produit) | 55 → 55 | **+0** — les mêmes sont réutilisés |
| Souscription **dupliquée** | 55 → 55 | +0, mais **HTTP 201** — `FRA-202`, aucune protection |

Les 6 comptes : `CAPITAL, CLASSIC, INTEREST, PENALTY, TAXE, TERM_DEPOSIT`, tous en
`XAF`, tous à solde 0. Le Dépositaire naît **actif** — aucun `PATCH` requis.

### Modèle réel de la souscription — non documenté ailleurs

Il n'existe **qu'une seule souscription par Dépositaire**, dont le champ `product`
est un **tableau**. Souscrire n'en crée pas une nouvelle : cela **ajoute au
tableau**. Le doublon s'y accumule donc silencieusement :

```
1 souscription  →  product = ['Cotisation 20000/mois', 'plastique', 'plastique']
```

Validation référentielle confirmée : `product_id` inexistant → **404 « Product not
found »**, `depositary_id` inexistant → **400 « Depositary not found »**. Deux codes
différents pour deux références manquantes.

---

## 13. 🔴 `ANO-DEP-TYPE-02` — aucun contrôle de cohérence de type

**Question posée** : LENDING = prêt, COLLECT = épargne — et concrètement ?

La différence n'est pas décorative, elle est **dans le schéma** :

| | LENDING | COLLECT |
|---|---|---|
| Champs propres | `loan_duration`, `recovery_day`, `interest_calculation`, `interest_application`, `penalty_day`, `is_reconductable`, **`amount_by_segment`** | `type` (CASH/CASH_DAT/PRODUCT), `measure`, `measure_price`, `interest_rate`, `vat` |
| Ce que ça dit | combien on prête, sur quelle durée, quand on recouvre | combien on collecte, à quelle cadence, sur quel support |
| Requis | 10 champs | 8 champs |
| Communs | `amount_min`, `amount_max`, `penalty_*` | idem |

**Mais le serveur ne vérifie rien.** Souscrire un **Dépositaire** — une structure
d'épargne — à un produit **LENDING** :

```
POST /depositaries/subscriptions/create  { product_id: <LENDING>, ... }
  → HTTP 201

produits = [('Cotisation 20000/mois','COLLECT'), ('plastique','COLLECT'),
            ('plastique','COLLECT'), ('DEMO_QA0808_Nano','LENDING')]
```

Un kiosque d'épargne peut donc « vendre » un prêt, et rien ne l'en empêche.

> **La barrière est côté Loader — `D-DEP-9`.** `valider_type_produit()` lève
> **avant le réseau**, même patron que `valider_montant()` (`FRA-195`) : ce qui
> n'a pas de sens ne doit pas partir. Elle est `@staticmethod`, donc éprouvable
> sans client HTTP — une barrière testable seulement contre le serveur n'est pas
> une barrière.

Double garde : `filtrer_catalogue()` écarte les LENDING **avant** la boucle (une
fois, pas 54), et `souscrire()` revalide de son côté au cas où le filtre serait
contourné.

### Qui consomme réellement les produits

| Service | `product_id` au contrat |
|---|---:|
| client-service | 4 |
| collect-service | 4 |
| depositary-service | 4 |
| account-service | **0** |
| company-service | **0** |

Les trois consommateurs sont **tous du côté épargne**. Aucun service livré ne
consomme un produit LENDING : le module de prêt relève du **Sprint 5** (`CT-02`).

**Un produit LENDING sert-il quand même au Loader ?** Oui, pour trois raisons :
`UC-11` et `EF-69` en exigent le catalogue ; `amount_by_segment` est la **source
des montants** de la simulation comportementale `UC-02` ; et le jour où
loan-service arrive, le catalogue est déjà en place. Ce qu'il ne fait **pas** :
alimenter une souscription.

---

## Corrections apportées au code

| Défaut | Correction |
|---|---|
| `nationality` = libellé du pays | → code ISO2 |
| `password/f/change` avec le token ROOT | → `token_alternatif` dans `base.py`, `auth_token` transmis |
| Admin User référençant l'`identity_id` généré localement | → l'identifiant **rendu par le serveur** |
| `admin_email` = `owner.email` | → adresse distincte, pour éviter le conflit d'unicité |
| `souscrire()` sans contrôle de type | → `type_produit` **obligatoire et nommé** + `D-DEP-9` |

**97 tests verts** après corrections.

---

## À remonter à l'équipe serveur

1. **Défaut référentiel** — le User cascade de company-service référence le
   `company_id` dans son champ `identity` (6 cas sur 6).
2. **`company_id` vide** sur tous les Users cascade — aucun rattachement.
3. **`admin_email` inutilisé** — le champ est requis, accepté, et sans effet.
4. **`id_number`** — le message d'erreur annonce une contrainte de casse qui n'est
   pas appliquée.
5. **`ANO-DEP-TYPE-02`** — aucun contrôle de cohérence de type : un Dépositaire
   peut souscrire à un produit `LENDING` en HTTP 201. Neutralisé côté Loader par
   `D-DEP-9`, mais la validation manque côté serveur.

---

*Campagne exécutée avec autorisation, empreinte minimale et documentée, chaque
conclusion contre‑vérifiée avant d'être écrite.*
