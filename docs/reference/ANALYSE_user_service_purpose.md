# Service Utilisateur — la couche *purpose*

| | |
|---|---|
| **Source** | Document Fonctionnel FinZuu, TNS Agency v1.0 (18/03/2026) — `docs/reference/documentation_technique.pdf`, §II.2 |
| **Croisé avec** | l'OpenAPI réel v1.0.1 (40 chemins), la matrice RBAC, et les disciplines `D-USR-*` du Loader |
| **Établi le** | 10 août 2026 |

> Ce document ne décrit pas *comment* le service marche (c'est l'affaire de
> l'OpenAPI et des disciplines). Il répond à la question qui vient **avant** :
> **pourquoi ce service existe, et quel problème humain il résout.**

---

## 1. À quel besoin métier réel répond-il ?

**Un besoin de confiance et de contrôle d'accès dans un système qui manipule
l'argent d'autrui.**

FinZuu est une plateforme *Banking-as-a-Service* : plusieurs institutions
(banques, IMF, opérateurs télécoms) opèrent **sur la même infrastructure**. La
question fondatrice n'est pas technique, elle est humaine :

> *« Qui a le droit de faire quoi, sur l'argent de qui ? »*

Le Document Fonctionnel le dit en une phrase (§II.2) :
*« Ce service gère les utilisateurs, les menus, les permissions et les groupes
de **tout le système**. »*

**« Tout le système »** est le mot important. User-service n'est pas *un* service
parmi neuf — c'est **le gardien** devant les huit autres. Sans lui, n'importe
qui créditerait n'importe quel compte.

---

## 2. Quel problème humain résout-il ?

Trois problèmes, tous liés à la **méfiance nécessaire** d'un système financier :

**a) Le problème de l'usurpation.** Dans une IMF de quartier, l'agent qui
enregistre une épargne n'est pas le directeur qui approuve un investissement.
User-service **matérialise cette séparation des rôles** — le flow à 3 requêtes
(register → change password → login) garantit qu'un compte créé par
l'administrateur ne devient utilisable qu'après que **la personne elle-même** a
posé son mot de passe. L'administrateur crée l'accès, il ne connaît jamais le
secret.

**b) Le problème de l'imputabilité.** Quand de l'argent bouge, il faut pouvoir
répondre à *« qui a fait ça ? »*. Le Document Fonctionnel prévoit
`Log (log_user)` avec `ip_address`, `country`, `user`, `menu` (§II.2.2.5) — un
journal d'audit des actions. C'est l'exigence FATF/AML : toute action tracée à
une personne.

**c) Le problème de l'accès dégradé.** Le contexte est l'Afrique subsaharienne,
*« Low Connectivity »* (Introduction du doc). Un même utilisateur métier doit
pouvoir agir depuis un smartphone (App), un ordinateur (BackOffice) ou **un
téléphone basique par USSD**. User-service authentifie **indépendamment du
canal** — le jeton vaut partout.

---

## 3. Quelle est sa raison d'être — en une phrase

> **User-service est le registre d'identité opérationnelle et le point de
> contrôle d'accès de toute la plateforme.** Il ne manipule aucun argent ; il
> décide qui, parmi les humains, a le droit d'en manipuler.

Il faut le distinguer nettement d'identity-service, avec lequel on le confond
facilement :

| | user-service | identity-service |
|---|---|---|
| Gère | **l'accès** (qui se connecte, avec quels droits) | **l'identité civile** (KYC : CNI, date de naissance) |
| Répond à | *« as-tu le droit ? »* | *« qui es-tu, légalement ? »* |
| Objet central | `User` (compte + groupe + permissions) | `Identity` (pièce, nationalité, adresse) |
| Lien | un `User` **porte** une `Identity` | une `Identity` peut exister **sans** `User` (un client final) |

**Un client de microfinance a une `Identity` mais pas forcément un `User`** — il
n'administre rien, il épargne. Un agent a **les deux**.

---

## 4. Les cinq types d'utilisateur — et ce que chacun représente humainement

Annexe 1 du Document Fonctionnel :

| Type | Ce que c'est, dans la vraie vie | Peut-il tout faire ? |
|---|---|---|
| **ROOT** | Le super-administrateur **de la plateforme FinZuu** | **Oui — bypass total** |
| **STAFF** | Un employé **de FinZuu** (le siège) | selon ses permissions |
| **COMPANY** | Un employé **d'une institution cliente** (banque, IMF, kiosque) | selon ses permissions |
| **GUEST** | Un invité, accès minimal | quasi rien |
| *(CUSTOMER)* | *Le client final* — présent en base (`tag CUSTOMER`), absent de l'Annexe 1 | consulte, souscrit |

### Le point que le pilote a corrigé, et qui est capital

**ROOT ne fonctionne PAS comme les autres.** Les autres types sont autorisés
**par leurs permissions** (le middleware vérifie `custom_permissions`). ROOT,
lui, est un **bypass** : le système **ne vérifie pas ses permissions**, il peut
tout faire par nature.

