# Orange Money — contrat opérateur

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Référentiel des contrats opérateurs · Fiche T2
**Rédigée le** 2026-09-03 · **Socle de référence** [`00_socle_gsma.md`](00_socle_gsma.md)
**Nature** 100 % documentaire. Aucun appel vers une API Orange, aucune inscription, aucun compte créé.

> **Verdict en une phrase.** Le contrat technique d'Orange Money **n'est pas public**. La surface
> publique d'Orange est marketing (produit, pays, éligibilité) plus une couche OAuth 2.0 et un
> modèle d'erreur communs à *toute* la plateforme Orange ; **aucune route, aucun champ, aucun code
> d'erreur Orange Money n'est publié par Orange**. Tout ce qui circule sur les chemins et les
> payloads provient de SDK communautaires et n'a **aucune valeur contractuelle**.

---

## 1. Le portail développeur

### 1.1 Trois surfaces distinctes, à ne pas confondre

| # | Surface | URL | État constaté |
|---|---|---|---|
| P1 | **Orange Developer** — portail produit groupe | `https://developer.orange.com/` | Public en lecture. Page produit Orange Money visible sans compte. |
| P2 | **Orange Developer Doc** — portail documentaire groupe | `https://docs.developer.orange.com/` | Public. **Orange Money n'y a aucune page technique.** |
| P3 | **Orange Sonatel** — portail filiale Sénégal | `https://developer.orange-sonatel.com/` | Public en lecture, mais documentation technique derrière compte. |

### 1.2 P1 — la page produit

**FACT.** Nom exact du produit et version : **« Orange Money Web Payment / M Payment 1.0 »**,
catégorie *Payments*. Description officielle : « Enable your customer to pay for your products
through Orange Money on your website or your mobile application. »
Source : `https://developer.orange.com/apis/om-webpay` (consulté le 2026-09-03) **[OFFICIELLE]**

**FACT.** La page ne comporte que **deux onglets : « Overview » et « FAQs »**. Il n'existe ni
« Getting started », ni « API reference », ni lien vers un fichier de spécification.
*Vérifié personnellement par rendu de la page le 2026-09-03.*

Cette absence est **structurelle, pas accidentelle** : d'autres APIs Orange exposent bien ces
onglets. Comparaison faite sur `https://developer.orange.com/apis/sms/getting-started`, qui existe
réellement et publie ses endpoints en clair, alors que
`https://developer.orange.com/apis/om-webpay/getting-started` et `…/api-reference` retombent sur le
contenu de l'Overview (repli d'application monopage). Source : agent de recherche, vérifications
croisées le 2026-09-03 **[OFFICIELLE]**

**Note de méthode importante.** `developer.orange.com` répond **HTTP 403 à `curl`** (protection
anti-robot) : je l'ai constaté moi-même sur cinq URL. Les pages n'ont donc pu être lues qu'à
travers un rendu de navigateur, et **je n'ai pas pu en archiver le HTML brut** dans
`sources/orange-money/`. C'est une limite de traçabilité que j'assume et signale plutôt que de la
masquer.

### 1.3 P2 — le portail documentaire ne documente pas Orange Money

**FACT, vérifié personnellement.** J'ai téléchargé le catalogue de `docs.developer.orange.com`
(HTTP 200, 130 339 o, archivé dans `sources/orange-money/`). La rubrique **Payment** y contient
exactement trois entrées, et voici leurs libellés extraits du HTML :

> « **Direct Carrier Billing** — Direct Carrier Billing allows simple purchases of digital services
> with the Orange mobile account · **Orange Money** — Enable your customer to pay for your products
> through Orange Money on your website or your mobile application · **Billing M2M** — The Billing API
> lets internation[al]… »

L'entrée « Orange Money » **renvoie vers la page marketing P1**, pas vers une page documentaire.
À comparer aux Network APIs, qui ont, elles, `/getting-started` et `/api-reference` publics
(ex. `https://docs.developer.orange.com/network-apis/api-catalog/number-verification/es/current/api-reference`).
Source : `https://docs.developer.orange.com/` (consulté le 2026-09-03) **[OFFICIELLE]**

