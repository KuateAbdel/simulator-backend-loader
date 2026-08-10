# Retest complet MEP1 — état de l'environnement

| | |
|---|---|
| **Objet** | Vérification empirique de l'état des 10 services de l'instance TEST, préalable au retest des 81 bugs ouverts. |
| **Établi le** | 10 août 2026 |
| **Nature** | Lecture seule. Mesures brutes, horodatées. |
| **Client** | FinZuu · **Prestataire** : TNS Agency |

> **Ce document ne modifie aucun statut Jira.** Il mesure ; la Direction décide.

---

## 1. Versions exposées par chaque service

Relevé le 10/08/2026 à 10:49 GMT, via `GET /openapi.json` sur chaque service.

| Service | Titre OpenAPI | Version | Chemins | Opérations |
|---|---|---|---:|---:|
| user | Auth Service | **1.0.1** | 40 | 47 |
| company | Company Service | **1.0.1** | 10 | 14 |
| identity | Auth Service | **1.0.1** | 12 | 13 |
| account | Account Service | **1.0.0** | 18 | 22 |
| client | Client Service | **1.0.0** | 10 | 10 |
| product | Product Service | **1.0.1** | 8 | 11 |
| collect | Collect Service | **1.0.1** | 12 | 12 |
| depositary | Depositary Service | **1.0.1** | 13 | 13 |
| config | Config Service | **1.0.1** | 25 | 28 |
| ussd | USSD Service | **1.0.1** | 5 | 8 |

**Commande de preuve** (exemple user-service) :
```
curl -s https://user-service.test.services.fintech4esg.com/openapi.json | jq '.info.version'
→ "1.0.1"
```

---

## 2. Comparaison avec nos propres mesures d'août

C'est le seul point de comparaison **factuel** dont nous disposons : le nombre de
chemins que nous avions nous-mêmes relevé les 8 et 9 août.

| Service | Mesuré en août | Mesuré aujourd'hui | Écart |
|---|---|---|---|
| user | **40 chemins** (`2026-08-08_user_service_audit.md`) | 40 chemins | **aucun** |
| identity | **13 endpoints** (`2026-08-09_identity_service_audit.md`) | 13 endpoints | **aucun** |

> **Sur ces deux services, la surface d'API est strictement identique à celle
> mesurée il y a un et deux jours.** Pour les huit autres, nous n'avions pas
> consigné de comptage exact en août — l'écart n'est donc pas mesurable, et est
> déclaré **non déterminé** plutôt que supposé.

---

## 3. Certificats TLS — pourquoi ils ne prouvent rien

| Service | Émis le | Expire le | Émetteur |
|---|---|---|---|
| user | 20/07/2026 | 18/10/2026 | Let's Encrypt (YR2) |
| company | 24/07/2026 | 22/10/2026 | Let's Encrypt (YR1) |
| identity | 23/07/2026 | 21/10/2026 | Let's Encrypt (YR1) |
| account | 25/07/2026 | 23/10/2026 | Let's Encrypt (YR1) |
| client | 26/07/2026 | 24/10/2026 | Let's Encrypt (YR1) |
| product | 23/07/2026 | 21/10/2026 | Let's Encrypt (YR2) |
| collect | 02/08/2026 | 31/10/2026 | Let's Encrypt (YR2) |
| depositary | 31/07/2026 | 29/10/2026 | Let's Encrypt (YR2) |
| config | 26/07/2026 | 24/10/2026 | Let's Encrypt (YR1) |
| ussd | 05/07/2026 | 03/10/2026 | Let's Encrypt (YR1) |

> ⚠️ **Ces dates ne sont PAS un indice de redéploiement applicatif.** Ce sont des
> certificats Let's Encrypt, renouvelés automatiquement tous les ~90 jours par
> l'infrastructure, indépendamment de tout déploiement de code. Un certificat
> émis le 02/08 ne signifie pas que collect-service a été redéployé le 02/08 —
> seulement que son certificat a été renouvelé ce jour-là.

---

## 4. Empreinte OpenAPI — référence pour toute vérification future

`sha256` des 16 premiers caractères du contrat OpenAPI, relevé le 10/08. **Toute
divergence future de ces empreintes prouvera un changement de surface d'API.**

