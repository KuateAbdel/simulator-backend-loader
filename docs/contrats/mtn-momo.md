# MTN Mobile Money (MoMo) — contrat opérateur

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Référentiel des contrats opérateurs · Fiche T2
**Rédigée le** 2026-09-03 · **Socle de référence** [`00_socle_gsma.md`](00_socle_gsma.md)
**Nature** 100 % documentaire. **Aucun appel à l'API transactionnelle MoMo**, aucune inscription,
aucun compte créé.

> **Verdict en une phrase.** MTN est **le seul opérateur du référentiel dont le contrat technique
> soit réellement public et lisible sans compte** : 53 opérations avec chemins et verbes exacts,
> les énumérations de statuts et d'erreurs, les identifiants de pays dont **`mtncameroon`**, et une
> sandbox documentée avec ses numéros de test. C'est aussi le seul dont on puisse écrire un profil
> sans rien inventer — à trois trous près, dont l'un (le verbe du callback) est un conflit interne
> à la documentation de MTN elle-même.

---

## 0. Note de méthode — comment ces faits ont été obtenus

Le portail est une application Azure API Management. Deux conséquences pratiques :

1. **Les pages de documentation sont des coquilles** (~6,5 Ko) ; le texte visible vit dans des
   iframes `/content/html_widgets/<id>.html`.
2. **Les données d'API sont servies par l'API de contenu du portail**, sous `/developer/*`.

**J'ai interrogé moi-même cette API de contenu et j'ai revérifié chaque liste.** C'est l'API de
*lecture du site*, celle qu'un navigateur appelle en affichant la page — **ce n'est pas l'API MoMo**.
`sandbox.momodeveloper.mtn.com` n'a jamais été appelé, conformément à la mission.

Ce que j'ai vérifié personnellement, et non repris d'un tiers : **les 53 opérations** (23 + 16 + 14,
recomptées), **les 8 énumérations du schéma**, **les 4 produits et leurs `terms`**, **le tableau des
codes d'erreur** (widget `ohu47`) et **le parcours d'intégration** (widget `ht0i6`). Tous sont
archivés en JSON et HTML bruts dans `docs/contrats/sources/mtn-momo/`.

---

## 1. Le portail développeur

**URL : `https://momodeveloper.mtn.com/`. État : PUBLIC.** L'inscription n'est requise que pour
souscrire à un produit et obtenir des clés — **pas pour lire la documentation**.
(consulté le 2026-09-03) **[OFFICIELLE]**

Navigation visible sans connexion : « Home · Documentation · API Sandbox · Products · Support ·
Sign in · Sign up ».

Détail révélateur : le `<title>` de **toutes** les pages du portail, page d'accueil comprise, est
**« - Developer portal - Test environment »**, et le `<meta name="author">` vaut **`Ericsson`**.
**DÉDUIT** : la plateforme MoMo est bâtie sur un socle Ericsson, et le portail public est
l'instance de test. Cohérent avec le fait que l'unique hôte d'API publié soit celui de la sandbox
(§ 6).

Mention légale en pied de page : « MTN (PTY) LTD is an authorised Financial Service Provider.
FSP license number: **44774** — MoMo is a subsidiary of MTN Group » *(vérifié personnellement,
widget archivé)*.

**Pages de documentation ouvertes sans compte** : `/api-documentation` (Introduction),
`/getting-started`, `/api-description` (API User and Key Management), `/use-cases`, `/testing`
(Sandbox Use Cases), `/common-error`, `/callback`, `/brand-guidelines`, `/best-practices`,
`/get-started`, `/API-collections` et `/api-details` (référence API interactive complète).

**Nuance mesurée** : `/products`, `/Product-descriptions` et `/apis` sont servies en HTTP 200 mais
**ne rendent aucun contenu métier** à un visiteur non connecté. En revanche `/api-details` et
`/API-collections` rendent **la référence complète**. L'anomalie est dans l'affichage, pas dans les
droits.

---

## 2. Spécification téléchargeable sans compte

**Un fichier existe et se télécharge — mais il est vide de toute opération.** C'est le piège le plus
subtil de cette fiche.

La référence propose un menu « API definition » : *Open API 3 (YAML) · Open API 3 (JSON) ·
Open API 2 (JSON) · WADL · Changelog*. L'export passe par
`/developer/apis/collection?export=true&format=openapi-link&api-version=2022-04-01-preview`, qui
renvoie un lien SAS Azure Blob à expiration courte.

**Contenu intégral du `Collection.yaml` ainsi obtenu (466 octets) :**

```yaml
openapi: 3.0.1
info:
  title: Collection
  description: 'Enable remote collection of bills, fees or taxes'
  version: '1.0'
servers:
  - url: https://sandbox.momodeveloper.mtn.com/collection
paths: { }
components:
  securitySchemes:
    apiKeyHeader: { type: apiKey, name: Ocp-Apim-Subscription-Key, in: header }
    apiKeyQuery:  { type: apiKey, name: subscription-key, in: query }
security:
  - { }
  - apiKeyHeader: [ ]
  - apiKeyQuery: [ ]
```

