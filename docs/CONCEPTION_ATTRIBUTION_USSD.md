# Conception — Mécanisme d'attribution USSD

**Référence** FZ-CONC-ATTRIB-2026-001 · version 0.1 · à valider
**Face serveur du contrat** `FZ-CONTRAT-ATTRIB-2026-001 v0.3` (VALIDÉ 24/08, figé — copie : `docs/CONTRAT_ATTRIBUTION_USSD.md`) — les routes,
corps et codes de ce document sont **exactement** ceux du contrat ; cette note
ne les redéfinit pas, elle dit comment le Loader les tient.
**Couvre** `INV-SIM-01` `CR-06` (atomicité) · `EF-17` (libération) · autorité
serveur sur l'échéance · listes fermées servies · le trou de l'attribution
perdue.

---

## 0. Trois faits mesurés qui commandent tout

**F1 — le pool existe déjà, c'est `org_hierarchy` niveau CLIENT.** Chaque
client créé par un run REAL y laisse un nœud portant précisément les trois
critères du tirage — `country_code`, `gender`, `categorie` (rangés par `P-04`
à l'écriture, ce sont *nos décisions de quota*, aucune vérité concurrente ne
peut diverger) — et son msisdn dans `name` (`"Client {msisdn}"`). L'index
`idx_profil_client` sert déjà exactement cette requête. **Aucune nouvelle
source de données n'est nécessaire pour le tirage.**

**F2 — le msisdn est stable d'un run à l'autre** (`D-CLI-11` : il dérive du
client, pas du run). C'est la clé naturelle du bail, et c'est elle qui règle
la question « que se passe-t-il si le Loader recrée sa population ? ».

**F3 — `RegistreUnicite` ne se réemploie PAS.** Sa docstring le dit :
*« une mémoire de processus suffit — une exécution est un seul processus »*.
Il garde l'unicité msisdn/id_number/email **pendant un run**, dans la RAM de
ce run. L'attribution est l'inverse : des requêtes HTTP concurrentes, sans
run, qui doivent se coordonner **dans la base**. Le réemployer serait lui
faire porter un contrat qu'il ne tient pas. Ce qui se réemploie, c'est le
*motif* qui a produit `VerrouRepository` (`C2`) : « GET-avant-POST n'est sûr
que séquentiellement » — mais ici, mieux qu'un verrou : une primitive
nativement atomique (§3).

**État du jour, et le changement de statut qui en découle (arbitrage Yaniv,
24/08) :** la carte a été purgée le 24/08 — c'était le geste exceptionnel
d'AVANT le run qui bâtit. Une fois la population bâtie et l'attribution en
service, la doctrine s'inverse : **`org_hierarchy` niveau CLIENT n'est plus
une simple carte d'observation, c'est le STOCK des numéros attribuables** —
un actif de production dont dépend un service tiers. On ne le purge plus.
La purge reste un outil d'exception, et elle doit désormais SAVOIR ce qu'elle
casserait (§1.5). Le mécanisme reste honnête sur un pool vide — même code que
« stock épuisé » — mais ce cas ne doit plus se produire qu'avant la première
mise en service.

---

## 1. Modèle de données

### 1.1 Où vivent les baux — les deux options, et le choix

**Option A — un champ `bail` sur le nœud client d'`org_hierarchy`.**
Séduisante : le tirage et le marquage deviennent UN `find_one_and_update`
(filtre profil + « pas de bail actif », `$set` du bail). Atomicité gratuite.

Rejetée pour trois raisons :

1. **La purge tuerait les baux.** `org_hierarchy` est dans
   `COLLECTIONS_NOTRE_CARTE` (US-F3, effaçable). Un bail est un engagement
   envers un *appareil externe* — il ne doit pas mourir parce qu'on a vidé
   notre carte interne.
2. **La recréation de population perdrait les baux.** Un nouveau run écrit de
   nouveaux nœuds ; le champ bail de l'ancien nœud disparaît avec lui, alors
   que le msisdn — et le client réel côté plateforme — sont toujours là.
