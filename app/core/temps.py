"""
app/core/temps.py
=================
Le squelette temporel de TOUTE la simulation — `EF-76`, `ENF-16`, `EF-71`.

**Pas seulement du credit.** `EF-77` impose la vie commune a 100 % des 2 000
clients sur 180 jours : chaque mouvement d'epargne, chaque paiement marchand,
chaque operation P2P doit etre horodate. Sans ce module, aucun evenement des
Sprints 4 et 5 ne peut porter de date.

LE MALENTENDU QU'IL FAUT DISSIPER D'ABORD
-----------------------------------------
**Un jour de SIMULATION n'est pas un jour REEL.** C'est la formule de Duhamel,
reprise verbatim ci-dessous :

    horodatage_reel = ancre + (jour_de_simulation x SECONDES_PAR_JOUR)

Avec `SECONDES_PAR_JOUR = 226.49` — le repli du script Duhamel, et exactement le
mode « realiste » de l'Annexe D.3 — les 180 jours de la fenetre tiennent en
**11 h 19 de temps reel**. Les 90 jours du cycle d'un pret tiennent en 5 h 40.

C'est la raison d'etre de ce parametre, et elle est visuelle : **pour que les
graphiques ne soient pas plats.** Un peuplement qui horodate tout a la meme
seconde produit un tableau de bord ou toutes les courbes montent d'un trait puis
s'arretent. Un bailleur voit immediatement que rien n'a ete vecu.

180 OU 90 ? LES DEUX, ET CE NE SONT PAS LA MEME CHOSE
------------------------------------------------------
    `ENF-16`          la FENETRE historique  = 180 jours, parametrable par
                      `SIM_START_DATE` / `SIM_END_DATE`
    `UC-03` point 4   le CYCLE D'UN PRET est « horodate retroactivement sur les
                      **90 derniers jours** »
    Annexe D.1        les jalons DPD du defaut total tombent a 15, 30, 60 et 90 j

Un pret dure 15 a 30 jours (Annexe E) et ses jalons de retard vont jusqu'a 90.
Le cycle de credit occupe donc la **seconde moitie** de la fenetre ; la premiere
moitie porte la vie commune qui le precede. Confondre les deux ferait naitre des
prets avant que le client n'existe.

LES DEUX REGIMES, ET C'EST LA DECISION DE CONCEPTION
-----------------------------------------------------
Les memes quatre fonctions servent deux usages opposes, et seuls l'ancre et
`secondes_par_jour` changent :

  **RETRO-DATATION** (peuplement en masse, mode « instantane » de l'Annexe D.3)
  `secondes_par_jour = 86 400` — un jour de simulation EST un jour calendaire,
  mais dans le PASSE. L'ancre est `sim_start_date`. Les 2 000 clients et leurs
  180 jours d'activite sont ecrits d'un coup, avec des horodatages qui remontent
  jusqu'a six mois en arriere. C'est le mode du `OBJ-04` : moins de 30 minutes.

  **OBSERVATION EN DIRECT** (demonstration commerciale)
  `secondes_par_jour` vaut 0,2 a 60 (accelere) ou 226,49 (realiste). L'ancre est
  l'instant du lancement, et les evenements se produisent DEVANT le prospect.
  C'est le mode qui montre un cycle complet en une reunion.

**Le peuplement retro-date n'est pas moins « vivant » que l'observation :** ses
horodatages sont etales sur 180 vrais jours, donc les courbes ont un relief. Le
mode direct ajoute seulement le spectacle du temps qui passe.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne decide d'AUCUN evenement. Il convertit des jours en horodatages, rien de
plus. Ce que fait chaque profil jour apres jour reste l'arbitrage `A-07`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Final

from app.core.cdc import FENETRE_JOURS

#: Le repli du script Duhamel quand la calibration Kafka echoue — et exactement
#: le mode « realiste » de l'Annexe D.3 : « un jour metier est represente par
#: environ 226 secondes de temps reel ». La concordance n'est pas fortuite :
#: c'est la meme valeur, vue de deux documents.
SECONDES_PAR_JOUR_REALISTE: Final = 226.49

#: Un jour calendaire. C'est la valeur du mode retro-date : un jour de
#: simulation EST un jour reel, simplement situe dans le passe.
SECONDES_PAR_JOUR_CALENDAIRE: Final = 86_400.0

#: Annexe D.3, mode « accelere » : « un jour metier est represente par une duree
#: reelle comprise entre 0,2 et 60 secondes ».
ACCELERE_MIN: Final = 0.2
ACCELERE_MAX: Final = 60.0

#: `UC-03` point 4 — le cycle d'un pret est retro-date sur les 90 DERNIERS jours
#: de la fenetre, pas sur les 180. Les jalons DPD de l'Annexe D.1 vont jusqu'a
#: 90 jours : un pret ne dispose donc pas de plus que cela pour se derouler.
JOURS_CYCLE_CREDIT: Final = 90


class ModeCompression(StrEnum):
    """Les trois modes de l'Annexe D.3 — `EF-71`, priorite S."""

    #: « L'ensemble des evenements est materialise immediatement. Mode par
    #: defaut pour le peuplement en masse. » Les horodatages restent etales sur
    #: la fenetre reelle : instantane designe l'ECRITURE, pas les dates.
    INSTANTANE = "INSTANTANE"
    #: « Adapte a la demonstration commerciale d'un cycle complet. »
    ACCELERE = "ACCELERE"
    #: « Simulation lente pour observation en conditions proches du reel. »
    REALISTE = "REALISTE"


