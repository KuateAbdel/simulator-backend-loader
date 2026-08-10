# Journal des décisions — Loader FinZuu

Registre des décisions de conception prises pour ce dépôt : ce qui a été tranché,
par qui, sur quelle preuve, et où c'est appliqué dans le code.

**Pourquoi ce fichier existe** : une décision qui ne vit que dans une conversation
est une décision perdue. Chaque ligne ci-dessous doit pouvoir être retrouvée,
comprise, et contestée par quelqu'un qui n'était pas là.

**Règle de préséance appliquée à tous les arbitrages** :
**CDC v1.2 souverain sur le métier** → **contrat serveur souverain sur le fil** →
**pages Service Anatomy sur le comportement observé** → **diagrammes UML : à corriger**.
Un nom qui change ne change pas le métier.

---

## D-01 · Les 4 comptes financiers du Lender — création explicite

**Tranché le 8 août 2026 · Yaniv**

`UC-10` / `EF-13` décrivent 4 comptes par Lender. `03_sequence_lender.puml` marquait
cette étape « hypothèse non vérifiée » (Trou #2).

**Preuve** : comptage exhaustif des 42 comptes de l'environnement TEST —
`7 OPERATION + (5 × 6 Dépositaire) + 5 CHECKING = 42`, **zéro résiduel**.
**0 Company sur 7** porte les 4 comptes. company-service n'expose aucune route liée
aux comptes.

**Décision** : **aucune cascade n'existe.** L'intention du CDC est maintenue — chaque
Lender a bien ses 4 comptes — mais le Loader les crée lui-même, par 4 `POST /accounts/`
explicites (`owner_type=COMPANY`, `external_class=COMPANY_SERVICE`).
La création explicite reste **non testée en écriture** : account-service n'expose
**aucun DELETE**, toute écriture y est définitive. Reporté au module Organisation.

**Appliqué** : `docs/empirical/2026-08-08_TROU-2_comptes_financiers_lender.md` ·
`03_sequence_lender.puml` · `app/models/domain.py` (`LenderRegistryEntry`, champs
`*_account_id` optionnels) · commit `dfce6f4`

---

## D-02 · CO-01 fermé — le Lender est un rôle porté par une Company

**Tranché le 8 août 2026 · Yaniv**

Le CDC §6.3 tranche explicitement : *« Un Lender est un rôle métier porté par une
Company »*. Jamais rattaché à une Branche ou une Agence. Ce n'est pas un point ouvert.

**Appliqué** : `docs/empirical/2026-08-08_recon_9_services.md` §2 · `lenders_registry`

---

## D-03 · Volumétrie des Dépositaires — 40 à 80, pas 120 à 200

**Tranché le 8 août 2026 · Yaniv**

Le Document Maître §9 annonçait 120‑200 (30‑50/pays). Le CDC `UC-09`, scénario
nominal, point 3 : *« Il génère entre **10 et 20 Kiosques par pays** »* → **40 à 80**.
Le glossaire CDC pose l'équivalence « Kiosque / Dépositaire », que le diagramme de
classe confirme (une seule classe `Kiosque_Depositaire`).

**Preuve complémentaire** : le référentiel ne le permettait pas autrement. 17 à 25
quartiers disponibles par pays — à 30‑50 kiosques, la Côte d'Ivoire aurait dû loger
50 guichets dans 17 quartiers, soit 3 empilés au même endroit.

**Appliqué** : `app/core/cdc.py` (`KIOSQUES_PAR_PAYS`) · `09_activity.puml` · commit `6340d7f`

---

## D-04 · Clients Corporate — 400, pas 500

**Tranché le 8 août 2026 · Yaniv**

Le Document Maître §7 évoquait « 500 clients Business (25 % de 2000) ». 25 % est la
distribution **naturelle de Faker**, pas notre exigence. `EF-23` impose 80/20 → **400**.

**Appliqué** : `app/core/cdc.py` (`PART_CORPORATE`, `repartition_clients()`)

---

## D-05 · Branche et Agence — niveaux logiques internes au Loader

**Tranché le 8 août 2026 · Yaniv**

company-service n'expose **aucune route** pour Branche ni Agence, et son enum
`CompanyType` ne comporte **aucune valeur `BRANCH`**. Les matérialiser en Companies
filles ferait exploser le budget de 12‑20 Companies fixé par `UC-07`, sans bénéfice.

**Décision** : Branche et Agence restent **logiques**, persistées chez nous. Seuls
Company (IMF) et Kiosque_Dépositaire existent côté serveur, reliés par `company_id`.

**Conséquence assumée** : une **sixième collection MongoDB**, `org_hierarchy`. Sans
elle, `CR-02` est invérifiable — ce critère de recette exige de contrôler que
« chaque Kiosque a un District valide, chaque Agence une Ville valide ».
Confirmé depuis : `CreateDepositaireSchema` ne comporte **aucun champ géographique**
(`name`, `currency`, `company_id` seulement). Sans `org_hierarchy`, l'ancrage
géographique du Kiosque n'existerait **nulle part**.

**Appliqué** : `app/models/enums.py` (`NiveauOrganisation`) · `app/models/domain.py`
(`OrgHierarchyNode`) · `app/core/database.py` · `docs/CONTEXT.md` (5 → 6 schémas) ·
commit `6ee7eeb`

---

## D-06 · Les 12 rôles métier — 12 groupes, `company_id = ""`

**Tranché le 8 août 2026 · sur observation, sans écriture de test**

La question était : 12 groupes globaux, ou 60‑100 dupliqués par Company ?

**Preuve** : les 4 groupes existants portent tous `company_id = ''` (chaîne vide).
Aucun test d'écriture n'a été nécessaire.

**Décision** : **12 groupes au total**, créés une seule fois, `company_id: ""`,
`routes` vide. Le mapping proposé — 12 rôles métier → 3 `tag` → 5 `UserType` — reste
**à valider** (arbitrage produit, page RBAC : *« toute nouvelle fonctionnalité doit
être arbitrée ici »*).

**Appliqué** : documenté dans `docs/empirical/2026-08-08_user_service_audit.md` §5.
**Code : à écrire.**

---

## D-07 · Les permissions `LENDER` sont hors périmètre

**Tranché le 8 août 2026 · Yaniv**

user-service porte 22 permissions `LENDER` (`LENDER_INVESTMENT_APPROVE`,
`LENDER_LENDER_CREATE`…). Elles relèvent du **Sprint 5**. Le Loader couvre le
**Sprint 1‑4**. Le RBAC anticipe simplement le module Prêt.

**Décision** : ne jamais les assigner. Aucune remise en cause du CDC.
La frontière CDC Loader / Test Strategy Module Prêt reste absolue.

**Appliqué** : `docs/empirical/2026-08-08_user_service_audit.md` §5

---

## D-08 · Le choix du produit de prêt suit `UC-02`, pas §6.6

**Tranché le 8 août 2026 · par les faits**

Deux passages du CDC divergeaient : §6.6 dit que le produit vient de Faker,
`UC-02` dit que le Loader le sélectionne.

**Preuve** : `decision.selected_product` et `decision.selected_amount`
**n'existent nulle part** dans les payloads Faker. Le point est tranché par la
mesure : **`UC-02` s'applique** — le Loader sélectionne le produit compatible avec
la catégorie du client, puis tire un montant dans la fourchette du segment.

Le catalogue à 4 produits (6 créations) reprend donc tout son sens.

**Appliqué** : `docs/empirical/2026-08-08_faker_maitrise_complete.md` §4

---

## D-09 · Les 12 rôles — **11 à créer**, `CUSTOMER` réutilisé

**Précisé le 9 août 2026 · Yaniv** — complète `D-06`, qui disait « 12 groupes créés
une seule fois » et laissait croire qu'on en crée douze.

**Origine des 12 rôles** : *Stratégie Seed v2.0*, repris en Gap 1 de la page
Service Anatomy user-service (56360965) et dans
`docs/empirical/2026-08-08_recon_9_services.md` §4.

**Le 12ᵉ rôle, « Client », EST le groupe `CUSTOMER` déjà en base** (tag `CUSTOMER`,
12 permissions). On ne le recrée pas : on le réutilise tel quel. **11 groupes à
créer, 1 réutilisé.**

### Mapping proposé — 12 rôles → 3 `tag` → 5 `UserType`

Le Confluence note explicitement que ce mapping *« n'est pas encore matérialisé »*.
Voici la proposition, **en attente de validation** (c'est l'arbitrage `A-05`) :

| # | Rôle métier | `tag` | `UserType` | Action |
|---|---|---|---|---|
| 1 | Super-Admin | `STAFF` | `ROOT` | créer |
| 2 | Admin | `STAFF` | `STAFF` | créer |
| 3 | Marketing | `STAFF` | `STAFF` | créer |
| 4 | Compliance | `STAFF` | `STAFF` | créer |
| 5 | Collecte | `STAFF` | `STAFF` | créer |
| 6 | Comptable | `STAFF` | `STAFF` | créer |
| 7 | Branche | `STAFF` | `STAFF` | créer |
| 8 | Employé/IT | `STAFF` | `STAFF` | créer |
| 9 | Agent | `STAFF` | `STAFF` | créer |
| 10 | Marchand | `COMPANY` | `COMPANY` | créer |
| 11 | Kiosque | `COMPANY` | `COMPANY` | créer |
| 12 | **Client** | `CUSTOMER` | `CUSTOMER` | ♻️ **réutiliser l'existant** |

**Deux conséquences à assumer** :

* Le `UserType` **`GUEST`** n'est porté par **aucun** des 12 rôles métier. Le groupe
  `GUEST` (3 permissions) reste en base, inutilisé par le Loader.
* Le `tag` **`ROOT`** est persisté en base bien qu'absent de l'énumération. Le rôle
  Super-Admin prend donc `tag: STAFF` — **jamais `ROOT` en écriture** (`A4`).

**Réversibilité** : `DELETE /api/v1/groupes/{id}` existe — rare dans cet écosystème.
La création des 11 rôles est donc la seule opération d'écriture entièrement
réversible du Loader.

**Correction apportée à `D-06`** : sa preuve affirmait que « les 4 groupes existants
portent tous `company_id = ''` ». **Faux** — mesuré le 09/08, le groupe `COMPANY`
porte **`null`**. La décision (groupes globaux, créés une fois) reste valide.

**Périmètre** : c'est du travail **Loader**, hors UML — *« Périmètre à porter par le
Loader »*, `recon_9_services.md` §4.

**Code : à écrire.** `creer_groupe()` et `supprimer_groupe()` existent déjà dans
`app/clients/user_service.py` ; il manque l'exécuteur et la table des permissions
par rôle (`A-05`).

---

## D-10 · `loader_runs` gagne un 7ᵉ champ — la configuration du run

**Tranché le 9 août 2026 · conséquence directe de l'exigence de paramétrage**

`CONTEXT.md` fige **6 schémas MongoDB à respecter exactement**. Celui de
`loader_runs` portait 6 champs : `_id`, `sim_start_date`, `sim_end_date`,
`status`, `mode`, `checkpoints`.

**Le problème** : dès que la volumétrie devient paramétrable (demande de la
Direction Technique du 9 août), **le `run_id` ne suffit plus à reproduire une
exécution**. Deux runs de même identifiant, lancés sous des paramètres
différents, produiraient des résultats différents. `ENF-15` serait perdue et
`CR-04` — *« deux exécutions identiques donnent le même résultat »* —
deviendrait invérifiable.

**Décision** : ajout d'un champ **`configuration`**, portant l'empreinte
complète — pays actifs et motifs d'exclusion, surcharges par territoire,
répartition des clients, ajouts de la surcouche référentielle, et **les écarts
au CDC**.

**Pourquoi pas dans `checkpoints`** : les checkpoints portent la **reprise
après interruption**, ils changent *pendant* l'exécution. La configuration est
**figée au lancement**. Les mélanger rendrait impossible de dire ce qui avait
été *demandé* — or c'est précisément ce que le tableau de bord doit montrer,
à côté de ce qui a été *produit*.

**Coût assumé** : `CONTEXT.md` passe de 6 champs à 7 sur cette collection. Le
nombre de collections reste 6.

**Appliqué** : `app/models/domain.py` (`LoaderRun.configuration`) ·
`app/repositories/loader_runs.py` (`creer(configuration=…)`) ·
`app/core/configuration.py` (`empreinte()`) ·
`app/services/surcouche_referentiel.py` (`ajouts()`)

---

## D-11 · `org_hierarchy` gagne le niveau `AGENT` — le 6ᵉ du CDC

**Tranché le 9 août 2026 · trou de conception trouvé en clôturant le Sprint 2**

Le CDC §6 décrit **six niveaux**. `org_hierarchy` n'en modélisait que **cinq** —
elle s'arrêtait au Kiosque.

**Pourquoi ce n'était pas visible** : `D-05` avait tranché que Branche et Agence
restent logiques *parce qu'elles n'ont aucune contrepartie serveur*. L'Agent, lui,
**a une contrepartie** : c'est un `User` de user-service portant le groupe
« Agent ». Il semblait donc n'avoir rien à faire ici.

**Ce qui a été manqué** : `User` porte `company_id` et `identity`, **jamais de
référence vers un Depositaire**. Le rattachement Agent → Kiosque, exigé par
`UC-09` point 4 — *« il rattache chaque Agent à un Kiosque et à une Company
mère »* — **n'existe nulle part**.

Sans lui, la question *« quels Agents dans ce Kiosque ? »* n'a aucune réponse.
C'est **exactement le défaut que nous reprochons à config-service**, dont le
`Telco` ne porte pas son pays (`ANALYSE_CONFIG_SERVICE.md`, règle 2 — *« toute
relation métier a son inverse interrogeable »*).

**Décision** : quatrième valeur `AGENT` dans `NiveauOrganisation`, et champ
`user_id` sur `OrgHierarchyNode`, renseigné à ce niveau uniquement — symétrique
de `depositary_id` au niveau KIOSQUE.

**Ce que ça ne change pas** : la règle du modèle est **appliquée, pas modifiée**.
`EF-18` — *« un nœud ne peut exister sans son supérieur »* — vaut pour l'Agent
comme pour les trois autres niveaux : `ajouter_agent()` refuse un Kiosque
inexistant.

**Une différence assumée avec le Kiosque** : aucune unicité n'est imposée.
`EF-17` parle d'un *« nombre paramétrable d'Agents par Kiosque »* et `UC-09` exige
« **au moins** un ». Plusieurs Agents dans un même Kiosque sont légitimes — là où
`(run_id, district_id)` unique interdit deux Kiosques dans un quartier.

**Deux contrôles de recette gagnés** : `agents_du_kiosque()` répond à la relation
inverse sans balayage, et `kiosques_sans_agent()` vérifie la postcondition
`UC-09` — liste vide = tenue.

**Appliqué** : `app/models/enums.py` · `app/models/domain.py`
(`OrgHierarchyNode.user_id`) · `app/repositories/org_hierarchy.py`
(`ajouter_agent`, `agents_du_kiosque`, `kiosques_sans_agent`) ·
`docs/CONTEXT.md`

**Rattachement effectif** : Sprint 3, quand les Kiosques existeront. Le modèle,
lui, le porte dès maintenant.

---

## Décisions en attente

| # | Sujet | Pourquoi c'est bloqué |
|---|---|---|
| ~~ANO-CPY-BUG-06~~ | ~~Création de Company bloquée~~ | ✅ **LEVÉ, mesuré le 08/08** — `POST /companies/` → HTTP 201. L'étape Organisation est débloquée. |
| ~~A-01~~ | ~~**Sénégal indisponible chez Faker**~~ ✅ **TRANCHÉ le 10/08 — voir note ci-dessous.** ~~ | 500 clients concernés. Trois voies : générateur interne pour SN · demande à Oti d'ajouter SN au `run_id` · réduction à 3 pays (contredirait `OBJ-01`). **Arbitrage utilisateur.** |
| **A-02** | **`EF-80` inapplicable tel qu'écrit** | Les champs `decision.*` n'existent pas, et les 2000 clients viennent de la famille A qui ne porte aucune décision. Deux options : le Loader attribue lui-même APPROVED/DECLINED dans les proportions du CDC (l'isolation vis-à-vis de ReadyScore reste totale), ou seuls quelques clients ont un vrai scoring. **Recommandation : la première.** |
| ~~A-03~~ | ~~Raisons sociales non crédibles~~ | ✅ **RÉSOLU** — `app/services/generateur.py`. Le Loader **compose** à partir de la matière réelle de Faker (patronymes, formes juridiques, secteurs) : `DEMO_SARL Kouassi Textile` au lieu de `Test Business CI 200`. Rien n'est inventé à partir de rien. |
| **A-04** | **Où stocker les ~700 prêts simulés** | `CR-10` exige de vérifier 100 séquences de remboursement, `ENF-14` les indicateurs PAR. Sans persistance, invérifiable. Une 7ᵉ collection `simulated_loans` ? |
| **A-05** | **Permissions exactes des 12 rôles** | Arbitrage produit, pas technique. Proposition rédigée, non validée. |
| ~~A-06~~ | ~~Code source `ready_scoring/` (Duhamel)~~ | ✅ **LEVÉ le 9 août 2026** — Yaniv a transmis `lifecycle_orchestrator.py`. **Les 4 fonctions nommées par `EF-76` y sont, verbatim**, ainsi que `_adjust_weights` (9 variables), `_sample_profile` et `_loan_terms` (2 replis). Les poids par défaut `0.50/0.25/0.13/0.12` **concordent exactement** avec `EF-67`. Extrait consigné dans `docs/reference/duhamel_lifecycle_orchestrator_EXTRAIT.py`. **Les étapes 6 et 7 sont débloquées.** ⚠️ **Reste absent** : `built_in_behaviors_v1()["profiles"]`, `build_timed_actions`, `expand_actions_daily`, `repay_amount_for_action` — **importés** par le script, non définis dedans. Les 4 profils sont donc *nommés et pondérés*, mais leur **forme jour par jour** manque encore. Nouvel arbitrage **A-07**. |
| **A-07** | **La forme des 4 profils comportementaux** | `EF-67` fige les poids (50/25/13/12), et `A-06` a livré le mécanisme de pondération. Mais **ce que fait chaque profil jour après jour** vit dans `ready_scoring/repayment_simulator.py`, non transmis. Deux voies : obtenir ce module, ou **définir nous-mêmes** les 4 séquences à partir de leurs noms, qui sont explicites (`pay_before_due`, `partial_then_full_dpd10`, `partial_then_never_finish`, `never_pays`). **Recommandation : la seconde** — les noms portent leur sémantique, et `CR-10` ne vérifie que la cohérence des séquences, pas leur identité au script de Duhamel. |

### Note sur l'outillage Duhamel — frontière à tenir

`docs/reference/lifecycle_orchestrator_README.md` documente *ReadyScore Kafka simulation tools* :
un paquet `ready_scoring/` (`kafka_consume`, `repayment_simulator`, `loan_tracker`,
`push_commands`) qui **consomme des topics Kafka** et y pousse des commandes
(bootstrap `152.53.140.115:9092`, tunnel SSH).

**Le Loader ne suit pas ce transport.** `ENF-16` l'interdit explicitement :
*« aucune dépendance à un cluster Kafka de production »*, et la Stack Technique fait du
Loader un orchestrateur **HTTP pur**.

> Du travail de Duhamel, le Loader reprend **la méthodologie** — les 4 fonctions de dates
> et les 4 profils comportementaux — **jamais le canal Kafka**. Les deux outils opèrent sur
> des plans différents : Duhamel sur des événements, le Loader sur des API REST.

---

## Erreurs de sondage commises et corrigées

Consignées pour que personne ne les refasse.

| Erreur | Correction |
|---|---|
| `/api/v1/groups/` → 404, conclu « endpoint absent » | La route est **en français** : `/api/v1/groupes/` → 200. Conclusion erronée reprise dans le Document Maître §11.0, **à retirer** |
| 24 appels à `/random` sans varier de paramètre, conclu « distribution 100 % APPROVED » | Le cache Faker est **clé par jeu de paramètres complet** — c'était 24 fois le même client |
| SN testé uniquement sur la famille A (enum strict) | Testé ensuite sur la famille B (sans enum) : **404**, SN absent des deux côtés |
| Pagination attachée à un modèle Pydantic via `object.__setattr__` | Remplacé par un champ typé `paginate` sur `ReponseServeur` |
| `nationality` renseignée avec le libellé du pays (« Cameroun ») | → code ISO 3166-1 alpha-2. **Bug trouvé uniquement par écriture réelle** — aucun test hors ligne ne pouvait le voir |
| `password/f/change` appelé avec le token ROOT | Refusé en 401. L'étape 2 n'accepte que l'`auth_token` de `register` |
| Admin User référençant l'`identity_id` généré localement | Le serveur **ignore** l'`_id` envoyé et génère le sien — toujours relire celui qui est rendu |

---

*Tenu à jour à chaque décision. Une décision non écrite ici n'existe pas.*

---

> **Les disciplines de service (`D-XXX-N`) ne figurent pas ici.** Elles sont
> imposées par le comportement des services, pas décidées par nous, et vivent
> dans le module qui les applique. Registre complet : `docs/DISCIPLINES.md` —
> **59 disciplines**, chacune adossée à une mesure des 8 ou 9 août.

## D-12 · Aucun nom n'est émis deux fois — registre d'unicité dans le générateur

**Constat, mesuré le 9 août sur le référentiel réel.**

| Niveau | Produit | Distincts | Doublons |
|---|---:|---:|---|
| Branches | 51 | **47** | `Centre`, `Est`, `Nord`, `Sud-Ouest` — régions de **plusieurs pays** |
| Kiosques | 82 | **81** | `Plateau` — quartier de **deux pays** |
| Agences | 50 | 50 | — |
| Companies | 8 demandées | **5** | 5 patronymes par pays, **marge nulle** au plafond du CDC |

**Personne ne nous arrête.** Ni company-service, ni depositary-service, ni
product-service n'imposent l'unicité de `name` (`ANO-PRD-UNIQ-01`). Le doublon
n'est pas rejeté : il est **créé, en silence**. Et trois services n'ont pas de
`DELETE` — il serait définitif.

Le cas grave est le Kiosque : **depositary-service n'a aucun champ
géographique**. Deux `DEMO_Kiosque Plateau` sont strictement indiscernables dans
l'interface. C'est exactement le défaut que nous reprochons à config-service
(règle 2 : *« toute relation métier a son inverse interrogeable »*).

**Décision.** `Generateur` tient un registre `_noms_emis`, comme il tenait déjà
`_emails_emis` et comme `RegistreUnicite` tient les MSISDN. La levée suit le
sens métier, pas un compteur :

| Entité | Discriminant | Pourquoi celui-là |
|---|---|---|
| Branche, Agence, Kiosque | **le code pays** | c'est ainsi qu'un groupe panafricain réel distingue ses agences homonymes |
| Company | **le suffixe commercial** | `Tamadou & Fils` et `Tamadou Négoce` : deux maisons du même patronyme se distinguent ainsi dans la vraie vie. `CM` ne dirait rien — elles y sont toutes |
| dernier recours | un rang | le référentiel n'a pas d'homonyme intra-pays, mais `CFG-03` permet d'en ajouter |

On ne préfixe **pas** tous les noms : `DEMO_Agence Douala CM` alourdirait 50 noms
pour en désambiguïser zéro. Le discriminant paraît là où l'ambiguïté existe.

**Conséquence de conception.** Le registre est **consommable** : il ne rend un
nom qu'une fois. `creer_kiosque()` renvoie donc désormais `(depositary_id, nom)`
— l'appelant recomposait le nom pour l'étiquette de son rapport et aurait obtenu
un nom **différent de celui réellement écrit sur le serveur**. *Un nom se calcule
une seule fois, au moment où il est posé.*

**Ce que ça illustre.** Le Loader **anticipe, il ne subit pas**. Le serveur ne
saura jamais nous dire que nous avons créé deux Kiosques identiques ; c'est à
nous de ne pas le faire. Même logique que `RegistreUnicite`, qui réserve les
MSISDN **avant le réseau** plutôt que de découvrir le conflit après une cascade
sur trois services.

**Limite assumée.** 20 patronymes pour 4 pays est un bouchon. Il tient pour les
Companies (3–5 par pays) ; il ne tiendra **pas** pour 2 000 clients. Le vrai
tirage arrive avec le client Faker, **Sprint 4** — `D-FAKER-1` s'y appliquera.

**Vérifié** : `TestUniciteDesNoms`, 4 tests · 341 au total.

---

## `A-01` — tranché le 10 août : le Sénégal n'est pas un cas particulier

**Décision du pilote** : *« l'équipe Faker a dit vouloir l'intégrer, donc c'est
prévu. Ne sois pas statique : traite le Sénégal comme tous les autres. »*

### Ce que cet arbitrage change : rien dans la conception

Vérifié le 10 août, le Sénégal était **déjà traité comme les trois autres à
chaque niveau** :

| | |
|---|---|
| `PAYS_CIBLES` | `("CM","CI","BF","SN")` — depuis le premier commit |
| Référentiel | 22 quartiers, +221, XOF/BCEAO |
| Opérateurs | Orange (Sonatel) 55 % · Free (Yas) 25 % · Expresso 20 % — **les trois vrais, avec leurs vrais préfixes** |
| Planification | 10 Kiosques prévus dans le plan courant |
| Invariants | `valider_devise_pays("XOF","SN")` ✅ · `XAF`, `EUR`, `USD` refusés |
| MSISDN | **200/200 attribuables** à un opérateur réel sénégalais |

**`A-01` ne bloquait qu'une chose : la source des payloads clients du Sprint 4.**
Aucun module existant n'en dépend. La conception n'a jamais été statique sur ce
point — c'est le **fournisseur de données** qui l'était.

### Ce qui reste vrai, et qui n'est pas un blocage

Tant que Faker ne rend pas le Sénégal, les 500 clients sénégalais du Sprint 4
n'ont pas de source. Deux voies, et aucune n'exige de toucher à la conception :

1. **Attendre l'intégration annoncée** — voie retenue par défaut ;
2. **Composer** ces 500 clients comme le Loader compose déjà les raisons
   sociales, les dates de naissance, les adresses et les MSISDN — puisque
   *« les MSISDN de Faker ne respectent aucun plan réel »* et que nous les
   remplaçons **déjà pour les quatre pays**.

> **Le point de méthode** : le Loader ne dépend de Faker que pour les
> patronymes, les formes juridiques et les secteurs. Tout le reste — géographie,
> numérotation, identité, cohérence monétaire — vient de **notre** référentiel.
> C'est précisément ce qui fait qu'un pays absent de Faker ne casse pas la
> conception.

**Vérifié le 10/08** : devises cloisonnées par pays (aucun croisement accepté),
12 opérateurs réels avec leurs plans de numérotation, 800 MSISDN générés sur
4 pays, **800 attribuables**.

---

## D-09 v2 · Mapping role -> UserType revise — alignement CDC + Manuel (10/08)

**Ce qui a change.** Le premier mapping `D-09` classait 9 des 12 roles metier
en `UserType.STAFF`. **C'etait une erreur de lecture du systeme**, revelee en
lisant la documentation officielle (Doc Fonctionnel, Manuel de Reference
14516354, Matrice RBAC 10321921, CDC).

**La distinction que j'avais manquee :**

| UserType | Qui c'est (Manuel de Reference) |
|---|---|
| `STAFF` | l'equipe de gestion **du siege FinZuu** (Back-Office) |
| `COMPANY` | le personnel **d'une institution cliente** — *« englobe le Business, l'Agent, le Kiosque, la Secretaire, le CFO, le Guichetier »* |

**Le Loader genere des INSTITUTIONS (IMF), pas le siege.** Le CDC est explicite :
*« il rattache chaque Agent a une **Company mere** »*. Un Agent, un Kiosque, une
Branche appartiennent a une institution — donc `COMPANY`, pas `STAFF`.

**Le mapping n'etait pas prescrit.** La page Seed v2.0 note : *« le mapping
12 roles -> 5 UserType n'est pas encore materialise »*. `D-09` etait donc une
decision de ma part, non une exigence — et elle etait fausse.

### Le mapping revise

| Role | Ancien | Nouveau | Justification |
|---|---|---|---|
| Super-Admin | ROOT | **ROOT** | administration plateforme (inchange) |
| Admin | STAFF | **COMPANY** | admin d'une institution |
| Marketing | STAFF | **COMPANY** | marketing/campagnes d'institution |
| Collecte | STAFF | **COMPANY** | pilotage collecte terrain (CO) |
| Comptable | STAFF | **COMPANY** | CFO d'institution (Manuel : CO englobe le CFO) |
| Branche | STAFF | **COMPANY** | unite territoriale de l'institution |
| Agent | STAFF | **COMPANY** | rattache a une Company mere (CDC) |
| **Compliance** | STAFF | **STAFF** | validation KYC finale — fonction SIEGE (Matrice RBAC : approbation = Institution/ST) |
| **Employe/IT** | STAFF | **STAFF** | exploitation, logs systeme — fonction SIEGE exclusive |
| Marchand, Kiosque | COMPANY | **COMPANY** | inchange |
| Client | CUSTOMER | **CUSTOMER** | inchange |

**Repartition : 1 ROOT, 8 COMPANY, 2 STAFF, 1 CUSTOMER.**

### Trois lignes de conduite respectees

1. **La geographie n'est pas touchee.** Le `type_user` est du TRANSPORT
   (conformiste, on suit leur contrat) ; l'arbre et le referentiel geographique
   sont notre MODELE (anti-corruption, notre richesse). Corriger un type ne
   change rien a la geographie.
2. **Les permissions restent distinctes.** Le *type* (niveau 1) et les
   *permissions* (niveau 3) sont deux choses. Cette revision ne touche que le
   type ; les permissions par role restent l'arbitrage `A-05`, non valide.
3. **Les 3 niveaux ne se confondent pas** : UserType (5, contrat CDC) / Role-
   Groupe (12, Seed v2.0) / Permission (40, catalogue serveur).

### Consequence sur l'environnement TEST

Les 11 groupes deja crees en base (run du 09/08) portent l'ANCIEN type. Le
`GET`-avant-`POST` les reutilise par NOM — il ne corrigera donc pas leur type
tout seul. Pour resynchroniser : `DELETE /groupes/{id}` (fonctionnel, prouve le
09/08) sur les 6 roles reclasses, puis recreation. **A faire au prochain run
`REAL`, signale, pas execute en silence.**
