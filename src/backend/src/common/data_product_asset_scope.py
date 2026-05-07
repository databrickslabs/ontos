"""Helpers for scoping asset visibility to Data Products a user can access.

Issue #347: Data Consumers should see assets that are linked to Data Products
they can access — not all assets, and not zero assets when the ``assets``
feature flag is off.

Two responsibilities live here:

1. Resolve the set of Data Product (and OutputPort) IDs a given user can
   currently access. This deliberately reuses the same listing logic as
   ``GET /api/data-products`` so there is one source of truth.
2. Given a set of accessible DP/Port IDs, resolve the set of asset UUIDs
   linked to them via ``entity_relationships`` (DP -> asset, OutputPort ->
   asset).

Producers and Consumers are both non-admin and both go through this
restriction. Admins are exempt (caller is responsible for short-circuiting
when ``is_admin`` is True).
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.entity_relationships import EntityRelationshipDb

logger = get_logger(__name__)

# Source-side entity types whose outgoing relationships link to assets.
# DataProduct -> hasDataset / hasTable / ... ; OutputPort -> portHasTable / ...
_DP_SOURCE_TYPES = ("DataProduct", "OutputPort")


def _to_uuid(value: object) -> Optional[UUID]:
    """Best-effort conversion of an entity_relationship target_id to UUID.

    Returns None when the target_id is not UUID-shaped (asset IDs always are,
    but some legacy rows may store synthetic IDs)."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def get_accessible_data_product_ids(
    *,
    data_products_manager,
    is_admin: bool,
) -> Optional[Set[str]]:
    """Return the set of DP IDs accessible to the current user.

    Returns ``None`` to indicate "no restriction" — when the caller is admin.
    Returns an empty set when the user has zero accessible DPs (e.g. a fresh
    Consumer with no subscriptions and no project membership).
    """
    if is_admin:
        return None
    try:
        # ``list_products`` already applies project-membership/admin filters.
        products = data_products_manager.list_products(
            skip=0, limit=10_000, is_admin=False,
        )
    except Exception:
        logger.exception("Failed to list accessible data products for scoping")
        return set()

    return {str(p.id) for p in products if getattr(p, "id", None)}


def get_output_port_ids_for_products(
    db: Session, *, product_ids: Iterable[str]
) -> Set[str]:
    """Return the set of OutputPort IDs belonging to the given DataProducts."""
    pids = list(product_ids)
    if not pids:
        return set()
    try:
        from src.db_models.data_products import OutputPortDb
        rows = (
            db.query(OutputPortDb.id)
            .filter(OutputPortDb.product_id.in_(pids))
            .all()
        )
        return {str(r[0]) for r in rows}
    except Exception:
        logger.exception("Failed to fetch output port IDs for product scoping")
        return set()


def get_asset_ids_linked_to_products(
    db: Session,
    *,
    product_ids: Iterable[str],
    port_ids: Optional[Iterable[str]] = None,
) -> Set[UUID]:
    """Return the set of asset UUIDs linked to the given DPs / OutputPorts via
    ``entity_relationships``.

    Considers outgoing relationships where source is DataProduct/OutputPort.
    Asset-tier target IDs are stored as UUIDs (string form) in target_id.
    """
    pid_list = [str(p) for p in product_ids]
    port_list = [str(p) for p in (port_ids or [])]
    if not pid_list and not port_list:
        return set()

    try:
        clauses = []
        if pid_list:
            clauses.append(
                (EntityRelationshipDb.source_type == "DataProduct")
                & EntityRelationshipDb.source_id.in_(pid_list)
            )
        if port_list:
            clauses.append(
                (EntityRelationshipDb.source_type == "OutputPort")
                & EntityRelationshipDb.source_id.in_(port_list)
            )

        rows = (
            db.query(EntityRelationshipDb.target_id)
            .filter(or_(*clauses))
            .all()
        )
        result: Set[UUID] = set()
        for (target_id,) in rows:
            uid = _to_uuid(target_id)
            if uid is not None:
                result.add(uid)
        return result
    except Exception:
        logger.exception("Failed to resolve DP-linked asset IDs")
        return set()


def resolve_accessible_asset_ids(
    db: Session,
    *,
    data_products_manager,
    is_admin: bool,
) -> Optional[List[UUID]]:
    """High-level entry point. Returns:

    - ``None`` when no restriction should apply (admin user). Callers must
      treat this as "return all assets, unfiltered."
    - A (possibly empty) list of asset UUIDs the user is allowed to see
      (Producers + Consumers).
    """
    dp_ids = get_accessible_data_product_ids(
        data_products_manager=data_products_manager,
        is_admin=is_admin,
    )
    if dp_ids is None:
        return None
    if not dp_ids:
        return []
    port_ids = get_output_port_ids_for_products(db, product_ids=dp_ids)
    asset_ids = get_asset_ids_linked_to_products(
        db, product_ids=dp_ids, port_ids=port_ids
    )
    return list(asset_ids)


def is_asset_accessible(
    db: Session,
    *,
    asset_id: UUID,
    data_products_manager,
    is_admin: bool,
) -> bool:
    """Single-asset variant for the ``GET /api/assets/{id}`` path.

    Admins always pass. Non-admins pass iff the asset is linked to at least one
    accessible DP/OutputPort.
    """
    if is_admin:
        return True
    accessible_ids = resolve_accessible_asset_ids(
        db, data_products_manager=data_products_manager, is_admin=False,
    )
    if accessible_ids is None:
        return True
    return asset_id in set(accessible_ids)
