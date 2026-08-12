# Produits, souscriptions et crédit — ce que le CDC dit, mot pour mot

> Écrit le **12/08/2026**, à partir d'une lecture **directe** de
> `Cahier_Charges_Loader_FinZuu_v1_2_final.docx` (1197 lignes extraites) et de
> mesures sur les OpenAPI **vivants** de product-service et collect-service.
>
> **Pourquoi ce document existe.** Trois questions de Yaniv ce jour-là —
> « on crée les produits LENDING ? », « le client souscrit à un LENDING ? »,
> « `loan_json.json`, c'est pour les prêts de Duhamel ? » — ont montré que la
> réponse vivait dans nos têtes et dans dix fichiers, pas dans un endroit
> lisible. Chaque affirmation ci-dessous porte sa **ligne de CDC** ou sa
> **mesure**. Rien n'y est déduit.

---

## 1. La question qui compte : souscrit-on un client à un produit de crédit ?

**Non. Jamais.**

Le mot « souscri- » apparaît **14 fois** dans le CDC. **Toujours** avec
« Collecte ». **Jamais** avec « Prêt ».

`UC-13`, ligne 202, point 4 :

> « Il **souscrit** le client à 1 à 3 produits **Collecte**
> (CASH, CASH_DAT, PRODUCT) selon son profil segmenté. »

Un produit de crédit sert autrement — `UC-02`, ligne 549 :

> « Un **prêt** est créé, référencé au client, avec un montant et une durée
> conformes au catalogue produits. »

**La distinction est structurelle** : une souscription Collecte *attache* un
produit à un client (`PUT /clients/subscribe`). Un prêt est une **entité
distincte**, générée depuis le catalogue crédit, avec son propre cycle de vie
(décaissement → remboursements → `REPAID`/`DEFAULTED`).

> **Le serveur ne l'interdit pas.** `FRA-230`, mesuré le 09/08 : `PUT /subscribe`
> avec un `product_id` LENDING renvoie **200**. Le refus est le nôtre
> (`D-CLI-10`). *Le permis n'est pas le juste.*

---

## 2. Crée-t-on les produits de crédit ? Oui.

`UC-11`, ligne 161 :

> « Le catalogue produits Collecte (CASH, CASH_DAT, PRODUCT) **et Prêt (Nano,
> Macro, BNPL, ReadyToGo)** est créé et rattaché aux Companies éligibles selon
> leur licence. »

`EF-` ligne 818 :

> « Le Loader DOIT s'appuyer sur le **catalogue produits crédit officiel** validé
> par la Direction Technique le 20 juillet 2026, couvrant les produits Nano,
> Macro, BNPL et ReadyToGo. »

Donc : **on crée les 4 produits de crédit**, et **on n'y souscrit personne**.
Ils sont la *référence* depuis laquelle `UC-02` génère des prêts.

---

## 3. `loan_json.json` — ce que c'est exactement

C'est l'**Annexe E**, « Catalogue produits crédit officiel (AJOUT V1.2) »,
ligne 1137 :

> « Le catalogue produits crédit officiel, validé par la Direction Technique le
> 20 juillet 2026, définit les quatre produits crédit FinZuu avec leur
> **segmentation par risque**. »

Et son usage, ligne 290 (`Type 2 — Vie crédit APPROVED`) :

> « … **décaissement d'un prêt selon le catalogue `loan_json.json` officiel et
> selon le produit et le montant retournés par Faker**, cycle de remboursement
> journalier avec évènements `REPAY_LOAN` programmés selon le profil, et clôture
> du prêt en état `REPAID` ou `DEFAULTED` en fin de cycle. »

Il est lié à la méthodologie Duhamel — ligne 29 :

> « Intégration de la **méthodologie de simulation comportementale du référent
> loan-simulation (Duhamel)** … 4 profils … Annexe D Méthodologie de simulation,
> Annexe E Catalogue produits crédit officiel. »

### Ce que le fichier porte réellement — mesuré

