"""Business lineage across the model stack: concept → product → contract schema → physical asset."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from rdflib import Graph

from src.controller.entity_relationships_manager import EntityRelationshipsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb, SchemaPropertyDb
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.db_models.semantic_links import EntitySemanticLinkDb

ONTOLOGY = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"
CONCEPT_IRI = "http://demo.ontos.app/concepts#Customer"


@pytest.fixture(scope="module")
def manager() -> EntityRelationshipsManager:
    g = Graph()
    g.parse(ONTOLOGY)
    osm = SimpleNamespace(_graph=g, get_entity_type=lambda _iri: None)
    return EntityRelationshipsManager(osm)  # type: ignore[arg-type]


@pytest.fixture
def stack(db_session):
    """Product → port → contract → schema object/property → table/column, plus concept links."""
    s = SimpleNamespace()
    s.product = DataProductDb(id=str(uuid4()), name="Customer 360", status="active")
    s.contract = DataContractDb(
        id=str(uuid4()), name="customer-contract", version="1.0.0", version_family_id=str(uuid4()),
    )
    db_session.add_all([s.product, s.contract])
    db_session.flush()

    s.port = OutputPortDb(
        id=str(uuid4()), product_id=s.product.id, name="customers", version="1.0.0", contract_id=s.contract.id,
    )
    s.schema = SchemaObjectDb(
        id=str(uuid4()), contract_id=s.contract.id, name="customers", logical_type="object",
        physical_name="crm.customers",
    )
    db_session.add_all([s.port, s.schema])
    db_session.flush()
    s.prop = SchemaPropertyDb(id=str(uuid4()), object_id=s.schema.id, name="customer_id", logical_type="string")

    table_type = AssetTypeDb(id=uuid4(), name="Table")
    column_type = AssetTypeDb(id=uuid4(), name="Column")
    db_session.add_all([s.prop, table_type, column_type])
    db_session.flush()

    s.table = AssetDb(id=uuid4(), name="customers", asset_type_id=table_type.id, location="prod.crm.customers")
    s.other_table = AssetDb(id=uuid4(), name="x", asset_type_id=table_type.id, location="prod.crm.not_customers")
    s.column = AssetDb(id=uuid4(), name="customer_id", asset_type_id=column_type.id)
    db_session.add_all([s.table, s.other_table, s.column])
    db_session.flush()

    db_session.add_all([
        EntityRelationshipDb(
            source_type="Table", source_id=str(s.table.id),
            target_type="Column", target_id=str(s.column.id), relationship_type="hasColumn",
        ),
        EntitySemanticLinkDb(entity_type="data_product", entity_id=s.product.id, iri=CONCEPT_IRI, label="Customer"),
        EntitySemanticLinkDb(
            entity_type="data_contract_property", entity_id=f"{s.contract.id}#customers#customer_id",
            iri=CONCEPT_IRI, label="Customer",
        ),
        # Dangling relationship to an entity that does not exist
        EntityRelationshipDb(
            source_type="DataProduct", source_id=s.product.id,
            target_type="Dataset", target_id=str(uuid4()), relationship_type="hasDataset",
        ),
    ])
    db_session.flush()
    return s


def _keys(graph):
    return {n.id for n in graph.nodes}


def _edges(graph):
    return {(e.source, e.target, e.relationship_type) for e in graph.edges}


def test_contract_lineage_spans_all_layers(manager, db_session, stack):
    graph = manager.get_business_lineage(db_session, "DataContract", stack.contract.id, max_depth=2)

    nodes = {n.id: n for n in graph.nodes}
    schema_key = f"SchemaObject:{stack.schema.id}"
    prop_key = f"SchemaProperty:{stack.prop.id}"
    table_key = f"Table:{stack.table.id}"
    column_key = f"Column:{stack.column.id}"
    concept_key = f"Concept:{CONCEPT_IRI}"

    for key in (schema_key, prop_key, table_key, column_key, concept_key, f"OutputPort:{stack.port.id}"):
        assert key in nodes, key
    assert f"Table:{stack.other_table.id}" not in nodes  # suffix match respects '.' boundaries

    edges = _edges(graph)
    assert (schema_key, table_key, "implementedBy") in edges
    assert (prop_key, column_key, "implementedBy") in edges
    assert (concept_key, prop_key, "describes") in edges

    assert nodes[concept_key].layer == "business"
    assert nodes[f"DataContract:{stack.contract.id}"].layer == "logical"
    assert nodes[schema_key].layer == "logical"
    assert nodes[table_key].layer == "physical"
    assert nodes[f"OutputPort:{stack.port.id}"].context_id == stack.product.id
    assert nodes[schema_key].context_id == stack.contract.id
    assert all(e.derived for e in graph.edges if e.relationship_type != "hasColumn")


def test_table_lineage_walks_back_to_business(manager, db_session, stack):
    graph = manager.get_business_lineage(
        db_session, "Table", str(stack.table.id), max_depth=3, direction="upstream",
    )
    keys = _keys(graph)
    assert f"SchemaObject:{stack.schema.id}" in keys
    assert f"DataContract:{stack.contract.id}" in keys
    assert f"Concept:{CONCEPT_IRI}" in keys


def test_no_edges_to_unresolvable_nodes(manager, db_session, stack):
    graph = manager.get_business_lineage(db_session, "DataProduct", stack.product.id, max_depth=3)
    keys = _keys(graph)
    for e in graph.edges:
        assert e.source in keys and e.target in keys, e
    assert next(n for n in graph.nodes if n.is_center).layer == "delivery"


def test_legacy_logical_assets_hidden(manager, db_session, stack):
    attr_type = AssetTypeDb(id=uuid4(), name="LogicalAttribute")
    db_session.add(attr_type)
    db_session.flush()
    attr = AssetDb(id=uuid4(), name="Customer.Id", asset_type_id=attr_type.id)
    db_session.add(attr)
    db_session.flush()
    db_session.add(EntityRelationshipDb(
        source_type="LogicalAttribute", source_id=str(attr.id),
        target_type="Column", target_id=str(stack.column.id), relationship_type="implementedBy",
    ))
    db_session.flush()

    graph = manager.get_business_lineage(db_session, "Column", str(stack.column.id), max_depth=2)
    assert f"LogicalAttribute:{attr.id}" not in _keys(graph)

    # ...but its own lineage still works
    graph = manager.get_business_lineage(db_session, "LogicalAttribute", str(attr.id), max_depth=1)
    assert f"Column:{stack.column.id}" in _keys(graph)


def _add_product(db_session, name):
    dp = DataProductDb(id=str(uuid4()), name=name, status="active")
    db_session.add(dp)
    db_session.flush()
    return dp


def test_direction_follows_flow_not_stored_edge(manager, db_session, stack):
    """dependsOn points consumer → provider: the provider is upstream."""
    provider = _add_product(db_session, "Provider")
    consumer = _add_product(db_session, "Consumer")
    db_session.add_all([
        EntityRelationshipDb(source_type="DataProduct", source_id=stack.product.id,
                             target_type="DataProduct", target_id=provider.id, relationship_type="dependsOn"),
        EntityRelationshipDb(source_type="DataProduct", source_id=consumer.id,
                             target_type="DataProduct", target_id=stack.product.id, relationship_type="dependsOn"),
    ])
    db_session.flush()

    up = _keys(manager.get_business_lineage(db_session, "DataProduct", stack.product.id, 2, "upstream"))
    down = _keys(manager.get_business_lineage(db_session, "DataProduct", stack.product.id, 2, "downstream"))

    assert f"DataProduct:{provider.id}" in up and f"DataProduct:{provider.id}" not in down
    assert f"DataProduct:{consumer.id}" in down and f"DataProduct:{consumer.id}" not in up
    assert f"Concept:{CONCEPT_IRI}" in up and f"Concept:{CONCEPT_IRI}" not in down
    assert f"DataContract:{stack.contract.id}" in down and f"DataContract:{stack.contract.id}" not in up

    edge = next(e for e in manager.get_business_lineage(db_session, "DataProduct", stack.product.id, 1).edges
                if e.relationship_type == "dependsOn" and e.target == f"DataProduct:{provider.id}")
    assert edge.reversed


def test_both_is_union_of_chains_without_siblings(manager, db_session, stack):
    """A sibling product sharing the concept must not appear — it is neither up- nor downstream."""
    sibling = _add_product(db_session, "Sibling")
    db_session.add(EntitySemanticLinkDb(entity_type="data_product", entity_id=sibling.id, iri=CONCEPT_IRI, label="Customer"))
    db_session.flush()

    both = _keys(manager.get_business_lineage(db_session, "DataProduct", stack.product.id, 3))
    assert f"Concept:{CONCEPT_IRI}" in both
    assert f"Table:{stack.table.id}" in both
    assert f"DataProduct:{sibling.id}" not in both


def test_skipped_layer_is_filled(manager, db_session, stack):
    """Product → Dataset skips Logical; the Dataset's governing contract fills the gap (as a leaf)."""
    ds_type = AssetTypeDb(id=uuid4(), name="Dataset")
    db_session.add(ds_type)
    db_session.flush()
    ds = AssetDb(id=uuid4(), name="ds", asset_type_id=ds_type.id)
    other = DataContractDb(id=str(uuid4()), name="other", version="1", version_family_id=str(uuid4()))
    db_session.add_all([ds, other])
    db_session.flush()
    db_session.add_all([
        EntityRelationshipDb(source_type="DataProduct", source_id=stack.product.id,
                             target_type="Dataset", target_id=str(ds.id), relationship_type="hasDataset"),
        EntityRelationshipDb(source_type="Dataset", source_id=str(ds.id),
                             target_type="DataContract", target_id=other.id, relationship_type="governedBy"),
    ])
    db_session.flush()

    graph = manager.get_business_lineage(db_session, "DataProduct", stack.product.id, 2, "downstream")
    keys = _keys(graph)
    assert f"Dataset:{ds.id}" in keys
    assert f"DataContract:{other.id}" in keys
    # leaf: its schema is not expanded from the gap-fill
    assert not any(e.source == f"DataContract:{other.id}" for e in graph.edges)


