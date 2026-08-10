# Ce que JJB verra à l'écran — inventaire des artefacts de sondage

| | |
|---|---|
| **Objet** | Toutes les entités de test présentes dans l'environnement TEST, service par service, dans l'ordre où le serveur les rend. |
| **Mesuré le** | 10 août 2026 |
| **Pourquoi** | Premier risque **purement démonstration** du projet. Aucun de ces objets ne peut être supprimé sur trois des services concernés. |

> **Ces objets ne sont pas tous les nôtres.** Certains précèdent le projet
> (30-31 juillet), d'autres sont nos sondages des 7 et 8 août. Le tableau le
> distingue.

---

## 1. Companies — `GET /api/v1/companies/`

**8 entrées, triées par date décroissante.**

| # | Nom | Type | Créée le | Origine |
|---:|---|---|---|---|
| 1 | `DEMO_QA0808_SARL Tamadou Textile` | IMF | 08/08 16:39 | **nous** |
| 2 | `PROBE_IDENTITY_CASCADE` | BANK | 07/08 13:16 | **notre sonde** |
| 3 | `PROBE_GAP_ADMIN_CASCADE` | BANK | 07/08 11:03 | **notre sonde** |
| 4 | `PROBE_CASCADE_COMPANY` | BANK | 07/08 04:52 | **notre sonde** |
| 5 | `PROBE_CASQ1_COMPANY_XAF` | BANK | 07/08 03:33 | **notre sonde** |
| 6 | `FinTech4ESG` | MERCHANT | 31/07 14:35 | tiers |
| 7 | `TNS Agency` | BANK | 31/07 09:16 | tiers |
| 8 | `Aquiba SARL` | BANK | 31/07 08:47 | tiers |

**4 sondes sur 8.** Aucun `DELETE`, aucun `PATCH` sur ce service — **ni suppression ni renommage possibles**.

**Après une campagne complète** : 17 Companies `DEMO_*` plus récentes s'insèrent en tête. Les sondes descendent en **positions 18 à 21** — hors de la première page si la pagination est à 20.

---

## 2. Dépositaires — `GET /api/v1/depositaries/`

**12 entrées, et c'est le service le plus pollué : 11 sur 12 sont des artefacts de test.**

| # | Nom | Créé le | Origine |
|---:|---|---|---|
| 1 | `DEMO_QA0808_Kiosque Bepanda` | 08/08 16:53 | **nous** |
| 2 | `Depositaire Test` | 07/08 05:09 | tiers |
| 3 | `PROBE_Q2_CUSTOMER` | 07/08 05:09 | **notre sonde** |
| 4 | `PROBE_WITHDRAWAL_INACTIVE` | 07/08 05:02 | **notre sonde** |
| 5 | `PROBE_CASCADE_DEP` | 07/08 04:52 | **notre sonde** |
| 6 | `PROBE_STATUS_TEST_CLEAN2` | 07/08 04:37 | **notre sonde** |
| 7 | `PROBE_STATUS_TEST_CLEAN` | 07/08 04:34 | **notre sonde** |
| 8 | `PROBE_DIVERGENCE_CURRENCY` | 07/08 03:24 | **notre sonde** |
| 9 | `PROBE_CASQ1_DEVISE_BIDON` | 07/08 03:10 | **notre sonde** |
| 10 | `PROBE_CASQ1_DEP_TEST` | 07/08 02:15 | **notre sonde** |
| 11 | `Depositaire Test` | 31/07 09:24 | tiers |
| 12 | `Testtt` | 30/07 04:31 | tiers |

**8 sondes à nous, 3 objets de test antérieurs au projet.**

**Après une campagne complète** : 60 Kiosques `DEMO_*` en tête. Les 11 descendent en **positions 61 à 72** — invisibles sur les trois premières pages.

**Mitigation** : `PATCH /{id}/status/{bool}` existe. **Mais `FRA-203`/`FRA-204` ont
établi que « désactivé » n'arrête ni les collectes ni les retraits** — rien ne
garantit que le champ filtre l'affichage. **À vérifier avant de compter dessus.**

---

## 3. Produits — `GET /api/v1/products/` ⚠️ **le risque le plus concret**

**8 entrées seulement. C'est la liste la plus courte, donc celle où les déchets restent visibles.**

