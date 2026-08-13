# Backlog produit — Super-Admin du Loader FinZuu

> Rédigé le 13/08/2026. Remplace le §5 de `CONCEPTION_API_SUPER_ADMIN.md`
> comme référence de travail : même périmètre, format canonique.
>
> **Conventions** : chaque story suit « En tant que… je veux… afin de… » ;
> critères d'acceptation en Gherkin (Étant donné / Quand / Alors) ; priorité
> MoSCoW (Must / Should / Could / Won't-v1) ; chaque story cite ses exigences
> CDC. L'acteur est toujours **le Super-Admin du Loader** (« l'Admin ») —
> jamais celui de la plateforme (`MODELE_UTILISATEURS.md` §1).
>
> **Definition of Done commune** (s'applique à chaque story, sans exception) :
> route implémentée + schéma OpenAPI publié sur `/docs` · ruff + mypy propres ·
> tests unitaires ET tests d'API (httpx) verts · comportement d'erreur testé
> (401, 409, 422 avec motif) · journalisée dans `audit_trail` si elle écrit ·
> aucune écriture qui contourne un exécuteur existant.

---

## ÉPOPÉE 1 — Session & sécurité

### US-A1 · Connexion — **Must** · EF-50, CR-05
**En tant qu'**Admin du Loader, **je veux** me connecter avec mon email et mon
mot de passe, **afin de** piloter l'outil sans assistance technique.

```gherkin
Étant donné le compte créé par le bootstrap au premier démarrage
Quand je soumets email + mot de passe valides sur POST /admin/auth/login
Alors je reçois un jeton de session à durée limitée
Et aucun mot de passe n'apparaît dans les logs ni dans la réponse

Étant donné un mot de passe erroné
Quand je tente de me connecter
Alors je reçois 401 sans indication sur lequel des deux champs est faux
```

### US-A2 · Premier mot de passe forcé — **Must** · sécurité bootstrap
**En tant qu'**Admin, **je veux** être obligé de changer le mot de passe
initial à la première connexion, **afin qu'**aucun secret de bootstrap ne
survive à la mise en service.

```gherkin
Étant donné un compte avec must_change_password=True
Quand je me connecte avec succès
Alors toute route autre que POST /admin/auth/password répond 403
Et après le changement, must_change_password passe à False définitivement
```

---

## ÉPOPÉE 2 — Configuration & référentiels

### US-B1 · Lire la configuration résolue — **Must** · EF-50, CFG-01→04
**En tant qu'**Admin, **je veux** voir chaque paramètre avec sa valeur ET son
origine (défaut CDC, surcharge pays, région ou ville), **afin de** savoir ce
qu'un run utilisera réellement avant de le lancer.

```gherkin
Étant donné une surcharge « nb_clients=300 » posée sur le Sénégal
Quand je lis GET /admin/configuration
Alors la valeur SN affiche 300 avec origine "surcharge pays"
Et les autres pays affichent 500 avec origine "défaut CDC (2000/4)"
```

### US-B2 · Modifier les volumes — **Must** · EF-10, EF-14→17, EF-20
**En tant qu'**Admin, **je veux** régler les volumes (clients, companies,
branches, agences, kiosques, agents) par niveau géographique, **afin d'**
adapter la génération à chaque environnement (TEST, DEMO, client).

```gherkin
Étant donné aucun run en cours
Quand je soumets PUT /admin/configuration avec nb_clients=1000
Alors la valeur est persistée et relue à l'identique
Et le DRY_RUN suivant annonce 1000 clients

Étant donné un quota hors des bornes du CDC (ex. femmes à 10 %)
Quand je soumets la modification
Alors je reçois 422 citant l'exigence violée (EF-22 : « 2 femmes / 1 homme »)

Étant donné un run à l'état EN_COURS
Quand je soumets une modification quelconque de configuration
Alors je reçois 409 avec l'identifiant du run qui verrouille (EF-55)
```

### US-B3 · Activer / désactiver un pays — **Must** · EF-05, A-08
**En tant qu'**Admin, **je veux** activer ou désactiver un pays pour les
prochains runs, **afin de** générer par périmètre — sans jamais toucher au
config-service partagé par accident.

```gherkin
Étant donné le Sénégal actif
Quand je le désactive côté Loader
Alors le prochain DRY_RUN annonce 3 pays et 1500 clients
Et AUCUN appel n'est parti vers PATCH /countries/deactivate de config-service

Étant donné que je veux désactiver côté SERVEUR (action distincte, A-08)
Quand je l'invoque
Alors une confirmation dédiée m'avertit que config-service est PARTAGÉ
```

### US-B4 · Ajouter une ville — **Must** · CFG-05/06, EF-02
**En tant qu'**Admin, **je veux** ajouter une ville (région, 9 champs, GPS)
sans modifier le classeur source, **afin d'**enrichir la géographie de façon
réversible.

