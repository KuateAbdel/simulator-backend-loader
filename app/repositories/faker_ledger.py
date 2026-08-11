"""
app/repositories/faker_ledger.py
================================
Registre de consommation Faker — support de **D-FAKER-1**, la discipline la
plus stricte du projet.

    « Une fois qu'un client Faker a ete consomme pour UN usage — Depositaire,
      Lender local, OU CollectClient — ce meme client_id ne doit plus jamais
      etre reutilise pour un autre usage. »

LE DEFAUT CORRIGE LE 11/08 — L'INDEX PROTEGEAIT LE REGISTRE, PAS L'ECOSYSTEME
----------------------------------------------------------------------------
La v1 de ce module affirmait que le garde-fou etait « structurel, pas seulement
applicatif », `_id` etant le `client_id`. C'etait vrai du REGISTRE, et faux de
ce qui compte. `resulting_entity_id` etant obligatoire, l'entree ne pouvait
s'ecrire qu'APRES la creation de l'entite :

    1. tirer chez Faker               -> client_id
    2. `est_consomme(client_id)` ?    -> non
    3. CREER L'ENTITE SUR LE SERVEUR  <- IRREVERSIBLE : ni identity-service, ni
                                         account-service, ni depositary-service
                                         n'exposent de DELETE
    4. `marquer_consomme(...)`        -> False, deja consomme

A l'etape 4 il est trop tard : l'entite existe pour toujours, nee d'un client
Faker deja employe ailleurs. `D-FAKER-1` est viole et rien ne le repare. La
fenetre entre 2 et 4 s'etend sur un appel reseau, avec un plafond de 20 workers
concurrents (`H14`/`H15`) — ce n'est pas une fenetre theorique.

Le module documentait meme le piege : « entre le find_one et l'insert_one, un
autre worker peut passer. C'est `marquer_consomme()` qui tranche. » Le
diagnostic etait juste ; la conclusion s'arretait une etape trop tot.

LA CORRECTION — RESERVATION WRITE-AHEAD
---------------------------------------
    reserver()   AVANT l'appel reseau. `insert_one` atomique : le duplicate
                 tranche, sans aucune lecture prealable. Rendre False n'est pas
                 une erreur, c'est le signal de changer de `seed` (CDC §185).
    confirmer()  APRES la creation. Pose `CONSOMME` et `resulting_entity_id`.
    liberer()    Le client est ecarte pour raison de QUOTA : il n'a rien
                 produit, donc il n'est pas consomme. La reservation dispararait.
    reservations_orphelines()  Une reservation qui survit a la fin du run : le
                 client a ete revendique sans rien produire. Meme role que
                 `intentions_orphelines()` sur le journal d'intention.

C'est le patron write-ahead de `audit_trail` — la seule atomicite dont nous
disposions face a des services sans transaction ni rollback.

CE QUE CE MODULE NE FAIT PAS
----------------------------
Il ne recupere JAMAIS une reservation orpheline de lui-meme. Une orpheline est
le symptome d'un processus mort en cours d'ecriture ; la reclamer en silence
effacerait la trace de l'incident. `reclamer_orphelines()` existe, mais elle est
explicite et elle rend le compte de ce qu'elle a libere — meme philosophie que
`--ignorer-verrou` sur `EF-55`, qui ne contourne pas le verrou mais CLOT le run
bloque, visiblement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pymongo.errors import DuplicateKeyError

from app.core.database import COLLECTION_FAKER_CONSUMPTION_LEDGER
from app.models.domain import FakerConsumptionLedger
from app.models.enums import EtatConsommationFaker, FakerConsumptionType
from app.repositories.base import RepositoryBase, en_document


class ConsommationIncoherente(RuntimeError):
    """Une transition d'etat impossible a atteindre par un chemin correct.

    Confirmer une consommation qui n'a jamais ete reservee, ou la confirmer deux
    fois, signale un defaut de cablage — jamais une condition de course. Le taire
    laisserait une entite irreversible sans trace de son origine Faker.
    """


class FakerLedgerRepository(RepositoryBase):
    collection_name = COLLECTION_FAKER_CONSUMPTION_LEDGER

    # ------------------------------------------------------------------
    # Temps 1 — la reservation, AVANT tout appel reseau
    # ------------------------------------------------------------------

    async def reserver(
        self,
        client_id: str,
        *,
        consumed_for: FakerConsumptionType,
        country_code: str,
        run_id: UUID,
        seed: int | None = None,
    ) -> bool:
        """Revendique un `client_id`. `False` s'il est deja pris.

        **Aucune lecture prealable.** C'est l'`insert_one` qui tranche : un
        `find_one` suivi d'un `insert_one` rouvrirait exactement la fenetre que
        cette methode existe pour fermer.

        `False` n'est pas une erreur — c'est le signal prescrit par le CDC §185 :
        « le Loader change le parametre seed et refait un appel jusqu'a obtenir
        un nouveau client_id unique ».
        """
        entree = FakerConsumptionLedger(
            id=client_id,
            consumed_for=consumed_for,
            country_code=country_code.upper(),
            run_id=run_id,
            state=EtatConsommationFaker.RESERVE,
            reserved_at=datetime.now(UTC),
            seed=seed,
        )
        try:
            await self.collection.insert_one(en_document(entree))
        except DuplicateKeyError:
            return False
        return True

    # ------------------------------------------------------------------
    # Temps 2 — la confirmation, APRES la creation de l'entite
    # ------------------------------------------------------------------

    async def confirmer(self, client_id: str, resulting_entity_id: UUID) -> None:
        """Scelle la consommation : l'entite existe, definitivement.

        La mise a jour est CONDITIONNELLE sur `state == RESERVE`. Si elle ne
        trouve rien, ce n'est pas benin : soit la reservation n'a jamais eu lieu
        — l'entite a donc ete creee hors du registre —, soit elle est deja
        confirmee, et deux entites sont nees du meme client Faker. Les deux cas
        sont des defauts de cablage, et ils doivent crier.
        """
        resultat = await self.collection.update_one(
            {"_id": client_id, "state": EtatConsommationFaker.RESERVE.value},
            {
                "$set": {
                    "state": EtatConsommationFaker.CONSOMME.value,
                    "resulting_entity_id": str(resulting_entity_id),
                    "consumed_at": datetime.now(UTC).isoformat(),
                }
            },
        )
        if resultat.matched_count == 1:
            return

        existant = await self.obtenir(client_id)
        if existant is None:
            raise ConsommationIncoherente(
                f"{client_id} confirme sans avoir ete reserve. L'entite a donc ete "
                "creee AVANT d'entrer au registre — c'est precisement la fenetre que "
                "`reserver()` ferme. Aucun DELETE n'existe pour la reprendre."
            )
        raise ConsommationIncoherente(
            f"{client_id} est deja {existant.state.value} (entite "
            f"{existant.resulting_entity_id}). Une seconde confirmation signifie que "
            "DEUX entites sont nees du meme client Faker : D-FAKER-1 est viole, et "
            "les deux entites sont irreversibles."
        )

    # ------------------------------------------------------------------
    # La liberation — un client ecarte pour quota n'est pas consomme
    # ------------------------------------------------------------------

    async def liberer(self, client_id: str) -> bool:
        """Rend un client revendique mais NON employe.

        Un client ecarte pour raison de quota — mauvais sexe au regard d'`EF-22`,
        mauvaise tranche d'age, categorie deja saturee — n'a rien produit. Il
        n'est donc pas consomme, et le retenir epuiserait le vivier sans rien
        creer : 2000 clients demandes, 2000 tirages perdus.

        La suppression est CONDITIONNELLE sur `RESERVE` : une consommation
        confirmee ne se libere jamais, meme par erreur d'appel.
        """
        resultat = await self.collection.delete_one(
            {"_id": client_id, "state": EtatConsommationFaker.RESERVE.value}
        )
        return resultat.deleted_count == 1

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    async def reservations_orphelines(self, run_id: UUID) -> list[FakerConsumptionLedger]:
        """Les clients revendiques par CE run et qui n'ont rien produit.

        Ce sont elles qui comptent. Une orpheline dit soit qu'un worker est mort
        entre la reservation et la creation, soit qu'un chemin de code oublie de
        confirmer — et dans le second cas une entite irreversible existe sans que
        le registre la relie a son client Faker.
        """
        curseur = self.collection.find(
            {"run_id": str(run_id), "state": EtatConsommationFaker.RESERVE.value}
        ).sort("reserved_at", 1)
        return [FakerConsumptionLedger.model_validate(d) async for d in curseur]

    async def reclamer_orphelines(self, *, plus_vieilles_que: timedelta) -> int:
        """Libere les reservations abandonnees par un run mort. **Explicite.**

        Jamais appelee automatiquement : une orpheline est le symptome d'un
        incident, et la reclamer en silence en effacerait la trace. L'age est
        exige de l'appelant — sans borne, cette methode viderait les reservations
        d'un run concurrent en cours d'execution.
        """
        limite = (datetime.now(UTC) - plus_vieilles_que).isoformat()
        resultat = await self.collection.delete_many(
            {
                "state": EtatConsommationFaker.RESERVE.value,
                "reserved_at": {"$lt": limite},
            }
        )
        return int(resultat.deleted_count)

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    async def est_consomme(self, client_id: str) -> bool:
        """Vrai si le client est deja pris — reserve OU consomme.

        ⚠ **Ce n'est PAS le garde-fou.** Cette methode sert aux journaux et aux
        rapports. Ne jamais l'employer pour decider d'un tirage : entre elle et
        l'ecriture, un autre worker passe. `reserver()` est le seul juge.
        """
        return await self.collection.find_one({"_id": client_id}) is not None

    async def obtenir(self, client_id: str) -> FakerConsumptionLedger | None:
        return await self._trouver_un(FakerConsumptionLedger, {"_id": client_id})

    async def compter_par_usage(self, consumed_for: FakerConsumptionType) -> int:
        """Ne compte que les consommations SCELLEES.

        Une reservation en vol n'est pas une consommation : l'inclure gonflerait
        le rapport de clients qui n'existent peut-etre pas.
        """
        return await self._compter(
            {
                "consumed_for": consumed_for.value,
                "state": EtatConsommationFaker.CONSOMME.value,
            }
        )

    async def total(self) -> int:
        """Total des consommations scellees, tous usages et tous runs confondus."""
        return await self._compter({"state": EtatConsommationFaker.CONSOMME.value})

    async def compter_par_pays(self, run_id: UUID) -> dict[str, int]:
        """Repartition par pays pour CE run — `OBJ-01` exige les 4 pays.

        Le Senegal y apparaitra a zero tant que ses clients viennent du
        generateur interne : Faker rend 422 sur `SN` (arbitrage `A-01`). C'est
        une information, pas une anomalie — et elle doit rester VISIBLE.
        """
        pipeline: list[dict[str, Any]] = [
            {
                "$match": {
                    "run_id": str(run_id),
                    "state": EtatConsommationFaker.CONSOMME.value,
                }
            },
            {"$group": {"_id": "$country_code", "n": {"$sum": 1}}},
        ]
        return {
            str(ligne["_id"]): int(ligne["n"])
            async for ligne in self.collection.aggregate(pipeline)
        }
