"""The ODCS tag routes keep the tag assignments the contract page shows in step (#1484)."""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.tags_manager import TagsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.tags import EntityTagAssociationDb, TagDb
from src.repositories.tags_repository import tag_namespace_repo
from src.routes.data_contracts_routes import get_data_contracts_manager


def _assigned(db_session: Session, contract_id: str) -> set:
    return {
        name for (name,) in db_session.query(TagDb.name)
        .join(EntityTagAssociationDb, EntityTagAssociationDb.tag_id == TagDb.id)
        .filter(EntityTagAssociationDb.entity_type == "data_contract",
                EntityTagAssociationDb.entity_id == str(contract_id))
    }


@pytest.fixture
def contract_id(client: TestClient, db_session: Session):
    manager = DataContractsManager(data_dir=Path("/tmp"), tags_manager=TagsManager())
    app.dependency_overrides[get_data_contracts_manager] = lambda: manager
    tag_namespace_repo.get_or_create_default_namespace(db_session, user_email="test")
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=f"Route {uuid.uuid4().hex[:6]}", version="1.0.0", status="draft"))
    db_session.commit()
    yield cid
    app.dependency_overrides.pop(get_data_contracts_manager, None)


def test_a_tag_added_renamed_and_deleted_through_the_routes(client: TestClient, db_session: Session, contract_id):
    old, new = f"route_old_{uuid.uuid4().hex[:6]}", f"route_new_{uuid.uuid4().hex[:6]}"

    created = client.post(f"/api/data-contracts/{contract_id}/tags", json={"name": old})
    assert created.status_code == 201, created.text
    tag_id = created.json()["id"]
    assert _assigned(db_session, contract_id) == {old}

    renamed = client.put(f"/api/data-contracts/{contract_id}/tags/{tag_id}", json={"name": new})
    assert renamed.status_code == 200, renamed.text
    db_session.expire_all()
    assert _assigned(db_session, contract_id) == {new}

    deleted = client.delete(f"/api/data-contracts/{contract_id}/tags/{tag_id}")
    assert deleted.status_code == 204, deleted.text
    db_session.expire_all()
    assert _assigned(db_session, contract_id) == set()


def test_deleting_one_tag_keeps_the_others(client: TestClient, db_session: Session, contract_id):
    keep, drop = f"keep_{uuid.uuid4().hex[:6]}", f"drop_{uuid.uuid4().hex[:6]}"
    client.post(f"/api/data-contracts/{contract_id}/tags", json={"name": keep})
    drop_id = client.post(f"/api/data-contracts/{contract_id}/tags", json={"name": drop}).json()["id"]

    assert client.delete(f"/api/data-contracts/{contract_id}/tags/{drop_id}").status_code == 204
    db_session.expire_all()

    assert _assigned(db_session, contract_id) == {keep}
