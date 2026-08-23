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

**16/08 — LE COCKPIT DEVIENT COMPLET (journee entiere, decisions Yaniv).**
(1) UC-07 : US-D1 cree la LICENCE avec la company (trou ferme — le catalogue
restait FERME) ; licences consultables/attribuables par company A NOUS
(GET/POST .../licences, 409 deja licenciee, fenetre sim+30j). (2) US-D3
REFONDU conception Yaniv : le depositaire nait d'un QUARTIER + company A
NOUS — nom DEMO_Kiosque <quartier>, devise DERIVEE, coherence
company<->quartier (422 INCOHERENCE nomme), quartier=UN kiosque (409),
noeud d'arbre differe DIT. Ecran 2 champs, composition affichee.
(3) Inventaire DEPOSITAIRES (4 statuts, registre = org_hierarchy UNION
journal) + ETAT is_active visible et CHANGEABLE la-bas (PATCH status
mesure, verite D-DEP-8 portee, etranger permis par decision et DIT,
relecture prouvee) — l'invariant anti-fermeture REVISE (les noms mensongers
restent interdits). (4) TELCOS la-bas : GET telcos-config (15 reels, etat,
PORTEURS) + activer/desactiver derriere la garde des references inverses
(409 mesure — scenario ca/CI du 09/08) ; verite INV-18 dite (la generation
suit le classeur — exclusion des tirages = arbitrage separe A trancher).
(5) DEVISES la-bas : porteurs affiches (XOF: ca·SN·BF·CI en direct !),
« Tester la desactivation » rend le refus MESURE. (6) Apercu Company
MODIFIABLE en place (4 champs saisis + Recomposer — prouve) ; les composes
ne s'editent pas (fidelite au run, dit a l'ecran). (7) Base Mongo serveur
REMISE A ZERO (demande Yaniv, sauvegarde gardee), mot de passe durable
repose a l'identique. Lecon de discipline : un push est parti avant la
suite complete — la CI l'a BLOQUE (CD skipped), correction, revert de
doctrine documente. RESTE (recommandations validees par Yaniv, a livrer) :
variante d'apercu regenerable, diff payload<->relecture, scenarios nommes.

