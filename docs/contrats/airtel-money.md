# Airtel Money — contrat opérateur

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Référentiel des contrats opérateurs · Fiche T2
**Rédigée le** 2026-09-03 · **Socle de référence** [`00_socle_gsma.md`](00_socle_gsma.md)
**Nature** 100 % documentaire. Aucune inscription, aucun compte créé. *(Une réserve de méthode est
signalée au § 0.2 : elle doit être lue.)*

> **Verdict en une phrase.** Le portail développeur d'Airtel **existe et est bien structuré**, mais
> **toute la documentation technique est derrière un mur d'inscription**, filiale par filiale.
> Ce qui est public : le parcours d'onboarding, quatre libellés commerciaux, et **la liste des
> 13 pays** — chacun étant une entité séparée avec son propre domaine et son propre compte.
> **Le Cameroun n'y figure pas.**

---

## 0. Notes de méthode — deux points à lire avant le reste

### 0.1 Le portail est une application Angular : `curl` seul ne voit rien

Le HTML servi par `developers.airtel.africa` ne contient aucun contenu, seulement les bundles
(`main.c0f420ec255d0ba5.js`, `runtime…js`, `polyfills…js`, `styles…css`). Toute lecture par simple
récupération HTTP ne voit qu'une coquille vide. Les faits ci-dessous proviennent soit d'un rendu
navigateur, soit de la lecture du bundle JavaScript lui-même — les deux étant publics et anonymes.

**Piège majeur, prouvé personnellement.** Plusieurs résumés de moteurs de recherche affirment qu'une
documentation existe à `https://developers.airtel.africa/docs`. **C'est faux.** J'ai récupéré quatre
chemins et comparé :

| Chemin | HTTP | Type | Taille |
|---|---|---|---|
| `/` | 200 | `text/html` | 66 090 o |
| `/docs` | 200 | `text/html` | **66 090 o** |
| `/swagger.json` | 200 | `text/html` | **66 090 o** |
| `/openapi.json` | 200 | `text/html` | **66 090 o** |

Et la comparaison ligne à ligne de `/docs` contre `/swagger.json` ne montre **qu'une seule ligne de
différence**, qui est un compteur anti-cache :

```
< …&ns=2&cb=1820145398" async nonce="aK8Pq3RZ7nM5EJX4D0H2wQ=="></script></body>
> …&ns=3&cb=1980122459" async nonce="aK8Pq3RZ7nM5EJX4D0H2wQ=="></script></body>
```

Ce sont donc bien des **replis d'application monopage identiques**, pas des documents.
**Ne jamais reprendre l'affirmation « la doc Airtel est à /docs ».**

### 0.2 Réserve à remonter — une entorse partielle à la consigne

**Je la signale plutôt que de la masquer.** Au cours de la recherche, deux requêtes `GET` non
authentifiées ont été émises sur les **racines** `https://openapi.airtel.africa/` et
`https://openapiuat.airtel.africa/`, afin de vérifier que ces hôtes cités par des tiers existent.
**Les deux ont répondu HTTP 401.** Aucune route métier n'a été appelée, aucun identifiant transmis,
aucun corps de requête envoyé, aucun compte créé.

La mission dit « **aucun appel vers une API opérateur** ». Interroger la racine d'un hôte d'API,
même sans route ni identifiant, est à la limite de cette consigne. Le seul fait qui en découle —
*ces deux hôtes existent et exigent une authentification* — est marqué ci-dessous, et **la direction
peut décider de l'écarter** si elle juge la mesure irrégulière. Le reste de la fiche n'en dépend pas.

---

## 1. Le portail développeur

**URL : `https://developers.airtel.africa/`**, `<title>Developer Portal</title>`, HTTP 200.
(consulté le 2026-09-03) **[OFFICIELLE]**

### 1.1 Une architecture à deux étages — c'est le fait structurant

