# Revue de FZ-SPEC-DASHATTRIB-2026-001 · Conception de la durée configurable

**Référence** FZ-REVUE-DASHATTRIB-2026-001 · 25/08/2026 · note, pas du code
**Base** la spécification v1.0 lue intégralement + vérification de chaque
point contre le code du Loader et les mesures de production du 25/08.

---

# SUJET 1 — Revue de la spécification

## 1.1 Ce que je confirme, avec les preuves

**L'asymétrie tient à cinquante baux — très largement.** La vue de masse est
deux lectures Mongo internes : `attribution_baux` (50 documents) + la jointure
vers les nœuds clients (collection indexée, `idx_profil_client`). Mesure
d'ordre : quelques dizaines de millisecondes. `ENF-D02 < 1 s` a un facteur 10
de marge ; l'architecture tiendrait à cinq cents baux sans changer une ligne.
Et `ENF-D03 < 3 s` tient **à condition de paralléliser** : B d'abord (elle
donne `account_id`), puis C∥D∥E ensemble — mesuré ~1,5 s ; en séquentiel pur
on frôle les 3 s les mauvais jours.

**Les six règles AFF sont justes et suffisamment dures.** AFF-01 à AFF-06
transcrivent exactement les anomalies mesurées. Aucune n'est trop sévère.

**AFF-04 (« rattaché », jamais « actif chez ») est bien formulée — tu ne
durcis pas trop.** La règle interdit la *confusion*, pas l'*évolution* : le
jour où VIE existe, la source E fournira la preuve d'activité et l'écran
pourra afficher les deux vérités côte à côte, chacune sous son nom. La
formulation actuelle le permet sans révision. Je la garderais mot pour mot.

**Le panneau latéral plutôt qu'un sous-onglet** : exactement le bon choix —
un dossier se consulte en gardant la liste des baux sous les yeux, et c'est ce
que fait un poste de conseiller bancaire.

**§9 États limites, cas 3** : faire de l'asymétrie un atout en présentation
(la vue de masse survit à une plateforme muette) est la meilleure décision du
document.

**§11, « modification d'un bail en cours » exclue** : non seulement juste,
mais — voir Sujet 2 — c'est cette exclusion qui **répond d'avance** à la
question de migration de la durée configurable.

## 1.2 Ce qui est inexact — deux colonnes de source erronées

**§5.2, colonne « Interlocuteur — ⚡ Loader » : ce champ N'EXISTE PAS.** Le
bail porte six champs (msisdn, poignée, clé, profil, deux dates) — aucun
libellé libre. Le concept est bon et léger à construire (un champ `interlocuteur`
sur le document de bail + une route d'annotation **admin** — pas publique :
c'est une écriture, elle doit être authentifiée). Mais aujourd'hui la source
est `∅ à construire`, pas `⚡`.

**§5.2, colonne « Appareil — ⚡ Loader » : contradiction interne.** Le §12 dit
lui-même que le contrat interdit tout identifiant d'appareil — la table §5.2
le marque pourtant comme disponible. La colonne est `∅ + révision de contrat
explicite` (0.4, champ *optionnel* `appareil` transmis par l'app à
l'attribution — à trancher par toi, ce n'est pas un identifiant unique, juste
« Redmi Note 13 », compatible avec l'esprit d'INV-SIM-06 mais ça reste une
révision).

**§5.5, « Libération — origine de la libération » : l'origine n'est pas
tracée.** La route DELETE est publique et anonyme (ENF-07) ; le journal
enregistre l'événement, pas l'auteur. Distinguer « libéré depuis l'interface »
de « libéré par l'app (EF-17) » exige une route admin de libération distincte
qui journalise son auteur — léger, mais `à construire`, pas acquis.

## 1.3 Ce que la spécification ignore — quatre règles à ajouter

**AFF-07 (proposée) — un client, PLUSIEURS nœuds.** Chaque run écrit son
propre nœud : un client reconnu trois fois a trois nœuds. Toute jointure
bail→nœud doit **dédupliquer par msisdn et prendre le nœud le plus récent**
(le pool le fait déjà ; les écrans doivent suivre la même règle, sinon deux
écrans peuvent montrer deux kiosques de rattachement différents pour le même
bail).

**AFF-08 (proposée) — `product_ids` ment sur les nœuds de reprise.** `D-CLI-5`
mesuré : le serveur ne sait pas restituer les souscriptions d'un client
existant, donc les nœuds écrits par reconnaissance ont `product_ids` vide.
Conséquence : dans le **dossier**, les produits viennent de la source B
(`fiche.product[]`, toujours vraie) — jamais de A. La source A ne sert les
produits qu'en agrégat statistique, avec sa réserve.

**AFF-09 (proposée) — les horodatages plateforme sont NAÏFS.** Mesuré :
`created_at: "2026-08-25T04:23:24.877000"` — sans fuseau. Les nôtres sont
UTC-aware. Une campagne qui traverse GMT (Dakar) et WAT (Douala) affichera des
heures fausses d'une heure si on mélange. Règle : tout s'affiche dans UN
fuseau déclaré à l'écran (« heures en UTC » ou fuseau de l'étape).

