"""A before_update policy gate on PUT /api/data-contracts/{id} sees the tags after the update.

The gate's ASSERT used to see only the request, so an update that didn't send tags
was checked as if the contract had none.
"""
import json
import uuid
from datetime import datetime

import pytest

from src.db_models.compliance import CompliancePolicyDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb


@pytest.fixture
def pii_gate(db_session):
    """An active before_update gate on contracts: they must keep the pii tag."""
    now = datetime.utcnow()
    policy_id, wf_id = str(uuid.uuid4()), str(uuid.uuid4())
    db_session.add(CompliancePolicyDb(
        id=policy_id, name='Keeps pii', rule="MATCH (c:data_contract) ASSERT HAS_TAG('pii')",
        is_active=True,
    ))
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'gate-{wf_id[:8]}', description='gate',
        trigger_config=json.dumps({'type': 'before_update', 'entity_types': ['data_contract']}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='gate', name='Gate',
        step_type='policy_check', config=json.dumps({'policy_id': policy_id}), order=0,
        created_at=now, updated_at=now,
    ))
    db_session.commit()


def test_the_gate_sees_the_stored_tags_and_an_empty_list_clears_them(client, pii_gate):
    created = client.post('/api/data-contracts', json={
        'name': 'Gated', 'version': '1.0.0', 'status': 'draft',
        'description': {'purpose': 'p', 'usage': 'u'},
    })
    assert created.status_code in (200, 201), created.text
    contract_id = created.json()['id']

    tagged = client.put(f'/api/data-contracts/{contract_id}', json={'tags': ['pii']})
    untouched = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})
    cleared = client.put(f'/api/data-contracts/{contract_id}', json={'tags': []})

    assert tagged.status_code == 200, tagged.text
    # No tags in the request: the stored pii tag stays, so the gate passes
    assert untouched.status_code == 200, untouched.text
    assert cleared.status_code == 400
    assert cleared.json()['detail']['message'] == 'Pre-update validation failed'