*Vérifié personnellement dans le bundle.* Le routeur Angular n'expose que **quatre routes de premier
niveau** : `developer`, `documentation`, `marketplace`, `user` (plus `""`, `404`, `**`).

**Étage 1 — `developers.airtel.africa` n'est qu'un sélecteur de pays.** `/documentation`,
`/developer` et `/marketplace` redirigent tous vers `/login-country`, qui affiche « Select Country »
et ce bandeau, **FACT**, verbatim :

> « **New! Now applications are managed per Op-Co select country first to Proceed** »

**Étage 2 — le choix d'un pays renvoie vers un domaine de filiale, et atterrit sur une page de
connexion.** Vérifié sur deux pays :

- Uganda → `https://developers.airtel.ug/user/login`
- Kenya → `https://developers.airtelkenya.com/user/login`

**Conséquence directe pour le référentiel** : **une application n'est pas portable d'un pays à
l'autre.** Chaque Op-Co a son domaine, son compte, ses clés. Un profil « Airtel » unique serait une
simplification fausse.

### 1.2 Ce qui est lisible sans connexion

Mesuré sur `developers.airtel.ug`. La page `/home` est publique. Titre : « Build, Innovate and Power
your apps with Airtel Platform ».

Parcours annoncé en trois étapes, **FACT**, verbatim :

> « **Sign up** — Choose an API Product / Sign up for an Account / Register an Application
> **Test for free** — Read Documentation & Instructions carefully / Submit API request to get
> realistic response
> **Go Live** — Comply with API requirements Get Production access / After Legal compliance,
> onboarding, approval- Go Live »

Les menus `Products` et `Developer` s'ouvrent sans connexion, **mais leurs entrées ne sont pas des
liens** : les cartes produit renvoient vers `/user/login`. Liens réellement publics : `/home`,
`/user/support`, `/user/signup`, `/user/login`, `/user/forgot-password`, `/brand-guidelines`.

**Ce qui est fermé** : `/developer` et `/marketplace` redirigent vers `/user/login` ;
`/documentation` sur le domaine pays rend une page **vide** (navigation seule, ~7 caractères de
corps). **La documentation d'API n'est donc pas consultable sans compte.**

Le communiqué officiel d'Airtel le confirme, **FACT**, verbatim :

> « Businesses can access the developer portal and Airtel's API library by using the following URL:
> `https://developers.airtel.africa/developer` and **signing up** to get started. **Once the business
> logs in on the portal, they can begin to explore the API documentation** and start integrating by
> registering an application. »
> — `https://www.airtel.africa/assets/pdf/press-release/Airtel-Africa-Developer-Portal_ENGLISH.pdf`
> **[OFFICIELLE]**

**Formulaire d'inscription** (`/user/signup`, public) : First Name, Last Name, User Name, Email Id,
Phone Number, Password, captcha, et « By signing up, you agree to the Airtel API Terms of use ».
Titre : « Create a new API Management account. »

### 1.3 Les 13 pays — la donnée publique la plus exploitable

**FACT**, transcrit verbatim depuis le sélecteur officiel, **orthographes d'origine conservées** :

> **Uganda · Kenya · Tanzania · Rwanda · Madagascar · DRC · Gabon · Zambia · Chad · Niger ·
> Malawi · CONGOB · Seychellas**

(« Seychellas » et « CONGOB » sont les libellés exacts affichés par le portail — coquilles incluses.)

**Deux conclusions pour FinZuu :**

1. **Le Cameroun n'est pas dans la liste.** Airtel n'opère pas au Cameroun ; c'est cohérent avec le
   marché, où MTN et Orange se partagent le mobile money. **Airtel est donc, pour le périmètre
   camerounais de la sandbox, un opérateur hors sujet** — sauf si le périmètre s'étend au Tchad, au
   Gabon ou aux deux Congo, qui sont eux couverts.
2. Le chiffre de « 14+ pays » circule dans des résumés de moteurs de recherche. **Le sélecteur
   officiel en affiche 13.** Je retiens 13, sourcé.