**`paths: { }` est vide.** Idem pour `Collection.json` (Swagger 2.0, `"paths": {}`),
`Collection.xml` (WADL, `<resources base="…/collection" />` sans ressource), `Disbursements.yaml`
(466 o) et `Remittance.yaml` (475 o). Le lien blob de `Sandbox User Provisioning.yaml` n'est pas
téléchargeable en l'état (espaces non encodés).

**Conclusion : il n'existe pas de spécification machine exploitable en accès anonyme.** Le contenu
structuré des opérations n'est accessible que par l'API de contenu du portail (§ 0) ou par
l'affichage HTML. C'est une nuance décisive : **quiconque conclurait « MTN publie son OpenAPI »
sur la seule existence du fichier se tromperait.**

**PDF de spécification : INTROUVABLE.** Les seuls PDF du domaine sont des formulaires KYC de mise en
production (ex. `content/Nigeria_KYC.pdf`).

**Ce qui est archivé, en revanche** (récupéré par mes soins) : les listes d'opérations, le schéma et
les produits, en JSON brut, dans `docs/contrats/sources/mtn-momo/`. C'est fonctionnellement
l'équivalent de la spécification, obtenu autrement.

---

## 3. Les produits

Quatre produits d'abonnement. *Vérifié personnellement via `/developer/products` (archivé).*
Tous portent `subscriptionRequired: true`, `approvalRequired: false`, `subscriptionsLimit: 1`.

| id | Libellé et description | `terms` (verbatim) |
|---|---|---|
| `momowidget` | **Collection Widget** — « Receive mobile money payments on your website through a USSD or QR code » | `Prerequires \| Collection Widget` · `APIs \| MoMoPay` · `Documentation \| /widget-api` |
| `collections` | **Collections** — « Enable remote collection of bills, fees or taxes. » | `Prerequires \| OAuth 2.0` · `APIs \| ValidateAccountHolder, Balance, RequestToPay` · `Documentation \| /docs/services/collection` |
| `disbursements` | **Disbursements** — « Automatically deposit funds to multiple users » | `Prerequires \| OAuth 2.0` · `APIs \| ValidateAccountHolder, Balance, Transfer` |
| `remittances` | **Remittances** — « Remit funds to local recipients from the diaspora with ease » | `Prerequires \| OAuth 2.0` · `APIs \| ValidateAccountHolder, Balance, Transfer` |

Quatre **APIs** (objets distincts des produits) : `collection`, `disbursement`, `remittance`,
`sandbox-provisioning-api`.

Souscriptions, **FACT** : « Developers are issued a Primary Key and Secondary Key for every product.
Both primary and secondary Subscription key provides access to the API. **Subscriptions are stored
under the user profile and have no expiry.** » — le lien d'activation de compte, lui, « expires
within 24 hours ».

---

## 4. Authentification — deux niveaux

**FACT** (page *API User and Key Management*) :

> « There are two credentials used in the Open API. — **Subscription Key** — **API User and API Key** »
>
> « The subscription key is used to give access to APIs in the API Manager portal. […] The
> subscription key is assigned to the **`Ocp-Apim-Subscription-Key`** parameter of the header. »
>
> « The API User and API Key are used to grant access to the **wallet system in a specific country**.
> API user and Key are wholly managed by the user through Partner Portal. »
>
> « The Open API uses **Oauth 2.0** token for authentication of request. User will request an access
> token using **Client Credential Grant according to RFC 6749**. The token received is according to
> **RFC 6750 Bearer Token**. »
>
> « The API user and API key are used in the **basic authentication header** when requesting the
> access token. »

**C'est un modèle à deux étages, et il faut le comprendre pour ne pas se tromper de simulation :**
la clé d'abonnement ouvre la *passerelle*, le couple API User / API Key ouvre le *portefeuille d'un
pays donné*. Un client correctement authentifié à la passerelle peut donc échouer au second étage.

Provisionnement (sandbox uniquement), **FACT** — routes citées littéralement :

```http
POST {baseURL}/apiuser
Host: momodeveloper.mtn.com
X-Reference-Id: c72025f5-5cd1-4630-99e4-8ba4722fad56
Ocp-Apim-Subscription-Key: d484a1f0d34f4301916d0f2c9e9106a2

{"providerCallbackHost": "clinic.com"}
```
→ 201. Puis `POST {baseURL}/apiuser/{APIUser}/apikey` → 201 avec `{ "apiKey": "…" }`,
et `GET {baseURL}/apiuser/{APIUser}` → 200 avec
`{ "providerCallbackHost": "clinic.com", "targetEnvironment": "sandbox" }`.

**FACT, important** : « It is possible to fetch API user details such as Call Back Host. However,
**it is not possible to fetch the API key**. Provider shall be required to generate a new Key should
they lose the existing one. »

**FACT** : en production « the provisioning is done through the User Portal » ; la Provisioning API
n'existe que sur la sandbox, « **for testing purposes only** ».

