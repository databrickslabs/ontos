"""#1614: a consumer reads the tables, views and columns under a product's datasets.

The asset read rule counted only assets a readable product (or its output
port) links directly. The product page also shows the tables and views of
its datasets and their columns, and opening one answered 403 ("Asset is not
linked to a Data Product accessible to this user"). The rule now follows
the same tree as the hierarchy (product -> hasDataset -> hasTable / hasView ->
hasColumn), and nothing else: a schema an output port links shows no tree on
the page, so its tables stay denied.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller.assets_manager import assets_manager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_products import DataProductDb, OutputPortDb
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
    ``replacedBy`` table R (not containment). P's output port links schema S,
    S hasTable ST hasColumn SC (schema import writes these; the page shows none).
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
    d, t, c, v, dq, tq, o, r, sch, st, sc = (
        asset(n) for n in ("D", "T", "C", "V", "DQ", "TQ", "O", "R", "S", "ST", "SC")
    )
    port = OutputPortDb(id=str(uuid.uuid4()), product_id=p.id, name="port", version="1.0.0")
    db_session.add(port)
    db_session.flush()
    db_session.add_all([
        _rel("DataProduct", p.id, "hasDataset", "Dataset", d.id),
        _rel("Dataset", d.id, "hasTable", "Table", t.id),
        _rel("Table", t.id, "hasColumn", "Column", c.id),
        _rel("Dataset", d.id, "hasView", "View", v.id),
        _rel("Table", t.id, "replacedBy", "Table", r.id),
        _rel("DataProduct", q.id, "hasDataset", "Dataset", dq.id),
        _rel("Dataset", dq.id, "hasTable", "Table", tq.id),
        _rel("OutputPort", port.id, "portHasSchema", "Schema", sch.id),
        _rel("Schema", sch.id, "hasTable", "Table", st.id),
        _rel("Table", st.id, "hasColumn", "Column", sc.id),
    ])
    db_session.flush()
    return SimpleNamespace(
        p=p, q=q, d=d, t=t, c=c, v=v, dq=dq, tq=tq, o=o, r=r, port=port, sch=sch, st=st, sc=sc,
    )


def _dpm(products):
    dpm = MagicMock()
    dpm.list_products.return_value = [
        SimpleNamespace(id=x.id, name=x.name, status=x.status) for x in products
    ]

    def _linked(db, *, product_ids, port_ids=None):
        from src.repositories.data_products_repository import data_product_repo

        pids = list(product_ids)
        return entity_relationship_repo.get_asset_ids_linked_to_products(
            db, product_ids=pids,
            port_ids=data_product_repo.get_output_port_ids_for_products(db, product_ids=pids),
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


def test_schema_an_output_port_links_is_readable_but_not_its_tables(db_session, tree):
    # The port links S directly (unchanged rule); the page shows no tree under it
    assert _readable(db_session, tree, tree.sch) is True
    assert _readable(db_session, tree, tree.st) is False
    assert _readable(db_session, tree, tree.sc) is False


def test_product_tree_ids_match_the_hierarchy(db_session, tree):
    ids = entity_relationship_repo.get_product_tree_asset_ids(
        db_session, product_ids=[tree.p.id],
    )
    assert ids == {tree.d.id, tree.t.id, tree.v.id, tree.c.id}


def test_listing_uses_the_same_set(db_session, tree):
    ids = set(assets_manager.resolve_accessible_asset_ids(
        db_session, data_products_manager=_dpm([tree.p, tree.q]), is_admin=False,
    ))
    assert ids == {tree.d.id, tree.t.id, tree.v.id, tree.c.id, tree.sch.id}
