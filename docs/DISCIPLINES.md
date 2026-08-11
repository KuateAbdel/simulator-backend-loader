# Les disciplines de service — registre complet

| | |
|---|---|
| **Objet** | Les **63 disciplines** que le Loader applique face aux 9 services FinZuu. Chacune neutralise un écart empirique **mesuré**, pas supposé. |
| **Nature** | Registre consolidé. Chaque discipline vit dans le code, à l'endroit où elle s'applique — ce document en est l'**index**, pas la source. |
| **Pourquoi il existe** | 59 disciplines vivaient dans les commentaires ; **26 seulement** figuraient dans les docs. La connaissance était là mais introuvable sans lire 4 000 lignes. |
| **Écrit le** | 9 août 2026 |

> **Lire ce document, c'est lire ce que le Loader sait du terrain.** Une
> discipline n'est jamais une préférence de style : c'est une mesure du 8 ou 9
> août transformée en règle exécutable.

### 🔸 Convention d'origine — ajoutée le 11/08

Les séries `D-XXX-*` viennent des pages **Service Anatomy** (espace TST). Nous
avons **prolongé** certaines séries sans le signaler, et c'était une source de
confusion : qui lit `D-DEP-9` va le chercher sur la page `63340549` et ne le
trouve jamais.

Le marqueur **🔸 signale une discipline qui est NÔTRE**, absente de la page
Anatomy du service.

| Service | Page Anatomy | Ce que nous appliquons |
|---|---|---|
| depositary (`63340549`) | `D-DEP-1` → `8` | + **`D-DEP-9`** 🔸 |
| client (`60555267`) | `D-CLI-1` → `8` | + **`D-CLI-9`**, **`D-CLI-10`** 🔸 |
| product (`60358657`) | `D-PRD-1` → `9` | identique |
| collect (`62521348`) | `D-COL-1` → `16` | sous-ensemble |
| user (`56360965`) | `D-USR-*` | sous-ensemble |

Prolonger une numérotation d'autrui n'est pas neutre : elle donne à notre règle
l'autorité d'une page qui ne la porte pas. Le marqueur rend l'emprunt visible.

---

## Une note de méthode — pourquoi ce document, et pas un module Python

Un module `app/core/disciplines.py` a existé jusqu'au 9 août. Il portait le
texte de **5** disciplines sous forme de constantes, *« pour que chaque
garde-fou puisse nommer explicitement la discipline qu'il applique »*.

**L'intention était juste. L'exécution n'a jamais eu lieu :** aucun module ne
l'importait. Pendant ce temps, chaque garde-fou écrivait son propre texte à
l'endroit où il s'applique — et ces textes-là sont devenus **plus précis** que
les constantes. `collect_service.py` nomme `FRA-195` et le qualifie d'« écriture
fantôme » ; la constante disait seulement « mutation réelle silencieuse ».

C'était donc une **table parallèle** — la même faute que
`_PATRONYMES_PAR_PAYS` dupliqué et que `MAX_CONCURRENT_WORKERS = 25` resté
derrière la correction de `D-USR-1`. Elle avait d'ailleurs déjà dérivé : elle
annonçait **5** disciplines quand il y en a **59**.

Le module a été supprimé après vérification que **chacun des cinq textes survit
là où il s'applique** — 2 occurrences pour `D-FAKER-1`, 5 pour `D-CMP-2`, 18
pour la famille `D-PRD-*`, 20 pour les montants de collecte.

> **La règle qui en sort :** une discipline vit **une seule fois**, au point
> d'application. Ce document l'**indexe** ; il ne la duplique pas. Un index qui
> se prend pour une source devient une seconde source, et deux sources
> divergent.

---

## Ce qui distingue une discipline d'une décision

| | Décision (`D-01`…`D-12`) | Discipline (`D-XXX-N`) |
|---|---|---|
| Porte sur | **notre** conception | **leur** comportement |
| Née de | un arbitrage | une mesure |
| Vit dans | `docs/DECISIONS.md` | le module qui l'applique |
| Change si | nous changeons d'avis | **le serveur change** |

Les décisions nous appartiennent. Les disciplines nous sont **imposées** — et
chacune disparaîtra le jour où le service qu'elle contourne sera corrigé.

---

## Transport — `D-USR-*` · 8 disciplines · `app/clients/base.py`

