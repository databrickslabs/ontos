"""The Git (Indirect) delivery writes a data product as its ODPS export (#1385).

The file is the document ``GET /data-products/{id}/odps/export`` returns, not wrapped,
so an ODPS import reads it back (the round trip is in
``tests/integration/test_product_git_file_roundtrip.py``).
"""
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml

from src.controller.data_products_manager import DataProductsManager
from src.controller.tags_manager import TagsManager
from src.db_models.data_products import DataProductDb
from src.db_models.delivery_methods import DeliveryMethodDb
from src.file_models.data_products import DataProductFileModel
from src.models.data_products import (
    ONTOS_PORT_ASSET_IDENTIFIER_PROPERTY,
    ONTOS_PORT_ASSET_TYPE_PROPERTY,
    ONTOS_PORT_CONTAINS_PII_PROPERTY,
    ONTOS_PORT_DELIVERY_METHOD_PROPERTY,
)

pytestmark = pytest.mark.usefixtures("seeded_product_types")

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "odps-json-schema-v1.0.0.json"


@pytest.fixture
def manager(db_session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session, ws_client=MagicMock(), notifications_manager=MagicMock(),
        tags_manager=TagsManager(),
    )


def _props(node: dict) -> dict:
    return {cp["property"]: cp["value"] for cp in node.get("customProperties") or []}


def _stored_product(manager, db_session) -> DataProductDb:
    method = DeliveryMethodDb(name=f"share-{uuid.uuid4().hex[:8]}")
    db_session.add(method)
    db_session.flush()
    created = manager.create_product({
        "name": "Orders", "version": "1.0.0", "productType": "source-aligned",
        "description": {"purpose": "Sales orders", "usage": "Reporting"},
        "outputPorts": [{
            "name": "orders", "version": "1.0.0", "contractId": "c-1", "type": "table",
            "deliveryMethodId": str(method.id), "containsPii": True,
            "assetType": "table", "assetIdentifier": "main.sales.orders",
        }],
        "inputPorts": [{
            "name": "raw", "version": "1.0.0", "contractId": "c-0",
            "assetType": "table", "assetIdentifier": "main.raw.orders",
        }],
        "support": [{"channel": "sales", "url": "https://chat/sales", "tool": "slack"}],
    }, db=db_session, user="a@b.com")
    return db_session.get(DataProductDb, created.id)


def test_the_file_is_the_products_odps_export(manager, db_session):
    product = _stored_product(manager, db_session)

    document = DataProductFileModel.to_yaml_dict(product)

    assert document == manager.build_odps_export(product.id, db=db_session)
    assert DataProductFileModel.wrap_as_resource(product, document) is document
    schema = json.loads(SCHEMA_PATH.read_text())
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(document)) == []


def test_the_file_has_the_port_fields_odps_has_no_place_for(manager, db_session):
    product = _stored_product(manager, db_session)

    document = DataProductFileModel.to_yaml_dict(product)

    output = _props(document["outputPorts"][0])
    assert output[ONTOS_PORT_DELIVERY_METHOD_PROPERTY] == str(
        product.output_ports[0].delivery_method_id)
    assert output[ONTOS_PORT_CONTAINS_PII_PROPERTY] is True
    assert output[ONTOS_PORT_ASSET_IDENTIFIER_PROPERTY] == "main.sales.orders"
    assert _props(document["inputPorts"][0]) == {
        ONTOS_PORT_ASSET_TYPE_PROPERTY: "table",
        ONTOS_PORT_ASSET_IDENTIFIER_PROPERTY: "main.raw.orders",
    }
    assert DataProductFileModel.get_filename(product) == "orders-v1-0-0.yaml"


@pytest.fixture
def app_sessions(db_session):
    """The app's session factory, on the test database."""
    from sqlalchemy.orm import sessionmaker
    from src.common import database

    previous = database._SessionLocal
    database.set_session_factory(sessionmaker(bind=db_session.get_bind(), autoflush=False))
    yield
    database.set_session_factory(previous)


def test_a_detached_product_is_serialized_in_a_session_of_its_own(
    manager, db_session, app_sessions,
):
    """A delivery may get the product after its session closed (expired and detached):
    it is read again by its id."""
    product = _stored_product(manager, db_session)
    expected = manager.build_odps_export(product.id, db=db_session)
    db_session.expire(product)
    db_session.expunge(product)

    assert DataProductFileModel.get_filename(product) == "orders-v1-0-0.yaml"
    assert DataProductFileModel.to_yaml_dict(product) == expected


def test_a_product_that_is_not_stored_is_not_serialized():
    with pytest.raises(ValueError):
        DataProductFileModel.to_yaml_dict(DataProductDb(name="Never stored", version="1"))


def test_an_imported_delivery_method_that_does_not_exist_here_is_not_kept(
    manager, db_session,
):
    document = {
        "apiVersion": "v1.0.0", "kind": "DataProduct", "name": "Elsewhere",
        "version": "1.0.0", "status": "draft",
        "outputPorts": [{
            "name": "out", "version": "1.0.0",
            "customProperties": [{
                "property": ONTOS_PORT_DELIVERY_METHOD_PROPERTY, "value": str(uuid.uuid4()),
            }],
        }],
    }

    result = manager.create_products_from_files(
        [("p.yaml", yaml.safe_dump(document).encode())], user="a@b.com",
    )

    assert result.created == 1, result.items
    stored = db_session.get(DataProductDb, result.created_ids[0])
    assert stored.output_ports[0].delivery_method_id is None
