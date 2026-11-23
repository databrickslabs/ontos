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


def test_a_v302_export_nests_the_options_and_validates(db_session):
    # v3.0.2 defines logicalTypeOptions too: the nested form is its spec form
    manager, cid = _upload(db_session, _v302(_document(api_version="v3.0.2", nested=False)))
    exported = _export(manager, db_session, cid)

    columns = _columns(exported)
    assert columns["code"]["logicalTypeOptions"]["maxLength"] == 8
    assert "maxLength" not in columns["code"]
    assert _errors(exported, "odcs-json-schema-v3.0.2.json") == []
    assert _errors(exported, "odcs-json-schema-v3.0.2-strict.json") == []


@pytest.mark.parametrize("schema_file", [
    "odcs-json-schema-v3.0.2.json", "odcs-json-schema-v3.0.2-strict.json",
])
def test_flat_type_options_fail_both_bundled_v302_schemas(db_session, schema_file):
    # the nested form is the spec form; the flat one fails the plain schema too
    manager, cid = _upload(db_session, _v302(_document(api_version="v3.0.2", nested=False)))
    exported = _export(manager, db_session, cid)
    for column in exported["schema"][0]["properties"]:
        column.update(column.pop("logicalTypeOptions", {}))

    assert any("maxLength" in e for e in _errors(exported, schema_file))


@pytest.mark.parametrize("version,nested", [
    (None, True), ("v3.1.0", True), ("v3.2.0", True), ("v3.0.2", True), ("v3.0.0", True),
    ("v2.2.2", False),
])
def test_which_versions_nest_the_options(version, nested):
    assert nests_type_options(version) is nested


# --- stored options ODCS has no logicalTypeOptions key for -------------------------

EXTRA = {
    "amount": ("number", {"minimum": 0, "precision": 2}),
    "ts": ("timestamp", {"format": "yyyy", "customFormat": "yyyy/dd"}),
    "tags": ("array", {"minItems": 1, "itemType": "string"}),
    "code": ("string", {"maxLength": 4, "minimum": 1}),
}


def _v302(document):
    """ODCS v3.0.2 has no `timestamp` logicalType: leave those columns out."""
    props = document["schema"][0]["properties"]
    document["schema"][0]["properties"] = [p for p in props if p["logicalType"] != "timestamp"]
    return document


def _extra_document(api_version="v3.1.0"):
    document = _document(api_version=api_version, nested=False)
    document["schema"][0]["properties"] = [
        {"name": name, "logicalType": logical_type, **options}
        for name, (logical_type, options) in EXTRA.items()
    ]
    return _v302(document) if api_version < "v3.1.0" else document


@pytest.mark.parametrize("version,schema_file", [
    ("v3.1.0", "odcs-json-schema-v3.1.0.json"), ("v3.0.2", "odcs-json-schema-v3.0.2.json"),
])
def test_an_export_with_non_odcs_options_validates(db_session, version, schema_file):
    manager, cid = _upload(db_session, _extra_document(version))
    exported = _export(manager, db_session, cid)

    columns = _columns(exported)
    assert columns["tags"]["items"] == {"logicalType": "string"}
    assert columns["tags"]["logicalTypeOptions"] == {"minItems": 1}
    props = {cp["property"]: cp["value"] for cp in columns["amount"]["customProperties"]}
    assert props == {"ontos.precision": 2}
    assert _errors(exported, schema_file) == []


def test_non_odcs_options_round_trip_to_the_same_stored_values(db_session):
    manager, cid = _upload(db_session, _extra_document())
    stored = _stored(db_session, cid)
    exported = _export(manager, db_session, cid)
    exported["id"] = str(uuid.uuid4())
    exported["name"] = f"{exported['name']}-again"

    manager_again, cid_again = _upload(db_session, exported)

    assert _stored(db_session, cid_again) == stored
    assert stored["amount"]["precision"] == 2 and stored["tags"]["itemType"] == "string"
    # the ontos.* entries are options again, not column custom properties
    again = _columns(_export(manager_again, db_session, cid_again))
    assert again == _columns(exported)
    rows = db_session.query(SchemaPropertyDb).filter_by(name="amount").all()
    assert all(not any(cp.property.startswith("ontos.") for cp in r.custom_properties)
               for r in rows)


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


def test_the_contract_api_reads_nested_object_and_timestamp_options(db_session):
    document = _document(nested=True)
    document["schema"][0]["properties"].append({
        "name": "address", "logicalType": "object", "required": True,
        "logicalTypeOptions": {"required": ["street"], "maxProperties": 3},
    })
    manager, cid = _upload(db_session, document)
    db_session.expire_all()

    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid))

    columns = {c.name: c for c in api.contract_schema[0].properties}
    # the column's own `required` flag is not replaced by the object's property names
    assert columns["address"].required is True
    assert columns["ts"].timezone is True
    exported = _columns(_export(manager, db_session, cid))
    assert exported["address"]["logicalTypeOptions"] == {
        "required": ["street"], "maxProperties": 3}
    assert exported["address"]["required"] is True
    assert _errors(_export(manager, db_session, cid), "odcs-json-schema-v3.1.0.json") == []


