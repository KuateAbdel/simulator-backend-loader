"""
tests/test_admin_api.py
=======================
Lot A de l'API Super-Admin — `US-A1`, `US-A2`, `US-A4`, `US-B5`.

Chaque test reprend un critere Gherkin du backlog (`BACKLOG_SUPER_ADMIN.md`,
page Confluence 67665922) — un critere = un test nomme. La Definition of Done
exige les comportements d'erreur : 401, 403 et 422 sont testes au meme titre
que les succes.

Base de donnees : une base MongoDB DEDIEE (`loader_finzuu_tests_api`), nettoyee
a chaque session de test — jamais la base de developpement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar

import httpx
import pytest
import pytest_asyncio

from app.core import database
from app.core.config import settings
from app.main import app
from app.repositories.super_admin import SuperAdminRepository

#: Un domaine PLAUSIBLE : email-validator refuse les TLD reserves (.test,
#: .example) — et c'est exactement la rigueur demandee. Aucun mail ne part.
EMAIL = "pilote-tests@finzuu.com"
MDP_INITIAL = "initial-bootstrap-9911"
MDP_DURABLE = "cheval-agrafe-batterie-13aout"  # conforme I-AUTH-9 (ni « passe » ni mot banni)


@pytest_asyncio.fixture()
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """API + base dediee + compte bootstrap frais (must_change_password=True)."""
    monkeypatch.setattr(settings, "mongodb_database", "loader_finzuu_tests_api")
    database.connect()
    await database.get_database().drop_collection(
        database.COLLECTION_SUPER_ADMIN_ACCOUNTS
    )
    # Isolation anti-brute-force (I-AUTH-11) : compteurs de throttle vierges a
    # chaque test, sinon les echecs d'un test declenchent le 429 du suivant.
    await database.get_database().drop_collection(database.COLLECTION_AUTH_THROTTLE)
    # Compte de bootstrap = un SUPER_ADMIN (comme app/services/bootstrap.py) :
    # le defaut fail-closed de `creer` est 'viewer', reserve aux comptes crees
    # par l'API. Le pilote initial du Loader, lui, est super_admin.
    await SuperAdminRepository().creer(EMAIL, MDP_INITIAL, role="super_admin")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    database.close()


async def _login(client: httpx.AsyncClient, mdp: str = MDP_INITIAL) -> dict[str, Any]:
    reponse = await client.post(
        "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": mdp}
    )
    assert reponse.status_code == 200, reponse.text
    return dict(reponse.json())


async def _session_complete(client: httpx.AsyncClient) -> dict[str, str]:
    """Login initial + changement de mot de passe force -> jeton plein."""
    initial = await _login(client)
    reponse = await client.post(
        "/admin/auth/password",
        json={"ancien": MDP_INITIAL, "nouveau": MDP_DURABLE},
        headers={"Authorization": f"Bearer {initial['access_token']}"},
    )
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


async def _registre_vierge() -> None:
    """Repart d'un journal vide — le registre est DERIVE du journal."""
    await database.get_database().drop_collection("audit_trail")


async def _inscrire_groupe_au_registre(groupe_id: str, nom: str) -> None:
    """Seme une creation write-ahead au journal — la forme EXACTE qu'emet
    `ExecuteurRoles._creer_journalise` en REAL. C'est ce qui rend un groupe
    « a nous » : AUCUN prefixe sur les groupes, le registre seul fait foi."""
    from uuid import uuid4

    from app.repositories.audit_trail import AuditTrailRepository
    from app.routes.admin_entites import RUN_ADMIN

    audit = AuditTrailRepository()
    async with audit.intention(
        RUN_ADMIN,
        entity_type="Group",
        entity_id=uuid4(),
        operation="CREATE",
        cible="user-service POST /api/v1/groupes/create",
        payload={"name": nom},
    ) as suivi:
        suivi.reussi({"group_id": groupe_id, "name": nom})


class TestUSA1Connexion:
    async def test_login_valide_rend_un_jeton_a_duree_limitee(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        assert session["token_type"] == "bearer"  # noqa: S105 — un type, pas un secret
        assert 0 < session["expires_in"] <= 24 * 3600
        assert session["must_change_password"] is True
        assert MDP_INITIAL not in str(session), "le mot de passe ne sort JAMAIS"

    async def test_mot_de_passe_errone_401_sans_dire_quel_champ(
        self, client: httpx.AsyncClient
    ) -> None:
        reponse = await client.post(
            "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": "faux"}
        )
        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "identifiants invalides"

    async def test_email_inconnu_rend_le_MEME_401(self, client: httpx.AsyncClient) -> None:
        """Dire « email inconnu » confirmerait l'existence des comptes."""
        reponse = await client.post(
            "/admin/auth/login",
            json={"email": "autre-inconnu@finzuu.com", "mot_de_passe": MDP_INITIAL},
        )
        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "identifiants invalides"

    async def test_un_email_INVALIDE_est_un_422_pas_un_string_accepte(
        self, client: httpx.AsyncClient
    ) -> None:
        """Exigence de Yaniv du 13/08 — la lecon des bugs de la plateforme :
        elle accepte n'importe quoi dans ses champs, PAS NOUS. Un email est un
        email (RFC), jamais un string libre."""
        for invalide in ("pas-un-email", "a@b", "@finzuu.com", "yaniv@", ""):
            reponse = await client.post(
                "/admin/auth/login",
                json={"email": invalide, "mot_de_passe": "peu importe"},
            )
            assert reponse.status_code == 422, f"{invalide!r} accepte comme email"


