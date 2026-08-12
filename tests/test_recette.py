"""
tests/test_recette.py
=====================
Le module de recette — `CR-01` a `CR-12`.

**Ce que ces tests protegent avant tout** : qu'aucun critere ne puisse etre
declare TENU sans preuve. Le defaut que ce module corrige est precisement
celui-la — des controles ecrits et jamais declenches, donc une conformite
supposee. Un rapport qui declare « tenu » ce qu'il n'a pas mesure serait pire que
pas de rapport du tout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.cdc import PREFIXE_DONNEES
from app.models.enums import NiveauOrganisation, RunStatus
from app.services.recette import ControleRecette, Verdict

RUN_ID = UUID("4dc3a050-8a5a-48df-8933-7d81351ef8f5")

pytestmark = pytest.mark.asyncio


@dataclass(slots=True)
class _Noeud:
    name: str
    id: UUID = field(default_factory=uuid4)


class _HierarchieFausse:
    """Arbre en memoire. Aucun MongoDB : la recette ne doit dependre que de ce
    qu'on lui donne a lire."""

    def __init__(
        self,
        *,
        anomalies: list[str] | None = None,
        kiosques: int = 0,
        orphelins: list[str] | None = None,
        noms: list[str] | None = None,
        clients: int = 0,
    ) -> None:
        self._anomalies = anomalies or []
        self._kiosques = kiosques
        self._orphelins = orphelins or []
        self._noms = noms
        #: `EF-26` — les rattachements Client -> Kiosque. Zero par defaut :
        #: `CR-04` doit rester NON_VERIFIABLE tant qu'aucun run reel n'a eu lieu.
        self._clients = clients

    async def verifier_cr02(self, run_id: UUID) -> list[str]:
        return list(self._anomalies)

    async def compter_clients(self, run_id: UUID) -> int:
        return self._clients

    async def par_niveau(self, run_id: UUID, niveau: NiveauOrganisation) -> list[Any]:
        if niveau is NiveauOrganisation.KIOSQUE:
            noms = self._noms or [f"{PREFIXE_DONNEES}Kiosque {i}" for i in range(self._kiosques)]
            return [_Noeud(n) for n in noms[: self._kiosques or len(noms)]]
        return []

    async def kiosques_sans_agent(self, run_id: UUID) -> list[str]:
        return list(self._orphelins)


class _RegistreFaux:
    def __init__(self, *, total: int = 0, partiels: int = 0) -> None:
        self._total = total
        self._partiels = partiels

    async def compter(self, lender_type: Any = None) -> int:
        return self._total

    async def partiellement_initialises(self) -> list[Any]:
        return [object()] * self._partiels


class _AuditFaux:
    def __init__(self, *, entrees: dict[str, int] | None = None, orphelines: int = 0) -> None:
        self._entrees = entrees or {}
        self._orphelines = orphelines

    async def compter_par_type(self, run_id: UUID) -> dict[str, int]:
        return dict(self._entrees)

    async def intentions_orphelines(self, run_id: UUID) -> list[Any]:
        return [object()] * self._orphelines


def _controle(
    hierarchie: Any = None, registre: Any = None, audit: Any = None
) -> ControleRecette:
    return ControleRecette(
        run_id=RUN_ID,
        hierarchie=hierarchie or _HierarchieFausse(),
        registre=registre or _RegistreFaux(),
        audit=audit or _AuditFaux(),
    )


def _critere(rapport: Any, reference: str) -> Any:
    return next(c for c in rapport.criteres if c.reference == reference)


class TestAucuneConformiteSupposee:
    """Le coeur du module : sans donnee, jamais de verdict TENU."""

    async def test_un_run_vide_ne_declare_aucun_critere_tenu_a_tort(self) -> None:
        rapport = await _controle().executer()

        for reference in ("CR-02", "UC-09", "EF-13", "CR-06", "CR-07", "CR-04"):
            assert _critere(rapport, reference).verdict is Verdict.NON_VERIFIABLE, (
                f"{reference} ne doit JAMAIS etre tenu sans donnee"
            )

    async def test_chaque_non_verifiable_porte_sa_raison(self) -> None:
        rapport = await _controle().executer()
        for critere in rapport.criteres:
            if critere.verdict is Verdict.NON_VERIFIABLE:
                assert critere.detail, f"{critere.reference} non verifiable SANS raison"

    async def test_un_non_verifiable_suffit_a_rendre_le_run_partial(self) -> None:
        """Meme logique que `Issue.NON_LIVRE` : on ne declare pas COMPLETED ce
        qu'on n'a pas pu confronter."""
        rapport = await _controle().executer()
        assert rapport.statut is RunStatus.PARTIAL


class TestCR02:
    async def test_une_anomalie_geo_rend_le_critere_viole_et_le_run_failed(self) -> None:
        hier = _HierarchieFausse(anomalies=["Kiosque X sans district_id"], kiosques=3)
        rapport = await _controle(hierarchie=hier).executer()

        critere = _critere(rapport, "CR-02")
        assert critere.verdict is Verdict.VIOLE
        assert "1 anomalie" in critere.detail
        assert rapport.statut is RunStatus.FAILED

    async def test_un_arbre_sain_rend_le_critere_tenu(self) -> None:
        hier = _HierarchieFausse(kiosques=4)
        critere = _critere(await _controle(hierarchie=hier).executer(), "CR-02")
        assert critere.verdict is Verdict.TENU