### En-têtes d'une opération réelle (`RequesttoPay`)

| En-tête | Requis | Description (verbatim) |
|---|---|---|
| `Authorization` | oui | « Bearer Authentication Token generated using CreateAccessToken API Call » |
| `X-Target-Environment` | oui | « The identifier of the Wallet Platform system where the transaction shall be processed. This parameter is used to route the request to the Wallet Platform system that will initiate the transaction. » |
| `X-Reference-Id` | oui | « Format - UUID. Recource ID of the created request to pay transaction. […] 'Universal Unique ID' for the transaction generated using **UUID version 4**. » |
| `X-Callback-Url` | non | « URL to the server where the callback should be sent. » |
| `Ocp-Apim-Subscription-Key` | oui | schéma de sécurité déclaré (`apiKeyHeader`) |

### Valeurs de `X-Target-Environment` publiées

**FACT**, verbatim, 15 valeurs :

```
mtnuganda · mtnghana · mtnivorycoast · mtnzambia · mtncameroon · mtnbenin · mtncongo
mtnswaziland · mtnguineaconakry · mtnsouthafrica · mtnliberia · mtnsouthsudan
mtnnigeria · mtnrwanda · sandbox (For Test Environment)
```

**`mtncameroon` est publié.** C'est le fait le plus directement exploitable de tout ce référentiel
pour FinZuu : le pays cible a un identifiant d'environnement officiel et nommé.

---

## 5. Les opérations — 53 chemins exacts

*Toutes les listes ci-dessous ont été récupérées et recomptées par moi-même. JSON bruts archivés.*

### 5.1 API `collection` — base `https://sandbox.momodeveloper.mtn.com/collection` — **23 opérations**

```
POST   /v1_0/bc-authorize                                              bc-authorize
DELETE /v2_0/invoice/{referenceId}                                     CancelInvoice
DELETE /v1_0/preapproval/{preapprovalid}                               CancelPreApproval
POST   /token/                                                         CreateAccessToken
POST   /v2_0/invoice                                                   CreateInvoice
POST   /oauth2/token/                                                  CreateOauth2Token
POST   /v2_0/payment                                                   CreatePayments
GET    /v1_0/account/balance                                           GetAccountBalance
GET    /v1_0/account/balance/{currency}                                GetAccountBalanceInSpecificCurrency
GET    /v1_0/preapprovals/{accountHolderIdType}/{accountHolderId}      GetApprovedPreApprovals
GET    /v1_0/accountholder/{accountHolderIdType}/{accountHolderId}/basicuserinfo  GetBasicUserinfo
GET    /v2_0/invoice/{x-referenceId}                                   GetInvoiceStatus
GET    /v2_0/payment/{x-referenceId}                                   GetPaymentStatus
GET    /v2_0/preapproval/{referenceId}                                 GetPreApprovalStatus
GET    /oauth2/v1_0/userinfo                                           GetUserInfoWithConsent
POST   /v2_0/preapproval                                               PreApproval
POST   /v1_0/requesttopay                                              RequesttoPay
POST   /v1_0/requesttopay/{referenceId}/deliverynotification           RequesttoPayDeliveryNotification
GET    /v1_0/requesttopay/{referenceId}                                RequesttoPayTransactionStatus
GET    /v1_0/requesttowithdraw/{referenceId}                           RequestToWithdrawTransactionStatus
POST   /v1_0/requesttowithdraw                                         RequestToWithdraw-V1
POST   /v2_0/requesttowithdraw                                         RequestToWithdraw-V2
GET    /v1_0/accountholder/{accountHolderIdType}/{accountHolderId}/active  ValidateAccountHolderStatus
```

### 5.2 API `disbursement` — base `…/disbursement` — **16 opérations**

```
POST   /v1_0/bc-authorize          POST /token/          POST /oauth2/token/
POST   /v1_0/deposit  (Deposit-V1)                       POST /v2_0/deposit  (Deposit-V2)
GET    /v1_0/account/balance                             GET  /v1_0/account/balance/{currency}
GET    /v1_0/accountholder/{accountHolderIdType}/{accountHolderId}/basicuserinfo
GET    /v1_0/deposit/{referenceId}      GET /v1_0/refund/{referenceId}
GET    /v1_0/transfer/{referenceId}     GET /oauth2/v1_0/userinfo
POST   /v1_0/refund (V1)                POST /v2_0/refund (V2)
POST   /v1_0/transfer
GET    /v1_0/accountholder/{accountHolderIdType}/{accountHolderId}/active
```

### 5.3 API `remittance` — base `…/remittance` — **14 opérations**

Mêmes primitives, plus `POST /v2_0/cashtransfer` et `GET /v2_0/cashtransfer/{referenceId}`.

**Deux résidus de travaux internes, publiés par erreur** — *constatés personnellement, rapportés
tels quels sans interprétation* :

