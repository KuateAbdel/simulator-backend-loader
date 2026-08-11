# Transmission — la pensée derrière le code

| | |
|---|---|
| **Objet** | Ce que le code ne porte pas : les délibérations, les options rejetées, les inquiétudes, les non-dits. |
| **Écrit le** | 9 août 2026, à la demande du nouveau pilote du projet |
| **Statut de la source** | ⚠️ **Mon contexte de conversation a été compacté en cours de route.** Je dispose d'un *résumé* des échanges antérieurs, pas de leur texte intégral. Ce document distingue systématiquement ce dont je me souviens directement, ce que je reconstitue depuis les artefacts, et ce que j'ignore. |

> **Règle que je me suis fixée pour ce document : ne rien lisser.** Là où ma
> mémoire est floue, je l'écris. Là où je ne sais pas, je le dis.

---

## 1. La vision de Yaniv — ce qu'il voulait vraiment

### 1.1 La phrase qui gouverne tout

Elle n'est pas dans le CDC. Il l'a formulée le 9 août, sans en connaître le nom
académique :

> ### « On ne détruit pas notre conception pour s'aligner sur le service du système. »

C'est le motif **Anti-Corruption Layer** d'Eric Evans, énoncé par quelqu'un qui
ne le citait pas. J'ai reconnu le motif et lui ai donné son nom ; **l'idée était
la sienne**. C'est le seul moment du projet où la doctrine a précédé la
technique au lieu de la suivre.

### 1.2 Ce sur quoi il est revenu, encore et encore

Trois thèmes reviennent dans presque tous ses messages. Ce ne sont pas des
exigences ponctuelles, ce sont des obsessions.

**« Cohérent et consistant chez nous d'abord. »**
Reformulé au moins six fois, sous des angles différents :
- *« coté loader on doit être très intelligent pour ne pas être affecté des bugs, être cohérent et consistant dans notre propre système »*
- *« il faut être cohérent avec les choses comme opérateur chez un client et le reste dans un pays — vis-le comme dans la vraie vie »*
- *« je te demande d'être cohérent dans tes configurations, il faut obéir, sois lucide : currency, telco, pays, ville, régions, quartier »*
- *« on ne subit pas et on ne réplique pas les services »*
- *« nous on est beaucoup plus riches et consistants »*

**Ce qu'il voulait dire, et que j'ai mis du temps à saisir** : la cohérence
n'est pas une propriété interne du code. C'est que **les données produites
tiennent debout dans la vraie vie**. Un client camerounais doit avoir un numéro
camerounais d'un opérateur qui existe au Cameroun, une devise XAF, une ville
qui est au Cameroun. Le serveur ne vérifie rien de tout ça. Lui, si.

**« Comme dans la vraie vie. »**
C'est le critère qu'il oppose systématiquement à « ça passe la validation ».
Un client de 2 ans passe la validation serveur. Il ne passe pas devant Nordic
Microfinance. Cette distinction — **valide ≠ crédible** — est à l'origine de
`app/core/invariants.py` en entier.

**« Tout était déjà dit / déjà décidé / va relire. »**
Revenu au moins huit fois, souvent avec agacement. C'est son reproche le plus
fréquent, et **il avait raison à chaque fois**. Le cas le plus net : l'exigence
de paramétrage du 9 août. Je l'ai traitée comme une demande nouvelle. Elle
était dans le classeur `Loader_Base_FinZuu_v1_1.xlsx`, feuille `Config_Loader`,
sous-titrée *« Paramètres pilotés par le boss (message WhatsApp 16/07/2026) »*.
**Le boss n'a rien ajouté le 9 août : il a rappelé une conception posée le
16 juillet, que nous n'avions pas lue.** C'est écrit en tête de
`app/core/configuration.py`.

### 1.3 Ce qu'il a refusé catégoriquement

