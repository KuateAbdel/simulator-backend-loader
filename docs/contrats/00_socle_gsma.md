# Socle commun — le standard GSMA Mobile Money API

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Référentiel des contrats opérateurs · Document T1
**Rédigé le** 2026-09-03 · **Auteur** Kuate Abdel Yaniv (QA Lead / SDET)
**Nature** 100 % documentaire. Aucun appel d'API, aucune inscription, aucun compte créé.

---

## 0. Ce que ce document est, et ce qu'il n'est pas

**C'est** l'étalon. Le standard GSMA est la seule grammaire de mobile money qui soit publique,
versionnée et commune à plusieurs opérateurs. Les cinq fiches opérateur (`orange-money.md`,
`mtn-momo.md`, `moov-money.md`, `airtel-money.md`, `areeba.md`) mesurent chacune leur écart
**par rapport à ce document-ci**, jamais l'une par rapport à l'autre.

**Ce n'en est pas** une description de ce que font les opérateurs. Aucun opérateur d'Afrique
centrale n'est ici présumé conforme. Le fait qu'une notion existe dans le socle ne permet
**jamais** d'affirmer qu'elle existe chez un opérateur : c'est précisément l'erreur que le
référentiel doit empêcher.

### Sources primaires consultées

| # | Document | URL | Consulté le | Nature |
|---|---|---|---|---|
| S1 | Mobile Money API — Getting Started (API Fundamentals, comportement, erreurs) | `https://developer.mobilemoneyapi.io/api-versions-1.2/get-started.html` | 2026-09-03 | **OFFICIELLE** (GSMA) |
| S2 | Mobile Money API — API Service Definition (objets, chemins, énumérations) | `https://developer.mobilemoneyapi.io/api-versions-1.2/resources/api-service-definition.html` | 2026-09-03 | **OFFICIELLE** (GSMA) |
| S3 | Portail développeur — racine et index des versions | `https://developer.mobilemoneyapi.io/` · `/api-versions-1.2/` | 2026-09-03 | **OFFICIELLE** (GSMA) |

Les pages S1 et S2 sont archivées telles que servies dans
`docs/contrats/sources/gsma/` (HTML brut + extraction texte), avec leurs empreintes :

- `mmapi-1.2_api-service-definition.html` — md5 `3b9b90192f2a02c0a92154943e75bedb` — 250 561 o
- `mmapi-1.2_get-started.html` — md5 `82beee6790a155ff2d29fb79e91ef112` — 90 653 o

Mention légale portée en pied de ces deux pages : « Copyright © 2024 GSMA ».
**DÉDUIT** : le contenu de la version 1.2 n'a pas été retouché depuis 2024.

### Ce que je n'ai pas pu consulter

- **Le fichier OpenAPI (OAS3) lui-même.** La page `/api-versions-1.2/resources/open-oas3-ui.html`
  a bien répondu HTTP 200 (32 253 o), mais c'est une coquille VuePress : le contenu du visualiseur
  est chargé par JavaScript et **aucune URL de fichier `.yaml`/`.json` n'y figure**. Récupérer la
  spécification machine exigerait soit l'exécution du JS, soit l'inscription au portail — les deux
  hors périmètre de cette mission. → **INTROUVABLE en accès anonyme.**
- **Le document « Mobile Money API Security Design »**, cité par S1 (§ *HTTP Header Information*)
  comme la référence des en-têtes de sécurité. Non atteint sans inscription. → **INTROUVABLE.**
- **Les collections Postman, le simulateur GSMA et les SDK**, annoncés sur S3 : l'accès au tableau
  de bord développeur demande une inscription, que la mission interdit. → **NON CONSULTÉ** (et non
  « inexistant » : la distinction compte).

### Convention de lecture des tableaux d'objets

S1 (§ *API Endpoints*) définit une notation d'optionalité que je reprends telle quelle dans tout
ce document. **FACT**, citation :

> « → Request optionality ← Response optionality · **O** Field is optional · **M** Field is
> mandatory · **C** Field is conditional · **NA** Field does not need to be supplied. If supplied,
> it will be ignored. »

Donc `→ M ← O` se lit : *obligatoire en requête, facultatif en réponse*.
Autre règle générale, **FACT** : « string fields have a default maximum length of 256 characters
unless specified otherwise ».

---

## 1. Ce que la MM API est, en trois phrases

C'est un **dictionnaire commun**. Chaque opérateur de mobile money a inventé ses propres mots pour
dire « débiter Untel de 500 F » ; la GSMA a écrit une fois pour toutes comment on l'écrit, pour
qu'un développeur n'ait pas à réapprendre à parler à chaque frontière.

La forme est banale et c'est voulu : du REST, du JSON, des noms de ressources au pluriel
(`/transactions`, `/accounts`, `/quotations`), trois verbes seulement.
**FACT** (S1, § *Methods*) : « POST. Used to create a resource · PATCH. Used to update a resource ·
GET. Used to return a representation of a resource or a collection of resources. »
Aucun `PUT` et aucun `DELETE` côté client — le `PUT` est réservé au sens inverse (§ 2.5).

