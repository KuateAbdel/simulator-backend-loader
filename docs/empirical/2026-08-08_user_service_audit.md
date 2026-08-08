# user-service — audit empirique du 8 août 2026

| | |
|---|---|
| **Objet** | Vérifier l'état réel du service, et confronter les 43 écarts documentés le 27/07 (page Confluence 56360965) à ce qui est mesurable aujourd'hui. |
| **Nature** | **Lecture seule.** `INV-USR-19` respecté : **aucun login échoué n'a été tenté** (anti-brute-force à 3 tentatives). |

## Verdict

Le service est **fonctionnellement complet et opérationnel**. L'écart le plus grave du dossier est corrigé. Plusieurs dettes d'observabilité et de robustesse subsistent — aucune ne bloque le Loader, toutes dictent sa conception.

---

## 1. Ce qui a été corrigé depuis le 27/07

| Écart | Sévérité | État mesuré |
|---|---|---|
| **VIOL‑06.7** — JWT en clair dans `Log.headers`, rétention 7 jours | **CRITIQUE** | ✅ **CORRIGÉ** — `authorization` totalement absent des logs |
| **VIOL‑06.8** — objet User complet embarqué dans chaque Log (RGPD) | ÉLEVÉ | ✅ **CORRIGÉ** — champ `user` vide |
| **H16** — endpoint inexistant → 401 (fuite APISIX) | MOYEN | ✅ **CORRIGÉ** — 404 propre |
| **H8** — `CheckPermissionSchema.permission` déclaré string | MOYEN | ✅ **CORRIGÉ** — déclaré `array` |
| **ÉCART‑43** — ROOT pas omnipotent (403 config, 401 product) | **CRITIQUE** | ✅ **CORRIGÉ** — `config-service` 200, `product-service` 200 |
| **A6** — `Groupe.permissions` mêlait noms et UUID | MOYEN | ✅ **CORRIGÉ** — noms uniquement |

`VIOL-06.7` permettait de lire les JWT de toutes les sessions des 7 derniers jours. Sa correction est la meilleure nouvelle de l'audit.

## 2. Ce qui subsiste

| Écart | Mesure du jour | Conséquence pour le Loader |
|---|---|---|
| **H14** — aucun rate limit | 20 requêtes consécutives → `{200: 20}`, aucun 429 | Auto-régulation à **25 workers** (`D-USR-1`) |
| **H18/H19** — aucune traçabilité | En-têtes : `content-length, content-type, date, server`. `X-Request-Id` envoyé par le client → **ignoré** | Le Loader génère et journalise ses propres UUIDv4 |
| **H20** — pagination non bornée | `limit=9999999999` → **200** (`limit=-1` → 400) | `limit` cappé à **100** côté client |
| **H22** — observabilité | `/metrics`, `/ready`, `/live`, `/healthz`, `/api/v1/health` → **404** | Aucun monitoring exploitable |
| **H26** — preflight CORS | `OPTIONS` → **401** | Sans effet : le Loader tourne serveur-side |
| **H27** — compression | `content-encoding` absent | Coût de bande passante à assumer |
| **A3** — `Log.headers` | Type `str`, **non parsable en JSON** | Champ à ignorer |
| **H23** — pollution des logs | 50 derniers logs : **50/50 sur `/health`** | `/api/v1/logs/` inexploitable → SIEM local obligatoire |
| **H11** — datetime | Suffixe `Z` **absent partout** : `'2026-07-16T15:26:03.857000'` | Dates naïves — parsing défensif, UTC assumé |
| **VIOL‑06.4** — titre OpenAPI | Toujours `"Auth Service"` alors que le service couvre 6 domaines | Cosmétique |

**Un chiffre s'est dégradé** : les logs sont passés de **96 200** (27/07) à **308 844** (08/08) — ×3,2 en douze jours, soit ~17 700/jour, à 99 % du bruit de sonde Kubernetes.

---

## 3. Architecture réelle

**40 chemins, 47 opérations, 20 schémas.** Par domaine : Auth 17 · Users 7 · Menu 7 · Groupes 7 · Permissions 5 · Logs 3 · `/health` 1.

**Les 17 opérations d'authentification** — le service est complet, pas un socle minimal :

```
login · logout · me · refresh · register
password : change · f/change (premier login) · request/{email} · reset
MFA      : enable · disabled · verify · totp/setup · totp/confirm
OTP      : resend-otp · verify-otp
RBAC     : check-permission
```

**Jetons** (décodés) :

| Jeton | Durée | Claims |
|---|---|---|
| `access_token` | **4 h** (14 400 s) | `email, exp, iat, sub, type, user_name` |
| `refresh_token` | **7 j** (604 800 s) | `exp, iat, sub, type` |
| `auth_token` | **absent** pour un utilisateur déjà onboardé | — |

