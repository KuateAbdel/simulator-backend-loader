"""
tests/test_referentiel_statique.py
==================================
Le catalogue de JJB — `1_Static_Data.zip`, transmis le 12/08/2026.

**Ce que ces tests protegent** : que le Loader n'envoie jamais au serveur un
libelle qui n'existe dans aucune source. `industries`, `sectors` et `occupation`
sont des CHAINES LIBRES cote serveur — aucun des neuf services ne les valide.
La seule barriere est ici.

Et une seconde chose, aussi importante : que le referentiel ne change pas sous nos
pieds. Si JJB livre une version 2, le chargement doit ECHOUER bruyamment plutot
que de faire partir 20 Companies et 2000 clients avec des valeurs disparues, sur
des services sans `DELETE`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.referentiel_statique import (
    COMPTES_ATTENDUS,
    FICHIER_OCCUPATIONS,
    FICHIER_SECTEURS,
    PAYS_CIBLES_LIBELLES,
    ReferentielIncoherent,
    ReferentielStatique,
    charger_statique,
)

DOSSIER = Path("docs/reference/static_data")


@pytest.fixture(scope="module")
def referentiel() -> ReferentielStatique:
    return charger_statique(DOSSIER)


class TestLesComptes:
    """Les comptes mesures le 12/08. Un fichier tronque se detecte ICI."""

    def test_les_huit_comptes_sont_ceux_mesures(
        self, referentiel: ReferentielStatique
    ) -> None:
        reels = {
            "industries": len(referentiel.industries),
            "secteurs": len(referentiel.secteurs),
            "formes_juridiques": len(referentiel.formes_juridiques),
            "groupes": len(referentiel.groupes),
            "professions": len(referentiel.professions),
            "profils_revenu": len(referentiel.profils_revenu),
            "pays": len(referentiel.pays),
            "fonctions_dirigeant": len(referentiel.fonctions_dirigeant),
        }
        assert reels == COMPTES_ATTENDUS

    def test_la_richesse_est_reelle_pas_annoncee(
        self, referentiel: ReferentielStatique
    ) -> None:
        """Le gain se mesure : 576 professions contre les 18 metiers que le
        Loader inventait, et dont UN SEUL — « Commercant » — servait les 1600
        clients INDIVIDUAL (mesure du 12/08)."""
        assert len(referentiel.professions) > 500
        assert len(referentiel.secteurs) > 100


class TestLaCoherenceInterne:
    def test_aucun_secteur_orphelin_d_industrie(
        self, referentiel: ReferentielStatique
    ) -> None:
        connues = set(referentiel.industries.values())
        for secteur, industries in referentiel.secteurs.items():
            assert industries, f"{secteur} sans industrie"
            assert set(industries) <= connues, secteur

    def test_chaque_profession_appartient_a_UN_SEUL_groupe(
        self, referentiel: ReferentielStatique
    ) -> None:
        """Une profession dans deux groupes aurait un profil de revenu ambigu,
        dependant de l'ordre de lecture du fichier."""
        for profession, secteur in referentiel.professions.items():
            assert secteur in referentiel.groupes, profession

    def test_chaque_groupe_pointe_vers_un_profil_qui_existe(
        self, referentiel: ReferentielStatique
    ) -> None:
        for groupe in referentiel.groupes.values():
            assert groupe.profil_defaut in referentiel.profils_revenu
            for profil in groupe.variants.values():
                assert profil in referentiel.profils_revenu

    def test_aucun_libelle_vide_nulle_part(
        self, referentiel: ReferentielStatique
    ) -> None:
        """Une chaine vide passe le `minItems: 1` du serveur SANS RIEN SIGNIFIER.
        C'est exactement le defaut mesure le 12/08 : nos Fondations recevaient
        `sectors=[""]`."""
        assert all(v.strip() for v in referentiel.industries.values())
        assert all(s.strip() for s in referentiel.secteurs)
        assert all(f.strip() for f in referentiel.formes_juridiques)
        assert all(p.strip() for p in referentiel.professions)
        assert all(
            f.francais.strip() and f.anglais.strip()
            for f in referentiel.fonctions_dirigeant
        )


