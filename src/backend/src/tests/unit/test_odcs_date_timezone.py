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

    exported = manager.build_odcs_from_db(contract, db_session)

    day = _column(exported, "day")
    assert day["format"] == "yyyy-MM-dd"
    assert "timezone" not in day
    assert _column(exported, "code")["pattern"] == "^[A-Z]+$"
    # still stored
    stored = db_session.query(SchemaPropertyDb).filter_by(name="day").one()
    assert json.loads(stored.logical_type_options_json)["timezone"] == "UTC"