| Service | Empreinte (sha256, tronquée) |
|---|---|
| user | `ae28e8b41b3ceda0` |
| company | `377f33191f54d823` |
| identity | `c006e8d6c9136d46` |
| account | `e5e1699a2c7d6abd` |
| client | `ce675a2d681dab29` |
| product | `d6ca14523f8c0591` |
| collect | `6b36d74ea9e4fbe5` |
| depositary | `26dab3146614e892` |
| config | `2498be07e8dd660e` |
| ussd | `0853bd6ed8be465d` |

---

## 5. Ce qui est établi, ce qui ne l'est pas

**Établi, avec preuve** :
- Les 10 services répondent (`/health`, `/docs`, `/openapi.json` en 200).
- Aucun n'a franchi une version majeure ou mineure : tous en `1.0.0` ou `1.0.1`.
- user-service et identity-service ont une **surface d'API identique** à celle
  mesurée les 8 et 9 août.

**Non déterminé** :
- Un correctif applicatif **sans changement de version ni de surface** est
  possible et **invisible à ce niveau**. Un bug corrigé dans la logique interne
  d'un endpoint existant ne modifie ni la version affichée, ni le contrat
  OpenAPI, ni le certificat. **La seule façon de le savoir est de rejouer chaque
  test — c'est l'objet de la campagne qui suit.**

> **Conséquence pour l'ordre de la campagne** : l'environnement ne porte aucun
> signe visible de redéploiement depuis nos mesures d'août, mais **cette absence
> de signe ne vaut pas preuve d'absence de correctif**. Chaque ticket doit donc
> être rejoué individuellement. On ne peut pas conclure « 0 corrigé » depuis les
> versions seules.

---

*Suite : retest ticket par ticket, en commençant par les 28 bugs classés
« Not a bug ». Sections ajoutées au fur et à mesure, chacune avec sa commande,
son code HTTP et son horodatage.*

---

# IDENTITY-SERVICE — 9 bugs retestés (campagne mai 2026)

Tous étaient au statut **« Not a bug »**. Token ROOT monté pour les
contre-mesures. Horodatage des mesures : 10/08/2026 ~11:06–11:10 GMT.

