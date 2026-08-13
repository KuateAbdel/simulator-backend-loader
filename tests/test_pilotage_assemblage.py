"""
tests/test_pilotage_assemblage.py
=================================
AU-5 — le test d'ASSEMBLAGE du moteur (`pilotage.executer`), en CI.

Avant ce test, les briques etaient couvertes (executeurs a 86-99 %) mais
l'assemblage — l'ordre des huit modules, le verrou, la persistance du run,
le rapport, les mesures, la reconciliation — n'etait prouve que par des
DRY_RUN manuels hors pytest. C'etait le point bas de l'audit (30 %).

Les HUIT clients HTTP sont doubles (aucun reseau) ; MongoDB est la base de
TEST dediee ; le mode est DRY_RUN — exactement le chemin qu'un operateur
declenche, borne a un petit perimetre pour rester rapide.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

import tests.test_clients_execution as tex
from app.core import database
from app.core.config import settings
from app.core.configuration import ConfigurationExecution
from app.models.enums import RunMode, RunStatus
from app.repositories.loader_runs import LoaderRunRepository
from app.services.pilotage import ClientsHTTP, executer


class _LectureVide:
    """Un double de service en LECTURE SEULE : tout ce qui liste rend vide,
    tout ce qui cherche rend None — l'etat d'un environnement vierge. En
    DRY_RUN, AUCUNE methode d'ecriture ne doit etre atteinte : ce double n'en
    porte pas, et un appel d'ecriture leverait AttributeError — le test
    tomberait, et c'est voulu."""

    def __init__(self) -> None:
        self.appels: list[str] = []

    async def fermer(self) -> None:
        return None

    # Helpers PURS des vrais clients (aucun reseau) — autorises tels quels.
    @staticmethod
    def identifiant(fiche: Any) -> Any:
        return (fiche or {}).get("_id") or (fiche or {}).get("id")

    @staticmethod
    def identifiant_owner(fiche: Any) -> Any:
        return ((fiche or {}).get("owner") or {}).get("_id")

    @staticmethod
    def valider_type_produit(type_produit: Any) -> None:
        return None

    def __getattr__(self, nom: str) -> Any:
        if nom.startswith(("lister", "chercher", "inventaire", "souscriptions")):
            async def _lecture(*args: Any, **kwargs: Any) -> Any:
                self.appels.append(nom)
                return [] if nom.startswith(("lister", "inventaire", "souscriptions")) else None

            return _lecture
        raise AttributeError(nom)


class _ComptesAssemblage(tex.FauxComptes):
    """Le FauxComptes des tests d'execution + TOUS les constructeurs de
    payload du vrai client (purs — aucune methode `payload*` ne touche le
    reseau, ce sont des compositions de dictionnaires)."""

    def __getattr__(self, nom: str) -> Any:
        if nom.startswith("payload"):
            from app.clients.account_service import AccountServiceClient

            reel = getattr(AccountServiceClient, nom)

            def _builder(*args: Any, **kwargs: Any) -> Any:
                return reel(self, *args, **kwargs)

            return _builder
        raise AttributeError(nom)


class _UsersLecture(_LectureVide):
    async def lister_permissions(self) -> list[str]:
        return [f"PERM_{i}" for i in range(30)]


def _fermable(objet: Any) -> Any:
    """Ajoute un `fermer()` inerte aux doubles qui n'en ont pas — le moteur
    ferme ses huit clients dans son `finally`, doubles compris."""
    if not hasattr(objet, "fermer"):
        async def fermer() -> None:
            return None

        objet.fermer = fermer
    return objet


@pytest_asyncio.fixture()
async def base_de_test(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    monkeypatch.setattr(settings, "mongodb_database", "loader_finzuu_tests_api")
    database.connect()
    collections = ("loader_runs", "audit_trail", "faker_consumption_ledger",
                   "org_hierarchy", "lenders_registry")
    for collection in collections:
        await database.get_database().drop_collection(collection)
    yield
    # Nettoyage de SORTIE aussi : le test du verrou seme un run RUNNING — le
    # laisser empoisonnerait tout test EF-55 execute apres (mesure : 5 tests
    # de configuration tombes en 409 avant ce teardown).
    for collection in collections:
        await database.get_database().drop_collection(collection)
    database.close()


async def test_AU5_le_moteur_ENTIER_s_assemble_a_vide(base_de_test: None) -> None:
    """Le DRY_RUN complet, huit modules, zero reseau : le run est persiste
    avec sa configuration figee, son rapport, ses mesures et ses checkpoints,
    et la reconciliation est close."""
    configuration = ConfigurationExecution.defaut_cdc()
    for pays in ("CI", "BF", "SN"):
        configuration.desactiver_pays(pays, "assemblage borne a un pays")
    configuration.nb_clients = 40

    run_id = uuid4()
    lignes: list[str] = []
    code = await executer(
        RunMode.DRY_RUN,
        run_id=run_id,
        configuration=configuration,
        sortie=lignes.append,
        gerer_connexion=False,
        clients_http=ClientsHTTP(
            users=_UsersLecture(),
            faker=_fermable(tex.FauxFaker()),
            clients=_fermable(tex.FauxClientService()),
            companies=_LectureVide(),
            comptes=_fermable(_ComptesAssemblage()),
            produits=_LectureVide(),
            depositaires=_LectureVide(),
            identites=_LectureVide(),
        ),
    )
    assert code == 0, "\n".join(lignes[-15:])

    run = await LoaderRunRepository().obtenir(run_id)
    assert run is not None, "le run doit etre PERSISTE (EF-64)"
    assert run.status in (RunStatus.COMPLETED, RunStatus.PARTIAL)
    assert run.configuration["nb_clients"] == 40, "la configuration est FIGEE (D-10)"
    assert len(run.checkpoints) >= 7, "les huit modules posent leurs checkpoints"
    assert run.mesures, "les mesures de population partent avec le run (US-E3)"
    assert run.mesures["quotas_par_pays"][0]["clients"]["mesure"] == 40

    rapport = "\n".join(lignes)
    assert "STATUT" in rapport
    assert "aucune intention orpheline" in rapport, "la reconciliation est CLOSE"
    assert "CM : 40/40" in rapport, "le perimetre borne est respecte"


async def test_AU5_le_verrou_EF55_refuse_au_niveau_du_MOTEUR(
    base_de_test: None,
) -> None:
    """Pas seulement les routes : le moteur lui-meme refuse un second run."""
    from datetime import date as _date

    from app.models.domain import LoaderRun

    depot = LoaderRunRepository()
    await depot.remplacer(
        LoaderRun(
            _id=uuid4(), sim_start_date=_date(2026, 2, 1),
            sim_end_date=_date(2026, 8, 1), status=RunStatus.RUNNING,
        )
    )
    lignes: list[str] = []
    code = await executer(
        RunMode.DRY_RUN,
        sortie=lignes.append,
        gerer_connexion=False,
        clients_http=ClientsHTTP(
            users=_UsersLecture(), faker=_fermable(tex.FauxFaker()),
            clients=_fermable(tex.FauxClientService()), companies=_LectureVide(),
            comptes=_fermable(_ComptesAssemblage()), produits=_LectureVide(),
            depositaires=_LectureVide(), identites=_LectureVide(),
        ),
    )
    assert code == 2
    assert any("EF-55" in ligne for ligne in lignes)