# --- options the editors don't show survive the contract API and saves --------------

UNSHOWN = {
    "address": ("object", {"required": ["street"], "minProperties": 1, "maxProperties": 3}),
    "tags": ("array", {"minItems": 1, "uniqueItems": True}),
    "ts": ("timestamp", {"format": "yyyy", "defaultTimezone": "UTC",
                         "minimum": "2020-01-01T00:00:00Z", "exclusiveMaximum": True}),
    "day": ("date", {"minimum": "2020-01-01", "maximum": "2030-12-31"}),
}


def _unshown_contract(db_session):
    document = _document(nested=True)
    document["schema"][0]["properties"] = [
        {"name": name, "logicalType": logical_type, "logicalTypeOptions": dict(options)}
        for name, (logical_type, options) in UNSHOWN.items()
    ]
    return _upload(db_session, document)


def _api_columns(manager, db_session, cid):
    db_session.expire_all()
    api = manager._build_contract_api_model(db_session, db_session.get(DataContractDb, cid))
    return api, {c.name: c for c in api.contract_schema[0].properties}


def test_the_contract_api_reads_date_bounds_and_unshown_options(db_session):
    manager, cid = _unshown_contract(db_session)

    _, columns = _api_columns(manager, db_session, cid)

    assert columns["day"].minimum == "2020-01-01"
    assert columns["address"].requiredProperties == ["street"]
    assert columns["tags"].uniqueItems is True
    assert columns["ts"].defaultTimezone == "UTC"


def test_a_save_of_what_the_api_returns_keeps_the_options(db_session):
    from src.models.data_contracts_api import DataContractUpdate

    manager, cid = _unshown_contract(db_session)
    before = _stored(db_session, cid)
    api, _ = _api_columns(manager, db_session, cid)
    schema = api.model_dump(by_alias=True)["schema"]

    manager.update_contract_with_relations(
        db_session, cid, DataContractUpdate.model_validate({"schema": schema}),
        current_user="alice")
    db_session.commit()

    assert _stored(db_session, cid) == before


def test_an_editor_save_that_doesnt_send_them_keeps_the_options(db_session):
    manager, cid = _unshown_contract(db_session)
    before = _stored(db_session, cid)

    # the schema editor sends only the fields it shows
    manager.update_contract_with_relations(db_session, cid, {"schema": [{
        "name": "orders", "properties": [
            {"name": "address", "logicalType": "object"},
            {"name": "tags", "logicalType": "array", "minItems": 1},
            {"name": "ts", "logicalType": "timestamp", "format": "yyyy",
             "minimum": "2020-01-01T00:00:00Z"},
            {"name": "day", "logicalType": "date", "minimum": "2020-01-01",
             "maximum": "2030-12-31"},
        ]}]}, current_user="alice")
    db_session.commit()

    assert _stored(db_session, cid) == before


def test_an_editor_save_keeps_date_time_bounds_it_sends_back_empty(db_session):
    manager, cid = _unshown_contract(db_session)
    before = _stored(db_session, cid)

    # the editor parses bounds as numbers: date-time text comes back as null
    manager.update_contract_with_relations(db_session, cid, {"schema": [{
        "name": "orders", "properties": [
            {"name": "address", "logicalType": "object"},
            {"name": "tags", "logicalType": "array", "minItems": 1},
            {"name": "ts", "logicalType": "timestamp", "format": "yyyy", "minimum": None},
            {"name": "day", "logicalType": "date", "minimum": None, "maximum": None},
        ]}]}, current_user="alice")
    db_session.commit()

    assert _stored(db_session, cid) == before


def test_invalid_or_unknown_nested_options_are_not_stored(db_session):
    document = _document(nested=True)
    document["schema"][0]["properties"] = [
        {"name": "tags", "logicalType": "array",
         "logicalTypeOptions": {"uniqueItems": "yes", "minItems": 1, "name": "x"}},
        {"name": "address", "logicalType": "object",
         "logicalTypeOptions": {"required": "street", "minProperties": "x"}},
        {"name": "code", "logicalType": "string", "customProperties": [
            {"property": "ontos.logicalType", "value": "date"},
            {"property": "ontos.precision", "value": 2}]},
    ]
    manager, cid = _upload(db_session, document)

    assert _stored(db_session, cid) == {"tags": {"minItems": 1}, "address": {},
                                        "code": {"precision": 2}}
    _, columns = _api_columns(manager, db_session, cid)  # the contract still reads
    assert columns["code"].logicalType == "string" and columns["tags"].name == "tags"
    rows = db_session.query(SchemaPropertyDb).filter_by(name="code").all()
    # an ontos.* name that is no option stays a custom property
    assert {cp.property for r in rows for cp in r.custom_properties} == {"ontos.logicalType"}
