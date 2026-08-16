"""Invariants collect-service et depositary-service, portes cote Loader.

Ces tests ne verifient pas le serveur — ils verifient que **le Loader refuse
d'envoyer ce qui corromprait la base**. C'est toute la difference entre subir
une anomalie et l'anticiper.
"""

from __future__ import annotations

import pytest

from app.clients.collect_service import (
    CollecteNonSimulable,
    MontantInvalide,
    valider_collecte,
    valider_montant,
)
from app.clients.contracts import PolicyType
from app.clients.depositary_service import COMPTES_DEPOSITAIRE


class TestEcritureFantome:
    """FRA-195 / D-COL-9 — l'anomalie la plus dangereuse de l'ecosysteme.

    Un montant negatif ou nul produit un rejet HTTP APPARENT mais une mutation
    REELLE en base. Aucune verification post-appel ne peut la rattraper : la
    barriere doit etre AVANT le reseau.
    """

    @pytest.mark.parametrize("montant", [0, -1, -0.01, -100000])
    def test_montant_nul_ou_negatif_refuse_avant_envoi(self, montant: float) -> None:
        with pytest.raises(MontantInvalide, match="FRA-195"):
            valider_montant(montant)

    def test_le_message_explique_pourquoi_c_est_irrattrapable(self) -> None:
        """Un futur mainteneur doit comprendre qu'il ne s'agit pas de zele."""
        with pytest.raises(MontantInvalide) as erreur:
            valider_montant(0)
        message = str(erreur.value)
        assert "mute la base silencieusement" in message
        assert "apres coup" in message

    def test_montant_positif_accepte(self) -> None:
        valider_montant(1000.0)

    def test_amount_min_de_la_policy_respecte(self) -> None:
        """D-COL-10 — on se fie a la Policy, jamais au message serveur, qui
        annonce un plafond faux (FRA-198)."""
        valider_montant(1000.0, amount_min=1000.0)
        with pytest.raises(MontantInvalide, match="D-COL-10"):
            valider_montant(999.0, amount_min=1000.0)


class TestCollectesBloquees:
    """D-COL-13 / FRA-197 — souscrire n'est pas collecter."""

    def test_collecte_product_refusee(self) -> None:
        with pytest.raises(CollecteNonSimulable, match="FRA-197"):
            valider_collecte(PolicyType.PRODUCT, collect_quantity=5.0)

    def test_collect_quantity_est_verifie_avant_le_blocage(self) -> None:
        """D-COL-12 est une regle de CONTRAT, durable ; D-COL-13 une limitation
        TEMPORAIRE. La regle durable est verifiee en premier, pour rester vivante
        apres correction de FRA-197."""
        with pytest.raises(MontantInvalide, match="D-COL-12"):
            valider_collecte(PolicyType.PRODUCT, collect_quantity=None)

    def test_le_message_rappelle_que_la_souscription_reste_possible(self) -> None:
        """Le catalogue doit rester complet (D-PRD-9) meme si la collecte est
        bloquee — les deux ne sont pas liees."""
        with pytest.raises(CollecteNonSimulable) as erreur:
            valider_collecte(PolicyType.PRODUCT, collect_quantity=5.0)
        assert "souscription reste possible" in str(erreur.value)

    @pytest.mark.parametrize("type_policy", [PolicyType.CASH, PolicyType.CASH_DAT])
    def test_cash_et_cash_dat_sont_simulables(self, type_policy: PolicyType) -> None:
        valider_collecte(type_policy, None)


class TestDepositaire:
    def test_les_6_comptes_de_la_souscription(self) -> None:
        """D-DEP-2 — crees UNE FOIS, par Depositaire et non par produit."""
        assert set(COMPTES_DEPOSITAIRE) == {
            "CAPITAL",
            "INTEREST",
            "PENALTY",
            "TAXE",
            "CLASSIC",
            "TERM_DEPOSIT",
        }
        assert len(COMPTES_DEPOSITAIRE) == 6

    def test_aucune_methode_de_FERMETURE_mensongere_n_est_exposee(self) -> None:
        """D-DEP-8 / FRA-203 : desactiver un Depositaire n'arrete NI les
        collectes NI les retraits. Exposer une « fermeture » qui ne ferme rien
        inviterait a construire une logique fausse.

        REVISION 16/08 (decision Yaniv — visibilite et action completes) :
        `changer_statut` est desormais EXPOSE, parce que la route qui
        l'appelle PORTE la verite D-DEP-8 dans sa reponse (l'etat est
        administratif, jamais une fermeture). Les noms MENSONGERS restent
        interdits : fermer/cloturer promettraient un arret qui n'existe pas.
        """
        from app.clients import depositary_service

        interdits = {"fermer_depositaire", "cloturer", "cloturer_depositaire"}
        exposees = set(dir(depositary_service.DepositaryServiceClient))
        assert not (interdits & exposees)
        assert "changer_statut" in exposees, (
            "le geste d'etat est expose (16/08) — avec sa verite, cote route"
        )

    def test_aucune_methode_de_cloture_de_collecte(self) -> None:
        """D-COL-11 / FRA-196 — la cloture est bloquee cote serveur.

        `fermer()` est volontairement exclu de la liste : c'est le cycle de vie
        du client HTTP, commun aux 8 clients, sans rapport avec la cloture d'une
        epargne. On cible les noms METIER.
        """
        from app.clients import collect_service

        interdits = {"cloturer", "cloturer_epargne", "cloturer_collecte", "fermer_collecte"}
        exposees = set(dir(collect_service.CollectServiceClient))
        assert not (interdits & exposees)
        assert "fermer" in exposees, "le cycle de vie du client reste expose"
