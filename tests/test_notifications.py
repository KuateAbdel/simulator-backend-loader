"""
tests/test_notifications.py
===========================
Systeme de NOTIFICATION + TRACABILITE des connexions (demande boss, 20/08).

Doctrine « comme Microsoft » : evenement -> resolution des destinataires PAR
ROLE (les Super-Admins) -> canaux (in-app toujours, email si sensible). Regle
d'or testee ici : informer ne casse JAMAIS l'action qui le declenche — Mailjet
n'est pas provisionne dans ces tests et tout doit passer quand meme.

Base de donnees : une base MongoDB DEDIEE (`loader_finzuu_tests_notifs`),
nettoyee a chaque test — jamais la base de developpement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.core import database
from app.core.config import settings
from app.main import app
from app.repositories.notifications import NotificationRepository
from app.repositories.super_admin import SuperAdminRepository

#: L'ACTEUR des gestes — le pilote connecte (bootstrap super_admin).
EMAIL = "pilote-notifs@finzuu.com"
#: Un SECOND Super-Admin actif — l'audience attendue des notifications.
COLLEGUE = "collegue-notifs@finzuu.com"
MDP_INITIAL = "initial-bootstrap-9911"
MDP_DURABLE = "cheval-agrafe-batterie-13aout"


@pytest_asyncio.fixture()
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """API + base dediee + DEUX Super-Admins (l'acteur et son audience)."""
    monkeypatch.setattr(settings, "mongodb_database", "loader_finzuu_tests_notifs")
    database.connect()
    db = database.get_database()
    await db.drop_collection(database.COLLECTION_SUPER_ADMIN_ACCOUNTS)
    await db.drop_collection(database.COLLECTION_AUTH_THROTTLE)
    await db.drop_collection(database.COLLECTION_NOTIFICATIONS)
    await db.drop_collection(database.COLLECTION_AUDIT_TRAIL)
    depot = SuperAdminRepository()
    await depot.creer(EMAIL, MDP_INITIAL, role="super_admin")
    await depot.creer(COLLEGUE, MDP_INITIAL, role="super_admin")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    database.close()


async def _session_complete(
    client: httpx.AsyncClient, email: str = EMAIL, mdp_initial: str = MDP_INITIAL
) -> dict[str, str]:
    """Login initial + changement de mot de passe force -> jeton plein."""
    reponse = await client.post(
        "/admin/auth/login", json={"email": email, "mot_de_passe": mdp_initial}
    )
    assert reponse.status_code == 200, reponse.text
    jeton_initial = reponse.json()["access_token"]
    reponse = await client.post(
        "/admin/auth/password",
        json={"ancien": mdp_initial, "nouveau": MDP_DURABLE},
        headers={"Authorization": f"Bearer {jeton_initial}"},
    )
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


async def _boite(destinataire: str) -> list[Any]:
    """La boite d'un compte, lue au depot — l'etat BRUT, sans passer l'API."""
    return await NotificationRepository().lister(destinataire)


# ---------------------------------------------------------------------------
# Les EVENEMENTS notifient — la resolution par role
# ---------------------------------------------------------------------------


class TestEvenementsNotifient:
    async def test_compte_cree_notifie_les_autres_super_admins_jamais_lacteur(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/comptes",
            json={"email": "recrue-notifs@finzuu.com", "role": "viewer"},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text

        notifs_collegue = await _boite(COLLEGUE)
        assert len(notifs_collegue) == 1
        notif = notifs_collegue[0]
        assert notif.type == "compte_cree"
        assert notif.donnees["email"] == "recrue-notifs@finzuu.com"
        assert notif.donnees["acteur"] == EMAIL
        assert notif.lu is False
        # L'acteur ne se notifie pas lui-meme.
        assert await _boite(EMAIL) == []

    async def test_role_change_notifie_aussi_la_personne_visee_sans_doublon(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.put(
            f"/admin/comptes/{COLLEGUE}/role", json={"role": "admin"}, headers=entetes
        )
        assert reponse.status_code == 200, reponse.text

        # Le collegue est A LA FOIS Super-Admin (audience) et vise : UNE
        # notification, pas deux — la livraison dedoublonne.
        notifs = await _boite(COLLEGUE)
        assert len(notifs) == 1
        assert notifs[0].type == "role_change"
        assert notifs[0].donnees["role"] == "admin"

    async def test_compte_desactive_notifie_meme_sans_email_provisionne(
        self, client: httpx.AsyncClient
    ) -> None:
        """Geste sensible = in-app + email. Mailjet N'EST PAS provisionne ici :
        l'action reussit ET l'in-app arrive quand meme (informer ne casse rien,
        le canal email rend simplement False)."""
        entetes = await _session_complete(client)
        await SuperAdminRepository().creer("cible-notifs@finzuu.com", MDP_INITIAL)
        reponse = await client.put(
            "/admin/comptes/cible-notifs@finzuu.com/etat",
            json={"actif": False, "motif": "depart de l'equipe"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text

        notifs = await _boite(COLLEGUE)
        assert [n.type for n in notifs] == ["compte_desactive"]
        assert notifs[0].donnees["motif"] == "depart de l'equipe"

    async def test_compte_reactive_notifie_in_app(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        depot = SuperAdminRepository()
        await depot.creer("cible-notifs@finzuu.com", MDP_INITIAL)
        await depot.changer_etat("cible-notifs@finzuu.com", actif=False)
        reponse = await client.put(
            "/admin/comptes/cible-notifs@finzuu.com/etat",
            json={"actif": True, "motif": "retour de conge"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        assert [n.type for n in await _boite(COLLEGUE)] == ["compte_reactive"]

    async def test_les_roles_admin_et_viewer_ne_sont_pas_dans_laudience(
        self, client: httpx.AsyncClient
    ) -> None:
        """L'audience des gestes sensibles = les SUPER-ADMINS actifs. Un admin
        ou un viewer ne la rejoint pas ; un Super-Admin DESACTIVE non plus."""
        entetes = await _session_complete(client)
        depot = SuperAdminRepository()
        await depot.creer("observateur-notifs@finzuu.com", MDP_INITIAL, role="viewer")
        await depot.creer("gestionnaire-notifs@finzuu.com", MDP_INITIAL, role="admin")
        await depot.creer("dormant-notifs@finzuu.com", MDP_INITIAL, role="super_admin")
        await depot.changer_etat("dormant-notifs@finzuu.com", actif=False)

        reponse = await client.post(
            "/admin/comptes",
            json={"email": "recrue-notifs@finzuu.com", "role": "viewer"},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text

        assert len(await _boite(COLLEGUE)) == 1  # le seul autre super_admin ACTIF
        for exclu in (
            "observateur-notifs@finzuu.com",
            "gestionnaire-notifs@finzuu.com",
            "dormant-notifs@finzuu.com",
        ):
            assert await _boite(exclu) == [], f"{exclu} ne devait rien recevoir"


# ---------------------------------------------------------------------------
# La BOITE — endpoints in-app, chacun ne voit que les SIENNES
# ---------------------------------------------------------------------------


class TestBoiteNotifications:
    async def test_lister_rend_les_miennes_avec_le_compteur_de_non_lues(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        depot = NotificationRepository()
        await depot.creer(EMAIL, "compte_cree", {"email": "a@finzuu.com"})
        await depot.creer(EMAIL, "role_change", {"email": "b@finzuu.com"})
        await depot.creer(COLLEGUE, "compte_cree", {"email": "c@finzuu.com"})

        reponse = await client.get("/admin/notifications", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["non_lues"] == 2
        assert len(corps["notifications"]) == 2, "jamais celles d'un autre"
        assert {n["type"] for n in corps["notifications"]} == {
            "compte_cree",
            "role_change",
        }
        # La vue publique porte tout ce que le rendu localise exige.
        premiere = corps["notifications"][0]
        assert set(premiere) == {"id", "type", "donnees", "lu", "quand"}

    async def test_compteur_de_la_cloche(self, client: httpx.AsyncClient) -> None:
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/notifications/non-lues", headers=entetes)
        assert reponse.status_code == 200
        assert reponse.json() == {"non_lues": 0}
        await NotificationRepository().creer(EMAIL, "compte_cree", {})
        reponse = await client.get("/admin/notifications/non-lues", headers=entetes)
        assert reponse.json() == {"non_lues": 1}

    async def test_marquer_lu_puis_tout_lu(self, client: httpx.AsyncClient) -> None:
        entetes = await _session_complete(client)
        depot = NotificationRepository()
        premiere = await depot.creer(EMAIL, "compte_cree", {})
        await depot.creer(EMAIL, "role_change", {})
        await depot.creer(EMAIL, "compte_reactive", {})

        reponse = await client.put(
            f"/admin/notifications/{premiere.id}/lu", headers=entetes
        )
        assert reponse.status_code == 200
        assert await depot.compter_non_lues(EMAIL) == 2

        reponse = await client.put("/admin/notifications/tout-lu", headers=entetes)
        assert reponse.status_code == 200
        assert reponse.json() == {"marquees": 2}
        assert await depot.compter_non_lues(EMAIL) == 0
        # Rien ne se supprime : la boite garde ses 3 entrees, lues.
        assert len(await _boite(EMAIL)) == 3

    async def test_marquer_lu_la_notification_dun_autre_404(
        self, client: httpx.AsyncClient
    ) -> None:
        """La boite est bornee au proprietaire : marquer la notification d'un
        AUTRE compte est un 404 — elle n'existe pas pour moi."""
        entetes = await _session_complete(client)
        autre = await NotificationRepository().creer(COLLEGUE, "compte_cree", {})
        reponse = await client.put(
            f"/admin/notifications/{autre.id}/lu", headers=entetes
        )
        assert reponse.status_code == 404
        assert (await _boite(COLLEGUE))[0].lu is False, "la sienne reste non lue"

    async def test_boite_accessible_a_un_viewer(
        self, client: httpx.AsyncClient
    ) -> None:
        """Recevoir n'est pas un privilege : la boite est ouverte a TOUT compte
        authentifie (Viewer+), seul le DECLENCHEMENT depend du role."""
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/comptes",
            json={"email": "observateur-notifs@finzuu.com", "role": "viewer"},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        initial = reponse.json()["mot_de_passe_initial"]
        entetes_viewer = await _session_complete(
            client, "observateur-notifs@finzuu.com", initial
        )
        reponse = await client.get("/admin/notifications", headers=entetes_viewer)
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["notifications"] == []

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.get("/admin/notifications")
        assert reponse.status_code == 401


# ---------------------------------------------------------------------------
# TRACABILITE des connexions — le Journal + la fiche
# ---------------------------------------------------------------------------


class TestTraceConnexion:
    async def test_login_inscrit_une_ligne_session_au_journal(
        self, client: httpx.AsyncClient
    ) -> None:
        """Chaque connexion reussie ecrit une intention `Session/LOGIN` resolue
        en SUCCES sous RUN_ADMIN — c'est elle que l'onglet Journal affiche."""
        await _session_complete(client)
        journal = database.get_database()[database.COLLECTION_AUDIT_TRAIL]
        intention = await journal.find_one(
            {"entity_type": "Session", "action": "INTENTION"}
        )
        assert intention is not None, "la connexion doit laisser une trace"
        assert intention["after"]["operation"] == "LOGIN"
        assert intention["after"]["payload"]["par"] == EMAIL
        assert intention["after"]["payload"]["role"] == "super_admin"
        resultat = await journal.find_one(
            {"entity_type": "Session", "action": "RESULTAT"}
        )
        assert resultat is not None
        assert resultat["after"]["statut"] == "SUCCES"

    async def test_login_echoue_ne_trace_pas_de_session(
        self, client: httpx.AsyncClient
    ) -> None:
        """Le refus 401 ne fabrique PAS de ligne Session : le Journal trace les
        connexions ETABLIES (les echecs, eux, nourrissent le throttle)."""
        reponse = await client.post(
            "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": "faux"}
        )
        assert reponse.status_code == 401
        journal = database.get_database()[database.COLLECTION_AUDIT_TRAIL]
        assert await journal.find_one({"entity_type": "Session"}) is None

    async def test_derniere_connexion_remontee_dans_la_fiche(
        self, client: httpx.AsyncClient
    ) -> None:
        """`derniere_connexion` est posee au login et VISIBLE dans la fiche du
        compte (ecran Utilisateurs) ; un compte jamais connecte porte None."""
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/comptes", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        fiches = {c["email"]: c for c in reponse.json()["comptes"]}
        assert fiches[EMAIL]["derniere_connexion"] is not None
        assert fiches[COLLEGUE]["derniere_connexion"] is None, "jamais connecte"
