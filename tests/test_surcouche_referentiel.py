"""Surcouche referentielle — CFG-03.

« Ajout region/ville » — Direction Technique, 9 aout 2026.

Le classeur reste la source de reference et n'est JAMAIS modifie. Les ajouts
vivent dans une couche distincte, tracee et reversible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.surcouche_referentiel import (
    PREFIXE_SURCOUCHE,
    AjoutRefuse,
    SurcoucheReferentiel,
)


@pytest.fixture(scope="module")
def base() -> ReferentielGeo:
    return charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))


class TestInvariantsEf02:
    """« Chaque Region a un Country parent, chaque City une Region, chaque
    District une City. » Applique aux ajouts, exactement comme au chargement.

    La difference : au chargement, une ligne orpheline est journalisee puis
    exclue (UC-05). Ici l'ajout est un ACTE DELIBERE — on le refuse sur-le-champ
    pour dire au Super-Admin ou est son erreur.
    """

    def test_une_region_sans_pays_valide_est_refusee(self, base: ReferentielGeo) -> None:
        with pytest.raises(AjoutRefuse, match="EF-02"):
            SurcoucheReferentiel().ajouter_region(base, pays="ZZ", nom="Atlantide")

    def test_une_ville_sans_region_valide_est_refusee(self, base: ReferentielGeo) -> None:
        with pytest.raises(AjoutRefuse, match="EF-02"):
            SurcoucheReferentiel().ajouter_ville(base, region_id="INEXISTANTE", nom="Gotham")

    def test_un_quartier_sans_ville_valide_est_refuse(self, base: ReferentielGeo) -> None:
        with pytest.raises(AjoutRefuse, match="EF-02"):
            SurcoucheReferentiel().ajouter_quartier(base, city_id="INEXISTANTE", nom="Zone 1")

    def test_un_nom_vide_est_refuse(self, base: ReferentielGeo) -> None:
        with pytest.raises(AjoutRefuse, match="sans nom"):
            SurcoucheReferentiel().ajouter_region(base, pays="CM", nom="   ")

    def test_un_doublon_est_refuse(self, base: ReferentielGeo) -> None:
        existante = base.regions_du_pays("CM")[0].name
        with pytest.raises(AjoutRefuse, match="existe deja"):
            SurcoucheReferentiel().ajouter_region(base, pays="CM", nom=existante)


class TestChaineComplete:
    """Region -> Ville -> Quartier, entierement dans la surcouche."""

    def test_la_chaine_s_enchaine(self, base: ReferentielGeo) -> None:
        sur = SurcoucheReferentiel()
        region = sur.ajouter_region(base, pays="CM", nom="Nouvelle Region", capitale="Kribi")
        ville = sur.ajouter_ville(base, region_id=region.region_id, nom="Ville Neuve")
        quartier = sur.ajouter_quartier(
            base, city_id=ville.city_id, nom="Zone Neuve", zone_type="commercial"
        )

        assert ville.country_iso2 == "CM", "le pays est herite de la region parente"
        assert quartier.zone_type == "commercial"
        assert len(sur.journal) == 3

    def test_une_ville_peut_pendre_a_une_region_du_classeur(self, base: ReferentielGeo) -> None:
        sur = SurcoucheReferentiel()
        region_existante = base.regions_du_pays("SN")[0]
        ville = sur.ajouter_ville(base, region_id=region_existante.region_id, nom="Ville Test SN")
        assert ville.country_iso2 == "SN"


class TestIdentifiants:
    def test_un_ajout_est_reconnaissable_a_l_oeil(self, base: ReferentielGeo) -> None:
        """`SC-CM-REG-...` ne peut pas etre confondu avec `CM-01` du classeur."""
        sur = SurcoucheReferentiel()
        region = sur.ajouter_region(base, pays="CM", nom="Test Region")
        assert region.region_id.startswith(f"{PREFIXE_SURCOUCHE}-CM-REG-")

    def test_l_identifiant_est_stable(self, base: ReferentielGeo) -> None:
        """ENF-15 : rejouer le meme ajout produit le meme identifiant."""
        premier = SurcoucheReferentiel().ajouter_region(base, pays="CI", nom="Region X")
        second = SurcoucheReferentiel().ajouter_region(base, pays="CI", nom="Region X")
        assert premier.region_id == second.region_id


class TestApplication:
    """`appliquer()` rend un NOUVEAU referentiel — l'original reste intact."""

    def test_le_classeur_n_est_jamais_mute(self, base: ReferentielGeo) -> None:
        avant_regions = len(base.regions)
        avant_quartiers = len(base.quartiers)

        sur = SurcoucheReferentiel()
        region = sur.ajouter_region(base, pays="BF", nom="Region Ajoutee")
        ville = sur.ajouter_ville(base, region_id=region.region_id, nom="Ville Ajoutee")
        sur.ajouter_quartier(base, city_id=ville.city_id, nom="Quartier Ajoute")

        assert len(base.regions) == avant_regions, "l'original ne doit pas bouger"
        assert len(base.quartiers) == avant_quartiers

        enrichi = sur.appliquer(base)
        assert len(enrichi.regions) == avant_regions + 1
        assert len(enrichi.quartiers) == avant_quartiers + 1

    def test_le_referentiel_enrichi_repond_aux_memes_questions(self, base: ReferentielGeo) -> None:
        sur = SurcoucheReferentiel()
        region = sur.ajouter_region(base, pays="BF", nom="Region Interrogeable")
        ville = sur.ajouter_ville(base, region_id=region.region_id, nom="Ville Interrogeable")
        sur.ajouter_quartier(base, city_id=ville.city_id, nom="Quartier Interrogeable")
        enrichi = sur.appliquer(base)

        assert any(r.name == "Region Interrogeable" for r in enrichi.regions_du_pays("BF"))
        assert enrichi.quartiers_de_ville(ville.city_id)
        assert ville.city_id in {v.city_id for v in enrichi.villes_porteuses_de_quartiers("BF")}

    def test_telcos_et_devises_survivent_a_l_application(self, base: ReferentielGeo) -> None:
        enrichi = SurcoucheReferentiel().appliquer(base)
        assert len(enrichi.telcos) == 12
        assert enrichi.devise_du_pays("CM").code == "XAF"
        assert enrichi.indicatif("CM") == "237"

    def test_une_surcouche_vide_ne_change_rien(self, base: ReferentielGeo) -> None:
        enrichi = SurcoucheReferentiel().appliquer(base)
        assert len(enrichi.regions) == len(base.regions)
        assert enrichi.rapport.nb_quartiers == base.rapport.nb_quartiers

    def test_le_rapport_ef06_dit_la_verite(self, base: ReferentielGeo) -> None:
        """Le decompte affiche en debut d'execution doit inclure les ajouts."""
        sur = SurcoucheReferentiel()
        sur.ajouter_region(base, pays="CI", nom="Region Comptee")
        enrichi = sur.appliquer(base)
        assert enrichi.rapport.nb_regions == base.rapport.nb_regions + 1


