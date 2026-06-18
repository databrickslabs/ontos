"""Unit tests for duplicate data-contract name rejection (ONT-NEG-002).

Creating a contract whose name duplicates an existing contract in the same
domain previously succeeded silently. It must now raise a ConflictError
(surfaced as HTTP 409 by the route).
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.common.errors import ConflictError
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb


def _manager():
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    # The duplicate check runs before any writes; neutralize the post-create
    # side effects so the happy-path create stays dependency-free.
    mgr._queue_delivery = lambda *a, **k: None
    mgr._update_search_index = lambda *a, **k: None
    return mgr


@pytest.fixture
def existing_contract(db_session: Session):
    cid = str(uuid.uuid4())
    db_session.add(
        DataContractDb(id=cid, name="Customer Data", version="1.0.0", status="active")
    )
    db_session.commit()
    return cid


class TestDuplicateContractName:
    def test_duplicate_name_same_domain_raises_conflict(
        self, db_session: Session, existing_contract
    ):
        manager = _manager()
        with pytest.raises(ConflictError):
            manager.create_contract_with_relations(
                db=db_session,
                contract_data={"name": "Customer Data", "version": "1.0.0"},
                current_user="alice@example.com",
            )

    def test_duplicate_name_is_case_insensitive(
        self, db_session: Session, existing_contract
    ):
        manager = _manager()
        with pytest.raises(ConflictError):
            manager.create_contract_with_relations(
                db=db_session,
                contract_data={"name": "customer DATA", "version": "1.0.0"},
                current_user="alice@example.com",
            )

    def test_distinct_name_is_allowed(self, db_session: Session, existing_contract):
        manager = _manager()
        created = manager.create_contract_with_relations(
            db=db_session,
            contract_data={"name": "Orders Data", "version": "1.0.0"},
            current_user="alice@example.com",
        )
        assert created.id is not None
        assert created.name == "Orders Data"
