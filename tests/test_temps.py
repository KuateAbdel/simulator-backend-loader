"""
tests/test_temps.py
===================
Le squelette temporel — `EF-76`, `ENF-16`, `EF-71`, `UC-03` point 4.

**Ce que ces tests protegent avant tout** : que personne ne confonde un jour de
SIMULATION avec un jour REEL. C'est le malentendu le plus couteux de toute la
simulation — il produirait soit un tableau de bord plat (tout horodate a la meme
seconde), soit des prets nes avant leur client.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.cdc import FENETRE_JOURS
from app.core.temps import (
    ACCELERE_MAX,
    ACCELERE_MIN,
    JOURS_CYCLE_CREDIT,
    SECONDES_PAR_JOUR_CALENDAIRE,
    SECONDES_PAR_JOUR_REALISTE,
    FenetreInvalide,
    ModeCompression,
    TempsSimulation,
)

DEBUT = date(2026, 2, 12)
FIN = date(2026, 8, 11)


def _temps(**kwargs: object) -> TempsSimulation:
    base: dict[str, object] = {"debut": DEBUT, "fin": FIN}
    base.update(kwargs)
    return TempsSimulation(**base)  # type: ignore[arg-type]


class TestLaFenetre:
    def test_la_fenetre_par_defaut_fait_180_jours(self) -> None:
        """`ENF-16` — et la conformite est une PROPRIETE, pas un commentaire."""
        t = _temps()
        assert t.nb_jours == FENETRE_JOURS
        assert t.conforme_enf16

    def test_une_fenetre_hors_180_jours_est_signalee_sans_etre_refusee(self) -> None:
        """`ENF-16` la dit **parametrable** : 90 jours est legitime, mais l'ecart
        doit se voir. On ne refuse pas ce que le CDC autorise."""
        t = _temps(fin=date(2026, 5, 13))
        assert t.nb_jours == 90
        assert not t.conforme_enf16
        assert "ECART a ENF-16" in t.resume()

    def test_une_fenetre_inversee_est_refusee(self) -> None:
        with pytest.raises(FenetreInvalide, match="inversee"):
            TempsSimulation(debut=FIN, fin=DEBUT)

    def test_l_ancre_est_toujours_en_UTC(self) -> None:
        """Quatre pays, deux fuseaux. Un evenement date en heure locale serait
        incomparable a celui du pays voisin."""
        assert _temps().ancre.tzinfo is UTC
        assert _temps().ancre == datetime(2026, 2, 12, tzinfo=UTC)


class TestUnJourDeSimulationNEstPasUnJourReel:
    """Le coeur du module. La formule de Duhamel :
    `horodatage = ancre + (jour x SECONDES_PAR_JOUR)`."""

    def test_le_mode_realiste_reprend_la_valeur_de_duhamel(self) -> None:
        """`SECONDES_PAR_JOUR_REPLI = 226.49` du script Duhamel EST le mode
        « realiste » de l'Annexe D.3 : « environ 226 secondes »."""
        t = _temps(mode=ModeCompression.REALISTE)
        assert t.secondes_par_jour == SECONDES_PAR_JOUR_REALISTE

    def test_en_realiste_les_180_jours_tiennent_en_moins_de_12_heures(self) -> None:
        """Le chiffre qui rend le malentendu visible."""
        heures = _temps(mode=ModeCompression.REALISTE).duree_reelle.total_seconds() / 3600
        assert 11.0 < heures < 12.0

    def test_en_accelere_a_10_s_par_jour_le_cycle_tient_en_une_demi_heure(self) -> None:
        """C'est le mode de la demonstration commerciale : un cycle complet de
        180 jours devant un prospect, en une reunion."""
        t = _temps(mode=ModeCompression.ACCELERE, secondes_par_jour_accelere=10.0)
        assert t.duree_reelle.total_seconds() == pytest.approx(1800.0)

    def test_en_instantane_un_jour_de_simulation_est_un_jour_calendaire(self) -> None:
        """Mode retro-date : les horodatages restent etales sur 180 VRAIS jours.
        « Instantane » qualifie l'ECRITURE, jamais les dates."""
        t = _temps(mode=ModeCompression.INSTANTANE)
        assert t.secondes_par_jour == SECONDES_PAR_JOUR_CALENDAIRE
        assert t._wall_time_for_sim_day(0).date() == DEBUT
        assert t._wall_time_for_sim_day(FENETRE_JOURS).date() == FIN

    @pytest.mark.parametrize("hors_bornes", [0.0, 0.1, 60.1, 1000.0])
    def test_le_mode_accelere_refuse_ce_qui_sort_de_l_annexe_D3(
        self, hors_bornes: float
    ) -> None:
        """« entre 0,2 et 60 secondes » — les bornes sont dans le CDC, pas dans
        notre gout."""
        with pytest.raises(FenetreInvalide, match=r"Annexe D\.3"):
            _temps(mode=ModeCompression.ACCELERE, secondes_par_jour_accelere=hors_bornes)

    @pytest.mark.parametrize("valide", [ACCELERE_MIN, 1.0, 30.0, ACCELERE_MAX])
    def test_les_bornes_de_l_annexe_D3_sont_inclusives(self, valide: float) -> None:
        assert _temps(
            mode=ModeCompression.ACCELERE, secondes_par_jour_accelere=valide
        ).secondes_par_jour == valide


