# Exigence de paramétrage — analyse d'impact

> **Demande de la Direction Technique, 9 août 2026** :
> *« Il est super important que le Loader soit flexible et paramétrable :
> activation et désactivation d'un pays · ajout région/ville · créer nb
> users/company, etc. par pays/région/ville, homme versus femme. À titre
> d'exemple. »*
>
> Le Super-Admin du Loader peut également **intervenir et agir sur les API**.

Cette exigence n'est pas cosmétique : **elle change le statut de la volumétrie**,
qui passe de constante figée à paramètre d'exécution. Elle est analysée ici avant
d'être planifiée.

---

## 1. Ce qui existait déjà, et ce que la demande ajoute

`EF-04` prévoyait : *« ajouter un pays ne demande aucune modification de code,
uniquement des lignes dans le fichier source »*. C'est **du paramétrage par
fichier, avant exécution**.

La demande va plus loin : **du paramétrage au moment du lancement, par un
non-technicien, depuis l'interface** (`OBJ-06`). Ce n'est pas la même chose, et
ça touche trois endroits du code.

| | `EF-04` (existant) | Demande du 09/08 |
|---|---|---|
| Qui | un développeur | **le Super-Admin, sans code** |
| Quand | avant l'exécution, par édition de fichier | **au lancement, par l'interface** |
| Quoi | ajouter un pays au référentiel | **activer/désactiver, ajouter, doser** |

---

## 2. Ce que le serveur permet réellement — mesuré le 9 août

### ✅ Activation / désactivation d'un pays — **existe**

```
PATCH /api/v1/countries/activate/{id}
PATCH /api/v1/countries/deactivate/{id}
```

Les mêmes existent pour `currencies` et `telcos`. La demande est directement
réalisable côté serveur.

> ⚠️ **Mais « désactiver un pays » a deux sens qu'il ne faut pas confondre :**
>
> | Sens | Effet |
> |---|---|
> | **Côté serveur** | Le pays passe `is_active: false` dans config-service — **c'est une donnée partagée**, visible par tous les services et toutes les équipes |
> | **Côté Loader** | Le pays est exclu de **notre** génération, sans rien toucher au serveur |
>
> Ce sont deux actions différentes, aux portées très différentes. La seconde est
> réversible et sans effet de bord ; la première modifie l'environnement de
> **toute l'équipe**. **Arbitrage `A-08` ouvert** — voir §5.

### ⚠️ Ajout d'une ville — **existe, avec un piège**

```
PUT /api/v1/countries/{id}     UpdateCountrySchema
```

**Les 9 champs sont requis** : `name_en`, `name_fr`, `iso_name`, `dial_code`,
`region`, `continent`, `cities[]`, `currencies[]`, `telcos[]`.

> 🔴 **Ce n'est pas un `PATCH`.** Un client qui n'enverrait que `cities` **perdrait
> tout le reste** — devise, opérateurs, indicatif. C'est exactement l'objet du
> ticket `TS-CFG-09` déjà ouvert.
>
> **Discipline** : toute mise à jour d'un pays passe par **relecture complète →
> modification du seul champ visé → renvoi intégral**. Jamais un envoi partiel.

### 🔴 Ajout d'une **région** — **impossible côté serveur**

config-service **n'a aucune notion de région administrative**. Son champ
`Country.region` vaut `"Middle Africa"` ou `"Western Africa"` : c'est la région
**continentale**.

> **Nos 51 régions administratives et nos 82 quartiers n'existent que chez nous.**
> « Ajouter une région » est donc, par construction, une opération **purement
> Loader** — et c'est une illustration de plus du *System of Record* : nous
> faisons autorité sur une dimension que le serveur ne sait pas porter.

### 🔴 Doser par pays / région / ville, homme vs femme — **aucune API**

Purement notre affaire. Aucun service ne connaît la notion de quota.

---

## 3. Ce que ça change dans notre conception

### 3.1 Les constantes du CDC deviennent des **valeurs par défaut**

Sept constantes de `app/core/cdc.py` sont aujourd'hui `Final` — figées à
l'import :

| Constante | Valeur CDC | Devient |
|---|---|---|
| `PAYS_CIBLES` | `CM, CI, BF, SN` | **paramétrable** — sous-ensemble activable |
| `COMPANIES_PAR_PAYS` | 3 à 5 | paramétrable **par pays** |
| `KIOSQUES_PAR_PAYS` | 10 à 20 | paramétrable **par pays** |
| `STAFF_PAR_PAYS` | 15 à 25 | paramétrable **par pays** |
| `NB_CLIENTS` | 2 000 | paramétrable, **réparti par territoire** |
| `RATIO_FEMMES_HOMMES` | 2 : 1 | paramétrable **par territoire** |
| `PART_INDIVIDUAL` / `PART_CORPORATE` | 80 / 20 | paramétrable |

**Elles ne disparaissent pas** : elles deviennent le **défaut contractuel**. Un
lancement sans paramètre doit produire exactement ce que le CDC décrit — c'est la
garantie que le paramétrage n'affaiblit pas l'exigence.