def test_gap_filled_schema_nests_in_its_contract(manager, db_session, stack):
    """Reached only as a gap-fill (Product → Dataset ⊃ Table ← SchemaObject), the schema
    object still gets its contract and containment edge, so it renders as a row."""
    ds_type = AssetTypeDb(id=uuid4(), name="Dataset")
    db_session.add(ds_type)
    db_session.flush()
    ds = AssetDb(id=uuid4(), name="ds", asset_type_id=ds_type.id)
    other_product = _add_product(db_session, "Other")
    db_session.add(ds)
    db_session.flush()
    db_session.add_all([
        EntityRelationshipDb(source_type="DataProduct", source_id=other_product.id,
                             target_type="Dataset", target_id=str(ds.id), relationship_type="hasDataset"),
        EntityRelationshipDb(source_type="Dataset", source_id=str(ds.id),
                             target_type="Table", target_id=str(stack.table.id), relationship_type="hasTable"),
    ])
    db_session.flush()

    graph = manager.get_business_lineage(db_session, "DataProduct", other_product.id, 3, "downstream")
    edges = _edges(graph)
    schema_key = f"SchemaObject:{stack.schema.id}"
    assert schema_key in _keys(graph)
    assert (f"DataContract:{stack.contract.id}", schema_key, "hasSchemaObject") in edges


