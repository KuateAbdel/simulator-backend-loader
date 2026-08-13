# Conception — l'API de pilotage du Super-Admin du LOADER

> Écrit le 13/08/2026, à partir de la vision exprimée par Yaniv le même jour,
> du CDC (EF-50 → EF-59, CR-05), de `MODELE_UTILISATEURS.md` et de l'existant.
> C'est le **contrat** que le frontend Next.js de Zidane consommera
> (`10_component.puml`) — le backend l'expose, l'écran ne parle qu'à lui.

---

## 0. Les principes, avant les routes

1. **Deux Super-Admin, aucun rapport entre eux.** Celui du LOADER vit dans
   notre MongoDB (`super_admin_accounts`, bootstrap au premier démarrage,
   `must_change_password=True`). Celui de la PLATEFORME est un groupe RBAC de
   user-service. L'API décrite ici authentifie le premier, jamais le second.
2. **Le Loader est tier-2.** L'écran de Zidane → notre API → les 9 services
   FinZuu. Le frontend n'appelle JAMAIS FinZuu directement : toute écriture
   passe par nos exécuteurs, donc par nos invariants, notre registre, notre
   journal. C'est ce qui rend chaque action de l'admin **disciplinée par
   construction** — l'admin ne peut pas contourner `INV-*` même s'il le veut.
3. **Chaque écriture suit le rite `D-01`** : composer → montrer (DRY_RUN) →
   confirmer explicitement → exécuter (REAL) → relire → recette. Le bouton
   « Run » de l'écran est en réalité DEUX actions : « préparer » (à blanc,
   rapport lisible) puis « confirmer » — parce que trois services n'ont pas
   de DELETE, la confirmation n'est jamais un défaut.
4. **Rien à usage unique.** Le CDC : « outil autonome, réutilisable et
   paramétrable » (§349), « 2000 clients **par exécution** » (§360), « actif
   réutilisable pour tous les futurs environnements » (§378). Chaque run est
   idempotent (CR-03), listable, comparable ; la purge par marqueur permet de
   régénérer à volonté ; la v1 est la première version d'un outil qui évoluera
   avec la plateforme.

## 1. Ce qui EXISTE déjà dans le backend (rien à réinventer)

| Capacité | Où elle vit | État |
|---|---|---|
| Compte Super-Admin Loader + hachage + bootstrap | `services/bootstrap.py`, `repositories/super_admin.py` | ✅ |
| Squelette FastAPI + cycle de vie Mongo + `/health` | `app/main.py`, `routes/health.py` | ✅ |
| Verrou d'exécution (EF-55) | `LoaderRunRepository.dernier_en_cours()` | ✅ préparé |
| Configuration en cascade ville→région→pays→CDC | `core/configuration.py` (CFG-01→04) | ✅ |
| Ajout de villes/valeurs SANS toucher au classeur | `surcouche_referentiel.py`, `AdministrationConfigService` (CFG-05/06) | ✅ |
| Orchestrateur 8 modules + reprise + 20 workers | `services/orchestrateur.py` | ✅ |
| Rapports par module + recette CR-01→12 | `services/recette.py` + rapports | ✅ |
| Registre Faker (write-ahead, réconciliation) | `repositories/faker_ledger.py` | ✅ |
| Journal d'audit des intentions | `audit_trail` | ✅ |
| Référentiels riches (géo, telcos, 576 métiers, 195 pays, revenus) | `geographie.py`, `referentiel_statique.py` | ✅ |

**L'API de pilotage est donc une COUCHE MINCE au-dessus d'un moteur déjà
testé (826 tests)** — pas un nouveau système.

## 2. La surface API — par user story du Super-Admin

### 2.1 Session
- `POST /admin/auth/login` — email + mot de passe → jeton de session Loader.
  Premier login : `must_change_password` force `POST /admin/auth/password`.

### 2.2 Configuration & référentiels (EF-50, EF-51)
- `GET /admin/configuration` — l'état résolu complet (défauts CDC + surcharges).
- `PUT /admin/configuration` — volumes (nb clients, companies, branches,
  agences, kiosques, agents par niveau), pays actifs/inactifs, quotas.
- `GET /admin/referentiels/geographie` — l'arbre pays→régions→villes→quartiers
  (51/50/82), avec GPS — la matière des écrans de sélection.
- `POST /admin/referentiels/villes` — ajout d'une ville (CFG-06 : relecture
  des 9 champs avant écriture ; le classeur n'est jamais modifié).
- `GET /admin/referentiels/telcos` — les 12 plans réels, parts de marché.
- `GET /admin/referentiels/catalogue-statique` — 6 industries, 112 secteurs,
  576 professions, 4 profils de revenu, 195 pays, 20 fonctions (lecture).
