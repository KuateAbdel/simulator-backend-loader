# Jugement des notes de Yaniv sur le travail de Duhamel

> Écrit le 12/08/2026 à la demande de Yaniv : *« lis-les, regarde et juge, ne
> consiste pas à vérifier si j'ai tort ou raison ».*
>
> Méthode : chaque affirmation est confrontée au **CDC v1.2** (docx extrait, 1197
> lignes) et à `docs/reference/duhamel_lifecycle_orchestrator_EXTRAIT.py`.
> Verdict par ligne, avec la référence. Aucune complaisance : deux points sont
> faux, et **l'un des deux me corrigeait moi aussi**.

---

## Verdict d'ensemble

**Sur 24 affirmations vérifiables : 19 justes, 2 fausses, 3 imprécises.**

Et surtout : ces notes **sont devenues** les modules 7.8 et 7.10 du CDC v1.2, plus
l'Annexe D. Elles ne décrivent pas seulement le travail de Duhamel — elles sont la
trace de la conception qui a produit le cahier des charges que nous appliquons.
Yaniv le dit lui-même : *« c'est ce qu'on faisait avant lorsqu'on concevait le CDC
que tu vois aujourd'hui »*.

---

## 1. Ce qui est JUSTE, et vérifié

| Affirmation | Verdict | La preuve |
|---|:---:|---|
| Les 5 modules (`kafka_consume`, `repayment_simulator`, `loan_tracker`, `push_commands`, `portfolio_kpis`) | ✅ | README, tableau « Repository layout » |
| Il consomme des events Kafka **existants** (`LOAN_CREATED`) sur un cluster réel `152.53.140.115:9092` | ✅ | README §1 et prérequis |
| Deux modes de comportement : JSON (`behaviors.example.json`) **ou** Excel (« Business Case Reevaluation ») | ✅ | README §2 et §4 |
| Il pousse des commandes en retour (`REPAY_LOAN`, `SET_DPD`) | ✅ | README « Full Kafka playbook » |
| Il déclenche un re-scoring sur `lifecycle.scoring.input.v36` | ✅ | README, `--trigger-rescoring` |
| Compression temporelle `--seconds-per-day` | ✅ | CDC Annexe D.3 : 3 modes |
| Les 4 clés de profil, exactement nommées | ✅ | `PROFILE_KEYS`, extrait ligne 62 |
| Les poids 50 / 25 / 13 / 12 | ✅ | CDC Annexe D.1 **et** `POIDS_PAR_DEFAUT_DUHAMEL` |
| **Neuf** variables d'ajustement | ✅ | CDC ligne 1110 : « selon **neuf** variables du client » |
| Tous les coefficients (femme ×1,22 / ×0,72 ; <22 ans ×1,12 ; risque A ×1,12 ; ratio ≥0,85 ×1,15 ; DPD ≥30 ×1,12 ; MoMo >150k ×1,06) | ✅ | `_adjust_weights`, extrait lignes 120-180 — **valeur par valeur** |
| ReadyScore = le service qui score, pas le loan-service | ✅ | topics `lifecycle.scoring.input/responses.v36` ; CDC `EF-80` : « sans appel HTTP à ReadyScore » |
| Duhamel ne traite **que** les APPROVED | ✅ | CDC ligne 292 : les DECLINED « ne reçoivent aucun prêt » |
| Les 4 produits, durées 15/15/30/15, taux 7-25 % | ✅ | Annexe E + mesure de `loan_json.json` |
| Les 20 fourchettes `amount_by_segment` (4 produits × 5 segments) | ✅ | **les vingt valeurs sont exactes**, vérifiées une à une |
| `loan_json.json` n'est **pas** du JSON valide | ✅ | `D-PRD-5` : 3 malformations confirmées, parser tolérant écrit |
| Nano/**Macro**, pas Micro | ✅ | `CO-02` ligne 923 : « Résolue en v1.2 par le catalogue officiel Nano/Macro/BNPL/ReadyToGo » |
| BNPL à 30 jours, les autres à 15 | ✅ | mesuré |
| Le boss veut la **méthodologie**, pas le code — Kafka est exclu | ✅ | `ENF-16` ; l'extrait : « **Rien de tout cela n'est repris** » |
| **180** jours, pas 90 (autocorrection de Yaniv) | ✅ | CDC ligne 286, 288, 852 : « fenêtre historique de **180** jours » |

> **Sur les coefficients, la précision est remarquable.** Les neuf lignes du
> tableau d'ajustement correspondent **exactement** au code. Ce n'est pas une
> reconstitution approximative : c'est une lecture juste.

---

## 2. Ce qui est FAUX — deux points, et le second me corrigeait

### 2.1 ❌ « Very High = mauvais risque » — l'inverse

Les notes disent :

> *« plus le segment est "Very High" (mauvais risque), plus le montant du prêt est
> ÉLEVÉ. C'est contre-intuitif mais logique en microfinance : les clients à haut
> risque acceptent des montants plus élevés (souvent en désespoir de cause) »*

**Le CDC dit exactement le contraire**, Annexe D.2 :

> « Segment de risque **Very High** → **Renforce le profil bon payeur** »
> « Segment de risque **Very Low** → **Renforce le défaut total** »

Et le code le confirme, `_adjust_weights` lignes 149-154 :

```python
if "very high" in seg or risk == "A":      # A = la MEILLEURE classe
    w["pay_before_due"] *= 1.12
    w["never_pays"]     *= 0.82
elif "very low" in seg or risk in ("D", "E"):   # D/E = les PIRES
    w["never_pays"]     *= 1.18
    w["pay_before_due"] *= 0.88
```

`Very High` est groupé avec **`risk == "A"`**, la meilleure classe de risque.
`Very Low` avec **`D` et `E`**, les pires.

**Donc `Very High` = très haute QUALITÉ de crédit, pas un risque élevé.** Il n'y a
aucun paradoxe : **les meilleurs clients obtiennent les plus gros prêts**, ce qui
est la banque la plus ordinaire du monde.

**Ce qui a induit en erreur** : la terminologie du CDC lui-même, qui écrit
« segment de **risque** Very High ». Le piège est réel, et il vaut d'être noté —
mais l'explication « en désespoir de cause » est une justification élaborée d'un
paradoxe qui n'existe pas. C'est le genre d'erreur qui se propage : elle *sonne*
juste.

> **Conséquence pratique** : cela **valide** la dérivation du segment faite le
> 12/08. Le segment y croît avec les signaux `quick_win` **et** avec le solde
> initial — donc `VERY_HIGH` = meilleur client = plus gros solde = plus gros prêt.
> Monotonie vérifiée par test. Si l'interprétation inverse avait été retenue, la
> dérivation aurait été **à l'envers**, et les 2000 clients auraient présenté une
> corrélation absurde devant un bailleur.

### 2.2 ❌ « Concept 3 — le tracking PAR/DPD : à intégrer » — à moitié seulement

Ce point demande une lecture fine, et **il me corrigeait moi aussi** : j'avais
écrit dans la conception que le PAR/DPD était « hors périmètre Loader ». C'est
inexact.

Le CDC v1.2 fait **deux** choses opposées sur PAR/DPD :

| Ligne | Ce qui est dit |
|---|---|
| **29** | « **Retraits** (responsabilités transférées à ReadyScore) : anciens OBJ 07 **rapport** PAR/DPD, ancien EF 72 **rapport** Portfolio At Risk, ancien UC **production rapport** PAR/DPD, ancien CR 11 **recette** PAR/DPD » |
| **379** | « la version 1.2 **ajoute** au périmètre inclus : … (c) la **production d'indicateurs** Portfolio At Risk (PAR) et Days Past Due (DPD) conformes aux standards microfinance » |

**La frontière est donc précise, et ce n'est pas la même chose :**

- ✅ **le Loader GÉNÈRE les données** dont le PAR est crédible — les événements
  `SET_DPD` aux jalons, les trajectoires de remboursement ;
- ❌ **le Loader ne produit PAS le RAPPORT** PAR/DPD — cela revient à ReadyScore.

Ligne 323 le dit dans les termes du métier : le Loader doit « **alimenter** les
tableaux de bord de démonstration en indicateurs PAR crédibles ». *Alimenter*,
pas *produire le tableau de bord*.

Et ligne 718 nuance encore : « Le Loader **POURRAIT** générer des scénarios de
retard (DPD) selon une distribution paramétrable » — un *pourrait*, pas un *doit*.

**Verdict** : le concept est bien à intégrer, mais **la génération des événements**,
non le reporting. Les notes ne faisaient pas la distinction ; ma conception non
plus. **Les deux sont corrigés ici.**

---

## 3. Ce qui est IMPRÉCIS — trois points

### 3.1 ⚠️ « Duhamel a un loan-service en fonctionnement chez lui »

Presque. Annexe C, ligne 1089 : « **Documentation du module loan-service fournie
par Duhamel** (dt@finzuu.com) le 20 juillet 2026 ». Et ligne 445 : « Développeur
externe — **Livre** le module loan-service ».

Donc Duhamel **livre** loan-service, et son orchestrateur en est un **client** via
Kafka. Ce ne sont pas la même pièce : l'orchestrateur consomme
`readyscore.loan.events.v1` et produit `readyscore.loan.commands.v1` ; le
loan-service est ce qui traite ces commandes. Juste sur le fond, imprécis sur la
frontière.

### 3.2 ⚠️ Les séquences jour par jour (« Jour 5 : 30 %, Jour 10 : 40 %… »)

**Ce sont des reconstitutions, pas des faits mesurés.** L'extrait est explicite :

> « `built_in_behaviors_v1()["profiles"]` est **importé** par le script, pas défini
> dedans… `build_timed_actions`, `expand_actions_daily` et
> `repay_amount_for_action` » manquent également.

Le CDC dit « **trois versements progressifs** » sans donner les pourcentages. Donc
`30 / 40 / 30` est **plausible et non vérifié**. Il faut le marquer comme
hypothèse, pas comme lecture — sinon on figera dans le code un chiffre qu'aucune
source ne porte.

**En revanche**, un chiffre est bien dans le CDC : le profil **Défaut total** émet
ses jalons DPD à **15, 30, 60 et 90 jours** (Annexe D.1). Celui-là est acquis.

### 3.3 ⚠️ « le module Lending n'existe pas dans FinZuu »

La prudence est **justifiée** : le CDC n'emploie jamais « module Lending ». Il
parle de « **Module Prêt** », de « **loan-service** », et de « **Lender** » comme
d'un *rôle métier porté par une Company* (ligne 467). Le mot du patron recouvre
donc le module Prêt/Lender de la plateforme, pas une pièce nommée ainsi dans le
CDC. Demander la clarification était la bonne réaction.

---

## 4. CE QUE CE TRAVAIL M'A APPRIS — `A-07` était mal caractérisé

**Ma propre erreur, et elle était importante.** J'affirmais, sur la foi de
l'extrait :

> « Les 4 profils sont **nommés** mais leur FORME — ce que chacun fait jour après
> jour — reste absente. »

C'est vrai **du script Python**. C'est faux **du CDC** : l'Annexe D.1 décrit les
quatre trajectoires en clair.

| Profil (CDC) | Clé Duhamel | Poids | Trajectoire décrite par le CDC |
|---|---|---:|---|
| **Bon payeur** | `pay_before_due` | 50 % | rembourse la totalité **avant l'échéance, en trois versements progressifs** |
| **Retard puis paiement** | `partial_then_full_dpd10` | 25 % | partiel, puis solde **une dizaine de jours après l'échéance** — soldé, mais retard formel |
| **Défaut partiel** | `partial_then_never_finish` | 13 % | partiel initial, puis **plus aucun paiement** — DPD croissant |
| **Défaut total** | `never_pays` | 12 % | **aucun** remboursement — jalons DPD à **15, 30, 60, 90 jours** |

**`A-07` doit donc être requalifié** : ce qui manque n'est pas la *forme* des
profils, mais les **montants et dates exacts** de chaque versement (« trois
versements progressifs » : dans quelles proportions ?). C'est beaucoup plus étroit
que ce que je disais, et cela rapproche le module Vie d'être écrivable.

---

## 5. Les trois durées, à ne plus confondre

L'autocorrection de Yaniv (« 180 jours comme dit le CDC ») est juste, et le CDC
porte bien **trois** durées distinctes :

| Durée | Ce qu'elle borne | Référence |
|---|---|---|
| **180 jours** | la **fenêtre historique** — la vie commune s'y déroule entièrement | lignes 286, 288, 852 |
| **180 + 30 jours** | la **validité des licences** des Companies | ligne 88 |
| **30 / 60 / 90 jours** | le **délai de re-scoring** d'un client DECLINED, paramétrable | lignes 274, 292 |

Les durées de **prêt** (15 et 30 jours) sont d'un autre ordre : elles viennent du
catalogue crédit, pas de la fenêtre.

---

## 6. Ce qu'il faut retenir pour l'implémentation

1. **`Very High` = meilleur client.** À écrire noir sur blanc dans le code, parce
   que la terminologie « segment de risque » du CDC induit l'erreur inverse.
2. **Le Loader génère les `SET_DPD`, pas le rapport PAR.** La frontière est ligne
   29 contre ligne 379.
3. **Les quatre profils ont leur forme dans l'Annexe D.1.** Seuls les montants des
   versements manquent — `A-07` requalifié.
4. **Neuf variables d'ajustement**, dont nous possédons déjà genre, âge, segment et
   `MOB_MONEY_ACCOUNT_AMOUNT`. La pondération est portable dès maintenant.
5. **Kafka est exclu** (`ENF-16`) : `Producer.produce_command` devient des écritures
   HTTP FinZuu. Une substitution de transport, pas une attente.

---

## Sources

CDC v1.2 (`Cahier_Charges_Loader_FinZuu_v1_2_final.docx`) : lignes 29, 88, 274,
286, 288, 292, 323, 379, 445, 467, 514-516, 546, 552, 718, 807, 816, 843, 849,
852, 855, 861, 923, 1085-1150 ·
`docs/reference/duhamel_lifecycle_orchestrator_EXTRAIT.py` ·
`docs/reference/lifecycle_orchestrator_README.md` ·
`docs/reference/loan_json.json` · `docs/reference/COMPREHENSION_PRODUITS_ET_CREDIT.md`
