# `A-05` — les 12 rôles et leurs permissions, **telles qu'elles sont en base**

| | |
|---|---|
| **Objet** | Arbitrage produit en attente. Table présentée sans correction ni proposition. |
| **Mesuré le** | 10 août 2026, par lecture directe de `GET /api/v1/groupes/` |
| **Mapping corrigé le** | 10 août 2026 (`D-09 v2`) puis **revérifié contre le code le 23 août 2026** — 6 rôles sur 12 avaient un `tag`/`UserType` périmé dans ce document |
| **Permissions assignables** | 61 — les 22 `LENDER_*` et la parasite `RC169_*` sont écartées en amont (`D-07`) |
| **Statut** | ⚠️ **Attribuées par le Loader sur sa propre proposition, jamais validées** |
| **Réversibilité** | `DELETE /api/v1/groupes/{id}` **prouvé fonctionnel** le 9 août — tout est révocable |

> ### Ce qu'on demande à l'administration
> Ces permissions ont été **attribuées par le Loader sur sa propre
> proposition, et jamais validées par personne**. Nous demandons un
> arbitrage produit, rôle par rôle. Tout est révocable :
> `DELETE /api/v1/groupes/{id}` est prouvé fonctionnel (9 août).
>
> **Le défaut à corriger en priorité** : la règle ne distingue jamais
> LECTURE et ÉCRITURE. Un Marketing peut créer et modifier des produits,
> pas seulement les consulter. Un Compliance peut modifier des identités.
> C'est grossier par construction, et c'est assumé le temps de l'arbitrage.
>
> **`STAFF` ≠ personnel des institutions.** `STAFF` désigne le SIÈGE
> FinZuu ; `COMPANY` le personnel des institutions clientes. Le Loader
> génère des IMF, pas le siège — d'où 8 rôles en `COMPANY` et seulement
> 2 en `STAFF` (Compliance et Employé/IT, fonctions siège exclusives).
>
> La règle appliquée est écrite dans `roles_execution.py` : *« chaque rôle
> reçoit les permissions dont le préfixe correspond à son domaine »*. Elle est
> **grossière par construction : elle ne distingue jamais lecture et écriture.**

---

## Ce que chaque rôle permet de FAIRE — en clair

> Écrit le 23/08 à la demande de Yaniv. Les codes de permission ne disent rien
> à qui doit choisir un rôle pour quelqu'un. Voici la traduction, rôle par
> rôle, de ce que la personne pourra réellement faire une fois le rôle
> attribué. **Chaque ligne est dérivée des permissions mesurées, pas d'une
> intention.**