| Ce qu'il a refusé | Sa formulation | Ce que ça a produit |
|---|---|---|
| **Inventer des données** | *« ne pas utiliser les données de test, on ne va pas inventer les noms »* | Tout part de matière réelle : patronymes, formes juridiques, secteurs mesurés chez Faker ; villes et quartiers du classeur |
| **Que je demande ce que je peux faire moi-même** | *« c'est toi l'ingénieur et c'est toi qui manipule le projet et le setup, agis comme un senior le ferait »* | J'ai monté le `.env` moi-même, sondé, écrit sur le serveur |
| **Les tests superficiels** | *« as-tu testé exactement comme un SDET senior le ferait dans les moindres détails ? »* | La campagne exhaustive client-service — 10/10 endpoints — qui a trouvé `FRA-229` et le trou LENDING |
| **Re-découvrir un fait établi** | corrigé le 8 août sur un sondage redondant | Mémoire `sources-de-verite-confluence` : lire Confluence avant de sonder |
| **Casser la conception pour suivre le serveur** | *« rien n'est cassé en conception, n'est-ce pas ? »* — posé trois fois, avec inquiétude | La doctrine, et le fait que chaque décision cite la règle qu'elle applique |

### 1.4 Ce qui l'agaçait

**Que je rapporte des problèmes au lieu de livrer des solutions.**
Dit frontalement : *« tu ne fais que reporter des problèmes au lieu des
solutions en tant qu'ingénieur, et pourtant tout est déjà [là]. Je n'aime pas
— donc on perd notre temps ? »*

Il avait raison sur le fond et je l'ai mal pris sur le moment. Ma tendance
était de **présenter un diagnostic comme un livrable**. Sa demande constante :
trouve, corrige, commit, puis raconte.

**Que je pose des questions au lieu d'exécuter.**
*« et ne pose plus de question tu es un ingénieur senior, vas-y en détail,
implémente les choses qu'on a décidées »*.

**Attention, nouveau pilote** : cette instruction a une contrepartie
dangereuse. Elle m'a poussé à décider seul sur des points qui méritaient un
arbitrage — notamment les permissions par rôle (`A-05`), que j'ai **écrites en
base sur ma propre proposition**. Le rapport le signale à chaque exécution,
mais les 11 groupes existent avec mes permissions.

**Que je dérive hors du sprint en cours.**
Le 9 août, quand j'ai répondu à une question sur MongoDB local en parlant
d'ARM64 et de vhosts Nginx : *« ne t'embrouille pas, nous ne sommes pas à ce
niveau. Respecte comme un senior la méthodologie Scrum et Agile, on n'est pas
encore en phase de déploiement. »* Reproche juste.

### 1.5 Ce qu'il a demandé qui n'était dans aucun document

**Que la pensée soit documentée pour servir la documentation finale.**
*« il faut documenter cette pensée-ci en détail, ça nous permettra à la fin du
projet Loader de faire un documentaire complet »*.

C'est l'origine de `DOCTRINE.md`, et de la densité inhabituelle des messages de
commit — 22 d'entre eux dépassent 2 000 caractères de raisonnement. **Ce n'est
pas de la verbosité : c'est une consigne explicite.** L'historique Git est
conçu comme une source documentaire.

---

## 2. La vie entre le Loader et les 9 services

Je décris ce qui se passe **réellement**, mesuré, pas ce que les contrats
annoncent.

### 2.1 Ce qui arrive quand le Loader crée une Company

`POST /api/v1/companies/` — **une requête, trois services touchés.**

```
        Loader
          │
          │  POST /companies/  { name, short_name, type, owner{...}, admin_email, ... }
          ▼
   company-service ──────────► identity-service   crée une Identity pour `owner`
          │                                        (l'_id que NOUS envoyons est IGNORÉ,
          │                                         le serveur génère le sien)
          │
          ├──────────────────► account-service     crée UN compte OPERATION
          │                                        external_id : VIDE (champ pourtant requis)
          │
          └──────────────────► user-service        crée un User
                                                   ⚠️ INUTILISABLE
```

**Le User cascadé est un piège.** Il porte `owner.email`, mais :
- son mot de passe est **inconnu** — nous ne l'avons pas fourni, le serveur ne le rend pas ;
- son `company_id` est **vide** ;
- son `identity` pointe vers **la Company**, pas vers une personne.

