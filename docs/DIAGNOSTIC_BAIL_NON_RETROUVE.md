# Diagnostic — le bail ne survit pas à la fermeture de l'application

**Référence** FZ-DIAG-BAIL-2026-001 · 25/08/2026
**Défaut rapporté** à la réouverture, l'écran de profil réapparaît et l'usager
refait une attribution — violation apparente d'`EF-06` et d'`INV-SIM-02`.
**Méthode** faits serveur d'abord (production), analyse du code ensuite.
Aucune correction n'a été apportée — ce document précède tout geste.

---

## 1. Les faits serveur — l'hypothèse 4 tombe en premier

Relevé de production, 25/08 :

```
attribution_baux : 2 BAUX ACTIFS
la plus longue échéance : 2026-09-01T08:46 UTC  → créé LE MATIN MÊME du constat
mes baux de preuve (04:51, 05:39) : tous deux LIBÉRÉS — ce ne sont pas eux
```

**Trois conséquences factuelles :**

1. **L'attribution a réussi — deux fois — depuis le téléphone.** L'hypothèse
   « stock épuisé, rien à persister » est éliminée : il y avait bien quelque
   chose à retrouver.
2. **Deux baux = deux clés d'idempotence distinctes.** Si l'application avait
   retrouvé sa tentative persistée (0.3.1) et re-soumis le même profil, le
   serveur aurait REJOUÉ le premier bail — il n'y en aurait qu'un.
3. **Le premier bail n'a jamais été libéré** : l'application ne savait plus
   qu'elle le détenait. Il immobilise un client pour rien jusqu'au 01/09 —
   c'est le symptôme d'exploitation exact que la Direction voulait éviter.

## 2. L'analyse du code — où chaque hypothèse se range

**H1 — « jamais écrit » : ÉLIMINÉE, par les faits.** Le code persiste la
tentative **avant** d'émettre (`ecrireTentative` est attendu avant le POST —
c'est l'ordre de la révision 0.3.1, vérifié dans `machine.ts`). Si les
écritures AsyncStorage échouaient, le POST ne partirait jamais — or deux baux
existent. **Les écritures fonctionnent sur cet appareil.**

**H3 — « effacé à tort après vérification » : ÉLIMINÉE, par les faits.** Les
deux baux sont **actifs côté serveur** — une vérification aurait rendu `200`,
jamais `404`. Et le seul chemin d'effacement (`acquitterBailEchu`) passe par
l'écran 13, que personne n'a rapporté avoir vu. La règle « on ne jette jamais
un bail sur un échec de vérification » est respectée par la machine à états.

**H2 — « écrit mais pas relu » : c'est ici, sous une forme que je n'avais pas
prévue.** Le défaut n'est pas dans la lecture — il est dans **le temps que
l'écran met à la refléter**. Le voici, dans le code livré :

```
App.tsx (démarrage)                    machine.demarrer()
──────────────────                     ──────────────────
destination initiale : 'accueil'       1. lireBail()            (local, ~ms)
   ↓ rendu IMMÉDIAT (ENF-02)           2. contrôle d'échéance   (local, ~ms)
ACCUEIL INTERACTIF affiché             3. verifierBail()        ← RÉSEAU,
   ↓ … pendant ce temps …                 timeout 15 s
setDestination(await demarrer())       4. alors seulement → 'composition'
```

**L'écran d'accueil est affiché, interactif, pendant toute la durée de la
vérification réseau** — jusqu'à 15 secondes sur un réseau mobile lent. Rien
n'indique qu'un bail existe et qu'une vérification est en cours. L'usager
voit l'écran de départ, conclut légitimement que son numéro est perdu, tape
« Commencer », traverse le profil, et re-attribue — **avant** que `demarrer()`
n'ait résolu. Chaque réouverture sur réseau lent reproduit le symptôme à
l'identique, et produit un bail orphelin de plus.

