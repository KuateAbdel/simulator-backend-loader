"""
app/clients/client_service.py
=============================
Client client-service — onboarding des 2000 Clients (UC-12 a UC-14, EF-20 a EF-29).

**Toutes les regles portees ici ont ete REJOUEES contre le serveur le 09/08/2026.**
La page Service Anatomy (60555267) date du 1er aout : elle a ete verifiee, pas
crue. Une de ses sept disciplines est caduque, et trois comportements qu'elle ne
documente pas ont ete decouverts. Le detail est dans
`docs/empirical/2026-08-09_client_service_verification.md`.

`POST /onboard` declenche une cascade vers DEUX services :

    POST /api/v1/clients/onboard
         |-> identity-service   +1 Identity  (_id GENERE par le serveur)
         `-> account-service    +1 CHECKING  (owner_type=IDENTITY,
                                              external_class=CLIENT_SERVICE)

C'est le chemin le plus emprunte de toute la campagne — **2000 fois**. Chaque
piege non neutralise ici se paie 2000 fois.

Les huit disciplines portees, avec leur statut au 09/08 :

  D-CLI-1  Les Produits COLLECT sont crees AVANT tout Client, une seule fois.
           `product_id` est requis a l'onboarding : sans catalogue, rien ne
           demarre. Structurel, non rejouable isolement.
  D-CLI-2  `id_expire_on` est TOUJOURS fourni. VERIFIE le 09/08 : son absence
           fait toujours planter le serveur en 400 « 'NoneType' object has no
           attribute 'isoformat' ». Le champ est optionnel dans la copie du
           schema portee par client-service, mais REQUIS dans l'original
           d'identity-service — les deux copies sont desynchronisees.
  D-CLI-3  CADUQUE. La page affirmait « id_number alphanumerique MAJUSCULES
           strict ». VERIFIE le 09/08 : `cm<hex>` en minuscules passe en 201.
           Seuls les caracteres speciaux sont refuses. Le message d'erreur
           annonce une contrainte que le serveur n'applique pas (FRA-228).
           Le Loader continue d'emettre des MAJUSCULES : se conformer au
           message reste le choix sur si la regle est un jour appliquee.
  D-CLI-4  `identity.type` envoye est IGNORE — le serveur ecrase vers
           CORPORATE. VERIFIE le 09/08 : envoye INDIVIDUAL, rendu CORPORATE.
           Ne jamais lire ce champ pour deduire la nature du client : c'est
           `Client.category` qui fait foi.
  D-CLI-5  GET-avant-POST par `msisdn`. VERIFIE : rejouer le meme msisdn rend
           400 « Client already exists ». L'unicite est reelle et serveur-side.
  D-CLI-6  Le rattachement Client -> Company n'existe PAS a la creation. La
           fiche Client ne porte aucun `company_id`, nulle part. Le lien passe
           uniquement par collect-service :
               Client --(Collect: client_id + depositary_id)--> Depositaire --> Company
           Il ne peut donc se faire qu'a la simulation d'une collecte.
  D-CLI-7  `PUT /clients/subscribe` pour les 2e et 3e produits (UC-13 : 1 a 3
           souscriptions). VERIFIE : 200, le tableau `product` passe a 2.
  D-CLI-8  **NOUVEAU, absent de toutes nos sources.** `identity.phone` DOIT
           etre strictement egal a `msisdn`, sinon 400 « Identity phone field
           must match msisdn ». Les tests du 01/08 utilisaient le meme numero
           des deux cotes par hasard et n'ont jamais rencontre la barriere.
           Un onboarding sur deux champs distincts echouerait 2000 fois.

Trois pieges supplementaires, neutralises ici :

  identity._id  Requis au contrat, **IGNORE** par le serveur qui genere le sien
                (mesure du 09/08). Meme famille que ANO-CPY-OWNERID-05 /
                FRA-227 sur company-service. Toujours relire l'identifiant
                RENDU — c'est lui que porte le compte CHECKING en cascade.
                `05_sequence_onboarding.puml` affirme l'inverse : correction UML.
  language      Envoye `fr`, **rendu `en`**. Le champ est ignore a l'onboarding.
                Le Loader repasse donc par `PATCH /clients/language/{id}` quand
                la langue cible n'est pas `en`. `segment`, lui, est honore.
  404 vide      `GET /clients/by-msisdn/{msisdn}` rend 404 quand le client
                n'existe pas, la ou un 200 avec corps vide serait attendu. Le
                meme piege que sur les souscriptions Depositaire : traite via
                `vide_si_404`, jamais comme une erreur.

Ce que le Loader ne fait PAS : creer l'Identity a part. `POST /onboard` la
cascade lui-meme. Passer par identity-service en amont produirait une Identity
orpheline, que rien ne rattacherait au Client — et identity-service n'a aucun
DELETE.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from app.clients.base import ClientFinZuu, JournalRequetes, normaliser_id
from app.clients.contracts import (
    ClientCategory,
    ClientSegment,
    Language,
    SubscriptionChannel,
)
from app.core.config import settings

#: Les seules devises legitimes des 4 pays cibles. Le referentiel config-service
#: ne peut PAS servir de source de validation : il contient deux entrees
#: parasites, `cv` et `00` (ANO-CFG-CUR-10 / FRA-222). On valide donc contre
#: cette liste close, pas contre le serveur.
DEVISES_AUTORISEES: Final[frozenset[str]] = frozenset({"XAF", "XOF"})

#: UC-13 : « 1 a 3 souscriptions a des produits Collecte ». Le serveur ne borne
#: RIEN — mesure du 09/08 : 6 produits attaches a un meme client sans broncher.
#: Le plafond est entierement a notre charge.
SOUSCRIPTIONS_MAX = 3


class OnboardingNonConforme(ValueError):
    """Le payload violerait un invariant — refuse AVANT le reseau.

    Tous les cas couverts sont irrattrapables apres coup : client-service
    n'expose ni DELETE, ni desactivation, et sa cascade cree une Identity et un
    compte que rien ne supprime non plus.
    """


def valider_onboarding(
    msisdn: str, identity: dict[str, Any], currency: str | None = None
) -> dict[str, Any]:
    """Normalise l'Identity embarquee et refuse ce qui corromprait la base.

    Renvoie une **copie** corrigee — l'appelant garde son dictionnaire intact.

    Les quatre barrieres, toutes mesurees le 09/08/2026 :

      D-CLI-8  `identity.phone` doit etre STRICTEMENT egal a `msisdn`, sinon
               400 « Identity phone field must match msisdn ». On l'aligne au
               lieu de le subir : sur 2000 onboardings, une divergence de champ
               echouerait 2000 fois.
      D-CLI-2  `id_expire_on` absent fait planter la cascade vers
               identity-service en 400 « 'NoneType' object has no attribute
               'isoformat' ». Le champ est optionnel dans la copie du schema
               portee par client-service, mais REQUIS dans l'original.
      D-CLI-3  `id_number` doit etre alphanumerique. Le serveur annonce en plus
               une contrainte de MAJUSCULES qu'il n'applique pas (FRA-228) —
               on s'y conforme quand meme, pour rester valide si elle l'est un
               jour.
      D-CLI-9  **`currency` n'est validee NULLE PART sur ce chemin.** Elle
               n'apparait meme pas dans la fiche Client rendue : elle traverse
               le service et atterrit telle quelle dans le compte CHECKING cree
               en cascade. Mesure du 09/08 : `ZZZ`, `ANY` et la chaine VIDE
               produisent chacun un compte porteur de cette valeur.

               **C'est l'origine de `ANO-ACC-CUR-08` / `FRA-222`** — le compte
               client reel portant `currency="ANY"`. La recommandation n°4 de ce
               ticket demandait d'identifier le chemin d'ecriture fautif : c'est
               celui-ci. Aucun filet n'existe hors du notre.
    """
    normalisee = dict(identity)
    numero = str(msisdn).strip()

    normalisee["phone"] = numero

    if not normalisee.get("id_expire_on"):
        raise OnboardingNonConforme(
            "id_expire_on absent — la cascade vers identity-service planterait en 400 "
            "(« 'NoneType' object has no attribute 'isoformat' »). D-CLI-2 : le champ est "
            "optionnel dans la copie du schema portee par client-service, mais REQUIS dans "
            "l'original d'identity-service. Les deux copies sont desynchronisees."
        )

    piece = str(normalisee.get("id_number", "")).strip().upper()
    if not piece or not piece.isalnum():
        raise OnboardingNonConforme(
            f"id_number '{piece}' non alphanumerique — c'est le SEUL controle reellement "
            "applique par le serveur. D-CLI-3 : le message d'erreur annonce en plus des "
            "MAJUSCULES obligatoires, contrainte qui n'est pas appliquee (FRA-228). Le "
            "Loader emet des majuscules par prudence, pas par zele."
        )
    normalisee["id_number"] = piece

    if currency is not None:
        devise = str(currency).strip().upper()
        if devise not in DEVISES_AUTORISEES:
            raise OnboardingNonConforme(
                f"currency '{devise}' hors des devises des 4 pays cibles "
                f"({', '.join(sorted(DEVISES_AUTORISEES))}). D-CLI-9 : ce champ n'est valide "
                "NULLE PART sur ce chemin — il traverse client-service et atterrit tel quel "
                "dans le compte CHECKING. C'est ainsi qu'un compte reel a fini avec "
                "currency='ANY' (FRA-222). Le referentiel config-service ne peut pas servir "
                "de garde-fou : il contient lui-meme les entrees parasites 'cv' et '00'."
            )

    return normalisee


class ClientServiceClient:
    """Onboarding et souscriptions des Clients finaux.

    Le service ne declare AUCUNE dependance dans son contrat OpenAPI — zero
    occurrence de « identity », « account » ou « product ». Ses deux cascades
    reelles ne sont connues que par la mesure. C'est exactement pourquoi le
    Loader relit systematiquement ce qu'il a cree.
    """

    def __init__(self, journal: JournalRequetes | None = None) -> None:
        self._client = ClientFinZuu("client-service", settings.client_service_base, journal=journal)

    async def fermer(self) -> None:
        await self._client.fermer()

    # ----------------------------------------------------------------------
    # Lecture — D-CLI-5 : GET avant POST, toujours
    # ----------------------------------------------------------------------

    async def chercher_par_msisdn(self, msisdn: str) -> dict[str, Any] | None:
        """`INV-CLI-01` impose l'unicite du `msisdn`. On evite le HTTP 400
        plutot que de le decouvrir.

        Le serveur rend **404** quand le client n'existe pas, la ou un 200 avec
        corps vide serait attendu — d'ou `vide_si_404`. Un 404 ici est un
        resultat legitime, jamais une panne.
        """
        reponse = await self._client.get(
            f"/api/v1/clients/by-msisdn/{msisdn.strip()}", vide_si_404=True
        )
        return reponse.data if isinstance(reponse.data, dict) else None

    async def chercher_par_id_number(self, id_number: str) -> dict[str, Any] | None:
        reponse = await self._client.get(
            f"/api/v1/clients/by-id-number/{id_number.strip()}", vide_si_404=True
        )
        return reponse.data if isinstance(reponse.data, dict) else None

    async def lister(self) -> list[dict[str, Any]]:
        """Inventaire complet, pagination bornee a 100 par le socle (H20).

        Le wrapper de cet endpoint annonce « Campaign data retrieved
        successfully » — copier-coller depuis un autre service
        (`OBS-CLI-TYPO-01`, toujours vrai le 09/08). Le champ `description`
        n'est donc jamais utilise pour decider quoi que ce soit.
        """
        return await self._client.lister_tout("/api/v1/clients/")

    # ----------------------------------------------------------------------
    # Ecriture — UC-12 : onboarding, cascade vers identity ET account
    # ----------------------------------------------------------------------

    async def onboarder(
        self,
        *,
        msisdn: str,
        identity: dict[str, Any],
        product_id: UUID | str,
        currency: str,
        category: ClientCategory,
        segment: ClientSegment,
        channel: SubscriptionChannel,
        language: Language = Language.EN,
    ) -> dict[str, Any]:
        """Onboarde un Client et renvoie la fiche **relue depuis le serveur**.

        Les barrieres de `valider_onboarding()` sont posees AVANT le reseau,
        parce qu'aucune ne serait rattrapable apres : ni client-service, ni
        identity-service, ni account-service n'exposent de DELETE.
        """
        msisdn = msisdn.strip()
        payload_identity = valider_onboarding(msisdn, identity, currency)

        corps = {
            "msisdn": msisdn,
            "language": language.value,
            "channel": channel.value,
            "segment": segment.value,
            "category": category.value,
            "identity": payload_identity,
            "product_id": str(product_id),
            "currency": currency,
        }
        reponse = await self._client.requete("POST", "/api/v1/clients/onboard", json_body=corps)
        fiche = reponse.data if isinstance(reponse.data, dict) else {}

        # `language` est IGNORE a l'onboarding : envoye 'fr', rendu 'en'
        # (mesure du 09/08). Le seul chemin qui fonctionne est le PATCH dedie.
        if language is not Language.EN and fiche.get("language") != language.value:
            identifiant = normaliser_id(fiche)
            if identifiant:
                fiche = await self.changer_langue(identifiant, language)

        return fiche

    async def souscrire(self, msisdn: str, product_id: UUID | str) -> dict[str, Any]:
        """2e et 3e produits — `UC-13` prevoit 1 a 3 souscriptions par client.

        `D-CLI-7`, verifie le 09/08 : HTTP 200, le tableau `product` s'allonge.

        Aucun controle de coherence n'est fait par le serveur entre la
        `category` du Client et celle du Produit — un CORPORATE souscrit sans
        broncher a un produit INDIVIDUAL (`OBS-CLI-CROSSCHECK-01`, reconfirme
        le 09/08). La coherence est donc **entierement a notre charge**, en
        amont, dans la selection du produit.
        """
        fiche_avant = await self.chercher_par_msisdn(msisdn)
        deja = len((fiche_avant or {}).get("product") or [])
        if deja >= SOUSCRIPTIONS_MAX:
            raise OnboardingNonConforme(
                f"{deja} souscriptions deja attachees — UC-13 en autorise {SOUSCRIPTIONS_MAX} au "
                "maximum. Le serveur ne borne RIEN : mesure du 09/08, 6 produits ont ete "
                "attaches a un meme client sans le moindre rejet. Le plafond du CDC est "
                "entierement a notre charge."
            )
        reponse = await self._client.requete(
            "PUT",
            "/api/v1/clients/subscribe",
            json_body={"msisdn": msisdn.strip(), "product_id": str(product_id)},
        )
        return reponse.data if isinstance(reponse.data, dict) else {}

    async def changer_langue(self, client_id: UUID | str, langue: Language) -> dict[str, Any]:
        """Seul chemin qui modifie reellement la langue.

        `PATCH` est aussi la **seule mutation** exposee par ce service : ni
        DELETE, ni activation, ni desactivation, ni transition de statut.
        """
        reponse = await self._client.requete(
            "PATCH",
            f"/api/v1/clients/language/{client_id}",
            json_body={"language": langue.value},
        )
        return reponse.data if isinstance(reponse.data, dict) else {}

    # ----------------------------------------------------------------------
    # Lecture des identifiants produits par la cascade
    # ----------------------------------------------------------------------

    @staticmethod
    def identity_id(fiche: dict[str, Any]) -> str | None:
        """L'identifiant de l'Identity **rendu par le serveur**.

        Celui que le Loader a envoye dans `identity._id` est ignore : le
        serveur genere le sien (mesure du 09/08, meme famille que FRA-227).
        C'est celui-ci, et lui seul, que porte le compte CHECKING cree en
        cascade — `owner_type=IDENTITY`, `owner_id=<cet identifiant>`.
        """
        identite = fiche.get("identity")
        return normaliser_id(identite) if isinstance(identite, dict) else None

    @staticmethod
    def account_id(fiche: dict[str, Any]) -> str | None:
        """Le compte CHECKING cree par la cascade. Jamais a creer nous-memes."""
        valeur = fiche.get("account_id")
        return str(valeur) if valeur else None

    @staticmethod
    def identifiant(fiche: dict[str, Any]) -> str | None:
        return normaliser_id(fiche)
