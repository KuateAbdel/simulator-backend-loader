# Audit d'intégration inter-services — 8 août 2026

| | |
|---|---|
| **Objet** | Comment les 9 services cohabitent réellement : qui référence qui, et ces références tiennent-elles ? |
| **Méthode** | Lecture seule, exhaustive. Chaque référence croisée est résolue contre le service cible. Aucune conclusion tirée d'un premier comptage. |
| **Inventaire** | 8 companies · 14 identities · 20 users · 55 accounts · 12 depositaries · 8 products · 3 clients |

---

## 1. 🔴 `ANO-ACC-OWNER-03` — `owner_type=COMPANY` désigne **deux choses**

Premier comptage : **43 comptes `owner_type=COMPANY` dont l'`owner_id` est
introuvable dans company-service**. Un tel chiffre annonce une base corrompue.
**Il ne l'est pas.** Contre-vérification :

| `owner_type=COMPANY`, l'`owner_id` pointe vers | Comptes |
|---|---:|
| **depositary-service** | **42** |
| company-service | 8 |
| nulle part | 1 |

Le croisement avec le **type** de compte est sans exception :

| Type de compte | Propriétaire réel | Occurrences |
|---|---|---:|
| `OPERATION` | **Company** | 8 / 8 |
| `CAPITAL`, `CLASSIC`, `INTEREST`, `PENALTY`, `TAXE`, `TERM_DEPOSIT` | **Depositary** | 42 / 42 |

> **`owner_type` n'est pas un discriminant fiable — le `type` du compte l'est.**
> Un Dépositaire est enregistré comme une « Company » dans account-service.
> `AccountOwnerType` ne possède aucune valeur `DEPOSITARY`.

**Règle pour le Loader** : pour retrouver les comptes d'un Kiosque, filtrer
`owner_type=COMPANY` **ET** `type != OPERATION`, puis résoudre l'`owner_id`
contre depositary-service. Ne jamais se fier à `owner_type` seul.

**Ceci clôt le Trou #2** : 42 comptes = 7 Dépositaires × 6, plus 8 `OPERATION`
en cascade de Company, plus 4 `CHECKING` de clients, plus 1 référence morte.
**55 sur 55, tous expliqués.**

---

## 2. ✅ Les cascades tiennent — sauf une, déjà connue

| Référence croisée | Résolution |
|---|---|
| `company.owner._id` → identity-service | **8 / 8** ✅ |
| `account.owner_id` (`IDENTITY`) → identity-service | **4 / 4** ✅ |
| `depositary.company_id` → company-service | 11 / 12 |
| `user.identity` → identity-service | 6 / 12 — **les 6 manquants sont des `company_id`** |

Les 6 échecs de `user.identity` ne sont **pas** des références mortes : ce sont
les Users en cascade de company-service, dont le champ `identity` porte le
`company_id`. Défaut déjà documenté (§4 de la campagne d'écriture), confirmé ici
sur l'ensemble de la population.

---

## 3. 🔴 `ANO-DEP-FK-04` — `company_id` n'est pas validé à la création d'un Dépositaire

Le Dépositaire `'Testtt'` porte `company_id = 0781f400-…`. Résolution directe :

```
GET /api/v1/companies/0781f400-86b2-406f-a455-76df5ed69ef1 → 404
```

**Une Company inexistante a été acceptée.** depositary-service ne vérifie pas
cette référence — contrairement à `product_id` et `depositary_id` sur les
souscriptions, qui sont bien validés (404 / 400). La validation est donc
**partielle et incohérente** au sein d'un même service.

**Conséquence pour le Loader** : le `company_id` transmis doit provenir de la
lecture qui suit la création de la Company, jamais d'un identifiant reconstruit.
Le serveur ne rattrapera pas l'erreur.

---

## 4. Carte de cohabitation — qui crée quoi chez qui

```
POST company-service /companies/
     ├─► identity-service   +1 Identity   (owner, _id GÉNÉRÉ par le serveur)
     ├─► account-service    +1 OPERATION  (owner_type=COMPANY, correct)
     └─► user-service       +1 User       INUTILISABLE : mdp inconnu,
                                          company_id vide, identity = company_id

POST depositary-service /depositaries/create
     └─► (rien)  +0 compte — le Dépositaire naît ACTIF

POST depositary-service /subscriptions/create   ← 1re seulement
     └─► account-service    +6 comptes    owner_type=COMPANY, owner_id=DEPOSITARY

POST product-service /products/
     └─► (interne)          +1 Policy dédiée, jamais partagée

POST client-service /onboard
     ├─► identity-service   +1 Identity
     ├─► user-service       +1 User       identity CORRECT ici (5/5)
     └─► account-service    +1 CHECKING   owner_type=IDENTITY, correct
```

**Trois services écrivent chez account-service sans qu'on le leur demande.**
C'est pourquoi le Loader ne crée jamais un compte qu'il n'a pas d'abord cherché.

---

## 5. Ce que l'environnement montre du catalogue

8 produits, dont **7 COLLECT et 1 LENDING** — ce dernier étant celui créé le
08/08. Deux `Cotisation 20000/mois` **strictement homonymes** : `INV-PRD-01`
confirmé, aucune unicité de nom. D'où `chercher_par_nom()` qui gère le doublon
au lieu de le découvrir.

---

*Audit en lecture seule. Aucune écriture. Chaque chiffre contre-vérifié avant
d'être écrit ici — le premier comptage annonçait 43 orphelins, il y en a 1.*
