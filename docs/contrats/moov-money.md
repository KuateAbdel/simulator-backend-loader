# Moov Money (Flooz) — contrat opérateur

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Référentiel des contrats opérateurs · Fiche T2
**Rédigée le** 2026-09-03 · **Socle de référence** [`00_socle_gsma.md`](00_socle_gsma.md)
**Nature** 100 % documentaire. Aucun appel vers une API Moov, aucune inscription, aucun compte créé.

> **Verdict en une phrase.** **Aucun portail développeur public n'existe**, dans aucun des neuf pays
> du périmètre. L'accès à l'API Moov Money se fait par **démarche commerciale hors ligne** — courrier
> et dossier d'entreprise auprès de la filiale nationale — ou en passant par un agrégateur tiers.
> C'est un résultat négatif, et c'est un résultat utile : il ferme la question.

---

## 0. Avertissement préalable — l'homonyme qui fausse toute recherche

**`docs.moov.io`, `api.moov.io` et `github.com/moovfinancial` remontent en tête sur presque toutes
les requêtes « Moov API ». Ce n'est pas Moov Africa.** C'est **Moov Financial Inc.**, une fintech
américaine sans aucun lien capitalistique ni technique avec Moov Africa (groupe Maroc Telecom).

Source : `https://docs.moov.io/` (consulté le 2026-09-03) **[TIERCE — homonyme, hors sujet]**

Toute spécification récupérée sur ces domaines serait **entièrement hors sujet**. Ce piège est
consigné ici en tête de fiche parce qu'il est le plus susceptible de contaminer une reprise du
dossier par quelqu'un d'autre.

---

## 1. Le portail développeur

### 1.1 Il n'existe pas — **INTROUVABLE**

Vérifications faites, et ce qu'elles ont donné :

**a. Le sous-domaine `developer.moov-africa.com` est une page de parking.**
*Vérifié personnellement* (HTTP 200, 5 203 o, archivé). Contenu intégral du texte visible :

> « developer.moov-africa.com is a totally awesome idea still being worked on. Check back later. —
> Home Transfer Renew Domain Pricing Email About Us Help Your Account — Copyright © 2026 **Hover** »

**b. Et surtout : ce sous-domaine ne prouve rien du tout.**
*Vérifié personnellement.* Le domaine `moov-africa.com` porte un **DNS générique (wildcard)** qui
renvoie tout sous-domaine vers l'IP du bureau d'enregistrement Hover :

| Nom interrogé | Résolution |
|---|---|
| `developer.moov-africa.com` | `216.40.34.41` |
| `zzz-random-test-9x.moov-africa.com` | `216.40.34.41` — **identique** |

**C'est le point de méthode le plus important de cette fiche.** Sans ce contre-test, on aurait
conclu qu'un portail développeur est « en préparation » chez Moov. C'est faux : la page de parking
s'affiche pour *n'importe quel* nom inventé. **L'existence du sous-domaine `developer` n'est aucun
indice de projet de portail.** Toute source affirmant le contraire est à écarter.

**c. Les sites nationaux ne contiennent aucun contenu technique.**
*Vérifié personnellement, au mot près.* J'ai téléchargé les pages d'accueil, supprimé les balises
HTML, et recherché sur le **texte visible** les termes `API`, `APIs`, `développeur`, `developer`,
`sandbox`, `webservice`, `WSDL`, `SOAP` avec frontières de mot :

| Pays | Domaine | HTTP | Occurrences dans le texte visible |
|---|---|---|---|
| Bénin | `www.moov-africa.bj` | 200 (271 043 o) | **aucune** |
| Burkina Faso | `moov-africa.bf` | 200 (83 541 o) | **aucune** |
| Côte d'Ivoire | `www.moov-africa.ci` | 200 (360 609 o) | **aucune** |
| Togo | `moov-africa.tg` | 200 (309 442 o) | **aucune** |

*Précision d'honnêteté* : une première recherche sur le HTML brut avait remonté 4 à 20
« occurrences ». Elles étaient toutes des **faux positifs d'attributs** (`api` dans « rapide », noms
de classes CSS, etc.). Le résultat ci-dessus est celui de la mesure correcte, après suppression des
balises.

**d. Les sitemaps confirment.** Crawl intégral des sitemaps officiels du Bénin et du Burkina
(778 URL) : **zéro page** contenant *api*, *developer*, *développeur*, *webservice*, *sdk* ou
*sandbox*. Les pages les plus proches sont commerciales : `/devenir-marchand/`,
`/paiement-marchand/`, `/entreprise/`.
Sources : `https://www.moov-africa.bj/wp-sitemap.xml` (archivé) et
`https://moov-africa.bf/sitemap_index.xml` (consultés le 2026-09-03) **[OFFICIELLES]**