C'est pour ça que **`FRA-48` n'était pas un bug pour ROOT** mais l'était pour
STAFF : le middleware ne reconnaissait *que* ROOT et refusait les autres. La
correction (mesurée le 10/08) a rendu STAFF fonctionnel — le RBAC évalue
maintenant les permissions, il ne se limite plus au flag `is_root`.

**Conséquence pour nos tests :** quand nous opérons en ROOT (comme le Loader
l'exige, `D-DEP-7`), nous sommes **hors de la matrice RBAC** — nous ne testons
jamais « le droit », nous testons « le comportement ». Ce n'est pas une faille
de méthode : c'est que ROOT **n'a pas de droits à tester**, il les a tous.

---

## 5. Où se place-t-il dans l'écosystème — ses voisins

L'architecture système (§I du doc) montre user-service **au centre du Module
Administration**, en amont de tout. Ses voisins directs :

```
                        ┌─────────────────┐
   tout appel ─────────▶│  USER-SERVICE   │  ◀─── il garde la porte
   (Bearer)             │  (le gardien)   │
                        └────────┬────────┘
                                 │ porte une
                                 ▼
                        ┌─────────────────┐
                        │ IDENTITY-SERVICE│  ◀─── l'identité civile du User
                        └─────────────────┘

   Ses CLIENTS (services qui dépendent de lui pour savoir qui agit) :
     company · account · product · depositary · collect · client · ussd
```

**Trois relations de voisinage à comprendre :**

- **user ↔ identity** : le plus intime. Un `User` **contient** une `Identity`
  (dictionnaire §II.2.2.1 : `identity: Object[Identity]`). On ne crée pas un
  User sans une Identity — c'est ce qui a bloqué mon premier test STAFF le 10/08.

- **user ↔ company** : `company_id` sur le User (nullable). Un employé de banque
  est rattaché à sa `Company` ; un employé FinZuu ne l'est pas. **La création
  d'une Company crée automatiquement un User de type COMPANY** (§II.3.1) — mais
  ce User cascadé est inutilisable (`D-CMP-2`), d'où l'Admin explicite du Loader.

- **user → tous les autres** : chaque service protégé demande à user-service
  *« ce Bearer est-il valide, et porte-t-il la permission `X` ? »* via
  `/auth/check-permission`. C'est le nerf du système — et c'est précisément
  l'endpoint que `FRA-2/19` accusaient d'accorder tout (corrigé le 10/08).

---

## 6. Comment les acteurs externes l'utilisent

**Trois canaux, un seul gardien** (§VII du doc) :

| Acteur externe | Canal | Ce qu'il fait passer par user-service |
|---|---|---|
| **Agent / staff d'institution** | BackOffice Web | login, gère clients/dépositaires selon ses permissions |
| **Client final** | App Mobile | login wallet, consulte, souscrit |
| **Client final sans internet** | **USSD** (`*126#`) | s'authentifie par son MSISDN, consulte solde |
| **Autre service** | interne (Bearer service) | valide un jeton, lit un User (`UC0003` : acteur *Services*) |

**Le point d'accès universel est le MSISDN pour le client, l'email pour le
staff.** Un client USSD n'a pas d'email — il est reconnu par son numéro, celui
que le Loader compose depuis les plans de numérotation réels (`EF-27`).

---

## 7. Ce que cette couche *purpose* change pour le Loader

Comprendre le *pourquoi* de user-service, ce n'est pas de la théorie — ça dicte
trois choses que le Loader fait déjà, et qui prennent maintenant leur sens :

1. **Pourquoi 12 rôles et pas 5 types.** Les 5 `UserType` (Annexe 1) sont des
   *catégories d'accès*. Les 12 rôles métier du Loader (`D-09`) sont des
   *métiers réels* (Compliance, Collecte, Agent, Kiosque…) qui se **projettent**
   sur ces 5 types. Un « Agent » et un « Comptable » sont tous deux `STAFF`,
   mais ne font pas le même travail — d'où des groupes distincts.

2. **Pourquoi le Loader écrit en ROOT.** Parce que ROOT est le seul acteur
   **hors matrice** : il peuple sans se heurter au RBAC. Un Loader qui opérerait
   en STAFF serait bloqué par les permissions qu'il n'a pas — exactement le
   piège de `FRA-48`.

3. **Pourquoi le flow à 3 requêtes est non négociable.** Parce que le *purpose*
   de user-service est la **confiance** : un compte n'existe vraiment que quand
   la personne a posé son secret. Le Loader respecte ce rite
   (register → change password → login) même pour ses comptes de démonstration.

---

## En une phrase

> **User-service répond à la plus vieille question de la banque — « à qui
> fais-je confiance, et pour quoi ? » — et il y répond pour toute la plateforme
> à la fois.** C'est pourquoi il est au centre de l'architecture, pourquoi tous
> les autres services l'interrogent, et pourquoi le Loader ne peut pas peupler
> un seul client sans passer par lui.

---

*Prochains services à traiter sur le même plan (couche purpose) : identity,
account, company — le Module Administration — puis les modules Prêt et Collecte.*
