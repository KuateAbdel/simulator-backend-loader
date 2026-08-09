# Doctrine d'architecture — Loader FinZuu

**Ce document explique *pourquoi* le Loader est construit comme il l'est.**

Les autres documents disent ce qui a été mesuré (`docs/empirical/`), ce qui a été
tranché (`DECISIONS.md`), et ce qui reste à faire (`PLAN_SPRINTS.md`). Celui-ci
dit **la règle qui gouverne les trois**.

Il est écrit pour être lu par quelqu'un qui n'était pas là — un développeur qui
reprend le projet, un auditeur, ou nous-mêmes dans six mois.

| | |
|---|---|
| **Établi le** | 9 août 2026 |
| **Auteur** | Kuate Abdel Yaniv — Tech Lead / DevSecOps / QA Lead |
| **Statut** | Doctrine active — toute décision de conception doit s'y conformer ou l'amender explicitement |

---

## 1. Le problème posé

Le Loader consomme **une source de données** (Faker fintech4esg) et **neuf
microservices** qu'il ne contrôle pas, qu'il ne peut pas corriger, et dont la
mesure a établi qu'ils sont **partiellement défaillants**.

Trois faits, tous mesurés, qui définissent le terrain :

1. **Les services acceptent l'absurde.** Un client de 2 ans, un genre
   `"peu importe"`, une devise `ZZZ`, un numéro camerounais pour un Sénégalais,
   six souscriptions là où le CDC en autorise trois.
2. **Trois services n'exposent aucun `DELETE`** — identity, account, depositary.
   Toute écriture y est **définitive**.
3. **Aucune transaction, aucun rollback.** `POST /clients/onboard` écrit dans
   trois services ; une interruption à mi-chemin laisse des orphelins permanents.

Et une contrainte de finalité : **la démonstration cible Nordic Microfinance,
IFC, AFD et la BAD** (`OBJ-04`). Des bailleurs qui connaissent le terrain
africain réel. Un jeu de données qui ne tient pas la route devant eux ne sert à
rien — il vaudrait mieux ne rien montrer.

**La question de conception est donc** : que fait-on quand l'amont est à la fois
imposé, défaillant, et irréversible ?

---

## 2. Les deux réponses possibles — et celle que nous avons choisie

Eric Evans, *Domain-Driven Design* (2003), pose exactement deux motifs face à un
système amont subi.

### Motif **Conformist**

On adopte le modèle de l'amont **tel qu'il est**, défauts compris. C'est
économique : aucune traduction à écrire.

**Ce que ça aurait donné ici** — et ce n'est pas une hypothèse, c'est ce que la
base de TEST contient déjà :

* des comptes clients portant `currency: "ANY"`, valeur d'un enum de segment ;
* un référentiel de devises contenant `cv` et `00` ;
* un opérateur télécom dont le motif de validation est `6|333`, sans ancres ;
* quatre pays sans devise rattachée ;
* vingt Users dont **aucun** n'a de `company_id`.

### Motif **Anti-Corruption Layer** (ACL)

On garde **notre** modèle, et on **traduit à la frontière**. Le coût est réel :
il faut écrire la traduction, la tester, et la maintenir. Le bénéfice l'est
aussi : **notre conception reste saine quoi qu'il arrive en face**.

> **C'est le motif retenu.** Formulé autrement, et c'est la phrase qui a présidé
> à ce choix : *« on ne détruit pas notre conception pour s'aligner sur le
> service du système ».*

---

## 3. Les quatre propriétés, et ce qui les porte

La doctrine recouvre quatre propriétés distinctes. Les confondre mène à des
décisions floues ; les nommer sépare les responsabilités.

| Propriété | Définition | Ce qui la porte |
|---|---|---|
| **Anti-Corruption Layer** | Le modèle amont ne pénètre jamais le nôtre | `app/core/invariants.py`, les disciplines `D-*`, les fonctions `valider_*` |
| **System of Record** | Nous faisons **autorité** sur ce que le serveur ne sait pas exprimer | `org_hierarchy`, `lenders_registry`, `faker_consumption_ledger`, `ReferentielGeo` |
| **Observabilité** | On sait à tout instant ce qui a été tenté, réussi, échoué | `audit_trail`, journal d'intention, `intentions_orphelines()` |
| **Piste d'audit** | Chaque écriture porte son avant, son après et son motif | `AuditTrailEntry` — `EF-61` → `EF-64` |

### Sur le System of Record — la nuance décisive

**Nous ne dupliquons pas le serveur. Nous faisons autorité sur ce qu'il ne sait
pas dire.** Quatre exemples mesurés :

