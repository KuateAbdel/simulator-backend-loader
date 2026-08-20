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
        from app.models.enums import RunStatus
        from app.repositories.loader_runs import LoaderRunRepository

        await database.get_database().drop_collection("loader_runs")
        run = LoaderRun(
            _id=_uuid4(), sim_start_date=_date(2026, 2, 14),
            sim_end_date=_date(2026, 8, 13), status=RunStatus.PARTIAL,
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
        assert corps["run_id"] == str(run.id)
        assert corps["quotas_par_pays"][0]["clients"] == {"mesure": 500, "cible": 500}
        assert corps["occupations"]["distinctes"] == 300
        assert "150 000 a 300 000" in corps["soldes"]["tranches"], (
            "150 000 doit etre une FRONTIERE de tranche — le seuil EF-68"
        )
        assert corps["naissances"]["a_l_etranger"] == 52

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
        reponse = await client.get("/admin/dashboard/population", headers=entetes)
        assert reponse.status_code == 404
        assert "mesures" in reponse.json()["detail"]

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
        assert corps["payload"]["short_name"] == "DEMO_TONT_MC"
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
        assert corps["fiche_relue"]["short_name"] == "DEMO_TONT_MC", (
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
            admin_entites, "_executeur_organisation", lambda mode: _Executeur(mode)
        )
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


class TestUSB6CreationDePays:
    """`US-B6` COMPLET (Yaniv 14/08) — creer un pays sur config-service, comme
    la ville et le telco, avec NOS invariants. config-service EXPOSE
    `POST /countries/create` (c'est ainsi que les 4 cibles ont ete creees)."""

    _GABON: ClassVar[dict[str, Any]] = {
        "iso_name": "GA", "name_en": "Gabon", "name_fr": "Gabon",
        "dial_code": "241", "region": "Middle Africa", "continent": "Africa",
        "devise_iso": "XAF", "cities": ["Libreville", "Port-Gentil"],
    }

    async def test_creer_un_pays_neuf_reussit_et_part_a_config_service(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays", json=self._GABON, headers=entetes
        )
        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert corps["pays"]["iso_name"] == "GA"
        assert corps["pays"]["devise"] == "XAF"
        assert corps["statut"] == "a_nous"
        assert len(_config_service_double["pays_crees"]) == 1, (
            "le pays part REELLEMENT a config-service (POST /countries/create)"
        )
        envoye = _config_service_double["pays_crees"][0]
        assert envoye["currencies"] == ["cur-xaf"], "la devise est resolue en UUID"
        assert "EF-05" in corps["note"], "creer le pays ne l'ajoute PAS a la generation"

    async def test_un_pays_qui_existe_deja_repond_409_jamais_un_double(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays",
            json={**self._GABON, "iso_name": "CM", "name_en": "Cameroon",
                  "name_fr": "Cameroun", "dial_code": "237"},
            headers=entetes,
        )
        assert reponse.status_code == 409, reponse.text
        assert "EXISTE deja" in reponse.json()["detail"]
        assert _config_service_double["pays_crees"] == [], "aucun doublon cree"

    async def test_une_devise_inconnue_est_refusee_AVANT_tout_POST(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays",
            json={**self._GABON, "devise_iso": "USD"},
            headers=entetes,
        )
        assert reponse.status_code == 422
        assert "devise" in reponse.json()["detail"]
        assert _config_service_double["pays_crees"] == [], "refus AVANT le POST"

    async def test_la_creation_est_journalisee_sous_RUN_ADMIN(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        from app.repositories.audit_trail import AuditTrailRepository
        from app.routes.admin_entites import RUN_ADMIN

        await _registre_vierge()
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays", json=self._GABON, headers=entetes
        )
        assert reponse.status_code == 201
        journal = await AuditTrailRepository().exporter_run(RUN_ADMIN)
        assert any(
            e.entity_type == "Country" and e.action == "INTENTION" for e in journal
        ), "la creation d'un pays laisse SA trace write-ahead"

    async def test_le_verrou_EF_55_couvre_la_creation_de_pays(
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
                "/admin/referentiels/pays", json=self._GABON, headers=entetes
            )
            assert reponse.status_code == 409
            assert "EF-55" in reponse.json()["detail"]
        finally:
            await database.get_database().drop_collection("loader_runs")

    async def test_un_iso_mal_forme_est_un_422_de_validation(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/pays",
            json={**self._GABON, "iso_name": "gabon"},
            headers=entetes,
        )
        assert reponse.status_code == 422

    async def test_sans_jeton_401(self, client: httpx.AsyncClient) -> None:
        reponse = await client.post(
            "/admin/referentiels/pays", json={"code": "GA"}
        )
        assert reponse.status_code == 401


class TestCreationDeMonnaie:
    """Creer une monnaie sur config-service (Yaniv 14/08) — meme patron que le
    pays : formulaire pur, GET-avant-POST, 409 si existe, EF-55, journal."""

    async def test_creer_une_monnaie_neuve_part_a_config_service(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/devises",
            json={"iso_name": "NGN", "name_en": "Naira", "name_fr": "Naira",
                  "accepts_decimal": True},
            headers=entetes,
        )
        assert reponse.status_code == 201, reponse.text
        assert reponse.json()["devise"]["iso_name"] == "NGN"
        assert len(_config_service_double["devises_creees"]) == 1
        assert _config_service_double["devises_creees"][0]["accepts_decimal"] is True

    async def test_une_monnaie_existante_repond_409_jamais_un_double(
        self, client: httpx.AsyncClient, _config_service_double: dict[str, Any]
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/devises",
            json={"iso_name": "XOF", "name_en": "CFA", "name_fr": "Franc CFA"},
            headers=entetes,
        )
        assert reponse.status_code == 409
        assert "EXISTE deja" in reponse.json()["detail"]
        assert _config_service_double["devises_creees"] == []

    async def test_un_code_devise_mal_forme_422(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _session_complete(client)
        reponse = await client.post(
            "/admin/referentiels/devises",
            json={"iso_name": "xof", "name_en": "x", "name_fr": "x"},
            headers=entetes,
        )
        assert reponse.status_code == 422

    async def test_le_verrou_EF_55_couvre_la_monnaie(
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
                "/admin/referentiels/devises",
                json={"iso_name": "GHS", "name_en": "Cedi", "name_fr": "Cedi"},
                headers=entetes,
            )
            assert reponse.status_code == 409
            assert "EF-55" in reponse.json()["detail"]
        finally:
            await database.get_database().drop_collection("loader_runs")


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
                {"_id": f"cfg-{code}", "iso_name": code}
                for code in ("CM", "CI", "BF", "SN")
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
        assert corps["payload"]["name"] == f"DEMO_Kiosque {qnom}"
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
            admin_entites, "_executeur_organisation", lambda mode: _Executeur(mode)
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