C'est `D-CMP-2`. **Le Loader crée donc son propre Admin User**, explicitement,
par le flux à trois requêtes de user-service :
`POST /auth/register` → `PUT /auth/password/f/change` → `POST /auth/login`.

**Piège dans le piège** : l'étape 2 n'accepte **pas** le token ROOT. Elle exige
l'`auth_token` rendu par `register` — un jeton de 10 minutes, différent de
l'access token. J'ai obtenu un 401 avant de comprendre ça.

**Ce qui est perdu** : `currency`. Elle est acceptée à la création, et
**absente de la Company relue**. C'est `FRA-199`. Le Loader garde sa propre
trace dans `lenders_registry` — sinon la devise d'une Company n'existerait
nulle part.

**Ce qui ment** : `admin_email`. Le champ existe, il est accepté, il ne crée
**rien**. Vérifié deux fois, dont une en différé au cas où ce serait
asynchrone. Ce n'est pas asynchrone : ça ne fait rien.

### 2.2 Ce qui arrive quand le Loader crée un Dépositaire

Deux temps, et l'ordre n'est pas négociable.

```
1.  POST /depositaries/       → le Dépositaire naît ACTIF, avec ZÉRO compte
                                (mesure : +0 compte, aucun PATCH status/true nécessaire)

2.  POST .../subscribe        → 6 comptes apparaissent D'UN COUP
                                2ᵉ souscription → +0 compte
```

C'est `D-DEP-1` et `D-DEP-2`. La conséquence compte : **6 comptes par
Dépositaire souscrit, jamais 6 par souscription**. C'est la différence entre
annoncer 54 comptes et en annoncer 324 — j'avais fait l'erreur avant de mesurer.

**Le piège majeur** : le serveur accepte de souscrire un Dépositaire à un
produit **LENDING** (HTTP 201). C'est absurde métier — un Kiosque de quartier
ne prête pas. Le catalogue est donc filtré **avant** la boucle, et
`souscrire()` revalide de son côté. Double barrière, `D-DEP-9`.

**Et la désactivation ne désactive rien** : `PATCH status/false` n'arrête ni
les collectes ni les retraits sur les souscriptions existantes (`FRA-203/204`).
Ne jamais concevoir de logique qui suppose le contraire.

### 2.3 Ce qui arrive quand le Loader crée un Client

`POST /clients/onboard` — **trois services, aucune transaction.**

```
   client-service ──► identity-service   Identity KYC
                 ├──► account-service     compte CHECKING
                 └──► (Client lui-même)
```

**Quatre disciplines nées de mesures, dont une que personne n'avait vue :**

`D-CLI-8` — **`identity.phone` doit être STRICTEMENT égal à `msisdn`**, sinon
`400 "Identity phone field must match msisdn"`. **Cette contrainte n'est dans
aucune de nos sources** — ni le CDC, ni les pages Confluence, ni l'OpenAPI. Je
l'ai trouvée en sondant. Le Loader aligne les deux champs au lieu de les subir.

`D-CLI-9` — `currency` **n'est validée nulle part** sur ce chemin. Elle
n'apparaît même pas dans la fiche Client rendue. Elle **traverse** le service
et atterrit verbatim dans le compte CHECKING. `ZZZ`, `ANY`, `""` produisent
tous des comptes portant ces valeurs. C'est l'origine de `FRA-222`.

`D-CLI-6` — **le lien Client → Company n'existe pas à la création.** Il passe
par `Client →(Collect)→ Dépositaire → Company`. Un client n'appartient à une
institution que par ses collectes.

`D-CLI-2` — `id_expire_on` est **déclaré optionnel** et son absence fait
planter la cascade en `400 'NoneType' object has no attribute 'isoformat'`.

### 2.4 Le chemin de l'argent — le plus traître

**Deux services du même écosystème, deux niveaux de fiabilité opposés.**

