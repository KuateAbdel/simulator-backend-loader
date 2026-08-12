"""Execution du module Organisation en DRY_RUN — hors ligne, avec des doublures.

Ce que ce test prouve : la chaine complete de l'etape 2 se deroule de bout en
bout **sans emettre une seule ecriture**. C'est la seule facon responsable
d'aborder company-service et account-service, qui n'exposent aucun DELETE.

Il verifie aussi le comportement en echec : UC-07 exige que « le Loader
journalise l'erreur et poursuit avec la Company suivante ». Le statut devient
alors PARTIAL — un etat terminal LEGITIME, pas un plantage.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.clients.base import ErreurService
from app.clients.contracts import CompanyType
from app.core.cdc import (
    COMPTES_LENDER,
    DOTATION_CAPITAL_INSTITUTIONNEL,
    DOTATION_CAPITAL_LOCAL,
    LENDERS_INSTITUTIONNELS,
    LENDERS_LOCAUX_PAR_PAYS,
    PAYS_CIBLES,
)
from app.models.enums import RunMode, RunStatus
from app.services.generateur import Generateur
from app.services.geographie import ReferentielGeo, charger_referentiel
from app.services.organisation import planifier
from app.services.organisation_execution import (
    FORME_PAR_TYPE,
    SECTEURS_MAX_PAR_COMPANY,
    SECTEURS_PAR_TYPE,
    ExecuteurOrganisation,
    RapportOrganisation,
    _fonction_du_dirigeant_pour,
    secteurs_et_industrie,
)
from app.services.referentiel_statique import charger_statique

RUN_ID = UUID("11111111-2222-3333-4444-555555555555")
SIM_START = date(2026, 2, 9)
SIM_END = date(2026, 8, 8)


# -- Doublures : aucune sortie reseau -------------------------------------


class CompanyClientMuet:
    """Repond « rien ne pre-existe » et compte les ecritures tentees."""

    def __init__(self) -> None:
        self.ecritures = 0

    async def chercher_par_short_name(self, short_name: str) -> dict[str, Any] | None:
        return None

    async def creer_company(self, **kwargs: Any) -> dict[str, Any]:
        self.ecritures += 1
        return {"_id": str(uuid4()), "name": kwargs["name"], "owner": {"_id": str(uuid4())}}

    async def creer_licence(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.ecritures += 1
        return {"_id": str(uuid4())}

    async def a_une_licence(self, company_id: Any) -> bool:
        return False

    @staticmethod
    def identifiant(company: dict[str, Any]) -> str | None:
        return str(company.get("_id")) if company.get("_id") else None

    @staticmethod
    def identifiant_owner(company: dict[str, Any]) -> str | None:
        owner = company.get("owner")
        return str(owner.get("_id")) if isinstance(owner, dict) and owner.get("_id") else None


class CompanyClientDefaillant(CompanyClientMuet):
    """Reproduit ANO-CPY-BUG-06 : la creation echoue en HTTP 400."""

    async def creer_company(self, **kwargs: Any) -> dict[str, Any]:
        raise ErreurService(
            "company-service",
            "POST",
            "/api/v1/companies/",
            400,
            "'NoneType' object has no attribute 'email'",
            "req-test",
        )


class UserClientMuet:
    def __init__(self) -> None:
        self.ecritures = 0

    async def creer_utilisateur_applicatif(self, **kwargs: Any) -> dict[str, Any]:
        self.ecritures += 1
        return {"access_token": "x"}


class AccountClientMuet:
    def __init__(self) -> None:
        self.ecritures = 0

    async def comptes_du_proprietaire(self, owner_id: Any) -> list[dict[str, Any]]:
        return []

    async def creer_compte(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ecritures += 1
        return {"_id": str(uuid4())}

    def payload_compte(self, **kwargs: Any) -> dict[str, Any]:
        return {"type": kwargs["type_compte"].value}

    def payloads_des_4_comptes_lender(
        self, company_id: Any, owner_name: str, currency: str
    ) -> dict[str, dict[str, Any]]:
        return {nom.lower(): {"type": nom, "currency": currency} for nom in COMPTES_LENDER}

    #: `UC-10` point 2 — la dotation. `solde_rendu` permet de simuler `FRA-218`,
    #: ou le solde relu differe du montant demande.
    solde_rendu: float | None = None
    dotations: list[float] = []  # noqa: RUF012 — doublure de test, pas un modele

    def payload_dotation_capital(
        self, *, compte_capital_id: Any, montant: float, nom_lender: str
    ) -> dict[str, Any]:
        return {"amount": montant, "dest_account_id": str(compte_capital_id)}

    async def crediter(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.ecritures += 1
        self.dotations.append(float(payload["amount"]))
        return {"_id": str(uuid4())}

    async def solde(self, account_id: Any) -> float | None:
        if self.solde_rendu is not None:
            return self.solde_rendu
        return self.dotations[-1] if self.dotations else 0.0

    @staticmethod
    def identifiant(compte: dict[str, Any]) -> str | None:
        return str(compte.get("_id"))

    @staticmethod
    def types_presents(comptes: list[dict[str, Any]]) -> set[str]:
        return set()


class RegistreMuet:
    def __init__(self) -> None:
        self.inscrits: list[str] = []

    async def enregistrer(self, **kwargs: Any) -> Any:
        self.inscrits.append(str(kwargs["company_id"]))

        class _Entree:
            id = uuid4()

        return _Entree()


class AuditMuet:
    def __init__(self) -> None:
        self.entrees: list[str] = []

    async def journaliser(self, **kwargs: Any) -> None:
        self.entrees.append(str(kwargs["entity_type"]))


#: `SD-1` — charge une fois pour tout le module. Les libelles de secteur et
#: d'industrie qu'il porte partent REELLEMENT au serveur : les simuler masquerait
#: une incoherence entre notre catalogue et ce qu'on envoie.
STATIQUE = charger_statique()


@pytest.fixture(scope="module")
def referentiel() -> ReferentielGeo:
    return charger_referentiel(
        __import__("pathlib").Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx")
    )


def _executeur(mode: RunMode, referentiel: ReferentielGeo, company_client: Any = None):  # type: ignore[no-untyped-def]
    doublures = {
        "company": company_client or CompanyClientMuet(),
        "user": UserClientMuet(),
        "account": AccountClientMuet(),
        "registre": RegistreMuet(),
        "audit": AuditMuet(),
    }
    executeur = ExecuteurOrganisation(
        # `SD-2` — le catalogue de JJB fournit les secteurs et industries reels.
        # Le charger ici plutot que de le simuler : ces libelles partent au
        # serveur, et un double appauvri masquerait une incoherence.
        statique=STATIQUE,
        run_id=RUN_ID,
        mode=mode,
        referentiel=referentiel,
        generateur=Generateur(RUN_ID),
        company_client=doublures["company"],
        user_client=doublures["user"],
        account_client=doublures["account"],
        registre_lenders=doublures["registre"],
        audit=doublures["audit"],
    )
    return executeur, doublures


class TestDryRun:
    async def test_aucune_ecriture_n_est_emise(self, referentiel: ReferentielGeo) -> None:
        """Le coeur du DRY_RUN : la chaine se deroule, rien n'est ecrit."""
        executeur, doublures = _executeur(RunMode.DRY_RUN, referentiel)
        plan = planifier(referentiel, RUN_ID)

        rapport = await executeur.executer(plan, SIM_START, SIM_END)

        assert doublures["company"].ecritures == 0
        assert doublures["user"].ecritures == 0
        assert doublures["account"].ecritures == 0
        assert rapport.companies_creees, "le dry-run doit annoncer ce qui serait cree"

    async def test_le_rapport_annonce_la_volumetrie_du_plan(
        self, referentiel: ReferentielGeo
    ) -> None:
        executeur, _ = _executeur(RunMode.DRY_RUN, referentiel)
        plan = planifier(referentiel, RUN_ID)

        rapport = await executeur.executer(plan, SIM_START, SIM_END)

        # `EF-12` — les 4 Lenders institutionnels GLOBAUX s'ajoutent aux
        # Companies par pays du plan. Ils etaient auparavant une simple ligne de
        # rapport, jamais crees : le total attendu ne les comptait donc pas.
        attendu = sum(p.nb_companies for p in plan.pays) + len(LENDERS_INSTITUTIONNELS)
        assert len(rapport.companies_creees) == attendu
        assert len(rapport.admins_crees) == attendu, "un Admin User par Company (D-CMP-2)"
        assert rapport.statut is RunStatus.COMPLETED

    async def test_les_4_lenders_institutionnels_sont_prevus(
        self, referentiel: ReferentielGeo
    ) -> None:
        """UC-08 : noms fixes, jamais issus de Faker."""
        executeur, _ = _executeur(RunMode.DRY_RUN, referentiel)
        rapport = await executeur.executer(planifier(referentiel, RUN_ID), SIM_START, SIM_END)
        for nom in LENDERS_INSTITUTIONNELS:
            assert any(nom in ligne for ligne in rapport.lenders_enregistres)


