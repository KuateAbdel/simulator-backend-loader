# Conception — catalogue produits et souscription client

> **Statut : conception, à valider avant implémentation.**
> Écrit le 12/08/2026. Aucune ligne de code n'est écrite tant que ce document
> n'est pas jugé cohérent et sans défaut.
>
> Toute affirmation porte sa **ligne de CDC** (docx extrait, 1197 lignes) ou sa
> **mesure** (OpenAPI vivants, serveur TEST). Rien n'est déduit.

---

## 0. AMENDEMENT DU 12/08 — le périmètre, arbitré par le patron

Information rapportée par Yaniv après contact direct avec le patron. Elle change
le périmètre, donc elle passe **avant** tout le reste.

| # | Ce qui est arbitré |
|---|---|
| 1 | Le Loader est un projet **long terme**, jusqu'au **sprint 8** de la plateforme FinZuu — pas du Loader. |
| 2 | La **MEP1** ne couvre que **4 sprints**. |
| 3 | **Les Lenders arrivent avec le module LENDING.** Ce n'est pas le périmètre courant : c'est une **évolution suivante** du Loader. |
| 4 | Le **produit doit être lié à une Company**, correctement, conformément au CDC. |
| 5 | Les **licences** : on obéit, on pose `READY_COLLECTE`. Elles ne sont **pas encore opérationnelles** — le Dépositaire n'a aucun lien — **mais l'équipe corrigera**. |
| 6 | **Nos notes côté Loader restent empiriques** — consigne de JJB. |

### 0.-1 LA DECISION QUI PRIME SUR TOUT LE RESTE — `D-PRET-0`

**Tranchee le 12/08/2026 par Yaniv, auteur du CDC. Elle n'est pas rediscutable.**

> **LE LOADER NE FAIT PAS DE PRETS. POINT.**

Ce qui est repris de Duhamel est sa **METHODOLOGIE**, jamais son objet :

| On prend | On ne prend pas |
|---|---|
| les **4 profils comportementaux** (`EF-67`) | la creation de prets |
| l'**ajustement contextuel** a 9 variables (`EF-68`) | les evenements `CREATE_LOAN` |
| la **compression temporelle** (Annexe D.3) — deja faite | les evenements `REPAY_LOAN`, `SET_DPD` |
| la notion de **DPD** comme concept | le transport Kafka (`ENF-16`) |

**Consequences directes, et elles sont simples :**

- aucun produit de **credit** n'est cree — il ne servirait a rien ;
- aucun evenement de credit n'est emis ;
- `UC-02`, `UC-03`, `EF-70`, `EF-71` decrivent une capacite **future**, hors du
  perimetre livrable ;
- ce qui reste du module 7.8 est **`EF-67` et `EF-68`** — l'attribution du profil
  a la creation du client, qui n'exige aucun pret.

**La mesure concorde avec la decision**, ce qui est le plus important :

| Fait | Source |
|---|---|
| « **neuf** services de production confirmes… les modules bulk-payment, **loan, lender** et notification sont a l'etat de specification » | CDC ligne 326 |
| « injection dans les **neuf** services vivants » | CDC ligne 375 |
| « l'outil **prepare et valide les payloads**, l'injection sera activee ulterieurement » | CDC ligne 382 |
| `loan-service/health` → **000** · `lending-service/health` → **000** | mesure du 12/08 |
| aucun client `loan_service.py` dans `app/clients/` | 13 fichiers, neuf services |

> **Ou je me suis embrouille, et je le note pour ne pas y revenir.** J'ai ecrit
> « le Loader cree les prets » en citant la postcondition d'`UC-02`. C'etait lire
> une specification de capacite future comme une exigence du livrable. `loan` et
> `lender` sont dans la MEME phrase du CDC, du MEME cote de la frontiere — et
> c'est l'auteur du CDC qui le rappelle.

### 0.0 TROIS CHOSES QU'IL NE FAUT PAS CONFONDRE

Mise en garde de Yaniv, 12/08. Elle etait justifiee : **je decrivais le script de
Duhamel depuis mes notes, pas depuis le script.** Correction faite apres lecture
integrale de `docs/reference/lifecycle_orchestrator_README.md` et de
`docs/reference/duhamel_lifecycle_orchestrator_EXTRAIT.py`.

#### Ce que le script de Duhamel FAIT reellement

Le paquet `ready_scoring/` est un **outil Kafka de bout en bout**, pas une API
REST. Cinq modules : `kafka_consume`, `repayment_simulator`, `loan_tracker`,
`push_commands`, `portfolio_kpis`.

