"""Output port server / PII / auto-approve and the owner team survive the ODPS export.

ODPS v1.0.0 has no place for them, so the export carries them as `ontos*` custom
properties (like `ontosPortStatus`) and the import reads them back into the columns.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
import yaml
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.db_models.teams import TeamDb
from src.models.data_products import (
    ONTOS_OWNER_TEAM_PROPERTY,
    ONTOS_PORT_AUTO_APPROVE_PROPERTY,
    ONTOS_PORT_CONTAINS_PII_PROPERTY,
    ONTOS_PORT_SERVER_PROPERTY,
    OutputPort,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "odps-json-schema-v1.0.0.json"
SERVER = {"host": "db.example.com", "database": "sales", "schema": "public", "table": "orders"}


@pytest.fixture
def product_manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )


def _product(name: str, **extra) -> dict:
    return {
        "name": name, "version": "1.0.0", "productType": "sourceAligned",
        "description": {"purpose": "Ontos field round-trip", "usage": "Tests"},
        "outputPorts": [{
            "name": "orders_out", "version": "1.0.0", "contractId": "c-out",
            "server": SERVER, "containsPii": True, "autoApprove": True,
        }],
        **extra,
    }


def _props(node: dict) -> dict:
    return {cp["property"]: cp["value"] for cp in node.get("customProperties") or []}


def _team(db: Session, name: str) -> TeamDb:
    team = TeamDb(name=name, created_by="a@b.com", updated_by="a@b.com")
    db.add(team)
    db.flush()
    return team


def _import(manager: DataProductsManager, document: dict):
    content = yaml.safe_dump(document).encode("utf-8")
    result = manager.create_products_from_files(
        [("p.yaml", content)], user="a@b.com", on_duplicate="new",
    )
    assert result.created == 1, result.items
    return manager.get_product(result.created_ids[0])


class TestPortFields:
    def test_export_carries_server_pii_and_auto_approve(self, product_manager, db_session):
        created = product_manager.create_product(
            _product("Port Fields"), db=db_session, user="a@b.com",
        )

        export = product_manager.build_odps_export(created.id, db=db_session)

        port = export["outputPorts"][0]
        assert "server" not in port and "containsPii" not in port
        assert _props(port)[ONTOS_PORT_SERVER_PROPERTY] == SERVER
        assert _props(port)[ONTOS_PORT_CONTAINS_PII_PROPERTY] is True
        assert _props(port)[ONTOS_PORT_AUTO_APPROVE_PROPERTY] is True
        schema = json.loads(SCHEMA_PATH.read_text())
        assert list(jsonschema.Draft7Validator(schema).iter_errors(export)) == []

    def test_unset_fields_are_not_exported(self, product_manager, db_session):
        data = _product("No Port Fields")
        data["outputPorts"][0] = {"name": "orders_out", "version": "1.0.0"}
        created = product_manager.create_product(data, db=db_session, user="a@b.com")

        port = product_manager.build_odps_export(created.id, db=db_session)["outputPorts"][0]

        assert "customProperties" not in port

    def test_round_trip_keeps_the_port_fields(self, product_manager, db_session):
        created = product_manager.create_product(
            _product("Port Trip"), db=db_session, user="a@b.com",
        )
        export = product_manager.build_odps_export(created.id, db=db_session)

        imported = _import(product_manager, export)

        port = imported.outputPorts[0]
        assert imported.id != created.id
        assert port.server.host == "db.example.com" and port.server.schema_name == "public"
        assert port.containsPii is True and port.autoApprove is True
        assert not port.customProperties
        again = product_manager.build_odps_export(imported.id, db=db_session)["outputPorts"][0]
        assert _props(again)[ONTOS_PORT_SERVER_PROPERTY] == SERVER

    def test_model_reads_the_properties_and_a_bare_field_wins(self):
        port = OutputPort(name="p", version="1", containsPii=False, customProperties=[
            {"property": ONTOS_PORT_CONTAINS_PII_PROPERTY, "value": True},
            {"property": ONTOS_PORT_AUTO_APPROVE_PROPERTY, "value": True},
            {"property": ONTOS_PORT_SERVER_PROPERTY, "value": {"host": "h"}},
            {"property": "owner", "value": "x"},
        ])

        assert port.containsPii is False
        assert port.autoApprove is True and port.server.host == "h"
        assert [cp.property for cp in port.customProperties] == ["owner"]


class TestOwnerTeam:
    def test_export_names_the_owner_team(self, product_manager, db_session):
        team = _team(db_session, "Orders Team")
        created = product_manager.create_product(
            _product("Owned", owner_team_id=team.id), db=db_session, user="a@b.com",
        )

        export = product_manager.build_odps_export(created.id, db=db_session)

        assert _props(export)[ONTOS_OWNER_TEAM_PROPERTY] == "Orders Team"

    def test_product_without_owner_team_has_no_property(self, product_manager, db_session):
        created = product_manager.create_product(_product("Unowned"), db=db_session, user="a@b.com")

        export = product_manager.build_odps_export(created.id, db=db_session)

        assert ONTOS_OWNER_TEAM_PROPERTY not in _props(export)

    def test_round_trip_restores_the_owner_team(self, product_manager, db_session):
        team = _team(db_session, "Orders Team")
        created = product_manager.create_product(
            _product("Owned Trip", owner_team_id=team.id), db=db_session, user="a@b.com",
        )
        export = product_manager.build_odps_export(created.id, db=db_session)

        imported = _import(product_manager, export)

        assert imported.owner_team_id == team.id
        left = {cp.property for cp in imported.customProperties or []}
        assert ONTOS_OWNER_TEAM_PROPERTY not in left
        again = product_manager.build_odps_export(imported.id, db=db_session)
        assert _props(again)[ONTOS_OWNER_TEAM_PROPERTY] == "Orders Team"

    def test_unknown_team_keeps_the_name_as_a_custom_property(self, product_manager, db_session):
        document = {"apiVersion": "v1.0.0", "kind": "DataProduct", "status": "draft",
                    **_product("Unknown Team"),
                    "customProperties": [{"property": ONTOS_OWNER_TEAM_PROPERTY, "value": "Gone"}]}

        imported = _import(product_manager, document)

        assert imported.owner_team_id is None
        assert _props(product_manager.build_odps_export(imported.id, db=db_session))[
            ONTOS_OWNER_TEAM_PROPERTY] == "Gone"
