"""
app/repositories/org_hierarchy.py
=================================
Arbre operationnel Branche -> Agence -> Kiosque -> Agent, cote Loader
(decisions `D-05` pour les trois premiers niveaux, `D-11` pour l'Agent).

Cette collection porte a elle seule la verification de recette **CR-02** :
« aucune incoherence geo-organisationnelle apres une generation complete —
chaque Kiosque a un District valide, chaque Agence une Ville valide ».

Elle est indispensable parce que `CreateDepositaireSchema` ne comporte **aucun
champ geographique** : `name`, `currency`, `company_id`, rien d'autre.
depositary-service ignore tout du quartier ou se trouve un Kiosque. Si nous ne
le stockons pas, l'information n'existe nulle part.

L'index unique `(run_id, district_id)` garantit qu'un quartier n'heberge qu'un
seul Kiosque par execution — sans lui, plusieurs guichets se superposeraient au
meme endroit, ce qu'un bailleur reperait immediatement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from pymongo.errors import DuplicateKeyError

from app.core.cdc import PREFIXE_DONNEES
from app.core.database import COLLECTION_ORG_HIERARCHY
from app.models.domain import OrgHierarchyNode
from app.models.enums import NiveauOrganisation
from app.repositories.base import RepositoryBase, en_document


class OrgHierarchyRepository(RepositoryBase):
    collection_name = COLLECTION_ORG_HIERARCHY

    async def ajouter_branche(
        self, run_id: UUID, company_id: UUID, name: str, country_code: str, region_id: str
    ) -> OrgHierarchyNode:
        noeud = OrgHierarchyNode(
            id=uuid4(),
            run_id=run_id,
            niveau=NiveauOrganisation.BRANCHE,
            parent_id=None,
            company_id=company_id,
            name=name,
            country_code=country_code.upper(),
            region_id=region_id,
        )
        await self._inserer(noeud)
        return noeud

    async def ajouter_agence(
        self,
        run_id: UUID,
        branche_id: UUID,
        company_id: UUID,
        name: str,
        country_code: str,
        city_id: str,
    ) -> OrgHierarchyNode:
        """Une Agence ne peut exister sans sa Branche (EF-18)."""
        if await self.collection.find_one({"_id": str(branche_id)}) is None:
            raise ValueError(f"Branche {branche_id} introuvable — emboitement viole (EF-18)")
        noeud = OrgHierarchyNode(
            id=uuid4(),
            run_id=run_id,
            niveau=NiveauOrganisation.AGENCE,
            parent_id=branche_id,
            company_id=company_id,
            name=name,
            country_code=country_code.upper(),
            city_id=city_id,
        )
        await self._inserer(noeud)
        return noeud

    async def ajouter_kiosque(
        self,
        run_id: UUID,
        agence_id: UUID,
        company_id: UUID,
        name: str,
        country_code: str,
        district_id: str,
        depositary_id: UUID,
    ) -> OrgHierarchyNode | None:
        """Renvoie None si le quartier heberge deja un Kiosque de ce run.

        `depositary_id` est la seule reference vers une entite reellement creee
        cote serveur — les niveaux BRANCHE et AGENCE n'ont aucune contrepartie
        distante, c'est tout l'objet de la decision D-05.
        """
        if await self.collection.find_one({"_id": str(agence_id)}) is None:
            raise ValueError(f"Agence {agence_id} introuvable — emboitement viole (EF-18)")
        noeud = OrgHierarchyNode(
            id=uuid4(),
            run_id=run_id,
            niveau=NiveauOrganisation.KIOSQUE,
            parent_id=agence_id,
            company_id=company_id,
            name=name,
            country_code=country_code.upper(),
            district_id=district_id,
            depositary_id=depositary_id,
        )
        try:
            await self.collection.insert_one(en_document(noeud))
        except DuplicateKeyError:
            return None
        return noeud

    async def ajouter_agent(
        self,
        run_id: UUID,
        kiosque_id: UUID,
        company_id: UUID,
        name: str,
        country_code: str,
        user_id: UUID,
    ) -> OrgHierarchyNode:
        """Rattache un Agent a son Kiosque — `UC-09` point 4, `D-11`.

        **Pourquoi ce noeud existe alors que l'Agent existe cote serveur.**
        L'Agent EST un `User` de user-service, porteur du groupe « Agent ».
        Mais `User` porte `company_id` et `identity`, **jamais de reference
        vers un Depositaire** : son rattachement au Kiosque n'existe nulle
        part. Sans ce noeud, *« quels Agents dans ce Kiosque ? »* reste sans
        reponse — le defaut meme que nous reprochons a config-service, dont le
        `Telco` ne porte pas son pays.

        `EF-18` s'applique sans exception : **un Agent ne peut exister sans son
        Kiosque**. Le controle est fait ici, avant l'insertion, comme aux trois
        niveaux superieurs.

        Contrairement au Kiosque, aucune unicite n'est imposee : `EF-17` parle
        d'un *« nombre parametrable d'Agents par Kiosque »*, et `UC-09` exige
        « **au moins** un ». Plusieurs Agents dans un meme Kiosque sont
        legitimes.
        """
        if await self.collection.find_one({"_id": str(kiosque_id)}) is None:
            raise ValueError(f"Kiosque {kiosque_id} introuvable — emboitement viole (EF-18)")
        noeud = OrgHierarchyNode(
            id=uuid4(),
            run_id=run_id,
            niveau=NiveauOrganisation.AGENT,
            parent_id=kiosque_id,
            company_id=company_id,
            name=name,
            country_code=country_code.upper(),
            user_id=user_id,
        )
        await self.collection.insert_one(en_document(noeud))
        return noeud

    async def ajouter_produit(
        self,
        run_id: UUID,
        company_id: UUID,
        product_id: UUID,
        marqueur: str,
        package: str,
        country_code: str,
    ) -> OrgHierarchyNode | None:
        """`A-12` / UC-11 pt 3 — le rattachement Produit -> Company.

        Le serveur ne le represente NULLE PART (« company » : zero occurrence
        dans l'OpenAPI de product-service, mesure du 12/08). Troisieme
        occurrence du motif EF-26/D-CLI-6 : le lien vit ici.

        NOEUD RACINE comme la BRANCHE — la Company n'est pas un noeud de
        l'arbre, `company_id` porte le lien. `name` = le MARQUEUR
        (DEMO_<code>), pas le nom metier : noeud technique, et CR-07 verifie
        les prefixes des noeuds — CAT 6 est satisfait par construction.

        Rend None si le couple (company, produit) est deja rattache sur ce
        run : un rattachement n'est pas une quantite, le doublon est un bug.
        """
        existant = await self.collection.find_one(
            {
                "run_id": str(run_id),
                "niveau": NiveauOrganisation.PRODUIT.value,
                "company_id": str(company_id),
                "product_id": str(product_id),
            }
        )
        if existant is not None:
            return None
        noeud = OrgHierarchyNode(
            id=uuid4(),
            run_id=run_id,
            niveau=NiveauOrganisation.PRODUIT,
            parent_id=None,
            company_id=company_id,
            name=marqueur,
            country_code=country_code.upper(),
            product_id=product_id,
            package=package,
        )
        await self.collection.insert_one(en_document(noeud))
        return noeud

    async def produits_par_company(self, run_id: UUID) -> dict[UUID, set[UUID]]:
        """La carte des rattachements — consommee par le panier (CAT 8)."""
        carte: dict[UUID, set[UUID]] = {}
        for noeud in await self.par_niveau(run_id, NiveauOrganisation.PRODUIT):
            if noeud.product_id is not None:
                carte.setdefault(noeud.company_id, set()).add(noeud.product_id)
        return carte

    async def ajouter_client(
        self,
        run_id: UUID,
        kiosque_id: UUID,
        company_id: UUID,
        country_code: str,
        msisdn: str,
        client_id: UUID,
    ) -> OrgHierarchyNode:
        """Rattache un Client a son Kiosque — `EF-26`, PREMIER TEMPS.

        **Pourquoi ce noeud existe alors que le Client existe cote serveur.**
        Mesure du 09/08 : la fiche Client rendue porte quinze cles et **aucune**
        ne permet un rattachement — ni `depositary_id`, ni `kiosque_id`, ni
        `company_id`. `EF-26` (« rattacher chaque client a un Kiosque existant du
        pays cible ») est donc **inapplicable a la creation**. Elle se satisfait
        en deux temps : ce noeud, puis la materialisation par une collecte, qui
        seule porte `client_id` ET `depositary_id` (`D-CLI-6`).

        Jusqu'a cette premiere collecte, ce noeud est notre SEULE trace. Sans
        lui, `CR-02` reste non verifiable quel que soit le nombre de clients
        crees — c'est exactement l'argument de `D-05`.

        `EF-18` s'applique sans exception, comme aux quatre niveaux superieurs :
        le Kiosque doit exister d'abord. Aucune unicite n'est imposee sur le
        rattachement lui-meme — un Kiosque sert evidemment plusieurs clients —
        mais `uniq_client_par_run` interdit d'attacher DEUX fois le meme client.

        Idempotent : rejouer le meme client sur le meme run ne cree pas de second
        noeud. `CR-03` l'exige, et la reprise passe par ce chemin.
        """
        if await self.collection.find_one({"_id": str(kiosque_id)}) is None:
            raise ValueError(f"Kiosque {kiosque_id} introuvable — emboitement viole (EF-18)")
        noeud = OrgHierarchyNode(
            id=uuid4(),
            run_id=run_id,
            niveau=NiveauOrganisation.CLIENT,
            parent_id=kiosque_id,
            company_id=company_id,
            # Un artefact du Loader porte le prefixe (`CR-07`/`EF-63`) ; une
            # personne, non. Le msisdn est la cle naturelle du Client, et stable
            # d'un run a l'autre depuis `D-CLI-11`.
            name=f"{PREFIXE_DONNEES}Client {msisdn}",
            country_code=country_code.upper(),
            client_id=client_id,
            # AUCUN `district_id` : voir `NiveauOrganisation`. L'index
            # `uniq_district_par_run` le rejetterait, mais la vraie raison est que
            # la geographie du client est DERIVEE de ce Kiosque — la dupliquer
            # rendrait l'incoherence possible.
        )
        try:
            await self.collection.insert_one(en_document(noeud))
        except DuplicateKeyError:
            existant = await self.collection.find_one(
                {"run_id": str(run_id), "client_id": str(client_id)}
            )
            if existant is None:  # pragma: no cover — l'index vient de le refuser
                raise
            return OrgHierarchyNode.model_validate(existant)
        return noeud

    async def clients_du_kiosque(self, kiosque_id: UUID) -> list[OrgHierarchyNode]:
        """La relation inverse — *« quels clients rattaches a ce Kiosque ? »*.

        `docs/ANALYSE_CONFIG_SERVICE.md` posait cette question et repondait
        « rien ». C'est ce noeud qui y repond. Sur l'index `idx_parent`, donc
        sans balayage.
        """
        curseur = self.collection.find(
            {"parent_id": str(kiosque_id), "niveau": NiveauOrganisation.CLIENT.value}
        )
        return [OrgHierarchyNode.model_validate(d) async for d in curseur]

    async def compter_clients(self, run_id: UUID) -> int:
        """Le compte des rattachements du run. Sert au rapport et a la recette,
        sans charger 2000 documents en memoire."""
        return await self.collection.count_documents(
            {"run_id": str(run_id), "niveau": NiveauOrganisation.CLIENT.value}
        )

    async def agents_du_kiosque(self, kiosque_id: UUID) -> list[OrgHierarchyNode]:
        """La relation inverse — *« quels Agents dans ce Kiosque ? »*.

        C'est la question que le modele ne savait pas repondre avant `D-11`.
        Elle s'appuie sur l'index `idx_parent`, donc sans balayage.
        """
        curseur = self.collection.find(
            {"parent_id": str(kiosque_id), "niveau": NiveauOrganisation.AGENT.value}
        )
        return [OrgHierarchyNode.model_validate(d) async for d in curseur]

    async def kiosques_sans_agent(self, run_id: UUID) -> list[str]:
        """`UC-09` postcondition : *« chaque Kiosque possede au moins un Agent »*.

        Rend les Kiosques qui n'en ont aucun. **Liste vide = postcondition
        tenue.** C'est un controle de recette, au meme titre que
        `verifier_cr02()`.
        """
        kiosques = await self.par_niveau(run_id, NiveauOrganisation.KIOSQUE)
        avec_agent = {
            str(document["parent_id"])
            async for document in self.collection.find(
                {"run_id": str(run_id), "niveau": NiveauOrganisation.AGENT.value}, {"parent_id": 1}
            )
        }
        return sorted(k.name for k in kiosques if str(k.id) not in avec_agent)

    async def par_niveau(self, run_id: UUID, niveau: NiveauOrganisation) -> list[OrgHierarchyNode]:
        curseur = self.collection.find({"run_id": str(run_id), "niveau": niveau.value})
        return [OrgHierarchyNode.model_validate(d) async for d in curseur]

    async def enfants(self, parent_id: UUID) -> list[OrgHierarchyNode]:
        curseur = self.collection.find({"parent_id": str(parent_id)})
        return [OrgHierarchyNode.model_validate(d) async for d in curseur]

    async def verifier_cr02(self, run_id: UUID) -> list[str]:
        """CR-02 — renvoie la liste des incoherences. Vide = recette passee.

        Controle les trois invariants d'emboitement en une seule lecture de la
        collection, sans aucun appel reseau.
        """
        noeuds = {n.id: n async for n in self._tous(run_id)}
        anomalies: list[str] = []

        for noeud in noeuds.values():
            if noeud.niveau is NiveauOrganisation.PRODUIT:
                # `A-12` — noeud RACINE comme la Branche : la Company n'est pas
                # un noeud, le lien passe par company_id. Verifiable ici :
                # l'identifiant produit, le package qui autorise (UC-11 pt 3),
                # et l'absence de parent.
                if noeud.product_id is None:
                    anomalies.append(f"Produit {noeud.name} sans product_id")
                if not noeud.package:
                    anomalies.append(f"Produit {noeud.name} sans package de licence (UC-11)")
                if noeud.parent_id is not None:
                    anomalies.append(
                        f"Produit {noeud.name} avec un parent — le lien passe par company_id"
                    )
                continue
            if noeud.niveau is NiveauOrganisation.BRANCHE:
                if not noeud.region_id:
                    anomalies.append(f"Branche {noeud.name} sans region_id")
                if noeud.parent_id is not None:
                    anomalies.append(f"Branche {noeud.name} avec un parent — niveau racine attendu")
                continue

            parent = noeuds.get(noeud.parent_id) if noeud.parent_id else None
            if parent is None:
                anomalies.append(f"{noeud.niveau.value} {noeud.name} : parent introuvable")
                continue

            if noeud.niveau is NiveauOrganisation.AGENCE:
                if not noeud.city_id:
                    anomalies.append(f"Agence {noeud.name} sans city_id")
                if parent.niveau is not NiveauOrganisation.BRANCHE:
                    anomalies.append(f"Agence {noeud.name} rattachee a un {parent.niveau.value}")
            elif noeud.niveau is NiveauOrganisation.KIOSQUE:
                if not noeud.district_id:
                    anomalies.append(f"Kiosque {noeud.name} sans district_id")
                if noeud.depositary_id is None:
                    anomalies.append(f"Kiosque {noeud.name} sans depositary_id")
                if parent.niveau is not NiveauOrganisation.AGENCE:
                    anomalies.append(f"Kiosque {noeud.name} rattache a un {parent.niveau.value}")
            elif noeud.niveau is NiveauOrganisation.CLIENT:
                # `EF-26` — le cinquieme niveau. Le laisser hors de ce controle
                # reviendrait a poser le rattachement sans le verifier, exactement
                # ce que le commentaire de l'AGENT ci-dessous reproche.
                #
                # Le district n'est PAS controle : le noeud n'en porte pas, par
                # conception. La coherence geographique du client vient de
                # `ancrer_sur_kiosque()`, qui la DERIVE de ce Kiosque — elle est
                # donc vraie par construction et non par verification. Ce qui
                # reste verifiable ici, c'est l'emboitement et le pays.
                if noeud.client_id is None:
                    anomalies.append(f"Client {noeud.name} sans client_id")
                if parent.niveau is not NiveauOrganisation.KIOSQUE:
                    anomalies.append(f"Client {noeud.name} rattache a un {parent.niveau.value}")
                elif noeud.country_code != parent.country_code:
                    anomalies.append(
                        f"Client {noeud.name} en {noeud.country_code} rattache au Kiosque "
                        f"{parent.name} en {parent.country_code} — EF-26 exige un Kiosque "
                        "du pays cible"
                    )
            elif noeud.niveau is NiveauOrganisation.AGENT:
                # Le 4e niveau manquait a ce controle. `D-11` a cree le niveau
                # AGENT precisement pour rendre `UC-09` point 4 verifiable ; le
                # laisser hors de `verifier_cr02()` revenait a le poser sans le
                # verifier. Un Agent rattache a une Agence, ou sans `user_id`,
                # passait en silence.
                if noeud.user_id is None:
                    anomalies.append(f"Agent {noeud.name} sans user_id")
                if parent.niveau is not NiveauOrganisation.KIOSQUE:
                    anomalies.append(f"Agent {noeud.name} rattache a un {parent.niveau.value}")

        return anomalies

    async def _tous(self, run_id: UUID) -> AsyncIterator[OrgHierarchyNode]:
        async for document in self.collection.find({"run_id": str(run_id)}):
            yield OrgHierarchyNode.model_validate(document)