**Il ne cree pas l'ecosysteme.** Il simule le **cycle de remboursement de prets
qui existent deja** :

| Il fait | Par quel canal |
|---|---|
| **decouvre** les prets | consomme `readyscore.loan.events.v1` (`LOAN_CREATED`) |
| **pousse** les remboursements | produit sur `readyscore.loan.commands.v1` : `REPAY_LOAN`, `SET_DPD` |
| lit le portefeuille | `readyscore.portfolio.daily_snapshots.v2` |
| declenche le re-scoring | `lifecycle.scoring.input.v36` |
| tire les comportements | `config/behaviors.example.json` ou le classeur Excel « Business Case Reevaluation-V2 » |
| suit un client / un pret | `loan_tracker follow-client`, `follow-loan` |

Bootstrap Kafka `152.53.140.115:9092`, via tunnel SSH avec `duhamel_key`.

> **Toute notre architecture de pilotage vient de la.** `--run-id`, `--dry-run`,
> `--seconds-per-day`, `--seed`, `--max-loans`, `--from-beginning` sont ses
> drapeaux CLI. Ce ne sont pas nos inventions : ce sont ses conventions, reprises.

#### CE QUE J'AI DIT DE FAUX, ET QUE JE CORRIGE

J'ecrivais « on **appellera** `loan-service` en HTTP ». L'en-tete de l'extrait dit
l'inverse, et c'est une doctrine, pas un detail :

> « `ENF-16` interdit explicitement toute dependance a un cluster Kafka, et la
> Stack Technique fait du Loader un orchestrateur **HTTP pur**. Le script
> original est un consommateur Kafka de bout en bout : `Consumer`, `Producer`,
> `AdminClient`, calibration par timestamps de topic, decouverte automatique de
> topics. **Rien de tout cela n'est repris.** »

Et, dans la liste des ecartes : « `Producer.produce_command` → **remplace par des
ecritures HTTP FinZuu** ».

**Le Loader ne subit donc pas l'absence de `loan-service` : il SUBSTITUE un
transport.** La methodologie de Duhamel est portee, son canal Kafka est refuse par
`ENF-16`, et les commandes deviennent des ecritures HTTP. C'est une conversion,
pas une attente.

#### Les trois choses, distinguees

| | Nature | Qui | Notre rapport a cette chose | MEP1 |
|---|---|---|---|:---:|
| **Methodologie loan-simulation** (Annexe D) | une **methode** + un script Kafka de reference | **Duhamel**, comme *referent loan-simulation* | on la **PORTE**, en refusant son transport (`ENF-16`) | ✅ **dedans** |
| **`loan-service`** | un **service** de la plateforme | **Duhamel**, comme *developpeur externe* (ligne 445 : « Livre le module loan-service ») | l'injection reelle des prets passera par lui (ligne 712) — mais le Loader ecrit deja en HTTP FinZuu | ⏸ `CT-02` — **non livre** |
| **Module LENDING de la plateforme** | un **module produit** FinZuu | l'equipe FinZuu | il apporte les **Lenders** — arbitrage du patron | ⏸ **sprint 8** |

#### Ce qui est repris VERBATIM — quatre choses, pas une

1. **Les 4 fonctions de conversion temporelle** (`EF-76`) — deja dans
   `app/core/temps.py`, sous leurs noms d'origine.
2. **`_adjust_weights`** — que l'extrait nomme « **le coeur intellectuel** » :
   **neuf variables client** vers les poids des quatre profils. Genre, age
   (derive de `scoring_date` moins `birth_date`), segment, `risk_class`,
   `repayment_ratio`, `max_dpd`, et `MOB_MONEY_ACCOUNT_AMOUNT`. Les coefficients
   sont explicites — une femme : `pay_before_due x 1,22`, `never_pays x 0,72` ;
   un client de moins de 22 ans : `never_pays x 1,12`.
