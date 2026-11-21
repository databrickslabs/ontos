"""A contract's apiVersion is an ODCS version, in the ODCS spelling.

A version without its "v" ('3.0.2') is stored as 'v3.0.2' by the create and update
models, the ODCS imports and the self-service creation, and the ODCS export writes the
same spelling for a value stored before. A new contract with a value outside the ODCS
enum (or null) is refused with the code ``odcs_api_version_unsupported`` on every
create path. An update may send back the stored value, even an invalid one, but may
not change it to one.
"""
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.common.odcs_api_version import UnsupportedOdcsApiVersionError
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.models.data_contracts_api import DataContractCreate, DataContractUpdate

SPELLINGS = [
    ("v3.1.0", "v3.1.0"), ("3.0.2", "v3.0.2"), (" V3.0.1 ", "v3.0.1"), ("v2.2.2", "v2.2.2"),
]


@pytest.mark.parametrize("key", ["apiVersion", "api_version"])
@pytest.mark.parametrize("sent, stored", SPELLINGS)
def test_a_create_stores_the_odcs_spelling(key, sent, stored):
    assert DataContractCreate.model_validate(
        {"name": "Orders", key: sent}).apiVersion == stored


@pytest.mark.parametrize("key", ["apiVersion", "api_version"])
@pytest.mark.parametrize("sent, stored", SPELLINGS)
def test_an_update_stores_the_odcs_spelling(key, sent, stored):
    assert DataContractUpdate.model_validate({"name": "Orders", key: sent}).apiVersion == stored


@pytest.mark.parametrize("key", ["apiVersion", "api_version"])
@pytest.mark.parametrize("sent", ["9.9.9", "v4.0.0", "latest", "", None])
def test_a_new_contract_outside_odcs_is_refused(key, sent):
    """Null included: before, an explicit null was pydantic's uncoded string_type error."""
    with pytest.raises(ValidationError) as err:
        DataContractCreate.model_validate({"name": "Orders", key: sent})
    [error] = err.value.errors()
    assert error["type"] == "odcs_api_version_unsupported"
    assert error["ctx"] == {"api_version": sent}


@pytest.mark.parametrize("camel, snake, refused", [
    ("v4.0.0", "v3.1.0", True), ("v3.0.2", "v4.0.0", False),
])
def test_a_create_with_both_spellings_checks_the_camel_case_one(camel, snake, refused):
    """The shared rule (camelCase wins when both are sent) decides what is checked."""
    data = {"name": "Orders", "apiVersion": camel, "api_version": snake}
    if refused:
        with pytest.raises(ValidationError) as err:
            DataContractCreate.model_validate(data)
        assert err.value.errors()[0]["ctx"] == {"api_version": camel}
    else:
        assert DataContractCreate.model_validate(data).apiVersion == camel


def test_the_create_route_answers_422_with_the_code_and_param():
    from fastapi import Body, FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.post("/x")
    def create(_body: DataContractCreate = Body(...)):
        return {}

    response = TestClient(app).post("/x", json={"name": "Orders", "apiVersion": "v4.0.0"})
    assert response.status_code == 422
    [detail] = response.json()["detail"]
    assert (detail["type"], detail["ctx"]) == (
        "odcs_api_version_unsupported", {"api_version": "v4.0.0"},
    )


def test_the_versions_follow_the_odcs_schema(monkeypatch, tmp_path):
    """The ODCS v3.2.0 work points ODCS_SCHEMA_PATH at the v3.2.0 schema, whose enum
    lists v3.2.0: the accepted versions follow it."""
    from src.common import odcs_api_version, odcs_validation

    schema = tmp_path / "odcs.json"
    schema.write_text('{"properties": {"apiVersion": {"enum": ["v3.2.0", "v3.1.0"]}}}')
    monkeypatch.setattr(odcs_validation, "ODCS_SCHEMA_PATH", schema)
    odcs_api_version._schema_api_versions.cache_clear()
    try:
        assert odcs_api_version.odcs_api_versions() == {"v3.2.0", "v3.1.0"}
        assert odcs_api_version.checked_api_version("3.2.0") == "v3.2.0"
    finally:
        odcs_api_version._schema_api_versions.cache_clear()


