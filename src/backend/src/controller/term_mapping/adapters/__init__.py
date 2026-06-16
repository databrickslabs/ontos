"""Target adapters: translate Ontos entity types into a uniform feature shape.

Each adapter knows how to list candidate target entities from the DB (filtered
by the run's RunTargetFilter) and how to derive the parent/child relationships
the engine needs for entity-vs-attribute distinction.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Protocol, TYPE_CHECKING

from sqlalchemy.orm import Session

from src.models.term_mappings import RunTargetFilter

from ..types import TargetEntity


class TargetAdapter(Protocol):
    """Each entity-type-family has one adapter implementation."""

    entity_types: List[str]   # e.g. ["asset"] or ["data_contract_schema", "data_contract_property"]

    def list_targets(self, db: Session, filters: RunTargetFilter) -> Iterable[TargetEntity]:
        ...

    def get_target(self, db: Session, entity_id: str) -> Optional[TargetEntity]:
        """Single-entity lookup used by the inline suggester. ``entity_id``
        follows the same encoding as ``list_targets`` emits (e.g.
        ``{contract_id}#{schema}#{prop}`` for contract properties)."""
        ...


from .asset_adapter import AssetAdapter  # noqa: E402
from .contract_adapter import ContractAdapter  # noqa: E402
from .product_adapter import ProductAdapter  # noqa: E402


def all_adapters() -> List[TargetAdapter]:
    """Adapter registry; new target families plug in here."""
    return [AssetAdapter(), ContractAdapter(), ProductAdapter()]
