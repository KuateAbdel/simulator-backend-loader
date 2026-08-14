# Reconnaissance PASSIVE du 14/08/2026 — « on ne doit pas être surpris »

Demandée par Yaniv le 14/08 : tout vérifier, partout où le Loader devra
interagir, EN DÉTAIL, avant l'hébergement et les paliers. **Lectures
seulement** — pas une seule écriture n'est partie. Sondes : `/health` des 9
services, listes complètes de config/user/product/company/depositary/client/
identity/collect, santé Faker. Deux passes (le réseau WSL a flanché sur la
seconde — un fait en soi, voir S6) + reprises ciblées.

Verdicts : ✅ CONFORME à l'hypothèse enregistrée · ⚠️ SURPRISE (hypothèse à
corriger) · 🔴 DÉCISION YANIV requise.

---

## S1 — 🔴 LES 11 RÔLES D-09 EXISTENT DÉJÀ SUR USER-SERVICE

**16 groupes** relevés, pas 4 : les historiques (ROOT, CUSTOMER 12 perms,
GUEST, COMPANY) + un **« STAFF » tag COMPANY** jamais mesuré avant (pas à
nous — hors ROLES_METIER) + **nos 11 rôles exactement** :

| Rôle | tag | permissions |
|---|---|---|
| Super-Admin | STAFF | 61 |
| Admin | COMPANY | 38 |
| Compliance | STAFF | 18 |
| Employe/IT | STAFF | 18 |
| Marketing | COMPANY | 9 |
| Branche | COMPANY | 7 |
| Kiosque | COMPANY | 6 |
| Collecte | COMPANY | 6 |
| Marchand | COMPANY | 5 |
| Comptable | COMPANY | 5 |
| Agent | COMPANY | 5 |

Les tags collent à D-09 v2 et les comptes de permissions collent à
`_permissions_du_role` sur les 61 permissions filtrées : **c'est notre
empreinte** — une écriture réelle antérieure (avant la journalisation des
groupes, livrée le 13/08 seulement). Conséquences mesurables :

- le PALIER 1 en REAL créera **ZÉRO groupe** (idempotence par nom : 11
  réutilisés) — le palier devient une simple collecte de group_id ;
- notre **registre est vide** → l'inventaire les classe ÉTRANGERS, la purge
  ne les touchera jamais, le DELETE individuel les refuse (403) ;
- **DÉCISION à trancher : les ADOPTER au registre** (mécanisme d'adoption
  explicite, journalisé — jamais automatique : adopter d'office ce qui nous
  ressemble referait le défaut de confiance) **ou les laisser étrangers**.

## S2 — ⚠️ SIX PAYS EN BASE, PAS QUATRE — dont un code ISO invalide

`ca` (minuscule !) et `CV` en plus de CM/CI/BF/SN. Chacun : 0 ville, 1 telco.
Les 4 cibles sont là ✅, jamais recréées ✅. Mais l'hypothèse « 4 pays lus »
est PÉRIMÉE, et `ca` **viole ISO 3166-1 alpha-2** (minuscule) — notre
validation stricte (`^[A-Z]{2}$`) nous protège d'en consommer ; l'inventaire
pays doit les montrer comme étrangers constatés.

## S3 — ✅ ANO-PRD-UNIQ-01 CONFIRMÉE EN VIE : le doublon existe déjà

product-service porte **« Cotisation 20000/mois » EN DOUBLE** (2 fiches, ids
distincts). La plateforme accepte le doublon de nom — ce n'est plus une
anomalie théorique, elle est DANS la base. Notre protocole à deux clés et
l'autorité d'unicité côté Loader sont indispensables, preuve sur pièce.
8 produits au total, aucun DEMO_, tous les ids UUID.

## S4 — ⚠️ LES RÉSIDUS DE NOS PROBES SONT LÀ, PERMANENTS — comme prévu, mais comptés

- company-service : 12 companies dont **8 PROBE_*** (12/08) et
  **DEMO_QA0808_STT** (écriture réelle du 09/08). AUCUN DELETE : confirmé.
- depositary-service : 12 dépositaires dont 1 DEMO_.
- client-service : 26 clients · identity : 57 identités · collect :
  **13 collectes déjà présentes** sur l'environnement TEST.
- config-service : **PROBE_TELCO_0317 toujours en base** (10/08) — 15 telcos
  au total, 3 rattachés à chaque pays cible, toutes les regex compilent ✅.

L'environnement TEST n'est PAS vierge : la réconciliation (statuts
à_nous/étranger/marqué_mais_inconnu) était la bonne conception.

## S5 — ⚠️ DEUX CONTRATS DE LECTURE DIFFÉRENTS POUR LE MÊME TELCO

La liste globale `/telcos` rend `{_id, name, phone_regex, is_active, ...}` —
**pas** `network_name`/`short_name`/parts de marché, qui n'existent que dans
le telco EMBARQUÉ du pays. Deux formes pour le même objet : toute lecture de
telcos doit dire LAQUELLE elle consomme. (Nos clients utilisent la forme
embarquée — c'est la bonne.)

## S6 — ⚠️ LE RÉSEAU DEPUIS LA MACHINE DE DEV EST DISQUALIFIÉ — mesuré

`/health` : 4 à 6 s PAR SERVICE depuis WSL ; DNS en échec intermittent
(« Temporary failure in name resolution ») ; product-service en
ConnectTimeout sur une passe ; Faker santé true puis false à 2 minutes
d'écart. **ENF-01 (2000 clients en 30 min) est intenable d'ici** — la
décision C-0 « héberger avant de charger » n'est plus un choix, c'est la
seule voie mesurée. Les timeouts/retries de nos clients devront être
recalibrés depuis le serveur.

## S7 — ✅ CE QUI COLLE EXACTEMENT AUX HYPOTHÈSES

- Permissions filtrées : **61** (84 brutes − 22 LENDER_* − RC169) — le compte
  exact de D-07. Aucun doublon de nom de groupe.
- Pays : 12-14 villes plates chacun, sans région/quartier — notre richesse
  interne (51/50/82) n'existe QUE chez nous, l'anti-corruption est justifiée.
- 5 devises. Fiche pays : 13 champs en lecture (les 9 d'écriture + horodatages
  et `_id`) — la relecture 9 champs reste le bon contrat d'ÉCRITURE.
- Tous les identifiants relevés sont des UUID **aujourd'hui** — mais aucun
  contrat ne le promet : `uuid_stable` (QA du 14/08) reste nécessaire.
- 9 services /health 200 (product en timeout UNE fois sur deux passes — voir S6).

---

**Actions issues de cette reconnaissance** : (1) 🔴 arbitrage Yaniv —
adoption des 11 rôles préexistants au registre, mécanisme explicite à
concevoir si oui ; (2) mettre à jour D-06/D-09 (« 4 groupes » → 16 relevés,
« STAFF » constaté) ; (3) l'inventaire pays doit montrer `ca`/`CV` comme
étrangers ; (4) recalibrer les timeouts depuis le serveur après hébergement ;
(5) aucune écriture n'a eu lieu — ce rapport est rejouable à l'identique.