**e. Sous-domaines testés en DNS — NXDOMAIN** : `developer.moov-africa.ci`,
`developers.moov-africa.ci`, `api.moov-africa.ci` *(vérifié personnellement)*,
`api.moov-africa.bj`, `business.moov-africa.bj`, `developer.moov-africa.bj`.

**f. Une seule exception, et je ne l'ai pas franchie.** `apimarchand.moov-africa.bj` **résout**
(`41.138.88.97`), sous le domaine officiel du Bénin — *vérifié personnellement*.
**Cet hôte n'a pas été interrogé** : la mission interdit tout appel vers une API opérateur. Je ne
peux donc rien affirmer sur ce qu'il sert. Le seul fait établi est qu'un nom d'hôte à vocation
d'API marchande existe dans le DNS officiel béninois.

### 1.2 État des sites par pays

| Pays | Domaine | État constaté le 2026-09-03 |
|---|---|---|
| Côte d'Ivoire | `www.moov-africa.ci` | En ligne, protégé Incapsula (403 sur `robots.txt`) · pas de section développeur |
| Bénin | `www.moov-africa.bj` | En ligne (WordPress/WooCommerce) · pas de section développeur |
| Burkina Faso | `moov-africa.bf` | En ligne · pas de section développeur |
| Togo | `moov-africa.tg` | En ligne (`www.` ne résout pas) · pas de section développeur |
| Niger | `www.moov-africa.ne` | En ligne · pas de section développeur |
| Tchad | `www.moov-africa.td` | En ligne · pas de section développeur |
| Mali | `www.moov-africa.ml` | **Certificat TLS invalide** — non consultable |
| Gabon | `www.moov-africa.ga` | **HTTP 500** — non consultable |
| Centrafrique | `www.moov-africa.cf` | **Timeout** — non consultable |

Pour les trois derniers, **l'absence de portail n'est pas prouvée, seulement non contredite**. La
distinction est maintenue.

---

## 2. Spécification téléchargeable sans compte

**INTROUVABLE.** Aucun fichier OpenAPI, Swagger, WSDL ou PDF de spécification n'est publié sur un
domaine `moov-africa.*` ni `maroctelecom.*`.

La procédure d'obtention documentée est explicitement **hors ligne**. Citation d'une source tierce
décrivant le parcours au Togo :

> « Vous envoyez à Moov Togo un courrier spécifiant que vous voulez implémenter le paiement par
> Flooz sur votre site marchand » — puis remise du RCCM, de la carte d'opérateur et d'une pièce
> d'identité ; **la documentation API est remise après ouverture du compte marchand**, avec
> fourniture d'une IP statique.

Source : `https://github.com/Tech228/FloozAPI/blob/master/Procedures.md` (consulté le 2026-09-03)
**[TIERCE — dépôt communautaire, ne cite aucune URL officielle]**

**DÉDUIT** : l'exigence d'une **IP statique** signale un contrôle d'accès par liste blanche
réseau, en amont de toute authentification applicative. Si elle se confirme, c'est une contrainte
d'architecture pour la sandbox et pour tout environnement de test FinZuu — mais elle n'est pas
sourcée officiellement.

→ **Rien n'a pu être versé au titre d'une spécification** dans `docs/contrats/sources/moov-money/`.

---

## 3. Ce qui est visible SANS inscription

**Depuis une source officielle : rien.** Ni mécanisme d'authentification, ni route, ni format
d'identifiant, ni code d'erreur, ni sandbox. La § 1 en apporte la mesure.

### 3.1 Ce qu'affirme un SDK communautaire — à traiter comme non confirmé

Le seul corpus technique concret en circulation vient d'un SDK non officiel, **qui ne cite aucune
source officielle** et précise lui-même de contacter Moov si les URL ne correspondent pas.

Source : `https://github.com/v1p3r75/moov-money-api-php-sdk` (consulté le 2026-09-03) **[TIERCE]**