```
GET /clone-671b0/v1_0/accountholder/msisdn/{accountHolderMSISDN}/basicuserinfo   « GetBasicUserinfo (clone) »
GET /v1_0/accountholder/msisdn/999{accountHolderMSISDN}999/basicuserinfo         « GetBasicUserinfo-v3 »
```

Ce sont des observations utiles pour un SDET : elles signalent que le catalogue publié n'est pas
tenu au propre, donc qu'il peut contenir d'autres écarts entre le publié et l'implémenté.

### 5.4 API `sandbox-provisioning-api` — **3 opérations**

```
POST /v1_0/apiuser · GET /v1_0/apiuser/{X-Reference-Id} · POST /v1_0/apiuser/{X-Reference-Id}/apikey
```

### 5.5 Sémantique des verbes — **FACT**, verbatim

> « The API uses **POST, GET, PUT** methods. »
>
> « **POST** […] The request includes a reference id which is used to uniquely identify the specific
> resource that are created by the POST request. **If a POST is using a reference id that is already
> used, then a duplication error response will be sent to the client.** »
>
> « The POST is an **asynchronous** method. The Wallet Platform will validate the request […] and
> then answer with **HTTP 202 Accepted**. The created resource will get status **PENDING**. Once the
> request has been processed the status will be updated to **SUCCESSFUL** or **FAILED**. »
>
> « The **PUT** method is used by the Open API when sending callbacks. Callback is sent if a callback
> URL is included in the POST request. **The Wallet Platform will only send the callback once. There
> is no retry on the callback if the Partner system does not respond.** If the callback is not
> received, then the Partner system can use GET to validate the status. »

---

## 6. Objets, énumérations et idempotence

### 6.1 Corps de `POST /v1_0/requesttopay` — **FACT**, verbatim

```json
{
    "amount": "string",
    "currency": "string",
    "externalId": "string",
    "payer": { "partyIdType": "MSISDN", "partyId": "string" },
    "payerMessage": "string",
    "payeeNote": "string"
}
```

| Champ | Description officielle |
|---|---|
| `amount` | « Amount that will be debited from the payer account. » |
| `currency` | « **ISO4217 Currency** » |
| `externalId` | « External id is used as a reference to the transaction. External id is used for **reconciliation**. […] **External id is not required to be unique.** » |
| `payer` | « Party identifies a account holder in the wallet platform. […] **MSISDN** - Mobile Number validated according to **ITU-T E.164** […] **EMAIL** - Validated to be a valid e-mail format […] **PARTY_CODE** - UUID of the party. » |
| `payerMessage` / `payeeNote` | messages inscrits dans l'historique du payeur / du bénéficiaire |

**Point à ne pas rater** : `externalId` **n'est pas unique** et sert à la réconciliation, tandis que
`X-Reference-Id` **doit** être unique et porte l'idempotence. Deux références aux rôles opposés —
les confondre casse à la fois le rejeu et le rapprochement.

### 6.2 Énumérations publiées — *vérifiées personnellement dans le schéma archivé*

```
partyIdType     : ["MSISDN", "EMAIL", "PARTY_CODE"]
      variante  : ["MSISDN", "Email", "Alias", "ID"]
      variante  : ["msisdn", "email", "id", "alias"]
statut          : ["PENDING", "SUCCESSFUL", "FAILED"]
statut étendu   : ["CREATED", "PENDING", "SUCCESSFUL", "FAILED"]
préapprobation  : ["APPROVED", "CANCELLED", "EXPIRED", "REJECTED", "PENDING"]
fréquence       : ["DAILY", "MONTHLY", "WEEKLY"]
canal           : ["online", "offline"]
```

**Trois listes de `partyIdType` coexistent dans le même document de schéma**, avec des casses
incompatibles (`MSISDN` / `Email` / `msisdn`). Elles appartiennent à des opérations différentes.
**Je ne les harmonise pas** : c'est un CONFLIT interne à la source, et il devient un trou (§ 9).

### 6.3 Idempotence — **le mécanisme est explicite, et c'est rare**

**FACT** :
- « If a POST is using a reference id that is already used, then a duplication error response will
  be sent to the client. »
- Erreur normée : **HTTP 409 · `RESOURCE_ALREADY_EXIST`** — « Duplicated Reference ID. Every request
  must have a unique reference ID; using an ID of the previous request will result in this error
  response. » Action prescrite : « Check X-Reference ID used is unique and is in **UUID V4** format ».
- Bonnes pratiques officielles : « **Generate X-Reference-Id server-side using UUIDs** · Persist
  transaction state before initiating MoMo requests · **Never reuse X-Reference-Id across different
  operations** · Ensure retry logic is idempotent »
- Et cet avertissement, qui vaut consigne de test : « **Do not treat HTTP 202 Accepted as success** ·
  Always poll for final transaction status »

**Comparaison au socle** : `X-Reference-Id` joue exactement le rôle du `X-CorrelationID` GSMA
(UUID, rejet du doublon), sous un autre nom, et **MTN le rend obligatoire là où la GSMA le laisse
conditionnel**. C'est une divergence *par renforcement* — plus sûre que le standard.

