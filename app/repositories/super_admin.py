"""
app/repositories/super_admin.py
===============================
Compte Super-Admin **du Loader** — a ne jamais confondre avec le role metier
« Super-Admin » de la plateforme FinZuu, qui vit dans les groupes de
user-service. Le premier pilote notre outil, le second est un role RBAC de
l'ecosysteme. Ils n'ont aucun rapport.

Seule l'empreinte est persistee. Le mot de passe initial n'est jamais ecrit en
base, jamais journalise, jamais renvoye par l'API.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.database import COLLECTION_SUPER_ADMIN_ACCOUNTS
from app.core.security import hacher, verifier
from app.models.domain import SuperAdminAccount
from app.repositories.base import RepositoryBase


class SuperAdminRepository(RepositoryBase):
    collection_name = COLLECTION_SUPER_ADMIN_ACCOUNTS

    async def par_email(self, email: str) -> SuperAdminAccount | None:
        return await self._trouver_un(SuperAdminAccount, {"email": email.strip().lower()})

    async def creer(
        self,
        email: str,
        mot_de_passe_initial: str,
        cree_par: str | None = None,
        role: str = "viewer",
    ) -> SuperAdminAccount:
        """Cree le compte avec `must_change_password=True`.

        Le mot de passe initial (env au bootstrap, genere pour un compte
        cree par l'API) est un mot de passe de premiere connexion, jamais un
        mot de passe durable. `cree_par` trace le createur (RBAC 15/08).

        `role` par defaut = `viewer` (FAIL-CLOSED) : un compte cree sans choix
        explicite n'a que la lecture. Le bootstrap, lui, passe `super_admin`.
        """
        from datetime import UTC, datetime

        compte = SuperAdminAccount(
            id=uuid4(),
            email=email.strip().lower(),
            password_hash=hacher(mot_de_passe_initial),
            must_change_password=True,
            role=role,
            cree_par=cree_par,
            cree_le=datetime.now(tz=UTC).isoformat() if cree_par else None,
        )
        await self._inserer(compte)
        return compte

    async def authentifier(self, email: str, mot_de_passe: str) -> SuperAdminAccount | None:
        """None si inconnu, mot de passe faux OU compte DESACTIVE — le meme
        401 generique pour les trois : rien a enumerer."""
        compte = await self.par_email(email)
        if compte is None or not compte.actif:
            return None
        return compte if verifier(mot_de_passe, compte.password_hash) else None

    # -- Gestion des comptes (RBAC, 15/08) ---------------------------------

    async def lister(self) -> list[SuperAdminAccount]:
        curseur = self.collection.find({}).sort("email", 1)
        return [
            SuperAdminAccount.model_validate(document)
            async for document in curseur
        ]

    async def changer_etat(self, email: str, actif: bool) -> bool:
        resultat = await self.collection.update_one(
            {"email": email.strip().lower()}, {"$set": {"actif": actif}}
        )
        return bool(resultat.matched_count)

    async def compter_actifs(self) -> int:
        return int(await self.collection.count_documents({"actif": {"$ne": False}}))

    async def compter_super_admins_actifs(self) -> int:
        """Comptes ACTIFS de role super_admin — la vraie borne d'anti-lock-out :
        perdre le dernier super_admin fermerait la gestion des acces. Un
        document sans champ `role` compte comme super_admin (defaut du modele),
        d'ou le `$nin` plutot qu'un `== super_admin`."""
        return int(
            await self.collection.count_documents(
                {"actif": {"$ne": False}, "role": {"$nin": ["admin", "viewer"]}}
            )
        )

    async def marquer_connexion(self, email: str) -> None:
        """Horodate la derniere connexion reussie (tracabilite Yaniv 20/08)."""
        from datetime import UTC, datetime

        await self.collection.update_one(
            {"email": email.strip().lower()},
            {"$set": {"derniere_connexion": datetime.now(tz=UTC).isoformat()}},
        )

    async def changer_role(self, email: str, role: str) -> bool:
        resultat = await self.collection.update_one(
            {"email": email.strip().lower()}, {"$set": {"role": role}}
        )
        return bool(resultat.matched_count)

    async def changer_mot_de_passe(self, email: str, nouveau: str) -> bool:
        resultat = await self.collection.update_one(
            {"email": email.strip().lower()},
            {"$set": {"password_hash": hacher(nouveau), "must_change_password": False}},
        )
        return bool(resultat.modified_count)

    async def existe_au_moins_un(self) -> bool:
        return await self._compter() > 0

    # -- Reinitialisation par email (`US-A4` v2) ---------------------------

    async def poser_code_reinitialisation(
        self, email: str, code_hash: str, expire_epoch: float
    ) -> bool:
        """Pose un code (HASH seulement) et remet le compteur d'essais a zero.

        Un nouveau code remplace l'ancien : il n'existe jamais deux codes
        valides en meme temps pour un compte.
        """
        resultat = await self.collection.update_one(
            {"email": email.strip().lower()},
            {
                "$set": {
                    "code_reset_hash": code_hash,
                    "code_reset_expire": expire_epoch,
                    "code_reset_essais": 0,
                }
            },
        )
        return bool(resultat.matched_count)

    async def incrementer_essais_reset(self, email: str) -> None:
        await self.collection.update_one(
            {"email": email.strip().lower()}, {"$inc": {"code_reset_essais": 1}}
        )

    async def effacer_code_reinitialisation(self, email: str) -> None:
        await self.collection.update_one(
            {"email": email.strip().lower()},
            {
                "$set": {
                    "code_reset_hash": None,
                    "code_reset_expire": None,
                    "code_reset_essais": 0,
                }
            },
        )
