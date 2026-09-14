# Résumé final — Référentiel des contrats opérateurs

**Annexe au `FZ-CDC-SANDBOX-2026-001`** · Établi le 2026-09-03
**Auteur** Kuate Abdel Yaniv (QA Lead / SDET)
**Branche** `feat/referentiel-contrats-operateurs` · **Commit** `30a5527`

---

## Ce qui est solide

Un seul contrat est réellement exploitable : **MTN**. Ses 53 opérations, ses 8 énumérations et ses
4 produits ont été récupérés et recomptés par mes soins, les JSON bruts sont versionnés. Son
`X-Target-Environment` publie **`mtncameroon`**, son idempotence est explicite (`X-Reference-Id`
UUID v4, rejet 409 `RESOURCE_ALREADY_EXIST`), ses statuts de transaction sont énumérés, et sa
sandbox offre 15 MSISDN de test déterministes.

Deux faits de périmètre décisifs : **le Cameroun n'est couvert que par MTN et Orange.** Airtel
(13 pays publiés), Moov (9 pays) et Areeba Guinée ne l'atteignent pas.

Trois résultats négatifs, prouvés et non supposés : Moov n'a **aucun** portail — le sous-domaine
`developer.` ne prouve rien, le DNS de `moov-africa.com` est un wildcard, vérifié en résolvant un
nom inventé. La documentation Airtel n'est **pas** à `/docs` — les chemins candidats renvoient la
même coquille SPA, à un compteur anti-cache près. Et la passerelle d'areeba **est** du Mastercard
MPGS : `epayment.areeba.com` partage l'IP `103.55.149.32` avec `ap.gateway.mastercard.com`.

Aucun des cinq opérateurs ne revendique la conformité GSMA.

## Ce qui manque

Le contrat technique de quatre opérateurs sur cinq n'est pas public : chemins, champs et codes
d'erreur proviennent de SDK communautaires, marqués `[TIERCE]` partout où ils apparaissent.

Trois trous se répètent chez tous sauf MTN, et ce sont les trois qui comptent pour une sandbox :
**l'idempotence**, **le contrat du webhook**, **les bornes de montant et la devise de test**. Le
premier est exactement le défaut prouvé sur le module Bulk (FRA-235, double paiement) : sans
contrat d'idempotence, ce défaut n'est pas testable. Sur le troisième : MTN teste en **EUR**,
Orange peut-être en `OUV` — **aucun jeu de données en XAF n'est rejouable tel quel.**

Le standard lui-même a un trou structurant : la GSMA rend `transactionStatus` obligatoire dans
toute réponse mais **ne l'énumère nulle part**. Elle normalise le cycle de vie de la requête et
celui du lot, pas celui de la transaction.

**Total : 59 trous opérateur, plus 10 dans le standard GSMA.**

## Niveau de confiance par opérateur

| Opérateur | Confiance | Motif en une ligne |
|---|---|---|
| **MTN MoMo** | **HAUT** | 53 opérations exactes, `mtncameroon`, idempotence sanctionnée, sandbox déterministe. Un profil s'écrit sans rien inventer. |
| **Orange Money** | **FAIBLE** | Contrat non public. Tunnel de paiement (redirection + OTP USSD, sans MSISDN marchand), tout le technique vient de SDK tiers. |
| **Airtel Money** | **FAIBLE** | Documentation entièrement sous connexion, **un compte par pays**, Cameroun absent. |
| **Moov Money** | **FAIBLE** | Aucun portail dans les 9 pays. Accès par courrier et dossier marchand. |
| **Areeba** | **FAIBLE** | Deux entreprises homonymes sans lien : la cible n'est pas identifiée. |

## Trois décisions qui reviennent à la direction

**D1 — S'inscrire ou non aux portails.** Douze des quatorze trous d'Orange se lèvent par un seul
geste : un compte sur `developer.orange-sonatel.com`, seul portail Orange annonçant un test
autonome avant dossier administratif. La mission l'interdisait expressément.

**D2 — De quel « Areeba » parle le cahier des charges ?** Deux entreprises, aucun lien établi par
aucune source. Trois lectures possibles, trois chantiers sans rapport.

**D3 — Le périmètre géographique.** S'il reste camerounais, **Airtel, Moov et Areeba en sortent**,
et 34 des 59 trous deviennent sans objet.

## Deux enseignements à réutiliser

**Les MSISDN de test déterministes de MTN** — un numéro par cas d'erreur, tout le reste en succès —
sont le meilleur mécanisme rencontré. À adopter tel quel dans la sandbox FinZuu, quel que soit
l'opérateur simulé.

**Le maker/checker de lot du socle GSMA** (`created` → `approved` → `completed`, avec `/rejections`
et `/completions`) décrit exactement ce que le module Bulk de la plateforme ne fait pas aujourd'hui.

## Réserves de méthode, déclarées

Une entorse partielle à la consigne « aucun appel vers une API opérateur » : deux `GET` non
authentifiés sur les **racines** `openapi.airtel.africa` et `openapiuat.airtel.africa` (401 les
deux, sans route métier ni identifiant). Le fait est isolé au § 0.2 de la fiche Airtel et **peut
être écarté** par la direction.

`developer.orange.com` (403 anti-robot) et `www.areeba.com` (403 Cloudflare) n'ont pas pu être
archivés en HTML brut. Trois sites Moov étaient injoignables (Mali, Gabon, Centrafrique) :
l'absence de portail y est **non prouvée**, seulement non contredite. Deux hôtes identifiés
(`apimarchand.moov-africa.bj`, `areeba.simplify.com`) n'ont **volontairement pas** été interrogés.

## Règle du référentiel

Un trou est un trou. Il est interdit de combler une case « NON DOCUMENTÉ » avec la valeur du socle
ou celle d'un autre opérateur, de présenter une source tierce comme officielle, ou d'arbitrer un
conflit sans en avoir la source. Les onze conflits recensés — dont trois internes à la
documentation de MTN et deux entre deux pages officielles d'Orange — sont consignés **des deux
côtés**, sans arbitrage.
