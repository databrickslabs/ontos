"""The ODPS export validates against the bundled ODPS v1.0.0 schema, and the output
port status survives export and import as the ontosPortStatus custom property.

ODPS v1.0.0 has no `status` on an output port (`additionalProperties: false`), so the
export used to fail schema validation for every product with an output port (#936).
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.models.data_products import ONTOS_PORT_STATUS_PROPERTY, OutputPort

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "odps-json-schema-v1.0.0.json"


@pytest.fixture
def product_manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )


def _product(name: str, port_status: str = "active") -> dict:
    return {
        "name": name, "version": "1.0.0", "productType": "sourceAligned",
        "description": {"purpose": "Port status round-trip", "usage": "Tests"},
        "inputPorts": [{"name": "orders_in", "version": "1.0.0", "contractId": "c-in"}],
        "outputPorts": [{
            "name": "orders_out", "version": "1.0.0", "contractId": "c-out",
            "status": port_status,
        }],
        "support": [{"channel": "#orders", "url": "https://example.com/orders"}],
        "team": {"name": "Orders", "members": [{"username": "owner@example.com", "role": "owner"}]},
    }


def _schema_errors(document: dict) -> list:
    schema = json.loads(SCHEMA_PATH.read_text())
    return [
        f"{list(e.path)}: {e.message}"
        for e in jsonschema.Draft7Validator(schema).iter_errors(document)
    ]


def _status_props(port: dict) -> list:
    return [
        cp for cp in port.get("customProperties") or []
        if cp.get("property") == ONTOS_PORT_STATUS_PROPERTY
    ]


class TestExport:
    def test_export_with_ports_team_and_support_validates(self, product_manager, db_session):
        created = product_manager.create_product(_product("Valid Export"), db=db_session, user="a@b.com")
        export = product_manager.build_odps_export(created.id, db=db_session)

        assert export["outputPorts"] and export["inputPorts"]
        assert _schema_errors(export) == []

    def test_port_status_is_a_custom_property(self, product_manager, db_session):
        created = product_manager.create_product(
            _product("Deprecated Port", port_status="deprecated"), db=db_session, user="a@b.com",
        )
        port = product_manager.build_odps_export(created.id, db=db_session)["outputPorts"][0]

        assert "status" not in port
        assert _status_props(port) == [{"property": ONTOS_PORT_STATUS_PROPERTY, "value": "deprecated"}]

    def test_port_without_status_has_no_custom_property(self, product_manager, db_session):
        data = _product("No Port Status")
        del data["outputPorts"][0]["status"]
        created = product_manager.create_product(data, db=db_session, user="a@b.com")
        port = product_manager.build_odps_export(created.id, db=db_session)["outputPorts"][0]

        assert "status" not in port and "customProperties" not in port


class TestImport:
    def _import(self, product_manager, document: dict):
        content = yaml.safe_dump(document).encode("utf-8")
        result = product_manager.create_products_from_files(
            [("p.yaml", content)], user="a@b.com", on_duplicate="new",
        )
        assert result.created == 1, result.items
        return product_manager.get_product(result.created_ids[0])

    def test_export_then_import_keeps_the_port_status(self, product_manager, db_session):
        created = product_manager.create_product(
            _product("Round Trip", port_status="deprecated"), db=db_session, user="a@b.com",
        )
        export = product_manager.build_odps_export(created.id, db=db_session)

        imported = self._import(product_manager, export)

        assert imported.id != created.id
        assert imported.outputPorts[0].status == "deprecated"
        assert not imported.outputPorts[0].customProperties
        re_export = product_manager.build_odps_export(imported.id, db=db_session)
        assert _status_props(re_export["outputPorts"][0])[0]["value"] == "deprecated"

    def test_an_older_export_with_a_bare_port_status_still_imports(self, product_manager, db_session):
        document = {"apiVersion": "v1.0.0", "kind": "DataProduct", "status": "draft",
                    **_product("Old Export", port_status="deprecated")}

        imported = self._import(product_manager, document)

        assert imported.outputPorts[0].status == "deprecated"


class TestOutputPortModel:
    def test_reads_the_status_from_the_custom_property(self):
        port = OutputPort(name="p", version="1", customProperties=[
            {"property": ONTOS_PORT_STATUS_PROPERTY, "value": "retired"},
            {"property": "owner", "value": "x"},
        ])

        assert port.status == "retired"
        assert [cp.property for cp in port.customProperties] == ["owner"]

    def test_a_bare_status_wins_over_the_custom_property(self):
        port = OutputPort(name="p", version="1", status="active", customProperties=[
            {"property": ONTOS_PORT_STATUS_PROPERTY, "value": "retired"},
        ])

        assert port.status == "active"
        assert port.customProperties is None

    def test_ports_without_the_property_are_unchanged(self):
        port = OutputPort(name="p", version="1", status="active",
                          customProperties=[{"property": "owner", "value": "x"}])

        assert port.status == "active"
        assert [cp.property for cp in port.customProperties] == ["owner"]
