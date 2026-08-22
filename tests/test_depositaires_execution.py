"""Execution du module Depositaires — hors ligne, avec des doublures.

Ce que ces tests verrouillent, dans l'ordre d'importance :

1. **`D-DEP-9`** — un Depositaire ne souscrit qu'a des produits `COLLECT`.
   Le serveur, lui, accepte un produit `LENDING` en HTTP 201 (mesure du 08/08,
   `ANO-DEP-TYPE-02`). C'est donc le seul garde-fou existant : s'il saute, un
   kiosque d'epargne se met a « vendre » des prets et personne ne le voit.
2. **`D-DEP-2`** — 6 comptes par Kiosque **souscrit**, jamais 6 par
   souscription. Confondre les deux ferait annoncer 324 comptes la ou il y en a
   54.
3. **`DRY_RUN`** — zero ecriture, ni vers le serveur ni vers `org_hierarchy`.
4. **Un quartier, un Kiosque** — la garantie doit tenir sans l'index Mongo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pymongo.errors import DuplicateKeyError

from app.clients.base import ErreurService
from app.clients.contracts import ProductType
from app.clients.depositary_service import COMPTES_DEPOSITAIRE, DepositaryServiceClient
from app.models.enums import RunMode, RunStatus
from app.services.depositaires_execution import (
    CompanyPorteuse,
    ExecuteurDepositaires,
    ProduitSouscriptible,
    RapportDepositaires,
)
from app.services.generateur import Generateur
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.organisation import planifier

RUN_ID = UUID("11111111-2222-3333-4444-555555555555")

#: Le referentiel reel, charge une seule fois : c'est un fichier de 3 onglets,
#: le relire a chaque test triplerait la duree de la suite pour rien.
_REFERENTIEL: ReferentielGeo | None = None


def _geo() -> ReferentielGeo:
    global _REFERENTIEL
    if _REFERENTIEL is None:
        _REFERENTIEL = charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))
    return _REFERENTIEL


EPARGNE = ProduitSouscriptible(uuid4(), "DEMO_Cotisation 20000/mois", ProductType.COLLECT)
PRET = ProduitSouscriptible(uuid4(), "DEMO_Nano credit", ProductType.LENDING)


# -- Doublures : aucune sortie reseau -------------------------------------


class DepositaireClientMuet:
    """Repond « rien ne pre-existe » et compte les ecritures tentees."""

    def __init__(self) -> None:
        self.creations = 0
        self.souscriptions: list[tuple[str, str]] = []

    async def chercher_par_nom(self, nom: str) -> dict[str, Any] | None:
        return None

    async def creer(self, nom: str, devise: str, company_id: Any) -> dict[str, Any]:
        self.creations += 1
        return {"_id": str(uuid4()), "name": nom, "currency": devise}

    async def a_deja_souscrit(self, depositary_id: Any, product_id: Any) -> bool:
        return False

    async def souscrire(
        self, depositary_id: Any, product_id: Any, *, type_produit: ProductType
    ) -> dict[str, Any]:
        # La doublure applique la MEME barriere que le client reel : sans cela,
        # le test validerait un executeur qui n'est protege que par hasard.
        DepositaryServiceClient.valider_type_produit(type_produit)
        self.souscriptions.append((str(depositary_id), str(product_id)))
        return {"_id": str(uuid4())}

    @staticmethod
    def identifiant(depositaire: dict[str, Any]) -> str | None:
        return str(depositaire.get("_id")) if depositaire.get("_id") else None


class DepositaireClientDefaillant(DepositaireClientMuet):
    """La creation echoue en HTTP 400 — le run doit poursuivre, pas s'arreter."""

    async def creer(self, nom: str, devise: str, company_id: Any) -> dict[str, Any]:
        raise ErreurService(
            "depositary-service", "POST", "/api/v1/depositaries/create", 400, "boom", "req-test"
        )


class HierarchieMuette:
    def __init__(self, *, quartiers_deja_pris: set[str] | None = None) -> None:
        self.ecritures = 0
        self.kiosques: list[str] = []
        #: (company_id, region_id) des Branches ecrites — la doublure applique
        #: l'index unique `uniq_branche_par_company_region_run` comme Mongo :
        #: c'est lui qui a tue le run REAL du 21/08, un test qui ne le rejoue
        #: pas ne protege rien.
        self.branches_posees: set[tuple[str, str]] = set()
        self._pris = quartiers_deja_pris or set()

    async def ajouter_branche(self, **kwargs: Any) -> Any:
        cle = (str(kwargs["company_id"]), str(kwargs["region_id"]))
        if cle in self.branches_posees:
            raise DuplicateKeyError("E11000 duplicate key error (doublure d'index)")
        self.branches_posees.add(cle)
        self.ecritures += 1
        return _Noeud()

    async def ajouter_agence(self, **kwargs: Any) -> Any:
        self.ecritures += 1
        return _Noeud()

    async def ajouter_kiosque(self, **kwargs: Any) -> Any:
        self.ecritures += 1
        district = str(kwargs["district_id"])
        if district in self._pris:
            return None  # ce que fait l'index unique Mongo
        self._pris.add(district)
        self.kiosques.append(str(kwargs["name"]))
        return _Noeud()


