"""
tests/test_clients.py
=====================
Le socle HTTP commun aux neuf clients — `app/clients/base.py`.
"""

from __future__ import annotations

import pytest


class TestPlafondDeConcurrence:
    """`D-USR-1` — le plafond doit etre GLOBAL, et il ne l'etait pas.

    Chaque client construisait son propre semaphore : neuf clients x 25 =
    jusqu'a 225 requetes simultanees, quand la mesure (`H14`/`H15`) donne 30
    pour maximum. Le plafond existait dans le code et pas dans les faits.
    """

    def test_une_seule_source_pour_le_plafond(self) -> None:
        """Il vivait en double — 20 dans l'orchestrateur, 25 dans le transport.
        Un plafond declare deux fois n'est pas un plafond, c'est une opinion."""
        from app.clients.base import MAX_CONCURRENCE
        from app.services.orchestrateur import PLAFOND_WORKERS

        assert PLAFOND_WORKERS is MAX_CONCURRENCE

    def test_le_plafond_est_la_borne_basse_du_domaine_mesure(self) -> None:
        """20 a 30 workers, degradation SILENCIEUSE au-dela. On ne s'approche
        pas du bord d'une falaise invisible."""
        from app.clients.base import MAX_CONCURRENCE

        assert MAX_CONCURRENCE == 20

    @pytest.mark.asyncio
    async def test_tous_les_clients_partagent_le_meme_semaphore(self) -> None:
        """Ce sont les services FinZuu qui degradent, pas chaque route prise
        isolement. La contrainte est globale, le garde-fou doit l'etre aussi."""
        from app.clients.base import semaphore_partage

        assert semaphore_partage() is semaphore_partage()

    def test_chaque_boucle_a_le_sien(self) -> None:
        """Un semaphore construit sur une boucle morte leve `RuntimeError` a
        l'acquisition — chaque boucle doit donc avoir le sien."""
        import asyncio

        assert asyncio.run(_semaphore()) is not asyncio.run(_semaphore())

    def test_l_entree_disparait_avec_la_boucle(self) -> None:
        """`WeakKeyDictionary`, pas `id(boucle)` : CPython reutilise les
        adresses. Une nouvelle boucle heriterait du semaphore d'une morte —
        a moitie epuise, sans que rien ne le signale."""
        import asyncio
        import gc

        from app.clients.base import _SEMAPHORES

        asyncio.run(_semaphore())
        gc.collect()
        assert len(_SEMAPHORES) == 0


async def _semaphore() -> object:
    from app.clients.base import semaphore_partage

    return semaphore_partage()
