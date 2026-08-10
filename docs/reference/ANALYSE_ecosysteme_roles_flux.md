# Écosystème, rôles et flux métier — la couche *purpose*

| | |
|---|---|
| **Sources Confluence** | *Manuel de Référence ReadyApp* (14516354, 17/05), *Matrice des Autorisations RBAC* (10321921, 01/05), *Document Fonctionnel* (12255233) |
| **Croisé avec** | le PDF technique v1.0, l'OpenAPI réel, les disciplines du Loader |
| **Établi le** | 10 août 2026 |

> ⚠️ **Ces pages Confluence (mai 2026) sont plus récentes et plus complètes que
> le PDF technique (mars 2026).** Là où elles divergent, Confluence fait
> autorité pour l'intention ; les mesures des 8-10 août font autorité pour
> l'état réel.

---

## 1. Les 5 profils — ce qu'ils sont *humainement*

| Code | Profil | Qui c'est, dans la vraie vie | Environnement |
|---|---|---|---|
| **RO** | ROOT | Le super-administrateur **de la plateforme FinZuu**. Accès total, consulte tout | Back-Office |
| **ST** | STAFF | L'équipe de gestion **de la microfinance / de FinZuu** (Back-Office). La structure **initiatrice** : enregistre commerçants, agents, configure le système | Back-Office |
| **CO** | COMPANY | L'utilisateur **professionnel** — Banque, MFI, Bailleur. **Englobe le Business, l'Agent et le Kiosque.** Personne morale ou commerçant | Back-Office / USSD / App |
| **CU** | CUSTOMER | Le **client final** — personne physique autonome. Épargne, emprunte, paie depuis son mobile | USSD / App |
| **GU** | GUEST | Invité non authentifié, en découverte du catalogue | Back-Office / USSD / App |

> **Le point que le pilote a martelé, et qui est confirmé ici : ROOT est
> hors matrice métier.** Dans la *Matrice Fonctionnelle de Synthèse*, ROOT n'a
> ✔ que sur l'administration système (comptes, permissions, logs, migration).
> Sur les flux financiers réels (collecte, épargne, prêt), **ROOT est ✖**. Ce
> n'est pas un acteur métier : c'est un bypass technique.

---

## 2. QUI fait la collecte — la réponse complète, sur pièces

C'est votre question initiale. Les deux matrices Confluence donnent une réponse
plus riche que « le dépositaire » : **la collecte est un flux à deux temps, avec
trois acteurs.**

### Matrice RBAC (page 10321921) — les flux financiers

| Action | Institution (ST) | Client (CU) | Kiosk/Collecteur (CO) | Merchant (CO) |
|---|---|---|---|---|
| **Initier un Dépôt (Collecte)** | ❌ | ❌ | ✅ | ✅ |
| **Confirmer un Dépôt** | ✅ | ❌ | ❌ | ❌ |
| Effectuer un Retrait | ❌ | ✅ | ✅ | ✅ |

### Matrice de synthèse (Manuel) — l'épargne

| Action | ST | CO | CU |
|---|---|---|---|
| Collecte de l'épargne | ✖ | ✔ | ✔ |
| Retrait de l'épargne | ✖ | ✔ | ✔ |
| Dépôt des fonds dans les comptes clients | ✖ | **✔** | ✖ |

### Ce qui en ressort — le flux réel de la collecte

```
  1. INITIATION          2. VALIDATION
  ─────────────          ─────────────
  CO (Agent/Kiosque)     ST (Staff, au Dashboard)
  ou CU (client lui-même)         │
  remet/saisit le cash            │ après remise physique du cash
         │                        ▼
         └──────────────▶  dépôt CONFIRMÉ dans le compte client
```

**Précision technique du Manuel, capitale :**
> *« La validation finale d'une collecte terrain se fait par le **Staff (ST)** au
> niveau du Dashboard **après remise du cash physique** par l'agent (CO). »*

**Donc, qui fait la collecte ?**

