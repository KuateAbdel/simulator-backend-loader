# Faker — le Sénégal est absent, et c'est le CONTRAT qui le dit

| | |
|---|---|
| **Objet** | Vérifier si Faker sert `country_code=SN`, avant d'écrire une source interne pour les 500 clients sénégalais (arbitrage `A-01`). |
| **Nature** | **Lecture seule stricte.** 10 appels `GET` + lecture de l'OpenAPI. `POST /cache/clear` jamais appelé. |
| **Date** | 11 août 2026 · `run_id = 20260620123721` |
| **Pourquoi refaire** | La mesure du 08/08 avait trois jours. Une source tierce peut être enrichie entre-temps — un fait daté n'est pas un fait acquis. |

---

## 1. Le contrat OpenAPI — la preuve la plus forte

Le 08/08 avait mesuré un **422 au runtime**. Aujourd'hui, la lecture du contrat
dit mieux : `SN` n'est pas rejeté, il **n'est pas déclaré**.

```
GET /v1/faker/client              country_code  enum: ["BF", "CI", "CM"]  default: "CI"
GET /v1/faker/client/individual   country_code  enum: ["BF", "CI", "CM"]  default: "CI"
GET /v1/faker/client/business     country_code  enum: ["BF", "CI", "CM"]  default: "CI"
FakerPayloadRequest (schéma)      country_code  enum: ["BF", "CI", "CM"]  default: "CI"
```

Un 422 pourrait être une régression passagère. Un enum de trois valeurs dans le
contrat **et** dans le schéma de requête est une décision de conception.

## 2. Famille A — le runtime confirme le contrat

| Endpoint | HTTP | Corps |
|---|---|---|
| `/v1/faker/client/individual?country_code=SN` | **422** | `literal_error` — « Input should be 'BF', 'CI' or 'CM' » |
| `/v1/faker/client/business?country_code=SN` | **422** | idem |
| `/v1/faker/client?country_code=SN` | **422** | idem |

## 3. Famille B / C — et le témoin de contrôle qui était nécessaire

Mon premier essai a produit des URLs **malformées** (`/random&run_id=` sans le
`?`). Les 404 obtenus étaient un artefact de ma construction, pas une mesure —
exactement le genre de faux résultat que le sondage S2 avait produit sur le cache.
Refait proprement, avec le même appel sur `CM` comme témoin :

| Endpoint | SN | CM (témoin) | Ce que ça prouve |
|---|---|---|---|
| `real-scoring-phone/random` | **404** « No matching client phone found » | **200** | SN n'a **aucune population scorée** |
| `real-scoring-payload/random` | **404** « No scoring payload found » | — | idem |
| `loan-history/random` | 404 | **404 aussi** | ⚠️ **ne prouve RIEN** |

> Le témoin était indispensable. `loan-history/random` rend 404 **sur le
> Cameroun aussi** — son 404 sur le Sénégal n'aurait donc rien démontré. Seul
> `real-scoring-phone`, qui répond 200 sur CM avec la même URL, isole
> réellement l'absence sénégalaise.

## 4. Verdict

**Faker ne sert pas le Sénégal, et rien n'indique qu'il le servira.** Les 500
clients sénégalais (25 % de la population exigée par `OBJ-01` et `EF-05`)
relèvent du générateur interne.

Ce n'est pas un contournement : c'est la doctrine du CDC §321 appliquée à un cas
de plus.

> « L'outil combinera **deux sources** de génération : d'une part l'API Faker
> pour les payloads clients, d'autre part un **générateur interne** pour les
> entités absentes de Faker. »

Le Loader compose déjà lui-même les Companies, les 4 Lenders institutionnels, les
Dépositaires, les raisons sociales, les adresses, les dates de naissance et les
MSISDN. Pour les trois pays servis, Faker ne fournit que **8 champs sur 21** —
servir le Sénégal entièrement en interne est une différence de degré, pas de
nature.

## 5. Ce que la source interne ne fabrique pas

| Champ | Valeur | Pourquoi |
|---|---|---|
| `msisdn` | `None` | Le composeur le produit depuis le plan de numérotation réel (`D-CFG-1`) — aucun numéro Faker n'est attribuable de toute façon |
| `identite` | `None` | Le générateur compose la pièce (`D-CLI-3`, `D-CLI-2`) |
| `company` | `None` | Le secteur vient du moteur de quotas (`EF-24`, taxonomie du CDC) |

Fabriquer un faux `sim_number` ou une fausse `company_name` pour « faire comme
Faker » serait l'invention arbitraire que le CDC interdit — **et cela effacerait
la trace de la provenance.**

## 6. La provenance est lisible partout

Le `client_id` porte le préfixe `INTERNE-` : `INTERNE-SN-IND-42`. Il voyage avec
l'identifiant jusque dans `faker_consumption_ledger`, où `compter_par_pays()` le
relit. Un opérateur qui compte 500 Sénégalais peut dire d'où ils viennent sans
consulter une table de correspondance ni relire le code.

Le rapport d'essai à blanc l'affiche :

```
Source INTERNE : SN 500  (Faker ne sert pas ces pays — arbitrage A-01)
```

**Ce n'est pas une alerte.** Un écart déclaré et arbitré n'est pas un échec : le
faire basculer le run en `PARTIAL` à chaque exécution noierait les vraies alertes.

## 7. Deux différences assumées avec les pays servis par Faker

1. **Le ratio des genres est produit directement** (2 femmes / 1 homme, `EF-22`)
   au lieu d'être obtenu par tirage-et-rejet. Nous contrôlons la source : la
   respecter d'emblée évite de brûler des tirages. Le moteur de quotas reste
   l'autorité et vérifie comme partout — il écarte simplement beaucoup moins, et
   le Sénégal converge donc plus vite que ses voisins.
2. **Aucune trace `secteur` ni `type juridique` Faker**, puisqu'il n'y a pas de
   matière Faker. Le secteur d'activité vient du moteur de quotas comme pour les
   autres pays.

## 8. Le test qui dira quand supprimer ce module

`test_le_contrat_faker_exclut_toujours_le_senegal` fige `PAYS_FAKER ==
{"BF","CI","CM"}`. **Si Oti ajoute SN un jour, ce test tombera** — et la bonne
réponse sera alors de **supprimer** la source interne, pas de la maintenir en
parallèle de Faker.

---

*10 appels en lecture seule le 11 août 2026, plus la lecture de l'OpenAPI. Chaque
ligne est reproductible ; le témoin de contrôle sur CM fait partie de la mesure.*