3. **Deux runs peuvent porter le même client** (nœud par run). Un bail par
   nœud n'est plus « un bail par client » : `INV-SIM-01` se raisonnerait sur
   la mauvaise unité.

**Option B — une collection dédiée `attribution_baux`, `_id = msisdn`.**
Retenue. Le msisdn est stable (F2), unique par construction (`_id`), et le
bail survit à la purge comme à la recréation de population. L'atomicité reste
entière : elle porte sur la collection des baux, pas sur le pool (§3).

### 1.2 Le document de bail

```
attribution_baux
  _id              msisdn (chaîne brute, indicatif compris)   ← unicité native
  attribution_id   UUID, la poignée opaque rendue à l'app
  cle_idempotence  chaîne, l'Idempotency-Key de la requête
  profil           { pays, genre, categorie }   — ce qui a été demandé
  attribue_le      datetime UTC (serveur)
  expire_le        datetime UTC (serveur)       — l'AUTORITÉ sur l'échéance
```

Aucune donnée personnelle au-delà du msisdn — le nom, la profession, la fiche
restent dans `org_hierarchy` et sur la plateforme. Le bail est un fait
d'occupation, pas une copie du client.

### 1.3 Index

| Index | Requête servie |
|---|---|
| `_id` (msisdn) | acquisition et libération — natif, unique |
| `uniq_attribution_id` (unique) | `DELETE /attributions/{id}` — la libération cherche par poignée, jamais par msisdn (l'app ne détient que la poignée comme clé d'action) |
| `uniq_cle_idempotence` (unique, sparse) | rejeu d'une attribution — le trou §4 |
| `idx_expire_le` (TTL, `expireAfterSeconds` ≈ 30 jours APRÈS échéance) | **concierge, jamais arbitre** — même doctrine que `verrous.py` : « le TTL purge à la minute, on ne s'y fie pas ». Il nettoie les baux morts pour que la collection ne croisse pas sans borne ; l'expiration *fonctionnelle* est décidée à la lecture (§5) |

Sur `org_hierarchy`, **rien à ajouter** : `idx_profil_client` couvre le tirage.

### 1.4 Classement US-F3 — décision à prendre

Le test `les_deux_listes_couvrent_TOUTES_les_collections` refusera la
collection non classée. Deux lectures possibles :

- **effaçable** : si on vide la carte, le pool disparaît — des baux sur un
  pool inexistant ne servent plus personne ;
- **protégée** : un bail engage un appareil externe ; le purger coupe une
  démonstration en cours.

**Recommandation : protégée.** La purge de la carte est un geste interne ; les
baux sont la seule collection du Loader dont dépend un tiers *en ce moment
même*. Un bail orphelin (msisdn absent de la carte repeuplée) est inoffensif :
il ne matche plus aucun tirage et le TTL le ramasse. L'inverse — couper une
démo — ne se rattrape pas.

### 1.5 La purge elle-même change de sens (arbitrage Yaniv, 24/08)

Protéger les baux ne suffit pas : **le pool est dans `org_hierarchy`**, et
`org_hierarchy` est classée effaçable (US-F3). Purger la carte avec
l'attribution en service viderait le stock de numéros pendant que des
appareils le consomment — des baux intacts sur un pool disparu.

La règle, gravée dans le code et pas dans une consigne :

- `US-F3` gagne une **garde d'attribution** : vider notre carte est REFUSÉ
  tant qu'il existe au moins un bail actif (`expire_le > now`), avec le
  compte et la première échéance dans le message — « 3 bail(s) actif(s),
  le plus long expire le 31/08 » — jamais un refus muet ;
- l'écran Purge affiche cet état AVANT la case à cocher : l'opérateur voit
  pourquoi le geste est fermé et quand il rouvrira ;
- aucun contournement par défaut. Si un jour il faut vraiment purger sous
  baux actifs (incident), c'est une décision explicite qui passera par une
  évolution assumée — pas par une option cachée aujourd'hui.

La purge redevient ce qu'elle doit être : l'outil de remise à zéro d'AVANT la
mise en service, pas un geste d'exploitation courante.

