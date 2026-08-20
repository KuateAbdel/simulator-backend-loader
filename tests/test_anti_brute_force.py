"""
tests/test_anti_brute_force.py
==============================
Invariant I-AUTH-11 — le login est protege du brute-force par un backoff
exponentiel AUTO-CICATRISANT, JAMAIS par un verrou dur du compte (ce serait
CWE-645 : deni de service sur l'utilisateur legitime, atteinte a la
Disponibilite du CIA).

Tests PURS de la loi de cooldown : sans base, sans reseau.
"""

from __future__ import annotations

from app.repositories.auth_throttle import (
    BASE_SECONDES,
    PLAFOND_SECONDES,
    SEUIL_SANS_DELAI,
    cooldown_pour,
)


class TestLoiDeCooldown:
    def test_aucun_delai_sous_le_seuil(self) -> None:
        """La faute de frappe honnete ne coute rien : 0s jusqu'au seuil."""
        for echecs in range(SEUIL_SANS_DELAI + 1):
            assert cooldown_pour(echecs) == 0.0

    def test_premier_cran_apres_le_seuil(self) -> None:
        assert cooldown_pour(SEUIL_SANS_DELAI + 1) == BASE_SECONDES

    def test_backoff_exponentiel(self) -> None:
        assert cooldown_pour(SEUIL_SANS_DELAI + 2) == BASE_SECONDES * 2
        assert cooldown_pour(SEUIL_SANS_DELAI + 3) == BASE_SECONDES * 4

    def test_monotone_croissant(self) -> None:
        precedent = -1.0
        for echecs in range(SEUIL_SANS_DELAI + 1, SEUIL_SANS_DELAI + 40):
            actuel = cooldown_pour(echecs)
            assert actuel >= precedent
            precedent = actuel

    def test_plafonne(self) -> None:
        """Meme sous attaque soutenue, l'attente reste bornee (Disponibilite)."""
        assert cooldown_pour(1000) == PLAFOND_SECONDES