| Élément | Valeur affirmée **[TIERCE]** |
|---|---|
| Protocole | **SOAP / WSDL** — pas REST |
| Sandbox | `https://testapimarchand2.moov-africa.bj:2010/com.tlc.merchant.api/UssdPush?wsdl` |
| Production | `https://apimarchand.moov-africa.bj/com.tlc.merchant.api/UssdPush?wsdl` |
| Authentification | `username` / `password` + clé de chiffrement **AES-256 de 32 caractères** (valeur d'exemple affichée dans le README : `tlc12345tlc12345tlc12345tlc12345`) |
| Opérations | `pushTransaction`, `pushWithPendingTransaction`, `getTransactionStatus`, `transferFlooz`, `getBalance`, `getMobileStatus`, `cashIn`, `airTime` |
| Champs | `telephone`, `amount`, `message`, `data1`, `data2`, `fee`, `referenceId`, `destination`, `walletId`, `subscriberTelephone` |
| Codes | **seulement** `0` = succès, `100` = en attente. Aucune table d'erreurs. |

**Quatre réserves, à porter telles quelles au référentiel :**

1. Ces URL sont ancrées sur le domaine **béninois uniquement**. Rien ne prouve qu'elles valent pour
   CI, BF, TG, ML, NE, TD, GA, CF. **Ne pas extrapoler d'un pays à l'autre.**
2. Le préfixe `com.tlc.merchant.api` suggère un socle d'éditeur tiers (« TLC »), pas une API maison
   Moov. Non confirmé.
3. **Deux codes de retour seulement.** Ce n'est pas une table d'erreurs, c'est un fragment. Toute
   assertion d'erreur bâtie là-dessus serait creuse.
4. **CONFLIT, non arbitré.** Une source tierce décrit pour la Côte d'Ivoire un mode principal
   *USSD Push* **avec un mode de repli USSD guidé** ; le SDK n'en documente aucun.
   `https://kolonell.com/fr/blog/integrer-moov-money-benin-togo-site-web-2026` **[TIERCE]** contre
   `github.com/v1p3r75/moov-money-api-php-sdk` **[TIERCE]**. Aucune des deux n'est officielle :
   **je ne tranche pas.**

### 3.2 Sandbox opérateur

**Aucune inscription sandbox publique.** Le seul hôte de test évoqué
(`testapimarchand2.moov-africa.bj:2010`) est cité par un tiers et suppose **déjà** des identifiants
marchands. Il n'a pas été interrogé.

---

## 4. La voie réelle : les agrégateurs

C'est, en pratique, la seule voie **documentée publiquement** vers Moov Money.
**Attention : les API ci-dessous sont celles de l'agrégateur, jamais celles de Moov.** Aucune ne
renvoie vers une documentation officielle Moov.

**Vérifiés page par page** :

| Agrégateur | Ce qui est documenté | Source **[TIERCE]** |
|---|---|---|
| **LigdiCash** | API propre (`POST /pay/v01/straight/checkout-invoice/create`, base `https://app.ligdicash.com`). Moov Bénin y est un simple opérateur : `operator_id: 2`, `operator_name: MOOV BENIN`, format **`229XXXXXXXX`**, **minimum 100 XOF**, validation par USSD Push. | `developers.ligdicash.com/api-paiement/payin-sans-redirect/operateurs/moov-benin` |
| **pawaPay** | Moov exposé sous les codes **`MOOV_BEN`** (Bénin, XOF) et **`MOOV_BFA`** (Burkina, XOF), tous deux en `PROVIDER_AUTH`, **sans décimales**. | `docs.pawapay.io/v2/docs/providers` |
| **Senfenico** | « une seule API » Mobile Money. Couverture Moov annoncée : Burkina + Bénin ; Niger et Togo « bientôt ». | `senfenico.com/fr/moov-money-api` |

**Cités mais non vérifiés page par page** : CinetPay, PayDunya, FedaPay, KkiaPay, Semoa,
Paymetrust. `docs.cinetpay.com` **n'a pas résolu** depuis l'environnement de recherche : sa
couverture Moov (souvent annoncée CI/BF/BJ/TG/ML) reste **non vérifiée**.

**Deux faits d'agrégateur méritent d'être retenus**, non parce qu'ils décrivent Moov, mais parce
qu'ils sont les seuls chiffres publics associés à Moov : le format `229XXXXXXXX` et le minimum de
100 XOF (LigdiCash), et l'absence de décimales en XOF (pawaPay). Ils sont **cohérents entre eux**
et cohérents avec le fait que le XOF n'a pas de subdivision d'usage. Ils restent des affirmations
d'intermédiaire.

---

## 5. Conformité au socle GSMA

Grille G1..G22 de [`00_socle_gsma.md`](00_socle_gsma.md) § 7.

**Le verdict est uniforme et il faut le dire tel quel : NON DOCUMENTÉ sur les 22 points.**

Aucune source officielle Moov ne documente quoi que ce soit du contrat. Remplir une seule case
autrement reviendrait à promouvoir un SDK communautaire au rang de contrat, ce que la mission
interdit expressément.

| Réf. | Point de contrôle | Verdict | Indice tiers, sans valeur contractuelle |
|---|---|---|---|
| G1 | Authentification | **NON DOCUMENTÉ** | `username`/`password` + AES-256 **[TIERCE]** |
| G2 | URI et versionnage | **NON DOCUMENTÉ** | SOAP `com.tlc.merchant.api/UssdPush?wsdl`, sans version **[TIERCE]** |
| G3 | Identification des parties | **NON DOCUMENTÉ** | `telephone`, `destination`, `walletId` **[TIERCE]** |
| G4 | Format MSISDN | **NON DOCUMENTÉ** | `229XXXXXXXX` pour le Bénin — **source agrégateur**, pas Moov |
| G5 | Montant | **NON DOCUMENTÉ** | `amount` et `fee` **[TIERCE]** ; « sans décimales » en XOF selon pawaPay |
| G6 | Références de transaction | **NON DOCUMENTÉ** | `referenceId` **[TIERCE]** |
| G7 | Types de transaction | **NON DOCUMENTÉ** | 8 opérations SOAP nommées **[TIERCE]** |
| G8 | **Idempotence** | **NON DOCUMENTÉ** | aucun indice, même tiers |
| G9 | Récupération de réponse perdue | **NON DOCUMENTÉ** | `getTransactionStatus` **[TIERCE]** — consultation, pas récupération |
| G10 | Notification asynchrone | **NON DOCUMENTÉ** | `pushWithPendingTransaction` et le code `100` suggèrent un modèle d'attente, sans contrat |
| G11 | Objet d'erreur | **NON DOCUMENTÉ** | aucun |
| G12 | Codes d'erreur | **NON DOCUMENTÉ** | `0` et `100` seulement **[TIERCE]** |
| G13 | Cycle de vie de la requête | **NON DOCUMENTÉ** | `100` = en attente **[TIERCE]** |
| G14 | Cycle de vie de la transaction | **NON DOCUMENTÉ** | aucun |
| G15 | Traitement par lot | **NON DOCUMENTÉ** | aucun |
| G16 | Solde et statut de compte | **NON DOCUMENTÉ** | `getBalance`, `getMobileStatus` **[TIERCE]** |
| G17 | Cotation / frais | **NON DOCUMENTÉ** | champ `fee` **[TIERCE]** |
| G18 | Contrepassation | **NON DOCUMENTÉ** | aucune opération de reversal parmi les 8 citées |
| G19 | Pagination | **NON DOCUMENTÉ** | sans objet en SOAP |
| G20 | Canal d'origine | **NON DOCUMENTÉ** | le canal est **imposé** : USSD Push **[TIERCE]** |
| G21 | Supervision | **NON DOCUMENTÉ** | aucun |
| G22 | Sandbox et limites | **NON DOCUMENTÉ** | un hôte de test cité, exigeant déjà des identifiants **[TIERCE]** |

**Synthèse : 0 CONFORME · 0 DIVERGENT · 22 NON DOCUMENTÉ.**

Une observation d'architecture, qui n'est pas un verdict : si le protocole est bien **SOAP**, alors
Moov Money est **structurellement étranger** au socle GSMA, qui est REST/JSON de bout en bout
(§ 1 du socle). Ce n'est pas noté DIVERGENT parce qu'aucune source officielle ne l'établit — c'est
une hypothèse, et elle est écrite comme telle.

---

## 6. TROUS À CALIBRER

Ici, le trou n'est pas dans un champ : **c'est le contrat entier qui manque.** Les entrées
ci-dessous découpent ce vide en décisions que la direction peut trancher séparément.

| # | Trou | Ce qui manque exactement | Impact sur la sandbox | Comment le lever |
|---|---|---|---|---|
| **T-MOOV-01** | **Le contrat, en totalité** | Aucune spécification publique, aucun portail, aucun document officiel. | Aucun profil Moov ne peut être construit sur des faits. Tout serait inventé. | Courrier + dossier marchand auprès de la filiale (§ 2). |
| **T-MOOV-02** | **Protocole : SOAP ou REST ?** | SOAP/WSDL affirmé par un seul SDK tiers, contredit par rien mais confirmé par rien. | Décision d'architecture structurante : un simulateur SOAP n'a rien de commun avec un simulateur REST. **Trou n°1.** | Idem. |
| **T-MOOV-03** | **Portée géographique des endpoints** | Les seules URL connues sont **béninoises**. Rien pour CI, BF, TG, ML, NE, TD, GA, CF. | Un profil « Moov » unique serait faux si chaque filiale a sa pile. | Idem, filiale par filiale. |
| **T-MOOV-04** | **Codes d'erreur** | Deux valeurs (`0`, `100`), toutes deux de succès ou d'attente. **Aucun code d'échec connu.** | Aucun scénario d'erreur ne peut être simulé. | Idem. |
| **T-MOOV-05** | **Idempotence et rejeu** | Aucun indice, même tiers. `referenceId` est-il unique ? contraint ? rejouable ? | Le double paiement ne peut pas être testé. | Idem. |
| **T-MOOV-06** | **Contrat de notification** | Le code `100` « en attente » implique une reprise asynchrone dont **rien** n'est connu : rappel, scrutation, délai, signature. | Le flux asynchrone entier est à inventer. | Idem. |
| **T-MOOV-07** | **Liste blanche d'IP** | Exigence d'IP statique affirmée **[TIERCE]**. Non confirmée, portée inconnue. | Si vraie, elle contraint l'hébergement de la sandbox et de tout environnement de test. | Idem. |
| **T-MOOV-08** | **Mode de repli USSD** | CONFLIT non arbitré (§ 3.1) : repli guidé pour la CI ou non. | Change la modélisation du parcours client. | Idem. |
| **T-MOOV-09** | **Ce que sert `apimarchand.moov-africa.bj`** | L'hôte résout dans le DNS officiel ; il n'a pas été interrogé, par respect de la consigne. | Seul point de contact officiel identifié — et non exploré. | Une autorisation explicite, ou la filiale. |
| **T-MOOV-10** | **Mali, Gabon, Centrafrique** | Sites non consultables (TLS invalide / 500 / timeout). L'absence de portail y est **non prouvée**. | Trois pays du périmètre restent non couverts par la recherche. | Nouvelle tentative, ou contact filiale. |
| **T-MOOV-11** | **Format du MSISDN** | `229XXXXXXXX` vient d'un **agrégateur**, pas de Moov, et ne vaut que pour le Bénin. | Validation des numéros arbitraire pour les huit autres pays. | Documentation Moov. |
| **T-MOOV-12** | **Montants : minimum, maximum, décimales** | 100 XOF minimum et « sans décimales » viennent d'agrégateurs. | Tests aux limites sans oracle. | Idem. |

**Décision à porter à la direction.** Contrairement à Orange, **aucun de ces trous ne se lève par
une inscription en ligne** : il n'y a pas de portail. La seule voie est une **démarche commerciale
auprès de chaque filiale nationale**, avec dossier d'entreprise. C'est un délai et un coût
administratif, pas une action technique — et cela doit être arbitré avant toute planification d'un
profil Moov dans la sandbox.

**Chemin de contournement à évaluer** : passer par un agrégateur (§ 4). On y gagne une API
documentée et un sandbox accessible ; on y perd le contrat opérateur lui-même — la sandbox
simulerait alors *l'agrégateur*, pas *Moov*. C'est un choix de périmètre, à trancher explicitement.

---

## 7. Sources archivées

Dans `docs/contrats/sources/moov-money/` :

| Fichier | Origine | Ce qu'il prouve |
|---|---|---|
| `parking_developer.moov-africa.com_2026-09-03.html` | `http://developer.moov-africa.com/` | La page de parking Hover, texte intégral |
| `sitemap_moov-africa.bj_2026-09-03.xml` | `https://www.moov-africa.bj/wp-sitemap.xml` | L'index du sitemap officiel béninois |
| `NOTES_VERIFICATION.txt` | mes propres mesures | Wildcard DNS, NXDOMAIN, zéro terme technique au mot près |

**Non archivable** : aucune spécification, il n'en existe pas de publique.

---

## 8. Niveau de confiance pour le futur profil opérateur

**FAIBLE — et plus faible que pour tout autre opérateur de ce référentiel.**

Ce qui est solide : l'**absence** de portail développeur public est établie par plusieurs mesures
convergentes et par un contre-test DNS qui écarte le seul faux indice. Le fait que l'accès soit
contractuel et hors ligne est cohérent entre sources. Le piège de l'homonyme est identifié.

Ce qui ne l'est pas : **absolument tout le reste**. Il n'existe pas un seul nom de champ, une seule
route, un seul code d'erreur Moov Money qui soit sourcé officiellement.

**Recommandation.** Classer Moov Money en *accès contractuel hors ligne, spécification non
publique*. **Ne jamais inscrire dans le profil un endpoint ou un code d'erreur autre que
« fourni par la filiale après signature ».** Les valeurs du SDK GitHub peuvent servir d'indice
d'architecture — SOAP, USSD Push — mais **jamais** de contrat.
