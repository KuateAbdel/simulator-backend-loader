# config-service — état réel de la base, 9 août 2026

| | |
|---|---|
| **Motif** | Avant d'écrire quoi que ce soit, savoir **ce qui existe déjà**. Le référentiel a été chargé le 30/07 par `loader_config_service.py`. Duplique-t-on ? |
| **Méthode** | Inventaire complet en lecture seule, puis **comparaison ligne à ligne** avec `Loader_Base_FinZuu_v1_1.xlsx`. |
| **Résultat** | **Aucune duplication à craindre.** Mais **6 entrées parasites sur 24**, et une chaîne référentielle **rompue**. |

---

## 1. ✅ Les 12 opérateurs sont déjà en base — **à l'identique**

```
12 identiques · 0 divergents · 0 absents
```

Les `phone_regex` du serveur sont **strictement égaux** à ceux de notre référentiel, opérateur par opérateur. C'est la preuve que le chargement du 30/07 a bien pris sa source dans `Loader_Base`.

> **Conséquence pour le Loader** : il ne recrée **rien**. `GET`-avant-`POST` sur les
> trois entités de config-service, et réutilisation de ce qui existe — exactement
> la discipline déjà appliquée aux 2 produits COLLECT préexistants (`D-PRD-9`).

---

## 2. 🔴 Six entrées parasites sur vingt-quatre

### Devises — 2 sur 4 sont des déchets

| `iso_name` | `name_fr` | Verdict |
|---|---|---|
| `XAF` | Franc CFA (BEAC) | ✅ |
| `XOF` | Franc CFA (BCEAO) | ✅ |
| **`cv`** | **`CD`** | ❌ déchet de test, **actif** |
| **`00`** | **`00`** | ❌ déchet de test, **actif** |

Déjà documenté — `ANO-CFG-CUR-10`, recommandation n°3 de `FRA-222`. **Toujours présent.**

### Pays — 2 sur 6 sont des déchets

| `iso_name` | `name_fr` | `dial_code` | Verdict |
|---|---|---|---|
| `CM` `CI` `BF` `SN` | Cameroun, Côte d'Ivoire, Burkina Faso, Sénégal | 237, 225, 226, 221 | ✅ |
| **`CV`** | **`cm`** | *(vide)* | ❌ actif |
| **`ca`** | **`cmer`** | *(vide)* | ❌ inactif, code en minuscules |

### Opérateurs — 2 sur 14 sont des déchets, dont un **dangereux**

| Nom | `phone_regex` | Verdict |
|---|---|---|
| **`MTNcongo1`** | **`6\|333`** | 🔴 **regex sans ancres** |
| **`cm`** | `^221(70\d{7})$` | ❌ **doublon exact d'Expresso Senegal** |

> 🔴 **`6|333` est le plus grave des six.** Sans `^` ni `$`, ce motif accepte
> **toute chaîne contenant un `6` ou la séquence `333`** — c'est-à-dire la quasi-
> totalité des numéros de téléphone du monde. Un système qui validerait un MSISDN
> contre ce regex laisserait **tout** passer. Ce n'est pas un déchet cosmétique :
> c'est une validation qui ne valide rien, sous une apparence de contrôle.

---

## 3. 🔴 La chaîne **pays → devise n'existe pas** côté serveur

| Pays | `currency` côté serveur | Ce que le référentiel dit |
|---|---|---|
| CM | **`None`** | `XAF` (zone CEMAC, BEAC) |
| CI | **`None`** | `XOF` (zone UEMOA, BCEAO) |
| BF | **`None`** | `XOF` |
| SN | **`None`** | `XOF` |

**Les quatre pays légitimes n'ont aucune devise rattachée**, alors que leur
`dial_code` est correctement renseigné et que leurs opérateurs sont bien liés
(3 chacun). Le lien pays → devise a été perdu au chargement, ou n'a jamais été
posé.

**Conséquence directe** : rien, côté serveur, ne permet de savoir qu'un client
camerounais doit être en `XAF`. C'est exactement ce que `FRA-222` a rendu visible
en aval — un compte client porteur de `currency="ANY"`.

> **Notre référentiel est donc la seule source où la chaîne
> `pays → devise → opérateur → région → ville → quartier` est complète et
> vérifiée.** Ce n'est pas une redondance de confort : c'est la seule
> matérialisation existante de cette cohérence.

---

## 4. Ce que le Loader en fait

| Constat | Décision |
|---|---|
| 12 opérateurs déjà présents, identiques | **Réutilisés**, jamais recréés (`GET`-avant-`POST`) |
| 2 devises légitimes présentes | **Réutilisées** |
| 4 pays légitimes présents | **Réutilisés** |
| 6 entrées parasites | **Ignorées à la lecture, jamais supprimées** — la purge d'un référentiel partagé n'est pas notre rôle |
| `Country.currency = None` | **Le Loader ne s'y fie pas** : la devise vient de notre référentiel (`devise_du_pays`) |
| `MTNcongo1` avec `6\|333` | **Jamais utilisé pour valider** — nos 12 motifs sont ancrés et vérifiés au chargement |

**Le Loader ne répare pas config-service.** Il constate, journalise, et reste
cohérent chez lui.

---

## 5. Anomalies à ticketer

| Code | Constat | Gravité |
|---|---|---|
| **`ANO-CFG-TELCO-01`** | `MTNcongo1` porte le regex **`6\|333`**, sans ancres — accepte quasiment tout numéro. Validation en apparence, aucune en réalité. | 🔴 **HAUTE** |
| **`ANO-CFG-COUNTRY-02`** | **Aucun des 4 pays n'a de devise rattachée** (`currency: null`) — la chaîne pays → devise est rompue à la racine | 🟠 moyenne |
| `ANO-CFG-TELCO-03` | Opérateur `cm` : doublon exact d'Expresso Senegal | 🟡 basse |
| `ANO-CFG-COUNTRY-04` | Pays parasites `CV` (`name_fr: "cm"`) et `ca` (`name_fr: "cmer"`) | 🟡 basse |
| `ANO-CFG-CUR-10` | Devises parasites `cv` et `00` — **déjà signalé dans `FRA-222`, toujours présent** | 🟡 basse |

---

*Inventaire exécuté en lecture seule le 9 août 2026 par Kuate Abdel Yaniv
(SDET/QA Lead). Aucune écriture, aucune suppression.*
