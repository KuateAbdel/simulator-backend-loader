"""Configuration d'execution — l'exigence de parametrage du boss.

Trois regles gouvernent ces tests :

  1. le parametrage touche les QUANTITES, jamais les INVARIANTS
  2. sans parametre, le CDC s'applique EXACTEMENT
  3. un ecart au CDC est autorise mais JAMAIS silencieux
"""

from __future__ import annotations

import pytest

from app.core.cdc import COMPANIES_PAR_PAYS, NB_CLIENTS, PAYS_CIBLES
from app.core.configuration import (
    PART_FEMMES_CDC,
    ConfigurationExecution,
    Surcharge,
)
from app.services.geographie import charger_referentiel


@pytest.fixture(scope="module")
def referentiel() -> object:
    from pathlib import Path

    return charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))


class TestDefautCdc:
    """Regle 2 — un lancement nu doit produire exactement le CDC."""

    def test_les_quatre_pays_sont_actifs(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        assert config.pays_actifs == sorted(PAYS_CIBLES)
        assert config.pays_inactifs == []

    def test_les_volumetries_sont_celles_du_cdc(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        assert config.resoudre("companies", "CM") == COMPANIES_PAR_PAYS
        assert config.nb_clients == NB_CLIENTS

    def test_le_ratio_ef22_vaut_deux_femmes_pour_un_homme(self) -> None:
        assert PART_FEMMES_CDC == pytest.approx(2 / 3)
        assert ConfigurationExecution.defaut_cdc().resoudre("part_femmes", "CM") == PART_FEMMES_CDC

    def test_une_configuration_nue_est_conforme(self) -> None:
        assert ConfigurationExecution.defaut_cdc().conforme_au_cdc


class TestResolutionEnCascade:
    """Le niveau le plus fin gagne ; aucun territoire sans regle."""

    def test_le_defaut_cdc_s_applique_sans_surcharge(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        assert config.resoudre("kiosques", "SN", "Dakar", "Pikine") == (10, 20)

    def test_la_surcharge_pays_l_emporte_sur_le_cdc(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].surcharge = Surcharge(companies=(8, 8))
        assert config.resoudre("companies", "CM") == (8, 8)
        assert config.resoudre("companies", "CI") == COMPANIES_PAR_PAYS

    def test_la_ville_l_emporte_sur_la_region_qui_l_emporte_sur_le_pays(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].surcharge = Surcharge(staff=(15, 15))
        config.pays["CM"].regions["Littoral"] = Surcharge(staff=(20, 20))
        config.pays["CM"].villes["Douala"] = Surcharge(staff=(30, 30))

        assert config.resoudre("staff", "CM") == (15, 15)
        assert config.resoudre("staff", "CM", "Littoral") == (20, 20)
        assert config.resoudre("staff", "CM", "Littoral", "Douala") == (30, 30)

    def test_une_surcharge_partielle_ne_masque_pas_le_reste(self) -> None:
        """Une region qui ne fixe que le staff laisse les companies remonter."""
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CI"].surcharge = Surcharge(companies=(4, 4))
        config.pays["CI"].regions["Abidjan"] = Surcharge(staff=(25, 25))
        assert config.resoudre("staff", "CI", "Abidjan") == (25, 25)
        assert config.resoudre("companies", "CI", "Abidjan") == (4, 4)

    def test_un_pays_inconnu_retombe_sur_le_cdc(self) -> None:
        """Aucun territoire ne peut se retrouver sans regle."""
        assert ConfigurationExecution.defaut_cdc().resoudre("companies", "ZZ") == COMPANIES_PAR_PAYS


class TestSoftDelete:
    """Un pays retire est marque INACTIF, jamais efface. On garde la trace.

    Idee reprise telle quelle de config-service : `activate`/`deactivate`
    plutot que `DELETE` est le bon choix pour un referentiel.
    """

    def test_desactiver_conserve_le_pays_et_son_motif(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "Faker ne sert pas le Senegal (A-01)")

        assert "SN" in config.pays, "le pays doit rester dans la configuration"
        assert config.pays_actifs == ["BF", "CI", "CM"]
        assert config.pays_inactifs == ["SN"]
        assert "A-01" in config.pays["SN"].motif_inactivite

    def test_la_reactivation_est_immediate(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("BF", "test")
        config.pays["BF"].reactiver()
        assert config.pays_actifs == sorted(PAYS_CIBLES)
        assert config.pays["BF"].motif_inactivite == ""

    def test_un_motif_vide_est_remplace_pas_accepte(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("CM", "   ")
        assert config.pays["CM"].motif_inactivite == "non precise"

    def test_desactiver_un_pays_inconnu_leve(self) -> None:
        with pytest.raises(ValueError, match="absent"):
            ConfigurationExecution.defaut_cdc().desactiver_pays("ZZ", "x")


class TestEcartsAuCdc:
    """Regle 3 — un ecart est AUTORISE mais jamais SILENCIEUX.

    Sans cette liste, CR-09 declarerait conforme un run qui ne l'est pas.
    """

    def test_un_pays_desactive_est_signale(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "A-01")
        ecarts = config.ecarts_au_cdc()
        assert any("SN" in e and "OBJ-01" in e for e in ecarts)
        assert not config.conforme_au_cdc

    def test_un_ratio_femmes_hors_ef22_est_signale(self) -> None:
        """Le Super-Admin peut demander 50/50. On l'accepte, on le dit."""
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].surcharge = Surcharge(part_femmes=0.5)
        ecarts = config.ecarts_au_cdc()
        assert any("EF-22" in e and "50%" in e for e in ecarts)

    def test_un_ratio_conforme_n_est_pas_signale(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].surcharge = Surcharge(part_femmes=PART_FEMMES_CDC)
        assert config.conforme_au_cdc

    def test_une_part_corporate_hors_ef23_est_signalee(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CI"].regions["Abidjan"] = Surcharge(part_corporate=0.5)
        assert any("EF-23" in e for e in config.ecarts_au_cdc())

    def test_un_volume_client_different_est_signale(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.nb_clients = 500
        assert any("OBJ-02" in e for e in config.ecarts_au_cdc())

    def test_l_ecart_nomme_la_portee_exacte(self) -> None:
        """« CM/Douala » et non « quelque part »."""
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].villes["Douala"] = Surcharge(part_femmes=0.1)
        assert any("CM/Douala" in e for e in config.ecarts_au_cdc())


class TestEmpreinte:
    """ENF-15 — des que la volumetrie est parametrable, le run_id ne suffit
    plus. La configuration doit etre persistee avec le run."""

    def test_l_empreinte_porte_l_etat_et_les_ecarts(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "A-01")
        config.pays["CM"].surcharge = Surcharge(companies=(8, 8))

        empreinte = config.empreinte()
        assert empreinte["pays"]["SN"]["actif"] is False
        assert empreinte["pays"]["CM"]["surcharge"] == {"companies": (8, 8)}
        assert empreinte["ecarts_au_cdc"], "les ecarts font partie de l'empreinte"

    def test_les_surcharges_vides_ne_polluent_pas_l_empreinte(self) -> None:
        empreinte = ConfigurationExecution.defaut_cdc().empreinte()
        assert empreinte["pays"]["CM"]["surcharge"] == {}
        assert empreinte["ecarts_au_cdc"] == []

    def test_le_resume_est_lisible_par_un_non_technicien(self) -> None:
        """OBJ-06 : l'outil doit etre utilisable par un non-technicien."""
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "Faker ne sert pas le Senegal")
        resume = config.resume()
        assert "Pays actifs" in resume
        assert "Faker ne sert pas le Senegal" in resume
        assert "ECARTS AU CDC" in resume


class TestRepartitionClients:
    """`resoudre()` repond « quelle regle s'applique ici ». C'est insuffisant
    pour une quantite GLOBALE : demander la part du Cameroun ne peut pas rendre
    2000, sinon quatre pays feraient 8000 clients.
    """

    def test_repartition_egale_sur_les_quatre_pays(self) -> None:
        parts = ConfigurationExecution.defaut_cdc().repartir_clients()
        assert sum(parts.values()) == NB_CLIENTS
        assert set(parts.values()) == {NB_CLIENTS // 4}

    def test_un_pays_desactive_recoit_zero_sans_disparaitre(self) -> None:
        """Il reste dans le resultat pour que le tableau de bord montre qu'il a
        ete exclu."""
        config = ConfigurationExecution.defaut_cdc()
        config.desactiver_pays("SN", "A-01")
        parts = config.repartir_clients()
        assert parts["SN"] == 0
        assert "SN" in parts
        assert sum(parts.values()) == NB_CLIENTS

    def test_le_reste_se_partage_entre_les_pays_libres(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].surcharge = Surcharge(clients=800)
        parts = config.repartir_clients()
        assert parts["CM"] == 800
        assert sum(parts.values()) == NB_CLIENTS
        assert parts["CI"] == parts["BF"] == parts["SN"] == 400

    def test_l_arrondi_est_absorbe_la_somme_tombe_juste(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.nb_clients = 2001
        parts = config.repartir_clients()
        assert sum(parts.values()) == 2001

    def test_une_surcharge_depassant_le_total_ne_corrige_pas_en_silence(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].surcharge = Surcharge(clients=3000)
        parts = config.repartir_clients()
        assert parts["CM"] == 3000
        assert parts["CI"] == 0, "on ne complete pas — l'ecart est signale"
        assert any("repartition impossible" in e for e in config.ecarts_au_cdc())

    def test_aucun_pays_actif_rend_zero_partout(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        for code in list(config.pays):
            config.desactiver_pays(code, "test")
        assert set(config.repartir_clients().values()) == {0}


class TestValidationContreLeReferentiel:
    """Nous reprochons a account-service d'accepter un `owner_id` qui ne resout
    nulle part (FRA-224). Une configuration acceptant `regions["Atlantide"]`
    commettrait exactement la meme faute — sur nos propres donnees.
    """

    def test_une_configuration_nue_est_saine(self, referentiel: object) -> None:
        assert ConfigurationExecution.defaut_cdc().valider_contre_referentiel(referentiel) == []

    def test_une_region_inexistante_est_detectee(self, referentiel: object) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["CM"].regions["Atlantide"] = Surcharge(staff=(5, 5))
        problemes = config.valider_contre_referentiel(referentiel)
        assert any("Atlantide" in p and "inexistante" in p for p in problemes)

    def test_une_ville_inexistante_est_detectee(self, referentiel: object) -> None:
        config = ConfigurationExecution.defaut_cdc()
        config.pays["SN"].villes["Gotham"] = Surcharge(clients=10)
        assert any("Gotham" in p for p in config.valider_contre_referentiel(referentiel))

    def test_une_region_reelle_passe(self, referentiel: object) -> None:
        config = ConfigurationExecution.defaut_cdc()
        region = referentiel.regions_du_pays("CM")[0].name  # type: ignore[attr-defined]
        config.pays["CM"].regions[region] = Surcharge(staff=(5, 5))
        assert config.valider_contre_referentiel(referentiel) == []

    def test_un_pays_hors_referentiel_est_detecte(self, referentiel: object) -> None:
        from app.core.configuration import ConfigurationPays

        config = ConfigurationExecution.defaut_cdc()
        config.pays["ZZ"] = ConfigurationPays(code="ZZ")
        assert any("ZZ" in p for p in config.valider_contre_referentiel(referentiel))


class TestSurchargeSurPaysDesactive:
    def test_une_surcharge_sans_effet_est_signalee(self) -> None:
        """Ce n'est pas une faute, c'est un oubli probable."""
        config = ConfigurationExecution.defaut_cdc()
        config.pays["SN"].surcharge = Surcharge(staff=(30, 30))
        config.desactiver_pays("SN", "A-01")
        assert any("sans effet" in e for e in config.ecarts_au_cdc())


class TestGardeFouQuantiteGlobale:
    """L'erreur que j'ai commise en ecrivant ce module, rendue impossible.

    `resoudre("clients", "CM")` rendait 2000 — le TOTAL, pas la part du
    Cameroun. Quatre pays auraient fait 8000 clients. Plutot que de le
    documenter, on l'interdit.
    """

    def test_resoudre_refuse_une_quantite_globale(self) -> None:
        with pytest.raises(ValueError, match="repartir_clients"):
            ConfigurationExecution.defaut_cdc().resoudre("clients", "CM")

    def test_le_message_explique_la_consequence(self) -> None:
        with pytest.raises(ValueError) as erreur:
            ConfigurationExecution.defaut_cdc().resoudre("clients", "CM")
        assert "quatre fois le volume" in str(erreur.value)

    def test_les_quantites_par_territoire_restent_resolubles(self) -> None:
        config = ConfigurationExecution.defaut_cdc()
        for quantite in ("companies", "kiosques", "staff", "part_femmes", "part_corporate"):
            assert config.resoudre(quantite, "CM") is not None