### 1.4 P3 — Sonatel : le seul portail filiale, et ce qu'il livre vraiment

**FACT, vérifié personnellement** (HTTP 200, 232 874 o, archivé). La page d'accueil met en avant
**trois APIs Orange Money**, libellés exacts relevés dans le HTML :

- **QR CODE - OM**
- **CASH IN - OM**
- **NOTIFICATION**

Ce sont des produits **distincts** de l'offre groupe « Web Payment / M Payment ». Mention de
sécurité affichée : « Sécurité garantie pour vos applications grâce à l'OAuth Token based access ».

**FACT, vérifié personnellement.** La page `https://developer.orange-sonatel.com/dev/docs/orange-money`
répond HTTP 200 (110 824 o) mais **ne contient aucune documentation technique** : ni endpoint, ni
champ, ni code d'erreur. Son contenu intégral utile est le parcours d'inscription. Citation
littérale extraite du HTML archivé :

> « **Intégration rapide en 3 étapes** — Le service est facile à intégrer grâce à un accès en ligne,
> la possibilité de tester en toute autonomie et une documentation détaillée : S'inscrire pour créer
> son compte · Créer une application pour tester rapidement la solution grâce aux multiples exemples
> disponibles dans la documentation · Envoyer ses documents administratifs depuis le site pour passer
> en production
>
> **Documents administratifs à fournir** — Etre une entreprise légalement enregistrée et fournir les
> documents ci-après dans le formulaire de complément d'informations *(nécessite un accès à votre
> compte développeur)* : Registre de Commerce et du Crédit Mobilier (RCCM) · Numéro d'Identification
> National des Entreprises et des Associations (NINEA) · Carte Nationale d'Identité (CNI) ou
> Passeport de toutes les personnes mentionnées sur le RCCM et celui du gestionnaire du compte ·
> Procuration du dirigeant social au profit du gestionnaire »

Deux enseignements, et le second est bon à savoir :

1. La phrase « **grâce à une documentation détaillée** » et « **multiples exemples disponibles dans
   la documentation** » atteste qu'une documentation technique **existe**. Elle est simplement
   derrière le compte. Ce n'est donc pas un trou d'existence, c'est un trou d'accès.
2. **Sonatel permet de tester « en toute autonomie » *avant* le dossier administratif.** Le passage
   en production est la 3ᵉ étape ; l'inscription et la création d'application sont les deux
   premières. **DÉDUIT** : c'est, de toutes les surfaces Orange examinées, la seule où une
   inscription libre semble suffire à atteindre la spécification. Si la direction décide un jour de
   lever un des trous de cette fiche, **c'est par là qu'il faut passer, et par nulle part ailleurs.**

Bannière relevée en tête de page : « Developer Portal is now API Portal and got refreshed » —
le portail a été refondu, les URL antérieures citées ailleurs peuvent être périmées.

**FACT, vérifié personnellement** : `https://developer.orange-sonatel.com/documentation` → **HTTP 404**.
`beta.developer.orange-sonatel.com` → DNS non résolu. `fibre.orange.sn`, présenté par un moteur de
recherche comme un portail développeur Orange, → **DNS non résolu** : non vérifiable, **écarté
intégralement**, aucun de son contenu supposé n'est repris ici.

### 1.5 La souscription est fermée

**FACT.** `https://developer.orange.com/products/payment/apply-orange-money/` affiche
« Sign in to access this page » et « You're about to apply for a subscription to the API 'Orange
Money Web Payment.' ». Les deux appels à l'action de la page produit (« Contact us », « Apply for
Orange Money ») pointent vers `…/products/payment-financial-services/apply-orange-money/`.
(consulté le 2026-09-03) **[OFFICIELLE]**

---

## 2. Spécification téléchargeable sans compte

**INTROUVABLE.**

Aucun fichier OpenAPI, Swagger, WSDL ou PDF de spécification Orange Money n'est téléchargeable
depuis un domaine Orange sans compte. Constats à l'appui :

