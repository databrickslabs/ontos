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


def _tag_then_check_gate(db_session, rule, step_type='assign_tag'):
    """An active before_update gate: assign (or remove) a reviewed tag, then a policy check."""
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
        step_type=step_type, on_pass='check', order=0, created_at=now, updated_at=now,
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
    add, remove = TagsManager.add_tag_to_entity, TagsManager.remove_tag_from_entity

    def adding(self, db, **kwargs):
        writes.append((kwargs['entity_id'], kwargs['assigned_value']))
        return add(self, db, **kwargs)

    def removing(self, db, **kwargs):
        writes.append((kwargs['entity_id'], 'removed'))
        return remove(self, db, **kwargs)

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', adding)
    monkeypatch.setattr(TagsManager, 'remove_tag_from_entity', removing)
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


def test_a_blocked_update_keeps_the_tag_a_remove_tag_step_removes(client, db_session, tag_writes):
    tag_id = _tag_then_check_gate(
        db_session, "MATCH (c:data_contract) ASSERT c.name = 'never'", step_type='remove_tag',
    )
    contract_id = _new_contract(client)
    db_session.add(EntityTagAssociationDb(
        tag_id=tag_id, entity_id=contract_id, entity_type='data_contract',
    ))
    db_session.flush()

    blocked = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    assert blocked.status_code == 400
    # Before, the step removed (and committed) it before the policy check blocked
    assert tag_writes == []


def test_an_update_that_passes_the_gate_loses_the_tag_its_remove_tag_step_removes(
    client, db_session, tag_writes,
):
    tag_id = _tag_then_check_gate(
        db_session, "MATCH (c:data_contract) ASSERT c.name = 'Renamed'", step_type='remove_tag',
    )
    contract_id = _new_contract(client)
    db_session.add(EntityTagAssociationDb(
        tag_id=tag_id, entity_id=contract_id, entity_type='data_contract',
    ))
    db_session.flush()

    passed = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    assert passed.status_code == 200, passed.text
    assert tag_writes == [(contract_id, 'removed')]
    assert _contract_tags(db_session, contract_id, tag_id) == []


# The gate's tag changes are written by the update, after its own tags and in its
# commit (#1403 review): a tags list in the same PUT can't overwrite them, and an
# update that fails after the gate leaves none of them.

def _tag_named(client, name):
    """A tag in the default namespace (an update's list names it without one)."""
    created = client.post('/api/tags', json={'name': name})
    assert created.status_code == 201, created.text
    return uuid.UUID(created.json()['id'])


def test_a_tag_list_in_the_put_keeps_the_tag_the_gate_assigns(client, db_session, tag_writes):
    tag_id = _tag_then_check_gate(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('reviewed') AND HAS_TAG('pii')",
    )
    contract_id = _new_contract(client)
    pii_id = _tag_named(client, 'pii')

    passed = client.put(f'/api/data-contracts/{contract_id}', json={'tags': ['pii']})

    # Before, the assign-tag step failed on the list ("list indices must be integers")
    assert passed.status_code == 200, passed.text
    assert [t.assigned_value for t in _contract_tags(db_session, contract_id, tag_id)] == ['yes']
    assert len(_contract_tags(db_session, contract_id, pii_id)) == 1


def test_a_tag_list_in_the_put_loses_the_tag_the_gate_removes(client, db_session, tag_writes):
    tag_id = _tag_then_check_gate(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('pii')", step_type='remove_tag',
    )
    contract_id = _new_contract(client)
    pii_id = _tag_named(client, 'pii')
    reviewed = db_session.get(TagDb, tag_id)
    fqn = f'{db_session.get(TagNamespaceDb, reviewed.namespace_id).name}/reviewed'

    passed = client.put(f'/api/data-contracts/{contract_id}', json={'tags': ['pii', fqn]})

    assert passed.status_code == 200, passed.text
    assert _contract_tags(db_session, contract_id, tag_id) == []
    assert len(_contract_tags(db_session, contract_id, pii_id)) == 1


def test_an_update_that_fails_after_the_gate_leaves_no_tag_from_it(
    client, db_session, tag_writes,
):
    tag_id = _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)

    failed = client.put(
        f'/api/data-contracts/{contract_id}', json={'domain_ids': [str(uuid.uuid4())]},
    )

    # The gate passes on the overlay; the manager then refuses the unknown domain.
    # Before, the gate had already written (and committed) its tag
    assert failed.status_code == 400, failed.text
    assert tag_writes == []
    assert _contract_tags(db_session, contract_id, tag_id) == []


def test_the_gate_tags_are_written_in_the_update_commit(client, db_session, monkeypatch):
    from src.controller.tags_manager import TagsManager

    tag_id = _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Renamed'")
    contract_id = _new_contract(client)
    commits = []
    add = TagsManager.add_tag_to_entity

    def adding(self, db, **kwargs):
        commits.append(kwargs.get('commit', True))
        return add(self, db, **kwargs)

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', adding)

    passed = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    assert passed.status_code == 200, passed.text
    # Only flushed: the update's own commit writes it with the contract
    assert commits == [False]
    assert len(_contract_tags(db_session, contract_id, tag_id)) == 1


def test_a_gate_tag_that_cannot_be_written_refuses_the_update(client, db_session, monkeypatch):
    from src.controller.tags_manager import TagsManager

    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Renamed'")
    contract_id = _new_contract(client)

    def broken(self, db, **kwargs):
        raise RuntimeError('tag table down')

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', broken)

    refused = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    # Refused whatever the gate's on_error (fail_open here). Before, the write error
    # counted as a gate error: fail_open let the update through without the tag
    assert refused.status_code == 400, refused.text
    # (the refused request rolls back the test's shared session, the contract with it)
    assert refused.json()['detail']['code'] == 'update_gate_tag_write_failed'