| Produit | Catégorie source | → cibles (`D-PRD-4`) | Durée | Taux | Min | Max |
|---|---|---|---:|---:|---:|---:|
| Nano | `Individual` | INDIVIDUAL | 15 j | 7–25 % → **24 %** | 5 000 | 200 000 |
| Macro | `Business` | CORPORATE | 15 j | 7–25 % → **24 %** | 25 000 | 600 000 |
| BNPL | `Any` | INDIVIDUAL **+** CORPORATE | 30 j | 7–25 % → **24 %** | 5 000 | 500 000 |
| ReadyToGo | `Any` | INDIVIDUAL **+** CORPORATE | 15 j | 7–25 % → **24 %** | 20 000 | 1 000 000 |

**Le taux est borné à 24 %, pas à 25 %.** `EF-35`, ligne 708 : « plafonds d'usure
BEAC/COBAC (taux **inférieur ou égal à 24** pour cent annuel) ». Le fichier
annonce 25 % : la borne est une **correction**, pas une recopie.

**`Any` n'existe pas dans l'enum serveur.** `ProductCategory = ['INDIVIDUAL',
'CORPORATE']` — mesuré sur l'OpenAPI. D'où `INV-PRD-04` (422) et le dédoublement
`D-PRD-4` : 4 produits déclarés → **6 créations**, avec des noms distincts
(`D-12`).

**Chaque produit porte `amount_by_segment`** — les 5 fourchettes de l'Annexe E
(`Very Low` → `Very High`). C'est la source de `UC-02` point 2, ligne 551 :

> « Le Loader détermine la **fourchette de montant selon le segment de risque** »

---

## 4. Qui reçoit un prêt ? Seuls les APPROVED.

Le CDC définit **trois types de vie** (chapitre 6.6) :

| Type | Population | Prêt ? | UC |
|---|---|---|---|
| **1** — vie commune | **100 % des 2000** (ligne 287) | non | `UC-14`, `UC-15` |
| **2** — cycle crédit | `decision_status = APPROVED` | **oui** | `UC-01` à `UC-04`, `UC-15` |
| **3** — sans crédit | `DECLINED` ou `NOT SCORED` | **non** | `UC-16`, `UC-17` |

Ligne 292, sur le Type 3 :

> « Ces clients **ne reçoivent aucun prêt et ne génèrent aucun événement de
> crédit** dans leur historique. »

Et `EF-` ligne 855 est catégorique :

> « … **sans jamais générer** d'événement de crédit (`CREATE_LOAN`, `REPAY_LOAN`,
> `SET_DPD`) pour ces clients. »

> **Type 2 s'ajoute à Type 1, il ne le remplace pas.** Ligne 290 : « **En plus de
> la vie commune de Type 1**, ces clients entrent dans la couche cycle crédit. »
> C'est ce qui a fait corriger le diagramme `04` (un `alt` exclusif y privait
> 700 clients APPROVED de toute vie commune).

---

## 5. Les deux impasses mesurées, et pourquoi elles ne sont pas des oublis

### 5.1 `A-02` — la source du scoring n'existe pas

Ligne 183 décrit ce que Faker devrait rendre :

> « … **décision de scoring APPROVED ou DECLINED, produit sélectionné, montant
> sélectionné, segment de risque** et historique de crédit éventuel. »

**Mesure du 11/08** : ces quatre champs appartiennent tous à la **famille B** de
Faker. Nos 2000 clients viennent nécessairement de la **famille A**, la seule
non plafonnée — et elle n'en porte **aucun**. `metadata.behavior_segment` vaut
`0.0` dans 14 tirages sur 15.

Le CDC décrit donc un chemin que la source de données ne permet pas. C'est
`A-02` : « `EF-80` inapplicable tel qu'écrit ».

**Recommandation appliquée le 12/08** pour le segment : il est dérivé de la
**même strate** que `solde_initial()` — les onze signaux `quick_win` que la
famille A porte réellement, projetés sur les cinq valeurs de l'Annexe E. Rien
n'est inventé ; c'est le même signal mesuré, exprimé sur l'axe que le serveur
offre. Distribution obtenue : `1,8 / 24,0 / 50,4 / 22,8 / 1,0 %`, monotone avec
le solde.

### 5.2 `A-11` — la proportion APPROVED n'est fixée nulle part

Le CDC nomme Type 2 et Type 3 « sous-populations » et **ne donne aucun
pourcentage**. Recherche exhaustive sur les 1197 lignes : aucune proportion.

Conséquence : le nombre de prêts simulés est **indéterminé**, donc `CR-10`
(« sur 100 prêts générés ») n'a pas de cible. **Arbitrage ouvert.**