---

## 2. Déroulé d'une attribution

```
POST /api/v1/attribution/attributions   { pays, genre, categorie }
Idempotency-Key: <uuid>
```

1. **Rejeu ?** Lecture sur `uniq_cle_idempotence`. Trouvé → on rejoue le
   `201` d'origine, sans tirage. C'est la moitié de la réponse au trou (§4).
2. **Critères valides ?** Pays/genre/catégorie confrontés au référentiel.
   Hors référentiel → `422 CRITERE_INVALIDE` (défaut applicatif, écran 10).
3. **Candidats.** `org_hierarchy` : `niveau=CLIENT` + les trois critères,
   projection sur `name` → liste de msisdn. Vide → `409 STOCK_EPUISE`
   (le pool n'a jamais eu ce profil — ou la carte est purgée : même vérité).
4. **Baux actifs.** Une lecture d'`attribution_baux` sur ces msisdn,
   `expire_le > now` → l'ensemble des occupés. `candidats − occupés` vide →
   `409 STOCK_EPUISE` (tout est pris).
5. **Ordre de tirage** — aléatoire ET reproductible (§6) : candidats libres
   triés par `sha256(cle_idempotence + ":" + msisdn)`.
6. **Acquisition atomique**, candidat par candidat dans cet ordre :

   ```python
   try:
       insert_one({_id: msisdn, attribution_id, cle_idempotence,
                   profil, attribue_le: now, expire_le: now + 7j})
   except DuplicateKeyError:
       # un bail existe — actif, ou échu ?
       pris = find_one_and_update(
           {"_id": msisdn, "expire_le": {"$lt": now}},   # ÉCHU seulement
           {"$set": {nouveau bail}},
       )
       if pris is None:
           continue          # actif : candidat suivant, jamais d'attente
   ```

   L'`insert_one` sur `_id` et le `find_one_and_update` filtré sur l'échéance
   sont chacun **indivisibles côté Mongo**. Deux appareils sur le même msisdn :
   un seul insert gagne, l'autre reçoit `DuplicateKeyError` et passe au
   candidat suivant. La concurrence ne produit jamais un double — au pire un
   détour (§3).
7. **Tous les candidats perdus** (concurrence extrême sur un pool presque
   vide) → `409 STOCK_EPUISE`. Honnête : au moment du dernier essai, il n'y
   avait rien de libre.
8. **Réponse `201`** : `attribution_id`, `msisdn`, `expire_le`, `attribue_le`
   — tous produits par le serveur. Étape 6 AVANT étape 8 : le marquage précède
   toujours la réponse, jamais l'inverse.

**Chemins d'échec, table du contrat §4 :** `409 STOCK_EPUISE` (écran 11) ·
`422 CRITERE_INVALIDE` (écran 10) · `400 CLE_IDEMPOTENCE_REQUISE` (écran 10) ·
`500 ERREUR_SERVEUR` (écran 10) · pas de réponse (écran 9). La distinction
409/500 est structurelle ici : le 409 est un **résultat calculé** (ensemble
vide), jamais une exception attrapée.

---

## 3. Atomicité — la primitive, et sa preuve

**Primitive : l'unicité de `_id` dans `attribution_baux`.** Le tirage n'est
pas « choisir puis marquer » — le marquage EST le tirage : celui dont
l'`insert_one` passe a tiré. Il n'existe aucune fenêtre entre lecture et
écriture pendant laquelle un autre appareil peut prendre le même msisdn,
parce que la décision est rendue par l'index unique de Mongo, pas par notre
code.

`VerrouRepository` (C2) n'est **pas** utilisé ici. Le verrou sérialise ; or on
n'a pas besoin de sérialiser : deux tirages concurrents sur le même profil
sont *souhaitables* et doivent réussir tous les deux — sur deux clients
différents. L'ordre de tirage haché par clé d'idempotence (§6) disperse
d'ailleurs les candidats : deux appareils simultanés commencent presque
toujours par des msisdn différents et ne se rencontrent même pas.

**Preuve par test — jamais une affirmation :**

1. *Le duel.* Pool réduit à UN client libre. Deux `POST` lancés par
   `asyncio.gather` sur la vraie base Mongo de test. Attendu : exactement un
   `201` et un `409`, et `attribution_baux` contient UN document.
2. *La meute.* 10 libres, 25 requêtes concurrentes. Attendu : 10 `201`
   portant **10 msisdn deux à deux distincts**, 15 `409`, 10 documents.
3. *Le vol de bail échu.* Un bail expiré, deux requêtes concurrentes visant ce
   msisdn (pool de 1). Attendu : un seul `find_one_and_update` gagne — un
   `201`, un `409`.

Ces tests tournent contre Mongo réel (la suite du Loader le fait déjà), pas
contre un bouchon — un bouchon prouverait notre implémentation du bouchon.

---

## 4. Le trou de l'attribution perdue

Le scénario : marquage réussi, réponse perdue. Un client attribué que personne
ne détient. **Aucun serveur ne peut distinguer « réponse perdue » de « client
parti »** — traiter le trou, c'est le rendre *récupérable* et *borné*, pas
l'empêcher.

**Récupérable — la clé d'idempotence (le cas nominal).** L'application
génère la clé AVANT d'émettre, et la conserve tant que la tentative n'a pas
abouti. Réseau tombé → elle réessaie avec la MÊME clé → étape 1 du déroulé la
reconnaît (`uniq_cle_idempotence`) et rejoue le `201` d'origine : le même
client, le même bail, **aucun second tirage**. Le client n'était pas perdu —
il attendait son propriétaire. Rétention : 72 heures, confirmées à la
validation v0.3. Le document de bail portant la clé, elle vit naturellement
avec lui — le serveur cesse simplement de la reconnaître comme rejeu au-delà
de 72 h (comparaison sur `attribue_le`, aucun second index temporel).

**Borné — trois filets, dans l'ordre :**
- l'usager abandonne définitivement (désinstallation…) → le bail expire à
  7 jours et le msisdn redevient tirable à la lecture (§5). Perte maximale :
  un client, sept jours — jamais une érosion silencieuse ;
- la recette peut libérer immédiatement : `DELETE /attributions/{id}` — et
  l'`attribution_id` figure dans la réponse rejouée comme dans le journal ;
- le TTL ramasse les documents morts, la collection ne croît pas.

**Ce qu'on ne fait PAS : un « accusé de réception ».** Exiger que l'app
confirme la bonne réception pour activer le bail déplace le trou (l'accusé
peut se perdre aussi) et double les états. L'idempotence règle le problème à
la racine : la réponse perdue devient simplement re-demandable.

---

## 5. Expiration — passive, tranchée

**Active (tâche de fond)** : un balayage marque les baux échus. Avantage :
compteurs `libres` toujours exacts. Défauts : un minuteur qui s'arrête fige le
pool (la doctrine du Loader l'a déjà rejeté pour les versions V-01 : « rien à
surveiller ») ; et il introduit une fenêtre où l'état en base ment (échu mais
pas encore balayé).

