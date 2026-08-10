# Compréhension du système FinZuu — document maître

| | |
|---|---|
| **Objet** | Consolidation complète de la compréhension du système FinZuu, acquise le 10 août 2026 par lecture croisée de toute la documentation officielle. |
| **Sources** | Cahier des Charges Loader v1.2 · Document Fonctionnel (PDF TNS + Confluence 12255233) · Manuel de Référence ReadyApp (14516354) · Matrice RBAC (10321921) · Lexique des Termes Clés (22118403) · Core Engine (10715137) · Statuts Comptes (32964609) · Stack & Méthodologie (18448385) · Service Anatomy user-service (56360965) · + mesures empiriques des 8-10 août |
| **Statut** | Référence. Là où doc et mesure divergent, la **mesure** fait autorité pour l'état réel ; la **doc** pour l'intention. |
| **Règle d'or** | Le Loader est **conformiste sur le transport** (enums, types), **anti-corruption sur le modèle** (géographie, arbre). |

---

## 1. Ce qu'est FinZuu — la raison d'être

**Une plateforme FinTech-as-a-Service (FaaS) en marque blanche, multi-tenant,
pour la microfinance en Afrique subsaharienne.**

- **Marque blanche** : le logiciel est développé une fois, commercialisé sous
  l'identité de chaque partenaire (Baobab Finance, SoliMFI, GreenPay…).
- **Multi-tenant** : chaque partenaire est un *tenant* isolé, sur la même infra,
  avec ses données, sa config, son thème.
- **But humain** : l'**inclusion financière** des populations non/sous-bancarisées
  — via USSD (sans internet), App mobile, et un réseau d'agents de proximité.

Le produit s'appelle **ReadyCash Suite / ReadyApp / ReadyCollect** selon le module.

---

## 2. L'architecture — 3 modules + canaux + wallet

```
CANAUX            USSD (*144#)  ·  App Mobile  ·  BackOffice Web
                        │
   ┌────────────────────┼─────────────────────────────────┐
   │  MODULE ADMINISTRATION (le socle commun)              │
   │   user · company · identity · account · config        │
   ├───────────────────────────────────────────────────────┤
   │  MODULE PRÊT            │  MODULE COLLECTE             │
   │   lender · client · loan│   depositary · client · collect │
   ├───────────────────────────────────────────────────────┤
   │  MODULE BULK PAIEMENT   ·   WALLET (Mifos, MoMo, Kafka)│
   └───────────────────────────────────────────────────────┘
```

**10 services vivants mesurés** (10/08) : user, company, identity, account,
config, client, product, depositary, collect, **ussd**. Plus **lender** et
**loan** référencés par le BackOffice mais non exposés (loan-service absent).

**Le Loader couvre** : Administration + Collecte (peuplés), Prêt partiel
(Lenders oui, prêts non injectables). **Hors périmètre** : Wallet (Kafka),
paiement marchand (QR/NFC), bulk, USSD — décisions doctrinales (`ENF-16`).

---

## 3. Les 5 acteurs — qui est qui (Annexe 1 + Manuel)

| Code | Type | Qui c'est, humainement | Environnement |
|---|---|---|---|
| **RO** | ROOT | super-admin **de la plateforme FinZuu** — accès total, **bypass** | Back-Office |
| **ST** | STAFF | l'équipe **du siège FinZuu** — config système, validation KYC finale, logs | Back-Office |
| **CO** | COMPANY | le personnel **d'une institution cliente** — englobe Business, **Agent, Kiosque**, Secrétaire, CFO, Guichetier | Back-Office / USSD / App |
| **CU** | CUSTOMER | le **client final** — personne physique, épargne/emprunte depuis son mobile | USSD / App |
| **GU** | GUEST | invité en découverte du catalogue | tous |

### Le point capital : ROOT est un BYPASS, pas un rôle à permissions

**Preuve mesurée (10/08) :** le groupe `ROOT` en base **ne porte PAS**
`COLLECT_WRITE` — et pourtant ROOT peut collecter. Le système **ne vérifie pas
les permissions de ROOT**. Un STAFF sans la permission est bloqué ; ROOT sans la
permission passe. **C'est une différence de nature, pas de degré.**

Conséquence : le Loader écrit **toujours en ROOT** (`D-DEP-7`) — c'est le seul
acteur hors matrice, qui peuple sans se heurter au RBAC.

---

## 4. Les 4 NIVEAUX du RBAC — à ne JAMAIS confondre

