# Plan d'intégration — les référentiels statiques de JJB

> Écrit le 12/08/2026. Source : `1_Static_Data.zip`, transmis par Yaniv, produit
> par JJ Bwanga. Copié dans `docs/reference/static_data/`.
>
> **Nature de l'opération : ADDITIVE.** Aucune exigence n'est retirée, aucun
> chemin d'écriture n'est modifié dans sa forme. Ce qui change est la **matière**
> que le Loader compose — plus riche, mieux ancrée. Les 745 tests actuels sont la
> ligne de flottaison : aucun ne doit tomber sans raison écrite.

---

## 0. La doctrine, et pourquoi elle est déjà prouvée

> *« Le serveur n'a pas de table de secteurs — nous portons 6 industries, 112
> secteurs, 576 professions. Le Loader est le référentiel ; le serveur ne reçoit
> que ce qu'il sait recevoir. »*

Ce n'est pas un nouveau principe : c'est **exactement** ce que nous faisons déjà
pour la géographie. config-service ne porte ni région, ni ville, ni quartier ;
`Loader_Base_FinZuu_v1_1.xlsx` en porte **51 régions, 50 villes, 82 quartiers**,
et le Loader n'envoie au serveur que les champs que ses contrats acceptent.

Le patron est donc connu, testé, et il tient depuis le Sprint 1 :

```
REFERENTIEL INTERNE (riche, cohérent, versionné)
        │
        ├── ce que le contrat serveur accepte  ──► HTTP FinZuu
        └── ce qu'il n'accepte pas             ──► notre MongoDB (trace)
```

---

## 1. Ce que contient le zip — inventaire mesuré

| Fichier | Contenu mesuré |
|---|---|
| `final_company_Industry-Sector.json` | **27** formes juridiques · **6** industries (id + label) · **112** secteurs avec `industry_ids` — relation **n:n**, 28 secteurs multi-industries |
| `Occupation.json` | **21** groupes · **576** professions · **4** profils de revenu lognormaux (μ, σ) · `classification_priority` (5 niveaux) · `employment_status_rules` (10 statuts) · 38 alias |
| `Lieu2Nationalite.csv` | **195** pays, colonnes `Country_EN` / `Pays_FR` |
| `Fonction_Compagnie_Dirigeants.csv` | **20** fonctions de dirigeant — FR, EN, abréviation |

### Les quatre profils de revenu

| Profil | μ | σ | Médiane implicite |
|---|---:|---:|---:|
| `bank_stable` | 12,15 | 0,28 | **189 094 FCFA** |
| `sme_formal` | 12,05 | 0,40 | **171 099** |
| `micro_informal` | 11,65 | 0,55 | **114 691** |
| `agri_seasonal` | 11,50 | 0,70 | **98 716** |

**140 professions agricoles** (Agronomy 69 · Livestock 33 · Fishing 20 ·
Forestry 18) — de quoi servir `EF-24` avec de la matière réelle.

---

## 2. L'état actuel, mesuré — ce que ces fichiers remplacent

| Ce que nous faisons aujourd'hui | Mesure |
|---|---|
| `OCCUPATIONS_PAR_SECTEUR` | **18 métiers** sur 4 familles CDC |
| `identity.occupation` par défaut | `"Commercant"` en dur |
| `industries` et `sectors` de la Company | **la même valeur dans les deux champs** (`organisation_execution.py:355-356`) |
| secteur d'une Fondation | **`""`** — chaîne vide, qui passe `minItems: 1` sans rien signifier |
| formes juridiques | celles de Faker (6) |
| occupation du dirigeant | `"Dirigeant"` en dur |
| `solde_initial` (`A-09`) | dérivé de 9 signaux `quick_win` — une **heuristique** |
| `id_place` | la ville de **résidence** |

**Trois de ces lignes sont des défauts que je connaissais et n'avais pas de quoi
corriger.** Le fichier apporte la matière qui manquait.

---

## 3. Ce qui NE DOIT PAS casser — les garanties à préserver

C'est la partie la plus importante du plan. Chaque garantie ci-dessous est
aujourd'hui tenue et mesurée ; elle doit l'être encore après.

| Garantie | Comment elle est vérifiée aujourd'hui | Risque de l'intégration |
|---|---|---|
| **`EF-24`** 20 % des professionnels en agriculture | `Agri 20/20` sur 4 pays | **élevé** — remplacer 18 métiers par 576 casse le lien avec les 4 familles CDC si on ne le reconstruit pas |
| **`EF-22`/`EF-23`** quotas genre, âge, catégorie | `Corp 100/100 · Femmes 333/333 · <25ans 300/300` | faible — indépendants de l'occupation |
| **`CR-09`** distribution comportementale | 50,0/25,0/13,0/12,0 exact | **moyen** — si `solde_initial` change, `EF-68` pèse un Mobile Money différent |
| **`EF-25`/`INV-09`** unicité | 2000/2000 distincts | nul |
| **`CR-03`** idempotence | msisdn identiques entre deux runs | **moyen** — toute nouvelle valeur doit être ancrée au CLIENT, jamais au run |
| **`INV-CPY-03/04`** `minItems: 1` | garde avant réseau | faible — le fichier ne fournit que des labels non vides |
| **745 tests** | suite verte | à surveiller lot par lot |