@pytest.mark.parametrize("content", [None, "not json", '{"properties": {}}'])
def test_an_unreadable_schema_refuses_every_version(monkeypatch, tmp_path, content):
    """Fail closed with the coded refusal (not a 500) when the schema is missing or
    unreadable, and read the schema again once it is fixed."""
    from src.common import odcs_api_version, odcs_validation

    schema = tmp_path / "odcs.json"
    if content is not None:
        schema.write_text(content)
    monkeypatch.setattr(odcs_validation, "ODCS_SCHEMA_PATH", schema)
    odcs_api_version._schema_api_versions.cache_clear()
    try:
        assert odcs_api_version.odcs_api_versions() == frozenset()
        with pytest.raises(UnsupportedOdcsApiVersionError):
            odcs_api_version.checked_api_version("v3.1.0")
        with pytest.raises(ValidationError) as err:
            DataContractCreate.model_validate({"name": "Orders", "apiVersion": "v3.1.0"})
        assert err.value.errors()[0]["type"] == "odcs_api_version_unsupported"

        schema.write_text('{"properties": {"apiVersion": {"enum": ["v3.1.0"]}}}')
        assert odcs_api_version.checked_api_version("v3.1.0") == "v3.1.0"
    finally:
        odcs_api_version._schema_api_versions.cache_clear()


def test_api_version_defaults():
    assert DataContractCreate.model_validate({"name": "Orders"}).apiVersion == "v3.1.0"
    assert DataContractUpdate.model_validate({"name": "Orders"}).apiVersion is None


@pytest.fixture
def manager():
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _contract(db, api_version):
    cid = str(uuid.uuid4())
    db.add(DataContractDb(
        id=cid, name=f"c-{cid[:8]}", version="1.0.0", status="draft", api_version=api_version,
    ))
    db.flush()
    return cid


def _update(manager, db, cid, api_version):
    body = DataContractUpdate.model_validate({"name": "Renamed", "apiVersion": api_version})
    manager.update_contract_with_relations(db=db, contract_id=cid, contract_data=body)
    db.expire_all()
    return db.get(DataContractDb, cid)


def test_an_update_may_send_back_a_stored_invalid_version(manager, db_session):
    cid = _contract(db_session, "v9")

    stored = _update(manager, db_session, cid, "v9")

    assert (stored.name, stored.api_version) == ("Renamed", "v9")


def test_an_update_may_move_to_an_odcs_version(manager, db_session):
    cid = _contract(db_session, "v9")

    assert _update(manager, db_session, cid, "3.0.2").api_version == "v3.0.2"


def test_an_update_to_a_version_outside_odcs_is_refused(manager, db_session):
    cid = _contract(db_session, "v3.1.0")

    with pytest.raises(UnsupportedOdcsApiVersionError) as err:
        _update(manager, db_session, cid, "9.9.9")
    assert (err.value.code, err.value.params) == (
        "odcs_api_version_unsupported", {"api_version": "v9.9.9"},
    )


@pytest.mark.parametrize("camel, snake, refused", [
    ("9.9.9", "v3.0.2", True), ("v3.0.2", "9.9.9", False),
])
def test_an_update_with_both_spellings_checks_the_camel_case_one(
    manager, db_session, camel, snake, refused
):
    """Same rule as on create: the camelCase apiVersion is the one checked and stored."""
    cid = _contract(db_session, "v3.1.0")
    body = DataContractUpdate.model_validate({"apiVersion": camel, "api_version": snake})

    if refused:
        with pytest.raises(UnsupportedOdcsApiVersionError) as err:
            manager.update_contract_with_relations(
                db=db_session, contract_id=cid, contract_data=body,
            )
        assert err.value.params == {"api_version": "v9.9.9"}
    else:
        manager.update_contract_with_relations(
            db=db_session, contract_id=cid, contract_data=body,
        )
        db_session.expire_all()
        assert db_session.get(DataContractDb, cid).api_version == camel