3. **`_sample_profile`** — tirage pondere sur la distribution cumulee.
4. **`_loan_terms`** — matching produit x categorie x segment, **avec deux
   replis** dont l'ordre est FIGE : `Medium -> High -> Low -> Very High ->
   Very Low`. C'est ce que `EF-69` et `D-08` decrivent cote Loader.

#### Trois parametres du script que nous devons connaitre

```
LOAN_CREATE_APPROVAL_RATE = 0.90    10 % des APPROVED n'ont PAS de pret cree
LOAN_DISBURSEMENT_CAP     = 1e9     plafond global de decaissement
SECONDS_PER_DAY           = 226.49  repli quand la calibration Kafka echoue
```

Les poids par defaut **`0.50 / 0.25 / 0.13 / 0.12`** sont **exactement** les
« poids empiriques 50/25/13/12 » d'`EF-67`, deja figes dans `app/core/cdc.py`.
**La concordance est confirmee** — ce n'etait pas une coincidence.

> **`LOAN_CREATE_APPROVAL_RATE` ne resout PAS `A-11`.** Ce n'est pas la proportion
> d'APPROVED dans la population : c'est le taux auquel un APPROVED obtient
> effectivement un pret. Les deux se composent. `A-11` reste ouvert — et hors
> perimetre MEP1 (§0.1).

#### Ce qui MANQUE encore — et c'est `A-07`

L'extrait le dit sans detour :

> « `built_in_behaviors_v1()["profiles"]` est **importe** par le script, pas
> defini dedans. Les 4 profils sont donc **nommes** mais leur FORME — ce que
> chacun fait jour apres jour — reste absente. Idem pour `build_timed_actions`,
> `expand_actions_daily` et `repay_amount_for_action`. »

Nous connaissons donc les **noms** (`pay_before_due`,
`partial_then_full_dpd10`, `partial_then_never_finish`, `never_pays`) et les
**poids**. Nous ne connaissons pas ce que chaque profil **fait quotidiennement**.

C'est `A-07`, et ce fichier a en revanche **ferme `A-06`** : les quatre fonctions
nommees par `EF-76` existent bel et bien, ce qui debloquait les etapes 6 et 7.

#### Ce qui est ECARTE, avec son motif

| Ecarte | Motif |
|---|---|
| toute la machinerie Kafka (`Consumer`, `Producer`, `AdminClient`) | `ENF-16` l'interdit |
| `calibrate_input_topic_pacing` | depend des timestamps de topic |
| `_check_live`, `_resolve_topics` | dependent du cluster |
| `par_dpd_tracking` | PAR/DPD releve de **ReadyScore**, hors perimetre Loader (corrections 9-12 du CDC v1.2) |
| `Producer.produce_command` | remplace par des ecritures **HTTP FinZuu** |

> **Le fichier d'extrait n'est jamais importe par `app/`.** Il est une preuve
> documentaire, pas une dependance.

### 0.0 bis Ce qui reste dedans, et ce qui sort — par module du CDC

La v1.2 ajoute trois modules. Ils **ne sortent pas ensemble** :

| Module CDC | Contenu | MEP1 | Pourquoi |
|---|---|:---:|---|
| **7.10** — Vie commune et re-scoring (`EF-76` → `EF-80`) | vie financiere commune de **Type 1**, applicable a « **100 %** des 2000 clients » (ligne 287) | ✅ **dedans** | ne depend d'aucun pret. Utilise les **fonctions de dates Duhamel**, deja portees |
| **7.9** — Alimentation des comptes (`EF-73` → `EF-75`) | `EF-73` solde initial · `EF-74` credit au decaissement · `EF-75` debit au remboursement | ⚠️ **partiellement** | `EF-73` est **livre** (`A-09`). `EF-74`/`EF-75` supposent un pret → sortent |
| **7.8** — Simulation comportementale (`EF-67` → `EF-71`) | `EF-67` attribution du profil · `EF-68` ajustement contextuel · `EF-69` catalogue credit · `EF-70`/`EF-71` historique de pret | ⚠️ **partiellement — CORRECTION** | voir ci-dessous |

#### CORRECTION DU 12/08 — j'avais sorti TOUT le module 7.8, c'etait faux

J'ecrivais « un profil de remboursement sans pret ne simule rien », et j'en
concluais que le module 7.8 sortait en entier. **`EF-67` dit le contraire, mot
pour mot :**

> « Le Loader DOIT attribuer a **CHAQUE CLIENT GENERE** un profil comportemental
> de remboursement parmi quatre valeurs : bon payeur, retard puis paiement, defaut
> partiel, defaut total. La distribution par defaut suit les poids empiriques
> 50/25/13/12. »

**« Chaque client genere »** — pas « chaque APPROVED », pas « chaque pret ».
L'attribution se fait **a la creation du client**, et n'exige aucun pret.

C'est exactement l'analogie de Yaniv : *« quand tu prepares les farines et les
oeufs, marque deja si cette farine donnera un gateau parfait ou immangeable »*.
Le profil est une propriete du CLIENT, pas du pret. Le pret ne fait que la
REVELER.

| Exigence | Contenu | Pret requis ? | MEP1 |
|---|---|:---:|:---:|
| **`EF-67`** | attribuer un profil a chaque client genere (50/25/13/12) | **non** | ✅ **dedans** |
| **`EF-68`** | ajuster selon 9 variables : genre, age, segment, historique, categorie, Mobile Money, classe de risque | **non** | ✅ **dedans** |
| `EF-69` | s'appuyer sur le catalogue credit officiel (Annexe E) | non | ⚠️ le catalogue est **lu et parse** ; sa creation sort |
| `EF-70` | historique de cycle de vie du pret, fidele au profil | **oui** | ⏸ sort |
| `EF-71` | distribution des statuts de pret | **oui** | ⏸ sort |

> **Ce que cela change pour le module Vie de MEP1** : chaque client des 2000 porte
> un profil comportemental **des sa creation**. L'ecosysteme cesse d'etre une
> photo. Le profil ne produit pas encore d'evenements de credit — mais il est
> **la**, attribue, mesurable, et `CR-09` (« distribution comportementale +/- 3 % »)
> devient **verifiable** sans qu'aucun pret existe.

> **Et le Loader est ici PLUS RICHE que le script dont il reprend la methode.**
> Note deja portee par `app/core/invariants.py` : `_adjust_weights` pondere par
> tranche d'age en lisant `ctx.get("birth_date")` — champ qui n'existe dans AUCUN
> payload Faker, ni famille A ni famille B. Cette branche est donc **du code mort
> chez Duhamel**. Chez nous elle s'active, puisque nous composons la date de
> naissance. Nous ne l'imitons pas : nous la servons mieux qu'il ne peut.

> **Nuance a garder en tete** : `_adjust_weights` consomme neuf variables dont
> nous possedons deja plusieurs — genre, age, segment (derive depuis le 12/08),
> `MOB_MONEY_ACCOUNT_AMOUNT`. La logique de ponderation est donc **portable des
> maintenant**. Ce qui manque n'est pas la matiere, c'est l'objet auquel
> l'appliquer : sans pret, un profil de remboursement n'a rien a rembourser.

> **La consequence pratique** : l'executeur VIE de MEP1 n'est **pas** ampute. Il
> porte la vie commune des **2000** clients — pas seulement de ceux sans pret.
> Type 1 s'applique a 100 % de la population, et Type 2 s'y **ajoute** (ligne 290 :
> « **En plus de** la vie commune de Type 1 »). Sortir le credit ne retire **rien**
> a MEP1 : cela retire la **couche** qui se posait par-dessus.

### 0.1 Ce que le point 3 débloque

**`A-11` cesse d'être bloquant.** La proportion APPROVED / DECLINED que le CDC ne
fixe nulle part ne concerne que la **couche crédit** — donc le module LENDING,
donc le sprint 8. Le module Vie de MEP1 n'a besoin que de la **vie commune de
Type 1**, applicable à « 100 % des 2000 clients » (CDC ligne 287) : comptes,
épargne, paiements marchands, P2P, Mobile Money, souscriptions Collecte,
opérations aux Kiosques.

C'est une **bonne nouvelle mesurable** : le blocage que je signalais ce matin
n'existe plus dans le périmètre courant.

### 0.2 Comment mettre le LENDING hors périmètre — et pas en commentaire

**Mesure de l'empreinte, faite avant de proposer quoi que ce soit :**

| | Compte |
|---|---:|
| fichiers applicatifs touchant `lender` / `LENDING` / `loan_json` | **23** |
| fichiers de test concernés | **8** |
| critères de recette concernés (`CR-08`, `CR-10`, `EF-13`) | **7** |
| produits LENDING créés | **6** |

**Commenter ce code serait une erreur**, et pour une raison simple : il est écrit,
testé, et il sera **exigé au sprint 8**. Un commentaire sur 23 fichiers détruit la
lisibilité, casse la suite de tests, et il faudra tout reconstituer dans six
sprints en ayant perdu le raisonnement.

**Le dépôt porte déjà le bon patron.** `ConfigurationPays` (ligne 148) :

> « `actif` est un **état**, pas une suppression : un pays retiré garde sa
> trace. »

**Décision : un interrupteur de périmètre, du même type.**

```
ConfigurationExecution.perimetre_lending : bool = False   # MEP1
                       motif_lending     : str            # « module LENDING — sprint 8 »
