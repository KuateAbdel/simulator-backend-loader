# Faker — le champ du solde initial n'est pas là où le CDC le place

| | |
|---|---|
| **Objet** | `MOB_MONEY_ACCOUNT_AMOUNT`, désigné par le CDC comme source du solde initial de chaque compte client. |
| **Nature** | **Lecture seule stricte.** 13 appels `GET`. `POST /cache/clear` jamais appelé. |
| **Date** | 11 août 2026 · `run_id = 20260620123721` |
| **Complète** | `2026-08-08_faker_maitrise_complete.md` §3, dont le bloc `quick_win` était tronqué. |

---

## 1. Ce que le CDC exige

> **UC-13**, étape 2 : « Il lit la valeur `MOB_MONEY_ACCOUNT_AMOUNT` du payload Faker. »
> **§ Flux monétaires** : « Le Loader DOIT doter chaque compte client d'un solde
> initial à sa création, dérivé du montant Mobile Money du payload Faker. Cette
> voie garantit que chaque client dispose d'un patrimoine cohérent avec son
> profil socio-économique, **sans invention arbitraire de montants**. »

L'exigence porte donc deux choses distinctes : un **champ** (`MOB_MONEY_ACCOUNT_AMOUNT`)
et une **intention** (un patrimoine cohérent avec le profil socio-économique,
et surtout : rien d'arbitraire). La suite montre que le champ est hors d'atteinte
et que l'intention, elle, reste tenable.

## 2. Mesure — famille A : le champ est absent

Six tirages, 3 pays × 2 seeds. `quick_win` compte **11 clés**, exhaustivement :

```
IS_DATA_RGS1  IS_DATA_RGS7  IS_DATA_RGS30  IS_DATA_RGS90
IS_RGS_1      IS_RGS_7      IS_RGS_30      IS_RGS_90
IS_SMARTPHONE_USER   LAST_EVENT_DATE   LAST_EVENT_TYPE
```

Racine : `client_id`, `country_code`, `currency`, `customer_category`,
`first_name`, `last_name`, `full_name`, `gender`, `identity`, `quick_win`,
`sim_number`. **Onze champs, aucun montant.**

| Tirage | `client_id` | devise | candidats « montant » |
|---|---|---|---|
| CM seed 7 | `CM-IND-572544` | XAF | **aucun** |
| CM seed 42 | `CM-IND-320409` | XAF | **aucun** |
| CI seed 7 | `CI-IND-570960` | XOF | **aucun** |
| CI seed 42 | `CI-IND-705970` | XOF | **aucun** |
| BF seed 7 | `BF-IND-341838` | XOF | **aucun** |
| BF seed 42 | `BF-IND-894503` | XOF | **aucun** |

Recherche insensible à la casse sur `MONEY`, `AMOUNT`, `MOB` : **zéro occurrence**.

> La devise, elle, est correcte et suit le pays : XAF pour CM, XOF pour CI et BF.
> C'est une confirmation utile — mais notre `valider_devise_pays()` reste la
> source, pas Faker.

## 3. Mesure — famille B : le champ existe, et il est souvent vide

`GET /real-scoring-payload/random`, **7 jeux de paramètres distincts** (le cache
est clé sur le jeu complet : varier un paramètre est la seule façon d'itérer).

| `client_id` | `MOB_MONEY_ACCOUNT_AMOUNT` | `MOB_MONEY_REVENUE` | `TOTAL_SPENT_MOB_MONEY_ACCOUNT` |
|---|---|---|---|
| `RC-CM-IND-CMC307388` | **0.0** | 605 314,78 | 451 464,95 |
| `RC-CI-IND-CIC101136` | **0.0** | 17 531,29 | 23 375,05 |
| `RC-BF-IND-BFC589851` | 46 125,26 | 2 634 040,44 | 2 118 078,05 |
| `RC-CM-IND-CMC6677` | **0.0** | 0.0 | 0.0 |
| `RC-CM-IND-CMC904722` | 76 983,96 | 242 912,34 | 181 304,75 |
| `RC-CI-IND-CIC191306` | **0.0** | 0.0 | 0.0 |
| `RC-BF-IND-BFC1089862` | 3 880 874,70 | 4 986 168,77 | 1 097 389,68 |

**3 valeurs exploitables sur 7.** Le champ est renseigné mais creux, et son
amplitude va de 46 k à 3,88 M — il n'est pas un solde de compte, il ressemble à
un encours instantané. Dix-sept clés contiennent `MONEY` en famille B, dont
`MOB_MONEY_REVENUE`, `TOTAL_CASHOUT_MOB_MONEY_ACCOUNT`,
`TOTAL_LOADING_MONEY_IN_MOB_MONEY` — toutes plus riches que celle que le CDC cite.

## 4. Le fait structurant, et il n'est pas nouveau

Le champ existe **uniquement dans la population qui ne peut pas fournir nos
2000 clients.** La famille B est figée au `run_id`, sans `seed`, sans pagination,
sans curseur — elle est inexploitable en volume (`CT-03`, et §0 de la mesure du
8 août).

C'est **la même cause racine** que pour `EF-80` (décision de scoring) et `EF-20`
(coordonnées géographiques) : le CDC a été écrit en supposant **une** population
Faker ; la mesure en a trouvé **deux, disjointes**. Chaque exigence inapplicable
est une exigence qui suppose qu'un client de famille A porte une donnée de
famille B. Ce n'est pas une erreur de rédaction ponctuelle — c'est un seul écart,
qui se manifeste trois fois.

## 5. Ce qui reste tenable

Trois voies, une seule honnête :

| Voie | Verdict |
|---|---|
| Dériver de la famille B | **Impossible en volume.** 2000 clients hors d'atteinte. |
| Inventer un montant | **Interdit par le CDC lui-même** : « sans invention arbitraire de montants ». |
| Dériver de ce que la famille A **porte réellement** | **Retenue** — voir ci-dessous. |

La famille A porte un profil socio-économique exploitable : la régularité
d'usage (`IS_RGS_1/7/30/90`), l'usage data (`IS_DATA_RGS*`), l'équipement
(`IS_SMARTPHONE_USER`), la dernière activité (`LAST_EVENT_DATE`,
`LAST_EVENT_TYPE`). Un solde initial calculé comme **fonction déterministe et
documentée de ces 11 champs**, borné par les strates de l'Annexe E, honore
l'intention écrite du CDC — « un patrimoine cohérent avec son profil
socio-économique » — là où son champ littéral est hors d'atteinte.

Déterministe : le même `client_id` doit rendre le même solde (`ENF-15`).
Documentée : la fonction est lisible, pas un tirage aléatoire déguisé — c'est
exactement ce que « sans invention arbitraire » interdit.

**Ouvre l'arbitrage `A-09`.** Ce document ne tranche pas : il mesure, et il pose
la seule voie qui ne contredise ni le volume exigé ni l'interdit du CDC.

---

*13 appels en lecture seule, le 11 août 2026. Chaque ligne des tableaux est
reproductible en variant le jeu de paramètres.*