**État limite n°4 (proposé) — la carte purgée.** Les baux sont protégés
(US-F3) mais les nœuds ne le sont pas : après une purge de carte, un bail échu
du journal n'a plus de territoire joignable. L'écran doit dire « territoire
inconnu — carte réinitialisée », pas afficher du vide. (La garde §1.5 empêche
le cas sur les baux *actifs* ; il ne concerne que l'historique.)

Deux mineures : les GPS sont nullables (la carte doit tolérer l'absence) ; et
si un écran additionne un jour des soldes, **jamais inter-devises** (XAF et
XOF coexistent) — la spec n'additionne rien aujourd'hui, je le pose en garde.

## 1.4 Coûts — rien d'infaisable, trois chantiers légers

| Élément de la spec | Réalité |
|---|---|
| Vue d'ensemble, Population, Baux (hors 2 colonnes) | données déjà là, ⚡ |
| Journal attributions/libérations/expirations | déjà là (journal + baux morts 30 j) |
| Champ Interlocuteur | à construire — léger (champ + route admin) |
| Journalisation des refus (§12) | à construire — léger, je confirme sa valeur |
| Origine des libérations | à construire — léger (route admin dédiée) |
| Colonne Appareil | révision de contrat d'abord — décision, pas technique |

## 1.5 La question précise : « attribués » par combinaison

**Oui, sans croiser deux sources plateforme — tout est chez nous, et c'est
déjà calculé.** `actifs_par_profil()` (agrégation d'`attribution_baux` par
pays×genre×catégorie) existe et sert déjà la route `/criteres`, qui calcule
`libres = total − attribués`... et ne rend que `libres`. Il suffit d'**exposer
les deux autres termes** (`attribues`, `total`) dans la même réponse — un
champ ajouté, zéro requête nouvelle, zéro appel plateforme. La grille
16 combinaisons × (libres/attribués/total) est une lecture ⚡ unique.

---

# SUJET 2 — La durée du bail devient configurable

## 2.1 Confirmation : le simulateur est indifférent — avec UNE réserve

**Tu ne te trompes pas sur le mécanisme** : l'app reçoit `expire_le`, le
stocke, le compare — jamais ne le calcule ; et la route de vérification (§3,
v0.3) resynchronise même l'échéance locale sur celle du serveur à chaque
lancement. Trois jours ou trente : le code de l'app ne voit pas la différence.

**La réserve — les MOTS de l'app, pas son code** : trois textes embarqués
disent « sept jours » (consigne de l'écran 4 « votre identité pour les sept
prochains jours », écran 13 « vos sept jours sont écoulés », confirmation de
rupture), et le CDC app (`EF-06`, `EF-07`) grave la durée. Avec un bail de
trois jours, ces écrans mentiraient. Correction de libellés à prévoir côté
app : afficher **la date d'échéance reçue** (« jusqu'au 28/08 ») au lieu d'une
durée — une PR de textes, aucun changement de logique.

## 2.2 Les baux en cours : ta préférence est la bonne — et elle est déjà imposée

**Option 1 — les baux existants gardent leur échéance.** Je la recommande sans
réserve, et pour deux raisons *structurelles* qui s'ajoutent à la tienne :

1. **L'idempotence l'exige déjà.** Le rejeu d'une clé rend « la même réponse
   201 » — donc le même `expire_le`. Recalculer les baux romprait ce contrat :
   la même clé rendrait deux échéances différentes selon l'heure du rejeu.
2. **Ta propre spec l'a tranché** (§11) : « un bail se libère ou expire, sa
   durée ne se négocie pas ». La migration option 1 est la seule cohérente
   avec cette exclusion.

L'option 2 (recalcul) créerait des expirations rétroactives ET des
vérifications qui passent de 200 à 404 sans cause visible — exclue. L'option 3
(choix opérateur) achète de la souplesse dont il n'existe aucun cas réel : pour
raccourcir UN bail précis, `EF-17` (libérer) puis réattribuer fait déjà tout,
proprement.

## 2.3 Où vit le réglage : global + surcharge PAR PAYS, sur le motif existant

Le Loader possède déjà exactement ce paradigme :
`ConfigurationExecution.resoudre(cle, pays)` — un défaut global, une
surcharge par pays, édité par les écrans de configuration existants
(US-B1/B2/B3). La durée du bail devient `bail_jours` dans cette mécanique
éprouvée : le tirage connaît `profil.pays`, il résout la durée à cet
instant-là. Une étape sénégalaise à 3 jours et une camerounaise à 15
coexistent sans que rien d'autre ne change. Coût : une lecture Mongo par
attribution (~1 ms), **fail-safe obligatoire** : configuration illisible →
défaut 7, jamais un crash.

## 2.4 Bornes : 1 à 30 jours

- **Minimum 1 jour.** Sous le jour, l'échéance peut tomber *pendant
  l'entretien lui-même*, et la combinaison vérification-au-lancement +
  horloges d'appareils rend les baux sub-journaliers piégeux. Une étape d'une
  demi-journée se gère par `EF-17`, pas par un bail de 4 heures.
- **Maximum 30 jours.** Au-delà, un numéro immobilisé plus d'un mois sans
  activité est un gel de pool que la libération manuelle sert mieux ; et 30
  garde la vie totale d'un document de bail bornée (échéance + rétention =
  60 jours max), ce qui garde le journal et les index sains.

