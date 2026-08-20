"""
tests/test_politique_mot_de_passe.py
====================================
Invariant I-AUTH-9 — un mot de passe durable devinable est refuse, JAMAIS
au motif qu'un autre compte l'utiliserait (oracle interdit).

Tests PURS : la politique ne consulte aucune base, ces cas n'ont besoin
d'aucune fixture Mongo.
"""

from __future__ import annotations

import pytest

from app.core.politique_mot_de_passe import LONGUEUR_MDP_MIN, est_acceptable, evaluer


class TestMotsDePasseRefuses:
    def test_trop_court(self) -> None:
        raisons = evaluer("court")
        assert any("caracteres" in r for r in raisons)

    def test_plancher_est_douze(self) -> None:
        assert LONGUEUR_MDP_MIN == 12
        assert evaluer("a" * 11)  # 11 -> refuse
        # 12 caracteres mais mono-caractere : refuse pour une AUTRE raison
        assert evaluer("a" * 12)

    def test_mono_caractere(self) -> None:
        assert any("repete" in r for r in evaluer("aaaaaaaaaaaaaa"))

    def test_sequence_de_touches(self) -> None:
        assert any("suite" in r for r in evaluer("abcdefghijklmno"))
        assert any("suite" in r for r in evaluer("ponmlkjihgfedcba"))  # descendante

    def test_mot_commun_meme_en_leet(self) -> None:
        # « P@ssw0rd » normalise -> « password » : attrape malgre le leet et
        # malgre les 12+ caracteres.
        assert not est_acceptable("P@ssw0rd-2026")
        assert not est_acceptable("MonAzerty-123")
        assert not est_acceptable("FinZuuLoader-42")

    def test_contient_email(self) -> None:
        raisons = evaluer("yaniv-quelque-chose-long", email="yaniv@finzuu.cm")
        assert any("email" in r for r in raisons)


class TestMotsDePasseAcceptes:
    @pytest.mark.parametrize(
        "mdp",
        [
            "un-mdp-suffisamment-long",
            "encore-un-autre-mdp-long",
            "cheval-agrafe-batterie-correcte",
            "R3d0ute-Volcan-Marmite",
        ],
    )
    def test_accepte(self, mdp: str) -> None:
        assert est_acceptable(mdp), evaluer(mdp)

    def test_pas_d_unicite_inter_comptes(self) -> None:
        """Le MEME mot de passe est acceptable pour deux personnes : la
        politique ne connait pas les autres comptes (anti-oracle)."""
        commun = "cheval-agrafe-batterie-correcte"
        assert est_acceptable(commun, email="a@finzuu.cm")
        assert est_acceptable(commun, email="b@finzuu.cm")
