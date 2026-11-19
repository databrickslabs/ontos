"""A before_update gate's WHERE and ASSERT see the entity as it will be after the update.

#1019 gave the ASSERT only the proposed change, because fields derived from the stored
row (``has_owner``, counts) describe the entity before it. Tags aren't such a field:
the stored tags, the update's tags and the tags earlier steps assign give the future
tag set. Both WHERE and ASSERT now see one future-state object:

1. A ``tags`` list in the update replaces the stored tags (``[]`` clears them); the
   stored tags count only when the update doesn't touch tags (no ``tags``, or null), and
   tags assigned by earlier steps go on top of them.
2. ``tag_count`` / ``has_tags`` are computed from that set, so they agree with
   ``HAS_TAG``.
3. The derived fields other triggers' rules see (``has_owner``, ``schema_object_count``,
   counts) are there too, for the contract after the update.
4. Stored fields the update doesn't carry, or sends as null (the manager skips nulls),
   keep their stored value, as in the WHERE.
"""
import uuid

from src.common.workflow_executor import (
    AssignTagStepHandler,
    ConditionalStepHandler,
    PolicyCheckStepHandler,
    RemoveTagStepHandler,
    StepContext,
    ValidationStepHandler,
    _policy_rule_object,
)
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.db_models.data_domains import DataDomain
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.models.data_contracts_api import ContractDescription, DataContractUpdate
from src.models.process_workflows import TriggerContext, TriggerType

LONG = 'x' * 100


def _policy(db, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Gate', rule=rule, is_active=True)
    db.add(policy)
    db.flush()
    return policy


def _contract(db, purpose=LONG, owner=None):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='contract', version='1.0.0', status='active',
        description_purpose=purpose, owner_team_id=owner, created_by='u@example.com',
    )
    db.add(contract)
    db.flush()
    return contract


def _tag(db, contract, names, namespace=None, value=None):
    """Assign tags of one namespace (a new one unless given) to the contract."""
    namespace = namespace or f'ns-{uuid.uuid4().hex[:6]}'
    ns = db.query(TagNamespaceDb).filter_by(name=namespace).first()
    if ns is None:
        ns = TagNamespaceDb(name=namespace)
        db.add(ns)
        db.flush()
    for name in names:
        tag = TagDb(name=name, namespace_id=ns.id, status='active')
        db.add(tag)
        db.flush()
        db.add(EntityTagAssociationDb(
            tag_id=tag.id, entity_id=contract.id, entity_type='data_contract',
            assigned_value=value,
        ))
    db.flush()


def _payload(**fields):
    # What the contract update route sends to before_update
    return DataContractUpdate(**fields).model_dump(exclude_unset=True)


def _context(contract, payload):
    trigger = TriggerContext(
        entity_type='data_contract', entity_id=contract.id,
        trigger_type=TriggerType.BEFORE_UPDATE, entity_data=payload,
        user_email='u@example.com',
    )
    return StepContext(
        entity=payload, entity_type='data_contract', entity_id=contract.id,
        entity_name='contract', user_email='u@example.com', trigger_context=trigger,
        execution_id='e', workflow_id='w', workflow_name='W', step_results={},
    )


def _gate(db, rule, contract, payload):
    policy = _policy(db, rule)
    return PolicyCheckStepHandler(db, {'policy_id': policy.id}).execute(
        _context(contract, payload),
    )


# 1. Which tags the gate sees

def test_an_update_that_does_not_touch_tags_keeps_the_stored_ones(db_session):
    contract = _contract(db_session)
    _tag(db_session, contract, ['confidential'])
    rule = "MATCH (c:data_contract) ASSERT HAS_TAG('confidential')"

    untouched = _gate(db_session, rule, contract, _payload(status='active'))
    # An explicit null doesn't touch them either (the manager only sets a list)
    null = _gate(db_session, rule, contract, _payload(status='active', tags=None))

    assert untouched.passed is True
    assert null.passed is True


def test_an_empty_tag_list_clears_the_stored_tags(db_session):
    contract = _contract(db_session)
    _tag(db_session, contract, ['confidential'])

    result = _gate(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('confidential')",
        contract, _payload(tags=[]),
    )

    assert result.passed is False


