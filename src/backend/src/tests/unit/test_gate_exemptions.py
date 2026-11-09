"""A status gate can be switched off per domain, data product or data contract (part of #1114).

A ``before_status_change`` workflow's trigger has ``disabled_for`` with
domain, data product and data contract ids. The gate is skipped for a listed
entity and for a product or contract assigned to a listed domain; the skip is
logged and audited. Other entities are gated as before.

The gates are real workflows run by the real executor.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.common.workflow_triggers import (
    GateEvaluationError,
    StatusChangeBlockedError,
    run_status_gates,
)
from src.controller import audit_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.models.process_workflows import (
    EntityType,
    GateExemptions,
    ProcessWorkflowCreate,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)


def _gate(db_session, name, *, disabled_for=None, on_error=None):
    """An active before_status_change workflow whose only step fails (it always blocks)."""
    trigger = {'type': 'before_status_change', 'entity_types': ['data_product', 'data_contract']}
    if disabled_for is not None:
        trigger['disabled_for'] = disabled_for
    if on_error:
        trigger['on_error'] = on_error
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=name, description='gate', trigger_config=json.dumps(trigger),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db_session.flush()
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='gate', name='Gate', step_type='fail',
        config=json.dumps({'message': 'The gate says no'}), order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


def _domain(db_session, name) -> str:
    did = str(uuid.uuid4())
    db_session.add(DataDomain(id=did, name=f'{name} {did[:6]}', created_by='admin@example.com'))
    db_session.commit()
    return did


def _assign(db_session, entity_type, entity_id, domain_id, primary=True):
    db_session.add(EntityDomainAssociationDb(
        domain_id=domain_id, entity_type=entity_type, entity_id=entity_id, is_primary=primary,
    ))
    db_session.commit()


def _product(db_session, domain_id=None) -> str:
    pid = str(uuid.uuid4())
    db_session.add(DataProductDb(
        id=pid, name=f'Product {pid[:8]}', version='1.0.0', status='draft',
        api_version='v1.0.0', kind='DataProduct',
    ))
    db_session.commit()
    if domain_id:
        _assign(db_session, 'data_product', pid, domain_id)
    return pid


def _contract(db_session, domain_id=None) -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=f'Contract {cid[:8]}', version='1.0.0', status='draft'))
    db_session.commit()
    if domain_id:
        _assign(db_session, 'data_contract', cid, domain_id)
    return cid


def _status(db_session, model, eid):
    db_session.expire_all()
    return db_session.get(model, eid).status


@pytest.fixture
def audited(monkeypatch):
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    return entries


@pytest.fixture
def product_manager(db_session) -> DataProductsManager:
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


class TestProducts:
    def test_a_gate_switched_off_for_a_domain_skips_its_products_only(
        self, product_manager, db_session, audited, caplog,
    ):
        sales, finance = _domain(db_session, 'Sales'), _domain(db_session, 'Finance')
        _gate(db_session, 'Enforcement gate', disabled_for={'domains': [sales]})
        in_sales, in_finance = _product(db_session, sales), _product(db_session, finance)

        caplog.set_level(logging.INFO)
        product_manager.transition_status(in_sales, 'proposed', current_user='owner@example.com')
        assert _status(db_session, DataProductDb, in_sales) == 'proposed'

        with pytest.raises(StatusChangeBlockedError):
            product_manager.transition_status(in_finance, 'proposed')
        assert _status(db_session, DataProductDb, in_finance) == 'draft'

        assert [e['action'] for e in audited] == ['GATE_SKIPPED']
        skip = audited[0]
        assert skip['success'] is True
        assert skip['username'] == 'owner@example.com'
        assert skip['details']['entity_id'] == in_sales
        assert skip['details']['workflow_name'] == 'Enforcement gate'
        assert skip['details']['disabled_for'] == {'kind': 'domain', 'id': sales}
        assert any(
            r.levelno == logging.INFO and 'skipped' in r.getMessage() and 'Enforcement gate' in r.getMessage()
            for r in caplog.records
        )

    def test_any_of_the_products_domains_counts(self, product_manager, db_session, audited):
        sales, finance = _domain(db_session, 'Sales'), _domain(db_session, 'Finance')
        _gate(db_session, 'Enforcement gate', disabled_for={'domains': [finance]})
        pid = _product(db_session, sales)
        _assign(db_session, 'data_product', pid, finance, primary=False)
        product_manager.transition_status(pid, 'proposed')
        assert _status(db_session, DataProductDb, pid) == 'proposed'

    def test_a_gate_switched_off_for_one_product(self, product_manager, db_session, audited):
        exempt, other = _product(db_session), _product(db_session)
        _gate(db_session, 'Enforcement gate', disabled_for={'data_products': [exempt]})
        product_manager.transition_status(exempt, 'proposed')
        assert _status(db_session, DataProductDb, exempt) == 'proposed'
        with pytest.raises(StatusChangeBlockedError):
            product_manager.transition_status(other, 'proposed')
        assert audited[0]['details']['disabled_for'] == {'kind': 'data_product', 'id': exempt}

    def test_only_the_switched_off_gate_is_skipped(self, product_manager, db_session, audited):
        sales = _domain(db_session, 'Sales')
        _gate(db_session, 'Enforcement gate', disabled_for={'domains': [sales]})
        _gate(db_session, 'Certification gate')
        pid = _product(db_session, sales)
        with pytest.raises(StatusChangeBlockedError) as err:
            product_manager.transition_status(pid, 'proposed')
        assert [r['workflow'] for r in err.value.params['reasons']] == ['Certification gate']

    def test_a_contract_id_does_not_switch_off_a_product(self, product_manager, db_session, audited):
        pid = _product(db_session)
        _gate(db_session, 'Enforcement gate', disabled_for={'data_contracts': [pid]})
        with pytest.raises(StatusChangeBlockedError):
            product_manager.transition_status(pid, 'proposed')
        assert audited == []


class TestContracts:
    def test_a_gate_switched_off_for_a_domain_skips_its_contracts_only(
        self, contract_manager, db_session, audited,
    ):
        sales, finance = _domain(db_session, 'Sales'), _domain(db_session, 'Finance')
        _gate(db_session, 'Enforcement gate', disabled_for={'domains': [sales]})
        in_sales, in_finance = _contract(db_session, sales), _contract(db_session, finance)
        contract_manager.transition_status(db_session, in_sales, 'proposed', current_user='owner@example.com')
        assert _status(db_session, DataContractDb, in_sales) == 'proposed'
        with pytest.raises(StatusChangeBlockedError):
            contract_manager.transition_status(db_session, in_finance, 'proposed')
        assert _status(db_session, DataContractDb, in_finance) == 'draft'
        assert audited[0]['details']['disabled_for'] == {'kind': 'domain', 'id': sales}
        assert audited[0]['details']['entity_type'] == 'data_contract'

    def test_a_gate_switched_off_for_one_contract(self, contract_manager, db_session, audited):
        exempt, other = _contract(db_session), _contract(db_session)
        _gate(db_session, 'Enforcement gate', disabled_for={'data_contracts': [exempt]})
        contract_manager.transition_status(db_session, exempt, 'proposed')
        assert _status(db_session, DataContractDb, exempt) == 'proposed'
        with pytest.raises(StatusChangeBlockedError):
            contract_manager.transition_status(db_session, other, 'proposed')


class TestWithGateErrors:
    """The switch also applies when the gates can't be listed (the fail_closed fallback, #1103)."""

    @pytest.fixture
    def listing_raises(self, monkeypatch):
        def boom(self, *args, **kwargs):
            raise RuntimeError('could not list the gates')
        monkeypatch.setattr(WorkflowsManager, 'get_workflows_for_trigger', boom)

    def _run(self, db_session, entity_id):
        run_status_gates(
            db_session, entity_type=EntityType.DATA_PRODUCT, entity_id=entity_id,
            from_status='draft', to_status='proposed', entity_name='P', user_email='u@example.com',
        )

    def test_a_switched_off_fail_closed_gate_does_not_refuse(self, db_session, listing_raises, audited):
        sales = _domain(db_session, 'Sales')
        _gate(db_session, 'Enforcement gate', on_error='fail_closed', disabled_for={'domains': [sales]})
        self._run(db_session, _product(db_session, sales))  # proceeds

    def test_a_fail_closed_gate_still_refuses_elsewhere(self, db_session, listing_raises, audited):
        sales = _domain(db_session, 'Sales')
        _gate(db_session, 'Enforcement gate', on_error='fail_closed', disabled_for={'domains': [sales]})
        with pytest.raises(GateEvaluationError):
            self._run(db_session, _product(db_session))

    def test_a_gate_that_errors_while_switched_off_is_skipped_before_it_runs(
        self, product_manager, db_session, audited, monkeypatch,
    ):
        def execute(self, workflow, *args, **kwargs):
            raise RuntimeError('should not run')
        monkeypatch.setattr(WorkflowExecutor, 'execute_workflow', execute)
        sales = _domain(db_session, 'Sales')
        _gate(db_session, 'Enforcement gate', on_error='fail_closed', disabled_for={'domains': [sales]})
        pid = _product(db_session, sales)
        product_manager.transition_status(pid, 'proposed')
        assert _status(db_session, DataProductDb, pid) == 'proposed'
        assert [e['action'] for e in audited] == ['GATE_SKIPPED']