class TestUC09:
    async def test_un_kiosque_sans_agent_est_une_violation(self) -> None:
        hier = _HierarchieFausse(kiosques=5, orphelins=["DEMO_Kiosque Plateau"])
        critere = _critere(await _controle(hierarchie=hier).executer(), "UC-09")
        assert critere.verdict is Verdict.VIOLE
        assert "Plateau" in critere.detail

    async def test_tous_les_kiosques_pourvus_est_tenu(self) -> None:
        hier = _HierarchieFausse(kiosques=5)
        critere = _critere(await _controle(hierarchie=hier).executer(), "UC-09")
        assert critere.verdict is Verdict.TENU


class TestEF13:
    async def test_un_lender_incomplet_est_signale(self) -> None:
        """`UC-10` autorise l'etat partiel — mais il doit etre VU."""
        critere = _critere(
            await _controle(registre=_RegistreFaux(total=16, partiels=2)).executer(), "EF-13"
        )
        assert critere.verdict is Verdict.VIOLE
        assert "2 Lender(s) sur 16" in critere.detail

    async def test_les_16_lenders_complets_sont_tenus(self) -> None:
        critere = _critere(await _controle(registre=_RegistreFaux(total=16)).executer(), "EF-13")
        assert critere.verdict is Verdict.TENU

    async def test_un_ecart_au_volume_du_cdc_est_dit_sans_etre_une_violation(self) -> None:
        critere = _critere(await _controle(registre=_RegistreFaux(total=12)).executer(), "EF-13")
        assert critere.verdict is Verdict.TENU
        assert "CDC en attend 16" in critere.detail


class TestCR06:
    async def test_une_intention_orpheline_viole_le_journal(self) -> None:
        audit = _AuditFaux(entrees={"Company": 18}, orphelines=3)
        critere = _critere(await _controle(audit=audit).executer(), "CR-06")
        assert critere.verdict is Verdict.VIOLE
        assert "INCONNU" in critere.detail

    async def test_un_journal_clos_est_tenu_et_ventile(self) -> None:
        audit = _AuditFaux(entrees={"Company": 18, "Lender": 16})
        critere = _critere(await _controle(audit=audit).executer(), "CR-06")
        assert critere.verdict is Verdict.TENU
        assert "Company 18" in critere.detail


class TestCR07:
    async def test_un_seul_nom_sans_prefixe_casse_la_reversibilite(self) -> None:
        """Sans outil de purge (`EF-65`), le prefixe EST la reversibilite. Une
        entite sans prefixe est un residu definitif."""
        hier = _HierarchieFausse(kiosques=2, noms=[f"{PREFIXE_DONNEES}Kiosque A", "Kiosque B"])
        critere = _critere(await _controle(hierarchie=hier).executer(), "CR-07")
        assert critere.verdict is Verdict.VIOLE
        assert "Kiosque B" in critere.detail

    async def test_toutes_prefixees_est_tenu(self) -> None:
        hier = _HierarchieFausse(kiosques=3)
        critere = _critere(await _controle(hierarchie=hier).executer(), "CR-07")
        assert critere.verdict is Verdict.TENU


class TestRapport:
    async def test_le_resume_porte_les_trois_comptes(self) -> None:
        texte = (await _controle().executer()).resume()
        assert "tenu(s)" in texte
        assert "viole(s)" in texte
        assert "non verifiable(s)" in texte

    async def test_les_criteres_du_sprint_5_sont_nommes_avec_leur_arbitrage(self) -> None:
        """Un critere bloque doit dire PAR QUOI. Sinon on relit le CDC pour le
        savoir, et personne ne le fait."""
        rapport = await _controle().executer()
        assert "A-07" in _critere(rapport, "CR-09").detail
        assert "A-04" in _critere(rapport, "CR-10").detail


class TestCR04:
    """`CR-04` — *« 2000 clients generes »*, rendu MESURABLE par `EF-26`.

    Ce critere annonçait « module Clients non livre », ce qui etait devenu faux :
    l'executeur existe. Ce qui manquait n'etait pas le module mais une TRACE cote
    Loader — la fiche Client rendue par le serveur ne porte aucun rattachement,
    donc rien ne permettait de compter *nos* clients sans balayer un inventaire
    partage avec toute l'equipe. Le noeud CLIENT est cette trace.
    """

    async def test_sans_rattachement_le_critere_reste_NON_VERIFIABLE(self) -> None:
        """Aucun run reel n'a encore eu lieu : le critere ne doit ni passer ni
        echouer, il doit se declarer non jugeable."""
        hier = _HierarchieFausse(kiosques=40, clients=0)
        critere = _critere(await _controle(hierarchie=hier).executer(), "CR-04")
        assert critere.verdict is Verdict.NON_VERIFIABLE
        assert "aucun client rattache" in critere.detail

    async def test_la_cible_atteinte_rend_le_critere_TENU(self) -> None:
        from app.core.cdc import NB_CLIENTS

        hier = _HierarchieFausse(kiosques=40, clients=NB_CLIENTS)
        critere = _critere(await _controle(hierarchie=hier).executer(), "CR-04")
        assert critere.verdict is Verdict.TENU
        assert str(NB_CLIENTS) in critere.detail

    async def test_un_compte_INCOMPLET_est_une_VIOLATION_pas_un_silence(self) -> None:
        """Un run qui rattache 1500 clients sur 2000 n'est pas « non
        verifiable » : il est mesure, et il est en dessous de la cible."""
        from app.core.cdc import NB_CLIENTS

        hier = _HierarchieFausse(kiosques=40, clients=NB_CLIENTS - 500)
        critere = _critere(await _controle(hierarchie=hier).executer(), "CR-04")
        assert critere.verdict is Verdict.VIOLE
        assert f"{NB_CLIENTS - 500} clients rattaches" in critere.detail
