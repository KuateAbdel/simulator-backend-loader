"""Le flow de creation d'un User applicatif — `user_service.py`.

Ce que ces tests figent est un ARBITRAGE, pas une mecanique : `register` est
L'ENGAGEMENT (le User existe, user-service n'a aucun `DELETE`), tout ce qui
suit est de la FINITION. Le Loader ne perd jamais un objet deja cree pour une
finition ratee.

L'arbitrage a ete pris le 15/09/2026, apres le run REAL `56f28cf0` : les 81
`password/f/change` avaient echoue (`FRA-247`), le module avait rendu « Staff
cree : 0 » et `FAILED` — et 81 Users existaient bel et bien chez FinZuu, sans
noeud chez nous ni rattachement Agent -> Kiosque.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.clients.base import ErreurService, ReponseServeur
from app.clients.contracts import UserType
from app.clients.user_service import UserServiceClient


class TransportDouble:
    """Remplace `ClientFinZuu` : enregistre les appels, rend des reponses figees."""

    def __init__(self, *, echec_finition: bool = False, sans_auth_token: bool = False) -> None:
        self.appels: list[tuple[str, str]] = []
        self._echec_finition = echec_finition
        self._sans_auth_token = sans_auth_token

    async def requete(self, methode: str, chemin: str, **_: Any) -> ReponseServeur:
        self.appels.append((methode, chemin))
        if chemin.endswith("/auth/register"):
            data: dict[str, Any] = {"user": {"id": "u-1", "user_name": "CM_Agent_000"}}
            if not self._sans_auth_token:
                data["auth_token"] = "jeton-auth-10min"  # noqa: S105 — doublure de test
            return ReponseServeur(
                status_code=201, response_type="Created", description="ok", data=data
            )
        if chemin.endswith("/auth/password/f/change"):
            if self._echec_finition:
                # `FRA-247`, mot pour mot ce que le serveur rend depuis le 15/09.
                raise ErreurService(
                    "user-service",
                    "PUT",
                    "/api/v1/auth/password/f/change",
                    401,
                    "Current password is incorrect",
                    "-",
                )
            return ReponseServeur(status_code=200, response_type="OK", description="ok", data={})
        raise AssertionError(f"appel inattendu : {methode} {chemin}")


def _client(transport: TransportDouble) -> UserServiceClient:
    client = UserServiceClient()
    client._client = transport  # type: ignore[assignment]
    return client


async def _creer(transport: TransportDouble) -> dict[str, Any]:
    return await _client(transport).creer_utilisateur_applicatif(
        user_name="CM_Agent_000",
        email="demo.staff.cm.age000@finzuu-demo.local",
        mot_de_passe_initial="Init#2026Aa",
        nouveau_mot_de_passe="Stf#CM0000Aa",
        identity_id=uuid4(),
        type_user=UserType.STAFF,
        groupes=["Agent"],
    )


@pytest.mark.asyncio
class TestFlowDeCreation:
    async def test_le_login_de_verification_est_supprime(self) -> None:
        """Il ne servait a rien — aucun appelant ne lisait son jeton — et il
        coutait un login par compte sur un service qui verrouille a la
        troisieme tentative (`INV-USR-19`)."""
        transport = TransportDouble()
        await _creer(transport)

        chemins = [c for _, c in transport.appels]
        assert not any(c.endswith("/auth/login") for c in chemins)
        assert chemins == ["/api/v1/auth/register", "/api/v1/auth/password/f/change"]

    async def test_le_nominal_rend_le_user_et_une_finition_aboutie(self) -> None:
        utilisateur = await _creer(TransportDouble())

        assert utilisateur["id"] == "u-1"
        assert utilisateur["finition"] == {"aboutie": True, "motif": ""}

    async def test_une_finition_refusee_ne_leve_pas(self) -> None:
        """`FRA-247` — le coeur de l'arbitrage. Lever ici faisait disparaitre
        du rapport un User qui EXISTE sur une plateforme sans `DELETE`."""
        utilisateur = await _creer(TransportDouble(echec_finition=True))

        assert utilisateur["id"] == "u-1", "l'identifiant du User cree est conserve"
        assert utilisateur["finition"]["aboutie"] is False
        assert "Current password is incorrect" in utilisateur["finition"]["motif"]
        assert "401" in utilisateur["finition"]["motif"]

    async def test_un_auth_token_absent_est_une_finition_ratee_pas_une_erreur(self) -> None:
        """Sans `auth_token`, l'etape 2 est impossible — mais le User est deja
        cree. Avant le 15/09 ce cas levait, et l'effacait du rapport."""
        transport = TransportDouble(sans_auth_token=True)
        utilisateur = await _creer(transport)

        assert utilisateur["id"] == "u-1"
        assert utilisateur["finition"]["aboutie"] is False
        assert "auth_token absent" in utilisateur["finition"]["motif"]
        assert [c for _, c in transport.appels] == ["/api/v1/auth/register"]

    async def test_un_echec_de_register_leve_toujours(self) -> None:
        """L'etape 1 est L'ENGAGEMENT : si elle echoue, rien n'existe, et
        l'appelant doit le savoir. La tolerance s'arrete a la finition."""

        class RegisterRefuse(TransportDouble):
            async def requete(self, methode: str, chemin: str, **_: Any) -> ReponseServeur:
                raise ErreurService(
                    "user-service", "POST", "/api/v1/auth/register", 400, "refuse", "-"
                )

        with pytest.raises(ErreurService):
            await _creer(RegisterRefuse())
