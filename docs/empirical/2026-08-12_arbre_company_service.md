# company-service — l'arbre de Companies, mesuré de bout en bout

> Campagne du **12/08/2026**, demandée par Yaniv : *« teste de bout en bout la
> création d'un arbre, pour être sûr et certain, et comprends comment le service
> se comporte. »*
>
> **Tout ce qui suit est mesuré.** Aucune affirmation ne vient du contrat seul, ni
> d'une page Confluence. Coût de la campagne : **4 Companies `PROBE_*`
> irréversibles** — company-service n'expose aucun `DELETE`.

---

## 1. Verdict : l'arbre fonctionne, sur trois niveaux au moins

```
n1  PROBE_FIL1786556253_MERE            IMF     parent = null
     └─ n2  PROBE_ISO1786556417_...     IMF     parent = n1
             └─ n3  PROBE_ARB1786557557_NIVEAU3   KIOSK   parent = n2
```

Trois créations, **trois HTTP 201**. Le lien parent-filiale est pleinement
opérationnel.

---

## 2. L'asymétrie du champ — à ne jamais oublier

| Sens | Champ | Forme |
|---|---|---|
| **écriture** | `company_id` | une chaîne — l'identifiant du parent |
| **lecture** | `parent` | **l'objet Company parent ENTIER**, imbriqué |

On envoie `company_id`, on reçoit `parent`. Une relecture naïve qui chercherait
`company_id` dans la réponse trouverait **toujours `None`** — et concluerait à
tort que le lien n'a pas pris.

> C'est exactement le piège qui m'a fait dire, en début de campagne, que « 0 des 8
> Companies a un parent » : je lisais `company_id` sur des fiches qui portent
> `parent`.

---

## 3. La récursion est COMPLÈTE, et c'est le fait le plus lourd

La fiche du niveau 3 contient son parent, **qui contient son propre parent** :

```
n3.parent.name        = PROBE_ISO..._IMFAVECPARENT
n3.parent.parent.name = PROBE_FIL..._MERE
```

**Mesure de la charge :**

| Fiche | Taille |
|---|---:|
| sans parent | **1 386** caractères |
| avec 2 ancêtres | **4 043** caractères |

**×2,9 pour deux niveaux** — chaque niveau triple à peu près la fiche, parce que
chaque ancêtre embarque son `owner` (16 champs) et son `address` (10 champs).

**Extrapolation** : un arbre à quatre niveaux (IMF → Branche → Agence → Kiosque)
produirait des fiches de l'ordre de **12 000 caractères**. Et `GET /companies/`
les rend **toutes**, à chaque appel.

---

## 4. Les licences suivent l'arbre

| Niveau | Type | Licence | Lues en base |
|---|---|---|---:|
| n1 | IMF | ✅ créée | 1 |
| n2 | IMF (enfant) | ✅ créée | 1 |
| n3 | **KIOSK** | ✅ créée | 1 |

Aucune contrainte : une filiale porte sa propre licence, y compris un `KIOSK`.
`GET /licenses/company/{id}` la retrouve.

---

## 5. Ce que le service NE SAIT PAS faire

### 5.1 Retrouver les filiales d'un parent — impossible

`SearchRequestSchema` n'offre que **trois** critères : `name`, `short_name`,
`type`. **Aucun critère `parent`.** Et il n'existe aucune route
`/companies/{id}/children`.

Retrouver les enfants d'une Company exige donc un **balayage complet de la
collection paginée, puis un filtre local** sur `parent._id`. C'est la même famille
que `P-01` — le système ne stocke jamais l'index inverse.

### 5.2 Supprimer — impossible

Neuf opérations sur les Companies, **aucun `DELETE`**. Seulement
`PATCH /activate` et `PATCH /deactivate`. Toute Company créée est définitive.

### 5.3 `GET /companies/{company_name}` — route morte

Déclarée dans l'OpenAPI, elle partage le motif de
`GET /companies/{company_id}`. Mesure : elle rend **`[]`**, jamais la Company.
FastAPI résout par ordre de déclaration, et `{company_id}` gagne.
(`ANO-CPY-ROUTE-01`, confirmé.)

