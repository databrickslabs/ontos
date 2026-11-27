"""Contracts and products from Tableau content (#1312 slice 4).

A contract inferred from a Semantic Model carries field captions, formulas and
the UC columns each field reads; a product created from that contract can
deliver the dashboards built on the model as dashboard output ports.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from uuid import uuid4

from sqlalchemy.orm.attributes import flag_modified

from src.controller.assets_manager import AssetsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.model_lineage import ModelLineageResolver
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.tests.unit.test_tableau_import import (  # noqa: F401 (fixtures)
    DS_PATH,
    WB_PATH,
    _asset,
    _fresh_cache,
    _import,
    asset_types,
    osm,
    uc_orders,
)


def _infer(db):
    _import(db, WB_PATH, DS_PATH)
    [schema] = AssetsManager().infer_schema_from_asset(db, _asset(db, DS_PATH).id)
    return schema


def test_semantic_model_infers_a_schema_with_formulas_and_uc_sources(db_session, asset_types, uc_orders):
    schema = _infer(db_session)

    assert (schema["name"], schema["physicalName"], schema["physicalType"]) == ("TPCH Orders", DS_PATH, "semantic model")
    props = {p["name"]: p for p in schema["properties"]}
    price, key, aov = props["Total Price"], props["Order Key"], props["Avg Order Value"]

    assert price["businessName"] == "Total Price" and price["description"] == "Order total"
    assert (price["physicalType"], price["logicalType"], price["physicalName"]) == ("REAL", "number", "o_totalprice")
    assert price["transformSourceObjects"] == ["samples.tpch.orders.o_totalprice"]
    assert "transformLogic" not in price
    assert key["logicalType"] == "integer"

    assert aov["transformLogic"] == "SUM([Total Price]) / COUNTD([Order Key])"
    assert aov["transformSourceObjects"] == ["samples.tpch.orders.o_totalprice", "samples.tpch.orders.o_orderkey"]
    assert "physicalName" not in aov


def test_field_reference_cycles_terminate(db_session, asset_types, uc_orders):
    _import(db_session, DS_PATH)
    price = _asset(db_session, f"{DS_PATH}.Total Price")
    price.properties = {**price.properties, "referenced_fields": ["Avg Order Value"]}
    flag_modified(price, "properties")
    db_session.flush()

    [schema] = AssetsManager().infer_schema_from_asset(db_session, _asset(db_session, DS_PATH).id)
    props = {p["name"]: p for p in schema["properties"]}
    assert set(props["Total Price"]["transformSourceObjects"]) == {
        "samples.tpch.orders.o_totalprice", "samples.tpch.orders.o_orderkey",
    }


def _product_with_port(db, location):
    product = DataProductDb(id=str(uuid4()), name="Orders Analytics", status="draft")
    db.add(product)
    db.flush()
    port = OutputPortDb(id=str(uuid4()), product_id=product.id, name="dashboard", version="1.0.0",
                        port_type="dashboard", asset_type="dashboard", asset_identifier=location)
    db.add(port)
    db.flush()
    return port


def test_lineage_links_a_port_to_the_dashboard_it_delivers(db_session, asset_types, uc_orders):
    _import(db_session, WB_PATH, DS_PATH)
    dashboard = _asset(db_session, f"{WB_PATH}.v~v1")
    port = _product_with_port(db_session, dashboard.location)

    links = ModelLineageResolver().neighbors(db_session, "OutputPort", port.id)
    assert ("Dashboard", str(dashboard.id)) in {(link.target_type, link.target_id) for link in links}


def _contract_on_model(db):
    contract = DataContractDb(id=str(uuid4()), name="TPCH Orders", version="1.0.0", status="active")
    db.add(contract)
    db.flush()
    db.add(SchemaObjectDb(id=str(uuid4()), contract_id=contract.id, name="TPCH Orders", physical_name=DS_PATH))
    db.flush()
    return contract


def test_contract_dashboards_are_the_views_reading_its_semantic_model(db_session, asset_types, uc_orders):
    _import(db_session, WB_PATH, DS_PATH)
    contract = _contract_on_model(db_session)

    dashboards = DataProductsManager(db=db_session).contract_dashboards(contract.id)
    assert [d.location for d in dashboards] == [f"{WB_PATH}.v~v1", f"{WB_PATH}.v~v2"]


def test_product_from_contract_adds_dashboard_ports_and_description(db_session, asset_types, uc_orders):
    _import(db_session, WB_PATH, DS_PATH)
    contract = _contract_on_model(db_session)

    product = DataProductsManager(db=db_session).create_from_contract(
        contract_id=contract.id, product_name="Orders Analytics", version="1.0.0", include_dashboards=True,
    )

    ports = {p.name: p for p in product.outputPorts}
    assert ports["TPCH Orders"].contractId == contract.id
    overview = ports["Orders Overview"]
    assert (overview.type, overview.assetType, overview.assetIdentifier) == ("dashboard", "dashboard", f"{WB_PATH}.v~v1")
    assert overview.server.location.endswith("/views/OrdersOverview/OrdersOverview")
    assert "Revenue by Status" in ports
    assert "Orders Overview, Revenue by Status" in product.description.purpose
    assert "/views/OrdersOverview/OrdersOverview" in product.description.usage


def test_product_from_contract_without_the_option_has_only_the_contract_port(db_session, asset_types, uc_orders):
    _import(db_session, WB_PATH, DS_PATH)
    contract = _contract_on_model(db_session)

    product = DataProductsManager(db=db_session).create_from_contract(
        contract_id=contract.id, product_name="Orders Analytics", version="1.0.0",
    )
    assert [p.name for p in product.outputPorts] == ["TPCH Orders"]