---

## 7. Erreurs

### 7.1 Table « Common Error Codes » — *vérifiée personnellement dans le widget archivé*

| HTTP | Code | Description (verbatim) |
|---|---|---|
| 409 | `RESOURCE_ALREADY_EXIST` | Duplicated Reference ID. Every request must have a unique reference ID… |
| 401 | `ACCESS DENIED DUE TO INVALID SUBSCRIPTION KEY` | Authentication failed. Credentials invalid. Header Ocp-APIM-Subscription-Key value is incorrect. |
| 404 | `RESOURCE NOT FOUND` | Reference ID not found. Requested resource does not exist. Predominantly occurs with Get Status API… |
| 400 | `REQUEST REJECTED / BAD REQUEST` | Bad request. Request does not follow the specification. |
| 403 | `FORBIDDEN IP` | Authorization failed. IP not authorized to utilize Disbursement API. |
| 500 | `NOT_ALLOWED` | Authorization failed. User does not have permission… |
| 500 | `NOT_ALLOWED_TARGET_ENVIRONMENT` | Value passed in header X-Target-Environment is incorrect |
| 500 | `INVALID_CALLBACK_URL_HOST` | Callback URL with different host name to configured for API User. |
| 500 | `INVALID_CURRENCY` | Currency not supported on the requested account |
| 503 | `SERVICE_UNAVAILABLE` | Service temporary unavailable, try again later |

Sans code HTTP associé :
- `INTERNAL_PROCESSING_ERROR` — « Default or Generic error code used when there is no specific error
  mapping. **This predominantly occurs due to insufficient customer funds** to complete the
  transaction. »
- `PAYEE_NOT_FOUND` — « The MSISDN being paid to is invalid. » / « **MSISDN format must include
  country code.** MSISDN is not registered for Mobile Money Service. »
- `PAYER_NOT_FOUND` — « MSISDN of the number from whom the money was requested in invalid. »
- `COULD_NOT_PERFORM_TRANSACTION` — « transaction timeout […] **delay to approve a transaction
  within the given time frame (5 minutes)**. »

**Ces 5 minutes sont le seul délai chiffré publié par MTN.** À retenir pour la sandbox.

### 7.2 Énumération `ErrorReason` complète — *vérifiée personnellement, 17 valeurs*

```
PAYEE_NOT_FOUND · PAYER_NOT_FOUND · NOT_ALLOWED · NOT_ALLOWED_TARGET_ENVIRONMENT
INVALID_CALLBACK_URL_HOST · INVALID_CURRENCY · SERVICE_UNAVAILABLE · INTERNAL_PROCESSING_ERROR
NOT_ENOUGH_FUNDS · PAYER_LIMIT_REACHED · PAYEE_NOT_ALLOWED_TO_RECEIVE · PAYMENT_NOT_APPROVED
RESOURCE_NOT_FOUND · APPROVAL_REJECTED · EXPIRED · TRANSACTION_CANCELED · RESOURCE_ALREADY_EXIST
```

**Sept de ces valeurs n'apparaissent pas dans la page « Common Error Codes »** :
`NOT_ENOUGH_FUNDS`, `PAYER_LIMIT_REACHED`, `PAYEE_NOT_ALLOWED_TO_RECEIVE`, `PAYMENT_NOT_APPROVED`,
`APPROVAL_REJECTED`, `EXPIRED`, `TRANSACTION_CANCELED`.

**Observation de SDET, et elle a du prix** : `NOT_ENOUGH_FUNDS` **existe dans le schéma**, alors que
la page publique dit que l'insuffisance de fonds remonte en `INTERNAL_PROCESSING_ERROR`. Les deux
sources officielles se contredisent sur le cas de test le plus courant du mobile money. Consigné
comme CONFLIT, non arbitré (§ 9, T-MTN-02).

### 7.3 Causes de `400` énumérées — **FACT**, verbatim

