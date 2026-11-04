"""The data product manager's write methods fire the product workflow triggers.

Every entry point (REST routes, Ask Ontos and MCP tools, ODPS imports) changes a
product through ``DataProductsManager``, so the triggers fire there, once the
change succeeded, and not in the callers:

- ``create_product`` (POST, the tool, the ODPS upload, from-contract): ``on_create``;
- ``update_product`` (PUT, the tool): ``on_update`` with the fields sent;
- ``delete_product`` (DELETE, the tool): ``on_delete``;
- ``unpublish_product``: ``on_unpublish``; ``certify_at_level``: ``on_certify``;
  ``decertify_product``: ``on_decertify``; ``request_certification``:
  ``on_request_certify``; ``request_publication``: ``on_request_publish``;
  ``unsubscribe``: ``on_unsubscribe``;
- ``transition_status``: its blocking ``before_status_change`` gates refuse the
  change, and ``on_status_change`` fires.

A refused or failed change fires nothing.
"""
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_triggers import StatusChangeBlockedError
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
)
from src.models.process_workflows import EntityType

USER = 'sue@example.com'


@pytest.fixture
def registry():
    """The trigger registry every product trigger goes through."""
    registry = MagicMock()
    registry.on_request_publish.return_value = []
    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        yield registry


@pytest.fixture
def manager(db_session):
    products = DataProductsManager(db=db_session, ws_client=MagicMock(),
                                   notifications_manager=MagicMock(), tags_manager=MagicMock())
    products._update_search_index = lambda *a, **k: None
    return products


def _row(db, **fields):
    row = DataProductDb(**{
        'id': str(uuid.uuid4()), 'api_version': 'v1.0.0', 'kind': 'DataProduct',
        'name': 'Orders', 'version': '1.0.0', 'status': 'active',
        'draft_owner_id': USER, **fields,
    })
    db.add(row)
    db.commit()
    return row


def _odps(name, **extra):
    return {'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': str(uuid.uuid4()),
            'name': name, 'version': '0.1.0', 'status': 'draft', **extra}


def _fired(registry, trigger):
    """The keyword arguments of each call of ``trigger`` on the registry."""
    return [c.kwargs for c in getattr(registry, trigger).call_args_list]


class TestCreate:
    def test_create_product_fires_on_create_for_the_user(self, manager, db_session, registry):
        created = manager.create_product(_odps('Made'), db=db_session, user=USER)

        assert _fired(registry, 'on_create') == [{
            'entity_type': EntityType.DATA_PRODUCT, 'entity_id': created.id,
            'entity_name': 'Made', 'entity_data': {'product_id': created.id, 'name': 'Made'},
            'user_email': USER, 'blocking': False,
        }]

    def test_the_workflow_user_is_the_one_given(self, manager, db_session, registry):
        # POST /data-products stamps the username and fires for the email.
        manager.create_product(_odps('Made'), db=db_session, user='sue',
                               workflow_user=USER)

        assert [c['user_email'] for c in _fired(registry, 'on_create')] == [USER]

    def test_an_invalid_product_fires_nothing(self, manager, db_session, registry):
        with pytest.raises(ValueError):
            manager.create_product(_odps('Bad', outputPorts='not a list'),
                                   db=db_session, user=USER)
        registry.on_create.assert_not_called()

    def test_an_odps_import_fires_on_create_per_product(self, manager, registry):
        content = json.dumps([_odps('Imported A'), _odps('Imported B')]).encode()
        result = manager.create_products_from_files([('p.json', content)], user='sue',
                                                    workflow_user=USER)

        assert result.created == 2
        fired = _fired(registry, 'on_create')
        assert sorted(c['entity_id'] for c in fired) == sorted(result.created_ids)
        assert {c['user_email'] for c in fired} == {USER}

    def test_a_product_from_a_contract_fires_on_create(self, manager, db_session, registry):
        contract = DataContractDb(id=str(uuid.uuid4()), name='c', version='1.0.0',
                                  status='active', version_family_id=str(uuid.uuid4()))
        db_session.add(contract)
        db_session.commit()

        created = manager.create_from_contract(contract.id, 'From contract', '1.0.0',
                                               user_email=USER)

        assert [(c['entity_id'], c['user_email']) for c in _fired(registry, 'on_create')] \
            == [(created.id, USER)]


