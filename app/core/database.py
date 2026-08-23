"""
app/core/database.py
====================
Acces MongoDB via motor (driver asynchrone officiel, FZ-STACK-LOADER-2026-001 §5.3).

Un seul client motor est cree au demarrage de l'application et partage par
toutes les requetes : ouvrir un client par requete epuiserait le pool de
connexions bien avant les 2000 clients de l'objectif OBJ-02.

Le client motor ne se connecte pas a l'instanciation. Un demarrage sans
MongoDB joignable ne fait donc pas echouer le processus -- c'est voulu : le
squelette doit pouvoir demarrer et repondre sur /health avant que la base ne
soit provisionnee.
"""

from __future__ import annotations

from typing import Any, Final

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.config import settings
from app.models.enums import NiveauOrganisation, RunStatus

#: Type du document renvoye par motor. Les classes de app/models/domain.py
#: valident ces dictionnaires bruts en entree comme en sortie -- aucun
#: document n'est manipule sans passer par elles.
MongoDocument = dict[str, Any]

# --------------------------------------------------------------------------
# Noms des 7 collections proprietaires. Aucune autre collection n'est creee
# par le Loader (cf. app/models/domain.py).
# --------------------------------------------------------------------------
COLLECTION_FAKER_CONSUMPTION_LEDGER: Final = "faker_consumption_ledger"
COLLECTION_LENDERS_REGISTRY: Final = "lenders_registry"
COLLECTION_LOADER_RUNS: Final = "loader_runs"
COLLECTION_AUDIT_TRAIL: Final = "audit_trail"
COLLECTION_SUPER_ADMIN_ACCOUNTS: Final = "super_admin_accounts"
#: Sixieme collection — arbre operationnel Branche/Agence/Kiosque cote Loader.
#: Consequence de la decision (b) du 08/08 : sans elle, CR-02 est invérifiable.
COLLECTION_ORG_HIERARCHY: Final = "org_hierarchy"
#: Septieme collection — la configuration COURANTE editee par le Super-Admin
#: (US-B1/B2/B3, 13/08). Document singleton versionne : le prochain run lance
#: par l'API l'utilisera, et `LoaderRun.configuration` (D-10) continue d'en
#: figer l'empreinte PAR RUN — la collection porte l'intention, le run porte
#: le fait.
COLLECTION_LOADER_CONFIGURATION: Final = "loader_configuration"
#: Huitieme collection — anti-brute-force du login (I-AUTH-11). Compteurs
#: d'echecs consecutifs PAR IDENTIFIANT soumis, avec cooldown a backoff
#: exponentiel AUTO-CICATRISANT. Jamais un verrou dur du compte (ce serait le
#: bug plateforme INV-USR-19 / CWE-645, deni de service sur l'utilisateur
#: legitime). Purgee par TTL des qu'un identifiant reste inactif.
COLLECTION_AUTH_THROTTLE: Final = "auth_throttle"
#: Neuvieme collection — notifications IN-APP (canal du systeme de notification).
#: Une entree par (destinataire, evenement) ; lues comme non lues sont gardees.
COLLECTION_NOTIFICATIONS: Final = "notifications"
#: Dixieme collection — VERROUS par ressource (`C2`). Une entree par geste en
#: cours (`pousser:CM`), purgee par TTL : la plateforme n'ayant aucun index
#: unique (RC-183), deux appels simultanes creeraient chacun leur exemplaire.
COLLECTION_VERROUS: Final = "verrous"
#: Onzieme collection — le RELEVE DE VERSION des services (`V-01`). Un
#: document par service, avec son historique : c'est l'historique qui permet
#: de dire « ca a change », et le changement est la seule information qui
#: demande une action.
COLLECTION_VERSIONS_SERVICES: Final = "service_versions"

_client: AsyncIOMotorClient[MongoDocument] | None = None


def connect() -> AsyncIOMotorClient[MongoDocument]:
    """Ouvre le client motor partage. Idempotent."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            uuidRepresentation="standard",
            # Mesure du 08/08 : avec le defaut de 30 s, un demarrage sans MongoDB
            # bloque 30 s avant de rendre la main. Beaucoup trop long pour une
            # sonde de disponibilite. 5 s suffisent a diagnostiquer une base
            # absente sans immobiliser l'application.
            serverSelectionTimeoutMS=5000,
        )
    return _client


def close() -> None:
    """Ferme le client motor partage. Idempotent."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def get_database() -> AsyncIOMotorDatabase[MongoDocument]:
    if _client is None:
        raise RuntimeError("Client MongoDB non initialise -- connect() n'a pas ete appele.")
    return _client[settings.mongodb_database]


def get_collection(name: str) -> AsyncIOMotorCollection[MongoDocument]:
    return get_database()[name]


