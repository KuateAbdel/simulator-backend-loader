"""Catalogue Produits — parser tolerant et regles de creation. Hors ligne.

Le fichier `loan_json.json` du depot est le VRAI fichier source, malformé tel
quel. Ces tests le lisent reellement : si le format change, ils cassent, ce qui
est le comportement voulu.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.clients.contracts import PolicyType, ProductCategory
from app.core.cdc import PREFIXE_DONNEES, TAUX_USURE_MAX_ANNUEL_PCT
from app.services.catalogue import (
    CATALOGUE_COLLECT,
    charger_loan_json,
    payloads_collect,
    payloads_lending,
)

LOAN_JSON = Path("docs/reference/loan_json.json")


@pytest.fixture(scope="module")
def produits():  # type: ignore[no-untyped-def]
    return charger_loan_json(LOAN_JSON)


class TestParserTolerant:
    """D-PRD-5 — le fichier n'est PAS du JSON valide."""

    def test_le_fichier_source_est_bien_invalide(self) -> None:
        """On documente la raison d'etre du parser : un json.loads direct echoue."""
        import json

        with pytest.raises(json.JSONDecodeError):
            json.loads(LOAN_JSON.read_text(encoding="utf-8"))

    def test_les_4_produits_sont_lus(self, produits) -> None:  # type: ignore[no-untyped-def]
        assert [p.nom for p in produits] == ["Nano", "Macro", "BNPL", "ReadyToGo"]

    def test_les_5_segments_de_l_annexe_e(self, produits) -> None:  # type: ignore[no-untyped-def]
        for produit in produits:
            assert set(produit.montants_par_segment) == {
                "Very Low",
                "Low",
                "Medium",
                "High",
                "Very High",
            }

    def test_les_fourchettes_correspondent_a_l_annexe_e(self, produits) -> None:  # type: ignore[no-untyped-def]
        nano = next(p for p in produits if p.nom == "Nano")
        assert nano.montants_par_segment["Very High"] == (100000.0, 200000.0)
        assert nano.montants_par_segment["Very Low"] == (5000.0, 15000.0)

        ready = next(p for p in produits if p.nom == "ReadyToGo")
        assert ready.montants_par_segment["Very High"] == (100000.0, 1000000.0)
        assert ready.duree_jours == 15

        bnpl = next(p for p in produits if p.nom == "BNPL")
        assert bnpl.duree_jours == 30, "BNPL est le seul a 30 jours"

    def test_categories_source(self, produits) -> None:  # type: ignore[no-untyped-def]
        categories = {p.nom: p.categorie_source for p in produits}
        assert categories == {
            "Nano": "Individual",
            "Macro": "Business",
            "BNPL": "Any",
            "ReadyToGo": "Any",
        }

    def test_fichier_absent_echoue_avec_le_chemin(self, tmp_path: Path) -> None:
        """UC-11, exception : aucun pret sans catalogue."""
        with pytest.raises(FileNotFoundError, match="Chemin attendu"):
            charger_loan_json(tmp_path / "absent.json")


class TestPlafondUsure:
    def test_le_taux_est_borne_a_24(self, produits) -> None:  # type: ignore[no-untyped-def]
        """EF-35 / CR-01 — le fichier annonce 25 %, le plafond BEAC/COBAC est 24 %.

        CR-08 verifie ce point en recette : « aucun pret genere ne depasse le
        plafond d'usure ».
        """
        for produit in produits:
            assert produit.taux_max == 25.0, "le fichier annonce bien 25 %"
            assert produit.taux_applique == TAUX_USURE_MAX_ANNUEL_PCT == 24.0


class TestSplitAny:
    """D-PRD-4 / INV-PRD-04 — « ANY » est refuse par l'enum category."""

    def test_4_produits_donnent_6_creations(self, produits) -> None:  # type: ignore[no-untyped-def]
        payloads = payloads_lending(produits)
        assert len(payloads) == 6, "Nano x1, Macro x1, BNPL x2, ReadyToGo x2"

    def test_aucune_categorie_any(self, produits) -> None:  # type: ignore[no-untyped-def]
        for payload in payloads_lending(produits):
            assert payload["category"] in ("INDIVIDUAL", "CORPORATE")

    def test_le_segment_any_reste_autorise(self, produits) -> None:  # type: ignore[no-untyped-def]
        """Le piege : `category` refuse ANY, `segment` l'accepte. Deux enums
        differents, jamais a confondre."""
        for payload in payloads_lending(produits):
            assert payload["segment"] == "ANY"

    def test_bnpl_existe_dans_les_deux_categories(self, produits) -> None:  # type: ignore[no-untyped-def]
        payloads = payloads_lending(produits)
        bnpl = [p for p in payloads if "BNPL" in str(p["name"])]
        assert {str(p["category"]) for p in bnpl} == {"INDIVIDUAL", "CORPORATE"}