class TestUneSeuleIndustriePasLUnion:
    """LE DEFAUT DE MA PREMIERE CONCEPTION, trouve en mesurant sur les vraies
    donnees plutot qu'en raisonnant.

    Je voulais deriver `industries` comme l'UNION des industries des secteurs
    choisis. Resultat mesure : une Fondation caritative avec
    `sectors=['NGO', 'Charity', 'Health']` tombait en
    `industries=['Commerce', 'Technology']` — parce que `Health` appartient aux
    deux. Une fondation en « Technology » n'a aucun sens.

    Une entreprise se classe par UNE activite principale. C'est la logique
    NACE/ISIC, et c'est celle qu'on applique.
    """

    def test_industrie_du_secteur_rend_UNE_valeur(
        self, referentiel: ReferentielStatique
    ) -> None:
        assert isinstance(referentiel.industrie_du_secteur("MicroFinance"), str)

    def test_les_correspondances_metier_attendues(
        self, referentiel: ReferentielStatique
    ) -> None:
        """Ces quatre libelles seront ceux des quatre `CompanyType`. Ils doivent
        EXISTER dans le fichier — sinon le Loader enverrait au serveur une valeur
        qui n'a aucune source."""
        assert referentiel.industrie_du_secteur("MicroFinance") == "Finance & Insurance"
        assert referentiel.industrie_du_secteur("Banking") == "Finance & Insurance"
        assert referentiel.industrie_du_secteur("Retail") == "Commerce"
        assert referentiel.industrie_du_secteur("NGO") == "Commerce"

    def test_un_secteur_MULTI_industries_rend_quand_meme_UNE_valeur(
        self, referentiel: ReferentielStatique
    ) -> None:
        """28 des 112 secteurs appartiennent a plusieurs industries."""
        multi = [s for s, i in referentiel.secteurs.items() if len(i) > 1]
        assert len(multi) > 20, f"{len(multi)} secteurs multi-industries"
        for secteur in multi:
            assert isinstance(referentiel.industrie_du_secteur(secteur), str)

    def test_le_choix_est_STABLE_entre_deux_chargements(self) -> None:
        """`ENF-15` — arbitraire mais reproductible. Un secteur qui changerait
        d'industrie d'un run a l'autre casserait `CR-03`."""
        a, b = charger_statique(DOSSIER), charger_statique(DOSSIER)
        for secteur in a.secteurs:
            assert a.industrie_du_secteur(secteur) == b.industrie_du_secteur(secteur)

    def test_un_secteur_inconnu_CRIE(self, referentiel: ReferentielStatique) -> None:
        with pytest.raises(ReferentielIncoherent, match="secteur inconnu"):
            referentiel.industrie_du_secteur("Blanchisserie Spatiale")


class TestLesProfilsDeRevenu:
    """`A-09` — ce qui remplacera l'heuristique `quick_win` de `solde_initial`."""

    def test_les_quatre_profils_sont_ordonnes_par_revenu(
        self, referentiel: ReferentielStatique
    ) -> None:
        """La hierarchie doit tenir : un salaire bancaire stable au-dessus d'un
        revenu agricole saisonnier. Sinon le modele contredirait le metier."""
        p = referentiel.profils_revenu
        assert p["bank_stable"].mu > p["sme_formal"].mu > p["micro_informal"].mu
        assert p["micro_informal"].mu > p["agri_seasonal"].mu

    def test_la_VARIABILITE_croit_quand_le_revenu_baisse(
        self, referentiel: ReferentielStatique
    ) -> None:
        """Un revenu informel est plus irregulier qu'un salaire — sigma croit
        quand mu decroit. C'est ce que le fichier encode, et c'est juste."""
        p = referentiel.profils_revenu
        assert p["bank_stable"].sigma < p["sme_formal"].sigma
        assert p["sme_formal"].sigma < p["micro_informal"].sigma
        assert p["micro_informal"].sigma < p["agri_seasonal"].sigma

    def test_les_VARIANTES_ne_sont_pas_ignorees(
        self, referentiel: ReferentielStatique
    ) -> None:
        """« Traditional healer » est dans le groupe *Health and social services*
        dont le defaut est `bank_stable`. Sa variante le met en
        `micro_informal`. L'ignorer donnerait a un guerisseur traditionnel le
        revenu d'un medecin hospitalier."""
        guerisseur = referentiel.profil_de_la_profession("Traditional healer")
        medecin = referentiel.profil_de_la_profession("Public hospital doctor")
        assert guerisseur.nom == "micro_informal"
        assert medecin.nom == "bank_stable"
        assert guerisseur.mu < medecin.mu

    def test_chaque_profession_a_un_profil(
        self, referentiel: ReferentielStatique
    ) -> None:
        for profession in referentiel.professions:
            assert referentiel.profil_de_la_profession(profession).mu > 0

    def test_une_profession_inconnue_CRIE(
        self, referentiel: ReferentielStatique
    ) -> None:
        with pytest.raises(ReferentielIncoherent, match="profession inconnue"):
            referentiel.profil_de_la_profession("Astronaute de Douala")


