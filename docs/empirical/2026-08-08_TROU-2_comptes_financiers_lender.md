# Sondage empirique — Trou #2 : les comptes financiers du Lender

| | |
|---|---|
| **Date** | 8 août 2026 |
| **Environnement** | TEST — `*.test.services.fintech4esg.com` (APISIX 3.13.0) |
| **Authentification** | ROOT (`noreply@finzuu.com`) — `POST /api/v1/auth/login` |
| **Nature du sondage** | **Lecture seule stricte** — aucun POST, PUT ou PATCH émis |
| **Exigences concernées** | UC-10, EF-13 (CDC v1.2) ; `03_sequence_lender.puml` |
| **Statut** | **Tranché** pour la partie « cascade automatique ». Voir §5 pour ce qui reste ouvert. |

## 1. Question posée

Le CDC v1.2 (UC-10, EF-13) postule que chaque Lender possède 4 comptes
financiers distincts : `CAPITAL`, `INTEREST`, `PENALTY`, `TAXE`. Le diagramme
`03_sequence_lender.puml` marque cette étape « ⚠⚠ HYPOTHÈSE NON VÉRIFIÉE ⚠⚠ »
— jamais testée empiriquement, contrairement aux 6 comptes du Dépositaire.

**Une Company portant le rôle de Lender reçoit-elle réellement ces 4 comptes
par cascade automatique, comme le Dépositaire reçoit ses 6 ?**

## 2. Protocole

Groupe de contrôle : les Dépositaires, dont la cascade de 6 comptes à la
première souscription est déjà confirmée (D-DEP-2). Groupe observé : les
Companies. Observation via `GET /api/v1/accounts/owner/{owner_id}`, complétée
par un inventaire exhaustif `GET /api/v1/accounts/`.

## 3. Résultats bruts

### 3.1 Groupe de contrôle — Dépositaires (11 au total, 6 inspectés)

| Dépositaire | Souscriptions | Comptes observés |
|---|---|---|
| `Depositaire Test` | HTTP 404 — 0 | **0** |
| `PROBE_Q2_CUSTOMER` | HTTP 404 — 0 | **0** |
| `PROBE_WITHDRAWAL_INACTIVE` | 1 | **6** — CAPITAL, INTEREST, PENALTY, TAXE, CLASSIC, TERM_DEPOSIT |
| `PROBE_CASCADE_DEP` | 1 | **6** — idem |
| `PROBE_STATUS_TEST_CLEAN2` | 1 | **6** — idem |
| `PROBE_STATUS_TEST_CLEAN` | HTTP 404 — 0 | **0** |

**FACT confirmé (D-DEP-2), avec une précision nouvelle :** la cascade des 6
comptes est déclenchée par la **souscription**, jamais par la création du
Dépositaire. Un Dépositaire sans souscription possède **zéro** compte —
corrélation parfaite sur les 6 cas observés, sans contre-exemple.

### 3.2 Groupe observé — Companies (7 au total, 7 inspectées)

| Company | Type | `account_id` | Comptes observés |
|---|---|---|---|
| `PROBE_IDENTITY_CASCADE` | BANK | oui | **1 — OPERATION** |
| `PROBE_GAP_ADMIN_CASCADE` | BANK | oui | **1 — OPERATION** |
| `PROBE_CASCADE_COMPANY` | BANK | oui | **1 — OPERATION** |
| `PROBE_CASQ1_COMPANY_XAF` | BANK | oui | **1 — OPERATION** |
| `FinTech4ESG` | MERCHANT | oui | **1 — OPERATION** |
| `TNS Agency` | BANK | oui | **1 — OPERATION** |
| `Aquiba SARL` | BANK | oui | **1 — OPERATION** |

**7 Companies sur 7, sans exception** — y compris les trois Companies
historiques non issues d'un sondage (`FinTech4ESG`, `TNS Agency`,
`Aquiba SARL`) : exactement **1 compte, de type `OPERATION`**. Jamais
`CAPITAL`, jamais `INTEREST`, jamais `PENALTY`, jamais `TAXE`.

**Companies portant les 4 comptes Lender : 0 / 7.**

### 3.3 Inventaire exhaustif — 42 comptes dans tout l'environnement TEST

| Type | Nombre | Origine identifiée |
|---|---|---|
| `OPERATION` | 7 | cascade création Company (1 par Company, 7 Companies) |
| `CAPITAL` | 5 | bundle Dépositaire |
| `INTEREST` | 5 | bundle Dépositaire |
| `PENALTY` | 5 | bundle Dépositaire |
| `TAXE` | 5 | bundle Dépositaire |
| `CLASSIC` | 5 | bundle Dépositaire |
| `TERM_DEPOSIT` | 5 | bundle Dépositaire |
| `CHECKING` | 5 | cascade onboarding Client (`external_class=CLIENT_SERVICE`) |