class TestReversibilite:
    def test_un_ajout_se_retire(self, base: ReferentielGeo) -> None:
        sur = SurcoucheReferentiel()
        region = sur.ajouter_region(base, pays="CM", nom="Ephemere")
        assert sur.retirer(region.region_id) is True
        assert sur.vide

    def test_retirer_un_inconnu_rend_faux_sans_lever(self, base: ReferentielGeo) -> None:
        assert SurcoucheReferentiel().retirer("INEXISTANT") is False

    def test_une_region_portant_des_enfants_ne_se_retire_pas(self, base: ReferentielGeo) -> None:
        """Meme discipline que les references inverses cote config-service."""
        sur = SurcoucheReferentiel()
        region = sur.ajouter_region(base, pays="CM", nom="Avec Enfants")
        sur.ajouter_ville(base, region_id=region.region_id, nom="Enfant")
        with pytest.raises(AjoutRefuse, match="porte encore"):
            sur.retirer(region.region_id)


class TestTracabilite:
    def test_les_ajouts_sont_serialisables_pour_l_empreinte(self, base: ReferentielGeo) -> None:
        """ENF-15 : sans la surcouche, rejouer un run_id donnerait un autre
        resultat. Elle fait partie de la configuration."""
        sur = SurcoucheReferentiel()
        region = sur.ajouter_region(base, pays="SN", nom="Region Tracee")
        sur.ajouter_ville(base, region_id=region.region_id, nom="Ville Tracee")

        ajouts = sur.ajouts()
        assert "Region Tracee" in ajouts["regions"].values()
        assert "Ville Tracee" in ajouts["villes"].values()
        assert len(ajouts["journal"]) == 2

    def test_le_resume_dit_que_le_classeur_est_intact(self, base: ReferentielGeo) -> None:
        sur = SurcoucheReferentiel()
        sur.ajouter_region(base, pays="CM", nom="Region Resumee")
        assert "n'a pas ete modifie" in sur.resume()

    def test_une_surcouche_vide_le_dit(self) -> None:
        assert "aucun ajout" in SurcoucheReferentiel().resume()