Le socle commun aux neuf clients. Il ne connaît aucun métier : il porte ce que
les services ont en commun **de défaillant**.

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-USR-1` | **Concurrence plafonnée à 20, partagée** | au-delà de 20–30 requêtes simultanées, la dégradation est **silencieuse** — aucun `429` (`H14`/`H15`) |
| `D-USR-2` | Retry sur erreur **transitoire seulement**, 3 tentatives | l'idempotence serveur est excellente (*no-op detection*) — rejouer est sûr |
| `D-USR-5` | Pagination bornée à **100** | le serveur accepte `limit=9999999999` (`H20`) |
| `D-USR-6` | `X-Request-Id` généré **et journalisé chez nous** | le serveur ignore le nôtre (`H19`) et ses logs sont pollués à **99 %** par les kube-probes (`H23`) |
| `D-USR-7` | Parser le wrapper `{status_code, response_type, description, data}` | ce n'est **pas** le format natif FastAPI `{detail: [...]}` |
| `D-USR-8` | Parsing datetime **défensif** | le suffixe `Z` est présent ou absent selon l'endpoint (`H11`) |
| `D-USR-10` | Rôles RBAC via `/groupes` | seule surface d'attribution des permissions |
| `D-DEP-7` | **Le token ROOT est le seul utilisé en écriture** | `FRA-205` |

> **`D-USR-1` a été corrigée le 9 août, et la correction compte.** Le plafond
> était de **25 par client** — neuf clients construisant chacun le sien, soit
> **jusqu'à 225 requêtes simultanées** quand la mesure en donne 30 pour maximum.
> *Le plafond existait dans le code et n'existait pas dans les faits.* Il est
> désormais **unique** (`semaphore_partage()`), **global**, et fixé à la **borne
> basse** du domaine mesuré. `PLAFOND_WORKERS` de l'orchestrateur n'est plus
> qu'un alias — un plafond déclaré deux fois n'est pas un plafond, c'est une
> opinion.

**Sécurité, plus strict que le serveur** : le SIEM local n'écrit **jamais** les
en-têtes (donc jamais le Bearer) et masque les mots de passe. Le serveur, lui,
persiste le JWT **en clair** dans ses logs pendant 7 jours (`VIOL-06.7`).

---

## Client — `D-CLI-*` · 12 disciplines *(8 de la page Anatomy + 4 nôtres)* · `app/clients/client_service.py`

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-CLI-1` | Les produits COLLECT existent **avant** tout Client | dépendance d'ordre, portée par l'orchestrateur |
| `D-CLI-2` | `id_expire_on` **toujours** fourni | son absence fait planter la cascade identity en `400 'NoneType' object has no attribute 'isoformat'` — le champ est pourtant **déclaré optionnel** |
| `D-CLI-3` | `id_number` alphanumérique | le serveur annonce une contrainte MAJUSCULES **qu'il n'applique pas** (`FRA-228`) — on s'y conforme quand même |
| `D-CLI-4` | `identity.type` envoyé est **ignoré** | le serveur écrase vers `CORPORATE` |
| `D-CLI-5` | `GET`-avant-`POST` par `msisdn` | rejouer le même msisdn rend le client existant — **inapplicable jusqu'au 12/08**, voir `D-CLI-11` |
| `D-CLI-6` | **Le lien Client → Company n'existe pas à la création** | il passe par `Client →(Collect)→ Dépositaire → Company` |
| `D-CLI-7` | `PUT /clients/subscribe` pour les 2ᵉ et 3ᵉ produits | `UC-13` : 1 à 3 souscriptions |
| `D-CLI-8` | **`identity.phone` doit être strictement égal à `msisdn`** | sinon `400 "Identity phone field must match msisdn"` — **absent de toutes nos sources**, trouvé par sondage |
| `D-CLI-9` 🔸 | `currency` **n'est validée nulle part** | elle traverse le service, n'apparaît pas dans la fiche Client rendue, et **atterrit verbatim dans le compte CHECKING** |
| `D-CLI-10` 🔸 | Un Client ne souscrit **qu'à** des produits `COLLECT` | le serveur accepte un LENDING — `FRA-230` |
| `D-CLI-11` 🔸 | **Le `msisdn` est fonction du client, jamais du `run_id`** | mesuré le 12/08 : le tirage de l'opérateur venait d'`alea`, donc la même matière client rendait `237679614504` au run 1 et `237699614504` au run 2. `D-CLI-5` cherchait une clé qui changeait à chaque run — il n'aurait **jamais** trouvé personne |
| `D-CLI-12` 🔸 | **La graine Faker est fonction du périmètre, jamais du `run_id`** | corollaire : elle était tirée dans `alea`, donc un second run réel tirait 2000 clients Faker entièrement différents. Le registre `D-FAKER-1` ne reconnaissait rien et l'écosystème doublait, sur des services sans `DELETE` |

