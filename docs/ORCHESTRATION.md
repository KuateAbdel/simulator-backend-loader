# Orchestration — l'ordre, le tempo, la reprise

| | |
|---|---|
| **Objet** | Comment le Loader **enchaîne** ses huit modules : dans quel ordre, à quelle cadence, et que faire quand ça casse au milieu. |
| **Statut** | Doctrine d'exécution. Écrite avant le premier `REAL` — **délibérément**. |
| **Écrit le** | 9 août 2026, en ouverture du Sprint 3 |
| **Ancré sur** | `docs/DOCTRINE.md` · `docs/DECISIONS.md` (D-01 → D-11) · mesures des 8 et 9 août |

> **Pourquoi ce document existe.** Cinq exécuteurs étaient écrits — Rôles,
> Organisation, Catalogue, Dépositaires, Staff — et **rien ne les enchaînait**.
> Chacun savait faire son métier ; aucun ne savait quand son tour venait, ni ce
> qui se passait si le précédent avait échoué à moitié. Un orchestrateur qui
> improvise son ordre écrit dans le désordre — et **trois services n'ont pas de
> `DELETE`**.

---

## 1. L'ordre n'est pas un choix — il est imposé

Chaque module dépend d'un identifiant produit par un autre. L'ordre est le seul
tri topologique possible du graphe de dépendances.

| # | Module | Ce qu'il produit | **Ce qui l'empêche d'être plus tôt** |
|---|---|---|---|
| 1 | **Rôles** | 11 `group_id` | rien — **aucune dépendance** |
| 2 | **Organisation** | `company_id`, licences, Admin Users, 4 comptes Lender | un Admin User exige un `group_id` (1) |
| 3 | **Catalogue** | `product_id` | **RIEN. Mesure du 11/08 : `CreateProductSchema` n'a AUCUN `company_id`** — requis : `type`, `name`, `category`. Le Catalogue pourrait passer en premier. Il reste ici parce que `product-service` expose un `deactivate` — donc partiellement reversible — et qu'on ouvre par le module totalement reversible |
| 4 | **Dépositaires** | Branches, Agences, Kiosques | un Dépositaire exige un `company_id` (2) |
| 5 | **Staff & Agents** | 60 à 100 Users | un User exige `group_id` (1) **et** `company_id` (2) ; un **Agent** exige un Kiosque (4) — `D-11` |
| 6 | **Clients** | 2 000 clients + comptes cascadés | un onboarding exige un `product_id` (3) ; le rattachement exige un Kiosque (4) |
| 7 | **Vie 180 jours** | transactions, re-scoring | exige des clients et leurs comptes (6) |
| 8 | **Recette** | rapport `CR-01` → `CR-12` | exige tout ce qui précède |

### Deux propriétés de cet ordre, et elles ne sont pas fortuites

**Le module 1 est le seul réversible.** `DELETE /api/v1/groupes/{id}` existe —
account-service, identity-service et depositary-service n'exposent rien de tel.
Commencer par le réversible n'est pas de la prudence décorative : c'est la seule
étape dont un échec ne laisse **aucune** trace.

**Le module 2 contient la seule écriture jamais exécutée.** `EF-13` — les
4 comptes du Lender — est la dernière hypothèse de `D-01` non vérifiée en
écriture. Elle passe **tôt**, sur 4 objets, plutôt que tard sur 2 000.

---

## 2. Le tempo — mesuré, pas estimé

### Le plafond dur : **20 workers asyncio**

> Mesure du 8 août (`H14`/`H15`) : au-delà de 20 à 30 workers, **dégradation
> silencieuse — sans `429`**.

C'est le fait le plus dangereux de tout le dossier. Un service qui répond `429`
se laisse piloter : on ralentit, on réessaie. Un service qui **dégrade sans le
dire** transforme la surcharge en corruption de données — des écritures
partielles qu'on croit réussies.

**Décision : 20, la borne basse.** Quand la panne est silencieuse, on ne
s'approche pas du bord pour voir. Ce n'est pas de la timidité, c'est
l'impossibilité de détecter qu'on l'a franchi.

