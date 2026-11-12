"""The "below the first maturity level" filter of ``AssetsManager.get_all_assets``.

It keeps the assets whose latest maturity snapshot reached no level while asset
levels exist. Assets never evaluated are left out (their level is unknown). It
intersects with the other filters, so it only ever narrows the result.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.maturity import MaturitySnapshotDb
from src.repositories.maturity_repository import maturity_repo

ME = "me@example.com"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _snap(db, asset, order, *, minutes_ago=0, total_levels=4, entity_type="Asset"):
    db.add(MaturitySnapshotDb(
        entity_type=entity_type, entity_id=str(asset.id), achieved_level_order=order,
        achieved_level_name=None if order is None else f"L{order}",
        total_levels=total_levels, evaluated_at=NOW - timedelta(minutes=minutes_ago),
    ))


@pytest.fixture
def graph(db_session: Session):
    """below (latest: no level), raised (was below, now L1), dropped (was L1, now below),
    leveled (L2), never (no snapshot), product_snap (a DataProduct snapshot with the id),
    other_owner (below, owned by someone else)."""
    table = AssetTypeDb(name="BelowFirstTable", category="data")
    role = BusinessRoleDb(name="BelowFirstOwner")
    db_session.add_all([table, role])
    db_session.flush()
    names = ["below", "raised", "dropped", "leveled", "never", "product_snap", "other_owner"]
    rows = {}
    for name in names:
        rows[name] = AssetDb(id=uuid.uuid4(), name=name, asset_type_id=table.id,
                             status="active", platform="databricks")
    db_session.add_all(rows.values())
    db_session.flush()
    for name in names:
        db_session.add(BusinessOwnerDb(
            object_type="asset", object_id=str(rows[name].id),
            user_email="other@example.com" if name == "other_owner" else ME,
            role_id=role.id, is_active=True,
        ))
    maturity_repo.create(db_session, name="Prerequisite", level_order=1, entity_type="Asset")
    _snap(db_session, rows["below"], None)
    _snap(db_session, rows["raised"], None, minutes_ago=10)
    _snap(db_session, rows["raised"], 1)
    _snap(db_session, rows["dropped"], 1, minutes_ago=10)
    _snap(db_session, rows["dropped"], None)
    _snap(db_session, rows["leveled"], 2)
    _snap(db_session, rows["product_snap"], None, entity_type="DataProduct")
    _snap(db_session, rows["other_owner"], None)
    db_session.flush()
    return SimpleNamespace(**rows)


def _names(result):
    return {item.name for item in result.items}


def test_keeps_the_assets_whose_latest_snapshot_has_no_level(db_session, graph):
    result = AssetsManager().get_all_assets(
        db=db_session, owner_email=ME, below_first_maturity_level=True,
    )
    assert _names(result) == {"below", "dropped"}
    assert result.total == 2


def test_without_the_owner_filter_it_keeps_every_asset_below(db_session, graph):
    result = AssetsManager().get_all_assets(db=db_session, below_first_maturity_level=True)
    assert _names(result) == {"below", "dropped", "other_owner"}


def test_narrows_restrict_to_ids(db_session, graph):
    result = AssetsManager().get_all_assets(
        db=db_session, below_first_maturity_level=True,
        restrict_to_ids=[graph.below.id, graph.leveled.id],
    )
    assert _names(result) == {"below"}


def test_no_asset_levels_means_no_asset_is_below(db_session, graph):
    for level in maturity_repo.get_all_ordered(db_session, entity_type="Asset"):
        maturity_repo.delete(db_session, db_obj=level)
    db_session.flush()
    result = AssetsManager().get_all_assets(db=db_session, below_first_maturity_level=True)
    assert result.total == 0


def test_a_snapshot_taken_without_levels_does_not_count(db_session, graph):
    _snap(db_session, graph.leveled, None, minutes_ago=-5, total_levels=0)
    db_session.flush()
    result = AssetsManager().get_all_assets(
        db=db_session, owner_email=ME, below_first_maturity_level=True,
    )
    assert "leveled" not in _names(result)


def test_flag_off_keeps_today_behaviour(db_session, graph):
    result = AssetsManager().get_all_assets(db=db_session, owner_email=ME)
    assert {"never", "leveled", "below"} <= _names(result)