class _Noeud:
    id = uuid4()


class AuditMuet:
    def __init__(self) -> None:
        self.entrees: list[str] = []

    async def journaliser(self, **kwargs: Any) -> None:
        self.entrees.append(str(kwargs["entity_type"]))


def _executeur(
    mode: RunMode,
    *,
    depositaires: DepositaireClientMuet | None = None,
    hierarchie: HierarchieMuette | None = None,
) -> tuple[ExecuteurDepositaires, DepositaireClientMuet, HierarchieMuette, AuditMuet]:
    client = depositaires or DepositaireClientMuet()
    arbre = hierarchie or HierarchieMuette()
    audit = AuditMuet()
    executeur = ExecuteurDepositaires(
        run_id=RUN_ID,
        mode=mode,
        referentiel=_geo(),
        generateur=Generateur(RUN_ID),
        depositary_client=client,  # type: ignore[arg-type]
        hierarchie=arbre,  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
    )
    return executeur, client, arbre, audit


_DEVISES = {"CM": "XAF", "CI": "XOF", "BF": "XOF", "SN": "XOF"}


def _porteuses(plan: Any = None) -> dict[str, list[CompanyPorteuse]]:
    """Une porteuse PAR RANG du plan — le contrat reel depuis le 21/08.

    Sans plan (tests unitaires hors `executer`), une seule IMF de rang 0.
    """
    if plan is None:
        return {
            pays: [CompanyPorteuse(uuid4(), f"IMF {pays}", pays, devise)]
            for pays, devise in _DEVISES.items()
        }
    return {
        plan_pays.country_code: [
            CompanyPorteuse(
                uuid4(),
                f"IMF {plan_pays.country_code} {rang}",
                plan_pays.country_code,
                _DEVISES[plan_pays.country_code],
                imf_rang=rang,
            )
            for rang in range(plan_pays.nb_imf)
        ]
        for plan_pays in plan.pays
    }


# -- D-DEP-9 : la decouverte du 08/08 ------------------------------------


def test_un_produit_lending_est_refuse_avant_le_reseau() -> None:
    """La barriere leve, elle ne se contente pas de renvoyer False.

    Elle est `@staticmethod` precisement pour etre eprouvable sans client HTTP :
    une barriere qu'on ne peut tester qu'en frappant le serveur n'est pas une
    barriere, c'est un espoir.
    """
    with pytest.raises(ValueError, match="D-DEP-9"):
        DepositaryServiceClient.valider_type_produit(ProductType.LENDING)

    DepositaryServiceClient.valider_type_produit(ProductType.COLLECT)  # ne leve pas


def test_le_catalogue_ecarte_les_produits_lending_une_seule_fois() -> None:
    """Le filtre est AVANT la boucle : un produit ecarte l'est une fois, pas 54.

    Et il laisse une trace — un catalogue mal constitue doit se voir dans le
    rapport, pas seulement dans les logs.
    """
    executeur, _, _, _ = _executeur(RunMode.DRY_RUN)
    rapport = RapportDepositaires(mode=RunMode.DRY_RUN)

    retenus = executeur.filtrer_catalogue([EPARGNE, PRET, EPARGNE], rapport)

    assert [p.type_produit for p in retenus] == [ProductType.COLLECT, ProductType.COLLECT]
    assert len(rapport.produits_ecartes) == 1
    assert "D-DEP-9" in rapport.produits_ecartes[0][1]