class FenetreInvalide(ValueError):
    """La fenetre de simulation ne permet aucune conversion coherente."""


@dataclass(frozen=True, slots=True)
class TempsSimulation:
    """Convertit les jours de simulation en horodatages, et l'inverse.

    Immuable : la fenetre est figee au lancement du run, comme la configuration
    (`D-10`). Un run qui deplacerait son ancre en cours d'execution produirait
    des evenements dont l'ordre ne voudrait plus rien dire.
    """

    debut: date
    fin: date
    mode: ModeCompression = ModeCompression.INSTANTANE
    #: Renseigne uniquement en mode `ACCELERE` — les deux autres modes ont une
    #: valeur imposee. Borne a l'intervalle de l'Annexe D.3.
    secondes_par_jour_accelere: float = 1.0

    def __post_init__(self) -> None:
        if self.fin < self.debut:
            raise FenetreInvalide(
                f"fenetre inversee : {self.debut.isoformat()} -> {self.fin.isoformat()}"
            )
        if self.mode is ModeCompression.ACCELERE and not (
            ACCELERE_MIN <= self.secondes_par_jour_accelere <= ACCELERE_MAX
        ):
            raise FenetreInvalide(
                f"mode ACCELERE : {self.secondes_par_jour_accelere} s/jour hors de "
                f"l'intervalle [{ACCELERE_MIN}, {ACCELERE_MAX}] de l'Annexe D.3"
            )

    # ------------------------------------------------------------------
    # La fenetre
    # ------------------------------------------------------------------

    @property
    def nb_jours(self) -> int:
        """Le nombre de jours de simulation. `ENF-16` en attend 180 par defaut."""
        return (self.fin - self.debut).days

    @property
    def conforme_enf16(self) -> bool:
        return self.nb_jours == FENETRE_JOURS

    @property
    def ancre(self) -> datetime:
        """L'origine des conversions : le premier instant du premier jour, UTC.

        Toujours UTC, jamais l'heure locale : les horodatages traversent quatre
        pays et deux fuseaux, et un evenement daté en heure locale serait
        incomparable a celui du pays voisin.
        """
        return datetime.combine(self.debut, datetime.min.time(), tzinfo=UTC)

    @property
    def secondes_par_jour(self) -> float:
        """Le facteur de compression effectif, selon le mode."""
        if self.mode is ModeCompression.REALISTE:
            return SECONDES_PAR_JOUR_REALISTE
        if self.mode is ModeCompression.ACCELERE:
            return self.secondes_par_jour_accelere
        return SECONDES_PAR_JOUR_CALENDAIRE

    @property
    def duree_reelle(self) -> timedelta:
        """Combien de temps REEL la fenetre occupe, dans ce mode.

        C'est le chiffre qui rend le malentendu visible : en mode realiste, 180
        jours de simulation tiennent en 11 h 19.
        """
        return timedelta(seconds=self.nb_jours * self.secondes_par_jour)

    @property
    def premier_jour_du_credit(self) -> int:
        """`UC-03` point 4 — le cycle de credit occupe les 90 DERNIERS jours.

        Un pret ne peut pas naitre avant, sinon ses jalons DPD depasseraient la
        fenetre. Sur une fenetre plus courte que 90 jours, le credit commence au
        premier jour et le rapport doit le signaler.
        """
        return max(0, self.nb_jours - JOURS_CYCLE_CREDIT)

    # ------------------------------------------------------------------
    # Les 4 fonctions de `EF-76`, sous leurs noms EXACTS
    #
    # « Le Loader DOIT reutiliser les fonctions de conversion des jours de
    #   simulation en horodatages reels issues du script du referent
    #   loan-simulation (fonctions _wall_from_sim_day, _current_sim_day,
    #   _wall_time_for_sim_day, _scoring_date_to_sim_day) »
    #
    # Les noms sont conserves a la lettre : l'exigence les CITE. Un renommage
    # « plus propre » rendrait `EF-76` invérifiable par simple lecture.
    # ------------------------------------------------------------------

    def _wall_time_for_sim_day(self, sim_day: float) -> datetime:
        """Jour de simulation -> horodatage reel. La conversion de base."""
        return self.ancre + timedelta(seconds=sim_day * self.secondes_par_jour)

    def _wall_from_sim_day(self, sim_day: float | None) -> str | None:
        """La meme conversion, en texte lisible. `None` propage `None`.

        Duhamel rend `None` sur une entree absente plutot que de lever : un
        horodatage manquant ne doit pas interrompre une campagne de 2 000
        clients. On conserve ce comportement.
        """
        if sim_day is None or self.secondes_par_jour <= 0:
            return None
        return self._wall_time_for_sim_day(sim_day).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")

    def _current_sim_day(self, maintenant: datetime | None = None) -> float:
        """Ou en est la simulation, MAINTENANT.

        N'a de sens qu'en **observation directe** : en retro-datation, « l'instant
        present » est apres la fin de la fenetre et cette valeur depasse
        `nb_jours`. C'est correct et cela veut dire « la fenetre est passee ».

        `maintenant` est injectable — sans quoi la fonction serait intestable.
        """
        if self.secondes_par_jour <= 0:
            return 0.0
        instant = maintenant or datetime.now(UTC)
        return (instant - self.ancre).total_seconds() / self.secondes_par_jour

    def _scoring_date_to_sim_day(self, scoring_date: str) -> float | None:
        """Une date de scoring Faker -> son jour de simulation.

        `EF-80` extrait les decisions des payloads Faker ; leurs dates doivent
        etre replacees dans notre fenetre. Une date illisible rend `None` —
        jamais une exception : `EF-32` impose de poursuivre sur une entree
        neutre.

        ⚠️ La valeur peut etre NEGATIVE (scoring anterieur a la fenetre) ou
        superieure a `nb_jours` (posterieur). L'appelant decide quoi en faire ;
        ce module ne tronque rien de lui-meme.
        """
        try:
            jour = date.fromisoformat(str(scoring_date)[:10])
        except ValueError:
            return None
        return float((jour - self.debut).days)

    # ------------------------------------------------------------------
    # Ce que la retro-datation exige, et que Duhamel n'avait pas a fournir
    # ------------------------------------------------------------------

    def date_du_jour(self, sim_day: int) -> date:
        """Le jour CALENDAIRE d'un jour de simulation.

        Duhamel travaille en temps compresse et n'a pas besoin de cette
        fonction. Nous si : `EF-77` demande une vie journaliere sur 180 jours,
        et une transaction porte une date, pas un instant compresse.

        Independante du mode : un jour de simulation correspond toujours a un
        jour calendaire de la fenetre. Seule l'HEURE depend de la compression.
        """
        if not 0 <= sim_day <= self.nb_jours:
            raise FenetreInvalide(
                f"jour {sim_day} hors de la fenetre [0, {self.nb_jours}] "
                f"({self.debut.isoformat()} -> {self.fin.isoformat()})"
            )
        return self.debut + timedelta(days=sim_day)

    def jours(self) -> range:
        """Les jours de simulation, du premier au dernier inclus.

        C'est la boucle de `UC-15` : « le Loader parcourt chaque client actif a
        chaque jour simule ».
        """
        return range(self.nb_jours + 1)

    def jours_du_credit(self) -> range:
        """Les jours ou un evenement de credit peut naitre — `UC-03` point 4."""
        return range(self.premier_jour_du_credit, self.nb_jours + 1)

    def resume(self) -> str:
        heures = self.duree_reelle.total_seconds() / 3600
        ecart = "" if self.conforme_enf16 else f" — ECART a ENF-16 : {FENETRE_JOURS} attendus"
        return (
            f"Fenetre : {self.debut.isoformat()} -> {self.fin.isoformat()} "
            f"({self.nb_jours} jours{ecart})\n"
            f"Mode    : {self.mode.value} — {self.secondes_par_jour:g} s par jour de simulation\n"
            f"Duree reelle equivalente : {heures:.2f} h\n"
            f"Cycle de credit : jours {self.premier_jour_du_credit} a {self.nb_jours} "
            f"(UC-03 pt 4 — les {JOURS_CYCLE_CREDIT} derniers)"
        )