---

## Collecte — `D-COL-*` · 12 disciplines · `app/clients/collect_service.py`

C'est la famille la plus dense : le chemin de l'argent est celui qui pardonne le
moins.

| # | Discipline | Le fait mesuré |
|---|---|---|
> ⚠️ **Statut de certitude — relevé le 11/08.** Les `D-COL-*` viennent de la
> page Anatomy collect-service. **Toutes n'ont pas la même force.** `D-COL-9`
> (écriture fantôme) est adossée à une mutation constatée ; `D-COL-14` (atomicité
> du retrait) ne l'est à **rien que nous ayons mesuré**. Confondre les deux, c'est
> s'appuyer sur du vide en croyant marcher sur du solide.
>
> **Le retrait n'a jamais été testé par nous.** Le simuler au Sprint 5 sans le
> mesurer d'abord ferait échouer `CR-12` — « solde = initial + décaissements −
> remboursements » — sans qu'on sache pourquoi.

| `D-COL-1` | Souscription Dépositaire ↔ Produit **avant** toute collecte | — |
| `D-COL-2` | Ouverture : `client_id` + `product_id` + `depositary_id` **ensemble** | les trois références partent en même temps |
| `D-COL-3` | Contribution suivante : `collect_id` + `amount` **seuls** | — |
| `D-COL-4` | **Ne jamais attendre que le compte CHECKING bouge** lors d'une collecte | épargne et compte courant sont deux flux distincts |
| `D-COL-9` | Discipline **non négociable** sur l'ordre des écritures | — |
| `D-COL-10` | Respecter `amount_min` **de la Policy** | le message de plafond est **trompeur** (`FRA-198`) — on se fie à la Policy, jamais au message |
| `D-COL-11` | **Ne jamais simuler de clôture** | bloquée (`FRA-196`), aucun bouton côté UI — **aucune méthode n'existe dans le client** |
| `D-COL-12` | `collect_quantity` obligatoire pour un produit PRODUCT | `FRA-197` |
| `D-COL-13` | **Ne pas simuler de collectes PRODUCT** tant que `FRA-197` n'est pas corrigé | garde-fou dans `valider_collecte()` |
| `D-COL-14` ⚠️ | L'atomicité du Retrait serait fiable — **JAMAIS RE-VÉRIFIÉE PAR NOUS** | vient de la page Anatomy collect-service. **Aucune mesure de retrait n'existe dans nos documents empiriques** (vérifié le 11/08). Le grand livre invoqué est probablement la transaction du **31/07 mise de côté**. `WithdrawalSchema` exige `amount` + `collect_id` — c'est tout ce que le contrat garantit |
| `D-COL-16` | Les Produits doivent être **corrects avant** toute Collecte | le Product embarqué dans une Collecte est une **copie figée**, jamais resynchronisée |

> **`D-COL-16` est celle qui coûterait le plus cher.** Un produit corrigé après
> coup ne corrige **rien** des collectes déjà ouvertes. C'est pourquoi le
> Catalogue passe **avant** les Clients dans l'ordre d'orchestration — et
> pourquoi `ExecuteurCatalogue` vérifie ses payloads **avant** le réseau.

---

## Dépositaire — `D-DEP-*` · 9 disciplines *(8 de la page Anatomy + 1 nôtre)*

