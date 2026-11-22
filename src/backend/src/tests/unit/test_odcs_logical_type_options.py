"""A column's type options go under `logicalTypeOptions` in an ODCS v3.1.0 export (#1635).

The export wrote them flat on the property (`format`, `maxLength`, `timezone` ...),
which ODCS v3.1.0 doesn't allow there (`unevaluatedProperties: false`), so the export
failed validation. A v3.0.x contract keeps the flat shape; the import reads both.
"""
import json
import uuid
from pathlib import Path

import jsonschema
import pytest

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, SchemaPropertyDb
from src.utils.odcs_type_options import nests_type_options

_SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
OPTIONS = {
    "day": ("date", {"format": "yyyy-MM-dd"}),
    "code": ("string", {"minLength": 2, "maxLength": 8, "pattern": "^[A-Z]+$"}),
    "ts": ("timestamp", {"format": "yyyy-MM-dd HH:mm", "timezone": True}),
    "amount": ("number", {"minimum": 0, "maximum": 100}),
    "tags": ("array", {"minItems": 1, "maxItems": 3}),
}


def _manager():
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    mgr._queue_delivery = lambda *a, **k: None
    mgr._update_search_index = lambda *a, **k: None
    return mgr


def _document(api_version="v3.1.0", nested=True):
    def column(name, logical_type, options):
        prop = {"name": name, "logicalType": logical_type}
        if nested:
            prop["logicalTypeOptions"] = dict(options)
        else:
            prop.update(options)
        return prop

    return {
        "apiVersion": api_version, "kind": "DataContract", "id": str(uuid.uuid4()),
        "name": f"orders-{uuid.uuid4().hex[:6]}", "version": "1.0.0", "status": "draft",
        "schema": [{"name": "orders", "properties": [
            column(name, logical_type, options)
            for name, (logical_type, options) in OPTIONS.items()
        ]}],
    }


def _upload(db_session, document):
    manager = _manager()
    contract = manager.create_from_upload(db_session, document, current_user="alice")
    db_session.commit()
    return manager, contract.id


def _export(manager, db_session, contract_id):
    db_session.expire_all()
    return manager.build_odcs_from_db(db_session.get(DataContractDb, contract_id), db_session)


def _columns(document):
    return {p["name"]: p for p in document["schema"][0]["properties"]}


def _stored(db_session, contract_id):
    db_session.expire_all()
    contract = db_session.get(DataContractDb, contract_id)
    ids = [o.id for o in contract.schema_objects]
    rows = db_session.query(SchemaPropertyDb).filter(SchemaPropertyDb.object_id.in_(ids))
    return {p.name: json.loads(p.logical_type_options_json or "{}") for p in rows}


def _errors(document, schema_file):
    schema = json.loads((_SCHEMAS / schema_file).read_text())
    return [e.message for e in jsonschema.Draft201909Validator(schema).iter_errors(document)]


def test_a_v310_export_writes_the_options_under_logical_type_options(db_session):
    manager, cid = _upload(db_session, _document(nested=True))

    columns = _columns(_export(manager, db_session, cid))

    for name, (_, options) in OPTIONS.items():
        assert columns[name]["logicalTypeOptions"] == options, name
        assert not set(options) & set(columns[name]), f"{name}: an option is still flat"


@pytest.mark.parametrize("nested", [True, False])
def test_a_v310_export_with_type_options_validates_against_the_schema(db_session, nested):
    manager, cid = _upload(db_session, _document(nested=nested))
    exported = _export(manager, db_session, cid)

    assert _columns(exported)["code"]["logicalTypeOptions"]["maxLength"] == 8
    assert _errors(exported, "odcs-json-schema-v3.1.0.json") == []


def test_the_import_reads_nested_options(db_session):
    _, cid = _upload(db_session, _document(nested=True))

    assert _stored(db_session, cid) == {name: opts for name, (_, opts) in OPTIONS.items()}


def test_the_import_still_reads_flat_options_of_older_exports(db_session):
    manager, cid = _upload(db_session, _document(nested=False))

    assert _stored(db_session, cid) == {name: opts for name, (_, opts) in OPTIONS.items()}
    # and a v3.1.0 export of it nests them
    assert _columns(_export(manager, db_session, cid))["day"]["logicalTypeOptions"] == {
        "format": "yyyy-MM-dd"}


def test_an_export_imported_again_keeps_the_options(db_session):
    manager, cid = _upload(db_session, _document(nested=True))
    exported = _export(manager, db_session, cid)
    exported["id"] = str(uuid.uuid4())
    exported["name"] = f"{exported['name']}-again"

    manager_again, cid_again = _upload(db_session, exported)

    assert _columns(_export(manager_again, db_session, cid_again)) == _columns(exported)


def test_a_flat_key_wins_over_the_nested_one(db_session):
    document = _document(nested=True)
    day = document["schema"][0]["properties"][0]
    day["format"] = "dd/MM/yyyy"  # an editor's flat value next to the nested one

    _, cid = _upload(db_session, document)

    assert _stored(db_session, cid)["day"] == {"format": "dd/MM/yyyy"}


def test_read_type_options_takes_only_a_map_and_skips_nulls():
    from src.utils.odcs_type_options import read_type_options

    assert read_type_options({"logicalTypeOptions": {"format": "a", "x": None}}) == {
        "format": "a"}
    assert read_type_options({"logicalTypeOptions": "not a map"}) == {}
    assert read_type_options({}) == {}


def test_a_v302_contract_keeps_the_flat_options(db_session):
    manager, cid = _upload(db_session, _document(api_version="v3.0.2", nested=True))

    columns = _columns(_export(manager, db_session, cid))

    assert "logicalTypeOptions" not in columns["code"]
    assert columns["code"]["maxLength"] == 8 and columns["day"]["format"] == "yyyy-MM-dd"


@pytest.mark.parametrize("version,nested", [
    (None, True), ("v3.1.0", True), ("v3.2.0", True), ("v3.0.2", False), ("v3.0.0", False),
])
def test_which_versions_nest_the_options(version, nested):
    assert nests_type_options(version) is nested


def test_an_editor_save_with_flat_options_keeps_them_nested_in_the_export(db_session):
    manager, cid = _upload(db_session, _document(nested=True))

    # the schema editor sends the options flat, as the contract API returns them
    manager.update_contract_with_relations(db_session, cid, {"schema": [{
        "name": "orders", "properties": [
            {"name": "day", "logicalType": "date", "format": "dd/MM/yyyy"},
            {"name": "code", "logicalType": "string", "maxLength": 4},
        ]}]}, current_user="alice")
    db_session.commit()

    columns = _columns(_export(manager, db_session, cid))
    assert columns["day"]["logicalTypeOptions"] == {"format": "dd/MM/yyyy"}
    assert columns["code"]["logicalTypeOptions"] == {"maxLength": 4}
