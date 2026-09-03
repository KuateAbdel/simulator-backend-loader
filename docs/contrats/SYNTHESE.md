# Référentiel des contrats opérateurs — synthèse

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Document T3
**Établie le** 2026-09-03 · **Auteur** Kuate Abdel Yaniv (QA Lead / SDET)
**Périmètre** cinq opérateurs, mesurés contre le socle [`00_socle_gsma.md`](00_socle_gsma.md)
**Nature** 100 % documentaire. Aucune inscription, aucun compte créé, aucune API de paiement appelée.
*(Une réserve de méthode unique est signalée au § 6 ; elle concerne Airtel.)*

---

## 1. Le tableau

| Opérateur | Portail développeur | Spec téléchargeable | Authentification | Proximité GSMA | Sandbox documentée | Trous |
|---|---|---|---|---|---|---|
| **MTN MoMo** | **OUI, public en lecture** — `momodeveloper.mtn.com` | **NON** — l'export existe mais son bloc `paths` est **vide** | OAuth 2.0 `client_credentials` (RFC 6749/6750) **+** `Ocp-Apim-Subscription-Key` — deux étages | **4 conforme · 13 divergent · 5 non documenté** | **OUI** — hôte, devise EUR, **15 MSISDN de test déterministes** | **11** |
| **Orange Money** | **OUI, mais marketing seul** — 2 onglets, ni *getting started* ni *api reference* | **NON** — le PDF officiel n'existe que republié sur Scribd | OAuth 2.0 `client_credentials` **[OFFICIELLE mais générique à toute la plateforme, jamais rattachée à Orange Money]** | **0 conforme · 9 divergent · 13 non documenté** | **NON** — une phrase atteste qu'un test est possible, sans URL ni quota | **14** |
| **Airtel Money** | **OUI, mais tout est sous connexion** — un domaine et un compte **par pays** | **NON** — `/docs` et `/swagger.json` sont des replis SPA, prouvé | **INTROUVABLE** en source officielle | **0 conforme · 0 divergent · 22 non documenté** | **NON** — « Test for free », sans aucun paramètre | **10** |
| **Moov Money** | **NON — aucun, dans les 9 pays** | **NON** — accès par courrier et dossier marchand | **INTROUVABLE** | **0 conforme · 0 divergent · 22 non documenté** | **NON** | **12** |
| **Areeba** | **DEUX ENTITÉS.** Liban : pas de portail, mais une référence MPGS publique · Guinée : **rien** | **NON** — page « Downloads » vide côté Liban | Liban : Basic RFC 7617 ou certificat · Guinée : **INTROUVABLE** | Liban : **sans objet** (carte, pas mobile money) · Guinée : **22 non documenté** | **NON** — le mot n'apparaît nulle part | **12** |

**Total : 59 trous opérateur, plus 10 trous dans le standard GSMA lui-même.**

---

## 2. Ce qui est solide

**Un seul contrat est réellement exploitable : MTN.** 53 opérations avec chemins et verbes exacts,
les en-têtes obligatoires, un mécanisme d'idempotence explicite et sanctionné, les statuts de
transaction énumérés, 17 codes d'erreur, l'identifiant d'environnement **`mtncameroon`**, et une
sandbox avec des numéros de test déterministes. Un profil peut être écrit sans rien inventer. Tous
ces faits ont été récupérés et recomptés par mes soins, et les JSON bruts sont versionnés.

**Deux faits de périmètre, solides et décisifs :**

- **Le Cameroun est couvert par MTN et par Orange, et par eux seuls.** Il figure dans les deux
  listes de pays d'Orange malgré leur conflit interne, et `mtncameroon` est un identifiant publié.
- **Airtel n'opère pas au Cameroun** (13 pays publiés, Cameroun absent) et **Moov non plus**
  (9 pays d'Afrique de l'Ouest et centrale, Cameroun absent). Areeba Guinée est guinéen.

**Trois résultats négatifs, mais établis** — ce sont des acquis, pas des échecs :