| Rôle | Ce que la personne peut faire | Ce qu'elle NE peut PAS faire |
|---|---|---|
| **Super-Admin** | **Tout.** Les 61 permissions : administrer les utilisateurs, les rôles et les permissions ; créer et modifier des institutions et leurs licences ; le référentiel (pays, villes, devises, opérateurs mobiles) ; les identités ; les produits et politiques ; les comptes et transactions ; les dépositaires et souscriptions ; les menus USSD | rien — c'est le rôle sans limite |
| **Admin** | Administrer **les utilisateurs, les rôles et les permissions** ; créer et modifier des institutions et leurs licences ; créer et modifier le **référentiel géographique et monétaire** ; créer et modifier des identités ; lire les journaux | toucher aux comptes, transactions, produits, dépositaires, clients |
| **Marketing** | **Créer et modifier** des produits et des politiques tarifaires ; enrôler un client, le lire, le modifier | comptes, transactions, dépositaires, utilisateurs |
| **Compliance** | Créer et modifier des **identités** (l'état civil KYC) ; créer et modifier le **référentiel** (pays, villes, devises, opérateurs) ; enrôler et modifier des clients | comptes, transactions, produits, dépositaires, utilisateurs |
| **Collecte** | Lire et **écrire** les collectes ; lire et **écrire** les dépositaires et leurs souscriptions | clients, comptes, produits, utilisateurs |
| **Comptable** | **Créer** des comptes, lire et **écrire** comptes et transactions | tout le reste |
| **Branche** | Enrôler, lire et modifier des clients ; lire et **écrire** dépositaires et souscriptions | comptes, transactions, produits, utilisateurs |
| **Employé/IT** | Administrer **les utilisateurs, les rôles, les permissions et les menus** ; activer/désactiver un compte utilisateur ; lire les journaux | aucune donnée métier (ni client, ni compte, ni produit, ni dépositaire) |
| **Agent** | Enrôler, lire et modifier des clients ; lire et **écrire** les collectes | comptes, dépositaires, produits, utilisateurs |
| **Marchand** | **Créer** des comptes, lire et **écrire** comptes et transactions — *exactement les mêmes pouvoirs que le Comptable* | tout le reste |
| **Kiosque** | Lire et **écrire** collectes, dépositaires et souscriptions — *exactement les mêmes pouvoirs que Collecte* | clients, comptes, produits, utilisateurs |
| **CUSTOMER** | Lire et **écrire** ses comptes et **ses transactions** ; lire et modifier sa fiche client ; faire des collectes ; s'enregistrer ; lire les menus USSD | administration, produits, dépositaires |

---

## Les six questions que nous posons à l'administration

Chacune vient d'un fait mesuré ci-dessus, pas d'une opinion.

### 1. 🔴 Un **Admin** d'institution peut se fabriquer n'importe quel pouvoir

`Admin` porte `USER_GROUPE_CREATE`, `USER_GROUPE_UPDATE`, `USER_GROUPE_DELETE`,
`USER_PERMISSION_CREATE`, `USER_PERMISSION_DELETE` et `USER_AUTH_REGISTER`.

**Concrètement** : une personne à qui l'on donne le rôle Admin peut créer un
nouveau rôle, y mettre les 61 permissions, créer un utilisateur et le lui
attribuer. Elle devient Super-Admin en trois requêtes. Or `Admin` est typé
`COMPANY` — c'est le personnel d'une **institution cliente**, pas le siège.

**Question** : un Admin d'institution doit-il pouvoir administrer les rôles et
les permissions de la plateforme, ou seulement les **utilisateurs** de sa
propre institution ?

### 2. 🔴 Trois rôles peuvent modifier le référentiel PARTAGÉ

`Admin` et `Compliance` portent `IDENTITY_COUNTRY_CREATE`,
`IDENTITY_CITY_CREATE`, `IDENTITY_CURRENCY_CREATE` et leurs `UPDATE`.

**Concrètement** : le personnel d'une institution peut créer un pays, une ville
ou une devise que **toutes les autres institutions** verront. Ces objets n'ont
aucune suppression côté serveur — une erreur est définitive.

**Question** : la géographie et les devises doivent-elles rester au siège ?

### 3. 🟠 La règle ne distingue jamais LECTURE et ÉCRITURE

Un `Marketing` **crée et modifie** des produits et des tarifs — il ne les
consulte pas. Un `Compliance` **crée et modifie** des identités. Un `Agent`
**modifie** des clients.

**Question** : quels rôles doivent être en lecture seule sur quels domaines ?

### 4. 🟠 Trois paires de rôles sont strictement identiques

`Marchand` = `Comptable` (5 permissions `ACCOUNT_*`, à l'identique).
`Kiosque` = `Collecte` (6 permissions, à l'identique).
`Branche` = `Collecte` + les clients.

**Question** : est-ce voulu ? Sinon, qu'est-ce qui doit les distinguer ?

### 5. 🟠 Un CUSTOMER peut écrire des transactions et des collectes

`ACCOUNT_TRANSACTION_WRITE` et `COLLECT_COLLECT_WRITE` sur le rôle du **client
final**. Ce rôle préexistait en base, le Loader ne l'a pas défini.

**Question** : un client final doit-il pouvoir écrire une transaction
lui-même, ou seulement la demander ?

### 6. 🟡 Personne ne peut supprimer un utilisateur

Aucun rôle ne porte de permission de suppression d'utilisateur : seulement
`USER_USER_ACTIVATE` et `USER_USER_DEACTIVATE`.

**Question** : c'est un choix de conception à confirmer — la désactivation
tient-elle lieu de suppression ?

---

## Ce qui se passe si rien n'est tranché

Les 11 rôles sont créés **tels que décrits ci-dessus**, et toute personne à
qui l'on donne `Admin` ou `Employé/IT` peut, dès demain, créer un utilisateur
de n'importe quel type et lui attribuer n'importe quel rôle — y compris un
rôle qu'elle vient de fabriquer avec tous les pouvoirs.

C'est réversible : `DELETE /api/v1/groupes/{id}` est prouvé fonctionnel
(9 août). Mais tant que l'arbitrage n'est pas rendu, c'est l'état du système.


---

## Vue d'ensemble

| Rôle | tag | UserType | perms | Familles couvertes |
|---|---|---|---:|---|
| **Super-Admin** | `STAFF` | `ROOT` | **61** | USER 18 · IDENTITY 15 · COMPANY 6 · PRODUCT 6 · ACCOUNT 5 · DEPOSITARY 4 · CLIENT 3 · COLLECT 2 · USSD 2 |
| **Admin** | `COMPANY` | `COMPANY` | **39** | USER 18 · IDENTITY 15 · COMPANY 6 |
| **Marketing** | `COMPANY` | `COMPANY` | **9** | PRODUCT 6 · CLIENT 3 |
| **Compliance** | `STAFF` | `STAFF` | **18** | IDENTITY 15 · CLIENT 3 |
| **Collecte** | `COMPANY` | `COMPANY` | **6** | DEPOSITARY 4 · COLLECT 2 |
| **Comptable** | `COMPANY` | `COMPANY` | **5** | ACCOUNT 5 |
| **Branche** | `COMPANY` | `COMPANY` | **7** | DEPOSITARY 4 · CLIENT 3 |
| **Employe/IT** | `STAFF` | `STAFF` | **18** | USER 18 |
| **Agent** | `COMPANY` | `COMPANY` | **5** | CLIENT 3 · COLLECT 2 |
| **Marchand** | `COMPANY` | `COMPANY` | **5** | ACCOUNT 5 |
| **Kiosque** | `COMPANY` | `COMPANY` | **6** | DEPOSITARY 4 · COLLECT 2 |
| **CUSTOMER** *(réutilisé)* | `CUSTOMER` | `CUSTOMER` | **12** | ACCOUNT 4 · USER 3 · CLIENT 2 · COLLECT 2 · USSD 1 |

---

## Détail par rôle

### Super-Admin

`tag: STAFF` · `UserType: ROOT` · créé par le Loader · **61 permissions**

Règle appliquée : préfixes `USER_`, `COMPANY_`, `IDENTITY_`, `ACCOUNT_`, `PRODUCT_`, `CLIENT_`, `COLLECT_`, `DEPOSITARY_`, `USSD_`

- `ACCOUNT_ACCOUNT_CREATE`
- `ACCOUNT_ACCOUNT_READ`
- `ACCOUNT_ACCOUNT_WRITE`
- `ACCOUNT_TRANSACTION_READ`
- `ACCOUNT_TRANSACTION_WRITE`
- `CLIENT_CLIENT_ONBOARD`
- `CLIENT_CLIENT_READ`
- `CLIENT_CLIENT_UPDATE`
- `COLLECT_COLLECT_READ`
- `COLLECT_COLLECT_WRITE`
- `COMPANY_COMPANY_CREATE`
- `COMPANY_COMPANY_READ`
- `COMPANY_COMPANY_UPDATE`
- `COMPANY_LICENSE_CREATE`
- `COMPANY_LICENSE_READ`
- `COMPANY_LICENSE_UPDATE`
- `DEPOSITARY_DEPOSITARY_READ`
- `DEPOSITARY_DEPOSITARY_WRITE`
- `DEPOSITARY_SUBSCRIPTION_READ`
- `DEPOSITARY_SUBSCRIPTION_WRITE`
- `IDENTITY_CITY_CREATE`
- `IDENTITY_CITY_READ`
- `IDENTITY_CITY_UPDATE`
- `IDENTITY_COUNTRY_CREATE`
- `IDENTITY_COUNTRY_READ`
- `IDENTITY_COUNTRY_UPDATE`
- `IDENTITY_CURRENCY_CREATE`
- `IDENTITY_CURRENCY_READ`
- `IDENTITY_CURRENCY_UPDATE`
- `IDENTITY_IDENTITY_CREATE`
- `IDENTITY_IDENTITY_READ`
- `IDENTITY_IDENTITY_UPDATE`
- `IDENTITY_MMO_CREATE`
- `IDENTITY_MMO_READ`
- `IDENTITY_MMO_UPDATE`
- `PRODUCT_POLICY_CREATE`
- `PRODUCT_POLICY_READ`
- `PRODUCT_POLICY_UPDATE`
- `PRODUCT_PRODUCT_CREATE`
- `PRODUCT_PRODUCT_READ`
- `PRODUCT_PRODUCT_UPDATE`
- `USER_AUTH_REGISTER`
- `USER_GROUPE_CREATE`
- `USER_GROUPE_DELETE`
- `USER_GROUPE_READ`
- `USER_GROUPE_UPDATE`
- `USER_LOG_READ`
- `USER_MENU_CREATE`
- `USER_MENU_DELETE`
- `USER_MENU_READ`
- `USER_MENU_UPDATE`
- `USER_PERMISSION_CREATE`
- `USER_PERMISSION_DELETE`
- `USER_PERMISSION_READ`
- `USER_PERMISSION_UPDATE`
- `USER_USER_ACTIVATE`
- `USER_USER_DEACTIVATE`
- `USER_USER_READ`
- `USER_USER_UPDATE`
- `USSD_MENUS_READ`
- `USSD_MENUS_WRITE`

### Admin

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **39 permissions**

Règle appliquée : préfixes `USER_`, `COMPANY_`, `IDENTITY_`

- `COMPANY_COMPANY_CREATE`
- `COMPANY_COMPANY_READ`
- `COMPANY_COMPANY_UPDATE`
- `COMPANY_LICENSE_CREATE`
- `COMPANY_LICENSE_READ`
- `COMPANY_LICENSE_UPDATE`
- `IDENTITY_CITY_CREATE`
- `IDENTITY_CITY_READ`
- `IDENTITY_CITY_UPDATE`
- `IDENTITY_COUNTRY_CREATE`
- `IDENTITY_COUNTRY_READ`
- `IDENTITY_COUNTRY_UPDATE`
- `IDENTITY_CURRENCY_CREATE`
- `IDENTITY_CURRENCY_READ`
- `IDENTITY_CURRENCY_UPDATE`
- `IDENTITY_IDENTITY_CREATE`
- `IDENTITY_IDENTITY_READ`
- `IDENTITY_IDENTITY_UPDATE`
- `IDENTITY_MMO_CREATE`
- `IDENTITY_MMO_READ`
- `IDENTITY_MMO_UPDATE`
- `USER_AUTH_REGISTER`
- `USER_GROUPE_CREATE`
- `USER_GROUPE_DELETE`
- `USER_GROUPE_READ`
- `USER_GROUPE_UPDATE`
- `USER_LOG_READ`
- `USER_MENU_CREATE`
- `USER_MENU_DELETE`
- `USER_MENU_READ`
- `USER_MENU_UPDATE`
- `USER_PERMISSION_CREATE`
- `USER_PERMISSION_DELETE`
- `USER_PERMISSION_READ`
- `USER_PERMISSION_UPDATE`
- `USER_USER_ACTIVATE`
- `USER_USER_DEACTIVATE`
- `USER_USER_READ`
- `USER_USER_UPDATE`

### Marketing

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **9 permissions**

Règle appliquée : préfixes `CLIENT_`, `PRODUCT_`

- `CLIENT_CLIENT_ONBOARD`
- `CLIENT_CLIENT_READ`
- `CLIENT_CLIENT_UPDATE`
- `PRODUCT_POLICY_CREATE`
- `PRODUCT_POLICY_READ`
- `PRODUCT_POLICY_UPDATE`
- `PRODUCT_PRODUCT_CREATE`
- `PRODUCT_PRODUCT_READ`
- `PRODUCT_PRODUCT_UPDATE`

### Compliance

`tag: STAFF` · `UserType: STAFF` · créé par le Loader · **18 permissions**

Règle appliquée : préfixes `IDENTITY_`, `CLIENT_`

- `CLIENT_CLIENT_ONBOARD`
- `CLIENT_CLIENT_READ`
- `CLIENT_CLIENT_UPDATE`
- `IDENTITY_CITY_CREATE`
- `IDENTITY_CITY_READ`
- `IDENTITY_CITY_UPDATE`
- `IDENTITY_COUNTRY_CREATE`
- `IDENTITY_COUNTRY_READ`
- `IDENTITY_COUNTRY_UPDATE`
- `IDENTITY_CURRENCY_CREATE`
- `IDENTITY_CURRENCY_READ`
- `IDENTITY_CURRENCY_UPDATE`
- `IDENTITY_IDENTITY_CREATE`
- `IDENTITY_IDENTITY_READ`
- `IDENTITY_IDENTITY_UPDATE`
- `IDENTITY_MMO_CREATE`
- `IDENTITY_MMO_READ`
- `IDENTITY_MMO_UPDATE`

### Collecte

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **6 permissions**

Règle appliquée : préfixes `COLLECT_`, `DEPOSITARY_`

- `COLLECT_COLLECT_READ`
- `COLLECT_COLLECT_WRITE`
- `DEPOSITARY_DEPOSITARY_READ`
- `DEPOSITARY_DEPOSITARY_WRITE`
- `DEPOSITARY_SUBSCRIPTION_READ`
- `DEPOSITARY_SUBSCRIPTION_WRITE`

### Comptable

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **5 permissions**

Règle appliquée : préfixes `ACCOUNT_`

- `ACCOUNT_ACCOUNT_CREATE`
- `ACCOUNT_ACCOUNT_READ`
- `ACCOUNT_ACCOUNT_WRITE`
- `ACCOUNT_TRANSACTION_READ`
- `ACCOUNT_TRANSACTION_WRITE`

### Branche

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **7 permissions**

Règle appliquée : préfixes `DEPOSITARY_`, `CLIENT_`

- `CLIENT_CLIENT_ONBOARD`
- `CLIENT_CLIENT_READ`
- `CLIENT_CLIENT_UPDATE`
- `DEPOSITARY_DEPOSITARY_READ`
- `DEPOSITARY_DEPOSITARY_WRITE`
- `DEPOSITARY_SUBSCRIPTION_READ`
- `DEPOSITARY_SUBSCRIPTION_WRITE`

### Employe/IT

`tag: STAFF` · `UserType: STAFF` · créé par le Loader · **18 permissions**

Règle appliquée : préfixes `USER_`

- `USER_AUTH_REGISTER`
- `USER_GROUPE_CREATE`
- `USER_GROUPE_DELETE`
- `USER_GROUPE_READ`
- `USER_GROUPE_UPDATE`
- `USER_LOG_READ`
- `USER_MENU_CREATE`
- `USER_MENU_DELETE`
- `USER_MENU_READ`
- `USER_MENU_UPDATE`
- `USER_PERMISSION_CREATE`
- `USER_PERMISSION_DELETE`
- `USER_PERMISSION_READ`
- `USER_PERMISSION_UPDATE`
- `USER_USER_ACTIVATE`
- `USER_USER_DEACTIVATE`
- `USER_USER_READ`
- `USER_USER_UPDATE`

### Agent

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **5 permissions**

Règle appliquée : préfixes `COLLECT_`, `CLIENT_`

- `CLIENT_CLIENT_ONBOARD`
- `CLIENT_CLIENT_READ`
- `CLIENT_CLIENT_UPDATE`
- `COLLECT_COLLECT_READ`
- `COLLECT_COLLECT_WRITE`

### Marchand

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **5 permissions**

Règle appliquée : préfixes `ACCOUNT_`

- `ACCOUNT_ACCOUNT_CREATE`
- `ACCOUNT_ACCOUNT_READ`
- `ACCOUNT_ACCOUNT_WRITE`
- `ACCOUNT_TRANSACTION_READ`
- `ACCOUNT_TRANSACTION_WRITE`

### Kiosque

`tag: COMPANY` · `UserType: COMPANY` · créé par le Loader · **6 permissions**

Règle appliquée : préfixes `COLLECT_`, `DEPOSITARY_`

- `COLLECT_COLLECT_READ`
- `COLLECT_COLLECT_WRITE`
- `DEPOSITARY_DEPOSITARY_READ`
- `DEPOSITARY_DEPOSITARY_WRITE`
- `DEPOSITARY_SUBSCRIPTION_READ`
- `DEPOSITARY_SUBSCRIPTION_WRITE`

### CUSTOMER

`tag: CUSTOMER` · `UserType: CUSTOMER` · **RÉUTILISÉ** — présent en base avant le projet, non modifié · **12 permissions**

Règle appliquée : préfixes *aucun — rôle réutilisé tel quel*

- `ACCOUNT_ACCOUNT_READ`
- `ACCOUNT_ACCOUNT_WRITE`
- `ACCOUNT_TRANSACTION_READ`
- `ACCOUNT_TRANSACTION_WRITE`
- `CLIENT_CLIENT_READ`
- `CLIENT_CLIENT_UPDATE`
- `COLLECT_COLLECT_READ`
- `COLLECT_COLLECT_WRITE`
- `USER_AUTH_REGISTER`
- `USER_USER_READ`
- `USER_USER_UPDATE`
- `USSD_MENUS_READ`