def test_a_step_tag_goes_on_top_of_the_stored_tags(db_session):
    contract = _contract(db_session)
    _tag(db_session, contract, ['stored'])
    payload = _payload(description=ContractDescription(purpose=LONG))
    payload['tags'] = {'reviewed': 'yes'}  # what an earlier assign-tag step leaves

    result = _gate(
        db_session,
        "MATCH (c:data_contract) ASSERT HAS_TAG('stored') AND TAG('reviewed') = 'yes'",
        contract, payload,
    )

    assert result.passed is True


def test_a_step_tag_on_an_update_with_null_tags_goes_on_top_of_the_stored_ones(db_session):
    contract = _contract(db_session)
    _tag(db_session, contract, ['stored'])
    context = _context(contract, _payload(status='active', tags=None))
    assigned = AssignTagStepHandler(
        db_session, {'key': 'reviewed', 'value': 'yes'},
    ).execute(context)
    policy = _policy(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('stored') AND HAS_TAG('reviewed')",
    )

    result = PolicyCheckStepHandler(db_session, {'policy_id': policy.id}).execute(context)

    assert assigned.passed is True
    assert result.passed is True


def test_a_tag_a_remove_tag_step_removes_is_gone_but_stays_stored_until_the_gate_passes(
    db_session,
):
    contract = _contract(db_session)
    _tag(db_session, contract, ['reviewed', 'kept'], namespace='gate')
    context = _context(contract, _payload(name='Renamed'))
    removed = RemoveTagStepHandler(db_session, {'key': 'gate/reviewed'}).execute(context)
    context.step_results['remove'] = removed.context_entry()
    policy = _policy(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('kept') AND NOT HAS_TAG('reviewed')",
    )

    result = PolicyCheckStepHandler(db_session, {'policy_id': policy.id}).execute(context)

    assert removed.data['deferred_tag_write']['action'] == 'remove'
    assert result.passed is True
    stored = db_session.query(EntityTagAssociationDb).filter_by(entity_id=contract.id).count()
    assert stored == 2