| Rôle | Ce qu'il fait dans la collecte |
|---|---|
| **CO** (Agent / Kiosque / Merchant) | **INITIE** la collecte terrain — il reçoit le cash du client |
| **CU** (client) | peut **initier lui-même** une épargne/un retrait depuis son mobile (USSD/App) |
| **ST** (staff) | **CONFIRME** au dashboard, après remise physique du cash |
| **RO** (root) | **rien** — hors flux métier |

C'est le mécanisme même de la microfinance de proximité : **l'agent collecte sur
le terrain, le siège réconcilie.** Le double temps (initier / confirmer)
correspond exactement au `D-COL-2` (ouverture) / validation que nous avons
mesuré, et à l'anomalie `ANO-ACC-STATUS-05` (le dépôt reste `PENDING` tant que
non confirmé).

---

## 3. Les sous-rôles de CO — l'arbre de la collecte

Le Manuel décompose CO en trois figures de terrain, qui sont **exactement
l'arbre du Loader** :

| Sous-rôle | Définition Manuel | Dans le Loader |
|---|---|---|
| **Agence** | *« point de commercialisation distant du headquarter, auquel les agents collecteurs sont rattachés »* | niveau `AGENCE` (`org_hierarchy`) |
| **Agent** | *« point de contact entre la microfinance et les utilisateurs finaux, pré-enregistré par l'institution. Gère la collecte sur le terrain avec validation par OTP commerçant »* | niveau `AGENT` (`D-11`) |
| **Kiosque** | *« gère les dépôts physiques et retraits pour le compte d'un client après vérification du solde et validation par OTP. Gère l'intégration opérateurs (MoMo, Orange, Wave) »* | niveau `KIOSQUE` |

> **Confirmation de notre conception `D-11`.** Le Manuel dit noir sur blanc que
> l'Agent est *« rattaché »* à l'Agence et opère *« sur le terrain »*. C'est
> exactement le rattachement Agent→Kiosque qui manquait, et que `D-11` a posé.
> **Notre arbre n'est pas une invention — c'est le modèle métier de FinZuu.**

---

## 4. Les 3 natures de client — confirmation du CDC

Le Manuel distingue clairement, ce qui éclaire `channel` (USSD/MOBILE/OFFICE) :

- **CU autonome** : s'inscrit seul, agit seul depuis son mobile (canal MOBILE/USSD)
- **CU servi au guichet** : le Kiosque agit pour lui (canal OFFICE)
- **CO commerçant** : gère ses propres flux professionnels

---

## 5. Ce que ces documents changent pour le Loader

**Rien n'est cassé — au contraire, tout est confirmé.** Trois validations
externes de notre conception :

1. **L'arbre Company→Branche→Agence→Kiosque→Agent** est le modèle métier réel
   (§3). `D-11` était juste.

2. **Le Loader écrit en ROOT** — et ROOT est bien le seul acteur hors matrice,
   qui peut tout peupler sans se heurter au RBAC (§1). `D-DEP-7` était juste.

3. **La collecte à deux temps** (initier CO/CU → confirmer ST) correspond à nos
   mesures (`D-COL-2`, `ANO-ACC-STATUS-05`). Quand le Sprint 5 simulera les
   collectes, **c'est l'Agent (CO) qui initie, le Staff (ST) qui confirme** —
   jamais ROOT, jamais le client seul pour un dépôt terrain.

**Le seul ajustement de vocabulaire** : nous disions « le dépositaire fait la
collecte ». Plus précisément : **le Kiosque (un Dépositaire) est l'endroit, et
l'Agent (CO) est la personne qui collecte**, validée par le Staff.

---

## En une phrase

> **La collecte n'est pas l'acte d'un seul rôle : c'est un flux de confiance
> entre trois acteurs — l'Agent qui reçoit le cash, le client qui l'apporte, et
> le Staff qui réconcilie.** C'est le cœur du modèle de microfinance de
> proximité, et le Loader le reproduit fidèlement dans son arbre et ses rôles.

---

*Pages Confluence restantes à exploiter : Lexique des Termes Clés (22118403),
Core Engine & Shared Services (10715137), Définitions des Statuts Comptes
(32964609), Stack Technique & Méthodologie (18448385), Audit RBAC (23232514).*

