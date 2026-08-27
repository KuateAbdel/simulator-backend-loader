# Contrat — Service d'attribution

**Référence** FZ-CONTRAT-ATTRIB-2026-001 · version 0.4 · en validation (révisions 0.3.x VALIDÉES, QA Lead 24/08)
**Consommateur** Simulateur USSD FinZuu (application React Native)
**Fournisseur** Loader FinZuu
**Couvre** `EF-01` `EF-02` `EF-03` `EF-04` `EF-05` `EF-15` `EF-17` `EF-20` `EF-22` · `INV-SIM-01` `INV-SIM-03` `INV-SIM-04` `INV-SIM-06` `INV-SIM-07` · `CR-04` `CR-05` `CR-06` `CR-08` `CR-14` · `ENF-05` `ENF-07`

> **Révision 0.4 — l'appareil, et la durée (25/08).** LA révision unique
> convenue après la mise en service. **(a) Le champ `appareil`** : la requête
> d'attribution PEUT porter une étiquette `appareil` — marque + modèle
> (« Redmi Note 13 »), telle que l'app la lit sans permission ni dépendance
> (`Build.BRAND`/`Build.MODEL`). Optionnelle, normalisée par le serveur
> (blancs retirés, 64 caractères max, tronquée jamais refusée — un champ de
> confort ne fait pas échouer une attribution), stockée sur le bail, exposée
> à l'administration en face du msisdn. **Ce n'est PAS un identifiant** :
> deux téléphones identiques portent la même étiquette ; aucun numéro de
> série, aucun IMEI, aucun identifiant publicitaire — rien qui désigne UN
> appareil. **(b) La durée du bail** — **LIVRÉE LE 27/08** : les sept jours
> **ont cessé** d'être une constante gravée. C'est un RÉGLAGE d'administration
> — valeur globale, surchargeable par pays, bornée 1 à 30 jours, **résolue au
> moment du tirage** et jamais mise en cache : un réglage changé vaut dès
> l'attribution suivante, sans redémarrage du service. Les baux existants
> gardent l'échéance qu'ils portent (option 1 : un bail est une promesse
> datée, on ne réécrit pas une promesse). L'application n'affiche pas « sept
> jours » mais LA DATE d'échéance que le serveur rend — ce qu'elle fait déjà
> (`expire_le` fait foi). La mécanique (§2, §3, §5) est inchangée : mêmes
> routes, mêmes conduites, mêmes garanties prouvées. Détail en **§2.3**.
>
> **Révision 0.3.1 — réserve levée (QA Lead, 24/08).** La clé d'idempotence
> est **persistée dès son émission et effacée à réception du `201`** : sans
> cela, une application tuée entre l'émission et la réponse — système,
> batterie, fermeture — perdait la clé, l'usager recommençait avec une
> nouvelle, et le premier client restait marqué sept jours. Le trou que la
> clé fermait se rouvrait au redémarrage. Cinq valeurs stockées
> transitoirement, quatre en régime établi (§2).
>
> **Révision 0.3 — validation du 24/08.** Deux corrections : la route de
> vérification du bail est ajoutée (§3 — sans elle, `EF-15` reposait sur la
> seule horloge du téléphone, ce que ce contrat interdit) ; la transmission de
> la langue au service USSD est retirée (l'arborescence arrêtée par la
> Direction porte une option « Changer Langue » dans le menu — la langue des
> menus se règle dans le parcours, l'application ne transmet rien). Rétention
> d'idempotence confirmée à 72 h ; routes ouvertes confirmées (`ENF-07`).
>
> **Révision 0.2 — dossier du 23/08.** Les libellés de `GET /criteres` passent
> au bilingue : le paramètre de langue (`EF-19` à `EF-21`) fait entrer un choix
> d'affichage là où le service détient la donnée. Voir §1.2. L'état local passe
> de trois à quatre valeurs (`INV-SIM-06` révisé).

---

## 0. Ce que ce contrat engage

L'application code **contre ce document**, jamais contre son implémentation. Le
serveur local de développement et le Loader en production doivent être
interchangeables par un simple changement d'adresse — c'est la condition qui
maintient `INV-SIM-03` : aucun simulacre ne peut entrer dans l'application.

Trois règles gouvernent l'ensemble :

1. **Le service est seul à savoir** quelles combinaisons de profil sont
   pourvues. L'application ne fige aucune liste et n'invente aucune valeur.
2. **Un tirage est atomique.** Deux appareils simultanés ne peuvent pas
   recevoir le même client (`INV-SIM-01`, `CR-06`).
3. **Un échec porte toujours un code exploitable.** *Stock épuisé* et *erreur
   serveur* sont deux situations distinctes, sans quoi l'écran 11 est
   inaffichable (`ENF-05`).

Base : `/api/v1/attribution` · corps et réponses en `application/json` · dates
en ISO 8601 UTC (`2026-08-31T14:22:07Z`).

---

## 1. `GET /api/v1/attribution/criteres`

Sert les trois listes fermées des écrans 2 (`EF-01`, `EF-02`, `EF-03`) **et leur
disponibilité réelle**.

### Pourquoi la disponibilité fait partie du contrat

`EF-01` restreint les pays « à ceux effectivement couverts par la population ».
Sans le stock, l'application proposerait des combinaisons vides et conduirait
l'usager dans un cul-de-sac — l'écran 11 en pleine démonstration devant un
partenaire. Le service rend donc, en une lecture, ce qui est proposable **et**
ce qui est servable.

### Réponse `200`

```json
{
  "pays": [
    { "code": "CM", "libelle_fr": "Cameroun",       "libelle_en": "Cameroon" },
    { "code": "CI", "libelle_fr": "Côte d'Ivoire",  "libelle_en": "Ivory Coast" }
  ],
  "genres":     [ { "code": "MALE",   "libelle_fr": "Homme",       "libelle_en": "Male" },
                  { "code": "FEMALE", "libelle_fr": "Femme",       "libelle_en": "Female" } ],
  "categories": [ { "code": "INDIVIDUAL", "libelle_fr": "Particulier", "libelle_en": "Individual" },
                  { "code": "CORPORATE",  "libelle_fr": "Entreprise",  "libelle_en": "Business" } ],
  "disponibilite": [
    { "pays": "CM", "genre": "FEMALE", "categorie": "INDIVIDUAL", "libres": 214 },
    { "pays": "CM", "genre": "MALE",   "categorie": "CORPORATE",  "libres": 0 }
  ],
  "releve_le": "2026-08-24T18:40:00Z"
}
```

| Champ | Règle |
|---|---|
| `code` | valeur du référentiel plateforme, transmise telle quelle au tirage. Pays en **ISO 3166-1 alpha-2** |
| `libelle_fr` `libelle_en` | **affichage seulement.** Ils ne portent aucune décision |
| `disponibilite` | **exhaustive** : toute combinaison absente vaut `libres = 0` |
| `libres` | clients non attribués **maintenant**. Indicatif, jamais une réservation |

`disponibilite` est une **photographie**, pas une promesse : un tirage peut
échouer en `409` juste après une lecture qui annonçait `libres > 0`. C'est
normal et l'application doit le traiter — la seule vérité est le tirage.

**Aucun cache.** L'écran 2 relit à chaque affichage : le stock bouge à chaque
attribution et à chaque expiration.

### 1.2 Pourquoi les deux langues, et pas un paramètre

`INV-SIM-07` interdit à l'application de traduire ce que le service restitue.
Or un nom de pays vient du service. Deux voies s'ouvraient :

- **un paramètre `?langue=`** — le service ne rend qu'une langue. Mais un
  changement de langue exigerait alors un nouvel appel réseau, et l'écran 2
  resterait figé dans l'ancienne langue si le réseau venait à tomber entre les
  deux. Le sélecteur deviendrait dépendant du réseau ;
- **les deux libellés en une lecture** — l'application *choisit* celui qui
  correspond à la langue retenue. Elle n'en produit aucun. `EF-20` est tenue
  hors ligne, et `CR-14` — le parcours complet dans les deux langues — se
  vérifie sans dépendre du serveur.

La seconde est retenue. Elle est aussi la seule qui respecte `INV-SIM-07` à la
lettre : *demander une langue, n'en produire aucune*.

**Ce que le service ne rend PAS.** Les textes propres à l'application — titres
d'écran, boutons, messages des écrans 9 à 13 — sont **embarqués** en français
et en anglais (`§5.4` du cahier des charges). Le service ne les fournit jamais.
La frontière est nette : le service rend ce qu'il **détient** (noms de pays,
libellés de référentiel), l'application porte ce qu'elle **dit**.