def test_the_update_route_answers_with_the_code_and_param():
    """The PUT route raises HTTPException(400, str(e)) from the coded error, as for a
    status change; the app's handler sends the code and params along."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from src.common.api_errors import CodedValueError, coded_http_exception_handler
    from src.common.odcs_api_version import check_api_version_change

    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)

    @app.put("/x")
    def update():
        try:
            check_api_version_change("v3.1.0", "v9.9.9")
        except CodedValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    response = TestClient(app).put("/x")
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert (detail["code"], detail["params"]) == (
        "odcs_api_version_unsupported", {"api_version": "v9.9.9"},
    )


@pytest.mark.parametrize("sent", ["v4.0.0", None])
def test_a_dict_create_outside_odcs_is_refused(manager, db_session, sent):
    """create_contract_with_relations with a dict (the assistant tools) skips the
    create model; it refuses the same values."""
    name = f"dict-{uuid.uuid4().hex[:8]}"
    with pytest.raises(UnsupportedOdcsApiVersionError):
        manager.create_contract_with_relations(
            db=db_session, contract_data={"name": name, "version": "1.0.0", "apiVersion": sent},
            current_user="alice",
        )
    assert db_session.query(DataContractDb).filter_by(name=name).count() == 0


@pytest.mark.parametrize("sent, stored", [("3.0.2", "v3.0.2"), (None, "v3.1.0")])
def test_a_dict_create_stores_the_odcs_spelling(manager, db_session, sent, stored):
    data = {"name": f"dict-{uuid.uuid4().hex[:8]}", "version": "1.0.0"}
    if sent is not None:
        data["apiVersion"] = sent

    created = manager.create_contract_with_relations(
        db=db_session, contract_data=data, current_user="alice",
    )
    assert created.api_version == stored


@pytest.mark.parametrize("sent, stored", [
    ("3.0.2", "v3.0.2"), ("v3.1.0", "v3.1.0"), (None, "v3.1.0"),
])
def test_a_file_import_stores_the_odcs_spelling(manager, db_session, sent, stored):
    """The ODCS file / text import (create_from_upload) normalizes like the REST models."""
    odcs = {"name": f"imported-{uuid.uuid4().hex[:8]}", "version": "1.0.0", "kind": "DataContract"}
    if sent is not None:
        odcs["apiVersion"] = sent

    created = manager.create_from_upload(db=db_session, parsed_odcs=odcs, current_user="alice")

    assert created.api_version == stored


@pytest.mark.parametrize("sent, stored", [("3.0.2", "v3.0.2"), (None, "v3.0.1")])
def test_a_self_service_contract_stores_the_odcs_spelling(manager, db_session, sent, stored):
    odcs = {"name": f"self-{uuid.uuid4().hex[:8]}", "version": "1.0.0"}
    if sent is not None:
        odcs["apiVersion"] = sent

    assert manager.create_from_odcs_dict(db_session, odcs, "alice").api_version == stored


def test_a_file_import_outside_odcs_is_refused(manager, db_session):
    odcs = {"name": f"imported-{uuid.uuid4().hex[:8]}", "version": "1.0.0", "apiVersion": "v9"}

    with pytest.raises(UnsupportedOdcsApiVersionError):
        manager.create_from_upload(db=db_session, parsed_odcs=odcs, current_user="alice")


def test_a_batch_import_reports_the_refusal_with_its_code(manager, db_session):
    """One file with a bad apiVersion is a failed item with the code; the batch goes on."""
    import yaml

    good, bad = (f"imported-{uuid.uuid4().hex[:8]}" for _ in range(2))
    files = [
        (f"{n}.yaml", yaml.safe_dump({"kind": "DataContract", "apiVersion": v, "name": n,
                                      "version": "1.0.0", "status": "draft"}),
         "application/x-yaml")
        for n, v in [(bad, "v9.9.9"), (good, "v3.0.2")]
    ]

    result = manager.create_contracts_from_files(db=db_session, files=files, current_user="alice")

    by_name = {item.name: item for item in result.items}
    assert (by_name[bad].status, by_name[bad].code, by_name[bad].params) == (
        "failed", "odcs_api_version_unsupported", {"api_version": "v9.9.9"},
    )
    assert by_name[good].status == "created"


def test_a_self_service_contract_outside_odcs_is_refused(manager, db_session):
    odcs = {"name": f"self-{uuid.uuid4().hex[:8]}", "version": "1.0.0", "apiVersion": "v9"}

    with pytest.raises(UnsupportedOdcsApiVersionError):
        manager.create_from_odcs_dict(db_session, odcs, "alice")


def _export(manager, db, api_version, with_team=False):
    from src.db_models.data_contracts import DataContractTeamDb, DataContractTeamMetadataDb

    cid = _contract(db, api_version)
    if with_team:
        db.add(DataContractTeamDb(contract_id=cid, username="alice@example.com", role="owner"))
        db.add(DataContractTeamMetadataDb(contract_id=cid, name="Orders team"))
        db.flush()
    db.expire_all()
    return manager.build_odcs_from_db(db.get(DataContractDb, cid), db)


@pytest.mark.parametrize("stored, exported", [
    ("3.0.2", "v3.0.2"), ("v3.0.2", "v3.0.2"), (None, "v3.1.0"), ("", "v3.1.0"),
])
def test_the_export_writes_the_odcs_spelling_of_a_stored_value(
    manager, db_session, stored, exported,
):
    """A row stored before the spelling fix ('3.0.2') exports as a valid ODCS apiVersion."""
    assert _export(manager, db_session, stored)["apiVersion"] == exported


def test_the_export_reads_a_stored_version_without_v_as_v3_1_0_for_the_team_object(
    manager, db_session,
):
    """'3.1.0' stored without its "v" gets the v3.1.0 team object, as 'v3.1.0' does."""
    exported = _export(manager, db_session, "3.1.0", with_team=True)

    assert exported["apiVersion"] == "v3.1.0"
    assert exported["team"]["name"] == "Orders team"