### La règle d'or du chantier

> **Le vocabulaire du CDC reste le contrat ; le fichier n'est que la matière.**

Les quatre familles `AGRICULTURE / TRANSPORTS / COMMERCE / SERVICES` sont citées
par `EF-24`. Elles **ne disparaissent pas**. On construit une **table de
correspondance** des 21 groupes vers ces 4 familles :

| Famille CDC | Groupes d'`Occupation.json` | Professions |
|---|---|---:|
| `AGRICULTURE` | Agronomy · Livestock · Fishing · Forestry | **140** |
| `TRANSPORTS` | Informal transport and logistics | 27 |
| `COMMERCE` | Informal commerce and street trade · Formal trade, hospitality | 63 |
| `SERVICES` | les 14 groupes restants | ~346 |

C'est la couche anti-corruption appliquée une fois de plus : **conformiste sur le
vocabulaire du CDC, enrichi sur la matière.**

---

## 4. Comment ça se passe, concrètement — six lots

### Lot 1 · Le chargeur, et lui seul

**Un module `app/services/referentiel_statique.py`**, sur le modèle exact de
`charger_referentiel()` : lecture au démarrage, validation stricte, échec bruyant.

```
charger_statique(chemin) -> ReferentielStatique
    .industries          6 · id -> label
    .secteurs            112 · label -> [industries]
    .formes_juridiques   27
    .professions         576 · label -> (groupe, profil de revenu)
    .groupes             21 · secteur -> (profil, professions)
    .profils_revenu      4 · nom -> (mu, sigma, definition)
    .pays                195 · EN <-> FR
    .fonctions_dirigeant 20 · FR, EN, abréviation
```

**Ce lot n'appelle rien et ne change aucun comportement.** Il charge, il valide,
il expose. Tests : les comptes exacts (6/112/27/576/21/4/195/20), la cohérence
des `industry_ids` (aucun orphelin), l'absence de label vide.

> **Pourquoi d'abord et seul** : si le chargeur est faux, tout ce qui suit est
> faux. Et il est mesurable sans toucher à une seule ligne d'exécution.

### Lot 2 · Les Companies — `industries` ≠ `sectors`

Le plus petit gain visible, et le plus rapide.

- `_profil_company` rend désormais un **secteur du fichier** et **son industrie**
- `industries=[industrie]`, `sectors=[secteur]` — deux axes, plus un doublon
- la Fondation cesse d'avoir un secteur vide : `NGO` ou `Charity`
- les 27 formes juridiques deviennent disponibles (`GIE`, `SCOP`, `ONG` sont
  pertinentes en zone UEMOA/CEMAC)

**Correspondance des 4 types serveur** :

| `CompanyType` | Secteur | Industrie | Forme |
|---|---|---|---|
| `IMF` | `MicroFinance` | Finance & Insurance | SARL |
| `BANK` | `Banking` | Finance & Insurance | SA |
| `MERCHANT` | tiré parmi Commerce | Commerce | SA / SARL / GIE |
| `FONDATION` | `NGO` ou `Charity` | Commerce | ONG / Charity |

`MicroFinance` et `Banking` **existent déjà** dans le fichier — la concordance
avec `_profil_company` est confirmée, pas forcée.

**Ne casse pas** : la raison sociale, les licences, la hiérarchie. Le champ
`secteur` sert aussi à `raison_sociale()`, donc les noms changeront — attendu, et
les tests de nom devront le refléter.

### Lot 3 · Les occupations des clients — 18 → 576

- `OCCUPATIONS_PAR_SECTEUR` devient une **vue** sur le référentiel, via la table
  de correspondance du §3
- l'occupation est tirée **ancrée au client** (`CR-03`)
- le défaut `"Commercant"` disparaît : il y a toujours une profession du groupe

**Ne casse pas `EF-24`** : la famille reste décidée par le quota, seule la
profession concrète change. `Agri 20/20` doit rester exact — c'est le test qui
juge.

### Lot 4 · Le dirigeant — `"Dirigeant"` → 20 fonctions

Trivial, et il enlève une valeur en dur. La fonction est tirée ancrée sur la
Company. `PDG / CEO` pour l'IMF racine, le reste réparti.

### Lot 5 · `solde_initial` — de l'heuristique au modèle documenté

**Le lot le plus délicat, et il vient en dernier des lots de fond.**

