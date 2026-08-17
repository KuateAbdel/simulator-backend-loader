"""US-D1 EDITABLE (17/08) — le dirigeant compose est AJUSTABLE dans l'apercu,
mais la fusion reste tenue par les invariants : tout peut changer SAUF ce qu'un
invariant fige. Ces tests prouvent les deux faces : une edition coherente est
appliquee, une edition qui viole un invariant est REFUSEE (InvariantViole), que
la route traduit en 422 lisible.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from app.core.invariants import InvariantViole
from app.services.generateur import Generateur
from app.services.geographie import charger_referentiel
from app.services.organisation_execution import ExecuteurOrganisation, OwnerChoisi
from app.services.referentiel_statique import charger_statique

REFERENTIEL = charger_referentiel(Path("docs/reference/Loader_Base_FinZuu_v1_1.xlsx"))
STATIQUE = charger_statique()
REFERENCE = date(2026, 8, 17)
#: run_id FIXE — le dirigeant compose (donc son id_expire_on, tire sur l'alea du
#: run) doit etre REPRODUCTIBLE, sinon le test devient flaky d'un CI a l'autre.
RUN = UUID("11111111-2222-3333-4444-555555555555")


def _owner() -> Any:
    """Un dirigeant compose, coherent, comme le Loader le produit."""
    return Generateur(RUN, reference=REFERENCE).identite(
        first_name="Salif",
        last_name="Tamadou",
        gender="MALE",
        country_code="CM",
        ville="Douala",
        region="Littoral",
        quartier="Bepanda",
        telephone="+237650000001",
        jeune=False,
        ancre_client="dirigeant:test",
        occupation="Directeur general",
        referentiel=REFERENTIEL,
        statique=STATIQUE,
    )


def _fusion(owner: Any, choix: OwnerChoisi) -> Any:
    """`_fusion_owner` ne touche que `self._generateur.reference` — un stub
    porteur du generateur suffit a l'exercer sans monter tout l'executeur."""
    gen = Generateur(RUN, reference=REFERENCE)
    stub = SimpleNamespace(_generateur=gen)
    return ExecuteurOrganisation._fusion_owner(stub, owner, choix)  # type: ignore[arg-type]


class TestOwnerOverrideSousInvariants:
    def test_une_edition_coherente_est_APPLIQUEE(self) -> None:
        """Prenom, email, naissance majeure, piece future : tout est repris."""
        owner = _owner()
        fusionne = _fusion(
            owner,
            OwnerChoisi(
                first_name="Awa",
                last_name="Diallo",
                email="awa.diallo@example.cm",
                gender="FEMALE",
                date_of_birth=date(1990, 5, 4),
                id_expire_on=date(2030, 1, 1),
            ),
        )
        assert fusionne.first_name == "Awa"
        assert fusionne.last_name == "Diallo"
        assert fusionne.email == "awa.diallo@example.cm"
        assert fusionne.gender == "FEMALE"
        assert fusionne.date_of_birth == date(1990, 5, 4)
        assert fusionne.id_expire_on == date(2030, 1, 1)

    def test_un_champ_absent_GARDE_le_compose(self) -> None:
        """`None` ne remplace rien — le dirigeant compose reste la reference."""
        owner = _owner()
        fusionne = _fusion(owner, OwnerChoisi(first_name="Awa"))
        assert fusionne.first_name == "Awa"
        assert fusionne.last_name == owner.last_name
        assert fusionne.email == owner.email
        assert fusionne.id_number == owner.id_number

    def test_id_number_est_normalise_en_MAJUSCULES(self) -> None:
        """FRA-228 — le Loader se conforme a la contrainte annoncee non appliquee."""
        owner = _owner()
        fusionne = _fusion(owner, OwnerChoisi(id_number="cm12345x"))
        assert fusionne.id_number == "CM12345X"

    def test_piece_EXPIREE_est_REFUSEE(self) -> None:
        """Une piece perimee ne passe pas — invariant FRA-200/D-CLI-2."""
        owner = _owner()
        with pytest.raises(InvariantViole):
            _fusion(owner, OwnerChoisi(id_expire_on=date(2020, 1, 1)))

    def test_un_dirigeant_MINEUR_est_REFUSE(self) -> None:
        """Majorite exigee — le serveur accepte 2 ans, pas nous."""
        owner = _owner()
        with pytest.raises(InvariantViole):
            _fusion(owner, OwnerChoisi(date_of_birth=date(2015, 1, 1)))

    def test_id_number_non_alphanumerique_est_REFUSE(self) -> None:
        """Un id_number avec des caracteres interdits est rejete."""
        owner = _owner()
        with pytest.raises(InvariantViole):
            _fusion(owner, OwnerChoisi(id_number="AB-12-#!"))
