"""
tests/test_attribution_ussd.py
==============================
Les preuves du mecanisme d'attribution — contrat FZ-CONTRAT-ATTRIB v0.3.1.

Trois proprietes n'existent que si un test les prouve (exigence de la
validation, 25/08) :

  1. L'ATOMICITE — deux attributions concurrentes sur le meme profil rendent
     deux clients DISTINCTS, ou l'une echoue en 409. Jamais le meme client.
     De la concurrence REELLE (`asyncio.gather` sur la vraie base Mongo),
     pas deux appels sequentiels deguises. INV-SIM-01, CR-06.
  2. L'IDEMPOTENCE — la meme cle rejouee rend la meme reponse 201, sans
     second tirage. Y compris apres un « redemarrage » (nouveau client HTTP,
     meme cle : le serveur ne voit pas la difference, c'est le point).
  3. LA DISTINCTION DES ECHECS — un 409 STOCK_EPUISE ne peut pas provenir
     d'une exception attrapee : un defaut serveur PROVOQUE rend 500,
     jamais 409.

Ces tests tournent contre Mongo REEL — un bouchon prouverait notre
implementation du bouchon.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from app.core import database
from app.core.config import settings
from app.main import app

pytestmark = pytest.mark.asyncio


# ── Le banc : API + base dediee + population semee ─────────────────────────


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """API sans session : les routes d'attribution sont PUBLIQUES (`ENF-07`) —
    qu'aucun en-tete d'authentification ne soit necessaire est en soi une
    verification du contrat §6."""
    database.connect()
    # Base dediee, comme test_admin_api — mais on ne peut pas monkeypatcher
    # dans une fixture partagee entre boucles : on pose directement.
    settings.mongodb_database = "loader_finzuu_tests_attribution"
    for nom in (
        database.COLLECTION_ORG_HIERARCHY,
        database.COLLECTION_ATTRIBUTION_BAUX,
        database.COLLECTION_AUDIT_TRAIL,
        database.COLLECTION_LOADER_CONFIGURATION,
    ):
        await database.get_database().drop_collection(nom)
    await database.ensure_indexes()

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    database.close()


async def _semer_clients(
    pays: str, genre: str, categorie: str, n: int, *, prefixe: str
) -> list[str]:
    """Seme des noeuds CLIENT dans la carte — la population attribuable.

    Insertion directe : le mecanisme est en LECTURE SEULE sur cette
    collection, le semis simule ce qu'un run REEL y ecrit (`P-04`).
    """
    collection = database.get_collection(database.COLLECTION_ORG_HIERARCHY)
    msisdns = []
    for i in range(n):
        msisdn = f"{prefixe}{i:04d}"
        msisdns.append(msisdn)
        await collection.insert_one(
            {
                "_id": str(uuid4()),
                "run_id": str(uuid4()),
                "niveau": "CLIENT",
                "parent_id": str(uuid4()),
                "company_id": str(uuid4()),
                "name": f"Client {msisdn}",
                "country_code": pays,
                "client_id": str(uuid4()),
                "gender": genre,
                "categorie": categorie,
            }
        )
    return msisdns


PROFIL = {"pays": "CM", "genre": "FEMALE", "categorie": "INDIVIDUAL"}
ROUTE = "/api/v1/attribution/attributions"


def _cle() -> str:
    return str(uuid4())


# ══════════════════════════════════════════════════════════════════════════
# 1. L'ATOMICITE — INV-SIM-01, CR-06
# ══════════════════════════════════════════════════════════════════════════


class TestAtomicite:
    async def test_le_duel_pool_de_UN(self, client: httpx.AsyncClient) -> None:
        """Deux appareils, UN client libre : exactement un 201 et un 409 —
        jamais deux 201, jamais le meme msisdn deux fois."""
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 1, prefixe="237699100")

        r1, r2 = await asyncio.gather(
            client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()}),
            client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()}),
        )
        statuts = sorted([r1.status_code, r2.status_code])
        assert statuts == [201, 409], f"attendu [201, 409], obtenu {statuts}"

        documents = await database.get_collection(
            database.COLLECTION_ATTRIBUTION_BAUX
        ).count_documents({})
        assert documents == 1, "UN bail, jamais deux, sur un pool de un"

    async def test_la_meute_25_requetes_sur_10_libres(
        self, client: httpx.AsyncClient
    ) -> None:
        """25 appareils simultanes, 10 clients : 10 gagnants portant 10 msisdn
        DEUX A DEUX DISTINCTS, 15 refus 409. C'est CR-06 en grand."""
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 10, prefixe="237699200")

        reponses = await asyncio.gather(
            *(
                client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()})
                for _ in range(25)
            )
        )
        gagnants = [r for r in reponses if r.status_code == 201]
        refus = [r for r in reponses if r.status_code == 409]
        assert len(gagnants) == 10, f"{len(gagnants)} gagnants au lieu de 10"
        assert len(refus) == 15

        msisdns = [r.json()["msisdn"] for r in gagnants]
        assert len(set(msisdns)) == 10, (
            f"DOUBLE ATTRIBUTION : {sorted(msisdns)} — INV-SIM-01 viole"
        )
        for r in refus:
            assert r.json()["code"] == "STOCK_EPUISE"

    async def test_le_vol_de_bail_echu(self, client: httpx.AsyncClient) -> None:
        """Un bail ECHU est libre (expiration passive). Deux voleurs
        simultanes : un seul gagne."""
        msisdns = await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 1, prefixe="237699300")
        # Le bail echu, pose directement : expire il y a une heure.
        maintenant = datetime.now(UTC)
        await database.get_collection(database.COLLECTION_ATTRIBUTION_BAUX).insert_one(
            {
                "_id": msisdns[0],
                "attribution_id": str(uuid4()),
                "cle_idempotence": str(uuid4()),
                "profil": dict(PROFIL),
                "attribue_le": maintenant - timedelta(days=8),
                "expire_le": maintenant - timedelta(hours=1),
            }
        )

        r1, r2 = await asyncio.gather(
            client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()}),
            client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()}),
        )
        assert sorted([r1.status_code, r2.status_code]) == [201, 409]
        gagnant = r1 if r1.status_code == 201 else r2
        assert gagnant.json()["msisdn"] == msisdns[0]
        # Et le bail est NEUF : echeance dans ~7 jours, pas dans le passe.
        expire = datetime.fromisoformat(gagnant.json()["expire_le"])
        assert expire > maintenant + timedelta(days=6)