Aujourd'hui : 9 signaux `quick_win` → 10 strates → un montant borné par
l'Annexe E. C'était la recommandation `A-09`, assumée comme un pis-aller parce
que `MOB_MONEY_ACCOUNT_AMOUNT` est absent de la famille A.

Demain : `profession → groupe → profil de revenu → LogNormal(μ, σ)`.

**Deux garde-fous obligatoires :**

1. **Les bornes de l'Annexe E restent.** Le tirage lognormal est **borné** par
   `SOLDE_INITIAL_MIN` / `SOLDE_INITIAL_MAX`. Une queue lognormale peut sortir
   des millions ; le CDC borne, donc on borne.
2. **`EF-68` en dépend.** Le profil comportemental pèse
   `MOB_MONEY_ACCOUNT_AMOUNT` au seuil de 150 000 FCFA. Changer la distribution
   des soldes **déplace** ce seuil dans la population. `CR-09` reste exact par
   quota, mais la mesure `EF-68` doit être **refaite** et rester dans le bon sens.

> **`A-09` devient un arbitrage FERMÉ.** Le CDC interdit « l'invention arbitraire
> de montants » ; avec un modèle de revenu documenté par profession, il n'y a plus
> d'invention. C'est le gain le plus important de tout le chantier.

### Lot 6 · Le lieu de naissance — tâche #15

`Lieu2Nationalite.csv` donne 195 pays. Combiné aux 50 villes de `Loader_Base` :

- majorité né dans une ville **du pays**, différente de la résidence (migration
  interne réelle)
- une minorité née à l'étranger, avec une nationalité cohérente
- `id_place` cesse d'être la ville de résidence

**Ne casse pas** `valider_coherence_territoriale` : la pièce reste délivrée dans
un lieu cohérent avec la nationalité.

---

## 5. L'ordre, et pourquoi celui-là

```
Lot 1  chargeur                      ── aucun impact, tout en dépend
Lot 2  Companies                     ── avant le PALIER 2 (ORGANISATION)
Lot 3  occupations clients           ── avant le PALIER 6 (CLIENTS)
Lot 4  dirigeants                    ── avec le lot 2
Lot 5  solde_initial                 ── ferme A-09 ; refaire la mesure EF-68
Lot 6  lieu de naissance             ── tâche #15, indépendant
```

**Contrainte dure** : les lots 2 et 4 doivent être terminés **avant** le palier 2,
et le lot 3 **avant** le palier 6. Créer une Company avec un secteur vide, ou
2000 clients tous « Commerçant », serait **irréversible** — company-service et
client-service n'ont aucun `DELETE`.

**Ce qui reste ouvert** : le palier 2 attend aussi tes décisions sur le catalogue
(noms métier, marqueur `short_name`). Les deux chantiers convergent là.

---

## 6. Le protocole de non-régression, lot par lot

À chaque lot, dans cet ordre, sans exception :

1. `ruff` + `mypy` propres
2. **suite complète verte** — un test qui tombe est examiné, jamais contourné
3. **mesure ciblée** du lot (les comptes, la distribution, la cohérence)
4. **DRY_RUN complet** — 2000/2000, quotas exacts, `ENF-01` tenu
5. **mutations** sur chaque garantie nouvelle : si la casser ne fait rien
   échouer, le test manque
6. commit avec la mesure dans le message

> **Le DRY_RUN est le juge final.** C'est « la dernière occasion de dire non »
> (`D-01`), et trois services n'ont aucun `DELETE`.

---

## 7. Ce que ça change pour la démonstration

| | Avant | Après |
|---|---|---|
| professions distinctes | **18** | **576** |
| secteurs de Company | 4 labels, dupliqués dans `industries` | **112** secteurs × **6** industries, distincts |
| formes juridiques | 6 | **27** |
| fonctions de dirigeant | 1, en dur | **20** |
| base du solde initial | heuristique `quick_win` | **modèle de revenu par profession** |
| lieu de naissance | = ville de résidence | ville réelle, parfois étrangère |

Un bailleur qui ouvre la liste des 2000 clients ne verra plus dix-huit métiers
répétés cent fois. Il verra une population.

---

## Sources

`docs/reference/static_data/` — `1_Static_Data.zip`,
`final_company_Industry-Sector.json`, `Occupation.json`, `Lieu2Nationalite.csv`,
`Fonction_Compagnie_Dirigeants.csv` · produits par JJ Bwanga, transmis le
12/08/2026 · CDC v1.2 `EF-24`, `EF-10`, `INV-CPY-03/04`, Annexe E ·
`docs/DECISIONS.md` (`A-09`) · `app/services/geographie.py` (le patron du
chargeur) · mesures du 12/08 sur `organisation_execution.py:355`,
`clients_composition.py:172`, `clients_execution.py` (`solde_initial`)
