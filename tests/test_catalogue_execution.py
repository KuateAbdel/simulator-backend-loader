"""
tests/test_catalogue_execution.py
=================================
`S3-05` — l'executeur Catalogue.

Ce que ces tests protegent :

  1. **le compte du CDC** — 12 produits, 10 creations, 2 reutilises. Un
     rapport qui annoncerait 12 creations mentirait sur deux produits.
  2. **les refus AVANT le reseau** — `policy` absente, `policy_id` partage,
     taux au-dessus du plafond d'usure. Le serveur ne dirait rien du second.
  3. **`D-PRD-9`** — les 2 preexistants sont RETROUVES, jamais recrees.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.clients.contracts import ProductType
from app.core.cdc import TAUX_USURE_MAX_ANNUEL_PCT
from app.models.enums import RunMode, RunStatus
from app.services.catalogue import (
    CATALOGUE_COLLECT,
    charger_loan_json,
    payloads_collect,
    payloads_lending,
)
from app.services.catalogue_execution import (
    CREATIONS_ATTENDUES,
    PRODUITS_ATTENDUS,
    ExecuteurCatalogue,
    RapportCatalogue,
)

LOAN_JSON = Path("docs/reference/loan_json.json")


def _tous_les_payloads() -> list[dict[str, Any]]:
    return payloads_lending(charger_loan_json(LOAN_JSON)) + payloads_collect()


class TestLeCompteDuCdc:
    """`UC-11` : 12 produits au total, dont 10 crees par le Loader."""

    def test_dix_creations_exactement(self) -> None:
        """6 LENDING (dedoublement `D-PRD-4`) + 4 COLLECT."""
        payloads = _tous_les_payloads()
        assert len(payloads) == CREATIONS_ATTENDUES == 10

    def test_les_deux_preexistants_ne_sont_jamais_dans_les_payloads(self) -> None:
        """`D-PRD-9` — « Cotisation 20000/mois » et « plastique » sont en base."""
        preexistants = {p.nom_recherche for p in CATALOGUE_COLLECT if p.preexistant}
        assert len(preexistants) == 2
        noms_emis = {str(p["name"]) for p in payloads_collect()}
        assert not (noms_emis & preexistants)

    def test_dix_plus_deux_font_les_douze_du_cdc(self) -> None:
        assert CREATIONS_ATTENDUES + 2 == PRODUITS_ATTENDUS == 12

    def test_le_split_D_PRD_4_produit_six_lending_a_partir_de_quatre(self) -> None:
        """`BNPL` et `ReadyToGo` portent `Category: Any`, refuse par l'enum
        serveur (`INV-PRD-04`, HTTP 422). Chacun est dedouble."""
        sources = charger_loan_json(LOAN_JSON)
        assert len(sources) == 4
        assert len(payloads_lending(sources)) == 6


class TestRefusAvantLeReseau:
    """Le Loader anticipe : ces trois controles tiennent en memoire."""

    def test_une_policy_absente_est_refusee_avant_tout_appel(self) -> None:
        """Le contrat la declare optionnelle ; son absence provoque un HTTP 500."""
        with pytest.raises(ValueError, match="policy absente"):
            ExecuteurCatalogue._verifier_avant_emission([{"name": "X", "policy": None}])

    def test_un_policy_id_partage_est_refuse(self) -> None:
        """Le cas le PLUS grave : le serveur ne dirait rien. La Policy est une
        reference vivante — la partager modifie retroactivement et
        silencieusement tous les autres Products (`INV-PRD-07`)."""
        with pytest.raises(ValueError, match="policy_id interdit"):
            ExecuteurCatalogue._verifier_avant_emission(
                [{"name": "X", "policy": {"a": 1}, "policy_id": "abc"}]
            )

    def test_un_taux_au_dessus_du_plafond_d_usure_est_refuse(self) -> None:
        """`EF-35` / `CR-01` — plafond BEAC/COBAC a 24 %, « meme en
        environnement de test »."""
        with pytest.raises(ValueError, match="plafond d'usure"):
            ExecuteurCatalogue._verifier_avant_emission(
                [{"name": "X", "policy": {"interest_rate": TAUX_USURE_MAX_ANNUEL_PCT + 1}}]
            )

    def test_les_payloads_reels_passent_tous_les_controles(self) -> None:
        """Le catalogue livre ne doit declencher aucun de ces refus."""
        ExecuteurCatalogue._verifier_avant_emission(_tous_les_payloads())


class TestStatutEtEcart:
    def test_reutiliser_sans_rien_creer_est_un_echec_systemique(self) -> None:
        """Retrouver un produit deja en base n'est pas un accomplissement de CE
        run — meme raisonnement que `RapportRoles`."""
        rapport = RapportCatalogue(mode=RunMode.REAL)
        rapport.reutilises.append("plastique")
        rapport.echoues.append(("X", "HTTP 500"))
        assert rapport.statut is RunStatus.FAILED

    def test_un_echec_isole_laisse_le_run_en_PARTIAL(self) -> None:
        rapport = RapportCatalogue(mode=RunMode.REAL)
        rapport.crees.append("A")
        rapport.echoues.append(("B", "HTTP 422"))
        assert rapport.statut is RunStatus.PARTIAL

    def test_un_compte_different_de_douze_est_SIGNALE_pas_corrige(self) -> None:
        """Le Loader constate l'etat de l'environnement, il ne le repare pas."""
        rapport = RapportCatalogue(mode=RunMode.REAL)
        rapport.crees.extend(str(i) for i in range(10))
        ExecuteurCatalogue._verifier_le_compte(rapport)
        assert "12 attendus" in rapport.ecart_au_cdc

    def test_le_compte_juste_ne_signale_rien(self) -> None:
        rapport = RapportCatalogue(mode=RunMode.REAL)
        rapport.crees.extend(str(i) for i in range(10))
        rapport.reutilises.extend(["Cotisation 20000/mois", "plastique"])
        ExecuteurCatalogue._verifier_le_compte(rapport)
        assert rapport.ecart_au_cdc == ""


class TestArtefactPourLaSuite:
    def test_les_souscriptibles_portent_un_type_EXPLICITE(self) -> None:
        """C'est le type qui declenche `D-DEP-9`. Un produit dont on ignore le
        type ne doit pas pouvoir entrer dans la boucle de souscription."""
        from app.services.depositaires_execution import ProduitSouscriptible

        p = ProduitSouscriptible(uuid4(), "DEMO_Collecte Cacao", ProductType.COLLECT)
        assert p.type_produit is ProductType.COLLECT

    @pytest.mark.asyncio
    async def test_un_produit_deja_present_est_reutilise_et_reste_souscriptible(self) -> None:
        """Les exclure priverait les Kiosques de deux produits reels."""
        identifiant = uuid4()

        class _Produits:
            async def chercher_par_nom(self, nom: str) -> dict[str, Any]:
                return {"_id": str(identifiant), "name": nom}

        executeur = ExecuteurCatalogue(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            product_client=_Produits(),  # type: ignore[arg-type]
            audit=None,  # type: ignore[arg-type]
            chemin_loan_json=LOAN_JSON,
        )
        rapport = await executeur.executer()
        assert len(rapport.crees) == 0, "tout existe deja : rien ne doit etre cree"
        assert len(rapport.souscriptibles) == PRODUITS_ATTENDUS
        assert all(isinstance(p.product_id, UUID) for p in rapport.souscriptibles)
        assert rapport.statut is RunStatus.COMPLETED
