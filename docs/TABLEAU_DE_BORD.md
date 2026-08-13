# Tableau de bord — l'état vivant du backlog

> Reconstruit le 13/08/2026 depuis les plans commités (`PLAN.md`,
> `PLAN_SPRINTS.md`, `PLAN_INTEGRATION_STATIC_DATA.md`,
> `CONCEPTION_CATALOGUE_ET_SOUSCRIPTION.md`, `ORCHESTRATION.md`).
> **Ce fichier est mis à jour à chaque tâche fermée** — c'est lui qui survit aux
> sessions, pas la liste de tâches de l'outil.
>
> Le Loader n'est pas un script : c'est le **backend de pilotage** de la
> plateforme. La cible est v1.0.0 — 2000 clients en 30 minutes, recette
> CR-01→CR-12 tenue, piloté par le Super-Admin sans assistance (CR-05).

## A. Chantier « référentiels statiques de JJB » — 6 lots

| # | Tâche | État |
|---|---|---|
| SD-1 | Chargeur `referentiel_statique.py` (6/112/27/576/21/4/195/20) | ✅ `345171c` |
| SD-2 | Companies : `industries` ≠ `sectors`, Fondation servie, 27 formes | ✅ `7f78fca` |
| SD-3 | Occupations : 18 → 576, règle `bank_stable`, EF-24 visible | ✅ `a2646ba` |
| SD-4 | Dirigeants : « Dirigeant » → 20 fonctions | ✅ `7f78fca` |
| SD-5 | `solde_initial` : heuristique → LogNormal(μ,σ) par profession, borné Annexe E, mesure EF-68 refaite — **A-09 FERMÉ** | ✅ 13/08 |
| SD-6 | Lieu de naissance : 195 pays + 50 villes, `id_place` ≠ résidence *(ancienne tâche #15)* | ✅ 13/08 |
| — | Bilan de chantier ultra-détaillé des 6 lots | ⬜ |

## B. Chantier « catalogue » — les 11 changements du §8

| # | Tâche | État |
|---|---|---|
| CAT 1-2 | **Décidé par Yaniv le 13/08** : produits RÉELS et recherchés — `Tontine Digitale` · `Compte Epargne Entreprise` · `Epargne Bloquee 6 Mois` · `Depot a Terme Entreprise 12 Mois` · `Warrantage Cerealier` · `Collecte Cacao Cooperative` (conception §4 : PAMECAS, warrantage sahélien). Marqueur `DEMO_` dans `short_name`, protocole à deux clés contre `ANO-PRD-UNIQ-01` | ✅ 13/08 |
| CAT 3-5 | Produits environnement constatés · 12 créations | ✅ (12/08, `c53c05d`) |
| CAT 6 | CR-07 : marqueur selon le type d'entité — s'active quand les produits entrent dans `org_hierarchy` | ⬜ avec CAT 7-8 |
| CAT 7-8 | Rattachement Produit→Company (`org_hierarchy`) + panier depuis SA Company *(ancienne tâche #29 / A-12)* | ⬜ |
| CAT 9-11 | `perimetre_lending` · `PRODUITS_ATTENDUS` fonction du périmètre · recette « hors périmètre » | ⬜ |

## C. La séquence REAL — l'ordre topologique d'ORCHESTRATION.md

| Palier | Tâche | État |
|---|---|---|
| 1 | Rôles : 11 `group_id` (seul module réversible) | ⬜ |
| 2 | Organisation : 16 Lenders, licences, Admin Users, 4 comptes (S3-03) | ⏸ paliers 1 + décisions catalogue |
| 3 | Catalogue : 12 créations, noms réels, marqueur `short_name` | ⬜ |
| 4 | Dépositaires : 40-80 nœuds, Agents (S3-06) | ⬜ |
| 5 | Staff & Agents : 60-100 users, 11 rôles | ⏸ **A-05** |
| 6 | Clients : 2000, quotas, EF-26 deux temps | ⬜ SD-3 ✅ prêt |
| — | Second run REAL identique — preuve CR-03 | ⬜ |
| 7 | Vie 180 jours + crédit (EF-67→80) | ⏸ **A-07, A-11, A-04** |
| 8 | Recette : CR-01→12 tous TENUS + mesure 30 min → **v1.0.0** | ⬜ |

## D. Super-Admin — étape 8 du PLAN, Sprint 6

| Tâche | État |
|---|---|
| Routes de pilotage EF-50→EF-59 — conception écrite (`CONCEPTION_API_SUPER_ADMIN.md`, 13/08) : 5 lots A→E, contrat OpenAPI d'abord pour Zidane | ⬜ socle CFG-01→06 ✅ |
| Purge par préfixe `DEMO_` + verrou d'exécution (EF-65/66) | ⬜ |

## E. Backlog S4/S5 restant

| Tâche | État |
|---|---|
| INV-18 — MSISDN pondérés par parts de marché opérateur | ⬜ |
| P-01 — index inverse (client→produit, client→kiosque) | ⬜ |
| P-02 — plafonds KYC BCEAO | ⬜ s'écrit AVEC le module Vie |
| P-03 — float de l'agent | ⬜ s'écrit AVEC le module Vie |

## F. Les arbitrages qui n'appartiennent qu'à Yaniv

`A-05` (permissions 11 rôles) · `A-07` (profils comportementaux) · `A-11`
(proportion APPROVED/DECLINED) · `A-04` (persistance des prêts) · `A-08`
(désactiver un pays) · noms métier du catalogue + marqueur `short_name` ·
Agents compris ou en sus des 15-25 staff/pays. Recommandations écrites dans
`PLAN_SPRINTS.md` §3.4 et `A-05_PERMISSIONS_A_TRANCHER.md`.