| Fait | Le serveur | Nous |
|---|---|---|
| Le quartier d'un Kiosque | `CreateDepositaireSchema` n'a **aucun champ géographique** | `org_hierarchy`, avec le `zone_type` |
| La devise d'un pays | `Country.currency = null` sur les 4 pays | `Pays.devise_iso`, vérifié sur deux feuilles |
| Le client Faker consommé | aucun champ nulle part | `faker_consumption_ledger` (`D-FAKER-1`) |
| Une écriture non confirmée | aucune notion | intention orpheline |

Sans nous, **`CR-02` serait invérifiable** : ce critère de recette exige de
contrôler que « chaque Kiosque a un District valide, chaque Agence une Ville
valide ». Aucun service ne porte cette information.

---

## 4. La règle, en une phrase

> ### Le Loader est **conformiste sur le transport**, **anti-corruption sur le modèle**.

**Conformiste sur le transport** : il respecte scrupuleusement les contrats HTTP,
y compris leurs bizarreries. `POST /identities/create` et non `POST /identities/`.
`/api/v1/groupes/` en français. `identity.phone` strictement égal à `msisdn`.
L'étape 2 du flow utilisateur avec l'`auth_token`, jamais le token ROOT. On ne
discute pas le protocole — on l'observe et on s'y plie.

**Anti-corruption sur le modèle** : il refuse absolument d'adopter le modèle de
données défaillant que ces contrats véhiculent. Un genre libre reste refusé même
si le serveur l'accepte. Une devise hors zone monétaire reste refusée même si
elle traverse trois services sans obstacle.

---

## 5. Ce que la couche absorbe — catalogue au 9 août 2026

### 5.1 Les défauts serveur anticipés, jamais réparés

| Réf | Défaut mesuré | Parade |
|---|---|---|
| `FRA-195` | Montant négatif : rejet HTTP **apparent**, mutation **réelle** | Barrière **avant** le réseau — aucune vérification postérieure ne rattraperait |
| `FRA-218` | Les frais sont retranchés du montant et crédités nulle part | Ne jamais déduire un solde ; toujours le relire |
| `FRA-219` | `change-status` répond **500 et réussit** | Ne jamais rejouer sur 500 de cette route |
| `FRA-220` | `owner_type=COMPANY` désigne **aussi** les Dépositaires (42/51) | Résolution par `type` de compte, jamais par `owner_type` |
| `FRA-222` | `currency` non validée, propagée au compte | Liste close, dérivée de la zone monétaire du pays |
| `FRA-223` | Dépositaire d'épargne souscrivant un produit de prêt | `D-DEP-9` |
| `FRA-224` / `FRA-225` | Références non validées à la création | `GET`-avant-`POST`, identifiants **relus** |
| `FRA-227` | `owner._id` requis au contrat, **ignoré** | Toujours relire l'identifiant **rendu** |
| `FRA-228` | Casse annoncée dans le message, non appliquée | Majuscules émises ; seuls les caractères spéciaux rejetés |
| `ANO-CLI-SEARCH-01` | `POST /search` **ignore tous ses critères** | L'endpoint n'est **jamais** utilisé |
| `ANO-CLI-LANG-01` | `language` accepté puis écarté | Repli automatique sur `PATCH /language` |
| `ANO-CFG-TELCO-01` | Motif `6\|333` **sans ancres** — valide tout | Nos 12 motifs sont ancrés et **vérifiés au chargement** |
| `ANO-CPY-LEAK-07` | Les erreurs fuient des traces Python | Tronquées à 500 caractères, **jamais parsées** |

### 5.2 Les invariants que personne ne pose — et que nous posons

| Champ | Ce que le serveur accepte | Notre règle, et son fondement |
|---|---|---|
| âge | **2 ans**, **120 ans** | **18 à 75** — majorité légale des 4 pays ; plafond de crédibilité |
| `gender` | n'importe quelle chaîne | `{MALE, FEMALE}` — `ANY` rendrait `EF-22` invérifiable |
| `marital_status` | n'importe quelle chaîne | enum stricte **+ plancher d'âge** : un veuf de 19 ans est invraisemblable |
| `id_expire_on` | présence seulement | future **et** cohérente avec la majorité du porteur |
| `currency` | `ZZZ`, `ANY`, chaîne vide | **déterminée par la zone monétaire** — CEMAC ou UEMOA |
| MSISDN | tout | conforme au **plan de numérotation réel** de l'opérateur |
| type de produit | LENDING sur un Client | **COLLECT seulement** — `UC-13` |
| catégorie | CORPORATE sur produit INDIVIDUAL | croisement vérifié |
| souscriptions | **6 acceptées** | **3** — `UC-13` |
| unicité | msisdn, id_number, email — messages trompeurs | les **trois**, normalisées avant comparaison |
| champs optionnels | persistés à `null` | **aucun champ vide, jamais** |