```

Ce qu'il change quand il est à `False` :

| Ce qui est affecté | Comportement MEP1 |
|---|---|
| `payloads_lending()` | non émis — **6 créations au lieu de 12** |
| `enregistrer_lender()` / `lenders_registry` | non appelé, collection vide |
| `EF-13` (les 4 comptes financiers de chaque Lender) | **HORS PÉRIMÈTRE**, et non « non vérifiable » |
| `CR-08` (plafond d'usure) | reste **TENU** — la borne 24 % est figée dans `cdc.py`, indépendamment de toute création |
| `CR-10` (100 séquences de remboursement) | **HORS PÉRIMÈTRE** |
| le code, les tests, les payloads crédit | **intacts**, prêts pour le sprint 8 |

> **La distinction « hors périmètre » / « non vérifiable » n'est pas cosmétique.**
> « Non vérifiable » dit *« nous ne pouvons pas juger »* — c'est un aveu.
> « Hors périmètre » dit *« ce n'est pas encore dû »* — c'est une décision. Devant
> un bailleur, les deux ne s'entendent pas du tout de la même façon.

### 0.3 La licence — obéir au CDC malgré un serveur incomplet

`UC-11` pt 3 exige le rattachement par licence. Nous posons donc
`READY_COLLECTE` (ou `ALL`) et nous rattachons.

**Note empirique, datée, comme JJB l'exige** — mesure du 12/08/2026 :

- product-service ne porte **aucune** référence à Company (« company » : zéro
  occurrence dans tout l'OpenAPI) ;
- le Dépositaire porte `company_id`, mais **aucun lien vers une licence** ;
- la licence est lisible par `GET /api/v1/licenses/company/{id}`, et rien ne
  contraint son usage.

Le rattachement est donc **posé et vérifié chez nous** en attendant la correction
annoncée. Le jour où le serveur le portera, notre trace deviendra un doublon
volontaire — ce qui est le bon sens de la marche : on n'attend pas un service
pour être cohérent.

---

## 1. La question de départ

> *« Le client souscrit à des produits qui sont dans son pays, c'est-à-dire dans
> sa microfinance, n'est-ce pas ? »*

**Oui.** Un client de l'IMF A ne peut pas souscrire au produit de l'IMF B. La
chaîne d'appartenance est :

```
Client ── Kiosque ── Agence ── Branche ── Company (IMF) ── Licence
   │                                          │
   └────────── souscription ─────► Produit ◄──┘
                                (UC-11 pt 3)