def test_concept_centered_lineage_resolves_semantic_keys(manager, db_session, stack):
    db_session.add_all([
        EntitySemanticLinkDb(entity_type="data_contract_schema", entity_id=f"{stack.contract.id}#customers",
                             iri=CONCEPT_IRI, label="Customer"),
        EntitySemanticLinkDb(entity_type="asset", entity_id=str(stack.table.id), iri=CONCEPT_IRI, label="Customer"),
        EntitySemanticLinkDb(entity_type="uc_table", entity_id="prod.crm.customers", iri=CONCEPT_IRI, label="Customer"),
    ])
    db_session.flush()

    graph = manager.get_business_lineage(db_session, "Concept", CONCEPT_IRI, 1, "downstream")
    keys = _keys(graph)
    assert f"DataProduct:{stack.product.id}" in keys
    assert f"SchemaObject:{stack.schema.id}" in keys
    assert f"SchemaProperty:{stack.prop.id}" in keys
    assert f"Table:{stack.table.id}" in keys
    assert not any("prod.crm.customers" in k for k in keys)  # raw uc_* links are not nodes


def test_concept_fanout_is_capped(manager, db_session, stack):
    from src.controller.model_lineage import MAX_CONCEPT_FANOUT
    iri = "http://demo.ontos.app/concepts#Popular"
    for i in range(MAX_CONCEPT_FANOUT + 5):
        dp = _add_product(db_session, f"p{i}")
        db_session.add(EntitySemanticLinkDb(entity_type="data_product", entity_id=dp.id, iri=iri, label="Popular"))
    db_session.flush()

    graph = manager.get_business_lineage(db_session, "Concept", iri, 1, "downstream")
    assert sum(1 for e in graph.edges if e.relationship_type == "describes") <= MAX_CONCEPT_FANOUT


