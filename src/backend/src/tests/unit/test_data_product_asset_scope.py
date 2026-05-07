"""Unit tests for issue #347: Data Consumer asset visibility scoping.

Verifies that:
- Admins see all assets (no restriction).
- Non-admins are restricted to assets linked to Data Products they can access.
- Non-admin with zero accessible DPs sees zero assets.
- Assets linked to multiple DPs are deduped.
- Both DataProduct->asset and OutputPort->asset relationships count.
- The scoping repository filter (``restrict_to_ids``) returns zero rows for an
  empty list (rather than silently ignoring the constraint).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.common.data_product_asset_scope import (
    get_accessible_data_product_ids,
    get_asset_ids_linked_to_products,
    get_output_port_ids_for_products,
    is_asset_accessible,
    resolve_accessible_asset_ids,
)
from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.db_models.entity_relationships import EntityRelationshipDb


# ---------------------------------------------------------------------------
# Fixtures: build a small DP / Asset graph in the in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
def dataset_type(db_session: Session) -> AssetTypeDb:
    at = AssetTypeDb(name="Dataset", category="data")
    db_session.add(at)
    db_session.flush()
    return at


@pytest.fixture
def asset_graph(db_session: Session, dataset_type: AssetTypeDb):
    """Create:
    - DP1 with OutputPort P1
    - DP2 (no port)
    - Assets A, B, C, D
    - DP1 -> hasDataset -> A
    - P1 (port of DP1) -> portHasTable -> B
    - DP2 -> hasDataset -> C
    - DP1 -> hasDataset -> D, DP2 -> hasDataset -> D (shared)
    - Asset E: NOT linked to any DP (orphan).
    """
    # Data Products
    dp1 = DataProductDb(id=str(uuid.uuid4()), name="DP1", version="1.0.0", status="active")
    dp2 = DataProductDb(id=str(uuid.uuid4()), name="DP2", version="1.0.0", status="active")
    db_session.add_all([dp1, dp2])
    db_session.flush()

    # Output port on DP1
    p1 = OutputPortDb(
        id=str(uuid.uuid4()), product_id=dp1.id, name="port1", version="1.0.0",
    )
    db_session.add(p1)
    db_session.flush()

    # Assets
    def mk_asset(name: str) -> AssetDb:
        a = AssetDb(
            id=uuid.uuid4(),
            name=name,
            asset_type_id=dataset_type.id,
            status="active",
        )
        db_session.add(a)
        return a

    a, b, c, d, e = (mk_asset(f"asset_{ch}") for ch in "abcde")
    db_session.flush()

    # Entity relationships (DP -> asset, port -> asset)
    rels = [
        EntityRelationshipDb(
            source_type="DataProduct", source_id=dp1.id,
            target_type="Dataset", target_id=str(a.id),
            relationship_type="hasDataset",
        ),
        EntityRelationshipDb(
            source_type="OutputPort", source_id=p1.id,
            target_type="Table", target_id=str(b.id),
            relationship_type="portHasTable",
        ),
        EntityRelationshipDb(
            source_type="DataProduct", source_id=dp2.id,
            target_type="Dataset", target_id=str(c.id),
            relationship_type="hasDataset",
        ),
        EntityRelationshipDb(
            source_type="DataProduct", source_id=dp1.id,
            target_type="Dataset", target_id=str(d.id),
            relationship_type="hasDataset",
        ),
        EntityRelationshipDb(
            source_type="DataProduct", source_id=dp2.id,
            target_type="Dataset", target_id=str(d.id),
            relationship_type="hasDataset",
        ),
    ]
    db_session.add_all(rels)
    db_session.flush()

    return SimpleNamespace(dp1=dp1, dp2=dp2, p1=p1, a=a, b=b, c=c, d=d, e=e)


def _mock_dpm(accessible_dps: List[DataProductDb]):
    """Stub DataProductsManager.list_products to return given DPs."""
    dpm = MagicMock()
    dpm.list_products.return_value = [
        SimpleNamespace(id=dp.id, name=dp.name) for dp in accessible_dps
    ]
    return dpm


# ---------------------------------------------------------------------------
# Helper-function tests
# ---------------------------------------------------------------------------


def test_get_accessible_dp_ids_admin_returns_none():
    dpm = _mock_dpm([])
    assert get_accessible_data_product_ids(data_products_manager=dpm, is_admin=True) is None
    dpm.list_products.assert_not_called()


def test_get_accessible_dp_ids_non_admin_returns_set(asset_graph):
    dpm = _mock_dpm([asset_graph.dp1, asset_graph.dp2])
    ids = get_accessible_data_product_ids(data_products_manager=dpm, is_admin=False)
    assert ids == {asset_graph.dp1.id, asset_graph.dp2.id}


def test_get_accessible_dp_ids_non_admin_no_dps_empty():
    dpm = _mock_dpm([])
    ids = get_accessible_data_product_ids(data_products_manager=dpm, is_admin=False)
    assert ids == set()


def test_get_output_port_ids(db_session, asset_graph):
    pids = get_output_port_ids_for_products(db_session, product_ids=[asset_graph.dp1.id])
    assert pids == {asset_graph.p1.id}

    # DP2 has no ports.
    assert get_output_port_ids_for_products(db_session, product_ids=[asset_graph.dp2.id]) == set()

    # Empty input → empty output.
    assert get_output_port_ids_for_products(db_session, product_ids=[]) == set()


def test_get_asset_ids_linked_to_products_dp_only(db_session, asset_graph):
    asset_ids = get_asset_ids_linked_to_products(
        db_session, product_ids=[asset_graph.dp1.id], port_ids=set(),
    )
    # DP1 directly links to A and D (not B which is via port).
    assert asset_ids == {asset_graph.a.id, asset_graph.d.id}


def test_get_asset_ids_linked_to_products_with_ports(db_session, asset_graph):
    asset_ids = get_asset_ids_linked_to_products(
        db_session,
        product_ids=[asset_graph.dp1.id],
        port_ids=[asset_graph.p1.id],
    )
    # DP1 -> A, D ; port P1 -> B.
    assert asset_ids == {asset_graph.a.id, asset_graph.b.id, asset_graph.d.id}


def test_get_asset_ids_dedup_multi_dp(db_session, asset_graph):
    asset_ids = get_asset_ids_linked_to_products(
        db_session,
        product_ids=[asset_graph.dp1.id, asset_graph.dp2.id],
        port_ids=set(),
    )
    # D is linked from both DP1 and DP2 — should appear once.
    assert asset_ids == {asset_graph.a.id, asset_graph.c.id, asset_graph.d.id}


def test_get_asset_ids_no_input_empty(db_session):
    assert get_asset_ids_linked_to_products(db_session, product_ids=[], port_ids=[]) == set()


def test_resolve_accessible_asset_ids_admin_none(db_session, asset_graph):
    dpm = _mock_dpm([])
    result = resolve_accessible_asset_ids(db_session, data_products_manager=dpm, is_admin=True)
    assert result is None  # "no restriction"


def test_resolve_accessible_asset_ids_non_admin_dp1_only(db_session, asset_graph):
    dpm = _mock_dpm([asset_graph.dp1])
    result = resolve_accessible_asset_ids(db_session, data_products_manager=dpm, is_admin=False)
    # DP1 -> A, D (direct) + port P1 -> B.
    assert set(result) == {asset_graph.a.id, asset_graph.b.id, asset_graph.d.id}


def test_resolve_accessible_asset_ids_non_admin_no_dps_empty(db_session):
    dpm = _mock_dpm([])
    result = resolve_accessible_asset_ids(db_session, data_products_manager=dpm, is_admin=False)
    assert result == []  # empty list, not None


def test_is_asset_accessible_admin_always_true(db_session, asset_graph):
    dpm = _mock_dpm([])
    # Admin: even an unreachable / unknown asset should pass.
    assert is_asset_accessible(
        db_session, asset_id=uuid.uuid4(),
        data_products_manager=dpm, is_admin=True,
    ) is True


def test_is_asset_accessible_non_admin_linked(db_session, asset_graph):
    dpm = _mock_dpm([asset_graph.dp1])
    assert is_asset_accessible(
        db_session, asset_id=asset_graph.a.id,
        data_products_manager=dpm, is_admin=False,
    ) is True


def test_is_asset_accessible_non_admin_unlinked_blocked(db_session, asset_graph):
    dpm = _mock_dpm([asset_graph.dp1])
    # asset_e is orphan; not linked to any DP.
    assert is_asset_accessible(
        db_session, asset_id=asset_graph.e.id,
        data_products_manager=dpm, is_admin=False,
    ) is False


def test_is_asset_accessible_non_admin_via_other_dp_blocked(db_session, asset_graph):
    # User has access to DP1 only; asset C is linked only to DP2.
    dpm = _mock_dpm([asset_graph.dp1])
    assert is_asset_accessible(
        db_session, asset_id=asset_graph.c.id,
        data_products_manager=dpm, is_admin=False,
    ) is False


# ---------------------------------------------------------------------------
# AssetsManager-level tests for restrict_to_ids plumbing
# ---------------------------------------------------------------------------


def test_assets_manager_restrict_to_ids_filters_results(db_session, asset_graph):
    mgr = AssetsManager()
    # Restrict to A only.
    result = mgr.get_all_assets(
        db=db_session, restrict_to_ids=[asset_graph.a.id],
    )
    assert result.total == 1
    assert {item.id for item in result.items} == {asset_graph.a.id}


def test_assets_manager_restrict_to_ids_empty_returns_zero(db_session, asset_graph):
    """Empty list must mean zero results (not 'no restriction')."""
    mgr = AssetsManager()
    result = mgr.get_all_assets(db=db_session, restrict_to_ids=[])
    assert result.total == 0
    assert result.items == []


def test_assets_manager_restrict_to_ids_none_unrestricted(db_session, asset_graph):
    """None means 'no restriction' — admin path."""
    mgr = AssetsManager()
    result = mgr.get_all_assets(db=db_session, restrict_to_ids=None)
    # All 5 assets we created.
    assert result.total >= 5