class TestAnticipationDesAnomalies:
    async def test_ano_cpy_bug_06_journalise_et_poursuit(self, referentiel: ReferentielGeo) -> None:
        """UC-07, cas alternatif : « le Loader journalise l'erreur et poursuit
        avec la Company suivante ». Le run ne s'arrete jamais sur une entite."""
        executeur, _ = _executeur(RunMode.REAL, referentiel, CompanyClientDefaillant())
        plan = planifier(referentiel, RUN_ID)

        rapport = await executeur.executer(plan, SIM_START, SIM_END)

        assert rapport.companies_echouees, "l'echec doit etre journalise"
        assert all("NoneType" in motif for _, motif in rapport.companies_echouees)
        attendu = sum(p.nb_companies for p in plan.pays) + len(LENDERS_INSTITUTIONNELS)
        assert len(rapport.companies_echouees) == attendu, (
            "toutes les Companies ont ete tentees, institutionnelles comprises, "
            "aucune interruption"
        )
        assert rapport.statut is RunStatus.FAILED, "aucune Company creee = probleme systemique"

    async def test_un_echec_partiel_donne_partial(self, referentiel: ReferentielGeo) -> None:
        """PARTIAL est un etat terminal LEGITIME, pas un plantage."""
        rapport = RapportOrganisation(mode=RunMode.REAL)
        rapport.companies_creees.append("DEMO_SARL Kouassi")
        rapport.companies_echouees.append(("DEMO_SA Kabore", "HTTP 400"))
        assert rapport.statut is RunStatus.PARTIAL

    async def test_le_detail_serveur_est_tronque(self, referentiel: ReferentielGeo) -> None:
        """ANO-CPY-LEAK-07 : les messages fuient des traces Python. On les
        tronque avant journalisation, on ne les parse jamais."""
        executeur, _ = _executeur(RunMode.REAL, referentiel, CompanyClientDefaillant())
        rapport = await executeur.executer(planifier(referentiel, RUN_ID), SIM_START, SIM_END)
        for _, motif in rapport.companies_echouees:
            assert len(motif) <= 200


