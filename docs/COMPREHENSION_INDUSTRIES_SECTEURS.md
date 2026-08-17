# Industries & Secteurs — la compréhension totale

> Ce document fige ce que nous avons établi sur le fonctionnement des industries
> et des secteurs dans le Loader : leur structure, leur convention, et surtout
> **le chemin qu'une entrée doit traverser pour compter vraiment** (référence →
> génération → plateforme). À relire avant toute évolution du référentiel ou du
> moteur. Il complète, sans les remplacer, les docstrings de
> `referentiel_statique.py`, `surcouche_referentiel.py` et
> `organisation_execution.py`.

---

## 1. Deux niveaux — et une confusion de vocabulaire normée

Le référentiel a **deux niveaux**, du plus large au plus fin :

- **Industrie** — le niveau HAUT. **6** industries : Finance & Insurance,
  Agriculture, Commerce, Logistic & Transport, Technology, Energy.
- **Secteur** — le niveau FIN, **sous** les industries. **112** secteurs.

**Le vocabulaire n'est PAS universel** — deux standards mondiaux s'inversent :

| Standard | Utilisé par | Ordre large → fin |
|---|---|---|
| **GICS** | S&P, MSCI, Bloomberg, Google Finance | **Secteur** → Industry Group → **Industrie** |
| **ICB / ISIC / NACE** | FTSE, LSEG, INSEE, ONU | **Industrie** → Secteur → Sous-secteur |

**La donnée de JJB tranche : convention ICB.** Dans
`final_company_Industry-Sector.json`, chaque secteur porte des `industry_ids`
qui pointent **vers le haut**. Donc chez nous : **l'industrie est le parent
(6, large), le secteur est l'enfant (112, fin).** On suit la donnée, on ne
l'inverse pas.

---

## 2. La relation est n:n — PAS un arbre

Ce n'est pas « 1 industrie → N secteurs » proprement. C'est **n:n** : **28
secteurs sur 112 appartiennent à ≥2 industries** (ex. `Fintech` = Finance ET
Technology ; `Consulting` = 5 industries).

Conséquence : **on ne représente jamais ça en arbre déroulant** — un secteur-pont
y apparaîtrait deux fois, les compteurs mentiraient. On le modélise en
**facettes / graphe** : les secteurs sont les atomes, les industries des
filtres/hubs. C'est ce que fait l'écran (constellation force-directed).

Répartition (nb de secteurs par industrie, ponts compris) : Commerce 64 ·
Technology 32 · Finance & Insurance 14 · Agriculture 12 · Energy 11 ·
Logistic & Transport 10.

---

## 3. Une entreprise a UNE industrie principale

Un secteur peut être multi-industries, mais **une Company se classe par UNE
activité principale** (logique NACE/ISIC). Donc :

- `ReferentielStatique.industrie_du_secteur(secteur)` rend **une seule**
  industrie : **la première par ordre alphabétique** parmi celles du secteur.
- Arbitraire mais **STABLE** → reproductible (`ENF-15`).
- Rendre l'**union** produirait des absurdités — mesuré : une fondation
  caritative tombait en « Technology » parce que `Health` ∈ {Commerce, Technology}.

---

## 4. LE point d'architecture : taxonomie ≠ profils de génération

C'est la clé, et elle est contre-intuitive. **Deux choses distinctes et
découplées :**

1. **La taxonomie** (`referentiel_statique`) : *quel secteur appartient à quelle
   industrie.* 112 secteurs, leurs `industry_ids`. C'est de la **donnée**.
2. **Les profils de génération** (`SECTEURS_PAR_TYPE`, dans
   `organisation_execution.py`) : *quels secteurs vont ensemble pour un type
   d'entreprise.* C'est de la **connaissance MÉTIER, DÉCLARÉE, pas calculée.**

```
SECTEURS_PAR_TYPE = {
  IMF:              ("MicroFinance", ("Lender", "Consulting", "Insurance")),
  BANK:             ("Banking",      ("Investment", "Brokerage", "Insurance")),
  MERCHANT:         ("Retail",       ("Wholesale", "Distribution", "Import Export")),
  FONDATION:        ("NGO",          ("Charity", "Education", "Health")),
  FUNDING_PROVIDER: ("Investment",   ("Lender", "Insurance")),
}
```

**Pourquoi déclaré et non calculé** (mesuré le 12/08) : tirer les connexes parmi
tous les secteurs de la même industrie produit `sectors=['Retail','NGO']` (un
commerçant qui est une ONG) ou `['MicroFinance','Cryptocurrency']` (une IMF dans
la crypto). *Le fichier dit quelle industrie ; il ne dit PAS quels secteurs vont
ensemble pour une IMF.* Cette connaissance n'est pas dans les données.

**Conséquence directe** : ajouter un secteur à la taxonomie ne le rend PAS
automatiquement « générable ». Il faut aussi **déclarer à quel(s) type(s)
d'entreprise il s'applique**.

---

## 5. Les trois couches qu'une entrée doit traverser pour COMPTER

Un Loader génère des entités et les pousse dans FinZuu. Une entrée n'est réelle
que si elle passe les trois :

| Couche | Ce qu'elle exige | Où |
|---|---|---|
| **1. Identité** | le label + son industrie | `referentiel_statique` / surcouche |
| **2. Intention de génération** | à quel type d'entreprise le secteur est un **connexe** | `SECTEURS_PAR_TYPE` (base) ⊕ `secteurs_types` (surcouche) |
| **3. Acceptation plateforme** | company-service accepte le `sectors` envoyé | contrat serveur — **chaînes libres** (`array of string, minItems 1`) |

