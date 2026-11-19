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


SEMANTIC = 'http://databricks.com/ontology/uc/semanticAssignment'
CONCEPT = {'url': 'http://example.com/ontology#Customer', 'type': SEMANTIC}


@pytest.fixture
def write_order(monkeypatch):
    """(kind, committed) of each gate tag write and semantic link add, in call order."""
    from src.controller.semantic_links_manager import SemanticLinksManager
    from src.controller.tags_manager import TagsManager

    order = []
    add_tag, add_link = TagsManager.add_tag_to_entity, SemanticLinksManager.add

    def adding_tag(self, db, **kwargs):
        order.append(('tag', kwargs.get('commit', True)))
        return add_tag(self, db, **kwargs)

    def adding_link(self, payload, created_by=None, **kwargs):
        order.append(('link', kwargs.get('commit', True)))
        return add_link(self, payload, created_by, **kwargs)

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', adding_tag)
    monkeypatch.setattr(SemanticLinksManager, 'add', adding_link)
    return order


def test_the_semantic_links_of_the_update_are_written_in_its_commit(
    client, db_session, write_order,
):
    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)

    passed = client.put(
        f'/api/data-contracts/{contract_id}', json={'authoritativeDefinitions': [CONCEPT]},
    )

    # Before, the link was added (and committed) before the gate's tag was written,
    # so a tag write that refused the update left the link behind
    assert passed.status_code == 200, passed.text
    assert write_order == [('tag', False), ('link', False)]


def test_a_refused_update_adds_no_semantic_link(client, db_session, monkeypatch, write_order):
    from src.controller.tags_manager import TagsManager

    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)

    def broken(self, db, **kwargs):
        write_order.append(('tag', 'failed'))
        raise RuntimeError('tag table down')

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', broken)

    refused = client.put(
        f'/api/data-contracts/{contract_id}', json={'authoritativeDefinitions': [CONCEPT]},
    )

    assert refused.status_code == 400, refused.text
    assert write_order == [('tag', 'failed')]


def test_a_tag_list_that_cannot_be_written_keeps_the_rest_of_the_update(
    client, db_session, monkeypatch,
):
    # The savepoint around the update's own tags: their failure undoes only them
    from src.controller.tags_manager import TagsManager

    contract_id = _new_contract(client)
    pii_id = _tag_named(client, 'pii')

    def broken(self, db, **kwargs):
        db.add(EntityTagAssociationDb(
            tag_id=pii_id, entity_id=contract_id, entity_type='data_contract',
        ))
        db.flush()
        raise RuntimeError('tag table down')

    monkeypatch.setattr(TagsManager, 'set_tags_for_entity', broken)

    passed = client.put(
        f'/api/data-contracts/{contract_id}', json={'name': 'Renamed', 'tags': ['pii']},
    )

    assert passed.status_code == 200, passed.text
    assert client.get(f'/api/data-contracts/{contract_id}').json()['name'] == 'Renamed'
    assert _contract_tags(db_session, contract_id, pii_id) == []


SCHEMA_WITH_CONCEPTS = [{
    'name': 'orders', 'physicalType': 'table', 'authoritativeDefinitions': [CONCEPT],
    'properties': [{
        'name': 'id', 'logicalType': 'string', 'authoritativeDefinitions': [CONCEPT],
    }],
}]


def test_the_schema_semantic_links_of_the_update_are_written_in_its_commit(
    client, db_session, write_order,
):
    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)

    passed = client.put(
        f'/api/data-contracts/{contract_id}', json={'schema': SCHEMA_WITH_CONCEPTS},
    )

    # Before, the schema and property links were added (and committed) as the schema
    # was recreated, before the gate's tag was written
    assert passed.status_code == 200, passed.text
    assert sorted(write_order) == [('link', False), ('link', False), ('tag', False)]


def test_a_refused_update_adds_no_schema_semantic_link(
    client, db_session, monkeypatch, write_order,
):
    from src.controller.tags_manager import TagsManager

    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)

    def broken(self, db, **kwargs):
        write_order.append(('tag', 'failed'))
        raise RuntimeError('tag table down')

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', broken)

    refused = client.put(f'/api/data-contracts/{contract_id}', json={
        'description': {'purpose': 'changed'}, 'schema': SCHEMA_WITH_CONCEPTS,
    })

    # Before: [('link', True), ('link', True), ('tag', 'failed')], the description
    # and the schema committed with the links although the update was refused
    assert refused.status_code == 400, refused.text
    assert refused.json()['detail']['code'] == 'update_gate_tag_write_failed'
    assert [kind for kind in write_order if kind[1] is True] == []