# ══════════════════════════════════════════════════════════════════════════
# 2. L'IDEMPOTENCE — le trou de l'attribution perdue
# ══════════════════════════════════════════════════════════════════════════


class TestIdempotence:
    async def test_la_meme_cle_rejoue_le_meme_201(self, client: httpx.AsyncClient) -> None:
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 5, prefixe="237699400")
        cle = _cle()

        premier = await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": cle})
        assert premier.status_code == 201, premier.text
        rejeu = await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": cle})
        assert rejeu.status_code == 201

        assert rejeu.json() == premier.json(), "le rejeu doit rendre LE MEME bail"
        documents = await database.get_collection(
            database.COLLECTION_ATTRIBUTION_BAUX
        ).count_documents({})
        assert documents == 1, "un second tirage a eu lieu — le trou n'est pas ferme"

    async def test_le_rejeu_apres_redemarrage(self, client: httpx.AsyncClient) -> None:
        """Le cas qui compte (validation, 25/08) : l'application est TUEE
        entre l'emission et la reponse, redemarre, relit sa cle persistee
        (revision 0.3.1) et REJOUE. Cote serveur, un redemarrage client est
        invisible — un NOUVEAU client HTTP avec la meme cle le simule
        exactement."""
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 5, prefixe="237699500")
        cle = _cle()

        premier = await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": cle})
        assert premier.status_code == 201

        # « Redemarrage » : un client HTTP neuf, sans aucun etat partage.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as neuf:
            rejeu = await neuf.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": cle})
        assert rejeu.status_code == 201
        assert rejeu.json() == premier.json()

        documents = await database.get_collection(
            database.COLLECTION_ATTRIBUTION_BAUX
        ).count_documents({})
        assert documents == 1, "le premier client est perdu 7 jours — trou §0 rouvert"


# ══════════════════════════════════════════════════════════════════════════
# 3. LA DISTINCTION DES ECHECS — la propriete structurelle du 409
# ══════════════════════════════════════════════════════════════════════════