class TestPolicyEmbarquee:
    """D-PRD-1 et D-PRD-7 — les deux pieges les plus couteux."""

    def test_chaque_produit_a_sa_propre_policy(self, produits) -> None:  # type: ignore[no-untyped-def]
        """INV-PRD-07 : partager une Policy modifierait retroactivement les
        autres Products, silencieusement."""
        payloads = payloads_lending(produits) + payloads_collect()
        noms = [str(p["policy"]["name"]) for p in payloads]
        assert len(noms) == len(set(noms)), "aucune Policy n'est partagee"

    def test_aucun_policy_id_n_est_envoye(self, produits) -> None:  # type: ignore[no-untyped-def]
        for payload in payloads_lending(produits) + payloads_collect():
            assert "policy_id" not in payload

    def test_la_policy_est_toujours_presente(self, produits) -> None:  # type: ignore[no-untyped-def]
        """ANO-PRD-POLICY-01 : optionnelle au contrat, HTTP 500 si absente."""
        for payload in payloads_lending(produits) + payloads_collect():
            assert payload["policy"], "policy vide provoquerait un HTTP 500"

    def test_les_5_fourchettes_vont_dans_amount_by_segment(self, produits) -> None:  # type: ignore[no-untyped-def]
        for payload in payloads_lending(produits):
            segments = payload["policy"]["amount_by_segment"]
            assert set(segments) == {"VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"}
            for bornes in segments.values():
                assert bornes["min_amount"] <= bornes["max_amount"]

    def test_measure_toujours_explicite(self) -> None:
        """D-PRD-8 — la WebApp injecte KILOGRAM en dur sans que l'operateur le
        sache. On choisit, on ne subit pas."""
        for payload in payloads_collect():
            assert payload["policy"]["measure"] in ("KILOGRAM", "LITER")


class TestCatalogueCollect:
    """D-PRD-9 — croisement PolicyType x Category, noms reels."""

    def test_croisement_complet_3x2(self) -> None:
        croisements = {(p.policy_type, p.categorie) for p in CATALOGUE_COLLECT}
        assert len(croisements) == 6
        for type_policy in (PolicyType.CASH, PolicyType.CASH_DAT, PolicyType.PRODUCT):
            for categorie in (ProductCategory.INDIVIDUAL, ProductCategory.CORPORATE):
                assert (type_policy, categorie) in croisements

    def test_les_2_preexistants_ne_sont_jamais_recrees(self) -> None:
        """« Cotisation 20000/mois » et « plastique » existent deja."""
        a_creer = {str(p["name"]) for p in payloads_collect()}
        assert not any("Cotisation 20000/mois" == n for n in a_creer)
        assert not any("plastique" == n for n in a_creer)
        assert len(payloads_collect()) == 4

    def test_les_preexistants_gardent_leur_nom_sans_prefixe(self) -> None:
        """Ils ne sont pas notres : on les retrouve tels qu'ils sont."""
        for produit in CATALOGUE_COLLECT:
            if produit.preexistant:
                assert not produit.nom_recherche.startswith(PREFIXE_DONNEES)
            else:
                assert produit.nom_recherche.startswith(PREFIXE_DONNEES)

    def test_les_noms_sont_reels_jamais_generiques(self) -> None:
        """Le CDC et la demo exigent des noms metier credibles."""
        noms = [p.nom for p in CATALOGUE_COLLECT]
        assert "Collecte Cacao" in noms, "produit d'export camerounais reel"
        assert "Depot a Terme 6 Mois" in noms
        for nom in noms:
            assert "Test" not in nom and "Produit 1" not in nom

    def test_le_catalogue_cible_compte_12_produits(self, produits) -> None:  # type: ignore[no-untyped-def]
        """6 LENDING + 6 COLLECT — la volumetrie du CDC."""
        assert len(payloads_lending(produits)) == 6
        assert len(CATALOGUE_COLLECT) == 6