- **Ajout d'un PAYS** : exposé mais gardé — `EF-05` borne à 4 pays cibles ;
  un 5ᵉ pays exige sa matière (régions, villes, telcos, patronymes). L'API
  refuse avec un message qui LISTE ce qui manque — refus pédagogique, pas mur.

### 2.3 Runs (EF-52 → EF-56 — le « bouton Run »)
- `POST /admin/runs` `{mode: DRY_RUN}` — prépare et exécute À BLANC ;
  rend le rapport complet (quotas prévus, solde doté, catalogue, écarts).
- `POST /admin/runs/{id}/confirmer` — le passage en REAL, action explicite
  (jamais un défaut) ; refuse si un run est en cours (verrou EF-55).
- `GET /admin/runs/{id}/progression` — temps réel (SSE ou polling) : palier
  en cours, compteurs par pays, erreurs au fil de l'eau.
- `GET /admin/runs` / `GET /admin/runs/{id}` — historique, rapport, recette
  CR-01→12 avec les trois verdicts, journal d'erreurs (EF-56), réconciliation
  Faker (suivi complet : réservé/confirmé/libéré par client Faker).
- `POST /admin/runs/{id}/arreter` — arrêt propre : fin de lot, réconciliation.

### 2.4 Entités à l'unité (la richesse côté Loader)
Le même moteur que les runs, à l'échelle 1 — composer chez nous, montrer,
confirmer, pousser :
- `POST /admin/entites/companies` — formulaire riche (type, pays, ville…) ;
  le Loader complète TOUT le reste (secteur+industrie JJB, forme juridique,
  dirigeant avec fonction et lieu de naissance, licences, adresse GPS) et rend
  l'aperçu ; `/confirmer` exécute la séquence exacte de `S3-03` sur la
  plateforme (company → licences → admin user → comptes).
- `POST /admin/entites/produits` — même rite ; le produit est créé côté
  plateforme avec policy embarquée, taux borné 24 %, marqueur `short_name`,
  protocole à deux clés contre `ANO-PRD-UNIQ-01`.