| # | Nom | Type | Créé le | Origine |
|---:|---|---|---|---|
| 1 | `DEMO_QA0808_Nano` | LENDING | 08/08 16:51 | **nous** |
| 2 | `plastique` | COLLECT | 04/08 18:04 | **préexistant — `D-PRD-9` le réutilise** |
| 3 | `Test_Produit_1785841588` | COLLECT | 04/08 11:06 | tiers |
| 4 | `PROBE_CASQUETTE5_1785569521712` | COLLECT | 01/08 07:32 | **notre sonde** |
| 5 | `PROBE_CASQUETTE5_1785569247112` | COLLECT | 01/08 07:28 | **notre sonde** |
| 6 | `PROBE_CASQUETTE5_1785569131001` | COLLECT | 01/08 07:26 | **notre sonde** |
| 7 | `Cotisation 20000/mois` | COLLECT | 31/07 21:46 | **doublon — `ANO-PRD-UNIQ-01`** |
| 8 | `Cotisation 20000/mois` | COLLECT | 31/07 09:13 | **préexistant, le plus ancien : celui que nous retenons** |

**Pourquoi c'est le cas le plus grave** : après la campagne, le catalogue comptera
**10 produits `DEMO_*` + 8 existants = 18**. Une page de 20 les montre **tous**.
Un bailleur regardant le catalogue produit verra `Test_Produit_1785841588` et
`PROBE_CASQUETTE5_1785569131001` **au milieu de l'offre commerciale**.

**Mitigation réelle** : **`PATCH /api/v1/products/{id}/deactivate` existe** —
c'est le seul service à en offrir une. Reste à vérifier si un produit désactivé
disparaît des listes ou porte seulement un drapeau.

---

## 4. Identités — `GET /api/v1/identities/`

**46 entrées.**

| Catégorie | Nombre | Exemples |
|---|---:|---|
| `PROBE_*` | **6** | `PROBE_Q3_CORPORATE`, `PROBE_Q3_SUCCESS`, `Probe` |
| `QA0808` | 2 | nos sondes du 8 août |
| `DEMO*` | **32** | `DEMOQA08092614F22`, `DEMOQA08093282B6C`… — **nos 32 identités du staff du 9 août** |
| tiers | 6 | `Aquiba`, `David`, `Dirigeant`, `JJ`, `Joe`… |

> ⚠️ **Les 32 identités `DEMO*` sont des orphelines.** Elles ont été créées lors
> du dry-run staff, sans User associé. C'est le motif de l'**écart 14** — la
> cascade partielle non protégée. Elles sont **définitives**, identity-service
> n'expose aucun `DELETE`.

**Peu visible en démonstration** : les identités ne sont normalement pas listées
dans une interface commerciale.

---

## 5. Groupes — `GET /api/v1/groupes/`

**16 entrées : 5 préexistants + 11 créés par nous.** Aucun déchet.
**Seul service avec un `DELETE` fonctionnel — prouvé le 9 août.**

---

## 6. Synthèse — ce qui sera visible le 14 août

| Service | Déchets | Visibles après campagne ? | Recours |
|---|---:|---|---|
| **Produits** | **4** | 🔴 **OUI — liste de 18, tout tient sur une page** | `PATCH /deactivate` — **à tester** |
| Dépositaires | 11 | 🟡 non — repoussés en positions 61-72 | `PATCH /status` — effet sur l'affichage inconnu |
| Companies | 4 | 🟡 non — repoussés en 18-21 | **aucun** — ni `DELETE` ni `PATCH` |
| Identités | 40 | 🟢 non listées en démonstration | aucun |
| Groupes | 0 | — | `DELETE` fonctionnel |

**Le seul risque à traiter avant le 14 est le catalogue produit.**

---

## 7. Ce qu'il faut décider

1. **Tester `PATCH /products/{id}/deactivate`** sur une de nos propres sondes
   `PROBE_CASQUETTE5_*` — vérifier si le produit disparaît de `GET /products/`
   ou porte seulement `is_active: false`. **10 minutes, sur nos objets, sans
   toucher à ceux des tiers.**

2. **Si la désactivation masque** : désactiver les 3 `PROBE_CASQUETTE5_*`.
   `Test_Produit_1785841588` n'est **pas à nous** — ne pas y toucher sans accord.

3. **Si elle ne masque pas** : l'assumer et préparer la phrase. Un environnement
   de TEST partagé contient des objets de test ; ce n'est pas anormal, ça
   s'explique en une phrase — à condition de ne pas le découvrir devant JJB.

---

*Mesuré par lecture seule. Aucune écriture n'a été faite pour produire ce
relevé.*
