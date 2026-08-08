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

## Décisions en attente

| # | Sujet | Pourquoi c'est bloqué |
|---|---|---|
| **A-01** | **Sénégal indisponible chez Faker** | 500 clients concernés. Trois voies : générateur interne pour SN · demande à Oti d'ajouter SN au `run_id` · réduction à 3 pays (contredirait `OBJ-01`). **Arbitrage utilisateur.** |
| **A-02** | **`EF-80` inapplicable tel qu'écrit** | Les champs `decision.*` n'existent pas, et les 2000 clients viennent de la famille A qui ne porte aucune décision. Deux options : le Loader attribue lui-même APPROVED/DECLINED dans les proportions du CDC (l'isolation vis-à-vis de ReadyScore reste totale), ou seuls quelques clients ont un vrai scoring. **Recommandation : la première.** |
| **A-03** | **Raisons sociales non crédibles** | Faker renvoie `Test Business CM 748`. `UC-08` exige *« un nom métier crédible »* et la démo cible IFC, AFD, BAD. Le Loader devra générer les raisons sociales. |
| **A-04** | **Où stocker les ~700 prêts simulés** | `CR-10` exige de vérifier 100 séquences de remboursement, `ENF-14` les indicateurs PAR. Sans persistance, invérifiable. Une 7ᵉ collection `simulated_loans` ? |
| **A-05** | **Permissions exactes des 12 rôles** | Arbitrage produit, pas technique. Proposition rédigée, non validée. |

---

## Erreurs de sondage commises et corrigées

Consignées pour que personne ne les refasse.

| Erreur | Correction |
|---|---|
| `/api/v1/groups/` → 404, conclu « endpoint absent » | La route est **en français** : `/api/v1/groupes/` → 200. Conclusion erronée reprise dans le Document Maître §11.0, **à retirer** |
| 24 appels à `/random` sans varier de paramètre, conclu « distribution 100 % APPROVED » | Le cache Faker est **clé par jeu de paramètres complet** — c'était 24 fois le même client |
| SN testé uniquement sur la famille A (enum strict) | Testé ensuite sur la famille B (sans enum) : **404**, SN absent des deux côtés |
| Pagination attachée à un modèle Pydantic via `object.__setattr__` | Remplacé par un champ typé `paginate` sur `ReponseServeur` |

---

*Tenu à jour à chaque décision. Une décision non écrite ici n'existe pas.*