class TestDistinctionDesEchecs:
    async def test_pool_vide_rend_409_calcule(self, client: httpx.AsyncClient) -> None:
        """Zero client seme pour ce profil : 409 STOCK_EPUISE — un RESULTAT,
        pas une panne."""
        await _semer_clients("CM", "MALE", "CORPORATE", 3, prefixe="237699600")
        # Le profil demande (FEMALE/INDIVIDUAL) n'a AUCUN client.
        r = await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()})
        assert r.status_code == 409
        assert r.json()["code"] == "STOCK_EPUISE"
        assert r.json()["details"]["libres"] == 0

    async def test_un_defaut_serveur_PROVOQUE_rend_500_jamais_409(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LA preuve de la propriete structurelle (contrat §5) : on CASSE la
        lecture du pool — si l'implementation attrapait l'exception pour la
        transformer en « stock epuise », ce test la demasquerait."""
        from app.repositories.org_hierarchy import OrgHierarchyRepository

        async def _panne(self: Any, run_id: Any, niveau: Any) -> Any:
            raise RuntimeError("panne provoquee — la base ne repond plus")

        monkeypatch.setattr(OrgHierarchyRepository, "par_niveau", _panne)
        r = await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()})
        assert r.status_code == 500, (
            f"un defaut serveur a rendu {r.status_code} — s'il rend 409, un bug "
            "se deguise en stock epuise et l'ecran 11 ment"
        )

    async def test_criteres_hors_referentiel_rendent_422(
        self, client: httpx.AsyncClient
    ) -> None:
        for demande, motif in (
            ({"pays": "ZZ", "genre": "FEMALE", "categorie": "INDIVIDUAL"}, "pays inconnu"),
            ({"pays": "CM", "genre": "AUTRE", "categorie": "INDIVIDUAL"}, "genre inconnu"),
            ({"pays": "CM", "genre": "FEMALE", "categorie": "PME"}, "categorie inconnue"),
        ):
            r = await client.post(ROUTE, json=demande, headers={"Idempotency-Key": _cle()})
            assert r.status_code == 422, motif
            assert r.json()["code"] == "CRITERE_INVALIDE", motif

    async def test_cle_absente_rend_400(self, client: httpx.AsyncClient) -> None:
        r = await client.post(ROUTE, json=PROFIL)
        assert r.status_code == 400
        assert r.json()["code"] == "CLE_IDEMPOTENCE_REQUISE"


# ══════════════════════════════════════════════════════════════════════════
# Les criteres, la verification, la liberation, la garde de purge
# ══════════════════════════════════════════════════════════════════════════


class TestCriteres:
    async def test_une_combinaison_a_zero_APPARAIT_jamais_masquee(
        self, client: httpx.AsyncClient
    ) -> None:
        """Tranche a la validation (contrat §8) : l'application GRISE, elle ne
        cache pas — donc le serveur doit rendre la ligne a zero."""
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 2, prefixe="237699700")

        r = await client.get("/api/v1/attribution/criteres")
        assert r.status_code == 200, r.text
        corps = r.json()
        dispo = {
            (d["pays"], d["genre"], d["categorie"]): d["libres"]
            for d in corps["disponibilite"]
        }
        assert dispo[("CM", "FEMALE", "INDIVIDUAL")] == 2
        # Les 3 autres combinaisons du pays existent, A ZERO — jamais absentes.
        assert dispo[("CM", "MALE", "CORPORATE")] == 0
        assert dispo[("CM", "MALE", "INDIVIDUAL")] == 0
        assert dispo[("CM", "FEMALE", "CORPORATE")] == 0

    async def test_libres_decroit_avec_les_baux(self, client: httpx.AsyncClient) -> None:
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 3, prefixe="237699800")
        r = await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()})
        assert r.status_code == 201

        corps = (await client.get("/api/v1/attribution/criteres")).json()
        dispo = {
            (d["pays"], d["genre"], d["categorie"]): d["libres"]
            for d in corps["disponibilite"]
        }
        assert dispo[("CM", "FEMALE", "INDIVIDUAL")] == 2

    async def test_les_libelles_pays_sont_bilingues(self, client: httpx.AsyncClient) -> None:
        """`INV-SIM-07` cote serveur : les deux libelles en une lecture,
        l'application choisit, elle ne traduit rien."""
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 1, prefixe="237699850")
        corps = (await client.get("/api/v1/attribution/criteres")).json()
        cm = next(p for p in corps["pays"] if p["code"] == "CM")
        assert cm["libelle_fr"] and cm["libelle_en"]