## 2.5 Rétention : elle NE suit PAS la durée

Le TTL est « 30 jours **après l'échéance** » — il est indépendant de la durée
par construction, quelle qu'elle soit. Deux raisons de le garder fixe : un
index TTL Mongo ne se reconfigure pas proprement à chaud ; et la vraie
question — une campagne de plusieurs mois perd ses premières semaines — est
celle que ta spec pose déjà au §12 (« allonger la rétention ou archiver »).
C'est **ce chantier-là** qui traitera l'historique long, pas la durée du bail.
Recommandation : rétention fixe, décision d'archivage séparée.

## 2.6 Le contrat : révision 0.4, narrative seulement

**Aucun changement de schéma** — mêmes quatre routes, mêmes corps :
`expire_le` porte déjà toute l'information. La révision remplace les mentions
« sept jours » posées comme des faits (§0, §2) par : *« la durée du bail est
une politique du serveur, réglable par l'administration (défaut : sept
jours) ; `expire_le` fait foi, comme toujours »*. Côté CDC de l'app : `EF-06`
et `EF-07` reformulés de la même façon, et les trois libellés d'écran passent
à la date d'échéance (2.1).

## 2.7 Régression : aucune propriété touchée — et voici pourquoi, point par point

| Propriété prouvée | Effet de la durée configurable |
|---|---|
| Atomicité (`_id=msisdn`, insert unique) | inchangée — seul le CONTENU d'`expire_le` varie, pas le geste |
| Idempotence (rejeu = document stocké) | inchangée — et c'est elle qui impose l'option 1 de migration |
| Expiration paresseuse (`expire_le < now`) | inchangée — la comparaison ignore comment la date fut calculée |
| Distinction 409/500 | inchangée — aucun chemin d'erreur modifié |

Le seul point de vigilance : le calcul d'échéance passe d'une constante à une
résolution de configuration — d'où le fail-safe (§2.3) et un test dédié
(« configuration absente → 7 jours, jamais une exception »).

---

## Récapitulatif des recommandations

| # | Décision | Ma recommandation |
|---|---|---|
| 1 | Sources §5.2 Interlocuteur / Appareil | corriger en `∅ à construire` ; Appareil = décision de contrat d'abord |
| 2 | Règles AFF | ajouter AFF-07 (dédup nœuds), AFF-08 (produits source B), AFF-09 (fuseau), état limite n°4 |
| 3 | « Attribués » par combinaison | exposer `attribues`/`total` dans `/criteres` — trivial, ⚡ |
| 4 | Migration durée | **option 1**, imposée par l'idempotence et par ta propre §11 |
| 5 | Portée du réglage | global + surcharge par pays, motif `resoudre()` existant |
| 6 | Bornes | 1 à 30 jours |
| 7 | Rétention | fixe (30 j post-échéance) ; l'historique long = chantier archivage §12 |
| 8 | Contrat | révision 0.4 narrative ; libellés app → date d'échéance |
