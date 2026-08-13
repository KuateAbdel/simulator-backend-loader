# Bilan de chantier — l'intégration des référentiels statiques de JJB

> Chantier ouvert le 12/08/2026 (plan en six lots, commit `28a4244`), clos le
> 13/08/2026. Nature ADDITIVE tenue : aucune exigence retirée, aucun chemin
> d'écriture modifié dans sa forme, et la ligne de flottaison des tests n'a
> jamais cédé (745 tests à l'ouverture → 908 à la clôture, zéro rouge).

## 1. Les six lots — livraison et preuve

| Lot | Livré | Commit | La preuve au commit |
|---|---|---|---|
| SD-1 chargeur | 12/08 | `345171c` | comptes exacts 6/112/27/576/21/4/195/20, échec bruyant |
| SD-2 Companies | 12/08 | `7f78fca` | `industries` ≠ `sectors`, Fondation `NGO`/`Charity`, 27 formes |
| SD-3 occupations | 13/08 | `a2646ba` | 533 métiers distincts pour 1600 INDIVIDUAL (contre **1**), règle `bank_stable`, EF-24 rendu VISIBLE (mutation trouvée puis fermée) |
| SD-4 dirigeants | 12/08 | `7f78fca` | 20 fonctions réelles, ancrées à la Company |
| SD-5 solde_initial | 13/08 | `842d413` | **A-09 FERMÉ** — LogNormal par profession, borné Annexe E, médiane 134 931 FCFA, EF-68 remesuré (43,4 %), CR-09 exact, D-01 au centime |
| SD-6 naissance | 13/08 | `5ea5803` | `place_of_birth` ne part plus à null, ~10 % nés à l'étranger (UN DESA), `id_place` libéré, cohérence pièce↔nationalité structurelle |

## 2. Les décisions d'ingénierie, et leur pourquoi

1. **Le vocabulaire du CDC reste le contrat, le fichier n'est que la matière**
   — les 4 familles d'EF-24 sont des VUES sur les 21 groupes (140/27/63/346).
2. **Une personne morale n'est jamais salariée** — la règle vient de la
   définition même du fichier (`bank_stable` = « salary, pension, payroll ») ;
   47 CORPORATE sur 100 étaient salariés avant.
3. **Tirage uniforme pour les INDIVIDUAL** — le seul choix sans chiffre
   inventé ; la pondération informelle (A-13) reste ouverte et déclarée.
4. **Segment ≠ solde depuis SD-5** — l'usage (quick_win) et le revenu
   (profession) sont deux axes réels distincts, assumés.
5. **La minorité née à l'étranger garde la nationalité locale** — une
   nationalité étrangère entraînerait pièce/msisdn/devise d'un pays sans
   référentiel ; déclaré, pas contourné.

## 3. Le protocole §6, tenu lot par lot

ruff + mypy propres · suite complète verte · mesure ciblée · DRY_RUN 2000/2000
· mutations (5 jouées sur le chantier, **3 trous de test trouvés et fermés** :
EF-24 invisible, écrêtage jamais exercé, câblage naissance) · commit avec la
mesure. Le juge final a toujours été le DRY_RUN — quotas exacts ×4 pays à
chaque lot.

## 4. Ce que la démonstration montre désormais

| | Avant | Après |
|---|---|---|
| Professions distinctes | 18 | **576** (533 vues sur 1600) |
| Secteurs Company | 4, dupliqués | **112 × 6 industries**, distincts |
| Formes juridiques | 6 | **27** |
| Fonctions dirigeant | 1 en dur | **20** |
| Solde initial | heuristique (1,02 Md total) | **modèle de revenu** (305 M — une clientèle réelle) |
| Lieu de naissance | = résidence, null au serveur | villes réelles + 195 pays |

## 5. Frontières — ce qui n'a PAS été fait, et pourquoi

- **A-13** : pondération informelle des professions INDIVIDUAL — exigerait des
  chiffres sourcés que ni le CDC ni le fichier ne fournissent.
- Nationalités étrangères (le Malien d'Abidjan) — hors CDC (4 pays).
- Les alias (38) chargés mais non consommés — serviront si une livraison
  future de JJB emploie les libellés bruts.