@pytest.mark.asyncio
async def test_aucune_souscription_lending_ne_part_sur_le_reseau() -> None:
    """Bout en bout : meme si un LENDING traverse le filtre, rien ne part.

    On court-circuite volontairement `filtrer_catalogue` en appelant
    `souscrire_kiosque` directement — c'est le scenario ou notre propre code
    aurait un defaut. Le serveur repondrait 201 ; la doublure, elle, applique la
    barriere reelle.
    """
    executeur, client, _, _ = _executeur(RunMode.REAL)
    rapport = RapportDepositaires(mode=RunMode.REAL)

    await executeur.souscrire_kiosque(
        depositary_id=uuid4(),
        nom_kiosque="DEMO_Kiosque Test",
        produits=[PRET, EPARGNE],
        rapport=rapport,
    )

    assert len(client.souscriptions) == 1  # seule l'epargne est passee
    assert len(rapport.souscriptions_echouees) == 1
    assert "D-DEP-9" in rapport.souscriptions_echouees[0][1]


# -- D-DEP-2 : 6 comptes par Kiosque, pas par souscription ---------------


@pytest.mark.asyncio
async def test_six_comptes_par_kiosque_souscrit_et_non_par_souscription() -> None:
    """Trois souscriptions sur un meme Kiosque -> toujours 6 comptes.

    Mesure du 08/08 : 1re souscription -> +6, 2e -> +0. Le compteur suit le
    Kiosque, jamais la souscription.
    """
    executeur, _, _, _ = _executeur(RunMode.REAL)
    rapport = RapportDepositaires(mode=RunMode.REAL)
    trois_produits = [
        EPARGNE,
        ProduitSouscriptible(uuid4(), "DEMO_Tontine", ProductType.COLLECT),
        ProduitSouscriptible(uuid4(), "DEMO_Plan Scolaire", ProductType.COLLECT),
    ]

    await executeur.souscrire_kiosque(
        depositary_id=uuid4(),
        nom_kiosque="DEMO_Kiosque Test",
        produits=trois_produits,
        rapport=rapport,
    )

    assert rapport.souscriptions_creees == 3
    assert rapport.kiosques_souscrits == 1
    assert rapport.comptes_attendus == len(COMPTES_DEPOSITAIRE) == 6


# -- DRY_RUN et idempotence ----------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_n_ecrit_ni_sur_le_serveur_ni_dans_la_hierarchie() -> None:
    """Zero ecriture des deux cotes.

    Ecrire `org_hierarchy` sans les Depositaires produirait des noeuds pointant
    vers un `depositary_id` inexistant — une base incoherente des le premier
    essai a blanc.
    """
    executeur, client, arbre, audit = _executeur(RunMode.DRY_RUN)
    plan = planifier(_geo(), RUN_ID)

    rapport = await executeur.executer(plan, _porteuses(plan), [EPARGNE])

    assert client.creations == 0
    assert client.souscriptions == []
    assert arbre.ecritures == 0
    assert audit.entrees == []
    assert rapport.kiosques_crees  # le plan est bien deroule, il est juste simule
    assert all(nom.endswith("[prevu]") for nom in rapport.kiosques_crees)
    assert rapport.statut is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_un_quartier_n_heberge_qu_un_seul_kiosque() -> None:
    """La garantie doit tenir **sans** l'index unique Mongo.

    En DRY_RUN, l'index ne joue pas : seul l'ensemble en memoire empeche deux
    guichets de se superposer. C'est ce que CR-02 verifie apres coup ; ici on
    verifie qu'on ne le viole pas avant.
    """
    executeur, _, _, _ = _executeur(RunMode.DRY_RUN)
    plan = planifier(_geo(), RUN_ID)

    rapport = await executeur.executer(plan, _porteuses(plan), [EPARGNE])

    prevus = len(rapport.kiosques_crees)
    assert prevus == len(executeur.quartiers_occupes)  # un quartier = un Kiosque
    assert prevus == sum(p.nb_kiosques for p in plan.pays)


@pytest.mark.asyncio
async def test_un_kiosque_deja_present_est_saute_et_non_recree() -> None:
    """D-DEP-3 — aucune unicite serveur, aucun DELETE : le doublon serait definitif."""

    class ClientAvecExistant(DepositaireClientMuet):
        async def chercher_par_nom(self, nom: str) -> dict[str, Any] | None:
            return {"_id": str(uuid4()), "name": nom}

    executeur, client, _, _ = _executeur(RunMode.REAL, depositaires=ClientAvecExistant())
    plan = planifier(_geo(), RUN_ID)

    rapport = await executeur.executer(plan, _porteuses(plan), [EPARGNE])

    assert client.creations == 0
    assert rapport.kiosques_crees == []
    assert rapport.kiosques_sautes
    # Saute n'est pas echec : un run idempotent reste COMPLETED.
    assert rapport.statut is RunStatus.COMPLETED
    # Mais les souscriptions manquantes sont bien rattrapees sur l'existant.
    assert client.souscriptions


