"""Invariants identity-service, portes cote Loader — Sprint 2.

Le 9e et dernier client du perimetre. Il ne sert PAS a l'onboarding des 2000
clients — `POST /clients/onboard` cascade lui-meme — mais aux Users que le
Loader cree explicitement : les 60 a 100 staff et l'Admin de chaque Company.

Ce service n'expose **aucun DELETE**. Une Identity absurde y resterait a vie.
Les barrieres sont donc AVANT le reseau, et testees ici sans reseau.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.clients.identity_service import (
    CHAMPS_ADRESSE_OBLIGATOIRES,
    InvariantViole,
    _en_datetime,
)


def adresse(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "address_line_1": "Rue 12",
        "street_name": "Akwa",
        "city": "Douala",
        "region": "Littoral",
        "country": "CM",
        "latitude": 4.05,
        "longitude": 9.7,
    }
    base.update(over)
    return base


class TestAdresseComplete:
    """D-IDN-2 — `country`, `city` et `region` sont OPTIONNELS au contrat et
    persistes a `null` quand on les omet (mesure 09/08). Nous disposons du
    referentiel : un champ vide serait une perte de richesse, pas une fatalite.
    """

    def test_les_cinq_champs_sont_exiges(self) -> None:
        assert CHAMPS_ADRESSE_OBLIGATOIRES == (
            "address_line_1",
            "street_name",
            "city",
            "region",
            "country",
        )

    def test_une_adresse_complete_passe(self) -> None:
        from app.core.invariants import exiger_champs_renseignes

        exiger_champs_renseignes(adresse(), CHAMPS_ADRESSE_OBLIGATOIRES)

    @pytest.mark.parametrize("manquant", ["city", "region", "country"])
    def test_un_champ_geographique_vide_est_refuse(self, manquant: str) -> None:
        from app.core.invariants import exiger_champs_renseignes

        with pytest.raises(InvariantViole, match=manquant):
            exiger_champs_renseignes(adresse(**{manquant: None}), CHAMPS_ADRESSE_OBLIGATOIRES)


class TestFormatDateTime:
    """Le contrat declare `date_of_birth` et `id_expire_on` en `date-time`, nos
    invariants manipulent des `date`. La conversion se fait une seule fois."""

    @pytest.mark.parametrize(
        "entree,attendu",
        [
            ("1995-04-12", "1995-04-12T00:00:00"),
            ("2030-01-01T00:00:00", "2030-01-01T00:00:00"),
        ],
    )
    def test_conversion(self, entree: str, attendu: str) -> None:
        assert _en_datetime(entree) == attendu

    def test_une_date_deja_horodatee_n_est_pas_doublee(self) -> None:
        assert _en_datetime("2030-01-01T08:30:00").count("T") == 1
