# REPRISE À FROID — Chantier QA / Service Anatomy (à lire EN PREMIER)

**But de ce document** : permettre de reprendre le travail **sans rien savoir d'autre**. Il contient
le contexte, la méthode, l'outillage, les identifiants d'objets, l'état exact, les pièges, et la
prochaine action. Dernière mise à jour : **02/09/2026**.

> Ordre de lecture conseillé à la reprise :
> 1. ce document (§1 à §4 suffisent pour agir)
> 2. `docs/SESSION_2026-09-02_BULK_PAIEMENT_INTEGRAL.md` (le détail de la journée bulk)
> 3. `docs/empirical/2026-09-02_anatomy_bulk_casquette1.md` (les sondages bruts)
> 4. `docs/ETAT_COMPLET_ET_REPRISE.md` (l'état du Loader, autre chantier)

---

## §1. QUI FAIT QUOI, ET DANS QUEL RÔLE

**Yann (Kuate Abdel Yaniv)** — QA Lead / SDET senior FinZuu, compte Jira/Confluence `ak@finzuu.com`
(displayName `akuate`, accountId `712020:2aebece9-ea58-4a50-bc6c-c04d067f21be`).
Deux chantiers parallèles :
- **Le Loader FinZuu** (produit interne qu'on développe : backend `simulator-backend` + frontend
  `simulator-frontend` + app simulateur USSD) — voir `docs/ETAT_COMPLET_ET_REPRISE.md`.
- **La QUALIFICATION de la plateforme FinZuu** (le code de **TNS Agency**, pas le nôtre) : Service
  Anatomy des services, Test Scenarios Confluence, bugs Jira. **C'est le chantier de ce document.**

**Ce que Yann attend (recadrages explicites, à ne jamais oublier)** :
- Agir en **senior** : comprendre avant de tester, ne pas être « spectateur du contrat ».
- **Trouver des bugs est le métier** : un défaut déclenché par une requête conforme est une
  TROUVAILLE, jamais une faute à s'excuser. Rendre compte en rapport de test sec.
- **Ne rien publier sans autorisation** : Jira et Confluence ne reçoivent RIEN sans son feu vert
  explicite. (Les 3 tickets du 02/09 ont été autorisés.)
- Proposer des **solutions de conception**, pas seulement des constats.
- Restituer **clairement**, sans ambiguïté, avec preuves reproductibles.

---

## §2. LA MÉTHODE (Service Anatomy × C4) — ne plus jamais s'en écarter

**Source de vérité** : Confluence page **12485206** (« 6. Service Compte — Couche 1 PURPOSE »), §18.

**Les 3 règles fondatrices** (à ne PAS confondre avec la discipline d'étiquetage) :
- **R1 — Feynman** : la mission doit se raconter à un enfant de 10 ans, ≤ 3 phrases, avec métaphore,
  zéro jargon. Si je n'y arrive pas, je ne maîtrise pas.
- **R2 — Evans** : Substance > Surface. Dépasser l'OpenAPI et les enums pour livrer le métier.
- **R3 — Meyer + Hughes** : les **invariants AVANT les tests** (0 pytest avant la Couche 7) ; quand la
  doc et le réel divergent, **le réel prime** (S1/S2 sur S3/S4), et chaque contradiction est cataloguée.

**Le modèle** : **C4 Model** (× DDD + SRE Production Reviews) → les **7 couches** : C1 PURPOSE ·
C2 CONTEXT · C3 CONTAINERS · C4 DOMAINS · C5 FLOWS · C6 BOUNDARIES · C7 FAILURE MODES.

**Deux définitions posées par Yann** :
- *Sondage* = une observation empirique unique répondant à UNE question factuelle. Pas d'attendu,
  pas de verdict — son produit est un **FAIT** (commande, code HTTP, réponse, horodatage).
- *Invariant* = propriété vraie à tout instant. C'est **l'ORACLE** : sans lui on ne peut qu'observer,
  jamais juger. D'où R3.

**Discipline d'étiquetage** (garde-fou, en tête de chaque page) : FACT / DÉDUIT / HYPOTHÈSE et
BUG / ANOMALIE / OBSERVATION. **BUG** exige une spec écrite opposable violée ; sinon **ANOMALIE** ;
un comportement voulu mais surprenant = **OBSERVATION**.

**Le « sas Confluence »** : une anomalie ambiguë se documente et s'arbitre AVANT d'ouvrir un bug Jira.

**Le format « Casquettes »** (industrialisation de la méthode, gabarit = Confluence **59834370**,
company-service) : Casquette 1 Architecte (8 questions Q1→Q8), 2 SDET, 3 SRE, 4 Data, 5 Product/UX.

**Où vivent les Anatomy déjà faites** : espace TST. account-service (« 6. Service Compte — Couche N » :
C1 `12485206`, C2 `30998530`, C3 `31096834`, C5 `32604161`, C6 `32931847`, Référentiel AccountStatus
`32604179` — pas de C4 ni C7) · config-service (TST `28901396` ; publication finale FinZuu `29949955`
avec 6 sous-pages 00→05 = LE modèle de publication) · user `56360965` · company `59834370` ·
product `60358657` · client `60555267` · collect `62521348` · depositary `63340549` · faker (dossier
`Faker` `71663617`, 7 couches closes) · ussd (Casquette 1 → a produit FRA-234).

---

## §3. L'ENVIRONNEMENT ET L'OUTILLAGE (pièges compris)

### 3.1 Les cibles
- Plateforme TNS, **instance de TEST uniquement** : `https://<service>.test.services.fintech4esg.com`
  — **tous les services résolvent vers 152.53.168.189** (passerelle unique **APISIX 3.13.0**).
  ⚠ `bulk-paiement.test…` (sans `-service`) **n'existe pas** ; c'est `bulk-paiement-service…`.
- 13 services sondés : user · config · identity · account · company · product · depositary · client ·
  collect · ussd · bulk-paiement · notification · faker (+ web-app, frontend sans OpenAPI).
- Notre Loader (le nôtre, à ne pas confondre) : `simul.api.fintech4esg.com` / serveur 152.53.118.110.

### 3.2 Authentification (discipline INV-USR-19 — impérative)
Identifiants ROOT dans `/home/yann/simulator-backend/.env` (`ROOT_USERNAME` / `ROOT_PASSWORD`).
`POST https://user-service.test.services.fintech4esg.com/api/v1/auth/login`
→ jeton valable ~4 h, **dans l'une des DEUX formes** :

| Forme | Emplacement du jeton | Mesurée |
|---|---|---|
| plate (historique) | `data.access_token` / `data.refresh_token` | en continu du 08/08 au 02/09/2026 |
| imbriquée | `data.token.access` / `data.token.refresh` | depuis le 04/09/2026 — **FRA-238**, changée sans préavis ni changement de version |

Le socle du Loader (`app/clients/base.py`, `SessionAuth._lire_jeton`) accepte les deux, la plate
prioritaire, et **lève une erreur dite** si une troisième apparaît — il n'invente jamais un jeton.
En sondage manuel, lire les deux emplacements.

**UN SEUL login par session** : 3 échecs verrouillent le compte ROOT partagé. Le client du Loader
implémente un disjoncteur ; en sondage manuel, faire pareil (se logger une fois, garder le jeton).

⚠ **Mot de passe ROOT — piège du 14/09/2026.** TNS a vidé plusieurs bases et **remis le compte tel
qu'avant**, donc `Pass1234` : la rotation du 17/08 (`Finzuu@2026Root`) ne vaut plus. Un `.env` resté
sur l'ancien mot de passe prend `401 Incorrect credentials` et, à la 3ᵉ tentative, **verrouille le
compte pour tout le monde** (`423 Account locked`). Distinguer les trois réponses avant d'insister :
`401` = mauvais mot de passe · `403` = mot de passe périmé · `423` = compte verrouillé.
Déverrouillage (ne passe PAS par `/auth/login`, marche donc malgré le verrou) :
`PUT /api/v1/auth/password/request/{email}` puis
`PUT /api/v1/auth/password/reset` `{email, password, otp}` — sur TEST l'OTP est `000000`.
Propager le mot de passe **partout** (le `.env` local ET celui du serveur déployé) *avant* de
déverrouiller, sinon un consommateur resté en arrière re-verrouille aussitôt.

### 3.3 Pièges machine (WSL) rencontrés — gain de temps garanti
- **Aucun `pip`** disponible (ni système, ni venv). Pour une lib pure-Python : télécharger la roue
  depuis PyPI et la dézipper, puis `PYTHONPATH=<dir>` :
  ```
  URL=$(curl -sS https://pypi.org/pypi/pypdf/json | python3 -c "import json,sys;d=json.load(sys.stdin);print([u['url'] for u in d['urls'] if u['filename'].endswith('.whl')][0])")
  curl -sSL -o pypdf.whl "$URL" && unzip -q pypdf.whl -d pylib
  PYTHONPATH=pylib python3 -c "from pypdf import PdfReader; ..."
  ```
- **Pas de `pdftotext`/poppler** → lire les PDF avec pypdf comme ci-dessus.
- **Réseau capricieux** : le premier `curl` d'une salve peut sortir en HTTP 000/timeout alors que le
  service est UP. Toujours `curl --retry 2 --retry-all-errors --max-time 20`, et **retester avec un
  témoin** (un autre service) avant de conclure à une panne.
- **Les .docx** se lisent en dézippant `word/document.xml` puis en supprimant les balises.

### 3.4 Les documents de spécification (le « DOIT »)
- **Doc technique TNS** : `docs/reference/documentation_technique.pdf` (48 pages, déjà dans le dépôt —
  **ne pas dupliquer**). Bulk = **Module V, p.39-42** ; `BULK` package de licence **p.15** ; canaux
  et stack **p.43** ; annexes p.44-48 (types de compte, statuts, segments, politiques).
- **Le zip des spécifications FinZuu** : `C:\Users\LENOVO T570\Downloads\1_Specification (1).zip`
  (côté Windows ; extrait en session dans le scratchpad). Contenu utile :
  - `0_Design-WebApp/FinZuu - Design WebApp-V4.pdf` (24 p.) — **le deck de conception**. Bulk :
    **pages 20-24**, la **p.23** est la plus dense. Même contenu en **V2 p.16-20**.
  - `documentation_technique.pdf` (le même que dans le dépôt)
  - `FinZuu_CompanyStructure-V01.docx` (« Transfert Bulk – OUT »)
  - `2_ReadyPay/`, `3_ReadyCollect/`, `4_ReadySave/`, UML PlantUML.
- Confluence : cloudId **`d03dee24-2899-4d6b-b343-675fdaf2d55d`**, espaces **TST** (work in progress)
  et **FinZuu** (publication finale).
- Jira : projet **FRA** (« FinZuu Ready App »). Assigné habituel des bugs : **finzuu.cm (Brill)**,
  accountId `712020:2e9d98ec-fbf0-41b0-8a56-069ed37ba507`.

### 3.5 Workflow Bug Jira FRA (ne pas se tromper de statut)
`Backlog / A Qualifier` → **`To Do / Qualifié`** → `To be Fixed` → `Fixing / In Dev` → `Ready for QA`
→ `Testing` → `Done / API ready` | `Done / App ready` | `Not a bug`.
Un bug créé arrive en *Backlog* : le passer en **To Do / Qualifié** avec la transition **id `11`**
(« Qualified »). Priorité et assigné se posent avec `editJiraIssue` (`additional_fields` à la
création ne pose pas toujours l'assigné — **vérifier après coup**).
**Gabarit de rédaction maison** (celui de FRA-234, à reproduire) : Résumé → Comportement attendu →
Comportement observé → Environnement → Reproduction (numérotée, avec chiffres et ids) → Impact →
Correction attendue → Vérification après correctif → note de provenance (Service Anatomy + relevé).
Titre : `[FUNC-<SERVICE>-<SUJET>-NN] phrase claire`.

---

## §4. OÙ ON EN EST — ÉTAT AU 02/09/2026

### 4.1 ussd-service — FRA-234 toujours ouvert
Re-mesuré le 02/09 : `POST /callback` → `END Une erreur est survenue…` ; `GET /menus/MAIN` → 400
(6 erreurs de validation) ; `GET /menus/` → 400 ; contrat inchangé (v1.0.1, `text` singulier).
Service UP. **Statut Jira : To Do / Qualifié.** Le canal USSD bout-en-bout reste bloqué (jalon
d'avant-v1 du simulateur). Détail piquant : `new_session` doit être la **chaîne** `"1"`.

### 4.2 bulk-paiement-service — Casquettes 1 et 2 CLOSES
Tout le détail : `docs/SESSION_2026-09-02_BULK_PAIEMENT_INTEGRAL.md` et
`docs/empirical/2026-09-02_anatomy_bulk_casquette1.md`. Les faits structurants à ne pas re-découvrir :
- v1.0.1, 19 opérations / 15 chemins, 2 agrégats (Campaign, Beneficiary), Bearer global,
  `/docs` et `/redoc` **publics**, exposé depuis le 29/07.
- **La chaîne stricte** : company (existe, 404 sinon) → campagne (obligatoire pour un bénéficiaire,
  404 sinon) → bénéficiaires.
- **`PATCH /paid` EXÉCUTE un vrai transfert** : compte **OPERATION de la company** → compte
  **CHECKING du bénéficiaire**, via account-service, paire DEBIT/CREDIT tag COMPANY.
- **La cascade** : créer un bénéficiaire crée une **identité neuve** (identity-service) + un **compte
  CHECKING neuf** (account-service) — l'`_id` d'identité fourni est **ignoré** → duplication KYC.
- **Machine d'états réelle** : `{CREATE, PAID}`, transition directe. `last_execution` **jamais**
  renseigné. Le scheduler `is_automatic` n'a **jamais** tourné (« Test AgriBiz » depuis le 31/07).
- **Ce qui est BIEN fait** : pré-vérification des fonds (unitaire ET campagne, tout-ou-rien, aucun
  solde négatif), `total_payment` recalculé dynamiquement, refus propres sur références fantômes.

### 4.3 Les 3 bugs — CRÉÉS, QUALIFIÉS, ASSIGNÉS (épic FRA-174)
| Clé | Sujet | Priorité | Preuve courte |
| --- | --- | --- | --- |
| **FRA-235** | Paiement rejouable → **double paiement**, routes bénéficiaire ET campagne | Highest | OPERATION 25→15→5, bénéficiaire 0→10→20 |
| **FRA-236** | Le **PUT documenté corrompt** le document et casse `GET /beneficiaries/` (400) | Highest | doc `b2237e77…` illisible/immodifiable/insupprimable |
| **FRA-237** | **DELETE ment** : 200 « deleted » sans supprimer (campagnes ×4 ; bénéficiaire PAID) | High | témoin : le delete d'un non-payé marche vraiment |
Message de purge du document `b2237e77-9712-4346-947f-258d25e179c3` **envoyé par Yann à TNS** →
**à vérifier à la reprise** : `GET /api/v1/beneficiaries/` doit repasser à 200.

### 4.4 Les 20 anomalies — EN ATTENTE DE L'ARBITRAGE DE YANN
Liste complète et argumentée : journal §6 (A-1→A-7 conception, B-1→B-9 contrat, C-1 règle découverte,
D-1→D-3 sécurité). Classement proposé : BUG solides = **A-1** (débit de la trésorerie au lieu d'une
provision), **A-3** (`receive_cash` disparu), **A-4** (unicité msisdn vs récurrence), **A-7** (licence
BULK jamais vérifiée), **B-3** (`last_execution`) · à trancher avec TNS/JJB = A-2, A-5, A-6, B-4 ·
qualité = B-1, B-2, B-6, B-7, B-9, D-1 · observations = le reste.
⚠ **D-3 n'appartient pas au bulk** : création de monnaie ex nihilo chez **account-service** (ROOT,
`credit` avec `src = dest`, +25 F sans contrepartie) — dossier account-service, famille inverse de
FRA-218.

### 4.5 Objets réels utiles (pour rejouer un sondage sans re-chercher)
| Objet | Id | Note |
| --- | --- | --- |
| Company « SA Mbarga Retail » | `2072d7be-e30f-4e76-8550-df8a7b4853dd` | company de sonde, licence [ALL] active |
| OPERATION de Mbarga | `16e7e19d-f434-4f46-92a1-82052bce7b97` | balance **0.0** (restituée) |
| Company « Aquiba SARL » | `285db515-cf98-4735-b759-99f39cf4c646` | licences READY_CASH **inactives/expirées** (preuve A-7) |
| OPERATION d'Aquiba | `b01d3ff7-e151-4de9-9bc9-303e56fc26f5` | a payé Richard Miller le 31/07 |
| Bénéficiaire Richard Miller | `c71ea598-fa56-4d9e-bbe3-23953d97e4fd` | **donnée d'origine — NE JAMAIS y toucher** |
| Doc empoisonné | `b2237e77-9712-4346-947f-258d25e179c3` | casse la liste (FRA-236) |
| Bénéficiaire PAID indélébile | `7e4d48f2-2fcd-45e2-8f1e-583da306bbaf` | preuve FRA-237 |
| Campagnes sondes indélébiles | `4963bf16…`, `47a02ac8…`, `f0e3864d…`, `f3c013dd…` | inertes |

### 4.6 Discipline de sondage à reconduire
Préfixe **`PROBE_*`** sur tout objet créé · msisdn de sonde 6900001xx · montants minuscules (10-25 XAF)
· **restituer l'argent** (débits symétriques) et **relire les soldes** en fin de batterie · ne jamais
écrire sur une donnée non préfixée PROBE · consigner chaque sonde (commande, code, réponse, heure).

---

## §5. LA CONCEPTION CIBLE DU MODULE BULK (le travail de fond)

**Où vit la conception écrite** : deck **Design WebApp V4 p.20-24** (V2 p.16-20) — « Flow Creation
d'un Bulk » + « Condition Financement Eligible » : Ref/Nom Programme, Statut Actif/Clos, âge ≥ 18,
Genre F/H, Éligibilité Immédiat/x mois, Catégorie Individue/Business, Type **Salaire/Don/Avance/Autre**,
Montant mini, Mode Auto/Manuel, **Portefeuilles**, **Import fichier CSV**.
Citation p.23 : « **Mise des fonds à disposition** via la plateforme — portefeuille renvoie au compte
d'opération **où l'argent réside** (Lender éligible) — paiements récurrents : **chaque date doit avoir
un fichier** ou réutiliser le même ».

**Le scénario de référence (Yann)** : le propriétaire d'une école vient payer ses 40 employés. Il
APPORTE ses fonds ; les employés ne sont PAS clients de la microfinance.

**Le flow cible** : provision dédiée (portefeuille du programme) → campagne rattachée → import du
fichier avec rapport ligne par ligne → contrôle Σ dûs ≤ provision (**jamais** la trésorerie de la
company) → exécution instantanée + **notification** à chaque payé → clôture (rapport payés/échecs,
reliquat rendu).

**L'invariant de conception** (formulé avec Yann) : *un compte interne de type client est réservé à
qui est enregistré comme client — un bénéficiaire n'en fait pas naître un.*
Cible : msisdn déjà client → **rattachement** de son compte ; sinon paiement **sortant** via Payment
Hub (opérateur déduit du préfixe ; telcos/monnaies du pays de la company = **config-service**, que
bulk n'appelle jamais) ou en **espèces** via le réseau dépositaires/kiosques.

**Le gabarit de fichier proposé** : obligatoires `msisdn` (validé plan de numérotation du pays) ·
`nom` · `prénom` · `montant` > 0 ; optionnels `référence` (matricule) · `mode de réception` ·
`devise` ; conditionnels naissance/genre/embauche **si** le programme porte des critères.
Vérifications : doublons msisdn, préfixe opérateur, **Σ comparée à la provision AVANT validation**,
rapport ligne par ligne (acceptées/rejetées + motif). ⚠ le deck dit **CSV**, l'API dit **Excel**.

**Les 5 angles morts** (personne ne les a encore posés) : ① **maker-checker** (celui qui importe ≠
celui qui paie) ② **échecs partiels** + plafond e-money BEAC + **reliquat rendu à la provision**
③ **frais** du payout (qui paie ?) ④ **référence de transaction opérateur** pour la réconciliation
⑤ **récurrence par fichier** (qui condamne l'unicité globale du msisdn mesurée).

**Les 7 propositions pour JJB/TNS** : 1) portefeuille de campagne (jamais l'OPERATION) 2) idempotence
du paiement 3) devise héritée de la company et validée config-service 4) rattachement par msisdn au
lieu de duplication KYC 5) notification à l'exécution 6) rétablir `receive_cash` 7) publier le gabarit
de fichier.

---

## §6. LA PROCHAINE ACTION (dans cet ordre)

1. **Vérifier la purge TNS** : `GET /api/v1/beneficiaries/` doit répondre 200 (le doc `b2237e77…`
   supprimé). Si oui, le noter dans FRA-236.
2. **Faire trancher les 20 anomalies** par Yann → tickets FRA (gabarit §3.5) ou page de sas Confluence.
3. **Écrire la page « Conception cible du Module Bulk »** (le contenu est §5 + journal §7) pour
   arbitrage JJB — **c'est le livrable le plus important** : il doit arriver AVANT que TNS ne corrige
   les 3 bugs en gardant l'architecture qui tape dans l'OPERATION.
4. **Finir la Casquette 2** : scheduler `is_automatic`, import-excel nominal (dès le gabarit connu),
   RBAC non-ROOT, machine d'états complète.
5. **Casquette 3 (SRE)** : latences, volumes, comportement du `paid` sous charge.
6. Publication Confluence des Anatomy bulk (gabarit 59834370) **si Yann le décide**.

---

## §7. CE QU'IL NE FAUT PLUS JAMAIS FAIRE (erreurs déjà commises)

1. Confondre les **3 règles** (R1/R2/R3) avec la discipline d'étiquetage FACT/DÉDUIT/HYPOTHÈSE.
2. Affirmer qu'**account-service n'a pas de page Anatomy** — il en a 6 (§2).
3. **S'excuser** d'un bug serveur révélé par une requête conforme (posture SDET).
4. **Publier** sur Jira/Confluence sans autorisation explicite.
5. Conclure à une panne sur un **seul** curl en échec (réseau WSL — utiliser un témoin).
6. Re-sonder ce que Confluence documente déjà (règle du 08/08 : ne jamais re-découvrir un fait établi).
7. Créer un bug et **oublier de vérifier l'assigné** et le passage en `To Do / Qualifié`.
