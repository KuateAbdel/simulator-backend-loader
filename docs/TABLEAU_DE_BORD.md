# Tableau de bord — l'état vivant du backlog

> Reconstruit le 13/08/2026 depuis les plans commités (`PLAN.md`,
> `PLAN_SPRINTS.md`, `PLAN_INTEGRATION_STATIC_DATA.md`,
> `CONCEPTION_CATALOGUE_ET_SOUSCRIPTION.md`, `ORCHESTRATION.md`).
> **Ce fichier est mis à jour à chaque tâche fermée** — c'est lui qui survit aux
> sessions, pas la liste de tâches de l'outil.
>
> Le Loader n'est pas un script : c'est le **backend de pilotage** de la
> plateforme. La cible est v1.0.0 — 2000 clients en 30 minutes, recette
> CR-01→CR-12 tenue, piloté par le Super-Admin sans assistance (CR-05).

## A. Chantier « référentiels statiques de JJB » — 6 lots

| # | Tâche | État |
|---|---|---|
| SD-1 | Chargeur `referentiel_statique.py` (6/112/27/576/21/4/195/20) | ✅ `345171c` |
| SD-2 | Companies : `industries` ≠ `sectors`, Fondation servie, 27 formes | ✅ `7f78fca` |
| SD-3 | Occupations : 18 → 576, règle `bank_stable`, EF-24 visible | ✅ `a2646ba` |
| SD-4 | Dirigeants : « Dirigeant » → 20 fonctions | ✅ `7f78fca` |
| SD-5 | `solde_initial` : heuristique → LogNormal(μ,σ) par profession, borné Annexe E, mesure EF-68 refaite — **A-09 FERMÉ** | ✅ 13/08 |
| SD-6 | Lieu de naissance : 195 pays + 50 villes, `id_place` ≠ résidence *(ancienne tâche #15)* | ✅ 13/08 |
| — | Bilan de chantier ultra-détaillé des 6 lots | ⬜ |

## B. Chantier « catalogue » — les 11 changements du §8

| # | Tâche | État |
|---|---|---|
| CAT 1-2 | **Décidé par Yaniv le 13/08** : produits RÉELS et recherchés — `Tontine Digitale` · `Compte Epargne Entreprise` · `Epargne Bloquee 6 Mois` · `Depot a Terme Entreprise 12 Mois` · `Warrantage Cerealier` · `Collecte Cacao Cooperative` (conception §4 : PAMECAS, warrantage sahélien). Marqueur `DEMO_` dans `short_name`, protocole à deux clés contre `ANO-PRD-UNIQ-01` | ✅ 13/08 |
| CAT 3-5 | Produits environnement constatés · 12 créations | ✅ (12/08, `c53c05d`) |
| CAT 6 | CR-07 par type d'entité | ✅ 13/08 — **par construction** : le nœud PRODUIT porte le MARQUEUR comme `name`, CR-07 vérifie les préfixes sans modification |
| CAT 7-8 | Rattachement Produit→Company + panier de SA Company *(ancienne #29 / A-12)* | ✅ 13/08 — niveau PRODUIT (nœud RACINE, liens n:n, ZÉRO produit créé : 6 produits × 8 porteuses = 48 liens), CR-02 les vérifie, panier STRICT dès que la carte existe (Company hors carte → refus dit), DRY fidèle (ancres planifiées empruntent les companies du rattachement) |
| CAT 9-11 | `perimetre_lending` · `PRODUITS_ATTENDUS` fonction du périmètre · recette « hors périmètre » | ⬜ |

## C-0. DÉCISION du 13/08 (Yaniv) — HÉBERGER AVANT DE CHARGER

Le Loader (backend) est déployé sur `simul.api.fintech4esg.com` AVANT tout palier REAL (Option B, 14/08 — `simul.fintech4esg.com` est réservé au frontend de Zidane).
Raison de fond : la MongoDB du Loader (registre Faker, org_hierarchy, runs,
configuration) est SA MÉMOIRE — charger depuis la machine de dev puis héberger
donnerait une instance vierge, amputée du registre qui rend CR-03, la reprise,
le dashboard et la purge possibles. La machine locale = développement
uniquement. Protocole chirurgical : déployer → brancher les 9 services (.env)
→ sonde E1 verte sur les 10 → DRY_RUN complet DEPUIS le serveur → paliers.

## C-1. GITHUB, CI/CD & ARCHITECTURE DE DÉPLOIEMENT — 14/08 (v0.5.0)

**Recon SSH du serveur (lecture seule)** : serveur PARTAGÉ (ERPNext, Nextcloud, Newsletter — on ne touche à rien). Défaut attrapé : port 8000 pris → Loader sur **8003** ; réseau `loader-net` déjà préparé → adopté ; user `apps` sous `/home/apps/loader`, jamais root ; nginx sur le HOST. **Mapping domaines TRANCHÉ (Option B, convention Newsletter)** : `simul.fintech4esg.com` = frontend Zidane, **`simul.api.fintech4esg.com` = notre backend + Swagger** (vhost `deploy/nginx/simul-api.conf` + certbot à créer). **CORS ajouté** (piloté par env, piège du split frontend/backend) + testé. Conception complète : `docs/ARCHITECTURE_DEPLOIEMENT.md`.


Dépôt : description + 6 topics posés · **Release v0.5.0 publiée**
(CHANGELOG Keep-a-Changelog, premier tag du dépôt) · main protégée
(force-push et suppression INTERDITS — historique append-only) · **CI verte
sur GitHub en 1 min 29** (ruff+mypy+948 tests contre MongoDB de service) ·
CD prêt : SSH par empreinte, ff-only, build natif ARM64, santé vérifiée —
**en attente des 4 secrets** (`DEPLOY_HOST/USER/SSH_KEY/KNOWN_HOSTS`, geste
Yaniv, runbook `docs/DEPLOIEMENT.md` §3) et de la préparation du serveur
(§3c). Domaine vérifié le 14/08 : DNS → 152.53.118.110, certificat
Let's Encrypt valide jusqu'au 18/10, **503 = proxy prêt, backend attendu** ;
port 22 ouvert. Les tests sont poussés sur GitHub mais JAMAIS déployés
(.dockerignore en liste blanche).

## C. La séquence REAL — l'ordre topologique d'ORCHESTRATION.md

| Palier | Tâche | État |
|---|---|---|
| 1 | Rôles : 11 `group_id` (seul module réversible) | ⬜ |
| 2 | Organisation : 16 Lenders, licences, Admin Users, 4 comptes (S3-03) | ⏸ paliers 1 + décisions catalogue |
| 3 | Catalogue : 12 créations, noms réels, marqueur `short_name` | ⬜ |
| 4 | Dépositaires : 40-80 nœuds, Agents (S3-06) | ⬜ |
| 5 | Staff & Agents : 60-100 users, 11 rôles | ⏸ **A-05** |
| 6 | Clients : 2000, quotas, EF-26 deux temps | ⬜ SD-3 ✅ prêt |
| — | Second run REAL identique — preuve CR-03 | ⬜ |
| 7 | Vie 180 jours + crédit (EF-67→80) | ⏸ **A-07, A-11, A-04** |
| 8 | Recette : CR-01→12 tous TENUS + mesure 30 min → **v1.0.0** | ⬜ |

## D. Super-Admin — étape 8 du PLAN, Sprint 6

| Tâche | État |
|---|---|
| Routes de pilotage EF-50→EF-59 — conception + backlog canonique (page Confluence 67665922). **Lot A LIVRÉ le 13/08** (sauf US-B4) : auth US-A1/A2/A4 + référentiels lecture US-B5 + configuration US-B1/B2/B3 (vue résolue avec origines, volumes bornés, quotas EF-22/23 verrouillés, verrou EF-55 en 409, pays activables — jamais config-service). **LOTS A ET B COMPLETS (13/08 soir)** : lot A entier + lot B — moteur extrait dans `pilotage.py` (UN moteur CLI+API, identité prouvée au centime), runs pilotés par l'API : préparer (DRY seul, rite D-01 structurel), confirmer (périmètre FIGÉ, 409 si config changée), progression, arrêt v1, historique append-only (DELETE→405), rapport rangé avec le run. **Lot C livré (13/08 nuit)** : dashboard E1 (santé 9 services+Faker, compteurs, alertes), E2 (arbre navigable org_hierarchy), E4 (traçabilité+réconciliation) + **E3 livré** : le moteur range ses mesures structurées avec le run (occupations, tranches de soldes avec frontière 150 000/EF-68, naissances, quotas mesure/cible), servies par GET /admin/dashboard/population. **LOT C COMPLET.** **Lot D : US-D2 livré** (produit à l'unité — aperçu/confirmer, 3 interfaces par policy_type, double clé d'unicité, registre interne, write-ahead sentinelle RUN_ADMIN, fiche relue). **US-D1 livré aussi** (company à l'unité : 3 champs saisis → ~40 composés, territoire résolu avec refus pédagogique, ancre sha256 inter-processus, séquence S3-03 réutilisée). **LOT D COMPLET. LOT E LIVRÉ (purge honnête : groupes supprimables + carte des résidus avec verdicts D-DEP-3/D-DEP-8, verrou EF-55, journal DELETE sous RUN_ADMIN). L'API SUPER-ADMIN v1 EST ENTIÈRE — lots A à E, 20 stories, 62 tests d'API.** | 🟡 en cours |
| Purge par préfixe `DEMO_` + verrou d'exécution (EF-65/66) | ⬜ |
| **LOT G — INVENTAIRE/RÉCONCILIATION (13/08 nuit, vision Yaniv « NOS données là-bas, avec NOS statuts »)** : `app/services/inventaire.py` — 4 statuts par croisement registre × plateforme (`a_nous` / `disparu_la_bas` / `marque_mais_inconnu` / `etranger`), servis par GET /admin/inventaire/{groupes,produits,companies} + **DELETE individuel d'un groupe À NOUS** (403 étranger, 404 inconnu, 409 sous run, 502 si panne OU si le serveur répond sans agir — relecture obligatoire, journal write-ahead sous RUN_ADMIN). **DÉCISION Yaniv : AUCUN préfixe sur les groupes, jamais** — les noms de rôles sont fonctionnels ; la reconnaissance des groupes est PAR REGISTRE (journal). **TROU FERMÉ** : `ExecuteurRoles` ne journalisait pas ses créations (seule écriture non tracée du moteur) → chaque groupe créé en REAL inscrit désormais son `group_id` serveur au registre en write-ahead ; la purge, qui filtrait sur `DEMO_` et n'aurait JAMAIS rien trouvé, reconnaît maintenant par registre. Registres : groupes=journal, produits=journal∪`produits_admin`, companies=`lenders_registry`. 920 tests (+11), 4 mutations attrapées, DRY_RUN 2000 propre. | ✅ |

## D-bis. Configuration avancée (#26) — TELCO livré 13/08

US-B7 ✅ : ajout de telco par l'API — **l'ALLER COMPLET** (surcouche locale
PUIS config-service : création GET-avant-POST + rattachement au pays par
relecture 9 champs), 4 invariants (unicité CROISÉE nom/code, regex compilable
ET composable avec preuve `exemple_msisdn`, somme des parts ≤ 100 = INV-18 à
l'écriture), échec d'envoi jamais silencieux (le local reste + motif),
journalisé sous RUN_ADMIN. La VILLE (US-B4) fait aussi l'aller complet.
**LOT H livré (14/08, décisions Yaniv)** : (1) **régions et quartiers SANS
LIMITE** — POST /admin/referentiels/{regions,quartiers}, invariants seulement
(EF-02 parent, non-duplication), jamais de plafond (testé : 15 régions
d'affilée) ; la réponse DIT que rien ne part à config-service et POURQUOI
(la ville seule a un contrat là-bas) ; pays en ISO 3166-1 alpha-2 strict ;
**défaut réel attrapé par le test** : `_toutes_regions` ignorait la surcouche
— une région ajoutée 2× écrasait la 1ʳᵉ en silence, corrigé. (2) **GET
/admin/referentiels/permissions** — la liste vivante, écartement D-07 dit.
(3) **POST /admin/entites/groupes** — création à l'unité avec tout ce que ça
implique (description requise, tag jamais ROOT/A4, company_id vide = global,
permissions validées contre la liste vivante → 422 nommé avant tout POST),
GET-avant-POST à TROIS issues (409 « À NOUS » avec id / 409 homonyme
ÉTRANGER / création), write-ahead + relecture + inscription au REGISTRE
(reconnaissable à la réconciliation, supprimable). (4) **Index structurel
`idx_entity_type_action`** sur audit_trail — le registre est dérivé du
journal, lu par entity_type : sans lui, chaque garde balaierait le journal
entier après les 180 jours du module VIE (avertissement indexage Yaniv,
testé structurellement). 944 tests (+12), 3 mutations attrapées.
**US-B6 livrée (14/08)** : POST /admin/referentiels/pays — le refus
pédagogique de la story v1. Un des 4 pays cibles → **409 « existe déjà »**
avec le geste correct (activation US-B3) — le scénario « l'admin crée ce qui
existe » ne fabrique jamais un double ; un 5ᵉ pays → **422 avec la liste
exacte de la matière manquante** (8 matières, chacune avec sa raison :
régions, villes, quartiers, plan de numérotation, parts de marché,
patronymes, profils de revenus, quota), et RIEN n'est modifié (ni surcouche,
ni config-service — testé). L'ajout d'un 5ᵉ pays ACTIF reste Won't v1
(backlog canonique) → v2. **#26 est CLOS pour la v1.**
Domaine corrigé (Yaniv 14/08) : `simul.fintech4esg.com`.

## D-ter. FRONTEND — phase 1 (fondation) LIVRÉE le 14/08 au soir

Repo `simulator-frontend`, commit `f952121` poussé. Le tri est appliqué
(design system JJB gardé, 7 pages fintech + mockData SUPPRIMÉS, Zidane
abandonné). Livré : contrat login corrigé sur pièce (`mot_de_passe`, pas
`password`), session JWT réelle 4 h avec compte à rebours et expiration DITE,
Login US-A1 + mot de passe forcé US-A2 (4 états, erreur nommée, idempotence
UI), garde d'auth + ErrorBoundary, nav des 6 épopées avec la user story
affichée par écran (nav.ts = source unique), tableau de bord avec sonde
réelle GET /health, squelettes honnêtes phases 2→7, **PWA** (manifest,
icônes fidèles au logo JJB, coquille en précache, DONNÉES JAMAIS en cache,
toast de mise à jour). **CORS mesuré** : origine prod autorisée (preflight
200), localhost refusé → proxy vite dev/preview (VITE_API_URL vide en local).
**Preuves** : tsc strict 0 erreur, build vert, navigateur headless — login
rendu sans erreur console + test de bout en bout réel (mauvais identifiants
→ « Le backend a refusé : identifiants invalides », 401 nommé du backend
hébergé). Incident du jour : git local frontend corrompu par l'extinction de
la machine (4 objets vides) → restauré intégralement depuis GitHub, zéro
perte. Reste frontend : phases 2→8 (`docs/PLAN_FRONTEND.md` du repo).

**Complément (même soir)** — session qui survit au refresh (localStorage,
retour Yaniv : la plateforme déconnecte au F5, pas nous — testé au double
refresh), œil sur tous les champs mdp, US-A4 dite honnêtement dans l'UI
(commit `179ee04`). **PHASE 2 LIVRÉE (commit `6036971`)** : Tableau de bord
US-E1 réel (10 HealthDot avec latences, bannière service down, compteurs
KpiCard du dernier run, vide honnête « Mongo vierge », alertes d'intégrité,
auto-refresh 60 s sans clignotement) + Configuration US-B1/B2/B3 (vue
résolue avec tag d'ORIGINE par valeur, volumes bornés doublés en UI, seuls
les champs touchés partent au PUT, réponse = vue RELUE, chips pays avec
motif obligatoire + « config-service jamais appelé » dit, quotas EF-22/23
verrouillés avec exigence citée, 409 EF-55 en bannière nommée). 401 →
déconnexion propre partout (prouvé navigateur : jeton invalide → retour
login + motif + purge). Reste : phases 3→8.

**US-A4 v2 LIVRÉE ET DÉPLOYÉE (14/08 soir, commits `f4eeac4` backend +
`7084f79` frontend)** : reset par email via Mailjet (clés Yaniv) — code 8
chiffres/15 min/5 essais, 202 anti-énumération, refus générique 401, mot de
passe durable + session pleine. **Fait mesuré** : compte Mailjet
« temporarily blocked » (mj-0001) sur v3.1 mais v3 historique ACCEPTE →
client à repli automatique, envoi réel prouvé (2 emails de test vers
l'adresse validée du compte = celle de Yaniv ; il doit contacter le support
Mailjet pour débloquer v3.1). 962 tests verts. Serveur provisionné
(MAILJET_* ajoutées au .env, conteneur recréé, health 200, route 202 en
prod). **Logo réel intégré** (zip WhatsApp de Yaniv, variante F violet +
étoile verte) : favicon, icônes PWA, login, sidebar (commit `d7b53d1`).
Credentials Loader retrouvés et vérifiés serveur : `ak@finzuu.com` (.env,
must_change_password actif — Yaniv choisira le durable). Session
persistante au refresh + compte à rebours réel du jeton. **Délivrance
Mailjet CONFIRMÉE par Yaniv** (emails de test reçus).

**PHASE 3 FRONTEND LIVRÉE (14/08 nuit, commit `1003c5b`)** — les Runs, le
rite D-01 à l'écran : Préparer & lancer (Stepper 3 étapes, DRY seul,
rapport intégral colorisé TENU/VIOLÉ, empreinte D-10, « dernière occasion
de dire non », ConfirmDialog danger, 409 périmètre → retour structurel à
l'étape ①, reprise du rite après refresh) ; Progression (polling 3 s,
arrêt confirmé « FAILED terminal vrai ») ; Historique & recette
(append-only dit, détail paliers + rapport). Composants Stepper +
ConfirmDialog. Preuves : build vert + banc d'essai navigateur sur API
simulée au contrat (8/8 assertions). Reste frontend : phases 4→8.

**MAILJET — SMTP RELAY en voie principale (14/08 nuit, commit `7963515`)** :
le compte reste bloqué (mj-0001) sur l'API HTTP — y compris avec le 2ᵉ jeu
de clés fourni par Yaniv (qui n'a AUCUN expéditeur validé) — mais le relais
SMTP in-v3.mailjet.com:587 ACCEPTE (mesuré avec les 2 jeux). Ordre d'envoi :
SMTP → API v3.1 → API v3. Clés anciennes conservées (expéditeur validé) ;
bascule sur les nouvelles si Yaniv confirme réception de leur test. Action
Yaniv : faire débloquer le compte au support Mailjet.

**PHASE 4 FRONTEND LIVRÉE (14/08 nuit, commit `2987561`)** — Référentiels :
Géographie (arbre pays→région→ville→quartier, badges anti-corruption
« ↗ config-service » / « ⌂ chez nous » avec raison, 3 formulaires EF-02
par construction, sans-limite dit), Pays & Monnaies (CountrySelect ISO 54
pays qui pré-remplit, monnaie d'abord, matière-pour-générer affichée après
création — déclarer ≠ générer), Telcos (4 invariants doublés à la frappe,
somme INV-18 en direct), Catalogue (comptes exacts en KPI + 5 onglets).
Aide « comment ça marche » ajoutée sur Configuration (retour Yaniv — écran
encore jugé peu clair : dette UX notée, mode simple/avancé à concevoir).
Preuves : build vert + banc navigateur 8/8. Reste : phases 5→8.

**15/08 — FRONTEND HÉBERGÉ + CI/CD + PHASE 5 LIVRÉE.**
(1) **Hébergé** : `https://simul.fintech4esg.com` EN LIGNE (nginx statique,
vhost simul.conf : SPA fallback, assets immutable, sw.js no-cache ; autres
services du serveur vérifiés 200 depuis l'hôte). (2) **CI/CD frontend** :
CI (tsc strict + build + URL API prouvée dans le bundle) puis CD (clé ed25519
dédiée en secret, hôte par empreinte, rsync --delete vers
/var/www/loader-frontend en user apps, santé = l'index en ligne sert LE
bundle du build) ; main protégée (CI requise, force-push/suppression
interdits) ; chaîne prouvée : push → CI 32 s → CD 35 s → vérifié en ligne.
**Plus AUCUN déploiement depuis la machine de dev.** (3) **BUG Géographie
attrapé par CAPTURE navigateur** (les assertions texte le rataient) :
`surcouche.resume` est une CHAÎNE, le front faisait `'ajouts' in resume` →
TypeError → l'ErrorBoundary GLOBAL avalait tout le cockpit (l'impression
« plusieurs pages en erreur » de Yaniv). Fix : type corrigé + **PageBoundary
PAR PAGE** (un écran qui casse reste local, sidebar vivante). Même famille
attrapée sur `admin_annonce` (email-chaîne rendue caractère par caractère).
(4) **PHASE 5 (commit `14722a5`)** : Produit US-D2 (3 interfaces par
policy_type, invariants doublés à la frappe, marqueur DEMO_ annoncé, aperçu
= payload exact, fiche relue), Company US-D1 (ville choisie DANS le
référentiel EF-02, aperçu = fiche composée ~40 champs — le backend DRY
renvoie désormais la MATIÈRE composée, commit backend `823299b`, 962 tests),
Groupe Lot H (permissions VIVANTES avec familles DÉRIVÉES + recherche +
cochées-seules + cocher/décocher le filtré ; 409 à trois issues nommées).
(5) **Devise ISO 4217 CONNUE par pays** (demande Yaniv : CM→XAF pré-rempli,
carte Monnaie pré-remplissable). (6) **Mot de passe Super-Admin réinitialisé**
(l'ancien bootstrap ne marchait plus — changé à la 1ʳᵉ connexion puis perdu) :
`scripts/reinitialiser_admin.py` dans le conteneur, login 200 vérifié.
(7) **RESPONSIVE réel (même soir, commit `6edc666`)** — mesuré avant de
corriger : à 390 px la sidebar en flux laissait 160 px au contenu. Sous
768 px elle devient un TIROIR superposé (fermée par défaut, hamburger,
backdrop, se referme à la navigation) ; banc 390/768/1366 vert, desktop
inchangé, zéro débordement X. (8) **VERSIONNING de la webapp** (demande
Yaniv) : source unique package.json (SemVer), injectée AU BUILD avec le
commit court, affichée bas de sidebar + login (« Loader v0.5.0 · abc1234 »),
CHANGELOG Keep-a-Changelog, **tag v0.5.0** ; v1.0.0 quand les 8 phases
seront tenues.
(9) **RBAC (décision Yaniv 15/08) : Super-Admin est un RÔLE multi-comptes**
(backend `6b45e10`, frontend `4f769cd`) — chaque personne a SON compte
(email RÉEL : le code US-A4 part vers l'email du compte), son mot de passe
changé librement SANS toucher les autres (bouton header à tout moment), son
cycle US-A2 propre. GET/POST /admin/comptes + PUT /{email}/etat :
désactivation réversible motivée (jamais de suppression — journal
attribuable), 401 générique pour un compte désactivé, gardes anti-lock-out
(jamais soi-même, jamais le dernier actif), write-ahead RUN_ADMIN. Écran
« Utilisateurs » : mot de passe initial généré affiché UNE fois + copie.
967 tests (+5). (10) **MAILJET — diagnostic verbatim CLOS** : le COMPTE est
bloqué (mj-0001) — v3.1 401 franc ; v3 « Sent »+MessageID puis **404 sur ce
même ID** ; SMTP accepte (250) puis journal du compte VIDE ; compteurs À VIE
à zéro ; expéditeur validé actif, login SMTP accepté. Nos clés et notre
chaîne (SMTP→v3.1→v3) sont bonnes — **action Yaniv : faire débloquer le
compte au support Mailjet** ; l'UI de création de compte DIT quand l'email
n'est pas parti et donne le canal de secours (mot de passe initial remis en
main propre).
(11) **PHASE 6 LIVRÉE (soir, commit `0d1d086`)** — les 5 écrans :
Écosystème US-E2 (arbre pliable, comptes du run), Population US-E3+P-01
(MESURE/CIBLE par pays, histogramme des soldes avec la frontière 150 000
EF-68 tracée, tranches ordonnées MÉTIER, top occupations, naissances SD-6,
index inverse), Traçabilité US-E4 (verdict d'abord, orphelines des DEUX
registres), Inventaire (4 statuts = 4 couleurs, adoption A-13 multi-
sélection à issues par identifiant, DELETE d'un groupe à nous relu),
Purge US-F1/F2 (rite 2 temps, résidus avec verdicts, case explicite +
danger). États vides HONNÊTES avec le geste cliquable. (12) **Mongo serveur
EFFACÉE à la demande de Yaniv** (sauvegarde
`/data/db/sauvegarde-avant-purge-20260815.gz` dans le volume mongo) : elle
ne portait que son DRY d'essai + le compte admin ; bootstrap re-créé au
redémarrage, mot de passe durable REPOSÉ à l'identique
(`Diag!Loader-2026-08-15a`) — zéro changement pour lui.
(13) **PHASE 8 LIVRÉE + v1.0.0 TAGGÉE (nuit, commit `7dfcd65`)** — a11y
(:focus-visible global, prefers-reduced-motion, Échap sur dialogues avec
focus sur l'action SÛRE, lang du document dynamique FR/EN, aria), titre
d'onglet par page, noscript, README à l'état réel. **QA finale : 18/18
écrans vérifiés au navigateur sur le site EN LIGNE** (+ mobile 390 : tiroir,
zéro débordement). Release :
github.com/KuateAbdel/simulator-frontend/releases/tag/v1.0.0.
**LES 8 PHASES DU PLAN FRONTEND SONT TENUES — la webapp Loader est v1.0.0.**
(La v1.0.0 du BACKEND reste liée à la recette CR-01→12 / 2000 clients en
30 min — voir section C.)

## E. Backlog S4/S5 restant

| Tâche | État |
|---|---|
| INV-18 — MSISDN pondérés par parts de marché | ✅ 13/08 — le mécanisme existait (EF-27), la GARANTIE mesurée manquait : 4 tests de distribution (CM ±3 pts sur 46/43/3, les 4 pays ±3,5 pts, anti-uniforme, ancrage CR-03), mutation « tirage uniforme » attrapée |
| P-01 — index inverse (client→produit, client→kiosque) | ✅ 14/08 — le lien s'écrit À L'ÉCRITURE : `product_ids` sur le nœud CLIENT (produit d'entrée au rattachement EF-26, puis chaque PUT /subscribe confirmé, `$addToSet` idempotent, nœud absent = ALERTE jamais silence, reprise D-CLI-5 = vide jamais inventé) ; servi par GET /admin/dashboard/index-inverse (2 agrégations chez NOUS — jamais 20 requêtes paginées vers FinZuu), noms joints depuis les nœuds du run. 7 tests (+repo contre le vrai Mongo), 3 mutations attrapées |
| P-02 — plafonds KYC BCEAO | ⬜ s'écrit AVEC le module Vie |
| P-03 — float de l'agent | ⬜ s'écrit AVEC le module Vie |

## F. Les arbitrages qui n'appartiennent qu'à Yaniv

`A-05` (permissions 11 rôles) · `A-07` (profils comportementaux) · `A-11`
(proportion APPROVED/DECLINED) · `A-04` (persistance des prêts) · `A-08`
(désactiver un pays) · noms métier du catalogue + marqueur `short_name` ·
Agents compris ou en sus des 15-25 staff/pays. Recommandations écrites dans
`PLAN_SPRINTS.md` §3.4 et `A-05_PERMISSIONS_A_TRANCHER.md`.

**A-13 — TRANCHÉ par Yaniv le 14/08 (« c'est nous qui les avons créés ») et
LIVRÉ le jour même** : les 11 rôles D-09 préexistants sur user-service
(recon `docs/empirical/2026-08-14_recon_passive.md`) sont À NOUS —
`POST /admin/inventaire/groupes/adoption` les inscrit au registre : issue
PAR identifiant (adopte / deja_au_registre / introuvable — jamais un échec
global muet), intention ADOPTION journalisée sous RUN_ADMIN dont le RESULTAT
porte le group_id (la ligne exacte qu'aurait écrite la création si le
journal avait existé), relecture du registre, verrou EF-55. Après adoption
le groupe est a_nous PARTOUT : inventaire, DELETE individuel, purge —
prouvé par test de bout en bout. Autres faits de la recon : 6 pays en base
(`ca` minuscule hors-ISO + CV), doublon produit vivant (ANO-PRD-UNIQ-01
confirmée), réseau dev disqualifié (4-6 s/health, DNS instable) → C-0
validée par la mesure. 948 tests.