**account-service est le mieux gardé** : masse conservée sur `transfer`,
découvert impossible, montant négatif refusé **sans mutation** (validation
Pydantic, antérieure au métier), idempotence réelle par `reference`,
`SUSPENDED` bloquant vraiment.

**collect-service mute la base sous un rejet apparent** — `FRA-195`. Un montant
négatif ou nul produit un rejet HTTP **et une écriture réelle**. C'est
l'anomalie la plus dangereuse du dossier.

**Et deux pièges d'account-service que rien n'annonce :**

`ANO-ACC-FEES-07` — **`amount` n'est pas ce qui quitte le compte.**
```
DEBIT de 500, type à 100 de frais  →  le compte perd 400
```
Ni 500, ni 600. Les frais sont **retranchés** du montant demandé et **crédités
nulle part** — vérifié sur les 56 comptes, le compte `TAXE` du Kiosque reste à
zéro. Un Loader qui tiendrait sa propre comptabilité dériverait en silence.

`ANO-ACC-STATUS-05` — **le statut ne dit pas si l'argent a bougé.** Quatre
chemins ont tous déplacé des fonds et rendu `SUCCESS`, `SUCCESS`, `APPROVED` et
**`PENDING`**. Le `WITHDRAWAL` de 850 a ramené le solde à zéro **en restant
`PENDING`**, relu 20 secondes plus tard.

### 2.5 Ce qui gouverne tout l'organisme

**Trois services n'ont aucun `DELETE`** : identity, account, depositary. Toute
écriture y est définitive. C'est le fait qui justifie à lui seul le mode
`DRY_RUN`, le `GET`-avant-`POST` systématique, le journal d'intention, et le
préfixe `DEMO_` — **la seule réversibilité disponible est de pouvoir
reconnaître ce qu'on a créé.**

**Aucune unicité serveur sur `name`** — Company, Product, Dépositaire, Groupe.
Le doublon n'est pas rejeté : il est créé, en silence, et définitivement.

**Aucun rate limit, et une dégradation silencieuse au-delà de 20-30 requêtes
simultanées, sans `429`.** Un service qui répond `429` se laisse piloter. Un
service qui dégrade sans le dire transforme la surcharge en corruption.

---

## 3. Les délibérations qui n'ont pas laissé de trace

### 3.1 `D-01` — les 4 comptes du Lender

**L'option rejetée** : supposer que la cascade Company crée les 4 comptes.
C'était l'hypothèse initiale, plausible puisque la cascade crée déjà un compte
`OPERATION`.

**Comment elle est tombée** : comptage exhaustif des 42 comptes de
l'environnement. Ils s'expliquent **intégralement** par 3 cascades connues,
zéro résiduel, et **0 Company sur 7** ne portait les 4 types.

**Ce qui est resté ouvert 24 heures** : la décision disait explicitement *« la
création explicite reste non testée en écriture »*. Elle l'est restée jusqu'au
9 août 15h — c'était la **dernière hypothèse non vérifiée du projet**.

### 3.2 `D-03` — un quartier, un Kiosque

**L'option rejetée** : plusieurs Kiosques par quartier, pour atteindre les
volumétries du CDC sans contrainte.

**Pourquoi rejetée** : *« on empilerait plusieurs guichets au même endroit, ce
qu'un bailleur repérerait »*. Argument de crédibilité, pas de technique.

**Ce que ça a coûté, découvert seulement le 9 août** : la Côte d'Ivoire n'a que
17 quartiers. Un tirage à 19 supprimait le pays entier du run. **25 % de
l'écosystème perdu par un coup de dés**, et le défaut est resté invisible
jusqu'au premier `DRY_RUN` réel.

### 3.3 `D-05` — Branche et Agence vivent chez nous

**La délibération** : fallait-il créer Branches et Agences côté serveur ?

**Le fait qui a tranché** : elles n'ont **aucune contrepartie**. Aucun
endpoint, aucun schéma. Le CDC les exige, le serveur ne les connaît pas.