```gherkin
Étant donné une région existante du Cameroun
Quand je soumets une ville complète
Alors elle est relue champ par champ avant persistance (CFG-06)
Et l'arbre géographique la porte au prochain GET
Et le classeur Loader_Base_FinZuu_v1_1.xlsx est resté intact
```

### US-B5 · Consulter les référentiels — **Must** · EF-51
**En tant qu'**Admin, **je veux** consulter tous les référentiels (arbre géo
51/50/82 avec GPS, 12 telcos et parts de marché, 576 professions par groupe et
profil de revenu, 112 secteurs × 6 industries, 27 formes, 20 fonctions,
195 pays), **afin de** comprendre la matière dont chaque entité sera composée.

```gherkin
Quand je lis GET /admin/referentiels/catalogue-statique
Alors les comptes sont exactement 6/112/27/576/21/4/195/20
Et chaque profession porte son groupe et son profil de revenu (mu, sigma)
```

### US-B6 · Demander un nouveau pays — **Could** · EF-05 (refus pédagogique)
**En tant qu'**Admin, **je veux** demander l'ajout d'un 5ᵉ pays et recevoir la
liste exacte de la matière manquante, **afin de** préparer une future
extension au lieu de me heurter à un mur.

```gherkin
Quand je soumets un pays hors des 4 cibles
Alors je reçois 422 listant : régions, villes, plan de numérotation telco,
      parts de marché, patronymes — chaque manque nommé
Et rien n'est modifié
```

---

## ÉPOPÉE 3 — Les runs

### US-C1 · Préparer un run (à blanc) — **Must** · EF-52, D-01
**En tant qu'**Admin, **je veux** lancer une préparation qui exécute tout À
BLANC, **afin de** lire ce que le réel ferait — « la dernière occasion de dire
non » — avant toute écriture sur des services sans DELETE.

```gherkin
Étant donné une configuration valide et aucun run en cours
Quand je poste POST /admin/runs {mode: DRY_RUN}
Alors je reçois un run_id et le rapport complet : quotas par pays, solde
      total qui SERA déposé, 12 produits, refus avant réseau avec motifs
Et AUCUNE requête d'écriture n'est partie vers FinZuu
```

### US-C2 · Confirmer le passage en réel — **Must** · EF-52, EF-55, D-01
**En tant qu'**Admin, **je veux** confirmer explicitement l'exécution réelle
d'une préparation que j'ai lue, **afin que** l'écriture irréversible ne soit
jamais un défaut ni un accident.

```gherkin
Étant donné un DRY_RUN terminé et lu
Quand je poste POST /admin/runs/{id}/confirmer
Alors le run REAL démarre sur LE MÊME périmètre figé au moment du DRY_RUN

Étant donné un autre run à l'état EN_COURS
Quand je confirme
Alors je reçois 409 avec l'identifiant du run en cours (EF-55)

Étant donné une configuration modifiée APRÈS le DRY_RUN
Quand je confirme
Alors je reçois 409 « le périmètre a changé — re-préparer » (D-01)
```

### US-C3 · Suivre la progression — **Must** · EF-53
**En tant qu'**Admin, **je veux** voir la progression en temps réel (palier
1→8, compteurs par pays, erreurs au fil de l'eau), **afin de** surveiller sans
lire des logs.

```gherkin
Étant donné un run EN_COURS au palier CLIENTS
Quand je lis GET /admin/runs/{id}/progression
Alors je vois le palier actif, 4 compteurs pays sous la forme fait/cible,
      et les N dernières erreurs horodatées avec leur motif tronqué
```

### US-C4 · Arrêter proprement — **Must** · D-FAKER-1
**En tant qu'**Admin, **je veux** arrêter un run en cours proprement, **afin
de** ne laisser ni réservation orpheline ni écriture à moitié faite.

```gherkin
Étant donné un run EN_COURS
Quand je poste POST /admin/runs/{id}/arreter
Alors le lot en cours se termine, le registre Faker est réconcilié
Et le rapport final porte l'état PARTIAL avec le point d'arrêt exact
```

### US-C5 · Reprendre après interruption — **Must** · CR-03, D-CLI-5
**En tant qu'**Admin, **je veux** relancer le même périmètre après une panne,
**afin de** compléter l'écosystème sans créer un seul doublon.

```gherkin
Étant donné un run REAL interrompu à 60 %
Quand je relance le même périmètre
Alors les entités existantes sont reconnues (registre + GET-avant-POST)
Et seul le manquant est créé — le rapport distingue « déjà présents » de « créés »
```

