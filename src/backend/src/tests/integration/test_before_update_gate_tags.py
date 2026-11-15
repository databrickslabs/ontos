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
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb


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


def _tag_then_check_gate(db_session, rule):
    """An active before_update gate: assign the gate/reviewed tag, then a policy check."""
    now = datetime.utcnow()
    namespace = TagNamespaceDb(name=f'gate-{uuid.uuid4().hex[:6]}')
    db_session.add(namespace)
    db_session.flush()
    tag = TagDb(name='reviewed', namespace_id=namespace.id, status='active')
    db_session.add(tag)
    policy_id, wf_id = str(uuid.uuid4()), str(uuid.uuid4())
    db_session.add(CompliancePolicyDb(id=policy_id, name='Check', rule=rule, is_active=True))
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'gate-{wf_id[:8]}', description='gate',
        trigger_config=json.dumps({'type': 'before_update', 'entity_types': ['data_contract']}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='tag', name='Tag',
        step_type='assign_tag', on_pass='check', order=0, created_at=now, updated_at=now,
        config=json.dumps({'key': f'{namespace.name}/reviewed', 'value': 'yes'}),
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='check', name='Check',
        step_type='policy_check', config=json.dumps({'policy_id': policy_id}), order=1,
        created_at=now, updated_at=now,
    ))
    db_session.commit()
    return tag.id


def _contract_tags(db_session, contract_id, tag_id):
    db_session.expire_all()
    return db_session.query(EntityTagAssociationDb).filter_by(
        entity_id=contract_id, entity_type='data_contract', tag_id=tag_id,
    ).all()


def _new_contract(client):
    created = client.post('/api/data-contracts', json={
        'name': 'Gated', 'version': '1.0.0', 'status': 'draft',
        'description': {'purpose': 'p', 'usage': 'u'},
    })
    assert created.status_code in (200, 201), created.text
    return created.json()['id']


@pytest.fixture
def tag_writes(monkeypatch):
    """The tag assignments written (and committed) through TagsManager.add_tag_to_entity.

    The test session rolls a request back with everything it committed, so the table
    alone can't show a write the request committed before it failed.
    """
    from src.controller.tags_manager import TagsManager

    writes = []
    original = TagsManager.add_tag_to_entity

    def recording(self, db, **kwargs):
        writes.append((kwargs['entity_id'], kwargs['assigned_value']))
        return original(self, db, **kwargs)

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', recording)
    return writes


def test_a_blocked_update_leaves_no_tag_from_an_assign_tag_step(client, db_session, tag_writes):
    tag_id = _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'never'")
    contract_id = _new_contract(client)

    blocked = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    assert blocked.status_code == 400
    assert blocked.json()['detail']['message'] == 'Pre-update validation failed'
    # Before, the step wrote (and committed) the tag before the policy check blocked
    assert tag_writes == []
    assert _contract_tags(db_session, contract_id, tag_id) == []


def test_an_update_that_passes_the_gate_gets_the_tag_of_its_assign_tag_step(
    client, db_session, tag_writes,
):
    tag_id = _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Renamed'")
    contract_id = _new_contract(client)

    passed = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    assert passed.status_code == 200, passed.text
    assert tag_writes == [(contract_id, 'yes')]
    assert [t.assigned_value for t in _contract_tags(db_session, contract_id, tag_id)] == ['yes']