**Ce que j'ai raté 24 heures** : le diagramme de classes les marquait encore
`<<FinZuu API>>`. Corrigé le 9 août seulement, sur votre question.

### 3.4 `D-09` — les 12 rôles

**Ce qui a failli être décidé autrement** : donner `tag: ROOT` au Super-Admin.
Le tag existe **en base** sur le groupe ROOT.

**Pourquoi non** : il est **absent de l'énumération** du contrat. Un tag
persisté que l'enum ne déclare pas est un état que le serveur lui-même ne sait
pas produire. Le Super-Admin porte donc `tag: STAFF` et `UserType: ROOT`.

**Ce que Yaniv a insisté pour clarifier, plusieurs fois** : la distinction entre
le **Super-Admin de la plateforme FinZuu** (un `User` de `UserType.ROOT`) et le
**Super-Admin du Loader** (`super_admin_accounts`, notre base, jamais poussé).
Il y est revenu au moins trois fois. C'est un point où il craignait une
confusion structurelle.

### 3.5 `D-04` — les quotas clients

**Le fait mesuré** : Faker tire naturellement **75/25** Individual/Corporate.
`EF-23` exige **80/20**.

**L'option rejetée** : accepter la distribution naturelle. Refusée parce que le
CDC est explicite.

**La conséquence acceptée** : tirage et rejet. On consomme plus de clients
Faker que nécessaire, et `D-FAKER-1` interdit de réutiliser un `client_id`.

**Trois quotas ne sont protégés par rien côté serveur** : le genre (aucun
paramètre `sex` chez Faker, et le serveur ne valide pas `gender`), l'âge (aucun
filtre d'âge, et **Faker ne fournit aucune date de naissance**), et le secteur.
Le Loader les impose seul.

### 3.6 `A-06` — l'arbitrage qui a débloqué deux sprints

**Le blocage** : `EF-76` nomme quatre fonctions du code de Duhamel
(`ready_scoring/`) que nous n'avions pas.

**Yaniv a transmis le fichier** — `lifecycle_orchestrator.py`. Les 4 fonctions
y sont **verbatim**, et les poids correspondent à `EF-67`.

**La frontière que j'ai posée, et qu'il a acceptée** : le paquet de Duhamel
consomme des **topics Kafka** avec un bootstrap de production. `ENF-16`
l'interdit. **Du travail de Duhamel, le Loader reprend la méthodologie — les 4
fonctions de dates et les 4 profils — jamais le canal Kafka.**

**Découverte au passage** : `_adjust_weights` a une branche sur l'âge du client.
Faker ne fournit **aucune date de naissance**. Cette branche est donc **du code
mort chez Duhamel** — et vivante chez nous, puisque nous générons les dates.

### 3.7 Un désaccord réel, et Yaniv avait raison

Le 9 août, j'ai reporté une anomalie sur les jetons CUSTOMER (401 au lieu de
403). Il m'a poussé à re-vérifier. **En rejouant, CUSTOMER et STAFF donnent
tous deux 403.** Le 401 du matin était transitoire.

J'ai retiré le ticket. C'est le seul cas où j'ai publié une anomalie fausse, et
c'est son insistance sur la re-vérification qui l'a évitée.

**Deuxième cas, même jour** : `ANO-CFG-COUNTRY-02`. J'avais lu
`Country.currency` (singulier) — le champ n'existe pas, c'est `currencies`
(pluriel), et il est correct. Rétracté publiquement.

---

## 4. Ce que le Loader devait devenir

**Réponse honnête : je ne sais pas, et c'est un vrai trou.**

Ce que j'ai dans le dossier :
- `OBJ-05` mentionne un **journal purgeable par préfixe** — donc réutilisable ;
- `EF-50` → `EF-59` décrivent des **routes Super-Admin** de pilotage ;
- `CR-01` → `CR-12` sont des critères de recette d'un **produit livré**, pas d'un script jetable ;
- le diagramme de déploiement prévoit un **frontend Next.js** développé par Zidane, avec un vhost dédié et un certificat déjà en place ;
- `ENF-15` (reproductibilité) et `CR-04` (deux exécutions identiques → même résultat) n'ont de sens que pour un outil **réutilisé**.

