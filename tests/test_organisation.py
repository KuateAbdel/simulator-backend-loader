"""Tests du module Organisation sur le referentiel reel Loader_Base.

Aucun appel reseau : la planification est entierement hors ligne, c'est tout
son interet — elle doit prouver la faisabilite AVANT la premiere ecriture.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from app.core.cdc import KIOSQUES_PAR_PAYS, PAYS_CIBLES
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.organisation import planifier

REFERENTIEL = Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
RUN_ID = UUID("11111111-2222-3333-4444-555555555555")


@pytest.fixture(scope="module")
def referentiel() -> ReferentielGeo:
    return charger_referentiel(REFERENTIEL)


def test_referentiel_conforme_a_obj_01(referentiel: ReferentielGeo) -> None:
    """OBJ-01 : 51 regions, 50 villes, 82 quartiers sur 4 pays."""
    assert referentiel.rapport.nb_regions == 51
    assert referentiel.rapport.nb_villes == 50
    assert referentiel.rapport.nb_quartiers == 82
    assert sorted(referentiel.rapport.pays) == sorted(PAYS_CIBLES)


def test_aucun_orphelin_dans_le_referentiel(referentiel: ReferentielGeo) -> None:
    """EF-02 : integrite referentielle complete, aucune entite exclue."""
    assert referentiel.rapport.orphelins == []


def test_villes_sans_quartier_sont_exclues(referentiel: ReferentielGeo) -> None:
    """UC-09, exception : un Kiosque exige un quartier.

    38 villes sur 50 n'en ont aucun — elles ne peuvent donc pas heberger
    d'Agence utile.
    """
    porteuses = sum(len(referentiel.villes_porteuses_de_quartiers(p)) for p in PAYS_CIBLES)
    assert porteuses == 12
    assert referentiel.rapport.nb_villes - porteuses == 38


def test_plan_respecte_la_volumetrie_cdc(referentiel: ReferentielGeo) -> None:
    """UC-07 (3-5 Companies/pays) et UC-09 (10-20 Kiosques/pays)."""
    plan = planifier(referentiel, RUN_ID)
    assert plan.realisable, plan.resume()
    assert len(plan.pays) == len(PAYS_CIBLES)

    kiosques_min, kiosques_max = KIOSQUES_PAR_PAYS
    for pays in plan.pays:
        assert 3 <= pays.nb_companies <= 5
        assert kiosques_min <= pays.nb_kiosques <= kiosques_max
        assert pays.nb_imf >= 1


def test_un_quartier_n_heberge_qu_un_kiosque(referentiel: ReferentielGeo) -> None:
    """Sans cette garantie, plusieurs guichets se superposeraient au meme endroit."""
    plan = planifier(referentiel, RUN_ID)
    quartiers = [
        kiosque.district_id
        for pays in plan.pays
        for branche in pays.branches
        for agence in branche.agences
        for kiosque in agence.kiosques
    ]
    assert len(quartiers) == len(set(quartiers))


def test_emboitement_strict_du_plan(referentiel: ReferentielGeo) -> None:
    """EF-18 : Branche->Region, Agence->Ville de cette Region, Kiosque->Quartier
    de cette Ville. Aucun niveau ne peut exister hors de son superieur."""
    plan = planifier(referentiel, RUN_ID)
    for pays in plan.pays:
        for branche in pays.branches:
            region = referentiel.regions[branche.region_id]
            assert region.country_iso2 == pays.country_code
            for agence in branche.agences:
                ville = referentiel.villes[agence.city_id]
                assert ville.region_id == branche.region_id
                for kiosque in agence.kiosques:
                    quartier = referentiel.quartiers[kiosque.district_id]
                    assert quartier.city_id == agence.city_id


def test_reproductibilite_stricte(referentiel: ReferentielGeo) -> None:
    """ENF-15 : meme run_id, meme ecosysteme, strictement."""
    premier = planifier(referentiel, RUN_ID)
    second = planifier(referentiel, RUN_ID)
    assert premier.pays == second.pays

    autre = planifier(referentiel, UUID("99999999-8888-7777-6666-555555555555"))
    assert autre.realisable


def test_referentiel_absent_echoue_avec_le_chemin(tmp_path: Path) -> None:
    """EF-01, exception : arret explicite avec le chemin attendu, jamais un
    echec silencieux."""
    with pytest.raises(FileNotFoundError, match="Chemin attendu"):
        charger_referentiel(tmp_path / "absent.xlsx")


def test_ef03_coordonnees_gps_associees(referentiel: ReferentielGeo) -> None:
    """EF-03 : « associer a chaque niveau geographique ses coordonnees GPS
    lorsqu'elles sont disponibles dans le referentiel »."""
    avec_gps = [v for v in referentiel.villes.values() if v.latitude and v.longitude]
    assert len(avec_gps) == referentiel.rapport.nb_villes, "toutes les villes portent un GPS"

    for ville in avec_gps:
        assert ville.latitude is not None and ville.longitude is not None
        # Afrique de l'Ouest et centrale : latitudes positives, longitudes
        # de part et d'autre du meridien de Greenwich.
        assert 0 < ville.latitude < 30, f"{ville.name} hors zone : {ville.latitude}"
        assert -20 < ville.longitude < 20, f"{ville.name} hors zone : {ville.longitude}"


def test_une_coordonnee_absente_reste_none(referentiel: ReferentielGeo) -> None:
    """Jamais 0.0 par defaut : ce point designerait le golfe de Guinee."""
    assert all(v.latitude != 0.0 for v in referentiel.villes.values())
