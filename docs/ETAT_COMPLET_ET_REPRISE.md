# ÉTAT COMPLET & REPRISE — Loader FinZuu (backend + frontend)

> Écrit le 14/08/2026 sur ordre de Yaniv, pour ne RIEN perdre de la session.
> Versionné sur GitHub (survit à l'extinction de la machine). Détaillé, pas
> un résumé. Deux projets : **backend** (déployé, en ligne) et **frontend**
> (en construction). Tout ce qu'il faut pour reprendre est ici.

---

## SESSION DU 24/08/2026 — L'HONNÊTETÉ DES ÉCRANS (lire EN PREMIER)

**Backend + frontend, ~10 commits, CI et déploiements verts. 1140 tests.**
Fil conducteur d'une exigence de Yaniv : *« le système doit être vrai, pas de
fake, aucune incohérence »*.

### Ce qui a été livré

| # | Chantier | Où |
|---|---|---|
| `V-01` | **Onglet Versions** — ce que chaque service PORTE, et surtout ce qui a CHANGÉ. Relevé par `openapi.json`, TTL 3 h à la lecture (pas de tâche de fond), verrou C2 contre la double sonde. Le pire cas détecté : des chemins qui bougent **à version identique** | back + front |
| `V-02` | **Le bouton « Pousser » ne ment plus** — la règle est écrite UNE fois (`_porte_d_operation`), consommée par la porte ET par `GET /pays` (`poussable`, `manques`) | back + front |
| `V-03` | **Écosystème à CINQ niveaux** — pays › IMF › branche › agence › kiosque, agrégats par ligne, identifiants résolus en NOMS, anomalies nommées, treemap de charge, 3 mesures (concentration + Gini + référence, couverture bornée au périmètre, intégrité), **couverture inverse** (quartiers libres) | back + front |
| `V-04` | **Dates de création** dans l'inventaire et la purge, depuis le journal d'audit. `null` = pas de nous, jamais une date inventée | back + front |
| `V-05` | **Pays et état actif des companies** — `country_code` de `lenders_registry`, `is_active` de la fiche plateforme | back + front |
| `I-ENT-1` | **INVARIANT** : on ne crée une entité que dans un pays EN OPÉRATION. Inscrit dans `DISCIPLINES.md` avec ses **deux faces** | back + front + doc |
| `P-04` | **Liste des clients filtrable** (pays + sexe + profession), profil rangé à l'écriture, 2 requêtes Mongo, zéro appel FinZuu | back + front |
| — | **Cascade** pays › région › ville › quartier sur le formulaire Dépositaire ; companies filtrées actives + du pays | front |
| — | Recherche rapide + index A-D/E-H + pagination sur Géographie, Pays & Devises, Telcos ; zoom cartographique du globe | front |

### Les bugs trouvés — et comment

**Aucun ne produisait d'erreur.** Tous sont sortis d'une capture d'écran ou
d'une mesure, jamais du build ni des tests.

1. **`--danger`, `--warning`, `--success` n'existaient pas** dans le thème
   FinZuu. Chaque `var(--danger)` était une propriété INVALIDE, donc ignorée :
   tuile transparente, texte blanc sur blanc. Même piège que `--background` le
   22/08. **Audit complet ensuite : les 33 tokens utilisés sont tous définis.**
2. **Un canal par variable** — la carte de charge repeignait la tuile ENTIÈRE
   en rouge dès qu'UN kiosque avait un défaut : 6 tuiles sur 8 rouges pour
   4 kiosques sur 54. La teinte porte l'institution, un bandeau porte le défaut.
3. **`COUVERTURE 12 / 3156`** — le dénominateur était le référentiel des
   48 pays alors que le run n'en touche que 4. Un ratio qui faisait passer une
   couverture correcte pour un échec.
4. **La liste des pays figée à 4** dans l'écran Company, deux jours après que
   le backend eut retiré le verrou. Six pays s'affichent maintenant.
5. **L'arbre ne se confrontait à rien** — voir ci-dessous.
6. **Ma propre borne de temps ne bornait rien** : `wait_for(f(await g()))`
   évalue `await g()` AVANT que le délai ne l'enveloppe (49 s de tests au lieu
   de 4).
7. **Le quatrième état oublié** : pendant le chargement, le select des pays
   restait vide ET muet — ce qui se lit comme une panne.

### L'ARBRE SE CONFRONTE AU RÉEL (la question de Yaniv qui a le plus compté)

