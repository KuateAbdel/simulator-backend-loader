# Modèle Utilisateurs et Rôles — notre compréhension consolidée

**Ce document existe parce que cette compréhension se perdait.** Elle était
éparpillée entre `D-06`, `D-09`, un audit empirique, trois docstrings de code et
une page Confluence. Elle est désormais à un seul endroit.

Périmètre : **qui existe, combien, qui les crée, et dans quel ordre.**

---

## 1. Les DEUX Super-Admin — distinction absolue

C'est la confusion la plus coûteuse du projet. Elle est tranchée, et rappelée
dans trois fichiers du code (`repositories/super_admin.py`, `services/bootstrap.py`,
`models/enums.py`).

| | **Super-Admin du LOADER** | **Super-Admin de la PLATEFORME** |
|---|---|---|
| Vit dans | **notre MongoDB**, collection `super_admin_accounts` | **user-service**, comme groupe RBAC |
| Nature | Compte de pilotage de **notre outil** | **Rôle métier** de l'écosystème FinZuu |
| Créé par | Bootstrap au premier démarrage (`SUPER_ADMIN_EMAIL`) | Le Loader, via `POST /groupes/create` |
| Existe côté FinZuu ? | **Non. Aucune existence.** | Oui |
| Combien | **1** (Phase 1 du CDC = Super-Admin uniquement) | 1 groupe |
| Mot de passe | Haché immédiatement, `must_change_password=True`, le clair n'est ni journalisé ni conservé | N/A — c'est un groupe, pas un compte |

> **Ils n'ont aucun rapport.** Le premier pilote notre outil ; le second est un
> rôle RBAC de l'écosystème. Le passage du mode `DRY_RUN` à `REAL` est toujours
> une action explicite du **Super-Admin du Loader**, jamais un défaut.

---

## 2. Les 5 `UserType` — l'axe technique

Énumération figée du serveur (`contracts.py`, page 56360965). Hypothèse `H-05`
du CDC : *« les credentiels des cinq rôles utilisateurs (ROOT, STAFF, COMPANY,
CUSTOMER, GUEST) seront valides pendant toute la durée du projet »*.

| `UserType` | Qui, dans notre écosystème | Le Loader en crée-t-il ? |
|---|---|---|
| `ROOT` | Le compte de service `noreply@finzuu.com` | **Non** — il existe déjà, on s'en sert |
| `STAFF` | Le personnel des IMF : Admin, Marketing, Compliance, Agent… | **Oui**, 60 à 100 |
| `COMPANY` | L'Admin User de chaque Company | **Oui**, 1 par Company |
| `CUSTOMER` | Les clients finaux | **Par cascade**, à l'onboarding |
| `GUEST` | — | **Non.** Aucun des 12 rôles métier ne le porte |

---

## 3. Les 3 `tag` — l'axe « à qui s'applique ce rôle »

`STAFF` · `COMPANY` · `CUSTOMER`. Ce sont **littéralement les 3 cases de l'UI**
du back-office.

> ⚠️ Le tag `ROOT` est **persisté en base bien qu'absent de l'énumération** (`A4`).
> À accepter en lecture, **jamais à émettre en écriture**.

---

## 4. Les 12 rôles métier — **11 à créer, 1 réutilisé**

Origine : **Stratégie Seed v2.0**, reprise en Gap 1 de la page Service Anatomy
user-service. Décision : `D-09`.

| # | Rôle métier | `tag` | `UserType` | Action |
|---|---|---|---|---|
| 1 | Super-Admin *(plateforme)* | `STAFF` | `ROOT` | créer |
| 2 | Admin | `STAFF` | `STAFF` | créer |
| 3 | Marketing | `STAFF` | `STAFF` | créer |
| 4 | Compliance | `STAFF` | `STAFF` | créer |
| 5 | Collecte | `STAFF` | `STAFF` | créer |
| 6 | Comptable | `STAFF` | `STAFF` | créer |
| 7 | Branche | `STAFF` | `STAFF` | créer |
| 8 | Employé/IT | `STAFF` | `STAFF` | créer |
| 9 | Agent | `STAFF` | `STAFF` | créer |
| 10 | Marchand | `COMPANY` | `COMPANY` | créer |
| 11 | Kiosque | `COMPANY` | `COMPANY` | créer |
| 12 | **Client** | `CUSTOMER` | `CUSTOMER` | ♻️ **réutiliser le groupe `CUSTOMER` existant** |

**Tous globaux** : `company_id: ""`, `routes: []` — jamais dupliqués par Company
(`D-06`). **`DELETE /groupes/{id}` existe** : c'est la seule écriture du Loader
entièrement réversible.

**Permissions** : par **nom**, jamais par UUID. Sur les 84 permissions du service,
**~61 sont assignables** — on écarte les **22 `LENDER`** (Sprint 5, hors périmètre,
`D-07`) et la permission parasite `RC169_VALID_1785245294`.
**La répartition permission → rôle reste l'arbitrage `A-05`, non tranché.**

---

## 5. Combien d'utilisateurs au total — le compte honnête

C'est le chiffre que personne n'avait posé. Il distingue ce que **nous créons
délibérément** de ce qui **arrive par cascade sans qu'on le demande**.