---

## 2. Spécification téléchargeable sans compte

**INTROUVABLE.** Voir la démonstration au § 0.1 : les chemins candidats sont des replis SPA, pas des
documents. Aucun OpenAPI, Swagger ou PDF de spécification n'est accessible sans compte.

→ Rien n'a pu être versé au titre d'une spécification dans `docs/contrats/sources/airtel-money/`,
qui ne contient que les deux coquilles SPA archivées **comme preuve du faux positif**.

---

## 3. Ce qui est visible SANS inscription

### 3.1 Produits — des libellés commerciaux, jamais une liste d'API

**FACT**, verbatim depuis le menu `Products` et la page d'accueil :

| Libellé exact | Description affichée |
|---|---|
| **Airtel Mobile Money Remittance** | « Enabling customers to transfer or receive funds in recipient's wallet in local currency » |
| **Selling Goods & Services** | « We offer a business to collect money from customers seamlessly and in a safe manner » |
| **Bulk Payments** | « Enabling organizations to pay their stakeholders, including employees and vendors, with a click of a button. » |
| **Generate Business till** | « Now merchants can generate a till number to accept payments on the till. » |

Menu `Developer` : deux entrées seulement, « Register Application » et « Documentation ».

**Un seul nom de produit technique est observable**, et pas dans la documentation : la chaîne
littérale `"Collection-APIs"` apparaît dans le bundle `199.b3b426570a5e3009.js`, comparée au champ
`name` des produits d'un compte (`"Collection-APIs"==n.name`). C'est la preuve qu'un produit porte
ce nom, **pas** une liste de produits publiée. **[OFFICIELLE]**

Aucune mention publique de **KYC** ni d'**Account Enquiry** comme produit nommé : **INTROUVABLE**.