---

## 6. Deux anomalies serveur trouvées — et elles ne nous touchent pas

**Je les signale sans dramatiser** : notre client évite déjà les deux routes.

### 6.1 `POST /search` par `short_name` seul → **HTTP 500**

```
{"status_code":500,"description":"Une erreur interne s'est produite",
 "data":"decoding to str: need a bytes-like object, NoneType found"}
```

`short_name` est pourtant un critère **déclaré** du schéma. `{"type": "IMF"}` et
`{"name": "..."}` fonctionnent ; `short_name` seul plante.

> **Sans impact chez nous** : `chercher_par_short_name()` ne passe pas par
> `/search`. Elle liste et filtre localement, précisément parce que la route par
> nom est morte. Le contournement adopté pour un défaut nous en évite un second.

### 6.2 `paginate.last_page` est faux sur `/search`

| Endpoint | `total` | `per_page` | `last_page` | Attendu |
|---|---:|---:|---:|---:|
| `GET /companies/` | 11 | 10 | 2 | 2 ✅ |
| `GET /companies/?limit=100` | 11 | 100 | 1 | 1 ✅ |
| `POST /search {"type":"IMF"}` | 3 | 10 | **2** | **1** ❌ |
| `POST /search {"name":"..."}` | 1 | 10 | **2** | **1** ❌ |

Correct sur la liste, faux sur la recherche. Or `base.py:590` fait de
`last_page` la **borne du parcours** — une boucle sur `/search` irait chercher une
page 2 fantôme.

> **Sans impact chez nous** : nous ne paginons que `GET /companies/`.

---

## 7. Mes deux erreurs de sonde, et je les assume

Un rapport de QA qui n'attribue pas ses propres fautes ne vaut rien.

**7.1 Téléphone partagé.** Mon premier essai donnait le même numéro aux deux
dirigeants → `400 : Identity with this phone number already exists`. **Invariant
légitime du service, faute de ma sonde.** Le téléphone d'une Identity est unique
à l'échelle du système.

**7.2 J'ai failli déclarer un bug qui n'existait pas.** Le second échec —
`'NoneType' object has no attribute 'email'` — ressemblait trait pour trait à
`ANO-CPY-BUG-06`, déclaré corrigé le 08/08. **J'ai isolé la variable avant de
conclure**, et j'ai eu raison : `AGENCY` sans parent passe en 201, `IMF` avec
parent passe en 201. Ni le type ni le parent ne posent problème. L'échec venait de
mon propre enchaînement.

J'ai aussi vérifié le piège `FRA-195` — *rejet apparent, mutation réelle* : il ne
s'applique pas ici. Le 400 était un vrai refus, aucune Company fantôme.

**7.3 `date` non sérialisable.** `creer_licence` attend des chaînes ISO, pas des
objets `date`. Ma faute encore.

---

## 8. Ce que la filiale EST, exactement

> *« La filiale, c'est quoi ? Un truc qu'on déroule ? Ou un champ qu'on entre ? »*

**C'est UN champ, et un seul** : `company_id`, posé à la création. Il n'y a aucune
structure séparée, aucune table de hiérarchie, aucun endpoint dédié.

Le « déroulé » n'existe **qu'en lecture** : le serveur reconstitue et imbrique
toute la chaîne ascendante dans la réponse. Vers le haut seulement — jamais vers
le bas.

| | Sens | Coût |
|---|---|---|
| **vers le haut** | automatique, imbriqué, récursif | la fiche triple par niveau |
| **vers le bas** | **inexistant** | balayage complet + filtre local |

---

## 9. Les impacts sur le Loader — ce que cette campagne change

### 9.1 Ce qui est confirmé

Notre modèle fait porter la hiérarchie par l'**IMF** : c'est son `company_id` que
chaque Dépositaire référence. Les `BANK`, `MERCHANT` et `FONDATION` sont
indépendantes et ne portent rien. **Cette lecture est juste**, et le service la
permet sans réserve.

