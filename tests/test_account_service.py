"""
tests/test_account_service.py
=============================
`D-ACC-1` a `D-ACC-4` — les disciplines de l'audit monetaire du 08/08.

Elles vivaient dans `docs/empirical/2026-08-08_flux_monetaires.md` seulement.
**Une connaissance qui reste dans un rapport ne protege rien.**
"""

from __future__ import annotations

from typing import Any

import pytest

from app.clients.account_service import AccountServiceClient


class _Reponse:
    def __init__(self, data: Any) -> None:
        self.data = data


def _client(lignes: Any) -> AccountServiceClient:
    client = AccountServiceClient.__new__(AccountServiceClient)

    class _Transport:
        async def get(self, chemin: str, **_: Any) -> _Reponse:
            return _Reponse(lignes)

    client._client = _Transport()  # type: ignore[assignment]
    return client


class TestFraisNuls:
    """`D-ACC-3` — la parade retenue par l'audit, enfin executable.

    `ANO-ACC-FEES-07` : un DEBIT de 500 sur un type a 100 de frais retire
    **400**. Les frais sont retranches du montant demande et credites NULLE
    PART — verifie sur les 56 comptes.
    """

    @pytest.mark.asyncio
    async def test_un_type_sans_frais_passe(self) -> None:
        client = _client([{"type": "WITHDRAWAL", "fees": 0}])
        await client.verifier_frais_nuls(["WITHDRAWAL"])

    @pytest.mark.asyncio
    async def test_un_type_a_frais_est_REFUSE(self) -> None:
        """Mieux vaut refuser que produire un grand livre qui ne s'equilibre
        pas : aucun compte ne porterait la difference."""
        client = _client([{"type": "TAXE", "fees": 100}])
        with pytest.raises(ValueError, match="frais non nuls"):
            await client.verifier_frais_nuls(["TAXE"])

    @pytest.mark.asyncio
    async def test_un_montant_de_frais_illisible_est_traite_comme_PROHIBITIF(self) -> None:
        """`D-ACC-1` interdit de presumer. Un inconnu n'est pas un zero."""
        client = _client([{"type": "TAXE", "fees": "??"}])
        with pytest.raises(ValueError, match="frais non nuls"):
            await client.verifier_frais_nuls(["TAXE"])

    @pytest.mark.asyncio
    async def test_la_table_est_relue_a_chaque_campagne_jamais_mise_en_cache(self) -> None:
        """`transaction-configs` est modifiable par API — `TAXE` l'a ete le
        28/07. Ce qui etait sans frais hier peut ne plus l'etre."""
        client = _client([{"transaction_type": "deposit", "amount": 0}])
        table = await client.frais_par_type()
        assert table == {"DEPOSIT": 0.0}
        assert await client.frais_par_type() == table  # relu, pas memorise

    @pytest.mark.asyncio
    async def test_un_type_absent_de_la_table_ne_bloque_pas(self) -> None:
        """Absent de `transaction-configs` = aucun frais configure. C'est le
        cas de la majorite des types."""
        client = _client([])
        await client.verifier_frais_nuls(["WITHDRAWAL", "DEPOSIT"])
