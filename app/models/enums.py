"""
app/models/enums.py
===================
Enumerations du package "Domaine Loader" (02_class.puml) et du diagramme
d'etat (06_state.puml). Ces valeurs sont propriete du Loader : elles ne sont
JAMAIS negociees avec un service FinZuu amont.
"""

from __future__ import annotations

from enum import StrEnum


class LenderType(StrEnum):
    """Type de Lender. Rappel : Lender = ROLE porte par une Company.

    company-service ne connait PAS ce concept nativement (0 occurrence
    "lender" dans son contrat) -- le Loader porte cette logique lui-meme,
    via la collection lenders_registry.
    """

    LOCAL = "LOCAL"
    INSTITUTIONNEL = "INSTITUTIONNEL"


class FakerConsumptionType(StrEnum):
    """Usage pour lequel un client Faker a ete consomme (D-FAKER-1)."""

    DEPOSITARY = "DEPOSITARY"
    LENDER_LOCAL = "LENDER_LOCAL"
    COLLECT_CLIENT = "COLLECT_CLIENT"


class EtatConsommationFaker(StrEnum):
    """Les deux temps d'une consommation Faker.

    POURQUOI DEUX ETATS ET NON UN SEUL
    ----------------------------------
    La v1 du registre n'en avait qu'un : on ecrivait l'entree APRES la creation
    de l'entite, parce que `resulting_entity_id` etait obligatoire. La sequence
    reelle etait donc :

        1. tirer chez Faker            -> client_id
        2. `est_consomme(client_id)` ? -> non, on continue
        3. CREER L'ENTITE SUR LE SERVEUR   <- IRREVERSIBLE, aucun DELETE
        4. `marquer_consomme(...)`     -> False : deja consomme !

    A l'etape 4, il est trop tard. L'entite existe, definitivement, et elle est
    nee d'un client Faker deja employe ailleurs : `D-FAKER-1` est viole et rien
    ne peut le reparer. La fenetre entre 2 et 4 s'etend sur un appel reseau, et
    le plafond de concurrence est de 20 workers.

    L'index unique sur `_id` protegeait donc le REGISTRE, pas l'ECOSYSTEME.

    La reservation est ecrite AVANT l'appel reseau — c'est le meme patron
    write-ahead que le journal d'intention (`audit_trail`), la seule atomicite
    dont nous disposions face a des services sans transaction ni rollback.
    """

    #: Revendique, aucune entite encore creee. Une reservation qui survit a la
    #: fin du run est ORPHELINE : le client a ete revendique sans rien produire.
    RESERVE = "RESERVE"
    #: L'entite existe sur le serveur. Etat definitif — jamais libere.
    CONSOMME = "CONSOMME"


