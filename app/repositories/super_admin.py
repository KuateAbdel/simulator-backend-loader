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

    async def creer(self, email: str, mot_de_passe_initial: str) -> SuperAdminAccount:
        """Cree le compte avec `must_change_password=True`.

        Le mot de passe fourni par variable d'environnement est un mot de passe
        de premiere connexion, jamais un mot de passe durable.
        """
        compte = SuperAdminAccount(
            id=uuid4(),
            email=email.strip().lower(),
            password_hash=hacher(mot_de_passe_initial),
            must_change_password=True,
        )
        await self._inserer(compte)
        return compte

    async def authentifier(self, email: str, mot_de_passe: str) -> SuperAdminAccount | None:
        compte = await self.par_email(email)
        if compte is None:
            return None
        return compte if verifier(mot_de_passe, compte.password_hash) else None

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
