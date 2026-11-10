"""Regression tests: output/management port ``type`` survives a product update.

``DataProductUpdate`` is dumped with ``model_dump(exclude_unset=True, by_alias=True)``,
which names the port type key ``port_type`` (the model alias). ``update()`` used to read
only ``type``, so every save that carried ports reset the output port Type to NULL and
every management port Type to ``rest``.
"""
import uuid
from unittest.mock import MagicMock

from src.db_models.data_products import DataProductDb, ManagementPortDb, OutputPortDb
from src.models.data_products import DataProductUpdate
from src.repositories.data_products_repository import data_product_repo


def _product(port_type="table", mgmt_type="topic"):
    product = DataProductDb(id=str(uuid.uuid4()), name="P", version="1.0.0", status="draft")
    port = OutputPortDb(id=str(uuid.uuid4()), name="out", version="1.0.0", port_type=port_type)
    product.output_ports.append(port)
    product.management_ports.append(
        ManagementPortDb(name="m", content="discoverability", port_type=mgmt_type))
    return product, port


def _update(product, payload):
    model = DataProductUpdate(**{"id": product.id, **payload})
    data_product_repo.update(db=MagicMock(), db_obj=product, obj_in=model)


def test_update_with_existing_output_port_keeps_type():
    product, port = _product()
    _update(product, {"output_ports": [
        {"id": port.id, "name": "out", "version": "1.0.0", "type": "table"}]})
    assert product.output_ports[0].port_type == "table"


def test_update_changes_existing_output_port_type():
    product, port = _product()
    _update(product, {"output_ports": [
        {"id": port.id, "name": "out", "version": "1.0.0", "type": "api"}]})
    assert product.output_ports[0].port_type == "api"


def test_update_new_output_port_keeps_type():
    product, _ = _product()
    _update(product, {"output_ports": [{"name": "new", "version": "1.0.0", "type": "stream"}]})
    assert [p.port_type for p in product.output_ports] == ["stream"]


def test_update_accepts_port_type_key_in_dict_payload():
    product, port = _product()
    data_product_repo.update(db=MagicMock(), db_obj=product, obj_in={
        "output_ports": [
            {"id": port.id, "name": "out", "version": "1.0.0", "port_type": "file"}]})
    assert product.output_ports[0].port_type == "file"


def test_update_management_port_keeps_type():
    product, _ = _product()
    _update(product, {"management_ports": [
        {"name": "m", "content": "discoverability", "type": "topic"}]})
    assert [m.port_type for m in product.management_ports] == ["topic"]


def test_update_management_port_without_type_defaults_to_rest():
    product, _ = _product()
    _update(product, {"management_ports": [{"name": "m", "content": "discoverability"}]})
    assert [m.port_type for m in product.management_ports] == ["rest"]


def test_update_without_ports_leaves_port_types_alone():
    product, _ = _product()
    _update(product, {"name": "renamed"})
    assert product.output_ports[0].port_type == "table"
    assert product.management_ports[0].port_type == "topic"
