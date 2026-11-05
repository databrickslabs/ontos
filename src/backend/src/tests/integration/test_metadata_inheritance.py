"""Metadata inheritance: asset → contract, and contract + asset → product."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.controller.metadata_manager import MetadataManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.db_models.metadata import DocumentMetadataDb, LinkMetadataDb, RichTextMetadataDb


def _note(entity_type, entity_id, title, *, level=50, inheritable=True):
    return RichTextMetadataDb(
        id=uuid4(), entity_type=entity_type, entity_id=str(entity_id), title=title,
        content_markdown=f"# {title}", level=level, inheritable=inheritable,
    )


@pytest.fixture
def manager() -> MetadataManager:
    return MetadataManager()


@pytest.fixture
def stack(db_session):
    """Product with a contract port and a dashboard port; the contract is implemented by a table."""
    s = SimpleNamespace()
    s.product = DataProductDb(id=str(uuid4()), name="Orders Analytics", status="draft", max_level_inheritance=99)
    s.contract = DataContractDb(id=str(uuid4()), name="orders-contract", version="1.0.0", version_family_id=str(uuid4()))
    db_session.add_all([s.product, s.contract])
    db_session.flush()

    table_type = AssetTypeDb(id=uuid4(), name="Table")
    dashboard_type = AssetTypeDb(id=uuid4(), name="Dashboard")
    db_session.add_all([table_type, dashboard_type])
    db_session.flush()

    s.table = AssetDb(id=uuid4(), name="orders", asset_type_id=table_type.id, location="prod.sales.orders")
    s.linked_table = AssetDb(id=uuid4(), name="order_lines", asset_type_id=table_type.id, location="prod.sales.order_lines")
    s.dashboard = AssetDb(
        id=uuid4(), name="Orders Overview", asset_type_id=dashboard_type.id,
        location="https://tableau.example.com/views/OrdersOverview",
    )
    s.unrelated = AssetDb(id=uuid4(), name="customers", asset_type_id=table_type.id, location="prod.crm.customers")
    db_session.add_all([s.table, s.linked_table, s.dashboard, s.unrelated])
    db_session.flush()

    db_session.add_all([
        SchemaObjectDb(
            id=str(uuid4()), contract_id=s.contract.id, name="orders", logical_type="object",
            physical_name="sales.orders",
        ),
        EntityRelationshipDb(
            source_type="Table", source_id=str(s.linked_table.id),
            target_type="DataContract", target_id=s.contract.id, relationship_type="implementsContract",
        ),
        OutputPortDb(
            id=str(uuid4()), product_id=s.product.id, name="orders", version="1.0.0", contract_id=s.contract.id,
        ),
        OutputPortDb(
            id=str(uuid4()), product_id=s.product.id, name="dashboard", version="1.0.0", port_type="dashboard",
            asset_type="dashboard", asset_identifier="https://TABLEAU.example.com/views/OrdersOverview",
        ),
    ])
    db_session.flush()
    return s


def test_contract_sources_are_implementing_assets(manager, db_session, stack):
    sources = manager.resolve_inheritance_sources(db_session, entity_type="data_contract", entity_id=stack.contract.id)
    assert set(sources) == {("asset", str(stack.linked_table.id)), ("asset", str(stack.table.id))}


def test_product_sources_are_port_contracts_and_assets(manager, db_session, stack):
    sources = manager.resolve_inheritance_sources(db_session, entity_type="data_product", entity_id=stack.product.id)
    assert set(sources) == {("data_contract", stack.contract.id), ("asset", str(stack.dashboard.id))}


def test_contract_inherits_inheritable_asset_metadata(manager, db_session, stack):
    shown = _note("asset", stack.table.id, "Table notes")
    hidden = _note("asset", stack.table.id, "Private", inheritable=False)
    other = _note("asset", stack.unrelated.id, "Unrelated")
    db_session.add_all([shown, hidden, other])
    db_session.flush()

    merged = manager.get_merged_metadata(db_session, entity_type="data_contract", entity_id=stack.contract.id)

    assert [rt.title for rt in merged.rich_texts] == ["Table notes"]
    assert merged.sources[str(shown.id)] == f"asset:{stack.table.id}"
    assert merged.source_names[f"asset:{stack.table.id}"] == "orders"


def test_product_inherits_dashboard_snapshot_and_contract_notes(manager, db_session, stack):
    snapshot = DocumentMetadataDb(
        id=uuid4(), entity_type="asset", entity_id=str(stack.dashboard.id), title="Snapshot",
        original_filename="snapshot.png", content_type="image/png", size_bytes=4,
        storage_path="/Volumes/c/s/v/uploads/asset/x/snapshot.png", level=10, inheritable=True,
    )
    preview = _note("asset", stack.dashboard.id, "Dashboard preview", level=10)
    contract_note = _note("data_contract", stack.contract.id, "Contract terms")
    own_link = LinkMetadataDb(
        id=uuid4(), entity_type="data_product", entity_id=stack.product.id, title="Runbook",
        url="https://example.com/runbook",
    )
    db_session.add_all([snapshot, preview, contract_note, own_link])
    db_session.flush()

    merged = manager.get_merged_metadata(db_session, entity_type="data_product", entity_id=stack.product.id)

    assert [d.title for d in merged.documents] == ["Snapshot"]
    assert [rt.title for rt in merged.rich_texts] == ["Dashboard preview", "Contract terms"]
    assert [link.title for link in merged.links] == ["Runbook"]
    assert merged.sources[str(snapshot.id)] == f"asset:{stack.dashboard.id}"
    assert merged.sources[str(contract_note.id)] == f"contract:{stack.contract.id}"
    assert merged.sources[str(own_link.id)] == stack.product.id
    assert merged.source_names == {
        f"asset:{stack.dashboard.id}": "Orders Overview",
        f"contract:{stack.contract.id}": "orders-contract",
    }


def test_product_does_not_inherit_transitively(manager, db_session, stack):
    db_session.add(_note("asset", stack.table.id, "Table notes"))
    db_session.flush()

    merged = manager.get_merged_metadata(db_session, entity_type="data_product", entity_id=stack.product.id)

    assert merged.rich_texts == []


def test_product_max_level_inheritance_is_the_default(manager, db_session, stack):
    stack.product.max_level_inheritance = 20
    db_session.add_all([
        _note("asset", stack.dashboard.id, "Shallow", level=10),
        _note("asset", stack.dashboard.id, "Deep", level=50),
    ])
    db_session.flush()

    merged = manager.get_merged_metadata(db_session, entity_type="data_product", entity_id=stack.product.id)
    assert [rt.title for rt in merged.rich_texts] == ["Shallow"]

    explicit = manager.get_merged_metadata(
        db_session, entity_type="data_product", entity_id=stack.product.id, max_level_inheritance=99,
    )
    assert [rt.title for rt in explicit.rich_texts] == ["Shallow", "Deep"]


def test_explicit_contract_ids_still_inherit(manager, db_session, stack):
    extra = DataContractDb(id=str(uuid4()), name="extra", version="1.0.0", version_family_id=str(uuid4()))
    db_session.add(extra)
    db_session.flush()
    db_session.add(_note("data_contract", extra.id, "Extra terms"))
    db_session.flush()

    merged = manager.get_merged_metadata(
        db_session, entity_type="data_domain", entity_id="d-1", contract_ids=[extra.id],
    )
    assert [rt.title for rt in merged.rich_texts] == ["Extra terms"]
