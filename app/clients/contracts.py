"""
app/clients/contracts.py
========================
Enumerations des contrats FinZuu amont, RECOPIEES telles qu'elles sont
declarees par les serveurs — jamais re-decouvertes par sondage.

Regle d'usage, non negociable : toute valeur envoyee a un service FinZuu vient
d'ici. Un enum serveur ne se discute pas — la moindre valeur hors liste produit
un HTTP 422, et le contrat FR/EN ne suit pas toujours le vocabulaire du CDC
(voir CompanyType).

Provenance de chaque bloc :
  - company / product / client / user  -> pages Service Anatomy (espace TST),
    faits verrouilles empiriquement, cites en tete de chaque enum.
  - account / identity                 -> contrat OpenAPI runtime. account-service
    est le SEUL service du perimetre sans page Anatomy ("D-ACC-XXX toujours a
    extraire", Document Maitre §10) — ces valeurs sont donc a re-verifier lorsque
    cette page sera produite.
  - Faker                              -> Cartographie empirique v1.1
    (FZ-DOC-FAKER-2026-001, page 51740675).

Arbitrage de nommage (cf. docs/empirical/2026-08-08_recon_9_services.md §2.1) :
le CDC parle d'« Agence », « Kiosque », « Fonds institutionnel » ; le serveur
ecrit AGENCY, KIOSK, FUNDING_PROVIDER. Le Loader envoie la valeur serveur et
conserve le vocabulaire du CDC dans ses libelles et ses rapports.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

# --------------------------------------------------------------------------
# company-service — page 59834370, Casquette 1 Q2
# --------------------------------------------------------------------------


class CompanyType(StrEnum):
    """7 valeurs. FONDATION est en francais cote serveur (ANO-CPY-NAMING-02).

    Les 4 Lenders institutionnels (Nordic Microfinance, IFC, AFD, BAD) portent
    FUNDING_PROVIDER — c'est le « Fonds institutionnel » du CDC §6.2.
    """

    MERCHANT = "MERCHANT"
    BANK = "BANK"
    IMF = "IMF"
    AGENCY = "AGENCY"
    KIOSK = "KIOSK"
    FUNDING_PROVIDER = "FUNDING_PROVIDER"
    FONDATION = "FONDATION"


class PackageName(StrEnum):
    """Packages de licence. READY_CASH pour le credit, READY_COLLECTE pour la
    collecte, ALL pour les deux (UC-07)."""

    ALL = "ALL"
    READY_CASH = "READY_CASH"
    READY_COLLECTE = "READY_COLLECTE"
    BULK = "BULK"


# --------------------------------------------------------------------------
# product-service — page 60358657, Casquette 1 Q2 (les 9 enums empiriques)
# --------------------------------------------------------------------------


class ProductType(StrEnum):
    COLLECT = "COLLECT"
    LENDING = "LENDING"


class ProductCategory(StrEnum):
    """INV-PRD-04 : strictement 2 valeurs. « ANY » provoque un HTTP 422.

    C'est cet enum — et lui seul — qui impose le split D-PRD-4 des produits
    Category=Any du catalogue source (BNPL, ReadyToGo) en 2 creations.
    """

    INDIVIDUAL = "INDIVIDUAL"
    CORPORATE = "CORPORATE"


class ProductSegment(StrEnum):
    """A ne JAMAIS confondre avec ProductCategory : ici « ANY » est valide.

    Porte la segmentation par risque de l'Annexe E du CDC.
    """

    ANY = "ANY"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class PolicyType(StrEnum):
    CASH = "CASH"
    CASH_DAT = "CASH_DAT"
    PRODUCT = "PRODUCT"


class InterestType(StrEnum):
    DAILY = "DAILY"
    FORTNIGHTLY = "FORTNIGHTLY"
    MONTHLY = "MONTHLY"


class InterestCalculation(StrEnum):
    DAILY = "DAILY"
    INSTANTLY = "INSTANTLY"
    DEBT = "DEBT"


class InterestApplication(StrEnum):
    CAPITAL = "CAPITAL"
    DEBT = "DEBT"


class PenaltyType(StrEnum):
    AMOUNT = "AMOUNT"
    PERCENT = "PERCENT"


class PolicyMeasure(StrEnum):
    """D-PRD-8 : toujours choisi explicitement selon la nature du produit.

    La WebApp injecte KILOGRAM en dur et en silence (OBS-PRD-UX-01) — le Loader
    ne reproduit jamais ce defaut.
    """

    KILOGRAM = "KILOGRAM"
    LITER = "LITER"


# --------------------------------------------------------------------------
# client-service — page 60555267, Casquette 1 Q2 (schemas bruts)
# --------------------------------------------------------------------------


class ClientCategory(StrEnum):
    """`Category` cote serveur. Enum distinct de ProductCategory, memes valeurs.

    OBS-CLI-CROSSCHECK-01 : aucune validation croisee Client/Product — un Client
    CORPORATE souscrit sans rejet a un Produit INDIVIDUAL.
    """

    INDIVIDUAL = "INDIVIDUAL"
    CORPORATE = "CORPORATE"


class ClientSegment(StrEnum):
    """`Segment` cote serveur. Point de jonction avec metadata.behavior_segment
    de Faker (EF-80)."""

    ANY = "ANY"
    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class SubscriptionChannel(StrEnum):
    USSD = "USSD"
    MOBILE = "MOBILE"
    OFFICE = "OFFICE"


class Language(StrEnum):
    EN = "en"
    FR = "fr"


# --------------------------------------------------------------------------
# user-service — page 56360965, Casquette 1 Q2
# --------------------------------------------------------------------------


class UserType(StrEnum):
    COMPANY = "COMPANY"
    CUSTOMER = "CUSTOMER"
    GUEST = "GUEST"
    ROOT = "ROOT"
    STAFF = "STAFF"


class TagGroupe(StrEnum):
    """3 valeurs declarees. « ROOT » est persiste hors enum en base (A4) —
    a accepter en lecture, jamais a emettre en ecriture."""

    STAFF = "STAFF"
    COMPANY = "COMPANY"
    CUSTOMER = "CUSTOMER"


class MfaMethod(StrEnum):
    """« » (chaine vide) est persiste hors enum quand la MFA est desactivee (A5)."""

    EMAIL = "EMAIL"
    SMS = "SMS"
    TOTP = "TOTP"


# --------------------------------------------------------------------------
# identity-service — contrat OpenAPI runtime (pas de page Anatomy)
# --------------------------------------------------------------------------


class IdentityType(StrEnum):
    """D-CLI-4 : la valeur envoyee est IGNOREE — le serveur ecrase vers CORPORATE.

    Renseignee malgre tout, le champ etant requis au contrat.
    """

    CORPORATE = "CORPORATE"
    INDIVIDUAL = "INDIVIDUAL"


class IdentityGender(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    ANY = "ANY"


class IdentityMaritalStatus(StrEnum):
    SINGLE = "SINGLE"
    MARRIED = "MARRIED"
    DIVORCED = "DIVORCED"
    WIDOWED = "WIDOWED"


# --------------------------------------------------------------------------
# account-service — contrat OpenAPI runtime (SEUL service sans page Anatomy)
# --------------------------------------------------------------------------


class AccountType(StrEnum):
    """Les 4 premiers types portent les comptes du Lender (UC-10 / EF-13), que
    le Loader cree explicitement — aucune cascade ne les produit (Trou #2).

    Le bundle Depositaire en cree 6 d'un coup a la souscription : CAPITAL,
    INTEREST, PENALTY, TAXE, CLASSIC, TERM_DEPOSIT (D-DEP-2).
    """

    CAPITAL = "CAPITAL"
    CHECKING = "CHECKING"
    INTEREST = "INTEREST"
    PENALTY = "PENALTY"
    TAXE = "TAXE"
    CLASSIC = "CLASSIC"
    TERM_DEPOSIT = "TERM_DEPOSIT"
    OPERATION = "OPERATION"
    COMMITMENT = "COMMITMENT"


class AccountStatus(StrEnum):
    """Aucun DELETE n'existe sur account-service : CLOSED est le seul retrait
    possible, et toute creation y est donc definitive."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"


class OwnerType(StrEnum):
    COMPANY = "COMPANY"
    IDENTITY = "IDENTITY"


class ProviderSource(StrEnum):
    ACCOUNT = "ACCOUNT"
    BANK = "BANK"
    CASH = "CASH"
    MOMO = "MOMO"


class TransactionSense(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class TransactionTag(StrEnum):
    """Seule occurrence du concept « lender » dans tout l'ecosysteme FinZuu :
    account-service sait TAGUER une transaction, sans connaitre l'entite.
    Coherent avec « Lender = role porte par une Company » (CDC §6.3)."""

    COMPANY = "COMPANY"
    LENDER = "LENDER"
    SAVING = "SAVING"
    TO_SHARE = "TO_SHARE"
    SELF = "SELF"


class TransactionType(StrEnum):
    CAPITAL = "CAPITAL"
    CHECKING = "CHECKING"
    INTEREST = "INTEREST"
    REFUND = "REFUND"
    RECONDUCTION = "RECONDUCTION"
    PENALTY = "PENALTY"
    TAXE = "TAXE"
    RECONCILIATION = "RECONCILIATION"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    INVESTMENT = "INVESTMENT"
    TRANSFERT = "TRANSFERT"


# --------------------------------------------------------------------------
# Faker fintech4esg — Cartographie empirique v1.1 (page 51740675)
# --------------------------------------------------------------------------


class FakerCustomerCategory(StrEnum):
    INDIVIDUAL = "Individual"
    BUSINESS = "Business"


class FakerDecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


#: F-03 : seul run_id valide. Tout autre valeur repond HTTP 404.
#: Ne jamais confondre avec LoaderRun._id, qui appartient au Loader.
FAKER_RUN_ID: Final = "20260620123721"

# TROIS CONSTANTES RETIREES LE 09/08 — elles etaient MORTES et FAUSSES.
#
# `PAYS_CIBLES`, `MAX_CONCURRENT_WORKERS` (25) et `MAX_PAGE_LIMIT` (100)
# vivaient ici en double de `app/core/cdc.py` et `app/clients/base.py`.
# Aucune n'etait importee nulle part — mais `MAX_CONCURRENT_WORKERS` portait
# encore 25 apres la correction de `D-USR-1` a 20. Une constante morte ne fait
# rien ; une constante morte que quelqu'un finit par importer fait pire que
# rien.
#
# Sources uniques : `app.core.cdc.PAYS_CIBLES`,
# `app.clients.base.MAX_CONCURRENCE`, `app.clients.base.LIMITE_PAGE_MAX`.
#
# Leurs commentaires affirmaient par ailleurs DEUX FAITS QUE NOUS AVONS MESURES
# FAUX le 08/08 (`docs/empirical/2026-08-08_faker_maitrise_complete.md` §6) :
#
#   « SN est accepte au runtime, les 4 pays sont atteignables »
#      -> FAUX. Famille A : HTTP 422. Famille B : HTTP 404. Le Senegal est
#         ABSENT de Faker. `A-01` a ete TRANCHE le 10/08 : le Senegal n'est pas
#         un cas particulier, le generateur interne le sert comme les trois
#         autres. Plus aucun client en suspens.
#   « CT-04/F-11 : Faker ne valide PAS ses filtres, `country_code=ZZ` rend un
#     client au hasard »
#      -> FAUX, et c'est une AMELIORATION de leur cote : `ZZ` rend desormais
#         un 422 (famille A) / 404 (famille B).
#
# Un commentaire perime est plus dangereux qu'un commentaire absent : il se
# lit comme un fait etabli.