## FRA-4 — 8 endpoints accessibles sans Bearer → **CORRIGÉ**
```
curl -k https://identity-service.test.services.fintech4esg.com/api/v1/identities/
→ HTTP 401   (le ticket relevait HTTP 200 + 333 identités)
```
Contre-mesure (distinguer correctif d'une rupture) : le **même** endpoint avec
Bearer ROOT → **HTTP 200 + données**. L'authentification est donc réellement
appliquée, ce n'est pas une coupure de service. `/ocr/languages` idem
(401 sans, 200 avec).

## FRA-5 — JWT non vérifié, alg=none accepté → **CORRIGÉ**
```
Bearer eyJhbGciOiJub25lI…  → HTTP 401
Bearer abc.def.ghi          → HTTP 401
Bearer <garbage>            → HTTP 401
```
Tous les jetons forgés ou malformés sont rejetés.

## FRA-6 — OCR : payload validé avant authentification → **CORRIGÉ**
```
POST /api/v1/ocr/ocr           sans Bearer → HTTP 401  (ticket : 422)
POST /api/v1/ocr/ocr/base64    sans Bearer → HTTP 401  (ticket : 422)
POST .../base64 + payload      sans Bearer → HTTP 401  (ticket : 400)
```
L'authentification est désormais la première couche vérifiée.

## FRA-9 — endpoint POST /identities/{id}/validate absent → **CORRIGÉ**
L'endpoint est présent dans l'OpenAPI et fonctionne :
```
POST /api/v1/identities/{id}/validate  (Bearer ROOT, {})
→ HTTP 200 {"description":"Identity validated", …"is_verified":true}
```
> Aparté non lié au bug d'origine : le ticket notait que ROOT ne devrait PAS
> pouvoir valider (matrice I.3). Ici ROOT a pu. Le **défaut signalé** — endpoint
> absent — est corrigé ; la nuance RBAC est un point distinct à vérifier
> séparément.

## FRA-10 — PUT partiel impossible → **CORRIGÉ**
```
PUT /api/v1/identities/{id}  -d '{"occupation":"…"}'  (Bearer ROOT)
→ HTTP 200 {"description":"Identity updated"}
```
Le ticket relevait 422 « Field required » sur 12 champs. La modification d'un
seul champ est désormais acceptée.

## FRA-11 — validations métier KYC absentes → **CORRIGÉ**
```
date_of_birth futur (2031)     → HTTP 422  (ticket : 201)
pièce expirée (2020)           → HTTP 422  (ticket : 201)
âge 226 ans (1800)             → HTTP 422  (ticket : 201)
nationality "MARS"             → HTTP 422  (ticket : 201)
```

## FRA-12 — id_number accepte caractères dangereux → **CORRIGÉ**
```
id_number="111;DROP--"  → HTTP 422
id_number="<script>"    → HTTP 422
id_number="111'222"     → HTTP 422
id_number="111$222"     → HTTP 422
```
Le ticket relevait 201 pour les 9 patterns. Un regex de validation est
désormais appliqué.

## FRA-13 — champ requis + longueurs illimitées → **CORRIGÉ**
```
id_expire_on omis          → HTTP 422  (ticket : 201)
first_name de 5000 chars   → HTTP 422  (ticket : 201)
```

## FRA-14 — pas d'unicité sur id_number → **CORRIGÉ**
```
création 1 (id_number=PROBEUNIQ…)          → HTTP 201
création 2 (MÊME id_number)                → HTTP 400
```
Le ticket relevait 201/201 (doublon accepté). Le doublon est désormais refusé.
Le code est 400 et non 409 comme le suggérait l'attendu, mais le comportement
métier — rejet du doublon — est obtenu.

## Écritures laissées en base (identity-service n'a aucun DELETE)
- Identité réelle `8915ec15-…` (une de nos `DEMOQA0809`) : `is_verified` passé à
  true (FRA-9) et `occupation` modifiée (FRA-10).
- 1 identité créée `PROBEUNIQ60201` (FRA-14, création 1).
- Les tests FRA-11/12/13 n'ont créé **aucune** entité (tout rejeté en 422).

**Bilan identity : 9 / 9 CORRIGÉ.**

---

# CONFIG-SERVICE — 5 bugs + INFRA (campagne mai 2026)

Tous au statut **« Not a bug »**. Mesures : 10/08/2026 ~11:11–11:13 GMT.

## FRA-44 — pagination page≤0 → HTTP 500 + fuite BSON → **CORRIGÉ**
```
GET /api/v1/countries/?page=-1   → HTTP 422   (ticket : 500)
GET /api/v1/currencies/?page=0   → HTTP 422   (ticket : 500)
GET /api/v1/telcos/?page=-1      → HTTP 422   (ticket : 500)
```
Aucune fuite BSON dans les corps de réponse (le ticket exposait la requête
MongoDB interne). Les 3 endpoints valident désormais `page >= 1`.

## FRA-45 — Currency.iso_name doublon autorisé → **CORRIGÉ**
```
POST /currencies/create  iso_name=ZZ15  → HTTP 201
POST /currencies/create  iso_name=ZZ15  → HTTP 409   (ticket : 201)
```

## FRA-46 — Telco.name doublon autorisé → **CORRIGÉ**
```
POST /telcos/create  name=PROBE_TELCO_0317  → HTTP 201
POST /telcos/create  name=PROBE_TELCO_0317  → HTTP 409   (ticket : 201)
```

## FRA-47 — Telco phone_regex non compilable accepté → **CORRIGÉ**
```
POST /telcos/create  phone_regex="[unclosed bracket ("  → HTTP 422   (ticket : 201)
```
La regex est désormais testée par `re.compile()` avant insertion. Neutralise
le DoS transversal décrit (identity-service ne récupérera plus de regex
invalide) et le vecteur ReDoS.

## FRA-48 — RBAC ne reconnaît que ROOT → **CORRIGÉ (lecture) / COMPORTEMENT DIFFÉRENT (écriture)**

Les comptes de test `Probe_STAFF`/`Probe_GUEST` du ticket n'existent plus. Un
STAFF **complet** a donc été recréé selon le flow réel du système —
`identity → register(type_user=STAFF, identity, groupes=[STAFF]) → password/f/change → login` —
pour obtenir un vrai `access_token` (un compte sans groupe ni mot de passe
finalisé ne teste PAS le RBAC : son jeton temporaire rend 401 pour une raison
sans rapport).

```
STAFF complet, GET  /api/v1/countries/   → HTTP 200   (ticket : 403)
STAFF complet, POST /api/v1/countries/create → HTTP 404 (ticket : 403 ; STAFF attendu 201)
```

**Lecture : le défaut est levé.** Le middleware ne renvoie plus le `403`
systématique — un STAFF authentifié et porteur du groupe STAFF lit désormais le
référentiel (200). C'était le cœur du bug (« le middleware ne reconnaît que
ROOT »).

