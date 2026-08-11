"""
app/services/source_interne.py
==============================
La source d'identites INTERNE — reponse a l'arbitrage `A-01`, le Senegal.

POURQUOI ELLE EXISTE : FAKER NE SERT PAS LE SENEGAL
--------------------------------------------------
`OBJ-01` et `EF-05` exigent QUATRE pays. Faker n'en sert que trois, et ce n'est
pas un aleas de runtime — **son contrat le declare** :

    GET /v1/faker/client            country_code  enum: ["BF", "CI", "CM"]
    GET /v1/faker/client/individual country_code  enum: ["BF", "CI", "CM"]
    GET /v1/faker/client/business   country_code  enum: ["BF", "CI", "CM"]

Mesure du 11/08, refaite en direct trois jours apres la premiere :

    famille A  /client/individual?country_code=SN  -> HTTP 422
               « Input should be 'BF', 'CI' or 'CM' »   (literal_error)
    famille B  /real-scoring-phone/random&...&SN   -> HTTP 404
               ... et la MEME URL sur CM           -> HTTP 200

Le temoin de controle sur CM etait necessaire : `loan-history/random` rend 404
sur le Cameroun aussi, donc son 404 sur SN n'aurait rien prouve. Seul
`real-scoring-phone` isole vraiment l'absence de population senegalaise.

CE N'EST PAS UN CONTOURNEMENT — C'EST LA DOCTRINE DU CDC, §321
--------------------------------------------------------------
    « L'outil combinera DEUX sources de generation : d'une part l'API Faker
    pour les payloads clients, d'autre part un GENERATEUR INTERNE pour les
    entites organisationnelles absentes de Faker. »

Le Loader compose deja lui-meme ce que Faker ne fournit pas : les Companies,
les 4 Lenders institutionnels, les Depositaires, les raisons sociales, les
adresses, les dates de naissance, les MSISDN — et meme, pour les trois pays
servis, tout sauf huit champs. Servir le Senegal ainsi applique la meme regle a
un cas de plus. La difference n'est pas de nature ; elle est de degre.

LA PROVENANCE EST VISIBLE, JAMAIS MASQUEE
-----------------------------------------
Le `client_id` porte le prefixe `INTERNE-` : il se lit dans le rapport, dans le
registre de consommation, et dans le journal. Un operateur qui compte 500
clients senegalais doit pouvoir dire d'ou ils viennent SANS relire ce fichier.

Les champs qui n'existent que chez Faker restent a `None` — `msisdn`,
`identite`, `company`. Fabriquer un faux `sim_number` ou une fausse
`company_name` pour « faire comme Faker » serait exactement l'invention
arbitraire que le CDC interdit, et cela effacerait la trace. Le composeur n'en
a de toute facon pas besoin : il compose deja le MSISDN (aucun numero Faker
n'est attribuable, `D-CFG-1`) et la piece d'identite.

DEUX DIFFERENCES ASSUMEES AVEC LES PAYS SERVIS PAR FAKER
--------------------------------------------------------
1. **Le ratio des genres est produit directement**, deux femmes pour un homme
   (`EF-22`), au lieu d'etre obtenu par tirage-et-rejet. Nous controlons la
   source : la respecter d'emblee evite de bruler des tirages pour rien. Le
   moteur de quotas reste l'autorite et verifie comme partout ailleurs — il
   ecarte simplement beaucoup moins. Le Senegal converge donc plus vite que
   ses voisins, et c'est explicable.
2. **Aucun `secteur` ni `type juridique` de tracabilite Faker.** Le secteur
   d'activite vient du moteur de quotas (`EF-24`, taxonomie du CDC), comme pour
   les autres pays — seule la trace « d'ou venait la matiere » est vide, parce
   qu'il n'y a pas de matiere Faker.

TOUT EST DETERMINISTE (`ENF-15`)
--------------------------------
Le meme `seed` rend le meme client, sans aucun tirage aleatoire : le genre, le
prenom, le patronyme et le profil socio-economique derivent du seed par calcul.
Deux executions de meme `run_id` produisent donc le meme ecosysteme senegalais
— exactement la garantie que le `seed` apporte du cote Faker.
"""

from __future__ import annotations

from typing import Final, Protocol

from app.clients.faker_service import CategorieClient, ClientFaker
from app.services.generateur import (
    CLES_PROFIL_INTERNE,
    PATRONYMES_PAR_PAYS,
    patronyme,
    prenom,
)

#: Prefixe du `client_id` interne. Il rend la provenance lisible partout ou
#: l'identifiant circule — rapport, registre, journal — sans qu'on ait a
#: consulter une table de correspondance.
PREFIXE_INTERNE: Final = "INTERNE"

#: `EF-22` — « ratio deux femmes pour un homme ». Produit directement : un seed
#: sur trois donne un homme. Le moteur de quotas verifie quand meme.
CYCLE_GENRE: Final = 3


