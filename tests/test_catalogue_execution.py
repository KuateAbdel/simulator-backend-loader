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
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest

from app.clients.contracts import ProductType
from app.core.cdc import TAUX_USURE_MAX_ANNUEL_PCT
from app.models.enums import RunMode, RunStatus
from app.services.catalogue import (
    PRODUITS_ENVIRONNEMENT,
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

    def test_douze_creations_exactement(self) -> None:
        """6 LENDING (dedoublement `D-PRD-4`) + 6 COLLECT.

        Elles etaient DIX jusqu'au 12/08 : deux produits COLLECT venaient de
        l'environnement (`D-PRD-9`). Mesure du jour : ils portent 99 % d'interet
        mensuel et une fourchette de 3 a 3 — voir `PRODUITS_ENVIRONNEMENT`.
        """
        payloads = _tous_les_payloads()
        assert len(payloads) == CREATIONS_ATTENDUES == 12

    def test_les_douze_du_CDC_sont_desormais_TOUTES_les_notres(self) -> None:
        """`UC-11` annonce douze produits au catalogue. Ils sont maintenant douze
        CREATIONS : le catalogue vu par nos clients est entierement le notre,
        entierement prefixe, donc entierement reversible (`CR-07`)."""
        assert CREATIONS_ATTENDUES == PRODUITS_ATTENDUS == 12

    def test_aucun_produit_de_l_environnement_dans_les_payloads(self) -> None:
        noms_emis = {str(p["name"]) for p in payloads_collect()}
        for refuse in PRODUITS_ENVIRONNEMENT:
            assert refuse not in noms_emis

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


class TestPolicyTypeJusquAuPanier:
    """`UC-13` — le `PolicyType` doit ARRIVER jusqu'a `_panier()`.

    DEFAUT DU 12/08, ET IL ETAIT JUSTE PAR COINCIDENCE
    --------------------------------------------------
    `ProduitSouscriptible` a gagne un `policy_type` pour ordonner le panier
    (`CASH` -> `CASH_DAT` -> `PRODUCT`). Deux des QUATRE sites de construction ne
    le renseignaient pas, dont celui du produit PLANIFIE en DRY_RUN.

    Sans lui, le tri retombe sur le NOM — et « Cotisation » < « Depot » <
    « plastique » dans l'ordre alphabetique. Le rapport a blanc affichait donc un
    ordre metier correct POUR UNE RAISON FAUSSE. Aucun symptome ne le denonçait ;
    un simple renommage de produit l'aurait fait apparaitre en REEL.

    C'est la meme famille que le defaut du 11/08 documente juste au-dessus dans
    `catalogue_execution.py` : le produit prevu qui n'entrait pas dans
    `souscriptibles`. Meme endroit, meme lecon, appliquee a moitie.
    """

    #: `D-PRD-9` — les DEUX produits que le Loader ne cree pas mais RETROUVE.
    #: Mesure du 12/08 : tous deux presents en base, et tous deux INDIVIDUAL.
    #:
    #: FAIT A SIGNALER, trouve en ecrivant ce test : « Cotisation 20000/mois » est
    #: le seul produit `CASH` INDIVIDUAL du catalogue, donc le PRODUIT D'ENTREE
    #: des 1600 clients individuels — et il est preexistant. S'il disparaissait de
    #: l'environnement, `UC-13` n'aurait plus de porte d'entree pour eux.
    #: `rapport.ecart_au_cdc` le signale deja ; le panier tomberait alors sur
    #: `CASH_DAT`, ce qui serait un depot a terme sans epargne prealable.
    PREEXISTANTS: ClassVar[dict[str, tuple[str, str]]] = {
        "Cotisation 20000/mois": ("CASH", "INDIVIDUAL"),
        "plastique": ("PRODUCT", "INDIVIDUAL"),
    }

    @classmethod
    async def _a_blanc(cls) -> Any:
        """Les quatre produits COLLECT manquants sont PLANIFIES — on exerce donc
        le site de construction qui oubliait le `policy_type` — et les deux
        preexistants sont RETROUVES, comme dans l'environnement reel."""

        preexistants = cls.PREEXISTANTS

        class _Produits:
            async def chercher_par_nom(self, nom: str) -> dict[str, Any] | None:
                for attendu, (policy, categorie) in preexistants.items():
                    if attendu in nom:
                        return {
                            "_id": str(uuid4()),
                            "name": nom,
                            "category": categorie,
                            # `policy.type`, comme le vrai serveur (mesure 12/08).
                            "policy": {"type": policy},
                        }
                return None

        return await ExecuteurCatalogue(
            run_id=uuid4(),
            mode=RunMode.DRY_RUN,
            product_client=_Produits(),  # type: ignore[arg-type]
            audit=None,  # type: ignore[arg-type]
            chemin_loan_json=LOAN_JSON,
        ).executer()

    @pytest.mark.asyncio
    async def test_a_blanc_chaque_COLLECT_porte_son_policy_type(self) -> None:
        rapport = await self._a_blanc()
        collect = [p for p in rapport.souscriptibles if p.type_produit is ProductType.COLLECT]
        assert collect, "aucun COLLECT : le test ne prouverait rien"
        sans = [p.nom for p in collect if not p.policy_type]
        assert sans == [], f"policy_type absent : {sans}"

    @pytest.mark.asyncio
    async def test_a_blanc_les_trois_PolicyType_sont_TOUS_representes(self) -> None:
        """Le catalogue en declare trois par categorie. Si le rapport a blanc n'en
        montrait qu'un, `UC-13` ne pourrait produire qu'un panier d'un produit —
        et `D-01` fait de ce rapport « la derniere occasion de dire non »."""
        rapport = await self._a_blanc()
        collect = [p for p in rapport.souscriptibles if p.type_produit is ProductType.COLLECT]
        for categorie in ("INDIVIDUAL", "CORPORATE"):
            types = {p.policy_type for p in collect if p.categorie == categorie}
            assert types == {"CASH", "CASH_DAT", "PRODUCT"}, f"{categorie} : {types}"

    @pytest.mark.asyncio
    async def test_le_policy_type_ne_recopie_JAMAIS_le_ProductType(self) -> None:
        """Il vit dans `policy.type`, pas au premier niveau. Les confondre
        mettrait « COLLECT » partout et rendrait l'ordre metier muet."""
        rapport = await self._a_blanc()
        for produit in rapport.souscriptibles:
            assert produit.policy_type not in {"COLLECT", "LENDING"}, produit.nom
