# Stratégie d'audit du Loader — et le premier audit exécuté

> Rédigé et EXÉCUTÉ le 13/08/2026 à la demande de Yaniv : « impartial, pas de
> mais qui tiennent — un manque se signale ET se corrige ». Ce document est
> les deux : la stratégie (rejouable à chaque jalon) et le procès-verbal du
> premier passage, constats et corrections inclus.

---

## 1. La stratégie — sept axes, chacun outillé

| Axe | Question posée | Outillage | Cadence |
|---|---|---|---|
| A. Reproductibilité (ENF-15/CR-03) | Un même périmètre rejoué rend-il le MÊME écosystème ? | grep `hash(`, `date.today()`, `random` non semé ; test double-run | chaque commit qui compose |
| B. Statique | Types et lint sans exception ? | `ruff` (règles S incluses) + `mypy` — zéro erreur toléré | chaque commit |
| C. Tests | Tout passe, et qu'est-ce qui n'est PAS couvert ? | suite complète + `pytest-cov` (ajouté par cet audit) | chaque commit / couverture à chaque jalon |
| D. Mutations | Casser une garantie fait-il tomber un test ? | mutations manuelles ciblées (protocole §6 du plan SD) | chaque lot livré |
| E. Sécurité | Secrets, surface d'auth ? | grep secrets, `.env` non suivi, revue des routes 401/403/409/422 | chaque jalon |
| F. Véracité documentaire | Le code dit-il vrai ? | relecture croisée docstrings ↔ mesures (deux mensonges déjà attrapés et corrigés ce jour) | continu |
| G. Dette | Quels bouchons, où, avec quel plan de sortie ? | grep TODO/bouchon/réserve + ce registre | chaque jalon |

**Règle de verdict** : chaque constat reçoit un des trois — `CORRIGÉ` (dans le
commit de l'audit), `ENREGISTRÉ` (dette nommée avec plan de sortie), `SANS
OBJET` (faux positif expliqué). Aucun quatrième état.

---

## 2. Procès-verbal du passage du 13/08

### Constats CORRIGÉS (dans ce commit)

| # | Constat | Sévérité | Correction |
|---|---|---|---|
| AU-1 | `_expiration_piece()` dérivait de `date.today()` — le DERNIER champ à échapper à l'ancrage temporel : deux exécutions du même `run_id` à deux jours d'écart rendaient des `id_expire_on` différents (entaille ENF-15, la même que la date de naissance avait déjà corrigée) | **haute** | ancrée sur `self._reference` (la fenêtre du run, figée D-10). Corrigée AVANT tout palier REAL — aucune donnée serveur affectée |
| AU-2 | `admin_entites.py` : `entity_id` du journal d'intention dérivé de `hash()` — randomisé par processus, l'identifiant n'aurait pas survécu à un redémarrage (le MÊME défaut corrigé sur US-D1 le même jour, présent dans US-D2) | moyenne | `uuid5(NAMESPACE_OID, marqueur)` — stable par construction |
| AU-3 | La référence de composition des entités à l'unité était `date.today()` nue — la promesse « même demande = même Company » ne tenait pas au changement de jour | moyenne | alignée sur la règle du moteur (`sim_end_date` sinon aujourd'hui) et la promesse REQUALIFIÉE : l'idempotence vaut À FENÊTRE ÉGALE, comme pour les runs |
| AU-4 | Pas d'outil de couverture — on affirmait « bien testé » sans le chiffre | moyenne | `pytest-cov` ajouté ; premier chiffre : **83 %** global (5789 lignes, 973 non couvertes) |

### Constats ENREGISTRÉS (dette nommée, plan de sortie)

| # | Constat | Plan de sortie |
|---|---|---|
| AU-5 | `pilotage.py` à **30 %** de couverture : le moteur `executer()` n'est prouvé que par les DRY_RUN réels (hors pytest) et les routes le doublent. Ses BRIQUES sont couvertes (exécuteurs 86-99 %), l'ASSEMBLAGE ne l'est pas en CI | rendre les clients injectables dans `executer()` (fabrique paramétrable) pour un test d'assemblage complet à vide — planifié avec le durcissement pré-palier 1 |
| AU-6 | Le « bouchon » patronymes/prénoms (`generateur.py`) : matière Faker rejouée en dur tant que le tirage réel de noms n'existe pas — dette DÉCLARÉE dans le code depuis l'origine | disparaît quand le client Faker fournira les noms ; `D-FAKER-1` s'appliquera alors |
| AU-7 | `ClientCompose.jeune` (propriété) relit l'âge contre `date.today()` — dérive possible en franchissant minuit. AUCUN consommateur dans le chemin réel (vérifié) | surveillée ; si un consommateur apparaît, la propriété devra prendre la référence du run |
| AU-8 | account-service reste le seul service sans page Anatomy (`D-ACC-XXX` à extraire) — noté depuis le 8/08 | campagne d'extraction avant le palier 6 (c'est lui qui encaisse les 2000 dotations) |

### Vérifications SANS ÉCART (affirmations re-prouvées sur pièce ce jour)

- Liste close devises `{XAF: BEAC/CEMAC, XOF: BCEAO/UEMOA}` (`invariants.py:97`) ✅
- EF-55 : index Mongo **unique partiel** sur `status=RUNNING` (`database.py:139`) ✅
- FRA-219 : parade STRUCTURELLE — le client depositary n'expose aucune méthode change-status, la route n'est jamais appelable ✅
- CFG-06 : relecture des 9 champs après écriture config-service (`config_service.py:376`) ✅
- « Pas de second crédit » à la reprise (`clients_execution.py:1621`) ✅
- Aucun `random` non semé dans `app/` ✅ · aucun secret en clair ✅ · `.env` non suivi ✅
- Deux mensonges documentaires attrapés et corrigés ce jour : « client-service expose un DELETE » (faux — PATCH langue est sa seule mutation) ; l'en-tête historique de `main.py` (déjà corrigé le 11/08)

---

## 3. Chiffres de référence du jalon (13/08/2026 soir)

- **888 tests**, 0 échec · ruff + mypy **zéro erreur** · couverture **83 %**
- Points hauts : recette 99 %, source interne 100 %, rôles 97 %, référentiel statique 93 %
- Point bas assumé : pilotage 30 % (AU-5)
- 30 commits poussés ce jour, `main` == `origin/main`