**16/08 (suite) — LES 3 RECOMMANDATIONS SONT LIVREES, bout en bout.**
(1) Variante d'apercu + scenarios nommes : backend `d568300` (session
precedente). (2) **DIFF PAYLOAD<->RELECTURE livre et DEPLOYE** (backend
`6d61029`, CI verte + CD 45 s) : la relecture (FRA-218) prouvait
l'EXISTENCE, le diff prouve la FIDELITE — `app/services/relecture.py`
(chemins pointes, egalite de VALEUR 3==3.0, bool marque, listes en CONTENU),
cable sur les 4 creations a l'unite ; company : payload CONTRACTUEL capture
par l'executeur (`rapport.payload_company`, jamais reconstruit) + vraie
RELECTURE ajoutee (la route rendait l'ECHO du POST) ; divergence = 201 qui
DIT, jamais une erreur — FRA-199 (`currency` perdue) se lit dans la reponse.
992 tests (+13), 2 mutations attrapees, la 3e a SURVECU et disait vrai
(branche morte supprimee). (3) **FRONTEND v1.1.0** (`3b5e27d`) : le chantier
non commite de la session precedente (variante 🎲, scenarios, DiffTable)
repris et complete — VERDICT DU BACKEND (l'autorite) affiche sur les 4
ecrans de creation, fiche RELUE rendue pour Company ; preuves : tsc strict,
build vert, banc navigateur 7/7 sur API simulee au contrat (verdict
infidele rendu, capture relue), CHANGELOG 1.1.0.

**20/08 — NOTIFICATIONS + TRAÇABILITÉ DES CONNEXIONS (demande boss), LIVRÉ
BOUT EN BOUT** (backend `2dbe6d7`, frontend `729dd8a`, CI/CD verts × 2).
Doctrine « comme Microsoft » : événement → destinataires PAR RÔLE
(Super-Admins actifs, jamais l'acteur) → canaux (in-app toujours, email si
sensible) ; informer ne casse JAMAIS l'action. Backend : modèle+collection
`notifications` (index destinataire), repository borné au destinataire,
service (compte_cree / role_change avec la personne visée dédoublonnée /
compte_desactive in-app+EMAIL / compte_reactive), routes GET/PUT
/admin/notifications (chacun ne voit QUE les siennes, 404 sinon, boîte
ouverte au Viewer — recevoir n'est pas un privilège) ; traçabilité :
`derniere_connexion` posée au login + remontée dans la fiche, chaque
connexion réussie inscrit Session/LOGIN au Journal sous RUN_ADMIN (tracer
ne bloque jamais le login, le 401 ne trace rien). Transport EMAIL : nouvelles
clés Mailjet du boss (Confluence 67665944, lecture seule), relais SMTP port
2525 confirmé (587 repli), envoi réel REÇU (confirmé Yann). 1038 tests
(+14). Frontend : cloche 🔔 header (badge non-lues sondé 30 s, panneau,
marquer lu/tout lu, rendu localisé FR/EN depuis type+donnees — le backend
n'envoie jamais une phrase) + colonne « Dernière connexion » (ou « jamais
connecté ») ; banc navigateur 10/10, captures relues. **ÉTAPE OPS FAITE le
soir même, en ops-as-code** (commit `7280021`) : le SSH direct depuis la
machine de dev étant refusé (classificateur de permissions — et c'est
conforme à la doctrine « plus rien depuis la machine de dev »), les 3
MAILJET_* sont passées en **secrets GitHub** et le CD **enforce le `.env`
serveur à chaque déploiement** (idempotent, sauvegarde unique, échec nommé
si un secret manque, empreinte sha256 tronquée au log). Preuves : log CD
`empreinte api-key en place : a47373825232` = l'empreinte de la NOUVELLE clé
calculée localement, santé OK, sonde reset 202, et un code de
réinitialisation RÉELLEMENT envoyé vers ak@finzuu.com depuis la prod
(20/08 ~19h, à vérifier en boîte). Plus jamais de dérive secrets/serveur.

**20/08 (nuit) — REFONTE NAV + COCKPIT MÉTIER (audit UX senior, demandes
JJB).** (1) **Audit du backoffice de la plateforme** au navigateur (login
ROOT sur web-app.test, sections/onglets parcourus jusqu'au pied de page) :
architecture BONNE (sidebar 8 entrées, Back-Office = 1 entrée → 4 sections
× onglets, gabarit table unique), finition FAIBLE (« Nouveau Prosuit »,
« Nouvelle Utilisateur », Logs = HTTP brut 479 884 lignes inutilisables,
colonnes désalignées, données de test crues) — on copie la structure, pas
la finition ; notre Journal d'intentions est SUPÉRIEUR à leurs Logs.
(2) **Sidebar Loader : 18 → 8 sections** (frontend `ffa5e62`) — Runs /
Observatoire / Entités / Référentiels / Inventaire & Purge deviennent des
sections à onglets (`SectionOnglets` générique), Journal déjà onglet
d'Administration (`1c9ab28`) ; identifiants de page FINS conservés
(navigation croisée intacte, PAGE_META : le header suit l'onglet actif).
Banc 14/14. **RÈGLE FERME : plus jamais d'entrée de sidebar — un onglet.**
(3) **Cockpit métier** (`d602622`) : « Santé de la plateforme », pictogramme
+ libellé bilingue par sonde (Utilisateurs & accès, Comptes & soldes,
Identité KYC…), zéro « -service » à l'écran, nom technique en infobulle,
bannière de panne en métier. Banc 16/16. (4) **Contrat frontend↔backend
VÉRIFIÉ : 66/66** chemins d'api.ts présents dans l'openapi.json DÉPLOYÉ
(+ 4 littéraux inventaire). CI/CD vertes, EN LIGNE, bundle prouvé.

**20/08 (nuit, VEILLE DE DÉMO) — PLUS JAMAIS DE `DEMO_` (décision direction,
catégorique) — backend v0.7.0 (`b9a981d`), frontend v1.2.1, DÉPLOYÉS.**
Doctrine A-13 étendue à TOUT : écriture 100 % métier (raisons sociales
composées forme+patronyme+activité, « Kiosque <quartier> », noms UC-08 tels
quels, short_name = code déclaré, staff `CM_TellerAgent_001`, nœud
« Client <msisdn> ») ; réversibilité PAR REGISTRE — **CR-07 redéfini** (nœud
distant sans id serveur = VIOLÉ) ; lecture rétro-compatible (inventaire
reconnaît le stock marqué d'avant, repli legacy du GET-avant-POST produits —
la reprise CR-03 ne double jamais un produit à nous). Preuves : 1 038 tests,
DRY_RUN 2000 propre, CI/CD verts × 2. **Sénégal vérifié suite signalement
Oti : SN ACTIF et complet sur config-service (14 villes, devise, telcos),
500 clients SN composés au DRY — RAS, demander à Oti le point précis.**
Alimentation des comptes CONFIRMÉE dans le code : solde initial client =
POST /accounts/credit (DEPOSIT/MOMO/SELF, montant LogNormal par profession
EF-73/EF-68) puis solde RELU ; dotation Lender = INVESTMENT/BANK/LENDER.

**21/08 (matin, JOUR DE DÉMO) — PRÉ-VOL à la confirmation (exigence Yaniv),
backend `b707fce` DÉPLOYÉ.** POST /confirmer franchit 4 portes : préparation
connue (404) · terminée et lue (409) · périmètre inchangé (409) · **PRÉ-VOL :
les 10 sondes répondent à l'instant T, sinon 503 qui NOMME les pannes et
« RIEN n'est parti »** (réutilise LA sonde E1 — une seule vérité). Frontière
des mécanismes : pré-vol = mort AVANT départ ; retry D-USR-2 = hoquet EN VOL
(3 tentatives, backoff, transitoire seul — l'idempotence serveur mesurée
rend le rejeu sûr) ; write-ahead + réconciliation = le doute ; reprise =
l'interruption franche. Écran : 409 re-préparer → retour structurel à
l'étape ① ; 503 pré-vol → bannière avec le message nommé, l'étape ② reste
ouverte (re-confirmer sans re-préparer). 1 039 tests (+1, sondes doublées).

## D-quinquies. LE PREMIER RUN REAL EN PRODUCTION — 21/08, FAILED, disséqué et durci

**Le fait** : présentation du Loader à la direction le 21/08 (appréciée ;
consigne ferme : « jamais le mot démo — c'est un produit officiel interne »).
DRY_RUN 15h18 propre (PARTIAL attendu), REAL 15h29 confirmé → **FAILED à
DEPOSITAIRES en 4 min**. Audit du soir, lecture seule prod + code, trois
causes PROUVÉES :

1. **ORGANISATION 14/18** — email d'owner déterministe (`nom.nom@…`) dont
   l'unicité n'était garantie qu'EN MÉMOIRE DU RUN ; collision avec les
   résidus du 17/08 (`mbarga.mbarga@`, `ouedraogo.ouedraogo@` — prouvé sur
   user-service) → 400 « Identity with this email already exists ».
2. **CATALOGUE 4/6** — 422 reproduit sur pièce : « The fields measure and
   measure_price are required for PRODUCT collection policy » ; on envoyait
   `measure_price: 0.0` en dur (leur validation traite 0 comme absent —
   anomalie à remonter). Warrantage et Cacao ne pouvaient JAMAIS naître.
3. **DEPOSITAIRES FATAL** — `porteuses[imf_rang % len(porteuses)]` : avec
   14 IMF sur 18, le modulo repliait deux rangs sur la même company → deux
   Branches même (run, company, région) → E11000 sur NOTRE index →
   exception non rattrapée, run mort. CLIENTS/STAFF jamais tentés, Faker
   jamais appelé (registre clos à 0).

**Durcissement livré le soir même (chantier A)** : le rang de plan voyage
avec la porteuse (`CompanyPorteuse.imf_rang`) et le réseau d'une IMF absente
est **sauté et déclaré, jamais réattribué** (UC-07) ; `DuplicateKeyError`
rattrapée en échec nommé ; les adresses déjà prises sur user-service sont
**semées dans le générateur au lancement** (`reserver_emails`, une lecture —
owners, staff et clients immunisés d'un coup, DRY compris) ; `prix_mesure`
métier par produit PRODUCT (mil 240, cacao 1800 FCFA/kg) refusé à 0 dès la
construction ; erreurs COMPLÈTES (troncatures 160→600, rapport entier du
module persisté dans le checkpoint `resume`, trace d'exception incluse) ;
502 pays/devise relaye le refus réel de config-service ; journal admin :
**issue jointe** (l'échec du pays GN en séance s'affichait comme un CREATE
ordinaire) + **acteur** sur les intentions référentiels/entités/inventaire.
Tests : rejeu du crash en doublure d'index (le test meurt comme la prod si
la réattribution revient).

**Constaté aussi ce jour-là** : création pays GN par un collaborateur
direction — devise GNF créée (gardes anti-doublon OK, 1 seule malgré 3
tentatives), pays refusé par config-service, cause exacte à lire au replay
(le 502 muet est corrigé) ; 43 kiosques UC-09 sans agent laissés sur la
plateforme (pas de DELETE) — le prochain run les ADOPTE (GET-avant-POST
par nom, déjà en place). Chantiers ouverts : B (contrat inter-phases
généralisé), C1 (pays 100 % paramétrable dans la GÉNÉRATION — conception à
valider), C2 (balayage « demo » : 62 occurrences backend + frontend).

## D-sexies. C1 — LE LOADER MAÎTRE DE SES PAYS (22/08) + import des fichiers direction

**La décision (Yaniv, 22/08)** : le Loader est le System of Record — un pays
naît DANS le Loader (fiche complète : devise, TVA, fuseau, régulateurs — tout
ce que config-service n'a pas de champ pour porter) ; le pousser vers
config-service reste le geste VOLONTAIRE d'US-B6. Jamais d'import en masse
vers la plateforme.

**Livré** : `SurcoucheReferentiel.ajouter_pays` (l'« autre opération » promise
depuis le 14/08) — ISO2 unique, indicatif borné, TVA [0-40], devise JAMAIS
orpheline (forgée avec le pays si inconnue), retrait réversible qui emporte la
devise du dernier pays, `appliquer()` fusionne `pays_index` + devises, les
gardes région/telco reconnaissent les pays de surcouche (la chaîne
pays→région→ville→quartier→telco s'enchaîne entièrement en surcouche).
Persistance Mongo complète (frozenset devise inclus), relecture prouvée
identique. **+10 tests (1054).**

**Import des fichiers direction** (`scripts/importer_referentiel_pays.py`,
re-lançable, GET-avant-POST à chaque niveau) : `Import_pays.xlsx` (48 fiches)
TRAITÉ en senior data scientist — **7 MCC faux corrigés contre le plan UIT
E.212** (bloc décalé d'un cran : MG/ZM/MZ/BI/SC/GW/AO), accents FR restaurés
(« Erithre »→Érythrée), devises multi-valeurs LS/NA tranchées (LSL/NAD),
décimales ISO 4217 vérifiées, TVA et fuseaux comblés (48/48, 8 taux marqués
« à confirmer »), 8 regex telco réécrites dans NOTRE grammaire et validées
par le composeur réel, espaces/NBSP/tabulations purgés, CV absent de la
feuille telco relevé + `afrique_ouest_centrale_pays_villes_1.csv` (24 pays,
563 lignes, 0 doublon). **Résultat en base locale (surcouche v10) : 44 pays ·
259 régions · 461 villes (232 avec GPS réel, ±0,01°) · 128 quartiers RÉELS
(communes officielles : Kaloum, Gombe, Poto-Poto…) · 34 devises. 0 refus
d'invariant.** Les 4 cibles restent au classeur. Fichiers traités versionnés
dans `docs/reference/`.

**Trous DITS, jamais inventés** : 22 pays (Est/Sud) sans géographie (hors
CSV `_1` — d'autres fichiers annoncés), 441 villes sans quartier (US-B4),
0 telco importé (le fichier n'a NI parts de marché NI regex composables
hors les 8 réécrites — INV-18 refuse, on ne contourne pas). **Reste C1
lot 2** : patronymes par pays + porte d'activation « matière complète » +
planification au-delà de `PAYS_CIBLES` — alors seulement un pays importé
devient GÉNÉRABLE. Et rejouer l'import SUR LE SERVEUR après déploiement
(la surcouche v10 est locale).

## D-septies. AUDIT PROD 22/08 + les 4 bugs de conception C1 corrigés

**Batterie QA sur la PROD** (`simul.api.fintech4esg.com`, Super-Admin réel) :
login 200 · E1 10/10 sondes UP (~350 ms) · 6 tests négatifs PASS (gardes
422/409 exactes, refus GN cite C1 — preuve que le déploiement est le bon) ·
3 écritures VRAIES PASS (ville Mbalmayo → surcouche serveur PUIS config-service
« envoyé » ; quartier Ndokoti/Douala ; telco Nexttel CM 5 %) · doublon refusé ·
journal admin avec **issue + acteur** vérifié en prod (durcissement du 21/08
opérant). **Import serveur REJOUÉ** (à blanc puis réel, via SSH+docker) :
surcouche prod v6 = 44 pays · 259 régions · 462 villes · 129 quartiers ·
34 devises — GN complet (8 régions, Conakry et ses 5 communes, GPS).

**4 bugs de conception attrapés par l'audit, corrigés en ADDITIF (+5 tests,
1059)** : BUG-C1-01/02 `POST /pays/fiche` crée le pays DANS le Loader (le
push US-B6 reste volontaire et inchangé) · BUG-C1-03 `GET /pays` liste les
48 fiches avec complétude + présence config-service, et `/geographie` montre
désormais les pays SANS régions (l'écran n'affichait que 24/48) · BUG-C1-04
`DELETE /surcouche/{id}` expose la réversibilité CFG-03 (gardes anti-orphelin,
classeur immuable → 404).

## D-octies. LA DOCTRINE OPÉRATIONNELLE (22/08, Yaniv) — plus AUCUN verrou statique

**Le principe posé par Yaniv** : le Loader PORTE l'information (il peut porter
le globe) ; ce qui est EN OPÉRATION, c'est ce qui existe sur la plateforme —
aucun marqueur artificiel, l'état opérationnel EST la présence sur
config-service, vérifiée en direct. Les 4 pays cibles étaient le PREMIER
USAGE, jamais une constante de conception. Système fluide, dynamique à
l'extrême, MAIS tous les invariants de la vraie vie tenus (EF-02 intact).

**Verrous statiques levés** : `Literal["CM","CI","BF","SN"]` de la company à
l'unité → porte dynamique `_exiger_pays_operationnel` (fiche au Loader + EN
OPÉRATION + matière : patronymes, telco, villes — refus 422 qui NOMME chaque
manque, 503 si config-service muet : zéro-trust, on ne crée pas à l'aveugle) ·
US-B3 admet un pays HORS des 4 au périmètre (mêmes conditions + ≥1 quartier,
D-03) · la planification Organisation étend l'ordre CDC (les rangs des 4 ne
bougent pas — ENF-15) · `valider_nationalite` paramétrable (défaut = 4) ·
l'écart au CDC DIT toute extension de périmètre (CR-09 honnête) · l'exécuteur
company reçoit le référentiel APPLIQUÉ (classeur+surcouche, plus le classeur
seul).

**Consolidation des routes pays (décision : « des doublons, on arrête »)** +
**suppression de la création manuelle** (« pas de l'automatisation, c'est
lourd ») : les pays entrent dans le Loader UNIQUEMENT par l'import backend
(fichiers versionnés → script, invariants ligne à ligne). Surface finale :
`GET /pays` (fiches+complétude+opération — matière du globe, points
clignotants = présents des deux côtés) · `POST /pays/{iso}/pousser` (mise en
opération depuis NOTRE fiche : devise créée là-bas si absente, villes du
référentiel — rien n'est ressaisi, refus complet relayé, idempotent) ·
`DELETE /surcouche/{id}` · US-B4/B7 régions/villes/quartiers/telcos INTACTS.
L'ancienne `POST /pays` (payload ressaisi vers config-service) est supprimée.
Tests réécrits : 1062.

## D-nonies. LE GLOBE AFRIQUE + complément de géographie (22/08 soir)

**Globe en PROD dans l'écran Géographie** (frontend `dda65bb`→`d042a10`) :
fond Natural Earth 1:50m (frontières réelles — les tracés Google sont
propriétaires), tokens FinZuu, i18n FR/EN, tooltips, reduced-motion, états
VIVANTS depuis `GET /pays` — un pays qui clignote est EN OPÉRATION (présent
des deux côtés, vérifié en direct). **Le dynamisme s'est prouvé seul : le
globe affiche 5 pays en opération, pas 4 — il a détecté CV (Cabo Verde),
présent sur config-service depuis avant nous** (recon 14/08 : « ca/CV en
plus des 4 »). QA navigateur prod : login réel, 0 erreur console, un bug
visuel attrapé et corrigé (token `--background` inexistant → pays hors
référentiel rendus noirs).

**Complément de géographie « connaissance sûre »**
(`scripts/completer_geographie.py`, commit `033664d`) : 24 pays Est/Sud/MR
+146 régions (découpages officiels — 12 pays au découpage COMPLET),
+157 villes GPS réels, +60 quartiers officiels (CBD Nairobi, Kariakoo,
Bole, Sandton…) ; + les régions manquantes de l'audit (AO 2024, GQ
Djibloho, ML Taoudénit/Ménaka). Local v11, serveur v21. **État prod :
48 pays · 456 régions · 669 villes · 271 quartiers · plus AUCUN pays sans
géographie.** Reste hors matière : telcos (parts de marché à demander),
patronymes (C1 lot 2), fichiers `_2` de la direction à venir.

## D-decies. GeoNames + le globe final (22/08, fin de journée)

**Source de vérité installée : GeoNames** (geonames.org, CC-BY — le gazetier
mondial) : subdivisions admin1 officielles + toutes les villes ≥ 15 000 hab,
GPS et population. Extraits 48 pays versionnés (`docs/reference/geonames/`),
importeur à fusion soignée (`importer_geonames.py` : régions RÉUTILISÉES par
nom normalisé — 2311 correspondances, 170 créées ; 549 villes déjà connues
reconnues). **PROD v22 : 48 pays · 626 régions · 3 148 villes ·
271 quartiers — 2 920 villes aux coordonnées réelles.** 2 sauts déclarés
(admin1 ET/28 hors fichier).

**Globe finalisé en prod** (frontend `5e15101`) : marquages EXACTS de
l'artefact validé (mer bleue, vert clignotant, ambre, anneaux — palette
scopée clair+sombre, la page garde le chrome FinZuu) + vue table repliable
des fiches (état/devise/TVA/complétude, i18n). Dynamisme prouvé : le globe
a détecté seul CV en opération (présent sur config-service depuis la recon
du 14/08). QA navigateur prod : 0 erreur console.

## D-undecies. Le panneau config-service + vague 2 (22/08, clôture)

**Panneau de chargement config-service EN PROD** (frontend `bf0bf94`) : la
machine d'états d'un pays, vérifiée EN DIRECT — EN OPÉRATION (5) / PRÊT À
POUSSER (43, bouton depuis NOTRE fiche) / FICHE SEULE (0) / LÀ-BAS SEULEMENT
(**1 anomalie détectée et affichée : « CA »**, le résidu que la recon du
14/08 avait vu). `GET /pays` rend `hors_loader`. Création manuelle de pays
ET de monnaie SUPPRIMÉES (routes + écrans) — l'entrée est l'import backend ;
`pousser` forge la devise là-bas depuis notre fiche. Géographie épurée :
l'arbre et la recherche retirés, le globe + la vue table sont LA structure,
seul l'ajout de QUARTIER survit (aucune source mondiale ne les fournit).

**Vague 2 de la connaissance sûre** (`completer_quartiers_telcos.py`,
`5d2070b`) : +33 quartiers officiels (Plateau/Cocody à Abidjan, Katutura,
Rohero…) et **+38 telcos réels sur 13 marchés maîtrisés** — parts de marché
régulateurs/GSMA, plans de numérotation réels, CHAQUE ligne validée par le
composeur (38/38, longueurs conformes UIT contre-vérifiées, INV-18 ≤ 100
partout). Serveur v23. **Nexttel (défunt au Cameroun, erreur de ma batterie
QA) RETIRÉ de la prod via DELETE /surcouche — première utilisation réelle
de la réversibilité (v24, 38 telcos).** État final prod : 48 pays ·
626 régions · 3 148 villes · 272 quartiers · 38 telcos · 34 devises.

## E. Backlog S4/S5 restant

| Tâche | État |
|---|---|
| INV-18 — MSISDN pondérés par parts de marché | ✅ 13/08 — le mécanisme existait (EF-27), la GARANTIE mesurée manquait : 4 tests de distribution (CM ±3 pts sur 46/43/3, les 4 pays ±3,5 pts, anti-uniforme, ancrage CR-03), mutation « tirage uniforme » attrapée |
| P-01 — index inverse (client→produit, client→kiosque) | ✅ 14/08 — le lien s'écrit À L'ÉCRITURE : `product_ids` sur le nœud CLIENT (produit d'entrée au rattachement EF-26, puis chaque PUT /subscribe confirmé, `$addToSet` idempotent, nœud absent = ALERTE jamais silence, reprise D-CLI-5 = vide jamais inventé) ; servi par GET /admin/dashboard/index-inverse (2 agrégations chez NOUS — jamais 20 requêtes paginées vers FinZuu), noms joints depuis les nœuds du run. 7 tests (+repo contre le vrai Mongo), 3 mutations attrapées |
| P-02 — plafonds KYC BCEAO | ⬜ s'écrit AVEC le module Vie |
| P-03 — float de l'agent | ⬜ s'écrit AVEC le module Vie |

## D-duodecies. CAMPAGNE QA SUR LA PROD (23/08) — 45 cas réels, 4 défauts corrigés

Batterie jouée contre `simul.api.fintech4esg.com` et le config-service réel,
**aucune simulation** : 10 cas d'erreur (401/422/404) ✅, 16 cas
d'activation/désactivation ✅ (chaque geste vérifié par **relecture
indépendante** — ça agit vraiment ; la garde des références inverses refuse
`Moov Africa CI` en 409 sans effet de bord), 19 cas d'aller complet ✅
(**Guinée poussée pour de vrai** : GNF orpheline adoptée, 2 telcos créés +
rattachés, 48 villes ; re-poussée = idempotente, 0 doublon).

**4 défauts mesurés et corrigés (`46e88d1`)** : (1) la docstring publiée dans
le **Swagger de prod** annonçait un ordre FAUX (« devise → pays → telcos »
alors que le code fait « devise → TELCOS → pays ») ; (2) la porte « ≥ 1 ville »
n'existait pas — capitale vide → `cities: [""]`, ville fantôme **ineffaçable** ;
(3) devise/telcos créés avant le pays restaient **orphelins en silence** quand
le pays échouait (`AOA`, `GNF` mesurées ainsi) — le 502 les nomme désormais ;
(4) le refus de désactivation répondait « référencée par `[]` » à une devise
orpheline — message FAUX, remplacé par la vraie raison (aucun contrat de
réactivation mesuré → irréversible). +10 tests (1072).

**`GET /pays-config` — la relecture qui manquait** : on poussait sans jamais
pouvoir relire. Les 9 champs, villes, devise et telcos **résolus par nom** +
écarts (champs vides, villes absentes/fantômes, telcos absents, `hors_loader`).

**Ce qu'elle a révélé** : les 4 pays du CDC ne portaient que **12-14 villes**
là-bas contre 70-181 chez nous → **361 villes manquantes**, un run REAL aurait
planté. Complétées (SN +56, BF +62, CM +74, CI +169) : **5 pays sur 7 sans
aucun écart**. Restent `CV` (mauvaise devise `XAF` au lieu de `CVE`, 0 ville,
0 telco → arbitrage) et le parasite `ca`. **L'aller est SYNCHRONE** : CI
(169 villes) dépasse un timeout client de 60 s.

## D-terdecies. LA CONCEPTION « COHÉRENCE » C1→C7 (23/08, 2ᵉ partie)

**`I-CFG-SYNC` — la matière suit l'ÉTAT du pays** (règle Yaniv) : en
opération → envoi immédiat ; hors opération → `differe`, rien ne part, tout
partira au `pousser` ; plateforme muette → `indetermine` (l'absence et le
silence sont deux faits distincts). Un seul endroit dans le code.

**Livrés** : `I-CFG-SYNC` (`a4b5a20`) · **C1** anti-doublon par clé
normalisée — accents/casse/ponctuation, sur telcos, devises, pays ET villes
(`7665f24`) · **C3** 338 appels → 2 pour compléter un pays (`7665f24`) ·
**C6** `POST /pays/{iso}/rectifier`, réécriture complète car le serveur n'a
**aucun PATCH**, aperçu obligatoire + fusion de la matière des autres équipes
(`7665f24`/`0541693`) · **relais honnête** des pannes plateforme, 423 reste
423 (`7b9ee70`).

**Livrés aussi (fin de journée)** : **C2** verrou par ressource (409 immédiat,
TTL, verrou périmé repris ; prouvé en prod : 2 allers simultanés → `[200,
409]`) · **C4** `GET /coherence` (verdict, le pire l'emporte) **+ pré-vol qui
BLOQUE un REAL** si le périmètre a dérivé · **C5** `POST /synchroniser`
(aperçu/confirmation, idempotent) · **C7** `PATCH /pays/{iso}/etat` — sortir
d'opération et y revenir, avec garde et relecture. `6d25108`, `79f163b`.

**CV RECTIFIÉ sur la prod** (décision Yaniv) : `Cabo Verde`, `dial_code 238`,
devise **CVE**, 15 villes — la fiche portait `name/region/continent = "cm"`,
0 ville et `XAF`. **6 pays sur 7 sans aucun écart** ; reste le parasite `CA`,
qui n'appartient pas au Loader.

**Deux bugs graves attrapés** : le telco d'un pays hors opération était créé
là-bas puis orphelin définitif ; et l'aperçu de rectification ÉCRIVAIT (il a
créé `CVE`). Les deux corrigés et prouvés en prod.

## F. Les arbitrages qui n'appartiennent qu'à Yaniv

**A-14 — TRANCHÉ par Yaniv le 23/08 et APPLIQUÉ** : la fiche `CV` du
référentiel PARTAGÉ a été rectifiée (« tout doit être consistent et cohérent,
pas de mauvaise devise »). · `A-05` (permissions 11 rôles) · `A-07` (profils comportementaux) · `A-11`
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
