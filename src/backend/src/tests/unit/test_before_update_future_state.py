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
3. Other fields derived from the stored row stay out.
4. Stored fields the update doesn't carry, or sends as null (the manager skips nulls),
   keep their stored value, as in the WHERE.
"""
import uuid

from src.common.workflow_executor import (
    AssignTagStepHandler,
    PolicyCheckStepHandler,
    StepContext,
    _policy_rule_object,
)
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.data_contracts import DataContractDb
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


def _tag(db, contract, names, namespace=None):
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


def test_tags_sent_as_names_are_read_like_assignments(db_session):
    # A raw payload with FQN strings (the shape DataProduct tags have) instead of
    # AssignedTagCreate dicts: the manager accepts both
    contract = _contract(db_session)

    result = _gate(
        db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('confidential')",
        contract, {'tags': ['security/confidential']},
    )

    assert result.passed is True


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


def test_fields_derived_from_the_stored_row_stay_out(db_session):
    contract = _contract(db_session, owner='team-1')

    obj = _policy_rule_object(db_session, _context(contract, _payload(status='active')))

    assert obj['owner'] == 'team-1'
    assert not {'has_owner', 'has_description', 'relationship_count',
                'quality_check_count'} & set(obj)


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