class TestLaTableEF24:
    """`EF-24` — 20 % des professionnels en agriculture. La famille du CDC reste
    le CONTRAT ; le fichier n'est que la MATIERE."""

    GROUPES_AGRICOLES = (
        "Agronomy and crop farming",
        "Livestock and animal production",
        "Fishing and aquaculture",
        "Forestry and forest products",
    )

    def test_les_quatre_groupes_agricoles_existent(
        self, referentiel: ReferentielStatique
    ) -> None:
        for groupe in self.GROUPES_AGRICOLES:
            assert groupe in referentiel.groupes, groupe

    def test_ils_portent_assez_de_metiers_pour_EF_24(
        self, referentiel: ReferentielStatique
    ) -> None:
        """Le quota agricole est de 20 % des CORPORATE, soit 80 clients sur la
        campagne. Une poignee de metiers les rendrait tous identiques."""
        metiers = referentiel.professions_des_groupes(self.GROUPES_AGRICOLES)
        assert len(metiers) >= 100, f"{len(metiers)} metiers agricoles"

    def test_ils_sont_TOUS_en_profil_agricole(
        self, referentiel: ReferentielStatique
    ) -> None:
        for groupe in self.GROUPES_AGRICOLES:
            assert referentiel.groupes[groupe].profil_defaut == "agri_seasonal"

    def test_un_groupe_inconnu_CRIE(self, referentiel: ReferentielStatique) -> None:
        with pytest.raises(ReferentielIncoherent, match="groupe inconnu"):
            referentiel.professions_des_groupes(("Peche a la baleine",))


