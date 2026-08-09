"""
app/services/roles_execution.py
===============================
Execution du module Roles — `D-09`, Sprint 2, story `S2-02`.

**11 groupes a creer, 1 reutilise.** Le 12e role metier, « Client », EST le
groupe `CUSTOMER` deja en base (tag `CUSTOMER`, 12 permissions). On ne le
recree pas.

Origine des 12 roles : *Strategie Seed v2.0*, reprise en Gap 1 de la page
Service Anatomy user-service (56360965). Le Confluence note explicitement que
le mapping vers les 5 `UserType` *« n'est pas encore materialise »* — celui de
`D-09` est le premier.

CE QUI REND CE MODULE PARTICULIER
----------------------------------
**C'est la seule ecriture entierement REVERSIBLE du Loader.**
`DELETE /api/v1/groupes/{id}` existe — rare dans cet ecosysteme ou trois
services n'exposent aucune suppression. Un run de roles rate se defait.

Cela ne dispense pas du mode `DRY_RUN` : on montre ce qui serait cree avant de
le creer, comme partout ailleurs.

LES CONTRAINTES PORTEES
-----------------------
  `GET`-avant-`POST`   Aucune unicite serveur sur `name` n'est garantie. Les 4
                       groupes existants sont relus avant toute creation ; ceux
                       qui portent deja le nom voulu sont REUTILISES.
  tag `ROOT` interdit  Il est persiste en base sur le groupe ROOT, mais absent
                       de l'enumeration (`A4`). Le role Super-Admin prend donc
                       `tag: STAFF` — jamais `ROOT` en ecriture.
  `company_id = ""`    Role GLOBAL. Les 4 groupes existants portent la chaine
                       vide — sauf `COMPANY`, qui porte `null` (mesure du
                       09/08, correction apportee a `D-06`). On emet toujours
                       la chaine vide.
  `routes` vide        Comme sur les 4 groupes existants.
  22 permissions       Les `LENDER_*` relevent du Sprint 5, hors perimetre
  ecartees             (`D-07`). La permission parasite `RC169_*` aussi. Le
                       filtrage vit dans `UserServiceClient.lister_permissions`.

CE QUI RESTE EN ATTENTE
-----------------------
**`A-05` — les permissions exactes de chaque role** est un arbitrage PRODUIT,
pas technique. Ce module cree donc les 11 groupes avec un jeu **minimal et
coherent**, chaque role recevant les permissions de son domaine. Le rapport le
signale explicitement : Yaniv corrigera **sur piece** plutot que sur
description.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.clients.contracts import TagGroupe, UserType
from app.clients.user_service import UserServiceClient
from app.models.enums import RunMode, RunStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RoleMetier:
    """Un des 12 roles de la Strategie Seed v2.0.

    `prefixes_permissions` designe les familles de permissions du domaine —
    c'est la proposition en attente de `A-05`, pas une decision figee.
    """

    nom: str
    description: str
    tag: TagGroupe
    type_user: UserType
    prefixes_permissions: tuple[str, ...]
    reutilise: bool = False


#: Les 12 roles, dans l'ordre de `D-09`. Le 12e est marque `reutilise` : il
#: existe deja en base sous le nom `CUSTOMER`, avec ses 12 permissions.
ROLES_METIER: tuple[RoleMetier, ...] = (
    RoleMetier(
        "Super-Admin",
        "Administration complete de la plateforme",
        TagGroupe.STAFF,
        UserType.ROOT,
        (
            "USER_",
            "COMPANY_",
            "IDENTITY_",
            "ACCOUNT_",
            "PRODUCT_",
            "CLIENT_",
            "COLLECT_",
            "DEPOSITARY_",
            "USSD_",
        ),
    ),
    RoleMetier(
        "Admin",
        "Administration d'une institution : utilisateurs, roles, parametrage",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("USER_", "COMPANY_", "IDENTITY_"),
    ),
    RoleMetier(
        "Marketing",
        "Consultation de la base client et des campagnes",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("CLIENT_", "PRODUCT_"),
    ),
    RoleMetier(
        "Compliance",
        "Controle KYC et conformite reglementaire",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("IDENTITY_", "CLIENT_"),
    ),
    RoleMetier(
        "Collecte",
        "Pilotage des operations de collecte terrain",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("COLLECT_", "DEPOSITARY_"),
    ),
    RoleMetier(
        "Comptable",
        "Consultation des comptes et des mouvements financiers",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("ACCOUNT_",),
    ),
    RoleMetier(
        "Branche",
        "Encadrement d'une unite territoriale",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("DEPOSITARY_", "CLIENT_"),
    ),
    RoleMetier(
        "Employe/IT",
        "Support technique et exploitation",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("USER_",),
    ),
    RoleMetier(
        "Agent",
        "Agent de terrain rattache a un Kiosque",
        TagGroupe.STAFF,
        UserType.STAFF,
        ("COLLECT_", "CLIENT_"),
    ),
    RoleMetier(
        "Marchand",
        "Commercant acceptant les paiements de la plateforme",
        TagGroupe.COMPANY,
        UserType.COMPANY,
        ("ACCOUNT_",),
    ),
    RoleMetier(
        "Kiosque",
        "Point physique de depot et retrait",
        TagGroupe.COMPANY,
        UserType.COMPANY,
        ("COLLECT_", "DEPOSITARY_"),
    ),
    RoleMetier(
        "CUSTOMER",
        "Client final — role deja present en base",
        TagGroupe.CUSTOMER,
        UserType.CUSTOMER,
        (),
        reutilise=True,
    ),
)


@dataclass(slots=True)
class RapportRoles:
    """Ce que l'execution a produit, et ce qu'elle a saute.

    `reutilises` n'est PAS un echec : c'est l'idempotence qui fonctionne.
    """

    mode: RunMode
    crees: list[str] = field(default_factory=list)
    reutilises: list[str] = field(default_factory=list)
    echoues: list[tuple[str, str]] = field(default_factory=list)
    permissions_disponibles: int = 0
    arbitrage_en_attente: bool = True

    @property
    def statut(self) -> RunStatus:
        if not self.echoues:
            return RunStatus.COMPLETED
        if not self.crees and not self.reutilises:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    def resume(self) -> str:
        lignes = [
            f"Mode        : {self.mode.value}",
            f"Roles crees : {len(self.crees)}",
            f"Reutilises  : {len(self.reutilises)} ({', '.join(self.reutilises) or '-'})",
            f"Echecs      : {len(self.echoues)}",
            f"Permissions assignables : {self.permissions_disponibles}",
            f"STATUT : {self.statut.value}",
        ]
        for nom, motif in self.echoues:
            lignes.append(f"  ECHEC {nom} : {motif}")
        if self.arbitrage_en_attente:
            lignes.append(
                "  ⚠ A-05 NON TRANCHE — les permissions par role sont une proposition. "
                "Chaque role porte celles de son domaine ; a corriger sur piece."
            )
        return "\n".join(lignes)


class ExecuteurRoles:
    """Cree les 11 roles manquants, reutilise `CUSTOMER`.

    `DRY_RUN` n'emet aucune ECRITURE mais conserve les LECTURES : sans elles,
    le rapport annoncerait des creations qui n'auraient jamais lieu, puisqu'une
    partie des groupes existe deja.
    """

    def __init__(self, *, mode: RunMode, user_client: UserServiceClient) -> None:
        self.mode = mode
        self._users = user_client

    @property
    def ecriture_reelle(self) -> bool:
        return self.mode is RunMode.REAL

    async def executer(self) -> RapportRoles:
        rapport = RapportRoles(mode=self.mode)

        permissions = await self._users.lister_permissions()
        rapport.permissions_disponibles = len(permissions)

        existants = {
            str(groupe.get("name", "")).strip(): groupe
            for groupe in await self._users.lister_groupes()
        }

        for role in ROLES_METIER:
            if role.nom in existants:
                # Idempotence — ce n'est pas un echec. `CUSTOMER` tombe ici par
                # construction (`D-09`), les autres si un run precedent les a
                # deja crees.
                rapport.reutilises.append(role.nom)
                continue

            if role.reutilise:
                # `CUSTOMER` devrait exister. S'il manque, c'est un fait a
                # signaler, pas a corriger en silence.
                rapport.echoues.append(
                    (role.nom, "role attendu en base mais absent — D-09 suppose sa presence")
                )
                continue

            attribuees = _permissions_du_role(role, permissions)

            if not self.ecriture_reelle:
                rapport.crees.append(f"{role.nom} ({len(attribuees)} permissions)")
                continue

            try:
                await self._users.creer_groupe(
                    nom=role.nom,
                    description=role.description,
                    tag=role.tag,
                    permissions=attribuees,
                    company_id="",
                )
            except Exception as erreur:
                motif = f"{type(erreur).__name__}: {erreur}"[:200]
                logger.warning("role %s en echec : %s", role.nom, motif)
                rapport.echoues.append((role.nom, motif))
                continue

            rapport.crees.append(f"{role.nom} ({len(attribuees)} permissions)")

        return rapport


def _permissions_du_role(role: RoleMetier, disponibles: list[str]) -> list[str]:
    """Les permissions du domaine d'un role — **proposition, pas decision**.

    `A-05` est un arbitrage produit. En attendant, chaque role recoit les
    permissions dont le prefixe correspond a son domaine. Les 22 `LENDER_*` et
    la permission parasite `RC169_*` sont deja ecartees en amont par
    `UserServiceClient.lister_permissions` (`D-07`).
    """
    if not role.prefixes_permissions:
        return []
    return sorted(nom for nom in disponibles if nom.startswith(role.prefixes_permissions))
