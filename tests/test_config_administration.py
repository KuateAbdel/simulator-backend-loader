"""Administration config-service — les actions du Super-Admin sur le partage.

Ces tests verifient les barrieres **hors reseau**. Le referentiel est partage
par toute l'equipe : une desactivation mal ciblee couterait une demi-journee a
quelqu'un d'autre.

Toutes les regles viennent de mesures du 09/08/2026.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.clients.config_service import AdministrationConfigService, ReferenceInverse, _identifiants


class TestAsymetrieEcritureLecture:
    """ANO-CFG-ASYM-08 — on ECRIT `currencies: ["uuid"]`, on LIT
    `currencies: [{objet complet}]`. Documente depuis juin."""

    def test_les_objets_lus_deviennent_des_uuid(self) -> None:
        lus = [
            {"_id": "aaa", "iso_name": "XAF", "name_fr": "Franc CFA (BEAC)"},
            {"_id": "bbb", "iso_name": "XOF"},
        ]
        assert _identifiants(lus) == ["aaa", "bbb"]

    def test_des_uuid_deja_plats_passent_inchanges(self) -> None:
        assert _identifiants(["aaa", "bbb"]) == ["aaa", "bbb"]

    def test_une_liste_vide_ou_absente_ne_casse_pas(self) -> None:
        assert _identifiants(None) == []
        assert _identifiants([]) == []


class TestMotifTelco:
    """RC-184 documente l'absence de `re.compile()` cote serveur. Nous ajoutons
    l'exigence d'ANCRAGE, que `6|333` ne respecte pas."""

    @pytest.fixture
    def admin(self) -> AdministrationConfigService:
        return AdministrationConfigService()

    async def test_le_motif_de_mtncongo1_est_refuse(self, admin: Any) -> None:
        """`6|333` est compilable — mais sans ancres, il accepte toute chaine
        contenant un 6. Une validation qui ne valide rien."""
        with pytest.raises(ValueError, match="non ancre"):
            await admin.creer_telco_si_absent("Test", "6|333")

    @pytest.mark.parametrize("motif", ["^237(67\\d{7})", "237(67\\d{7})$", "67\\d{7}"])
    async def test_un_motif_partiellement_ancre_est_refuse(self, admin: Any, motif: str) -> None:
        with pytest.raises(ValueError, match="non ancre"):
            await admin.creer_telco_si_absent("Test", motif)

    async def test_un_motif_non_compilable_est_refuse(self, admin: Any) -> None:
        with pytest.raises(ValueError, match="non compilable"):
            await admin.creer_telco_si_absent("Test", "^237(67\\d{7}$")

    async def test_le_message_cite_le_defaut_reel(self, admin: Any) -> None:
        with pytest.raises(ValueError) as erreur:
            await admin.creer_telco_si_absent("Test", "6|333")
        assert "MTNcongo1" in str(erreur.value)


class TestRefusDeDesactiverUneDevise:
    """100 % des devises sont partagees. XOF est referencee par SN, BF et CI ;
    XAF par CM. Aucun cas ne permet de retirer une devise sans casser une zone
    monetaire entiere."""

    async def test_la_desactivation_est_toujours_refusee(self, monkeypatch: Any) -> None:
        admin = AdministrationConfigService()

        async def inverses(_id: str, _famille: str) -> list[str]:
            return ["BF", "CI", "SN"]

        monkeypatch.setattr(admin, "references_inverses", inverses)
        with pytest.raises(ReferenceInverse, match="TOUJOURS refusee"):
            await admin.desactiver_devise("uuid-xof")

    async def test_le_message_nomme_les_pays_casses(self, monkeypatch: Any) -> None:
        admin = AdministrationConfigService()

        async def inverses(_id: str, _famille: str) -> list[str]:
            return ["BF", "CI", "SN"]

        monkeypatch.setattr(admin, "references_inverses", inverses)
        with pytest.raises(ReferenceInverse) as erreur:
            await admin.desactiver_devise("uuid-xof")
        assert "'SN'" in str(erreur.value) or "SN" in str(erreur.value)


class TestReferencesInversesSurTelco:
    """Le piege mesure le 09/08 : `Moov Africa CI` est reference par la Cote
    d'Ivoire ET par le pays parasite `ca`. Une cascade naive, ecrite de bonne
    foi pour nettoyer un dechet, aurait casse un pays reel."""

    async def test_un_operateur_partage_ne_peut_pas_etre_desactive(self, monkeypatch: Any) -> None:
        admin = AdministrationConfigService()

        async def inverses(_id: str, _famille: str) -> list[str]:
            return ["CI", "ca"]

        monkeypatch.setattr(admin, "references_inverses", inverses)
        with pytest.raises(ReferenceInverse, match="encore reference"):
            await admin.desactiver_telco("uuid-moov", pays_attendu="ca")

    async def test_le_message_nomme_le_pays_qui_serait_casse(self, monkeypatch: Any) -> None:
        admin = AdministrationConfigService()

        async def inverses(_id: str, _famille: str) -> list[str]:
            return ["CI", "ca"]

        monkeypatch.setattr(admin, "references_inverses", inverses)
        with pytest.raises(ReferenceInverse) as erreur:
            await admin.desactiver_telco("uuid-moov", pays_attendu="ca")
        assert "CI" in str(erreur.value)
        assert "unidirectionnelle" in str(erreur.value)


class TestImmuniteAuxParasites:
    """`D-CFG-1` / `D-CFG-2` — le Loader ne repare pas config-service.

    Il ne se laisse pas atteindre. Six entrees parasites sur 24 dans
    l'environnement TEST ; la plus dangereuse est `MTNcongo1` et son regex
    `6|333`, **sans ancres** : il valide tout numero contenant un `6`.
    """

    def test_un_regex_sans_ancres_est_inexploitable(self) -> None:
        """Le cas reel — `MTNcongo1`. Validation en apparence, aucune en fait."""
        from app.clients.config_service import regex_exploitable

        assert not regex_exploitable(r"6|333")

    def test_un_regex_ancre_des_deux_cotes_est_exploitable(self) -> None:
        from app.clients.config_service import regex_exploitable

        assert regex_exploitable(r"^237(67|68|65|69|62)\d{7}$")

    def test_une_ancre_seule_ne_suffit_pas(self) -> None:
        """`^6` accepte `612345678901234` : ancre a gauche, libre a droite."""
        from app.clients.config_service import regex_exploitable

        assert not regex_exploitable(r"^6")
        assert not regex_exploitable(r"6$")

    def test_un_regex_non_compilable_est_refuse(self) -> None:
        from app.clients.config_service import regex_exploitable

        assert not regex_exploitable(r"^[6-$")

    def test_un_motif_vide_est_refuse(self) -> None:
        from app.clients.config_service import regex_exploitable

        assert not regex_exploitable("")

    def test_EF_27_ne_consulte_JAMAIS_le_regex_serveur(self) -> None:
        """La decision qui protege : `valider_msisdn_operateur` s'appuie sur
        NOTRE referentiel, jamais sur config-service. Un developpeur qui
        « ameliorerait » le Loader en lisant le regex serveur reintroduirait
        `6|333` sans s'en apercevoir."""
        import inspect

        from app.core import invariants

        source = inspect.getsource(invariants.valider_msisdn_operateur)
        assert "referentiel" in source
        assert "config_service" not in source and "ConfigService" not in source
