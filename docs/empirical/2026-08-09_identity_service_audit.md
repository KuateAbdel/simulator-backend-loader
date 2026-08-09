# identity-service — audit empirique du 9 août 2026

| | |
|---|---|
| **Motif** | Dernier des 9 services jamais sondé directement. Observé jusqu'ici **uniquement à travers les cascades** des autres services. |
| **Méthode** | Contrat OpenAPI runtime lu intégralement, puis mesure. **Lecture seule — zéro écriture, zéro empreinte.** |
| **Statut** | 🟡 **Partie I terminée** (contrat, 13 endpoints, 13 schémas). Partie II (état de la base) en attente de credentials. |
| **Base** | `https://identity-service.test.services.fintech4esg.com` |

> **Pourquoi ce service compte.** Il est au centre de tout sans avoir jamais été
> regardé : `CreateUserSchema.identity` l'exige avant tout User, `company.owner`
> y cascade, `account.owner_id` de type `IDENTITY` y pointe, et l'omission de
> `id_expire_on` y fait planter client-service (`ANO-CLI-IDENTITY-01`).
> Le Loader en dépend à chaque onboarding client — 2000 fois.

---

## 1. ✅ L'authentification est **réellement appliquée**

Contrairement à depositary-service (`FRA-205` : aucune RBAC réelle), identity-service
refuse tout appel non authentifié.

| Appel sans jeton | Réponse |
|---|---|
| `GET /health` | `200` — `{"status":"ok"}` (exposition volontaire, normale) |
| `GET /api/v1/identities/` | **`401`** `Authentication required` |
| `GET /api/v1/identities/by-email/{email}` | **`401`** |
| `GET /api/v1/ocr/languages` | **`401`** |

Le schéma déclaré (`BearerAuth`, JWT, sécurité globale) **correspond au comportement
réel**. C'est le premier service du périmètre dont la sécurité déclarée n'est pas
démentie par la mesure.

---

## 2. 🟠 Le service ne s'appelle pas comme on le croit

```
info.title   = "Auth Service"
info.version = "1.0.1"
```

Le service déployé sous le nom `identity-service` **se déclare « Auth Service »**.
Sans conséquence fonctionnelle, mais toute personne qui inspecte le contrat pour
la première fois se demandera si elle interroge le bon service.

---

## 3. 🔴 Asymétrie de validation entre **création** et **mise à jour**

Trois champs sont des énumérations déclarées dans `components.schemas`.
Elles ne sont **référencées que dans deux des trois schémas** qui les utilisent.

| Champ | `CreateIdentitySchema` | `UpdateIdentitySchema` | `SearchRequestSchema` |
|---|---|---|---|
| `type` | `$ref IdentityType` ✅ | `$ref` ✅ | `$ref` ✅ |
| **`gender`** | **`string` libre** ❌ | `$ref IdentityGender` ✅ | `$ref` ✅ |
| **`marital_status`** | **`string` libre** ❌ | `$ref IdentityMaritalStatus` ✅ | `$ref` ✅ |

**Le seul schéma qui écrit la donnée est le seul qui ne la valide pas.** Une
Identity peut naître avec `gender: "peu importe"`, et ne pourra ensuite plus être
mise à jour sans corriger ce champ — la mise à jour, elle, est stricte.

**Impact direct sur le Loader** : `EF-22` exige **2 femmes pour 1 homme** sur
2000 clients. Ce quota se joue entièrement sur un champ que le serveur n'a aucune
raison de refuser, quelle que soit la valeur envoyée. Une faute de frappe dans
notre générateur ne serait signalée par personne.

> **Discipline `D-IDN-1`** — le Loader valide `gender`, `marital_status` et `type`
> **contre les énumérations du contrat, côté Loader, avant l'envoi**. Ne jamais
> compter sur le rejet du serveur : il n'aura pas lieu.

Valeurs officielles à respecter :

| Énumération | Valeurs |
|---|---|
| `IdentityType` | `CORPORATE`, `INDIVIDUAL` |
| `IdentityGender` | `MALE`, `FEMALE`, **`ANY`** |
| `IdentityMaritalStatus` | `SINGLE`, `MARRIED`, `DIVORCED`, `WIDOWED` |

> ⚠️ `IdentityGender` contient **`ANY`** — la même valeur parasite que celle
> retrouvée dans le champ `currency` d'un compte réel (`ANO-ACC-CUR-08`,
> `FRA-222`). Le Loader ne l'émettra **jamais** : `EF-22` exige une répartition
> mesurable, et `ANY` la rend invérifiable.

---

## 4. Champs requis à la création — 10 sur 16

`CreateIdentitySchema`, requis : `first_name`, `date_of_birth`, `nationality`,
`id_number`, `id_place`, `id_expire_on`, `phone`, `email`, `occupation`, `address`.

Optionnels : `type`, `last_name`, `place_of_birth`, `gender`, `marital_status`,
`alternate_phone`.

Trois constats à retenir :

* **`last_name` est nullable, `first_name` non.** Une Identity à un seul nom est
  contractuellement valide.
* **`type` n'est pas requis** — alors que `D-CLI-4` établit que sa valeur est de
  toute façon **écrasée vers `CORPORATE`** par client-service. Le champ est donc
  optionnel *et* ignoré.
* **`id_expire_on` est requis et non nullable**, ce qui confirme la cause de
  `ANO-CLI-IDENTITY-01` : les copies embarquées du schéma chez client-service et
  company-service sont désynchronisées de l'original.