### 5.3 Ce que la source amont ne fournit pas — et que nous composons

`Faker` est la **matière brute**. Là où elle est pauvre ou incohérente, le Loader
**compose** ; il n'invente jamais à partir de rien.

| Champ | Faker donne | Nous ajoutons |
|---|---|---|
| Raison sociale | `Test Business CM 748` | patronyme + forme juridique + secteur **de Faker** → `DEMO_SARL Kouassi Textile` |
| Date de naissance | **rien** — ni famille A, ni B | composée, bornée, cohérente avec la pièce |
| Adresse | **rien** | `Loader_Base` : région, ville, quartier, GPS |
| Occupation | **rien** | dérivée de `sector_assignments` |
| MSISDN | 8 chiffres **sans le préfixe opérateur** | le préfixe — implicite pour un habitant du pays, absent pour un programme |

> **La différence entre inventer et composer est la ligne que ce projet ne
> franchit pas.** Tout part de matière réelle : patronymes et formes juridiques
> de Faker, géographie de `Loader_Base`, plans de numérotation du référentiel.

---

## 6. Pourquoi la rigidité est une propriété, pas une limite

Une objection revient naturellement : *pourquoi le Loader ne s'adapterait-il pas
au comportement du serveur au fil de l'eau ?*

**Parce qu'une couche anti-corruption qui s'adapte silencieusement cesse d'en
être une.** Trois raisons, dans l'ordre de gravité :

1. **Ça détruirait `ENF-15`.** Un comportement dépendant de l'état du serveur au
   moment de l'exécution n'est plus reproductible. Deux exécutions du même
   `run_id` donneraient des résultats différents.

2. **Ça détruirait la valeur de détection.** L'investigation menée pour bâtir
   cette couche a produit **onze tickets**. Un Loader qui contournerait
   silencieusement un nouveau défaut cesserait de le révéler — il en deviendrait
   le complice.

3. **Ça masquerait les régressions.** Si le serveur corrige `FRA-222` demain et
   casse autre chose, une couche adaptative absorberait le changement sans rien
   dire.

**La bonne formulation** : le Loader est **rigide à l'exécution, souple à la
conception**. Il échoue bruyamment sur l'inconnu, et n'évolue que par décision
documentée.

`D-CLI-3` en est l'illustration exacte. Une discipline héritée affirmait que
`id_number` devait être en majuscules strictes. La mesure du 9 août l'a démentie.
Elle n'a pas été contournée : **elle a été déclarée caduque, corrigée dans le
code, et la correction porte sa preuve.**

---

## 7. Comment une discipline naît, vit et meurt

C'est le cycle qui garantit qu'aucune règle du Loader n'est arbitraire.

```
1. MESURE        un comportement est constaté sur le serveur, avec sa commande
                 exacte et sa réponse intégrale
2. TICKET        si c'est un défaut, il est remonté à l'équipe qui tient le
                 service — le Loader ne répare jamais
3. DISCIPLINE    une barrière est posée côté Loader, nommée D-XXX
4. TEST          la barrière est vérifiée hors réseau, avec le motif expliqué
                 dans le message d'erreur
5. DÉCISION      si elle change une conception, elle entre dans DECISIONS.md
6. REVÉRIFICATION  toute discipline héritée est rejouée avant d'être crue
```

**L'étape 6 n'est pas une formalité.** Appliquée aux 7 disciplines de
client-service, elle en a invalidé **une** et découvert **trois** comportements
non documentés — dont `D-CLI-8`, qui aurait fait échouer **deux mille**
onboardings.

> **Verify, don't trust.** Une source datée est une hypothèse, pas un fait.

---

## 8. La frontière — ce que le Loader ne fait pas

Une doctrine se définit autant par ses refus.