---

## 2. `POST /api/v1/attribution/attributions`

Tire un client libre correspondant au profil, le marque attribué, et rend son
numéro. C'est le geste central de la phase 1 (`EF-04`, `EF-05`).

### Requête

```json
{
  "pays": "CM",
  "genre": "FEMALE",
  "categorie": "INDIVIDUAL",
  "appareil": "Redmi Note 13"
}
```

`pays`, `genre`, `categorie` : les codes des LISTES FERMÉES servies par
`GET /criteres` — l'application les présente en menus déroulants, rien n'est
saisi. `appareil` (révision 0.4) : optionnel — étiquette marque + modèle pour
la lecture d'exploitation, normalisée serveur (64 max), jamais un identifiant.

En-tête **obligatoire** :

```
Idempotency-Key: 9f2c1e70-5b3a-4a1e-9f0d-2b7c8e441a03
```

### Pourquoi une clé d'idempotence

Sans elle, une réponse perdue en chemin — réseau coupé après le marquage —
laisse un client marqué attribué que personne ne détient. Le numéro est
**perdu pour sept jours**, et le pool se vide silencieusement à chaque
démonstration ratée.

L'application génère un UUID v4 **par tentative d'attribution**, et le
**persiste dès son émission** — pas seulement en mémoire : une application
tuée entre l'émission et la réponse (système, batterie, fermeture) doit
retrouver sa clé au redémarrage, sinon l'usager recommence avec une nouvelle
clé, un second client est tiré et le premier reste marqué sept jours — le
trou §0 rouvert. La clé est **effacée à réception du `201`**, et renouvelée
seulement quand l'usager change de profil. Le service conserve la
correspondance `clé → attribution` **72 heures au minimum** et rejoue la même
réponse `201` pour une clé déjà vue, sans tirer un second client.