**Passive (à la lecture)** : un bail est échu quand `expire_le < now`, point.
Le tirage traite l'échu comme libre (étape 6, le `find_one_and_update` filtré) ;
la disponibilité (`GET /criteres`) compte `expire_le > now` ; la libération
d'un bail échu rend `404` (déjà mort). Aucun processus à surveiller, aucun
état intermédiaire, l'horloge du **serveur** est la seule autorité — changer
l'heure du téléphone ne prolonge rien, exactement la contrainte 2.

**Tranché : passive.** Le TTL Mongo reste comme concierge (nettoyage physique,
30 jours après échéance — les baux morts servent d'historique de recette entre
temps), jamais comme arbitre : c'est mot pour mot la doctrine de `verrous.py`.

**Un bail échu est donc libre *immédiatement*** — pas « à la première
sollicitation » au sens d'un état à basculer : il n'y a pas d'état à
basculer. `expire_le < now` EST l'état libre. La première sollicitation ne le
libère pas, elle le *constate*.

---

## 6. Sélection — aléatoire, et reproductible

`$sample` de Mongo est aléatoire mais **non semable** : un test ne peut pas le
rejouer. Tri par msisdn : reproductible mais pas aléatoire — le même client
sortirait toujours en premier, usure inégale du pool et collisions garanties
entre appareils simultanés.