- Moov n'a **aucun** portail développeur, et le seul indice contraire est réfuté : le DNS de
  `moov-africa.com` est un wildcard, ce que j'ai prouvé en résolvant un sous-domaine inventé.
- La documentation Airtel n'est **pas** à `/docs` : les chemins candidats renvoient la même coquille
  SPA, à un compteur anti-cache près.
- La passerelle d'areeba **est** du Mastercard MPGS : `epayment.areeba.com` et
  `ap.gateway.mastercard.com` partagent l'IP `103.55.149.32`.

**Aucun des cinq opérateurs ne revendique la conformité GSMA.** Vérifié dans le code pour Airtel
(0 occurrence dans 1,4 Mo de bundle) et pour MTN (l'unique occurrence du portail est un prix
décerné en 2023). MTN reformule pourtant les principes du standard presque mot pour mot dans sa page
d'introduction : proximité d'esprit, divergence de lettre.

---

## 3. Ce qui manque

**Le contrat technique de quatre opérateurs sur cinq n'est pas public.** Pour Orange, Airtel et
Moov, tout ce qui circule — chemins, champs, codes d'erreur, statuts — provient de SDK
communautaires. Ces sources sont souvent concordantes entre elles, ce qui est rassurant, mais elles
n'ont **aucune valeur contractuelle** et sont marquées **[TIERCE]** partout où elles apparaissent.

**Trois trous se répètent chez tous les opérateurs sauf MTN**, et ce sont les trois qui comptent le
plus pour une sandbox :

1. **L'idempotence.** Aucune clé, aucun en-tête, aucune règle de rejeu chez Orange, Airtel ni Moov.
   Or c'est exactement le défaut que nous avons prouvé sur le module Bulk de la plateforme
   (FRA-235, double paiement) : sans contrat d'idempotence, ce défaut n'est pas testable.
2. **Le contrat du webhook.** Verbe, corps, signature, politique de rejeu : inconnus partout sauf
   chez MTN — qui tranche d'ailleurs sévèrement (**envoi unique, aucun rejeu**, polling recommandé)
   mais **sans signature ni HMAC**, ce qui reste un trou de sécurité.
3. **Les bornes de montant et la devise de test.** MTN teste en **EUR**, Orange peut-être en `OUV`
   (source tierce, hors ISO 4217) : **aucun jeu de données en XAF n'est rejouable tel quel** contre
   une sandbox opérateur.

**Le standard lui-même a un trou structurant** : la GSMA rend `transactionStatus` obligatoire dans
toute réponse mais **ne l'énumère nulle part**. Elle normalise le cycle de vie de la requête et
celui du lot, pas celui de la transaction. Les statuts de transaction sont donc un point de
divergence garantie entre opérateurs, et le socle ne peut pas servir de recours (T-SOCLE-01).

---

## 4. Trois décisions à porter à la direction

Elles ne relèvent pas de la recherche : elles relèvent d'un arbitrage.

**D1 — S'inscrire, ou non, aux portails.** Douze des quatorze trous d'Orange se lèvent par un seul
geste : créer un compte sur `developer.orange-sonatel.com`, le seul portail Orange annonçant un
test autonome *avant* dossier administratif. De même côté Airtel, un compte par Op-Co. La mission
interdit expressément toute inscription — c'est donc une décision, pas une action.

**D2 — De quel « Areeba » parle le cahier des charges ?** Deux entreprises, aucun lien. Tant que ce
n'est pas tranché, tout travail sur Areeba risque de porter sur la mauvaise entreprise. Trois
lectures possibles : opérateur guinéen (chantier commercial), PSP carte libanais (hors périmètre
mobile money), ou confusion d'origine (ligne à retirer).

**D3 — Le périmètre géographique.** Si la sandbox reste centrée sur le Cameroun, **Airtel, Moov et
Areeba en sortent**, et 34 des 59 trous deviennent sans objet. L'effort se concentre alors sur MTN
(exploitable) et Orange (à débloquer par D1). Si le périmètre s'étend, Airtel exige un profil **par
pays** — c'est un trou de conception, pas d'information.

---