C'est **mon défaut de conception**, et il est subtil : la machine à états
honore la persistance (le bail *est* relu, la vérification *est* tolérante à
l'échec réseau) — mais **l'interface offre la phase 1 pendant la fenêtre de
vérification**, ce qui viole l'esprit d'`EF-06`/`INV-SIM-02` aussi sûrement
qu'une persistance cassée. La contrainte que j'avais moi-même écrite —
« le rendu n'attend AUCUN réseau » (ENF-02) — a été appliquée au mauvais
écran : elle vaut pour *afficher vite*, pas pour *afficher l'écran de départ
quand l'état local dit le contraire*.

## 3. Le diagnostic, en une phrase

> Le bail est écrit, il survit, il est relu — mais l'application route vers
> l'accueil interactif **avant** d'avoir consulté l'état local, et n'en sort
> qu'après une vérification réseau pouvant durer 15 secondes ; sur le terrain,
> l'usager re-attribue pendant cette fenêtre.

**Réserve d'honnêteté** : une défaillance stricte de lecture AsyncStorage sur
cet appareil précis ne peut pas être exclue à 100 % sans le téléphone en main
(il était débranché au moment du diagnostic). Les faits la rendent improbable
(les écritures fonctionnent, même API), et la correction ci-dessous la
couvrirait de toute façon — la preuve sur appareil (captures adb avant/après
redémarrage forcé) sera jointe dès que le téléphone est rebranché.

## 4. La clé d'idempotence — le trou 0.3.1 n'est PAS rouvert, mais il est contourné

Le code est conforme à 0.3.1 : clé **persistée avant l'émission**, effacée au
`201`, relue par `attribuer()` et réutilisée **si le profil demandé est le
même**. Le mécanisme est intact.

Mais le défaut d'écran le contourne : la clé n'est relue qu'au moment où
l'usager re-soumet un profil — et les deux baux distincts prouvent que ce
filet n'a pas suffi (profil différent à la seconde tentative, ou tentative
déjà effacée par le `201` de la première session — les deux sont cohérents
avec les faits). La correction du routage traite la cause ; le filet
d'idempotence reste ce qu'il est : un filet, pas la ceinture.

## 5. La correction proposée — après validation, pas avant

**Principe : l'état LOCAL commande le premier écran ; le réseau n'est jamais
sur le chemin du routage initial.**

1. `demarrer()` se scinde : une **décision locale immédiate** (bail présent et
   non échu à l'horloge locale → `composition`, sans attendre) ; la
   **vérification serveur passe en arrière-plan** et ne fait que corriger
   après coup (`absent` → écran 13 ; `200` → resynchronise l'échéance —
   conduites inchangées du contrat §3).
2. Pendant la vérification, l'écran de composition affiche le numéro stocké —
   l'usager retrouve « sa carte SIM » instantanément, conforme au principe
   fondateur. Aucun nouvel écran : c'est un ré-ordonnancement.
3. **Le test qui prouve** (exigé) : un test de la machine qui écrit un bail
   dans le dépôt, reconstruit une `Coordination` neuve (le « redémarrage »),
   et vérifie que la destination est `composition` **sans qu'aucun appel
   réseau n'ait été attendu** — le client de vérification étant un bouchon
   *lent*, le test échoue si le routage l'attend. Plus le miroir : bail échu
   localement → écran 13 ; vérification `absent` en arrière-plan → bascule
   vers 13.
4. **Nettoyage d'exploitation** : le premier bail orphelin (créé ce matin,
   jamais libéré) sera libéré via `EF-17` une fois la correction validée —
   ou expirera seul le 01/09.

**Effet de bord corrigé du même geste** : la fenêtre de re-attribution
disparaissant, plus aucun bail orphelin ne peut naître de ce chemin.

## 6. Anomalie secondaire découverte pendant le diagnostic

Le journal (`/admin/journal`, run administratif) montre **0 trace
`AttributionBail`** alors que le code journalise chaque attribution et
libération — mes propres cycles de preuve du matin devraient y figurer. Soit
la route filtre les types d'entités qu'elle connaît, soit `_journaliser`
échoue silencieusement (il est volontairement non bloquant). À élucider — ce
n'est pas le défaut du jour, mais le Journal du futur tableau de bord en
dépend directement.

---

*Diagnostic rendu avant toute correction, comme demandé. En attente de
validation pour : (1) la correction §5 et son test, (2) la preuve sur appareil
dès rebranchement, (3) puis le contrat 0.4 (appareil + durée configurable).*