**Conclusion que je tire, mais que Yaniv n'a jamais formulée explicitement dans
ce que j'ai en mémoire** : le Loader est un **produit**, pas un script. La
version cible est `v1.0.0` et le SemVer est respecté depuis le début.

**Ce que je n'ai jamais entendu** : ce qui se passe après le 14 août. Ni
maintenance, ni évolution, ni qui reprend. **Question à poser.**

---

## 5. Les zones sans conclusion

### 5.1 Les arbitrages ouverts, avec leur poids réel

| | Sujet | Ce qui bloque | Poids |
|---|---|---|---|
| `A-01` | **Sénégal absent de Faker** | 3 voies : générateur interne pour SN · demander à Oti d'ajouter SN au `run_id` · réduire à 3 pays (contredirait `OBJ-01`) | **500 clients, 25 % du volume** |
| `A-02` | `EF-80` inapplicable tel qu'écrit | les champs `decision.*` n'existent pas ; les 2 000 clients viennent de la famille A qui ne porte aucune décision | bloque le scoring |
| `A-04` | **Où stocker les ~700 prêts simulés** | `loan-service` n'est pas livré. Une 7ᵉ collection ? | `CR-10` et `ENF-14` invérifiables sans ça |
| `A-05` | **Permissions exactes des 12 rôles** | arbitrage produit, pas technique | **les 11 groupes sont en base avec MA proposition** |
| `A-07` | **La forme des 4 profils comportementaux** | `EF-67` fige les poids ; ce que fait chaque profil **jour après jour** vit dans `ready_scoring/`, non transmis | bloque le Sprint 5 entier |
| `A-08` | Désactivation : chez nous / chez eux / les deux | posé le 9 août, jamais tranché | l'exigence du boss |

### 5.2 Les « on verra plus tard » jamais revenus

- **Le nom de domaine** : `loader.*` ou `simul.*` ? Le DNS dit `simul.`, le projet s'appelle Loader. Jamais tranché.
- **Les Agents sont-ils inclus dans les 15–25 staff par pays, ou en plus ?** `UC-09` est ambigu. J'ai tranché « inclus » et signalé le débordement. Jamais confirmé.
- **L'environnement DEMO** : `Config_Loader` cible « TEST + DEMO » depuis le 16 juillet. **Toute notre connaissance empirique est TEST.** Jamais sondé DEMO.

### 5.3 Les hypothèses laissées passer

- **Le budget de 30 minutes** (`ENF-01`) n'a jamais été mesuré. Le `DRY_RUN` sans clients prend 99 s. Je n'ai aucune extrapolation fiable.
- **Aucune écriture MongoDB n'a jamais eu lieu.** Les 6 collections n'ont jamais parlé à un vrai serveur.
- **L'onboarding client n'a jamais tourné en réel.** Zéro client créé à ce jour.

---

## 6. Ce que je sais et qui n'est écrit nulle part

### 6.1 Observations serveur non documentées

**Le format des `account_number` générés** : `04YSYAAUQI4V`, `G4UW2LI463JI`,
`Z4B5WAIWFGAC` — 12 caractères alphanumériques majuscules, apparemment
aléatoires. Le champ est **requis au contrat mais nullable** : on envoie `None`
et le serveur génère. Je n'ai jamais vérifié s'il est unique globalement ou par
propriétaire.

**Les logs serveur sont pollués à 99 % par les kube-probes.** C'est mesuré
(`H23`) et documenté, mais la conséquence l'est moins : **notre SIEM local est
la seule traçabilité réelle du projet.** Si `logs/loader_*.jsonl` est perdu, il
n'y a aucun recours côté serveur.

**Le serveur persiste le JWT en clair dans ses propres logs pendant 7 jours**
(`VIOL-06.7`, classé CRITIQUE). Notre client est délibérément plus strict : il
n'écrit **jamais** les en-têtes de requête.

