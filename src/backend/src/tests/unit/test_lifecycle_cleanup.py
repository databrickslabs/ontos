"""Lifecycle clean-up before configurable stages (#1212).

A contract's ``transition_status`` lowercases both statuses and is strict, as a
product's: a stored status outside the lifecycle (written before the lifecycle
clean-up) no longer allows any target. The dataset and asset transition maps,
which nothing read, are gone.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.common.api_errors import InvalidStatusTransitionError
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.models import lifecycle


@pytest.fixture
def contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _contract(db_session: Session, status: str) -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(
        id=cid, name=f'Contract {cid[:8]}', version='1.0.0', status=status,
    ))
    db_session.commit()
    return cid


class TestContractTransitionStatus:
    def test_statuses_in_any_case_are_compared_and_stored_lowercase(
        self, contract_manager, db_session,
    ):
        cid = _contract(db_session, 'Draft')
        updated = contract_manager.transition_status(
            db=db_session, contract_id=cid, new_status='PROPOSED', current_user='alice',
        )
        assert updated.status == 'proposed'

    def test_an_unknown_current_status_allows_no_target(self, contract_manager, db_session):
        cid = _contract(db_session, 'archived')
        with pytest.raises(InvalidStatusTransitionError) as err:
            contract_manager.transition_status(
                db=db_session, contract_id=cid, new_status='active', current_user='alice',
            )
        assert err.value.params['fromStatus'] == 'archived'
        assert err.value.params['allowed'] == []
        db_session.expire_all()
        assert db_session.get(DataContractDb, cid).status == 'archived'

    def test_a_target_outside_the_map_is_refused_with_the_allowed_ones(
        self, contract_manager, db_session,
    ):
        cid = _contract(db_session, 'draft')
        with pytest.raises(InvalidStatusTransitionError) as err:
            contract_manager.transition_status(
                db=db_session, contract_id=cid, new_status='active', current_user='alice',
            )
        assert err.value.params == {
            'fromStatus': 'draft', 'toStatus': 'active', 'allowed': ['proposed', 'deprecated'],
        }


def test_the_unused_dataset_and_asset_maps_are_gone():
    assert not hasattr(lifecycle, 'DATASET_TRANSITIONS')
    assert not hasattr(lifecycle, 'ASSET_TRANSITIONS')