```

`UC-11` point 3, ligne 164 :

> « Il **rattache chaque produit aux Companies dont la licence l'autorise**
> (`READY_CASH` pour crédit, `READY_COLLECTE` pour Collecte, `ALL` pour les
> deux). »

Et les Companies sont créées **par pays** — `UC-07` ligne 86 : « Entre 3 et 5
Companies **par pays** ». Donc le périmètre de souscription d'un client est celui
de sa Company, donc de son pays.

---

## 2. Un catalogue, ou un catalogue par Company ?

C'est la question suivante, et le CDC la tranche. `UC-11` point 2, ligne 164 :

> « Il définit **les 3 produits Collecte** selon les spécifications FinZuu. »

**Trois** produits Collecte — un par `PolicyType` — et le titre de `UC-11` dit
« **le** catalogue produits » au singulier.

| Lecture | Volumétrie | Verdict |
|---|---|---|
| **(a)** un catalogue partagé, rattaché aux Companies éligibles | 3 × 2 catégories = **6** COLLECT | ✅ conforme au CDC |
| (b) un catalogue par Company | 20 Companies × 6 = **120** COLLECT | ❌ contredit « les 3 produits » |

**Décision : (a).** Un catalogue unique, rattaché à toutes les Companies dont la
licence l'autorise.

> **Pourquoi 6 et non 3.** `ProductCategory` mesuré sur l'OpenAPI vaut
> `['INDIVIDUAL', 'CORPORATE']` — **aucune valeur `ANY`**. Un produit doit donc
> choisir sa catégorie, et couvrir les deux populations exige deux produits par
> `PolicyType`. C'est exactement l'argument de `D-PRD-4`, qui dédouble déjà
> `BNPL` et `ReadyToGo` pour la même raison (`INV-PRD-04`, HTTP 422).

**Conséquence rassurante** : puisque toutes les Companies éligibles offrent le
même catalogue, la contrainte « produits de sa propre IMF » est satisfaite
**pour tous les clients**. Elle n'est pas restrictive en pratique — mais elle doit
être **représentée**, pour deux raisons données au §5.

---

## 3. La barrière de licence — la vraie contrainte

| Package | Peut offrir COLLECT | Peut offrir LENDING |
|---|---|---|
| `READY_COLLECTE` | ✅ | ❌ |
| `READY_CASH` | ❌ | ✅ |
| `ALL` | ✅ | ✅ |
| `BULK` | ❌ | ❌ |

Mesuré : `PackageName = ['ALL', 'READY_CASH', 'READY_COLLECTE', 'BULK']`.
**Attention à l'orthographe** — `READY_COLLECTE` avec un `E` final ; notre code
l'écrit correctement.

**Vérification faite avant d'écrire cette conception** — sinon elle aurait été
défectueuse : les Companies qui hébergent des Kiosques reçoivent
`PackageName.ALL` (`organisation_execution.py:737`), donc `READY_COLLECTE`
implicitement. Les bailleurs institutionnels n'ont que `READY_CASH`, et
**n'hébergent aucun Kiosque**. **Aucun client ne peut donc être bloqué faute de
licence.**

> **Règle de conception** : le panier d'un client est tiré des produits que **sa
> Company** est autorisée à offrir. Aujourd'hui l'ensemble est identique pour
> tous ; la règle reste écrite parce qu'une Company sans `READY_COLLECTE` doit
> rendre ses clients non souscriptibles, et non pas souscriptibles en silence.

---

## 4. Les noms — du métier, pas des étiquettes techniques

`DEMO_Cotisation Individuelle 20000/mois` n'est pas un nom de produit. C'est une
étiquette collée devant. Un catalogue de démonstration destiné à un bailleur doit
porter les noms que porte le métier.

### Ce que le métier utilise réellement — recherché, pas inventé

- **UEMOA** : les dépôts sont **à vue 55,5 %**, **à terme 22,7 %**, autres
  21,8 %. La cotisation régulière domine, le dépôt à terme est le second pilier.
- **PAMECAS (Sénégal)** commercialise `Tontine digitale`, `Épargne Prévoyance`
  (sans intérêt, frais mensuels) et **`Épargne Bloquée`** — un équivalent de
  dépôt à terme rémunéré **4 à 5 % annuel**, avec sortie anticipée possible.
- La **tontine** est un système d'épargne collective rotative, culturellement
  central dans les quatre pays cibles.
- Le **warrantage** (ou *crédit-stockage*) est le produit agricole standard du
  Sahel : le paysan stocke une partie de sa récolte en magasin, **le stock est la
  garantie**, le crédit atteint **80 % de la valeur du stock**, l'opération dure
  **6 à 8 mois** et le stockage se fait d'octobre à décembre. Burkina Faso :
  **~5 700 tonnes sur 300 magasins** (BAD, 2020), taux de remboursement proche
  de 100 %.

Le warrantage est **exactement** la sémantique de `PolicyType.PRODUCT` : une
collecte **en nature**, mesurée (`measure` = `KILOGRAM`), avec un
`measure_price`. Ce n'est pas une analogie — c'est le même objet métier.

### Le catalogue Collecte proposé

| `PolicyType` | INDIVIDUAL | CORPORATE | Ancrage métier |
|---|---|---|---|
| `CASH` | **`Tontine Digitale`** | **`Compte Epargne Entreprise`** | dépôts à vue = 55,5 % des dépôts UEMOA ; `Tontine digitale` est un produit PAMECAS réel |
| `CASH_DAT` | **`Epargne Bloquee 6 Mois`** | **`Depot a Terme Entreprise 12 Mois`** | `Épargne Bloquée` PAMECAS (4–5 % annuel) ; `DAT` est le terme standard UEMOA |
| `PRODUCT` | **`Warrantage Cerealier`** | **`Collecte Cacao Cooperative`** | warrantage = standard sahélien ; le cacao est le produit d'export camerounais |

> **Sans accents**, par cohérence avec le code existant (`Depot a Terme`,
> `Cotisation Commercants`). Ce n'est pas de la négligence : le dépôt tient une
> discipline ASCII sur les identifiants et les noms émis.

**`Warrantage Cerealier` sert aussi `EF-24`** — 20 % des professionnels en
agriculture. Un paysan qui stocke son mil est le client type de ce produit.

### La réversibilité sans polluer le nom

Retirer le préfixe `DEMO_` du nom crée un vrai problème : `CR-07` / `EF-63`
exigent que **chaque entité générée soit identifiable**, sinon une purge laisse
des résidus. Le contrat offre la sortie — `CreateProductSchema` porte
`short_name` et `description`, tous deux libres :

```
name        "Tontine Digitale"                    ← métier, propre
short_name  "DEMO_TONT_IND"                       ← marqueur technique
description "Jeu de donnees DEMO Loader FinZuu — tontine mensuelle, ..."
```

Mesuré : les produits du serveur utilisent déjà `short_name` de cette façon
(`plast`, `TP_1785841588`, `P5_1785569521712`).

> **Conséquence à assumer, et elle est réelle** : le critère de purge d'un
> produit devient `short_name`, plus `name`. `CR-07` doit donc **choisir le champ
> selon le type d'entité** au lieu de tester `name` partout. C'est une
> modification de la recette, pas un détail — et la taire aurait introduit un
> défaut silencieux.

---

## 5. Le rattachement Produit → Company : ce que le serveur ne porte pas

**Mesure du 12/08** : le mot « company » apparaît **zéro fois** dans tout
l'OpenAPI de product-service — ni champ, ni route. Ses dix routes sont trois
`policies`, six `products`, un `health`.

Or `UC-11` exige le rattachement. **Troisième occurrence** du motif déjà rencontré
avec `EF-26` (Client → Kiosque) et `D-CLI-6` (Client → Company) : le CDC exige un
lien que le serveur ne représente pas.

Le lien n'existe côté serveur que **transitivement, et seulement après une
Collect** :

```
Product ──┐
          ├──(Collect)── Depositary ── Company ── Licence