**`GET /playground-client/random` de Faker a un timeout mesuré à 90 secondes** —
aggravé depuis les 25 s documentés en juillet. Un seul appel mange 5 % du budget
de 30 minutes. Il est interdit en campagne, mais **rien dans le code ne
l'empêche techniquement** : c'est une discipline, pas un garde-fou.

**`POST /v1/faker/cache/clear` existe et n'a jamais été appelé.** Il
réinitialiserait un cache **partagé** avec l'équipe ReadyScore. Je l'ai
délibérément évité. Personne ne m'a dit de le faire — c'était une décision de
prudence.

### 6.2 Intuitions non confirmées

**Le cache Faker est clé par jeu de paramètres complet.** Vérifié. Mais je n'ai
jamais mesuré sa **taille** ni sa **politique d'éviction** — `GET /cache/health`
rendait « Redis 7.4.8, 12 clés » au moment de la mesure. Si le cache se remplit
pendant nos 2 000 tirages, le comportement pourrait changer. **Non testé.**

**Je soupçonne que `chercher_par_nom` sur product-service est O(n) côté
Loader** : il liste tout l'inventaire à chaque appel. Avec 12 produits c'est
sans effet. Avec un catalogue qui grossit à chaque run — et rien ne le purge —
ça pourrait devenir un coût. **Jamais mesuré.**

**Les Companies parasites de l'environnement** (`PROBE_IDENTITY_CASCADE`,
`PROBE_CASCADE_COMPANY`, etc.) sont **nos propres sondes du 8 août**. Elles ne
sont pas préfixées `DEMO_`. Elles ne peuvent pas être supprimées. Elles
apparaîtront dans toute démonstration qui liste les Companies.

### 6.3 Des choses que j'ai remarquées sans les documenter

**HUIT régions ne portent aucune ville** — `CI-05` Denguélé, `CI-13` Woroba,
`BF-13` Sud-Ouest, `SN-03` Fatick, `SN-04` Kaffrine, `SN-06` Kédougou, `SN-09`
Matam, `SN-11` Sédhiou.

> ⚠️ **Correction du 9 août.** Une première version de ce document écrivait
> *« 51 régions pour 50 villes, donc une région sans ville »*. **Arithmétique
> naïve, chiffre faux** : cinq régions portent plusieurs villes (7 villes
> surnuméraires), ce qui masque sept des huit vides. Corrigé sur vérification
> du nouveau pilote.

**Ce ne sont pas des lacunes du classeur — ce sont des choix de construction.**
Un Kiosque de microfinance s'implante dans un quartier urbain identifiable, pas
dans un village sans découpage. Le classeur est **leur** fichier, construit par
eux ; les régions sans ville et les villes sans quartier sont cohérentes avec
le terrain.

**Le fait mesuré à retenir, sans l'interprétation fautive** : la génération
exploite **11 régions sur 51** et **12 villes sur 50** — celles qui portent des
quartiers. `OBJ-01` annonce « 51 régions, 50 villes, 82 quartiers » ; la
démonstration montrera **12 villes**. Ce n'est pas une correction à faire,
c'est **une phrase à préparer pour le 14**. La capacité reste confortable :
82 quartiers pour 40 à 80 Kiosques.

**Le Burkina Faso n'a que 2 villes porteuses de quartiers.** C'est le goulot
d'étranglement de tout l'arbre organisationnel : une Agence placée ailleurs ne
pourrait héberger aucun Kiosque. C'est documenté en tête d'`organisation.py`,
mais jamais remonté comme un risque de volumétrie.

**`Moov Africa CI` est partagé entre `CI` et le pays parasite `ca`.** Une
cascade naïve de désactivation aurait cassé la Côte d'Ivoire. J'ai posé le
garde-fou et documenté, mais **je n'ai jamais vérifié s'il existe d'autres
partages de ce type** au-delà des telcos et devises.

**100 % des devises sont partagées** : XOF entre SN, BF, CI ; XAF pour CM
seulement. Une cascade devise → pays est donc **structurellement impossible**.
`desactiver_devise()` lève toujours.

