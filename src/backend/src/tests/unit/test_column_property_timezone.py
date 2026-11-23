"""`timezone` is a boolean on ODCS v3.1 timestamp / time columns, a zone name on a date."""
import uuid
from pathlib import Path

from src.controller.data_contracts_manager import DataContractsManager
from src.models.data_contracts_api import ColumnProperty


def test_timezone_accepts_a_boolean_and_a_zone_name():
    flag = ColumnProperty(name="ts", logicalType="timestamp", timezone=True)
    name = ColumnProperty(name="day", logicalType="date", timezone="UTC")

    assert flag.timezone is True
    assert name.timezone == "UTC"


def test_a_timestamp_timezone_flag_survives_create_and_export(db_session):
    manager = DataContractsManager(data_dir=Path("/tmp"))
    manager._queue_delivery = lambda *a, **k: None
    manager._update_search_index = lambda *a, **k: None
    contract = manager.create_contract_with_relations(
        db=db_session,
        contract_data={
            "name": f"events-{uuid.uuid4().hex[:6]}", "version": "1.0.0",
            "schema": [{"name": "events", "properties": [
                {"name": "ts", "logicalType": "timestamp", "format": "yyyy", "timezone": True},
            ]}],
        },
        current_user="alice@example.com",
    )
    db_session.refresh(contract)

    exported = manager.build_odcs_from_db(contract, db_session)

    ts = next(p for p in exported["schema"][0]["properties"] if p["name"] == "ts")
    # The flat `timezone` / `format` keys are the current export shape, not the
    # intended ODCS one: they move under `logicalTypeOptions` with #1635.
    assert ts["timezone"] is True
    assert ts["format"] == "yyyy"