class TestLeChargementRefuseLIncoherent:
    """Un referentiel incoherent doit interrompre l'execution. Jamais un echec
    silencieux : `EF-01` applique la meme regle a la geographie."""

    def test_un_dossier_absent_CRIE_avec_le_chemin(self) -> None:
        with pytest.raises(FileNotFoundError, match="Chemin attendu"):
            charger_statique(Path("/inexistant/nulle/part"))

    def test_un_industry_id_orphelin_CRIE(self, tmp_path: Path) -> None:
        self._copier(tmp_path)
        brut = json.loads((tmp_path / FICHIER_SECTEURS).read_text(encoding="utf-8"))
        brut["sectors"][0]["industry_ids"] = [999]
        (tmp_path / FICHIER_SECTEURS).write_text(
            json.dumps(brut), encoding="utf-8"
        )
        with pytest.raises(ReferentielIncoherent, match="n'existent pas"):
            charger_statique(tmp_path)

    def test_un_profil_de_revenu_inconnu_CRIE(self, tmp_path: Path) -> None:
        self._copier(tmp_path)
        brut = json.loads((tmp_path / FICHIER_OCCUPATIONS).read_text(encoding="utf-8"))
        brut["profession_groups"][0]["default_profile"] = "revenu_imaginaire"
        (tmp_path / FICHIER_OCCUPATIONS).write_text(
            json.dumps(brut), encoding="utf-8"
        )
        with pytest.raises(ReferentielIncoherent, match="profil par defaut"):
            charger_statique(tmp_path)

    def test_une_profession_DANS_DEUX_groupes_CRIE(self, tmp_path: Path) -> None:
        """Son profil de revenu dependrait de l'ordre de lecture du fichier."""
        self._copier(tmp_path)
        brut = json.loads((tmp_path / FICHIER_OCCUPATIONS).read_text(encoding="utf-8"))
        volee = brut["profession_groups"][0]["professions"][0]
        brut["profession_groups"][1]["professions"].append(volee)
        (tmp_path / FICHIER_OCCUPATIONS).write_text(
            json.dumps(brut), encoding="utf-8"
        )
        with pytest.raises(ReferentielIncoherent, match="ambigu"):
            charger_statique(tmp_path)

    def test_un_COMPTE_qui_change_CRIE(self, tmp_path: Path) -> None:
        """LE CONTROLE LE PLUS IMPORTANT EN EXPLOITATION. Si JJB livre une
        version 2, le chargement echoue et l'ecart se lit — plutot que de
        decouvrir apres coup que 2000 clients portent une occupation disparue."""
        self._copier(tmp_path)
        brut = json.loads((tmp_path / FICHIER_SECTEURS).read_text(encoding="utf-8"))
        brut["sectors"] = brut["sectors"][:10]
        (tmp_path / FICHIER_SECTEURS).write_text(
            json.dumps(brut), encoding="utf-8"
        )
        with pytest.raises(ReferentielIncoherent, match="comptes du referentiel"):
            charger_statique(tmp_path)

    @staticmethod
    def _copier(cible: Path) -> None:
        for fichier in DOSSIER.iterdir():
            if fichier.suffix in (".json", ".csv"):
                (cible / fichier.name).write_bytes(fichier.read_bytes())


class TestLesFonctionsEtLesPays:
    def test_les_vingt_fonctions_portent_leurs_trois_formes(
        self, referentiel: ReferentielStatique
    ) -> None:
        for fonction in referentiel.fonctions_dirigeant:
            assert fonction.rang >= 1
            assert fonction.francais and fonction.anglais and fonction.abreviation

    def test_le_PDG_est_le_premier(self, referentiel: ReferentielStatique) -> None:
        """L'IMF racine recevra celle-la ; le reste sera reparti."""
        premiere = referentiel.fonctions_dirigeant[0]
        assert "CEO" in premiere.abreviation
        assert "Directeur" in premiere.francais

    def test_les_quatre_pays_cibles_sont_dans_le_referentiel(
        self, referentiel: ReferentielStatique
    ) -> None:
        """Le lieu de naissance (tache #15) en dependra : un client ne peut pas
        naitre dans un pays absent du referentiel.

        MESURE DU 12/08, et elle m'a corrige : la Cote d'Ivoire s'appelle
        « Côte d'Ivoire » dans le fichier, PAS « Ivory Coast ». Mon premier test
        cherchait le libelle anglais attendu et echouait.
        """
        for libelle in PAYS_CIBLES_LIBELLES.values():
            assert libelle in referentiel.pays, libelle

    def test_le_pont_entre_code_ISO_et_libelle(
        self, referentiel: ReferentielStatique
    ) -> None:
        """`nationality` exige l'alpha-2 (« Cameroun » rend un 422, mesure du
        08/08) ; un LIEU de naissance s'ecrit en clair."""
        assert referentiel.nom_du_pays("CM") == "Cameroun"
        assert referentiel.nom_du_pays("CM", en_francais=False) == "Cameroon"
        assert referentiel.nom_du_pays("SN") == "Sénégal"
        assert "Ivoire" in referentiel.nom_du_pays("CI")

    def test_un_pays_hors_perimetre_CRIE(
        self, referentiel: ReferentielStatique
    ) -> None:
        with pytest.raises(ReferentielIncoherent, match="hors perimetre"):
            referentiel.nom_du_pays("FR")