def test_port_binds_to_asset_by_identifier(manager, db_session, stack):
    stack.port.asset_identifier = "prod.crm.customers"
    db_session.flush()

    down = manager.get_business_lineage(db_session, "DataProduct", stack.product.id, 1, "downstream")
    assert (f"OutputPort:{stack.port.id}", f"Table:{stack.table.id}", "portHasAsset") in _edges(down)

    up = manager.get_business_lineage(db_session, "Table", str(stack.table.id), 1, "upstream")
    assert f"OutputPort:{stack.port.id}" in _keys(up)


def test_column_lineage_walks_to_property(manager, db_session, stack):
    graph = manager.get_business_lineage(db_session, "Column", str(stack.column.id), 2, "upstream")
    prop_key = f"SchemaProperty:{stack.prop.id}"
    assert prop_key in _keys(graph)
    assert (prop_key, f"Column:{stack.column.id}", "implementedBy") in _edges(graph)


def test_containment_does_not_pull_in_siblings(manager, db_session, stack):
    """Column → (up) Table must not walk back down to the table's other columns."""
    col_type_id = stack.column.asset_type_id
    sibling = AssetDb(id=uuid4(), name="email", asset_type_id=col_type_id)
    db_session.add(sibling)
    db_session.flush()
    db_session.add(EntityRelationshipDb(
        source_type="Table", source_id=str(stack.table.id),
        target_type="Column", target_id=str(sibling.id), relationship_type="hasColumn",
    ))
    db_session.flush()

    graph = manager.get_business_lineage(db_session, "Column", str(stack.column.id), 3)
    keys = _keys(graph)
    assert f"Table:{stack.table.id}" in keys
    assert f"Column:{sibling.id}" not in keys

    # From the table itself, its columns are contents, not siblings
    assert f"Column:{sibling.id}" in _keys(manager.get_business_lineage(db_session, "Table", str(stack.table.id), 1))


def test_walk_stops_at_node_budget(manager, db_session, stack, monkeypatch):
    import src.controller.entity_relationships_manager as erm
    monkeypatch.setattr(erm, "MAX_LINEAGE_NODES", 3)

    graph = manager.get_business_lineage(db_session, "DataContract", stack.contract.id, 3)
    assert graph.truncated
    assert len(graph.nodes) <= 3 + 3  # budget, plus containers of gap-fill leaves
    keys = _keys(graph)
    for e in graph.edges:
        assert e.source in keys and e.target in keys