**Écriture : comportement différent.** `POST /countries/create` rend `404` et
non plus `403`. La route existe pourtant dans l'OpenAPI. Ce n'est plus le rejet
RBAC décrit ; le point mérite une vérification séparée (payload ou routage), il
n'est pas conclu ici.

## FRA-17 — APISIX : 5 security headers manquants → **TOUJOURS PRÉSENT**
```
          HSTS   X-Frame  X-Content  CSP   Server
user      ABSENT ABSENT   ABSENT     ABSENT APISIX/3.13.0
account   ABSENT ABSENT   ABSENT     ABSENT APISIX/3.13.0
identity  ABSENT ABSENT   ABSENT     ABSENT APISIX/3.13.0
company   ABSENT ABSENT   ABSENT     ABSENT APISIX/3.13.0
config    ABSENT ABSENT   ABSENT     ABSENT APISIX/3.13.0
```
Identique au ticket : les 4 en-têtes de sécurité restent absents et le header
`Server` expose toujours la version exacte `APISIX/3.13.0`.

## Écritures laissées en base (config-service — pas de DELETE sur create)
- 1 Currency `PROBE45a` (iso_name `ZZ15`)
- 1 Telco `PROBE_TELCO_0317`
- 1 Telco à regex invalide **non créé** (rejeté 422)

**Bilan config + infra : 5 CORRIGÉ (dont FRA-48 en lecture) · 1 TOUJOURS PRÉSENT (FRA-17).**

---

# USER-SERVICE — 11 bugs « Not a bug » retestés (campagne mai 2026)

Token ROOT. Pour FRA-37/40/41, le flow MFA réel a dû être reconstitué :
`login → auth_token (challenge) → mfa/verify(otp)`. L'OTP de test est **fixé à
`000000` en backend** (information métier). Mesures : 10/08/2026 ~11:24–12:31.

## FRA-1 — POST /auth/register renvoie 401 sous Bearer ROOT → **CORRIGÉ**
```
POST /auth/register  (Bearer ROOT, {})  → HTTP 422   (ticket : 401)
```
422 = authentification acceptée, seule la validation du corps échoue. Le rejet
d'auth du ticket a disparu ; la création de comptes fonctionne (utilisée pour
tout le reste de la campagne).

## FRA-2 & FRA-19 — check-permission accorde tout → **CORRIGÉ**
```
permission ["DELETE_EVERYTHING"]  → HTTP 400 "Unknown permissions"
permission ["FAKE_XYZ"]           → HTTP 400
permission []                     → HTTP 422
permission ["'; DROP TABLE--"]    → HTTP 422
permission ["USER_USER_READ"] ROOT → HTTP 200 (accordée à bon droit)
```
Le ticket relevait 200 « Check permission » dans 100 % des cas. L'endpoint
discrimine désormais : permission connue et détenue → 200 ; inconnue → 400 ;
malformée → 422.

## FRA-3 — refresh_token accepté comme access_token → **CORRIGÉ**
```
refresh_token sur /auth/me   → HTTP 401
refresh_token sur /users/    → HTTP 401
(témoin) access_token /auth/me → HTTP 200
```
Le refresh_token n'est plus accepté sur les endpoints protégés. Le témoin
access_token → 200 prouve que ce n'est pas une rupture de service.

## FRA-22 — endpoints /search au format non standard → **COMPORTEMENT DIFFÉRENT**
```
GET /groupes/               → data=[items]           (standard)
GET /groupes/search/ROOT    → data=[count,[items]]   (NON standard — comme au ticket)
GET /users/search/a         → data=[items]           (standard — différent du ticket)
```
État mixte : `groupes/search` conserve le format non standard signalé, tandis
que `users/search` est désormais standard. Ni pleinement corrigé, ni identique.

## FRA-28 — PUT /permissions/{id} → HTTP 500 → **CORRIGÉ**
```
PUT /permissions/{id}  (payload conforme)  → HTTP 200 "Permission updated"   (ticket : 500)
```

## FRA-33 — register type_user=ROOT (escalade de privilège) → **CORRIGÉ**
```
POST /auth/register  type_user=ROOT  → HTTP 403   (ticket : 201)
```
La création d'un compte ROOT par un ROOT est désormais refusée.

