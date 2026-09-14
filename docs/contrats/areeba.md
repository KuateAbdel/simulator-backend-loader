# Areeba — contrat opérateur

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Référentiel des contrats opérateurs · Fiche T2
**Rédigée le** 2026-09-03 · **Socle de référence** [`00_socle_gsma.md`](00_socle_gsma.md)
**Nature** 100 % documentaire. Aucun appel vers une API de paiement, aucune inscription, aucun
compte créé.

> **Verdict en une phrase.** **« Areeba » désigne deux entreprises entièrement distinctes**, et les
> confondre est l'erreur la plus coûteuse que ce référentiel puisse contenir. L'une est un
> **processeur carte libanais** (Mastercard en marque blanche, pas de mobile money) ; l'autre est un
> **opérateur télécom guinéen** avec un vrai mobile money (MoMo, `*440#`) mais **aucune API
> publique**. Aucune source ne relie les deux.

---

## 0. Le point déterminant : deux entreprises, un seul nom

C'était la question à trancher avant toute autre, et elle est tranchée.

| | **Entité 1 — areeba (Liban)** | **Entité 2 — Areeba Guinée** |
|---|---|---|
| Nature | **Processeur / acquéreur carte**, émetteur de wallet régulé au Liban | **Opérateur télécom**, ex-MTN Guinée |
| Domaine | `areeba.com`, `areeba.iq`, `epayment.areeba.com` | `areeba.gn` |
| Actionnaire | **M1 Group** (filiale à 100 %) | **État guinéen** (rachat à MTN) |
| Pays | Jordanie, Liban, Irak, Égypte, Qatar, EAU | **Guinée** uniquement |
| Mobile money ? | Non au sens GSMA (wallet Zaky, Liban, hors périmètre) | **Oui — MoMo, USSD `*440#`** |
| API publique ? | **Oui**, mais c'est du **Mastercard MPGS** en marque blanche | **Non, rien** |

**Racine de l'homonymie**, sourcée : « Areeba » était la marque mobile du groupe libanais
**Investcom** (famille Mikati) ; MTN a racheté Investcom en 2006-2007 et retiré la marque. L'areeba
libanaise de paiement est, elle, une filiale du **M1 Group** (également Mikati) créée en **2017**.
**Aucune source, officielle ou tierce, n'établit de lien capitalistique, contractuel ou technique
entre les deux.**

**Conséquence pour le référentiel : « Areeba » ne doit jamais figurer comme une seule ligne dans un
tableau d'opérateurs de mobile money.**

### Note de méthode

`www.areeba.com` est protégé par Cloudflare et **répond HTTP 403 à toute récupération directe** —
*constaté personnellement*. Le contenu de areeba.com cité ci-dessous a été obtenu via un proxy
d'extraction de texte qui rend la page officielle telle quelle ; il est marqué
**[OFFICIELLE via proxy]**. En revanche `epayment.areeba.com`, `areeba.iq` et `areeba.gn` ont été
ouverts **en direct, sans proxy et sans compte** : **[OFFICIELLE, directe]**.

---

## 1. Entité 1 — areeba (Liban) : un processeur carte, pas un opérateur mobile money

### 1.1 Nature et périmètre

**FACT**, verbatim :

> « Our extraordinary experience […] enables us to offer our esteemed clientele a unique range of
> payment services […]: **from issuer processing and merchant acquiring to digital payments**. »
>
> « areeba is a **regional processor** covering countries in the Levant, North Africa & the Gulf »
>
> « We are proud to have the support of the **M1 Group as a fully owned subsidiary**. »

Lancée en **2017**, 200+ professionnels, **6 pays** : **Jordan, Lebanon, Iraq, Egypt, Qatar, UAE**.
**Aucun pays d'Afrique subsaharienne.** Plateforme propriétaire **Verto** (Issuing, Switch,
Acquiring, Financial Module), certifiée **PCI DSS depuis 2018**.
Source : `https://www.areeba.com/english/about-us` (consulté le 2026-09-03) **[OFFICIELLE via proxy]**

Catalogue de services : Issuing Processing, Cards Issuing, Digital Solutions, Card As A Service,
Acquiring, Acceptance Solutions, ATM Driving & Management. La page « Digital Solutions » contient
exactement : *Digital First, 3D Secure, Virtual Card, Card Control and e-pin, Mobile Payment and
Tokenization* — **aucune mention de « mobile money », de wallet MSISDN ou de réseau d'agents.**