---

## 7. Ce que vous devriez savoir et n'avez pas demandé

### 7.1 Le fait le plus important du projet

**Rien de ce que le Loader a écrit ne peut être défait.**

11 groupes créés (ceux-là sont supprimables), et **4 comptes financiers
définitifs** sur `DEMO_QA0808_SARL Tamadou Textile`. Plus les 8 Companies de
sondage du 8 août, dont 5 portent des noms `PROBE_*` non préfixés `DEMO_`.

**L'environnement TEST est partagé.** Chaque écriture y est visible par les
autres équipes, et permanente.

### 7.2 Ce qui n'existe pas et que le calendrier suppose

À 5 jours de la démonstration :

| | État |
|---|---|
| Le client Faker | **n'existe pas** — 20 patronymes codés en dur |
| Le module Clients (Sprint 4) | **n'existe pas** — 0 client créé |
| Le module Vie 180 jours (Sprint 5) | **n'existe pas** — 0 ligne |
| Le module Recette (`CR-01`→`CR-12`) | **n'existe pas** |
| Les routes Super-Admin (`EF-50`→`EF-59`) | **n'existent pas** |
| Le frontend | **Zidane, aucun commit connu** |
| MongoDB local | **non installé** |

**Ce qui existe et fonctionne** : le référentiel géographique complet, les 9
clients avec leurs 65 disciplines, 4 exécuteurs, l'orchestrateur, les
invariants, 393 tests. C'est beaucoup — mais c'est **la moitié amont** du
projet.

### 7.3 Le piège de méthode qui m'a eu, et qui vous aura

**Le rétrofit avant.** Chaque capacité nouvelle a été branchée dans les modules
écrits **après** elle, jamais dans ceux écrits **avant**. Prouvé par les
horodatages.

Si vous ajoutez une capacité transverse, **la seule protection est de vérifier
immédiatement tous les consommateurs existants**, pas seulement d'écrire le
nouveau code correctement.

### 7.4 Les tests ne mesurent pas ce que vous croyez

393 tests, tous verts, tous honnêtes — et **aucun ne teste une arête du
graphe**. Ils testent des nœuds. Le défaut le plus grave que vous avez trouvé
(#8, `nb_kiosques` dupliqué) est invisible pour eux **par construction**.

**« `ruff` + `mypy` + tests verts » n'est pas une définition de terminé.** Je
l'ai présentée comme telle dans `PLAN_SPRINTS.md`. C'est à corriger.

### 7.5 Ce que Yaniv craignait le plus

Revenu trois fois, avec des mots presque identiques :

> *« rien n'est cassé en conception, n'est-ce pas ? tout est clair ? j'espère
> que tout ce qu'on a passé du temps à dire, à faire, ne tombe pas à l'eau. »*

Sa peur n'était pas le bug. C'était que **le travail de conception soit perdu** —
que les décisions se dissolvent dans le code sans que personne puisse les
retrouver.

C'est pour ça que `DECISIONS.md` existe, que les commits sont longs, et que
`DOCTRINE.md` est écrit *« pour quelqu'un qui n'était pas là »*.

**Ce document en fait partie.**

### 7.6 Une chose que je dois dire sur moi

J'ai livré chaque module en annonçant qu'il était terminé, vérifié, vert. Sur le
plan du module, c'était vrai. **Sur le plan du système, j'ai décrit des
capacités comme des comportements** — l'orchestrateur « sait reprendre », le
Catalogue « refuse avant le réseau », `D-ACC-3` est « lue au démarrage de chaque
campagne ». Ces phrases sont vraies du code et fausses de l'exécution.

Vous l'avez trouvé en une passe d'audit. **Prenez chacune de mes affirmations
de livraison comme portant sur le module, jamais sur la chaîne**, tant qu'un
test d'intégration ne l'aura pas prouvé.

---

*Écrit le 9 août 2026. Si quelque chose ici contredit le code, c'est le code qui
fait foi — et cette contradiction est elle-même une information.*
