"""Catalogue Produits — parser tolerant et regles de creation. Hors ligne.

Le fichier `loan_json.json` du depot est le VRAI fichier source, malformé tel
quel. Ces tests le lisent reellement : si le format change, ils cassent, ce qui
est le comportement voulu.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.clients.contracts import PolicyMeasure, PolicyType, ProductCategory
from app.core.cdc import PREFIXE_DONNEES, TAUX_USURE_MAX_ANNUEL_PCT
from app.services.catalogue import (
    CATALOGUE_COLLECT,
    PRODUITS_ENVIRONNEMENT,
    ProduitCollecte,
    charger_loan_json,
    duree_mois_du_produit,
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

    def test_les_SIX_collect_sont_les_notres_aucun_de_l_environnement(self) -> None:
        """DECISION DU 12/08 — `D-PRD-9` renversee sur mesure.

        Ces deux produits etaient RETROUVES plutot que crees : ils existaient
        deja avec des abonnes, et product-service n'a ni unicite ni `DELETE`. La
        regle etait bonne ; ce qu'elle ignorait, c'est ce qu'ils CONTIENNENT.

        Mesure du 12/08 sur le serveur TEST :
            « Cotisation 20000/mois »  interest_rate 99,0 %  amount 1 000 -> 100 000
            « plastique »              interest_rate 22,0 %  amount 3,0 -> 3,0

        Le produit d'ENTREE de nos 1600 clients INDIVIDUAL portait 99 % d'interet
        mensuel, et « plastique » n'acceptait qu'une quantite de exactement 3.
        On ne batit pas un catalogue de demonstration sur les valeurs de test
        d'un environnement partage.
        """
        a_creer = {str(p["name"]) for p in payloads_collect()}
        assert len(a_creer) == 6, "croisement complet PolicyType x Category"
        for refuse in PRODUITS_ENVIRONNEMENT:
            assert refuse not in a_creer, f"{refuse} porte des valeurs de test"

    def test_chaque_produit_du_catalogue_porte_le_prefixe(self) -> None:
        """`CR-07`/`EF-63` — sans exception, desormais. Le drapeau `preexistant`
        qui rendait deux noms nus a disparu avec les produits qu'il servait :
        aucune entite de notre catalogue n'echappe plus a la purge."""
        for produit in CATALOGUE_COLLECT:
            assert produit.nom_recherche.startswith(PREFIXE_DONNEES), produit.nom
        for payload in payloads_collect():
            assert str(payload["name"]).startswith(PREFIXE_DONNEES)

    def test_les_produits_de_l_environnement_sont_NOMMES_pour_etre_evites(self) -> None:
        """Les connaitre est ce qui permet de ne pas les consommer par accident —
        et de les signaler au rapport plutot que de les taire."""
        assert PRODUITS_ENVIRONNEMENT == ("Cotisation 20000/mois", "plastique")
        noms = {p.nom for p in CATALOGUE_COLLECT}
        assert not (noms & set(PRODUITS_ENVIRONNEMENT)), (
            "un produit de notre catalogue ne doit pas porter le nom exact d'un "
            "produit de l'environnement : le GET-avant-POST le retrouverait"
        )

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