class TestUSA2MotDePasseForce:
    async def test_toute_route_est_403_tant_que_le_mdp_initial_survit(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        reponse = await client.get(
            "/admin/referentiels/catalogue-statique",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert reponse.status_code == 403
        assert "POST /admin/auth/password" in reponse.json()["detail"], (
            "le 403 doit indiquer le chemin de sortie"
        )

    async def test_le_changement_leve_l_obligation_DEFINITIVEMENT(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        assert (
            await client.get("/admin/referentiels/catalogue-statique", headers=entetes)
        ).status_code == 200
        # Un nouveau login n'exige plus le changement.
        session = await _login(client, MDP_DURABLE)
        assert session["must_change_password"] is False

    async def test_un_jeton_vole_ne_suffit_pas_l_ancien_mdp_est_reverifie(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        reponse = await client.post(
            "/admin/auth/password",
            json={"ancien": "pas-le-bon", "nouveau": MDP_DURABLE},
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert reponse.status_code == 401

    async def test_un_mot_de_passe_court_ou_identique_est_refuse(
        self, client: httpx.AsyncClient
    ) -> None:
        session = await _login(client)
        entetes = {"Authorization": f"Bearer {session['access_token']}"}
        court = await client.post(
            "/admin/auth/password",
            json={"ancien": MDP_INITIAL, "nouveau": "court"},
            headers=entetes,
        )
        assert court.status_code == 422
        identique = await client.post(
            "/admin/auth/password",
            json={"ancien": MDP_INITIAL, "nouveau": MDP_INITIAL},
            headers=entetes,
        )
        assert identique.status_code == 422


class TestUSA4ReinitialisationParEmail:
    """`US-A4` v2 — le reset par email (Mailjet), livre le 14/08.

    Le vrai Mailjet n'est JAMAIS appele : le client est monkeypatche par un
    faux qui capture (destinataire, sujet, texte) — le code est extrait du
    texte capture, exactement ce que ferait l'utilisateur dans sa boite.
    """

    @staticmethod
    def _provisionner(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
        monkeypatch.setattr(settings, "mailjet_api_key", "cle-de-test")
        monkeypatch.setattr(settings, "mailjet_secret_key", "secret-de-test")
        monkeypatch.setattr(settings, "mailjet_expediteur", "loader@finzuu.com")
        captures: list[tuple[str, str, str]] = []

        async def faux_envoi(destinataire: str, sujet: str, texte: str) -> bool:
            captures.append((destinataire, sujet, texte))
            return True

        # La route importe le MODULE (mailjet.envoyer_email) — on patche la
        # fonction dans le module, la route voit le faux.
        from app.clients import mailjet as module_mailjet

        monkeypatch.setattr(module_mailjet, "envoyer_email", faux_envoi)
        return captures

    @staticmethod
    def _code_depuis(captures: list[tuple[str, str, str]]) -> str:
        import re

        assert captures, "aucun email capture"
        trouve = re.search(r"\b(\d{8})\b", captures[-1][2])
        assert trouve, f"pas de code a 8 chiffres dans : {captures[-1][2]!r}"
        return trouve.group(1)

    async def test_non_provisionne_503_nomme(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # L'etat non provisionne est FORCE — le .env de la machine de dev
        # peut porter de vraies cles, le test ne doit pas en dependre.
        monkeypatch.setattr(settings, "mailjet_api_key", None)
        monkeypatch.setattr(settings, "mailjet_secret_key", None)
        monkeypatch.setattr(settings, "mailjet_expediteur", None)
        reponse = await client.post(
            "/admin/auth/mot-de-passe-oublie", json={"email": EMAIL}
        )
        assert reponse.status_code == 503
        assert "MAILJET" in reponse.json()["detail"]

    async def test_202_identique_que_le_compte_existe_ou_non(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captures = self._provisionner(monkeypatch)
        connu = await client.post(
            "/admin/auth/mot-de-passe-oublie", json={"email": EMAIL}
        )
        inconnu = await client.post(
            "/admin/auth/mot-de-passe-oublie", json={"email": "personne@finzuu.com"}
        )
        assert connu.status_code == inconnu.status_code == 202
        assert connu.json()["detail"] == inconnu.json()["detail"], (
            "la reponse ne doit pas reveler l'existence du compte"
        )
        assert len(captures) == 1, "un seul email : celui du compte qui existe"

    async def test_le_code_recu_reinitialise_et_ouvre_une_session_pleine(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captures = self._provisionner(monkeypatch)
        await client.post("/admin/auth/mot-de-passe-oublie", json={"email": EMAIL})
        code = self._code_depuis(captures)

        nouveau = "reinitialise-par-email-14aout"
        reponse = await client.post(
            "/admin/auth/reinitialiser",
            json={"email": EMAIL, "code": code, "nouveau": nouveau},
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["must_change_password"] is False, (
            "le mot de passe choisi par son proprietaire est DURABLE"
        )
        # Le nouveau mot de passe fonctionne au login ; l'ancien est mort.
        assert (await _login(client, nouveau))["must_change_password"] is False
        mort = await client.post(
            "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": MDP_INITIAL}
        )
        assert mort.status_code == 401
        # Le code est CONSOMME : le rejouer echoue.
        rejoue = await client.post(
            "/admin/auth/reinitialiser",
            json={"email": EMAIL, "code": code, "nouveau": "encore-un-autre-mdp-long"},
        )
        assert rejoue.status_code == 401

    async def test_cinq_essais_rates_tuent_le_code_meme_correct(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captures = self._provisionner(monkeypatch)
        await client.post("/admin/auth/mot-de-passe-oublie", json={"email": EMAIL})
        code = self._code_depuis(captures)
        faux = "00000000" if code != "00000000" else "11111111"
        for _ in range(5):
            rate = await client.post(
                "/admin/auth/reinitialiser",
                json={"email": EMAIL, "code": faux, "nouveau": "un-mdp-suffisamment-long"},
            )
            assert rate.status_code == 401
        bloque = await client.post(
            "/admin/auth/reinitialiser",
            json={"email": EMAIL, "code": code, "nouveau": "un-mdp-suffisamment-long"},
        )
        assert bloque.status_code == 401, "5 echecs consomment le code, meme correct"

    async def test_code_expire_401_generique(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captures = self._provisionner(monkeypatch)
        await client.post("/admin/auth/mot-de-passe-oublie", json={"email": EMAIL})
        code = self._code_depuis(captures)
        # Perime le code en base — la voie du temps, sans attendre 15 min.
        import time as module_time

        await SuperAdminRepository().collection.update_one(
            {"email": EMAIL}, {"$set": {"code_reset_expire": module_time.time() - 1}}
        )
        reponse = await client.post(
            "/admin/auth/reinitialiser",
            json={"email": EMAIL, "code": code, "nouveau": "un-mdp-suffisamment-long"},
        )
        assert reponse.status_code == 401
        assert reponse.json()["detail"] == "code invalide ou expiré", (
            "le refus est GENERIQUE — expire et faux sont indistinguables"
        )


class TestSessionRequise:
    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.get("/admin/referentiels/catalogue-statique")
        assert reponse.status_code == 401

    async def test_jeton_falsifie_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.get(
            "/admin/referentiels/geographie",
            headers={"Authorization": "Bearer pas.un.jeton"},
        )
        assert reponse.status_code == 401


class TestUSB5Referentiels:
    async def test_le_catalogue_statique_porte_les_comptes_EXACTS(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.get(
            "/admin/referentiels/catalogue-statique", headers=entetes
        )
        assert reponse.status_code == 200
        assert reponse.json()["comptes"] == {
            "industries": 6,
            "secteurs": 112,
            "formes_juridiques": 27,
            "professions": 576,
            "groupes": 21,
            "profils_revenu": 4,
            "pays": 195,
            "fonctions_dirigeant": 20,
        }
        profils = reponse.json()["profils_revenu"]
        assert profils["bank_stable"]["mu"] == 12.15

    async def test_la_geographie_rend_l_arbre_complet(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        # Surcouche vierge : les autres tests y ajoutent des villes, et ce
        # test verifie les comptes EXACTS du classeur (CR-01).
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        reponse = await client.get("/admin/referentiels/geographie", headers=entetes)
        assert reponse.status_code == 200
        arbre = reponse.json()["pays"]
        assert {p["pays"] for p in arbre} == {"CM", "CI", "BF", "SN"}
        nb_regions = sum(len(p["regions"]) for p in arbre)
        nb_villes = sum(len(r["villes"]) for p in arbre for r in p["regions"])
        nb_quartiers = sum(
            len(v["quartiers"]) for p in arbre for r in p["regions"] for v in r["villes"]
        )
        assert (nb_regions, nb_villes, nb_quartiers) == (51, 50, 82), (
            "les comptes CR-01 du referentiel doivent arriver ENTIERS a l'ecran"
        )

    async def test_les_telcos_portent_les_parts_de_marche(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/referentiels/telcos", headers=entetes)
        assert reponse.status_code == 200
        telcos = reponse.json()["telcos"]
        assert len(telcos["CM"]) >= 3
        assert all(t["regex_msisdn"] for pays in telcos.values() for t in pays)


class TestUSB1ConfigurationResolue:
    async def test_l_etat_initial_est_le_CDC_version_0(
        self, client: httpx.AsyncClient
    ) -> None:
        """Sans document : le contrat, pas une erreur."""
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_configuration")
        reponse = await client.get("/admin/configuration", headers=entetes)
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["version"] == 0
        assert corps["nb_clients"] == {"valeur": 2000, "origine": "défaut CDC"}
        assert corps["conforme_au_cdc"] is True
        assert set(corps["repartition_clients"]) == {"CM", "CI", "BF", "SN"}
        assert all(v == 500 for v in corps["repartition_clients"].values())

    async def test_une_surcharge_pays_porte_son_ORIGINE(
        self, client: httpx.AsyncClient
    ) -> None:
        """LE critere Gherkin d'US-B1 : SN surcharge a 300 -> origine
        « surcharge pays », les autres -> « défaut CDC »."""
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_configuration")
        await client.put(
            "/admin/configuration",
            json={"pays": {"SN": {"clients": 300}}},
            headers=entetes,
        )
        corps = (await client.get("/admin/configuration", headers=entetes)).json()
        sn = corps["pays"]["SN"]["quantites"]["clients"]
        cm = corps["pays"]["CM"]["quantites"]["clients"]
        assert sn == {"valeur": 300, "origine": "surcharge pays"}
        assert cm["origine"].startswith("défaut CDC")
        # 2000 - 300 = 1700 repartis sur les 3 autres : 567/567/566.
        assert sum(corps["repartition_clients"].values()) == 2000

    async def test_les_quotas_contractuels_sont_AFFICHES_non_parametrables(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        corps = (await client.get("/admin/configuration", headers=entetes)).json()
        assert corps["quotas_contractuels"]["part_femmes"]["origine"].startswith("EF-22")
        assert corps["quotas_contractuels"]["part_corporate"]["origine"].startswith("EF-23")


class TestUSB2ModifierLesVolumes:
    async def test_la_valeur_est_persistee_et_RELUE_a_l_identique(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_configuration")
        reponse = await client.put(
            "/admin/configuration", json={"nb_clients": 1000}, headers=entetes
        )
        assert reponse.status_code == 200
        assert reponse.json()["nb_clients"]["valeur"] == 1000
        assert reponse.json()["version"] == 1
        relu = (await client.get("/admin/configuration", headers=entetes)).json()
        assert relu["nb_clients"] == {"valeur": 1000, "origine": "paramétré"}
        assert relu["modifie_par"] == EMAIL

    async def test_un_quota_contractuel_est_un_422_citant_l_exigence(
        self, client: httpx.AsyncClient
    ) -> None:
        """Gherkin US-B2 : « femmes a 10 % -> 422 citant EF-22 ». Les quotas
        du CDC ne sont PAS des reglages — extra="forbid", champ inconnu."""
        entetes = await _session_complete(client)
        reponse = await client.put(
            "/admin/configuration",
            json={"pays": {"CM": {"part_femmes": 0.10}}},
            headers=entetes,
        )
        assert reponse.status_code == 422

    async def test_une_fourchette_invalide_est_un_422_avec_la_regle(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.put(
            "/admin/configuration",
            json={"pays": {"CM": {"companies": [9, 3]}}},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "min <= max" in reponse.json()["detail"]

    async def test_des_cibles_pays_au_dela_du_total_sont_REFUSEES(
        self, client: httpx.AsyncClient
    ) -> None:
        """« On ne corrige jamais en silence » — le depassement est un refus."""
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_configuration")
        reponse = await client.put(
            "/admin/configuration",
            json={"nb_clients": 100, "pays": {"CM": {"clients": 80}, "SN": {"clients": 90}}},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "depassent le total" in reponse.json()["detail"]

    async def test_un_pays_hors_cibles_est_un_422_EF_05(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.put(
            "/admin/configuration",
            json={"pays": {"GA": {"clients": 10}}},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "EF-05" in reponse.json()["detail"]

    async def test_le_verrou_EF_55_rend_409_pendant_un_run(
        self, client: httpx.AsyncClient
    ) -> None:
        """Gherkin US-B2 : run EN_COURS -> 409 avec l'identifiant du run."""
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        run = LoaderRun(
            _id=_uuid4(),
            sim_start_date=_date(2026, 2, 1),
            sim_end_date=_date(2026, 8, 1),
            status=RunStatus.RUNNING,
        )
        await LoaderRunRepository().remplacer(run)
        try:
            reponse = await client.put(
                "/admin/configuration", json={"nb_clients": 500}, headers=entetes
            )
            assert reponse.status_code == 409
            assert str(run.id) in reponse.json()["detail"]
            assert "EF-55" in reponse.json()["detail"]
        finally:
            await database.get_database().drop_collection("loader_runs")


class TestUSB3EtatDesPays:
    async def test_desactiver_cote_loader_ne_touche_jamais_config_service(
        self, client: httpx.AsyncClient
    ) -> None:
        """Gherkin US-B3 : 3 pays actifs apres desactivation, et AUCUN appel
        reseau — le module des routes n'importe meme pas le client
        config-service, l'appel est impossible par construction."""
        import app.routes.admin_configuration as module

        assert "config_service" not in str(vars(module).keys())
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_configuration")
        reponse = await client.put(
            "/admin/configuration/pays/SN",
            json={"actif": False, "motif": "hors perimetre de ce test"},
            headers=entetes,
        )
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["pays"]["SN"]["actif"] is False
        assert corps["pays"]["SN"]["motif_inactivite"] == "hors perimetre de ce test"
        assert corps["repartition_clients"]["SN"] == 0
        assert sum(corps["repartition_clients"].values()) == 2000, (
            "les 2000 se repartissent sur les 3 pays restants"
        )

    async def test_reactiver_efface_le_motif(self, client: httpx.AsyncClient) -> None:
        entetes = await _session_complete(client)
        await client.put(
            "/admin/configuration/pays/SN",
            json={"actif": False, "motif": "x"},
            headers=entetes,
        )
        corps = (
            await client.put(
                "/admin/configuration/pays/SN", json={"actif": True}, headers=entetes
            )
        ).json()
        assert corps["pays"]["SN"]["actif"] is True
        assert corps["pays"]["SN"]["motif_inactivite"] == ""

    async def test_le_dernier_pays_actif_est_INDESACTIVABLE(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_configuration")
        for code in ("CM", "CI", "BF"):
            await client.put(
                f"/admin/configuration/pays/{code}",
                json={"actif": False, "motif": "test"},
                headers=entetes,
            )
        reponse = await client.put(
            "/admin/configuration/pays/SN",
            json={"actif": False, "motif": "le dernier"},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "dernier pays actif" in reponse.json()["detail"]


class TestUSB4AjoutDeVille:
    async def _preparer(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        # Surcouche vierge : le singleton vit dans loader_configuration.
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        return entetes

    async def test_une_ville_complete_est_creee_et_RELUE_depuis_la_base(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await self._preparer(client)
        regions = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()["pays"]
        region_cm = next(p for p in regions if p["pays"] == "CM")["regions"][0]["id"]

        reponse = await client.post(
            "/admin/referentiels/villes",
            json={
                "region_id": region_cm,
                "nom": "Nkoteng",
                "latitude": 4.5167,
                "longitude": 12.0333,
                "population": 45000,
            },
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert corps["ville"]["nom"] == "Nkoteng"
        assert corps["ville"]["pays"] == "CM"
        assert corps["ville"]["id"].startswith("SC-CM-"), (
            "l'identifiant de surcouche est reconnaissable a l'oeil, jamais "
            "confondable avec le classeur"
        )
        assert corps["avertissements"] == []
        assert corps["surcouche"]["version"] == 1

    async def test_la_ville_SURVIT_et_apparait_dans_l_arbre(
        self, client: httpx.AsyncClient
    ) -> None:
        """LE point d'US-B4 : la persistance. La ville est relue depuis Mongo
        par une AUTRE requete — elle survivrait a un redemarrage."""
        entetes = await self._preparer(client)
        regions = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()["pays"]
        region_cm = next(p for p in regions if p["pays"] == "CM")["regions"][0]["id"]
        await client.post(
            "/admin/referentiels/villes",
            json={"region_id": region_cm, "nom": "Obala"},
            headers=entetes,
        )
        arbre = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()
        noms = {
            v["nom"]
            for p in arbre["pays"]
            for r in p["regions"]
            for v in r["villes"]
        }
        assert "Obala" in noms
        assert "Obala" in " ".join(arbre["surcouche"]["journal"])

    async def test_le_classeur_n_est_JAMAIS_modifie(
        self, client: httpx.AsyncClient
    ) -> None:
        """CFG-03 — la surcouche est reversible, le classeur immuable."""
        import hashlib
        from pathlib import Path

        classeur = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
        # Lecture bloquante assumee dans un test : le fichier fait ~100 Ko.
        avant = hashlib.sha256(classeur.read_bytes()).hexdigest()  # noqa: ASYNC240
        entetes = await self._preparer(client)
        regions = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()["pays"]
        region_cm = next(p for p in regions if p["pays"] == "CM")["regions"][0]["id"]
        await client.post(
            "/admin/referentiels/villes",
            json={"region_id": region_cm, "nom": "Ntui"},
            headers=entetes,
        )
        apres = hashlib.sha256(classeur.read_bytes()).hexdigest()  # noqa: ASYNC240
        assert apres == avant

    async def test_une_region_inexistante_est_un_422_EF_02(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/referentiels/villes",
            json={"region_id": "REGION-FANTOME", "nom": "Nulle Part"},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "EF-02" in reponse.json()["detail"]

    async def test_un_doublon_de_nom_est_un_422(self, client: httpx.AsyncClient) -> None:
        entetes = await self._preparer(client)
        regions = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()["pays"]
        cm = next(p for p in regions if p["pays"] == "CM")
        region_cm = cm["regions"][0]["id"]
        ville_existante = cm["regions"][0]["villes"][0]["nom"]
        reponse = await client.post(
            "/admin/referentiels/villes",
            json={"region_id": region_cm, "nom": ville_existante},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "existe deja" in reponse.json()["detail"]

    async def test_une_ville_sans_GPS_est_acceptee_AVEC_avertissement(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await self._preparer(client)
        regions = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()["pays"]
        region_cm = next(p for p in regions if p["pays"] == "CM")["regions"][0]["id"]
        reponse = await client.post(
            "/admin/referentiels/villes",
            json={"region_id": region_cm, "nom": "Sans Gps"},
            headers=entetes,
        )
        assert reponse.status_code == 201
        assert any("GPS" in a for a in reponse.json()["avertissements"])

    async def test_le_verrou_EF_55_bloque_aussi_les_villes(
        self, client: httpx.AsyncClient
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        entetes = await self._preparer(client)
        await database.get_database().drop_collection("loader_runs")
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=_uuid4(),
                sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1),
                status=RunStatus.RUNNING,
            )
        )
        try:
            reponse = await client.post(
                "/admin/referentiels/villes",
                json={"region_id": "peu-importe", "nom": "Bloquee"},
                headers=entetes,
            )
            assert reponse.status_code == 409
            assert "EF-55" in reponse.json()["detail"]
        finally:
            await database.get_database().drop_collection("loader_runs")


class TestLotBRuns:
    """`US-C1`/`US-C2`/`US-C3`/`US-C4`/`US-C6` — le cablage des routes.

    Le MOTEUR est deja prouve ailleurs (858 tests + DRY_RUN reel au centime
    pres) : ici, il est DOUBLE par un faux qui ecrit le meme cycle de vie
    dans loader_runs. Ces tests verrouillent ce que les routes garantissent :
    le rite D-01 structurel, le perimetre fige, les 409, l'historique.
    """

    @staticmethod
    def _doubler_sondes(
        monkeypatch: pytest.MonkeyPatch,
        *,
        en_panne: tuple[str, ...] = (),
        derive: tuple[str, ...] = (),
    ) -> None:
        """Double les DEUX pre-vols de /confirmer — aucun appel reseau.

        1. le pre-vol de VIE (21/08) : les 10 sondes E1 — tout vert, ou une
           panne NOMMEE ;
        2. le pre-vol de COHERENCE (`C4`, 23/08) : le referentiel de la
           plateforme a-t-il DERIVE sur le perimetre ? Un service peut etre UP
           et porter un referentiel desynchronise — c'est arrive le 23/08 sur
           les 4 pays du CDC (12-14 villes la-bas contre 70-181 chez nous).
        """

        async def fausse_sonde(client: Any, nom: str, base: str) -> dict[str, Any]:
            if nom in en_panne:
                return {"nom": nom, "etat": "down", "http": None,
                        "latence_ms": 1, "erreur": "ConnectTimeout"}
            return {"nom": nom, "etat": "up", "http": 200, "latence_ms": 1}

        async def fausse_derive(codes: list[str]) -> list[str]:
            return list(derive)

        monkeypatch.setattr("app.routes.admin_runs._sonder", fausse_sonde)
        monkeypatch.setattr("app.routes.admin_runs._derive_du_perimetre", fausse_derive)

    @staticmethod
    def _doubler_moteur(monkeypatch: pytest.MonkeyPatch, *, statut_final: str = "PARTIAL"):
        """Remplace pilotage.executer par un double qui joue le cycle de vie."""
        from datetime import date as _date

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.configuration import ConfigurationRepository
        from app.repositories.loader_runs import LoaderRunRepository
        from app.routes import admin_runs

        appels: list[dict[str, Any]] = []

        async def faux_moteur(mode, etapes=None, ignorer_verrou=False, *, run_id=None,
                              configuration=None, sortie=print, gerer_connexion=True):
            appels.append({"mode": mode, "run_id": run_id, "configuration": configuration})
            if configuration is None:
                configuration, _ = await ConfigurationRepository().charger()
            run = LoaderRun(
                _id=run_id,
                sim_start_date=_date(2026, 2, 14),
                sim_end_date=_date(2026, 8, 13),
                mode=mode,
                status=RunStatus.PENDING,
                configuration=configuration.empreinte(),
            )
            depot = LoaderRunRepository()
            await depot.remplacer(run)
            await depot.changer_statut(run.id, RunStatus.RUNNING)
            await depot.ajouter_checkpoint(run.id, "ROLES", {"statut": "COMPLETED"})
            sortie("rapport du faux moteur")
            await depot.changer_statut(run.id, RunStatus(statut_final))
            return 0

        monkeypatch.setattr(admin_runs, "executer", faux_moteur)
        return appels

    async def _preparer_et_attendre(self, client: httpx.AsyncClient, entetes) -> str:
        reponse = await client.post("/admin/runs", json={}, headers=entetes)
        assert reponse.status_code == 202, reponse.text
        run_id = reponse.json()["run_id"]
        for _ in range(50):
            detail = await client.get(f"/admin/runs/{run_id}", headers=entetes)
            if detail.status_code == 200 and detail.json().get("statut") not in (
                "PENDING", "RUNNING",
            ):
                break
            await __import__("asyncio").sleep(0.05)
        return run_id

    async def test_US_C1_preparer_rend_202_puis_le_rapport_est_range(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appels = self._doubler_moteur(monkeypatch)
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        run_id = await self._preparer_et_attendre(client, entetes)
        assert appels[0]["mode"].value == "DRY_RUN"
        detail = (await client.get(f"/admin/runs/{run_id}", headers=entetes)).json()
        assert detail["statut"] == "PARTIAL"
        assert "rapport du faux moteur" in detail["rapport"], (
            "le rapport que le CLI imprime doit etre RANGE avec le run"
        )

    async def test_US_C1_le_REAL_direct_n_existe_pas(
        self, client: httpx.AsyncClient
    ) -> None:
        """Le rite D-01 est STRUCTUREL : aucun chemin ne lance un REAL sans
        preparation."""
        entetes = await _session_complete(client)
        reponse = await client.post("/admin/runs", json={"mode": "REAL"}, headers=entetes)
        assert reponse.status_code == 422
        assert "confirmer" in reponse.json()["detail"]

    async def test_US_C2_confirmer_lance_le_REAL_sur_le_perimetre_FIGE(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appels = self._doubler_moteur(monkeypatch)
        self._doubler_sondes(monkeypatch)  # pre-vol tout vert
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("loader_configuration")
        preparation_id = await self._preparer_et_attendre(client, entetes)

        reponse = await client.post(
            f"/admin/runs/{preparation_id}/confirmer", headers=entetes
        )
        assert reponse.status_code == 202, reponse.text
        assert reponse.json()["mode"] == "REAL"
        assert reponse.json()["preparation_id"] == preparation_id
        for _ in range(50):
            if len(appels) == 2:
                break
            await __import__("asyncio").sleep(0.05)
        assert appels[1]["mode"].value == "REAL"
        assert appels[1]["configuration"] is not None, (
            "le REAL recoit l'empreinte FIGEE de la preparation, jamais None"
        )

    async def test_US_C2_pre_vol_de_COHERENCE_refuse_409_si_le_referentiel_a_derive(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`C4` — les 10 services peuvent etre UP et porter un referentiel
        DESYNCHRONISE. Le 23/08, les 4 pays du CDC portaient 12 a 14 villes
        la-bas contre 70 a 181 chez nous : un REAL aurait compose des adresses
        dans des villes que la plateforme ne connait pas. On ne part pas sur
        une derive CONNUE."""
        appels = self._doubler_moteur(monkeypatch)
        self._doubler_sondes(
            monkeypatch,  # vie : tout vert — c'est la COHERENCE qui refuse
            derive=("CM : 74 ville(s) du Loader absentes de la plateforme",),
        )
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("loader_configuration")
        preparation_id = await self._preparer_et_attendre(client, entetes)

        reponse = await client.post(
            f"/admin/runs/{preparation_id}/confirmer", headers=entetes
        )
        assert reponse.status_code == 409, reponse.text
        detail = reponse.json()["detail"]
        assert "cohérence" in detail, detail
        assert "ne porte pas ce que le run suppose" in detail, detail
        assert "74 ville(s)" in detail, "la derive MESUREE est nommee"
        assert "synchroniser" in detail, "le geste qui la ferme est dit"
        assert len(appels) == 1, "RIEN n'est parti : seule la preparation a tourne"

    async def test_US_C2_pre_vol_refuse_un_pays_du_perimetre_ABSENT_de_la_plateforme(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le cas d'une base FRAICHE : le referentiel n'a jamais ete pousse.
        Un pays absent n'apparait dans AUCUNE mesure d'ecart — il n'y a rien a
        comparer — et serait passe entre les mailles. C'est pourtant le pire
        etat : un REAL qui cree des Companies dans un pays inconnu."""
        from app.routes import admin_runs

        appels = self._doubler_moteur(monkeypatch)

        async def fausse_sonde(cli: Any, nom: str, base: str) -> dict[str, Any]:
            return {"nom": nom, "etat": "up", "http": 200, "latence_ms": 1}

        async def mesure_vide() -> dict[str, Any]:
            return {"pays": [], "compte": 0, "sans_ecart": 0}  # plateforme VIERGE

        monkeypatch.setattr("app.routes.admin_runs._sonder", fausse_sonde)
        monkeypatch.setattr(
            "app.routes.admin_referentiels._mesurer_pays_config", mesure_vide
        )
        monkeypatch.setattr(
            admin_runs, "_pays_du_perimetre", lambda _preparation: ["CM", "SN"]
        )

        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("loader_configuration")
        preparation_id = await self._preparer_et_attendre(client, entetes)

        reponse = await client.post(
            f"/admin/runs/{preparation_id}/confirmer", headers=entetes
        )
        assert reponse.status_code == 409, reponse.text
        detail = reponse.json()["detail"]
        assert "CM : ABSENT" in detail and "SN : ABSENT" in detail, detail
        assert "pousser" in detail, "le geste qui repare est dit"
        assert len(appels) == 1, "RIEN n'est parti"

    async def test_US_C2_pre_vol_un_service_en_panne_refuse_503_et_rien_ne_part(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exigence Yaniv (21/08) : AVANT de pousser quoi que ce soit, la
        preuve de vie des 10 sondes. Un service muet -> 503 qui le NOMME,
        et le moteur n'est PAS lance — aucune ecriture n'est partie."""
        appels = self._doubler_moteur(monkeypatch)
        self._doubler_sondes(monkeypatch, en_panne=("collect-service",))
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("loader_configuration")
        preparation_id = await self._preparer_et_attendre(client, entetes)

        reponse = await client.post(
            f"/admin/runs/{preparation_id}/confirmer", headers=entetes
        )
        assert reponse.status_code == 503, reponse.text
        detail = reponse.json()["detail"]
        assert "collect-service" in detail, "la panne est NOMMEE, jamais generique"
        assert "RIEN n'est parti" in detail
        assert len(appels) == 1, (
            "seule la preparation a tourne — le pre-vol refuse AVANT le moteur"
        )

    async def test_US_C2_une_configuration_changee_est_un_409_re_preparer(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE critere ne en redigeant la story : le rapport lu ne decrit plus
        ce qui va s'executer -> re-preparer (D-01)."""
        self._doubler_moteur(monkeypatch)
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("loader_configuration")
        preparation_id = await self._preparer_et_attendre(client, entetes)

        # La configuration CHANGE apres la preparation.
        await client.put(
            "/admin/configuration", json={"nb_clients": 750}, headers=entetes
        )
        reponse = await client.post(
            f"/admin/runs/{preparation_id}/confirmer", headers=entetes
        )
        assert reponse.status_code == 409
        assert "re-preparer" in reponse.json()["detail"]

    async def test_US_C2_une_preparation_inachevee_ne_se_confirme_pas(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        courant = LoaderRun(
            _id=_uuid4(), sim_start_date=_date(2026, 2, 1),
            sim_end_date=_date(2026, 8, 1), status=RunStatus.RUNNING,
        )
        await LoaderRunRepository().remplacer(courant)
        try:
            reponse = await client.post(
                f"/admin/runs/{courant.id}/confirmer", headers=entetes
            )
            assert reponse.status_code == 409
            assert "TERMINE" in reponse.json()["detail"].upper()
        finally:
            await database.get_database().drop_collection("loader_runs")

    async def test_US_C3_la_progression_rend_les_paliers(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_moteur(monkeypatch)
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        run_id = await self._preparer_et_attendre(client, entetes)
        progression = (
            await client.get(f"/admin/runs/{run_id}/progression", headers=entetes)
        ).json()
        assert progression["statut"] == "PARTIAL"
        assert any(p.get("phase") == "ROLES" for p in progression["paliers"]) or (
            progression["paliers"]
        ), "les checkpoints de l'orchestrateur sont la matiere de la progression"

    async def test_US_C4_arreter_sans_tache_locale_est_un_409_honnete(
        self, client: httpx.AsyncClient
    ) -> None:
        from uuid import uuid4 as _uuid4

        entetes = await _session_complete(client)
        reponse = await client.post(f"/admin/runs/{_uuid4()}/arreter", headers=entetes)
        assert reponse.status_code == 409
        assert "pas en cours dans ce processus" in reponse.json()["detail"]

    async def test_US_C6_l_historique_est_append_only(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_moteur(monkeypatch)
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await self._preparer_et_attendre(client, entetes)
        historique = (await client.get("/admin/runs", headers=entetes)).json()
        assert len(historique["runs"]) == 1
        # Aucune route de suppression : DELETE rend 405, pas 200.
        run_id = historique["runs"][0]["run_id"]
        suppression = await client.request(
            "DELETE", f"/admin/runs/{run_id}", headers=entetes
        )
        assert suppression.status_code == 405


class TestLotCDashboard:
    """`US-E1`/`US-E2`/`US-E4` — la visualisation, depuis NOS collections.

    Les sondes /health sont DOUBLEES (le reseau n'entre pas dans un test) ;
    l'arbre, le registre et le journal sont de VRAIS documents inseres dans
    la base de test — le dashboard lit exactement ce que le run ecrirait.
    """

    @staticmethod
    def _doubler_sondes(monkeypatch: pytest.MonkeyPatch) -> None:
        from app.routes import admin_dashboard

        async def fausse_sonde(client, nom, base):
            return {"nom": nom, "etat": "up", "http": 200, "latence_ms": 7}

        monkeypatch.setattr(admin_dashboard, "_sonder", fausse_sonde)

    @staticmethod
    async def _semer_un_run() -> Any:
        """Un run avec un arbre minimal REEL : branche > agence > kiosque >
        agent + client — inseres par les repositories, jamais a la main."""
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository
        from app.repositories.org_hierarchy import OrgHierarchyRepository

        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("org_hierarchy")
        run = LoaderRun(
            _id=_uuid4(), sim_start_date=_date(2026, 2, 14),
            sim_end_date=_date(2026, 8, 13), status=RunStatus.PARTIAL,
        )
        await LoaderRunRepository().remplacer(run)

        arbre = OrgHierarchyRepository()
        company = _uuid4()
        branche = await arbre.ajouter_branche(
            run_id=run.id, company_id=company, name="DEMO_Branche Littoral",
            country_code="CM", region_id="CM-REG-01",
        )
        agence = await arbre.ajouter_agence(
            run_id=run.id, branche_id=branche.id, company_id=company,
            name="DEMO_Agence Douala", country_code="CM", city_id="CM-CT-01",
        )
        kiosque = await arbre.ajouter_kiosque(
            run_id=run.id, agence_id=agence.id, company_id=company,
            name="DEMO_Kiosque Bepanda", country_code="CM",
            district_id="CM-DIS-01", depositary_id=_uuid4(),
        )
        assert kiosque is not None
        await arbre.ajouter_agent(
            run_id=run.id, kiosque_id=kiosque.id, company_id=company,
            name="DEMO_Agent 1", country_code="CM", user_id=_uuid4(),
        )
        await arbre.ajouter_client(
            run_id=run.id, kiosque_id=kiosque.id, company_id=company,
            country_code="CM", msisdn="+237650000001", client_id=_uuid4(), produit_entree=None,
        )
        return run

    async def test_US_E1_la_vue_d_ensemble_sonde_et_compte(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_sondes(monkeypatch)
        entetes = await _session_complete(client)
        await self._semer_un_run()
        reponse = await client.get("/admin/dashboard", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert len(corps["services"]) == 10, "les 9 services FinZuu + Faker"
        assert all(s["etat"] == "up" for s in corps["services"])
        assert corps["compteurs"]["branches"] == 1
        assert corps["compteurs"]["kiosques"] == 1
        assert corps["compteurs"]["clients"] == 1
        assert corps["dernier_run"]["statut"] == "PARTIAL"

    async def test_US_E2_l_arbre_est_NAVIGABLE_et_assemble(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        await self._semer_un_run()
        reponse = await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        branche = corps["branches"][0]
        assert branche["pays"] == "CM"
        kiosque = branche["agences"][0]["kiosques"][0]
        assert kiosque["nom"] == "DEMO_Kiosque Bepanda"
        assert kiosque["nb_agents"] == 1
        assert kiosque["nb_clients"] == 1, (
            "le rattachement EF-26 doit etre VISIBLE dans l'arbre — c'est la "
            "structure que la plateforme ne sait pas montrer"
        )

    async def test_V03_l_arbre_a_CINQ_niveaux_pays_puis_IMF(
        self, client: httpx.AsyncClient
    ) -> None:
        """`V-03` (23/08) — l'arbre en avait TROIS et commencait a la Branche.
        Sur le plan reel : 20 branches a plat, sans pays, et les deux IMF d'un
        meme pays y apparaissaient en lignes jumelles « Centre » / « Centre »,
        impossibles a distinguer."""
        entetes = await _session_complete(client)
        await self._semer_un_run()
        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        assert corps["pays"], "le niveau PAYS existe"
        pays = corps["pays"][0]
        assert pays["iso2"] == "CM"
        assert pays["nom"] == "Cameroun", "le pays porte son NOM, pas son code"
        assert pays["companies"], "le niveau IMF existe"
        imf = pays["companies"][0]
        assert imf["branches"], "et sous l'IMF, ses branches"
        assert imf["branches"][0]["agences"][0]["kiosques"], "cinq niveaux"

    async def test_V03_chaque_niveau_porte_ses_AGREGATS(
        self, client: httpx.AsyncClient
    ) -> None:
        """Une ligne qui porte ses totaux n'oblige jamais a deplier pour
        savoir ce qu'il y a dessous — c'est ce qui separe un arbre lisible
        d'un arbre decoratif."""
        entetes = await _session_complete(client)
        await self._semer_un_run()
        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        pays = corps["pays"][0]
        assert pays["agregats"]["kiosques"] == 1
        assert pays["agregats"]["agents"] == 1
        assert pays["agregats"]["clients"] == 1
        assert pays["agregats"]["companies"] == 1
        # et le total remonte bien depuis la feuille
        imf = pays["companies"][0]
        assert imf["agregats"]["clients"] == pays["agregats"]["clients"]

    async def test_V03_les_IDENTIFIANTS_deviennent_des_NOMS(
        self, client: httpx.AsyncClient
    ) -> None:
        """L'ecran rendait `"quartier": "CM-DT-001"`. Pour savoir qu'il
        s'agit de Bastos, il fallait ouvrir la base. Un ecran qui oblige a
        aller chercher ailleurs ce qu'il affiche n'a pas fait son travail."""
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository
        from app.repositories.org_hierarchy import OrgHierarchyRepository

        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("org_hierarchy")
        run, company = _uuid4(), _uuid4()
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=run, sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.COMPLETED,
            )
        )
        arbre = OrgHierarchyRepository()
        # Des identifiants REELS du referentiel : CM-02 = Centre,
        # CM-CT-01 = Yaounde, CM-DT-001 = Bastos.
        branche = await arbre.ajouter_branche(
            run_id=run, company_id=company, name="Branche Centre",
            country_code="CM", region_id="CM-02", company_nom="IMF Test",
        )
        agence = await arbre.ajouter_agence(
            run_id=run, branche_id=branche.id, company_id=company,
            name="Agence Yaounde", country_code="CM", city_id="CM-CT-01",
        )
        await arbre.ajouter_kiosque(
            run_id=run, agence_id=agence.id, company_id=company,
            name="Kiosque Bastos", country_code="CM",
            district_id="CM-DT-001", depositary_id=_uuid4(),
        )

        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        branche_rendue = corps["branches"][0]
        assert branche_rendue["pays_nom"] == "Cameroun"
        assert branche_rendue["region_id"] == "CM-02", "l'identifiant reste disponible"
        assert branche_rendue["region"] == "Centre", "et le NOM s'affiche"
        agence_rendue = branche_rendue["agences"][0]
        assert agence_rendue["ville"] == "Yaounde", agence_rendue
        kiosque = agence_rendue["kiosques"][0]
        assert kiosque["quartier"] == "Bastos", kiosque
        assert kiosque["quartier_id"] == "CM-DT-001"

    async def test_V03_un_identifiant_INCONNU_n_est_JAMAIS_maquille_en_nom(
        self, client: httpx.AsyncClient
    ) -> None:
        """Un quartier absent du referentiel garde son identifiant brut. Lui
        inventer un nom serait un mensonge d'ecran — et masquerait justement
        le cas qu'il faut voir : une geographie qui a bouge sous l'arbre."""
        entetes = await _session_complete(client)
        await self._semer_un_run()  # seme des identifiants qui n'existent pas
        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        branche = corps["branches"][0]
        assert branche["region"] == branche["region_id"], (
            "identifiant inconnu -> on rend l'identifiant, jamais un nom invente"
        )

    async def test_V03_les_ANOMALIES_structurelles_sont_NOMMEES(
        self, client: httpx.AsyncClient
    ) -> None:
        """`UC-09` postcondition : un Agent par Kiosque, sans exception. Un
        kiosque sans agent n'ouvre pas — l'arbre doit le dire, pas le taire."""
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import NiveauOrganisation, RunStatus
        from app.repositories.loader_runs import LoaderRunRepository
        from app.repositories.org_hierarchy import OrgHierarchyRepository

        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection("org_hierarchy")
        run, company = _uuid4(), _uuid4()
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=run, sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.COMPLETED,
            )
        )
        arbre = OrgHierarchyRepository()
        branche = await arbre.ajouter_branche(
            run_id=run, company_id=company, name="Branche Littoral",
            country_code="CM", region_id="CM-03", company_nom="IMF Test",
        )
        agence = await arbre.ajouter_agence(
            run_id=run, branche_id=branche.id, company_id=company,
            name="Agence Douala", country_code="CM", city_id="CM-CT-02",
        )
        await arbre.ajouter_kiosque(
            run_id=run, agence_id=agence.id, company_id=company,
            name="Kiosque Bepanda", country_code="CM",
            district_id="CM-DT-010", depositary_id=_uuid4(),
        )  # AUCUN agent rattache

        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        kiosque = corps["pays"][0]["companies"][0]["branches"][0]["agences"][0]["kiosques"][0]
        assert any("aucun agent" in a for a in kiosque["anomalies"]), kiosque
        assert corps["mesures"]["integrite"]["kiosques_sans_agent"] == 1
        assert corps["pays"][0]["companies"][0]["nom"] == "IMF Test", (
            "le nom de l'IMF est range avec la branche — sinon l'ecran groupe "
            "par UUID et deux IMF du meme pays deviennent indiscernables"
        )
        assert NiveauOrganisation.KIOSQUE  # garde l'import utile

    async def test_V03_les_TROIS_MESURES_disent_si_c_est_credible(
        self, client: httpx.AsyncClient
    ) -> None:
        """Un compteur dit COMBIEN. Ces trois-la disent SI C'EST CREDIBLE."""
        entetes = await _session_complete(client)
        await self._semer_un_run()
        mesures = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()["mesures"]
        assert mesures["concentration"]["nb_imf"] == 1
        assert mesures["concentration"]["part_max_pourcent"] == 100.0
        assert mesures["concentration"]["verdict"] == "concentre", (
            "une seule IMF qui porte tous les kiosques n'est pas un ecosysteme"
        )
        # LE DENOMINATEUR EST LE PERIMETRE, PAS LE GLOBE (defaut vu a l'ecran
        # le 24/08 : « 12 villes / 3156 », ou 3156 etait le referentiel des 48
        # pays alors que le run n'en touchait que quatre — un ratio qui ne veut
        # rien dire, et qui fait passer une couverture correcte pour un echec).
        assert mesures["couverture"]["villes_du_referentiel"] > 0
        assert mesures["couverture"]["villes_du_referentiel"] < 200, (
            "borne aux villes des pays de l'arbre, pas aux 3156 du referentiel"
        )
        assert mesures["integrite"]["branches_sans_agence"] == 0

    async def test_V03_l_arbre_AVOUE_quand_ses_kiosques_ont_disparu(
        self, client: httpx.AsyncClient
    ) -> None:
        """Question de Yaniv (24/08) : « si je purge la base, plus rien ne
        s'affiche, n'est-ce pas ? » — NON, et c'etait un mensonge par omission.

        `org_hierarchy` est NOTRE memoire d'un run. La purge n'y touche pas, et
        la plateforme peut etre videe de son cote : l'arbre continuait a
        afficher des kiosques dont le Depositaire n'existait plus, sans le dire.

        Le double rend une plateforme SANS aucun depositaire — l'etat exact
        d'une base fraichement videe. L'arbre doit l'avouer."""
        entetes = await _session_complete(client)
        await self._semer_un_run()
        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        verif = corps["verification"]
        assert verif["verifie"] is True, "la plateforme a repondu, on a donc mesure"
        assert verif["kiosques_disparus"] == 1, verif
        assert "etat PASSE" in verif["motif"], verif["motif"]
        assert corps["mesures"]["integrite"]["kiosques_disparus_la_bas"] == 1

    async def test_V03_une_plateforme_MUETTE_ne_conclut_PAS_que_tout_va_bien(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un ecran qui affirme sans avoir mesure est pire que muet."""

        class _Muet:
            async def lister(self):  # type: ignore[no-untyped-def]
                raise ConnectionError("depositary-service injoignable")

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            "app.clients.depositary_service.DepositaryServiceClient",
            lambda *a, **k: _Muet(),
        )
        entetes = await _session_complete(client)
        await self._semer_un_run()
        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        assert corps["verification"]["verifie"] is False
        assert corps["verification"]["motif"] == "non verifie"
        assert corps["mesures"]["integrite"]["kiosques_disparus_la_bas"] is None, (
            "on ne dit pas 0 quand on ne sait pas — 0 serait une affirmation"
        )

    async def test_V03_la_couverture_INVERSE_dit_ou_creer_le_prochain(
        self, client: httpx.AsyncClient
    ) -> None:
        """`D-03` — un quartier = UN kiosque. Les quartiers NON pris sont
        litteralement les emplacements disponibles. Sans cela, ouvrir le
        formulaire US-D3 revenait a deviner un quartier libre dans une liste
        de plusieurs centaines, puis a se faire refuser."""
        entetes = await _session_complete(client)
        await self._semer_un_run()
        corps = (
            await client.get("/admin/dashboard/ecosysteme", headers=entetes)
        ).json()
        libres = corps["pays"][0]["quartiers_libres"]
        assert libres["compte"] > 0, "le referentiel en porte bien plus qu'un"
        assert libres["exemples"], "et l'ecran en montre quelques-uns"
        premier = libres["exemples"][0]
        assert premier["quartier"] and premier["ville"] and premier["region"], premier
        assert corps["mesures"]["couverture"]["quartiers_libres"] == libres["compte"]

    async def test_US_E2_un_run_sans_arbre_est_un_404(
        self, client: httpx.AsyncClient
    ) -> None:
        from uuid import uuid4 as _uuid4

        entetes = await _session_complete(client)
        reponse = await client.get(
            f"/admin/dashboard/ecosysteme?run_id={_uuid4()}", headers=entetes
        )
        assert reponse.status_code == 404

    async def test_US_E4_la_tracabilite_reconcilie(
        self, client: httpx.AsyncClient
    ) -> None:
        from app.repositories.audit_trail import AuditTrailRepository

        entetes = await _session_complete(client)
        run = await self._semer_un_run()
        await database.get_database().drop_collection("audit_trail")
        await database.get_database().drop_collection("faker_consumption_ledger")
        from uuid import uuid4 as _uuid4

        async with AuditTrailRepository().intention(
            run.id, entity_type="Company", entity_id=_uuid4(),
            operation="CREATE", cible="company-service", payload={"name": "x"},
        ) as suivi:
            suivi.reussi({"ok": True})

        reponse = await client.get("/admin/dashboard/tracabilite", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["journal"]["nb_entrees"] >= 1
        assert corps["journal"]["intentions_orphelines"] == []
        assert "journal est clos" in corps["reconciliation"]


class TestUSE3Population:
    """`US-E3` — les mesures rangees par le moteur, servies par le dashboard."""

    @staticmethod
    async def _semer_mesures() -> Any:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunMode, RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        await database.get_database().drop_collection("loader_runs")
        # `P-06` — REEL, parce que la vue cumulative ne compte QUE ce qui a
        # ete ecrit : un DRY_RUN mesure ce qu'il aurait fait, il ne peuple pas.
        run = LoaderRun(
            _id=_uuid4(), sim_start_date=_date(2026, 2, 14),
            sim_end_date=_date(2026, 8, 13), status=RunStatus.PARTIAL,
            mode=RunMode.REAL,
        )
        depot = LoaderRunRepository()
        await depot.remplacer(run)
        await depot.attacher_mesures(
            run.id,
            {
                "quotas_par_pays": [
                    {"pays": "CM", "clients": {"mesure": 500, "cible": 500}}
                ],
                "occupations": {"distinctes": 300, "total": 500, "top": {"Cocoa farmer": 9}},
                "soldes": {
                    "tranches": {"100 000 a 150 000": 120, "150 000 a 300 000": 180},
                    "total_dote": 74_188_605.0,
                },
                "naissances": {"a_l_etranger": 52, "au_pays": 448},
            },
        )
        return run

    async def test_les_mesures_sont_servies_MESURE_ET_CIBLE(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        run = await self._semer_mesures()
        reponse = await client.get("/admin/dashboard/population", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        # `P-06` — sans `run_id`, la Population couvre TOUS les runs porteurs
        # de mesures : l'entete l'annonce (`portee`), et `runs_mesures` dit
        # lesquels. Un `run_id` nul n'est pas une absence, c'est le cumul.
        assert corps["run_id"] is None
        assert corps["portee"] == "tous"
        assert corps["runs_mesures"] == [str(run.id)]
        # Le recoupement contre les noeuds reellement en base accompagne
        # chaque pays — un ecran qui affirme sans avoir mesure est un ecran
        # qui ment.
        assert corps["quotas_par_pays"][0]["clients"]["mesure"] == 500
        assert corps["quotas_par_pays"][0]["clients"]["cible"] == 500
        assert "en_base" in corps["quotas_par_pays"][0]["clients"]
        assert corps["occupations"]["distinctes"] == 300
        assert "150 000 a 300 000" in corps["soldes"]["tranches"], (
            "150 000 doit etre une FRONTIERE de tranche — le seuil EF-68"
        )
        assert corps["naissances"]["a_l_etranger"] == 52

    async def test_un_DRY_RUN_ne_compte_PAS_dans_la_population_actuelle(
        self, client: httpx.AsyncClient
    ) -> None:
        """`P-06` — un DRY_RUN mesure ce qu'il AURAIT cree, il n'ecrit rien.

        Le premier cumul servi le 24/08 sommait les DRY_RUN avec les runs
        REELS : la prod annoncait 2000 clients au Burkina pour 500 noeuds
        reellement en base, et 1500 en Cote d'Ivoire pour zero. C'est le
        recoupement `en_base` qui l'a montre.
        """
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunMode, RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        entetes = await _session_complete(client)
        reel = await self._semer_mesures()

        blanc = LoaderRun(
            _id=_uuid4(), sim_start_date=_date(2026, 2, 14),
            sim_end_date=_date(2026, 8, 13), status=RunStatus.PARTIAL,
            mode=RunMode.DRY_RUN,
        )
        depot = LoaderRunRepository()
        await depot.remplacer(blanc)
        await depot.attacher_mesures(
            blanc.id,
            {"quotas_par_pays": [{"pays": "CM", "clients": {"mesure": 500, "cible": 500}}]},
        )

        corps = (
            await client.get("/admin/dashboard/population", headers=entetes)
        ).json()
        assert corps["runs_mesures"] == [str(reel.id)], "le DRY_RUN a ete compte"
        assert corps["quotas_par_pays"][0]["clients"]["mesure"] == 500, (
            "500 + 500 = les mesures du DRY_RUN ont ete sommees a celles du REEL"
        )

        # Il reste CONSULTABLE en le designant : on refuse de le faire passer
        # pour la realite, pas de le montrer.
        vise = await client.get(
            f"/admin/dashboard/population?run_id={blanc.id}", headers=entetes
        )
        assert vise.status_code == 200, vise.text
        assert vise.json()["quotas_par_pays"][0]["clients"]["mesure"] == 500

    async def test_un_run_sans_mesures_est_un_404_explique(
        self, client: httpx.AsyncClient
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        run = LoaderRun(
            _id=_uuid4(), sim_start_date=_date(2026, 2, 1),
            sim_end_date=_date(2026, 8, 1), status=RunStatus.PARTIAL,
        )
        await LoaderRunRepository().remplacer(run)
        # `P-06` — UN PERIMETRE VIDE N'EST PAS UNE ERREUR, C'EST UN ETAT.
        #
        # Cette route rendait 404 : l'ecran Population affichait alors une
        # erreur technique la ou la verite est simple — le Loader n'a encore
        # peuple personne. On sert donc 200 et on EXPLIQUE, pour que l'ecran
        # rende un texte plutot qu'un vide ou une erreur.
        #
        # Le 404 reste, et il est teste juste apres : il vaut quand
        # l'operateur designe UN run precis qui, lui, ne porte pas de mesures.
        reponse = await client.get("/admin/dashboard/population", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["quotas_par_pays"] == []
        assert "mesures" in corps["note"]

        # Le meme run, DESIGNE explicitement : 404 explique.
        cible = await client.get(
            f"/admin/dashboard/population?run_id={run.id}", headers=entetes
        )
        assert cible.status_code == 404
        assert "mesures" in cible.json()["detail"]

    async def test_le_MOTEUR_produit_reellement_ces_mesures(self) -> None:
        """Pas seulement la route : l'agregateur du moteur, sur un rapport
        REEL d'executeur — 200 clients composes, mesures completes."""
        import tests.test_clients_execution as tex
        from app.models.enums import RunMode
        from app.services.pilotage import _mesures_population

        clients = tex.FauxClientService()
        executeur = tex._executeur(
            mode=RunMode.REAL, nb_clients=200, pays_actifs=("CM",),
            ledger=tex.FauxLedger(), clients=clients,
            arbre=tex.FauxArbre(tex._kiosques("CM")),
        )
        rapport = await executeur.executer()
        mesures = _mesures_population([rapport])
        assert mesures["quotas_par_pays"][0]["clients"]["mesure"] == 200
        assert mesures["occupations"]["distinctes"] > 80
        assert sum(mesures["soldes"]["tranches"].values()) == mesures["occupations"]["total"]
        part = mesures["naissances"]["a_l_etranger"] / mesures["occupations"]["total"]
        assert 0.03 < part < 0.20, f"{part:.1%} nes a l'etranger"
        profils = mesures["quotas_par_pays"][0]["profils"]
        assert profils["BON_PAYEUR"]["mesure"] == profils["BON_PAYEUR"]["cible"], (
            "CR-09 : mesure et cible cote a cote, et EXACTES"
        )


class TestUSD2ProduitALUnite:
    """`US-D2` — la creation de produit stricte, les trois interfaces, les
    deux cles. product-service est DOUBLE : chaque refus doit tomber AVANT
    tout POST, et la fiche rendue doit venir d'une RELECTURE."""

    VALIDE_CASH: ClassVar[dict[str, Any]] = {
        "nom": "Tontine Marche Central", "code": "TONT_MC",
        "policy_type": "CASH", "categorie": "INDIVIDUAL",
        "montant_min": 1000, "montant_max": 500000, "taux": 5.0,
    }

    @staticmethod
    def _doubler_produits(
        monkeypatch: pytest.MonkeyPatch,
        *,
        homonyme: dict[str, Any] | None = None,
        marqueur_existant: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from app.routes import admin_entites

        posts: list[dict[str, Any]] = []

        class _Produits:
            async def chercher_par_short_name(self, marqueur: str):
                return marqueur_existant

            async def chercher_par_nom(self, nom: str):
                return homonyme

            async def creer_produit(self, payload):
                posts.append(payload)
                return {"_id": "11111111-1111-1111-1111-111111111111", **payload}

            async def fermer(self):
                return None

        monkeypatch.setattr(admin_entites, "_client_produits", lambda: _Produits())
        return posts

    async def _preparer(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "produits_admin"}
        )
        await database.get_database().drop_collection("audit_trail")
        return entetes

    async def test_l_apercu_rend_le_payload_EXACT_sans_aucun_POST(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        posts = self._doubler_produits(monkeypatch)
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/entites/produits/apercu", json=self.VALIDE_CASH, headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["payload"]["name"] == "Tontine Marche Central"
        assert corps["payload"]["short_name"] == "TONT_MC"  # sans prefixe (20/08)
        assert corps["payload"]["policy"]["type"] == "CASH"
        assert posts == [], "l'apercu ne poste JAMAIS"

    async def test_la_matrice_des_TROIS_interfaces_est_appliquee(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_produits(monkeypatch)
        entetes = await self._preparer(client)
        cas = [
            ({**self.VALIDE_CASH, "duree_mois": 6}, "n'expire pas"),
            ({**self.VALIDE_CASH, "policy_type": "CASH_DAT"}, "SANS terme"),
            ({**self.VALIDE_CASH, "policy_type": "PRODUCT"}, "choix METIER"),
            ({**self.VALIDE_CASH, "measure": "LITER"}, "collecte en nature"),
            ({**self.VALIDE_CASH, "montant_min": 3, "montant_max": 3}, "min < max"),
            ({**self.VALIDE_CASH, "nom": "Cotisation 20000/mois"}, "ENVIRONNEMENT"),
            ({**self.VALIDE_CASH, "nom": "Tontine Digitale", "code": "X_TD"}, "unicite"),
        ]
        for corps, attendu in cas:
            reponse = await client.post(
                "/admin/entites/produits/apercu", json=corps, headers=entetes
            )
            assert reponse.status_code == 422, f"{attendu}: {reponse.text}"
            assert attendu in str(reponse.json()["detail"]), attendu

    async def test_LENDING_et_champ_inconnu_sont_422_structurels(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_produits(monkeypatch)
        entetes = await self._preparer(client)
        for corps in (
            {**self.VALIDE_CASH, "policy_type": "LENDING"},
            {**self.VALIDE_CASH, "type": "LENDING"},
            {**self.VALIDE_CASH, "taux": 25.0},
        ):
            reponse = await client.post(
                "/admin/entites/produits/apercu", json=corps, headers=entetes
            )
            assert reponse.status_code == 422, reponse.text

    async def test_la_creation_POSTe_RELIT_et_inscrit_au_registre(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN

        posts = self._doubler_produits(
            monkeypatch,
            marqueur_existant=None,
        )
        # La relecture post-POST retrouve le produit par son marqueur : le
        # double rend None AVANT le POST puis la fiche APRES.
        from app.routes import admin_entites

        etat = {"cree": False}

        class _Produits:
            async def chercher_par_short_name(self, marqueur):
                return {"_id": "abc", "short_name": marqueur} if etat["cree"] else None

            async def chercher_par_nom(self, nom):
                return None

            async def creer_produit(self, payload):
                etat["cree"] = True
                posts.append(payload)
                return {"_id": "abc", **payload}

            async def fermer(self):
                return None

        monkeypatch.setattr(admin_entites, "_client_produits", lambda: _Produits())
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/entites/produits", json=self.VALIDE_CASH, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert corps["fiche_relue"]["short_name"] == "TONT_MC", (
            "la fiche vient d'une RELECTURE, jamais deduite (FRA-218)"
        )
        assert len(posts) == 1
        # Le registre interne porte l'entree — l'autorite d'unicite.
        doublon = await client.post(
            "/admin/entites/produits", json=self.VALIDE_CASH, headers=entetes
        )
        assert doublon.status_code == 409
        assert "registre" in doublon.json()["detail"]
        # Le write-ahead sous le run sentinelle est clos.
        assert await AuditTrailRepository().intentions_orphelines(RUN_ADMIN) == []

    async def test_un_homonyme_ETRANGER_est_refuse_avant_POST(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        posts = self._doubler_produits(
            monkeypatch, homonyme={"_id": "999", "short_name": "pas-a-nous"}
        )
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/entites/produits", json=self.VALIDE_CASH, headers=entetes
        )
        assert reponse.status_code == 409
        assert "etranger" in reponse.json()["detail"]
        assert posts == [], "le refus tombe AVANT tout POST"

    async def test_le_PRODUCT_exige_sa_mesure_et_la_porte(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_produits(monkeypatch)
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/entites/produits/apercu",
            json={
                "nom": "Collecte Karite", "code": "KARITE_IND",
                "policy_type": "PRODUCT", "categorie": "INDIVIDUAL",
                "montant_min": 100, "montant_max": 300000,
                "measure": "KILOGRAM", "measure_price": 250.0,
            },
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        policy = reponse.json()["payload"]["policy"]
        assert policy["measure"] == "KILOGRAM"
        assert policy["measure_price"] == 250.0


class TestUSD1CompanyALUnite:
    """`US-D1` — le cablage de la route ; `creer_company()` (la sequence
    S3-03) est l'unite deja couverte par les tests d'organisation."""

    DEMANDE: ClassVar[dict[str, Any]] = {
        "type_company": "MERCHANT", "pays": "CM", "ville": "Douala",
    }

    @staticmethod
    def _doubler_executeur(monkeypatch: pytest.MonkeyPatch, *, echec: str | None = None):
        from app.routes import admin_entites

        appels: list[dict[str, Any]] = []

        class _Executeur:
            def __init__(self, mode):
                self.mode = mode

            def _telephone_du_pays(self, pays, index):
                return "+237650009999"

            async def creer_company(self, *, rapport, **kwargs):
                appels.append({"mode": self.mode, **kwargs})
                if echec:
                    rapport.companies_echouees.append((kwargs.get("patronyme"), echec))
                    return None
                rapport.companies_creees.append("DEMO_Composee")
                rapport.admins_crees.append("admin@x.finzuu.com")
                rapport.cascades_identity_verifiees += 1
                dry = str(self.mode).endswith("DRY_RUN")
                return {"_id": "cid-1", "name": "DEMO_Composee", "_dry_run": dry}

            async def creer_licence(self, company_id, packages, debut, fin, rapport):
                # Meme comportement observable que le vrai (UC-07) : succes ->
                # append au rapport ; le test verifie l'ENCHAINEMENT, pas HTTP.
                appels.append(
                    {"licence": company_id, "packages": [str(p) for p in packages]}
                )
                rapport.licences_creees.append(company_id)

        monkeypatch.setattr(
            admin_entites,
            "_executeur_organisation",
            lambda mode, referentiel=None: _Executeur(mode),
        )
        # La porte operationnelle (22/08) verifie la presence sur
        # config-service en direct : le double de lecture repond les 4 cibles.
        from app.routes import admin_referentiels

        class _LecturePays:
            async def lister_pays(self):
                return [
                    {"_id": f"cfg-{code}", "iso_name": code}
                    for code in ("CM", "CI", "BF", "SN")
                ]

            async def fermer(self):
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _LecturePays())
        return appels

    async def test_l_apercu_compose_TOUT_depuis_3_champs_sans_ecrire(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appels = self._doubler_executeur(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/companies/apercu", json=self.DEMANDE, headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["fiche"]["_dry_run"] is True
        assert reponse.json()["admin_annonce"] == "admin@x.finzuu.com"
        appel = appels[0]
        assert str(appel["mode"]).endswith("DRY_RUN")
        # Les ~40 champs composes depuis 3 saisis : territoire resolu,
        # patronyme reel, forme et secteur du type.
        assert appel["region"], "la region est RESOLUE depuis la ville"
        assert appel["quartier"] is not None
        assert appel["forme_juridique"]
        assert appel["secteur"]
        assert appel["type_company"].value == "MERCHANT"

    async def test_une_ville_inconnue_est_un_422_PEDAGOGIQUE(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_executeur(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/companies/apercu",
            json={**self.DEMANDE, "ville": "Atlantis"},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "EF-02" in reponse.json()["detail"]
        assert "Douala" in reponse.json()["detail"], (
            "le refus LISTE les villes disponibles — pedagogique, pas un mur"
        )

    async def test_la_confirmation_execute_en_REAL_et_rend_la_fiche(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appels = self._doubler_executeur(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/companies", json=self.DEMANDE, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        assert str(appels[0]["mode"]).endswith("REAL")
        assert reponse.json()["cascade_owner_verifiee"] is True
        # UC-07 (16/08) : la company a l'unite naît AVEC sa licence, comme au
        # run — sinon son catalogue resterait ferme (la licence conditionne
        # UC-11). Le package est ALL, et la reponse le DIT.
        assert reponse.json()["licence_creee"] is True
        assert "ALL" in reponse.json()["licence_detail"]
        licence = next(a for a in appels if "licence" in a)
        assert licence["licence"] == "cid-1"
        assert licence["packages"] == ["ALL"]

    async def test_un_echec_serveur_est_un_502_avec_le_motif(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_executeur(monkeypatch, echec="HTTP 400 : refus simule")
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/companies", json=self.DEMANDE, headers=entetes
        )
        assert reponse.status_code == 502
        assert "refus simule" in reponse.json()["detail"]

    async def test_le_meme_apercu_rend_la_MEME_composition(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CR-03 a l'unite : deux apercus identiques -> meme patronyme, meme
        telephone — l'ancre est la demande, jamais l'horloge."""
        appels = self._doubler_executeur(monkeypatch)
        entetes = await _session_complete(client)
        for _ in range(2):
            await client.post(
                "/admin/entites/companies/apercu", json=self.DEMANDE, headers=entetes
            )
        assert appels[0]["patronyme"] == appels[1]["patronyme"]
        assert appels[0]["telephone"] == appels[1]["telephone"]


class TestLotEPurge:
    """`US-F1`/`US-F2` — la purge honnete : supprime le reversible, LISTE le
    permanent avec son verdict mesure."""

    @staticmethod
    def _doubler_users(monkeypatch: pytest.MonkeyPatch, *, echec_sur: str | None = None):
        from uuid import uuid4 as _uuid4

        from app.routes import admin_purge

        # Noms FONCTIONNELS, sans prefixe — decision Yaniv 13/08. Les deux
        # premiers seront inscrits au registre par les tests ; CUSTOMER jamais.
        etat = {
            "groupes": [
                {"_id": str(_uuid4()), "name": "Agent"},
                {"_id": str(_uuid4()), "name": "Marchand"},
                {"_id": str(_uuid4()), "name": "CUSTOMER"},
            ],
            "supprimes": [],
        }

        class _Users:
            async def lister_groupes(self):
                return list(etat["groupes"])

            async def supprimer_groupe(self, groupe_id):
                nom = next(
                    g["name"] for g in etat["groupes"] if g["_id"] == str(groupe_id)
                )
                if echec_sur and nom == echec_sur:
                    raise RuntimeError("panne simulee")
                etat["supprimes"].append(nom)

            async def fermer(self):
                return None

        monkeypatch.setattr(admin_purge, "_client_users", lambda: _Users())
        return etat

    async def test_US_F1_preparer_montre_les_DEUX_colonnes_sans_ecrire(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler_users(monkeypatch)
        await _registre_vierge()
        for groupe in etat["groupes"][:2]:
            await _inscrire_groupe_au_registre(groupe["_id"], groupe["name"])
        entetes = await _session_complete(client)
        reponse = await client.post("/admin/purge/preparer", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        noms = [g["nom"] for g in corps["purgeable"]["groupes"]]
        assert noms == ["Agent", "Marchand"], (
            "CUSTOMER n'est pas au registre — jamais dans la colonne purgeable, "
            "et la reconnaissance n'a besoin d'AUCUN prefixe"
        )
        assert "D-DEP-3" in corps["residus_marques"]["depositaires"]["verdict"]
        assert "D-DEP-8" in corps["residus_marques"]["depositaires"]["verdict"]
        assert "PATCH langue" in corps["residus_marques"]["clients"]["verdict"]
        assert etat["supprimes"] == [], "preparer n'ecrit JAMAIS"

    async def test_US_F2_confirmer_supprime_les_notres_et_journalise(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN

        etat = self._doubler_users(monkeypatch)
        await _registre_vierge()
        for groupe in etat["groupes"][:2]:
            await _inscrire_groupe_au_registre(groupe["_id"], groupe["name"])
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/purge/confirmer",
            json={"supprimer_groupes": True},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["supprimes"] == ["Agent", "Marchand"]
        assert etat["supprimes"] == ["Agent", "Marchand"], (
            "CUSTOMER intact — on ne supprime que ce que le registre reconnait"
        )
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        assert sum(1 for e in journal if e.action == "DELETE") == 2, (
            "chaque suppression est journalisee sous RUN_ADMIN"
        )
        assert "residus_marques" in reponse.json(), "le rapport REDIT les residus"

    async def test_US_F2_un_echec_n_arrete_pas_la_purge(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler_users(monkeypatch, echec_sur="Agent")
        await _registre_vierge()
        for groupe in etat["groupes"][:2]:
            await _inscrire_groupe_au_registre(groupe["_id"], groupe["name"])
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/purge/confirmer",
            json={"supprimer_groupes": True},
            headers=entetes,
        )
        assert reponse.status_code == 200
        assert reponse.json()["supprimes"] == ["Marchand"]
        assert reponse.json()["echecs"][0]["groupe"] == "Agent"

    async def test_un_id_hors_uuid_ne_perd_pas_sa_trace_de_journal(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QA 14/08 — `UUID(groupe["id"])` levait sur un id legacy, et
        l'exception etait AVALEE par la defense du journal : suppression
        reelle SANS trace. Desormais `uuid_stable` derive, la trace reste."""
        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes import admin_purge
        from app.routes.admin_entites import RUN_ADMIN

        gid = "grp-legacy-7"

        class _Users:
            async def lister_groupes(self):  # type: ignore[no-untyped-def]
                return [{"_id": gid, "name": "Agent"}]

            async def supprimer_groupe(self, groupe_id):  # type: ignore[no-untyped-def]
                return None

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_purge, "_client_users", lambda: _Users())
        await _registre_vierge()
        await _inscrire_groupe_au_registre(gid, "Agent")
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/purge/confirmer",
            json={"supprimer_groupes": True},
            headers=entetes,
        )
        assert reponse.status_code == 200
        assert reponse.json()["supprimes"] == ["Agent"]
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        assert sum(
            1 for e in journal if e.action == "DELETE" and e.entity_type == "Group"
        ) == 1, "la suppression d'un id legacy laisse SA trace — plus jamais avalee"

    async def test_le_verrou_EF_55_couvre_aussi_la_purge(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        self._doubler_users(monkeypatch)
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=_uuid4(), sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.RUNNING,
            )
        )
        try:
            reponse = await client.post(
                "/admin/purge/confirmer",
                json={"supprimer_groupes": True},
                headers=entetes,
            )
            assert reponse.status_code == 409
        finally:
            await database.get_database().drop_collection("loader_runs")


class TestInventaireReconciliation:
    """La famille 5 — « voir NOS donnees la-bas, avec NOS statuts » (vision
    Yaniv 13/08 soir). Quatre statuts par croisement registre x plateforme :
    a_nous, disparu_la_bas, marque_mais_inconnu, etranger. Le DELETE
    individuel d'un groupe est la seule action — et chaque issue d'erreur
    (403, 404, 409, 502) est un critere Gherkin teste ici."""

    @staticmethod
    def _doubler_users(
        monkeypatch: pytest.MonkeyPatch,
        groupes: list[dict[str, str]],
        *,
        panne: bool = False,
        suppression_muette: bool = False,
    ) -> dict[str, Any]:
        from app.routes import admin_inventaire

        etat: dict[str, Any] = {"groupes": list(groupes), "supprimes": []}

        class _Users:
            async def lister_groupes(self):  # type: ignore[no-untyped-def]
                return list(etat["groupes"])

            async def supprimer_groupe(self, groupe_id):  # type: ignore[no-untyped-def]
                if panne:
                    raise RuntimeError("panne simulee")
                if suppression_muette:
                    return None  # 200 sans agir — le config-service sait le faire
                etat["groupes"] = [
                    g for g in etat["groupes"] if g["_id"] != str(groupe_id)
                ]
                etat["supprimes"].append(str(groupe_id))

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_inventaire, "_client_users", lambda: _Users())
        return etat

    async def test_sans_jeton_l_inventaire_repond_401(
        self, client: httpx.AsyncClient
    ) -> None:
        reponse = await client.get("/admin/inventaire/groupes")
        assert reponse.status_code == 401

    async def test_groupes_les_trois_statuts_sans_aucun_prefixe(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un groupe du registre present = a_nous ; un groupe du registre
        ABSENT la-bas = disparu_la_bas (signale, jamais recree en douce) ;
        CUSTOMER = etranger. La reconnaissance ignore totalement les noms."""
        from uuid import uuid4 as _uuid4

        notre, disparu = str(_uuid4()), str(_uuid4())
        self._doubler_users(
            monkeypatch,
            [
                {"_id": notre, "name": "Agent"},
                {"_id": str(_uuid4()), "name": "CUSTOMER"},
            ],
        )
        await _registre_vierge()
        await _inscrire_groupe_au_registre(notre, "Agent")
        await _inscrire_groupe_au_registre(disparu, "Kiosque")
        entetes = await _session_complete(client)

        reponse = await client.get("/admin/inventaire/groupes", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert [g["nom"] for g in corps["a_nous"]] == ["Agent"]
        assert [g["nom"] for g in corps["disparu_la_bas"]] == ["Kiosque"]
        assert [g["nom"] for g in corps["etranger"]] == ["CUSTOMER"]
        assert corps["comptes"] == {
            "a_nous": 1,
            "disparu_la_bas": 1,
            "marque_mais_inconnu": 0,
            "etranger": 1,
        }
        assert corps["anomalies"] == 1, "le disparu EST une anomalie, comptee"

    async def test_delete_d_un_groupe_a_nous_verifie_par_relecture(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN

        notre = str(_uuid4())
        etat = self._doubler_users(monkeypatch, [{"_id": notre, "name": "Agent"}])
        await _registre_vierge()
        await _inscrire_groupe_au_registre(notre, "Agent")
        entetes = await _session_complete(client)

        reponse = await client.delete(
            f"/admin/inventaire/groupes/{notre}", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json() == {"supprime": "Agent", "verifie_par_relecture": True}
        assert etat["supprimes"] == [notre]
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        operations = [
            (e.after or {}).get("operation")
            for e in journal
            if e.action == "INTENTION" and e.entity_type == "Group"
        ]
        assert "DELETE" in operations, "l'intention est ecrite AVANT l'acte"

        # Et le registre l'a OUBLIE : il n'est plus ni a_nous ni disparu.
        relecture = await client.get("/admin/inventaire/groupes", headers=entetes)
        assert relecture.json()["comptes"]["a_nous"] == 0
        assert relecture.json()["comptes"]["disparu_la_bas"] == 0

    async def test_delete_d_un_groupe_etranger_403_meme_bien_nomme(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le nom ne protege pas, le registre si : un groupe nomme comme un
        de nos roles mais hors registre reste ETRANGER — 403, jamais touche."""
        from uuid import uuid4 as _uuid4

        etranger = str(_uuid4())
        etat = self._doubler_users(monkeypatch, [{"_id": etranger, "name": "Agent"}])
        await _registre_vierge()
        entetes = await _session_complete(client)

        reponse = await client.delete(
            f"/admin/inventaire/groupes/{etranger}", headers=entetes
        )
        assert reponse.status_code == 403
        assert "ETRANGER" in reponse.json()["detail"]
        assert etat["supprimes"] == [], "rien n'a ete tente sur le serveur"

    async def test_delete_d_un_groupe_inconnu_404(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        self._doubler_users(monkeypatch, [])
        entetes = await _session_complete(client)
        reponse = await client.delete(
            f"/admin/inventaire/groupes/{_uuid4()}", headers=entetes
        )
        assert reponse.status_code == 404

    async def test_delete_sous_run_409_avant_toute_lecture(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        self._doubler_users(monkeypatch, [])
        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=_uuid4(), sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.RUNNING,
            )
        )
        try:
            reponse = await client.delete(
                f"/admin/inventaire/groupes/{_uuid4()}", headers=entetes
            )
            assert reponse.status_code == 409
        finally:
            await database.get_database().drop_collection("loader_runs")

    async def test_delete_en_panne_502_et_l_echec_est_journalise(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN

        notre = str(_uuid4())
        self._doubler_users(
            monkeypatch, [{"_id": notre, "name": "Agent"}], panne=True
        )
        await _registre_vierge()
        await _inscrire_groupe_au_registre(notre, "Agent")
        entetes = await _session_complete(client)

        reponse = await client.delete(
            f"/admin/inventaire/groupes/{notre}", headers=entetes
        )
        assert reponse.status_code == 502
        assert "RuntimeError" in reponse.json()["detail"]
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        statuts = [
            (e.after or {}).get("statut")
            for e in journal
            if e.action == "RESULTAT" and e.entity_type == "Group"
        ]
        assert "ECHEC" in statuts, "l'echec aussi laisse une trace"
        # Le groupe n'a PAS quitte le registre : il est toujours a nous.
        relecture = await client.get("/admin/inventaire/groupes", headers=entetes)
        assert relecture.json()["comptes"]["a_nous"] == 1

    async def test_delete_ou_le_serveur_repond_sans_agir_502(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Famille 2b : 200 sans effet. La RELECTURE le confond — jamais
        « supprime » sur la seule foi du code HTTP."""
        from uuid import uuid4 as _uuid4

        notre = str(_uuid4())
        self._doubler_users(
            monkeypatch,
            [{"_id": notre, "name": "Agent"}],
            suppression_muette=True,
        )
        await _registre_vierge()
        await _inscrire_groupe_au_registre(notre, "Agent")
        entetes = await _session_complete(client)

        reponse = await client.delete(
            f"/admin/inventaire/groupes/{notre}", headers=entetes
        )
        assert reponse.status_code == 502
        assert "repondu sans agir" in reponse.json()["detail"]

    async def test_un_id_serveur_hors_uuid_reste_supprimable_et_trace(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QA 14/08 — le contrat serveur ne garantit AUCUN format d'id.
        Exiger un UUID au chemin rendait un groupe a id legacy visible mais
        INSUPPRIMABLE (422 avant la route). L'autorite est le registre ; le
        journal derive un UUID STABLE (meme doctrine que _sceller)."""
        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN
        from app.services.inventaire import uuid_stable

        gid = "grp-legacy-42"
        etat = self._doubler_users(monkeypatch, [{"_id": gid, "name": "Agent"}])
        await _registre_vierge()
        await _inscrire_groupe_au_registre(gid, "Agent")
        entetes = await _session_complete(client)

        reponse = await client.delete(
            f"/admin/inventaire/groupes/{gid}", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        assert etat["supprimes"] == [gid]
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        assert any(
            e.entity_id == uuid_stable(gid)
            for e in journal
            if e.entity_type == "Group" and e.action == "INTENTION"
        ), "l'id illisible ne perd pas le lien — uuid5 stable au journal"

    async def test_A13_l_adoption_rend_notres_les_groupes_preexistants(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A-13 (Yaniv 14/08) : « c'est nous qui les avons crees la-bas » —
        avant le journal du 13/08. L'adoption inscrit au registre, avec une
        issue PAR identifiant, et apres elle le groupe est a_nous PARTOUT."""
        from uuid import uuid4 as _uuid4

        notre_ancien, deja, disparu = str(_uuid4()), str(_uuid4()), str(_uuid4())
        etat = self._doubler_users(
            monkeypatch,
            [
                {"_id": notre_ancien, "name": "Super-Admin"},
                {"_id": deja, "name": "Agent"},
            ],
        )
        await _registre_vierge()
        await _inscrire_groupe_au_registre(deja, "Agent")
        entetes = await _session_complete(client)

        reponse = await client.post(
            "/admin/inventaire/groupes/adoption",
            json={"groupe_ids": [notre_ancien, deja, disparu]},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["comptes"] == {
            "adoptes": 1, "deja_au_registre": 1, "introuvables": 1,
        }, "chaque identifiant recoit SON issue — jamais un echec global muet"
        assert corps["registre_apres"] == 2

        # Et le groupe adopte est desormais A NOUS partout : inventaire...
        inventaire = await client.get("/admin/inventaire/groupes", headers=entetes)
        assert sorted(g["nom"] for g in inventaire.json()["a_nous"]) == [
            "Agent", "Super-Admin",
        ]
        # ... et DELETE individuel (la garde du registre le laisse passer).
        suppression = await client.delete(
            f"/admin/inventaire/groupes/{notre_ancien}", headers=entetes
        )
        assert suppression.status_code == 200, suppression.text
        assert etat["supprimes"] == [notre_ancien]

    async def test_l_adoption_est_journalisee_et_le_verrou_la_couvre(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.audit_trail import AuditTrailRepository
        from app.repositories.loader_runs import LoaderRunRepository
        from app.routes.admin_entites import RUN_ADMIN

        gid = str(_uuid4())
        self._doubler_users(monkeypatch, [{"_id": gid, "name": "Compliance"}])
        await _registre_vierge()
        entetes = await _session_complete(client)

        reponse = await client.post(
            "/admin/inventaire/groupes/adoption",
            json={"groupe_ids": [gid]},
            headers=entetes,
        )
        assert reponse.status_code == 200
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        operations = [
            (e.after or {}).get("operation")
            for e in journal
            if e.action == "INTENTION" and e.entity_type == "Group"
        ]
        assert "ADOPTION" in operations, "l'adoption laisse SA trace — nommee"

        await database.get_database().drop_collection("loader_runs")
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=_uuid4(), sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.RUNNING,
            )
        )
        try:
            bloque = await client.post(
                "/admin/inventaire/groupes/adoption",
                json={"groupe_ids": [gid]},
                headers=entetes,
            )
            assert bloque.status_code == 409, "EF-55 couvre aussi l'adoption"
        finally:
            await database.get_database().drop_collection("loader_runs")

    async def test_produits_les_quatre_statuts(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registre = journal (catalogue) UNION `produits_admin` ; marqueur
        dans short_name. Le DEMO_ inconnu de nos registres est SIGNALE."""
        from uuid import uuid4 as _uuid4

        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes import admin_inventaire
        from app.routes.admin_entites import RUN_ADMIN

        du_run, de_l_admin, disparu = str(_uuid4()), str(_uuid4()), str(_uuid4())
        plateforme = [
            {"_id": du_run, "name": "Tontine Digitale", "short_name": "DEMO_TONTINE"},
            {"_id": de_l_admin, "name": "Warrantage", "short_name": "DEMO_WAR"},
            {"_id": str(_uuid4()), "name": "Poubelle", "short_name": "DEMO_MYSTERE"},
            {"_id": str(_uuid4()), "name": "Cotisation 20000/mois", "short_name": "COTIS"},
        ]

        class _Produits:
            async def inventaire(self):  # type: ignore[no-untyped-def]
                return list(plateforme)

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_inventaire, "_client_produits", lambda: _Produits())

        await _registre_vierge()
        audit = AuditTrailRepository()
        for pid, nom in ((du_run, "Tontine Digitale"), (disparu, "Epargne Bloquee")):
            async with audit.intention(
                RUN_ADMIN, entity_type="Product", entity_id=_uuid4(),
                operation="CREATE", cible="product-service",
                payload={"name": nom},
            ) as suivi:
                suivi.reussi({"product_id": pid})
        await database.get_database()["loader_configuration"].update_one(
            {"_id": "produits_admin"},
            {"$set": {"produits": [
                {"name": "Warrantage", "short_name": "DEMO_WAR", "product_id": de_l_admin}
            ]}},
            upsert=True,
        )
        entetes = await _session_complete(client)

        reponse = await client.get("/admin/inventaire/produits", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert sorted(p["nom"] for p in corps["a_nous"]) == [
            "Tontine Digitale", "Warrantage",
        ]
        assert [p["nom"] for p in corps["disparu_la_bas"]] == ["Epargne Bloquee"]
        assert [p["short_name"] for p in corps["marque_mais_inconnu"]] == [
            "DEMO_MYSTERE"
        ]
        assert [p["nom"] for p in corps["etranger"]] == ["Cotisation 20000/mois"]
        assert corps["anomalies"] == 2

    async def test_companies_reconnues_par_le_registre_des_lenders(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        from app.routes import admin_inventaire

        notre, disparue = str(_uuid4()), str(_uuid4())
        plateforme = [
            {"_id": notre, "name": "Baobab Finance", "short_name": "DEMO_BAOBAB"},
            {"_id": str(_uuid4()), "name": "Orpheline", "short_name": "DEMO_ORPHE"},
            {"_id": str(_uuid4()), "name": "Vraie Banque", "short_name": "VB"},
        ]

        class _Companies:
            async def lister_companies(self):  # type: ignore[no-untyped-def]
                return list(plateforme)

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            admin_inventaire, "_client_companies", lambda: _Companies()
        )
        registre = database.get_database()["lenders_registry"]
        await registre.delete_many({})
        await registre.insert_many(
            [
                {"_id": str(_uuid4()), "company_id": notre, "lender_type": "IMF"},
                {"_id": str(_uuid4()), "company_id": disparue, "lender_type": "IMF"},
            ]
        )
        entetes = await _session_complete(client)
        try:
            reponse = await client.get("/admin/inventaire/companies", headers=entetes)
            assert reponse.status_code == 200, reponse.text
            corps = reponse.json()
            assert [c["nom"] for c in corps["a_nous"]] == ["Baobab Finance"]
            assert [c["id"] for c in corps["disparu_la_bas"]] == [disparue]
            assert [c["short_name"] for c in corps["marque_mais_inconnu"]] == [
                "DEMO_ORPHE"
            ]
            assert [c["nom"] for c in corps["etranger"]] == ["Vraie Banque"]
            assert corps["anomalies"] == 2, (
                "une company du registre absente la-bas est GRAVE — comptee"
            )
        finally:
            await registre.delete_many({})




async def _semer_telco(iso: str, nom: str, court: str, motif: str, part: float,
                       exemple: str) -> None:
    """Equipe un pays de test d'un operateur — la porte d'operation exige au
    moins un telco composable (calibrage 22/08)."""
    from pathlib import Path as _Path

    from app.repositories.surcouche import SurcoucheRepository
    from app.services.geographie import charger_referentiel as _charger

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    surcouche.ajouter_telco(
        _charger(_Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")),
        pays=iso, network_name=nom, short_name=court, regex_msisdn=motif,
        part_marche=part, exemple_msisdn=exemple,
    )
    await depot.enregistrer(surcouche, par="import-test")


async def _semer_fiche_pays(**champs: Any) -> None:
    """Seme une fiche pays comme l'IMPORT BACKEND le fait — la seule porte
    d'entree des pays depuis la decision direction du 22/08 (plus de POST)."""
    from pathlib import Path as _Path

    from app.repositories.surcouche import SurcoucheRepository
    from app.services.geographie import charger_referentiel as _charger

    depot = SurcoucheRepository()
    surcouche, _ = await depot.charger()
    surcouche.ajouter_pays(
        _charger(_Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")), **champs
    )
    await depot.enregistrer(surcouche, par="import-test")


class TestV02LeBoutonPousserNeMentPlus:
    """`V-02` (23/08, Yaniv) — l'ecran affichait un bouton « Pousser »
    cliquable sur des pays que la porte refusait ensuite en 422 : un clic pour
    une erreur. La regle etait ecrite DEUX fois — une dans la porte, une dans
    l'ecran — et deux ecritures d'une meme regle finissent par diverger.

    Elle vit maintenant a UN seul endroit, et `GET /pays` la porte."""

    async def test_un_pays_SANS_telco_n_est_PAS_poussable_et_le_dit(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="GA", nom_fr="Gabon", nom_en="Gabon", capitale="Libreville",
            dial_code="241", devise_iso="XAF", tva_percent=18.0,
        )
        fiches = (await client.get("/admin/referentiels/pays", headers=entetes)).json()
        gabon = next(p for p in fiches["pays"] if p["iso2"] == "GA")
        assert gabon["poussable"] is False, gabon
        assert "AUCUN operateur telecom" in gabon["manques"], gabon["manques"]

    async def test_l_ECRAN_et_la_PORTE_disent_la_MEME_chose(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Le test qui empeche la divergence de revenir : ce que l'ecran
        annonce non poussable, la porte doit le refuser — et l'inverse."""
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="GA", nom_fr="Gabon", nom_en="Gabon", capitale="Libreville",
            dial_code="241", devise_iso="XAF", tva_percent=18.0,
        )
        fiches = (await client.get("/admin/referentiels/pays", headers=entetes)).json()
        for fiche in fiches["pays"]:
            reponse = await client.post(
                f"/admin/referentiels/pays/{fiche['iso2']}/pousser", headers=entetes
            )
            if fiche["poussable"]:
                assert reponse.status_code != 422, (
                    f"{fiche['iso2']} annonce poussable mais la porte refuse : "
                    f"{reponse.text[:200]}"
                )
            else:
                assert reponse.status_code == 422, (
                    f"{fiche['iso2']} annonce NON poussable mais la porte accepte"
                )

    async def test_un_pays_COMPLET_est_poussable_avec_ses_avertissements(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Un avertissement ne bloque PAS : un marche a un seul operateur
        opere, il ne ressemble simplement a aucun marche africain."""
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="TG", nom_fr="Togo", nom_en="Togo", capitale="Lomé",
            dial_code="228", devise_iso="XOF", tva_percent=18.0,
        )
        await _semer_telco(
            "TG", "Togocom", "TGCOM", r"^228(9[0-9]\d{6})$", 30.0, "22890123456"
        )
        fiches = (await client.get("/admin/referentiels/pays", headers=entetes)).json()
        togo = next(p for p in fiches["pays"] if p["iso2"] == "TG")
        assert togo["poussable"] is True, togo
        assert togo["manques"] == []
        assert any("un seul operateur" in a for a in togo["avertissements"])


class TestUSB6CreationDePays:
    """CONSOLIDATION 22/08 — un seul sens par verbe : POST /pays CREE dans le
    Loader ; POST /pays/{iso}/pousser MET EN OPERATION sur config-service,
    depuis NOTRE fiche (rien n'est ressaisi — le Loader sait quoi envoyer)."""

    _GABON_FICHE: ClassVar[dict[str, Any]] = {
        "iso2": "GA", "nom_fr": "Gabon", "nom_en": "Gabon",
        "capitale": "Libreville", "dial_code": "241", "devise_iso": "XAF",
        "tva_percent": 18.0, "timezone": "Africa/Libreville",
        "region_africa": "Middle Africa",
    }

    async def _fiche_gabon(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(**self._GABON_FICHE)
        return entetes

    async def test_un_pays_sans_telco_ne_se_pousse_PAS(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Porte de completude (22/08) : EN OPERATION = UTILISABLE. Sans
        operateur, aucun numero composable (EF-27) — on ne pousse pas une
        coquille vide. Le refus NOMME la matiere manquante."""
        entetes = await self._fiche_gabon(client)
        reponse = await client.post(
            "/admin/referentiels/pays/GA/pousser", headers=entetes
        )
        assert reponse.status_code == 422, reponse.text
        assert "AUCUN operateur telecom" in reponse.json()["detail"]
        assert _config_service_double["pays_crees"] == [], "rien ne part"

    async def test_pousser_fait_l_aller_COMPLET_devise_pays_villes_telcos(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """L'ordre du contrat config-service : devise -> pays+villes ->
        telcos CREES puis RATTACHES (US-B7 : un telco non rattache
        n'appartient a aucun pays). Les parts de marche restent CHEZ NOUS."""
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="GN", nom_fr="Guinée", nom_en="Guinea", capitale="Conakry",
            dial_code="224", devise_iso="GNF", tva_percent=18.0,
            devise_nom="Guinean Franc", devise_decimales=0, banque_centrale="BCRG",
        )
        # un telco du pays, comme la vague 2 l'a fait (via le service)
        from pathlib import Path as _Path

        from app.repositories.surcouche import SurcoucheRepository
        from app.services.geographie import charger_referentiel as _charger

        depot = SurcoucheRepository()
        surcouche, _ = await depot.charger()
        surcouche.ajouter_telco(
            _charger(_Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")),
            pays="GN", network_name="Orange Guinee", short_name="Orange GN",
            regex_msisdn=r"^224(62\d{7}|61\d{7})$", part_marche=65.0,
            exemple_msisdn="224621234567",
        )
        await depot.enregistrer(surcouche, par="import-test")

        reponse = await client.post(
            "/admin/referentiels/pays/GN/pousser", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["statut"] == "mis_en_operation"
        assert corps["devise"]["statut"] == "mise_en_operation"  # GNF absent la-bas
        assert corps["echecs"] == []
        assert corps["telcos"] == [
            {"nom": "Orange Guinee", "statut": "mis_en_operation", "rattache": True}
        ]
        assert _config_service_double["crees"] == ["Orange Guinee"], (
            "le telco est CREE la-bas AVANT le pays, depuis NOTRE plan"
        )
        assert _config_service_double["pays_crees"][0]["telcos"] == [
            "tl-Orange Guinee"
        ], "le payload du pays reference le telco par UUID — l'ordre du contrat"
        assert _config_service_double["rattaches"] == [], (
            "a la CREATION le payload porte deja les telcos — le rattachement "
            "apres coup ne sert qu'au cas adoption"
        )

    async def test_pousser_un_pays_deja_en_operation_est_idempotent(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays/CM/pousser", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["statut"] == "deja_en_operation"
        assert _config_service_double["pays_crees"] == [], "aucun doublon cree"

    async def test_une_devise_absente_labas_est_CREEE_depuis_notre_fiche(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="NG", nom_fr="Nigéria", nom_en="Nigeria", capitale="Abuja",
            dial_code="234", devise_iso="NGN", tva_percent=7.5,
            devise_nom="Naira", devise_decimales=2, banque_centrale="CBN",
        )
        await _semer_telco(
            "NG", "MTN Nigeria", "MTN NG", r"^234(803\d{7})$", 36.0, "2348031234567"
        )
        reponse = await client.post(
            "/admin/referentiels/pays/NG/pousser", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["devise"]["statut"] == "mise_en_operation"
        assert _config_service_double["devises_creees"][0]["iso_name"] == "NGN"
        assert _config_service_double["devises_creees"][0]["accepts_decimal"] is True

    async def test_un_pays_sans_ville_NI_capitale_ne_se_pousse_PAS(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Trou attrape le 23/08 : `villes or [capitale]` avec une capitale
        VIDE envoyait `cities: [""]` — une ville fantome, INEFFACABLE la-bas
        (config-service n'a aucun DELETE sur les villes)."""
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="TD", nom_fr="Tchad", nom_en="Chad", capitale="",
            dial_code="235", devise_iso="XAF", tva_percent=18.0,
        )
        await _semer_telco(
            "TD", "Airtel Tchad", "Airtel TD", r"^235(6[0-9]\d{6})$", 60.0,
            "23561234567"
        )
        reponse = await client.post(
            "/admin/referentiels/pays/TD/pousser", headers=entetes
        )
        assert reponse.status_code == 422, reponse.text
        assert "AUCUNE ville ni capitale" in reponse.json()["detail"]
        assert _config_service_double["pays_crees"] == [], "rien ne part"
        assert _config_service_double["crees"] == [], (
            "la porte parle AVANT le reseau — aucun telco cree pour rien"
        )

    async def test_les_avertissements_de_credibilite_sont_DITS(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Calibrage 22/08 : un marche a UN operateur qui couvre 30 % opere,
        mais ne ressemble a aucun marche africain. Non bloquant, TOUJOURS dit
        — sans ce test, un refactor supprimerait les avertissements en
        silence."""
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="TG", nom_fr="Togo", nom_en="Togo", capitale="Lomé",
            dial_code="228", devise_iso="XOF", tva_percent=18.0,
        )
        await _semer_telco(
            "TG", "Togocom", "TGCOM", r"^228(9[0-9]\d{6})$", 30.0, "22890123456"
        )
        reponse = await client.post(
            "/admin/referentiels/pays/TG/pousser", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        avertissements = reponse.json()["avertissements"]
        assert any("un seul operateur" in a for a in avertissements), avertissements
        assert any("30 % < 50 %" in a for a in avertissements), avertissements

    async def test_un_marche_credible_ne_declenche_AUCUN_avertissement(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="ML", nom_fr="Mali", nom_en="Mali", capitale="Bamako",
            dial_code="223", devise_iso="XOF", tva_percent=18.0,
        )
        await _semer_telco(
            "ML", "Orange Mali", "OML", r"^223(7[0-9]\d{6})$", 55.0, "22370123456"
        )
        await _semer_telco(
            "ML", "Moov Africa Malitel", "MAM", r"^223(6[0-9]\d{6})$", 40.0,
            "22360123456"
        )
        reponse = await client.post(
            "/admin/referentiels/pays/ML/pousser", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["avertissements"] == [], reponse.json()

    async def test_un_echec_en_chemin_DIT_les_residus_laisses_la_bas(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mesure du 23/08 sur la PROD : `AOA` et `GNF` trainaient sur
        config-service sans aucun pays — nees d'un aller interrompu APRES la
        creation de la devise. Le 502 doit NOMMER ce qui reste."""
        from app.clients.base import ErreurService
        from app.routes import admin_referentiels

        class _AdminQuiEchoueAuPays:
            async def resoudre_devise(self, code_iso):  # type: ignore[no-untyped-def]
                return None

            async def creer_devise_si_absent(self, payload):  # type: ignore[no-untyped-def]
                return {"id": "cur-new", "iso_name": payload["iso_name"]}, True

            async def creer_telco_si_absent(self, nom, phone_regex):  # type: ignore[no-untyped-def]
                return {"id": f"tl-{nom}", "name": nom}, True

            async def creer_pays_si_absent(self, payload):  # type: ignore[no-untyped-def]
                raise ErreurService(
                    service="config-service",
                    methode="POST",
                    url="/api/v1/countries/create",
                    status=400,
                    detail="dial_code deja utilise",
                    request_id="qa-23-08",
                )

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            admin_referentiels, "_config_admin", lambda: _AdminQuiEchoueAuPays()
        )
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="RW", nom_fr="Rwanda", nom_en="Rwanda", capitale="Kigali",
            dial_code="250", devise_iso="RWF", tva_percent=18.0,
            devise_nom="Rwandan Franc", devise_decimales=0, banque_centrale="BNR",
        )
        await _semer_telco(
            "RW", "MTN Rwanda", "MTN RW", r"^250(78\d{7})$", 60.0, "250781234567"
        )
        reponse = await client.post(
            "/admin/referentiels/pays/RW/pousser", headers=entetes
        )
        assert reponse.status_code == 502, reponse.text
        detail = reponse.json()["detail"]
        assert "dial_code deja utilise" in detail, "le refus COMPLET voyage"
        assert "devise RWF" in detail and "MTN Rwanda" in detail, (
            "les residus crees la-bas sont NOMMES"
        )
        assert "Re-pousser RW" in detail, "le geste de rattrapage est dit"

    async def test_pousser_un_pays_inconnu_du_loader_est_un_422(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        reponse = await client.post(
            "/admin/referentiels/pays/ZZ/pousser", headers=entetes
        )
        assert reponse.status_code == 422
        assert "inconnu du Loader" in reponse.json()["detail"]
        assert _config_service_double["pays_crees"] == [], "rien ne part"

    async def test_la_mise_en_operation_est_journalisee_sous_RUN_ADMIN(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN

        await _registre_vierge()
        entetes = await self._fiche_gabon(client)
        await _semer_telco(
            "GA", "Airtel Gabon", "Airtel GA", r"^241(0[2467]\d{6})$", 55.0,
            "24102123456"
        )
        reponse = await client.post(
            "/admin/referentiels/pays/GA/pousser", headers=entetes
        )
        assert reponse.status_code == 200
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        assert any(
            e.entity_type == "Country" and e.action == "INTENTION" for e in journal
        ), "la mise en operation laisse SA trace write-ahead"

    async def test_le_verrou_EF_55_couvre_la_mise_en_operation(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        entetes = await _session_complete(client)
        await database.get_database().drop_collection("loader_runs")
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=_uuid4(), sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.RUNNING,
            )
        )
        try:
            reponse = await client.post(
                "/admin/referentiels/pays/CM/pousser", headers=entetes
            )
            assert reponse.status_code == 409
            assert "EF-55" in reponse.json()["detail"]
        finally:
            await database.get_database().drop_collection("loader_runs")

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.post("/admin/referentiels/pays/GA/pousser")
        assert reponse.status_code == 401


class TestCreationDeMonnaie:
    """DECISION 22/08 — la creation manuelle de monnaie N'EXISTE PLUS : les
    devises entrent par l'import backend, et POST /pays/{iso}/pousser cree
    la devise sur config-service depuis NOTRE fiche quand elle y manque
    (prouve par TestUSB6CreationDePays)."""

    async def test_la_creation_manuelle_de_monnaie_n_existe_plus(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/devises",
            json={"iso_name": "NGN", "name_en": "Naira", "name_fr": "Naira",
                  "accepts_decimal": True},
            headers=entetes,
        )
        assert reponse.status_code == 404, reponse.text

class TestRegionsQuartiersSansLimite:
    """Decision Yaniv 14/08 : « le nombre que l'on veut, pas de barrieres
    fixes — juste la consistance et la non-duplication. » Et le Loader SAIT
    quoi envoyer : la ville part la-bas, region et quartier restent chez nous
    avec la RAISON dite dans la reponse."""

    @staticmethod
    async def _surcouche_vierge() -> None:
        await database.get_database()["loader_configuration"].delete_one(
            {"_id": "surcouche"}
        )

    async def test_la_chaine_complete_region_ville_quartier(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """L'admin CONSTITUE sa geographie : region -> ville -> quartier.
        Chaque niveau dit s'il part la-bas, et pourquoi."""
        await self._surcouche_vierge()
        entetes = await _session_complete(client)

        region = await client.post(
            "/admin/referentiels/regions",
            json={"pays": "CM", "nom": "Region Test G", "capitale": "Ville Test G"},
            headers=entetes,
        )
        assert region.status_code == 201, region.text
        assert region.json()["config_service"]["envoye"] is False
        assert "region CONTINENTALE" in region.json()["config_service"]["raison"]

        ville = await client.post(
            "/admin/referentiels/villes",
            json={"region_id": region.json()["region"]["id"], "nom": "Ville Test G"},
            headers=entetes,
        )
        assert ville.status_code == 201, ville.text
        assert _config_service_double["villes"], "la VILLE, elle, part a config-service"

        quartier = await client.post(
            "/admin/referentiels/quartiers",
            json={"city_id": ville.json()["ville"]["id"], "nom": "Quartier Test G"},
            headers=entetes,
        )
        assert quartier.status_code == 201, quartier.text
        assert quartier.json()["config_service"]["envoye"] is False
        assert "Kiosque" in quartier.json()["config_service"]["raison"]
        await self._surcouche_vierge()

    async def test_aucune_barriere_fixe_quinze_regions_d_affilee(
        self, client: httpx.AsyncClient
    ) -> None:
        await self._surcouche_vierge()
        entetes = await _session_complete(client)
        for rang in range(15):
            reponse = await client.post(
                "/admin/referentiels/regions",
                json={"pays": "SN", "nom": f"Region Sans Limite {rang}"},
                headers=entetes,
            )
            assert reponse.status_code == 201, (
                f"la {rang + 1}e region est refusee — une barriere fixe existe : "
                f"{reponse.text}"
            )
        await self._surcouche_vierge()

    async def test_les_seuls_refus_sont_des_invariants(
        self, client: httpx.AsyncClient
    ) -> None:
        await self._surcouche_vierge()
        entetes = await _session_complete(client)
        premier = await client.post(
            "/admin/referentiels/regions",
            json={"pays": "CM", "nom": "Region Doublon"},
            headers=entetes,
        )
        assert premier.status_code == 201
        doublon = await client.post(
            "/admin/referentiels/regions",
            json={"pays": "CM", "nom": "Region Doublon"},
            headers=entetes,
        )
        assert doublon.status_code == 422
        assert "existe deja" in doublon.json()["detail"]
        orphelin = await client.post(
            "/admin/referentiels/regions",
            json={"pays": "GA", "nom": "Region Sans Pays"},
            headers=entetes,
        )
        assert orphelin.status_code == 422, "EF-02 : le pays parent doit exister"
        fantome = await client.post(
            "/admin/referentiels/quartiers",
            json={"city_id": "CM-CT-INEXISTANTE", "nom": "Quartier Fantome"},
            headers=entetes,
        )
        assert fantome.status_code == 422, "EF-02 : la ville parente doit exister"
        await self._surcouche_vierge()


class TestPermissionsEtCreationDeGroupe:
    """Decision Yaniv 14/08 : voir les permissions et CREER un groupe depuis
    l'ecran — avec tout ce que ca implique (D-06/D-09/A4), et l'unicite chez
    NOUS puisque le serveur n'en a aucune."""

    @staticmethod
    def _doubler_users(
        monkeypatch: pytest.MonkeyPatch,
        groupes: list[dict[str, Any]] | None = None,
        *,
        sans_id: bool = False,
        muet: bool = False,
    ) -> dict[str, Any]:
        from uuid import uuid4 as _uuid4

        from app.routes import admin_entites, admin_referentiels

        etat: dict[str, Any] = {"groupes": list(groupes or []), "crees": []}

        class _Users:
            async def lister_permissions(self):  # type: ignore[no-untyped-def]
                return ["CLIENT_CLIENT_ONBOARD", "USER_USER_CREATE"]

            async def chercher_groupe(self, nom):  # type: ignore[no-untyped-def]
                cible = nom.strip().lower()
                for g in etat["groupes"]:
                    if str(g.get("name", "")).strip().lower() == cible:
                        return g
                return None

            async def creer_groupe(self, **kwargs):  # type: ignore[no-untyped-def]
                if sans_id:
                    return {}
                groupe = {
                    "_id": str(_uuid4()),
                    "name": kwargs["nom"],
                    "tag": kwargs["tag"].value,
                    "permissions": kwargs["permissions"],
                }
                etat["crees"].append(groupe)
                if not muet:
                    etat["groupes"].append(groupe)
                return groupe

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_entites, "_client_users", lambda: _Users())
        monkeypatch.setattr(admin_referentiels, "_client_users", lambda: _Users())
        return etat

    async def test_les_permissions_se_lisent_depuis_l_ecran(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_users(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/referentiels/permissions", headers=entetes)
        assert reponse.status_code == 200
        assert reponse.json()["compte"] == 2
        assert "LENDER" in reponse.json()["note"], "l'ecartement D-07 est DIT"

    async def test_creer_un_groupe_l_inscrit_au_registre(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.inventaire import registre_groupes

        etat = self._doubler_users(monkeypatch)
        await _registre_vierge()
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={
                "nom": "Auditeur Externe",
                "description": "Lecture seule pour les audits bailleurs",
                "tag": "STAFF",
                "permissions": ["CLIENT_CLIENT_ONBOARD"],
            },
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert corps["statut"] == "a_nous"
        gid = corps["groupe"]["id"]
        assert etat["crees"][0]["_id"] == gid
        registre = await registre_groupes()
        assert registre.get(gid) == "Auditeur Externe", (
            "sans cette ligne, le groupe serait invisible a la reconciliation"
        )

    async def test_homonyme_a_nous_409_reutiliser_jamais_doubler(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        gid = str(_uuid4())
        self._doubler_users(monkeypatch, [{"_id": gid, "name": "Agent"}])
        await _registre_vierge()
        await _inscrire_groupe_au_registre(gid, "Agent")
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={"nom": "Agent", "description": "doublon tente", "tag": "COMPANY"},
            headers=entetes,
        )
        assert reponse.status_code == 409
        assert "A NOUS" in reponse.json()["detail"]
        assert gid in reponse.json()["detail"], "l'identite de l'existant est rendue"

    async def test_homonyme_etranger_409_ni_consomme_ni_recree(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        self._doubler_users(monkeypatch, [{"_id": str(_uuid4()), "name": "CUSTOMER"}])
        await _registre_vierge()
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={"nom": "CUSTOMER", "description": "collision", "tag": "CUSTOMER"},
            headers=entetes,
        )
        assert reponse.status_code == 409
        assert "ETRANGER" in reponse.json()["detail"]

    async def test_permission_inconnue_422_nommee_avant_tout_POST(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler_users(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={
                "nom": "Groupe Errone",
                "description": "permission qui n'existe pas",
                "tag": "STAFF",
                "permissions": ["PERMISSION_INVENTEE"],
            },
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "PERMISSION_INVENTEE" in reponse.json()["detail"]
        assert etat["crees"] == [], "refus AVANT le POST — rien n'est parti"

    async def test_le_tag_ROOT_est_refuse_en_ecriture(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_users(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={"nom": "Racine", "description": "tentative ROOT", "tag": "ROOT"},
            headers=entetes,
        )
        assert reponse.status_code == 422, "A4 : ROOT jamais en ecriture"

    async def test_un_serveur_sans_identifiant_502_et_journal_ECHEC(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN

        self._doubler_users(monkeypatch, sans_id=True)
        await _registre_vierge()
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={"nom": "Intracable", "description": "reponse vide", "tag": "STAFF"},
            headers=entetes,
        )
        assert reponse.status_code == 502
        assert "INTRACABLE" in reponse.json()["detail"].upper()
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        statuts = [
            (e.after or {}).get("statut")
            for e in journal
            if e.action == "RESULTAT" and e.entity_type == "Group"
        ]
        assert "ECHEC" in statuts

    async def test_un_serveur_qui_repond_sans_lister_502(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_users(monkeypatch, muet=True)
        await _registre_vierge()
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={"nom": "Invisible", "description": "cree mais absent", "tag": "STAFF"},
            headers=entetes,
        )
        assert reponse.status_code == 502
        assert "relecture" in reponse.json()["detail"]


class TestR01LeDernierRunEstLePlusRECENT:
    """`R-01` (24/08) — « le dernier run » n'existait pas.

    `lister()` triait sur `_id`, en promettant « du plus recent au plus
    ancien ». Or `_id` est un UUID4 : ALEATOIRE. Le tri ne donnait aucune
    chronologie, et `_dernier_run()` rendait un run TIRE AU HASARD.

    Consequence MESUREE le 24/08 : apres un REAL qui avait cree 500 clients,
    le tableau de bord, l'ecosysteme, la population et l'index inverse
    affichaient TOUS zero — ils lisaient la preparation DRY_RUN, qui n'ecrit
    rien. Et deux personnes pouvaient voir deux runs differents au meme
    instant, ce qui interdit a l'ecran d'etre une source de confiance."""

    async def test_l_historique_est_CHRONOLOGIQUE_pas_alphabetique_sur_l_uuid(
        self, client: httpx.AsyncClient
    ) -> None:
        import asyncio
        from datetime import date as _date

        from app.models.enums import RunMode
        from app.repositories.loader_runs import LoaderRunRepository

        await database.get_database().drop_collection("loader_runs")
        depot = LoaderRunRepository()
        ordre = []
        for _ in range(6):
            run = await depot.creer(
                sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1),
                mode=RunMode.DRY_RUN,
            )
            ordre.append(run.id)
            await asyncio.sleep(0.01)  # horodatages distincts

        listes = await depot.lister(limite=10)
        assert [r.id for r in listes] == list(reversed(ordre)), (
            "du plus RECENT au plus ancien — un tri sur l'UUID donnerait un "
            "ordre aleatoire, et « le dernier run » serait un run au hasard"
        )

    async def test_deux_lectures_rendent_le_MEME_ordre(
        self, client: httpx.AsyncClient
    ) -> None:
        """Un ecran qui change d'ordre a chaque rafraichissement n'est pas une
        source de confiance. `_id` departage en second, de facon STABLE."""
        from datetime import date as _date

        from app.models.enums import RunMode
        from app.repositories.loader_runs import LoaderRunRepository

        await database.get_database().drop_collection("loader_runs")
        depot = LoaderRunRepository()
        for _ in range(5):
            await depot.creer(
                sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1),
                mode=RunMode.DRY_RUN,
            )
        premiere = [r.id for r in await depot.lister(limite=10)]
        seconde = [r.id for r in await depot.lister(limite=10)]
        assert premiere == seconde

    async def test_un_run_SANS_horodatage_n_est_pas_perdu(
        self, client: httpx.AsyncClient
    ) -> None:
        """Les runs anterieurs au champ n'ont pas de date. Ils passent APRES,
        jamais a la trappe — l'historique est append-only (CR-06)."""
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.core.database import COLLECTION_LOADER_RUNS
        from app.models.domain import LoaderRun
        from app.models.enums import RunMode, RunStatus
        from app.repositories.base import en_document
        from app.repositories.loader_runs import LoaderRunRepository

        await database.get_database().drop_collection("loader_runs")
        ancien = _uuid4()
        document = en_document(
            LoaderRun(
                _id=ancien, sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.COMPLETED,
            )
        )
        document.pop("cree_le", None)  # exactement un run d'AVANT le champ
        await database.get_database()[COLLECTION_LOADER_RUNS].insert_one(document)

        depot = LoaderRunRepository()
        recent = await depot.creer(
            sim_start_date=_date(2026, 2, 1),
            sim_end_date=_date(2026, 8, 1),
            mode=RunMode.REAL,
        )
        listes = await depot.lister(limite=10)
        assert [r.id for r in listes] == [recent.id, ancien], (
            "le run horodate d'abord, l'ancien ensuite — et AUCUN n'est perdu"
        )


class TestR01RattrapageDesAnciensRuns:
    """`R-01` — les runs crees AVANT `cree_le` sont rattrapes au demarrage,
    depuis leur PREMIER checkpoint. La date n'est jamais inventee : c'est
    l'instant ou le run a reellement commence a s'executer."""

    async def test_la_date_vient_du_PREMIER_checkpoint(
        self, client: httpx.AsyncClient
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.core import database as db
        from app.core.database import COLLECTION_LOADER_RUNS
        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.base import en_document
        from app.repositories.loader_runs import LoaderRunRepository

        await database.get_database().drop_collection("loader_runs")
        ancien = _uuid4()
        document = en_document(
            LoaderRun(
                _id=ancien, sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.COMPLETED,
                checkpoints=[
                    {"phase": "ROLES", "horodatage": "2026-08-24T09:06:34.402707+00:00"},
                    {"phase": "CLIENTS", "horodatage": "2026-08-24T09:12:00+00:00"},
                ],
            )
        )
        document.pop("cree_le", None)
        await database.get_database()[COLLECTION_LOADER_RUNS].insert_one(document)

        await db.rattraper_horodatage_des_runs()

        relu = await LoaderRunRepository().obtenir(ancien)
        assert relu is not None and relu.cree_le is not None
        assert relu.cree_le.isoformat().startswith("2026-08-24T09:06:34"), (
            "le PREMIER checkpoint, pas le dernier — c'est le debut du run"
        )

    async def test_un_run_SANS_checkpoint_ne_recoit_AUCUNE_date(
        self, client: httpx.AsyncClient
    ) -> None:
        """On ne comble pas un trou par une valeur plausible."""
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.core import database as db
        from app.core.database import COLLECTION_LOADER_RUNS
        from app.models.domain import LoaderRun
        from app.models.enums import RunStatus
        from app.repositories.base import en_document
        from app.repositories.loader_runs import LoaderRunRepository

        await database.get_database().drop_collection("loader_runs")
        muet = _uuid4()
        document = en_document(
            LoaderRun(
                _id=muet, sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.FAILED,
            )
        )
        document.pop("cree_le", None)
        await database.get_database()[COLLECTION_LOADER_RUNS].insert_one(document)

        await db.rattraper_horodatage_des_runs()

        relu = await LoaderRunRepository().obtenir(muet)
        assert relu is not None and relu.cree_le is None


class TestV05PaysDeChaqueCompany:
    """`V-05` (24/08) — le formulaire de creation d'un depositaire doit
    n'offrir que les companies DU PAYS choisi. Le backend refusait deja « un
    kiosque a Douala pour une company de Dakar » (422 INCOHERENCE), mais
    l'ecran le proposait quand meme : une liste qui offre un choix impossible
    fait travailler l'utilisateur pour rien.

    La source est `lenders_registry`, qui porte `country_code` — pas une
    deduction depuis le nom."""

    async def test_le_pays_vient_du_REGISTRE_jamais_du_nom(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        from app.models.enums import LenderType
        from app.repositories.lenders_registry import LendersRegistryRepository
        from app.routes import admin_inventaire

        await _registre_vierge()
        await database.get_database().drop_collection("lenders_registry")
        camerounaise, sans_role = _uuid4(), _uuid4()
        await LendersRegistryRepository().enregistrer(
            company_id=camerounaise,
            lender_type=LenderType.LOCAL,
            country_code="CM",
        )

        class _Faux:
            async def lister_companies(self):  # type: ignore[no-untyped-def]
                return [
                    {"_id": str(camerounaise), "name": "IMF du Wouri", "short_name": "WOURI"},
                    {"_id": str(sans_role), "name": "Societe sans role", "short_name": "SSR"},
                ]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_inventaire, "_client_companies", lambda: _Faux())
        entetes = await _session_complete(client)
        corps = (
            await client.get("/admin/inventaire/companies", headers=entetes)
        ).json()
        toutes = [
            ligne
            for statut in corps
            if isinstance(corps[statut], list)
            for ligne in corps[statut]
        ]
        avec_pays = next(x for x in toutes if x["id"] == str(camerounaise))
        sans_pays = next(x for x in toutes if x["id"] == str(sans_role))
        assert avec_pays["pays"] == "CM", avec_pays
        assert sans_pays["pays"] is None, (
            "absente du registre : pays INCONNU, jamais devine depuis le nom"
        )


class TestV04DatesDeCreation:
    """`V-04` (23/08, demande administration) — la DATE de creation dans
    l'inventaire ET la purge.

    Devant un ecran de purge, la premiere question est « ca date de quand ? ».
    Un residu de la semaine derniere ne se traite pas comme une entite du run
    d'aujourd'hui — et on ne supprime pas a l'aveugle sur un ecosysteme ou
    trois services n'ont AUCUN DELETE.
    """

    async def test_une_entite_A_NOUS_porte_sa_date(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes import admin_inventaire
        from app.routes.admin_entites import RUN_ADMIN

        await _registre_vierge()
        groupe = _uuid4()
        audit = AuditTrailRepository()
        async with audit.intention(
            RUN_ADMIN, entity_type="Group", entity_id=groupe, operation="CREATE",
            cible="user-service", payload={"name": "Role Test V04"},
        ) as suivi:
            suivi.reussi({"group_id": str(groupe), "name": "Role Test V04"})

        class _Faux:
            async def lister_groupes(self):  # type: ignore[no-untyped-def]
                return [{"_id": str(groupe), "name": "Role Test V04"}]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_inventaire, "_client_users", lambda: _Faux())
        entetes = await _session_complete(client)
        corps = (
            await client.get("/admin/inventaire/groupes", headers=entetes)
        ).json()
        ligne = next(g for g in corps["a_nous"] if g["id"] == str(groupe))
        assert ligne["cree_le"], "la date vient du journal, seul a la connaitre"
        assert ligne["cree_le"].startswith("20"), ligne["cree_le"]

    async def test_une_entite_ETRANGERE_a_une_date_NULLE_jamais_inventee(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On ne connait la date que de ce que NOUS avons cree. Pour le reste
        la plateforme ne l'expose pas : `null` est une INFORMATION — pas de
        date, pas de nous."""
        from uuid import uuid4 as _uuid4

        from app.routes import admin_inventaire

        await _registre_vierge()
        etranger = str(_uuid4())

        class _Faux:
            async def lister_groupes(self):  # type: ignore[no-untyped-def]
                return [{"_id": etranger, "name": "Groupe d une autre equipe"}]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_inventaire, "_client_users", lambda: _Faux())
        entetes = await _session_complete(client)
        corps = (
            await client.get("/admin/inventaire/groupes", headers=entetes)
        ).json()
        ligne = next(g for g in corps["etranger"] if g["id"] == etranger)
        assert "cree_le" in ligne, "la cle est TOUJOURS presente"
        assert ligne["cree_le"] is None, "et vaut null — jamais une date inventee"


class TestP04ListeDesClientsFiltrable:
    """`P-04` (23/08) — la LISTE des clients, filtrable par pays, sexe et
    profession. Le dashboard rendait des DISTRIBUTIONS, jamais un client :
    « montre-moi les femmes agricultrices du Cameroun » n'avait pas de reponse.

    Le genre, la profession et la categorie sont NOS decisions de quota
    (EF-22/23/24), pas des donnees de la plateforme — les ranger avec le noeud
    ne cree aucune verite concurrente, et evite 200 requetes paginees vers
    identity-service (`D-IDN-3`, limit=10 par defaut) pour UN affichage.
    """

    async def _semer(self, run):  # type: ignore[no-untyped-def]
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.core.database import COLLECTION_ORG_HIERARCHY
        from app.models.domain import LoaderRun, OrgHierarchyNode
        from app.models.enums import NiveauOrganisation, RunStatus
        from app.repositories.base import en_document
        from app.repositories.loader_runs import LoaderRunRepository

        imf, kiosque_id = _uuid4(), _uuid4()
        await database.get_database().drop_collection("loader_runs")
        await database.get_database().drop_collection(COLLECTION_ORG_HIERARCHY)
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=run, sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.COMPLETED,
            )
        )
        arbre = database.get_database()[COLLECTION_ORG_HIERARCHY]
        noeuds = [
            OrgHierarchyNode(
                _id=kiosque_id, run_id=run, niveau=NiveauOrganisation.KIOSQUE,
                parent_id=_uuid4(), company_id=imf, name="Kiosque Elig-Essono",
                country_code="CM", district_id="CM-DT-001",
                city_id="CM-CT-01", depositary_id=_uuid4(),
            ),
        ]
        profils = [
            ("CM", "FEMALE", "Agricultrice", "INDIVIDUAL", "237670000001"),
            ("CM", "FEMALE", "Agricultrice", "INDIVIDUAL", "237670000002"),
            ("CM", "FEMALE", "Couturiere", "INDIVIDUAL", "237670000003"),
            ("CM", "MALE", "Agriculteur", "INDIVIDUAL", "237670000004"),
            ("SN", "FEMALE", "Agricultrice", "CORPORATE", "221770000005"),
        ]
        for pays, genre, metier, categorie, msisdn in profils:
            noeuds.append(
                OrgHierarchyNode(
                    _id=_uuid4(), run_id=run, niveau=NiveauOrganisation.CLIENT,
                    parent_id=kiosque_id, company_id=imf,
                    name=f"Client {msisdn}", country_code=pays,
                    client_id=_uuid4(), gender=genre, occupation=metier,
                    categorie=categorie, product_ids=[str(_uuid4())],
                )
            )
        await arbre.insert_many([en_document(n) for n in noeuds])

    async def test_les_trois_criteres_filtrent_ENSEMBLE(
        self, client: httpx.AsyncClient
    ) -> None:
        from uuid import uuid4 as _uuid4

        run = _uuid4()
        await self._semer(run)
        entetes = await _session_complete(client)
        reponse = await client.get(
            f"/admin/dashboard/clients?run_id={run}&pays=CM&genre=FEMALE"
            "&profession=agricultrice",
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["total"] == 2, corps
        assert {c["msisdn"] for c in corps["clients"]} == {
            "237670000001", "237670000002"
        }, corps["clients"]

    async def test_chaque_ligne_porte_le_NUMERO_et_sa_geographie(
        self, client: httpx.AsyncClient
    ) -> None:
        """Le msisdn est A NOUS : compose depuis le plan de numerotation reel
        et valide contre l'operateur (`EF-27`). La geographie est DERIVEE du
        Kiosque — jamais dupliquee sur le client, elle pourrait diverger."""
        from uuid import uuid4 as _uuid4

        run = _uuid4()
        await self._semer(run)
        entetes = await _session_complete(client)
        corps = (
            await client.get(
                f"/admin/dashboard/clients?run_id={run}&pays=CM", headers=entetes
            )
        ).json()
        ligne = corps["clients"][0]
        assert ligne["msisdn"].startswith("2376")
        assert ligne["client_id"] and ligne["genre"] and ligne["profession"]
        assert ligne["kiosque"] == "Kiosque Elig-Essono"
        assert ligne["ville"], "la ville remonte du Kiosque"

    async def test_les_FACETTES_disent_ce_qui_reste_derriere_chaque_filtre(
        self, client: httpx.AsyncClient
    ) -> None:
        """Un ecran qui propose un filtre sans dire ce qu'il reste derriere
        fait cliquer a l'aveugle."""
        from uuid import uuid4 as _uuid4

        run = _uuid4()
        await self._semer(run)
        entetes = await _session_complete(client)
        corps = (
            await client.get(
                f"/admin/dashboard/clients?run_id={run}&genre=FEMALE", headers=entetes
            )
        ).json()
        assert corps["total"] == 4
        assert corps["facettes"]["pays"] == {"CM": 3, "SN": 1}
        assert corps["facettes"]["profession"]["Agricultrice"] == 3
        assert corps["facettes"]["categorie"] == {"INDIVIDUAL": 3, "CORPORATE": 1}

    async def test_la_pagination_borne_la_reponse(
        self, client: httpx.AsyncClient
    ) -> None:
        from uuid import uuid4 as _uuid4

        run = _uuid4()
        await self._semer(run)
        entetes = await _session_complete(client)
        corps = (
            await client.get(
                f"/admin/dashboard/clients?run_id={run}&taille=2&page=1", headers=entetes
            )
        ).json()
        assert corps["total"] == 5
        assert len(corps["clients"]) == 2
        assert corps["pages"] == 3

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/admin/dashboard/clients")).status_code == 401


class TestIndexInverseCommeService:
    """`P-01` cote SERVICE : GET /admin/dashboard/index-inverse — deux
    agregations chez NOUS, jamais 20 requetes paginees vers FinZuu."""

    async def test_les_deux_questions_du_plan_recoivent_leur_reponse(
        self, client: httpx.AsyncClient
    ) -> None:
        from datetime import date as _date
        from uuid import uuid4 as _uuid4

        from app.core.database import COLLECTION_ORG_HIERARCHY
        from app.models.domain import LoaderRun, OrgHierarchyNode
        from app.models.enums import NiveauOrganisation, RunStatus
        from app.repositories.base import en_document
        from app.repositories.loader_runs import LoaderRunRepository

        run, imf = _uuid4(), _uuid4()
        produit, kiosque_id = _uuid4(), _uuid4()
        await database.get_database().drop_collection("loader_runs")
        await LoaderRunRepository().remplacer(
            LoaderRun(
                _id=run, sim_start_date=_date(2026, 2, 1),
                sim_end_date=_date(2026, 8, 1), status=RunStatus.COMPLETED,
            )
        )
        arbre = database.get_database()[COLLECTION_ORG_HIERARCHY]
        documents = [
            OrgHierarchyNode(
                _id=kiosque_id, run_id=run, niveau=NiveauOrganisation.KIOSQUE,
                parent_id=_uuid4(), company_id=imf, name="DEMO_Kiosque P01",
                country_code="CM", district_id="CM-DT-P01", depositary_id=_uuid4(),
            ),
            OrgHierarchyNode(
                _id=_uuid4(), run_id=run, niveau=NiveauOrganisation.PRODUIT,
                parent_id=None, company_id=imf, name="DEMO_TONTINE",
                country_code="CM", product_id=produit, package="READY_ALL",
            ),
        ]
        for rang in range(2):
            documents.append(
                OrgHierarchyNode(
                    _id=_uuid4(), run_id=run, niveau=NiveauOrganisation.CLIENT,
                    parent_id=kiosque_id, company_id=imf,
                    name=f"DEMO_Client 2379900P{rang}", country_code="CM",
                    client_id=_uuid4(), product_ids=[str(produit)],
                )
            )
        await arbre.insert_many([en_document(n) for n in documents])
        entetes = await _session_complete(client)
        try:
            reponse = await client.get(
                f"/admin/dashboard/index-inverse?run_id={run}", headers=entetes
            )
            assert reponse.status_code == 200, reponse.text
            corps = reponse.json()
            assert corps["clients_par_produit"] == [
                {"product_id": str(produit), "marqueur": "DEMO_TONTINE", "clients": 2}
            ], "« combien de clients par produit ? » — UNE requete, avec le nom"
            assert corps["clients_par_kiosque"] == [
                {"kiosque_id": str(kiosque_id), "nom": "DEMO_Kiosque P01", "clients": 2}
            ]
        finally:
            await arbre.delete_many({"run_id": str(run)})
            await database.get_database().drop_collection("loader_runs")


class TestJournalisationDesRoles:
    """Le trou du 13/08, ferme et prouve de bout en bout : les groupes crees
    en REAL par `ExecuteurRoles` etaient la SEULE ecriture non journalisee du
    moteur — sans prefixe ni journal, ils devenaient invisibles a la
    reconciliation. Ici : executer REAL -> le registre les connait."""

    async def test_un_run_REAL_inscrit_chaque_groupe_au_registre(
        self, client: httpx.AsyncClient
    ) -> None:
        from uuid import uuid4 as _uuid4

        from app.models.enums import RunMode
        from app.repositories.audit_trail import AuditTrailRepository
        from app.services.inventaire import registre_groupes
        from app.services.roles_execution import ExecuteurRoles

        class _Users:
            async def lister_permissions(self):  # type: ignore[no-untyped-def]
                return ["USER_USER_CREATE"]

            async def lister_groupes(self):  # type: ignore[no-untyped-def]
                return [{"name": "CUSTOMER"}]

            async def creer_groupe(self, **kwargs):  # type: ignore[no-untyped-def]
                return {"_id": str(_uuid4()), "name": kwargs["nom"]}

        await _registre_vierge()
        rapport = await ExecuteurRoles(
            mode=RunMode.REAL,
            user_client=_Users(),  # type: ignore[arg-type]
            audit=AuditTrailRepository(),
            run_id=_uuid4(),
        ).executer()

        registre = await registre_groupes()
        assert len(rapport.crees) == 11
        assert len(registre) == 11, (
            "chaque groupe cree est au registre — c'est notre SEULE memoire, "
            "les groupes ne portent aucun prefixe"
        )
        assert sorted(registre.values())[0], "le nom accompagne l'identifiant"


@pytest.fixture(autouse=True)
def _config_service_double(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """AUCUN test d'API ne parle au VRAI config-service : les fabriques du
    routeur sont doublees par defaut. Le double enregistre chaque geste —
    l'unicite dans les deux sens est verifiable sur ses traces."""
    from app.routes import admin_referentiels

    traces: dict[str, Any] = {
        "crees": [], "rattaches": [], "villes": [], "pays_crees": [],
        "devises_creees": [], "echec": None,
    }

    class _Lecture:
        async def lister_pays(self):  # type: ignore[no-untyped-def]
            return [
                {
                    "_id": f"cfg-{code}",
                    "iso_name": code,
                    "name_en": code,
                    "name_fr": code,
                    "dial_code": "237",
                    "region": "Africa",
                    "continent": "Africa",
                    "cities": [],
                    "currencies": ["cur-xaf"],
                    "telcos": [],
                }
                for code in ("CM", "CI", "BF", "SN")
            ]

        async def lister_telcos(self):  # type: ignore[no-untyped-def]
            return [{"_id": "tl-connu", "network_name": "Operateur Connu"}]

        async def lister_devises(self):  # type: ignore[no-untyped-def]
            return [
                {"_id": "cur-xaf", "iso_name": "XAF"},
                {"_id": "cur-xof", "iso_name": "XOF"},
            ]

        async def fermer(self):  # type: ignore[no-untyped-def]
            return None

    class _Admin:
        async def resoudre_devise(self, code_iso):  # type: ignore[no-untyped-def]
            return {"XOF": "cur-xof", "XAF": "cur-xaf"}.get(code_iso.upper())

        async def creer_devise_si_absent(self, payload):  # type: ignore[no-untyped-def]
            iso = str(payload.get("iso_name", "")).upper()
            if iso in ("XOF", "XAF"):  # deja en base -> pas de doublon
                return {"id": f"cur-{iso.lower()}", "iso_name": iso}, False
            traces["devises_creees"].append(payload)
            return {"id": f"cur-new-{iso}", "iso_name": iso}, True

        async def creer_pays_si_absent(self, payload):  # type: ignore[no-untyped-def]
            iso = str(payload.get("iso_name", "")).upper()
            if iso in ("CM", "CI", "BF", "SN"):  # deja en base -> pas de doublon
                return {"id": f"cfg-{iso}", "iso_name": iso}, False
            traces["pays_crees"].append(payload)
            return {"id": f"cfg-new-{iso}", "iso_name": iso}, True

        async def ajouter_ville(self, country_id, ville):  # type: ignore[no-untyped-def]
            if traces["echec"]:
                raise RuntimeError(traces["echec"])
            traces["villes"].append((country_id, ville))
            return {"_id": country_id, "cities": [ville]}

        async def ajouter_villes(self, country_id, villes):  # type: ignore[no-untyped-def]
            if traces["echec"] or traces.get("echec_villes"):
                raise RuntimeError(traces["echec"] or traces["echec_villes"])
            traces["villes"].extend((country_id, v) for v in villes)
            traces["lots"] = traces.get("lots", 0) + 1  # C3 : compte les ALLERS
            return {"_id": country_id, "cities": list(villes)}, list(villes)

        async def creer_telco_si_absent(self, nom, phone_regex):  # type: ignore[no-untyped-def]
            if traces["echec"]:
                raise RuntimeError(traces["echec"])
            traces["crees"].append(nom)
            return {"_id": f"tl-{nom}", "name": nom}, True

        async def rattacher_telco_au_pays(self, country_id, telco_id):  # type: ignore[no-untyped-def]
            traces["rattaches"].append((country_id, telco_id))
            return {"_id": country_id}

        async def fermer(self):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(admin_referentiels, "_config_admin", lambda: _Admin())
    monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())

    # `V-03` — l'ecosysteme CONFRONTE son arbre a depositary-service. Un test
    # qui touche le reseau est un mauvais test : il est lent, il depend d'un
    # service qui n'est pas sous test, et il echoue pour de mauvaises raisons.
    # On double donc aussi ce client. `lister()` rend une liste VIDE : la
    # plateforme ne porte AUCUN depositaire, ce qui est l'etat par defaut d'un
    # environnement de test — et c'est le cas le plus interessant, celui ou
    # l'arbre doit avouer que ses kiosques ont disparu.
    class _Depositaires:
        async def lister(self):  # type: ignore[no-untyped-def]
            return []

        async def fermer(self):  # type: ignore[no-untyped-def]
            return None

    monkeypatch.setattr(
        "app.clients.depositary_service.DepositaryServiceClient",
        lambda *a, **k: _Depositaires(),
    )
    return traces


class TestUSB7AjoutDeTelco:
    """`US-B7` — l'ALLER COMPLET : la surcouche locale PUIS config-service
    (creation + rattachement au pays), et les quatre invariants."""

    VALIDE: ClassVar[dict[str, Any]] = {
        "pays": "CM",
        "network_name": "Nexttel CM",
        "short_name": "Nexttel",
        "regex_msisdn": r"^237(66\d{7})$",
        "part_marche": 6.0,
        "exemple_msisdn": "237661234567",
    }

    async def _preparer(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        return entetes

    async def test_l_ajout_enregistre_CHEZ_NOUS_puis_ENVOIE_la_bas(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/referentiels/telcos", json=self.VALIDE, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert corps["telco"]["id"].startswith("SC-CM-TL-")
        assert corps["config_service"]["statut"] == "envoye"
        assert _config_service_double["crees"] == ["Nexttel CM"], (
            "le telco est CREE sur config-service (GET-avant-POST du client)"
        )
        assert _config_service_double["rattaches"] == [("cfg-CM", "tl-Nexttel CM")], (
            "PUIS rattache au pays — un telco non rattache n'appartient a personne"
        )
        # Et il participe au referentiel fusionne, avec la somme du marche.
        assert corps["somme_parts_du_pays"] == 98.0  # 92 + 6
        telcos = (
            await client.get("/admin/referentiels/telcos", headers=entetes)
        ).json()["telcos"]["CM"]
        assert any(t["nom"] == "Nexttel CM" for t in telcos)

    async def test_la_somme_des_parts_ne_depasse_JAMAIS_100(
        self, client: httpx.AsyncClient
    ) -> None:
        """INV-18 etendu a l'ecriture : CM porte deja 92 % — ajouter 9 %
        ferait 101, un marche qui n'existe pas."""
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/referentiels/telcos",
            json={**self.VALIDE, "part_marche": 9.0},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "101.0" in reponse.json()["detail"]

    async def test_le_plan_doit_etre_UTILISABLE_pas_seulement_present(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await self._preparer(client)
        incompilable = await client.post(
            "/admin/referentiels/telcos",
            json={**self.VALIDE, "regex_msisdn": "^23766[\\d{7}$"},
            headers=entetes,
        )
        assert incompilable.status_code == 422
        assert "incompilable" in incompilable.json()["detail"]

        exemple_faux = await client.post(
            "/admin/referentiels/telcos",
            json={**self.VALIDE, "exemple_msisdn": "699999999"},
            headers=entetes,
        )
        assert exemple_faux.status_code == 422
        assert "preuve" in exemple_faux.json()["detail"]

    async def test_le_doublon_est_refuse_AVANT_toute_ecriture(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """L'unicite COTE LOADER : MTN CM existe au classeur — le refus tombe
        avant la surcouche ET avant tout envoi serveur."""
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/referentiels/telcos",
            json={**self.VALIDE, "network_name": "MTN CM", "short_name": "MTN2"},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "existe deja" in reponse.json()["detail"]
        assert _config_service_double["crees"] == [], "AUCUN envoi n'est parti"

    async def test_un_echec_d_envoi_laisse_le_LOCAL_et_le_DIT(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Jamais silencieux : l'ajout local reste (notre trace d'abord), et
        le rapport porte l'echec d'envoi pour le rejouer plus tard."""
        _config_service_double["echec"] = "config-service indisponible"
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/referentiels/telcos", json=self.VALIDE, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert "echec" in corps["config_service"]["statut"]
        assert "RuntimeError" in corps["config_service"]["motif"]
        assert corps["telco"]["nom"] == "Nexttel CM", "le LOCAL est en place"

    async def test_la_ville_aussi_fait_l_aller_complet(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """US-B4 etendu : la ville part aussi vers config-service — et SEULE
        la ville : region et quartier restent chez nous (le serveur n'a aucun
        champ pour eux, son `region` est continentale)."""
        entetes = await self._preparer(client)
        regions = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()["pays"]
        region_cm = next(p for p in regions if p["pays"] == "CM")["regions"][0]["id"]
        reponse = await client.post(
            "/admin/referentiels/villes",
            json={"region_id": region_cm, "nom": "Bafia"},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        assert reponse.json()["config_service"]["statut"] == "envoye"
        assert _config_service_double["villes"] == [("cfg-CM", "Bafia")]


class TestComptesRBAC:
    """RBAC (decision Yaniv 15/08) — Super-Admin est un ROLE multi-comptes :
    chacun son email reel, son mot de passe, son cycle US-A2 ; desactivation
    reversible, jamais de suppression ; gardes anti-lock-out."""

    EMAIL_B = "collegue-tests@finzuu.com"

    @pytest.fixture(autouse=True)
    def _aucun_email_reel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AUCUN test n'emet de courrier reel — la route appelle le MODULE
        (mailjet.envoyer_email), on patche la fonction du module. Le faux
        rend False : le createur est le canal de secours, et c'est dit."""
        from app.clients import mailjet as module_mailjet

        async def faux_envoi(*_: object, **__: object) -> bool:
            return False

        monkeypatch.setattr(module_mailjet, "envoyer_email", faux_envoi)

    async def test_la_liste_montre_la_vue_publique_jamais_un_hash(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/comptes", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["compte"] == 1
        fiche = corps["comptes"][0]
        assert fiche["email"] == EMAIL
        assert fiche["actif"] is True
        assert "password_hash" not in fiche and "hash" not in str(fiche).lower()

    async def test_creer_un_compte_puis_son_cycle_A2_complet_et_independant(
        self, client: httpx.AsyncClient
    ) -> None:
        """LE coeur de la demande : un 2e compte nait, se connecte avec son
        mot de passe initial, le change LUI-MEME — et le compte du createur
        continue de fonctionner, intact."""
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/comptes", json={"email": self.EMAIL_B}, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        initial_b = corps["mot_de_passe_initial"]
        assert len(initial_b) >= 20
        assert corps["compte"]["must_change_password"] is True
        assert corps["compte"]["cree_par"] == EMAIL
        # Mailjet n'est pas provisionne dans les tests : l'envoi est FAUX dit,
        # jamais une exception — le createur est le canal de secours.
        assert corps["email_envoye"] is False

        connexion_b = await client.post(
            "/admin/auth/login",
            json={"email": self.EMAIL_B, "mot_de_passe": initial_b},
        )
        assert connexion_b.status_code == 200, connexion_b.text
        assert connexion_b.json()["must_change_password"] is True

        durable_b = "mon-durable-a-moi-15aout!"
        change_b = await client.post(
            "/admin/auth/password",
            json={"ancien": initial_b, "nouveau": durable_b},
            headers={
                "Authorization": f"Bearer {connexion_b.json()['access_token']}"
            },
        )
        assert change_b.status_code == 200, change_b.text

        # B se connecte avec SON durable ; A avec le SIEN — independants.
        assert (
            await client.post(
                "/admin/auth/login",
                json={"email": self.EMAIL_B, "mot_de_passe": durable_b},
            )
        ).status_code == 200
        assert (
            await client.post(
                "/admin/auth/login",
                json={"email": EMAIL, "mot_de_passe": MDP_DURABLE},
            )
        ).status_code == 200

    async def test_un_email_deja_porteur_est_un_409_jamais_un_doublon(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        assert (
            await client.post("/admin/comptes", json={"email": EMAIL}, headers=entetes)
        ).status_code == 409

    async def test_gardes_anti_lock_out_puis_desactivation_reelle(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        # Se desactiver soi-meme : refuse.
        soi = await client.put(
            f"/admin/comptes/{EMAIL}/etat",
            json={"actif": False, "motif": "test lock-out"},
            headers=entetes,
        )
        assert soi.status_code == 409
        # Creer B, le desactiver : accepte — et son login devient le MEME
        # 401 generique que des identifiants faux (rien a enumerer).
        creation = await client.post(
            "/admin/comptes", json={"email": self.EMAIL_B}, headers=entetes
        )
        initial_b = creation.json()["mot_de_passe_initial"]
        desactivation = await client.put(
            f"/admin/comptes/{self.EMAIL_B}/etat",
            json={"actif": False, "motif": "depart de l'equipe (test)"},
            headers=entetes,
        )
        assert desactivation.status_code == 200, desactivation.text
        assert desactivation.json()["compte"]["actif"] is False
        refus = await client.post(
            "/admin/auth/login",
            json={"email": self.EMAIL_B, "mot_de_passe": initial_b},
        )
        assert refus.status_code == 401
        assert refus.json()["detail"] == "identifiants invalides"
        # Reactivation : le mot de passe n'a pas change.
        reactivation = await client.put(
            f"/admin/comptes/{self.EMAIL_B}/etat",
            json={"actif": True, "motif": "retour (test)"},
            headers=entetes,
        )
        assert reactivation.status_code == 200
        assert (
            await client.post(
                "/admin/auth/login",
                json={"email": self.EMAIL_B, "mot_de_passe": initial_b},
            )
        ).status_code == 200

    async def test_le_dernier_compte_actif_est_indesactivable(
        self, client: httpx.AsyncClient
    ) -> None:
        """Meme un AUTRE admin ne peut pas eteindre la derniere lumiere."""
        entetes = await _session_complete(client)
        # Deux SUPER_ADMINS : l'anti-lock-out se joue entre porteurs du role,
        # et seul un super_admin peut desactiver (garde exige_super_admin).
        creation = await client.post(
            "/admin/comptes",
            json={"email": self.EMAIL_B, "role": "super_admin"},
            headers=entetes,
        )
        initial_b = creation.json()["mot_de_passe_initial"]
        connexion_b = await client.post(
            "/admin/auth/login",
            json={"email": self.EMAIL_B, "mot_de_passe": initial_b},
        )
        durable_b = "durable-de-b-15aout!"
        jeton_b = (
            await client.post(
                "/admin/auth/password",
                json={"ancien": initial_b, "nouveau": durable_b},
                headers={
                    "Authorization": f"Bearer {connexion_b.json()['access_token']}"
                },
            )
        ).json()["access_token"]
        entetes_b = {"Authorization": f"Bearer {jeton_b}"}
        # B desactive A (createur) : accepte, il reste B.
        assert (
            await client.put(
                f"/admin/comptes/{EMAIL}/etat",
                json={"actif": False, "motif": "test dernier actif"},
                headers=entetes_b,
            )
        ).status_code == 200
        # B tente de se desactiver : 409 soi-meme ; et A (desactive) ne
        # compte plus — B est le dernier actif.
        assert (
            await client.put(
                f"/admin/comptes/{self.EMAIL_B}/etat",
                json={"actif": False, "motif": "test"},
                headers=entetes_b,
            )
        ).status_code == 409


class TestInventaireDepositaires:
    """16/08 (question Yaniv « aura-t-on la visibilite ? ») — reconciliation
    des depositaires : registre = depositary_id des Kiosques d'org_hierarchy
    (UC-09), marqueur DEMO_ dans name, AUCUN supprimable (D-DEP-3)."""

    async def test_les_quatre_statuts_depuis_org_hierarchy_et_le_marqueur(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from uuid import uuid4 as _uuid4

        from app.routes import admin_inventaire

        du_run, disparu = str(_uuid4()), str(_uuid4())
        plateforme = [
            {"_id": du_run, "name": "DEMO_Kiosque Bonapriso", "currency": "XAF"},
            {"_id": str(_uuid4()), "name": "DEMO_Kiosque Mystere", "currency": "XAF"},
            {"_id": str(_uuid4()), "name": "Depositaire Metier", "currency": "XOF"},
        ]

        class _Depositaires:
            async def lister(self):  # type: ignore[no-untyped-def]
                return list(plateforme)

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            admin_inventaire, "_client_depositaires", lambda: _Depositaires()
        )

        org = database.get_database()["org_hierarchy"]
        await org.delete_many({})
        await org.insert_many(
            [
                {
                    "niveau": "KIOSQUE",
                    "depositary_id": du_run,
                    "name": "DEMO_Kiosque Bonapriso",
                },
                {
                    "niveau": "KIOSQUE",
                    "depositary_id": disparu,
                    "name": "DEMO_Kiosque Efface",
                },
            ]
        )
        entetes = await _session_complete(client)

        reponse = await client.get("/admin/inventaire/depositaires", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert [d["nom"] for d in corps["a_nous"]] == ["DEMO_Kiosque Bonapriso"]
        assert [d["nom"] for d in corps["disparu_la_bas"]] == ["DEMO_Kiosque Efface"]
        assert [d["nom"] for d in corps["marque_mais_inconnu"]] == [
            "DEMO_Kiosque Mystere"
        ]
        assert [d["nom"] for d in corps["etranger"]] == ["Depositaire Metier"]
        assert "D-DEP-3" in corps["note"], "l'insupprimabilite est DITE"
        await org.delete_many({})


class TestUSD3DepositaireALUnite:
    """US-D3 REFONDU (16/08, conception Yaniv) — le depositaire naît d'un
    QUARTIER + une company A NOUS : nom COMPOSE `DEMO_Kiosque <Quartier>`
    (EF-63), devise DERIVEE du pays (D-DEP-6), COHERENCE company<->quartier
    (pas de kiosque a Douala pour une company de Dakar), quartier LIBRE
    (un quartier = UN kiosque), GET-avant-POST (D-DEP-3), relecture."""

    @staticmethod
    def _un_quartier(pays: str = "CM") -> tuple[str, str]:
        """(district_id, nom) d'un quartier REEL du referentiel."""
        from app.routes.admin_referentiels import _geo

        referentiel = _geo()
        for ville in referentiel.villes.values():
            if ville.country_iso2 != pays:
                continue
            quartiers = referentiel.quartiers_de_ville(ville.city_id)
            if quartiers:
                return quartiers[0].district_id, quartiers[0].name
        raise AssertionError(f"aucun quartier pour {pays} dans le classeur")

    @staticmethod
    async def _company_a_nous(company_id: str) -> None:
        await database.get_database()["lenders_registry"].delete_many({})
        await database.get_database()["lenders_registry"].insert_one(
            {"company_id": company_id, "nom": "DEMO_SARL Test"}
        )

    @staticmethod
    def _doubler(
        monkeypatch: pytest.MonkeyPatch,
        *,
        fiche_company: dict | None = None,
        existants: list | None = None,
    ):
        from app.routes import admin_entites

        etat = {"liste": list(existants or []), "crees": []}

        class _Depositaires:
            async def lister(self):  # type: ignore[no-untyped-def]
                return list(etat["liste"])

            async def chercher_par_nom(self, nom):  # type: ignore[no-untyped-def]
                cible = nom.strip().lower()
                return next(
                    (d for d in etat["liste"] if str(d.get("name", "")).lower() == cible),
                    None,
                )

            async def creer(self, nom, devise, company_id):  # type: ignore[no-untyped-def]
                fiche = {"_id": f"dep-{len(etat['crees']) + 1}", "name": nom,
                         "currency": devise, "company_id": company_id}
                etat["crees"].append(fiche)
                etat["liste"].append(fiche)
                return fiche

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        class _Companies:
            async def obtenir_company(self, company_id):  # type: ignore[no-untyped-def]
                return dict(fiche_company) if fiche_company is not None else None

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            admin_entites, "_client_depositaires_unite", lambda: _Depositaires()
        )
        monkeypatch.setattr(
            admin_entites, "_client_companies_unite", lambda: _Companies()
        )
        return etat

    async def test_company_etrangere_403_avant_tout(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler(monkeypatch, fiche_company={"name": "X"})
        await database.get_database()["lenders_registry"].delete_many({})
        qid, _ = self._un_quartier()
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/depositaires/apercu",
            json={"quartier_id": qid, "company_id": "cie-inconnue"},
            headers=entetes,
        )
        assert reponse.status_code == 403
        assert "etrangere" in reponse.json()["detail"]

    async def test_l_incoherence_devise_est_un_422_nomme(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Company de Dakar (XOF) + quartier de Douala (XAF) -> refus DIT."""
        self._doubler(
            monkeypatch,
            fiche_company={"name": "DEMO_SARL Dakar", "currency": "XOF"},
        )
        await self._company_a_nous("cie-sn")
        qid, _ = self._un_quartier("CM")
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/depositaires/apercu",
            json={"quartier_id": qid, "company_id": "cie-sn"},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "INCOHERENCE" in reponse.json()["detail"]
        assert "XOF" in reponse.json()["detail"] and "XAF" in reponse.json()["detail"]

    async def test_le_rite_complet_compose_depuis_le_quartier(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler(
            monkeypatch,
            fiche_company={"name": "DEMO_SARL Douala", "currency": "XAF"},
        )
        await self._company_a_nous("cie-cm")
        await _registre_vierge()
        await database.get_database()["org_hierarchy"].delete_many({})
        qid, qnom = self._un_quartier("CM")
        entetes = await _session_complete(client)
        demande = {"quartier_id": qid, "company_id": "cie-cm"}

        apercu = await client.post(
            "/admin/entites/depositaires/apercu", json=demande, headers=entetes
        )
        assert apercu.status_code == 200, apercu.text
        corps = apercu.json()
        assert corps["payload"]["name"] == f"Kiosque {qnom}"  # sans prefixe (20/08)
        assert corps["payload"]["currency"] == "XAF", "la devise est DERIVEE"
        assert corps["composition"]["coherence_verifiee_par"] == "devise de la company"
        assert etat["crees"] == [], "l'apercu n'ecrit JAMAIS"

        creation = await client.post(
            "/admin/entites/depositaires", json=demande, headers=entetes
        )
        assert creation.status_code == 201, creation.text
        assert creation.json()["statut"] == "a_nous"
        assert creation.json()["fiche_relue"]["currency"] == "XAF"

        # Doublon de nom -> 409 (D-DEP-3 : permanent)
        assert (
            await client.post(
                "/admin/entites/depositaires", json=demande, headers=entetes
            )
        ).status_code == 409

    async def test_un_quartier_occupe_est_un_409(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un quartier n'heberge qu'UN kiosque — l'unite respecte le run."""
        self._doubler(
            monkeypatch, fiche_company={"name": "DEMO_SARL", "currency": "XAF"}
        )
        await self._company_a_nous("cie-cm")
        qid, _ = self._un_quartier("CM")
        org = database.get_database()["org_hierarchy"]
        await org.delete_many({})
        await org.insert_one(
            {"niveau": "KIOSQUE", "district_id": qid, "name": "DEMO_Kiosque Occupant"}
        )
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/depositaires/apercu",
            json={"quartier_id": qid, "company_id": "cie-cm"},
            headers=entetes,
        )
        assert reponse.status_code == 409
        assert "UN" in reponse.json()["detail"]
        await org.delete_many({})


class TestLicencesALUnite:
    """16/08 — voir et ATTRIBUER une licence a une company A NOUS (UC-07)."""

    @staticmethod
    def _doubler(monkeypatch: pytest.MonkeyPatch, *, licences: list | None = None):
        from app.routes import admin_entites

        etat = {"licences": list(licences or []), "creees": []}

        class _Companies:
            async def licences_de_company(self, company_id):  # type: ignore[no-untyped-def]
                return list(etat["licences"])

            async def a_une_licence(self, company_id):  # type: ignore[no-untyped-def]
                return bool(etat["licences"])

            async def creer_licence(self, company_id, packages, debut, fin):  # type: ignore[no-untyped-def]
                fiche = {"company_id": str(company_id),
                         "packages": [p.value for p in packages],
                         "start_date": debut, "end_date": fin}
                etat["creees"].append(fiche)
                etat["licences"].append(fiche)
                return fiche

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            admin_entites, "_client_companies_unite", lambda: _Companies()
        )
        return etat

    async def test_etrangere_403_et_a_nous_licenciee_du_run_UC07(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler(monkeypatch)
        await database.get_database()["lenders_registry"].delete_many({})
        entetes = await _session_complete(client)

        refus = await client.post(
            "/admin/entites/companies/cie-x/licences",
            json={"packages": ["ALL"]},
            headers=entetes,
        )
        assert refus.status_code == 403

        await database.get_database()["lenders_registry"].insert_one(
            {"company_id": "cie-x", "nom": "DEMO_SARL"}
        )
        creation = await client.post(
            "/admin/entites/companies/cie-x/licences",
            json={"packages": ["READY_COLLECTE"]},
            headers=entetes,
        )
        assert creation.status_code == 201, creation.text
        assert creation.json()["licences"][0]["packages"] == ["READY_COLLECTE"]
        assert etat["creees"][0]["packages"] == ["READY_COLLECTE"]
        # La fenetre UC-07 : debut < fin, la marge +30 j est dedans
        fen = creation.json()["fenetre"]
        assert fen["debut"] < fen["fin"]

        # Deja licenciee -> 409, jamais d'empilement silencieux
        doublon = await client.post(
            "/admin/entites/companies/cie-x/licences",
            json={"packages": ["ALL"]},
            headers=entetes,
        )
        assert doublon.status_code == 409

        # GET : les licences RELUES
        lecture = await client.get(
            "/admin/entites/companies/cie-x/licences", headers=entetes
        )
        assert lecture.status_code == 200
        assert lecture.json()["compte"] == 1
        await database.get_database()["lenders_registry"].delete_many({})


class TestEtatsLaBas:
    """16/08 (Yaniv : visibilite ET action COMPLETES) — l'etat des
    depositaires se voit et se change LA-BAS ; les telcos config-service
    s'activent/desactivent avec la garde des references inverses ; la
    devise porte son refus MESURE."""

    @staticmethod
    def _doubler_depositaires(monkeypatch: pytest.MonkeyPatch):
        from app.routes import admin_inventaire

        etat = {
            "liste": [
                {"_id": "dep-1", "name": "DEMO_Kiosque Bonapriso", "is_active": True},
                {"_id": "dep-2", "name": "Depositaire Metier", "is_active": True},
            ]
        }

        class _Depositaires:
            async def lister(self):  # type: ignore[no-untyped-def]
                return [dict(d) for d in etat["liste"]]

            async def changer_statut(self, did, actif):  # type: ignore[no-untyped-def]
                for d in etat["liste"]:
                    if d["_id"] == str(did):
                        d["is_active"] = actif
                return {}

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            admin_inventaire, "_client_depositaires", lambda: _Depositaires()
        )
        return etat

    async def test_l_etat_du_depositaire_se_voit_et_se_change_avec_la_verite(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_depositaires(monkeypatch)
        await database.get_database()["org_hierarchy"].delete_many({})
        await _registre_vierge()
        entetes = await _session_complete(client)

        # L'etat est VISIBLE a l'inventaire
        inventaire = await client.get("/admin/inventaire/depositaires", headers=entetes)
        assert all(
            ligne["actif"] is True for ligne in inventaire.json()["etranger"]
        ), "is_active de la plateforme reporte sur chaque ligne"

        # Desactivation d'un ETRANGER : permise (decision 16/08) mais DITE
        reponse = await client.patch(
            "/admin/inventaire/depositaires/dep-2/etat",
            json={"actif": False, "motif": "test de visibilite"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["actif"] is False
        assert corps["statut"] == "etranger"
        assert "ETRANGERE" in corps["note"]
        assert "n'arrete NI les collectes NI les retraits" in corps["verite_d_dep_8"]

        # 404 pour un inconnu
        assert (
            await client.patch(
                "/admin/inventaire/depositaires/fantome/etat",
                json={"actif": True, "motif": "test"},
                headers=entetes,
            )
        ).status_code == 404

    @staticmethod
    def _doubler_config(monkeypatch: pytest.MonkeyPatch, *, garde: bool = False):
        from app.clients.config_service import ReferenceInverse
        from app.routes import admin_referentiels

        etat = {
            "telcos": [
                {"_id": "t-1", "network_name": "Orange CM", "short_name": "OCM",
                 "is_active": True},
            ],
            "pays": [
                {"iso_name": "CM", "telcos": ["t-1"], "currencies": ["d-1"]},
                *([{"iso_name": "CI", "telcos": ["t-1"], "currencies": []}] if garde else []),
            ],
        }

        class _Lecture:
            async def lister_telcos(self):  # type: ignore[no-untyped-def]
                return [dict(t) for t in etat["telcos"]]

            async def lister_pays(self):  # type: ignore[no-untyped-def]
                return [dict(p) for p in etat["pays"]]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        class _Admin:
            async def activer_telco(self, tid):  # type: ignore[no-untyped-def]
                etat["telcos"][0]["is_active"] = True
                return {}

            async def desactiver_telco(self, tid, *, pays_attendu):  # type: ignore[no-untyped-def]
                autres = [
                    p["iso_name"] for p in etat["pays"]
                    if tid in p["telcos"] and p["iso_name"] != pays_attendu
                ]
                if autres:
                    raise ReferenceInverse(
                        f"operateur {tid} encore reference par {autres} — "
                        "desactivation refusee."
                    )
                etat["telcos"][0]["is_active"] = False
                return {}

            async def desactiver_devise(self, did):  # type: ignore[no-untyped-def]
                raise ReferenceInverse(
                    "devise partagee par 3 pays — desactivation refusee (mesure 09/08)"
                )

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())
        monkeypatch.setattr(admin_referentiels, "_config_admin", lambda: _Admin())
        return etat

    async def test_telco_liste_puis_desactivation_reelle_avec_relecture(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_config(monkeypatch)
        entetes = await _session_complete(client)

        liste = await client.get("/admin/referentiels/telcos-config", headers=entetes)
        assert liste.status_code == 200, liste.text
        ligne = liste.json()["telcos"][0]
        assert ligne["actif"] is True and ligne["porteurs"] == ["CM"]

        reponse = await client.patch(
            "/admin/referentiels/telcos-config/t-1/etat",
            json={"actif": False, "motif": "test"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["etat_relu"] is False
        assert "GESTE SEPARE" in reponse.json()["note"], (
            "la verite INV-18 est dite : la generation suit le classeur"
        )

    async def test_la_garde_des_references_inverses_PARLE_en_409(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deux pays referencent l'operateur : la desactivation refusee avec
        le message MESURE — le scenario `ca`/Cote d'Ivoire du 09/08."""
        self._doubler_config(monkeypatch, garde=True)
        entetes = await _session_complete(client)
        reponse = await client.patch(
            "/admin/referentiels/telcos-config/t-1/etat",
            json={"actif": False, "motif": "test"},
            headers=entetes,
        )
        assert reponse.status_code == 409
        assert "encore reference par" in reponse.json()["detail"]

    async def test_la_devise_porte_son_refus_mesure(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_config(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.patch(
            "/admin/referentiels/devises-config/d-1/etat",
            json={"actif": False, "motif": "test"},
            headers=entetes,
        )
        assert reponse.status_code == 409
        assert "mesure 09/08" in reponse.json()["detail"]


class TestC7SortirUnPaysDOperation:
    """`C7`/`A-08` (23/08) — le verbe qui manquait. `activer_pays` et
    `desactiver_pays` existaient dans le client depuis la mesure du 09/08,
    mais AUCUNE route ne les exposait : l'aller etait sans retour."""

    @staticmethod
    def _doubler(monkeypatch: pytest.MonkeyPatch, *, present: bool = True, agit: bool = True):  # type: ignore[no-untyped-def]
        from app.routes import admin_referentiels

        etat: dict[str, Any] = {"actif": True, "gestes": []}

        class _Lecture:
            async def lister_pays(self):  # type: ignore[no-untyped-def]
                if not present:
                    return []
                return [{"_id": "cfg-CM", "iso_name": "CM", "is_active": etat["actif"]}]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        class _Admin:
            async def activer_pays(self, cid):  # type: ignore[no-untyped-def]
                etat["gestes"].append(("activer", cid))
                if agit:
                    etat["actif"] = True
                return {}

            async def desactiver_pays(self, cid):  # type: ignore[no-untyped-def]
                etat["gestes"].append(("desactiver", cid))
                if agit:
                    etat["actif"] = False
                return {}

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())
        monkeypatch.setattr(admin_referentiels, "_config_admin", lambda: _Admin())
        return etat

    async def _config_sans_cm(self) -> None:
        """CM retire de la configuration : la garde ne doit plus s'opposer."""
        from app.repositories.configuration import ConfigurationRepository

        depot = ConfigurationRepository()
        configuration, _ = await depot.charger()
        if "CM" in configuration.pays:
            configuration.pays["CM"].desactiver("banc de test C7")
        await depot.enregistrer(configuration, par="test")

    async def test_la_desactivation_AGIT_et_est_RELUE(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler(monkeypatch)
        entetes = await _session_complete(client)
        await self._config_sans_cm()
        reponse = await client.patch(
            "/admin/referentiels/pays/CM/etat",
            json={"actif": False, "motif": "retrait du perimetre"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["etat_relu"] is False, "l'etat rendu est MESURE, pas demande"
        assert corps["avant"] is True
        assert etat["gestes"] == [("desactiver", "cfg-CM")]

    async def test_un_serveur_qui_repond_SANS_AGIR_est_demasque(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`ANO-CFG-LIFECYCLE` : la signature exacte vue en juin."""
        self._doubler(monkeypatch, agit=False)
        entetes = await _session_complete(client)
        await self._config_sans_cm()
        reponse = await client.patch(
            "/admin/referentiels/pays/CM/etat",
            json={"actif": False, "motif": "test"},
            headers=entetes,
        )
        assert reponse.status_code == 502, reponse.text
        assert "n'a PAS change a la relecture" in reponse.json()["detail"]

    async def test_desactiver_un_pays_ACTIF_dans_la_configuration_est_refuse(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """La garde mesuree : le run le viserait et echouerait a la 1500e
        ecriture au lieu d'ici."""
        etat = self._doubler(monkeypatch)
        entetes = await _session_complete(client)
        from app.repositories.configuration import ConfigurationRepository

        depot = ConfigurationRepository()
        configuration, _ = await depot.charger()
        if "CM" in configuration.pays:
            configuration.pays["CM"].reactiver()
            await depot.enregistrer(configuration, par="test")
            reponse = await client.patch(
                "/admin/referentiels/pays/CM/etat",
                json={"actif": False, "motif": "test"},
                headers=entetes,
            )
            assert reponse.status_code == 409, reponse.text
            assert "ACTIF dans la configuration" in reponse.json()["detail"]
            assert etat["gestes"] == [], "rien n'est parti"

    async def test_un_pays_absent_de_la_plateforme_est_un_422(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler(monkeypatch, present=False)
        entetes = await _session_complete(client)
        reponse = await client.patch(
            "/admin/referentiels/pays/CM/etat",
            json={"actif": True, "motif": "test"},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "pousser" in reponse.json()["detail"]

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        assert (
            await client.patch(
                "/admin/referentiels/pays/CM/etat",
                json={"actif": True, "motif": "test"},
            )
        ).status_code == 401


class TestC4EtC5CoherenceEtSynchronisation:
    """`C4`/`C5` (23/08) — une derive qui attend qu'on ouvre un ecran n'est
    pas surveillee : 361 villes ont manque pendant dix jours. La sonde rend
    un VERDICT, et la synchronisation ferme l'ecart d'un geste."""

    @staticmethod
    def _doubler(monkeypatch: pytest.MonkeyPatch, pays: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
        from app.routes import admin_referentiels

        class _Lecture:
            async def lister_pays(self):  # type: ignore[no-untyped-def]
                return [dict(p) for p in pays]

            async def lister_telcos(self):  # type: ignore[no-untyped-def]
                return [{"_id": "t-1", "network_name": "MTN Cameroon"}]

            async def lister_devises(self):  # type: ignore[no-untyped-def]
                return [{"_id": "d-xaf", "iso_name": "XAF"}]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())

    _COMPLET: ClassVar[dict[str, Any]] = {
        "_id": "cfg-CM", "iso_name": "CM", "name_en": "Cameroon",
        "name_fr": "Cameroun", "dial_code": "237", "region": "Middle Africa",
        "continent": "Africa", "cities": [], "currencies": ["d-xaf"],
        "telcos": [{"_id": "t-1"}],
    }

    async def test_verdict_DERIVE_quand_il_manque_des_villes(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler(monkeypatch, [self._COMPLET])  # 0 ville la-bas, 87 chez nous
        entetes = await _session_complete(client)
        corps = (
            await client.get("/admin/referentiels/coherence", headers=entetes)
        ).json()
        assert corps["verdict"] == "derive", corps
        assert corps["derive"][0]["iso2"] == "CM"
        assert "synchroniser" in corps["geste"]

    async def test_verdict_ANOMALIE_l_emporte_sur_la_derive(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un systeme qui annonce « coherent » avec une anomalie en cours ment
        plus qu'il n'informe — le PIRE verdict gagne."""
        parasite = {"_id": "cfg-ca", "iso_name": "ca", "cities": [], "telcos": []}
        self._doubler(monkeypatch, [self._COMPLET, parasite])
        entetes = await _session_complete(client)
        corps = (
            await client.get("/admin/referentiels/coherence", headers=entetes)
        ).json()
        assert corps["verdict"] == "anomalie", corps
        assert any(a["iso2"] == "CA" for a in corps["anomalies"])
        assert corps["derive"], "la derive reste VISIBLE sous l'anomalie"
        assert "rectifier" in corps["geste"]

    async def test_l_apercu_de_synchronisation_n_ecrit_RIEN(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        corps = (
            await client.post(
                "/admin/referentiels/synchroniser", json={}, headers=entetes
            )
        ).json()
        assert corps["statut"] == "apercu"
        assert _config_service_double["villes"] == [], "aucune ville envoyee"
        assert _config_service_double["pays_crees"] == []

    async def test_la_synchronisation_confirmee_ferme_l_ecart_de_CHAQUE_pays(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/synchroniser", json={"confirmer": True}, headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["statut"] == "synchronise"
        assert corps["compte"] >= 1, corps
        assert all(
            ligne["statut"] in ("deja_en_operation", "mis_en_operation")
            or ligne["statut"].startswith("refuse")
            for ligne in corps["rapport"]
        ), corps["rapport"]
        assert _config_service_double["villes"], "des villes sont VRAIMENT parties"

    async def test_la_synchronisation_ne_touche_QUE_les_pays_en_operation(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """`I-CFG-SYNC` : un pays hors operation n'a rien a synchroniser — sa
        matiere partira ENTIERE a sa mise en operation."""
        entetes = await _session_complete(client)
        corps = (
            await client.post(
                "/admin/referentiels/synchroniser", json={}, headers=entetes
            )
        ).json()
        # le double ne porte que CM, CI, BF, SN la-bas
        assert {c["iso2"] for c in corps["a_synchroniser"]} <= {"CM", "CI", "BF", "SN"}

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/admin/referentiels/coherence")).status_code == 401
        assert (
            await client.post("/admin/referentiels/synchroniser", json={})
        ).status_code == 401


class TestC2VerrouParRessource:
    """`C2` (23/08) — le `GET`-avant-`POST` qui tient l'unicite n'est sur que
    SEQUENTIELLEMENT. Deux appels simultanes sur le meme pays lisent tous les
    deux « absent » et creent tous les deux ; le doublon est ensuite
    DEFINITIF (la plateforme n'a ni index unique ni DELETE)."""

    async def test_deux_allers_simultanes_sur_le_meme_pays_UN_SEUL_passe(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        import asyncio

        entetes = await _session_complete(client)
        reponses = await asyncio.gather(
            client.post("/admin/referentiels/pays/CM/pousser", headers=entetes),
            client.post("/admin/referentiels/pays/CM/pousser", headers=entetes),
        )
        statuts = sorted(r.status_code for r in reponses)
        assert statuts == [200, 409], [r.status_code for r in reponses]
        refus = next(r for r in reponses if r.status_code == 409)
        assert "DEJA en cours" in refus.json()["detail"]
        assert "RC-183" in refus.json()["detail"], "le refus porte sa raison"

    async def test_deux_pays_DIFFERENTS_ne_se_bloquent_pas(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Le verrou est par RESSOURCE, jamais global — sinon il deviendrait
        lui-meme le goulot d'etranglement."""
        import asyncio

        entetes = await _session_complete(client)
        reponses = await asyncio.gather(
            client.post("/admin/referentiels/pays/CM/pousser", headers=entetes),
            client.post("/admin/referentiels/pays/CI/pousser", headers=entetes),
        )
        assert [r.status_code for r in reponses] == [200, 200], [
            r.status_code for r in reponses
        ]

    async def test_le_verrou_est_RENDU_meme_quand_le_geste_echoue(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Un verrou qui survit a un echec transformerait une panne passagere
        en blocage permanent."""
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        # ZZ est inconnu du Loader -> 422, mais le verrou doit etre rendu
        assert (
            await client.post("/admin/referentiels/pays/ZZ/pousser", headers=entetes)
        ).status_code == 422
        deuxieme = await client.post(
            "/admin/referentiels/pays/CM/pousser", headers=entetes
        )
        assert deuxieme.status_code == 200, deuxieme.text

    async def test_un_verrou_PERIME_est_repris_jamais_un_blocage_definitif(
        self, client: httpx.AsyncClient
    ) -> None:
        """Un processus tue laisse son verrou : il DOIT pouvoir etre repris."""
        from datetime import UTC, datetime, timedelta

        from app.repositories.verrous import RessourceVerrouillee, VerrouRepository

        depot = VerrouRepository()
        await depot.rendre("test:perime")
        await depot.prendre("test:perime", par="processus-mort")
        with pytest.raises(RessourceVerrouillee):
            await depot.prendre("test:perime", par="second")
        # on force la peremption, comme le TTL l'aurait fait
        await depot.collection.update_one(
            {"_id": "test:perime"},
            {"$set": {"expire_le": datetime.now(UTC) - timedelta(seconds=1)}},
        )
        await depot.prendre("test:perime", par="repreneur")  # ne leve plus
        await depot.rendre("test:perime")


class TestUnePanneDeLaPlateformeEstDITE:
    """23/08 — la plateforme a repondu `HTTP 423` a notre login (compte ROOT
    PARTAGE), le disjoncteur `INV-USR-19` a refuse de retenter pour ne pas
    aggraver — et nos ecrans ont rendu un **500 muet**. Le diagnostic exact
    dormait dans les logs du conteneur pendant que l'utilisateur lisait
    « Internal Server Error ». Un systeme honnete relaie la panne."""

    @staticmethod
    def _plateforme_en_panne(monkeypatch: pytest.MonkeyPatch, statut: int):  # type: ignore[no-untyped-def]
        from app.clients.base import ErreurService
        from app.routes import admin_referentiels

        def _boum():  # type: ignore[no-untyped-def]
            raise ErreurService(
                "config-service", "POST", "/auth/login", statut,
                "DISJONCTEUR : dernier login refuse (HTTP 423) — aucune "
                "nouvelle tentative avant ~9 min (INV-USR-19)", "-",
            )

        class _Lecture:
            async def lister_telcos(self):  # type: ignore[no-untyped-def]
                _boum()

            async def lister_devises(self):  # type: ignore[no-untyped-def]
                _boum()

            async def lister_pays(self):  # type: ignore[no-untyped-def]
                _boum()

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())

    async def test_un_423_de_la_plateforme_VOYAGE_avec_son_motif(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._plateforme_en_panne(monkeypatch, 423)
        entetes = await _session_complete(client)
        for route in (
            "/admin/referentiels/telcos-config",
            "/admin/referentiels/devises-config",
            "/admin/referentiels/pays-config",
        ):
            reponse = await client.get(route, headers=entetes)
            assert reponse.status_code == 423, f"{route} -> {reponse.status_code}"
            detail = reponse.json()["detail"]
            assert "config-service : HTTP 423" in detail, detail
            assert "DISJONCTEUR" in detail, "le motif exact arrive a l'ecran"

    async def test_une_panne_quelconque_devient_502_jamais_500(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._plateforme_en_panne(monkeypatch, 500)
        entetes = await _session_complete(client)
        reponse = await client.get(
            "/admin/referentiels/telcos-config", headers=entetes
        )
        assert reponse.status_code == 502, reponse.text
        assert "config-service" in reponse.json()["detail"]


class TestC6RectifierUnPaysEnOperation:
    """`C6` (23/08, Yaniv) — config-service n'a **aucun PATCH**, que des
    `PUT` : toute modification est une REECRITURE INTEGRALE. Piege (un champ
    omis est EFFACE) et chance a la fois — le Loader etant System of Record,
    rectifier, c'est le MEME geste que pousser."""

    @staticmethod
    def _doubler(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
        from app.routes import admin_referentiels

        etat: dict[str, Any] = {
            "pays": {
                "_id": "cfg-CV", "iso_name": "CV", "name_en": "Cape Verde",
                "name_fr": "", "dial_code": "", "region": "Western Africa",
                "continent": "Africa",
                # une ville posee par une AUTRE equipe, inconnue de nous
                "cities": ["Praia-Ilha"],
                "currencies": ["cur-xaf"],          # FAUX : notre fiche dit CVE
                "telcos": ["tl-etranger"],          # rattache par un autre
            },
            "put": [],
            "ecritures": [],
        }

        class _Lecture:
            async def lister_pays(self):  # type: ignore[no-untyped-def]
                return [dict(etat["pays"])]

            async def lister_telcos(self):  # type: ignore[no-untyped-def]
                return [{"_id": "tl-etranger", "network_name": "Operateur Tiers"}]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        class _Admin:
            async def resoudre_devise(self, iso):  # type: ignore[no-untyped-def]
                return "cur-cve" if iso.upper() == "CVE" else None

            async def creer_devise_si_absent(self, payload):  # type: ignore[no-untyped-def]
                etat["ecritures"].append(("devise", payload))
                return {"id": "cur-neuve", "iso_name": payload["iso_name"]}, True

            async def creer_telco_si_absent(self, nom, regex):  # type: ignore[no-untyped-def]
                etat["ecritures"].append(("telco", nom))
                return {"_id": f"tl-{nom}", "name": nom}, True

            async def remplacer_pays(self, cid, payload):  # type: ignore[no-untyped-def]
                etat["put"].append((cid, payload))
                etat["pays"].update(payload)
                return dict(etat["pays"])

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())
        monkeypatch.setattr(admin_referentiels, "_config_admin", lambda: _Admin())
        return etat

    async def _fiche_cap_vert(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="CV", nom_fr="Cap-Vert", nom_en="Cabo Verde", capitale="Praia",
            dial_code="238", devise_iso="CVE", tva_percent=15.0,
            devise_nom="Cape Verdean Escudo", devise_decimales=2,
            banque_centrale="BCV", region_africa="Western Africa",
        )
        await _semer_telco(
            "CV", "CVMovel", "CVM", r"^238(9[0-9]\d{5})$", 70.0, "2389912345"
        )
        return entetes

    async def test_l_apercu_montre_l_ECART_et_n_ecrit_RIEN(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler(monkeypatch)
        entetes = await self._fiche_cap_vert(client)
        reponse = await client.post(
            "/admin/referentiels/pays/CV/rectifier", json={}, headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["statut"] == "apercu"
        assert etat["put"] == [], "AUCUNE ecriture sans confirmation"
        assert corps["ecart"]["name_fr"] == {"avant": "", "apres": "Cap-Vert"}
        assert corps["ecart"]["dial_code"] == {"avant": "", "apres": "238"}
        assert corps["ecart"]["devise"]["iso_attendu"] == "CVE"

    async def test_l_apercu_ne_cree_NI_devise_NI_telco(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defaut attrape sur la PROD le 23/08 : l'apercu resolvait la devise
        et la CREAIT si absente — avant meme de tester `confirmer`. La devise
        `CVE` est nee d'un simple apercu. Un apercu LIT, il ne prepare rien."""
        etat = self._doubler(monkeypatch)
        entetes = await self._fiche_cap_vert(client)
        # notre fiche demande CVE ; on simule une plateforme qui ne l'a PAS
        from app.routes import admin_referentiels

        admin_reel = admin_referentiels._config_admin()

        class _SansDevise:
            def __getattr__(self, nom):  # type: ignore[no-untyped-def]
                return getattr(admin_reel, nom)

            async def resoudre_devise(self, _iso):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_admin", lambda: _SansDevise())
        reponse = await client.post(
            "/admin/referentiels/pays/CV/rectifier", json={}, headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        corps = reponse.json()
        assert corps["statut"] == "apercu"
        assert etat["ecritures"] == [], "AUCUNE creation pendant un apercu"
        assert etat["put"] == []
        assert corps["ecart"]["devise"]["a_creer_la_bas"] is True, (
            "ce qui SERA cree est annonce, pas fait"
        )
        assert corps["ecart"]["telcos_a_creer"] == ["CVMovel"]

    async def test_la_rectification_reecrit_les_9_champs_dans_l_ordre_du_pousser(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        etat = self._doubler(monkeypatch)
        entetes = await self._fiche_cap_vert(client)
        reponse = await client.post(
            "/admin/referentiels/pays/CV/rectifier",
            json={"confirmer": True, "motif": "devise XAF au lieu de CVE"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["statut"] == "rectifie"
        assert len(etat["put"]) == 1, "UN seul PUT, complet"
        _cid, payload = etat["put"][0]
        assert sorted(payload) == [
            "cities", "continent", "currencies", "dial_code", "iso_name",
            "name_en", "name_fr", "region", "telcos",
        ], "les 9 champs — un champ omis serait EFFACE"
        assert payload["currencies"] == ["cur-cve"], "la devise suit NOTRE fiche"
        assert payload["name_fr"] == "Cap-Vert" and payload["dial_code"] == "238"

    async def test_la_matiere_des_AUTRES_equipes_est_CONSERVEE(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le piege du PUT : reecrire avec nos seules donnees SUPPRIMERAIT ce
        qu'une autre equipe a ajoute. Villes et telcos fusionnent."""
        etat = self._doubler(monkeypatch)
        entetes = await self._fiche_cap_vert(client)
        await client.post(
            "/admin/referentiels/pays/CV/rectifier",
            json={"confirmer": True}, headers=entetes,
        )
        _cid, payload = etat["put"][0]
        assert "Praia-Ilha" in payload["cities"], "la ville d'une autre equipe SURVIT"
        assert "Praia" in payload["cities"], "et la notre est ajoutee"
        assert "tl-etranger" in payload["telcos"], "le telco d'une autre equipe SURVIT"
        assert "tl-CVMovel" in payload["telcos"], "et le notre est rattache"

    async def test_rectifier_un_pays_HORS_operation_est_refuse(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On ne rectifie que ce qui existe la-bas — sinon c'est un pousser."""
        self._doubler(monkeypatch)
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="GA", nom_fr="Gabon", nom_en="Gabon", capitale="Libreville",
            dial_code="241", devise_iso="XAF", tva_percent=18.0,
        )
        reponse = await client.post(
            "/admin/referentiels/pays/GA/rectifier",
            json={"confirmer": True}, headers=entetes,
        )
        assert reponse.status_code == 422
        assert "pousser" in reponse.json()["detail"]

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        assert (
            await client.post("/admin/referentiels/pays/CV/rectifier", json={})
        ).status_code == 401


class TestC1CleDeComparaisonAntiDoublon:
    """`C1` (23/08) — l'unicite est A NOUS (`RC-183` : aucun index unique
    cote serveur). Une autorite d'unicite qui compare des chaines EXACTES
    n'en est pas une : un accent ou une majuscule suffisait a creer un
    doublon DEFINITIF (aucun DELETE cote config-service)."""

    def test_la_cle_plie_accents_casse_et_ponctuation(self) -> None:
        from app.clients.config_service import cle_comparaison

        assert cle_comparaison("Orange Guinée") == cle_comparaison("ORANGE GUINEE")
        assert cle_comparaison("Yaoundé") == cle_comparaison("yaounde")
        assert cle_comparaison("Moov Africa - CI") == cle_comparaison("Moov  Africa CI")
        assert cle_comparaison("MTN Côte d'Ivoire") == cle_comparaison("MTN Cote d Ivoire")

    def test_la_cle_ne_confond_PAS_deux_operateurs_differents(self) -> None:
        """Le piege inverse : trop normaliser fusionnerait deux vrais
        operateurs. `Orange CM` et `Orange CI` restent DEUX telcos."""
        from app.clients.config_service import cle_comparaison

        assert cle_comparaison("Orange Cameroon") != cle_comparaison("Orange Cote d'Ivoire")
        assert cle_comparaison("MTN Ghana") != cle_comparaison("MTN Guinee")

    async def test_un_telco_deja_la_bas_sous_un_autre_ACCENT_est_ADOPTE(self) -> None:
        from app.clients.config_service import AdministrationConfigService

        admin = AdministrationConfigService()
        envois: list[Any] = []

        class _Faux:
            async def lister_tout(self, _chemin):  # type: ignore[no-untyped-def]
                return [{"_id": "tl-1", "name": "ORANGE  GUINEE"}]

            async def requete(self, *a, **k):  # type: ignore[no-untyped-def]
                envois.append((a, k))
                raise AssertionError("aucun POST ne doit partir : le telco existe deja")

        admin._client = _Faux()  # type: ignore[assignment]
        fiche, cree = await admin.creer_telco_si_absent("Orange Guinée", r"^224(6\d{8})$")
        assert cree is False, "reconnu malgre l'accent et la casse"
        assert fiche["_id"] == "tl-1"
        assert envois == []

    async def test_une_ville_deja_la_bas_sous_un_autre_ACCENT_n_est_pas_doublee(
        self,
    ) -> None:
        from app.clients.config_service import AdministrationConfigService

        admin = AdministrationConfigService()
        ecritures: list[Any] = []

        class _Reponse:
            data: ClassVar[dict[str, Any]] = {
                "_id": "cfg-CM", "iso_name": "CM", "cities": ["Yaoundé", "Douala"],
                "currencies": [], "telcos": [],
            }

        class _Faux:
            async def get(self, _chemin):  # type: ignore[no-untyped-def]
                return _Reponse()

            async def requete(self, *a, **k):  # type: ignore[no-untyped-def]
                ecritures.append(k.get("json_body"))
                return _Reponse()

        admin._client = _Faux()  # type: ignore[assignment]
        await admin.ajouter_ville("cfg-CM", "Yaounde")
        assert ecritures == [], "aucun PUT : la ville existe deja, autrement accentuee"
        await admin.ajouter_ville("cfg-CM", "Bafoussam")
        assert ecritures and "Bafoussam" in ecritures[0]["cities"], (
            "une VRAIE nouvelle ville part quand meme"
        )


class TestC3UnSeulAllerRetourPourLesVilles:
    """`C3` (23/08) — completer un pays coutait 2 appels PAR ville (338 pour
    la Cote d'Ivoire, > 60 s, timeout frontend). `UpdateCountrySchema` exige
    les 9 champs de toute facon : une seule relecture sert pour toutes."""

    async def test_toutes_les_villes_manquantes_partent_en_UN_lot(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays/CM/pousser", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["statut"] == "deja_en_operation"
        assert _config_service_double.get("lots", 0) <= 1, (
            "UN aller-retour au plus, quel que soit le nombre de villes"
        )
        assert len(_config_service_double["villes"]) > 1, (
            "et le lot porte bien PLUSIEURS villes"
        )

    async def test_un_echec_du_lot_est_DIT_avec_le_nombre_et_le_rattrapage(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        """Tout ou rien assume : mais jamais muet, et le geste de reprise est
        nomme (l'aller est idempotent)."""
        _config_service_double["echec_villes"] = "config-service indisponible"
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays/CM/pousser", headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        echecs = reponse.json()["echecs"]
        assert echecs and "ville(s) non envoyee(s)" in echecs[0], echecs
        assert "re-pousser" in echecs[0], "le rattrapage est dit"


class TestICFGSyncLaMatiereSuitLOperation:
    """`I-CFG-SYNC` (23/08, Yaniv) — la coherence des deux cotes.

    Regle : la matiere s'ecrit TOUJOURS chez nous ; elle ne part la-bas que
    si le pays est EN OPERATION. Sinon elle attend le `pousser`, qui l'envoie
    ENTIERE. Un pays hors operation ne doit JAMAIS faire naitre un telco, une
    ville ou une devise sur le referentiel PARTAGE.
    """

    TELCO_ET: ClassVar[dict[str, Any]] = {
        "pays": "ET", "network_name": "Ethio Telecom", "short_name": "ETHIO",
        "regex_msisdn": r"^251(9\d{8})$", "part_marche": 90.0,
        "exemple_msisdn": "251911234567",
    }

    @staticmethod
    def _doubler(monkeypatch: pytest.MonkeyPatch, *, muet: bool = False):  # type: ignore[no-untyped-def]
        from app.routes import admin_referentiels

        traces: dict[str, Any] = {"telcos_crees": [], "rattaches": [], "villes": []}

        class _Lecture:
            async def lister_pays(self):  # type: ignore[no-untyped-def]
                if muet:
                    raise ConnectionError("config-service injoignable")
                return [{"_id": "cfg-CM", "iso_name": "CM"}]  # ET n'y est PAS

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        class _Admin:
            async def creer_telco_si_absent(self, nom, regex):  # type: ignore[no-untyped-def]
                traces["telcos_crees"].append(nom)
                return {"_id": f"tl-{nom}", "name": nom}, True

            async def rattacher_telco_au_pays(self, cid, tid):  # type: ignore[no-untyped-def]
                traces["rattaches"].append((cid, tid))
                return {}

            async def ajouter_ville(self, cid, nom):  # type: ignore[no-untyped-def]
                traces["villes"].append((cid, nom))
                return {}

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())
        monkeypatch.setattr(admin_referentiels, "_config_admin", lambda: _Admin())
        return traces

    async def _fiche_ethiopie(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        await _semer_fiche_pays(
            iso2="ET", nom_fr="Éthiopie", nom_en="Ethiopia", capitale="Addis-Abeba",
            dial_code="251", devise_iso="ETB", tva_percent=15.0,
            devise_nom="Ethiopian Birr", devise_decimales=2, banque_centrale="NBE",
        )
        return entetes

    async def test_un_telco_sur_un_pays_HORS_operation_ne_part_PAS(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE bug du 23/08 : `creer_telco_si_absent` partait AVANT la
        resolution du pays — l'operateur naissait la-bas puis le rattachement
        echouait. Un orphelin de plus dans le referentiel PARTAGE, qu'aucun
        DELETE ne permet de retirer."""
        traces = self._doubler(monkeypatch)
        entetes = await self._fiche_ethiopie(client)
        reponse = await client.post(
            "/admin/referentiels/telcos", json=self.TELCO_ET, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        assert traces["telcos_crees"] == [], (
            "AUCUN telco ne doit naitre la-bas pour un pays absent"
        )
        assert traces["rattaches"] == []
        envoi = reponse.json()["config_service"]
        assert envoi["statut"] == "differe", envoi
        assert "pousser" in envoi["raison"], "le geste qui la fera partir est dit"

    async def test_le_telco_reste_ECRIT_chez_nous_malgre_le_differe(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le Loader est le System of Record : le differe ne perd RIEN."""
        self._doubler(monkeypatch)
        entetes = await self._fiche_ethiopie(client)
        await client.post(
            "/admin/referentiels/telcos", json=self.TELCO_ET, headers=entetes
        )
        vue = await client.get("/admin/referentiels/telcos", headers=entetes)
        noms = [t["nom"] for t in vue.json()["telcos"].get("ET", [])]
        assert "Ethio Telecom" in noms, vue.json()["telcos"].get("ET")

    async def test_un_telco_sur_un_pays_EN_operation_part_IMMEDIATEMENT(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'autre moitie de la regle : synchrone sans geste supplementaire."""
        traces = self._doubler(monkeypatch)
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        reponse = await client.post(
            "/admin/referentiels/telcos",
            json={"pays": "CM", "network_name": "Nexttel CM", "short_name": "NXT",
                  "regex_msisdn": r"^237(66\d{7})$", "part_marche": 6.0,
                  "exemple_msisdn": "237661234567"},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        assert reponse.json()["config_service"]["statut"] == "envoye"
        assert traces["telcos_crees"] == ["Nexttel CM"]
        assert traces["rattaches"] == [("cfg-CM", "tl-Nexttel CM")], (
            "cree PUIS rattache — les deux gestes vont ensemble (US-B7)"
        )

    async def test_une_ville_sur_un_pays_HORS_operation_est_DIFFEREE_pas_en_echec(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Avant : la reponse disait « echec » pour un comportement NORMAL —
        un mot faux qui affole l'ecran et pousse a re-tenter pour rien."""
        traces = self._doubler(monkeypatch)
        entetes = await self._fiche_ethiopie(client)
        region = await client.post(
            "/admin/referentiels/regions",
            json={"pays": "ET", "nom": "Oromia", "capitale": "Adama"},
            headers=entetes,
        )
        assert region.status_code == 201, region.text
        reponse = await client.post(
            "/admin/referentiels/villes",
            json={"region_id": region.json()["region"]["id"], "nom": "Adama",
                  "latitude": 8.54, "longitude": 39.27, "population": 400000,
                  "poids_economique": 1.0},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        assert reponse.json()["config_service"]["statut"] == "differe"
        assert traces["villes"] == [], "rien ne part pour un pays absent"

    async def test_une_plateforme_MUETTE_ne_conclut_a_rien(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Zero-trust : l'ABSENCE et le SILENCE sont deux faits differents.
        Dire « pas en operation » a cause d'un incident reseau serait une
        conclusion inventee."""
        traces = self._doubler(monkeypatch, muet=True)
        entetes = await self._fiche_ethiopie(client)
        reponse = await client.post(
            "/admin/referentiels/telcos", json=self.TELCO_ET, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        envoi = reponse.json()["config_service"]
        assert envoi["statut"] == "indetermine", envoi
        assert traces["telcos_crees"] == []


class TestPaysConfigRelecture:
    """23/08 — la RELECTURE de l'aller `US-B6`. Campagne QA sur la prod : on
    pouvait POUSSER un pays sans jamais pouvoir RELIRE ce qui avait atterri
    la-bas. `GET /pays-config` est l'oeil qui manquait."""

    @staticmethod
    def _doubler(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
        from app.routes import admin_referentiels

        class _Lecture:
            async def lister_pays(self):  # type: ignore[no-untyped-def]
                return [
                    {  # complet
                        "_id": "cfg-CM", "iso_name": "CM", "name_en": "Cameroon",
                        "name_fr": "Cameroun", "dial_code": "237",
                        "region": "Middle Africa", "continent": "Africa",
                        "is_active": True, "cities": ["Douala", "Yaoundé"],
                        "currencies": ["d-xaf"], "telcos": [{"_id": "t-1"}],
                    },
                    {  # amputee : champs vides, ville fantome, telco absent
                        "_id": "cfg-GN", "iso_name": "GN", "name_en": "Guinea",
                        "name_fr": "", "dial_code": "", "region": "Western Africa",
                        "continent": "Africa", "is_active": True,
                        "cities": ["Conakry", "", "Conakry"], "currencies": [],
                        "telcos": [],
                    },
                    {"_id": "cfg-ca", "iso_name": "ca", "cities": [], "telcos": []},
                ]

            async def lister_telcos(self):  # type: ignore[no-untyped-def]
                return [{"_id": "t-1", "network_name": "MTN Cameroon"}]

            async def lister_devises(self):  # type: ignore[no-untyped-def]
                return [{"_id": "d-xaf", "iso_name": "XAF"}]

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_referentiels, "_config_lecture", lambda: _Lecture())

    async def test_la_relecture_resout_les_UUID_en_NOMS(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un ecran qui affiche `d694b215-…` n'apprend rien a personne : la
        devise et les operateurs sont rendus par leur NOM."""
        self._doubler(monkeypatch)
        entetes = await _session_complete(client)
        reponse = await client.get("/admin/referentiels/pays-config", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        par_code = {ligne["iso2"]: ligne for ligne in reponse.json()["pays"]}
        assert par_code["CM"]["devises"] == ["XAF"]
        assert par_code["CM"]["telcos"] == ["MTN Cameroon"]
        assert par_code["CM"]["champs"]["dial_code"] == "237"

    async def test_les_ECARTS_sont_mesures_champ_par_champ(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler(monkeypatch)
        entetes = await _session_complete(client)
        par_code = {
            ligne["iso2"]: ligne
            for ligne in (
                await client.get("/admin/referentiels/pays-config", headers=entetes)
            ).json()["pays"]
        }
        ecarts = par_code["GN"]["ecarts"]
        assert "name_fr" in ecarts["champs_vides"] and "dial_code" in ecarts["champs_vides"]
        assert ecarts["villes_fantomes"] == 2, "une chaine vide + un doublon"
        assert par_code["CM"]["ecarts"]["champs_vides"] == []

    async def test_le_pays_hors_loader_est_MONTRE_jamais_cache(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Le 4e etat : present la-bas, inconnu de nous — le residu `ca`
        minuscule de la plateforme, vu a la recon du 14/08."""
        self._doubler(monkeypatch)
        entetes = await _session_complete(client)
        corps = (
            await client.get("/admin/referentiels/pays-config", headers=entetes)
        ).json()
        parasite = next(ligne for ligne in corps["pays"] if ligne["iso2"] == "CA")
        assert parasite["connu_du_loader"] is False
        assert parasite["ecarts"]["hors_loader"] is True
        assert corps["compte"] == 3
        assert corps["sans_ecart"] < corps["compte"], (
            "le compteur ne peut pas dire « tout va bien » quand un pays est ampute"
        )

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        assert (
            await client.get("/admin/referentiels/pays-config")
        ).status_code == 401


class TestRefusDeDesactivationDeDevise:
    """23/08 — mesure sur la PROD : `GNF` n'a AUCUN porteur, et le refus lui
    repondait « referencee par [] ». Un message faux dans un systeme qui se
    veut honnete est un defaut, pas un detail."""

    async def test_devise_PORTEE_le_refus_nomme_les_porteurs(self) -> None:
        from app.clients.config_service import AdministrationConfigService, ReferenceInverse

        admin = AdministrationConfigService()

        async def _porteurs(_id, _famille):  # type: ignore[no-untyped-def]
            return ["SN", "BF", "CI"]

        admin.references_inverses = _porteurs  # type: ignore[method-assign]
        with pytest.raises(ReferenceInverse) as refus:
            await admin.desactiver_devise("d-xof")
        assert "referencee par ['SN', 'BF', 'CI']" in str(refus.value)
        assert "zone monetaire" in str(refus.value)

    async def test_devise_ORPHELINE_le_refus_dit_la_VRAIE_raison(self) -> None:
        from app.clients.config_service import AdministrationConfigService, ReferenceInverse

        admin = AdministrationConfigService()

        async def _aucun(_id, _famille):  # type: ignore[no-untyped-def]
            return []

        admin.references_inverses = _aucun  # type: ignore[method-assign]
        with pytest.raises(ReferenceInverse) as refus:
            await admin.desactiver_devise("d-gnf")
        message = str(refus.value)
        assert "AUCUN pays" in message, "le message ne ment plus"
        assert "IRREVERSIBLE" in message, "la vraie raison du refus est dite"
        assert "referencee par []" not in message


class TestVarianteApercu:
    """16/08 — « regenerer une variante » : la reponse propre a « je veux
    modifier le genere ». On n'edite pas la composition — on en tire une
    AUTRE, coherente, et la MEME variante redonne la MEME fiche (CR-03)."""

    async def test_variante_change_le_tirage_mais_reste_reproductible(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        appels = TestUSD1CompanyALUnite._doubler_executeur(monkeypatch)
        entetes = await _session_complete(client)
        base = dict(TestUSD1CompanyALUnite.DEMANDE)

        for variante in (0, 1, 1):
            reponse = await client.post(
                "/admin/entites/companies/apercu",
                json={**base, "variante": variante},
                headers=entetes,
            )
            assert reponse.status_code == 200, reponse.text

        v0, v1, v1bis = (a["patronyme"] for a in appels)
        assert v0 != v1, "une variante differente tire un AUTRE patronyme"
        assert v1 == v1bis, "la MEME variante redonne le MEME tirage (CR-03)"


class TestScenariosNommes:
    """16/08 — presets de configuration REJOUABLES. Appliquer passe par LE
    chemin du PUT : gardes comprises, reponse RELUE."""

    async def test_le_cycle_complet_sauver_appliquer_supprimer(
        self, client: httpx.AsyncClient
    ) -> None:
        await database.get_database()["loader_configuration"].delete_many(
            {"_id": "scenarios_admin"}
        )
        entetes = await _session_complete(client)

        creation = await client.post(
            "/admin/configuration/scenarios",
            json={"nom": "Demo client 200", "demande": {"nb_clients": 200}},
            headers=entetes,
        )
        assert creation.status_code == 201, creation.text
        assert creation.json()["scenario"]["cree_par"] == EMAIL

        # 409 homonyme — jamais d'ecrasement silencieux
        assert (
            await client.post(
                "/admin/configuration/scenarios",
                json={"nom": "Demo client 200", "demande": {"nb_clients": 300}},
                headers=entetes,
            )
        ).status_code == 409

        # Appliquer = le chemin du PUT : la vue RELUE porte la valeur
        application = await client.post(
            "/admin/configuration/scenarios/Demo client 200/appliquer",
            headers=entetes,
        )
        assert application.status_code == 200, application.text
        assert application.json()["nb_clients"]["valeur"] == 200

        # Lister puis supprimer
        liste = await client.get("/admin/configuration/scenarios", headers=entetes)
        assert liste.json()["compte"] == 1
        assert (
            await client.delete(
                "/admin/configuration/scenarios/Demo client 200", headers=entetes
            )
        ).status_code == 200
        assert (
            await client.post(
                "/admin/configuration/scenarios/Demo client 200/appliquer",
                headers=entetes,
            )
        ).status_code == 404


class TestDiffPayloadRelecture:
    """16/08 — la 3e recommandation validee par Yaniv : la relecture prouvait
    l'EXISTENCE (FRA-218), le diff prouve la FIDELITE. Chaque champ ENVOYE est
    confronte a la fiche RELUE ; une divergence n'invalide jamais la creation
    (201 maintenu), elle se DIT avec les deux valeurs en face."""

    async def _preparer_produits(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "produits_admin"}
        )
        await _registre_vierge()
        return entetes

    @staticmethod
    def _doubler_produits_avec(monkeypatch: pytest.MonkeyPatch, deformer):
        """Un product-service qui persiste `deformer(payload)` — l'identite
        pour un serveur fidele, une alteration pour un serveur qui trahit."""
        from app.routes import admin_entites

        etat: dict[str, Any] = {"fiche": None}

        class _Produits:
            async def chercher_par_short_name(self, marqueur):  # type: ignore[no-untyped-def]
                return etat["fiche"]

            async def chercher_par_nom(self, nom):  # type: ignore[no-untyped-def]
                return None

            async def creer_produit(self, payload):  # type: ignore[no-untyped-def]
                etat["fiche"] = {"_id": "p-1", **deformer(dict(payload))}
                return {"_id": "p-1"}

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_entites, "_client_produits", lambda: _Produits())

    async def test_produit_fidele_le_diff_le_PROUVE(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._doubler_produits_avec(monkeypatch, lambda p: p)
        entetes = await self._preparer_produits(client)
        reponse = await client.post(
            "/admin/entites/produits",
            json=TestUSD2ProduitALUnite.VALIDE_CASH,
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        diff = reponse.json()["diff_relecture"]
        assert diff["fidele"] is True
        assert diff["divergences"] == {}
        assert diff["absents_de_la_relecture"] == []
        assert diff["champs_compares"] >= 7, (
            "le payload produit entier est confronte, policy comprise"
        )

    async def test_produit_altere_la_creation_TIENT_et_l_ecart_se_DIT(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _trahir(payload: dict[str, Any]) -> dict[str, Any]:
            payload["name"] = str(payload["name"]).upper()  # normalise en douce
            payload.pop("segment")  # perdu a la persistance
            return payload

        self._doubler_produits_avec(monkeypatch, _trahir)
        entetes = await self._preparer_produits(client)
        reponse = await client.post(
            "/admin/entites/produits",
            json=TestUSD2ProduitALUnite.VALIDE_CASH,
            headers=entetes,
        )
        assert reponse.status_code == 201, (
            "l'entite EXISTE — une divergence n'est jamais une erreur HTTP"
        )
        diff = reponse.json()["diff_relecture"]
        assert diff["fidele"] is False
        assert "name" in diff["divergences"]
        assert diff["divergences"]["name"]["envoye"] != diff["divergences"]["name"]["relu"]
        assert diff["absents_de_la_relecture"] == ["segment"]

    async def test_depositaire_FRA199_currency_perdue_est_DITE(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE cas qui a motive le diff : depositary-service peut perdre
        `currency` a la persistance (FRA-199) — avant, la fiche relue etait
        rendue telle quelle et l'admin comparait a l'oeil."""
        from app.routes import admin_entites

        etat: dict[str, Any] = {"liste": []}

        class _Depositaires:
            async def chercher_par_nom(self, nom):  # type: ignore[no-untyped-def]
                cible = nom.strip().lower()
                return next(
                    (d for d in etat["liste"] if str(d.get("name", "")).lower() == cible),
                    None,
                )

            async def creer(self, nom, devise, company_id):  # type: ignore[no-untyped-def]
                fiche = {"_id": "dep-1", "name": nom, "company_id": company_id}
                etat["liste"].append(fiche)  # currency JAMAIS persistee (FRA-199)
                return fiche

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        class _Companies:
            async def obtenir_company(self, company_id):  # type: ignore[no-untyped-def]
                return {"name": "DEMO_SARL Douala", "currency": "XAF"}

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(
            admin_entites, "_client_depositaires_unite", lambda: _Depositaires()
        )
        monkeypatch.setattr(
            admin_entites, "_client_companies_unite", lambda: _Companies()
        )
        await TestUSD3DepositaireALUnite._company_a_nous("cie-cm")
        await _registre_vierge()
        await database.get_database()["org_hierarchy"].delete_many({})
        qid, _ = TestUSD3DepositaireALUnite._un_quartier("CM")
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/depositaires",
            json={"quartier_id": qid, "company_id": "cie-cm"},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        diff = reponse.json()["diff_relecture"]
        assert diff["fidele"] is False
        assert diff["absents_de_la_relecture"] == ["currency"]
        assert diff["divergences"] == {}, "name et company_id, eux, sont fideles"

    async def test_groupe_les_permissions_reordonnees_restent_FIDELES(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'ordre d'une liste appartient au serveur — son CONTENU a nous."""
        from app.routes import admin_entites, admin_referentiels

        etat: dict[str, Any] = {"groupes": []}

        class _Users:
            async def lister_permissions(self):  # type: ignore[no-untyped-def]
                return ["CLIENT_CLIENT_ONBOARD", "USER_USER_CREATE"]

            async def chercher_groupe(self, nom):  # type: ignore[no-untyped-def]
                cible = nom.strip().lower()
                for g in etat["groupes"]:
                    if str(g.get("name", "")).strip().lower() == cible:
                        return g
                return None

            async def creer_groupe(self, **kwargs):  # type: ignore[no-untyped-def]
                groupe = {
                    "_id": "g-diff-1",
                    "name": kwargs["nom"],
                    "description": kwargs["description"],
                    "tag": kwargs["tag"].value,
                    "company_id": kwargs["company_id"],
                    # Le serveur rend la liste dans SON ordre — pas le notre.
                    "permissions": list(reversed(kwargs["permissions"])),
                }
                etat["groupes"].append(groupe)
                return groupe

            async def fermer(self):  # type: ignore[no-untyped-def]
                return None

        monkeypatch.setattr(admin_entites, "_client_users", lambda: _Users())
        monkeypatch.setattr(admin_referentiels, "_client_users", lambda: _Users())
        await _registre_vierge()
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/groupes",
            json={
                "nom": "Auditeur Diff",
                "description": "Banc du diff payload-relecture",
                "tag": "STAFF",
                "permissions": ["USER_USER_CREATE", "CLIENT_CLIENT_ONBOARD"],
            },
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        diff = reponse.json()["diff_relecture"]
        assert diff["fidele"] is True, (
            "permissions comparees en CONTENU : reordonner n'est pas trahir"
        )

    async def test_company_le_payload_capture_est_confronte_a_la_RELECTURE(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L'executeur capture le payload CONTRACTUEL au moment de l'envoi
        (rapport.payload_company) ; la route RELIT la plateforme et confronte
        — ici le serveur a tronque le nom, et ca se DIT."""
        from app.routes import admin_entites

        ENVOYE = {
            "name": "DEMO_Composee", "short_name": "DEMO_CMP",
            "type": "MERCHANT", "industries": ["Retail Trade"],
            "sectors": ["Commerce"], "currency": "XAF",
        }

        class _Companies:
            async def chercher_par_short_name(self, court):  # type: ignore[no-untyped-def]
                return {"_id": "cid-1", **ENVOYE, "name": "DEMO_Compose"}

        class _Executeur:
            def __init__(self, mode):
                self.mode = mode
                self._companies = _Companies()

            def _telephone_du_pays(self, pays, index):
                return "+237650009999"

            async def creer_company(self, *, rapport, **kwargs):  # type: ignore[no-untyped-def]
                rapport.companies_creees.append("DEMO_Composee")
                rapport.admins_crees.append("admin@x.finzuu.com")
                rapport.cascades_identity_verifiees += 1
                rapport.payload_company = dict(ENVOYE)
                return {"_id": "cid-1", "name": "DEMO_Composee"}

            async def creer_licence(self, company_id, packages, debut, fin, rapport):  # type: ignore[no-untyped-def]
                rapport.licences_creees.append(company_id)

        monkeypatch.setattr(
            admin_entites,
            "_executeur_organisation",
            lambda mode, referentiel=None: _Executeur(mode),
        )

        class _LecturePays:
            async def lister_pays(self):
                return [
                    {"_id": f"cfg-{code}", "iso_name": code}
                    for code in ("CM", "CI", "BF", "SN")
                ]

            async def fermer(self):
                return None

        from app.routes import admin_referentiels

        monkeypatch.setattr(
            admin_referentiels, "_config_lecture", lambda: _LecturePays()
        )
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/entites/companies",
            json={"type_company": "MERCHANT", "pays": "CM", "ville": "Douala"},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert corps["fiche_relue"]["_id"] == "cid-1", "la preuve vient de la RELECTURE"
        diff = corps["diff_relecture"]
        assert diff["fidele"] is False
        assert list(diff["divergences"]) == ["name"]
        assert diff["divergences"]["name"] == {
            "envoye": "DEMO_Composee",
            "relu": "DEMO_Compose",
        }


class TestAntiBruteForce:
    """I-AUTH-11 — le login se protege du brute-force par backoff auto-cicatrisant,
    et ne verrouille JAMAIS le compte (pas de CWE-645, la Disponibilite d'abord)."""

    async def test_le_brute_force_finit_en_429_avec_retry_after(
        self, client: httpx.AsyncClient
    ) -> None:
        # Sous le seuil : chaque echec est un 401 muet, aucun delai.
        for _ in range(6):
            r = await client.post(
                "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": "faux"}
            )
            assert r.status_code == 401, r.text
        # Au-dela : le cooldown mord — 429 GENERIQUE + Retry-After.
        bloque = await client.post(
            "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": "faux"}
        )
        assert bloque.status_code == 429, bloque.text
        assert int(bloque.headers["Retry-After"]) > 0
        # Le message ne nomme ni le compte ni la cause exacte (anti-enumeration).
        assert "compte" not in bloque.text.lower()

    async def test_un_login_reussi_efface_le_compteur(
        self, client: httpx.AsyncClient
    ) -> None:
        # Quelques echecs, puis une reussite : le compteur repart de zero.
        for _ in range(4):
            assert (
                await client.post(
                    "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": "faux"}
                )
            ).status_code == 401
        bon = await client.post(
            "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": MDP_INITIAL}
        )
        assert bon.status_code == 200, bon.text
        # Apres cicatrisation, 4 nouveaux echecs restent sous le seuil : aucun
        # 429 (sinon la reussite n'aurait pas remis le compteur a zero).
        for _ in range(4):
            r = await client.post(
                "/admin/auth/login", json={"email": EMAIL, "mot_de_passe": "faux"}
            )
            assert r.status_code == 401, r.text

    async def test_429_identique_pour_un_email_inexistant(
        self, client: httpx.AsyncClient
    ) -> None:
        """Anti-enumeration : le throttle se declenche pareil que le compte
        existe ou non — un 429 ne revele jamais l'existence d'un email."""
        inexistant = "fantome-inexistant@finzuu.com"
        for _ in range(6):
            r = await client.post(
                "/admin/auth/login",
                json={"email": inexistant, "mot_de_passe": "faux"},
            )
            assert r.status_code == 401, r.text
        bloque = await client.post(
            "/admin/auth/login", json={"email": inexistant, "mot_de_passe": "faux"}
        )
        assert bloque.status_code == 429, bloque.text


async def _session_avec_role(client: httpx.AsyncClient, email: str, role: str) -> dict[str, str]:
    """Cree un compte du role donne (via le super-admin bootstrap), fait son
    cycle premiere-connexion, renvoie ses en-tetes de session PLEINE."""
    admin = await _session_complete(client)
    creation = await client.post(
        "/admin/comptes", json={"email": email, "role": role}, headers=admin
    )
    initial = creation.json()["mot_de_passe_initial"]
    conn = await client.post(
        "/admin/auth/login", json={"email": email, "mot_de_passe": initial}
    )
    jeton0 = conn.json()["access_token"]
    reponse = await client.post(
        "/admin/auth/password",
        json={"ancien": initial, "nouveau": "cheval-agrafe-batterie-solide"},
        headers={"Authorization": f"Bearer {jeton0}"},
    )
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


class TestMatriceRBAC:
    """FZ-RBAC-LOADER — la permission est verifiee A L'API (403), pas seulement
    a l'UI. Viewer lit ; Admin opere ; seul le Super-Admin fait tout."""

    async def test_viewer_lit_mais_n_ecrit_pas(self, client: httpx.AsyncClient) -> None:
        v = await _session_avec_role(client, "viewer-rbac@finzuu.com", "viewer")
        # Lecture : autorisee.
        assert (
            await client.get("/admin/referentiels/produits-catalogue", headers=v)
        ).status_code == 200
        # Ecriture : refusee 403 AVANT tout effet (la garde tombe la premiere).
        ecr = await client.post(
            "/admin/referentiels/industries", json={"label": "RBAC-Interdit"}, headers=v
        )
        assert ecr.status_code == 403, ecr.text
        # Actions sensibles : refusees aussi.
        assert (await client.post("/admin/purge/preparer", json={}, headers=v)).status_code == 403
        assert (await client.get("/admin/comptes", headers=v)).status_code == 403

    async def test_admin_opere_mais_n_est_pas_super_admin(
        self, client: httpx.AsyncClient
    ) -> None:
        a = await _session_avec_role(client, "admin-rbac@finzuu.com", "admin")
        # Ecriture ordinaire : autorisee.
        cree = await client.post(
            "/admin/referentiels/industries",
            json={"label": "RBAC-Test-Industrie"},
            headers=a,
        )
        assert cree.status_code == 201, cree.text
        await client.delete("/admin/referentiels/industries/RBAC-Test-Industrie", headers=a)
        # Comptes et purge : reserves au Super-Admin -> 403 pour un Admin.
        assert (await client.get("/admin/comptes", headers=a)).status_code == 403
        assert (await client.post("/admin/purge/preparer", json={}, headers=a)).status_code == 403


class TestJournalAdmin:
    """Audit — le journal « qui a fait quoi, quand », réservé au Super-Admin."""

    async def test_le_journal_montre_qui_a_fait_quoi(self, client: httpx.AsyncClient) -> None:
        entetes = await _session_complete(client)
        await client.post(
            "/admin/comptes",
            json={"email": "trace-audit@finzuu.com", "role": "viewer"},
            headers=entetes,
        )
        reponse = await client.get("/admin/journal", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        entrees = reponse.json()["entrees"]
        assert any(
            e["acteur"] == EMAIL and "trace-audit@finzuu.com" in str(e["details"])
            for e in entrees
        ), entrees

    async def test_journal_reserve_au_super_admin(self, client: httpx.AsyncClient) -> None:
        a = await _session_avec_role(client, "admin-journal@finzuu.com", "admin")
        assert (await client.get("/admin/journal", headers=a)).status_code == 403


class TestC1FichesPays:
    """`C1` (22/08) — les 4 bugs de conception releves par l'audit prod.

    BUG-C1-02 : creer un pays DANS le Loader par l'API. BUG-C1-03 : le lister
    avec sa completude, et le voir dans /geographie meme sans regions.
    BUG-C1-04 : la reversibilite CFG-03 exposee en DELETE.
    """

    _EGYPTE: ClassVar[dict[str, Any]] = {
        "iso2": "EG",
        "nom_fr": "Égypte",
        "nom_en": "Egypt",
        "capitale": "Le Caire",
        "dial_code": "20",
        "devise_iso": "EGP",
        "tva_percent": 14.0,
        "timezone": "Africa/Cairo",
        "region_africa": "Northern Africa",
        "devise_nom": "Egyptian Pound",
        "devise_decimales": 2,
        "banque_centrale": "CBE",
    }

    async def _preparer(self, client: httpx.AsyncClient) -> dict[str, str]:
        entetes = await _session_complete(client)
        await database.get_collection("loader_configuration").delete_one(
            {"_id": "surcouche"}
        )
        return entetes

    async def test_get_pays_liste_les_fiches_avec_completude(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await self._preparer(client)
        reponse = await client.get("/admin/referentiels/pays", headers=entetes)
        assert reponse.status_code == 200, reponse.text
        # 4e etat de la machine (22/08) : rien la-bas qui nous soit inconnu
        # dans le double (les 4 cibles) -> liste VIDE, jamais null quand la
        # plateforme repond.
        assert reponse.json()["hors_loader"] == []
        fiches = reponse.json()["pays"]
        codes = {f["iso2"] for f in fiches}
        assert {"CM", "CI", "BF", "SN"} <= codes
        cm = next(f for f in fiches if f["iso2"] == "CM")
        assert cm["origine"] == "classeur"
        assert cm["tva_percent"] == 19.25
        assert cm["completude"]["regions"] == 10
        assert cm["completude"]["telcos"] >= 3

    async def test_une_fiche_importee_se_voit_partout(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await self._preparer(client)
        await _semer_fiche_pays(**self._EGYPTE)

        fiches = (
            await client.get("/admin/referentiels/pays", headers=entetes)
        ).json()["pays"]
        eg = next(f for f in fiches if f["iso2"] == "EG")
        assert eg["origine"] == "surcouche"
        assert eg["completude"] == {
            "regions": 0, "villes": 0, "quartiers": 0, "telcos": 0,
        }

        # BUG-C1-03 : un pays SANS region apparait dans l'arbre, regions vides
        arbre = (
            await client.get("/admin/referentiels/geographie", headers=entetes)
        ).json()["pays"]
        eg_arbre = next(p for p in arbre if p["pays"] == "EG")
        assert eg_arbre["regions"] == []

    async def test_la_creation_manuelle_de_pays_n_existe_plus(
        self, client: httpx.AsyncClient
    ) -> None:
        """Decision direction 22/08 : les pays entrent par l'IMPORT BACKEND
        uniquement — l'ecran ne cree pas de pays, il les voit, les pousse en
        operation, les retire."""
        entetes = await self._preparer(client)
        reponse = await client.post(
            "/admin/referentiels/pays", json=self._EGYPTE, headers=entetes
        )
        assert reponse.status_code == 405, reponse.text

    async def test_le_retrait_est_garde_puis_reversible(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await self._preparer(client)
        await _semer_fiche_pays(**self._EGYPTE)
        await client.post(
            "/admin/referentiels/regions",
            json={"pays": "EG", "nom": "Le Caire"},
            headers=entetes,
        )
        # garde anti-orphelin : le pays porte une region -> 422 explique
        refus = await client.delete(
            "/admin/referentiels/surcouche/EG", headers=entetes
        )
        assert refus.status_code == 422
        assert "porte encore" in refus.json()["detail"]
        # retirer l'enfant puis le pays — et sa devise forgee part avec lui
        region_id = "SC-EG-REG-LE-CAIRE"
        assert (
            await client.delete(
                f"/admin/referentiels/surcouche/{region_id}", headers=entetes
            )
        ).status_code == 200
        retrait = await client.delete(
            "/admin/referentiels/surcouche/EG", headers=entetes
        )
        assert retrait.status_code == 200
        assert "aucun ajout" in retrait.json()["surcouche"]["resume"]

    async def test_retirer_du_classeur_repond_404(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await self._preparer(client)
        reponse = await client.delete(
            "/admin/referentiels/surcouche/CM-CT-01", headers=entetes
        )
        assert reponse.status_code == 404
        assert "classeur est immuable" in reponse.json()["detail"]