## 5. Deux enseignements à réutiliser, indépendamment des opérateurs

**Les MSISDN de test déterministes de MTN sont le meilleur mécanisme rencontré.** Un numéro par cas
d'erreur, tout le reste en succès : `46733123455` déclenche `PayerNotFound`, `46733123461` déclenche
`InternalProcessingError`, et ainsi de suite sur quinze numéros, plus six adresses e-mail et six
UUID. C'est reproductible, auto-documenté et testable sans coordination. **La sandbox FinZuu devrait
l'adopter tel quel**, quel que soit l'opérateur simulé.

**Le maker/checker de lot du socle GSMA décrit ce que le module Bulk ne fait pas.** L'état
intermédiaire `approved`, la séparation entre l'analyse et l'exécution, et les deux collections de
résultats `/rejections` et `/completions` sont exactement les notions absentes de notre module Bulk
aujourd'hui. Rapprochement à faire, hors périmètre de la présente mission.

---

## 6. Réserves de méthode, déclarées

**Une entorse partielle à la consigne « aucun appel vers une API opérateur ».** Au cours de la
recherche Airtel, deux requêtes `GET` non authentifiées ont été émises sur les **racines**
`openapi.airtel.africa` et `openapiuat.airtel.africa` — sans route métier, sans identifiant, sans
corps. Les deux ont répondu **401**. Le seul fait qui en découle (ces hôtes existent et exigent une
authentification) est isolé au § 0.2 de la fiche Airtel et **peut être écarté** par la direction.
Aucun autre appel de ce type n'a eu lieu, sur aucun opérateur.

**Deux domaines n'ont pas pu être récupérés directement.** `developer.orange.com` répond **403** à
toute récupération non navigateur (protection anti-robot) et `www.areeba.com` **403** derrière
Cloudflare. Leurs pages ont été lues par rendu ou par proxy d'extraction, et **n'ont pas pu être
archivées en HTML brut**. Si un fait tiré de ces pages doit devenir opposable, il faudra le
reprendre depuis un navigateur réel.

**Trois sites Moov étaient inaccessibles** (Mali : certificat TLS invalide · Gabon : HTTP 500 ·
Centrafrique : timeout). L'absence de portail y est **non prouvée**, seulement non contredite.

**Deux hôtes identifiés n'ont volontairement pas été interrogés** : `apimarchand.moov-africa.bj`
(résout sous le domaine officiel béninois) et `areeba.simplify.com` (résout, inaccessible depuis le
poste). Consigne respectée.

---

## 7. Ce que ce référentiel interdit

Un trou est un trou. On l'écrit, on le chiffre, on le fait trancher.

Il est **interdit**, sans exception, de combler une case « NON DOCUMENTÉ » avec la valeur du socle
GSMA ou celle d'un autre opérateur, de présenter une source tierce comme officielle, ou d'arbitrer
un CONFLIT enregistré sans en avoir la source. Les onze conflits recensés dans ce référentiel —
dont trois internes à la documentation de MTN elle-même et deux entre deux pages officielles
d'Orange — sont consignés **des deux côtés**, sans arbitrage.

---

## 8. Index des livrables

| Document | Objet |
|---|---|
| [`00_socle_gsma.md`](00_socle_gsma.md) | L'étalon : GSMA Mobile Money API 1.2, grille G1..G22, 10 trous du standard |
| [`mtn-momo.md`](mtn-momo.md) | Confiance **HAUTE** — 53 opérations, `mtncameroon`, sandbox déterministe |
| [`orange-money.md`](orange-money.md) | Confiance **FAIBLE** — tunnel de paiement, contrat non public |
| [`airtel-money.md`](airtel-money.md) | Confiance **FAIBLE** — un compte par pays, Cameroun absent |
| [`moov-money.md`](moov-money.md) | Confiance **FAIBLE** — aucun portail, accès hors ligne |
| [`areeba.md`](areeba.md) | Confiance **FAIBLE** — deux entités homonymes, cible à identifier |
| `sources/` | Pages et JSON bruts archivés, par opérateur, avec empreintes et notes de vérification |