C'est la clé de tout le système d'accès. Quatre concepts distincts, empilés :

| Niveau | Combien | Ce que c'est | Source |
|---|---|---|---|
| **1. UserType** | **5** | l'enveloppe d'accès (RO/ST/CO/CU/GU) | CDC H-05 |
| **2. Rôle / Groupe** | **12** | un paquet de permissions **+ une liste de menus** | Stratégie Seed v2.0 |
| **3. Permission** | **40** | l'habilitation granulaire (`COLLECT_WRITE`…) sur 7 services | catalogue serveur |
| **4. Menu** | *variable* | l'élément d'interface **visible** selon les permissions | Doc Fonctionnel §II.2.2.3 |

**Comment ils s'articulent :**

```
UserType borne  →  Rôle regroupe  →  Permission autorise l'ACTION  →  Menu montre l'ÉCRAN
```

- **Le serveur vérifie la PERMISSION**, jamais le type. Le type borne ce qu'on
  peut recevoir. Celui qui porte `COLLECT_WRITE` collecte — Agent (CO), Kiosque
  (CO), ou le client lui-même (CU, pour son propre argent).
- **Le menu est la traduction visuelle du RBAC** (voir §7).

---

## 5. Les 12 rôles métier et leur mapping — révisé le 10/08 (`D-09 v2`)

Origine : *Stratégie Seed v2.0* (Confluence 56360965). Le mapping rôle→UserType
**n'était pas prescrit** (« pas encore matérialisé ») — c'est une décision du
Loader, corrigée le 10/08 après lecture du CDC et du Manuel.

**Principe :** `STAFF` = siège FinZuu (fonctions exclusives : config système,
validation KYC finale, logs). `COMPANY` = personnel d'institution. **Le Loader
génère des institutions, donc la majorité est COMPANY.**

| Rôle | UserType | Permissions (domaine) | Justification |
|---|---|---|---|
| **Super-Admin** | ROOT | toutes familles | administration plateforme |
| **Admin** | COMPANY | USER, COMPANY, IDENTITY | admin d'une institution |
| **Marketing** | COMPANY | CLIENT, PRODUCT | marketing/campagnes d'institution |
| **Compliance** | **STAFF** | IDENTITY, CLIENT | validation KYC finale = fonction siège |
| **Collecte** | COMPANY | COLLECT, DEPOSITARY | pilotage collecte terrain |
| **Comptable** | COMPANY | ACCOUNT | CFO d'institution (Manuel : CO englobe le CFO) |
| **Branche** | COMPANY | DEPOSITARY, CLIENT | unité territoriale de l'institution |
| **Employé/IT** | **STAFF** | USER | exploitation, logs = fonction siège |
| **Agent** | COMPANY | COLLECT, CLIENT | rattaché à une Company mère (CDC) |
| **Marchand** | COMPANY | ACCOUNT | commerçant |
| **Kiosque** | COMPANY | COLLECT, DEPOSITARY | point de dépôt/retrait |
| **CUSTOMER** | CUSTOMER | *(réutilisé, 12 perms dont `COLLECT_WRITE`)* | client final |

**Répartition : 1 ROOT · 8 COMPANY · 2 STAFF · 1 CUSTOMER.**

> **Preuve d'alignement base ↔ code (10/08 17:58) : 12/12 rôles alignés, 16
> groupes en base, 0 doublon.** Correction faite par `DELETE` des 6 rôles mal
> typés + recréation — pas de doublon, la géographie non touchée. Les
> **permissions** restent l'arbitrage `A-05` (proposition, non validée) : elles
> sont distinctes du type.

---

## 6. CUSTOMER ≠ Client — la confusion centrale, tranchée

**Deux objets différents, dans deux services différents.** Le vocabulaire se
ressemble, la réalité non.

| | **User (type_user=CUSTOMER)** | **Client** |
|---|---|---|
| Vit dans | `user-service` | `client-service` |
| Répond à | *« qui a le droit de se connecter ? »* | *« qui a souscrit à un produit, et combien possède-t-il ? »* |
| Contient | user_name, password, groupes (permissions) | msisdn, category, product[], identity, account_id |
| Rôle | **identifiant de connexion** (authentification) | **relation commerciale** (le dossier client) |