| Le Loader **ne** | Pourquoi |
|---|---|
| ne répare **jamais** un défaut serveur | Ce n'est pas son rôle ; c'est celui de l'équipe qui tient le service |
| ne supprime **rien** dans un référentiel partagé | Les 6 parasites de config-service sont signalés, pas purgés |
| n'écrit **jamais** en base directement | Tier 2 : il consomme les API, comme n'importe quel client. Écrire en base court-circuiterait la validation métier et corromprait les invariants |
| ne passe **jamais** par Kafka | `ENF-16` l'interdit. De Duhamel on reprend **la méthodologie**, jamais le transport |
| ne calcule **aucun** indicateur PAR/DPD | Retiré du CDC v1.2 — c'est ReadyScore qui les produit |
| n'appelle **jamais** ReadyScore | `EF-80` : les décisions sont extraites des payloads Faker. Un environnement de TEST ne dépend pas d'un service de PRODUCTION |
| ne rejoue **jamais** un `4xx` | Un 4xx signale **notre** payload ; le rejouer le répéterait |

---

## 8 bis. Cinq règles issues de l'analyse config-service (9 août)

Comprendre un service amont défaillant sert à ne pas répéter ses choix. Ces cinq
règles viennent de `docs/ANALYSE_CONFIG_SERVICE.md`.

1. **Aucune donnée métier dans une chaîne technique.** config-service encode le
   pays d'un opérateur dans son `phone_regex` — dès qu'un motif est mal formé
   (`6|333`), l'information **disparaît**. Chez nous, `Telco.country_iso2` est un
   champ.
2. **Toute relation métier a son inverse interrogeable.** *« Quels opérateurs au
   Cameroun ? »* n'a pas de réponse directe côté serveur. **Si une question du
   métier exige un balayage, le modèle est incomplet.**
3. **Références, jamais copies.** Leur `embed-at-creation` sans invalidation crée
   deux sources de vérité qui divergent silencieusement. Seule exception chez
   nous : `audit_trail`, où figer l'état **est** le but.
4. **Soft-delete plutôt que suppression** dans tout ce qui tient lieu de
   référentiel. C'est leur meilleure idée, et nous la prenons.
5. **Une entité promise doit exister.** Le Document Fonctionnel annonce quatre
   entités ; `City` n'a jamais été implémentée. Chez nous, `Region`, `City` et
   `District` sont des entités réelles.

> **Le gain concret de cette analyse** : la règle 2 nous a fait voir un trou dans
> **notre propre** conception — le rattachement **Client → Kiosque** (`EF-26`)
> n'est persisté nulle part. Sans index, la question *« quels clients dans ce
> Kiosque ? »* imposerait un balayage de 2 000 clients. À poser dès l'onboarding.

---

## 9. Ce que la doctrine produit

À la fin, deux livrables — et le second n'existe que grâce à la doctrine.

**Le premier** : un écosystème de démonstration cohérent dans la base FinZuu.
C'est ce que le CDC demande.

**Le second** : **la preuve que cet écosystème se tient.** Le back-office FinZuu
montrera les données. Le tableau de bord du Loader montrera qu'elles sont
cohérentes — et il est **structurellement le seul à pouvoir le faire** :

* la hiérarchie complète Pays → Région → Ville → Quartier → Kiosque, avec le type
  de zone — **le serveur n'a aucun champ pour ça** ;
* la répartition par opérateur, comparée aux parts de marché réelles ;
* les quotas `EF-22` / `EF-23` / `EF-24` **mesurés**, pas déclarés ;
* les intentions orphelines — ce qui a peut-être été écrit sans confirmation ;
* le journal complet, purgeable par préfixe (`OBJ-05`, `CR-07`).

---

## 10. En une page, pour la documentation finale

> Le Loader FinZuu est un **orchestrateur HTTP** qui peuple un écosystème de
> démonstration en consommant une source de données et neuf microservices qu'il
> ne contrôle pas et dont plusieurs sont défaillants.
>
> Il applique le motif **Anti-Corruption Layer** : il est **conformiste sur le
> transport** — il respecte les contrats HTTP jusque dans leurs bizarreries — et
> **anti-corruption sur le modèle** — il refuse d'adopter les incohérences que
> ces contrats véhiculent.
>
> Sa base propre n'est pas une copie du serveur : elle est le **System of
> Record** de tout ce que le serveur ne sait pas exprimer — la géographie fine,
> la zone monétaire, la consommation de la source, et les écritures non
> confirmées.
>
> Il est **rigide à l'exécution** et **souple à la conception** : il échoue
> bruyamment sur l'inconnu, et n'évolue que par décision documentée. C'est cette
> rigidité qui lui a permis de révéler **onze défauts** du système avant même sa
> première exécution complète.
>
> Il ne répare rien. Il constate, journalise, se protège, et poursuit.

---

*Cette doctrine est amendable. Elle ne l'est que par une décision inscrite dans
`DECISIONS.md`, avec sa preuve. Une exception non documentée est une violation.*