def test_fra199_la_devise_vient_du_referentiel_pas_d_une_table_codee() -> None:
    """`Company.currency` est write-only et perdue a la persistance (FRA-199) —
    raison de plus pour que NOTRE trace soit juste.

    La table `DEVISE_PAR_PAYS` codee en dur a ete retiree : la devise est
    determinee par la **zone monetaire** portee par le referentiel. XAF est la
    zone CEMAC, XOF la zone UEMOA. Croisement Sprint 1.
    """
    from pathlib import Path

    from app.services.geographie import charger_referentiel

    referentiel = charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))
    assert referentiel.devise_du_pays("CM").code == "XAF"
    for pays in ("CI", "BF", "SN"):
        assert referentiel.devise_du_pays(pays).code == "XOF"


def test_le_telephone_suit_le_plan_de_numerotation_du_pays() -> None:
    """Defaut reel corrige : `f"+237{600000000 + index}"` codait l'indicatif
    camerounais en dur POUR LES QUATRE PAYS — une Company senegalaise recevait
    un numero camerounais. Et `600000001` n'etait meme pas valide au Cameroun,
    aucun operateur n'y utilisant le prefixe `60`.
    """
    import random
    from pathlib import Path

    from app.services.geographie import charger_referentiel

    referentiel = charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))
    for pays, indicatif in (("CM", "237"), ("CI", "225"), ("BF", "226"), ("SN", "221")):
        alea = random.Random(f"test-{pays}")  # noqa: S311
        numero, operateur = referentiel.composer_msisdn(pays, "00000001", alea)
        assert numero.startswith(indicatif), f"{pays} : indicatif errone"
        assert operateur.country_iso2 == pays
        assert referentiel.operateur_du_msisdn(numero, pays) is not None