**Nuance à ne pas escamoter** : cette entité émet bien un portefeuille électronique au Liban, nommé
**Zaky**. **FACT** : « areeba […] has announced the launch of Zaky, its new mobile wallet
application. **Regulated by the Central Bank of Lebanon** […] P2P money transfers, mobile recharge,
top-up services […] the user can create an e-wallet in Lebanese Pounds or US Dollars. » (2020)
Mais c'est un wallet bancaire libanais, hors du périmètre de la sandbox. *(Noter que « Zaky »
désigne un wallet au Liban et une **carte Visa Classic** en Irak — même marque, deux produits.)*

**Verdict entité 1 : processeur / acquéreur carte, doublé d'un émetteur de wallet régulé au Liban.
Ce n'est en aucun cas un opérateur de mobile money au sens GSMA.**

### 1.2 Portail développeur : il n'y en a pas, mais il y a mieux et moins

**Aucun portail développeur de marque areeba** : pas de `developer.areeba.com`, pas de
`docs.areeba.com`, aucun lien « Developers » dans la navigation.

Ce qui existe à la place :

- **Deux pages HTML statiques d'intégration marchand**, publiques et sans compte :
  `www.areeba.com/documentations/areeba_docs.integration.html` (« Areeba Gateway Integration »,
  actuelle) et `.../integration.html` (« Hosted Checkout Integration », ancienne, « Published Time:
  Wed, 11 May 2022 »).
- **Une référence d'API complète, publique, sans compte** :
  `https://epayment.areeba.com/api/documentation/apiDocumentation/rest-json/version/100/api.html`,
  titre « Gateway API Reference Documentation », pied de page **« Copyright © 2026 Mastercard »**.

**C'est du Mastercard Payment Gateway Services (MPGS) en marque blanche — et je l'ai prouvé au
niveau DNS :**

```
epayment.areeba.com        -> 103.55.149.32   (nom canonique : ap.gateway.mastercard.com)
ap.gateway.mastercard.com  -> 103.55.149.32
```

Même adresse IP, et le nom canonique de `epayment.areeba.com` **est** celui de Mastercard.
*Mesure faite par mes soins le 2026-09-03.*

**Ce que cela signifie pour le référentiel** : documenter « l'API areeba » reviendrait à documenter
MPGS. Ce n'est ni un contrat propre à areeba, ni du mobile money.

### 1.3 Spécification téléchargeable

**INTROUVABLE.** *Vérifié personnellement* : la page « Downloads » de la référence d'API est **vide
de tout fichier**. Son contenu textuel intégral, tel que je l'ai extrait :

> « Downloads / Resources / Downloads / Glossary / FAQs / Copyright © 2026 Mastercard »

Aucun lien OpenAPI, Swagger, WADL, Postman ni PDF. La documentation est du HTML rendu, pas une
spécification machine. Le seul PDF public repéré est juridique
(`Simplify_Merchant_Terms_of_Use.pdf`), **non ouvert**, donc non vérifié.

### 1.4 Ce qui est visible sans inscription

**Ressources MPGS exposées** : Agreement, Authentication, Batch, Browser Payment, Gateway, Hosted
Checkout, Payment Plan, Session, Standalone Risk Assessment, Tokenization, Transaction, **Wallet**.
SDK JavaScript : Checkout, Click to Pay, Paypal, Risk, Rupay, Session, ThreeDS.

> ⚠️ La ressource nommée « **Wallet** » y est définie comme « An electronic service that allows
> payers to securely **store payment details (e.g. credit card details)** » — c'est un **coffre de
> cartes** type Click to Pay, **pas** un portefeuille de monnaie électronique. Le mot piège.

**Authentification**, **FACT**, verbatim :

> « The API username and password must be sent as **BASIC Authentication in the Authorization
> header** (refer to RFC 7617). Username and password are concatenated by a `:` and the whole string
> is **Base64 encoded**. — Username is **`merchant.anyMerchantID`**, password is `myPassword` […]
> `Authorization: Basic bWVyY2hhbnQuYW55TWVyY2hhbnRJRDpteVBhc3N3b3Jk` »

Seconde méthode admise : « **Certificate authentication.** ». Obtention du mot de passe : aucune
auto-inscription — « Your login credentials will be provided to you when you are successfully
**boarded onto the gateway** », puis *Admin > Integration Settings > Edit*, « **up to two
passwords** ».

**Routes**, **FACT** :

| Verbe | URL |
|---|---|
| POST | `https://epayment.areeba.com/api/rest/version/100/merchant/{MERCHANT_ID}/session` |
| GET | `https://epayment.areeba.com/api/rest/version/100/merchant/{MERCHANT_ID}/order/{ORDER_ID}` |

