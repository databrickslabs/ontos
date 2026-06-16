"""Unit tests for adapter `get_target` lookups.

These exercise the per-entity lookup path that suggest_inline relies on
when the user opens the concept picker on a persisted entity. The
list_targets path used by bulk runs has its own integration coverage;
get_target is the small, mockable cousin that surfaces edge cases:

* entity_id encoding (the data-contract adapter parses
  contractId#schema#prop tuples).
* sub-entity vs top-level for assets (Column rows resolve to a parent
  via the hasColumn relationship; non-Column rows don't).
* graceful None returns on missing rows.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ============================================================
# AssetAdapter
# ============================================================


def _patch_bulk_parents(parents):
    """Patch the bulk parent resolver to return a fixed dict, avoiding the
    raw-SQL execute path."""
    return patch(
        "src.controller.term_mapping.adapters.asset_adapter._bulk_resolve_parents",
        return_value=parents,
    )


def test_asset_adapter_get_target_returns_none_when_row_missing():
    from src.controller.term_mapping.adapters.asset_adapter import AssetAdapter

    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.first.return_value = None

    adapter = AssetAdapter()
    assert adapter.get_target(db, "nonexistent-id") is None


def test_asset_adapter_get_target_builds_column_with_parent():
    """Column rows are sub-entities — they need a hasColumn parent resolved
    so the suggester can prefer attribute_assignment heuristics."""
    from src.controller.term_mapping.adapters.asset_adapter import AssetAdapter

    asset_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    asset = SimpleNamespace(
        id=asset_id,
        name="customer_email",
        asset_type_id="t1",
        properties={
            "columnDataType": "STRING",
            "isPrimaryKey": False,
            "isForeignKey": True,
            "classification": "pii",
        },
        platform="databricks",
        location="main.customers.customer",
    )
    asset_type = SimpleNamespace(id="t1", name="Column")

    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.first.return_value = (asset, asset_type)

    parents = {asset_id: {"id": parent_id, "name": "customer"}}
    adapter = AssetAdapter()
    with _patch_bulk_parents(parents):
        target = adapter.get_target(db, asset_id)

    assert target is not None
    assert target.entity_type == "asset"
    assert target.entity_id == asset_id
    assert target.name == "customer_email"
    assert target.type_label == "STRING"
    assert target.parent_entity_type == "asset"
    assert target.parent_entity_id == parent_id
    assert target.parent_name == "customer"
    assert target.is_pk is False
    assert target.is_fk is True
    assert target.extras["asset_type_name"] == "Column"
    assert target.extras["classification"] == "pii"


def test_asset_adapter_get_target_table_has_no_parent():
    """Table rows aren't sub-entities — the adapter must NOT pretend there's
    a parent asset, even if _bulk_resolve_parents returned one."""
    from src.controller.term_mapping.adapters.asset_adapter import AssetAdapter

    asset_id = str(uuid.uuid4())
    asset = SimpleNamespace(
        id=asset_id,
        name="customers",
        asset_type_id="t2",
        properties={},
        platform="databricks",
        location="main.customers",
    )
    asset_type = SimpleNamespace(id="t2", name="Table")

    db = MagicMock()
    db.query.return_value.join.return_value.filter.return_value.first.return_value = (asset, asset_type)

    adapter = AssetAdapter()
    with _patch_bulk_parents({}):
        target = adapter.get_target(db, asset_id)

    assert target.parent_entity_type is None
    assert target.parent_entity_id is None
    assert target.parent_name is None


# ============================================================
# ContractAdapter
# ============================================================


def _make_contract_db(contract_id, schemas=()):
    return SimpleNamespace(
        id=contract_id,
        name="Customer Contract",
        version="1.0.0",
        status="active",
        schema_objects=list(schemas),
    )


def _patch_contract_lookup(db, contract):
    """Set up db.query(DataContractDb).filter(...).first() chain."""
    db.query.return_value.filter.return_value.first.return_value = contract


def test_contract_adapter_get_target_returns_none_when_contract_missing():
    from src.controller.term_mapping.adapters.contract_adapter import ContractAdapter

    db = MagicMock()
    _patch_contract_lookup(db, None)
    assert ContractAdapter().get_target(db, str(uuid.uuid4())) is None


def test_contract_adapter_get_target_top_level_contract():
    """One-part entity_id resolves to the contract itself."""
    from src.controller.term_mapping.adapters.contract_adapter import ContractAdapter

    contract_id = str(uuid.uuid4())
    contract = _make_contract_db(contract_id)
    db = MagicMock()
    _patch_contract_lookup(db, contract)

    target = ContractAdapter().get_target(db, contract_id)
    assert target is not None
    assert target.entity_type == "data_contract"
    assert target.entity_id == contract_id
    assert target.name == "Customer Contract"
    assert target.extras["version"] == "1.0.0"
    assert target.extras["status"] == "active"


def test_contract_adapter_get_target_schema_level():
    """Two-part entity_id resolves to a schema object inside the contract."""
    from src.controller.term_mapping.adapters.contract_adapter import ContractAdapter

    contract_id = str(uuid.uuid4())
    schema = SimpleNamespace(
        name="Customer",
        business_name="Customer Master",
        logical_type="object",
        physical_type="table",
        description="Top-level customer record",
        properties=[],
    )
    contract = _make_contract_db(contract_id, schemas=[schema])
    db = MagicMock()
    _patch_contract_lookup(db, contract)

    target = ContractAdapter().get_target(db, f"{contract_id}#Customer")
    assert target.entity_type == "data_contract_schema"
    assert target.entity_id == f"{contract_id}#Customer"
    assert target.label == "Customer Master"
    assert target.type_label == "object"
    assert target.parent_entity_type == "data_contract"
    assert target.parent_entity_id == contract_id
    assert target.parent_name == "Customer Contract"


def test_contract_adapter_get_target_schema_missing_returns_none():
    from src.controller.term_mapping.adapters.contract_adapter import ContractAdapter

    contract_id = str(uuid.uuid4())
    contract = _make_contract_db(contract_id, schemas=[])
    db = MagicMock()
    _patch_contract_lookup(db, contract)
    assert ContractAdapter().get_target(db, f"{contract_id}#Missing") is None


def test_contract_adapter_get_target_property_level():
    """Three-part entity_id resolves to a property within a schema."""
    from src.controller.term_mapping.adapters.contract_adapter import ContractAdapter

    contract_id = str(uuid.uuid4())
    prop = SimpleNamespace(
        name="customer_email",
        business_name="Email",
        logical_type="string",
        physical_type="varchar",
        primary_key=False,
        required=True,
        classification="pii",
        parent_property_id=None,
    )
    schema = SimpleNamespace(
        name="Customer",
        business_name="Customer Master",
        logical_type="object",
        physical_type="table",
        description="",
        properties=[prop],
    )
    contract = _make_contract_db(contract_id, schemas=[schema])
    db = MagicMock()
    _patch_contract_lookup(db, contract)

    target = ContractAdapter().get_target(
        db, f"{contract_id}#Customer#customer_email"
    )
    assert target.entity_type == "data_contract_property"
    assert target.entity_id == f"{contract_id}#Customer#customer_email"
    assert target.name == "customer_email"
    assert target.label == "Email"
    assert target.type_label == "string"
    assert target.parent_entity_type == "data_contract_schema"
    assert target.parent_entity_id == f"{contract_id}#Customer"
    assert target.parent_name == "Customer"
    assert target.is_pk is False
    assert target.extras["classification"] == "pii"
    assert target.extras["required"] is True


def test_contract_adapter_get_target_property_missing_returns_none():
    from src.controller.term_mapping.adapters.contract_adapter import ContractAdapter

    contract_id = str(uuid.uuid4())
    schema = SimpleNamespace(
        name="Customer",
        business_name="Customer Master",
        logical_type="object",
        physical_type="table",
        description="",
        properties=[],
    )
    contract = _make_contract_db(contract_id, schemas=[schema])
    db = MagicMock()
    _patch_contract_lookup(db, contract)

    assert (
        ContractAdapter().get_target(db, f"{contract_id}#Customer#unknown_col") is None
    )


def test_contract_adapter_get_target_skips_nested_properties():
    """Properties with parent_property_id are nested struct fields; the
    top-level encoding `{contract}#{schema}#{name}` should not match them
    by accident."""
    from src.controller.term_mapping.adapters.contract_adapter import ContractAdapter

    contract_id = str(uuid.uuid4())
    nested = SimpleNamespace(
        name="street",
        business_name=None,
        logical_type="string",
        physical_type=None,
        primary_key=False,
        required=False,
        classification=None,
        parent_property_id="some-parent-uuid",
    )
    schema = SimpleNamespace(
        name="Address",
        business_name=None,
        logical_type="object",
        physical_type="struct",
        description="",
        properties=[nested],
    )
    contract = _make_contract_db(contract_id, schemas=[schema])
    db = MagicMock()
    _patch_contract_lookup(db, contract)

    # The nested 'street' field shouldn't be picked up by the top-level
    # 3-part lookup.
    assert (
        ContractAdapter().get_target(db, f"{contract_id}#Address#street") is None
    )


# ============================================================
# ProductAdapter
# ============================================================


def test_product_adapter_get_target_returns_none_when_missing():
    from src.controller.term_mapping.adapters.product_adapter import ProductAdapter

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert ProductAdapter().get_target(db, "nonexistent") is None


def test_product_adapter_get_target_builds_entity():
    from src.controller.term_mapping.adapters.product_adapter import ProductAdapter

    product_id = str(uuid.uuid4())
    product = SimpleNamespace(
        id=product_id,
        name="Customer 360",
        version="2.1.0",
        status="released",
        domain="customer",
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = product

    target = ProductAdapter().get_target(db, product_id)
    assert target is not None
    assert target.entity_type == "data_product"
    assert target.entity_id == product_id
    assert target.name == "Customer 360"
    assert target.extras["version"] == "2.1.0"
    assert target.extras["status"] == "released"
    assert target.extras["domain"] == "customer"


def test_product_adapter_get_target_falls_back_to_id_when_name_missing():
    """A product without a name should still produce a usable label rather
    than crashing — defensive against partial demo data."""
    from src.controller.term_mapping.adapters.product_adapter import ProductAdapter

    product_id = str(uuid.uuid4())
    product = SimpleNamespace(
        id=product_id,
        name=None,
        version=None,
        status=None,
        domain=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = product

    target = ProductAdapter().get_target(db, product_id)
    assert target.name == product_id
    assert target.label == product_id
