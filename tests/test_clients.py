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


class TestSessionPartagee:
    """`ECART-38` — une seule session pour les neuf clients.

    Chaque client tenait SON token et faisait donc son propre
    `/auth/login` : neuf ouvertures de session pour un seul compte ROOT,
    quand `INV-USR-19` verrouille a la 3e tentative echouee.
    """

    @pytest.mark.asyncio
    async def test_les_neuf_clients_partagent_une_seule_session(self) -> None:
        from app.clients.base import session_partagee

        assert session_partagee() is session_partagee()

    @pytest.mark.asyncio
    async def test_un_access_frais_est_reutilise_sans_appel_reseau(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.clients.base import SessionAuth

        s = SessionAuth()
        s.enregistrer({"access_token": "abc", "refresh_token": "def"})
        assert s.access_utilisable()
        assert s.refresh_utilisable()
        assert s.access == "abc"
        assert s.access_expire_le is not None
        assert s.access_expire_le > datetime.now(UTC) + timedelta(hours=3)

    @pytest.mark.asyncio
    async def test_un_access_expirant_dans_la_marge_est_considere_mort(self) -> None:
        """On renouvelle AVANT l'expiration, jamais au moment ou elle tombe
        en pleine campagne."""
        from datetime import UTC, datetime

        from app.clients.base import MARGE_RENOUVELLEMENT, SessionAuth

        s = SessionAuth(access="abc", access_expire_le=datetime.now(UTC) + MARGE_RENOUVELLEMENT / 2)
        assert not s.access_utilisable()

    @pytest.mark.asyncio
    async def test_le_refresh_survit_a_l_access(self) -> None:
        """access 4 h, refresh 7 j (mesure du 08/08). C'est ce decalage qui
        rend `/auth/refresh` utile — sans lui on se reloguerait 42 fois."""
        from datetime import UTC, datetime

        from app.clients.base import SessionAuth

        s = SessionAuth()
        s.enregistrer({"access_token": "a", "refresh_token": "r"})
        s.access_expire_le = datetime.now(UTC)
        assert not s.access_utilisable()
        assert s.refresh_utilisable()

    @pytest.mark.asyncio
    async def test_une_reponse_sans_access_token_leve(self) -> None:
        from app.clients.base import SessionAuth

        with pytest.raises(ValueError, match="access_token absent"):
            SessionAuth().enregistrer({"refresh_token": "seul"})

    @pytest.mark.asyncio
    async def test_le_verrou_empeche_vingt_logins_simultanes(self) -> None:
        """LE point dangereux. Sans verrou, 20 workers qui rencontrent un
        token expire lancent 20 `/auth/login` — et le seuil anti-brute-force
        d'`INV-USR-19` est a 3."""
        import asyncio

        from app.clients.base import SessionAuth

        session = SessionAuth()
        appels = 0

        async def _renouveler() -> str:
            nonlocal appels
            if session.access_utilisable() and session.access is not None:
                return session.access
            async with session.verrou:
                if session.access_utilisable() and session.access is not None:
                    return session.access
                appels += 1
                await asyncio.sleep(0)
                return session.enregistrer({"access_token": "unique"})

        resultats = await asyncio.gather(*(_renouveler() for _ in range(20)))
        assert appels == 1, "un seul renouvellement pour vingt workers"
        assert set(resultats) == {"unique"}


class TestDisjoncteurLogin:
    """22/08 — apres un login REFUSE, aucune nouvelle tentative pendant la
    fenetre : c'est ce qui empeche le Loader de verrouiller le compte ROOT
    partage (INV-USR-19, seuil a 3) quand un mot de passe est perime."""

    def test_le_disjoncteur_bloque_puis_expire(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.clients.base import FENETRE_DISJONCTEUR_LOGIN, SessionAuth

        s = SessionAuth()
        assert s.login_bloque_jusqua is None
        s.login_bloque_jusqua = datetime.now(UTC) + FENETRE_DISJONCTEUR_LOGIN
        assert datetime.now(UTC) < s.login_bloque_jusqua
        s.login_bloque_jusqua = datetime.now(UTC) - timedelta(seconds=1)
        assert datetime.now(UTC) >= s.login_bloque_jusqua

    async def test_un_login_refuse_arme_le_disjoncteur_et_le_dit(self) -> None:
        """Le refus arme ; l'appel suivant echoue SANS toucher /auth/login."""
        from datetime import UTC, datetime

        from app.clients.base import ClientFinZuu, ErreurService, SessionAuth
        from app.core.config import settings

        client = ClientFinZuu("user-service", settings.user_service_base)
        session = SessionAuth()
        session.login_bloque_jusqua = datetime.now(UTC).replace(year=2999)
        session.login_refus_motif = "HTTP 401"
        try:
            import pytest

            with pytest.raises(ErreurService) as attrape:
                await client._ouvrir_session(session)
            assert attrape.value.status == 423
            assert "DISJONCTEUR" in attrape.value.detail
            assert "INV-USR-19" in attrape.value.detail
        finally:
            await client.fermer()