Script client : `https://epayment.areeba.com/static/checkout/checkout.min.js`, avec
`Checkout.configure({session:{id:'…'}})` puis `Checkout.showPaymentPage()` ou
`Checkout.showEmbeddedPage('#embed-target')`.

Opération : `"apiOperation": "INITIATE_CHECKOUT"`, `interaction.operation = "PURCHASE"`,
`order.{currency, amount, id, description}`, `transaction.source = "INTERNET"`. Réponse :
`{"checkoutMode":"WEBSITE","result":"SUCCESS","session":{"id":"SESSION0002302185668G00104591H4",…},
"successIndicator":"cc1b74e1f5c84bd8"}`.

**CONFLIT de version documentaire, non arbitré** : l'ancienne page (2022) donne les mêmes routes sur
`https://ap-gateway.mastercard.com/api/rest/version/**60**/…` avec
`"apiOperation": "CREATE_CHECKOUT_SESSION"`, tandis que la page actuelle donne **version 100** sur
`epayment.areeba.com` avec `INITIATE_CHECKOUT`. **Les deux pages sont en ligne simultanément sur
areeba.com.** La v100 est la plus récente (exemples horodatés `2025-01-07`). Je ne tranche pas.

**Formats**, **FACT** — avec une contradiction interne à la source :
`{merchantId}` — « This identifier can be **up to 12 characters** in length. Data may consist of the
characters 0-9, a-z, A-Z, '-', '_' — Min length: 1, **Max length: 40**. »
**CONFLIT dans la source elle-même** (12 contre 40), rapporté tel quel.
`session.id` : format observé `SESSION0002302185668G00104591H4` · `session.version` : 10 caractères
exactement · `successIndicator` : 16 à 32 caractères ASCII.

**Erreurs**, **FACT** — `error.cause`, sensible à la casse :
`INVALID_REQUEST` · `REQUEST_REJECTED` · `SERVER_BUSY` · `SERVER_FAILED`.
`error.validationType` : `INVALID` · `MISSING` · `UNSUPPORTED`.
Champs : `error.explanation` (≤1000), `error.field` (≤100), `error.supportCode` (≤100).
Codes transactionnels vus dans les exemples : `"result":"SUCCESS"`, `"status":"CAPTURED"`,
`"gatewayCode":"APPROVED"`, `"gatewayRecommendation":"PROCEED"`,
`"authenticationStatus":"AUTHENTICATION_SUCCESSFUL"`, `"risk":{"gatewayCode":"ACCEPTED",
"provider":"Brighterion"}`.

**Sandbox** : **le mot « sandbox » n'apparaît nulle part** dans la documentation d'intégration
areeba (0 occurrence sur le texte extrait). Un environnement de test est pourtant impliqué : la page
annonce « Use the below test card to test your integration » avec les libellés *Card Number /
Expiry Date / Security Code / Cardholder Name*, **mais les valeurs sont absentes du HTML servi** —
**je n'ai donc aucun numéro de carte de test à rapporter : INTROUVABLE.** Un « ACS emulator » 3DS est
documenté, et les exemples contiennent `"acsReference":"MPGS_ACS_SANDBOX"` et
`"dsReference":"MC_DS_SANDBOX"` — ce qui atteste d'un environnement de test Mastercard, mais **ses
conditions d'accès, quotas et limites ne sont documentés nulle part.**

---

## 2. Entité 2 — Areeba Guinée : un vrai mobile money, zéro API

### 2.1 Nature

Opérateur télécom guinéen complet, **ex-MTN Guinée**. Adresse « Coleah, route du Niger, Matam »,
service client 660 22 22 22 / 8800, `serviceclient.gn@areeba.gn`, « © 2026 Areeba Guinée ».
Source : `https://areeba.gn/` (consulté le 2026-09-03) **[OFFICIELLE, directe]**

Historique : MTN a acquis sa présence en Guinée via la marque Areeba rachetée à Investcom, puis a
**revendu son opération de Guinée-Conakry à l'État guinéen, officialisé le 30 décembre 2024**.
**[TIERCE]**

**CONFLIT non tranché sur le taux de détention final** : des sources tierces divergent — 75 % rachetés
fin décembre 2024 portant l'État à 87,5 %, contre un décret de décembre 2025 le portant à 100 %.
Ces pages n'ont pas été ouvertes une par une : **NON VÉRIFIÉ EN SOURCE PRIMAIRE**, non arbitré. Le
fait sûr est la cession actée le 30/12/2024.

### 2.2 Le service MoMo — *relevé personnellement sur la page officielle*

Code USSD principal : **`*440#`**. J'ai extrait **19 codes USSD** de la page :

