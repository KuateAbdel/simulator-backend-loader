"""
app/core/cdc.py
===============
Parametres de generation du Loader, tires EXCLUSIVEMENT du Cahier des Charges
v1.2 (FZ-CDC-LOADER-2026-001), autorite supreme sur le perimetre fonctionnel.

Pourquoi ce module existe : les documents de synthese derivent avec le temps —
c'est normal, ils consolident. Le CDC, lui, est contractuel. En figeant ici la
valeur ET sa reference d'exigence, toute divergence future se tranche par une
relecture du CDC, jamais par un arbitrage d'opinion.

Chaque constante porte sa reference (UC-xx, EF-xx, ENF-xx, OBJ-xx, CR-xx).
Verifiees une par une contre le texte du CDC le 8 aout 2026.

Deux derives relevees par rapport au Document Maitre de Synthese v2.2, tranchees
ici en faveur du CDC :

  1. Depositaires/Kiosques. Le Document Maitre §9 annonce 120-200 (30-50/pays).
     Le CDC UC-09, scenario nominal, point 3 : « Il genere entre 10 et 20
     Kiosques par pays » -> 40 a 80 au total. Le glossaire CDC pose l'equivalence
     « Kiosque / Depositaire », que le diagramme de classe confirme (une seule
     classe Kiosque_Depositaire) et que le CDC §4.4 redit : « depositary-service
     — Creation des kiosques et souscriptions ». Ecart d'un facteur 3, non
     neutre : chaque Depositaire coute 1 creation + 1 souscription declenchant
     6 comptes, sous un plafond de 30 minutes (ENF-01).

  2. Clients Business. Le Document Maitre §7 evoque « 500 clients Business
     (25 % de 2000) ». 25 % est la distribution NATURELLE de Faker (Cartographie
     v1.1 §5.6), pas notre exigence. EF-23 impose 80/20 -> 400.

Consequence de conception, valable pour les 4 distributions ci-dessous : Faker
ne garantit AUCUNE d'entre elles. Le Loader doit les IMPOSER par quota et
re-tirage, jamais accepter le tirage naturel. Un client ecarte pour raison de
quota n'est pas « consomme » au sens D-FAKER-1 — il n'entre au ledger que s'il
a reellement produit une entite.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# Perimetre geographique — OBJ-01, CDC §6.1
# --------------------------------------------------------------------------

#: Les 4 pays cibles. EF-05 : toute operation ciblant un pays absent est rejetee.
PAYS_CIBLES: Final[tuple[str, ...]] = ("CM", "CI", "BF", "SN")

#: Referentiel enrichi, INTERNE au Loader (Loader_Base_FinZuu_v1.1.xlsx).
#: Jamais pousse dans config-service, qui ne connait que Country.cities[].
NB_REGIONS: Final = 51
NB_VILLES: Final = 50
NB_QUARTIERS: Final = 82

# --------------------------------------------------------------------------
# Organisation — UC-07, UC-08, UC-09, EF-10 a EF-19
# --------------------------------------------------------------------------

#: UC-07 : « Entre 3 et 5 Companies par pays sont creees ». Soit 12 a 20 au total.
COMPANIES_PAR_PAYS: Final[tuple[int, int]] = (3, 5)

#: EF-12 / UC-08 : 3 Lenders locaux par pays, soit 12.
LENDERS_LOCAUX_PAR_PAYS: Final = 3

#: UC-08 : 4 Lenders institutionnels, noms fixes, JAMAIS issus de Faker.
#: Portent le type Company FUNDING_PROVIDER (cf. app/clients/contracts.py).
LENDERS_INSTITUTIONNELS: Final[tuple[str, ...]] = (
    "Nordic Microfinance",
    "IFC",
    "AFD",
    "BAD",
)

#: UC-10 / EF-13 : 4 comptes financiers par Lender. Aucune cascade serveur ne
#: les produit — le Loader les cree explicitement (sondage Trou #2, 08/08).
COMPTES_LENDER: Final[tuple[str, ...]] = ("CAPITAL", "INTEREST", "PENALTY", "TAXE")

# --------------------------------------------------------------------------
# Dotation du capital des Lenders — UC-10, point 2 du scenario nominal
# --------------------------------------------------------------------------
#
# CE QUE LE CDC EXIGE, MOT POUR MOT :
#   « Il alimente le compte CAPITAL avec un montant initial DEPENDANT DU TYPE DE
#     LENDER (institutionnels plus dotes que locaux). Il initialise les 3 autres
#     comptes a zero. »
#
# Nous creions les quatre a zero. Un Lender a capital nul ne peut rien financer,
# et l'IFC affichant 0 franc devant un bailleur se voit au premier ecran.
#
# LE CDC NE DONNE AUCUN CHIFFRE — il impose une dotation DIFFERENCIEE et laisse
# le montant ouvert. Le choisir n'est donc pas un ecart, c'est executer
# l'exigence. Mais il doit etre RAISONNE, pas invente. Voici le raisonnement :
#
#   `EF-46`  « au moins un pret par jour »
#   `ENF-16` fenetre de 180 jours
#   Annexe E montants par segment, de 5 000 (Nano Very Low) a 1 000 000 FCFA
#            (ReadyToGo Very High) — moyenne de catalogue autour de 275 000
#
#   180 jours x 1 pret x ~275 000 FCFA  ->  ~50 000 000 FCFA par pays
#   reparti sur 3 Lenders locaux         ->  ~17 000 000 chacun au minimum
#
# On retient 50 millions par Lender local : la marge couvre une cadence
# superieure au plancher d'`EF-46`, et l'ordre de grandeur correspond au
# portefeuille reel d'une IMF de taille moyenne en zone CEMAC/UEMOA.
#
# L'institutionnel REFINANCE les locaux — il est en amont dans la chaine. Un
# ordre de grandeur au-dessus est donc la lecture juste de « plus dotes » :
# 500 millions, soit de quoi refinancer les trois locaux d'un pays entier.
#
# Les 3 autres comptes restent a ZERO : ils se rempliront par les interets, les
# penalites et les taxes des remboursements simules (Sprint 5). Les doter
# d'avance serait inventer des revenus jamais percus.
DOTATION_CAPITAL_LOCAL: Final = 50_000_000.0
DOTATION_CAPITAL_INSTITUTIONNEL: Final = 500_000_000.0

#: UC-09, point 3 : « Il genere entre 10 et 20 Kiosques par pays ». 40 a 80 au
#: total. Kiosque = Depositaire (glossaire CDC).
KIOSQUES_PAR_PAYS: Final[tuple[int, int]] = (10, 20)

#: UC-09, point 2 : « entre 15 et 25 utilisateurs staff par pays ».
STAFF_PAR_PAYS: Final[tuple[int, int]] = (15, 25)

# --------------------------------------------------------------------------
# Population client — OBJ-02, EF-22 a EF-25
# --------------------------------------------------------------------------

#: OBJ-02 / EF-77 / ENF-01 / CR-04 : 2000 clients par execution.
NB_CLIENTS: Final = 2000

#: EF-23 : « 80 pour cent d'individus, 20 pour cent de professionnels ».
#: Soit 1600 INDIVIDUAL / 400 CORPORATE. Faker tire naturellement 75/25
#: (Carto §5.6) — quota a imposer.
PART_INDIVIDUAL: Final = 0.80
PART_CORPORATE: Final = 0.20

#: EF-22 : « 60 pour cent d'individus de moins de 25 ans, ratio deux femmes
#: pour un homme ». Aucun filtre Faker sur l'age — a imposer par re-tirage.
PART_MOINS_DE_25_ANS: Final = 0.60
AGE_SEUIL_JEUNE: Final = 25
RATIO_FEMMES_HOMMES: Final[tuple[int, int]] = (2, 1)

#: EF-24 : « 20 pour cent des professionnels au secteur agricole ; les 80 pour
#: cent restants aux secteurs transports, commerce et services ».
PART_CORPORATE_AGRICOLE: Final = 0.20

#: UC-13 : « 1 a 3 souscriptions a des produits Collecte ».
SOUSCRIPTIONS_PAR_CLIENT: Final[tuple[int, int]] = (1, 3)

# --------------------------------------------------------------------------
# Fenetre temporelle — ENF-16, EF-76 a EF-79
# --------------------------------------------------------------------------

#: ENF-16 : fenetre historique de 180 jours, parametrable via SIM_START_DATE
#: et SIM_END_DATE.
FENETRE_JOURS: Final = 180

#: EF-79 : re-scoring des DECLINED a 30, 60 ou 90 jours apres le refus initial.
#: Ne JAMAIS confondre ce 90 avec la fenetre globale de 180 jours.
DELAIS_RESCORING_JOURS: Final[tuple[int, ...]] = (30, 60, 90)

#: EF-76 : les 4 fonctions de conversion temporelle du referent loan-simulation,
#: a reutiliser imperativement, sous ces noms exacts.
FONCTIONS_DUHAMEL: Final[tuple[str, ...]] = (
    "_wall_from_sim_day",
    "_current_sim_day",
    "_wall_time_for_sim_day",
    "_scoring_date_to_sim_day",
)

# --------------------------------------------------------------------------
# Cadence et mouvements — EF-40 a EF-46
# --------------------------------------------------------------------------

#: EF-42 : « un a plusieurs debits et credits selon le segment (1 a 5) ».
MOUVEMENTS_PAR_CLIENT_PAR_JOUR: Final[tuple[int, int]] = (1, 5)

#: EF-40 : au minimum 3 compagnies par jour ouvre en mode continu.
COMPANIES_MIN_PAR_JOUR: Final = 3

#: EF-41 : 10 nouvelles entrees par jour, reparties 20 % compagnies / 80 % individus.
ENTREES_PAR_JOUR: Final = 10

# --------------------------------------------------------------------------
# Simulation comportementale — EF-67, Annexe D, CR-09
# --------------------------------------------------------------------------

#: EF-67 : « poids empiriques 50/25/13/12 » — bon payeur, retard puis paiement,
#: defaut partiel, defaut total.
#:
#: ⚠️ **LE PIEGE DE VOCABULAIRE DE L'ANNEXE D.2 — a lire AVANT d'ecrire le
#: Sprint 5.** L'Annexe D.2 du CDC pondere ces poids selon 9 variables du client,
#: et deux lignes sont contre-intuitives :
#:
#:     « Segment de risque **Very High** -> renforce le profil BON PAYEUR »
#:     « Segment de risque **Very Low**  -> renforce le DEFAUT TOTAL »
#:
#: La note metier finale du CDC l'explique : « la logique de segmentation associe
#: les segments Very High a des montants PLUS IMPORTANTS. Cette pratique, courante
#: en microfinance et conforme aux standards CGAP, permet de compenser les pertes
#: attendues sur ces populations par une marge d'interet plus elevee. »
#:
#: Donc dans ce CDC, **`Very High` designe la QUALITE du client, pas son risque de
#: defaut.** Un client Very High emprunte davantage parce qu'on lui fait
#: davantage confiance.
#:
#: Inverser ce sens produirait une population ou les MEILLEURS clients font
#: defaut — l'exact inverse de la realite, et un bailleur qui connait le metier
#: le verrait au premier tableau de bord.
PROFILS_COMPORTEMENTAUX: Final[dict[str, int]] = {
    "BON_PAYEUR": 50,
    "RETARD_PUIS_PAIEMENT": 25,
    "DEFAUT_PARTIEL": 13,
    "DEFAUT_TOTAL": 12,
}

#: CR-09 / ENF-13 : tolerance de +/- 3 points sur un echantillon de 1000 clients.
TOLERANCE_DISTRIBUTION_POINTS: Final = 3

# --------------------------------------------------------------------------
# Conformite — ENF-14, EF-35, CR-01 **REGLEMENTAIRE**
# --------------------------------------------------------------------------
#
# ⚠️ **COLLISION DE NUMEROTATION DANS LE CDC — relevee le 11/08.** Le CDC utilise
# `CR-01`, `CR-02` et `CR-03` DEUX FOIS, avec deux sens differents :
#
#     §9.3 Contraintes REGLEMENTAIRES     §12 Criteres de RECETTE
#     CR-01 taux <= 24 % (usure)          CR-01 geographie complete
#     CR-02 identites fictives            CR-02 coherence geo-organisationnelle
#     CR-03 MSISDN conformes au           CR-03 idempotence, aucun doublon
#           regulateur (ART, ARTCI,
#           ARCEP-BF, ARTP)
#
# **Les deux series vivent dans notre code.** Ici, `CR-01` designe la contrainte
# REGLEMENTAIRE (le plafond d'usure). Dans `app/services/recette.py`, `CR-01`
# designe le critere de RECETTE (la geographie).
#
# Ce n'est pas notre erreur, mais elle nous traverse : toute citation de `CR-01`,
# `CR-02` ou `CR-03` doit dire de QUELLE serie elle parle.

#: EF-35 / CR-01 : plafond d'usure BEAC/COBAC, meme en environnement de test.
TAUX_USURE_MAX_ANNUEL_PCT: Final = 24.0

#: ENF-14 : seuils standards microfinance a respecter pour une distribution nominale.
PAR30_MAX_PCT: Final = 15.0
PAR90_MAX_PCT: Final = 8.0
TAUX_RECOUVREMENT_MIN_PCT: Final = 85.0

# --------------------------------------------------------------------------
# Performance et reversibilite — OBJ-04, OBJ-05, EF-63, ENF-01
# --------------------------------------------------------------------------

#: ENF-01 / OBJ-04 / CR-04 : 2000 clients en moins de 30 minutes.
DUREE_MAX_EXECUTION_MINUTES: Final = 30

#: UC-07 / EF-63 / OBJ-05 : chaque donnee generee porte ce prefixe, qui la rend
#: reconnaissable et supprimable (CR-07, reversibilite).
PREFIXE_DONNEES: Final = "DEMO_"

#: UC-07 : la licence couvre « la fenetre historique 180 jours plus 30 jours a venir ».
LICENCE_MARGE_FUTURE_JOURS: Final = 30


def nb_companies_total() -> tuple[int, int]:
    """Fourchette totale de Companies sur les 4 pays — UC-07."""
    bas, haut = COMPANIES_PAR_PAYS
    return bas * len(PAYS_CIBLES), haut * len(PAYS_CIBLES)


def nb_kiosques_total() -> tuple[int, int]:
    """Fourchette totale de Kiosques/Depositaires sur les 4 pays — UC-09."""
    bas, haut = KIOSQUES_PAR_PAYS
    return bas * len(PAYS_CIBLES), haut * len(PAYS_CIBLES)


def nb_lenders_total() -> int:
    """12 locaux + 4 institutionnels — UC-08 / EF-12."""
    return LENDERS_LOCAUX_PAR_PAYS * len(PAYS_CIBLES) + len(LENDERS_INSTITUTIONNELS)


def repartition_clients() -> dict[str, int]:
    """1600 INDIVIDUAL / 400 CORPORATE — EF-23 applique a OBJ-02."""
    corporate = round(NB_CLIENTS * PART_CORPORATE)
    return {"INDIVIDUAL": NB_CLIENTS - corporate, "CORPORATE": corporate}