class TestSetting:
    def _create(self, mgr, trigger_type, disabled_for):
        workflow = ProcessWorkflowCreate(
            name='Enforcement gate', is_active=True,
            trigger=WorkflowTrigger(
                type=trigger_type, entity_types=[EntityType.DATA_PRODUCT],
                disabled_for=GateExemptions(**disabled_for),
            ),
            steps=[WorkflowStepCreate(step_id='ok', name='OK', step_type='pass', config={}, order=0)],
        )
        return workflow, mgr.validate_workflow(workflow)

    def test_disabled_for_is_stored_with_the_trigger_and_defaults_to_nothing(self, db_session):
        mgr = WorkflowsManager(db_session)
        sales = _domain(db_session, 'Sales')
        pid = _product(db_session)
        workflow, validation = self._create(
            mgr, TriggerType.BEFORE_STATUS_CHANGE, {'domains': [sales], 'data_products': [pid]},
        )
        assert validation.valid, validation.errors
        created = mgr.create_workflow(workflow)
        stored = mgr.get_workflow(created.id).trigger.disabled_for
        assert stored.domains == [sales] and stored.data_products == [pid] and stored.data_contracts == []
        raw = json.loads(db_session.get(ProcessWorkflowDb, created.id).trigger_config)
        assert raw['disabled_for']['domains'] == [sales]
        # A workflow saved before the setting existed has no key: nothing is switched off
        old_id = _gate(db_session, 'Old gate')
        assert mgr.get_workflow(old_id).trigger.disabled_for.is_empty()

    def test_unknown_ids_are_refused(self, db_session):
        _, validation = self._create(
            WorkflowsManager(db_session), TriggerType.BEFORE_STATUS_CHANGE,
            {'domains': ['no-such-domain'], 'data_contracts': ['no-such-contract']},
        )
        assert not validation.valid
        assert "disabled_for: unknown domain 'no-such-domain'" in validation.errors
        assert "disabled_for: unknown data contract 'no-such-contract'" in validation.errors

    def test_refused_exemptions_carry_a_code_and_params(self, db_session):
        """The messages stay English strings and also carry a code for clients."""
        mgr = WorkflowsManager(db_session)
        workflow, _ = self._create(
            mgr, TriggerType.BEFORE_STATUS_CHANGE,
            {'domains': ['no-such-domain'], 'data_contracts': ['no-such-contract']},
        )
        errors = mgr._validate_gate_exemptions(workflow.trigger)
        assert [(e.code, e.params) for e in errors] == [
            ('gate_exemption_not_found', {'kind': 'domain', 'id': 'no-such-domain'}),
            ('gate_exemption_not_found', {'kind': 'data_contract', 'id': 'no-such-contract'}),
        ]
        assert errors[0] == "disabled_for: unknown domain 'no-such-domain'"
        sales = _domain(db_session, 'Sales')
        workflow, _ = self._create(mgr, TriggerType.ON_CREATE, {'domains': [sales]})
        errors = mgr._validate_gate_exemptions(workflow.trigger)
        assert [(e.code, e.params) for e in errors] == [
            ('gate_exemptions_wrong_trigger', {'triggerType': 'on_create'}),
        ]

    def test_only_status_gates_can_be_switched_off(self, db_session):
        sales = _domain(db_session, 'Sales')
        _, validation = self._create(WorkflowsManager(db_session), TriggerType.ON_CREATE, {'domains': [sales]})
        assert not validation.valid
        assert any('before_status_change' in e for e in validation.errors)

    def test_an_unreadable_value_switches_nothing_off(self, db_session):
        wf_id = _gate(db_session, 'Odd gate', disabled_for={'domains': 'not-a-list'})
        assert WorkflowsManager(db_session).get_workflow(wf_id).trigger.disabled_for.is_empty()