def test_a_tag_removed_then_assigned_again_by_the_gate_is_assigned_after_it(db_session):
    from src.common.workflow_executor import apply_deferred_tag_writes
    from src.models.process_workflows import (
        ExecutionStatus, StepExecutionStatus, WorkflowExecution, WorkflowStepExecutionResult,
    )

    contract = _contract(db_session)
    _tag(db_session, contract, ['reviewed'], namespace='again')
    context = _context(contract, _payload(name='Renamed'))
    steps = []
    for step_id, handler in (
        ('remove', RemoveTagStepHandler(db_session, {'key': 'again/reviewed'})),
        ('assign', AssignTagStepHandler(db_session, {'key': 'again/reviewed'})),
    ):
        result = handler.execute(context)
        context.step_results[step_id] = result.context_entry()
        steps.append(result)
    policy = _policy(db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('reviewed')")
    gate = PolicyCheckStepHandler(db_session, {'policy_id': policy.id}).execute(context)
    # Stored in reverse order: the writes follow the steps, not the timestamps
    execution = WorkflowExecution(
        workflow_id='w', status=ExecutionStatus.SUCCEEDED, step_executions=[
            WorkflowStepExecutionResult(
                status=StepExecutionStatus.SUCCEEDED, passed=True, result_data=result.data,
            ) for result in reversed(steps)
        ],
    )

    apply_deferred_tag_writes(db_session, [execution], 'u@example.com')

    assert gate.passed is True
    assert steps[1].data['deferred_tag_write']['action'] == 'assign'
    stored = db_session.query(EntityTagAssociationDb).filter_by(entity_id=contract.id).count()
    assert stored == 1


def test_tags_sent_as_names_are_read_like_assignments(db_session):
    # A raw payload with FQN strings (the shape DataProduct tags have) instead of
    # AssignedTagCreate dicts: the manager accepts both
    contract = _contract(db_session)

    result = _gate(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('confidential')",
        contract, {'tags': ['security/confidential']},
    )

    assert result.passed is True


def _resent(namespace, value=None):
    # The update resends the stored tag; model_dump gives every tag an assigned_value
    tag = {'tag_fqn': f'{namespace}/classification'}
    if value is not None:
        tag['assigned_value'] = value
    return _payload(tags=[tag])


def test_a_tag_resent_without_a_value_keeps_its_stored_value(db_session):
    # add_tag_to_entity keeps the stored value for None (#1420), so the gate must too
    contract = _contract(db_session)
    _tag(db_session, contract, ['classification'], namespace='levels', value='high')

    result = _gate(
        db_session, "MATCH (c:data_contract) ASSERT TAG('classification') = 'high'",
        contract, _resent('levels'),
    )

    assert result.passed is True


def test_a_tag_resent_by_id_without_a_value_keeps_its_stored_value(db_session):
    contract = _contract(db_session)
    _tag(db_session, contract, ['classification'], namespace='levels', value='high')
    tag = db_session.query(TagDb).filter_by(name='classification').one()

    result = _gate(
        db_session, "MATCH (c:data_contract) ASSERT TAG('classification') = 'high'",
        contract, _payload(tags=[{'tag_id': tag.id}]),
    )

    assert result.passed is True


def test_a_tag_resent_with_an_empty_or_new_value_does_not_keep_the_stored_one(db_session):
    contract = _contract(db_session)
    _tag(db_session, contract, ['classification'], namespace='levels', value='high')
    rule = "MATCH (c:data_contract) ASSERT TAG('classification') = 'high'"

    # An empty string clears the value; the tag stays assigned
    cleared = _gate(db_session, rule, contract, _resent('levels', ''))
    changed = _gate(db_session, rule, contract, _resent('levels', 'low'))
    still_tagged = _gate(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('classification')",
        contract, _resent('levels', ''),
    )

    assert cleared.passed is False
    assert changed.passed is False
    assert still_tagged.passed is True


def _context_without_id(payload):
    # A step without an entity id: nothing stored to load, the payload alone counts
    trigger = TriggerContext(
        entity_type='data_contract', entity_id='',
        trigger_type=TriggerType.BEFORE_UPDATE, entity_data=payload,
        user_email='u@example.com',
    )
    return StepContext(
        entity=payload, entity_type='data_contract', entity_id=None,
        entity_name='contract', user_email='u@example.com', trigger_context=trigger,
        execution_id='e', workflow_id='w', workflow_name='W', step_results={},
    )


def test_without_a_stored_entity_the_gate_sees_the_update_alone(db_session):
    null_tags = {'status': 'active', 'tags': None}
    listed = {'tags': ['security/pii']}

    status_policy = _policy(db_session, "MATCH (c:data_contract) ASSERT c.status = 'active'")
    tags_policy = _policy(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('pii') AND c.tag_count = 1",
    )
    status = PolicyCheckStepHandler(db_session, {'policy_id': status_policy.id}).execute(
        _context_without_id(null_tags),
    )
    tags = PolicyCheckStepHandler(db_session, {'policy_id': tags_policy.id}).execute(
        _context_without_id(listed),
    )

    assert status.passed is True
    # A null with no stored tags to keep: no tags are known, not a null
    assert 'tags' not in _policy_rule_object(db_session, _context_without_id(null_tags))
    assert tags.passed is True


# 2. tag_count / has_tags

def test_tag_count_and_has_tags_describe_the_future_tags(db_session):
    contract = _contract(db_session)
    # One assignment under two keys (FQN and name)
    _tag(db_session, contract, ['stored'])
    payload = _payload(status='active')
    payload['tags'] = {'reviewed': 'yes'}
    counted = "MATCH (c:data_contract) ASSERT c.tag_count = 2 AND c.has_tags = True"

    merged = _gate(db_session, counted, contract, payload)
    cleared = _gate(
        db_session,
        "MATCH (c:data_contract) ASSERT c.tag_count = 0 AND c.has_tags = False",
        contract, _payload(tags=[]),
    )

    assert merged.passed is True
    assert cleared.passed is True


def test_a_tag_count_gate_passes_an_update_that_keeps_tagged_entities_tagged(db_session):
    # The maturity gate "Tags assigned" (ASSERT obj.tag_count > 0) failed every update
    contract = _contract(db_session)
    _tag(db_session, contract, ['stored'])

    result = _gate(
        db_session, "ASSERT obj.tag_count > 0", contract, _payload(status='active'),
    )

    assert result.passed is True


# 3. Fields derived from the stored row

def test_a_null_in_the_update_keeps_the_stored_value(db_session):
    # update_contract_with_relations only writes the fields that aren't null
    contract = _contract(db_session, owner='team-1')

    result = _gate(
        db_session,
        "MATCH (c:data_contract) ASSERT c.owner = 'team-1' AND LENGTH(c.description) >= 70"
        " AND c.name = 'contract'",
        contract, _payload(owner_team_id=None, name=None, descriptionPurpose=None),
    )

    assert result.passed is True


def test_a_description_without_a_purpose_keeps_the_stored_purpose(db_session):
    contract = _contract(db_session, purpose=LONG)

    result = _gate(
        db_session, "MATCH (c:data_contract) ASSERT LENGTH(c.description) >= 70",
        contract, _payload(description=ContractDescription(usage='new usage')),
    )

    assert result.passed is True


def test_a_domain_change_is_the_future_domain(db_session):
    # update_contract_with_relations: domainIds with primaryDomainId (else the first),
    # else domainId, else a domain name; a domain field without a value unassigns the
    # contract. As the compliance loader keys a stored primary domain (#1459): its name
    # under domain, its id under domain_id
    contract = _contract(db_session)
    sales, ops = (
        DataDomain(id=str(uuid.uuid4()), name=name, created_by='u@example.com')
        for name in ('Sales', 'Ops')
    )
    db_session.add_all([sales, ops])
    db_session.flush()

    def domain(payload):
        obj = _policy_rule_object(db_session, _context(contract, payload))
        return obj.get('domain_id'), obj.get('domain')

    assert domain(_payload(domainIds=[sales.id, ops.id], primaryDomainId=ops.id)) == (
        ops.id, 'Ops',
    )
    assert domain(_payload(domainIds=[sales.id, ops.id])) == (sales.id, 'Sales')
    assert domain(_payload(domainId=ops.id)) == (ops.id, 'Ops')
    assert domain(_payload(domainIds=[])) == (None, None)
    # A name (the assistant tool's field) is resolved to its domain
    assert domain({'domain': 'Sales'}) == (sales.id, 'Sales')
    assert domain({'domain': 'Unknown'}) == (None, None)
    # An id the update names but no domain has (the manager then refuses the update)
    assert domain(_payload(domainId='d-3')) == ('d-3', None)
    gate = _gate(
        db_session,
        f"MATCH (c:data_contract) ASSERT c.domain = 'Ops' AND c.domain_id = '{ops.id}'",
        contract, _payload(domainIds=[ops.id]),
    )
    assert gate.passed is True


def test_derived_fields_describe_the_contract_after_the_update(db_session):
    # The default "Data Contract Schema Validation" rules, copied onto before_update
    contract = _contract(db_session, owner='team-1')
    db_session.add(SchemaObjectDb(
        id=str(uuid.uuid4()), contract_id=contract.id, name='orders', logical_type='object',
    ))
    db_session.flush()

    def obj(payload):
        return _policy_rule_object(db_session, _context(contract, payload))

    renamed = obj(_payload(name='Renamed'))
    cleared = obj(_payload(owner_team_id='', contract_schema=[]))
    two_objects = obj(_payload(contract_schema=[
        {'name': 'orders', 'logicalType': 'object'}, {'name': 'items', 'logicalType': 'object'},
    ]))

    # Stored, when the update doesn't send the field
    assert renamed['has_owner'] is True
    assert renamed['schema_object_count'] == 1
    assert renamed['has_purpose'] is True
    assert {'relationship_count', 'quality_check_count', 'is_certified'} <= set(renamed)
    # From the update when it sends it
    assert cleared['has_owner'] is False
    assert cleared['schema_object_count'] == 0
    assert two_objects['schema_object_count'] == 2
    gate = _gate(
        db_session, "MATCH (c:data_contract) ASSERT c.schema_object_count > 0 AND c.has_owner",
        contract, _payload(name='Renamed'),
    )
    assert gate.passed is True


def _assign_domain(db, contract, domain, primary=True):
    from src.db_models.domain_associations import EntityDomainAssociationDb
    db.add(EntityDomainAssociationDb(
        domain_id=domain.id, entity_id=contract.id, entity_type='data_contract',
        is_primary=primary,
    ))
    db.flush()


def test_the_gate_keys_the_domain_alike_whether_or_not_the_update_sends_it(db_session):
    # #1403 review: domain is the primary domain's name, domain_id its id, for a
    # stored contract (the loader's side, #1540) as for one the update moves
    from src.common.compliance_entities import AppEntityLoader
    from src.common.workflow_executor import _proposed_values, _with_stored_primary_domain

    contract = _contract(db_session, owner='team-1')
    sales, ops = (
        DataDomain(id=str(uuid.uuid4()), name=name, created_by='u@example.com')
        for name in ('Sales', 'Ops')
    )
    db_session.add_all([sales, ops])
    db_session.flush()
    _assign_domain(db_session, contract, sales)

    def obj(payload):
        return _policy_rule_object(db_session, _context(contract, payload))

    untouched = obj(_payload(name='Renamed'))
    moved = obj(_payload(domainIds=[ops.id]))
    loaded = AppEntityLoader(db_session).load_entity('data_contract', contract.id)
    stored = _with_stored_primary_domain(
        db_session, _context(contract, {}), loaded,
    )
    every_field = _payload(
        owner_team_id='team-2', description=ContractDescription(purpose='p'),
        domainIds=[ops.id],
    )

    # Before, a stored contract's domain was None (the loader read a dropped column)
    assert (untouched['domain'], untouched['domain_id']) == ('Sales', sales.id)
    assert (moved['domain'], moved['domain_id']) == ('Ops', ops.id)
    # The overlay writes only keys the stored contract has, and a rule sees the
    # same keys whether or not the update sends the field
    assert set(_proposed_values(db_session, every_field)) <= set(stored)
    assert set(loaded) <= set(stored)
    assert set(untouched) <= set(moved)
    assert set(moved) - set(untouched) <= set(_payload(domainIds=[ops.id]))  # request keys


# 4. One object for WHERE and ASSERT

def test_assert_sees_the_stored_fields_the_update_does_not_carry(db_session):
    contract = _contract(db_session, purpose=LONG)

    result = _gate(
        db_session,
        "MATCH (c:data_contract) WHERE c.status = 'active' ASSERT LENGTH(c.description) >= 70",
        contract, _payload(status='active'),
    )

    assert result.passed is True
    assert 'not_applicable' not in result.data


def test_where_and_assert_agree_on_a_field_the_update_does_not_carry(db_session):
    contract = _contract(db_session, owner='team-1')

    result = _gate(
        db_session,
        "MATCH (c:data_contract) WHERE c.owner = 'team-1' ASSERT c.owner = 'team-1'",
        contract, _payload(status='active'),
    )

    assert result.passed is True
    assert 'not_applicable' not in result.data


def test_where_and_assert_see_the_same_tags(db_session):
    contract = _contract(db_session)
    _tag(db_session, contract, ['pii'])
    rule = "MATCH (c:data_contract) WHERE HAS_TAG('pii') ASSERT HAS_TAG('gdpr')"

    untouched = _gate(db_session, rule, contract, _payload(status='active'))
    with_gdpr = _gate(db_session, rule, contract, _payload(tags=['pii', 'gdpr']))

    # Selected by the stored pii tag, and failed: it has no gdpr tag
    assert untouched.passed is False
    assert 'not_applicable' not in untouched.data
    assert with_gdpr.passed is True
    assert 'not_applicable' not in with_gdpr.data


# 5. Validation and conditional steps see the same object

def test_a_validation_step_sees_the_stored_tags_an_update_does_not_resend(db_session):
    # The default "Check Owner Tag" rule, on a before_update trigger
    contract = _contract(db_session)
    _tag(db_session, contract, ['owner'])
    rule = "MATCH (obj:Object) ASSERT HAS_TAG('owner')"

    renamed = ValidationStepHandler(db_session, {'rule': rule}).execute(
        _context(contract, _payload(name='Renamed')),
    )
    cleared = ValidationStepHandler(db_session, {'rule': rule}).execute(
        _context(contract, _payload(tags=[])),
    )

    assert renamed.passed is True
    assert cleared.passed is False


def test_a_conditional_step_sees_the_stored_fields_an_update_does_not_resend(db_session):
    contract = _contract(db_session, owner='team-1')

    result = ConditionalStepHandler(
        db_session, {'condition': "obj.owner = 'team-1'"},
    ).execute(_context(contract, _payload(name='Renamed')))

    assert result.branch is True
