"""
tests/test_relecture.py
=======================
Le DIFF payload <-> relecture (16/08) — banc du service PUR, sans HTTP ni
Mongo : la mecanique de comparaison merite ses preuves a elle, les routes
prouvent ensuite le CABLAGE (test_admin_api).
"""

from __future__ import annotations

from app.services.relecture import comparer_payload_relecture


class TestComparerPayloadRelecture:
    def test_fidele_quand_chaque_champ_envoye_se_relit_a_l_identique(self) -> None:
        """Les champs AJOUTES par le serveur (_id, timestamps) ne sont pas des
        divergences — le diff est ORIENTE payload -> relu."""
        verdict = comparer_payload_relecture(
            {"name": "DEMO_X", "currency": "XAF"},
            {"_id": "abc", "created_at": "2026-08-16", "name": "DEMO_X", "currency": "XAF"},
        )
        assert verdict["fidele"] is True
        assert verdict["champs_compares"] == 2
        assert verdict["divergences"] == {}
        assert verdict["absents_de_la_relecture"] == []

    def test_une_divergence_porte_les_DEUX_valeurs_en_face(self) -> None:
        verdict = comparer_payload_relecture(
            {"name": "DEMO_Tontine"}, {"name": "demo_tontine"}
        )
        assert verdict["fidele"] is False
        assert verdict["divergences"]["name"] == {
            "envoye": "DEMO_Tontine",
            "relu": "demo_tontine",
        }
        assert "EXISTE" in verdict["verdict"], (
            "une divergence n'invalide JAMAIS la creation — elle se dit"
        )

    def test_un_champ_perdu_a_la_persistance_est_dit_ABSENT(self) -> None:
        """Le cas FRA-199 : depositary-service perd `currency` a la
        persistance — la fiche relue ne porte plus le champ envoye."""
        verdict = comparer_payload_relecture(
            {"name": "DEMO_Kiosque Bonapriso", "currency": "XAF", "company_id": "cid"},
            {"_id": "dep-1", "name": "DEMO_Kiosque Bonapriso", "company_id": "cid"},
        )
        assert verdict["fidele"] is False
        assert verdict["absents_de_la_relecture"] == ["currency"]
        assert verdict["divergences"] == {}

    def test_l_egalite_est_de_VALEUR_jamais_de_type_pour_les_nombres(self) -> None:
        """La lecon de l'empreinte D-10 : le serveur rend 3.0 pour un 3."""
        verdict = comparer_payload_relecture(
            {"montant": 3, "taux": 5.0}, {"montant": 3.0, "taux": 5}
        )
        assert verdict["fidele"] is True

    def test_un_booleen_devenu_nombre_est_une_divergence(self) -> None:
        """`True == 1` en Python — mais un serveur qui rend `1` pour `true`
        a change la NATURE du champ, et ca se dit."""
        verdict = comparer_payload_relecture({"actif": True}, {"actif": 1})
        assert verdict["fidele"] is False
        assert "actif" in verdict["divergences"]

    def test_les_listes_scalaires_se_comparent_en_CONTENU(self) -> None:
        """L'ordre des permissions ou des sectors appartient au serveur."""
        verdict = comparer_payload_relecture(
            {"permissions": ["B", "A", "C"]}, {"permissions": ["A", "C", "B"]}
        )
        assert verdict["fidele"] is True
        manque = comparer_payload_relecture(
            {"permissions": ["A", "B"]}, {"permissions": ["A"]}
        )
        assert manque["fidele"] is False
        assert "permissions" in manque["divergences"]

    def test_les_dictionnaires_imbriques_deviennent_des_chemins_pointes(self) -> None:
        """`policy.measure` se lit champ par champ — jamais un `!=` global qui
        dirait seulement « quelque chose differe »."""
        verdict = comparer_payload_relecture(
            {"policy": {"measure": "KILOGRAM", "measure_price": 250.0}},
            {"policy": {"measure": "LITER", "measure_price": 250}},
        )
        assert verdict["fidele"] is False
        assert list(verdict["divergences"]) == ["policy.measure"]
        assert verdict["champs_compares"] == 2

    def test_un_sous_document_entier_absent_liste_ses_chemins(self) -> None:
        verdict = comparer_payload_relecture(
            {"address": {"city": "Douala", "country": "CM"}}, {"_id": "x"}
        )
        assert verdict["absents_de_la_relecture"] == [
            "address.city",
            "address.country",
        ]