### `Address` — 2 champs requis sur 10

Requis : `address_line_1`, `street_name`.
Optionnels : `address_line_2`, `street_number`, `postal_code`, **`city`**,
**`region`**, **`country`**, `latitude`, `longitude`.

> 🔴 **`country` est optionnel alors que `nationality` est requis.** Une Identity
> peut donc porter une nationalité sans que son adresse ne dise dans quel pays
> elle réside. Pour le Loader, dont toute la géographie repose sur 4 pays cibles
> (`OBJ-01`, `EF-05`), c'est une porte ouverte à des adresses hors référentiel.
>
> **Discipline `D-IDN-2`** — le Loader renseigne **toujours** `country`, `city`,
> `region` et les coordonnées GPS, depuis le référentiel `Loader_Base` déjà
> chargé et validé (`EF-01` → `EF-03`). Aucun de ces champs n'est laissé au
> serveur.

---

## 5. 🟠 Deux pièges de contrat pour le client HTTP

### 5.1 Pagination par défaut à **10**

`GET /api/v1/identities/` — `limit=10`, `page=1` par défaut. Un appel naïf ne rend
que **10 identités**, sans que rien ne signale la troncature.

> **Discipline `D-IDN-3`** — tout inventaire d'identités passe par la pagination
> complète du socle HTTP mutualisé (`ReponseServeur.paginate`), jamais par un
> appel simple. Le même piège vaut pour `GET /identities/search/{search}` et
> `POST /identities/search`.

### 5.2 Convention REST divergente — `POST /identities/create`

Les huit autres services créent par `POST /<ressource>/`. Celui-ci exige
`POST /api/v1/identities/**create**`. Une transposition mécanique depuis un autre
client produirait un `404` ou un `405`.

---

## 6. Deux zones du contrat qui n'apparaissent dans aucun de nos documents

### 6.1 `POST /api/v1/identities/{id}/validate` — sans corps de requête

Un endpoint de **validation d'identité** existe. Il ne prend **aucun paramètre et
aucun corps** : seulement l'identifiant en chemin. Réponses déclarées : `200`, `422`.

Aucune de nos sources — pages Service Anatomy, Document Maître, CDC, diagrammes
UML — ne le mentionne. Sa sémantique est inconnue : bascule-t-il un statut KYC ?
Est-il idempotent ? Que vaut une Identity non validée ?

**Non testé** : c'est une **écriture**, et le sondage est en lecture seule.

### 6.2 Un module **OCR** embarqué — 3 endpoints

`GET /ocr/languages`, `POST /ocr/ocr` (multipart), `POST /ocr/ocr/base64`.

Un service d'identité qui embarque de la reconnaissance de caractères — vraisemblablement
la lecture automatique des pièces d'identité, ce qui expliquerait le couple
`id_number` / `id_place` / `id_expire_on`. **Hors périmètre du Loader** : nous
composons nos identités, nous ne scannons aucun document.

> **Frontière `D-IDN-4`** — le Loader n'appelle **jamais** les routes `/ocr/*`.
> Elles supposent un document réel ; nous n'en produisons aucun.

---

## 7. Aucun `DELETE` — troisième service dans ce cas

`identity-service` n'expose aucune suppression. Comme `account-service` et
`depositary-service`, **toute Identity créée reste en base à vie**.

Trois services sans marche arrière, dans un environnement TEST partagé. Cela
renforce `ENF-05` (réversibilité par préfixe `DEMO_`) : le préfixe n'est pas un
confort de nommage, c'est **la seule réversibilité qui nous reste** sur ces trois
services.

---

## Récapitulatif — 13 endpoints, 13 schémas

| Ce qui est fiable | Ce qui ne l'est pas |
|---|---|
| L'authentification est réellement appliquée (401) | `gender` et `marital_status` **non validés à la création** |
| Les énumérations sont déclarées et cohérentes entre elles | `Address.country` optionnel alors que `nationality` est requis |
| `id_expire_on` requis et non nullable — l'original fait foi | La pagination par défaut à 10, silencieuse |
| Le contrat est complet et lisible | Le titre du service (« Auth Service ») |
| | Aucun `DELETE` — écriture définitive |

**4 disciplines dégagées** : `D-IDN-1` (valider les enums côté Loader),
`D-IDN-2` (toujours renseigner la géographie de l'adresse), `D-IDN-3` (paginer),
`D-IDN-4` (ne jamais appeler `/ocr/*`).

---

## Partie II — en attente

Ce qui exige un jeton et **reste à mesurer**, toujours en lecture seule :

1. **État réel de la base** — combien d'identités, réparties comment entre
   `CORPORATE` et `INDIVIDUAL`, quelles nationalités, quelles valeurs réelles de
   `gender` (y en a-t-il hors énumération, comme le `ANY` trouvé sur `currency` ?).
2. **`Address.country` sur les identités existantes** — combien sont vides.
3. **Comportement réel de la pagination** — le total est-il rendu, et est-il juste ?
4. **Les trois recherches** — `by-phone`, `by-email`, `search/{search}` : sensibles
   à la casse ? Rendent-elles `404` ou une liste vide quand rien ne correspond ?
   (piège déjà rencontré sur `GET /depositaries/subscriptions/depositary/{id}`.)
5. **Cohérence avec les cascades** — les identités créées par company-service et
   client-service portent-elles les mêmes champs que celles créées en direct ?

*Aucun de ces points ne demande la moindre écriture.*