- Aucune page du catalogue `docs.developer.orange.com` ne couvre Orange Money (§ 1.3).
- Même les APIs Orange qui possèdent une référence publique sur ce portail **n'exposent aucun lien
  de téléchargement OpenAPI/Swagger**. **[OFFICIELLE]**
- Un document officiel Orange intitulé **« Orange Money WebPay Dev – Getting started – Orange
  Developer » (17 pages)** existe : il n'a été trouvé que **republié sur Scribd**, contenu masqué
  derrière un paywall, sans aucune URL Orange d'origine.
  `https://www.scribd.com/document/638670689/…` (consulté le 2026-09-03) **[TIERCE]**

→ **Rien n'a pu être versé dans `docs/contrats/sources/orange-money/` au titre d'une
spécification.** Ce dossier ne contient que les quatre pages de portail archivées (§ 6).

**Conclusion : la spécification Orange Money est délivrée après contrat ou souscription.**

---

## 3. Ce qui est visible SANS inscription

### 3.1 Mécanisme d'authentification

**OFFICIEL — mais générique à toute la plateforme Orange, pas spécifique à Orange Money.**

Source : `https://developer.orange.com/tech_guide/2-legged-oauth-flow-step-by-step/`
(consulté le 2026-09-03) **[OFFICIELLE]**

```http
POST https://api.orange.com/oauth/v3/token
Authorization: Basic <base64(client_id:client_secret)>
Content-Type: application/x-www-form-urlencoded
Accept: application/json

grant_type=client_credentials
```

Réponse HTTP 200 :

```json
{ "token_type": "Bearer", "access_token": "...", "expires_in": 3600,
  "scope": "ope:API name:API version:access" }
```

**FACT** : « The `grant_type` is required and is fixed to `client_credentials` ». Les identifiants
sont fournis « in your client space MyApps > tab Credentials ». Débit annoncé sur l'endpoint de
jeton : **50 requêtes/minute**, HTTP 429 au-delà. `Accept: application/json` est obligatoire,
HTTP 406 sinon. Les appels ultérieurs portent `Authorization: Bearer {access_token}`
(`https://developer.orange.com/resources/quickstart/`, **[OFFICIELLE]**).

> ⚠️ **Aucun texte officiel ouvert ne rattache explicitement ce flux à Orange Money Web Payment.**
> Le rattachement est une inférence de bon sens, **pas un fait sourcé**. Il est consigné comme tel
> et ne doit pas être présenté au client comme acquis.

**CONFLIT non arbitré — version de l'endpoint de jeton :**

| Valeur | Source | Nature |
|---|---|---|
| `https://api.orange.com/oauth/**v3**/token` | `developer.orange.com/tech_guide/2-legged-oauth-flow-step-by-step/` | **OFFICIELLE** |
| `https://api.orange.com/oauth/**v2**/token` | `github.com/Ibracilinks/OrangeMoney` → `src/Api.php` | **TIERCE** |

Les deux sont enregistrées. Je ne tranche pas : la source officielle est plus récente mais ne parle
pas d'Orange Money, la source tierce parle d'Orange Money mais n'est pas officielle.

### 3.2 Routes et opérations

**Sur source OFFICIELLE : INTROUVABLE.** Aucun chemin HTTP Orange Money n'apparaît sur aucune page
Orange consultée.

**Sur sources TIERCES uniquement** — trois implémentations indépendantes et concordantes,
base `https://api.orange.com` :

| Verbe | Chemin | Rôle allégué |
|---|---|---|
| POST | `/orange-money-webpay/{env}/v1/webpayment` | initialisation du paiement |
| POST | `/orange-money-webpay/{env}/v1/transactionstatus` | consultation de statut |