`7 + (5 × 6) + 5 = 42`. **La totalité des comptes de l'environnement est
expliquée par trois cascades connues.** Aucun compte résiduel ne pourrait
provenir d'une cascade Lender non identifiée : l'argument est fermé par
comptage, pas par échantillonnage.

Répartition par propriétaire : `owner_type` = COMPANY (38) / IDENTITY (4) ;
`external_class` = COMPANY_SERVICE (38) / CLIENT_SERVICE (3) / BULK_SERVICE (1).

## 4. Conclusion

> **Il n'existe AUCUNE cascade automatique produisant les 4 comptes financiers
> d'un Lender.** L'hypothèse UC-10 / EF-13 est **infirmée** dans sa lecture
> « cascade ».

Trois constats la soutiennent :

1. **Aucune occurrence.** 0 Company sur 7 porte les 4 comptes, alors que ces
   4 types existent bien dans l'enum serveur `AccountType`
   (`CAPITAL, CHECKING, INTEREST, PENALTY, TAXE, CLASSIC, TERM_DEPOSIT,
   OPERATION, COMMITMENT`) et sont bien produits — mais uniquement dans le
   bundle Dépositaire.
2. **Aucun endpoint capable de la produire.** Le contrat OpenAPI de
   company-service ne comporte strictement aucune route liée aux comptes
   (`/companies/`, `/companies/{id}`, `/licenses/…` — rien d'autre). La seule
   action de l'écosystème produisant un lot de comptes est
   `POST /api/v1/depositaries/subscriptions/create`, liée à un
   `depositary_id`, sans équivalent au niveau Company.
3. **Le bundle Dépositaire n'est pas transposable.** Ses 6 comptes portent
   pourtant `owner_type=COMPANY` et `external_class=COMPANY_SERVICE` : dans
   account-service, un Dépositaire *est* modélisé comme une Company. Le
   déclencheur reste néanmoins la souscription à un produit, acte qui n'a
   aucun sens métier pour un Lender.

### Conséquence directe pour le module Organisation

Le Loader doit créer ces 4 comptes **lui-même, explicitement**, par 4 appels
distincts à `POST /api/v1/accounts/`. Contrat exact relevé
(`CreateAccountSchema`) :

```
requis : account_number, type, external_id, external_class, owner_type, owner_id, owner_name
```

soit, par compte : `type` ∈ {CAPITAL, INTEREST, PENALTY, TAXE},
`owner_type=COMPANY`, `external_class=COMPANY_SERVICE`,
`owner_id` = `company_id`, `currency` ∈ {XAF, XOF}.

C'est exactement la structure déjà prévue par `LenderRegistryEntry` : les 4
`*_account_id` restent `UUID | None`, un Lender partiellement initialisé
demeurant un état légitime (UC-10, cas d'exception).

## 5. Ce qui reste ouvert — et pourquoi je ne l'ai pas tranché

La création explicite des 4 comptes est **plausible mais non vérifiée** : le
contrat l'autorise, aucune observation ne prouve encore que le serveur
l'accepte et rattache correctement le compte à la Company.

Le vérifier exige une **écriture irréversible** : account-service n'expose
**aucun endpoint DELETE**. Un compte créé ne peut être que passé en `CLOSED`
via `PUT /accounts/change-status/{id}/{status}` — il reste en base
définitivement, dans un environnement TEST partagé. Décision utilisateur
requise avant de procéder.

## 6. Anomalies annexes relevées (à confirmer, hors périmètre du sondage)

- **`external_id` vide sur les comptes OPERATION.** Les 7 comptes issus de la
  cascade Company ont `external_id=""`, alors que le champ est déclaré requis
  à la création. Le rattachement fonctionne malgré tout via `owner_id`
  (`GET /accounts/owner/{company_id}` répond correctement). À ne pas imiter :
  le Loader renseignera toujours `external_id`.
- **HTTP 404 pour « aucune souscription ».**
  `GET /depositaries/subscriptions/depositary/{id}` répond 404 sur un
  Dépositaire sans souscription, là où un 200 avec liste vide serait attendu.
  Le client httpx du Loader devra traiter ce 404 comme « zéro résultat », pas
  comme une erreur.
- **`CLASSIC` à 1000.0 sur `PROBE_CASCADE_DEP`** — solde non nul issu d'un
  sondage antérieur, sans incidence ici.

---

*Sondage exécuté et documenté avant tout développement du module Organisation,
conformément au Trou #2 du document maître §12.*
