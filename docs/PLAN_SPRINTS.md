# Loader FinZuu v1.0.0 — Plan de conduite

**Méthode : Scrum.** Sprints d'incréments livrables, backlog priorisé, rien
d'entrepris hors backlog. Ce document remplace le travail au fil de l'eau.

| | |
|---|---|
| **Version cible** | **1.0.0** — première livraison du Loader |
| **Établi le** | 9 août 2026 |
| **Tenu par** | Kuate Abdel Yaniv — Tech Lead / DevSecOps / QA Lead |

---

## 1. La règle qui gouverne tout le backlog

> **Le CDC dit QUOI. Il ne dit pas COMMENT tenir la qualité technique.**

Le CDC v1.2 est un **SRS** (IEEE 830) : il exprime le besoin fonctionnel de la
Direction Technique. Les propriétés d'unicité, d'atomicité, de cohérence humaine
et de traçabilité relèvent d'un **SDD** (IEEE 1016) — et **c'est à nous de le
poser**. Ce ne sont pas des exigences oubliées par le CDC : ce sont des
exigences d'une autre nature.

**Corollaire opérationnel** : chaque défaut mesuré côté serveur devient une
**barrière côté Loader**, jamais un simple ticket. Le Loader ne répare pas le
serveur — il reste cohérent malgré lui.

---

## 2. Les 4 rôles que je tiens sur ce projet

| Rôle | Ce qu'il exige à chaque incrément |
|---|---|
| **Architecte** | Le domaine s'enracine sur `Country → Company → Kiosque → Client`, jamais sur Client. Aucune spéculation : rien n'est conçu sans mesure préalable. |
| **QA Lead** | *Verify, don't trust.* Toute discipline héritée est **rejouée** avant d'être codée. Une source datée est une hypothèse, pas un fait. |
| **DBA** | Unicité, atomicité, invariants, traçabilité. Notre base est la **seule** à pouvoir les garantir : trois services n'ont aucun `DELETE`, aucun n'a de transaction. |
| **DevSecOps** | Préfixe `DEMO_`, mode `DRY_RUN` par défaut, empreinte déclarée à chaque campagne, aucun secret commité. |

---

## 3. Backlog — **tous** les manques recensés

Rien n'est masqué. Chaque ligne porte sa preuve et son sprint.

### 3.1 🔴 Invariants absents du système — notre couche de qualité

| # | Manque | Preuve | Sprint |
|---|---|---|---|
| `INV-01` | **Âge non contrôlé** — 2 ans et 120 ans acceptés | mesure 09/08 | **S1** |
| `INV-02` | **Faker ne fournit aucune date de naissance** — famille A *et* B | mesure 09/08 | **S1** |
| `INV-03` | **`gender` non validé** — `"peu importe"` → 201 | mesure 09/08 | **S1** |
| `INV-04` | **`marital_status` non validé** | mesure 09/08 | **S1** |
| `INV-05` | **`currency` non validée** et propagée au compte — origine de `FRA-222` | mesure 09/08 | ✅ fait |
| `INV-06` | **Type de produit non contrôlé** — LENDING accepté sur un Client | mesure 09/08 | ✅ fait |
| `INV-07` | **Catégorie croisée** — CORPORATE sur produit INDIVIDUAL | mesure 09/08 | ✅ fait |
| `INV-08` | **Plafond de souscriptions** — 6 acceptées, `UC-13` en autorise 3 | mesure 09/08 | ✅ fait |
| `INV-09` | **Unicité triple** — `msisdn`, `id_number`, `email` ; `EF-25` n'en cite qu'un | mesure 09/08 | **S1** |
| `INV-10` | **Casse non normalisée** — `id_number` et `nationality` en minuscules acceptés | mesure 09/08 | **S1** |
| `INV-11` | **Cohérence `id_expire_on`** — aucune règle : une pièce peut expirer hier | contrat | ✅ fait |
| `INV-12` | **Atomicité** — cascade à 3 services, aucun rollback, aucun `DELETE` | structurel | **S1** |
| `INV-13` | **`EF-27`** — MSISDN vs regex opérateur : les 12 plans réels n'étaient **pas chargés** | mesure 09/08 | ✅ fait |
| `INV-14` | **Les MSISDN de Faker ne respectent aucun plan réel** — 18/18 non attribuables sur 3 pays | mesure 09/08 | ✅ constaté |
| `INV-15` | **Devise ↔ zone monétaire** — `XAF` = CEMAC (CM), `XOF` = UEMOA (CI, BF, SN). Ma liste close `{XAF, XOF}` était **trop permissive** | référentiel | ✅ fait |
| `INV-16` | **Situation familiale ↔ âge** — un veuf de 18 ans passe | mesure 09/08 | ✅ fait |
| `INV-17` | **Champs vides** — `city`, `region`, `country`, GPS persistés à `null` | mesure 09/08 | ✅ fait |
| `INV-18` | **Répartition par opérateur** — le référentiel porte les parts de marché réelles (MTN CM 46 %, Orange CM 43 %…), jamais utilisées | référentiel | **S4** |