class TestDotationDuCapital:
    """`UC-10` point 2 — « il alimente le compte CAPITAL avec un montant initial
    dependant du type de Lender (institutionnels plus dotes que locaux) ».

    Ce que ces tests protegent : que le CAPITAL ne reste JAMAIS a zero. Un Lender
    a capital nul ne peut rien financer, et l'IFC affichant 0 franc devant un
    bailleur se voit au premier ecran.
    """

    async def test_l_institutionnel_est_plus_dote_que_le_local(self) -> None:
        """La seule contrainte CHIFFREE du CDC sur ce point."""
        assert DOTATION_CAPITAL_INSTITUTIONNEL > DOTATION_CAPITAL_LOCAL

    async def test_le_dry_run_annonce_la_dotation_qu_il_n_ecrit_pas(
        self, referentiel: ReferentielGeo
    ) -> None:
        """`D-01`, lecon du 11/08 : l'essai a blanc annonce TOUT ce que le reel
        ecrira. Un rapport qui tait une ecriture fait dire oui a l'aveugle."""
        executeur, doublures = _executeur(RunMode.DRY_RUN, referentiel)

        rapport = await executeur.executer(planifier(referentiel, RUN_ID), SIM_START, SIM_END)

        attendu = (
            LENDERS_LOCAUX_PAR_PAYS * len(PAYS_CIBLES) * DOTATION_CAPITAL_LOCAL
            + len(LENDERS_INSTITUTIONNELS) * DOTATION_CAPITAL_INSTITUTIONNEL
        )
        assert rapport.capital_dote == attendu
        assert doublures["account"].ecritures == 0, "le DRY_RUN n'ecrit rien"

    async def test_le_reel_credite_et_RELIT_le_solde(self, referentiel: ReferentielGeo) -> None:
        """`FRA-218` — les frais sont retranches et credites nulle part. Le solde
        se RELIT, il ne se deduit pas."""
        executeur, doublures = _executeur(RunMode.REAL, referentiel)
        compte = doublures["account"]
        compte.dotations = []
        compte.solde_rendu = None

        rapport = await executeur.executer(planifier(referentiel, RUN_ID), SIM_START, SIM_END)

        assert compte.dotations, "aucune dotation emise"
        assert DOTATION_CAPITAL_INSTITUTIONNEL in compte.dotations
        assert DOTATION_CAPITAL_LOCAL in compte.dotations
        assert rapport.capital_dote > 0

    async def test_un_solde_relu_different_ne_fait_pas_echouer_le_lender(
        self, referentiel: ReferentielGeo
    ) -> None:
        """`FRA-218` en action : le rapport porte le solde REEL, pas le demande —
        et l'ecart ne casse pas le run."""
        executeur, doublures = _executeur(RunMode.REAL, referentiel)
        compte = doublures["account"]
        compte.dotations = []
        compte.solde_rendu = 1.0  # le serveur a mange le montant

        rapport = await executeur.executer(planifier(referentiel, RUN_ID), SIM_START, SIM_END)

        assert rapport.capital_dote == float(len(compte.dotations)), (
            "le rapport doit porter le solde RELU, jamais la somme demandee"
        )
        assert rapport.companies_creees, "un ecart de solde n'annule aucune Company"