### 9.2 Ce qui doit être corrigé dans nos décisions

`D-05` justifiait de ne pas persister Branche et Agence ainsi : *« company-service
n'expose aucune route pour elles, et son enum `CompanyType` ne comporte aucune
valeur BRANCH »*.

**C'est exact pour `BRANCH`, et faux pour Agence et Kiosque** :
`CompanyType = ['MERCHANT','BANK','IMF','AGENCY','KIOSK','FUNDING_PROVIDER','FONDATION']`.
Et `UC-07` ligne 86 les nomme lui-même parmi les types.

La vraie justification est **triple**, et aucune n'est une impossibilité
technique :

1. **La volumétrie.** `UC-07` fixe « entre 3 et 5 Companies par pays », soit 12 à
   20. `UC-09` exige 40 à 80 Kiosques. On ne met pas 80 Kiosques dans un budget de
   20 Companies.
2. **La duplication.** Un Kiosque **existe déjà** côté serveur, comme
   **Dépositaire** porteur de `company_id`. En faire aussi une Company le
   créerait **deux fois**, dans deux services, sans lien entre les deux. C'est
   l'argument le plus fort, et il est neuf.
3. **Le coût de lecture.** Mesuré au §3 : chaque niveau triple la fiche. Un arbre
   à quatre niveaux rendrait `GET /companies/` illisible.

> **Ce qui reste ouvert** : `parent_company_id` est accepté par notre client et
> **aucun appelant ne le passe**. Il faut soit l'employer, soit écrire la décision
> de ne pas l'employer. Un paramètre mort dans un client est une invitation au
> défaut.

### 9.3 Le `PUT` est notre seul outil de réparation

`UpdateCompanySchema` exige **7 champs** : c'est un **remplacement complet**, pas
un patch. Un `PUT` partiel écrase le nom, le type, le dirigeant, l'adresse.

Mais il n'y a **aucun `DELETE`**. Donc si une Company porte une valeur fausse, le
`PUT` est **la seule voie de correction**. Et le cas existe déjà en base :

```
DEMO_QA0808_SARL Tamadou Textile
    industries = ["MicroFinance"]   ← c'est un SECTEUR, pas une industrie
    sectors    = ["Textile"]        ← et Textile n'a aucun rapport avec MicroFinance
```

**Décision** : jamais dans le flux de création ; uniquement en réparation
délibérée, en renvoyant les 7 champs **relus depuis la fiche existante**.

---

## 10. Le tableau de bord de company-service

| Fait | Mesuré |
|---|---|
| opérations | **14** sur 10 chemins — 9 sur `companies`, 5 sur `licenses` |
| `DELETE` | **aucun** |
| cascade d'une création | **4 services** : company, identity, account, user |
| parent-filiale | ✅ opérationnel, ≥ 3 niveaux |
| lecture du parent | récursive et complète, ×2,9 par niveau |
| lecture des enfants | **impossible** — balayage + filtre |
| critères de recherche | 3 : `name`, `short_name`, `type` |
| `search` par `short_name` | **HTTP 500** |
| `paginate.last_page` sur `search` | **faux** |
| `GET /companies/{name}` | **route morte** |
| `PUT` | remplacement complet, 7 champs requis |
| unicité du téléphone d'Identity | **globale**, tous services confondus |

---

## Traces laissées en base — irréversibles

| Nom | Type | Parent | Motif |
|---|---|---|---|
| `PROBE_FIL1786556253_MERE` | IMF | — | racine de l'arbre |
| `PROBE_ISO1786556417_AGENCYSANSPARENT` | AGENCY | — | isoler le type du parent |
| `PROBE_ISO1786556417_IMFAVECPARENT` | IMF | MERE | niveau 2 |
| `PROBE_ARB1786557557_NIVEAU3` | KIOSK | IMFAVECPARENT | niveau 3 |

Toutes préfixées `PROBE_`, toutes avec une licence `ALL`. Elles documentent la
campagne ; elles ne doivent pas être reproduites.