class SourceIdentites(Protocol):
    """Ce que l'executeur CLIENTS attend d'une source, Faker ou interne.

    Le contrat est volontairement celui de `FakerClient.tirer_client` : la
    boucle de peuplement n'a alors AUCUN branchement par pays. Un `if pays ==
    "SN"` reparti dans la boucle aurait fini par diverger du chemin principal —
    et c'est le chemin principal qui est teste.
    """

    async def tirer_client(
        self, pays: str, categorie: str, seed: int
    ) -> ClientFaker | None: ...


class SourceInterne:
    """Produit des clients pour un pays que Faker ne sert pas.

    Aucun appel reseau : tout est calcule. Le mode a blanc et le mode reel sont
    donc identiques ici, et la source ne peut pas etre indisponible.
    """

    #: Les pays que cette source sait servir. `EF-05` borne le perimetre aux
    #: quatre cibles ; un pays hors referentiel de patronymes serait servi avec
    #: des noms d'un autre pays, et personne ne le verrait.
    PAYS_SERVIS: Final[frozenset[str]] = frozenset({"SN"})

    async def tirer_client(
        self, pays: str, categorie: str, seed: int
    ) -> ClientFaker | None:
        """Compose un client depuis le seed. Rend `None` sur un pays non servi.

        `None` plutot qu'une exception : l'executeur traite deja un tirage muet
        comme un ecart a compter, et un pays non servi n'est pas une panne — la
        boucle doit pouvoir continuer sur les autres.
        """
        territoire = pays.upper()
        if territoire not in self.PAYS_SERVIS:
            return None

        business = categorie == CategorieClient.BUSINESS
        # `EF-22` — deux femmes pour un homme, produit directement.
        genre = "MAN" if seed % CYCLE_GENRE == 0 else "WOMAN"

        return ClientFaker(
            # La provenance, lisible sans decodeur.
            client_id=f"{PREFIXE_INTERNE}-{territoire}-{'BIZ' if business else 'IND'}-{seed}",
            pays=territoire,
            # Zone UEMOA. Le composeur la reprend du pays de toute facon
            # (`valider_devise_pays`) — la poser juste ici evite qu'un lecteur
            # croie a une incoherence.
            devise="XOF",
            categorie=CategorieClient.BUSINESS if business else CategorieClient.INDIVIDUAL,
            # Faker seul a un `sim_number`. Le notre est compose par le
            # composeur, depuis le plan de numerotation reel (`D-CFG-1`).
            msisdn=None,
            prenom=prenom("FEMALE" if genre == "WOMAN" else "MALE", seed),
            nom=patronyme(territoire, seed),
            nom_complet=None,
            genre=genre,
            # La piece d'identite est composee par le generateur (`D-CLI-3`
            # alphanumerique majuscules, `D-CLI-2` expiration toujours posee).
            identite=None,
            # Pas de matiere Faker : le secteur vient du moteur de quotas.
            company=None,
            quick_win=self._profil(seed),
            seed=seed,
        )

    @staticmethod
    def _profil(seed: int) -> dict[str, int]:
        """Le profil socio-economique, derive du seed par calcul.

        Ces onze champs sont exactement ceux que la famille A porte, et c'est
        d'eux que `solde_initial()` derive le patrimoine du client (`A-09`). Un
        profil constant donnerait 500 Senegalais au solde identique — visible au
        premier graphique. Chaque cle est donc allumee ou eteinte par un bit
        distinct du seed : la dotation senegalaise s'etale comme celle de ses
        voisins, et reste strictement reproductible.
        """
        return {cle: (seed >> rang) & 1 for rang, cle in enumerate(CLES_PROFIL_INTERNE)}


def source_pour(pays: str, faker: SourceIdentites, interne: SourceIdentites) -> SourceIdentites:
    """Rend la source qui sert ce pays. Le SEUL endroit qui choisit.

    Concentrer l'arbitrage ici plutot que dans la boucle garantit que Faker et
    la source interne empruntent rigoureusement le meme chemin ensuite — meme
    composeur, meme registre, memes quotas, memes controles.
    """
    return interne if pays.upper() in SourceInterne.PAYS_SERVIS else faker


def est_interne(client_id: str) -> bool:
    """Vrai si ce client vient de la source interne — lisible depuis l'`_id` seul.

    C'est ce qui permet au rapport, au registre et au journal de dire la
    provenance sans conserver un champ de plus a cote.
    """
    return client_id.startswith(f"{PREFIXE_INTERNE}-")


__all__ = [
    "CYCLE_GENRE",
    "PATRONYMES_PAR_PAYS",
    "PREFIXE_INTERNE",
    "SourceIdentites",
    "SourceInterne",
    "est_interne",
    "source_pour",
]