class TestLesQuatreFonctionsDeEF76:
    """`EF-76` **cite les noms**. Un renommage « plus propre » rendrait
    l'exigence invérifiable par simple lecture."""

    def test_les_quatre_noms_exacts_existent(self) -> None:
        t = _temps()
        for nom in (
            "_wall_from_sim_day",
            "_current_sim_day",
            "_wall_time_for_sim_day",
            "_scoring_date_to_sim_day",
        ):
            assert hasattr(t, nom), f"{nom} — nom cite par EF-76, il ne se renomme pas"

    def test_la_conversion_est_bijective(self) -> None:
        """Aller-retour : jour -> date -> jour. Sans ca, un evenement horodate ne
        pourrait pas etre replace dans la fenetre."""
        t = _temps()
        for jour in (0, 1, 45, 90, 179, FENETRE_JOURS):
            iso = t.date_du_jour(jour).isoformat()
            assert t._scoring_date_to_sim_day(iso) == float(jour)

    def test_wall_from_sim_day_propage_None_au_lieu_de_lever(self) -> None:
        """Duhamel rend `None` sur une entree absente. Un horodatage manquant ne
        doit pas interrompre une campagne de 2 000 clients."""
        assert _temps()._wall_from_sim_day(None) is None

    def test_une_date_de_scoring_illisible_rend_None(self) -> None:
        """`EF-32` : « gerer les cas d'absence par une entree neutre, **sans
        interrompre l'execution globale** »."""
        t = _temps()
        for illisible in ("pas-une-date", "", "2026-13-45", "N/A"):
            assert t._scoring_date_to_sim_day(illisible) is None

    def test_un_scoring_hors_fenetre_rend_une_valeur_signee_sans_troncature(self) -> None:
        """Le module ne tronque RIEN de lui-meme : l'appelant decide. Un scoring
        anterieur a la fenetre rend un jour negatif, et c'est une information."""
        t = _temps()
        assert t._scoring_date_to_sim_day("2026-01-01") == -42.0
        assert t._scoring_date_to_sim_day("2026-12-25") == 316.0

    def test_current_sim_day_est_injectable_donc_testable(self) -> None:
        """Sans injection, cette fonction serait intestable — et elle porte la
        progression d'une demonstration en direct."""
        t = _temps(mode=ModeCompression.REALISTE)
        instant = t.ancre.replace(microsecond=0)
        assert t._current_sim_day(instant) == 0.0
        plus_tard = t._wall_time_for_sim_day(7.0)
        assert t._current_sim_day(plus_tard) == pytest.approx(7.0)


class TestLeCycleDeCredit:
    """`UC-03` point 4 — « horodates retroactivement sur les 90 derniers jours »."""

    def test_le_credit_occupe_les_90_derniers_jours_de_la_fenetre(self) -> None:
        t = _temps()
        assert t.premier_jour_du_credit == FENETRE_JOURS - JOURS_CYCLE_CREDIT
        assert t.jours_du_credit()[0] == 90
        assert t.jours_du_credit()[-1] == FENETRE_JOURS

    def test_sur_une_fenetre_plus_courte_que_90_jours_le_credit_part_du_debut(self) -> None:
        """Pas d'index negatif, et pas de silence : le credit commence au jour 0
        et la fenetre est signalee non conforme."""
        t = _temps(fin=date(2026, 3, 14))  # 30 jours
        assert t.premier_jour_du_credit == 0
        assert not t.conforme_enf16

    def test_la_vie_commune_couvre_TOUTE_la_fenetre_pas_seulement_le_credit(self) -> None:
        """`EF-77` — la vie commune concerne 100 % des clients sur 180 jours. Le
        credit n'en occupe que la seconde moitie."""
        t = _temps()
        assert len(t.jours()) == FENETRE_JOURS + 1
        assert len(t.jours()) > len(t.jours_du_credit())


class TestLesGardeFous:
    def test_un_jour_hors_fenetre_est_refuse_bruyamment(self) -> None:
        """La doctrine : « rigide a l'execution, le Loader echoue bruyamment sur
        l'inconnu ». Un jour hors fenetre produirait une transaction datee hors
        de la periode annoncee."""
        t = _temps()
        for hors in (-1, FENETRE_JOURS + 1, 10_000):
            with pytest.raises(FenetreInvalide, match="hors de la fenetre"):
                t.date_du_jour(hors)

    def test_le_temps_est_immuable(self) -> None:
        """La fenetre est figee au lancement, comme la configuration (`D-10`). Un
        run qui deplacerait son ancre en cours d'execution produirait des
        evenements dont l'ordre ne voudrait plus rien dire."""
        t = _temps()
        with pytest.raises(AttributeError):
            t.debut = date(2020, 1, 1)  # type: ignore[misc]