Le format d'URI est normé, **FACT** (S1, § *URI*) : `{…]/{version}/mm/{Resource}`, où « `…` is
defined upon implementation of the API by the API provider », `mm` est littéral, et `{version}`
suit `X.Y.Z`. **DÉDUIT** : la GSMA ne normalise donc **ni le nom d'hôte, ni le préfixe de chemin** —
seulement la queue de l'URI. Deux implémentations conformes peuvent avoir des URLs entièrement
différentes ; c'est attendu, ce n'est pas une divergence.

---

## 2. Les objets du vocabulaire

### 2.1 Party — l'identification des deux côtés d'un mouvement

Il n'existe **pas** d'objet nommé `party`. Le standard nomme les deux extrémités d'un mouvement
`debitParty` et `creditParty`, et chacune est un **tableau de couples clé/valeur**, pas une chaîne.
**FACT** (S2, *Transaction Object Definition*) :

| Champ | Type | Optionalité | Règle citée |
|---|---|---|---|
| `creditParty` | array | `→ C ← C` | « creditParty must be supplied if debitParty is omitted. If debitParty is supplied, then creditParty is optional. » |
| `debitParty` | array | `→ C ← C` | « debitParty must be supplied if creditParty is omitted. If creditParty is supplied, then debitParty is optional. » |

Cardinalité, **FACT** (S2, *Transaction UML Class Diagram*) :
`Credit Party Identifier "1..10" --* "1" Transaction` — de 1 à 10 identifiants par partie.

**Le point qui compte, et qu'on rate facilement** : la conditionnalité croisée signifie qu'une
transaction GSMA-conforme peut légalement n'avoir **qu'un seul côté explicite**. L'autre est alors
implicite — typiquement le compte du client API lui-même. **DÉDUIT** : un simulateur qui exige
systématiquement les deux parties est *plus strict* que le standard, ce qui est un écart réel même
s'il paraît anodin ; il refusera des requêtes qu'un opérateur conforme accepte.

Les clés admises sont énumérées (S2, § *Account Identifiers*) — **FACT**, liste intégrale des
21 codes : `accountcategory`, `bankaccountno`, `accountrank`, `identityalias`, `iban`, `accountid`,
`msisdn`, `swiftbic`, `sortcode`, `organisationid`, `username`, `walletid`, `linkref`, `consumerno`,
`serviceprovider`, `storeid`, `bankname`, `bankaccounttitle`, `emailaddress`, `mandatereference`.

La seule dont le **format** soit normé est le MSISDN. **FACT** :
> « Must contain between 6 and 15 consecutive digits >First character can contain a ‘+’ or digit
> >Can contain spaces. »

C'est une définition très permissive : elle **n'impose ni indicatif pays, ni longueur fixe, ni
absence d'espaces**. Toute contrainte plus serrée chez un opérateur (« 237 obligatoire », « 9
chiffres exactement ») est une **divergence par restriction**, à consigner comme telle.

Le ciblage d'un compte dans le chemin d'URL a deux formes, **FACT** (S2, § *Identifying a Target
Account*) :
- un seul identifiant : `/accounts/{identifierType}/{identifier}`
- plusieurs : `/accounts/{id1}@{val1}${id2}@{val2}${id3}@{val3}`, « The path uses a `$` delimiter to
  separate each identifier, up to a limit of three account identifiers. Each key/value is delimited
  by `@` ».

### 2.2 Amount et currency — deux champs, jamais un seul

**FACT** (S2) : `amount` est de type **`string`**, pas un nombre ; `currency` est un champ séparé,
`Enumeration = ISO Currency Codes`, c'est-à-dire le code alphabétique à trois lettres d'ISO 4217.

Les règles de validation du montant sont explicites et communes à *tous* les champs monétaires
(`amount`, `amountDue`, `feeAmount`, `commissionAmount`, `currentBalance`, `fxRate`…).
**FACT** (S1, § *Amount Validation*), citation intégrale :

> « Between zero and four decimal places can be supplied. · Leading zeroes are not permitted except
> where the value is less than 1. For any value less than one, one and only one leading zero must be
> supplied. · Trailing zeroes are permitted. · Negative values are not permitted. · Maximum value
> that can be supplied is 999999999999999999.9999. »

La table d'exemples fournie par la GSMA est un jeu de tests prêt à l'emploi — je la recopie telle
quelle parce qu'elle vaut une batterie :

| Valeur | Admise ? | | Valeur | Admise ? |
|---|---|---|---|---|
| `5` | oui | | `-5.5` | **non** |
| `5.0` | oui | | `0.5` | oui |
| `5.` | **non** | | `.5` | **non** |
| `5.00` | oui | | `00.5` | **non** |
| `5.5` / `5.50` | oui | | `0` | oui |
| `5.5555` | oui | | `00.00` | **non** |
| `5.55555` | **non** | | `0.00` | oui |
| `555555555555555555` | oui | | `0000001.32` | **non** |
| `5555555555555555555` | **non** | | | |

**DÉDUIT, et important pour la sandbox** : le montant étant une *chaîne*, `"5.00"` et `"5"` sont
deux représentations distinctes du même montant, toutes deux valides. Un contrôle d'idempotence ou
de rapprochement qui compare les payloads octet à octet les traitera comme différents. Le standard
ne dit nulle part comment normaliser ; c'est un trou (§ 8).

