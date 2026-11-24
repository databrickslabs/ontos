"""The Git (Indirect) delivery serializes a stored product (#1385).

``to_yaml_dict`` read ``entity.descriptions``, ``entity.tags`` and other
attributes ``DataProductDb`` doesn't have, so every Git delivery of a product failed.
"""
import uuid

from src.db_models.data_products import (
    DataProductDb, DescriptionDb, InputPortDb, OutputPortDb, SupportDb,
)
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.file_models.data_products import DataProductFileModel


def _product(db_session) -> DataProductDb:
    product = DataProductDb(
        id=str(uuid.uuid4()), name="Orders", version="1.0.0", status="draft",
        description=DescriptionDb(purpose="Sales orders", usage="Reporting"),
        output_ports=[OutputPortDb(
            name="orders", version="1.0.0", contract_id="c-1", port_type="table",
            asset_type="table", asset_identifier="main.sales.orders",
        )],
        input_ports=[InputPortDb(name="raw", version="1.0.0", contract_id="c-0")],
        support_channels=[SupportDb(channel="sales", url="https://chat/sales", tool="slack")],
    )
    namespace = TagNamespaceDb(name="default")
    db_session.add_all([product, namespace])
    db_session.flush()
    tag = TagDb(name="gold", namespace_id=namespace.id)
    db_session.add(tag)
    db_session.flush()
    db_session.add(EntityTagAssociationDb(
        tag_id=tag.id, entity_id=product.id, entity_type="data_product",
    ))
    db_session.flush()
    return product


def test_a_stored_product_is_serialized_with_its_real_fields(db_session):
    product = _product(db_session)

    result = DataProductFileModel.to_yaml_dict(product)

    assert result["name"] == "Orders"
    assert result["description"] == {"purpose": "Sales orders", "usage": "Reporting"}
    assert result["tags"] == ["default/gold"]
    assert result["outputPorts"] == [{
        "name": "orders", "version": "1.0.0", "type": "table", "contractId": "c-1",
        "assetType": "table", "assetIdentifier": "main.sales.orders",
    }]
    assert result["inputPorts"] == [{"name": "raw", "version": "1.0.0", "contractId": "c-0"}]
    assert result["supportChannels"] == [
        {"channel": "sales", "url": "https://chat/sales", "tool": "slack"}
    ]


def test_a_product_without_optional_parts_is_serialized(db_session):
    product = DataProductDb(id=str(uuid.uuid4()), name="Bare", version="0.1", status="draft")
    db_session.add(product)
    db_session.flush()

    assert DataProductFileModel.to_yaml_dict(product) == {
        "name": "Bare", "version": "0.1", "status": "draft",
    }


def test_a_product_is_wrapped_and_named_for_delivery(db_session):
    product = _product(db_session)

    assert DataProductFileModel.get_filename(product) == "orders-v1-0-0.yaml"
    assert DataProductFileModel.wrap_as_resource(
        product, DataProductFileModel.to_yaml_dict(product))
