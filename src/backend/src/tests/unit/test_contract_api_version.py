"""A contract's apiVersion is an ODCS version.

``DataContractCreate`` now reads ``apiVersion`` by name, so a client value is
stored instead of the default. A version without its "v" ('3.0.2', as the
inline create dialog sent) is normalized; a new contract with a value outside
the ODCS enum is refused with the code ``odcs_api_version_unsupported``. An
update may send back the stored value, even an invalid one, but may not change
it to one.
"""
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.common.odcs_versions import UnsupportedOdcsApiVersionError
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.models.data_contracts_api import DataContractCreate, DataContractUpdate


@pytest.mark.parametrize("model", [DataContractCreate, DataContractUpdate])
@pytest.mark.parametrize("sent, stored", [
    ("v3.1.0", "v3.1.0"), ("3.0.2", "v3.0.2"), (" V3.0.1 ", "v3.0.1"), ("v2.2.2", "v2.2.2"),
])
def test_api_version_is_normalized(model, sent, stored):
    assert model.model_validate({"name": "Orders", "apiVersion": sent}).apiVersion == stored


@pytest.mark.parametrize("sent", ["9.9.9", "latest", ""])
def test_a_new_contract_outside_odcs_is_refused(sent):
    with pytest.raises(ValidationError) as err:
        DataContractCreate.model_validate({"name": "Orders", "apiVersion": sent})
    [error] = err.value.errors()
    assert error["type"] == "odcs_api_version_unsupported"
    assert error["ctx"] == {"api_version": sent}


def test_api_version_defaults_and_keeps_alias():
    assert DataContractCreate.model_validate({"name": "Orders"}).apiVersion == "v3.1.0"
    assert DataContractCreate.model_validate(
        {"name": "Orders", "api_version": "3.0.2"}).apiVersion == "v3.0.2"
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


def test_the_update_route_answers_with_the_code_and_param():
    """The PUT route raises HTTPException(400, str(e)) from the coded error, as for a
    status change; the app's handler sends the code and params along."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from src.common.api_errors import CodedValueError, coded_http_exception_handler
    from src.common.odcs_versions import check_api_version_change

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