### US-C6 · Historique et recette — **Must** · EF-56, CR-01→12, CR-06
**En tant qu'**Admin, **je veux** consulter chaque run passé avec son rapport,
sa recette (13 critères, verdict TENU/VIOLÉ/NON VÉRIFIABLE avec raison) et sa
réconciliation Faker, **afin de** prouver la conformité à tout moment.

```gherkin
Quand je lis GET /admin/runs/{id}
Alors la recette porte les 13 critères CR, chacun avec verdict ET raison
Et l'historique est append-only : aucune route de suppression n'existe
```

---

## ÉPOPÉE 4 — Entités à l'unité

### US-D1 · Créer une Company depuis le Loader — **Should** · UC-07/08, S3-03
**En tant qu'**Admin, **je veux** saisir 3-4 champs (type, pays, ville, nom
optionnel) et voir l'aperçu COMPLET composé par le Loader (secteur+industrie,
forme juridique, dirigeant avec fonction et lieu de naissance, licences, GPS),
**afin de** créer sur la plateforme une Company aussi riche que celles des
runs — sans en connaître les 40 champs.

```gherkin
Étant donné le formulaire soumis avec type=MERCHANT, pays=CM, ville=Douala
Quand je demande l'aperçu
Alors je vois la fiche complète SANS qu'aucun appel d'écriture ne soit parti
Quand je confirme
Alors la séquence S3-03 s'exécute (company → licences → admin user → comptes)
Et la fiche affichée est RELUE depuis la plateforme, jamais déduite (FRA-218)

Étant donné une composition qui violerait un invariant
Quand je demande l'aperçu
Alors je reçois le refus AVANT réseau avec l'invariant nommé
```

### US-D2 · Créer un produit COLLECT — **Must** · UC-11, D-PRD-1→9, D-12, EF-35, ANO-PRD-UNIQ-01, ANO-PRD-POLICY-01, INV-PRD-07
**En tant qu'**Admin, **je veux** créer un produit de collecte complet côté
Loader — qui, une fois validé chez nous, est envoyé à la plateforme et relu —
**afin que** le Loader et la plateforme portent EXACTEMENT le même catalogue,
avec une rigueur que product-service n'a pas.