| Population | Volume | Origine | `UserType` |
|---|---:|---|---|
| Super-Admin du Loader | **1** | notre MongoDB — **hors FinZuu** | — |
| **Staff des IMF** | **60 à 100** | Loader, flow 3 requêtes | `STAFF` |
| **Admin User par Company** | **12 à 20** | Loader, flow 3 requêtes | `COMPANY` |
| User cascade de Company | 12 à 20 | ⚠️ **subi** — cascade `POST /companies/` | `COMPANY` |
| User cascade d'onboarding client | **2 000** | ⚠️ **subi** — cascade `POST /clients/onboard` | `CUSTOMER` |

> **Total dans user-service après un run complet : ~2 084 à 2 140 Users.**
> Dont **72 à 120 créés délibérément** par le Loader, et **~2 012 à 2 020 subis
> par cascade**.

**Base de départ mesurée le 9 août 2026** : **20 Users** — `ROOT` 1 · `CUSTOMER` 9 ·
`COMPANY` 8 · `GUEST` 2 · **`STAFF` 0**. Et **4 groupes**, pas 12.

### Une ambiguïté du CDC que je ne tranche pas seul

`UC-09` point 2 exige **15 à 25 utilisateurs staff par pays**, et point 4 rattache
**un Agent à chacun des 10 à 20 Kiosques** du pays. Les Agents sont-ils **compris
dans** les 15-25, ou **s'y ajoutent-ils** ?

* Compris → il ne reste que **5 staff non-Agent par pays** pour couvrir Admin,
  Marketing, Compliance, Comptable, Branche, Employé/IT — soit 6 rôles pour 5 postes.
* En sus → **25 à 45 users par pays**, soit 100 à 180 au total.

**Lecture retenue par défaut : les Agents sont compris**, le CDC parlant
d'« utilisateurs staff » sans réserve. **À confirmer.**

---

## 6. Qui crée quoi, et dans quel ordre — la séquence imposée

L'ordre n'est pas un choix de conception, il est **imposé par les contrats**.

```
0.  Bootstrap Super-Admin du LOADER          -> notre MongoDB
1.  Les 11 groupes                           -> POST /groupes/create
2.  Identity                                 -> POST /identities/create   OBLIGATOIRE AVANT
3.  User (flow 3 requetes)                   -> register / password-f-change / login
```

**Pourquoi cet ordre est contraint** :

1. **`CreateUserSchema.identity` est requis** → une Identity doit exister **avant**
   tout User. Ce n'est pas un choix. *(vérifié en écriture réelle le 09/08)*
2. **Le flow à 3 requêtes est indissociable.** S'arrêter après `register` laisse
   un compte à `is_first_login=true`, **incapable de se connecter** — c'est l'état
   de 16 des 20 Users de l'environnement.
3. **L'étape 2 refuse le token ROOT** : `401 « Type de token invalide. Attendu: auth »`.
   Elle n'accepte que l'`auth_token` rendu par `register`, **valide 10 minutes**.
4. **Anti-brute-force à 3 tentatives** (`INV-USR-19`) → un login échoué n'entre
   **jamais** en boucle de retry.

---

## 7. Les 5 pièges que notre code doit neutraliser

Notre système doit rester cohérent **malgré** le serveur, jamais grâce à lui.

| # | Piège mesuré | Notre parade |
|---|---|---|
| 1 | Le **JWT ne porte aucun droit** — ROOT et STAFF sont indiscernables hors `sub` | Ne **jamais** décoder le JWT pour déduire une permission (`ÉCART-39`) |
| 2 | Un **login prématuré rend `HTTP 200`** avec `access_token: None` | Ne jamais valider un login sur le code HTTP — **vérifier le jeton lui-même** |
| 3 | Le User cascade de Company est **inutilisable** : mot de passe inconnu, `company_id` vide, `identity` pointant vers la Company | Le Loader crée **son propre** Admin, correctement référencé |
| 4 | **`company_id` vide sur 20/20 Users** — le multi-tenant n'existe pas en base | Le Loader renseigne **toujours** `company_id`, sans attendre que le serveur l'exige |
| 5 | `groupes` mélange **noms et UUID bruts** selon les Users | Toujours émettre des **noms**. En lecture, accepter les deux |

---

## 8. Ce qui reste ouvert — nommé, pas caché

| # | Question | Nature |
|---|---|---|
| `A-05` | Quelles permissions pour chacun des 11 rôles | **Arbitrage produit** — Yaniv |
| — | Les Agents sont-ils compris dans les 15-25 staff/pays | **Lecture du CDC** — Yaniv |
| — | Pourquoi un jeton `CUSTOMER` fraîchement émis est rejeté (`401 « Token invalide ou expiré »`) | **Anomalie serveur**, à ticketer |
| — | Le module Utilisateurs **n'existe pas dans `PLAN.md`** | Notre dette de traçabilité |

---

*Sources : `D-06`, `D-07`, `D-09` · `docs/empirical/2026-08-08_user_service_audit.md` ·
`docs/empirical/2026-08-09_identity_service_audit.md` · page Confluence 56360965 ·
CDC v1.2 `UC-07`, `UC-09`, `H-05` · mesures serveur du 9 août 2026.*
