"""#1614: a consumer reads the tables, views and columns under a product's datasets.

The asset read rule counted only assets a readable product (or its output
port) links directly. The product page also shows the tables and views of
its datasets and their columns, and opening one answered 403 ("Asset is not
linked to a Data Product accessible to this user"). The rule now follows
the same tree (hasTable / hasView, then hasColumn), and nothing else.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller.assets_manager import assets_manager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_products import DataProductDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.repositories.entity_relationships_repository import entity_relationship_repo


def _rel(src_type, src_id, rel, tgt_type, tgt_id):
    return EntityRelationshipDb(
        source_type=src_type, source_id=str(src_id), relationship_type=rel,
        target_type=tgt_type, target_id=str(tgt_id),
    )


@pytest.fixture
def tree(db_session):
    """active product P -> dataset D -> table T -> column C; D -> view V.

    Draft product Q -> dataset DQ -> table TQ. Orphan table O. Table T also
    ``replacedBy`` table R (not containment).
    """
    at = AssetTypeDb(name="Table", category="data")
    db_session.add(at)
    db_session.flush()

    def asset(name):
        a = AssetDb(id=uuid.uuid4(), name=name, asset_type_id=at.id, status="active")
        db_session.add(a)
        return a

    p = DataProductDb(id=str(uuid.uuid4()), name="P", version="1.0.0", status="active")
    q = DataProductDb(id=str(uuid.uuid4()), name="Q", version="1.0.0", status="draft")
    db_session.add_all([p, q])
    d, t, c, v, dq, tq, o, r = (asset(n) for n in ("D", "T", "C", "V", "DQ", "TQ", "O", "R"))
    db_session.flush()
    db_session.add_all([
        _rel("DataProduct", p.id, "hasDataset", "Dataset", d.id),
        _rel("Dataset", d.id, "hasTable", "Table", t.id),
        _rel("Table", t.id, "hasColumn", "Column", c.id),
        _rel("Dataset", d.id, "hasView", "View", v.id),
        _rel("Table", t.id, "replacedBy", "Table", r.id),
        _rel("DataProduct", q.id, "hasDataset", "Dataset", dq.id),
        _rel("Dataset", dq.id, "hasTable", "Table", tq.id),
    ])
    db_session.flush()
    return SimpleNamespace(p=p, q=q, d=d, t=t, c=c, v=v, dq=dq, tq=tq, o=o, r=r)


def _dpm(products):
    dpm = MagicMock()
    dpm.list_products.return_value = [
        SimpleNamespace(id=x.id, name=x.name, status=x.status) for x in products
    ]

    def _linked(db, *, product_ids, port_ids=None):
        return entity_relationship_repo.get_asset_ids_linked_to_products(
            db, product_ids=list(product_ids), port_ids=[],
        )

    dpm.list_linked_asset_ids_for_products.side_effect = _linked
    return dpm


def _readable(db, tree, asset):
    return assets_manager.is_asset_accessible(
        db, asset_id=asset.id, data_products_manager=_dpm([tree.p, tree.q]),
        is_admin=False,
    )


def test_table_of_a_linked_dataset_is_readable(db_session, tree):
    assert _readable(db_session, tree, tree.t) is True


def test_view_of_a_linked_dataset_is_readable(db_session, tree):
    assert _readable(db_session, tree, tree.v) is True


def test_column_of_a_contained_table_is_readable(db_session, tree):
    assert _readable(db_session, tree, tree.c) is True


def test_dataset_itself_still_readable(db_session, tree):
    assert _readable(db_session, tree, tree.d) is True


def test_table_under_a_draft_product_stays_denied(db_session, tree):
    # Q is a draft: not consumer-visible, so neither is its tree
    assert _readable(db_session, tree, tree.tq) is False


def test_non_containment_link_is_not_followed(db_session, tree):
    assert _readable(db_session, tree, tree.r) is False


def test_orphan_table_stays_denied(db_session, tree):
    assert _readable(db_session, tree, tree.o) is False


def test_contained_ids_respects_depth(db_session, tree):
    one_hop = entity_relationship_repo.get_contained_asset_ids(
        db_session, parent_ids=[tree.d.id],
        relationship_types=("hasTable", "hasView", "hasColumn"), max_depth=1,
    )
    assert one_hop == {tree.t.id, tree.v.id}