class TestVerificationEtLiberation:
    async def test_verification_200_puis_404_apres_liberation(
        self, client: httpx.AsyncClient
    ) -> None:
        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 1, prefixe="237699900")
        bail = (
            await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()})
        ).json()

        # 200 tant que le bail est actif — meme corps que le 201 (contrat §3).
        v = await client.get(f"/api/v1/attribution/attributions/{bail['attribution_id']}")
        assert v.status_code == 200
        assert v.json() == bail

        # Liberation : 204, puis 404 (succes fonctionnel), et le msisdn
        # redevient tirable A L'INSTANT.
        s = await client.delete(f"/api/v1/attribution/attributions/{bail['attribution_id']}")
        assert s.status_code == 204
        encore = await client.delete(
            f"/api/v1/attribution/attributions/{bail['attribution_id']}"
        )
        assert encore.status_code == 404

        v2 = await client.get(f"/api/v1/attribution/attributions/{bail['attribution_id']}")
        assert v2.status_code == 404

        re_tire = await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()})
        assert re_tire.status_code == 201
        assert re_tire.json()["msisdn"] == bail["msisdn"]

    async def test_un_bail_echu_rend_404_pas_un_200_decore(
        self, client: httpx.AsyncClient
    ) -> None:
        """`expire_le < now` EST l'etat libre — pas d'etat intermediaire."""
        maintenant = datetime.now(UTC)
        attribution_id = str(uuid4())
        await database.get_collection(database.COLLECTION_ATTRIBUTION_BAUX).insert_one(
            {
                "_id": "237699999999",
                "attribution_id": attribution_id,
                "cle_idempotence": str(uuid4()),
                "profil": dict(PROFIL),
                "attribue_le": maintenant - timedelta(days=8),
                "expire_le": maintenant - timedelta(minutes=1),
            }
        )
        v = await client.get(f"/api/v1/attribution/attributions/{attribution_id}")
        assert v.status_code == 404


class TestGardeDePurge:
    async def test_la_purge_refuse_sous_bail_actif(self, client: httpx.AsyncClient) -> None:
        """`§1.5` (arbitrage Yaniv 24/08) : vider la carte avec un bail actif
        couperait une demonstration — REFUS explicite, jamais muet."""
        from app.repositories.super_admin import SuperAdminRepository

        await database.get_database().drop_collection(
            database.COLLECTION_SUPER_ADMIN_ACCOUNTS
        )
        await database.get_database().drop_collection(database.COLLECTION_AUTH_THROTTLE)
        await SuperAdminRepository().creer(
            "garde-purge@finzuu.com", "initial-garde-0101", role="super_admin"
        )
        connexion = await client.post(
            "/admin/auth/login",
            json={"email": "garde-purge@finzuu.com", "mot_de_passe": "initial-garde-0101"},
        )
        assert connexion.status_code == 200, connexion.text
        jeton = connexion.json()["access_token"]
        bascule = await client.post(
            "/admin/auth/password",
            headers={"Authorization": f"Bearer {jeton}"},
            json={"ancien": "initial-garde-0101", "nouveau": "prairie-cadran-mouette-77"},
        )
        assert bascule.status_code == 200, bascule.text
        entetes = {"Authorization": f"Bearer {bascule.json()['access_token']}"}

        await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 1, prefixe="237699950")
        bail = (
            await client.post(ROUTE, json=PROFIL, headers={"Idempotency-Key": _cle()})
        ).json()

        refus = await client.post(
            "/admin/purge/confirmer",
            headers=entetes,
            json={"supprimer_groupes": False, "vider_notre_base": True},
        )
        assert refus.status_code == 409, refus.text
        assert "bail" in refus.json()["detail"]

        # Apres liberation (EF-17), la purge rouvre.
        await client.delete(f"/api/v1/attribution/attributions/{bail['attribution_id']}")
        accord = await client.post(
            "/admin/purge/confirmer",
            headers=entetes,
            json={"supprimer_groupes": False, "vider_notre_base": True},
        )
        assert accord.status_code == 200, accord.text