**Retenu : tri par empreinte, semé par la clé d'idempotence.**

```
ordre = sorted(libres, key=lambda m: sha256(f"{cle_idempotence}:{m}"))
```

- **aléatoire en pratique** : la clé est un UUID v4, l'ordre est uniforme,
  le pool s'use uniformément ;
- **reproductible exactement** : un test qui fixe la clé connaît l'ordre
  complet du tirage — il peut affirmer *quel* client sortira, pas seulement
  « un client » ;
- **anti-collision gratuit** : deux appareils simultanés ont deux clés, donc
  deux ordres différents — ils convergent rarement sur le même candidat, la
  boucle d'acquisition ne détourne presque jamais.

C'est le motif `ENF-15` du Loader (tout tirage dérive d'une graine stable),
appliqué avec la graine naturellement disponible par requête.

---

## 7. Vérification et libération

### Vérification — `GET /api/v1/attribution/attributions/{attribution_id}`

Ajoutée à la validation v0.3 : c'est elle qui rend l'autorité serveur
*exerçable* — l'application l'appelle à chaque lancement.

Implémentation : UNE lecture sur `uniq_attribution_id`, puis la même vérité
calculée que partout — `expire_le > now` → `200` avec le bail ; introuvable
**ou** échu → `404`. Aucun état à basculer, aucun code d'expiration : le
`404` du bail échu tombe du §5 tout seul. Route en lecture pure, aucune
écriture, aucun verrou.

### Volontaire — `DELETE /api/v1/attribution/attributions/{attribution_id}`

1. `find_one_and_delete({"attribution_id": id})` — atomique, par poignée.
2. Trouvé et `expire_le > now` → `204`, le msisdn est re-tirable à l'instant.
3. Trouvé mais échu, ou introuvable → `404` — **succès fonctionnel** (contrat
   §3) : le bail n'existe plus, le but est atteint. L'app efface son état
   local dans les deux cas.
4. Chaque libération est journalisée dans `audit_trail` sous `RUN_ADMIN`
   (`entity_type="AttributionBail"`, action `DELETE`) — la recette doit
   pouvoir répondre à « qui a libéré quoi, quand », c'est son outil.

Pas de corps, pas de confirmation en deux temps : l'appelant est l'écran 8
(instrumentation), déjà gardé par la manipulation délibérée côté app, et le
geste est réversible en re-tirant.

### Par expiration

Il n'y a **pas de déroulé** : c'est le §5. Aucun code ne s'exécute à
l'échéance ; la vérité change toute seule parce qu'elle est calculée, jamais
stockée comme un drapeau.

---

## 8. Exposition — comment, sans dénaturer le Loader

**Correction d'un présupposé de l'énoncé : le Loader a déjà un frontend
HTTP.** C'est une application FastAPI (`app/main.py`) servie sur
`simul.api.fintech4esg.com`, avec routeurs, CI/CD et déploiement. Ce qui est
vrai : tout ce qu'elle expose aujourd'hui est de l'**administration
authentifiée par session**. La nouveauté n'est pas « exposer du HTTP », c'est
« exposer trois routes *publiques* ».

**Un routeur dédié, une frontière nette :**

```
app/routes/attribution_publique.py     préfixe /api/v1/attribution
```

- **hors de `/admin`**, sans `SessionAdmin` — `ENF-07` l'exige et §8.1 le
  borne ;
- **surface minimale et fermée** : `GET /criteres`, `POST /attributions`,
  `GET /attributions/{id}` (v0.3), `DELETE /attributions/{id}`. Rien d'autre. Aucune de ces routes ne crée,
  modifie ou supprime un client, un pays, une écriture de la carte — elles ne
  touchent QUE `attribution_baux` (+ le journal). La nature d'outil de
  peuplement est intacte : l'attribution *consomme* le peuplement, elle n'y
  participe pas ;
