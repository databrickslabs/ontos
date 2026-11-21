"""ODCS v3.1 has no timezone option on a date column: the export leaves it out.

The editors offered a free-text Timezone on date columns; a stored value stays
stored (and readable), but the ODCS export doesn't write it for a date.
"""
import json
import uuid
from pathlib import Path

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import SchemaPropertyDb


def _manager():
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    mgr._queue_delivery = lambda *a, **k: None
    mgr._update_search_index = lambda *a, **k: None
    return mgr


def _column(doc, name):
    return next(p for p in doc["schema"][0]["properties"] if p["name"] == name)


def test_a_date_column_exports_its_format_but_no_timezone(db_session):
    manager = _manager()
    contract = manager.create_contract_with_relations(
        db=db_session,
        contract_data={
            "name": f"orders-{uuid.uuid4().hex[:6]}", "version": "1.0.0",
            "schema": [{"name": "orders", "properties": [
                {"name": "day", "logicalType": "date", "format": "yyyy-MM-dd", "timezone": "UTC"},
                {"name": "code", "logicalType": "string", "pattern": "^[A-Z]+$"},
            ]}],
        },
        current_user="alice@example.com",
    )
    db_session.refresh(contract)

    exported = manager.build_odcs_from_db(contract, db_session, for_export=True)

    day = _column(exported, "day")
    # Flat `format` is the current export shape, not the intended ODCS one: type options
    # move under `logicalTypeOptions` with #1635.
    assert day["format"] == "yyyy-MM-dd"
    assert "timezone" not in day
    assert _column(exported, "code")["pattern"] == "^[A-Z]+$"
    # still stored
    stored = db_session.query(SchemaPropertyDb).filter_by(name="day").one()
    assert json.loads(stored.logical_type_options_json)["timezone"] == "UTC"


def test_a_custom_format_is_not_exported_as_a_non_schema_key(db_session):
    manager = _manager()
    contract = manager.create_contract_with_relations(
        db=db_session,
        contract_data={
            "name": f"events-{uuid.uuid4().hex[:6]}", "version": "1.0.0",
            "schema": [{"name": "events", "properties": [
                {"name": "ts", "logicalType": "timestamp", "format": "yyyy-MM-dd",
                 "customFormat": "yyyy/dd"},
            ]}],
        },
        current_user="alice@example.com",
    )
    db_session.refresh(contract)

    exported = manager.build_odcs_from_db(contract, db_session, for_export=True)

    ts = _column(exported, "ts")
    # Flat `format`: current shape, to move under `logicalTypeOptions` with #1635.
    assert ts["format"] == "yyyy-MM-dd"
    assert "customFormat" not in ts
    stored = db_session.query(SchemaPropertyDb).filter_by(name="ts").one()
    assert json.loads(stored.logical_type_options_json)["customFormat"] == "yyyy/dd"


def test_a_save_keeps_the_stored_options_the_export_leaves_out(db_session):
    manager = _manager()
    contract = manager.create_contract_with_relations(
        db=db_session,
        contract_data={
            "name": f"orders-{uuid.uuid4().hex[:6]}", "version": "1.0.0",
            "schema": [{"name": "orders", "properties": [
                {"name": "day", "logicalType": "date", "format": "yyyy-MM-dd", "timezone": "UTC"},
                {"name": "ts", "logicalType": "timestamp", "customFormat": "yyyy/dd"},
            ]}],
        },
        current_user="alice@example.com",
    )

    # an editor save sends the options it loaded (from the stored contract, not the export)
    manager.update_contract_with_relations(db_session, contract.id, {
        "schema": [{"name": "orders", "properties": [
            {"name": "day", "logicalType": "date", "format": "yyyy-MM-dd", "timezone": "UTC"},
            {"name": "ts", "logicalType": "timestamp", "customFormat": "yyyy/dd"},
        ]}],
    }, current_user="alice@example.com")
    db_session.expire_all()

    options = {
        p.name: json.loads(p.logical_type_options_json or "{}")
        for p in db_session.query(SchemaPropertyDb).filter(
            SchemaPropertyDb.name.in_(["day", "ts"])
        )
    }
    assert options["day"]["timezone"] == "UTC"
    assert options["ts"]["customFormat"] == "yyyy/dd"
    stored_contract = db_session.get(type(contract), contract.id)
    # the internal source of an update still has them; only the export leaves them out
    internal = manager.build_odcs_from_db(stored_contract, db_session)
    assert _column(internal, "day")["timezone"] == "UTC"
    assert _column(internal, "ts")["customFormat"] == "yyyy/dd"
    refreshed = manager.build_odcs_from_db(stored_contract, db_session, for_export=True)
    assert "timezone" not in _column(refreshed, "day")
    assert "customFormat" not in _column(refreshed, "ts")
