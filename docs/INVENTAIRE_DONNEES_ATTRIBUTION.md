# Inventaire des données — tableau de bord d'attribution

**Référence** FZ-INV-ATTRIB-2026-001 · 25/08/2026
**Mission** administration — campagne Afrique subsaharienne : dizaines de baux
simultanés, plusieurs pays, suivi sur des semaines.
**Méthode** rien de supposé : chaque champ ci-dessous a été **lu en production
le 25/08** sur un client réel du pool (`237629171640`, Inès Kambire, Douala),
ou vérifié dans le code du Loader. Les anomalies citées sont mesurées.

Légende coût : `⚡ Loader` = zéro appel réseau (nos collections) ·
`1 GET` = un appel plateforme · `∅` = n'existe pas, à construire.

---

## 1. Le client

### Côté Loader — ⚡ zéro réseau (`org_hierarchy`, nœud CLIENT)

| Champ | Contenu | Fiable |
|---|---|---|
| `msisdn` (dans `name`) | la clé de jointure universelle | ✓ stable (D-CLI-11) |
| `country_code` | pays | ✓ notre décision de quota |
| `gender` | MALE/FEMALE | ✓ (EF-22, rangé à l'écriture) |
| `categorie` | INDIVIDUAL/CORPORATE | ✓ (EF-23) |
| `occupation` | une des 576 professions | ✓ (EF-24) |
| `product_ids` | produits souscrits (ids) | ✓ à l'écriture ; vide sur reprise D-CLI-5 |
| `client_id` | l'id serveur | ✓ |
| `company_id` + parent (kiosque) | l'IMF et le guichet | ✓ |

### Côté client-service — 1 GET par msisdn (~0,5 s), les 15 clés réelles

```
_id · created_at · updated_at · msisdn · language · channel · segment ·
category · identity{17} · is_active · product[] · account_id ·
subscription_fees · subscription_date · status
```

Et **`identity` embarque 17 champs** — dont l'état civil complet :
`first_name, last_name, date_of_birth, place_of_birth, gender, nationality,
marital_status, id_number, id_place, id_expire_on, phone, email, occupation,
address{11}`. Le `marital_status` est réel depuis SD-7 (lu : `MARRIED`).

**Fiabilité — trois pièges mesurés :**
- `identity.type` rend `CORPORATE` pour un particulier — **ne jamais le
  lire**, `category` fait foi (D-CLI-4, écrasement serveur connu).
- `language` est **fiable** (lu : `fr`) — mais uniquement parce que le Loader
  repasse par `PATCH /clients/language` après l'onboarding qui l'ignore.
- `status` rend `PENDING` sur un client pleinement opérationnel — signification
  non établie, **à ne pas afficher tel quel** sans clarification TNS.

**Verdict :** identité, catégorie, produit, langue, msisdn, géographie —
**tout existe et se lit en un GET**. Le Loader détient déjà le tiers utile
(profil de quota + géo) sans réseau.

## 2. Les comptes

### La découverte qui conditionne tout : la clé de jointure

**Les comptes appartiennent à l'IDENTITY, pas au client.** Mesuré :
`GET /accounts/owner/{client_id}` → 0 résultat ;
`GET /accounts/owner/{identity._id}` → le compte. `owner_type: "IDENTITY"`,
`external_class: "CLIENT_SERVICE"`. La fiche client donne aussi `account_id`
directement pour le CHECKING.

### Les champs réels (1 GET) — lus en production

```
balance: 161981.6 · balance_avail: 161981.6 · currency: "XAF" · type: "CHECKING"
status: "ACTIVE" · account_number: "Z5B3UUZI4HRT" · label · owner_name
direct_momo: true · created_at · updated_at
```

**Fiabilité :**
- le **solde se RELIT toujours, jamais ne se calcule** — `FRA-218` : les frais
  sont retranchés du montant et crédités nulle part ;
- `currency` est **fiable sur les comptes clients** (XAF réel lu) — l'anomalie
  `FRA-199` (devise perdue) concerne les companies ;
- `owner_type` vaut `IDENTITY` pour les clients — l'anomalie owner_type connue
  concerne les comptes adossés aux companies (`COMPANY_SERVICE`).

**Combien de comptes ?** Un client attribué possède **1 CHECKING** (cascade
d'onboarding), doté selon le modèle de revenu (A-09/SD-5). Les 4 comptes sont
pour les Lenders, les 6 pour les Dépositaires — pas pour les clients. Il n'y
aura pas d'autre compte client tant que le module VIE n'existe pas.

## 3. Collectes et souscriptions

**Souscriptions — OUI, deux sources :**
- ⚡ Loader : `product_ids` sur le nœud (P-01 — « clients par produit » en une
  agrégation) ;
- 1 GET : `fiche.product[]` — la **fiche produit complète embarquée** (nom,
  type COLLECT, description, policy avec taux). Ce qu'un partenaire verrait
  dans le parcours USSD est donc montrable tel quel.

**Collectes — mesuré : 0.** `GET collectes du client` répond, vide. Aucun
client n'a d'épargne ouverte ni d'historique de versements : **c'est le module
VIE qui les créera**, il n'existe pas. À sa livraison, deux disciplines
s'imposeront à l'écran : `FRA-195` (l'écriture fantôme — la pire anomalie de
l'écosystème) et `D-COL-4` (l'argent des collectes va au compte CLASSIC du
**Dépositaire**, jamais au compte du client — le tableau devra le dire pour ne
pas paraître faux).

## 4. Le bail (`attribution_baux` — ⚡ Loader)

Ce que le mécanisme conserve **aujourd'hui**, par bail :

```
_id (msisdn) · attribution_id · cle_idempotence · profil{pays, genre, categorie}
attribue_le · expire_le
```

Deux gratuités déjà en place :
- **l'historique court existe DÉJÀ** : le TTL ne ramasse un bail que **30 jours
  après son échéance** — les baux morts restent lisibles 5 semaines, l'échelle
  de la campagne ;
- le profil demandé est sur le bail — la vue « baux par pays/genre/catégorie »
  est une agrégation ⚡.

Sans effort à ajouter si besoin : un compteur de rejeux de clé (combien de
fois l'app a redemandé), le user-agent de l'appel. ∅ aujourd'hui.

## 5. L'activité

| Événement | Tracé aujourd'hui ? | Où |
|---|---|---|
| Attribution (201) | **OUI** | `audit_trail`, `AttributionBail`/CREATE — msisdn, profil, échéance |
| Libération (EF-17) | **OUI** | `audit_trail`, `AttributionBail`/DELETE |
| Expiration | **NON** (passive, par conception §5) — mais reconstituable : le bail mort reste 30 j avec son `expire_le` | dérivable ⚡ |
| Échecs par code (409 STOCK_EPUISE, 422, 400) | **∅ — à construire** (journalisation légère des refus) | — |
| Rejeux d'idempotence | **∅ — à construire** | — |

## 6. La géographie — double source, et elle est riche

**⚡ Loader (par jointure msisdn → nœud → arbre) :** quartier (`district_id` du
kiosque, nom du kiosque = le quartier), ville (agence), région (branche), pays,
IMF (`company_nom`). **La vue « où sont les baux actifs » est donc une
agrégation sans réseau** : bail.msisdn → nœud client → chaîne territoriale.

**Serveur (`identity.address`, dans le même GET que la fiche) :**

```
city: "Douala" · region: "Littoral" · country: "CM"
latitude: 4.048 · longitude: 9.7          ← des CARTES sont possibles
+ address_line_1, street_name
```

Les coordonnées GPS sont réelles (celles du référentiel, posées à la
création). Une carte des baux actifs par ville est faisable avec les données
existantes.

## 7. Ce qui existe et n'était pas demandé

- **`segment`** (`MEDIUM`…) et **profil socio-économique** — la segmentation
  qu'un bailleur demande ; le **solde initial** suit un modèle de revenu par
  profession (SD-5), donc les soldes sont *présentables*.
- **L'IMF de rattachement** du client (⚡) — « quel partenaire sert ce
  client », pertinent quand l'interlocuteur EST une institution.
- **`direct_momo: true`** sur le compte — argument mobile money.
- **Les mesures de population par run** (`LoaderRun.mesures`) — quotas
  femmes/jeunes/agri par pays, déjà servis par l'Observatoire (P-06).
- **Le pool par combinaison** — `GET /criteres` public, seize lignes, déjà là.
- **`email`** (`…@demo.fintech4esg.local`) et **`id_number`** — complètent une
  fiche « carte d'identité » crédible à l'écran.
- **Versions et santé des 13 services** (V-01) — si le tableau de bord veut un
  bandeau « l'écosystème répond ».

---

## Synthèse coût/valeur

| Bloc | Disponible | Coût |
|---|---|---|
| Baux actifs + profil + échéances | aujourd'hui | ⚡ |
| Vue territoriale des baux (quartier→pays) | aujourd'hui | ⚡ (jointure interne) |
| Historique attributions/libérations (5 semaines) | aujourd'hui | ⚡ |
| Fiche client complète (état civil, langue, produit, GPS) | aujourd'hui | 1 GET / client |
| Solde et statut du compte | aujourd'hui | 1 GET / client (clé = identity._id) |
| Collectes / épargne | **module VIE requis** | ∅ |
| Échecs par code, compteur de rejeux | **à construire (léger)** | ∅ |
| Expirations comme événements | dérivable des baux morts | ⚡ |