Client ───┘
```

`CollectSchema` porte les trois références d'un coup — `client_id`,
`depositary_id`, `product_id` (mesuré).

### Décision : le rattachement vit dans `org_hierarchy`

Même solution que `EF-26`, pour la même raison, et elle a déjà fait ses preuves :

- un niveau `PRODUIT` dans `org_hierarchy`, `parent_id` = la Company, portant
  `product_id` et le package de licence qui l'autorise ;
- `verifier_cr02()` gagne sa branche : un produit LENDING rattaché à une Company
  sans `READY_CASH` ni `ALL` est une anomalie ;
- **deux raisons de le faire, et la seconde suffit** :
  1. sans trace, la postcondition de `UC-11` est **invérifiable** — argument
     `D-05` ;
  2. le jour où une Company n'aura pas `ALL`, la règle du §3 devra être
     **appliquée**, et l'appliquer exige de savoir qui offre quoi.

---

## 6. Ce qu'on refuse d'hériter

`D-PRD-9` faisait **retrouver** deux produits plutôt que les recréer :
`Cotisation 20000/mois` et `plastique` existaient déjà avec des abonnés, et
product-service n'a ni unicité ni `DELETE`. **La règle était bonne. Ce qu'elle
ignorait, c'est ce qu'ils contiennent.**

**Mesure du 12/08 sur le serveur TEST :**

| | `Cotisation 20000/mois` | `plastique` |
|---|---|---|
| `interest_rate` | **99,0 %** *(mensuel)* | 22,0 % |
| `amount_min → max` | 1 000 → **100 000** | **3,0 → 3,0** |
| `measure` | KILOGRAM | LITER |
| `vat` | 0 | 3,0 |
| préfixe / marqueur | **aucun** | **aucun** |
| doublon en base | **oui** (`ANO-PRD-UNIQ-01`) | non |

Le produit d'**entrée** de nos 1600 clients INDIVIDUAL portait **99 % d'intérêt
mensuel**, et `plastique` n'acceptait qu'une quantité de **exactement 3**.

**Trois raisons de ne plus s'en servir, et la troisième suffit :**

1. Présenter 99 % d'intérêt mensuel à un bailleur décrédibilise la démonstration.
2. Attacher 1600 clients `DEMO_` à un produit non marqué casse `CR-07` : une
   purge ne les retrouverait pas.
3. Ce sont des entités **partagées par toute l'équipe**. La règle du Loader est de
   ne jamais écrire sur le partagé — et **une souscription écrit**.

**Décision** : ils sont **constatés au rapport, jamais consommés**.
L'environnement est un fait qu'on constate, pas une dépendance qu'on subit.

---

## 7. Les comptes, réconciliés

| | Déclarés au CDC | Créations | MEP1 | Pourquoi l'écart |
|---|---:|---:|:---:|---|
| Collecte | **3** (`UC-11` pt 2) | **6** | ✅ | `ProductCategory` n'a pas de valeur `ANY` |
| Crédit | **4** (Annexe E) | **6** | ⏸ sprint 8 | `BNPL` et `ReadyToGo` portent `Any` → `D-PRD-4` |
| **Total** | **7** | **12** | **6** | `PRODUITS_ATTENDUS` devient dépendant du périmètre |

`PRODUITS_ATTENDUS` n'est donc plus une constante mais une **fonction du
périmètre** : 6 en MEP1, 12 quand le module LENDING entre. Le figer à 12
ferait échouer la vérification du compte sur un run parfaitement conforme.

Les deux produits de l'environnement **ne comptent plus** dans notre catalogue :
ils n'en font pas partie.

---

## 8. Ce qui change, concrètement

| # | Changement | Fichier |
|---|---|---|
| 1 | Les six noms Collecte deviennent des noms métier | `catalogue.py` |
| 2 | Le marqueur `DEMO_` passe du `name` au `short_name` | `catalogue.py` |
| 3 | `Warrantage Cerealier` remplace `plastique` (`KILOGRAM`) | `catalogue.py` |
| 4 | Les deux produits de l'environnement sont **constatés**, plus consommés | `catalogue_execution.py` |
| 5 | `CREATIONS_ATTENDUES` : 10 → **12** | `catalogue_execution.py` |
| 6 | `CR-07` choisit le champ marqueur **selon le type d'entité** | `recette.py` |
| 7 | Niveau `PRODUIT` dans `org_hierarchy` + branche `CR-02` | `org_hierarchy.py`, `enums.py` |
| 8 | Le panier d'un client est tiré des produits de **sa Company** | `clients_execution.py` |
| 9 | `perimetre_lending` — interrupteur, jamais un commentaire (§0.2) | `configuration.py` |
| 10 | `PRODUITS_ATTENDUS` devient fonction du périmètre : 6 en MEP1 | `catalogue_execution.py` |
| 11 | La recette distingue **hors périmètre** de **non vérifiable** | `recette.py` |

**Ordre d'implémentation** — 1→5 d'abord (le catalogue), puis 6 (la recette, qui
dépend de 2), puis 7→8 (le rattachement, qui est la tâche #29 / `A-12`).

---

## 9. Les défauts que cette conception ferme, et ceux qu'elle laisse ouverts

**Fermés :**
- un produit d'entrée à 99 % d'intérêt devant un bailleur ;
- 1600 souscriptions sur une entité partagée non marquée ;
- un catalogue dépendant de l'état d'un environnement qu'on ne contrôle pas ;
- des noms de produits qui ne ressemblent à aucun produit réel.

**Laissés ouverts, et déclarés :**
- **`A-11`** — la proportion APPROVED / DECLINED n'est fixée nulle part dans le
  CDC. **Ne bloque plus MEP1** (§0.1) : elle appartient à la couche crédit, donc
  au module LENDING du sprint 8. À rouvrir à ce moment-là.
- Le second temps d'`EF-26` — la matérialisation du rattachement par une Collect
  appartient à l'exécuteur VIE.
- `CT-02` — loan-service n'est pas livré ; les prêts sont préparés, jamais
  injectés.

---

## Sources

- [Zone UMOA — encours des dépôts collectés par les IMF](https://www.lejecos.com/Zone-Umoa-L-encours-des-depots-collectes-par-les-institutions-de-microfinance-s-est-accru-de-584-milliards-FCfa-en-2025_a30874.html)
- [PAMECAS — nos produits financiers](https://pamecas.sn/produit.php)
- [UM-PAMECAS — Confédération des Institutions Financières d'Afrique de l'Ouest](https://www.cif-ao.org/reseau/um-pamecas/)
- [Cirad — Stocker une partie des récoltes en échange d'un crédit ? Les avantages du warrantage au Sahel](https://www.cirad.fr/les-actualites-du-cirad/actualites/2023/encourager-le-stockage-de-cereales-au-sahel)
- [FAO — Le warrantage, un dispositif pour améliorer la sécurité alimentaire en Afrique subsaharienne](https://www.fao.org/family-farming/detail/en/c/1642925/)
- [Inter-réseaux — Le warrantage paysan : stocker pour accéder au crédit ?](https://www.inter-reseaux.org/publication/agriculteurs-et-acces-au-financement-quel-role-pour-letat/le-warrantage-paysan-stocker-pour-acceder-au-credit/)
- [Oxfam — Warrantage paysan au Burkina Faso](https://oi-files-d8-prod.s3.eu-west-2.amazonaws.com/s3fs-public/file_attachments/rr-warrantage-burkina-faso-141015-fr.pdf)
- [Advans Cameroun](https://www.advanscameroun.com/)

Sources internes : `Cahier_Charges_Loader_FinZuu_v1_2_final.docx` (lignes 86,
152–164, 200–202, 290, 292, 818, 918, 1137) · OpenAPI product-service,
collect-service, company-service (mesurés le 12/08/2026) ·
`docs/reference/COMPREHENSION_PRODUITS_ET_CREDIT.md`