async def ensure_indexes() -> None:
    """Cree les index qui portent les invariants du domaine.

    Ces index ne sont pas une optimisation : ils rendent structurellement
    impossibles des violations que la couche applicative ne peut garantir
    seule sous concurrence.

    - faker_consumption_ledger : `_id` = client_id Faker. L'unicite de la cle
      primaire MongoDB EST le garde-fou D-FAKER-1 -- aucun index additionnel
      n'est requis pour cela. L'index sur (consumed_for, country_code) sert
      les statistiques de fin de run.
    - lenders_registry : un couple (company_id, lender_type) est unique. Une
      Company ne porte pas deux fois le meme role (EF-12, idempotence ENF-04).
    - audit_trail : index sur run_id + timestamp pour l'export du journal
      d'une execution (EF-62).
    - super_admin_accounts : email unique (Phase 1 = Super-Admin unique).
    """
    db = get_database()

    await db[COLLECTION_FAKER_CONSUMPTION_LEDGER].create_index(
        [("consumed_for", 1), ("country_code", 1)],
        name="idx_consumed_for_country",
    )
    # La reconciliation cherche les reservations orphelines d'UN run — le seul
    # acces chaud de cette collection en fin d'execution. L'index est PARTIEL sur
    # `RESERVE` parce qu'au repos cet ensemble doit etre VIDE : une reservation
    # qui survit est un incident, et l'index reste minuscule tant que tout va
    # bien. Indexer les `CONSOMME` aurait coute 2000 entrees pour rien.
    await db[COLLECTION_FAKER_CONSUMPTION_LEDGER].create_index(
        [("run_id", 1), ("reserved_at", 1)],
        name="idx_reservations_en_vol",
        partialFilterExpression={"state": "RESERVE"},
    )
    await db[COLLECTION_LENDERS_REGISTRY].create_index(
        [("company_id", 1), ("lender_type", 1)],
        name="uniq_company_lender_type",
        unique=True,
    )
    await db[COLLECTION_LENDERS_REGISTRY].create_index(
        [("country_code", 1)],
        name="idx_country_code",
    )
    await db[COLLECTION_LOADER_RUNS].create_index(
        [("status", 1)],
        name="idx_status",
    )
    # `EF-55` RENDU STRUCTUREL — 11/08.
    #
    # Le verrou d'execution etait APPLICATIF : `dernier_en_cours()` interrogeait
    # la base, puis on creait le run. Entre les deux, deux processus passent tous
    # les deux. Un verrou qui se contourne par une fenetre de concurrence n'est
    # pas un verrou, c'est une convention.
    #
    # Index unique PARTIEL sur `status == "RUNNING"` : deux runs RUNNING
    # deviennent impossibles au niveau du moteur. `PAUSED` n'est pas concerne —
    # un run en pause ne genere rien, et `EF-55` interdit deux GENERATIONS
    # simultanees.
    #
    # `$in` n'est pas supporte par `partialFilterExpression` : l'egalite stricte
    # est la seule forme legale, et c'est exactement celle qu'il nous faut.
    await db[COLLECTION_LOADER_RUNS].create_index(
        [("status", 1)],
        name="uniq_un_seul_running",
        unique=True,
        partialFilterExpression={"status": RunStatus.RUNNING.value},
    )
    await db[COLLECTION_AUDIT_TRAIL].create_index(
        [("run_id", 1), ("timestamp", 1)],
        name="idx_run_timestamp",
    )
    # LE REGISTRE EST DERIVE DU JOURNAL — 14/08. `registre_groupes` et
    # `registre_produits` (reconciliation, garde du DELETE, purge) lisent par
    # `entity_type`. Sans cet index, chaque garde balaierait le journal
    # ENTIER — negligeable aujourd'hui, un scan de dizaines de milliers
    # d'entrees apres les 180 jours de mouvements du module VIE. L'index
    # porte aussi `action` : les lectures du registre distinguent
    # INTENTION/RESULTAT/DELETE, la paire est la cle d'acces reelle.
    await db[COLLECTION_AUDIT_TRAIL].create_index(
        [("entity_type", 1), ("action", 1)],
        name="idx_entity_type_action",
    )
    await db[COLLECTION_SUPER_ADMIN_ACCOUNTS].create_index(
        [("email", 1)],
        name="uniq_email",
        unique=True,
    )
    # I-AUTH-11 : les compteurs anti-brute-force s'auto-purgent. Le champ
    # `expire_le` porte une date d'inactivite ; MongoDB supprime le document
    # quand elle est depassee (expireAfterSeconds=0). Un identifiant qui cesse
    # d'echouer redevient donc vierge tout seul.
    await db[COLLECTION_AUTH_THROTTLE].create_index(
        "expire_le",
        name="ttl_auth_throttle",
        expireAfterSeconds=0,
    )
    # Verrous par ressource : purge automatique quand `expire_le` est depassee.
    # Le TTL de Mongo passe a la minute — la reprise d'un verrou perime est
    # donc faite AUSSI a la prise, on ne se fie pas au balayage pour la
    # justesse (seulement pour le menage).
    await db[COLLECTION_VERROUS].create_index(
        "expire_le",
        name="ttl_verrous",
        expireAfterSeconds=0,
    )
    # Notifications : la boite d'un destinataire se lit par (destinataire, plus
    # recentes d'abord) ; le compteur de non-lues filtre en plus sur `lu`.
    await db[COLLECTION_NOTIFICATIONS].create_index(
        [("destinataire", 1), ("cree_le", -1)],
        name="idx_destinataire_recent",
    )
    # CR-02 : la verification de recette se fait par une seule requete sur
    # (run_id, niveau). L'unicite du district par run garantit qu'aucun quartier
    # n'heberge deux Kiosques du meme run — c'est ce qui rend la repartition
    # geographique credible plutot que concentree (partial : seuls les noeuds
    # KIOSQUE portent un district_id).
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("niveau", 1)],
        name="idx_run_niveau",
    )
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("parent_id", 1)],
        name="idx_parent",
    )
    # `P-04` — l'ecran « clients » filtre par pays, genre, categorie et
    # profession. Sans cet index, chaque affichage balayait les 2000 noeuds du
    # run. Partiel : seuls les noeuds CLIENT portent ces champs.
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("country_code", 1), ("gender", 1), ("categorie", 1)],
        name="idx_profil_client",
        partialFilterExpression={"niveau": NiveauOrganisation.CLIENT.value},
    )
    # `A-12` RENDU STRUCTUREL — 13/08, meme doctrine que EF-55 et le Kiosque
    # par quartier : le controle applicatif (`find_one` avant insert) reste la
    # reponse AIMABLE (None), l'index unique est le verrou reel sous
    # concurrence. Un rattachement Produit -> Company n'existe qu'UNE fois par
    # run — un lien n'est pas une quantite, le double est un bug. Partiel :
    # seuls les noeuds PRODUIT portent un product_id.
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("company_id", 1), ("product_id", 1)],
        name="uniq_produit_par_company",
        unique=True,
        partialFilterExpression={"niveau": NiveauOrganisation.PRODUIT.value},
    )
    # `EF-26` + `CR-03` — un client ne se rattache qu'UNE fois par run.
    #
    # Sans cet index, une reprise ajouterait un second noeud pour le meme client
    # et « quels clients dans ce Kiosque ? » repondrait 4000 pour 2000 clients.
    # L'idempotence du rattachement est structurelle, pas confiee a l'appelant :
    # c'est la meme raison qui fait de `faker_consumption_ledger._id` le
    # client_id Faker lui-meme.
    #
    # Partiel, car seuls les noeuds CLIENT portent un `client_id` — les quatre
    # niveaux superieurs le laissent a `null`, et un index unique non partiel les
    # ferait tous collisionner sur cette valeur.
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("client_id", 1)],
        name="uniq_client_par_run",
        unique=True,
        partialFilterExpression={"client_id": {"$type": "string"}},
    )
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("district_id", 1)],
        name="uniq_district_par_run",
        unique=True,
        partialFilterExpression={"district_id": {"$type": "string"}},
    )
    # LES DEUX NIVEAUX LOGIQUES MERITENT LA MEME GARANTIE — 11/08.
    #
    # Seul le KIOSQUE etait protege structurellement. Or le modele est aussi
    # strict au-dessus. Mais la PORTEE de cette unicite n'est pas celle qu'on
    # croit, et c'est le reel qui la dicte :
    #
    #   une IMF n'a pas DEUX directions regionales dans la meme Region
    #   une IMF n'a pas DEUX agences dans la meme Ville
    #   ... mais DEUX IMF CONCURRENTES ont chacune la leur a Douala.
    #
    # La concurrence existe. Baobab et SoliMFI ont toutes deux une agence a
    # Douala, et c'est normal. La cle porte donc `company_id` : **le proprietaire
    # de la contrainte est l'institution, pas l'execution.**
    #
    # `run_id` reste dans la cle parce qu'il PARTITIONNE : chaque execution a son
    # arbre (`EF-64`), et un rejeu ne doit pas etre BLOQUE par l'arbre du run
    # precedent — il doit produire le sien.
    #
    # Premiere version de ces index, posee une heure plus tot : `(run_id,
    # region_id)`. Elle interdisait a la deuxieme IMF d'un pays d'avoir une
    # branche dans une region deja servie — une regle qui n'existe nulle part
    # dans la vraie vie.
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("company_id", 1), ("region_id", 1)],
        name="uniq_branche_par_company_region_run",
        unique=True,
        partialFilterExpression={"niveau": NiveauOrganisation.BRANCHE.value},
    )
    await db[COLLECTION_ORG_HIERARCHY].create_index(
        [("run_id", 1), ("company_id", 1), ("city_id", 1)],
        name="uniq_agence_par_company_ville_run",
        unique=True,
        partialFilterExpression={"niveau": NiveauOrganisation.AGENCE.value},
    )