class TestUpdate:
    def test_update_product_fires_on_update_with_the_fields_sent(
        self, manager, db_session, registry
    ):
        row = _row(db_session)
        changes = {'description': {'purpose': 'changed'}}

        manager.update_product(row.id, dict(changes), db=db_session, user=USER)

        assert _fired(registry, 'on_update') == [{
            'entity_type': EntityType.DATA_PRODUCT, 'entity_id': row.id,
            'entity_name': 'Orders', 'entity_data': changes, 'user_email': USER,
            'blocking': False,
        }]

    def test_a_missing_product_fires_nothing(self, manager, db_session, registry):
        assert manager.update_product(str(uuid.uuid4()), {'name': 'x'}, db=db_session) is None
        registry.on_update.assert_not_called()

    def test_a_refused_update_fires_nothing(self, manager, db_session, registry):
        row = _row(db_session)
        with pytest.raises(PermissionError):
            manager.update_product_with_auth(row.id, {'name': 'x'}, 'carl@example.com', [],
                                             db=db_session)
        registry.on_update.assert_not_called()

    def test_update_with_auth_fires_for_the_owner(self, manager, db_session, registry):
        row = _row(db_session)
        manager.update_product_with_auth(row.id, {'name': 'Renamed'}, USER, [], db=db_session)
        assert [(c['entity_id'], c['user_email']) for c in _fired(registry, 'on_update')] \
            == [(row.id, USER)]


class TestDelete:
    def test_delete_product_fires_on_delete(self, manager, db_session, registry):
        row = _row(db_session)

        assert manager.delete_product(row.id, user='sue', workflow_user=USER) is True

        assert _fired(registry, 'on_delete') == [{
            'entity_type': EntityType.DATA_PRODUCT, 'entity_id': row.id,
            'entity_name': None, 'entity_data': {'product_id': row.id}, 'user_email': USER,
            'blocking': False,
        }]

    def test_a_missing_product_fires_nothing(self, manager, registry):
        assert manager.delete_product(str(uuid.uuid4()), user=USER) is False
        registry.on_delete.assert_not_called()