> **`INV-14` — la décision qui en découle.** Appliquer `EF-27` aux MSISDN de
> Faker rejetterait **100 % des 2 000 clients**. Le Loader **compose donc son
> propre MSISDN** depuis le plan de numérotation réel, pondéré par les parts de
> marché — exactement comme il compose déjà les raisons sociales, les dates de
> naissance et les adresses. Le `sim_number` de Faker n'est conservé que pour la
> traçabilité. **C'est la même doctrine, appliquée à un cinquième champ.**

### 3.2 🔴 Points cassés côté serveur — anticipés, jamais réparés

| Réf | Défaut | Parade Loader | État |
|---|---|---|---|
| `FRA-218` | Les frais disparaissent de l'opération | ne jamais déduire un solde, toujours le relire | ✅ portée |
| `FRA-219` | `change-status` répond 500 et réussit | ne jamais rejouer sur 500 de cette route | ✅ portée |
| `FRA-220` | `owner_type=COMPANY` désigne aussi les Dépositaires | résolution par `type` de compte | ✅ portée |
| `FRA-222` | `currency` non validée | liste close `{XAF, XOF}` | ✅ portée |
| `FRA-223` | Dépositaire souscrivant du LENDING | `D-DEP-9` | ✅ portée |
| `FRA-224` / `FRA-225` | Références non validées à la création | `GET`-avant-`POST`, identifiants relus | ✅ portée |
| `FRA-227` | `owner._id` ignoré | toujours relire l'identifiant rendu | ✅ portée |
| `FRA-228` | Casse annoncée, non appliquée | majuscules émises, seuls les spéciaux rejetés | ✅ portée |
| `ANO-CLI-SEARCH-01` | `POST /search` ignore ses critères | **`/search` jamais utilisé** | ✅ portée |
| `ANO-CLI-LANG-01` | `language` ignoré à l'onboarding | repli sur `PATCH /language` | ✅ portée |
| — | **Jeton CUSTOMER rejeté comme invalide** | non ticketé, cause inconnue | **S2** |

### 3.3 ⬜ Exigences CDC non couvertes

| Réf | Exigence | Sprint |
|---|---|---|
| `EF-26` | Rattacher chaque client à un Kiosque — **inapplicable à la création**, deux temps via `org_hierarchy` | **S4** |
| `EF-27` | Valider le MSISDN contre le regex telco du pays | **S1** |
| `EF-22` | 60 % < 25 ans, 2 femmes / 1 homme | **S1** *(barrières)* + **S4** *(quotas)* |
| `UC-09` | 60 à 100 users staff, 11 rôles | **S2** |
| `EF-76` → `EF-80` | Vie commune 180 jours, re-scoring | **S5** |

### 3.4 Arbitrages en attente — **vous**

| # | Sujet | Impact |
|---|---|---|
| **`A-01`** | **Sénégal absent de Faker** — 500 clients sans source | bloque 25 % de `S4` |
| **`A-07`** | Forme des 4 profils comportementaux | bloque `S5` — *recommandation : on les définit* |
| **`A-05`** | Permissions exactes des 11 rôles | bloque la finition de `S2` |
| **`A-04`** | Persistance des ~700 prêts simulés | bloque `CR-10` en `S6` |
| — | Agents compris ou en sus des 15-25 staff/pays | dimensionne `S2` |

---

## 4. Les sprints