### Réponse `201`

```json
{
  "attribution_id": "3f8b2c14-77ad-4c3e-9a11-0d5e6f8b2c14",
  "msisdn": "237699000006",
  "expire_le": "2026-08-31T18:42:11Z",
  "attribue_le": "2026-08-24T18:42:11Z"
}
```

| Champ | Règle |
|---|---|
| `attribution_id` | **poignée du bail**, opaque. Seule clé de la vérification (§3) et de la libération (§4) |
| `msisdn` | **format brut, indicatif compris.** Un seul format circule ; le formatage d'affichage `699 000 006` appartient à la couche de présentation |
| `expire_le` | **fixé par le serveur.** Fait foi en cas de divergence avec l'horloge de l'appareil |
| `attribue_le` | horodatage du tirage, pour le journal de l'écran 8 |

### Ce que l'application stocke, et rien d'autre

`msisdn` · `expire_le` · `attribution_id` — auxquels s'ajoute la **langue
retenue** (`EF-21`), que `INV-SIM-06` autorise explicitement depuis la révision
du 23/08. Quatre valeurs en régime établi — **cinq transitoirement** : la clé
d'idempotence et le profil demandé vivent sur l'appareil entre l'émission de
la demande et la réception du `201`, puis sont effacés (révision 0.3.1). Une
clé n'est pas une donnée personnelle : c'est un numéro de tentative.

