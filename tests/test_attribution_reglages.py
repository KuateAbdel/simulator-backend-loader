"""
tests/test_attribution_reglages.py
==================================
Les preuves du contrat 0.4 §(b) — LA DUREE REGLABLE — et de la REVOCATION
d'administration.

Quatre proprietes n'existent que si un test les prouve :

  1. LA DUREE S'APPLIQUE — un bail tire apres un reglage porte l'echeance du
     reglage, globale ou surchargee par pays. Mesuree sur `expire_le`, pas sur
     une intention.
  2. UN BAIL EST UNE PROMESSE DATEE — un bail tire AVANT le changement garde
     son echeance. C'est l'option 1 de la revision, et c'est ce qui rend le
     reglage sans danger pour les telephones en main de l'equipe QA.
  3. LA REVOCATION REND LE CLIENT AU POOL — et l'appareil le decouvre en 404
     a sa verification, exactement comme une expiration.
  4. LES DEUX SUJETS NE SE MELANGENT PAS — le reglage du bail n'ecrit RIEN
     dans `loader_configuration`, la collection de la machinerie d'execution.
     Aucun run n'est concerne par une duree de bail.

Contre Mongo REEL, comme `test_attribution_ussd` : un bouchon prouverait notre
implementation du bouchon.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from app.core import database
from app.core.config import settings
from app.main import app
from app.repositories.super_admin import SuperAdminRepository

pytestmark = pytest.mark.asyncio

EMAIL = "pilote-reglages@finzuu.com"
MDP_INITIAL = "initial-bootstrap-7742"
MDP_DURABLE = "chariot-lanterne-sable-27aout"  # conforme I-AUTH-9

EMAIL_ADMIN = "admin-simple@finzuu.com"
MDP_ADMIN_INITIAL = "initial-bootstrap-5518"
MDP_ADMIN_DURABLE = "fenetre-cordage-prairie-27aout"

ROUTE_PUBLIQUE = "/api/v1/attribution/attributions"
ROUTE_REGLAGES = "/admin/attributions/reglages"
PROFIL_CM = {"pays": "CM", "genre": "FEMALE", "categorie": "INDIVIDUAL"}
PROFIL_BF = {"pays": "BF", "genre": "MALE", "categorie": "INDIVIDUAL"}


#: Les index sont poses UNE FOIS pour toute la session, pas a chaque test.
#: `drop_collection` + `ensure_indexes()` par test reconstruisait une
#: vingtaine d'index 35 fois — mesure du 27/08 : ~100 s ajoutees a la suite
#: complete. VIDER une collection ne detruit pas ses index ; les supprimer
#: pour les recreer aussitot etait du travail pur perte. L'isolation est
#: identique : chaque test part de collections vides.
#:
#: Ce n'est pas qu'une question de vitesse. Une suite plus lente charge la
#: machine, et une course sensible a la charge ailleurs dans le projet
#: (`TestC2VerrouParRessource`) perd plus souvent — mesure du meme jour.
_INDEX_POSES = False


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """API + base dediee + population semee + compte super_admin de bootstrap."""
    global _INDEX_POSES
    database.connect()
    settings.mongodb_database = "loader_finzuu_tests_reglages"
    if not _INDEX_POSES:
        await database.ensure_indexes()
        _INDEX_POSES = True
    for nom in (
        database.COLLECTION_ORG_HIERARCHY,
        database.COLLECTION_ATTRIBUTION_BAUX,
        database.COLLECTION_ATTRIBUTION_REGLAGES,
        database.COLLECTION_AUDIT_TRAIL,
        database.COLLECTION_LOADER_CONFIGURATION,
        database.COLLECTION_SUPER_ADMIN_ACCOUNTS,
        database.COLLECTION_AUTH_THROTTLE,
    ):
        await database.get_collection(nom).delete_many({})
    await SuperAdminRepository().creer(EMAIL, MDP_INITIAL, role="super_admin")

    await _semer_clients("CM", "FEMALE", "INDIVIDUAL", 5, prefixe="23760010")
    await _semer_clients("BF", "MALE", "INDIVIDUAL", 5, prefixe="22660010")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    database.close()


async def _semer_clients(
    pays: str, genre: str, categorie: str, n: int, *, prefixe: str
) -> list[str]:
    """Seme des noeuds CLIENT — le mecanisme est en LECTURE SEULE dessus."""
    collection = database.get_collection(database.COLLECTION_ORG_HIERARCHY)
    msisdns = []
    for i in range(n):
        msisdn = f"{prefixe}{i:02d}"
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


async def _entetes(
    client: httpx.AsyncClient,
    email: str = EMAIL,
    initial: str = MDP_INITIAL,
    durable: str = MDP_DURABLE,
) -> dict[str, str]:
    """Login + changement de mot de passe force -> jeton plein."""
    ouverture = await client.post(
        "/admin/auth/login", json={"email": email, "mot_de_passe": initial}
    )
    assert ouverture.status_code == 200, ouverture.text
    reponse = await client.post(
        "/admin/auth/password",
        json={"ancien": initial, "nouveau": durable},
        headers={"Authorization": f"Bearer {ouverture.json()['access_token']}"},
    )
    assert reponse.status_code == 200, reponse.text
    return {"Authorization": f"Bearer {reponse.json()['access_token']}"}


async def _attribuer(client: httpx.AsyncClient, profil: dict[str, str]) -> dict[str, Any]:
    reponse = await client.post(
        ROUTE_PUBLIQUE, json=profil, headers={"Idempotency-Key": str(uuid4())}
    )
    assert reponse.status_code == 201, reponse.text
    return dict(reponse.json())


def _jours_de_bail(bail: dict[str, Any]) -> float:
    """La duree REELLE portee par le bail, mesuree sur ses deux dates."""
    debut = datetime.fromisoformat(bail["attribue_le"])
    fin = datetime.fromisoformat(bail["expire_le"])
    return (fin - debut).total_seconds() / 86400


# ══════════════════════════════════════════════════════════════════════════
# 1. LA DUREE S'APPLIQUE — contrat 0.4 §(b)
# ══════════════════════════════════════════════════════════════════════════


class TestDureeReglable:
    async def test_sans_reglage_le_defaut_du_cdc_vaut(self, client: httpx.AsyncClient) -> None:
        """L'etat initial n'est pas un cas d'erreur : sept jours, version 0."""
        entetes = await _entetes(client)
        lecture = await client.get(ROUTE_REGLAGES, headers=entetes)
        assert lecture.status_code == 200, lecture.text
        assert lecture.json()["reglages"] == {"jours_defaut": 7, "par_pays": {}}
        assert lecture.json()["version"] == 0

        bail = await _attribuer(client, PROFIL_CM)
        assert _jours_de_bail(bail) == pytest.approx(7.0, abs=0.01)

    async def test_la_valeur_globale_s_applique_au_tirage_suivant(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _entetes(client)
        reglage = await client.put(ROUTE_REGLAGES, json={"jours_defaut": 3}, headers=entetes)
        assert reglage.status_code == 200, reglage.text
        assert reglage.json()["version"] == 1

        bail = await _attribuer(client, PROFIL_CM)
        assert _jours_de_bail(bail) == pytest.approx(3.0, abs=0.01)

    async def test_la_surcharge_pays_prime_sur_la_globale(self, client: httpx.AsyncClient) -> None:
        """Deux pays, deux durees, dans la MEME base et le meme instant."""
        entetes = await _entetes(client)
        reponse = await client.put(
            ROUTE_REGLAGES,
            json={"jours_defaut": 10, "par_pays": {"bf": 1}},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        #: Le code pays est normalise en majuscules — « bf » et « BF » sont le
        #: meme pays, l'operateur ne doit pas avoir a le savoir.
        assert reponse.json()["reglages"]["par_pays"] == {"BF": 1}

        assert _jours_de_bail(await _attribuer(client, PROFIL_CM)) == pytest.approx(10.0, abs=0.01)
        assert _jours_de_bail(await _attribuer(client, PROFIL_BF)) == pytest.approx(1.0, abs=0.01)

    async def test_le_reglage_n_est_jamais_mis_en_cache(self, client: httpx.AsyncClient) -> None:
        """Change entre deux attributions -> vaut des la suivante, sans
        redemarrage du service. C'est ce que « resolue AU MOMENT du tirage »
        veut dire."""
        entetes = await _entetes(client)
        await client.put(ROUTE_REGLAGES, json={"jours_defaut": 2}, headers=entetes)
        premier = await _attribuer(client, PROFIL_CM)
        await client.put(ROUTE_REGLAGES, json={"jours_defaut": 9}, headers=entetes)
        second = await _attribuer(client, PROFIL_CM)

        assert _jours_de_bail(premier) == pytest.approx(2.0, abs=0.01)
        assert _jours_de_bail(second) == pytest.approx(9.0, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════
# 2. UN BAIL EST UNE PROMESSE DATEE — option 1 de la revision 0.4
# ══════════════════════════════════════════════════════════════════════════


class TestPromesseDatee:
    async def test_un_bail_deja_tire_garde_son_echeance(self, client: httpx.AsyncClient) -> None:
        """LE test de la revision : baisser la duree ne raccourcit AUCUN bail
        en cours. Un telephone de l'equipe QA ne perd pas son numero parce
        qu'un operateur a change un reglage."""
        entetes = await _entetes(client)
        bail = await _attribuer(client, PROFIL_CM)
        echeance_promise = bail["expire_le"]
        assert _jours_de_bail(bail) == pytest.approx(7.0, abs=0.01)

        await client.put(ROUTE_REGLAGES, json={"jours_defaut": 1}, headers=entetes)

        recensement = await client.get("/admin/attributions", headers=entetes)
        assert recensement.status_code == 200, recensement.text
        ligne = next(b for b in recensement.json()["baux"] if b["msisdn"] == bail["msisdn"])
        assert ligne["expire_le"] == echeance_promise, (
            "le bail a ete reecrit par un reglage posterieur — une promesse datee ne se relit pas"
        )

        verification = await client.get(f"{ROUTE_PUBLIQUE}/{bail['attribution_id']}")
        assert verification.status_code == 200
        assert verification.json()["expire_le"] == echeance_promise


# ══════════════════════════════════════════════════════════════════════════
# 3. LES REFUS — bornes et referentiel, TOUJOURS avant l'ecriture
# ══════════════════════════════════════════════════════════════════════════


class TestRefus:
    @pytest.mark.parametrize("jours", [0, 31, -3])
    async def test_hors_bornes_refuse_en_422(self, client: httpx.AsyncClient, jours: int) -> None:
        entetes = await _entetes(client)
        reponse = await client.put(ROUTE_REGLAGES, json={"jours_defaut": jours}, headers=entetes)
        assert reponse.status_code == 422, reponse.text
        assert "globale" in str(reponse.json()["detail"])

    @pytest.mark.parametrize("jours", [1, 30])
    async def test_les_bornes_elles_memes_sont_acceptees(
        self, client: httpx.AsyncClient, jours: int
    ) -> None:
        """Bornes INCLUSIVES — 1 et 30 sont des reglages valides."""
        entetes = await _entetes(client)
        reponse = await client.put(ROUTE_REGLAGES, json={"jours_defaut": jours}, headers=entetes)
        assert reponse.status_code == 200, reponse.text
        assert _jours_de_bail(await _attribuer(client, PROFIL_CM)) == pytest.approx(
            float(jours), abs=0.01
        )

    async def test_la_surcharge_hors_bornes_nomme_le_pays(self, client: httpx.AsyncClient) -> None:
        entetes = await _entetes(client)
        reponse = await client.put(
            ROUTE_REGLAGES,
            json={"jours_defaut": 7, "par_pays": {"BF": 99}},
            headers=entetes,
        )
        assert reponse.status_code == 422, reponse.text
        assert "BF" in str(reponse.json()["detail"])

    async def test_un_pays_hors_referentiel_est_refuse(self, client: httpx.AsyncClient) -> None:
        """Une surcharge sur un code mal frappe ne s'appliquerait jamais et
        rien ne le signalerait : l'operateur croirait avoir regle ce pays."""
        entetes = await _entetes(client)
        reponse = await client.put(
            ROUTE_REGLAGES,
            json={"jours_defaut": 7, "par_pays": {"ZZ": 3}},
            headers=entetes,
        )
        assert reponse.status_code == 422, reponse.text
        assert "ZZ" in str(reponse.json()["detail"])

    async def test_un_refus_n_ecrit_rien(self, client: httpx.AsyncClient) -> None:
        """REFUS AVANT ECRITURE : la version ne bouge pas d'un refus."""
        entetes = await _entetes(client)
        await client.put(ROUTE_REGLAGES, json={"jours_defaut": 4}, headers=entetes)
        await client.put(ROUTE_REGLAGES, json={"jours_defaut": 999}, headers=entetes)

        lecture = await client.get(ROUTE_REGLAGES, headers=entetes)
        assert lecture.json()["reglages"]["jours_defaut"] == 4
        assert lecture.json()["version"] == 1


# ══════════════════════════════════════════════════════════════════════════
# 3 bis. LE FAIL-SAFE — un réglage de confort ne fait jamais tomber le tirage
# ══════════════════════════════════════════════════════════════════════════


class TestFailSafe:
    async def test_un_reglage_illisible_n_empeche_pas_une_attribution(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LE test du fail-safe : la lecture du réglage EXPLOSE, et le tirage
        aboutit quand même — sept jours, la valeur du CDC. Couper le service
        pour protéger un détail de confort serait la faute inverse."""
        from app.repositories import attribution_reglages

        async def lecture_qui_explose(self: object) -> None:
            raise RuntimeError("base injoignable pendant la lecture du réglage")

        monkeypatch.setattr(
            attribution_reglages.ReglagesBailRepository, "charger", lecture_qui_explose
        )
        bail = await _attribuer(client, PROFIL_CM)
        assert _jours_de_bail(bail) == pytest.approx(7.0, abs=0.01)

    @pytest.mark.parametrize("valeur", ["sept", -3, 0, 999, None, True])
    async def test_une_valeur_globale_absurde_en_base_est_ignoree(
        self, client: httpx.AsyncClient, valeur: object
    ) -> None:
        """La route PUT valide, mais elle n'est pas le seul chemin vers ce
        document : correction à la main, restauration, migration ratée. Une
        valeur que personne n'a validée ne doit pas atteindre un bail."""
        entetes = await _entetes(client)
        await client.put(ROUTE_REGLAGES, json={"jours_defaut": 5}, headers=entetes)
        await database.get_collection(
            database.COLLECTION_ATTRIBUTION_REGLAGES
        ).update_one({"_id": "courant"}, {"$set": {"jours_defaut": valeur}})

        bail = await _attribuer(client, PROFIL_CM)
        assert _jours_de_bail(bail) == pytest.approx(7.0, abs=0.01)

    async def test_une_surcharge_pays_absurde_laisse_la_globale_agir(
        self, client: httpx.AsyncClient
    ) -> None:
        """Une surcharge illisible disparaît — le pays suit la globale. Elle
        n'emporte NI le réglage global, NI les autres pays."""
        entetes = await _entetes(client)
        await client.put(
            ROUTE_REGLAGES,
            json={"jours_defaut": 4, "par_pays": {"BF": 2}},
            headers=entetes,
        )
        await database.get_collection(
            database.COLLECTION_ATTRIBUTION_REGLAGES
        ).update_one({"_id": "courant"}, {"$set": {"par_pays.BF": "deux"}})

        assert _jours_de_bail(await _attribuer(client, PROFIL_BF)) == pytest.approx(
            4.0, abs=0.01
        )
        assert _jours_de_bail(await _attribuer(client, PROFIL_CM)) == pytest.approx(
            4.0, abs=0.01
        )


# ══════════════════════════════════════════════════════════════════════════
# 3 ter. LES BAUX EN COURS — la promesse « inchangés » devient un chiffre
# ══════════════════════════════════════════════════════════════════════════


class TestBauxEnCours:
    async def test_le_recensement_montre_le_bail_reste_sous_l_ancien_reglage(
        self, client: httpx.AsyncClient
    ) -> None:
        """Un bail tiré à 7 j puis un réglage à 1 j : le recensement doit DIRE
        que ce bail court encore sous l'ancien réglage. Sans cela, « les baux
        existants sont inchangés » reste invisible à l'écran."""
        entetes = await _entetes(client)
        bail = await _attribuer(client, PROFIL_CM)
        await client.put(ROUTE_REGLAGES, json={"jours_defaut": 1}, headers=entetes)

        recensement = await client.get("/admin/attributions", headers=entetes)
        corps = recensement.json()
        ligne = next(b for b in corps["baux"] if b["msisdn"] == bail["msisdn"])

        assert ligne["accorde_pour_jours"] == 7
        assert ligne["jours_si_attribue_maintenant"] == 1
        assert ligne["sous_ancien_reglage"] is True
        assert corps["sous_ancien_reglage"] == 1
        assert corps["reglage_courant"]["jours_defaut"] == 1

    async def test_sans_changement_aucun_bail_n_est_signale(
        self, client: httpx.AsyncClient
    ) -> None:
        """Le drapeau ne crie pas pour rien : sans changement de réglage,
        aucun bail n'est « sous l'ancien réglage »."""
        entetes = await _entetes(client)
        await _attribuer(client, PROFIL_CM)
        corps = (await client.get("/admin/attributions", headers=entetes)).json()

        assert corps["sous_ancien_reglage"] == 0
        assert all(b["sous_ancien_reglage"] is False for b in corps["baux"])

    async def test_le_reglage_chiffre_ce_qu_il_ne_touche_pas(
        self, client: httpx.AsyncClient
    ) -> None:
        """Le PUT rend le NOMBRE de baux qui gardent leur échéance et jusqu'à
        quand court le plus long — une promesse non chiffrée n'est pas
        vérifiable."""
        entetes = await _entetes(client)
        premier = await _attribuer(client, PROFIL_CM)
        await _attribuer(client, PROFIL_BF)

        reponse = await client.put(
            ROUTE_REGLAGES, json={"jours_defaut": 2}, headers=entetes
        )
        assert reponse.status_code == 200, reponse.text
        existants = reponse.json()["baux_existants"]

        assert existants["actifs_inchanges"] == 2
        assert existants["plus_longue_echeance"] is not None
        #: L'échéance annoncée est bien celle d'un bail RÉEL, pas un calcul.
        recensement = await client.get("/admin/attributions", headers=entetes)
        echeances = {b["expire_le"] for b in recensement.json()["baux"]}
        assert existants["plus_longue_echeance"] in echeances
        assert premier["expire_le"] in echeances


# ══════════════════════════════════════════════════════════════════════════
# 4. LA REVOCATION — le geste dedie et journalise
# ══════════════════════════════════════════════════════════════════════════


class TestRevocation:
    async def test_le_bail_revoque_rend_le_client_au_pool(self, client: httpx.AsyncClient) -> None:
        entetes = await _entetes(client)
        bail = await _attribuer(client, PROFIL_CM)

        reponse = await client.request(
            "DELETE",
            f"/admin/attributions/{bail['msisdn']}",
            json={"motif": "téléphone rendu par le testeur"},
            headers=entetes,
        )
        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["msisdn"] == bail["msisdn"]
        assert reponse.json()["revoque_par"] == EMAIL

        recensement = await client.get("/admin/attributions", headers=entetes)
        assert bail["msisdn"] not in {b["msisdn"] for b in recensement.json()["baux"]}

    async def test_l_appareil_le_decouvre_en_404(self, client: httpx.AsyncClient) -> None:
        """Aucun canal descendant n'existe (`ENF-05`) : l'appareil apprend la
        rupture a sa prochaine verification, et sa conduite est celle de
        l'expiration — ecran 13, retour a la composition."""
        entetes = await _entetes(client)
        bail = await _attribuer(client, PROFIL_CM)
        assert (await client.get(f"{ROUTE_PUBLIQUE}/{bail['attribution_id']}")).status_code == 200

        await client.request(
            "DELETE",
            f"/admin/attributions/{bail['msisdn']}",
            json={"motif": "bail orphelin, recensement du jour"},
            headers=entetes,
        )

        perdu = await client.get(f"{ROUTE_PUBLIQUE}/{bail['attribution_id']}")
        assert perdu.status_code == 404
        assert perdu.json()["code"] == "BAIL_INCONNU"

    async def test_le_motif_est_obligatoire(self, client: httpx.AsyncClient) -> None:
        """Une revocation sans motif est le « clic silencieux » que ce module
        s'interdit depuis sa premiere version."""
        entetes = await _entetes(client)
        bail = await _attribuer(client, PROFIL_CM)

        for corps in ({}, {"motif": ""}, {"motif": "  "}):
            reponse = await client.request(
                "DELETE",
                f"/admin/attributions/{bail['msisdn']}",
                json=corps,
                headers=entetes,
            )
            assert reponse.status_code == 422, (corps, reponse.text)

        recensement = await client.get("/admin/attributions", headers=entetes)
        assert bail["msisdn"] in {b["msisdn"] for b in recensement.json()["baux"]}

    async def test_un_numero_sans_bail_rend_404(self, client: httpx.AsyncClient) -> None:
        """On ne rend pas 204 « par confort » : l'operateur doit savoir s'il a
        coupe quelque chose ou frappe dans le vide."""
        entetes = await _entetes(client)
        reponse = await client.request(
            "DELETE",
            "/admin/attributions/237600000000",
            json={"motif": "essai sur un numéro sans bail"},
            headers=entetes,
        )
        assert reponse.status_code == 404, reponse.text

    async def test_la_revocation_entre_au_journal_avec_son_motif(
        self, client: httpx.AsyncClient
    ) -> None:
        entetes = await _entetes(client)
        bail = await _attribuer(client, PROFIL_CM)
        await client.request(
            "DELETE",
            f"/admin/attributions/{bail['msisdn']}",
            json={"motif": "appareil volé — coupure demandée par le QA Lead"},
            headers=entetes,
        )

        journal = await client.get("/admin/journal", headers=entetes)
        assert journal.status_code == 200, journal.text
        ligne = next(
            e
            for e in journal.json()["entrees"]
            if e["operation"] == "REVOKE" and e["cible"] == bail["msisdn"]
        )
        assert ligne["acteur"] == EMAIL, "un geste d'administration a un auteur"
        assert ligne["issue"] == "SUCCES"
        assert "volé" in str(ligne["details"]["motif"])

    async def test_les_deux_gestes_inscrivent_leur_origine(
        self, client: httpx.AsyncClient
    ) -> None:
        """LA distinction du journal (demande QA 27/08) : liberation par
        l'appareil et revocation par l'administration effacent le meme bail.
        « Rendu par le partenaire » et « repris ici » ne sont PAS la meme
        information — l'origine est donc ECRITE dans les deux traces, jamais
        deduite de l'absence d'auteur."""
        entetes = await _entetes(client)

        #: 1. Le geste de l'APPAREIL — DELETE public, EF-17.
        rendu = await _attribuer(client, PROFIL_CM)
        libere = await client.delete(f"{ROUTE_PUBLIQUE}/{rendu['attribution_id']}")
        assert libere.status_code == 204, libere.text

        #: 2. Le geste de l'ADMINISTRATION — sur un autre bail.
        repris = await _attribuer(client, PROFIL_CM)
        revoque = await client.request(
            "DELETE",
            f"/admin/attributions/{repris['msisdn']}",
            json={"motif": "reprise par l'administration"},
            headers=entetes,
        )
        assert revoque.status_code == 200, revoque.text

        journal = await client.get("/admin/journal", headers=entetes)
        entrees = journal.json()["entrees"]

        par_appareil = next(
            e for e in entrees if e["cible"] == rendu["msisdn"] and e["operation"] == "DELETE"
        )
        par_administration = next(
            e for e in entrees if e["cible"] == repris["msisdn"] and e["operation"] == "REVOKE"
        )

        assert par_appareil["origine"] == "appareil"
        assert par_appareil["acteur"] == "simulateur USSD (route publique)"
        assert par_administration["origine"] == "administration"
        assert par_administration["acteur"] == EMAIL

        #: Les deux lignes ne se confondent NI par l'origine, NI par l'acteur,
        #: NI par l'operation — trois lectures independantes du meme fait.
        assert par_appareil["origine"] != par_administration["origine"]
        assert par_appareil["acteur"] != par_administration["acteur"]
        assert par_appareil["operation"] != par_administration["operation"]

    async def test_l_attribution_aussi_porte_son_origine(
        self, client: httpx.AsyncClient
    ) -> None:
        """Pas seulement les ruptures : un bail NAIT d'un appareil, et la
        trace CREATE le dit — sinon l'origine ne se lirait qu'a la fin."""
        entetes = await _entetes(client)
        bail = await _attribuer(client, PROFIL_CM)

        journal = await client.get("/admin/journal", headers=entetes)
        creation = next(
            e
            for e in journal.json()["entrees"]
            if e["cible"] == bail["msisdn"] and e["operation"] == "CREATE"
        )
        assert creation["origine"] == "appareil"

    async def test_un_admin_simple_ne_peut_pas_revoquer(self, client: httpx.AsyncClient) -> None:
        """Reserve au super_admin comme la purge : ce geste coupe un appareil
        EXTERNE, la seule chose du Loader dont un tiers depend a l'instant."""
        await _entetes(client)  # le super_admin existe, il n'agit pas ici
        bail = await _attribuer(client, PROFIL_CM)
        await SuperAdminRepository().creer(EMAIL_ADMIN, MDP_ADMIN_INITIAL, role="admin")
        entetes_admin = await _entetes(client, EMAIL_ADMIN, MDP_ADMIN_INITIAL, MDP_ADMIN_DURABLE)

        reponse = await client.request(
            "DELETE",
            f"/admin/attributions/{bail['msisdn']}",
            json={"motif": "tentative depuis un rôle insuffisant"},
            headers=entetes_admin,
        )
        assert reponse.status_code == 403, reponse.text

        #: ...mais il LIT le recensement et le reglage : voir n'est pas couper.
        assert (await client.get("/admin/attributions", headers=entetes_admin)).status_code == 200
        assert (await client.get(ROUTE_REGLAGES, headers=entetes_admin)).status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 5. LES DEUX SUJETS NE SE MELANGENT PAS
# ══════════════════════════════════════════════════════════════════════════


class TestSeparationDesSujets:
    async def test_le_reglage_n_ecrit_rien_dans_la_configuration_des_runs(
        self, client: httpx.AsyncClient
    ) -> None:
        """Un reglage de bail ne touche PAS `loader_configuration` — ni la
        configuration d'un run, ni la surcouche referentielle, ni le registre
        produits. Il vit dans sa propre collection."""
        entetes = await _entetes(client)
        configuration = database.get_collection(database.COLLECTION_LOADER_CONFIGURATION)
        assert await configuration.count_documents({}) == 0

        await client.put(
            ROUTE_REGLAGES,
            json={"jours_defaut": 5, "par_pays": {"BF": 2}},
            headers=entetes,
        )

        assert await configuration.count_documents({}) == 0, (
            "le réglage du bail a écrit dans la collection de la machinerie "
            "d'exécution — deux sujets, deux collections"
        )
        reglages = database.get_collection(database.COLLECTION_ATTRIBUTION_REGLAGES)
        assert await reglages.count_documents({}) == 1

    async def test_le_reglage_survit_a_la_purge(self) -> None:
        """La purge vide NOTRE CARTE. Un choix d'exploitation n'en fait pas
        partie : vider la carte ne remet pas la duree a sept jours."""
        from app.routes.admin_purge import (
            COLLECTIONS_NOTRE_CARTE,
            COLLECTIONS_PROTEGEES,
        )

        assert database.COLLECTION_ATTRIBUTION_REGLAGES in COLLECTIONS_PROTEGEES
        assert database.COLLECTION_ATTRIBUTION_REGLAGES not in COLLECTIONS_NOTRE_CARTE

    async def test_aucun_run_n_est_touche_par_une_revocation(
        self, client: httpx.AsyncClient
    ) -> None:
        """La revocation ne supprime QUE le bail : le client reste dans la
        carte, disponible pour une attribution suivante. Le mecanisme n'ecrit
        JAMAIS dans la population du Loader (engagement du contrat)."""
        entetes = await _entetes(client)
        carte = database.get_collection(database.COLLECTION_ORG_HIERARCHY)
        avant = await carte.count_documents({})

        bail = await _attribuer(client, PROFIL_CM)
        await client.request(
            "DELETE",
            f"/admin/attributions/{bail['msisdn']}",
            json={"motif": "vérification de non-régression"},
            headers=entetes,
        )

        assert await carte.count_documents({}) == avant
        assert (await carte.count_documents({"name": f"Client {bail['msisdn']}"})) == 1, (
            "la révocation a effacé un client de la carte"
        )

        #: Et le numero est REELLEMENT re-attribuable — pas seulement present.
        libres = await client.get("/api/v1/attribution/criteres")
        combinaison = next(
            d
            for d in libres.json()["disponibilite"]
            if (d["pays"], d["genre"], d["categorie"]) == ("CM", "FEMALE", "INDIVIDUAL")
        )
        assert combinaison["libres"] == 5
