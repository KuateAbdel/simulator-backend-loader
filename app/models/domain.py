"""
app/models/domain.py
====================
Les 6 documents MongoDB proprietaires du Loader, package "Domaine Loader"
de docs/reference/uml_diagrams/02_class.puml.

Regle de nommage stricte : chaque classe ci-dessous porte EXACTEMENT les
champs du diagramme de classe et de docs/CONTEXT.md, sans champ invente et
sans champ omis. Un champ absent du diagramme n'a pas sa place ici ; s'il
devient necessaire, il passe d'abord par une mise a jour du diagramme.

Le champ MongoDB `_id` est expose sous l'alias Python `id` (populate_by_name
actif) : la serialisation vers motor utilise systematiquement by_alias=True.

Frontiere a ne jamais franchir : ces 6 collections sont la SEULE persistance
du Loader. Toute entite FinZuu (Company, Client, Product, Account, Identity,
Kiosque...) vit dans son service amont et n'est jamais dupliquee ici -- seuls
ses identifiants sont references.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    EtatConsommationFaker,
    FakerConsumptionType,
    LenderType,
    NiveauOrganisation,
    RunMode,
    RunStatus,
)


class LoaderDocument(BaseModel):
    """Base commune : alias _id, validation stricte, pas de champ surnumeraire."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        use_enum_values=False,
    )


class FakerConsumptionLedger(LoaderDocument):
    """Collection `faker_consumption_ledger` -- support technique de D-FAKER-1.

    `_id` EST le client_id Faker : c'est l'unicite MongoDB elle-meme qui
    garantit qu'un client Faker ne peut pas etre revendique deux fois.

    DEUX TEMPS, ET LE PREMIER EST AVANT LE RESEAU
    ---------------------------------------------
    `state` porte la correction du 11/08. La v1 n'ecrivait l'entree qu'APRES la
    creation de l'entite, `resulting_entity_id` etant obligatoire : la fenetre
    entre le `find_one` de controle et l'`insert_one` s'etendait donc sur un
    appel reseau IRREVERSIBLE, avec 20 workers concurrents. L'index unique
    protegeait le registre ; il ne protegeait pas l'ecosysteme.

    Desormais `RESERVE` est ecrit AVANT l'appel reseau, et `CONSOMME` apres —
    le meme patron write-ahead que `audit_trail`. Voir `EtatConsommationFaker`.

    `run_id` etait absent, et son absence rendait la reconciliation aveugle :
    une reservation orpheline laissee par un run mort etait indistinguable des
    notres. `D-FAKER-1` reste GLOBAL — un client consomme le demeure d'un run a
    l'autre — mais on doit savoir QUI l'a consomme.
    """

    id: str = Field(alias="_id", description="client_id Faker -- cle naturelle")
    consumed_for: FakerConsumptionType
    country_code: str = Field(min_length=2, max_length=2)
    run_id: UUID = Field(description="Le run qui a revendique ce client Faker")
    state: EtatConsommationFaker = EtatConsommationFaker.RESERVE
    reserved_at: datetime
    #: Le `seed` qui a produit ce client. Sans lui, `ENF-15` n'est pas verifiable :
    #: rejouer un run exige de rejouer ses tirages.
    seed: int | None = None
    #: `None` tant que l'entite n'existe pas. C'est la PREUVE qu'un client
    #: revendique a reellement produit quelque chose — un client ecarte pour
    #: raison de quota n'en a pas, et sa reservation est liberee.
    resulting_entity_id: UUID | None = None
    consumed_at: datetime | None = None


class LenderRegistryEntry(LoaderDocument):
    """Collection `lenders_registry` -- le Lender comme ROLE porte par une Company.

    Les 4 comptes financiers (CAPITAL / INTEREST / PENALTY / TAXE, UC-10 et
    EF-13) sont declares optionnels ici, et c'est deliberé.

    **`EF-13` est VERIFIE EN ECRITURE depuis le 09/08/2026.** Aucune cascade
    serveur ne produit ces 4 comptes -- mesure exhaustive du 08/08 : 8 Companies
    en base, toutes avec le seul compte OPERATION. Le Loader les cree donc
    explicitement, par 4 POST (`D-01`), et l'ecriture reelle du 09/08 l'a
    confirme sur `DEMO_QA0808_SARL Tamadou Textile`.

    Ils restent optionnels parce qu'un Lender partiellement initialise est un
    etat legitime a representer (UC-10, cas d'exception), pas une donnee invalide
    a rejeter.

    (Cet en-tete disait « jamais verifiee empiriquement » jusqu'au 11/08, en
    contradiction avec `lenders_registry.py` dans le meme depot.)
    """

    id: UUID = Field(alias="_id")
    company_id: UUID = Field(description="Reference vers la Company porteuse du role")
    lender_type: LenderType
    #: `None` pour les 4 institutionnels : `EF-12` les qualifie de **globaux**,
    #: ils n'ont pas de pays d'intervention. Les 12 locaux le portent toujours.
    #: Inventer un code fictif aurait contredit `EF-05`, qui borne le perimetre
    #: aux quatre pays cibles.
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    capital_account_id: UUID | None = None
    interest_account_id: UUID | None = None
    penalty_account_id: UUID | None = None
    taxe_account_id: UUID | None = None