> « Incorrect/wrong values in the headers, and/or the X-ref ID does not meet UUID Version 4 ·
> Inputting a Body in an API that is not supported e.g. /Token API · Having unsupported special
> characters in the Body request for example **an apostrophe (')** · Invalid currency - needs to
> match the target environment currency · **More than 160 characters in the note and message** ·
> The URL posted to needs to be reviewed e.g. incorrect number of forward slashes (///). »

L'apostrophe interdite et la limite de 160 caractères sont deux invariants directement testables.

---

## 8. La sandbox

**Elle existe et elle est documentée.** Hôte : `sandbox.momodeveloper.mtn.com`.

**FACT**, verbatim :

> « To facilitate testing a set of predefined users and Test accounts are provided. […] **A developer
> needs to Signup and Subscribe to a Product before accessing any of the APIs.** »
>
> « **Test Environment** — The Target Environment used in Testing is 'sandbox' »
> « **Test Currency** — The currency used in Sandbox is **EUR** »
> « The following Numbers are predefined with respective response for all Testcases. **Any other
> number results in Success.** »
> « **Only https is allowed on sandbox** » · « Allow **PUT & POST** on your callback listener host »
> « Existing Partner Accounts created on Partner GUI **can't be used** for testing the sandbox
> usecases. »

**La devise de sandbox est l'EUR, pas le XAF.** Conséquence directe pour FinZuu : un jeu de données
en XAF ne peut pas être rejoué tel quel contre la sandbox MTN.

**MSISDN de test publiés** — chaque numéro déclenche une erreur déterministe :

```
46733123450 PayerFailed          46733123451 PayerRejected        46733123452 PayerExpired
46733123453 PayerOngoing         46733123454 PayerDelayed         46733123455 PayerNotFound
46733123456 PayeeNotAllowedToReceive                              46733123457 PayerNotAllowed
46733123458 NotAllowedTargetEnvironment                           46733123459 InvalidCallbackUrlHost
46733123460 InvalidCurrency      46733123461 InternalProcessingError
46733123462 ServiceUnavailable   46733123463 CouldNotPerformTransaction
46733123464 TransfertypeUnknown
```

Emails de test : `notfound@`, `notactive@`, `notallowed@`, `notallowedtargetenvironment@`,
`internalprocessingerror@`, `serviceunavailable@` `email.com`. PartyCodes de test : six UUID
publiés. Refund : identifiants `1` à `13`.

**C'est un modèle à copier.** Ce mécanisme — un identifiant par cas d'erreur, tout le reste en
succès — est exactement ce que la sandbox FinZuu devrait offrir. C'est le meilleur apport
méthodologique de cette fiche, indépendamment d'Orange ou de Moov.

**Parcours d'intégration** *(vérifié personnellement, widget archivé)* : « Fork Collection · Create
Subscription Keys · Create API User and API Key · Get Access Token · Make your first MoMo API Call »,
via Postman. « On a successful call, the API returns a **202 Accepted** response code · Customer will
receive a **PIN** to approve the debit from their MoMo Wallet. »

**Contraintes de callback publiées** : HTTPS obligatoire sur le port 443, host = nom de domaine et
**jamais une IP**, autorités intermédiaires acceptées limitées à une liste (Amazon, DigiCert,
Let's Encrypt, Comodo, Certum, Entrust…).

---

## 9. Conformité au socle GSMA

**MTN ne revendique nulle part la conformité GSMA.** *Vérification : le mot « GSMA » n'apparaît
qu'une seule fois sur tout le portail, et c'est un prix — « NOMINATED — Best Mobile Innovation for
Emerging Markets — GSMA Global Mobile Award (GSMA) 2023 ».*

Ce que MTN revendique à la place, **FACT**, page *Introduction* :

> « **Use of REST architectural principles.** — Providing a set of **well-defined objects that are
> abstracted from the underlying object representations** held in the various mobile money systems
> […] — Creation of a **standard set of transaction types and other key enumerations**, removing the
> need for developers to map for each and every API implementation — **Use of ISO international
> standards** for enumerators such as currency and country codes […] — **Recognising that no common
> mobile money account identifier exists, use of a flexible construct** to enable the target
> account(s) and transaction parties to be identified using one or multiple identifier types. »

**Ce paragraphe est une reformulation quasi mot pour mot des principes de conception du socle GSMA**
(comparer au § 1 de `00_socle_gsma.md`). MTN a manifestement adopté la philosophie du standard sans
en revendiquer le label ni en reprendre les noms de champs. C'est le constat le plus intéressant de
cette fiche : **proximité d'esprit, divergence de lettre.**

Normes explicitement citées par MTN : **RFC 6749**, **RFC 6750**, **ISO 4217**, **ITU-T E.164**,
**UUID v4**.

| Réf. | Point de contrôle | Verdict | Fondement |
|---|---|---|---|
| G1 | Authentification | **DIVERGENT** | OAuth2 `client_credentials` + Bearer = conforme à l'esprit du socle. Mais deux étages (`Ocp-Apim-Subscription-Key` **+** API User/Key), sans équivalent GSMA. |
| G2 | URI et versionnage | **DIVERGENT** | `/{api}/v1_0/{ressource}` — pas de segment `mm`, versionnage `v1_0`/`v2_0` et non `X.Y.Z`. Deux versions coexistent par opération. |
| G3 | Identification des parties | **DIVERGENT** | `payer`/`payee` avec `{partyIdType, partyId}` — objet **unique**, là où GSMA impose un **tableau** de 1 à 10 identifiants. Modèle plus simple, donc plus pauvre. |
| G4 | Format MSISDN | **DIVERGENT** | ITU-T E.164 avec indicatif pays **obligatoire** (« MSISDN format must include country code ») — plus strict que les « 6 à 15 chiffres, `+` toléré » du socle. |
| G5 | Montant | **CONFORME** | `amount` string + `currency` ISO 4217 séparé. Décimales et bornes non publiées. |
| G6 | Références | **DIVERGENT** | `X-Reference-Id` (unique, en-tête) et `externalId` (non unique, corps, réconciliation) au lieu de `transactionReference` / `requestingOrganisationTransactionReference`. Rôles équivalents, noms et emplacements différents. |
| G7 | Types de transaction | **DIVERGENT** | Pas de champ `type` : le type est porté par la **route** (`requesttopay`, `transfer`, `deposit`, `refund`, `cashtransfer`). Aucun des 9 codes GSMA. |
| G8 | **Idempotence** | **CONFORME (renforcé)** | `X-Reference-Id` UUID v4, **obligatoire**, rejet 409 `RESOURCE_ALREADY_EXIST`. Le socle laisse `X-CorrelationID` conditionnel : MTN est plus strict. |
| G9 | Récupération de réponse perdue | **DIVERGENT** | Pas de `/responses`. La doctrine officielle est le polling `GET /{ressource}/{referenceId}`, explicitement recommandé puisque le callback n'est jamais rejoué. |
| G10 | Notification asynchrone | **DIVERGENT** | `X-Callback-Url` (casse différente du `X-Callback-URL` GSMA). **Envoi unique, aucun rejeu** — le socle ne se prononce pas (T-SOCLE-08), MTN tranche, et tranche sévèrement. |
| G11 | Objet d'erreur | **DIVERGENT** | `{ "code": …, "message": … }` au lieu de `errorCategory`/`errorCode`/`errorDescription`. Pas de catégorie. |
| G12 | Catalogue d'erreurs | **DIVERGENT** | 17 `ErrorReason` publiés contre 30 codes GSMA. Recouvrement conceptuel réel (`NOT_ENOUGH_FUNDS` ≈ `InsufficientFunds`, `RESOURCE_ALREADY_EXIST` ≈ `DuplicateRequest`, `INVALID_CURRENCY` ≈ `CurrencyNotSupported`) mais aucun nom commun. |
| G13 | Cycle de vie de la requête | **DIVERGENT** | Pas d'objet `RequestState`. Le 202 + statut `PENDING` porté par la ressource elle-même tient le même rôle. Valeurs `PENDING`/`SUCCESSFUL`/`FAILED` ≠ `pending`/`completed`/`failed` (casse et vocabulaire). |
| G14 | Cycle de vie de la transaction | **DIVERGENT — et mieux que le socle** | `PENDING` → `SUCCESSFUL` \| `FAILED`, énuméré et documenté. **La GSMA ne normalise pas ce cycle (T-SOCLE-01) : MTN comble le trou du standard.** |
| G15 | Traitement par lot | **NON DOCUMENTÉ** | Aucune API de lot publiée. « Bulk » n'existe pas côté MoMo API. |
| G16 | Solde et statut de compte | **CONFORME** | `GET /v1_0/account/balance`, `/balance/{currency}`, `/accountholder/{type}/{id}/active` — équivalents fonctionnels de F5/F6 du socle. |
| G17 | Cotation / frais | **NON DOCUMENTÉ** | Aucune API de quotation. |
| G18 | Contrepassation | **DIVERGENT** | `POST /v1_0/refund` et `/v2_0/refund` (disbursement uniquement), pas de `reversals` sur la transaction d'origine. Remboursement partiel non documenté. |
| G19 | Pagination | **NON DOCUMENTÉ** | Aucune collection paginée publiée. |
| G20 | Canal d'origine | **DIVERGENT** | Pas de `X-Channel`. Énumération `["online","offline"]` dans le schéma, portée non documentée. |
| G21 | Supervision | **NON DOCUMENTÉ** | Aucun `/heartbeat`. |
| G22 | Sandbox et limites | **CONFORME (hors socle)** | Documentée, avec numéros de test déterministes, devise EUR et contraintes de callback (§ 8). Quotas chiffrés non publiés. |

**Synthèse : 4 CONFORME · 13 DIVERGENT · 5 NON DOCUMENTÉ.**

C'est de loin le meilleur score du référentiel — et surtout, **les DIVERGENT sont ici des
divergences renseignées**, pas des trous. On sait *en quoi* MTN diffère, ce qui est exactement ce
qu'un profil opérateur a besoin de savoir.

---

## 10. TROUS À CALIBRER

| # | Trou | Ce qui manque exactement | Impact sur la sandbox | Comment le lever |
|---|---|---|---|---|
| **T-MTN-01** | **CONFLIT : le verbe du callback** | La page *API User and Key Management* dit « **The PUT method** is used […] when sending callbacks » ; la page *Callback* dit « The callback will be a **POST** request ». Les deux sont officielles. Les deux pages disent par ailleurs « Allow **PUT & POST** on your callback listener host ». | Le récepteur de la sandbox doit choisir — ou accepter les deux, ce que MTN semble d'ailleurs recommander. | Question au support MTN. **Non arbitré.** |
| **T-MTN-02** | **CONFLIT : l'insuffisance de fonds** | Le schéma publie `NOT_ENOUGH_FUNDS` ; la page publique dit que ce cas remonte en `INTERNAL_PROCESSING_ERROR`. | C'est le scénario d'erreur le plus fréquent du mobile money. Deux oracles contradictoires. | Idem. **Non arbitré.** |
| **T-MTN-03** | **CONFLIT : trois `partyIdType`** | `["MSISDN","EMAIL","PARTY_CODE"]`, `["MSISDN","Email","Alias","ID"]`, `["msisdn","email","id","alias"]` coexistent dans le même schéma. | Validation d'entrée arbitraire ; sensibilité à la casse non tranchée. | Idem. **Non arbitré.** |
| **T-MTN-04** | **URL de base de la PRODUCTION** | INTROUVABLE. Seuls `sandbox.momodeveloper.mtn.com` (API) et `momoapi.mtn.com/profile` (portail de profil) sont publiés. **L'hôte de la passerelle de production n'apparaît nulle part.** | Le profil ne peut pas viser la production. | Souscription / support MTN. |
| **T-MTN-05** | **Spécification machine vide** | `paths: {}` dans tous les exports anonymes (§ 2). | Pas de validation automatique de schéma. Contourné ici par l'API de contenu, mais fragile. | Compte développeur. |
| **T-MTN-06** | **Quotas, rate limits, plafonds** | INTROUVABLE. Aucune valeur chiffrée. Durée de vie du token : « The received token has an expiry time », **sans valeur**. | Impossible de simuler les limites ni l'expiration du jeton. | Idem. |
| **T-MTN-07** | **Signature / vérification du callback** | Aucun HMAC, aucune signature d'en-tête. La seule protection publiée est TLS + liste d'autorités + host = domaine. Combiné à l'envoi unique sans rejeu, **le callback n'est pas authentifié**. | Décision de sécurité à prendre pour la sandbox. **Trou le plus sensible.** | Idem. |
| **T-MTN-08** | **Bornes du montant** | Décimales, minimum, maximum, arrondi en XAF : non publiés. | Tests aux limites sans oracle. | Idem. |
| **T-MTN-09** | **Produit « Collection Widget » / MoMoPay** | La page `/widget-api` existe mais son corps est vide pour un visiteur anonyme. Aucun code d'erreur widget. | Le canal QR/USSD n'est pas modélisable. | Compte développeur. |
| **T-MTN-10** | **Résidus du catalogue** | `clone-671b0` et `999{msisdn}999` publiés dans `remittance` (§ 5.3). | Signale que le catalogue publié n'est pas fiable à 100 % — d'autres écarts publié/implémenté sont possibles. | Vérification à la souscription. |
| **T-MTN-11** | **Devise de sandbox = EUR** | Fait établi, pas un trou d'information — mais un trou d'usage. | **Aucun jeu de test XAF n'est rejouable tel quel** contre la sandbox MTN. | Décision FinZuu sur la stratégie de jeux de données. |

**Aucun de ces trous n'empêche d'écrire un profil MTN.** Onze trous sur une base de 53 opérations
documentées, c'est une situation de travail normale — à l'opposé d'Orange et de Moov.

---

## 11. Sources archivées

Dans `docs/contrats/sources/mtn-momo/` — **toutes récupérées par mes soins le 2026-09-03** :

| Fichier | Contenu |
|---|---|
| `operations_collection_2026-09-03.json` | 23 opérations, brut |
| `operations_disbursement_2026-09-03.json` | 16 opérations, brut |
| `operations_remittance_2026-09-03.json` | 14 opérations, brut (résidus inclus) |
| `schema_collection_668d4753_2026-09-03.json` | schéma OpenAPI : 8 énumérations, dont `ErrorReason` (17 valeurs) |
| `products_2026-09-03.json` | 4 produits et leurs `terms` |
| `widget_common-error_ohu47_2026-09-03.html` | table des codes d'erreur, texte source |
| `widget_get-started_ht0i6_2026-09-03.html` | parcours d'intégration, texte source |
| `NOTES_VERIFICATION.txt` | ce qui a été mesuré, et la frontière API-de-contenu / API-MoMo |

---

## 12. Niveau de confiance pour le futur profil opérateur

**HAUT.**

C'est le seul opérateur du référentiel pour lequel un profil peut être écrit **sans rien inventer** :
53 chemins exacts, les verbes, les en-têtes obligatoires, le mécanisme d'idempotence et sa sanction,
les statuts de transaction énumérés, 17 codes d'erreur, l'identifiant de pays `mtncameroon`, une
sandbox avec des numéros de test déterministes.

Les trois réserves à porter au profil : le **verbe du callback** est ambigu (accepter PUT *et* POST
est la lecture prudente et conforme à la recommandation de MTN), **l'insuffisance de fonds** a deux
codes contradictoires (prévoir les deux), et **la production reste hors d'atteinte** — le profil
décrira la sandbox, pas la production, jusqu'à souscription.

Et une recommandation qui dépasse MTN : **le mécanisme des MSISDN de test déterministes (§ 8) doit
être repris tel quel dans la sandbox FinZuu**, quel que soit l'opérateur simulé. C'est la meilleure
idée d'ingénierie rencontrée dans tout ce référentiel.