## FRA-37 — OTP "000000" accepté → **NON-BUG CONFIRMÉ (comportement voulu)**
Flow MFA complet (challenge token) :
```
otp=000000  → HTTP 200 "User login"     ← OTP de test fixé en backend, PAR DESIGN
otp=111111  → HTTP 400 "Incorrect OTP"
```
`000000` est l'OTP de test **hardcodé côté backend** pour l'environnement de
test. Son acceptation n'est pas une faille : c'est le comportement attendu, et
tout autre OTP est correctement rejeté (400). Le statut **« Not a bug » est
justifié.**

## FRA-40 — pas de rate limit sur /mfa/verify → **TOUJOURS PRÉSENT**
```
20 × POST /mfa/verify {otp:"111111"}  → HTTP 400 ×20, aucun HTTP 429
```
MFA réellement activé (method=EMAIL), OTP incorrects sur un challenge valide.
Aucune protection anti-brute-force après 20 tentatives. Identique au ticket.

## FRA-41 — pas de rate limit sur /verify-otp → **TOUJOURS PRÉSENT**
```
20 × POST /verify-otp {otp:"111111"}  → HTTP 400 ×20, aucun HTTP 429
```

## FRA-43 — audit trail inexistant → **CORRIGÉ**
Le chemin a changé (`/logs/users` → `/logs/`) :
```
GET /api/v1/logs/?skip=0&limit=5  → HTTP 200, 5 entrées d'audit horodatées
```
La table d'audit existe et contient des enregistrements (dès le 16/07).

## État modifié puis rétabli
MFA a été **activé sur le compte ROOT** pour tester FRA-37/40/41, puis
**désactivé** (`PUT /auth/mfa/disabled` → 200). Vérifié : un login ROOT
redonne un `access_token` direct — compte revenu à son état initial.

**Bilan user-service : 6 CORRIGÉ · 2 TOUJOURS PRÉSENT (FRA-40, FRA-41) · 1
COMPORTEMENT DIFFÉRENT (FRA-22) · 1 NON-BUG CONFIRMÉ (FRA-37).**

---

# TABLEAU DE SYNTHÈSE — retest MEP1 du 10/08/2026

Périmètre retesté : les campagnes de **mai 2026** (user, identity, config,
infrastructure). Les tickets de la campagne d'août 2026 (`FRA-194` → `FRA-231`,
services collect / depositary / company / client / account) sont **exclus** :
créés et vérifiés présents les 8–9 août, leur état est déjà connu.
Les tickets **WebApp** (`FRA-206/207/210/213/214/215`) sont **hors périmètre**
(retest Zidane).

| Ticket | Service | Sévérité | Statut Jira | Verdict retest | Preuve (résumé) |
|---|---|---|---|---|---|
| FRA-4 | identity | Medium | Not a bug | **CORRIGÉ** | sans Bearer → 401 ; avec ROOT → 200 |
| FRA-5 | identity | Medium | Not a bug | **CORRIGÉ** | JWT alg=none / forgé → 401 |
| FRA-6 | identity | Medium | Not a bug | **CORRIGÉ** | OCR sans Bearer → 401 (avant validation) |
| FRA-9 | identity | Critical | Not a bug | **CORRIGÉ** | POST /validate → 200 "Identity validated" |
| FRA-10 | identity | Major | Not a bug | **CORRIGÉ** | PUT partiel {occupation} → 200 |
| FRA-11 | identity | — | Not a bug | **CORRIGÉ** | KYC (futur/expiré/226 ans/MARS) → 422 |
| FRA-12 | identity | Critical | Not a bug | **CORRIGÉ** | id_number injections → 422 |
| FRA-13 | identity | Major | Not a bug | **CORRIGÉ** | champ requis + 5000 car. → 422 |
| FRA-14 | identity | Major | Not a bug | **CORRIGÉ** | doublon id_number → 400 (refusé) |
| FRA-44 | config | High | Not a bug | **CORRIGÉ** | page≤0 → 422, aucune fuite BSON |
| FRA-45 | config | Highest | Not a bug | **CORRIGÉ** | doublon iso_name → 409 |
| FRA-46 | config | Medium | Not a bug | **CORRIGÉ** | doublon Telco.name → 409 |
| FRA-47 | config | High | Not a bug | **CORRIGÉ** | phone_regex invalide → 422 |
| FRA-48 | config | Major | Not a bug | **CORRIGÉ (lecture)** | STAFF complet GET → 200 (ticket 403) ; POST → 404 |
| FRA-17 | APISIX | Medium | Not a bug | **TOUJOURS PRÉSENT** | 4 headers absents, Server: APISIX/3.13.0 |
| FRA-1 | user | Medium | Not a bug | **CORRIGÉ** | register Bearer ROOT → 422 (plus 401) |
| FRA-2 | user | Medium | Not a bug | **CORRIGÉ** | check-permission discrimine |
| FRA-3 | user | Medium | Not a bug | **CORRIGÉ** | refresh_token → 401 sur routes protégées |
| FRA-19 | user | — | Not a bug | **CORRIGÉ** | idem FRA-2 (permission invalide → 400/422) |
| FRA-22 | user | — | Not a bug | **COMPORTEMENT DIFFÉRENT** | users/search standard, groupes/search non standard |
| FRA-28 | user | — | Not a bug | **CORRIGÉ** | PUT /permissions/{id} → 200 (plus 500) |
| FRA-33 | user | — | Not a bug | **CORRIGÉ** | register type_user=ROOT → 403 |
| FRA-37 | user | — | Not a bug | **NON-BUG CONFIRMÉ** | OTP 000000 = OTP de test backend, par design |
| FRA-40 | user | — | Not a bug | **TOUJOURS PRÉSENT** | 20 OTP faux → 400×20, aucun 429 |
| FRA-41 | user | — | Not a bug | **TOUJOURS PRÉSENT** | idem sur /verify-otp |
| FRA-43 | user | — | Not a bug | **CORRIGÉ** | GET /logs/ → 200 avec entrées d'audit |