La couche 3 est acquise : `CreateCompanySchema.industries` et `.sectors` sont des
**chaînes libres** côté plateforme. Donc un secteur ajouté **sera accepté** en
aval. Le maillon qui manquait était la **couche 2**.

---

## 6. Base immuable + surcouche = référentiel effectif

- **Le fichier de JJB (SD-1) est IMMUABLE.** On ne l'édite jamais ; il se
  remplace par livraison de fichier versionnée. Les comptes 6/112/27/576/… sont
  vérifiés par des tests.
- **Les ajouts du Super-Admin vivent dans une SURCOUCHE** (`surcouche_referentiel`,
  document Mongo `_id="surcouche"`) — réversible, tracée, même patron que les
  villes (US-B4) et telcos (US-B7).
- **Le référentiel EFFECTIF = base ⊕ surcouche.** C'est LUI, pas la base seule,
  que le run consomme :

  ```python
  statique = referentiel_effectif(
      charger_statique(),
      secteurs_ajoutes=dict(surcouche.secteurs),
      industries_ajoutees=list(surcouche.industries_ajoutees),
  )
  ```

  L'immuabilité porte sur le **fichier**, jamais sur le référentiel *de run* qui
  est **composé**. `referentiel_effectif` rend une COPIE (l'original frozen reste
  intact), et `industrie_du_secteur` résout dès lors un secteur ajouté au lieu de
  lever.

---

## 7. Ce qui fait qu'un secteur ajouté COMPTE vraiment

Ajouter un secteur = `{label, industries, types}` :

- `label` + `industries` → **identité** (couche 1). Le secteur existe, s'affiche,
  son industrie se résout.
- `types` (CompanyType : IMF, BANK, MERCHANT, FONDATION, FUNDING_PROVIDER) →
  **liaison générative** (couche 2). Stockée dans `surcouche.secteurs_types`.
  `connexes_par_type()` l'inverse en `type → secteurs`, que `pilotage` passe au
  générateur (`ExecuteurOrganisation.connexes_sup`), fusionné dans
  `secteurs_et_industrie`.

**Sans `types`** : le secteur est au référentiel (visible) mais **aucune Company
ne le porte** — c'est la sémantique juste, assumée.
**Avec `types`** : il devient un **connexe réellement tiré** au run.

**Preuve** (test `test_un_secteur_declare_connexe_est_reellement_tire`, rejoué en
CI) : sans binding, jamais tiré ; avec binding pour l'IMF, porté par ~21/60
Companies générées, industrie dérivée du principal, base intacte.

---

## 8. Carte du code

| Rôle | Fichier · symbole |
|---|---|
| Charger/valider la base (immuable) | `referentiel_statique.py` · `ReferentielStatique`, `charger_statique()` |
| Industrie d'un secteur (1, alpha, stable) | `referentiel_statique.py` · `industrie_du_secteur()` |
| **Référentiel effectif (base ⊕ surcouche)** | `referentiel_statique.py` · `referentiel_effectif()` |
| Surcouche (ajouts réversibles) | `surcouche_referentiel.py` · `SurcoucheReferentiel` |
| Liaison secteur→type | `surcouche_referentiel.py` · `secteurs_types`, `ajouter_secteur(types=…)`, `connexes_par_type()` |
| Profils métier (secteurs par type) | `organisation_execution.py` · `SECTEURS_PAR_TYPE` |
| Sélection des secteurs d'une Company | `organisation_execution.py` · `secteurs_et_industrie(…, connexes_sup)` |
| Câblage run | `pilotage.py` · référentiel effectif + `connexes_sup` → `ExecuteurOrganisation` |
| Endpoints d'édition | `routes/admin_referentiels.py` · `POST/DELETE /secteurs`, `/industries`, … |
| Écran | frontend `RefCatalogue*.tsx` (deux-volets + constellation) |

---

## 9. Invariants & garde-fous

- **Unicité** : un label de secteur/industrie est unique (classeur **et**
  surcouche).
- **Industries fermées par défaut** : un secteur ne se rattache qu'à des
  industries **existantes** ; on n'ouvre pas une 7ᵉ industrie par la porte d'un
  secteur (l'ajout d'industrie est une opération explicite, rare).
- **Garde anti-orphelin** : on refuse (409) de retirer une industrie encore
  rattachée à un secteur.
- **Réversibilité** : seul un ajout de surcouche se retire ; le classeur est
  intouchable (pas de corbeille dessus).
- **Reproductibilité** : la surcouche fait partie de ce qu'un run fige
  (`ENF-15`) — rejouer un `run_id` doit redonner la même donnée.

---

## 10. Périmètre exact (honnêteté)

- **Secteurs** : la verticale « compte vraiment » est **branchée et prouvée**.
- **Industries** : fusionnées dans le référentiel effectif (résolues en
  génération). Une industrie n'entre au tirage que via des secteurs qui la
  portent.
- **Formes juridiques, dirigeants, professions** : ajout/retrait **réversibles**
  et **affichés** (référentiel effectif côté lecture), mais le générateur les
  tire encore de profils **curés** (`FORME_PAR_TYPE`, `_fonction_du_dirigeant`,
  groupes de professions) — **pas encore de la surcouche**. Le même patron
  « effectif + liaison générative » resterait à câbler pour qu'ils soient
  *générés*, dimension par dimension.

---

### En une phrase

**L'industrie est le niveau large (6), le secteur le niveau fin (112), en
relation n:n ; une Company se classe par une industrie principale ; la
taxonomie et les profils de génération sont découplés (métier déclaré) ; et un
ajout ne *compte* que s'il traverse identité → liaison générative → acceptation
plateforme, via le référentiel effectif base ⊕ surcouche.**
