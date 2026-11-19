"""A contract's apiVersion is stored in the ODCS spelling.

A version without its "v" ('3.0.2', as the inline create dialog sent) is stored as
'v3.0.2' by the create and update models, the ODCS imports and the self-service
creation. Nothing is refused: a value outside the ODCS enum is stored as sent (the
refusal is a separate, breaking change). The ODCS export writes the same spelling
for a value stored before.
"""
import uuid
from pathlib import Path

import pytest

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.models.data_contracts_api import DataContractCreate, DataContractUpdate

SPELLINGS = [
    ("v3.1.0", "v3.1.0"), ("3.0.2", "v3.0.2"), (" V3.0.1 ", "v3.0.1"), ("v2.2.2", "v2.2.2"),
]


@pytest.mark.parametrize("sent, stored", SPELLINGS)
def test_a_create_stores_the_odcs_spelling(sent, stored):
    assert DataContractCreate.model_validate(
        {"name": "Orders", "api_version": sent}).apiVersion == stored


@pytest.mark.parametrize("key", ["apiVersion", "api_version"])
@pytest.mark.parametrize("sent, stored", SPELLINGS)
def test_an_update_stores_the_odcs_spelling(key, sent, stored):
    assert DataContractUpdate.model_validate({"name": "Orders", key: sent}).apiVersion == stored


@pytest.mark.parametrize("model", [DataContractCreate, DataContractUpdate])
@pytest.mark.parametrize("sent, stored", [("9.9.9", "v9.9.9"), ("latest", "latest")])
def test_a_value_outside_odcs_is_not_refused(model, sent, stored):
    assert model.model_validate({"name": "Orders", "api_version": sent}).apiVersion == stored


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


@pytest.mark.parametrize("sent, stored", [("3.0.2", "v3.0.2"), ("v9.9.9", "v9.9.9")])
def test_an_update_stores_the_version_sent(manager, db_session, sent, stored):
    cid = _contract(db_session, "v3.1.0")

    assert _update(manager, db_session, cid, sent).api_version == stored


@pytest.mark.parametrize("sent, stored", [
    ("3.0.2", "v3.0.2"), ("v3.1.0", "v3.1.0"), (None, "v3.1.0"),
    # The import only warns about a value outside ODCS; it keeps it
    ("v9.9.9", "v9.9.9"),
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