`{env}` est un segment pays/environnement. Valeurs citées : **`dev`** (test), **`gn`** (Guinée),
**`cm`** (Cameroun), **`ci`** (Côte d'Ivoire).

Sources **[TIERCES]**, consultées le 2026-09-03 :
`github.com/Ibracilinks/OrangeMoney` (`src/Api.php`) ·
`github.com/Foris-master/orange-money-sdk` (`README.md`) ·
`github.com/pathus90/om4j` (`README.md`).

En-têtes employés par ces SDK : `Authorization: Bearer <token>`, `Accept: application/json`,
`Content-Type: application/json`. **[TIERCE]**

> **Signalement d'honnêteté.** L'URL `https://api.orange.com/orange-money-webpay/cm/v1/webpayment`
> est apparue dans un index de moteur de recherche sous le titre « Products - Orange Developer ».
> **Elle n'a pas été ouverte** — la mission interdit tout appel vers une API opérateur. Ce n'est
> donc **pas** un fait vérifié, seulement un indice concordant, et il est consigné comme tel.

### 3.3 Format des identifiants et des champs

**Sur source OFFICIELLE : INTROUVABLE.** Aucun nom de champ Orange Money n'est publié par Orange.

**Un point officiel mérite pourtant d'être relevé, et il change la nature du contrat.**
**FACT** : le flux Web Payment décrit par Orange est une **redirection suivie d'un OTP** — le client
« generate a One Time Password (OTP) via the Orange Money USSD service on their mobile to validate
their payment ». Source : `https://developer.orange.com/apis/om-webpay` **[OFFICIELLE]**

**DÉDUIT** : **le marchand ne transmet donc jamais le MSISDN du payeur.** Orange Money Web Payment
n'est pas une API de débit direct comparable au socle GSMA ; c'est un tunnel de paiement hébergé.
Cette différence de nature prime sur toutes les divergences de détail de la § 4, et elle a une
conséquence directe sur la sandbox : **il n'y a pas de `debitParty` à simuler côté marchand.**

Champs cités par les SDK **[TIERCE]** :

- Requête `webpayment` : `merchant_key`, `currency`, `order_id`, `amount`, `return_url`,
  `cancel_url`, `notif_url`, `lang`
- Réponse `webpayment` : `status`, `message`, `pay_token`, `payment_url`, `notif_token`
- Requête `transactionstatus` : `order_id`, `amount`, `pay_token`

### 3.4 Idempotence

**INTROUVABLE, officiellement comme officieusement.** Aucune clé d'idempotence, aucun en-tête
dédié, aucune règle de rejeu documentée nulle part.

Le seul indice est un code d'erreur tiers « **Duplicate order ID** » (§ 3.5), qui suggère une
contrainte d'unicité sur `order_id`. Une contrainte d'unicité **n'est pas** une garantie
d'idempotence : elle dit qu'un doublon est rejeté, elle ne dit pas que le rejeu d'une requête
identique renvoie le résultat initial. La distinction est décisive pour la sandbox et reste
entièrement ouverte.

### 3.5 Codes d'erreur et statuts

**OFFICIEL, générique** — « This error model applies to all Orange APIs ».
Source : `https://developer.orange.com/resources/orange-apis-error-handling/`
(consulté le 2026-09-03) **[OFFICIELLE]**

Corps d'erreur JSON : `code` (integer), `message` (string), `description` (optionnel),
`infoURL` (optionnel).

| HTTP | `code` | Cause |
|---|---|---|
| 401 | 40 | Missing credentials |
| 401 | 41 | Invalid credentials |
| 401 | 42 | Expired OAuth token |
| 403 | 50 | Not subscribed to API |
| 403 | 53 | Rate-limited / quota exceeded |
| 503 | 5 | API unavailable |

Statuts HTTP couverts par le modèle : 400, 401, 403, 404, 405, 406, 408, 409, 415, 429, 500, 502,
503, 504.

**Codes métier Orange Money : aucun publié par Orange.** Sur sources **[TIERCES]** uniquement
(`om4j`) : `50` (access denied by ACL), `1201` (forbidden transaction), `1202` (« Invalid merchant
key »), `1203` (unsupported currency for country), `1204` (duplicate order ID).

**Statuts de transaction**, deux sources tierces concordantes (`om4j`, `orange-money-sdk`) :
`INITIATED`, `PENDING`, `EXPIRED`, `SUCCESS`, `FAILED`. **[TIERCE]**

> Rappel du socle : la GSMA **n'énumère pas** `transactionStatus` (T-SOCLE-01). Il n'y a donc ici
> ni conformité ni divergence à constater — seulement l'absence de source officielle.

### 3.6 Sandbox opérateur et limites annoncées

**Le mot « sandbox » n'apparaît nulle part sur les pages produit Orange.** Une seule phrase
officielle atteste qu'un test est possible, **FACT** :

> « APIs can be tested by merchants or their integrators prior to going live with commercial
> services. » — `https://developer.orange.com/apis/om-webpay` **[OFFICIELLE]**

> « Once I complete the tests, how do I go into production? — You will receive full details via
> email. Once the tests are completed, you are ready to go to production. »
> — `https://developer.orange.com/apis/om-webpay/faq` **[OFFICIELLE]**

**Aucune URL de sandbox, aucun plafond de montant, aucun quota, aucune limite de débit spécifique à
Orange Money ne sont publiés.** *Vérifié personnellement sur la FAQ le 2026-09-03 : la question des
environnements de test, quotas et plafonds n'y est pas traitée, et aucun tarif n'est publié — la
réponse est « Please speak to your local Orange operator ».*

Sur sources **[TIERCES]** : l'environnement de test correspond au segment `dev` du chemin, et la
devise de test serait `OUV` — « All supported countries use the testing currency code OUV in sandbox
mode » (`om4j`, `orange-money-sdk`, module Odoo `payment_orangemoney`).

**Le seul environnement de test dont l'accès autonome soit officiellement affirmé est celui de
Sonatel** (§ 1.4), et il exige une inscription.

### 3.7 Périmètre pays — **CONFLIT entre deux pages officielles Orange**

*Relevé personnellement le 2026-09-03 sur les deux pages.*

| Source | Liste citée |
|---|---|
| **Overview** `…/apis/om-webpay` | Mali, Cameroon, Cote d'Ivoire, Senegal, Madagascar, Botswana, Guinea Conakry, Guinea Bissau, Sierra Leone, RD Congo, Central African Republique, **Egypt** |
| **FAQ** `…/apis/om-webpay/faq` | Mali, Cameroon, Senegal, Madagascar, Botswana, Guinea Conakry, Sierra Leone, Cote d'Ivoire, Guinea Bissau, **Liberia** |

**CONFLIT, non arbitré.** L'Overview cite RD Congo, Centrafrique et Égypte, absents de la FAQ ;
la FAQ cite le Liberia, absent de l'Overview. Les deux pages sont officielles et du même produit.

**Ce conflit touche directement FinZuu : le Cameroun figure dans les deux listes** — c'est le seul
point de convergence utile ici, et il est solide.

### 3.8 Les autres produits « Payment » d'Orange, à ne pas confondre

| Produit | Ce que c'est | Source |
|---|---|---|
| **Orange Money Web Payment / M Payment 1.0** | l'objet de cette fiche | `…/apis/om-webpay` **[OFFICIELLE]** |
| **Pay with Orange Bill 1.0** | **Direct Carrier Billing** — « charges a digital content purchase or subscription to the Orange customer bill ». **Ce n'est pas Orange Money** : c'est de la facturation opérateur. | `…/apis/pay-with-orange-bill` **[OFFICIELLE]** |
| **Billing M2M** | listé sous « Payment » au catalogue documentaire | `docs.developer.orange.com` **[OFFICIELLE]** |
| **emoney wallet manager** | « operate electronic money accounts, and manage payments & cashing between users » — **périmètre UE**, pas Afrique | `…/resources/monetization-and-payment/` **[OFFICIELLE]** |
| **QR CODE - OM · CASH IN - OM · NOTIFICATION** | produits **Sonatel**, distincts de l'offre groupe | `developer.orange-sonatel.com` **[OFFICIELLE]** |

**Conditions d'accès, FACT** : marchands « fully KYA compliant », devant détenir un compte Orange
Money — « They must be officially registered retailers (Orange Money merchants - fully KYA
compliant) ». Coûts : « Please speak to your local Orange operator. »

---

## 4. Conformité au socle GSMA

Grille G1..G22 de [`00_socle_gsma.md`](00_socle_gsma.md) § 7.
**Règle de lecture : « NON DOCUMENTÉ » signifie « non su », jamais « absent ».**

| Réf. | Point de contrôle | Verdict | Fondement |
|---|---|---|---|
| G1 | Authentification client | **DIVERGENT (partiel)** | OAuth 2.0 `client_credentials` + `Bearer` : compatible avec le socle (§ 5 : OAuth2 admis). Mais `client_id`/`client_secret` en **Basic sur l'endpoint de jeton**, et **aucun** `X-API-Key`/`X-Client-Id`. Non rattaché officiellement à Orange Money. |
| G2 | URI et versionnage | **DIVERGENT** | `/orange-money-webpay/{env}/v1/…` — le segment littéral `mm` du socle est absent, et `{env}` (pays + environnement dans le chemin) n'a pas d'équivalent GSMA. Versionnage `v1`, non `X.Y.Z`. **[TIERCE]** |
| G3 | Identification des parties | **DIVERGENT — par nature** | Pas de `debitParty`/`creditParty`. Le payeur n'est **jamais** transmis (redirection + OTP, § 3.3). Le bénéficiaire est le `merchant_key`. Modèle de tunnel, pas de transfert. |
| G4 | Format MSISDN | **NON DOCUMENTÉ** | Aucun MSISDN dans le flux Web Payment. |
| G5 | Représentation du montant | **NON DOCUMENTÉ** | Champs `amount` + `currency` existent **[TIERCE]**, mais ni type, ni décimales, ni bornes ne sont publiés. Devise de test `OUV` **[TIERCE]** : hors ISO 4217, donc divergence probable — non confirmée. |
| G6 | Référence fournisseur vs. cliente | **DIVERGENT** | `order_id` (marchand) et `pay_token` (Orange) jouent les deux rôles, sans les noms GSMA. Pas de `transactionReceipt` distinct. **[TIERCE]** |
| G7 | Types de transaction | **DIVERGENT** | Aucune notion de `type` parmi les 9 codes GSMA. Un seul usage : paiement marchand. |
| G8 | **Idempotence** | **NON DOCUMENTÉ** | Aucune clé, aucun en-tête, aucune règle de rejeu (§ 3.4). |
| G9 | Récupération de réponse perdue | **NON DOCUMENTÉ** | Pas d'équivalent `/responses`. `transactionstatus` permet une consultation, mais son contrat n'est pas publié. |
| G10 | Notification asynchrone | **DIVERGENT** | `notif_url` + `notif_token` **[TIERCE]** ≠ `X-Callback-URL` + PUT du socle. **Contrat du webhook entièrement inconnu** : verbe, corps, signature, rejeu. |
| G11 | Objet d'erreur | **DIVERGENT** | `code`/`message`/`description`/`infoURL` **[OFFICIELLE]** au lieu de `errorCategory`/`errorCode`/`errorDescription`. Codes numériques, pas de catégorie. |
| G12 | Catalogue de codes d'erreur | **DIVERGENT (plateforme) / NON DOCUMENTÉ (métier)** | 6 codes plateforme officiels ; les codes métier 1201–1204 sont **[TIERCE]** et non confirmés. |
| G13 | Cycle de vie de la requête | **NON DOCUMENTÉ** | Pas d'objet `RequestState`, pas de `pending`/`completed`/`failed` documentés. |
| G14 | Cycle de vie de la transaction | **NON DOCUMENTÉ** | `INITIATED`/`PENDING`/`EXPIRED`/`SUCCESS`/`FAILED` **[TIERCE]** seulement. Rappel : le socle ne normalise pas ce cycle (T-SOCLE-01). |
| G15 | Traitement par lot | **NON DOCUMENTÉ** | Aucune notion de lot dans l'offre Web Payment. |
| G16 | Solde et statut de compte | **NON DOCUMENTÉ** | Absent de l'offre Web Payment. Éventuellement couvert par les produits Sonatel (« CASH IN - OM »), non vérifiable sans compte. |
| G17 | Cotation / frais / change | **NON DOCUMENTÉ** | Aucune API de cotation publiée. |
| G18 | Contrepassation / remboursement | **NON DOCUMENTÉ** | Aucun endpoint de reversal publié, ni officiel ni tiers. |
| G19 | Pagination | **NON DOCUMENTÉ** | Aucune collection paginée publiée. |
| G20 | Canal d'origine | **DIVERGENT** | Pas de `X-Channel`. En revanche `lang` **[TIERCE]**, et le canal réel de validation est **l'USSD** (OTP) côté client final — imposé, non paramétrable. |
| G21 | Supervision | **NON DOCUMENTÉ** | Aucun `/heartbeat` ni page de statut de service publiée. |
| G22 | Sandbox opérateur et limites | **NON DOCUMENTÉ** | Test attesté par une phrase, sans URL, sans quota, sans plafond (§ 3.6). |

**Synthèse de la grille : 0 CONFORME · 9 DIVERGENT · 13 NON DOCUMENTÉ.**

Il faut lire ce zéro correctement : il ne dit pas qu'Orange Money contredit la GSMA sur toute la
ligne, il dit qu'**Orange Money Web Payment n'est pas une API de mobile money au sens du socle** —
c'est un tunnel de paiement marchand. Comparer les deux champ à champ a une valeur limitée ; ce qui
compte pour la sandbox est en § 5.

---

## 5. TROUS À CALIBRER

Chaque trou est un point sur lequel la sandbox FinZuu devra **décider sans source**. La décision
devra être écrite et assumée comme une convention FinZuu, jamais présentée comme le comportement
d'Orange.

| # | Trou | Ce qui manque exactement | Impact sur la sandbox | Comment le lever |
|---|---|---|---|---|
| **T-OM-01** | **Contrat des routes** | Aucun chemin officiel. `/orange-money-webpay/{env}/v1/webpayment` et `/transactionstatus` sont **[TIERCES]** et non contractuels. | On ne peut pas garantir que le simulateur expose les bons chemins. | Souscription Orange, ou inscription Sonatel (§ 1.4). |
| **T-OM-02** | **Contrat du webhook `notif_url`** | Verbe HTTP, corps, **signature/authentification**, politique de rejeu, idempotence côté réception : **rien**, y compris en tierce. | Le webhook est le cœur du flux asynchrone. Sans contrat, la sandbox invente tout, y compris la sécurité. | Idem. **Trou le plus grave de cette fiche.** |
| **T-OM-03** | **Idempotence et rejeu** | Aucune clé, aucune fenêtre de rémanence, aucun comportement de rejeu. Unicité de `order_id` supposée par un code d'erreur tiers. | Impossible de tester le double paiement — c'est-à-dire exactement le défaut FRA-235 relevé sur le module Bulk. | Idem. |
| **T-OM-04** | **Format et bornes du montant** | Type (chaîne ou nombre), décimales, montant minimum et maximum, arrondi en XAF. | Les tests aux limites n'ont pas d'oracle. | Idem. |
| **T-OM-05** | **Devise de test** | `OUV` est **[TIERCE]** et hors ISO 4217. Non confirmé, et incompatible avec le socle (G5). | Si vrai, tout jeu de test en XAF est faux en sandbox. Si faux, on a introduit une devise fantôme. | Idem. **À trancher avant tout jeu de données.** |
| **T-OM-06** | **Codes d'erreur métier** | 1201–1204 sont **[TIERCES]**. Aucune table officielle. | Les assertions d'erreur de la sandbox seront arbitraires. | Idem. |
| **T-OM-07** | **Statuts de transaction** | `INITIATED`/`PENDING`/`EXPIRED`/`SUCCESS`/`FAILED` **[TIERCE]**. Transitions, terminalité et délais inconnus. | Aucune machine à états fiable. Aggravé par T-SOCLE-01 : le socle ne comble pas ce trou. | Idem. |
| **T-OM-08** | **Durée de vie du `pay_token` / expiration** | Le statut `EXPIRED` existe **[TIERCE]** mais **aucun délai n'est publié**. | Le scénario d'expiration ne peut pas être simulé fidèlement. | Idem. |
| **T-OM-09** | **Version de l'endpoint OAuth** | CONFLIT `v2` / `v3` non arbitré (§ 3.1). | Choix arbitraire dans la configuration du profil. | Confirmation Orange. |
| **T-OM-10** | **Rattachement du flux OAuth à Orange Money** | Aucune page officielle ne dit qu'Orange Money utilise `oauth/v3/token`. | Le mécanisme d'authentification du profil repose sur une inférence. | Idem. |
| **T-OM-11** | **Sandbox : URL, quotas, plafonds** | Aucune URL, aucun quota, aucun plafond, aucun tarif (§ 3.6). | Impossible de dimensionner ni de reproduire les limites. | Inscription Sonatel, ou opérateur local. |
| **T-OM-12** | **Périmètre pays** | CONFLIT Overview / FAQ (§ 3.7) : Égypte, RD Congo, RCA, Liberia. | Faible pour FinZuu — **le Cameroun figure dans les deux listes.** | Confirmation Orange. |
| **T-OM-13** | **Produits Sonatel (QR CODE-OM, CASH IN-OM, NOTIFICATION)** | Ces trois APIs sont probablement plus proches d'un vrai mobile money que le Web Payment groupe. **Contrat entièrement inconnu.** | On ignore si un modèle plus riche (cash-in, notification) est disponible. | Inscription Sonatel. |
| **T-OM-14** | **Contrepassation / remboursement** | Aucun endpoint, aucune procédure, ni officielle ni tierce. | Le cycle d'annulation est absent du profil. | Souscription. |

**Décision à porter à la direction.** Douze de ces quatorze trous se lèvent par le même geste :
**créer un compte développeur sur `developer.orange-sonatel.com`**, seul portail Orange annonçant
explicitement un test autonome avant dossier administratif. La présente mission l'interdit
expressément (« aucune inscription à un portail ») ; c'est donc un arbitrage, pas une action.

---

## 6. Sources archivées

Dans `docs/contrats/sources/orange-money/` :

| Fichier | Origine | Taille |
|---|---|---|
| `docs-developer-orange-com_catalogue_2026-09-03.html` | `https://docs.developer.orange.com/` | 130 339 o |
| `sonatel_accueil_2026-09-03.html` | `https://developer.orange-sonatel.com/` | 232 874 o |
| `sonatel_dev_2026-09-03.html` | `https://developer.orange-sonatel.com/dev` | 134 795 o |
| `sonatel_dev-docs-orange-money_2026-09-03.html` | `https://developer.orange-sonatel.com/dev/docs/orange-money` | 110 824 o |
| `NOTES_VERIFICATION.txt` | mes propres vérifications (403 anti-bot, 404, wildcard DNS) | — |

**Non archivable** : les pages de `developer.orange.com` (HTTP 403 sur récupération directe, § 1.2).
**Non archivable** : aucune spécification, il n'en existe pas de publique (§ 2).

---

## 7. Niveau de confiance pour le futur profil opérateur

**FAIBLE.**

Ce qui est solide : le produit existe, son nom et sa version sont établis, le Cameroun est dans le
périmètre, la nature du flux (redirection + OTP USSD, sans MSISDN marchand) est officielle, et le
modèle d'erreur plateforme est publié.

Ce qui ne l'est pas : **tout le contrat technique**. Chemins, champs, webhook, idempotence,
statuts, montants, devise de test, codes métier — chaque élément vient de SDK communautaires.
Un profil Orange Money construit aujourd'hui serait une reconstitution plausible, pas un contrat,
et devrait être étiqueté comme tel dans la sandbox jusqu'à obtention de la documentation officielle.