### Le budget de temps

| | |
|---|---|
| Objectif | **30 minutes** pour la campagne complète (Sprint 6) |
| Volume mesuré | 10 000 à 15 000 requêtes user-service seules (3 par User) |
| Volume total estimé | ~25 000 requêtes, cascades clients comprises |
| Débit exigé | **≈ 14 req/s** |
| Budget par requête, à 20 workers | **≈ 1,4 s** |

Ce n'est pas serré. C'est le rappel que **le budget existe** : une seule route
lente le mange en entier. `GET /playground-client/random` de Faker a un timeout
mesuré à **90 s** — un appel, et 3 % du budget total est parti. Il est
**interdit** en campagne (`L-04`).

### Aucun limiteur en face

`F-07` : Faker, **aucun rate limit** (45 appels consécutifs).
`H14` : user-service, **aucun rate limit** (20 requêtes → `{200: 20}`).

**C'est un piège, pas un feu vert.** Rien ne nous arrêtera si nous poussons trop
fort. Le plafond de 20 est **le nôtre**, auto-imposé, et il n'a aucun garde-fou
en face — d'où la règle : il vit dans la configuration, jamais en dur dans un
appel.

### Le jeton expire pendant le run

| Jeton | Durée |
|---|---|
| access | **4 h** |
| refresh | 7 j |
| auth | 10 min |

Une campagne de 30 minutes rentre dans les 4 h. **Une session de travail, non** —
je l'ai appris à mes dépens le 9 août en concluant « 0 pays en base » sur un
jeton mort depuis des heures.

`ÉCART-38` : **le Loader doit implémenter `/auth/refresh`**, que la WebApp
ignore. Un run interrompu et repris le lendemain repart sur un jeton périmé, et
un `401` mal lu devient un fait empirique faux.

---

## 3. Les quatre mécanismes de sûreté, et le moment où chacun agit

### `GET`-avant-`POST` — **avant** chaque écriture

Aucune unicité serveur sur `name` (Company, Product, Dépositaire, Groupe). Sans
relecture préalable, un second run duplique tout. `D-PRD-2`, `D-DEP-3`,
`D-CLI-5`, `D5`.

Cas non trivial, mesuré : **plusieurs correspondances possibles**. Règle —
retenir **la plus ancienne** (`ANO-PRD-UNIQ-01`). Jamais la première rendue :
l'ordre n'est pas garanti.

### Journal d'intention — **avant et après** chaque cascade

L'onboarding client touche **trois services sans transaction**. Il n'y a pas
d'atomicité à obtenir ; il y a une **trace** à garder.

```
ouvrir_intention()  →  écriture réelle  →  resoudre_intention()
```

Une intention ouverte et jamais résolue est un **écrit non confirmé** : peut-être
passé, peut-être pas. `intentions_orphelines()` les rend au démarrage suivant.
C'est le seul recours contre un écosystème sans `DELETE`.

### `RegistreUnicite` — **avant le réseau**

Trois unicités imposées par le serveur : `msisdn`, `id_number`, `email`. Elles
sont réservées **en mémoire, avant tout appel**.

**C'est ce mécanisme qui rend les 20 workers sûrs.** Sans lui, deux workers
tirent le même MSISDN, partent en parallèle, et l'un des deux découvre le
conflit **après** avoir déclenché une cascade sur trois services — dont deux
sans suppression. La réservation locale déplace le conflit du réseau vers la
mémoire, là où il ne coûte rien.

### Ledger Faker — **réserver, puis consommer**

`D-FAKER-1` : jamais réutiliser un `client_id` Faker déjà consommé.

> ⚠️ **Sous concurrence, l'ordre est vital.** Vingt workers qui lisent le ledger,
> tirent, puis écrivent le ledger tirent **le même client**. La séquence est
> **réserver l'id d'abord, consommer ensuite** — comme `RegistreUnicite`. Le `_id`
> du ledger *est* le `client_id` Faker : la clé primaire fait la contrainte,
> l'insertion échoue au doublon. **C'est la réservation.**

