"""Unit tests for requesting a steward review on a data contract.

Regression coverage for ONT-CUJ-008/ONT-CUJ-012-adjacent behaviour: after a
producer requests review, the contract must transition to ``proposed`` and be
discoverable by stewards via the approvals queue. A previous stub in
``request_steward_review`` constructed an in-memory ReviewedAsset and logged a
(false) "Created asset review record" without persisting anything; this test
pins the real surfacing path (the approvals queue) and that the call itself
does not raise.
"""
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from src.controller.approvals_manager import ApprovalsManager
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


@pytest.fixture
def draft_contract(db_session: Session):
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name="Reviewable", version="1.0.0", status="draft"))
    db_session.commit()
    return cid


class TestRequestStewardReview:
    def test_transitions_to_proposed_and_surfaces_in_approvals_queue(
        self, db_session: Session, draft_contract
    ):
        manager = _manager()
        result = manager.request_steward_review(
            db=db_session,
            notifications_manager=MagicMock(),
            contract_id=draft_contract,
            requester_email="producer@example.com",
            message="please review",
            current_user="producer@example.com",
        )
        db_session.commit()

        assert result["status"] == "proposed"

        contract = db_session.query(DataContractDb).filter_by(id=draft_contract).one()
        assert contract.status == "proposed"

        # The steward-facing surface: proposed contracts appear in the queue.
        queue = ApprovalsManager().get_approvals_queue(db_session)
        queued_ids = {c["id"] for c in queue["contracts"]}
        assert draft_contract in queued_ids

    def test_rejects_review_from_non_draft_status(self, db_session: Session):
        manager = _manager()
        cid = str(uuid.uuid4())
        db_session.add(DataContractDb(id=cid, name="Active", version="1.0.0", status="active"))
        db_session.commit()

        with pytest.raises(ValueError):
            manager.request_steward_review(
                db=db_session,
                notifications_manager=MagicMock(),
                contract_id=cid,
                requester_email="producer@example.com",
            )
