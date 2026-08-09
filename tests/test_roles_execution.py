"""Les 11 roles de D-09 — Sprint 2, story S2-02.

Le 12e role metier, « Client », EST le groupe CUSTOMER deja en base. On ne le
recree pas : 11 a creer, 1 reutilise.

C'est la SEULE ecriture entierement reversible du Loader — `DELETE /groupes/{id}`
existe, rare dans un ecosysteme ou trois services n'exposent aucune suppression.
"""

from __future__ import annotations

from typing import Any

from app.clients.contracts import TagGroupe, UserType
from app.models.enums import RunMode, RunStatus
from app.services.roles_execution import (
    ROLES_METIER,
    ExecuteurRoles,
    _permissions_du_role,
)

PERMISSIONS = [
    "ACCOUNT_ACCOUNT_CREATE",
    "CLIENT_CLIENT_ONBOARD",
    "COLLECT_COLLECT_CREATE",
    "COMPANY_COMPANY_CREATE",
    "DEPOSITARY_DEPOSITARY_CREATE",
    "IDENTITY_IDENTITY_CREATE",
    "PRODUCT_PRODUCT_CREATE",
    "USER_USER_CREATE",
    "USSD_MENU_READ",
]


class UserClientDouble:
    """Doublure : quatre groupes en base, comme mesure le 09/08."""

    def __init__(self, groupes: list[str] | None = None) -> None:
        self.ecritures: list[dict[str, Any]] = []
        self._groupes = groupes if groupes is not None else ["ROOT", "COMPANY", "CUSTOMER", "GUEST"]

    async def lister_permissions(self) -> list[str]:
        return list(PERMISSIONS)

    async def lister_groupes(self) -> list[dict[str, Any]]:
        return [{"name": nom} for nom in self._groupes]

    async def creer_groupe(self, **kwargs: Any) -> dict[str, Any]:
        self.ecritures.append(kwargs)
        return {"_id": "x", "name": kwargs["nom"]}


class UserClientDefaillant(UserClientDouble):
    async def creer_groupe(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("HTTP 400 groupe refuse")


class TestCatalogueDesRoles:
    def test_douze_roles_dont_un_reutilise(self) -> None:
        assert len(ROLES_METIER) == 12
        assert sum(1 for r in ROLES_METIER if r.reutilise) == 1

    def test_le_role_reutilise_est_customer(self) -> None:
        reutilise = next(r for r in ROLES_METIER if r.reutilise)
        assert reutilise.nom == "CUSTOMER"
        assert reutilise.type_user is UserType.CUSTOMER

    def test_aucun_role_n_emet_le_tag_root(self) -> None:
        """`ROOT` est persiste en base mais absent de l'enumeration (A4). Le
        Super-Admin prend donc tag STAFF."""
        assert all(
            r.tag in (TagGroupe.STAFF, TagGroupe.COMPANY, TagGroupe.CUSTOMER) for r in ROLES_METIER
        )
        super_admin = next(r for r in ROLES_METIER if r.nom == "Super-Admin")
        assert super_admin.tag is TagGroupe.STAFF
        assert super_admin.type_user is UserType.ROOT

    def test_aucun_role_ne_porte_le_usertype_guest(self) -> None:
        """Consequence assumee de D-09 : le groupe GUEST reste inutilise."""
        assert UserType.GUEST not in {r.type_user for r in ROLES_METIER}

    def test_les_onze_a_creer_ont_une_description(self) -> None:
        """`description` est REQUISE au contrat."""
        assert all(r.description.strip() for r in ROLES_METIER)


class TestPermissionsParRole:
    def test_le_comptable_ne_recoit_que_le_domaine_compte(self) -> None:
        role = next(r for r in ROLES_METIER if r.nom == "Comptable")
        assert _permissions_du_role(role, PERMISSIONS) == ["ACCOUNT_ACCOUNT_CREATE"]

    def test_le_super_admin_recoit_tous_les_domaines(self) -> None:
        role = next(r for r in ROLES_METIER if r.nom == "Super-Admin")
        assert len(_permissions_du_role(role, PERMISSIONS)) == len(PERMISSIONS)

    def test_customer_ne_recoit_rien_puisqu_il_est_reutilise(self) -> None:
        role = next(r for r in ROLES_METIER if r.reutilise)
        assert _permissions_du_role(role, PERMISSIONS) == []


class TestExecution:
    async def test_dry_run_n_ecrit_rien_mais_annonce(self) -> None:
        double = UserClientDouble()
        rapport = await ExecuteurRoles(mode=RunMode.DRY_RUN, user_client=double).executer()

        assert double.ecritures == []
        assert len(rapport.crees) == 11, "les 11 roles metier — seul CUSTOMER preexiste"
        assert rapport.reutilises == ["CUSTOMER"]
        assert rapport.statut is RunStatus.COMPLETED

    async def test_customer_est_reutilise_jamais_recree(self) -> None:
        double = UserClientDouble()
        rapport = await ExecuteurRoles(mode=RunMode.REAL, user_client=double).executer()

        assert "CUSTOMER" in rapport.reutilises
        assert all(e["nom"] != "CUSTOMER" for e in double.ecritures)

    async def test_l_idempotence_reutilise_ce_qui_existe_deja(self) -> None:
        """Un second run ne recree rien — ce n'est pas un echec."""
        double = UserClientDouble(groupes=[r.nom for r in ROLES_METIER])
        rapport = await ExecuteurRoles(mode=RunMode.REAL, user_client=double).executer()

        assert double.ecritures == []
        assert len(rapport.reutilises) == 12
        assert rapport.statut is RunStatus.COMPLETED

    async def test_les_roles_portent_company_id_vide(self) -> None:
        """Role GLOBAL — jamais duplique par Company (D-06)."""
        double = UserClientDouble()
        await ExecuteurRoles(mode=RunMode.REAL, user_client=double).executer()
        assert all(e["company_id"] == "" for e in double.ecritures)

    async def test_un_echec_journalise_et_poursuit(self) -> None:
        double = UserClientDefaillant()
        rapport = await ExecuteurRoles(mode=RunMode.REAL, user_client=double).executer()

        assert rapport.statut is RunStatus.FAILED, "aucun role cree"
        assert len(rapport.echoues) == 11
        assert all(len(motif) <= 200 for _, motif in rapport.echoues)

    async def test_customer_absent_est_signale_pas_cree(self) -> None:
        """D-09 suppose sa presence. S'il manque, c'est un fait a signaler."""
        double = UserClientDouble(groupes=["ROOT", "GUEST"])
        rapport = await ExecuteurRoles(mode=RunMode.REAL, user_client=double).executer()

        assert any(nom == "CUSTOMER" for nom, _ in rapport.echoues)
        assert all(e["nom"] != "CUSTOMER" for e in double.ecritures)

    async def test_le_rapport_signale_l_arbitrage_a05(self) -> None:
        double = UserClientDouble()
        rapport = await ExecuteurRoles(mode=RunMode.DRY_RUN, user_client=double).executer()
        assert "A-05" in rapport.resume()