---

## 4. Ce que la concurrence a le droit de faire

| Module | Parallélisable ? | Pourquoi |
|---|---|---|
| 1 · Rôles | ❌ **séquentiel** | 11 objets ; le `GET`-avant-`POST` porte sur une liste que chaque création modifie |
| 2 · Organisation | ⚠️ **par pays** | les Companies sont indépendantes entre pays ; à l'intérieur, `company → licence → admin` est une chaîne |
| 3 · Catalogue | ⚠️ **par company** | un `policy_id` ne se partage **jamais** (`D-PRD-7`) |
| 4 · Dépositaires | ⚠️ **par branche** | `EF-18` : un nœud ne peut exister sans son supérieur — la profondeur est séquentielle, la largeur non |
| 5 · Staff | ✅ **20 workers** | unicités pré-réservées |
| 6 · Clients | ✅ **20 workers** | unicités pré-réservées **et** ids Faker pré-réservés |
| 7 · Vie 180 j | ✅ **20 workers** | par client, indépendants |

**Règle générale : la profondeur est séquentielle, la largeur est parallèle.**
On ne crée jamais un enfant avant son parent ; on crée volontiers mille frères
à la fois.

---

## 5. Le mode gouverne tout

`DRY_RUN` **n'est pas** « ne rien faire ». Il **conserve les lectures** et
supprime les écritures. Sans les lectures, le rapport annoncerait des créations
qui n'auraient jamais lieu — puisqu'une partie des objets existe déjà.

> **Discipline : aucun module ne passe en `REAL` sans que son `DRY_RUN` ait été
> lu par un humain.** Trois services n'ont pas de `DELETE`. Le rapport de
> `DRY_RUN` est la dernière occasion de dire non.

---

## 6. La reprise — ce qui se passe quand ça casse à 60 %

L'ordre topologique donne une propriété que rien d'autre ne donne : **un run
interrompu s'arrête toujours sur un préfixe valide.** Les modules 1 à N sont
faits, N+1 à 8 ne le sont pas. Jamais l'inverse.

Reprise, dans l'ordre :

1. **Renouveler le jeton** — `/auth/refresh` (`ÉCART-38`), avant toute lecture
2. **Rendre les intentions orphelines** — `intentions_orphelines()`
3. **Relire l'état réel** — `GET`-avant-`POST` fait le reste : ce qui existe est réutilisé, pas recréé
4. **Reprendre au module interrompu**, pas au début

C'est ce qui rend `CR-04` — *« deux exécutions identiques donnent le même
résultat »* — vérifiable. L'idempotence n'est pas un bonus : c'est le mécanisme
de reprise lui-même.

---

## 7. Ce qui manque encore — dit franchement

| Manque | Sprint | Conséquence tant qu'il dure |
|---|---|---|
| 🔴 **Le client Faker n'existe pas** — 9 clients FinZuu écrits, zéro pour Faker | **S4** | Organisation et Staff rejouent une table de patronymes mesurés. C'est de la **matière réelle**, mais figée : 20 noms pour 2 000 clients ne tiendra pas |
| 🔴 **L'orchestrateur n'existe pas** — ce document le décrit, le code ne l'implémente pas | **S3** | Les exécuteurs se lancent à la main, un par un |
| 🟠 `/auth/refresh` non implémenté (`ÉCART-38`) | **S3** | Une session de plus de 4 h lit des `401` et les prend pour des faits |
| 🟠 Verrou d'exécution — rien n'empêche deux runs simultanés | **S6** | Deux runs concurrents dupliquent tout : le `GET`-avant-`POST` de l'un ne voit pas les écritures en vol de l'autre |

---

## 8. En une phrase

> **L'ordre vient des dépendances, le tempo vient des mesures, la reprise vient
> de l'idempotence.** Aucun des trois n'est un choix de style : chacun est la
> seule réponse possible à une contrainte constatée.
