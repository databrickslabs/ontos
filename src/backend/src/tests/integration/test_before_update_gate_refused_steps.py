"""A before_update gate of [Publish] then [a failing check] leaves the contract unpublished.

The entity action committed the publication as the gate ran, so the refused update
left the contract published (#1403 review). Saving such a gate is refused; a stored
one now fails at the entity action.
"""
import json
import uuid
from datetime import datetime

from src.common.workflow_executor import EntityActionStepHandler
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb

PUBLISH = {'action': 'publish', 'scope_source': 'fixed', 'fixed_scope': 'organization'}


def _publish_then_check_gate(db_session):
    """A stored gate (saved before the refusal): publish, then a policy check that fails."""
    now = datetime.utcnow()
    policy_id, wf_id = str(uuid.uuid4()), str(uuid.uuid4())
    db_session.add(CompliancePolicyDb(
        id=policy_id, name='Never', rule="MATCH (c:data_contract) ASSERT c.name = 'never'",
        is_active=True,
    ))
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'gate-{wf_id[:8]}', description='gate',
        trigger_config=json.dumps({'type': 'before_update', 'entity_types': ['data_contract']}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='publish', name='Publish',
        step_type='entity_action', on_pass='check', order=0, created_at=now, updated_at=now,
        config=json.dumps(PUBLISH),
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='check', name='Check',
        step_type='policy_check', config=json.dumps({'policy_id': policy_id}), order=1,
        created_at=now, updated_at=now,
    ))
    db_session.commit()


def test_a_refused_update_leaves_the_contract_unpublished(client, db_session, monkeypatch):
    _publish_then_check_gate(db_session)
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='Gated', version='1.0.0', status='active',
        created_by='u@example.com',
    )
    db_session.add(contract)
    db_session.commit()
    # The refused request rolls back the test's shared session, a commit of the
    # step with it: record the publications instead
    published = []
    publish = EntityActionStepHandler._handle_publication

    def publishing(self, entity_type, entity_id, context):
        published.append(entity_id)
        return publish(self, entity_type, entity_id, context)

    monkeypatch.setattr(EntityActionStepHandler, '_handle_publication', publishing)

    refused = client.put(
        f'/api/data-contracts/{contract.id}', json={'description': {'usage': 'changed'}},
        headers={'X-Force-Update': 'true'},
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()['detail']['message'] == 'Pre-update validation failed'
    assert published == []


def test_saving_a_before_update_gate_with_an_entity_action_is_refused(client, db_session):
    body = {
        'name': f'Publish gate {uuid.uuid4().hex[:6]}',
        'trigger': {'type': 'before_update', 'entity_types': ['data_contract']},
        'is_active': False,
        'steps': [{
            'step_id': 'publish', 'name': 'Publish', 'step_type': 'entity_action',
            'config': PUBLISH, 'order': 0,
        }],
    }

    created = client.post('/api/workflows', json=body)

    assert created.status_code == 400, created.text
    issues = created.json()['detail']['params']['issues']
    assert [(i['code'], i['params']) for i in issues] == [
        ('update_gate_entity_action', {'step': 'publish'}),
    ]
    assert db_session.query(ProcessWorkflowDb).filter_by(name=body['name']).count() == 0