> **`D-DEP-4` retrouvee le 11/08.** Le registre allait de `D-DEP-3` a `D-DEP-5` :
> un trou a 4. La regle etait appliquee dans le code (`company_service.py`,
> `FRA-199`) et vivait dans un seul document empirique. Une discipline non
> enregistree est une discipline qu'on redecouvre.

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-DEP-1` | Créer d'abord, **souscrire ensuite** | la création seule ne crée **aucun** compte (mesure du 08/08) |
| `D-DEP-2` | Les **6 comptes** naissent à la **première** souscription | par Dépositaire, pas par souscription |
| `D-DEP-3` | `GET`-avant-`POST` | aucune unicité de nom, **aucun `DELETE`** |
| `D-DEP-4` | **Ne jamais compter sur `Company.currency`** — le Loader garde sa propre trace | `FRA-199` : le champ est write-only et **perdu à la persistance** |
| `D-DEP-5` | `id_expire_on` toujours renseigné | `FRA-200` |
| `D-DEP-6` | **Ne jamais présumer** la cohérence de devise Company ↔ Dépositaire | `currency` accepte n'importe quelle chaîne (`FRA-201`) |
| `D-DEP-7` | Token ROOT en écriture | `FRA-205` |
| `D-DEP-8` | Désactiver un Dépositaire **n'arrête ni les collectes ni les retraits** | `FRA-203`/`204` — et c'est **logiquement inévitable** : créer une souscription EXIGE un Dépositaire actif (`400` sinon), donc « inactif avec souscription » ne peut être atteint que par actif → souscrit → désactivé. Il n'existe aucun autre chemin. **Ce n'est pas une observation, c'est une déduction** |
| `D-DEP-9` 🔸 | Un Dépositaire ne souscrit **qu'à** des produits `COLLECT` | le serveur accepte un LENDING (`FRA-223`) |

---

## Produit — `D-PRD-*` · 7 disciplines

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-PRD-1` | **Toujours** une `policy` complète | déclarée optionnelle, son absence provoque un **HTTP 500** (`ANO-PRD-POLICY-01`) |
| `D-PRD-2` | Inventaire complet **avant** toute création | — |
| `D-PRD-4` | **Dédoubler** les produits `Category: Any` | valeur refusée par l'enum serveur (`INV-PRD-04`, `422`) → 4 sources donnent 6 produits |
| `D-PRD-5` | Parser **tolérant** | `loan_json.json` **n'est pas du JSON valide** |
| `D-PRD-7` | **Jamais de `policy_id` partagé** — un embed par Product | la Policy est une **référence vivante** : la modifier change rétroactivement et **silencieusement** tous les Products (`INV-PRD-07`) |
| `D-PRD-8` | `measure` **choisi explicitement** | jamais la valeur que la WebApp injecte en dur |
| `D-PRD-9` | Les 2 produits préexistants sont **retrouvés, jamais recréés** | « Cotisation 20000/mois » et « plastique » |

> **`D-PRD-7` est la discipline la plus dangereuse à oublier**, parce qu'elle ne
> produit **aucune erreur**. Partager un `policy_id` corrompt les autres Products
> en silence. Le serveur ne nous le dirait jamais. D'où le refus **en amont**,
> dans `ProductServiceClient.creer_produit()` **et** dans
> `ExecuteurCatalogue._verifier_avant_emission()` — deux barrières, parce
> qu'aucune alarme ne sonnerait après.

---

## Comptes — `D-ACC-*` · 4 disciplines · `app/clients/account_service.py`

**Ajoutées le 9 août.** Elles étaient établies depuis l'audit monétaire du 8
(19 tests) et vivaient dans `docs/empirical/` **seulement**. Le client
account-service ne portait aucune discipline. *Une connaissance qui reste dans un
rapport ne protège rien.*

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-ACC-1` | **Ne jamais présumer qu'un solde a bougé de `amount`** | `ANO-ACC-FEES-07` — un DEBIT de 500 sur un type à 100 de frais retire **400**. Ni 500, ni 600. Les frais sont **retranchés** du montant demandé et **crédités nulle part** (vérifié sur les 56 comptes) |
| `D-ACC-2` | **Ne jamais lire le statut** pour savoir si l'argent a bougé | `ANO-ACC-STATUS-05` — quatre chemins ont tous déplacé des fonds et rendu `SUCCESS`, `SUCCESS`, `APPROVED` et **`PENDING`**. Le `WITHDRAWAL` de 850 a ramené le solde à zéro **en restant `PENDING`**, relu 20 s plus tard |
| `D-ACC-3` | **Lire `transaction-configs` avant chaque campagne**, n'émettre que des types à frais **0** | la table est modifiable par API — `TAXE` l'a été le **28/07**. Ce qui était sans frais hier peut ne plus l'être |
| `D-ACC-4` | **Aucun `DELETE`** — un compte ne peut qu'être `CLOSED` | — |

> **Ce qu'il faut dire aussi : account-service est le service le mieux gardé de
> l'écosystème.** Masse conservée sur `transfer`, découvert impossible, montant
> négatif refusé **sans mutation**, idempotence réelle par `reference`,
> `SUSPENDED` bloquant vraiment.
>
> Le contraste avec collect-service est majeur — `FRA-195` y établit une mutation
> réelle **sous un rejet apparent**. Deux services du même écosystème, deux
> niveaux de fiabilité opposés. **C'est pourquoi une discipline ne se généralise
> jamais d'un service à l'autre : elle se mesure, service par service.**

---

## Identité — `D-IDN-*` · 4 disciplines · `app/clients/identity_service.py`

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-IDN-1` | **Valider les enums côté Loader** | `gender` et `marital_status` ne sont **pas validés** par le serveur |
| `D-IDN-2` | **Toujours** renseigner la géographie | `country`, `city`, `region` sont acceptés vides |
| `D-IDN-3` | **Paginer** | `limit` vaut **10** par défaut, sans que rien ne le signale |
| `D-IDN-4` | **Ne jamais appeler `/ocr/*`** | trois routes de reconnaissance de pièce, hors périmètre |