**Aucun identifiant d'appareil n'est demandé ni stocké** : le bail est porté par
sa poignée, pas par une identité de terminal.

**La langue ne circule pas ici — ni nulle part ailleurs sur le réseau.** Elle
n'est pas un critère de tirage : deux usagers de langues différentes tirent
dans la même population. Et elle n'est pas non plus transmise au service
USSD : l'arborescence arrêtée par la Direction porte une option « Changer
Langue » dans le menu lui-même — la langue des menus se règle dans le
parcours, côté service. La langue retenue ne sert qu'à l'affichage des écrans
propres à l'application (`EF-20`, `EF-21`).

### Atomicité — l'exigence, pas l'implémentation

> Le tirage et le marquage forment **une seule opération indivisible**. Deux
> requêtes concurrentes sur le même profil rendent **deux clients distincts**,
> ou l'une échoue en `409`. Elles ne peuvent jamais rendre le même.

C'est `INV-SIM-01`, vérifié par `CR-06` en attribution simultanée.

Un `GET` puis un `POST` séparés ne satisfont pas cette exigence : entre les
deux, un autre appareil passe. Deux primitives conviennent, au choix du
Loader :

- un `findOneAndUpdate` filtrant sur l'état libre — le tirage **est** le
  marquage, aucune fenêtre n'existe ;
- le verrou par ressource `C2` déjà présent dans le Loader, écrit exactement
  pour ce motif : `GET`-avant-`POST` n'est sûr que séquentiellement.

### Expiration — paresseuse, jamais différée

Un bail échu **n'est pas** un client indisponible. Le tirage considère libre
tout client dont le bail est dépassé, sans attendre aucune tâche de fond. Un
balayage périodique reste possible pour la propreté des compteurs, il ne doit
jamais être **nécessaire** : un pool qui dépend d'un minuteur se vide le jour
où le minuteur s'arrête.

### 2.3 La durée du bail — un réglage, plus une constante

**Rien de ce paragraphe ne change une seule requête de l'application.** Il est
ici parce qu'une durée qui bouge sans que le consommateur le sache serait un
piège, et parce que la révision 0.4 §(b) l'a promise.

**Sept jours est désormais un DÉFAUT, pas la loi.** La durée applicable est
résolue **au moment du tirage** : la surcharge du pays demandé si elle existe,
sinon la valeur globale. Elle est bornée de **1 à 30 jours**. Le réglage est
relu à chaque attribution — le changer vaut dès la suivante, sans redéploiement
ni redémarrage.

**La seule conduite exigée de l'application est celle qu'elle tient déjà :
lire `expire_le`, jamais calculer une échéance.** Une application qui
afficherait « valable 7 jours » en dur mentirait le jour où le réglage passe à
trois. Le serveur reste la seule autorité d'horloge (§3).

**Un bail déjà tiré ne bouge pas.** Son `expire_le` est écrit au tirage et
aucun réglage postérieur ne le relit — un bail est une promesse datée. Baisser
la durée ne raccourcit aucun bail en cours ; l'appareil qui en détient un le
garde jusqu'au terme promis.

**Le réglage ne peut pas faire échouer une attribution.** Sa lecture est
protégée : base injoignable, document illisible ou valeur hors bornes, le
tirage aboutit avec le défaut de sept jours plutôt que de refuser un numéro.
C'est la doctrine du champ `appareil` (§0.4a) appliquée à l'identique — un
réglage de confort ne fait jamais tomber le cœur du mécanisme.

**La face d'administration — hors de la surface de ce contrat.** Le réglage se
lit et s'écrit par deux routes du Loader, réservées à ses opérateurs et jamais
appelées par l'application :

| Route | Ce qu'elle fait |
|---|---|
| `GET /admin/attributions/reglages` | la durée en vigueur, ses bornes, sa version, qui l'a modifiée et quand |
| `PUT /admin/attributions/reglages` | règle la valeur globale et les surcharges par pays ; refuse avant écriture une valeur hors bornes ou un pays hors référentiel, et chiffre les baux qu'elle laisse intacts |