---

## 6. Le système COMPLET — et où le Loader se situe (lecture des 5 dernières pages)

Lecture faite du Lexique (22118403), Core Engine (10715137), Statuts Comptes
(32964609), Stack & Méthodologie (18448385).

### Ce que ces pages révèlent du système entier

| Concept clé | Ce que c'est | Le Loader le couvre ? |
|---|---|---|
| **Multi-tenant / marque blanche** | chaque partenaire (Baobab, SoliMFI…) est un *tenant* isolé sur la même infra | ✅ **oui** — nos Companies SONT les tenants |
| **KYC 3 niveaux** (KYC0/1/2) | plafonds selon vérification d'identité (BCEAO) | ✅ nos identités portent le KYC complet |
| **Statuts de compte** | Actif → Suspendu / Dormant / Clos (+ Pending / Blocked) | ✅ mesuré (`ANO-ACC-STATUS`), respecté |
| **Collecte Cash + Produit** | épargne monnaie / articles physiques (kg, litre) | ✅ `D-COL`, catalogue COLLECT |
| **Réconciliation** | le siège rapproche les collectes du cash reçu | ✅ c'est le 2ᵉ temps (validation ST) |
| **Paiement marchand** (QR/NFC/MDR) | client paie un commerçant | ❌ **hors 9 services** — module Wallet |
| **Top-Up / Float agent** | rechargement wallet, liquidité agent | ❌ **hors périmètre** — Mifos Payment |
| **Bulk Payment** | paiement de masse (salaires) | ❌ module séparé, jamais rencontré |
| **Group Lending / Round-Up** | prêt solidaire, arrondi | ❌ « en développement » |

### La confirmation de la Stack (page 18448385)

- **Serveur Test = `152.53.168.189`** — c'est **exactement** la gateway que nous
  avons mesurée le 10/08. ARM64, NetCup. Confirmé.
- Stack : **FastAPI, MongoDB, Redis, Kafka, PostgreSQL** — le Loader est en
  FastAPI + MongoDB, aligné.
- Environnements : **DEV / TEST / PRE-PROD-DEMO** — le Loader cible TEST + DEMO.
- **DDD, Multi-tenant, Event-Driven, Zero Trust** — et *« Dynamic UI Rendering
  basé sur la Matrice RBAC »* : l'interface elle-même se dessine selon les
  permissions. D'où l'importance des 12 rôles que nous créons.

---

## 7. Verdict d'alignement du Loader

**Le Loader couvre exactement le socle que sa mission lui assigne, et le couvre
juste.**

| Module de l'écosystème | Services | Loader |
|---|---|---|
| **Administration** | user, company, identity, account, config | ✅ **peuplé** |
| **Collecte** | depositary, client, collect | ✅ **peuplé** |
| **Prêt** | lender, (loan) | 🟡 Lenders enregistrés ; prêts non injectables (`loan-service` absent) |
| **Canal USSD** | ussd | ⬜ découvert, non consommé |
| **Wallet / Paiement** | Mifos, Transaction, Partner MoMo | ❌ **hors périmètre** (Kafka, `ENF-16`) |
| **Bulk** | — | ❌ hors périmètre |

**Les frontières ne sont pas des trous — ce sont des décisions.** Le Loader est
un **orchestrateur HTTP** (`ENF-16`) : il ne touche pas au Wallet (Kafka), ne
simule pas les prêts (`loan-service` non livré), n'entre pas dans le paiement
marchand. Il peuple **l'épargne de proximité et son socle administratif** — le
cœur de la microfinance.

> **Rien de ce qui a été mesuré ne contredit ces documents. Tout ce que ces
> documents décrivent du périmètre Loader, le Loader le respecte.** L'arbre,
> les rôles, les types de compte, la collecte à deux temps, l'écriture en ROOT,
> la cohérence monétaire XAF/XOF, le KYC — chaque pièce de notre conception a
> maintenant sa justification métier dans le système officiel.
