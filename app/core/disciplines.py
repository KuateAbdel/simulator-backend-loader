"""
app/core/disciplines.py
=======================
Les 5 disciplines defensives NON NEGOCIABLES du Loader FinZuu.

Ce module ne contient AUCUNE logique metier. Il porte le texte de reference
des 5 disciplines, sous une forme citable depuis le code applicatif, pour que
chaque garde-fou pose ailleurs dans le backend puisse nommer explicitement la
discipline qu'il applique (docstring, message de log, message d'erreur HTTP).

Source normative : docs/reference/uml_diagrams/02_class.puml, package
"Domaine Loader", complete par les diagrammes de sequence 03/05/07/08 et par
docs/CONTEXT.md.

Pourquoi ces disciplines existent : chacune neutralise un ecart empirique
CONFIRME d'un service FinZuu amont. Aucune ne releve d'une preference de
style. Les violer ne produit pas un bug visible immediatement -- elle produit
une corruption silencieuse du jeu de donnees genere, detectee des jours plus
tard, en demonstration commerciale.
"""

from __future__ import annotations

from typing import Final

# --------------------------------------------------------------------------
# D-FAKER-1 -- unicite de consommation Faker
# --------------------------------------------------------------------------
D_FAKER_1: Final = (
    "D-FAKER-1 : avant CHAQUE tirage Faker, verifier le client_id contre "
    "faker_consumption_ledger. Un client_id deja consomme n'est JAMAIS reutilise "
    "pour un autre usage -- re-tirer avec un seed different. Le cache Redis Faker "
    "etant deterministe (CT-03), le meme seed rend le meme client indefiniment."
)

# --------------------------------------------------------------------------
# D-CMP-2 -- cascade Identity reelle, cascade User inexistante
# --------------------------------------------------------------------------
D_CMP_2: Final = (
    "D-CMP-2 : POST /companies/ cascade REELLEMENT vers identity-service pour "
    "l'owner (confirme empiriquement). En revanche admin_email ne cree AUCUN User. "
    "Le Loader cree l'Admin User lui-meme, explicitement, via le flow 3 etapes "
    "user-service : POST /auth/register -> PUT /auth/password/f/change -> POST /auth/login."
)

# --------------------------------------------------------------------------
# D-DEP-7 -- depositary-service sans RBAC reelle (FRA-205)
# --------------------------------------------------------------------------
D_DEP_7: Final = (
    "D-DEP-7 (FRA-205, CRITIQUE) : depositary-service n'applique AUCUNE restriction "
    "RBAC reelle. Toute ecriture sur ce service utilise exclusivement le token ROOT, "
    "jamais un token de moindre privilege -- meme si ce dernier est techniquement accepte. "
    "Corollaire D-DEP-8 (FRA-203/204) : PATCH status/false n'arrete PAS les collectes et "
    "retraits sur souscriptions existantes ; ne jamais concevoir de logique supposant le contraire."
)

# --------------------------------------------------------------------------
# D-PRD-4 / D-PRD-9 -- split "Any" et non-duplication du catalogue
# --------------------------------------------------------------------------
D_PRD_4_9: Final = (
    "D-PRD-4 / D-PRD-9 : l'enum serveur de product-service n'accepte QUE INDIVIDUAL et "
    'CORPORATE. Une categorie source "Any" (BNPL, ReadyToGo) est OBLIGATOIREMENT splittee '
    "en 2 creations distinctes, sinon HTTP 422 (INV-PRD-04). GET avant chaque POST (D-PRD-2) : "
    "un produit deja existant est reutilise, jamais duplique. Chaque Product porte sa PROPRE "
    "Policy embarquee (D-PRD-7) -- une Policy est une reference VIVANTE, la partager modifie "
    "retroactivement et silencieusement tous les Products liees (INV-PRD-07)."
)

# --------------------------------------------------------------------------
# D-COL-* -- montants collect-service strictement positifs
# --------------------------------------------------------------------------
D_COL_AMOUNT: Final = (
    "D-COL (montants) : aucun montant negatif ou nul n'est JAMAIS envoye a collect-service. "
    "Le service repond par un rejet HTTP apparent tout en appliquant une mutation reelle "
    "silencieuse -- la validation est donc entierement a la charge du Loader, AVANT l'appel HTTP."
)

#: Registre des 5 disciplines, indexe par identifiant court. Sert aux messages
#: de log structures et aux tests de conformite.
DISCIPLINES: Final[dict[str, str]] = {
    "D-FAKER-1": D_FAKER_1,
    "D-CMP-2": D_CMP_2,
    "D-DEP-7": D_DEP_7,
    "D-PRD-4/9": D_PRD_4_9,
    "D-COL-AMOUNT": D_COL_AMOUNT,
}