### ✅ Sprint 0 — Socle et connaissance *(terminé)*

Socle HTTP, 6 repositories, bootstrap Super-Admin, référentiel géographique,
**9 services sur 9 sondés**, 8 clients de services, 11 anomalies ticketées,
2 documents de modèle, `A-06` levé.

### 🎯 Sprint 1 — **Invariants et cohérence humaine** *(en cours)*

**But** : le Loader n'émet plus jamais une donnée qu'un banquier jugerait absurde.

| Story | Contenu |
|---|---|
| `S1-01` | Module `app/core/invariants.py` — âge, cohérence des dates, casse |
| `S1-02` | Âge : **18 à 75 ans**, majorité légale des 4 pays |
| `S1-03` | Cohérence `date_of_birth` ↔ `id_expire_on` ↔ `occupation` |
| `S1-04` | Unicité triple garantie **avant** le réseau, index locaux |
| `S1-05` | `EF-27` — regex telco par pays depuis `telcos.csv` |
| `S1-06` | Journal d'intention (write-ahead) dans `audit_trail` — l'atomicité |

**Définition de terminé** : `ruff` + `mypy` + tests verts, chaque règle adossée à
une mesure ou à une norme citée, aucune règle inventée.

### ⬜ Sprint 2 — Module Utilisateurs

11 rôles (`D-09`), 60 à 100 staff, `identity_service.py`, ticket du jeton
CUSTOMER rejeté. **Dépend de `A-05`.**

### ⬜ Sprint 3 — Organisation, Catalogue, Dépositaires en réel

Les trois exécuteurs déjà écrits passent de `DRY_RUN` à `REAL`. Companies,
licences, Admin Users, 4 comptes Lender (`EF-13`, jamais exécuté), catalogue,
40-80 Dépositaires.

### ⬜ Sprint 4 — Population client

2 000 clients, quotas `EF-22`/`EF-23`/`EF-24`, rattachement Kiosque en deux
temps. **Dépend de `A-01`.**

### ⬜ Sprint 5 — Vie 180 jours

Profils comportementaux, `_adjust_weights` de Duhamel — **enfin actif, puisque
nous fournissons la date de naissance**. Re-scoring. **Dépend de `A-07`.**

### ⬜ Sprint 6 — Pilotage et recette

Routes Super-Admin, purge par préfixe, verrou d'exécution, `CR-01` → `CR-12`,
mesure des 30 minutes. **→ v1.0.0**

---

## 5. Versionnage

**SemVer.** `1.0.0` = première livraison complète couvrant `CR-01` → `CR-12`.
Avant : `0.x.y`, un `0.x` par sprint clos. Le numéro n'est posé que sur un
incrément dont la définition de terminé est atteinte — jamais sur une intention.

| Version | Contenu | État |
|---|---|---|
| `0.1.0` | Socle et connaissance | ✅ |
| `0.2.0` | Invariants et cohérence humaine | 🎯 |
| `0.3.0` | Module Utilisateurs | ⬜ |
| `0.4.0` | Organisation, Catalogue, Dépositaires | ⬜ |
| `0.5.0` | Population client | ⬜ |
| `0.6.0` | Vie 180 jours | ⬜ |
| **`1.0.0`** | **Pilotage et recette** | ⬜ |

---

## 6. Sur les diagrammes UML — mon avis, contradictoire

Votre analyse « 7 diagrammes retenus, 7 éliminés » est la bonne doctrine. **Mais
notre situation est différente de celle qu'elle décrit** : les 11 diagrammes
existent déjà, ils ont été **corrigés sur preuve** le 8 août (7 corrections,
vérifiées appliquées dans les `.puml` le 9), et ils sont **cités par le CDC**.

Les supprimer maintenant coûterait de la traçabilité contractuelle sans rien
apporter. Ma position : **on les garde, et on applique la discipline
d'élimination au SDD à venir** — qui, lui, n'existe pas encore et doit être
écrit avec 5 à 7 vues, pas 11.

*Si vous préférez trancher dans les diagrammes existants, dites-le : c'est votre
appel, et je l'applique.*

---

*Ce plan se met à jour à la clôture de chaque sprint. Une tâche absente d'ici
n'est pas entreprise.*