---

## 3. `GET /api/v1/attribution/attributions/{attribution_id}`

Vérifie qu'un bail est **encore reconnu par le serveur**. C'est la route qui
rend l'autorité serveur *exerçable* : sans elle, l'application n'avait aucun
moyen d'interroger l'échéance qu'elle est censée respecter, et `EF-15`
reposait sur la seule horloge du téléphone — ce que ce contrat interdit.

**Quand l'application l'appelle : à chaque lancement**, avant de proposer la
composition. Jamais pendant une session — le callback tranche déjà, et
doubler chaque saisie d'une vérification ralentirait l'écran 6 pour rien.

### Réponses

| Code | Situation | Conduite de l'application |
|---|---|---|
| `200` | bail **actif** | met à jour `expire_le` local (le serveur peut avoir raison contre l'horloge), poursuit vers la composition |
| `404` | bail inconnu, **ou échu** | écran **13**, efface l'état local, reconduit en phase 1 |
| `5xx` / silence | erreur ou réseau | conserve l'état local et poursuit sur la foi de `expire_le` stocké — on ne jette jamais un bail sur un échec de vérification ; le callback tranchera |

### Corps `200`

```json
{
  "attribution_id": "3f8b2c14-77ad-4c3e-9a11-0d5e6f8b2c14",
  "msisdn": "237699000006",
  "attribue_le": "2026-08-24T18:42:11Z",
  "expire_le": "2026-08-31T18:42:11Z"
}
```

**Un bail échu rend `404`, pas un `200` décoré d'un drapeau.** C'est la même
doctrine que la libération : fonctionnellement, un bail échu n'existe plus —
`expire_le < now` *est* l'état libre, il n'y a pas d'état intermédiaire à
exposer. Le `404` couvre aussi tous les cas où le serveur a perdu le bail
(expiration, libération par la recette, réinitialisation du Loader) : d'où
qu'il vienne, la conduite de l'application est identique — écran 13, phase 1.

---

## 4. `DELETE /api/v1/attribution/attributions/{attribution_id}`

Rompt la liaison et **rend le client au pool** — `EF-17`, écran 8.

La rupture doit être **serveur**. Purement locale, chaque usage de la fonction
de recette fuirait un numéro pour sept jours et `INV-SIM-01` s'éroderait au
rythme des tests.

### Réponses

| Code | Situation | Conduite de l'application |
|---|---|---|
| `204` | libéré | efface l'état local, retour phase 1 |
| `404` | poignée inconnue **ou** bail déjà échu | **efface aussi l'état local** — le bail n'existe plus, le but est atteint |
| `5xx` | erreur serveur | conserve l'état local, écran 10. Ne jamais effacer sur un échec serveur : l'usager perdrait un bail encore valide |

`404` est un **succès fonctionnel** : idempotence de la libération.

---

## 5. Les échecs — table normative

C'est cette table qui rend `ENF-05` vérifiable et `CR-11` exécutable.

| Situation | HTTP | `code` | Écran | Rejouable |
|---|---|---|---|---|
| Attribution réussie | `201` | — | 4 | — |
| Aucun client pour ce profil | `409` | `STOCK_EPUISE` | **11** | non — changer de profil |
| Critère hors référentiel | `422` | `CRITERE_INVALIDE` | 10 | non — défaut applicatif |
| Clé d'idempotence absente | `400` | `CLE_IDEMPOTENCE_REQUISE` | 10 | non — défaut applicatif |
| Erreur interne | `500` `502` `503` `504` | `ERREUR_SERVEUR` | **10** | oui |
| Aucune réponse HTTP | — | — | **9** | oui |

### Corps d'erreur, uniforme

```json
{
  "code": "STOCK_EPUISE",
  "message": "Aucun client libre pour le profil CM / FEMALE / CORPORATE",
  "details": { "pays": "CM", "genre": "FEMALE", "categorie": "CORPORATE", "libres": 0 }
}
```

`code` est **la seule valeur sur laquelle l'application branche**. `message` et
`details` vont au journal de l'écran 8 — **jamais à l'écran du partenaire**,
qui ne doit voir ni code HTTP ni trace technique.

**`message` n'a donc pas de langue à respecter** : il est un diagnostic destiné
à la recette, pas un texte d'interface. Ce que lit le partenaire aux écrans 9,
10 et 11 est **embarqué dans l'application**, dans la langue retenue (`EF-20`).
Le service ne fournit aucun texte affichable à l'usager.

### La distinction qui compte

**Propriété structurelle exigée du serveur** : le stock épuisé est un
**résultat calculé** — l'ensemble « candidats moins baux actifs » est vide —
**jamais une exception attrapée**. Un bug serveur ne peut donc pas se
déguiser en stock épuisé, ni l'inverse.

`409 STOCK_EPUISE` et `500 ERREUR_SERVEUR` **ne doivent jamais se confondre**.
Le premier dit *« change de profil »* et se règle en salle. Le second dit
*« le service est en défaut »* et se règle en appelant TNS. Un message unique
rendrait l'écran 11 inatteignable et `CR-11` invérifiable.

---

## 6. Authentification — tranchée

`ENF-07` exige un fonctionnement *« sans compte utilisateur ni
authentification »*. Ces trois routes sont donc **ouvertes** dans le présent
contrat.

Si le Loader doit les protéger, ce ne peut pas être par une clé embarquée dans
l'application : un APK se décompresse, une clé qui y figure n'est pas un
secret. La restriction devrait alors être **d'infrastructure** — filtrage par
origine ou par réseau — et non un identifiant porté par le client.

**Tranché à la validation (24/08)** : routes ouvertes, conformément à
`ENF-07`. Si une protection s'avère nécessaire, elle sera d'infrastructure —
le point est porté à la Direction par le QA Lead.

---

## 7. Ce que ce contrat ne fait pas

- **Aucune création, modification ni suppression de client.** Le service
  attribue depuis une population existante (périmètre §2.2 du cahier des
  charges).
- **Aucun libellé de menu, aucune donnée financière** ne transite ici.
  L'attribution rend un numéro, rien de plus (`INV-SIM-03`).
- **Aucune route de saisie de numéro.** Il n'existe aucun moyen, dans ce
  contrat, de désigner un numéro voulu (`INV-SIM-04`, `CR-08`).
- **Aucune notion de session USSD.** Le callback est un contrat distinct,
  servi par ussd-service.
- **Aucun geste d'administration.** Régler la durée du bail (§2.3) et révoquer
  un bail depuis le Loader sont des gestes d'EXPLOITATION : ils vivent sous
  `/admin`, sous les rôles du Loader, et l'application n'en connaît rien. Une
  révocation ne lui est pas notifiée — aucun canal descendant n'existe
  (`ENF-05`) : elle la découvre à sa prochaine vérification de bail (§3), et sa
  conduite est celle de l'expiration. Un seul chemin, déjà prouvé.

---

## 8. Questions — état après validation

1. **Dimensionnement du pool** — portée par le QA Lead à la volumétrie du
   Loader. Seule question restée ouverte.
2. ~~Rétention de la clé d'idempotence~~ — **72 heures, confirmé**.
3. ~~Périmètre des critères~~ — **tranché** : les combinaisons réellement
   peuplées, et une combinaison à zéro **apparaît** avec `libres: 0`, jamais
   masquée — l'application la grise, elle ne la cache pas.
4. ~~Authentification~~ — **tranché**, §6 : routes ouvertes.

---

*v0.3 validée par le QA Lead le 24/08. Le contrat est FIGÉ : transmis au
Loader comme spécification de la face serveur, et référence unique de
l'application. Toute évolution passe par une révision numérotée.*
