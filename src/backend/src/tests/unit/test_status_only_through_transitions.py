"""A product's or contract's status changes only through a transition.

``PUT`` stored the ``status`` of the body directly, so it went around
``transition_status``: the allowed transitions, the ``before_status_change``
gates and, with the lifecycle fields, the deprecation reason. An update may
now only repeat the stored status (``status_change_requires_transition``).
A new entity starts in one of the lifecycle statuses, and ``certified`` is not
one (certification is ``certification_level``). The status change request
maps are the lifecycle maps, and an approved contract request goes through
``transition_status`` like a product's.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.common.api_errors import coded_http_exception_handler
from src.common.lifecycle_status import (
    CONTRACT_STATUSES,
    PRODUCT_STATUSES,
    CertifiedIsNotAStatusError,
    InvalidStatusError,
    StatusChangeRequiresTransitionError,
    check_status_unchanged,
    normalize_new_status,
)
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.models.lifecycle import DATA_CONTRACT_TRANSITIONS, DATA_PRODUCT_TRANSITIONS


@pytest.fixture
def product_manager(db_session: Session) -> DataProductsManager:
    mgr = DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


@pytest.fixture
def contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _product(db_session, status='active', certification_level=None) -> str:
    pid = str(uuid.uuid4())
    db_session.add(DataProductDb(
        id=pid, name=f'Product {pid[:8]}', version='1.0.0', status=status,
        api_version='v1.0.0', kind='DataProduct', certification_level=certification_level,
    ))
    db_session.commit()
    return pid


def _contract(db_session, status='active', certification_level=None) -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(
        id=cid, name=f'Contract {cid[:8]}', version='1.0.0', status=status,
        certification_level=certification_level,
    ))
    db_session.commit()
    return cid


class TestChecks:
    def test_an_update_may_repeat_the_stored_status_in_any_case(self):
        check_status_unchanged('active', 'active')
        check_status_unchanged('active', 'ACTIVE')
        check_status_unchanged('active', None)
        check_status_unchanged(None, 'draft')

    def test_an_update_that_changes_the_status_is_refused_with_both_statuses(self):
        with pytest.raises(StatusChangeRequiresTransitionError) as err:
            check_status_unchanged('active', 'deprecated')
        assert err.value.code == 'status_change_requires_transition'
        assert err.value.params == {'fromStatus': 'active', 'toStatus': 'deprecated'}
        assert 'change-status' in str(err.value)

    def test_a_new_entity_starts_in_a_lifecycle_status(self):
        assert normalize_new_status(None, PRODUCT_STATUSES) == 'draft'
        assert normalize_new_status('Active', PRODUCT_STATUSES) == 'active'
        assert normalize_new_status('sandbox', PRODUCT_STATUSES) == 'sandbox'

    def test_certified_is_not_a_status(self):
        with pytest.raises(CertifiedIsNotAStatusError) as err:
            normalize_new_status('certified', PRODUCT_STATUSES)
        assert err.value.code == 'certified_is_not_a_status'

    def test_an_unknown_status_is_refused_with_the_allowed_ones(self):
        with pytest.raises(InvalidStatusError) as err:
            normalize_new_status('archived', CONTRACT_STATUSES)
        assert err.value.params == {'status': 'archived', 'allowed': list(CONTRACT_STATUSES)}
        # Contracts have no sandbox
        with pytest.raises(InvalidStatusError):
            normalize_new_status('sandbox', CONTRACT_STATUSES)


class TestProductUpdate:
    def test_a_status_change_by_update_is_refused_and_nothing_is_stored(self, product_manager, db_session):
        pid = _product(db_session, status='active', certification_level=1)
        product_manager._repo = MagicMock(wraps=product_manager._repo)
        with pytest.raises(StatusChangeRequiresTransitionError):
            product_manager.update_product(
                pid, {'name': 'Renamed', 'status': 'deprecated'}, db=db_session,
            )
        product_manager._repo.update.assert_not_called()
        db_session.expire_all()
        assert db_session.query(DataProductDb).filter_by(status='deprecated').count() == 0

    def test_an_update_that_repeats_the_status_goes_through(self, product_manager, db_session):
        pid = _product(db_session, status='active')
        updated = product_manager.update_product(
            pid, {'name': 'Renamed', 'status': 'active'}, db=db_session,
        )
        assert updated.name == 'Renamed'
        assert db_session.get(DataProductDb, pid).status == 'active'


class TestProductCreate:
    def test_certified_is_refused(self, product_manager, db_session):
        with pytest.raises(CertifiedIsNotAStatusError):
            product_manager.create_product(
                {'name': 'Certified On Create', 'version': '1.0.0', 'status': 'certified'},
                db=db_session,
            )
        assert db_session.query(DataProductDb).filter_by(name='Certified On Create').first() is None

    def test_a_lifecycle_status_is_stored_lowercase(self, product_manager, db_session):
        created = product_manager.create_product(
            {'name': 'Proposed On Create', 'version': '1.0.0', 'status': 'Proposed'},
            db=db_session,
        )
        assert created.status == 'proposed'


class TestContractUpdate:
    def test_a_status_change_by_update_is_refused_and_nothing_is_stored(self, contract_manager, db_session):
        cid = _contract(db_session, status='active', certification_level=1)
        with pytest.raises(StatusChangeRequiresTransitionError):
            contract_manager.update_contract_with_relations(
                db=db_session, contract_id=cid, contract_data={'status': 'deprecated'},
            )
        db_session.expire_all()
        assert db_session.query(DataContractDb).filter_by(status='deprecated').count() == 0

    def test_an_update_that_repeats_the_status_goes_through(self, contract_manager, db_session):
        cid = _contract(db_session, status='active')
        contract_manager.update_contract_with_relations(
            db=db_session, contract_id=cid,
            contract_data={'name': 'Renamed contract', 'status': 'active'},
        )
        db_session.expire_all()
        stored = db_session.get(DataContractDb, cid)
        assert (stored.name, stored.status) == ('Renamed contract', 'active')


class TestContractCreate:
    def test_certified_is_refused(self, contract_manager, db_session):
        with pytest.raises(CertifiedIsNotAStatusError):
            contract_manager.create_contract_with_relations(
                db=db_session,
                contract_data={'name': 'Certified contract', 'version': '1.0.0', 'status': 'certified'},
            )

    def test_an_unknown_status_is_refused(self, contract_manager, db_session):
        with pytest.raises(InvalidStatusError):
            contract_manager.create_contract_with_relations(
                db=db_session,
                contract_data={'name': 'Archived contract', 'version': '1.0.0', 'status': 'archived'},
            )


class TestStatusChangeRequests:
    @pytest.mark.parametrize('status', list(DATA_PRODUCT_TRANSITIONS))
    def test_a_product_request_offers_the_lifecycle_transitions(self, product_manager, status):
        targets = [t['target'] for t in product_manager._get_allowed_status_transitions(status)]
        assert targets == DATA_PRODUCT_TRANSITIONS[status]
        assert 'certified' not in targets

    @pytest.mark.parametrize('status', list(DATA_CONTRACT_TRANSITIONS))
    def test_a_contract_request_offers_the_lifecycle_transitions(self, contract_manager, status):
        assert contract_manager._get_allowed_status_transitions(status) == DATA_CONTRACT_TRANSITIONS[status]

    def test_a_certified_status_has_no_transition(self, product_manager, contract_manager):
        assert product_manager._get_allowed_status_transitions('certified') == []
        assert contract_manager._get_allowed_status_transitions('certified') == []

    def test_an_approved_contract_request_goes_through_transition_status(self, contract_manager, db_session):
        cid = _contract(db_session, status='draft')
        calls = []
        real = contract_manager.transition_status

        def recording(**kwargs):
            calls.append(kwargs)
            return real(**kwargs)

        contract_manager.transition_status = recording
        result = contract_manager.handle_status_change_response(
            db=db_session, notifications_manager=MagicMock(), contract_id=cid,
            approver_email='steward@example.com', decision='approve', target_status='proposed',
            requester_email='producer@example.com', current_user='steward',
        )
        assert calls and calls[0]['new_status'] == 'proposed'
        assert result['status'] == 'proposed'

    def test_a_blocking_gate_stops_an_approved_contract_request(self, contract_manager, db_session, monkeypatch):
        from src.common import workflow_triggers

        from src.common.workflow_triggers import StatusChangeBlockedError

        cid = _contract(db_session, status='draft')
        registry = MagicMock()
        registry.before_status_change.return_value = (False, [])
        monkeypatch.setattr(workflow_triggers, 'get_trigger_registry', lambda db: registry)
        with pytest.raises(StatusChangeBlockedError):
            contract_manager.handle_status_change_response(
                db=db_session, notifications_manager=MagicMock(), contract_id=cid,
                approver_email='steward@example.com', decision='approve', target_status='proposed',
                requester_email='producer@example.com', current_user='steward',
            )
        db_session.expire_all()
        assert db_session.get(DataContractDb, cid).status == 'draft'


class TestApiDetail:
    def test_the_ui_gets_the_code_and_both_statuses(self):
        app = FastAPI()
        app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)

        @app.put('/x')
        def update():
            try:
                check_status_unchanged('active', 'deprecated')
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

        response = TestClient(app).put('/x')
        assert response.status_code == 400
        detail = response.json()['detail']
        assert detail['code'] == 'status_change_requires_transition'
        assert detail['params'] == {'fromStatus': 'active', 'toStatus': 'deprecated'}


class TestMcpUpdateTools:
    """The MCP update tools change the status through transition_status too."""

    @staticmethod
    def _ctx(db_session, product_manager=None, contract_manager=None):
        from src.tools.base import ToolContext

        return ToolContext(
            db=db_session, settings=MagicMock(),
            data_products_manager=product_manager, data_contracts_manager=contract_manager,
        )

    def test_a_product_status_change_is_a_transition(self, product_manager, db_session):
        import asyncio
        from src.tools.data_products import UpdateDataProductTool

        pid = _product(db_session, status='draft')
        result = asyncio.run(UpdateDataProductTool().execute(
            self._ctx(db_session, product_manager=product_manager), product_id=pid, status='active',
        ))
        # draft -> active is not a lifecycle transition (draft -> proposed -> ...)
        assert result.success is False
        assert 'Invalid status transition' in result.error
        assert result.error_code == 'invalid_status_transition'
        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).status == 'draft'

        result = asyncio.run(UpdateDataProductTool().execute(
            self._ctx(db_session, product_manager=product_manager), product_id=pid,
            status='proposed', description='Now proposed',
        ))
        assert result.success is True, result.error
        db_session.expire_all()
        assert db_session.get(DataProductDb, pid).status == 'proposed'

    def test_a_contract_status_change_outside_the_lifecycle_is_refused(
        self, contract_manager, db_session,
    ):
        import asyncio
        from src.tools.data_contracts import UpdateDataContractTool

        cid = _contract(db_session, status='draft')
        result = asyncio.run(UpdateDataContractTool().execute(
            self._ctx(db_session, contract_manager=contract_manager), contract_id=cid,
            status='active',
        ))
        assert result.success is False
        assert result.error_code == 'invalid_status_transition'
        assert "from 'draft' to 'active'" in result.error
        db_session.expire_all()
        assert db_session.get(DataContractDb, cid).status == 'draft'

    def test_a_blocking_gate_stops_a_contract_status_change(self, contract_manager, db_session, monkeypatch):
        import asyncio
        from src.common import workflow_triggers
        from src.tools.data_contracts import UpdateDataContractTool

        cid = _contract(db_session, status='draft')
        registry = MagicMock()
        registry.before_status_change.return_value = (False, [])
        monkeypatch.setattr(workflow_triggers, 'get_trigger_registry', lambda db: registry)
        result = asyncio.run(UpdateDataContractTool().execute(
            self._ctx(db_session, contract_manager=contract_manager), contract_id=cid, status='proposed',
        ))
        assert result.success is False
        # The workflow's coded refusal, not the exception class (#1143)
        assert result.error_code == 'status_change_blocked'
        assert 'blocked by workflow' in result.error
        db_session.expire_all()
        assert db_session.get(DataContractDb, cid).status == 'draft'
