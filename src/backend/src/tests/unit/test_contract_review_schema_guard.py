"""Unit tests for the 'schema required before review' guard (ONT-NEG-005).

An empty draft contract (no schema objects) could previously be proposed for
review (request-review returned 200, status -> proposed). It must now be
blocked and left in draft.
"""
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _draft(db_session: Session) -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name="C", version="1.0.0", status="draft"))
    db_session.commit()
    return cid


class TestRequireSchemaBeforeReview:
    def test_empty_draft_cannot_be_proposed(self, db_session: Session):
        manager = _manager()
        cid = _draft(db_session)

        with pytest.raises(ValueError, match="schema is required"):
            manager.request_steward_review(
                db=db_session,
                notifications_manager=MagicMock(),
                contract_id=cid,
                requester_email="producer@example.com",
            )

        # State must remain draft — the failed guard must not transition it.
        contract = db_session.query(DataContractDb).filter_by(id=cid).one()
        assert contract.status == "draft"

    def test_draft_with_schema_can_be_proposed(self, db_session: Session):
        manager = _manager()
        cid = _draft(db_session)
        db_session.add(
            SchemaObjectDb(id=str(uuid.uuid4()), contract_id=cid, name="orders")
        )
        db_session.commit()

        result = manager.request_steward_review(
            db=db_session,
            notifications_manager=MagicMock(),
            contract_id=cid,
            requester_email="producer@example.com",
        )
        assert result["status"] == "proposed"