*« Si je purge la base, plus rien ne s'affiche, n'est-ce pas ? »* — **NON, et
c'était un mensonge par omission.** `org_hierarchy` est notre mémoire d'un run ;
la purge n'y touche pas, et la plateforme peut être vidée de son côté.

`GET /ecosysteme` confronte désormais ses Kiosques à depositary-service, par la
MÊME réconciliation que l'écran Inventaire. Trois issues :

- tout existe → *« chaque Kiosque de l'arbre existe encore sur la plateforme »*
- base vidée → bandeau rouge : *« cet arbre décrit un état PASSÉ »*
- service muet → *« arbre NON vérifié »*, et l'intégrité écrit **`?`**, jamais
  `0` — un `0` serait une affirmation qu'on n'a pas mesurée

### La règle qui a guidé toute la journée

**Ce qu'on ne sait pas, on le DIT.** `null` n'est jamais comblé par un défaut
plausible : pas de date = pas de nous ; pas d'état = état inconnu ; pas de
mesure = « non vérifié ». Chaque fois, un test verrouille les deux branches.

---

## SESSION DU 23/08/2026 — CAMPAGNE QA SUR LA PROD (lire EN PREMIER pour reprendre)

**Aucune simulation : 45 cas joués contre `simul.api.fintech4esg.com` et le
config-service réel.** Commit `46e88d1`, CI + CD verts, 1072 tests.

### Ce qui a été MESURÉ (pas supposé)
* **Cas d'erreur : 10/10.** 401 sans jeton / jeton bidon, 422 pays inconnu,
  422 pays sans telco (AO, `ga` minuscule), 404 telco inconnu, 422 activation
  de devise, 422 corps invalide. Aucune écriture parasite.
* **Activation / désactivation : 16/16 — ça AGIT vraiment.** Chaque geste
  vérifié par **relecture indépendante** de config-service, pas par la réponse
  de la route. `Vodafone Egypt` désactivé → `is_active=false` mesuré → réactivé
  → état restauré. `PROBE_TELCO_0317` activé → mesuré → remis inactif.
  **La garde des références inverses tient** : `Moov Africa CI` (porté par `CI`
  ET le parasite `ca`) → 409, aucun effet de bord. Devises : désactivation
  refusée, XOF et GNF restent actives.
* **Aller complet : 19/19.** La **Guinée poussée pour de vrai** : devise GNF
  (orpheline, adoptée), 2 telcos créés puis rattachés, 48 villes. Re-poussée :
  `deja_en_operation`, 0 doublon, 0 ville re-envoyée.