```
*440#          menu principal MoMo          *440*2#        achat crédit
*440*4#        Startimes                    *440*4*1#      Canal+ / Easy TV
*440*4*2#      EDG (électricité)            *440*4*6*2#    Douanes
*440*4*6*3#    Vignette                     *440*4*6*4#    Contraventions
*440*8*3#      retrait sans carte GAB UBA
*100*1# *100*2# *100*3# *100*7# *100*8# *111#              (offres, hors MoMo)
*223*4# *223*5# *223*18# *223*20#                          (soldes, hors MoMo)
```

Services documentés, **FACT**, verbatim :

> **Transfert d'argent** — « Depuis `*440#`, transférez vers un proche, un client ou un partenaire.
> Le transfert national permet d'envoyer de l'argent partout en Guinée, vers un abonné MoMo comme
> vers un non-abonné : **frais de 1 000 GNF, de 2 000 GNF à 15 000 000 GNF**. Le transfert
> international permet d'envoyer vers plusieurs pays avec des **frais de 1 %**. »

Pays destinataires listés : Sénégal, Mali, Sierra Leone, Côte d'Ivoire, Guinée Bissau, Liberia,
Ghana, Bénin, Niger, Togo, **Cameroun**, Angola, Éthiopie, Lesotho, Madagascar, Malawi, Rwanda,
Ouganda, Zambie, Zimbabwe, El Salvador, Gambie, Congo B, Congo DRC.

Autres services : dépôt/retrait par agents agréés ; **retrait sans carte au GAB UBA** via `*440*8*3#`
entre **50 000 et 800 000 GNF** (code à 6 chiffres + code temporaire à 4 chiffres) ; **Bank to
Wallet** avec Ecobank, UBA, BSIC, First Bank ; paiement de factures ; paiement marchand.

**Le paiement vers un non-abonné est documenté** — c'est l'équivalent du `unregistered` du socle
GSMA (§ 3.4 de `00_socle_gsma.md`), sous une autre forme.

### 2.3 API : **INTROUVABLE**

*Vérifié personnellement.* Aucune page « API », « développeur » ou « documentation » sur `areeba.gn` ;
la recherche interne `?s=API` ne renvoie rien de tel ; pas de `sitemap_index.xml` (404).

La page Business liste 9 solutions (Flotte, Internet Dédié, VPN/MPLS, APN, Data Center, SMS Alert,
PABX, **USSD « Services interactifs sans Internet »**, Areeba Infini). L'entrée « USSD » est une
offre **commerciale**, sans aucune spécification technique publiée.

**Aucune API mobile money, aucun sandbox, aucun portail marchand technique.** Contact commercial :
`ebu.gn@areeba.gn`, 662 22 11 11.

---

## 3. Conformité au socle GSMA

**La grille doit être appliquée deux fois, parce qu'il y a deux entités.**

### 3.1 Entité 1 — areeba Liban

**La grille est sans objet.** G1..G22 mesurent un contrat de **mobile money** ; areeba Liban expose
un contrat de **paiement par carte** (MPGS). Les remplir produirait 22 divergences sans aucune
valeur informative — on ne mesure pas un acquéreur carte contre un standard de portefeuille mobile.

Le seul verdict utile est en amont : **hors périmètre du référentiel des opérateurs mobile money**.

Pour mémoire, si la direction voulait un jour intégrer areeba en tant que PSP carte : authentification
Basic RFC 7617 ou certificat, `POST /api/rest/version/100/merchant/{id}/session`, quatre `error.cause`,
onboarding commercial obligatoire, **pas de MSISDN, pas d'agents, pas d'USSD**.

### 3.2 Entité 2 — Areeba Guinée

| Réf. | Point de contrôle | Verdict |
|---|---|---|
| G1..G22 | **tous** | **NON DOCUMENTÉ** |

**Synthèse : 0 CONFORME · 0 DIVERGENT · 22 NON DOCUMENTÉ.**

Il n'existe **aucune** documentation d'API. Ce qui est publié est un catalogue de services au client
final : codes USSD, tarifs, plafonds, pays de destination. C'est précieux pour comprendre le
**métier** — et absolument inutilisable pour construire un **profil technique**.

---

## 4. TROUS À CALIBRER

### 4.1 Trou de nature, à trancher avant tout le reste

| # | Trou | Ce qui manque | Impact | Comment le lever |
|---|---|---|---|---|
| **T-ARE-00** | **De quel « Areeba » parle le cahier des charges ?** | Le `FZ-CDC-SANDBOX-2026-001` cite « Areeba » sans préciser l'entité. Les deux existent, aucune ne les relie. | **Tant que ce n'est pas tranché, tout travail sur Areeba risque de porter sur la mauvaise entreprise.** | **Question à poser à la direction. C'est l'action n°1.** |