`fxRate` fait exception à la règle des 4 décimales — **FACT** : « Note 10 decimal places supported ».

### 2.3 Transaction — l'objet central

**FACT** (S2, § *Transactions API*) : « The Transactions APIs are used to support mobile money
financial transaction use cases. Transactions are used for a wide range of use cases including
merchant payments, international transfers, domestic transfers, and agent cash-in/cash-out. »

Chemins, **FACT** :

| Opération | Chemin |
|---|---|
| Créer | `POST /transactions/type/{transactiontype}` |
| Consulter | `GET /transactions/{transactionReference}` |
| Mettre à jour | `PATCH /transactions/{transactionReference}` — « To update the transactionStatus of a transaction. » |
| Contrepasser | `POST /transactions/{originalTransactionReference}/reversals` |

Champs obligatoires en création (`→ M`), **FACT** : `type`, `amount`, `currency` — et *rien
d'autre*. Tout le reste est optionnel ou conditionnel. Les champs renseignés par le fournisseur et
jamais par le client (`→ NA ← M`) : `transactionReference`, `transactionStatus`.

Deux références coexistent et il ne faut pas les confondre :

| Champ | Qui l'écrit | Rôle |
|---|---|---|
| `transactionReference` | le **fournisseur** (`→ NA ← M`) | « Unique reference for the transaction. This is returned in the response by API provider. » |
| `requestingOrganisationTransactionReference` | le **client** (`→ O ← O`) | « A reference provided by the requesting organisation that is to be associated with the transaction. » |
| `transactionReceipt` | le fournisseur (`→ NA ← O`) | « Transaction receipt number as notified to the parties. **This may differ from the Transaction Reference.** » |

**DÉDUIT** : trois identifiants distincts peuvent désigner un même mouvement. Un rapprochement
qui n'en suit qu'un seul se trompera de clé tôt ou tard.

Le type est énuméré. **FACT** (S2, § *Transaction Types*) — les 9 codes, intégralement :