@pytest.mark.asyncio
async def test_un_kiosque_en_echec_ne_stoppe_pas_le_reseau() -> None:
    """Un 4xx n'est jamais rejoue — on journalise et on passe au suivant."""
    executeur, _, _, _ = _executeur(RunMode.REAL, depositaires=DepositaireClientDefaillant())
    plan = planifier(_geo(), RUN_ID)

    rapport = await executeur.executer(plan, _porteuses(plan), [EPARGNE])

    assert rapport.kiosques_echoues
    assert rapport.kiosques_crees == []
    assert rapport.comptes_attendus == 0
    # Rien n'a abouti : c'est systemique, donc FAILED et non PARTIAL.
    assert rapport.statut is RunStatus.FAILED


@pytest.mark.asyncio
async def test_un_pays_sans_imf_est_saute_sans_etre_un_echec() -> None:
    """UC-09 repose sur les IMF : sans porteur, ce n'est pas ici que ca se signale."""
    executeur, client, _, _ = _executeur(RunMode.REAL)
    plan = planifier(_geo(), RUN_ID)

    rapport = await executeur.executer(plan, {}, [EPARGNE])

    assert client.creations == 0
    assert rapport.kiosques_echoues == []
    assert len(rapport.kiosques_sautes) == len(plan.pays)
    assert all("aucune IMF" in motif for _, motif in rapport.kiosques_sautes)


# -- Le crash du 21/08 : une Organisation PARTIELLE ne doit ni dupliquer
# -- ni tuer le run -------------------------------------------------------


@pytest.mark.asyncio
async def test_le_reseau_d_une_imf_manquante_est_saute_jamais_reattribue() -> None:
    """REJEU DU CRASH DU PREMIER RUN REAL (21/08, prod).

    L'Organisation n'a cree que 14 IMF sur 18 : les rangs manquants etaient
    REPLIES par modulo sur les IMF survivantes -> deux Branches pour la meme
    company dans la meme region -> `E11000` -> run mort a DEPOSITAIRES.

    Le contrat depuis : le reseau d'une IMF absente est SAUTE et DECLARE.
    La doublure d'hierarchie applique le meme index unique que Mongo — si la
    reattribution revenait, ce test mourrait exactement comme la prod.
    """
    executeur, client, _arbre, _ = _executeur(RunMode.REAL)
    plan = planifier(_geo(), RUN_ID)
    porteuses = _porteuses(plan)
    # On ampute le rang 0 de CHAQUE pays : le pire cas mesurable — chaque pays
    # a au moins un reseau planifie sans porteuse.
    ampute = {pays: [p for p in liste if p.imf_rang != 0] for pays, liste in porteuses.items()}

    rapport = await executeur.executer(plan, ampute, [EPARGNE])

    # 1. Pas de crash, et AUCUN doublon (company, region) n'a atteint l'index.
    assert rapport.reseaux_sautes
    assert rapport.hierarchie_echouee == []
    # 2. Chaque reseau saute est declare avec son rang et son ampleur.
    assert all("rang 0" in motif for _, motif in rapport.reseaux_sautes)
    assert all("Kiosque(s) non crees" in motif for _, motif in rapport.reseaux_sautes)
    # 3. Les reseaux des IMF survivantes sont bien deroules, eux.
    assert rapport.branches_creees
    assert client.creations > 0
    # 4. Une degradation declaree n'est pas un run propre : PARTIAL.
    assert rapport.statut is RunStatus.PARTIAL


@pytest.mark.asyncio
async def test_une_branche_dupliquee_est_un_echec_nomme_pas_un_crash() -> None:
    """Defense en profondeur : meme si un doublon atteignait l'index, le run
    doit le RAPPORTER et poursuivre — plus jamais une `DuplicateKeyError` brute
    qui interrompt tout (c'est elle qui a masque la cause reelle le 21/08)."""

    class HierarchieDejaOccupee(HierarchieMuette):
        async def ajouter_branche(self, **kwargs: Any) -> Any:
            raise DuplicateKeyError("E11000 duplicate key error (doublure)")

    executeur, _, _, _ = _executeur(RunMode.REAL, hierarchie=HierarchieDejaOccupee())
    plan = planifier(_geo(), RUN_ID)

    rapport = await executeur.executer(plan, _porteuses(plan), [EPARGNE])

    assert rapport.hierarchie_echouee
    assert all("index d'unicite" in motif for _, motif in rapport.hierarchie_echouee)
    assert rapport.branches_creees == []
    # Rien n'a abouti alors que le plan prevoyait tout : systemique -> FAILED.
    assert rapport.statut is RunStatus.FAILED