---

## 6. Le catalogue Collecte — et le terme du dépôt à terme

### 6.1 Les six produits, croisement complet `PolicyType` × `Category`

| `PolicyType` | INDIVIDUAL | CORPORATE | Rôle métier |
|---|---|---|---|
| `CASH` | `Cotisation 20000/mois` 🔶 | `DEMO_Cotisation Commercants` | **produit d'entrée** — épargne régulière |
| `CASH_DAT` | `DEMO_Depot a Terme 6 Mois` | `DEMO_Depot a Terme Entreprise 12 Mois` | suppose une capacité d'épargne |
| `PRODUCT` | `plastique` 🔶 | `DEMO_Collecte Cacao` | collecte **en nature** |

🔶 = **préexistant** (`D-PRD-9`) : retrouvé, jamais recréé.

**L'ordre n'est pas indifférent** (`D-CLI-13`) : le panier suit
`CASH → CASH_DAT → PRODUCT`. Le premier part à l'onboarding, parce que
`OnboardClientSchema` exige `product_id` dès le premier appel. Un client dont
l'unique produit serait `plastique` ne serait pas un client d'épargne.

**Le nombre dépend du segment** — `UC-13` point 4 le dit littéralement : « selon
son **profil segmenté** ».

### 6.2 Un dépôt à terme sans terme — le manque était réel

**Mesure de l'OpenAPI vivant de product-service, 12/08.**
`CollectPolicySchema` porte **treize** champs :

```
name · type · interest_type · interest_rate · interest_x · vat
measure · measure_price · amount_min · amount_max
penalty_amount · penalty_percent · penalty_type
```

**Aucun n'est une durée.** `LendingPolicySchema` en a **quatre** :
`loan_duration`, `reconduction_day`, `recovery_day`, `penalty_day`.

Le terme d'un `CASH_DAT` ne pouvait donc vivre que dans le **nom** du produit
(« 6 Mois »), illisible par le code.

**Où il vit désormais** : `ProduitCollecte.duree_mois` (6 et 12), avec un
invariant qui refuse un `CASH_DAT` sans terme **et** un `CASH` avec terme. Il se
matérialise à la souscription dans **`CollectSchema.end_date`** — le seul champ
temporel que collect-service expose.

### 6.3 Les deux préexistants portent des valeurs de test — `A-10`

**Mesure du 12/08 sur le serveur TEST :**

| | `Cotisation 20000/mois` | `plastique` |
|---|---|---|
| `interest_rate` | **99,0 %** *(mensuel)* | 22,0 % |
| `amount_min → max` | 1 000 → **100 000** | **3,0 → 3,0** |
| `measure` | KILOGRAM | LITER |
| `vat` | 0 | 3,0 |
| préfixe `DEMO_` | **non** | **non** |

Le **produit d'entrée de 1600 clients INDIVIDUAL** porte 99 % d'intérêt mensuel,
et `plastique` n'accepte qu'une quantité de **exactement 3**. Notre catalogue les
*décrit* autrement (1 000 → 1 000 000 à 5 %) mais ces valeurs ne sont **jamais
envoyées** — `preexistant=True`.

Deux conséquences : la démo **dépend de l'état d'un environnement partagé**, et
1600 clients `DEMO_` s'attachent à un produit **qui n'est pas à nous**, alors que
la règle est de ne pas écrire sur le partagé. **Arbitrage `A-10` ouvert** ;
recommandation : créer nos équivalents, **12 créations au lieu de 10**.

---

## 7. Ce que product-service accepte, exactement

`CreateProductSchema` — mesuré, `*` = requis :

```
* type              ProductType        COLLECT | LENDING
* name              string
  short_name        string | null
  description       string | null
* category          ProductCategory    INDIVIDUAL | CORPORATE   (pas de ANY)
  segment           ProductSegment     défaut 'ANY' — 6 valeurs, comme ClientSegment
  policy_id         string | null
  policy            CollectPolicySchema | LendingPolicySchema
  subscription_fees number             défaut 0
```

Enums mesurées :

```
PolicyType     CASH · CASH_DAT · PRODUCT
PolicyMeasure  KILOGRAM · LITER
InterestType   DAILY · FORTNIGHTLY · MONTHLY
PenaltyType    AMOUNT · PERCENT
ProductSegment ANY · VERY_LOW · LOW · MEDIUM · HIGH · VERY_HIGH
```