def _gate(db_session, name, steps):
    """An active before_update gate on contracts named ``name``; ``steps``: (type, config)."""
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=name, description='gate',
        trigger_config=json.dumps({'type': 'before_update', 'entity_types': ['data_contract']}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    for order, (step_type, config) in enumerate(steps):
        db_session.add(WorkflowStepDb(
            id=str(uuid.uuid4()), workflow_id=wf_id, step_id=f's{order}', name=f'S{order}',
            step_type=step_type, config=json.dumps(config), order=order,
            on_pass=f's{order + 1}' if order + 1 < len(steps) else None,
            created_at=now, updated_at=now,
        ))
    db_session.commit()


def _policy(db_session, rule):
    policy_id = str(uuid.uuid4())
    db_session.add(CompliancePolicyDb(id=policy_id, name='Check', rule=rule, is_active=True))
    db_session.commit()
    return policy_id


def test_a_later_gate_sees_the_tag_an_earlier_gate_removes(client, db_session):
    contract_id = _new_contract(client)
    _tag_named(client, 'pii')
    tagged = client.put(f'/api/data-contracts/{contract_id}', json={'tags': ['pii']})
    assert tagged.status_code == 200, tagged.text
    policy_id = _policy(db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('pii')")
    _gate(db_session, f'a-remove-{uuid.uuid4().hex[:6]}', [('remove_tag', {'key': 'pii'})])
    _gate(db_session, f'b-check-{uuid.uuid4().hex[:6]}', [
        ('policy_check', {'policy_id': policy_id}),
    ])

    refused = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    # Before, the second gate saw the stored pii tag and passed, and the update
    # was saved without it
    assert refused.status_code == 400, refused.text
    assert refused.json()['detail']['message'] == 'Pre-update validation failed'
    # (the refused request rolls back the test's shared session, the tag with it)


def test_a_later_gate_sees_the_tag_an_earlier_gate_assigns(client, db_session):
    contract_id = _new_contract(client)
    pii_id = _tag_named(client, 'pii')
    policy_id = _policy(db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('pii')")
    _gate(db_session, f'a-assign-{uuid.uuid4().hex[:6]}', [('assign_tag', {'key': 'pii'})])
    _gate(db_session, f'b-check-{uuid.uuid4().hex[:6]}', [
        ('policy_check', {'policy_id': policy_id}),
    ])

    passed = client.put(f'/api/data-contracts/{contract_id}', json={'name': 'Renamed'})

    # Before, the second gate didn't see the first one's tag and refused the update
    assert passed.status_code == 200, passed.text
    assert len(_contract_tags(db_session, contract_id, pii_id)) == 1


def test_a_later_gate_sees_an_earlier_gate_change_to_the_tag_list(client, db_session):
    contract_id = _new_contract(client)
    _tag_named(client, 'pii')
    policy_id = _policy(db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('pii')")
    _gate(db_session, f'a-remove-{uuid.uuid4().hex[:6]}', [('remove_tag', {'key': 'pii'})])
    _gate(db_session, f'b-check-{uuid.uuid4().hex[:6]}', [
        ('policy_check', {'policy_id': policy_id}),
    ])

    refused = client.put(f'/api/data-contracts/{contract_id}', json={'tags': ['pii']})

    assert refused.status_code == 400, refused.text


def test_a_gated_update_whose_tag_list_cannot_be_written_is_refused(
    client, db_session, monkeypatch,
):
    from src.controller.tags_manager import TagsManager

    policy_id = _policy(db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('pii')")
    _gate(db_session, f'check-{uuid.uuid4().hex[:6]}', [
        ('policy_check', {'policy_id': policy_id}),
    ])
    contract_id = _new_contract(client)
    _tag_named(client, 'pii')

    def broken(self, db, **kwargs):
        raise RuntimeError('tag table down')

    monkeypatch.setattr(TagsManager, 'set_tags_for_entity', broken)

    refused = client.put(
        f'/api/data-contracts/{contract_id}', json={'name': 'Renamed', 'tags': ['pii']},
    )

    # The gate passed on the pii the list adds. Before, the update was saved
    # without it (the failed tag write was only logged)
    assert refused.status_code == 400, refused.text
    assert refused.json()['detail']['code'] == 'update_gate_tag_list_write_failed'


def test_new_authoritative_definitions_replace_the_contract_links(client, db_session):
    from src.db_models.semantic_links import EntitySemanticLinkDb

    contract_id = _new_contract(client)
    other = {'url': 'http://example.com/ontology#Order', 'type': SEMANTIC}
    first = client.put(
        f'/api/data-contracts/{contract_id}', json={'authoritativeDefinitions': [CONCEPT]},
    )
    assert first.status_code == 200, first.text

    replaced = client.put(
        f'/api/data-contracts/{contract_id}', json={'authoritativeDefinitions': [other]},
    )

    assert replaced.status_code == 200, replaced.text
    db_session.expire_all()
    links = db_session.query(EntitySemanticLinkDb).filter_by(
        entity_id=contract_id, entity_type='data_contract',
    ).all()
    assert [link.iri for link in links] == [other['url']]


@pytest.fixture
def graph(monkeypatch):
    """The knowledge graph calls of the semantic links, and the commits around them.

    ``events``: ('row', iri) when a link row is written, ('commit',) per session
    commit, ('add' | 'remove', entity_type, iri) per graph call.
    """
    from sqlalchemy.orm import Session

    from src.controller import semantic_links_manager as module

    events = []

    class FakeGraph:
        def add_entity_semantic_link_to_graph(self, entity_type, entity_id, iri, created_by=None):
            events.append(('add', entity_type, iri))

        def remove_entity_semantic_link_from_graph(self, entity_type, entity_id, iri):
            events.append(('remove', entity_type, iri))

        def _invalidate_cache(self):
            pass

    fake = FakeGraph()
    monkeypatch.setattr(module.SemanticLinksManager, '_models_manager', lambda self: fake)
    create, commit = module.entity_semantic_links_repo.create, Session.commit

    def creating(db, obj_in):
        events.append(('row', obj_in.iri))
        return create(db, obj_in=obj_in)

    def committing(self):
        events.append(('commit',))
        return commit(self)

    monkeypatch.setattr(module.entity_semantic_links_repo, 'create', creating)
    monkeypatch.setattr(Session, 'commit', committing)
    return events


def _graph_calls(events):
    return [event for event in events if event[0] in ('add', 'remove')]


def _committed_before_graph(events):
    """Every link row was followed by a commit before the first graph call."""
    first_graph = next(i for i, event in enumerate(events) if event[0] in ('add', 'remove'))
    last_row = max(i for i, event in enumerate(events) if event[0] == 'row')
    return last_row < first_graph and ('commit',) in events[last_row:first_graph]


def test_the_graph_gets_the_update_links_after_its_commit(client, db_session, graph):
    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)
    other = {'url': 'http://example.com/ontology#Order', 'type': SEMANTIC}
    first = client.put(
        f'/api/data-contracts/{contract_id}', json={'authoritativeDefinitions': [CONCEPT]},
    )
    assert first.status_code == 200, first.text
    graph.clear()

    replaced = client.put(
        f'/api/data-contracts/{contract_id}', json={'authoritativeDefinitions': [other]},
    )

    assert replaced.status_code == 200, replaced.text
    assert _graph_calls(graph) == [
        ('remove', 'data_contract', CONCEPT['url']), ('add', 'data_contract', other['url']),
    ]
    assert _committed_before_graph(graph)


def test_the_graph_gets_the_update_schema_links_after_its_commit(client, db_session, graph):
    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)
    graph.clear()

    passed = client.put(
        f'/api/data-contracts/{contract_id}', json={'schema': SCHEMA_WITH_CONCEPTS},
    )

    assert passed.status_code == 200, passed.text
    assert sorted(_graph_calls(graph)) == [
        ('add', 'data_contract_property', CONCEPT['url']),
        ('add', 'data_contract_schema', CONCEPT['url']),
    ]
    assert _committed_before_graph(graph)


def test_a_refused_update_leaves_the_graph_alone(client, db_session, monkeypatch, graph):
    from src.controller.tags_manager import TagsManager

    _tag_then_check_gate(db_session, "MATCH (c:data_contract) ASSERT c.name = 'Gated'")
    contract_id = _new_contract(client)

    def broken(self, db, **kwargs):
        raise RuntimeError('tag table down')

    monkeypatch.setattr(TagsManager, 'add_tag_to_entity', broken)

    refused = client.put(f'/api/data-contracts/{contract_id}', json={
        'authoritativeDefinitions': [CONCEPT], 'schema': SCHEMA_WITH_CONCEPTS,
    })

    assert refused.status_code == 400, refused.text
    assert _graph_calls(graph) == []