### Les 4 défauts trouvés et corrigés (`46e88d1`)
1. **Le Swagger de prod mentait sur l'ordre** : docstring « devise → pays →
   villes → telcos » alors que le code fait « devise → **TELCOS** → pays »
   (les UUID l'imposent). Contrat faux affiché au frontend.
2. **La porte « ≥ 1 ville » n'existait pas** : `villes or [capitale]` avec une
   capitale vide envoyait `cities: [""]` — ville fantôme **ineffaçable**
   (config-service n'a aucun DELETE sur les villes). 422 qui nomme la matière.
3. **Résidus orphelins tus** : devise et telcos sont créés AVANT le pays ; si
   le pays échoue, ils restent sans pays. `AOA` et `GNF` traînaient ainsi. Le
   502 les NOMME désormais + dit le geste de rattrapage.
4. **Message de refus faux** : une devise orpheline se voyait répondre
   « référencée par `[]` ». Elle dit maintenant la vraie raison (aucun contrat
   de RÉACTIVATION mesuré → geste irréversible). Vérifié en prod sur `00`,
   `AOA`, `ZZ15`, `cv`.

### `GET /pays-config` — la relecture qui manquait
On pouvait POUSSER un pays sans jamais RELIRE ce qui avait atterri là-bas
(le panneau couvrait telcos et devises, pas les pays). Pendant de
`/telcos-config` : les 9 champs, villes, devise et telcos **résolus par nom**,
écarts mesurés (champs vides, villes absentes, villes fantômes, telcos
absents, `hors_loader`).

### Ce que la relecture a révélé — et l'action menée
Les 4 pays du CDC portaient **12 à 14 villes** là-bas alors que le Loader en
a 70 à 181 : **361 villes du Loader n'étaient PAS sur la plateforme.** Un run
REAL aurait planté sur toute ville inconnue. Pilote sur SN (56 villes, 0
échec, relecture 70/70), puis BF (+62), CM (+74), CI (+169).
**Résultat : 5 pays sur 7 sans AUCUN écart** (BF, CI, CM, GN, SN).

### Ce qui RESTE cassé (arbitrage Yaniv)
* **CV (Cap-Vert)** : en opération avec **la mauvaise devise** — `XAF` là-bas,
  `CVE` dans notre fiche —, `dial_code` vide, 0 ville (15 chez nous), 0 telco
  au référentiel. Le poussé est refusé par la porte (aucun telco). Une
  correction est techniquement possible (`PUT /countries/{id}` prend les 9
  champs, mécanisme déjà utilisé par `ajouter_ville`) mais **change une fiche
  du référentiel PARTAGÉ** : décision Yaniv.
* **`ca`** : pays parasite, hors Loader, `dial_code` vide — connu depuis le
  14/08, toujours là.
* **Résidus partagés** : telcos `DEMOQA081738057_BADRGX`, `PROBE_TELCO_0317`,
  `cm`, `MTNcongo1` ; devises `00`, `ZZ15`, `cv`, `AOA`. Aucun DELETE n'existe.
* **L'aller est SYNCHRONE** : pousser CI (169 villes) a dépassé un timeout
  client de 60 s (le serveur, lui, a terminé). Le frontend doit prévoir la
  marge — ou l'aller doit devenir asynchrone.

---

## SESSION DU 23/08 — 2ᵉ PARTIE : LA CONCEPTION « COHÉRENCE » (C1→C7)

Règle posée par Yaniv après la campagne QA, et **codée comme invariant
unique** (`I-CFG-SYNC`) : la matière s'écrit TOUJOURS chez nous ; elle ne part
là-bas **que si le pays est EN OPÉRATION**, sinon elle attend le `pousser`.

| # | Chantier | État |
|---|---|---|
| `I-CFG-SYNC` | pays en opération → envoi immédiat ; hors opération → `differe` (jamais « échec ») ; plateforme muette → `indetermine` | ✅ `a4b5a20` |
| C1 | anti-doublon par **clé normalisée** (accents, casse, ponctuation) sur telcos, devises, pays, villes | ✅ `7665f24` |
| C3 | **338 appels → 2** pour compléter un pays (`ajouter_villes`, un seul PUT) | ✅ `7665f24` |
| C6 | `POST /pays/{iso}/rectifier` — réécriture complète (le serveur n'a **aucun PATCH**), aperçu obligatoire, fusion de la matière des autres équipes | ✅ `7665f24` + `0541693` |
| — | une panne plateforme est **relayée** (423 reste 423), plus de 500 muet | ✅ `7b9ee70` |
| C2 | **verrou par ressource** — 409 immédiat, TTL, verrou périmé repris ; posé sur pousser, rectifier, /telcos, /villes | ✅ `6d25108` |
| C4 | **`GET /coherence`** rend un verdict (`coherent`/`derive`/`anomalie`, le pire l'emporte) + **pré-vol qui BLOQUE un REAL** si le périmètre a dérivé | ✅ `6d25108` `79f163b` |
| C5 | **`POST /synchroniser`** — tous les pays en opération d'un geste, aperçu puis confirmation, idempotent | ✅ `6d25108` |
| C7 | **`PATCH /pays/{iso}/etat`** — sortir d'opération et y revenir, avec garde (refus si le pays est ACTIF dans la configuration) et relecture | ✅ |

### Résultat MESURÉ sur la prod (fin de journée)
* **CV rectifié** : `Cabo Verde`, `dial_code 238`, devise **CVE**, 15 villes —
  la fiche portait `name/region/continent = "cm"`, 0 ville, devise `XAF`.
* **6 pays sur 7 sans aucun écart** (BF, CI, CM, CV, GN, SN). Reste `CA`, le
  parasite hors Loader — il ne nous appartient pas.
* Sonde stable sur 3 tours ; synchronisation : **0 pays à synchroniser** ;
  verrou prouvé en conditions réelles (2 allers simultanés → `[200, 409]`).

### Deux bugs graves attrapés — dont un dans MON code
1. **Telco orphelin** : ajouter un opérateur à un pays **hors opération** le
   créait quand même là-bas (`creer_telco_si_absent` partait avant la
   résolution du pays), puis le rattachement échouait. Orphelin **définitif**
   dans le référentiel partagé. Reproduit, corrigé, prouvé en prod (KE).
2. **L'aperçu écrivait** : un simple aperçu de rectification a **créé la
   devise `CVE`** (7 → 8) avant de tester `confirmer`. Corrigé ; 3 aperçus en
   prod ⇒ 0 création.

### Incident plateforme (pas nous)
`config-service` a répondu **`HTTP 423`** à notre `POST /auth/login` (compte
ROOT **partagé**). Le disjoncteur `INV-USR-19` a tenu bon (~9 min sans
retenter, pour ne pas aggraver). Nos écrans rendaient un **500 muet** →
corrigé. Revenu à 200 tout seul, vérifié sur 3 tours.

### `CV` — un pays en opération ENTIÈREMENT corrompu (mesure)
Ce n'est pas « juste la mauvaise devise » : `name_en = name_fr = region =
continent = "cm"`, `dial_code` vide, **0 ville**, devise `XAF` au lieu de
`CVE`, et le telco `MTNcongo1` (motif `6|333`, non ancré). L'aperçu de
rectification est prêt et prouvé sans écriture — **la confirmation appartient
à Yaniv** (A-14, réécriture d'une fiche du référentiel PARTAGÉ).

---

## SESSION DU 22/08/2026 — LA JOURNÉE RÉFÉRENTIEL PAYS (lire EN PREMIER pour reprendre)

**Marathon complet, ~14 commits backend + 4 frontend, tout CI verte + déployé.
État final : backend surcouche serveur v26, frontend `78921ce`+.**

### 1. Durcissement post-mortem du 1er run REAL (21/08) — commit `9bef2bb`
Les 3 causes du crash ne peuvent plus tuer un run : DEPOSITAIRES ne réattribue
plus jamais le réseau d'une IMF absente (sauté+déclaré, UC-07), DuplicateKeyError
rattrapée ; emails pris semés au lancement (`reserver_emails`) ; `prix_mesure`
métier (mil 240, cacao 1800). Erreurs 600c, journal admin issue+acteur (vérifié
en prod). CR-01 de la recette était CODÉ EN DUR → mesure réelle (`63c19fe`).

### 2. C1 — le Loader maître de ses pays + fichiers direction (`c2a1cd6`)
Doctrine Yaniv : le Loader PORTE (peut porter le globe) ; l'OPÉRATION = présence
sur config-service, vérifiée EN DIRECT, aucun marqueur. `ajouter_pays` dans la
surcouche (devise jamais orpheline, retrait réversible). Fichiers du boss
TRAITÉS en data scientist : `Import_pays.xlsx` (48 fiches — 7 MCC faux corrigés
plan UIT, accents, TVA/fuseaux comblés, 8 regex réécrites) +
`afrique_ouest_centrale_pays_villes_1.csv` (24 pays, 563 lignes ; le `_1`
annonce des suites). Import re-lançable `scripts/importer_referentiel_pays.py`,
versionné `docs/reference/`. JAMAIS vers config-service (push = geste US-B6).

### 3. Audit QA prod + 4 bugs de conception corrigés (`0a3e87f`)
Batterie prod (login réel ak@finzuu.com) : gardes 422/409 exactes, écritures
VRAIES (Mbalmayo→surcouche PUIS config-service « envoyé », Ndokoti, telco),
journal issue+acteur. 4 bugs : GET /pays (fiches+complétude+sur_config_service),
POST /pays/fiche, DELETE /surcouche/{id} (réversibilité CFG-03), /geographie
montre les pays sans régions (l'écran cachait 24/48). Bug telco-retrait attrapé
par batterie destructive → corrigé (`6045e36`), cycle Égypte complet, base propre.

### 4. Doctrine opérationnelle — plus AUCUN verrou statique (`a31c9fa`)
Literal["CM","CI","BF","SN"] RETIRÉ de la company → porte dynamique
`_exiger_pays_operationnel` (fiche Loader + EN OPÉRATION vérifié live + matière :
patronymes, telco, villes — 422 qui NOMME les manques, 503 zéro-trust si
plateforme muette). US-B3 admet un 5e pays (matière complète + quartier D-03).
Planification : ordre CDC + extras (rangs des 4 intacts, ENF-15).
`valider_nationalite` paramétrable. Écart au CDC dit toute extension (CR-09).
CONSOLIDATION routes : POST /pays (création manuelle) SUPPRIMÉ — entrée pays =
IMPORT BACKEND uniquement (décision direction) ; POST /pays/{iso}/pousser part
de NOTRE fiche (devise créée là-bas si absente, villes du référentiel,
idempotent) ; GET /pays sert le globe. Création manuelle de MONNAIE aussi
SUPPRIMÉE (`0a7984e`) + `hors_loader` (4e état : là-bas mais inconnu → anomalie
MONTRÉE — détecte le résidu « ca/CA » de la plateforme).

### 5. Le GLOBE AFRIQUE (artifacts + frontend prod)
Artifacts : rapport https://claude.ai/code/artifact/b4dfe0b3-2939-4811-8cb7-6c34cbb2c64a
· globe https://claude.ai/code/artifact/38f446f0-e116-4be3-b1ff-9655dc7d68ba
Frontend : GlobeAfrique.tsx dans l'écran Géographie — Natural Earth 1:50m
(src/data/afrique-frontieres.json), états LIVE depuis GET /pays (vert clignotant
= EN OPÉRATION — a détecté CV tout seul), palette de l'ARTEFACT (scopée
clair/sombre), tuiles réelles, vue table, i18n FR/EN, reduced-motion.
Panneau « Pays & Monnaies » REFONDU = machine d'états + bouton Pousser +
anomalies + devises là-bas (formulaires de création supprimés). Géographie
ÉPURÉE : arbre + recherche SUPPRIMÉS (le globe est LA structure), seul l'ajout
de QUARTIER survit (aucune source mondiale ne les fournit, D-03).

### 6. GeoNames + compléments de connaissance sûre
`importer_geonames.py` (extraits 48 pays versionnés docs/reference/geonames/,
CC-BY) : +2481 villes → 3 148 villes GPS/population officielles.
`completer_geographie.py` : 24 pays Est/Sud/MR (+146 régions officielles,
+157 villes GPS, +60 quartiers). `completer_quartiers_telcos.py` : +33
quartiers officiels + **38 TELCOS RÉELS sur 13 marchés** (NG GH KE TZ UG RW
ZA GN ZM MZ CD ET MW — parts régulateurs/GSMA, plans composables validés par
le moteur 38/38, longueurs UIT contre-vérifiées). Nexttel (défunt au CM,
erreur de ma batterie) RETIRÉ via DELETE /surcouche.

### 7. LES LEÇONS DE YANIV (fautes à ne JAMAIS refaire)
- « Le Cameroun a 17 régions ?! » : GeoNames livre l'ANGLAIS (Far North,
  North Kivu...) → 14 doublons de traduction sur 5 pays. Règle de GÉOGRAPHE :
  NORMALISER À L'INGESTION → `scripts/normalisation_geo.py` = LA norme
  partagée (clé traduite, ordre trié) ; fusion réparatrice `a79a48d`+`dbcc6b1`.
- RÉCONCILIATION contre les listes OFFICIELLES (`dbcac13`) : 63 actions —
  renommages (Elgeyo-Marakwet, Cubango 2024, County/Region collés), fusions
  d'orthographe (Atacora/Atakora, FCT, Luanda Norte=Lunda Norte...), Somalie
  redescendue au niveau région, ajouts des manquants (Bomet, Tagant,
  Nouakchott Sud, Kavango West, Kunene, Omusati, Bakool, Kgalagadi, Chobe).
  **11/11 pays aux décomptes officiels, 0 orpheline. MANQUANTS ≠ DOUBLONS.**
- `mypy | tail` AVALE le code d'échec → toujours tester les codes retour
  AVANT commit (2 pushes fautifs ce jour).
- Vérifier AVANT d'envoyer ; auditer soi-même ; données confrontées au
  terrain ; trous DITS jamais inventés ; pas le mot « démo ».

### 8. INCIDENT PLATEFORME (résolu en séance)
~12h30 : compte ROOT partagé VERROUILLÉ (HTTP 423 login attempts) — /health
vert mais données refusées. Le Loader n'a PAS subi : portes → 503 zéro-trust,
écran → null. Déverrouillé ensuite ; RE-TEST COMPLET OK : lister_pays rend
6 pays (BF CI CM CV SN + « ca »), GN → 422 pédagogique, CM → aperçu
« SARL Mbarga Microfinance » à Mbalmayo. NE JAMAIS boucler les logins.

### 9. RESTE À FAIRE (la reprise)
1. **C1 lot 2 — rendre un 5e pays GÉNÉRABLE** : patronymes par pays dans la
   surcouche + porte déjà en place ; alors GN sera poussable et générable.
2. Telcos des ~31 marchés restants (matière boss/régulateurs) ; fichiers `_2`
   direction ; quartiers hors capitales ; CI 33 régions (arbitrage direction).
3. Anomalie « ca/CA » sur config-service : à nettoyer côté plateforme (Oti).
4. Prochain run REAL depuis le serveur (code durci déployé) ; puis 2e run
   identique = preuve CR-03.
5. Synchro villes → config-service pour pays DÉJÀ en opération (pousser ne
   met pas à jour les villes d'un pays existant — couture déclarée).

---

## 0. LES DEUX PROJETS & LEURS EMPLACEMENTS

| Projet | Local | GitHub | Déploiement |
|---|---|---|---|
| **Backend** (Python/FastAPI) | `/home/yann/simulator-backend` | `github.com/KuateAbdel/simulator-backend-loader` | **EN LIGNE** : `https://simul.api.fintech4esg.com` |
| **Frontend** (Vite/React, design JJB) | `/home/yann/simulator-frontend` | `github.com/KuateAbdel/simulator-frontend` | à venir : `https://simul.fintech4esg.com` |

Utilisateur : Kuate Abdel Yaniv (Tech Lead/DevSecOps). Français phonétique.
Discipline exigée : senior/principal engineer Microsoft, SDET, DBA, DevSecOps.

---

## 1. LE SERVEUR (partagé — NE JAMAIS casser les autres services)

- **IP** : `152.53.118.110` (Netcup, Ubuntu 24.04 **ARM64**, 10 vCPU, 16 Go, pas de swap).
- **Accès** : SSH root par mot de passe `GXHYQyKkZf5VmdT` (donné par Yaniv).
  User de déploiement : **`apps`** (groupes sudo+docker), sous `/home/apps/`.
- **Autres projets sur le serveur (À NE PAS TOUCHER)** : ERPNext CRM
  (`crm.finzuu.com`), Nextcloud Talk/Collabora (`signaling/recording/collabora.finzuu.com`),
  Newsletter de Zidane (`news.fintech4esg.com` + `news.api.fintech4esg.com`).
- **nginx est sur le HOST** (systemd, enabled au boot), route par `server_name`.
- **Port 8000 est PRIS** (finzuu-talk-recording). Le Loader backend = **8003**.
- **Réseau docker `loader-net`** pré-créé par Yaniv, adopté (external).
- **Convention domaines** (comme Newsletter) : nu = frontend, `.api` = backend.
- **CRM cert EXPIRÉ depuis 28/07** (cause : renouvellement `standalone` échoue
  car nginx tient le port 80). Pré-existant, PAS notre fait, PAS notre projet.

## 2. BACKEND — ÉTAT : DÉPLOYÉ, EN LIGNE, v0.5.0

### 2.1 Ce qui tourne sur le serveur (vérifié)
- 2 conteneurs `healthy` : `loader-loader-1` (FastAPI, 127.0.0.1:8003→8000),
  `loader-mongo-1` (Mongo 7, volume `loader_loader_mongo_data`, aucun port publié).
- `https://simul.api.fintech4esg.com/health` → 200 `{"status":"ok"}`.
- `/docs` (Swagger) et `/openapi.json` → 200, PUBLICS (pour Zidane).
- Cert Let's Encrypt `simul.api.fintech4esg.com` valide ~89 j, renouvellement
  auto + **hook de reload nginx posé** (`/etc/letsencrypt/renewal-hooks/deploy/`).
- **MongoDB serveur = VIDE** (aucune donnée métier ; 1 seul compte super-admin
  bootstrap). RIEN n'a été RUN — décision Yaniv : on ne lance aucun palier.

### 2.2 Le code backend (957 tests verts, ruff+mypy propres)
- API Super-Admin ENTIÈRE (lots A→H) : auth JWT + mot de passe forcé, config
  verrouillée EF-55, référentiels (villes, **régions/quartiers sans limite**,
  telcos, permissions), **création pays** (`POST /admin/referentiels/pays`),
  **création monnaie** (`POST /admin/referentiels/devises`), entités à l'unité
  (company/produit/groupe), runs pilotés (rite D-01), dashboard (santé 10
  services, population US-E3, index inverse P-01), purge honnête.
- **Réconciliation ici↔là-bas** : 4 statuts (à_nous/disparu_la_bas/
  marque_mais_inconnu/etranger), DELETE groupe gardé, **adoption A-13**.
- Registres dérivés du journal write-ahead + `lenders_registry` ; index
  structurel `(entity_type, action)`.
- P-01 (index inverse), moteur unifié CLI+API (`pilotage.py`).
- Référentiels statiques JJB (SD-1→6), catalogue CAT 1→11, perimetre_lending.
- `uuid_stable` (id serveur sans format garanti), CORS non applicable backend.

### 2.3 Faits mesurés (recon serveur, lecture seule)
- Les **11 rôles D-09 EXISTENT DÉJÀ** sur user-service (notre empreinte
  antérieure) → à ADOPTER (A-13) sur l'instance hébergée.
- **6 pays** sur config-service (`ca` minuscule hors-ISO + CV en plus des 4
  cibles CM/CI/BF/SN). **5 devises**. **15 telcos** (dont PROBE_TELCO_0317).
- **ANO-PRD-UNIQ-01 CONFIRMÉE** : « Cotisation 20000/mois » en DOUBLE.
- **Auth CENTRALISÉE prouvée** : un token user-service marche sur product/
  company/depositary (200). Le Loader fait UN login ROOT partagé (D-DEP-7).
- config-service EXPOSE `POST /countries/create` et `/currencies/create`
  (c'est ainsi que les 4 pays ont été créés — réf loader-config-service).
- config-service N'A PAS de régions/quartiers (404) → notre richesse reste
  chez nous.

### 2.4 CI/CD backend (fonctionnel, prouvé)
- CI : ruff + mypy strict + 957 tests contre MongoDB de service, sur push/PR.
- CD : après CI verte → SSH `apps@serveur` (clé dédiée), `git merge --ff-only`,
  `docker compose up -d --build` (ARM64 natif), santé /health vérifiée.
- Secrets GitHub posés : `DEPLOY_HOST/USER/SSH_KEY/KNOWN_HOSTS` + var
  `DEPLOY_PATH=/home/apps/loader`. Clé dédiée `github-actions-deploy-loader`
  autorisée pour `apps`. `workflow_dispatch` pour redéploiement manuel.
- Fichiers : `Dockerfile` (python:3.12-slim, PAS ghcr — creds ghcr périmés sur
  le serveur), `.dockerignore` (liste blanche), `docker-compose.yml` (8003,
  loader-net), `.github/workflows/{ci,deploy}.yml`, `docs/DEPLOIEMENT.md`,
  `deploy/nginx/simul-api.conf`, `deploy/letsencrypt/reload-nginx.sh`.
- Version : v0.5.0 taggée + Release GitHub. Branche main protégée.

## 3. FRONTEND — ÉTAT : FONDATION EN COURS

### 3.1 Décisions prises
- **Base = design de JJB** (zip `finzuu-dashobar-simulteur.zip`, projet Vite/
  React 18, PAS le PowerPoint). Le scaffold Next.js de Zidane est ABANDONNÉ
  (il était 100% mock, 0 appel backend, 0% fonctionnel — mesuré).
- **Design system JJB** : violet `#c68cff`/`#a855f7` + vert `#19af58`, surface
  `#faf7ff`, polices Sora/DM Sans/JetBrains Mono, radius 12px, composants
  (Card, SectionHeader, StatusBadge, TabBar, EmptyState), charts recharts,
  i18n FR/EN (`t()`, `translations`), sidebar sombre repliable.
- **On garde de JJB le design system, on JETTE ses pages fintech** (Overview
  clients, Lender, Analytics, Onboarding, Bulk — c'est l'app plateforme, pas
  l'admin Loader). On s'inspire de sa page BackOffice (patterns admin).
- **IA = les 6 épopées du backlog canonique** (Confluence 67665922 /
  `docs/BACKLOG_SUPER_ADMIN.md`), pas improvisée.
- **Principe : le Loader est PLUS RICHE** — l'UI montre l'arbre géo complet,
  la réconciliation 4 statuts, le « ce qui part / ce qui reste ».
- **Repo séparé** (pas un dossier du backend).
- **Bilingue FR/EN** (exigence JJB).
- **Déploiement** : build statique servi par nginx sur `simul.fintech4esg.com`.

### 3.2 Ce qui est DÉJÀ fait
- Repo créé, base JJB adoptée dans le dépôt.
- `src/lib/api.ts` : client API réel (VITE_API_URL=simul.api.fintech4esg.com,
  JWT Bearer, ApiError nommée, panne réseau dite). — À reporter proprement.
- `docs/PLAN_FRONTEND.md` + `docs/CONCEPTION_UX_UI.md` (conception détaillée :
  14 écrans, design system + composants à ajouter, QA/invariants d'interface/
  responsive, 8 phases).

### 3.3 Ce qui RESTE à faire (frontend) — les 8 phases
1. **Fondation** : design system adapté, garde d'auth, i18n Loader, layout +
   nav des 6 épopées (réécrire AppContext sans le fintech, Sidebar, types).
2. **Tableau de bord** (US-E1, santé 10 services) + **Configuration** (US-B1/2/3).
3. **Runs** — le rite D-01 (US-C1→C6) : préparer/confirmer/progression/arrêt/
   historique+recette. Le cœur.
4. **Référentiels** : géographie (arbre riche) + créations pays/monnaie/telco/
   région/ville/quartier (avec CountrySelect ISO, hiérarchie EF-02 imposée).
5. **Entités** (US-D1 company aperçu→confirmer, US-D2 produit 3 policy_types).
6. **Écosystème** (US-E2 arbre) + **Population** (US-E3 dataviz recharts).
7. **Inventaire** (réconciliation 4 statuts + adoption A-13) + **Traçabilité**
   (US-E4) + **Purge** (US-F1/F2 rite 2 temps).
8. **Polish** : responsive (360→1920px), a11y (AA, clavier), états vides,
   tests composants (Vitest), EN complet, CI/CD + déploiement.
- **Composants à créer** (langage JJB) : KpiCard, StatutPill (4 statuts),
  HealthDot, Stepper, DataTable, Tree, CountrySelect, Toast, ConfirmDialog,
  FormField/Select/NumberField.
- **QA/invariants d'interface** : hiérarchie « rien en l'air » (ville désactivée
  sans région), formats (ISO, MSISDN, regex ancrée, parts ≤ 100), verrou EF-55
  en lecture seule, le backend reste l'AUTORITÉ (l'UI double, l'erreur nommée
  s'affiche), TS strict, Error Boundary, 4 états par appel, idempotence UI.

## 4. TÂCHES RESTANTES BACKEND (rien de bloquant sauf arbitrages)

Développement backend COMPLET sauf le module VIE. Il reste :
- **#16 Module VIE (palier 7, EF-67→80)** : 180 jours de collectes/retraits +
  re-scoring Duhamel + P-02 (plafonds KYC) + P-03 (float agent). **BLOQUÉ sur
  3 arbitrages Yaniv** : **A-07** (proportions des 4 profils comportementaux),
  **A-11** (part APPROVED/DECLINED), **A-04** (persistance des prêts — ou
  simplement « VIE MEP1 = collecte seulement, sans crédit »). Dès ces réponses,
  je développe VIE avec le protocole (tests, mutations).
- **#24 A-05** (permissions exactes des 11 rôles) — validation sur pièce, avant
  le palier 5 REAL.
- **EXÉCUTION (après hébergement, sur GO de Yaniv, palier par palier)** :
  paliers REAL 1→6 (rôles→orga→catalogue→dépositaires→staff→clients), second
  run CR-03 (idempotence), recette finale CR-01→12 → v1.0.0. **Ordre** :
  santé E1 → login → **adoption A-13 des 11 rôles** → DRY_RUN depuis le serveur
  → paliers REAL. RIEN ne tourne sans décision explicite de Yaniv.
- **#26** : ajout de PAYS/monnaie = FAIT (14/08). Reste éventuel : formulaire
  guidé côté frontend.

## 5. DÉCISIONS CLÉS (à ne pas ré-litiger)
- Backend uniquement pour le Loader d'origine ; frontend repris car Zidane a
  échoué (mission du boss, 14/08).
- Héberger AVANT de charger (C-0). Machine locale = dev seulement.
- Produits COLLECT seulement (pas de LENDING, sprint 8). Noms réels, marqueur
  dans `short_name`.
- Le Loader = autorité d'unicité (la plateforme n'en a aucune). GET-avant-POST
  partout. NO TRUST in a service. Le Loader compose/envoie/relit/trace.
- Anti-corruption : référentiels riches internes, contrats minimaux aux serveurs.
- Créer un pays le DÉCLARE sur config-service ; ne l'ajoute PAS à la génération
  (EF-05 reste 4 pays).
- Tableau de bord vivant : `docs/TABLEAU_DE_BORD.md` (backend).

## 6. COMMENT REPRENDRE
1. Backend : `git pull` dans `/home/yann/simulator-backend`, `.venv` prêt,
   `.venv/bin/python -m pytest tests/ -q` (957 verts attendus). Mongo local :
   voir mémoire `mongodb-local-sans-sudo`.
2. Frontend : `git pull` dans `/home/yann/simulator-frontend`, lire
   `docs/CONCEPTION_UX_UI.md`, reprendre la **phase 1** (fondation).
3. Serveur : SSH root (mdp ci-dessus) ou `apps` (clé de déploiement dans les
   secrets GitHub). Conteneurs : `docker compose ps` sous `/home/apps/loader`.
4. Le CI/CD déploie tout push vert automatiquement (backend). Frontend : CI/CD
   à poser en phase 8.