| Code | Description (citation) |
|---|---|
| `billpay` | « Payment of bill from a business for goods and/or services. » |
| `deposit` | « Exchange of cash in return for e-Money at a physical agent or via ATM. » |
| `disbursement` | « Disbursement of funds (making payments from an organisation (business, NGO, government entity) to a mobile money recipient. » |
| `transfer` | « Transfer of funds between mobile money provider and another provider or financial institution in the same country. » |
| `merchantpay` | « Purchases of goods and/or services from shops (payer present) or online (payer not present). » |
| `inttransfer` | « Transfer of funds to a recipient in another country… » |
| `adjustment` | « General adjustments to an account via an adjustment transaction (e.g. refunds). » |
| `reversal` | « Reversal of a prior transaction to return funds to the payer. » |
| `withdrawal` | « Exchange of e-Money in return for cash at a physical agent or via ATM. » |

Sur l'objet `Reversal`, restriction, **FACT** : « Note that only Reversals and Refunds (adjustments)
are supported » — donc `type` ∈ {`reversal`, `adjustment`} sur ce chemin. Et un avertissement que
la sandbox devra reproduire, **FACT** :

> « For a partial reversal, the amount needs to be supplied. It should be noted that **some API
> providers do not support partial reversals and will return an error** if a partial amount is
> supplied. »

Enfin, casse : **FACT** (S1, § *Case Sensitivity*) « All API properties are defined in camelCase
format. All enumeration values referenced within the API use lower case notation – this includes
acronyms and abbreviations », à deux exceptions près : les codes ISO (pays, devise) et les codes
d'erreur, qui sont en CamelCase.

### 2.4 La référence d'idempotence — `X-CorrelationID`

C'est le point le plus mal compris du standard, donc je le cite avant de commenter.
**FACT** (S1, § *Client Correlation ID*) :

> « A client correlation id can be supplied by the API client on HTTP POST and PATCH requests. The
> client correlation id is a **UUID** that enables the client to correlate the API request with the
> resource created/updated by the provider. The client correlation id is specified in the HTTP
> Request Header. When a provider issues a callback, the provider should ensure that the original
> correlation id provided by the client is placed in request header.
>
> The client correlation ID **supports safe operations. A POST request that is submitted with a
> correlation ID that has already been supplied will be rejected as unsafe, thus avoiding
> transaction duplication.** »

En-tête, **FACT** (S1, § *Custom Request Headers*) : `X-CorrelationID` · valeur `UUID` ·
optionalité **`Conditional`**.

Quatre observations, dont trois sont des pièges :

1. **Il n'existe pas d'en-tête `Idempotency-Key` dans ce standard.** Le rôle est tenu par
   `X-CorrelationID`. Chercher `Idempotency-Key` chez un opérateur et conclure « non idempotent »
   serait une erreur de lecture.
2. **L'en-tête est *conditionnel*, pas obligatoire.** Le standard ne dit nulle part quelle est la
   condition. **DÉDUIT** : un fournisseur peut être conforme tout en n'exigeant jamais cet en-tête —
   et donc en n'offrant aucune protection contre le double envoi. La protection anti-doublon du
   standard est **facultative pour le fournisseur et à la main du client**.
3. **La sanction du doublon est nommée** : `BusinessRule` / `DuplicateRequest`, HTTP 400 — « The
   request has previously been processed, i.e. this request is a duplicate and hence has been
   rejected. » (**FACT**, S1, § *API Error Codes*). C'est le comportement à attendre d'un rejeu, et
   c'est vérifiable.
4. **La rémanence n'est pas spécifiée.** Combien de temps un `X-CorrelationID` reste-t-il « déjà
   vu » ? Le standard est muet. → trou (§ 8).

Le pendant de l'idempotence est la **récupération d'une réponse perdue**, **FACT** (S1, § *Missing
Response Retrieval*) :

> « In some circumstances, the client may not have received the final representation of the resource
> for which it attempted to create. For example, a proxy server issue may have resulted in a HTTP
> 5xx response but the provider may have actually successfully completed the request. The
> `/responses` API allows a client to identify and retrieve the final representation of the
> resource… the client issues a `GET /Responses/{clientCorrelationId}`. The provider will then match
> the client correlation id to the appropriate resource and return a link to that resource. If the
> resource is not found for the given correlation id then a HTTP 404 will be returned. »

L'objet retourné n'a qu'un champ, **FACT** : `link` (string, `→ NA ← M`), « Provides a URL to the
resource associated with the given correlation ID ».

**Note de lecture** : la casse du chemin est incohérente dans la source elle-même — `/responses`
dans le texte, `/Responses/{clientCorrelationId}` dans la phrase suivante. Consigné tel quel, non
arbitré.

### 2.5 Le callback — `X-Callback-URL`, et un `PUT` dans l'autre sens

Le standard définit deux régimes, **FACT** (S1, § *Use Case Flow Patterns*) :

> « **Synchronous Flow**. The final resource is always provided in response to an API request. There
> is no interim response. Can be used with POST, PATCH and GET requests.
> **Asynchronous Flow**. An interim response is always provided in response to an API request in the
> form of a Request State object. The final response is then provided via a callback or
> alternatively can be accessed via polling on Request State. Can be used with POST and PATCH
> requests. »

En asynchrone, deux mécanismes exclusifs. **FACT** (S1, § *Request State Object*) :

> « **Callback**. A request is initiated via a HTTP POST or PATCH request with an intermediate
> response represented by a Request State object. Once the request has been completed, **the
> provider will initiate a PUT request to the URL specified by the client in the `X-Callback-URL`
> request header**. The callback will provide the client with one of the following: Final
> representation of the resource for successful creation requests · A `{"result": "success"}`
> response for successful update requests
>
> **Polling**. A request is initiated via a HTTP POST or PATCH request with an intermediate response
> provided in the form of the Request State object. A HTTP GET is then issued against
> `/requeststate` by the client at intervals until the final resource state and resource reference
> is returned. »

Points à retenir :

- **Le verbe du callback est `PUT`.** Vérifié trois fois dans la source : la phrase ci-dessus, et
  les figures 3 et 5 (« Provider->>Client: HTTP PUT Request »). C'est le seul emploi de `PUT` du
  standard, et il va **du fournisseur vers le client**.
- **Le client répond `204`** au callback (figures 3 et 5 : « Client--)Provider: HTTP 204 Resposne »
  — coquille dans l'original, recopiée telle quelle).
- **En cas d'échec du traitement, le callback transporte l'objet d'erreur**, pas un code HTTP
  d'erreur (fig. 3 : « Provider->>Client: HTTP PUT Request, Error Object is Returned »).
- `X-Callback-URL` est **`Conditional`**, avec cette réserve, **FACT** : « Will only be used by the
  API provider **if they have implemented the Callback method**. » → **DÉDUIT** : un fournisseur
  conforme peut n'offrir que le polling. Ne jamais présumer du callback.

L'objet `RequestState` — pivot de tout l'asynchrone. **FACT** (S1) :

| Champ | Type | Optionalité | Validation / description |
|---|---|---|---|
| `serverCorrelationId` | string | `→ NA ← M` | UUID. « enable the client to identify the RequestState resource on subsequent polling requests » |
| `objectReference` | string | `→ NA ← O` | « Provides a reference to the subject resource, e.g. transaction reference. » |
| `status` | string | `→ NA ← M` | **`Enumeration = pending, completed, failed`** |
| `notificationMethod` | date-time *(sic)* | `→ NA ← M` | **`Enumeration = callback, polling`** |
| `pendingReason` | string | `→ NA ← O` | raison textuelle d'un `pending` |
| `expiryTime` | date-time | `→ NA ← O` | « the time by which the provider will fail the request if completion criteria have not been met » |
| `pollLimit` | integer | `→ NA ← O` | « the number of poll attempts… that will be allowed by the provider » |
| `errorReference` | object | `→ NA ← O` | objet `Errors` si l'asynchrone a échoué |

Le type déclaré de `notificationMethod` est **`date-time` alors que la valeur est une énumération de
chaînes** : erreur manifeste de la spécification, recopiée ici telle quelle et non corrigée.

Noter aussi qu'il y a **deux corrélateurs** : `X-CorrelationID` (posé par le client, sert
l'idempotence et `/responses`) et `serverCorrelationId` (posé par le fournisseur, sert le polling).
Les confondre casse le suivi.

### 2.6 L'objet d'erreur

**FACT** (S1, § *Errors Object Definition*) :

| Champ | Type | Optionalité | Validation |
|---|---|---|---|
| `errorCategory` | string | `→ M ← M` | `Enumeration = Errors Categories` |
| `errorCode` | string | `→ M ← M` | `Enumeration = Errors Codes` |
| `errorDescription` | string | `→ O ← O` | |
| `errorDateTime` | date-time | `→ O ← O` | |
| `errorParameters` | array | `→ O ← O` | couples clé/valeur, **max 20** |

Avertissement de la GSMA elle-même, **FACT** : « With the `errorParameters` property, care should be
taken regarding confidentially of information. Confidential parameter information should only be
disclosed to trusted clients. » — et sur le code générique : « The API Provider wishes to avoid
disclosure of confidential information… For example, the fact that a customer has breached their
monthly transaction limit may not be disclosed to specific clients. »

**DÉDUIT** : le standard *prévoit et légitime* qu'un fournisseur réponde `GenericError` là où il
connaît la cause exacte. Un opérateur avare en détail d'erreur n'est donc pas nécessairement
non-conforme.

---

## 3. Les cycles de vie

C'est ici que se trouve la découverte la plus importante de ce document, et elle est négative.

### 3.1 Cycle de vie de la *requête* — `requestState.status`

**FACT** : `Enumeration = pending, completed, failed`. Trois états, terminaux `completed` et
`failed`. C'est le seul cycle de vie pleinement normé du standard.

### 3.2 Cycle de vie d'un *lot* — `batchStatus`

**FACT** (S2, *Batch Transaction Object Definition*) : `Enumeration = created, approved, completed`.

Les deux modes de traitement sont décrits pas à pas (S2, § *Batch Transactions Workflow*) :

- **One-shot, sans approbateur** : `POST /batchtransactions` → le fournisseur analyse → « Once
  parsing has completed, the API provider will set the batch status… to ‘**completed**’ ».
- **Maker/checker** : `POST /batchtransactions` → « …will set the batch status… to ‘**created**’ »
  → `PATCH /batchtransactions` pour passer à ‘**approved**’ → le fournisseur poste les transactions
  « considering any scheduling considerations » → ‘**completed**’.

**Ce passage est directement transposable au module Bulk de la plateforme FinZuu** : la
distinction maker/checker, l'état intermédiaire `approved`, la séparation entre *analyse* et
*exécution*, et les deux collections de résultats (`/rejections`, `/completions`) sont exactement
les notions que le module Bulk ne matérialise pas aujourd'hui. Rapprochement à faire, hors
périmètre de la présente mission.

Plafond, **FACT** : « There is a limit of 999,999 transaction records per batch. »

### 3.3 Cycle de vie d'une *transaction* — **NON ÉNUMÉRÉ**

`transactionStatus` est déclaré `→ NA ← M`, donc **obligatoire dans toute réponse**, avec pour seule
description : « Indicates the status of the transaction as stored by the API provider. »
(**FACT**, S2, *Transaction Object Definition*).

**Aucune énumération n'est associée à ce champ nulle part dans S1 ni S2.** Vérifié par recherche
exhaustive du terme `transactionStatus` sur les 1 019 lignes de la définition de service : il
apparaît dans l'objet Transaction, l'objet Reversal, l'objet Statement Entry et comme paramètre de
filtre de `GET /accounts/…/transactions` — **jamais avec une liste de valeurs**.

C'est un fait considérable et contre-intuitif : **le standard GSMA normalise le cycle de vie de la
requête et celui du lot, mais pas celui de la transaction elle-même.** Les valeurs `pending` /
`completed` / `failed` que l'on croise partout appartiennent à `requestState.status`, pas à
`transactionStatus`. Les attribuer à la transaction serait une extrapolation — précisément ce que
la mission interdit.

**Conséquence directe pour la sandbox** : les statuts de transaction sont un point de **divergence
garantie** entre opérateurs. Aucun profil opérateur ne pourra s'appuyer sur le socle ici ; chacun
devra être calibré à la source, et à défaut de source, déclaré INTROUVABLE.

### 3.4 Les autres états, tous énumérés (utiles comme repères)

| Objet | Champ | Énumération (**FACT**) |
|---|---|---|
| Account / Account Status / Balance | `accountStatus` | `available`, `unavailable`, `unregistered` |
| Bill | `billStatus` | `paid`, `unpaid`, `partialpaid` |
| Bill Payment | `paymentType` | `fullpayment`, `partialpayment` |
| Authorisation Code | `codeState` | `active`, `expired`, `cancelled` |
| Authorisation Code | `amountType` | `exact`, `maximum` |
| Debit Mandate | `mandateStatus` | `active`, `inactive` |
| Link | `status` / `mode` | `active`, `inactive` / `push`, `pull`, `both` |
| Identity | `kycVerificationStatus` | `verified`, `unverified`, `rejected` |
| Identity | `accountRelationship` | `accountholder` |
| Heartbeat | `serviceStatus` | `available`, `unavailable`, `degraded` |
| Requesting Organisation | `requestingOrganisationIdentifierType` | `swiftbic`, `lei`, `organisationid` |
| Quote | `deliveryMethod` | `directtoaccount`, `agent`, `personaldelivery` |

Précision sur `unregistered`, **FACT** : « Unregistered indicates that although not available, a
transaction posted with the account identifier(s) will result in an **unregistered voucher
creation**. » — c'est le paiement vers un non-inscrit, notion à ne pas perdre.

---

## 4. Les grandes familles d'opérations

Onze familles, relevées section par section dans S2. Les chemins sont cités littéralement.

| # | Famille | Chemins normés (**FACT**) | Modes |
|---|---|---|---|
| F1 | **Transactions** (transfert, paiement marchand, dépôt, retrait, décaissement, transfert international) | `POST /transactions/type/{transactiontype}` · `GET /transactions/{transactionReference}` · `PATCH /transactions/{transactionReference}` | sync + async |
| F2 | **Contrepassation / remboursement** | `POST /transactions/{originalTransactionReference}/reversals` | — |
| F3 | **Lots (batch)** | `POST /batchtransactions` · `PATCH /batchtransactions/{batchID}` · `GET /batchtransactions/{batchID}` · `GET /batchtransactions/{batchID}/rejections` · `GET /batchtransactions/{batchID}/completions` | POST/PATCH **async uniquement**, GET sync uniquement |
| F4 | **Comptes** — création, lecture, mise à jour | `POST /accounts/{identityType}` (valeur `individual`) · `GET`/`PATCH /accounts/{identifierType}/{identifier}` · `PATCH /accounts/…/identities/{identityId}` | — |
| F5 | **Statut de compte** | `GET /accounts/{identifierType}/{identifier}/status` | sync |
| F6 | **Solde** | `GET /accounts/{identifierType}/{identifier}/balance` · variante « self » : `/accounts/balance` | sync |
| F7 | **Nom du titulaire** | `GET /accounts/{identifierType}/{identifier}/accountname` | sync |
| F8 | **Historique / relevé** | `GET /accounts/…/transactions` · `GET /accounts/…/statemententries` · `GET /statemententries/{transactionReference}` | sync |
| F9 | **Factures** | `GET /accounts/…/bills` · `POST`/`GET /accounts/…/bills/{billReference}/payments` · `GET /billcompanies` | — |
| F10 | **Mandats de prélèvement** | `POST`/`PATCH`/`GET /accounts/…/debitmandates[/{mandateReference}]` | POST/PATCH sync+async, GET sync |
| F11 | **Liaison de comptes** | `POST`/`PATCH`/`GET /accounts/…/links[/{linkReference}]` | POST/PATCH sync+async, GET sync |
| F12 | **Codes d'autorisation** (retrait sans carte, QR, pré-autorisation) | `POST`/`PATCH`/`GET /accounts/…/authorisationcodes[/{authorisationCode}]` | POST/PATCH sync+async, GET sync |
| F13 | **Cotations** (frais + taux de change avant transfert) | `POST /quotations` · `GET /quotations/{Quotation Reference}` | — |
| F14 | **Supervision** | `GET /heartbeat` | sync uniquement |
| F15 | **Récupération de réponse perdue** | `GET /responses/{clientCorrelationId}` | sync |

Pagination normalisée sur toutes les collections, **FACT** : paramètres `limit` (« If this is not
supplied, then the server will apply a limit of **50** records returned for each request »),
`offset`, `fromDateTime`, `toDateTime` ; en-têtes de réponse `X-Records-Available-Count` et
`X-Records-Returned-Count` ; et « API Providers should make sure that the transactions are returned
in **descending date created order** ».

Les **huit cas d'usage** mis en avant par le portail (S3, sommaire « Use cases ») sont, **FACT** :
Merchant payments · Disbursements · International transfers · P2P transfers · Recurring payments ·
Account linking · Bill payments · Agent Services. Ce sont des assemblages des familles ci-dessus,
pas des APIs supplémentaires.

---

## 5. Les en-têtes HTTP

**FACT** (S1, § *HTTP Header Information*), intégralement.

**Requête, standards — tous `Mandatory`** : `Accept: application/json` · `Accept-Charset: utf-8` ·
`Authorization` · `Content-Length` · `Content-Type: application/json`.

Valeur d'`Authorization`, **FACT** : « `Authorization: Basic {base64Encode(concatenated client's
username followed by ‘:’ and password)}` **OR** OAuth2 Access Token. For OAuth2 format is
`{‘Bearer’ token value}` ». → **Le standard admet donc explicitement le Basic Auth au même rang que
OAuth 2.0.** Un opérateur en Basic n'est pas hors-standard de ce seul fait.

**Requête, personnalisés — tous `Conditional`** :

| En-tête | Valeur / rôle (citation) |
|---|---|
| `X-API-Key` | « Used to pass pre-shared client's API key to the server » |
| `X-Client-Id` | « Used to pass pre-shared client's identifier… Can be used in addition to X-API-Key. » |
| `X-User-Bearer` | « Used to pass user's access token » — si OAuth 2.0/OIDC pour l'utilisateur final |
| `X-User-Credential-1` / `-2` | « an authentication credential of the end user (e.g. PIN, Password) » — « Should only be used when OAuth 2.0/OIDC… has not been implemented » |
| `X-Date` | date/heure d'émission, format HTTP-date RFC 7231 — intégrité |
| `X-Content-Hash` | « SHA-256 hex digest of the request content (encrypted or plain) » |
| `X-CorrelationID` | UUID — cf. § 2.4 |
| `X-Channel` | « string containing the channel that was used to originate the request. For example, USSD, Web, App. » |
| `X-Callback-URL` | URL de rappel — cf. § 2.5 |

**Réponse** : `Content-Length` et `Content-Type: application/json; charset=utf-8` (conditionnels au
corps JSON) ; `X-Date` en en-tête personnalisé.

L'existence de `X-Channel` mérite d'être relevée : **le canal d'origine (USSD / Web / App) est une
notion de premier rang du standard**, pas une invention FinZuu.

---

## 6. Le catalogue d'erreurs

**FACT** (S1). Six catégories, avec leur code HTTP :

| `errorCategory` | HTTP | Description (citation abrégée) |
|---|---|---|
| `BusinessRule` | **400** | « violation of a business rule… financial limit violations, duplicate requests, and invalid states » |
| `Validation` | **400** | « Violation of a constraint that will prevent the resource from being processed » |
| `Authorisation` | **401** | « not possible to authenticate or authorise the client or other party » |
| `Identification` | **404** | « The requested resource could not be matched… with the supplied identifier(s) » |
| `Internal` | **500** | « non-client related issues that do not constitute complete system unavailability » |
| `Service Unavailable` | **503** | « The service is not currently available » |

Les 30 `errorCode` normés, intégralement :

**`BusinessRule`** (19) — `GenericError`, `DailyVolumeLimitExceeded`, `DailyValueLimitExceeded`,
`WeeklyVolumeLimitExceeded`, `WeeklyValueLimitExceeded`, `MonthlyVolumeLimitExceeded`,
`MonthlyValueLimitExceeded`, `AccountMaxTotalValueExceeded`, `AccountMaxTotalVolumeExceeded`,
`LessThanTransactionMinValue`, `GreaterThanTransactionMaxValue`, `MaxBalanceExceeded`,
`SamePartiesError`, `DuplicateRequest`, `InsufficientFunds`, `IncorrectState`,
`UnderPaymentNotAllowed`, `OverPaymentNotAllowed`, `RateLimitError`.

**`Validation`** (6) — `GenericError`, `LengthError`, `FormatError`, `NegativeValue`,
`CurrencyNotSupported`, `MandatoryValueNotSupplied`.

**`Authorisation`** (3) — `ClientAuthorisationError` (« General Client Authentication failure. No
further details provided to prevent leakage of security information. »), `RequestDeclined` (« The
debit party did not approve the request. »), `RequestingPartyAuthorisationError`.

**`Identification`** (1) — `IdentifierError`.
**`Internal`** (1) et **`Service Unavailable`** (1) — `GenericError`.

Quatre de ces codes couvrent des invariants que la sandbox devra tenir : `SamePartiesError`
(débiteur = créditeur), `InsufficientFunds`, `DuplicateRequest`, `CurrencyNotSupported`.

Codes HTTP par méthode, **FACT** :

| Méthode | Succès | Intermédiaire | Erreur client | Erreur serveur |
|---|---|---|---|---|
| `GET` | 200 | N/A | 400, 401, 404 | 500, 503 |
| `POST` | 201 | **202** | 400, 401, 404 | 500, 503 |

**Le `PATCH` est absent de cette table alors qu'il est une méthode supportée du standard.** Son code
de succès n'apparaît que dans les diagrammes de séquence : **204** en synchrone (fig. 5), **202** en
asynchrone (fig. 7). Incohérence de la spécification, consignée, non arbitrée.

Format du `PATCH`, **FACT** (S1, § *Patch Specifics*) : « The PATCH format is based upon IETF RFC
6902… An example of a replace operation is `[{ "op": "replace", "path": "/XYZ", "value": "test" }]` ».

---

## 7. Grille de conformité — le gabarit imposé aux fiches opérateur

Chaque fiche opérateur remplit cette grille. Trois verdicts seulement, et jamais d'autre :

- **CONFORME** — la source officielle de l'opérateur documente la notion et elle correspond au socle.
- **DIVERGENT** — la source officielle documente la notion **autrement**. L'écart est décrit.
- **NON DOCUMENTÉ** — la notion n'est pas trouvable dans les sources officielles accessibles sans
  inscription. **Ce n'est pas « absent » : c'est « non su ».** Toute case NON DOCUMENTÉ engendre une
  entrée dans « TROUS À CALIBRER ».

| Réf. | Point de contrôle | Référence socle |
|---|---|---|
| G1 | Mécanisme d'authentification client | § 5 — Basic ou OAuth2 Bearer, `X-API-Key` / `X-Client-Id` |
| G2 | Format d'URI et versionnage | § 1 — `{…}/{version}/mm/{Resource}`, `X.Y.Z` |
| G3 | Identification des parties | § 2.1 — `debitParty`/`creditParty`, tableaux clé/valeur, clés énumérées |
| G4 | Format du MSISDN | § 2.1 — 6 à 15 chiffres, `+` toléré, espaces tolérés |
| G5 | Représentation du montant | § 2.2 — `amount` **string** + `currency` ISO 4217 séparé, ≤ 4 décimales |
| G6 | Référence de transaction fournisseur vs. cliente | § 2.3 — `transactionReference` vs `requestingOrganisationTransactionReference` |
| G7 | Types de transaction | § 2.3 — les 9 codes énumérés |
| G8 | Idempotence | § 2.4 — `X-CorrelationID` UUID, rejet `DuplicateRequest` |
| G9 | Récupération de réponse perdue | § 2.4 — `GET /responses/{clientCorrelationId}` |
| G10 | Notification asynchrone | § 2.5 — `X-Callback-URL` + **PUT** entrant, ou polling `/requeststate` |
| G11 | Objet d'erreur | § 2.6 — `errorCategory` + `errorCode` + `errorDescription` |
| G12 | Catalogue de codes d'erreur | § 6 — 6 catégories, 30 codes |
| G13 | Cycle de vie de la requête | § 3.1 — `pending`/`completed`/`failed` |
| G14 | Cycle de vie de la transaction | § 3.3 — **non normé par la GSMA** : à relever à la source, toujours |
| G15 | Traitement par lot | § 3.2 — `created`/`approved`/`completed`, `/rejections`, `/completions` |
| G16 | Consultation de solde et de statut | § 4 — F5, F6 |
| G17 | Cotation / frais / taux de change | § 4 — F13 |
| G18 | Contrepassation et remboursement partiel | § 2.3, F2 |
| G19 | Pagination des collections | § 4 — `limit` (défaut 50), `offset`, `X-Records-*-Count` |
| G20 | Canal d'origine | § 5 — `X-Channel` (USSD / Web / App) |
| G21 | Supervision | § 4 — F14 `GET /heartbeat` |
| G22 | Sandbox opérateur et limites annoncées | hors socle — factuel |

---

## 8. Trous à calibrer — au niveau du socle lui-même

Ces trous ne sont imputables à aucun opérateur : ils sont dans le standard. Ils devront être
tranchés par une décision FinZuu, et cette décision devra être écrite, parce qu'elle ne pourra
s'appuyer sur aucune source.

| # | Trou | Ce qui manque | Pourquoi ça bloque |
|---|---|---|---|
| **T-SOCLE-01** | **Statuts de transaction non énumérés** (§ 3.3) | `transactionStatus` est obligatoire en réponse mais n'a aucune liste de valeurs | La sandbox doit renvoyer *une* valeur. Sans arbitrage, chaque profil opérateur inventera la sienne et les tests deviendront incomparables. **Trou n°1, le plus structurant.** |
| **T-SOCLE-02** | **Durée de rémanence de `X-CorrelationID`** | aucune durée, aucune règle d'expiration | Détermine si un rejeu à H+1 doit être rejeté (`DuplicateRequest`) ou accepté. Deux comportements opposés, tous deux « conformes ». |
| **T-SOCLE-03** | **Portée de l'unicité de `X-CorrelationID`** | par client ? par compte ? global au fournisseur ? | Deux clients tirant le même UUID (improbable mais possible) : collision ou non ? |
| **T-SOCLE-04** | **Normalisation du montant-chaîne** (§ 2.2) | `"5"`, `"5.0"` et `"5.00"` sont tous valides et distincts textuellement | Rapprochement, hachage `X-Content-Hash`, comparaison de doublons : trois résultats différents pour un même montant. |
| **T-SOCLE-05** | **Code de succès du `PATCH`** (§ 6) | absent de la table des codes HTTP ; 204 et 202 dans les diagrammes seulement | Une assertion de test doit choisir. |
| **T-SOCLE-06** | **Casse du chemin `/responses`** (§ 2.4) | `/responses` et `/Responses` dans la même page | Sensible à la casse côté serveur : deux implémentations divergentes possibles. |
| **T-SOCLE-07** | **Type de `notificationMethod`** (§ 2.5) | déclaré `date-time`, valeurs `callback`/`polling` | Erreur de la spécification. Un générateur de code à partir du schéma produira un champ faux. |
| **T-SOCLE-08** | **Délai et politique de reprise du callback** | rien sur le nombre de tentatives, le délai, le comportement si le client répond 5xx | La sandbox doit décider seule de sa politique de rappel. |
| **T-SOCLE-09** | **Sécurité : le document de référence est inaccessible** | « Mobile Money API Security Design » cité mais non atteignable sans inscription | Signature, chiffrement, gestion des clés : entièrement à calibrer. |
| **T-SOCLE-10** | **Spécification machine (OAS3) non récupérable anonymement** | fichier `.yaml`/`.json` introuvable dans la page du visualiseur | Pas de validation automatique de schéma possible sans inscription au portail — décision d'inscription à prendre par la direction. |

---

## 9. Ce que ce socle autorise, et ce qu'il interdit

**Autorisé** : mesurer chaque opérateur contre les 22 points de la grille du § 7 ; qualifier un écart
de DIVERGENT en le citant ; conclure NON DOCUMENTÉ et ouvrir un trou.

**Interdit, sans exception** : déduire d'une notion présente ici qu'un opérateur l'implémente ;
combler une case NON DOCUMENTÉ d'un opérateur avec la valeur du socle ou celle d'un autre opérateur ;
présenter une source tierce (blog, tutoriel, agrégateur, SDK communautaire) comme officielle.

Un trou est un trou. On l'écrit, on le chiffre, on le fait trancher.