class LoaderRun(LoaderDocument):
    """Collection `loader_runs` -- etat de simulation d'une execution.

    `_id` est le run_id PROPRE au Loader. Il ne doit jamais etre confondu avec
    le run_id de partition Faker (20260620123721), qui appartient a un autre
    systeme et n'a pas la meme semantique.
    """

    id: UUID = Field(alias="_id", description="run_id Loader -- distinct du run_id Faker")
    sim_start_date: date
    sim_end_date: date
    status: RunStatus = RunStatus.PENDING
    mode: RunMode = RunMode.DRY_RUN
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    #: SEPTIEME champ, ajoute le 09/08/2026 -- decision D-10.
    #:
    #: Des que la volumetrie devient parametrable (exigence du 09/08), le
    #: `run_id` NE SUFFIT PLUS a reproduire une execution : deux runs de meme
    #: identifiant sous des parametres differents donneraient des resultats
    #: differents. `ENF-15` serait perdue et `CR-04` inverifiable.
    #:
    #: Ce champ porte l'empreinte complete -- pays actifs et leurs motifs
    #: d'exclusion, surcharges par territoire, repartition des clients, ajouts
    #: de la surcouche referentielle, et les ECARTS AU CDC. Rejouer un run,
    #: c'est rejouer `run_id` ET ceci.
    #:
    #: Il n'est PAS dans `checkpoints` : ceux-ci portent la reprise apres
    #: interruption, ils changent pendant l'execution. La configuration, elle,
    #: est figee au lancement. Melanger les deux rendrait impossible de dire ce
    #: qui avait ete demande.
    configuration: dict[str, Any] = Field(default_factory=dict)
    #: Le RAPPORT complet du run, tel que `pilotage.executer()` l'ecrit — la
    #: sortie que le CLI imprime, rangee avec le run pour que l'API la rende
    #: (US-C6). Attache en fin d'execution ; vide tant que le run court.
    rapport: str = ""
    #: `US-E3` — les MESURES structurees de la population composee : quotas
    #: mesure/cible par pays, profils CR-09, 576 metiers, tranches de soldes
    #: (frontiere a 150 000 — le seuil EF-68), naissances a l'etranger. Le
    #: dashboard les sert sans jamais requeter FinZuu.
    mesures: dict[str, Any] = Field(default_factory=dict)


class AuditTrailEntry(LoaderDocument):
    """Collection `audit_trail` -- SIEM applicatif interne (EF-61 a EF-64).

    `before` / `after` portent l'etat de l'entite de part et d'autre de
    l'action. `before` est None a la creation, `after` est None a la
    suppression -- les deux ne sont jamais None simultanement.
    """

    id: UUID = Field(alias="_id")
    run_id: UUID = Field(description="Reference vers LoaderRun._id")
    entity_type: str
    entity_id: UUID
    action: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    timestamp: datetime


class Notification(LoaderDocument):
    """Collection `notifications` -- une notification IN-APP destinee a UN compte.

    Le systeme de notification separe l'EVENEMENT (ce qui s'est passe) du CANAL
    (comment on previent). Ce document est le canal IN-APP : une entree par
    (destinataire, evenement). Le contenu n'est PAS rendu ici -- on garde le
    `type` et les `donnees` structurees, et c'est le frontend qui rend le texte
    localise (FR/EN). Le canal EMAIL, lui, part en plus via le relais Mailjet.

    `lu` porte l'etat de lecture (la cloche compte les non-lues). Rien ne se
    supprime -- une notification lue reste, elle grise seulement.
    """

    id: UUID = Field(alias="_id")
    #: Email du compte destinataire (resolu par ROLE au moment de l'emission).
    destinataire: str
    #: Type d'evenement (cf. services/notifications.py) -- la cle de rendu.
    type: str
    #: Donnees structurees de l'evenement (email vise, role, acteur, motif...).
    donnees: dict[str, Any] = Field(default_factory=dict)
    lu: bool = False
    cree_le: datetime