**Le formulaire, champ par champ (rien d'implicite) :**

| Champ | Règle STRICTE côté Loader | Ce que la plateforme ferait, elle |
|---|---|---|
| `name` | Nom métier réel, non vide, unique dans NOTRE registre | Accepte les doublons (`ANO-PRD-UNIQ-01`) |
| `short_name` | Généré : `DEMO_` + code court déclaré, unique, jamais vide | Champ libre, aucune contrainte |
| `type` | `COLLECT` seul en v1 (`perimetre_lending` fermé) | Accepte LENDING sans garde |
| `category` | `INDIVIDUAL` ou `CORPORATE` — jamais implicite | — |
| `policy.type` | `CASH` / `CASH_DAT` / `PRODUCT`, choisi explicitement | — |
| `policy` entière | EMBARQUÉE, complète — JAMAIS un `policy_id` partagé | `policy_id` partagé corrompt en silence (`INV-PRD-07`) ; `policy` absente = HTTP 500 (`ANO-PRD-POLICY-01`) |
| `interest_rate` | ≤ 24 % (plafond d'usure BEAC/COBAC, `EF-35`) | Accepte 99 % (mesuré sur « Cotisation 20000/mois ») |
| `measure` | TOUJOURS explicite — le mil se pèse, le lait se mesure (`D-PRD-8`) | La WebApp injecte KILOGRAM en dur sans le dire |
| `amount_min` / `amount_max` | `0 < min < max`, cohérents avec la catégorie | Accepte min=max=3 (mesuré sur « plastique ») |
| `duree_mois` | OBLIGATOIRE si `CASH_DAT`, INTERDIT sinon — un dépôt à terme sans terme n'existe pas | Aucun champ de durée sur COLLECT : le Loader la porte et la matérialise dans `CollectSchema.end_date` |
| `penalty_*` | Renseignés, jamais laissés au hasard du serveur | — |
| `description` | Préfixée « Jeu de données DEMO Loader FinZuu » | — |

**L'UNICITÉ — la discipline que la plateforme n'a pas, et que le Loader impose :**

```gherkin
Étant donné que product-service n'impose AUCUNE unicité (mesuré : deux
  « Cotisation 20000/mois » coexistent avec des abonnés sur chacune)
Alors le Loader est l'AUTORITÉ d'unicité, sur DEUX clés à la fois :
  - `name` unique dans notre registre ET vérifié par GET-avant-POST
  - `short_name` unique dans notre registre ET vérifié par GET-avant-POST
Et aucune création ne part si l'une des deux clés est déjà prise

Étant donné un nom déjà porté par un produit ÉTRANGER sur la plateforme
  (nom présent, notre short_name absent)
Quand je confirme la création
Alors elle est REFUSÉE avant réseau : ni consommé (A-10), ni doublé (D-12)
Et le motif nomme le produit étranger (_id, short_name) pour que je comprenne

Étant donné un nom identique à un produit de l'ENVIRONNEMENT
  (« Cotisation 20000/mois », « plastique »)
Quand je saisis le nom
Alors le refus est immédiat, avant même l'aperçu
```

**Le flux complet — validé chez nous PUIS poussé, jamais l'inverse :**

```gherkin
Étant donné un formulaire valide
Quand je demande l'aperçu (POST /admin/entites/produits — étape 1)
Alors je vois le payload EXACT qui partirait, policy embarquée comprise
Et AUCUN appel d'écriture n'est parti

Quand je confirme (étape 2)
Alors le Loader journalise l'intention (write-ahead), POSTe le produit,
  RELIT la fiche depuis la plateforme (jamais déduite — FRA-218),
  l'enregistre dans NOTRE registre produits (l'autorité d'unicité),
  et me montre la fiche RELUE avec son product_id
Et le produit est immédiatement souscriptible dans le prochain run —
  Loader et plateforme sont COHÉRENTS, par construction

Étant donné un champ invalide (taux 25 %, min > max, CASH_DAT sans durée...)
Quand je demande l'aperçu
Alors je reçois 422 avec CHAQUE champ fautif et sa règle nommée —
  le Loader est plus strict que product-service, jamais moins
```

### US-D3 · (Won't-v1) Créer du LENDING, supprimer une entité
LENDING attend le sprint 8 (`perimetre_lending`). La suppression n'existera
jamais pour identity/account/depositary : l'interface **affiche** cette
impossibilité au lieu de la cacher.

---

## ÉPOPÉE 5 — Visualisation

### US-E1 · Vue d'ensemble — **Must** · EF-57
**En tant qu'**Admin, **je veux** un atterrissage qui montre la santé des
9 services FinZuu, l'état du run courant/dernier, les compteurs par pays et
les alertes ouvertes, **afin de** juger l'état du système en dix secondes.

```gherkin
Quand je lis GET /admin/dashboard
Alors chaque service FinZuu porte son état (up/down) et sa latence du dernier /health
Et les compteurs viennent de NOS collections — aucun appel paginé vers FinZuu
```

### US-E2 · Écosystème navigable — **Must** · EF-58, EF-26
**En tant qu'**Admin, **je veux** descendre l'arbre pays → company → branch →
agence → kiosque → clients rattachés, **afin de** voir la structure que la
plateforme elle-même ne sait pas montrer (org_hierarchy est à nous).

### US-E3 · Population — **Must** · EF-22/23/24, CR-09, EF-68
**En tant qu'**Admin, **je veux** les distributions de la population (âges,
genres, 576 métiers dont part agricole, histogramme des soldes avec le seuil
150 000, les 4 profils 50/25/13/12, les naissances à l'étranger), **afin de**
présenter l'écosystème à un bailleur sans requête SQL.

```gherkin
Quand je lis GET /admin/dashboard/population?pays=CM
Alors chaque distribution porte la MESURE et la CIBLE côte à côte
Et les chiffres sont identiques à ceux de la recette du dernier run
```

### US-E4 · Traçabilité — **Must** · CR-06, D-FAKER-1
**En tant qu'**Admin, **je veux** consulter le registre Faker (chaque client
réservé/confirmé/libéré) et le journal d'audit horodaté, **afin de** répondre
« d'où vient cette entité ? » sur n'importe laquelle.

---

## ÉPOPÉE 6 — Purge

### US-F1 · Préparer une purge — **Should** · EF-59/EF-65, CR-07
**En tant qu'**Admin, **je veux** voir la liste EXACTE de ce que le marqueur
retrouve, service par service, et ce qui n'est PAS purgeable, **afin de**
décider en connaissance de cause.

```gherkin
Quand je poste POST /admin/purge/preparer
Alors je vois par service : le compte purgeable (DELETE existant) et le
      compte NON purgeable (identity/account/depositary), jamais caché
Et les produits sont retrouvés par short_name, les autres entités par préfixe
```

### US-F2 · Confirmer la purge — **Should** · EF-65
```gherkin
Étant donné une préparation lue
Quand je confirme
Alors seul le réversible est supprimé, chaque suppression journalisée
Et le rapport final liste les résidus marqués restants
```

---

## Hors périmètre v1 (Won't), dit explicitement
Multi-comptes admin et rôles de lecture · ajout d'un 5ᵉ pays actif ·
LENDING · édition manuelle des référentiels · suppression d'historique ·
tout appel direct du frontend vers FinZuu.

## Correspondance lots d'implémentation
Lot A = US-A1..B6 · Lot B = US-C1..C6 · Lot C = US-E1..E4 ·
Lot D = US-D1..D2 · Lot E = US-F1..F2.
