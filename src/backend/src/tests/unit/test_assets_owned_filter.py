"""Unit tests for the "owned by me" filter of ``AssetsManager.get_all_assets``.

The filter keeps the assets with an active business-owner assignment for a user,
using the same lookup as ``GET /api/user/ownerships``. It intersects with
``restrict_to_ids`` (the #347 scoping), so it only ever narrows the result.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb

ME = "me@example.com"
OTHER = "other@example.com"


@pytest.fixture
def owned_graph(db_session: Session):
    """Assets A, B, C (owned by ME; C inactive), D (owned by OTHER), E (no owner)."""
    table = AssetTypeDb(name="OwnedFilterTable", category="data")
    db_session.add(table)
    db_session.flush()
    role = BusinessRoleDb(name="OwnedFilterOwner")
    db_session.add(role)
    db_session.flush()

    def mk(name: str, platform: str = "databricks") -> AssetDb:
        a = AssetDb(
            id=uuid.uuid4(), name=name, asset_type_id=table.id, status="active",
            platform=platform, description=f"{name} description",
        )
        db_session.add(a)
        return a

    a, b, c, d, e = mk("A"), mk("B", platform="powerbi"), mk("C"), mk("D"), mk("E")
    db_session.flush()

    def own(asset: AssetDb, email: str, active: bool = True, object_type: str = "asset"):
        db_session.add(BusinessOwnerDb(
            object_type=object_type, object_id=str(asset.id), user_email=email,
            role_id=role.id, is_active=active,
        ))

    own(a, ME)
    own(b, ME)
    own(c, ME, active=False)
    own(d, OTHER)
    # An ownership of another object type with the same id must not count.
    own(e, ME, object_type="data_product")
    db_session.flush()
    return SimpleNamespace(a=a, b=b, c=c, d=d, e=e)


def _ids(result):
    return {item.id for item in result.items}


def test_owner_sees_only_their_active_assets(db_session, owned_graph):
    result = AssetsManager().get_all_assets(db=db_session, owner_email=ME)
    assert _ids(result) == {owned_graph.a.id, owned_graph.b.id}
    assert result.total == 2


def test_total_counts_all_owned_assets_across_pages(db_session, owned_graph):
    mgr = AssetsManager()
    first = mgr.get_all_assets(db=db_session, owner_email=ME, skip=0, limit=1)
    second = mgr.get_all_assets(db=db_session, owner_email=ME, skip=1, limit=1)
    assert first.total == 2 and second.total == 2
    assert len(first.items) == 1 and len(second.items) == 1
    assert _ids(first) | _ids(second) == {owned_graph.a.id, owned_graph.b.id}


def test_summaries_carry_the_description(db_session, owned_graph):
    result = AssetsManager().get_all_assets(db=db_session, owner_email=ME)
    assert {i.description for i in result.items} == {"A description", "B description"}


def test_non_owner_gets_an_empty_page(db_session, owned_graph):
    result = AssetsManager().get_all_assets(db=db_session, owner_email="nobody@example.com")
    assert result.total == 0
    assert result.items == []


def test_empty_email_gets_an_empty_page(db_session, owned_graph):
    result = AssetsManager().get_all_assets(db=db_session, owner_email="")
    assert result.total == 0


def test_combines_with_an_existing_filter(db_session, owned_graph):
    result = AssetsManager().get_all_assets(
        db=db_session, owner_email=ME, platform="powerbi",
    )
    assert _ids(result) == {owned_graph.b.id}
    assert result.total == 1


def test_narrows_restrict_to_ids_never_widens(db_session, owned_graph):
    mgr = AssetsManager()
    # Scoped user who may see A and D: owned filter keeps only A.
    result = mgr.get_all_assets(
        db=db_session, owner_email=ME,
        restrict_to_ids=[owned_graph.a.id, owned_graph.d.id],
    )
    assert _ids(result) == {owned_graph.a.id}
    # Scoped user who may see nothing: still nothing, even though ME owns A and B.
    empty = mgr.get_all_assets(db=db_session, owner_email=ME, restrict_to_ids=[])
    assert empty.total == 0


def test_no_owner_email_keeps_today_behaviour(db_session, owned_graph):
    result = AssetsManager().get_all_assets(db=db_session)
    assert {owned_graph.a.id, owned_graph.d.id, owned_graph.e.id} <= _ids(result)


def test_paging_assets_with_the_same_name_neither_repeats_nor_skips(db_session, owned_graph):
    # The same table name in several catalogs: ``name`` alone doesn't order them.
    table_id = owned_graph.a.asset_type_id
    role = db_session.query(BusinessRoleDb).filter_by(name="OwnedFilterOwner").one()
    twins = [
        AssetDb(id=uuid.uuid4(), name="orders", asset_type_id=table_id, status="active",
                platform="databricks", location=f"cat{i}.sales.orders")
        for i in range(5)
    ]
    db_session.add_all(twins)
    db_session.flush()
    for twin in twins:
        db_session.add(BusinessOwnerDb(
            object_type="asset", object_id=str(twin.id), user_email=OTHER,
            role_id=role.id, is_active=True,
        ))
    db_session.flush()

    mgr = AssetsManager()
    pages = [
        mgr.get_all_assets(db=db_session, owner_email=OTHER, skip=i, limit=1) for i in range(6)
    ]
    seen = [item.id for page in pages for item in page.items]
    assert len(seen) == len(set(seen)) == 6
    assert set(seen) == {owned_graph.d.id, *(t.id for t in twins)}
    # Same name: the id breaks the tie, so every page call agrees on one order.
    twin_ids = [i for i in seen if i != owned_graph.d.id]
    assert twin_ids == sorted(twin_ids, key=str)
