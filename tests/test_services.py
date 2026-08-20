class TestUniciteDesNoms:
    """`D-12` — aucun service n'impose l'unicite de `name`.

    Ni company-service, ni depositary-service, ni product-service
    (`ANO-PRD-UNIQ-01`). Un doublon n'est pas rejete : il est cree, en
    silence, et trois services n'exposent aucun `DELETE`.

    **Le Loader anticipe, il ne subit pas.** Ces tests verifient qu'il ne
    peut pas produire deux fois le meme nom, meme quand le referentiel reel
    contient des homonymes — ce qui est le cas.
    """

    def _referentiel(self) -> object:
        from pathlib import Path

        from app.services.geographie import charger_referentiel

        return charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))

    def test_les_regions_homonymes_ne_produisent_pas_deux_branches_identiques(self) -> None:
        """`Centre`, `Est`, `Nord`, `Sud-Ouest` existent dans PLUSIEURS pays.

        Mesure du 09/08 : 4 doublons sur 51 branches avant `D-12`.
        """
        from uuid import uuid4

        from app.services.generateur import Generateur

        ref = self._referentiel()
        regions = list(ref.regions.values())  # type: ignore[attr-defined]
        partages = {r.name.lower() for r in regions}
        assert len(partages) < len(regions), "le referentiel doit contenir des homonymes"

        gen = Generateur(uuid4())
        noms = [gen.nom_branche(r.name, r.country_iso2) for r in regions]
        assert len(set(noms)) == len(noms)
        assert "Branche Centre BF" in noms  # leve par le code pays

    def test_le_quartier_plateau_existe_deux_fois_et_donne_deux_kiosques_distincts(self) -> None:
        """Cas le PLUS grave : depositary-service n'a aucun champ geographique.

        Deux « Kiosque Plateau » seraient strictement indiscernables.
        """
        from uuid import uuid4

        from app.services.generateur import Generateur

        ref = self._referentiel()
        quartiers = list(ref.quartiers.values())  # type: ignore[attr-defined]
        gen = Generateur(uuid4())
        noms = [gen.nom_kiosque(q.name) for q in quartiers]
        assert len(set(noms)) == len(noms)
        assert "Kiosque Plateau 2" in noms

    def test_huit_companies_dans_un_pays_de_cinq_patronymes(self) -> None:
        """Le parametrage du boss autorise plus de companies que de patronymes.

        La levee passe par le SUFFIXE COMMERCIAL, pas par le code pays : deux
        maisons camerounaises ne se distinguent pas par « CM ».
        """
        from uuid import uuid4

        from app.services.generateur import Generateur, patronyme

        gen = Generateur(uuid4())
        noms = [gen.raison_sociale(patronyme("CM", i), "SARL", "Textile", "CM") for i in range(8)]
        assert len(set(noms)) == 8
        assert any(n.endswith("& Fils") for n in noms)

    def test_un_nom_calcule_deux_fois_ne_donne_pas_le_meme_resultat(self) -> None:
        """Le registre est CONSOMMABLE — c'est ce qui a impose que le nom du
        Kiosque voyage avec son identifiant plutot que d'etre recompose."""
        from uuid import uuid4

        from app.services.generateur import Generateur

        gen = Generateur(uuid4())
        assert gen.nom_kiosque("Bonapriso", "CM") != gen.nom_kiosque("Bonapriso", "CM")