- (v2 : dépositaires, clients à l'unité — même patron, déjà outillé.)

### 2.5 Dashboard (EF-57/58 — « voir tout l'écosystème »)
- `GET /admin/dashboard` — les comptes vivants : entités par type et par pays,
  quotas mesurés vs cibles, distribution des 4 profils comportementaux
  (CR-09), soldes (médiane, part ≥ 150 000), arbre org_hierarchy navigable,
  état de santé des 9 services FinZuu (le sondage `/health` de chacun).
  Source : NOS collections (l'index que P-01 renforcera), jamais 20 requêtes
  paginées vers FinZuu à chaque affichage.

### 2.6 Purge (EF-59 / EF-65)
- `POST /admin/purge/preparer` — liste ce que le marqueur retrouve
  (`DEMO_` sur les noms, `short_name` sur les produits — CR-07 par type
  d'entité), et dit ce qui n'est PAS purgeable (identity/account/depositary
  sans DELETE : listés, marqués, jamais cachés).
- `POST /admin/purge/confirmer` — exécute ce qui est réversible, rapporte le
  reste. La purge est un RUN comme un autre : journalisée, réconciliée.

## 3. L'ordre d'implémentation (S6, backend)

```
Lot A  auth + configuration + référentiels (lecture)   ── débloque Zidane
Lot B  runs : préparer/confirmer/progression/historique ── le bouton Run
Lot C  dashboard                                        ── lecture de nos collections
Lot D  entités à l'unité (company, produit)             ── réutilise S3-03/S3-05
Lot E  purge par marqueur                               ── EF-65, après CR-07 par type
```

Contrat d'abord : le schéma OpenAPI de chaque lot est publié sur `/docs` dès
le lot A — Zidane maquette sur le contrat, pas sur des promesses.

## 4. Ce que ça garantit (les « n'est-ce pas » de Yaniv, en engagements)

- L'admin **voit tout depuis le Loader** et n'écrit que par lui → chaque
  écriture passe par les invariants, le registre anti-doublon, le journal.
- Le Loader **connaît quoi remplir** : l'admin donne 4 champs, le référentiel
  complète les 40 autres — plus riche chez nous, conforme chez eux.
- **Aucun bug de la plateforme n'est subi** : unicité produits, casse,
  language ignoré, FRA-218… chaque parade vit dans les clients HTTP que
  l'API réutilise.
- **Qualité de service en QA senior** : chaque action rend un rapport relu
  (jamais déduit), la recette juge chaque run, le DRY_RUN précède chaque REAL.
- **Duhamel** : la méthodologie (poids ajustés Annexe D.2, cycle de vie) est
  intégrée dans le moteur (EF-67/68) et sera visible au dashboard (CR-09).

---

## 5. LES USER STORIES DU SUPER-ADMIN DU LOADER — complètes et datées

> Ajout du 13/08 (soir), à la demande de Yaniv : « ce qu'il peut et ne peut
> pas faire, à quel temps, et ce qu'il voit précisément ». Chaque story a un
> identifiant `US-*` ; le frontend de Zidane et nos tests d'API pointeront
> ces identifiants.

### Le cycle de vie — QUAND chaque story est possible

```
ETAT 0  premier demarrage    → US-A1, US-A2 uniquement (rien d'autre avant)
ETAT 1  configure, aucun run → tout SAUF les stories "pendant un run"
ETAT 2  run EN COURS         → lecture + progression + arret ; la config et
                               les creations d'entites sont VERROUILLEES
ETAT 3  apres un run         → tout, y compris purge et second run (CR-03)
```

### A. Session (ÉTAT 0+)

| # | Il PEUT | Il NE PEUT PAS |
|---|---|---|
| US-A1 | Se loguer (email + mot de passe du bootstrap) | Se créer un compte : il n'y a QU'UN admin en v1 (Phase 1 CDC) |
| US-A2 | Être FORCÉ de changer le mot de passe au premier login | Revoir un mot de passe en clair — haché dès le bootstrap, jamais journalisé |
| US-A3 | Se déconnecter ; session expirée = re-login | Déléguer : pas de rôles secondaires en v1 (v2 : lecteurs) |

### B. Configuration & référentiels (ÉTATS 1 et 3 — JAMAIS pendant un run)

| # | Il PEUT | Il NE PEUT PAS |
|---|---|---|
| US-B1 | Voir la configuration RÉSOLUE : chaque valeur avec son origine (défaut CDC / surcharge pays / région / ville) | Voir une valeur sans son origine — l'origine fait partie de la donnée |
| US-B2 | Modifier les volumes : nb clients (défaut 2000), companies, branches, agences, kiosques, agents par niveau, quotas | Casser un quota du CDC : EF-22/23/24 se paramètrent DANS leurs bornes, l'API refuse hors bornes avec la référence CDC |
| US-B3 | Activer/désactiver un pays pour le prochain run | Désactiver côté serveur par accident : Loader seul par défaut, l'action serveur est un bouton distinct et explicite (A-08) |
| US-B4 | Ajouter une ville (région existante, 9 champs, GPS) — relue avant écriture | Modifier le classeur source : la surcouche est réversible, le classeur est immuable |
| US-B5 | Consulter TOUS les référentiels : arbre géo 51/50/82 avec GPS, 12 telcos avec parts de marché, 576 professions par groupe et profil de revenu, 112 secteurs × 6 industries, 27 formes, 20 fonctions, 195 pays | Les éditer à la main : un référentiel se remplace par LIVRAISON de fichier (versionnée), jamais par édition de cellules |
| US-B6 | Demander l'ajout d'un PAYS et recevoir la LISTE de ce qui manque (régions, villes, telcos, patronymes, plan de numérotation) | L'activer sans cette matière : EF-05 borne à 4 — le refus est pédagogique |
| US-B7 | Modifier la config du re-scoring (30/60/90 j — CDC §299) et le terme des DAT | Rien pendant l'ÉTAT 2 : toute la section B est verrouillée run en cours |

### C. Les runs (le « bouton Run » — ÉTATS 1 et 3)

| # | Il PEUT | Il NE PEUT PAS |
|---|---|---|
| US-C1 | Lancer une PRÉPARATION (DRY_RUN) sur la config courante | Lancer un REAL directement : le DRY_RUN du même périmètre est un PRÉALABLE obligatoire (D-01) |
| US-C2 | Lire le rapport à blanc : par pays 500/500, quotas, solde total qui SERA déposé, 12 produits, écarts constatés, produits étrangers refusés | — |
| US-C3 | CONFIRMER le passage en REAL (action explicite, re-saisie du mot du run) | Confirmer si un run est déjà en cours : verrou EF-55, HTTP 409 avec l'id du run en cours |
| US-C4 | Suivre la PROGRESSION en direct : palier courant (1→8), compteurs par pays qui montent, erreurs au fil de l'eau, ETA sur le tempo mesuré | — |
| US-C5 | ARRÊTER proprement : fin du lot en cours, registre réconcilié, rien d'orphelin | Tuer brutalement depuis l'écran — l'arrêt sale n'existe pas dans l'API |
| US-C6 | REPRENDRE un run interrompu : même périmètre, CR-03 reconnaît l'existant, ne crée que le manquant | Créer un doublon en reprenant : structurellement impossible (registre + GET-avant-POST + unicité triple) |
| US-C7 | Consulter l'HISTORIQUE : chaque run avec mode, périmètre, durée, statut, rapport complet, recette CR-01→12 (TENU/VIOLÉ/NON VÉRIFIABLE avec raison), réconciliation Faker | Supprimer un run de l'historique : le journal est append-only (CR-06) |

### D. Entités à l'unité (ÉTATS 1 et 3)

| # | Il PEUT | Il NE PEUT PAS |
|---|---|---|
| US-D1 | Créer une COMPANY : il saisit type + pays + ville (+ nom s'il veut), le Loader compose TOUT le reste et montre l'APERÇU complet avant tout envoi ; à la confirmation, séquence S3-03 complète (company → licences → admin user → comptes) | Envoyer sans aperçu ; envoyer une Company qui violerait un invariant (secteur vide, ville hors pays…) — refus avant réseau, motif affiché |
| US-D2 | Créer un PRODUIT COLLECT : nom métier, type, catégorie, bornes, taux — aperçu puis envoi avec marqueur short_name et protocole deux clés | Créer un produit LENDING en v1 (interrupteur perimetre_lending, sprint 8) ; dépasser 24 % (refus BEAC/COBAC avant réseau) |
| US-D3 | Voir le résultat RELU depuis la plateforme après création (jamais déduit — FRA-218) | Supprimer une entité créée : les services n'ont pas de DELETE — l'API le DIT au lieu de le cacher |

### E. VISUALISATION — ce qu'il voit, écran par écran

**E1 — Vue d'ensemble (l'atterrissage après login)**
- 9 pastilles de santé des services FinZuu (vert/rouge, latence du dernier /health)
- l'état du Loader : run en cours OU dernier run (statut, date, durée)
- les 4 pays avec leurs compteurs vivants : clients / cible, companies, kiosques
- les alertes ouvertes (écarts CDC, entités non purgeables, anomalies FRA-*)

**E2 — Écosystème (le drill-down)**
- l'arbre navigable : pays → company → branch → agence → kiosque → clients
  rattachés (org_hierarchy, la donnée que la plateforme ne sait pas montrer)
- fiche entité au clic : tout ce que NOUS savons (y compris ce que le serveur
  ne porte pas : quartier, GPS, licences, journal de ses écritures)

**E3 — Population (la démonstration devant bailleur)**
- pyramide des âges (60 % < 25 ans visible), ratio femmes/hommes 2:1
- occupations : nuage/top des 576 métiers, part agriculture (EF-24 : 20 %)
- soldes : histogramme lognormal, médiane, part ≥ 150 000 FCFA (EF-68)
- 4 profils comportementaux : 50/25/13/12 mesuré vs cible (CR-09)
- lieux de naissance : carte/États des ~10 % nés à l'étranger

**E4 — Run en cours / rapport de run**
- barre des 8 paliers avec le palier actif, compteurs par pays en direct
- le rapport final tel qu'il existe aujourd'hui en console, mais structuré :
  quotas, solde doté, souscriptions UC-13, refusés avant réseau AVEC motifs
- la recette : les 13 critères CR, chacun TENU/VIOLÉ/NON VÉRIFIABLE + raison

**E5 — Traçabilité**
- le registre Faker : chaque client_id consommé, son état, son entité
- le journal d'audit : chaque intention d'écriture, réussie/échouée, horodatée
- la réconciliation : « aucune intention orpheline » ou la liste exacte

### F. Purge (ÉTAT 3)

| # | Il PEUT | Il NE PEUT PAS |
|---|---|---|
| US-F1 | PRÉPARER : voir la liste exacte de ce que le marqueur retrouve, par service, avec le compte | Purger sans préparation |
| US-F2 | CONFIRMER : exécution journalisée, rapport relu | Purger identity/account/depositary : AUCUN DELETE — la liste des résidus marqués lui est montrée, jamais cachée |

### G. Les interdits TRANSVERSAUX (ce que l'admin ne peut JAMAIS faire)

1. Contourner un invariant INV-* — aucune route « écriture brute » n'existe.
2. Écrire sur une entité partagée non marquée (leçon A-10).
3. Provoquer un doublon — registre, GET-avant-POST, unicité triple.
4. Lancer deux générations simultanées (EF-55).
5. Voir un secret en clair (mots de passe hachés, credentials .env jamais exposés par l'API).
6. Toucher au crédit avant le sprint 8 (perimetre_lending).