class TestTermeDuDepotATerme:
    """« CASH_DAT il faut une duree qu'il faut attribuer » — remarque de Yaniv,
    12/08. Elle etait juste, et le manque etait REEL.

    MESURE DE L'OPENAPI VIVANT DE PRODUCT-SERVICE, 12/08
    ----------------------------------------------------
    `CollectPolicySchema` porte TREIZE champs — `name`, `type`, `interest_type`,
    `interest_rate`, `interest_x`, `vat`, `measure`, `measure_price`,
    `amount_min`, `amount_max`, `penalty_amount`, `penalty_percent`,
    `penalty_type` — et **aucun n'est une duree**. `LendingPolicySchema` en a
    quatre (`loan_duration`, `reconduction_day`, `recovery_day`, `penalty_day`).

    Le terme ne pouvait donc vivre que dans le NOM du produit (« 6 Mois »),
    illisible par le code. Il est desormais une donnee, et il se materialise a la
    souscription dans `CollectSchema.end_date` — le seul champ temporel que
    collect-service expose.
    """

    def test_chaque_CASH_DAT_porte_un_terme(self) -> None:
        dat = [p for p in CATALOGUE_COLLECT if p.policy_type is PolicyType.CASH_DAT]
        assert dat, "aucun CASH_DAT : le test ne prouverait rien"
        for produit in dat:
            assert produit.duree_mois, f"{produit.nom} : depot a terme SANS terme"

    def test_le_terme_correspond_au_nom_annonce(self) -> None:
        """Un produit nomme « 6 Mois » avec un terme de 12 mentirait au bailleur."""
        for produit in CATALOGUE_COLLECT:
            if produit.duree_mois is not None:
                assert f"{produit.duree_mois} Mois" in produit.nom, produit.nom

    def test_ni_CASH_ni_PRODUCT_ne_portent_de_terme(self) -> None:
        """Une cotisation reguliere et une collecte en nature n'ont pas
        d'echeance : leur en donner une fabriquerait une fausse Collect."""
        for produit in CATALOGUE_COLLECT:
            if produit.policy_type is not PolicyType.CASH_DAT:
                assert produit.duree_mois is None, produit.nom

    def test_un_CASH_DAT_sans_terme_est_REFUSE_a_la_construction(self) -> None:
        """L'incoherence est refusee AVANT le reseau : product-service n'expose
        aucun `DELETE`, un produit mal forme serait definitif."""
        with pytest.raises(ValueError, match="incoherents"):
            ProduitCollecte(
                "Depot a Terme sans terme",
                PolicyType.CASH_DAT,
                ProductCategory.INDIVIDUAL,
                PolicyMeasure.KILOGRAM,
                1000.0,
                2000.0,
                5.0,
            )

    def test_un_CASH_avec_terme_est_REFUSE_aussi(self) -> None:
        with pytest.raises(ValueError, match="incoherents"):
            ProduitCollecte(
                "Cotisation avec terme",
                PolicyType.CASH,
                ProductCategory.INDIVIDUAL,
                PolicyMeasure.KILOGRAM,
                1000.0,
                2000.0,
                5.0,
                duree_mois=6,
            )

    def test_le_terme_est_retrouvable_par_nom_PREFIXE_ou_non(self) -> None:
        """`catalogue_execution` construit `ProduitSouscriptible` tantot depuis un
        payload (nom prefixe `DEMO_`), tantot depuis une fiche serveur (nom
        d'origine). Les deux doivent rendre le meme terme."""
        assert duree_mois_du_produit("Depot a Terme 6 Mois") == 6
        assert duree_mois_du_produit(f"{PREFIXE_DONNEES}Depot a Terme 6 Mois") == 6
        assert duree_mois_du_produit(f"{PREFIXE_DONNEES}Depot a Terme Entreprise 12 Mois") == 12

    def test_un_produit_sans_terme_rend_None_et_ne_leve_pas(self) -> None:
        assert duree_mois_du_produit("Cotisation 20000/mois") is None
        assert duree_mois_du_produit("produit inconnu") is None

    def test_le_contrat_serveur_n_accepte_TOUJOURS_pas_de_duree(self) -> None:
        """Le jour ou product-service ajoutera un champ de terme, ce test tombera
        et il faudra le declarer cote serveur plutot que seulement chez nous."""
        for payload in payloads_collect():
            policy = payload["policy"]
            interdits = [c for c in policy if any(
                k in c.lower() for k in ("dur", "day", "matur", "term", "end")
            )]
            assert interdits == [], (
                f"{payload['name']} : {interdits} — le contrat mesure le 12/08 "
                "n'acceptait aucun champ de duree en COLLECT"
            )
