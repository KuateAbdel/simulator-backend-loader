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
from typing import Any

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
MDP_DURABLE = "un-mot-de-passe-durable-13aout"


@pytest_asyncio.fixture()
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """API + base dediee + compte bootstrap frais (must_change_password=True)."""
    monkeypatch.setattr(settings, "mongodb_database", "loader_finzuu_tests_api")
    database.connect()
    await database.get_database().drop_collection(
        database.COLLECTION_SUPER_ADMIN_ACCOUNTS
    )
    await SuperAdminRepository().creer(EMAIL, MDP_INITIAL)

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
            country_code="CM", msisdn="+237650000001", client_id=_uuid4(),
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
        from app.routes.admin_entites import RUN_ADMIN
        from app.repositories.audit_trail import AuditTrailRepository

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