### 3.2 Un quota global devient un **arbre de quotas**

Aujourd'hui `RATIO_FEMMES_HOMMES` est unique et global. La demande le veut **par
pays, par région, par ville**. C'est un changement de nature :

```
défaut CDC  ──►  surcharge pays  ──►  surcharge région  ──►  surcharge ville
                                                        (le plus précis gagne)
```

**Règle de résolution** : le niveau le plus fin l'emporte ; en son absence, on
remonte. Un quota absent partout retombe sur le défaut CDC. **Aucun territoire
ne peut se retrouver sans règle.**

### 3.3 🔴 La tension avec `ENF-15` — le point dur

`ENF-15` exige que **deux exécutions du même `run_id` produisent le même
résultat**. Aujourd'hui c'est vrai parce que tout dérive du `run_id` et de
constantes figées.

**Dès que la volumétrie devient paramétrable, le `run_id` ne suffit plus.**

> **Conséquence obligatoire** : la configuration complète d'une exécution doit
> être **persistée avec elle**, dans `loader_runs`. Rejouer un run, c'est rejouer
> `run_id` **et** sa configuration. Sans cela, `ENF-15` est perdue et `CR-04`
> devient invérifiable.

C'est aussi ce qui rend le paramétrage **auditable** : le tableau de bord pourra
montrer, pour chaque exécution, *ce qui a été demandé* et *ce qui a été produit*.

### 3.4 Le référentiel doit accepter une **surcouche**

`ReferentielGeo` est chargé depuis le classeur et immuable. Ajouter une région ou
une ville au lancement suppose une **surcouche** au-dessus du fichier :

* le classeur reste la **source de référence**, jamais modifié par le Loader ;
* les ajouts du Super-Admin vivent dans une couche distincte, **tracée et
  réversible** ;
* les invariants du chargement (`EF-02`) s'appliquent **aussi** aux ajouts : une
  ville sans région valide est refusée, exactement comme dans le fichier.

---

## 4. Le Super-Admin agissant sur les API

C'est le prolongement naturel : le Super-Admin du Loader peut déclencher, depuis
l'interface, des actions sur config-service — activer un pays, ajouter une ville.

**Trois garde-fous non négociables**, cohérents avec la doctrine :

| Garde-fou | Raison |
|---|---|
| **Toute action passe par le journal d'intention** | Une écriture sur un référentiel **partagé** doit être traçable et réconciliable |
| **`DRY_RUN` d'abord, toujours** | Le mode par défaut montre ce qui serait fait avant que quoi que ce soit le soit |
| **Jamais de suppression** | Ni pays, ni devise, ni opérateur. On active, on désactive, on ajoute — **on ne détruit rien** dans un environnement partagé |

Et une limite de périmètre : **le Loader ne purge pas les 6 entrées parasites**
de config-service. Il les signale. Les supprimer relève de l'équipe qui tient le
service.

---

## 5. Arbitrage ouvert — `A-08`

> **« Désactiver un pays » : chez nous, chez eux, ou les deux ?**

| Option | Portée | Réversible | Risque |
|---|---|---|---|
| **Loader seul** | notre génération | oui, immédiat | aucun |
| **Serveur seul** | config-service, **toute l'équipe** | oui, par `activate` | un collègue peut être bloqué sans comprendre pourquoi |
| **Les deux** | complet | oui | idem |

**Recommandation : Loader seul par défaut**, avec l'action serveur disponible
mais **explicitement distincte dans l'interface** — deux boutons, deux libellés,
jamais un seul geste qui fait les deux. Un environnement de TEST est partagé ;
une désactivation silencieuse coûterait une demi-journée à quelqu'un d'autre.

---

## 6. Ce que ça donne au backlog

| # | Story | Sprint |
|---|---|---|
| `CFG-01` | Modèle de configuration d'exécution — arbre pays/région/ville, défauts CDC | **S6** |
| `CFG-02` | Persistance de la configuration dans `loader_runs` — **prérequis d'`ENF-15`** | **S6** |
| `CFG-03` | Surcouche référentielle : ajout région/ville, invariants `EF-02` appliqués | **S6** |
| `CFG-04` | Résolution des quotas — le niveau le plus fin gagne | **S6** |
| `CFG-05` | Actions Super-Admin sur config-service — intention, `DRY_RUN`, jamais de `DELETE` | **S6** |
| `CFG-06` | `PUT /countries/{id}` : relecture complète avant écriture (`TS-CFG-09`) | **S6** |

**Sprint 6 — Pilotage**, avec les routes Super-Admin déjà prévues
(`EF-50` → `EF-59`). L'exigence ne perturbe pas les sprints 2 à 5 : elle les
**paramètre**. La seule contrainte à respecter dès maintenant est **de ne pas
figer davantage** — toute nouvelle constante de volumétrie doit naître
paramétrable.

---

*Analyse du 9 août 2026. À valider par la Direction Technique sur le point `A-08`.*