- l'**écran Observatoire** pourra plus tard lire les baux (combien, par pays,
  échéances) — lecture seule, cohérent avec P-06. Hors périmètre de cette
  note.

### 8.1 Authentification — la tension, exposée honnêtement

`ENF-07` : aucun compte, aucune authentification. Donc trois routes ouvertes
sur l'Internet, dont une qui écrit. Risques réels : un curieux vide le pool
(64 clients ≈ 64 requêtes), ou énumère des `DELETE`.

Ce qui ne marche pas : une clé dans l'APK (un APK se décompresse — le contrat
§5 le dit déjà). Ce qui relève de l'infrastructure, pas de cette note :
filtrage d'origine, pare-feu. Ce que je propose **dans** le périmètre, sans
violer `ENF-07` :

- `DELETE` introuvable → `404` uniforme, jamais d'énumération possible
  (l'`attribution_id` est un UUID v4 : 2¹²² essais) ;
- **garde de débit** par adresse source sur `POST /attributions` (réutilisation
  du motif `auth_throttle` / I-AUTH-11 : ralentir, jamais verrouiller) —
  paramétrable, désactivable pour la recette ;
- journalisation de chaque attribution et libération : si le pool se vide, on
  saura par qui et quand.

**La décision d'un filtrage réseau au-dessus reste à la Direction** — hors de
mon périmètre, je la signale sans la trancher.

---

## 9. `GET /criteres` — les listes servies

Une agrégation sur `org_hierarchy` (`niveau=CLIENT`, groupée
pays × genre × catégorie) moins les baux actifs = `disponibilite` avec
`libres` par combinaison, exhaustive (absent = 0), conforme au contrat §1.
Les libellés `libelle_fr`/`libelle_en` des pays sortent de la **surcouche
référentielle** (`loader_configuration`) — le Loader les possède déjà, aucune
table nouvelle. Genres et catégories : libellés embarqués dans la route (deux
valeurs chacun, référentiel plateforme).

Pas de cache : deux requêtes Mongo par appel, sur des collections indexées de
quelques milliers de documents. Le contrat exige du frais (« aucun cache ») et
le coût est nul.

---

## 10. Ce que je ne tranche pas seul

1. ~~Classement US-F3~~ — **tranché par Yaniv le 24/08** : `attribution_baux`
   protégée, ET la purge de la carte refusée tant qu'un bail est actif
   (§1.5). La population bâtie ne se purge plus.
2. **Filtrage réseau au-dessus des routes publiques** (§8.1) — Direction.
3. **Durée du bail : 7 jours en constante ou paramètre de configuration ?**
   Le CDC dit sept jours ; je propose une constante nommée (`BAIL_JOURS = 7`)
   — un paramètre inviterait à la dérive sans exigence qui le demande. À
   confirmer.
4. **Dimensionnement du pool** — question déjà ouverte au contrat §7 et au
   deck : combien de démos simultanées pour ~64 clients par profil ? La
   réponse conditionne peut-être un bail plus court. Donnée Direction.
5. **La garde de débit** (§8.1) : seuils à fixer avec la recette pour ne pas
   gêner CR-06 (attributions simultanées volontaires).

---

## 11. Ordre d'implémentation proposé (après validation)

1. `attribution_baux` + index + classement US-F3 (décision §10.1 requise).
2. Le repository (acquisition atomique, libération, disponibilité) + les
   trois tests de concurrence du §3 — **les tests d'abord**, ils définissent
   l'atomicité avant qu'une ligne de route n'existe.
3. Les trois routes + table d'échecs du contrat.
4. Journalisation + garde de débit.
5. Rejeu complet contre la prod une fois un run REAL passé (le pool est vide
   aujourd'hui — F0).

---

*Rédigé pour validation avant toute implémentation. Le contrat v0.2 fait foi
côté application ; toute divergence découverte pendant l'implémentation
remonte ici avant d'être codée.*
