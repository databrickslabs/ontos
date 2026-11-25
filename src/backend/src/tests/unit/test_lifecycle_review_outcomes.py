"""Review outcomes, products from contracts and UC tag sync follow the Stage Category (#1213).

A workflow's review decision moves a contract to its group's approve or reject
stage and walks a reviewed product to an active-category stage, whatever the
stage keys; a product is created from an approved or active-category contract;
a move into a custom retired stage asks for a uc_tag_sync run.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.controller.lifecycle_service import lifecycle_service
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.models.process_workflows import TriggerContext, TriggerType


@pytest.fixture(autouse=True)
def fresh_cache():
    lifecycle_service.invalidate()
    yield
    lifecycle_service.invalidate()


def _stage(key, category, order, initial=False):
    return {'key': key, 'label': key.title(), 'category': category, 'color': None,
            'order': order, 'is_initial': initial}


def _two_reviews(db, entity_type):
    """``intake -> vetting -> legal -> live -> sunset``; reviews go back to intake."""
    group = lifecycle_service.save_group(db, {
        'name': f'Two reviews {entity_type}', 'description': None, 'entity_type': entity_type,
        'is_default_for_type': False,
        'stages': [_stage('intake', 'draft', 0, True), _stage('vetting', 'review', 1),
                   _stage('legal', 'review', 2), _stage('live', 'active', 3),
                   _stage('sunset', 'retired', 4)],
        'transitions': [
            {'from_key': 'intake', 'to_key': 'vetting'},
            {'from_key': 'vetting', 'to_key': 'legal'},
            {'from_key': 'vetting', 'to_key': 'intake'},
            {'from_key': 'legal', 'to_key': 'live'},
            {'from_key': 'legal', 'to_key': 'intake'},
            {'from_key': 'live', 'to_key': 'sunset'},
        ],
    }, 'admin')
    return group.id


def _product(db, status, group_id=None):
    pid = str(uuid.uuid4())
    db.add(DataProductDb(id=pid, name=f'P {pid[:8]}', version='1.0.0', status=status,
                         api_version='v1.0.0', kind='DataProduct',
                         lifecycle_stage_group_id=group_id))
    db.commit()
    return db.get(DataProductDb, pid)


def _contract(db, status, group_id=None):
    cid = str(uuid.uuid4())
    db.add(DataContractDb(id=cid, name=f'C {cid[:8]}', version='1.0.0', status=status,
                          lifecycle_stage_group_id=group_id))
    db.commit()
    return cid


def _context(entity_type, entity_id):
    return TriggerContext(
        entity_type=entity_type, entity_id=entity_id, entity_name='x',
        trigger_type=TriggerType.ON_REQUEST_REVIEW, user_email='producer@example.com',
    )


def test_the_default_review_walk_is_the_seeded_one(db_session):
    product = _product(db_session, 'proposed')
    assert lifecycle_service.review_activation_steps(db_session, 'data_product', product) == [
        'under_review', 'approved', 'active',
    ]


@pytest.mark.parametrize('succeeded,expected', [(True, 'live'), (False, 'intake')])
def test_a_reviewed_product_in_a_custom_group_follows_its_categories(
    db_session, succeeded, expected,
):
    product = _product(db_session, 'vetting', _two_reviews(db_session, 'data_product'))
    WorkflowExecutor(db_session)._apply_product_review_outcome(
        _context('data_product', product.id), product.id, succeeded, 'steward@example.com',
    )
    db_session.expire_all()
    assert db_session.get(DataProductDb, product.id).status == expected


@pytest.mark.parametrize('approved,expected', [(True, 'legal'), (False, 'intake')])
def test_a_contract_review_decision_in_a_custom_group(db_session, monkeypatch, approved, expected):
    from src.controller import data_contracts_manager as dcm

    cid = _contract(db_session, 'vetting', _two_reviews(db_session, 'data_contract'))
    real = dcm.DataContractsManager.__new__(dcm.DataContractsManager)
    monkeypatch.setattr(dcm, 'get_live_contracts_manager', lambda: real)
    # The manager's own transition (gates, triggers) is tested elsewhere: move it
    monkeypatch.setattr(real, 'transition_status', lambda **kw: _move(
        db_session, kw['contract_id'], kw['new_status']), raising=False)
    WorkflowExecutor(db_session)._apply_contract_review_decision(
        _context('data_contract', cid), cid, approved, 'steward@example.com',
    )
    db_session.expire_all()
    assert db_session.get(DataContractDb, cid).status == expected


def _move(db, contract_id, new_status):
    row = db.get(DataContractDb, contract_id)
    lifecycle_service.check_transition(db, 'data_contract', row, new_status)
    row.status = new_status
    db.commit()


def test_a_product_is_created_from_an_active_category_contract(db_session):
    from src.controller.data_products_manager import DataProductsManager

    group_id = _two_reviews(db_session, 'data_contract')
    mgr = DataProductsManager(db=db_session, ws_client=MagicMock(),
                              notifications_manager=MagicMock(), tags_manager=MagicMock())
    mgr._update_search_index = lambda *a, **k: None
    live = _contract(db_session, 'live', group_id)
    assert mgr.create_from_contract(live, 'From live', '1.0.0').name == 'From live'
    vetting = _contract(db_session, 'vetting', group_id)
    with pytest.raises(ValueError, match='approved or active'):
        mgr.create_from_contract(vetting, 'From vetting', '1.0.0')


def test_a_move_into_a_custom_retired_stage_requests_a_uc_tag_sync(db_session, monkeypatch):
    from src.common import uc_tag_sync_trigger as trigger

    _two_reviews(db_session, 'data_product')  # warms the cache with 'sunset'
    jobs = SimpleNamespace(run_workflow_unless_pending=MagicMock(return_value=7))
    monkeypatch.setattr(trigger, 'get_app_state_manager', lambda name: jobs)
    assert trigger.request_uc_tag_sync_after_transition('data_product', 'p', 'live', 'sunset') == 7
    assert trigger.request_uc_tag_sync_after_transition('data_product', 'p', 'intake', 'live') \
        is None
