# Retest FRA-234 — canal USSD — 14/09/2026

**Question posée** : Brill (`finzuu.cm`) déclare de vive voix avoir corrigé le
défaut du `ussd-service`. Est-ce le cas ?

## VERDICT : INDÉCIDABLE AUJOURD'HUI — et c'est le résultat le plus utile du jour

**Le défaut ne peut ni être confirmé ni être infirmé tant que la plateforme n'a
pas de client onboardé.** TNS a vidé les bases de plusieurs services FinZuu : il
n'existe plus aucun client dans `client-service`, et le `ussd-service`
n'ouvre de session que pour un client **onboardé**. Toute mesure du callback
faite aujourd'hui confond deux causes possibles — « le moteur de menus est
toujours cassé » et « ce numéro n'appartient à aucun client connu ».

Ce qui est en revanche établi : **le ticket ne déclare aucune correction** (F4).

## F1 — version inchangée (indice, pas preuve)

`GET /openapi.json` → `info.version = 1.0.1`. Identique au 23/08 et au 04/09.
On peut corriger sans monter la version : cet élément ne tranche rien seul.

## F2 — schémas d'API inchangés (NE TRANCHE PAS NON PLUS)

Lu sans jeton dans `components.schemas` :

| Schéma | Champ texte | `required` |
|---|---|---|
| `CreateMenuSchema` | `text` (singulier) | `['key', 'text']` |
| `UpdateMenuSchema` | `text` (singulier) | — |

`text_en` / `text_fr` n'apparaissent nulle part.

⚠ **Ne pas en conclure que rien n'a été corrigé.** Le ticket proposait DEUX
corrections au choix : (a) exposer `text_en` / `text_fr` dans les schémas, **ou**
(b) **projeter `text` vers le couple bilingue dans les deux sens**. Avec
l'option (b), `CreateMenuSchema` garde légitimement `text` au singulier.
F2 exclut (a), pas (b). *Erreur d'analyse commise puis corrigée le 14/09.*

## F3 — mesures du callback : CONFONDUES, à ne pas verser au ticket

Contrat d'entrée conforme à la mesure du 24/08
(`{session_id, msisdn, input, new_session}`, `new_session` en **chaîne**).

| Essai | msisdn | Origine du numéro | Réponse |
|---|---|---|---|
| 1 | `237690000301` | **inventé** | `END Une erreur est survenue.` |
| 2 | `237693205141` | pool d'attribution du Loader | `END Une erreur est survenue.` |

**Aucun des deux ne vaut preuve** :

* l'essai 1 utilise un numéro arbitraire — défaut de méthode ;
* l'essai 2 semblait solide, il ne l'est pas. Le pool d'attribution est bâti par
  `app/routes/attribution_publique.py::_pool()`, qui lit
  **`OrgHierarchyRepository`** — la carte que le Loader garde de SES PROPRES runs
  passés — et **jamais `client-service` en direct**. Depuis la purge des bases
  FinZuu, ces msisdn sont des **fantômes** : présents dans notre carte, absents
  de `client-service`. Le `END` peut donc signifier « client inconnu ».

La continuation (`input=1`, `new_session="0"`) rend `END Your session has
expired.` — conséquence normale d'une session close par le `END` précédent,
pas un symptôme distinct.

*Effet de bord assumé et annulé* : un bail a été tiré sur le Loader de
production pour l'essai 2 (`fd5cde1c-e3c5-4b10-b3bf-3062693e5123`,
msisdn `237693205141`) puis **libéré** — `DELETE` → `204`. Aucun résidu.

## F4 — le ticket ne déclare aucune correction (ÉTABLI)

Historique complet de FRA-234, trois entrées, rien d'autre :

| Date | Auteur | Changement |
|---|---|---|
| 23/08 19:44 | akuate | assignation à `finzuu.cm`, priorité Medium → **Highest** |
| 23/08 19:45 | akuate | Backlog / A Qualifier → To Do / Qualifié |
| **09/09 09:46** | **finzuu.cm** | To Do / Qualifié → **Fixing / In Dev** |

Statut actuel **`Fixing / In Dev`**, `resolution: null`, un seul commentaire (le
retest du 04/09, de nous). Brill a **pris** le ticket le 09/09 ; il ne l'a jamais
passé à `Done / API ready` — seul statut qui déclare une correction dans le
workflow FRA — et n'a laissé aucun commentaire décrivant un correctif.

**C'est le seul fait solide du jour** : ce qui est dit de vive voix n'est écrit
nulle part et, à la date du 14/09, le workflow dit « en cours ».

## Erreur de sondage commise et corrigée le 14/09 — à ne pas refaire

`GET /api/v1/ussd/menus/MAIN` **sans jeton** rend `401 Authentication required.
Code: 4012`. Lu d'abord comme un changement (le 04/09 la même route rendait
`400`). **Faux** : le ticket écrit dès le 23/08 que « l'authentification
fonctionne (`GET /menus/` sans jeton → 401 code 4012) » — les `400` ont tous été
mesurés **avec un Bearer ROOT**. Le 401 est le comportement normal, inchangé.
Les deux routes `menus` ne se retestent qu'avec un jeton ROOT.

## LE SEUL PROTOCOLE QUI TRANCHERA

Dans cet ordre — aucune étape n'est sautable :

1. **Déverrouiller le compte ROOT** (`423 Account locked`) par le flux OTP —
   voir le retest login du 14/09.
2. **Purger le Loader** (US-F3) : sa carte décrit un environnement qui n'existe
   plus. Sans purge, tout run repart sur des références mortes.
3. **Nouveau run REAL** : recharger organisation, catalogue, dépositaires,
   staff, puis **clients onboardés** dans `client-service`.
4. **Relever un msisdn réellement onboardé** — `GET /api/v1/clients/by-msisdn/
   {msisdn}` doit rendre 200 — et seulement ALORS rejouer les trois étapes de la
   section « Vérification après correctif » du ticket :
   `POST /menus/` → 201 · `GET /menus/MAIN` → 200 · `POST /callback` → `CON`.

Tant que l'étape 4 n'est pas atteinte, **rien ne doit être versé au ticket**.

## Conséquence sur le périmètre — inchangée

FRA-77, FRA-78, FRA-79 restent non livrables. Le simulateur USSD reste bloqué en
phase 2 ; sa phase 1 (attribution, notre Loader) est indépendante et fonctionne.
Ancienneté du défaut : **22 jours**.