---

## Référentiel — `D-CFG-*` · 2 disciplines · `app/clients/config_service.py`

**Ajoutées le 9 août**, et elles illustrent la doctrine mieux qu'aucune autre :
*nous ne réparons pas config-service — nous ne nous laissons pas atteindre.*

L'environnement TEST porte **6 entrées parasites sur 24** : 2 devises (`cv`,
`00`), 2 pays (`CV` nommé « cm », `ca` nommé « cmer »), 2 opérateurs (`cm`
doublon d'Expresso Senegal, et `MTNcongo1`).

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-CFG-1` | **`EF-27` ne se joue jamais sur les regex de ce service** | `MTNcongo1` porte **`6\|333`, sans ancres** — il accepte tout numéro contenant un `6`. Validation en apparence, aucune en fait |
| `D-CFG-2` | **Aucun comptage brut** — total et exploitable sont distingués | annoncer « 14 telcos » serait **exact et trompeur** |

### Pourquoi `D-CFG-1` devait être écrite alors que nous étions déjà immunisés

Le CDC dit *« valider le MSISDN contre le regex de l'opérateur telco du pays »*.
**Lu naïvement, cela désigne config-service.** Nous ne le faisons pas — notre
référentiel porte les **12 plans de numérotation réels** depuis le départ, et
c'est lui qui fait autorité.

Mais cette immunité était **implicite**. Un développeur qui « améliorerait » le
Loader en lisant le regex serveur — de bonne foi, en suivant le CDC à la lettre
— **réintroduirait `6|333` sans s'en apercevoir**. La note vit donc désormais à
l'endroit exact où la tentation se présente, et un test la verrouille.

> **C'est ça, être plus riche : ne pas dépendre de ce qui est cassé chez eux, et
> écrire pourquoi — pour que personne ne recrée la dépendance par zèle.**

---

## Company — `D-CMP-*` · 1 discipline

| # | Discipline | Le fait mesuré |
|---|---|---|
| `D-CMP-2` | Créer une Company **cascade vers trois services** — identity, account **et** user | mais le User cascadé est **inutilisable** : mot de passe inconnu, `company_id` vide, `identity` pointant vers la Company. **Le Loader crée donc son propre Admin.** |

---

## Ce que ce registre dit du terrain

**Compté sur les 59 disciplines :**

| Nature de l'écart contourné | Nombre |
|---|---:|
| Le serveur **ne valide pas** ce qu'il devrait | 11 |
| Le serveur **plante** sur un champ déclaré optionnel | 4 |
| Le serveur **accepte** ce qu'il devrait refuser | 7 |
| Aucune **unicité** là où le métier l'exige | 4 |
| Aucun **`DELETE`** — l'erreur est définitive | 3 services |
| Dégradation ou corruption **silencieuse** | 3 |

**La catégorie qui gouverne notre conception est la dernière.** Un `500` se
voit, se journalise, se rejoue. Une dégradation silencieuse, une Policy partagée,
un Kiosque en double : **rien ne sonne**. C'est contre celles-là que le Loader
place ses garde-fous **avant** le réseau — `RegistreUnicite`, le registre de noms
(`D-12`), `_verifier_avant_emission()`, le sémaphore partagé.

> **C'est le sens exact de la doctrine :** *le Loader anticipe, il ne subit pas.*
> Anticiper un `422`, c'est du confort. Anticiper ce dont le serveur ne dira
> **jamais rien**, c'est la seule chose qui rende un jeu de données fiable.

---

*Sources : les modules `app/clients/*.py` et `app/services/*_execution.py`, où
chaque discipline vit à l'endroit où elle s'applique · mesures des 8 et 9 août
2026 · `docs/empirical/`.*