class NiveauOrganisation(StrEnum):
    """Niveaux 3 a 6 de l'arbre operationnel (CDC §6.2), cote Loader.

    Decision d'architecture du 08/08 (option b) : Branche et Agence ne sont
    JAMAIS persistees cote serveur. company-service n'expose aucune route pour
    elles, et son enum CompanyType ne comporte aucune valeur BRANCH — les
    materialiser en Companies filles ferait exploser le budget de 12-20
    Companies fixe par UC-07, sans aucun benefice.

    Elles restent donc des niveaux LOGIQUES, dont l'unique role est de
    distribuer geographiquement : Branche -> Region, Agence -> Ville,
    Kiosque -> Quartier. La coherence exigee par EF-11/14/15/16/18 est
    integralement preservee, puisque c'est le Loader qui choisit ces trois
    niveaux AVANT d'appeler depositary-service.

    Seul le niveau KIOSQUE a une contrepartie serveur : le Depositaire, cree
    avec company_id = l'IMF racine.

    AGENT — quatrieme valeur, ajoutee le 09/08/2026 (decision `D-11`)
    -----------------------------------------------------------------
    Le CDC §6 decrit **six** niveaux ; nous n'en modelisions que cinq. Le
    sixieme, l'Agent, est *« une personne physique de terrain, rattachee a un
    Kiosque »*.

    Contrairement a Branche et Agence, **l'Agent A une contrepartie serveur** :
    c'est un `User` de user-service, porteur du groupe « Agent ». Il n'avait
    donc pas vocation a figurer ici — **sauf pour une chose**, et elle est
    decisive : **son rattachement au Kiosque n'existe nulle part cote
    serveur**. `User` porte `company_id` (vide sur les 20 users de
    l'environnement) et `identity`, jamais de reference vers un Depositaire.

    Sans ce niveau, la question *« quels Agents dans ce Kiosque ? »* n'a
    **aucune reponse** — exactement le defaut que nous reprochons a
    config-service, dont le `Telco` ne porte pas son pays
    (`docs/ANALYSE_CONFIG_SERVICE.md`, regle 2).

    Le niveau AGENT ne change pas la regle du modele, il l'applique : un noeud
    ne peut exister sans son superieur (`EF-18`).

    CLIENT — cinquieme valeur, ajoutee le 12/08/2026 (`EF-26`)
    ---------------------------------------------------------
    **Un Client n'est PAS un niveau de l'arbre du CDC §6.2**, qui s'arrete a
    l'Agent. Il figure ici pour la raison EXACTE qui a fait entrer l'Agent, et
    la mesure du 09/08 la donne sans ambiguite : la fiche Client rendue par
    client-service porte quinze cles, et **aucune** ne permet un rattachement.

        _id · created_at · updated_at · msisdn · language · channel · segment
        category · identity · is_active · product · account_id
        subscription_fees · subscription_date · status

    Ni `depositary_id`, ni `kiosque_id`, ni `company_id`. Le rattachement
    Client -> Kiosque n'existe **nulle part** cote serveur a la creation ; il ne
    se materialise que par une collecte, qui seule porte `client_id` ET
    `depositary_id` (`D-CLI-6`). `EF-26` est donc satisfaite en DEUX TEMPS, et ce
    noeud est le premier — notre seule trace jusqu'a la premiere collecte.

    Sans lui, *« quels clients rattaches a ce Kiosque ? »* reste sans reponse et
    `CR-02` demeure non verifiable, quel que soit le nombre de clients crees.

    DEUX CHOSES QUE CE NOEUD NE FAIT PAS, et les deux sont voulues :

    - **Il ne porte pas de `district_id`.** L'index `uniq_district_par_run` est
      UNIQUE : le second client d'un meme quartier serait rejete. Mais la vraie
      raison est meilleure — la geographie du client est DERIVEE de son Kiosque
      par `ancrer_sur_kiosque()`. Ne pas la dupliquer rend l'incoherence
      impossible, la ou la stocker puis la comparer la rendrait seulement
      detectable.
    - **Son `name` n'est pas celui de la personne** mais `DEMO_Client <msisdn>`.
      Ce noeud est un artefact du Loader, et les artefacts du Loader portent le
      prefixe (`CR-07`/`EF-63`) ; une personne, non. Le msisdn y est lisible
      parce qu'il est la cle naturelle du Client, et desormais stable d'un run a
      l'autre (`D-CLI-11`).
    """

    #: `CAT 7-8` / `A-12` (13/08) — le rattachement Produit -> Company. Le
    #: serveur ne le represente NULLE PART (« company » : zero occurrence dans
    #: l'OpenAPI de product-service, mesure du 12/08) : troisieme occurrence
    #: du motif EF-26/D-CLI-6, meme reponse — le lien vit chez nous.
    PRODUIT = "PRODUIT"
    BRANCHE = "BRANCHE"
    AGENCE = "AGENCE"
    KIOSQUE = "KIOSQUE"
    AGENT = "AGENT"
    CLIENT = "CLIENT"


class RunMode(StrEnum):
    """Mode d'execution d'un run.

    DRY_RUN est le mode par defaut : aucune ecriture n'est emise vers les
    services FinZuu. Le passage en REAL est toujours une action explicite du
    Super-Admin.
    """

    DRY_RUN = "DRY_RUN"
    REAL = "REAL"


class RunStatus(StrEnum):
    """Machine d'etat de LoaderRun.status (06_state.puml).

    PARTIAL est un etat terminal legitime, pas une erreur : le CDC prevoit
    qu'une entite en echec soit journalisee et que l'execution se poursuive
    (UC-07 / UC-08, cas alternatif).
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