> **`ÉCART-39` confirmé, toujours vrai** : le JWT ne porte **aucune permission**. Ne jamais le décoder pour en déduire un droit.
> **Le flow à 3 requêtes ne concerne que les Users à `is_first_login = true`.** Root reçoit directement `access_token` + `refresh_token`.

**Endpoints publics** (sans jeton) : `/health`, `/docs`, `/openapi.json` → 200.
**Protégés** : `/users/`, `/groupes/`, `/permissions/`, `/menus/`, `/logs/`, `/auth/me` → 401.

---

## 4. État réel de la base

| | |
|---|---|
| Users | **18** — ROOT 1 · CUSTOMER 9 · COMPANY 6 · GUEST 2 |
| **avec `company_id` renseigné** | **0 sur 18** |
| **`is_first_login = true`** | **15 sur 18** |
| `mfa_enabled` / `is_active = false` | 0 / 0 |
| Groupes | **4** |
| Permissions | **84** |
| Menus | 14 |
| Logs | **308 844** |

Ces deux chiffres disent l'essentiel : **le rattachement User→Company n'est utilisé nulle part**, et **15 users sur 18 n'ont jamais terminé leur onboarding**. C'est précisément le vide que le Loader vient combler.

---

## 5. Le RBAC — comment on crée un rôle

> ⚠️ **Correction d'une erreur de sondage du 08/08 matin.** J'avais rapporté `/api/v1/groups/` → 404 et conclu que l'endpoint n'existait pas. **La route est en français** : `/api/v1/groupes/` → **200**. La conclusion « Gap confirmé » reprise dans le Document Maître §11.0 est à retirer.

**`GroupeSchema`** — requis : `name`, `description`, `tag`, `company_id`. Optionnels : `permissions[]`, `routes[]`.

| Champ | Rôle |
|---|---|
| `name` | Nom du rôle |
| `description` | **Obligatoire** |
| `tag` | **« À qui s'applique ce rôle »** → `STAFF` \| `COMPANY` \| `CUSTOMER` — ce sont littéralement les 3 cases de l'UI |
| `company_id` | Périmètre |
| `permissions[]` | Par **nom** (`CLIENT_CLIENT_ONBOARD`), jamais par UUID |

**Routes** : `POST /groupes/create`, `GET/PUT/**DELETE** /groupes/{id}`, `GET /groupes/{name}/n`, `GET /groupes/search/{search}`.
`DELETE` existe — rare dans cet écosystème, et cela rend l'opération réversible.

**Les 4 groupes existants** portent tous **`company_id = ''`** (chaîne vide, pas `null`) :

| Nom | tag | Permissions | `company_id` |
|---|---|---:|---|
| ROOT | `ROOT` *(hors enum)* | 1 (magique) | `''` |
| COMPANY | `COMPANY` | 13 | `''` |
| CUSTOMER | `CUSTOMER` | 12 | `''` |
| GUEST | **`CUSTOMER`** | 3 | `''` |

> **Question tranchée sans écriture** : les rôles globaux se créent avec `company_id: ""`. **12 groupes au total, créés une seule fois** — et non 60 à 100 dupliqués par Company. `routes` reste vide, comme sur les 4 groupes existants.

**Les 84 permissions**, par préfixe :

| Préfixe | Nb | Préfixe | Nb |
|---|---:|---|---:|
| **LENDER** | **22** ⛔ | USER | 18 |
| IDENTITY | 15 | COMPANY | 6 |
| PRODUCT | 6 | ACCOUNT | 5 |
| DEPOSITARY | 4 | CLIENT | 3 |
| COLLECT | 2 | USSD | 2 |

⛔ **Les 22 permissions `LENDER` relèvent du Sprint 5 et sont hors du périmètre Loader** (Sprint 1‑4). Le RBAC anticipe le module Prêt ; nous ne les assignons pas. Une permission parasite traîne également : `RC169_VALID_1785245294`, résidu de test — à ne jamais assigner. Reste **~61 permissions assignables**.

---

## 6. Contraintes de séquence imposées par le contrat

1. **`CreateUserSchema.identity` est requis** → une Identity doit exister dans identity-service **avant** le User. La séquence `identity → user` n'est pas un choix.
   Requis complets : `user_name`, `type_user`, `identity`, `email`, `password`.
2. **Le flow à 3 requêtes** (`register` → `password/f/change` → `login`) ne s'applique qu'aux Users à `is_first_login = true`.
3. **Idempotence excellente** (pattern « no-op detection ») → rejouer une écriture est sûr.
4. **Anti-brute-force à 3 tentatives** (`INV-USR-19`) → un login échoué n'entre **jamais** dans une boucle de retry.

---

*Audit exécuté en lecture seule le 8 août 2026, sans aucune tentative de connexion échouée.*