class TestPublicationAndCertification:
    def test_unpublish_fires_on_unpublish(self, manager, db_session, registry):
        row = _row(db_session, publication_scope='organization')

        manager.unpublish_product(row.id, USER, db=db_session)

        db_session.expire_all()
        assert db_session.get(DataProductDb, row.id).publication_scope == 'none'
        registry.on_unpublish.assert_called_once_with(
            EntityType.DATA_PRODUCT, row.id, entity_name='Orders', user_email=USER,
        )

    def test_unpublishing_an_unpublished_product_fires_nothing(
        self, manager, db_session, registry,
    ):
        row = _row(db_session, publication_scope='none')

        assert manager.unpublish_product(row.id, USER, db=db_session) is not None

        registry.on_unpublish.assert_not_called()

    def test_a_failing_on_unpublish_keeps_the_unpublish(self, manager, db_session, registry):
        row = _row(db_session, publication_scope='organization')
        registry.on_unpublish.side_effect = RuntimeError('workflow engine down')

        assert manager.unpublish_product(row.id, USER, db=db_session) is not None

        db_session.expire_all()
        assert db_session.get(DataProductDb, row.id).publication_scope == 'none'

    def test_certify_fires_on_certify(self, manager, db_session, registry):
        row = _row(db_session)

        with patch('src.controller.certification_propagator.propagate_certification'):
            manager.certify_at_level(row.id, 2, USER, notes='ok', db=db_session)

        db_session.expire_all()
        assert db_session.get(DataProductDb, row.id).certification_level == 2
        registry.on_certify.assert_called_once_with(
            EntityType.DATA_PRODUCT, row.id, entity_name='Orders',
            entity_data={'certification_level': 2, 'notes': 'ok', 'certified_by': USER},
            user_email=USER, blocking=False,
        )

    def test_decertify_fires_on_decertify(self, manager, db_session, registry):
        row = _row(db_session, certification_level=2)

        assert manager.decertify_product(row.id, USER, db=db_session) == 2

        db_session.expire_all()
        assert db_session.get(DataProductDb, row.id).certification_level is None
        registry.on_decertify.assert_called_once_with(
            EntityType.DATA_PRODUCT, row.id, entity_name='Orders', user_email=USER,
        )

    def test_request_certification_fires_on_request_certify(
        self, manager, db_session, registry
    ):
        row = _row(db_session)

        manager.request_certification(row.id, 2, 'please', USER, db=db_session)

        registry.on_request_certify.assert_called_once_with(
            EntityType.DATA_PRODUCT, row.id, entity_name='Orders',
            entity_data={'requested_certification_level': 2, 'message': 'please',
                         'requester': USER},
            user_email=USER, blocking=True,
        )

    def test_request_publication_fires_on_request_publish(
        self, manager, db_session, registry
    ):
        row = _row(db_session)

        executions = manager.request_publication(
            row.id, 'organization', 'please', USER, 'active', db=db_session,
        )

        assert executions == []
        registry.on_request_publish.assert_called_once_with(
            EntityType.DATA_PRODUCT, row.id, entity_name='Orders',
            entity_data={'requested_scope': 'organization', 'justification': 'please',
                         'requester': USER, 'current_status': 'active'},
            user_email=USER, blocking=True,
        )

    def test_unsubscribe_fires_on_unsubscribe(self, manager, db_session, registry):
        row = _row(db_session)

        manager.unsubscribe(row.id, USER, db=db_session)

        assert _fired(registry, 'on_unsubscribe') == [{
            'entity_type': EntityType.SUBSCRIPTION, 'entity_id': row.id,
            'entity_name': row.id,
            'entity_data': {'product_id': row.id, 'subscriber_email': USER},
            'user_email': USER, 'blocking': False,
        }]


def _workflow(db, trigger, *, step_type='pass', **trigger_extra):
    """An active workflow on ``trigger`` for data products, with one step."""
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db.add(ProcessWorkflowDb(
        id=wf_id, name=f'{trigger} {wf_id[:6]}', description='test',
        trigger_config=json.dumps({'type': trigger, 'entity_types': ['data_product'],
                                   **trigger_extra}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db.flush()
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='only', name='Only step',
        step_type=step_type, config='{}', on_pass=None, on_fail=None, order=0,
        created_at=now, updated_at=now,
    ))
    db.commit()
    return wf_id


def _runs(db, wf_id):
    db.expire_all()
    rows = db.query(WorkflowExecutionDb).filter_by(workflow_id=wf_id).all()
    return [(json.loads(r.trigger_context)['entity_id'], r.triggered_by) for r in rows]


class TestRealWorkflows:
    """The same, with stored workflows run by the real registry and executor."""

    def test_a_manager_create_runs_the_on_create_workflow(self, manager, db_session):
        wf = _workflow(db_session, 'on_create')
        created = manager.create_product(_odps('Made'), db=db_session, user=USER)
        assert _runs(db_session, wf) == [(created.id, USER)]

    def test_a_blocking_gate_refuses_the_status_change(self, manager, db_session):
        row = _row(db_session)
        gate = _workflow(db_session, 'before_status_change', step_type='fail',
                         from_status='active', to_status='deprecated')
        on_status = _workflow(db_session, 'on_status_change')

        with pytest.raises(StatusChangeBlockedError):
            manager.transition_status(row.id, 'deprecated', USER)

        assert len(_runs(db_session, gate)) == 1
        assert _runs(db_session, on_status) == []
        assert db_session.get(DataProductDb, row.id).status == 'active'