**Noter que « Bulk Payments » est un produit annoncé.** C'est le seul opérateur du référentiel, avec
MTN (qui lui n'en a pas), à afficher explicitement un produit de paiement de masse — donc le plus
proche conceptuellement du module Bulk de la plateforme FinZuu. Son contrat est inaccessible.

### 3.2 Authentification

**Sur source OFFICIELLE, sans compte : INTROUVABLE.**

> ⚠️ **Piège écarté.** Le bundle du portail contient bien un en-tête `"X-country"` et un
> `Authorization: Bearer ${P}` — code verbatim :
> `addToken(M,P){let h={"X-country":this.config.XCountry};P&&(h.Authorization=\`Bearer ${P}\`)…}`.
> **Mais c'est l'authentification du frontend du portail vers son propre backend, pas l'API Airtel
> Money.** Je ne l'attribue donc pas à l'API. C'est exactement le genre d'inférence qui produit un
> profil faux.

Sur sources **[TIERCES]** — deux implémentations indépendantes concordantes :
`POST /auth/oauth2/token`, en-têtes `X-Country` et `X-Currency`, puis `Authorization: Bearer <token>`.
`github.com/osenco/airtel` (`src/Service.php`) · `github.com/ziangani/card-to-wallet`
(`app/Integrations/Airtel/Airtel.php`) (consultés le 2026-09-03).

### 3.3 Routes

**Sur source OFFICIELLE : INTROUVABLE.** Sur sources **[TIERCES]** uniquement — la plus complète
étant un fichier de configuration Go :

```
prod    = https://openapi.airtel.africa
staging = https://openapiuat.airtel.africa
POST /merchant/v1/payments/            (collecte)
POST /standard/v1/payments/refund      (remboursement)
GET  /standard/v1/payments/{ref}       (statut de collecte)
     /standard/v1/disbursements/       (décaissement + statut)
GET  /merchant/v1/transactions         (récapitulatif)
GET  /standard/v1/users/balance        (solde)
GET  /standard/v1/users/{msisdn}       (interrogation utilisateur)
```

Sources **[TIERCES]** : `github.com/truecheck/pesakit` (`config/airtel.go`) ·
`github.com/ziangani/card-to-wallet` · `github.com/osenco/airtel`.
**Pas de CONFLIT** : les trois concordent sur les URL de base et sur les préfixes
`/merchant/v1/`, `/standard/v1/`, `/auth/oauth2/token`.

*Rappel de la réserve du § 0.2* : les deux hôtes ci-dessus ont répondu **401** à une requête de
racine non authentifiée. C'est le seul élément officiel — et il est de méthode contestable.

### 3.4 Format des identifiants et idempotence

**INTROUVABLE côté officiel.** Structure de corps observée en source **[TIERCE]** (collecte) :

```json
{ "reference": "…",
  "subscriber":  { "country": "ZM", "currency": "ZMW", "msisdn": "…" },
  "transaction": { "amount": "…", "country": "ZM", "currency": "ZMW", "id": "…" } }
```

**Idempotence : INTROUVABLE, y compris en source tierce.** Aucune clé, aucun en-tête, aucune règle
de rejeu — rien, nulle part.

### 3.5 Statuts et erreurs

**Aucun code publié officiellement : INTROUVABLE.**

Source **[TIERCE] unique** (donc à confirmer), statuts lus dans `status.code` :
`ts` = Transaction Successful · `tf` = Failed · `ta` = **Ambiguous** · `tp` = Pending ·
`tn` = Not Found · `tr` = Refunded · `tc` = Cancelled.
Champs associés : `status.code`, `status.message`, `status.response_code`.
`github.com/AllDotPy/EasySwitch` (`easyswitch/integrators/airtel_money.py`) (consulté le 2026-09-03).

**L'état `ta` — « ambiguous » — mérite d'être relevé** : c'est un état que ni la GSMA ni MTN ne
définissent. S'il se confirme, il change la logique de réconciliation, puisqu'il désigne une
transaction dont l'issue n'est **pas** déterminée. Une seule source, donc **hypothèse**, pas fait.

**Aucune table d'erreurs**, même tierce : les statuts ne sont pas des erreurs.

### 3.6 Sandbox

**Elle existe, mais n'est décrite nulle part publiquement.** La seule mention officielle accessible
sans compte est l'étape « **Test for free** » du parcours : « Read Documentation & Instructions
carefully » / « Submit API request to get realistic response ». **Aucune limite annoncée** — ni
plafond, ni quota, ni jeu de données, ni numéro de test.

Hôte de préproduction cité par des tiers : `openapiuat.airtel.africa` (cf. réserve § 0.2).

---

## 4. Revendication du standard GSMA

**Aucune. INTROUVABLE.**

*Vérifié personnellement* : recherche insensible à la casse du terme `gsma` dans
`main.c0f420ec255d0ba5.js` (1 439 020 octets) → **0 occurrence**. L'agent de recherche a étendu la
vérification au runtime et aux quatre chunks paresseux (`76`, `199`, `555`, `590`) — également zéro,
ainsi que dans les pages publiques rendues et dans le communiqué de presse officiel.

Airtel qualifie ses API d'« **Open APIs** » et « **fintech Open APIs** », jamais de GSMA ni de
« harmonised ».

**Observation, qui n'est pas un verdict** : la structure tierce observée
(`/merchant/v1/payments/`, objets `subscriber` / `transaction`) **ne ressemble pas** au schéma GSMA.
Mais aucune source officielle ne l'établit, donc ce n'est pas consigné comme divergence.

---

## 5. Conformité au socle GSMA

Grille G1..G22 de [`00_socle_gsma.md`](00_socle_gsma.md) § 7.

**Verdict uniforme : NON DOCUMENTÉ sur les 22 points.** Aucune source officielle Airtel accessible
sans compte ne documente un seul élément du contrat. Toute autre notation reviendrait à promouvoir
des SDK communautaires au rang de contrat.

| Réf. | Point de contrôle | Verdict | Indice tiers, sans valeur contractuelle |
|---|---|---|---|
| G1 | Authentification | **NON DOCUMENTÉ** | `POST /auth/oauth2/token`, `X-Country`, `X-Currency`, Bearer **[TIERCE]** |
| G2 | URI et versionnage | **NON DOCUMENTÉ** | `/merchant/v1/…`, `/standard/v1/…` **[TIERCE]** — pas de segment `mm`, versionnage `v1` |
| G3 | Identification des parties | **NON DOCUMENTÉ** | objet `subscriber` unique **[TIERCE]**, pas de tableau `debitParty`/`creditParty` |
| G4 | Format MSISDN | **NON DOCUMENTÉ** | champ `msisdn` **[TIERCE]**, aucun format publié |
| G5 | Montant | **NON DOCUMENTÉ** | `transaction.amount` + `currency` **[TIERCE]** ; type et bornes inconnus |
| G6 | Références | **NON DOCUMENTÉ** | `reference` et `transaction.id` **[TIERCE]**, rôles non documentés |
| G7 | Types de transaction | **NON DOCUMENTÉ** | type porté par la route **[TIERCE]** |
| G8 | **Idempotence** | **NON DOCUMENTÉ** | aucun indice, même tiers |
| G9 | Récupération de réponse perdue | **NON DOCUMENTÉ** | aucun |
| G10 | Notification asynchrone | **NON DOCUMENTÉ** | aucun webhook documenté, ni officiel ni tiers |
| G11 | Objet d'erreur | **NON DOCUMENTÉ** | `status.{code,message,response_code}` **[TIERCE]** |
| G12 | Catalogue d'erreurs | **NON DOCUMENTÉ** | **aucune table d'erreurs n'existe**, même tierce |
| G13 | Cycle de vie de la requête | **NON DOCUMENTÉ** | `tp` = pending **[TIERCE]** |
| G14 | Cycle de vie de la transaction | **NON DOCUMENTÉ** | 7 codes à deux lettres dont `ta` ambiguous **[TIERCE, source unique]** |
| G15 | **Traitement par lot** | **NON DOCUMENTÉ** | produit « **Bulk Payments** » annoncé **[OFFICIELLE]**, contrat inaccessible |
| G16 | Solde et statut de compte | **NON DOCUMENTÉ** | `/standard/v1/users/balance`, `/users/{msisdn}` **[TIERCE]** |
| G17 | Cotation / frais | **NON DOCUMENTÉ** | aucun |
| G18 | Contrepassation | **NON DOCUMENTÉ** | `/standard/v1/payments/refund` **[TIERCE]** |
| G19 | Pagination | **NON DOCUMENTÉ** | `/merchant/v1/transactions` existe **[TIERCE]**, pagination inconnue |
| G20 | Canal d'origine | **NON DOCUMENTÉ** | aucun |
| G21 | Supervision | **NON DOCUMENTÉ** | aucun |
| G22 | Sandbox et limites | **NON DOCUMENTÉ** | « Test for free » **[OFFICIELLE]**, sans aucun paramètre |

**Synthèse : 0 CONFORME · 0 DIVERGENT · 22 NON DOCUMENTÉ.**

---

## 6. TROUS À CALIBRER

| # | Trou | Ce qui manque exactement | Impact sur la sandbox | Comment le lever |
|---|---|---|---|---|
| **T-AIR-01** | **Toute la documentation technique** | Elle existe — le portail l'annonce — mais elle est intégralement derrière `/user/login`, sur le domaine de chaque Op-Co. | Aucun profil ne peut être écrit sur des faits. | Créer un compte sur le portail de l'Op-Co visée. Interdit par la mission. |
| **T-AIR-02** | **Portée : un compte par pays** | « applications are managed per Op-Co ». Un compte Ouganda ne vaut pas pour le Tchad. | Un profil « Airtel » unique est probablement faux. Il faudra autant de profils que de pays. **Trou de conception, pas seulement d'information.** | Un compte par pays visé. |
| **T-AIR-03** | **Le Cameroun est absent** | Airtel n'opère pas au Cameroun. | **Airtel est hors sujet pour le périmètre camerounais.** À confirmer avec la direction avant d'y investir. | Décision de périmètre, pas recherche. |
| **T-AIR-04** | **Contrat de « Bulk Payments »** | Produit annoncé, aucune spécification. C'est pourtant le plus proche du module Bulk FinZuu. | Le cas d'usage le plus pertinent est le moins documenté. | Compte développeur. |
| **T-AIR-05** | **Idempotence** | Aucun indice, ni officiel ni tiers. Le vide le plus complet du référentiel sur ce point. | Le double paiement ne peut pas être testé. | Idem. |
| **T-AIR-06** | **Contrat du webhook** | Aucun webhook documenté nulle part. On ignore même s'il en existe un. | Le flux asynchrone est entièrement inconnu. | Idem. |
| **T-AIR-07** | **Codes d'erreur** | **Aucune table n'existe**, même tierce. Seuls 7 codes de *statut* à deux lettres, d'une source unique. | Aucune assertion d'erreur possible. | Idem. |
| **T-AIR-08** | **L'état `ta` (ambiguous)** | Un état d'issue indéterminée, absent de la GSMA et de MTN. Source unique. | Si confirmé, il impose une logique de réconciliation particulière. **À vérifier en priorité** : c'est le genre d'état qui fait perdre de l'argent. | Idem. |
| **T-AIR-09** | **Sandbox : limites** | « Test for free » sans aucun paramètre : ni quota, ni MSISDN de test, ni plafond. | Rien à reproduire. | Idem. |
| **T-AIR-10** | **Devises par pays** | La liste des pays est servie dynamiquement, sans code ISO ni devise. `X-Currency` existe **[TIERCE]** mais ses valeurs sont inconnues. | Pas de mapping pays → devise. | Idem. |

**Décision à porter à la direction.** Airtel est le cas le plus simple à arbitrer : **le Cameroun
n'est pas couvert**. Si la sandbox reste centrée sur le Cameroun, Airtel sort du périmètre et aucun
de ces trous n'a besoin d'être levé. Si le périmètre s'étend au Tchad, au Gabon, à la RDC ou au
Congo-Brazzaville, alors il faudra **un compte par pays**, et T-AIR-02 devient le premier sujet.

---

## 7. Sources archivées

Dans `docs/contrats/sources/airtel-money/` :

| Fichier | Ce qu'il prouve |
|---|---|
| `spa_shell_docs_2026-09-03.html` | la coquille servie à `/docs` |
| `spa_shell_swagger.json_2026-09-03.html` | la coquille servie à `/swagger.json` — **identique à la précédente à un compteur anti-cache près** |
| `NOTES_VERIFICATION.txt` | la démonstration du faux positif, le zéro GSMA dans le bundle, et la réserve du § 0.2 |

Ces deux fichiers sont archivés **comme preuve d'une absence**, pas comme documentation.

---

## 8. Niveau de confiance pour le futur profil opérateur

**FAIBLE.**

Ce qui est solide : le portail existe et son fonctionnement est compris ; l'architecture par Op-Co
est établie et a une conséquence de conception forte ; la liste des 13 pays est officielle et
exploitable ; l'absence de revendication GSMA est vérifiée dans le code ; et le faux positif `/docs`
est réfuté au caractère près.

Ce qui ne l'est pas : **tout le contrat technique**. Aucun chemin, aucun champ, aucune erreur
officielle. Ce qui circule vient de quatre dépôts communautaires — concordants entre eux, ce qui est
rassurant, mais sans aucune valeur contractuelle.

**Recommandation.** Trancher d'abord le périmètre géographique (T-AIR-03). Si Airtel reste au
programme, la levée passe par **une inscription par pays**, et le profil devra être décliné par
Op-Co dès la conception — pas rattrapé après coup.