**Une même personne = jusqu'à 3 objets** : une `Identity` (son KYC), une
`Client subscription` (son épargne), et *éventuellement* un `User` CUSTOMER (pour
l'App). Un client USSD basique est reconnu par son **MSISDN** — sans compte user.

**Ce que le CUSTOMER peut faire** (12 permissions, mesurées) : sa propre épargne
et son propre retrait (`COLLECT_WRITE`), consulter son compte, accéder à l'USSD.
**Ce qu'il ne peut pas** : déposer dans le compte d'un autre (CO seul), confirmer
un dépôt (ST seul). **Il agit pour lui-même, jamais pour autrui.**

---

## 7. Les MENUS — leur purpose profond

**Un menu = une entrée de navigation du BackOffice** (`name, link, description,
is_public` + `permissions[]` selon le Doc Fonctionnel). Mais son **purpose** va
bien au-delà de la navigation.

### Ce qu'ils contrôlent vraiment

> La **permission** dit ce qu'on peut FAIRE. Le **menu** dit ce qu'on peut VOIR
> EXISTER. Un Agent ne voit pas le menu « Définir les taux » — il ne sait même
> pas que la fonction existe. Fermer une porte à clé (permission) vs cacher
> qu'il y a une porte (menu).

### Pourquoi ils sont en base, pas dans le code frontend — LE purpose

C'est le **cœur technique de la marque blanche multi-tenant** :

| Sans menus en base | Avec menus en base |
|---|---|
| une interface figée pour tous | **chaque tenant configure ses écrans** |
| ajouter un écran = redéployer | ajouter un écran = créer un menu |
| le frontend décide qui voit quoi | **le backend décide** (Zero Trust) |

Le Core Engine le nomme : *« Dynamic UI Rendering — Permission-Based UI »*. Un
Groupe **possède une liste de menus** (Doc §II.2.2.4) ; à la connexion,
l'interface affiche **uniquement** les menus du groupe de l'user.

### Les 4 problèmes humains résolus

1. **Simplicité** : un collecteur ne voit que son bouton « Collecte » — inclusion.
2. **Autonomie du partenaire** : une banque configure ses écrans sans développeur.
3. **Zero Trust** : le frontend demande au serveur quels menus ; un frontend
   piraté ne peut pas révéler d'écrans interdits.
4. **Traçabilité** : le `Log` référence *« le menu mis en cause »* (audit AML).

### Analogie

> Une banque physique a des portes. La **permission** est la clé. Le **menu** est
> le fait de voir la porte. Même bâtiment, mais chacun ne voit que les portes qui
> le concernent.

**Le Loader ne crée pas de menus — c'est de la config d'interface (frontend
Zidane), pas de la donnée métier.** Doctrinalement juste (`ENF-16`).

---

## 8. La COLLECTE — le flux, les acteurs, les natures

### Trois natures, selon le PolicyType du produit (Annexe 10, mesuré)

| PolicyType | Nature | Ce qui est suivi |
|---|---|---|
| **CASH** | épargne d'argent classique | montant en devise |
| **CASH_DAT** | épargne à terme (durée fixée) | montant + date de fin |
| **PRODUCT** | collecte d'articles physiques (cacao, plastique…) | quantité + unité (**KILOGRAM / LITER**) |

### Qui fait la collecte — flux à DEUX temps, trois acteurs

```
1. INITIATION                          2. VALIDATION
   CO (Agent/Kiosque) reçoit le cash →  ST (Staff) confirme au Dashboard
   ou CU (client, depuis son mobile)    après remise physique du cash
```

Cité du Manuel : *« La validation finale d'une collecte terrain se fait par le
Staff (ST) après remise du cash physique par l'agent (CO). »* Ce double temps
correspond à nos mesures `D-COL-2` (ouverture) et `ANO-ACC-STATUS-05` (dépôt
`PENDING` tant que non confirmé).

### Préconditions (mesurées, isolément)

1. Le client existe. 2. Le produit existe. 3. Le dépositaire est **souscrit à CE
produit précis** (pas juste existant).

---

## 9. L'onboarding client — étape par étape (mesuré)

`POST /clients/onboard` · **7 champs requis** : `msisdn, channel, segment,
category, identity, product_id, currency` (+ `language` optionnel).

À chaque onboarding réussi :
1. Le client fournit son identité complète (KYC).
2. Il choisit un `product_id` **existant** — impossible d'onboarder « à vide ».
3. Le serveur crée une **Identity** (identity-service).
4. Le serveur crée **1 compte CHECKING** (account-service) — **un seul, garanti**.
5. Le Client embarque le produit souscrit.

> ⚠️ **Doc non confirmée** : la règle II.5.1 dit qu'un onboarding devrait créer
> aussi CLASSIC + COMMITMENT. **Jamais observé** — le Loader ne compte QUE sur le
> CHECKING garanti. Ne jamais supposer CLASSIC/COMMITMENT sans les avoir vus.

**Client = 2 catégories** : INDIVIDUAL, CORPORATE. Nuance : `identity.type` envoyé
est **ignoré** — le serveur force CORPORATE en interne (`D-CLI-4`). `Client.category`
est fiable ; l'`identity.type` qui l'accompagne ne l'est pas.

---

## 10. Les comptes financiers — 8 types, quelle création déclenche lesquels

Types (Annexe 4) : CAPITAL, CHECKING, INTEREST, PENALTY, TAXE, CLASSIC,
TERM_DEPOSIT, OPERATION (+ COMMITMENT mentionné).

| Création | Comptes déclenchés (règle II.5.1) |
|---|---|
| Company | 1× OPERATION |
| Dépositaire / Lender (à la souscription) | CAPITAL, INTEREST, PENALTY, TAXE |
| Onboarding client | CHECKING (garanti) [+ CLASSIC, COMMITMENT non confirmés] |

**Règles de transfert** : OPERATION ↔ CAPITAL seulement ; INTEREST/PENALTY/TAXE
→ CAPITAL uniquement, avec tag `TO_SHARE` ; jamais entre INTEREST/PENALTY/TAXE.

**Statuts de compte** (page 32964609) : Actif → Suspendu / Dormant / Clos
(+ Pending / Blocked pour la monnaie électronique).

---

## 11. Combien d'entités le Loader crée — le décompte

**USERS (user-service, comptes de connexion) : ≈ 111**

| | Combien | Type |
|---|---|---|
| Super-Admin | 1 | ROOT |
| Admin de Company | 12-20 (1/Company) | COMPANY |
| Staff opérationnel (Agents + encadrement) | 60-100 (15-25 × 4 pays) | COMPANY (sauf Compliance/IT) |

**PAS des users** : **2 000 Clients** (client-service, souscriptions) + **~2 100
Identities** (identity-service). Un client est une souscription, pas un compte
de connexion.

**Volumétrie complète** (mesurée, plan reproductible) : 16 Companies (8 IMF),
11 Branches, 12 Agences, 54-60 Kiosques, 60-100 staff, 2000 clients (1600 INDIV /
400 CORP), 12 produits, 12 Lenders locaux + 4 institutionnels.

**La géographie commande tout** : 4 pays (CM/CI/BF/SN), 11 régions et 12 villes
réellement exploitées (celles portant des quartiers), ~500 clients/pays.

---

## 12. Alignement du Loader — verdict

**Le transport (enums) est aligné à 100 %** (mesuré) :

| Enum | Verdict |
|---|---|
| UserType (5), CompanyType (7), AccountType (8+COMMITMENT) | ✅ aligné |
| PolicyType (CASH/CASH_DAT/PRODUCT), PolicyMeasure (KG/L) | ✅ aligné |
| channel (USSD/MOBILE/OFFICE), Category (INDIV/CORP) | ✅ aligné |

**Le modèle (notre richesse) est préservé** : géographie fine (régions,
quartiers, `zone_type`), arbre `org_hierarchy` à 4 niveaux (`D-11`), journal
d'intention, registre d'unicité, cohérence monétaire XAF/XOF. Le CDC confirme
d'ailleurs l'arbre (« Agent rattaché à une Company mère », « arbre géographique
5 niveaux »).

**Corrections faites le 10/08** (par lecture de la doc) :
- `D-09 v2` — mapping rôle→UserType corrigé (9 rôles étaient mal typés STAFF).
- Base resynchronisée sans doublon.

**Ce qui reste ouvert** : `A-05` (permissions exactes par rôle, proposition non
validée), `A-01` (Sénégal absent de Faker), les modules aval (Clients Sprint 4,
Vie 180j Sprint 5, Recette).

---

## En une phrase

> **FinZuu est une plateforme multi-tenant en marque blanche pour la microfinance
> africaine, où l'accès se joue sur 4 niveaux (type → rôle → permission → menu),
> où le pouvoir vient de la permission portée et non du type seul, et où le
> Loader peuple fidèlement le socle et la collecte — conformiste sur leurs
> contrats, plus riche sur son propre modèle géographique.**

---

*Document maître établi le 10 août 2026. Chaque affirmation est adossée à une
source documentaire citée ou à une mesure horodatée. Là où doc et mesure
divergent, la divergence est signalée.*