> **`segment` côté produit signifie « quel segment ce produit vise ».** Mesure du
> 12/08 : **les 8 produits du serveur portent `ANY`**, et notre catalogue l'émet
> en dur. `ANY` = ouvert à tous. Aucun conflit client/produit n'est donc possible
> aujourd'hui. Le jour où un produit ciblerait une strate,
> `_produits_compatibles()` est l'endroit où l'ajouter.

> **`interest_x` n'a aucune description dans le contrat.** Sa sémantique est
> inconnue. On ne la devine pas ; on ne l'utilise pas.

---

## 7 bis. Le produit est-il relié à la Company ? **Non.**

Question de Yaniv, 12/08. La réponse est mesurée, pas déduite.

**Le mot « company » apparaît ZÉRO fois dans tout le contrat OpenAPI de
product-service.** Ni champ dans `CreateProductSchema`, ni route. Ses dix routes
sont : trois sur les policies, six sur les products, une `/health`. L'unique
occurrence de « lender » est dans la *description* du service (« Service unique
de gestion des produits pour les modules lender et collecte ») — décorative.

Or `UC-11`, ligne 161, exige :

> « Le catalogue produits Collecte (CASH, CASH_DAT, PRODUCT) et Prêt (Nano,
> Macro, BNPL, ReadyToGo) est créé **et rattaché aux Companies éligibles selon
> leur licence**. »

**Troisième occurrence du même motif**, après `EF-26` (Client → Kiosque) et
`D-CLI-6` (Client → Company) : le CDC exige un lien que le serveur ne porte pas.

### Où le lien existe réellement

Transitivement, et **seulement une fois qu'une Collect existe** :

```
Product ──┐
          ├──(Collect)── Depositary ── Company ── Licence
Client ───┘
```

`CollectSchema` porte les trois références d'un seul coup — `client_id`,
`depositary_id`, `product_id` (mesuré). Le Dépositaire porte `company_id`
(contrat minimal : `name`, `currency`, `company_id`). La Company porte sa licence
via `GET /api/v1/licenses/company/{id}`.

### Ce que cela implique

La licence **conditionne** bien le catalogue — `READY_CASH` pour le crédit,
`READY_COLLECT` pour la collecte. Mais **rien côté serveur n'empêche** d'attacher
un produit crédit à une Company sans licence `READY_CASH`, parce qu'**il n'y a
aucun attachement du tout**. La contrainte est donc **entièrement à notre
charge**, exactement comme la cohérence catégorie
(`OBS-CLI-CROSSCHECK-01`).

> **Conséquence pratique** : la postcondition « rattaché aux Companies éligibles »
> de `UC-11` n'est **pas vérifiable côté serveur**. Comme pour `EF-26`, elle ne
> peut se prouver que depuis notre trace — argument de `D-05`. À ce jour le
> rattachement produit → Company n'est **ni écrit ni vérifié** : c'est un manque
> ouvert, pas une décision.

---

## 8. Ce qui reste hors périmètre, et pourquoi

`CT-02`, ligne 918 :

> « Le service **loan-service n'est pas livré** à la date de rédaction. La partie
> prêt du Loader ne peut être validée qu'en **mode simulé** jusqu'à sa
> livraison. »

Ligne 381 confirme le périmètre :

> « L'injection réelle des prêts tant que loan-service n'est pas livré en
> production ; **l'outil prépare et valide les payloads**, l'injection sera
> activée ultérieurement. »

Donc les prêts sont **préparés et validés**, jamais injectés en v1.0. Ce qui
bloque `CR-10` et `A-04` (persistance des ~700 prêts simulés).

---

## Références croisées

`docs/DISCIPLINES.md` (`D-CLI-10`, `D-CLI-13`, `D-PRD-4`, `D-PRD-9`) ·
`docs/DECISIONS.md` (`A-02`) · `docs/PLAN_SPRINTS.md` (`A-10`, `A-11`) ·
`docs/empirical/2026-08-09_client_service_exhaustif.md` ·
`docs/empirical/2026-08-11_faker_solde_initial.md` ·
`app/services/catalogue.py` · `app/services/clients_execution.py`