class OrgHierarchyNode(LoaderDocument):
    """Collection `org_hierarchy` -- arbre operationnel cote Loader (niveaux 3 a 6).

    SIXIEME collection, ajoutee le 08/08/2026 en consequence directe de la
    decision (b) sur Branche/Agence. Elle n'est pas un confort : sans elle,
    CR-02 devient invérifiable -- ce critere de recette exige de controler que
    « chaque Kiosque a un District valide, chaque Agence une Ville valide ».

    Un seul document par noeud, les trois niveaux dans la meme collection :
    l'arbre se relit alors par une seule requete, et la verification de
    recette porte sur une seule source.

    Invariant structurel (EF-18) : un noeud ne peut exister sans son superieur.
    - BRANCHE : parent_id = None, region_id renseigne
    - AGENCE  : parent_id = une BRANCHE, city_id renseigne
    - KIOSQUE : parent_id = une AGENCE, district_id ET depositary_id renseignes
    - AGENT   : parent_id = un KIOSQUE, user_id renseigne (D-11)

    Deux references pointent vers des entites reellement creees cote serveur :
    `depositary_id` au niveau KIOSQUE (depositary-service) et `user_id` au
    niveau AGENT (user-service). Les niveaux BRANCHE et AGENCE n'ont aucune
    contrepartie distante -- c'est tout l'objet de la decision (b).

    Pourquoi l'AGENT figure ici alors qu'il EXISTE cote serveur : parce que son
    RATTACHEMENT au Kiosque, lui, n'existe nulle part. `User` porte
    `company_id` et `identity`, jamais de reference vers un Depositaire. Sans
    ce noeud, « quels Agents dans ce Kiosque ? » reste sans reponse (`D-11`).
    """

    id: UUID = Field(alias="_id")
    run_id: UUID = Field(description="Reference vers LoaderRun._id (EF-64)")
    niveau: NiveauOrganisation
    parent_id: UUID | None = Field(
        default=None, description="None pour BRANCHE, sinon le noeud du niveau superieur"
    )
    company_id: UUID = Field(description="IMF racine — porte toute la descendance")
    name: str
    country_code: str = Field(min_length=2, max_length=2)
    region_id: str | None = None
    city_id: str | None = None
    district_id: str | None = None
    depositary_id: UUID | None = Field(
        default=None, description="Renseigne au niveau KIOSQUE uniquement (depositary-service)"
    )
    user_id: UUID | None = Field(
        default=None, description="Renseigne au niveau AGENT uniquement (user-service) — D-11"
    )
    client_id: UUID | None = Field(
        default=None,
        description="Renseigne au niveau CLIENT uniquement (client-service) — EF-26, 1er temps",
    )
    #: `A-12` — renseigne au niveau PRODUIT uniquement. `name` porte le
    #: MARQUEUR (DEMO_<code>) et non le nom metier : c'est un noeud technique,
    #: et CR-07 verifie les noms de noeuds par prefixe — le choix rend CAT 6
    #: satisfait sans modifier la recette.
    product_id: UUID | None = Field(default=None)
    #: `P-01` — l'index INVERSE client→produit, renseigne au niveau CLIENT :
    #: le produit d'entree a l'onboarding, puis chaque `PUT /subscribe`
    #: supplementaire. La plateforme ne stocke JAMAIS la reference inverse
    #: (« combien de clients par produit ? » = 20 requetes paginees la-bas) —
    #: enregistre A L'ECRITURE, ce lien y repond en UNE requete chez nous.
    #: Vide sur une REPRISE (D-CLI-5) : le serveur ne sait pas dire a quoi un
    #: client existant a souscrit, et on n'invente jamais.
    product_ids: list[str] = Field(default_factory=list)
    #: Le package de licence qui AUTORISE ce rattachement (UC-11 pt 3).
    package: str | None = Field(default=None)


class SuperAdminAccount(LoaderDocument):
    """Collection `super_admin_accounts` -- authentification propre au Loader.

    Distincte de user-service (cf. 10_component.puml) : ce compte pilote le
    Loader, il n'a aucune existence dans l'ecosysteme FinZuu. Bootstrap au
    premier demarrage via SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD_INITIAL.

    Seul le hash est persiste. Le mot de passe initial n'est jamais ecrit en
    base, ni journalise, ni renvoye par l'API.
    """

    id: UUID = Field(alias="_id")
    email: str
    password_hash: str
    must_change_password: bool = True
    #: RBAC (decision Yaniv 15/08) : « Super-Admin » est un ROLE que PLUSIEURS
    #: comptes portent — chacun avec son email reel et son propre cycle de mot
    #: de passe. Un compte desactive ne se connecte plus (401 generique) mais
    #: n'est jamais supprime : l'historique du journal reste attribuable.
    actif: bool = True
    #: RBAC du Loader (matrice FZ-RBAC-LOADER) : 'viewer' (lecture seule) <
    #: 'admin' (operations) < 'super_admin' (tout + gestion comptes/roles).
    #: Defaut 'super_admin' : les comptes existants (documents sans ce champ)
    #: et le bootstrap restent Super-Admin — aucune coupure de compatibilite.
    role: str = "super_admin"
    #: Qui a cree ce compte (email du createur) — None pour le bootstrap.
    cree_par: str | None = None
    cree_le: str | None = None
    #: Tracabilite (demande Yaniv 20/08) : horodatage ISO de la DERNIERE
    #: connexion reussie — « la derniere fois qu'il etait dans le systeme ».
    #: None tant que le compte ne s'est jamais connecte.
    derniere_connexion: str | None = None
    #: Reinitialisation par email (`US-A4` v2) — seul le HASH du code est
    #: persiste, avec sa peremption (epoch, sans piege de fuseau) et un
    #: compteur d'essais : 5 echecs consomment le code.
    code_reset_hash: str | None = None
    code_reset_expire: float | None = None
    code_reset_essais: int = 0