class TestSecteursEtIndustries:
    """`SD-2` — deux axes distincts, plus un doublon.

    LE DEFAUT CORRIGE, mesure le 12/08 : nous envoyions `industries=[secteur]` ET
    `sectors=[secteur]` — la MEME valeur dans les deux champs. `Finance &
    Insurance` est une INDUSTRIE, `MicroFinance` un SECTEUR de cette industrie.

    La trace est en base depuis le 08/08 : `DEMO_QA0808_SARL Tamadou Textile`
    porte `industries=["MicroFinance"]` et `sectors=["Textile"]` — deux valeurs
    qui n'ont aucun rapport. Sans `DELETE`, elle reste fausse a jamais.
    """

    def test_chaque_libelle_declare_EXISTE_dans_le_referentiel(self) -> None:
        """LE TEST LE PLUS IMPORTANT DE CETTE CLASSE. Treize libelles sont
        declares en dur ; si JJB en renomme un, le Loader enverrait au serveur une
        valeur qui n'a AUCUNE source. Ce test l'interdit."""
        manquants = [
            (typ.value, libelle)
            for typ, (principal, connexes) in SECTEURS_PAR_TYPE.items()
            for libelle in (principal, *connexes)
            if libelle not in STATIQUE.secteurs
        ]
        assert manquants == [], f"libelles absents du fichier de JJB : {manquants}"

    def test_chaque_forme_juridique_EXISTE_dans_le_referentiel(self) -> None:
        absentes = [
            (typ.value, forme)
            for typ, forme in FORME_PAR_TYPE.items()
            if forme not in STATIQUE.formes_juridiques
        ]
        assert absentes == [], f"formes absentes des 27 du fichier : {absentes}"

    def test_chaque_connexe_partage_l_industrie_de_son_principal(self) -> None:
        """Sinon une Company porterait des secteurs de deux industries, et
        `industries` — derivee du principal — mentirait sur une partie d'eux.

        C'est ce controle qui a fait ecarter le tirage automatique parmi TOUS les
        secteurs d'une industrie : il produisait `['Retail', 'NGO']`, un
        commercant qui est une ONG.
        """
        for typ, (principal, connexes) in SECTEURS_PAR_TYPE.items():
            industrie = STATIQUE.industrie_du_secteur(principal)
            hors = [c for c in connexes if industrie not in STATIQUE.secteurs[c]]
            assert hors == [], f"{typ.value} : {hors} hors de {industrie}"

    def test_UNE_SEULE_industrie_par_Company(self) -> None:
        """Une entreprise se classe par UNE activite principale — logique
        NACE/ISIC. Prendre l'union des industries des secteurs choisis classait
        une fondation caritative en « Technology », parce que `Health` appartient
        a la fois a Commerce et a Technology."""
        for typ in SECTEURS_PAR_TYPE:
            for rang in range(20):
                _, industries = secteurs_et_industrie(typ, f"a{rang}", STATIQUE)
                assert len(industries) == 1, (typ.value, industries)

    def test_le_PRINCIPAL_est_TOUJOURS_en_tete(self) -> None:
        for typ, (principal, _) in SECTEURS_PAR_TYPE.items():
            for rang in range(20):
                secteurs, _ = secteurs_et_industrie(typ, f"b{rang}", STATIQUE)
                assert secteurs[0] == principal, (typ.value, secteurs)

    def test_de_UN_a_TROIS_secteurs_sans_doublon(self) -> None:
        """`sectors` est un `array` de `minItems: 1` — une Company reelle en
        declare plusieurs, mais jamais deux fois le meme."""
        vues = set()
        for typ in SECTEURS_PAR_TYPE:
            for rang in range(40):
                secteurs, _ = secteurs_et_industrie(typ, f"c{rang}", STATIQUE)
                assert 1 <= len(secteurs) <= SECTEURS_MAX_PAR_COMPANY
                assert len(secteurs) == len(set(secteurs)), secteurs
                vues.add(len(secteurs))
        assert vues == {1, 2, 3}, f"les trois tailles doivent apparaitre : {vues}"

    def test_AUCUN_secteur_vide_JAMAIS(self) -> None:
        """`_profil_company` rendait `secteur=""` pour les Fondations, donc
        `sectors=[""]` : une chaine vide qui passe le `minItems: 1` du serveur SANS
        RIEN SIGNIFIER. C'est un doublon de defaut, pas une valeur."""
        for typ in SECTEURS_PAR_TYPE:
            for rang in range(20):
                secteurs, industries = secteurs_et_industrie(typ, f"d{rang}", STATIQUE)
                assert all(s.strip() for s in secteurs), (typ.value, secteurs)
                assert all(i.strip() for i in industries), (typ.value, industries)

    def test_la_FONDATION_est_une_ONG_pas_un_commerce_vide(self) -> None:
        secteurs, industries = secteurs_et_industrie(
            CompanyType.FONDATION, "fondation", STATIQUE
        )
        assert secteurs[0] == "NGO"
        assert industries == ["Commerce"]

    def test_le_BAILLEUR_institutionnel_ne_fait_PAS_de_microfinance(self) -> None:
        """`EF-12` — les 4 institutionnels financent, ils ne collectent pas."""
        secteurs, _ = secteurs_et_industrie(
            CompanyType.FUNDING_PROVIDER, "bailleur", STATIQUE
        )
        assert secteurs[0] == "Investment"
        assert "MicroFinance" not in secteurs

    def test_ANCRE_a_la_Company_jamais_au_run(self) -> None:
        """`CR-03` — deux runs du meme perimetre doivent donner les memes secteurs,
        sinon une reprise reecrirait la fiche."""
        for typ in SECTEURS_PAR_TYPE:
            a = secteurs_et_industrie(typ, "DEMO_SARL Kouassi", STATIQUE)
            b = secteurs_et_industrie(typ, "DEMO_SARL Kouassi", STATIQUE)
            assert a == b

    def test_deux_Companies_DIFFERENTES_ne_sont_pas_toutes_identiques(self) -> None:
        vus = {
            tuple(secteurs_et_industrie(CompanyType.MERCHANT, f"m{r}", STATIQUE)[0])
            for r in range(30)
        }
        assert len(vus) > 1, "toutes les Companies auraient les memes secteurs"