Trois lectures possibles, et elles mènent à trois chantiers sans rapport :

1. **Areeba Guinée** — un opérateur mobile money réel, sans API → chantier commercial (§ 4.3).
2. **areeba Liban** — un PSP carte → hors périmètre mobile money, chantier différent (§ 4.2).
3. **Une confusion d'origine** — le nom est arrivé dans le cahier des charges par un raccourci de
   recherche → la ligne est à retirer du référentiel.

### 4.2 Si c'est areeba Liban

| # | Trou | Ce qui manque |
|---|---|---|
| **T-ARE-01** | **Pertinence** | Ce n'est pas du mobile money. Est-ce bien ce qu'on veut simuler ? |
| **T-ARE-02** | CONFLIT de version | v60 sur `ap-gateway.mastercard.com` contre v100 sur `epayment.areeba.com`, les deux pages en ligne. Non arbitré. |
| **T-ARE-03** | CONFLIT interne sur `{merchantId}` | « up to 12 characters » contre « Max length: 40 » dans le même document. |
| **T-ARE-04** | **Cartes de test** | Les libellés existent, **les valeurs sont absentes du HTML**. Aucun jeu de test possible. |
| **T-ARE-05** | Sandbox | Le mot n'apparaît pas ; un environnement de test 3DS est impliqué mais ses conditions, quotas et limites ne sont documentés nulle part. |
| **T-ARE-06** | `areeba.simplify.com/commerce/docs` | **Inaccessible** depuis l'environnement de recherche (timeouts répétés). Le domaine résout. Une seconde offre passerelle (« Simplify Commerce ») est **supposée**, non vérifiée. À reprendre depuis un autre réseau. |
| **T-ARE-07** | Contenu direct de `areeba.com` | Jamais obtenu sans proxy (403 Cloudflare). **À refaire depuis un navigateur réel si un fait doit être opposable.** |

### 4.3 Si c'est Areeba Guinée

| # | Trou | Ce qui manque |
|---|---|---|
| **T-ARE-10** | **Toute API** | Collecte, décaissement, callback, webhook, sandbox, référence marchand : **rien de public**. Le contrat est à négocier, pas à intégrer. |
| **T-ARE-11** | Statut réglementaire | Agrément d'émetteur de monnaie électronique de la **BCRG**, entité juridique porteuse. Les mentions légales de `areeba.gn` sont quasi vides : ni RCCM, ni capital, ni agrément. |
| **T-ARE-12** | Actionnariat final | 87,5 % fin 2024 contre 100 % fin 2025 : sources tierces divergentes, non tranché. Compte pour un contrat avec une entité publique. |
| **T-ARE-13** | Périmètre | **La Guinée est-elle dans le périmètre de la sandbox ?** Si le périmètre est camerounais, Areeba Guinée est hors sujet — même si le Cameroun figure dans ses pays de destination de transfert. |

---

## 5. Sources archivées

Dans `docs/contrats/sources/areeba/` :

| Fichier | Origine | Ce qu'il prouve |
|---|---|---|
| `areeba.gn_momo_2026-09-03.html` | `https://areeba.gn/momo/` | Le service MoMo réel : 19 codes USSD, tarifs, plafonds, pays |
| `epayment.areeba.com_downloads_2026-09-03.html` | page « Downloads » de la référence d'API | Qu'elle est **vide**, sous copyright Mastercard |
| `NOTES_VERIFICATION.txt` | mes mesures | La preuve DNS `epayment.areeba.com` = `ap.gateway.mastercard.com`, le 403 Cloudflare, l'extraction des codes USSD |

**Non archivable** : `www.areeba.com` (403 Cloudflare en récupération directe).

---

## 6. Niveau de confiance pour le futur profil opérateur

**FAIBLE — mais pour une raison différente des autres fiches.**

Ailleurs, la confiance est faible parce que l'information manque. Ici, elle est faible **parce que
la cible elle-même n'est pas identifiée**. Les faits recueillis sont solides et vérifiés : la
dualité des entités, la preuve DNS du socle Mastercard, les 19 codes USSD guinéens, l'absence
totale d'API côté Guinée. Ce qui manque n'est pas une source, c'est une **décision**.

**Recommandation.** Poser T-ARE-00 à la direction avant tout autre travail. Selon la réponse :
retirer la ligne du référentiel, la reclasser en « PSP carte » hors périmètre mobile money, ou
ouvrir un chantier commercial avec Areeba Guinée. **Ne surtout pas produire un profil « Areeba »
qui mélangerait les deux** — ce serait un profil qui ne correspond à aucune entreprise existante.