## Compteurs

| Verdict | Nombre |
|---|---:|
| **CORRIGÉ** | **20** (dont FRA-48 en lecture) |
| **TOUJOURS PRÉSENT** | **3** (FRA-17, FRA-40, FRA-41) |
| **COMPORTEMENT DIFFÉRENT** | **1** (FRA-22) |
| **NON-BUG CONFIRMÉ** | **1** (FRA-37) |
| **Total retesté** | **26** (campagnes de mai) |

## Fait principal établi par la mesure

La page MEP1 (Confluence) indique « aucun bug corrigé à ce jour », déduction
tirée de l'absence de changement de statut Jira. **La mesure directe établit que
20 des 26 anomalies retestées sont corrigées.** Les correctifs ont donc été
déployés sur l'environnement TEST **sans mise à jour des statuts Jira** — ce qui
confirme l'hypothèse de départ (les statuts ne reflètent pas l'état réel).

Les correctifs constatés couvrent des points de sécurité et d'intégrité majeurs :
authentification (JWT, séparation access/refresh, anti-escalade), validation KYC
(FATF/BEAC), anti-injection, unicité des identifiants (id_number, iso_name,
Telco.name), robustesse de la pagination, et journal d'audit.

Trois défauts restent reproduits à l'identique — **FRA-17** (en-têtes de
sécurité APISIX) et **FRA-40 / FRA-41** (absence de limitation du taux de
vérification OTP). Un point est ambigu (**FRA-22**, format de réponse mixte
entre endpoints). Un point classé « Not a bug » est confirmé comme
comportement voulu (**FRA-37**, OTP de test).

## Points relevés en marge (hors tickets, à investiguer séparément)

- **FRA-48 / écriture** : `POST /countries/create` par un STAFF complet renvoie
  `404` (et non plus `403`). La route existe dans l'OpenAPI ; le point mérite
  vérification (routage ou payload), non conclu.
- **10ᵉ service découvert** : `ussd-service` (v1.0.1, 8 opérations) répond sur
  `ussd-service.test.services.fintech4esg.com` — voir
  `2026-08-10_inventaire_MEP1.md`.

## Traçabilité — écritures laissées sur l'environnement TEST

Trois services (identity, account, depositary) n'exposent aucun `DELETE`.
Entités de test laissées en base, toutes préfixées :
- identity : identités `Probe*`, `PROBEUNIQ60201` ; identité `8915ec15-…`
  (`DEMOQA0809`) marquée `is_verified=true` et `occupation` modifiée (FRA-9/10) ;
- config : Currency `iso_name=ZZ15`, Telco `PROBE_TELCO_0317`, quelques
  countries `PROBE` (FRA-45/46/48) ;
- user : comptes STAFF de test `probestaff*` et `probe_qa_staff` ;
- compte ROOT : MFA activé puis **désactivé** — état initial rétabli, vérifié.

---

*Fin du rapport de retest MEP1. Mesures brutes horodatées dans les sections
par service ci-dessus. Aucun statut Jira modifié.*