class TestFonctionDuDirigeant:
    """`SD-4` — « Dirigeant » etait code en dur. Le fichier de JJB en donne 20."""

    def test_l_IMF_racine_porte_la_fonction_de_PDG(self) -> None:
        """C'est elle qui porte toute la hierarchie (`UC-09`) : lui donner un
        titre subalterne serait incoherent."""
        fonction = _fonction_du_dirigeant_pour("DEMO_SARL Kouassi", True, STATIQUE)
        assert "Directeur" in fonction and "General" in fonction.replace("é", "e")

    def test_les_autres_ne_sont_pas_toutes_PDG(self) -> None:
        vues = {
            _fonction_du_dirigeant_pour(f"DEMO_SA Nom{r}", False, STATIQUE)
            for r in range(30)
        }
        assert len(vues) > 3, f"seulement {len(vues)} fonction(s) distincte(s) : {vues}"
        assert STATIQUE.fonctions_dirigeant[0].francais not in vues, (
            "la fonction de PDG est reservee a l'IMF racine"
        )

    def test_toujours_une_fonction_du_REFERENTIEL(self) -> None:
        admises = {f.francais for f in STATIQUE.fonctions_dirigeant}
        for est_imf in (True, False):
            for r in range(30):
                assert (
                    _fonction_du_dirigeant_pour(f"DEMO_X{r}", est_imf, STATIQUE)
                    in admises
                )

    def test_le_libelle_est_en_FRANCAIS_jamais_l_abreviation(self) -> None:
        """Les quatre pays cibles sont francophones, et `occupation` est un champ
        libre que le serveur ne valide pas — c'est a nous d'y mettre du sens."""
        fonction = _fonction_du_dirigeant_pour("DEMO_SA Test", False, STATIQUE)
        abreviations = {f.abreviation for f in STATIQUE.fonctions_dirigeant}
        anglais = {f.anglais for f in STATIQUE.fonctions_dirigeant}
        assert fonction not in abreviations
        assert fonction not in anglais

    def test_ANCREE_a_la_Company_jamais_au_run(self) -> None:
        """`CR-03` — `raison_sociale()` est stable d'un run a l'autre, donc la
        fonction doit l'etre aussi."""
        a = _fonction_du_dirigeant_pour("DEMO_SA Fall", False, STATIQUE)
        b = _fonction_du_dirigeant_pour("DEMO_SA Fall", False, STATIQUE)
        assert a == b
