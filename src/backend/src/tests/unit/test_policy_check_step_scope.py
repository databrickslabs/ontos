"""A workflow policy_check step gives the verdict a compliance run gives (#1149).

The step used to evaluate only the rule's ASSERT, on an object built from the
trigger payload: MATCH and WHERE were ignored and keys such as ``tags`` and
``description`` were missing. It now selects with MATCH and WHERE (a policy
that doesn't select the entity doesn't apply to it, and the step passes) and
evaluates ASSERT on the entity as the compliance loader builds it.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from src.common.compliance_entities import AppEntityLoader
from src.common.workflow_executor import PolicyCheckStepHandler, StepContext
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.models.data_contracts_api import ContractDescription, DataContractUpdate
from src.models.process_workflows import TriggerContext, TriggerType

# Rules of the retail demo (demo_data_retail.sql)
PURPOSE_RULE = (
    "MATCH (c:data_contract) WHERE c.status = 'active' "
    "ASSERT LENGTH(c.description) >= 70"
)
PII_RULE = "MATCH (p:data_product) WHERE HAS_TAG('pii') ASSERT HAS_TAG('gdpr')"
STATUS_RULE = (
    "MATCH (c:data_contract) ASSERT c.status != 'deprecated' AND c.status != 'retired'"
)
LONG = 'x' * 100


def _policy(db, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Gate', rule=rule, is_active=True)
    db.add(policy)
    db.flush()
    return policy


def _contract(db, name, status, purpose):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=name, version='1.0.0', status=status,
        description_purpose=purpose, created_by='u@example.com',
    )
    db.add(contract)
    db.flush()
    return contract


def _product(db, name, status='active'):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status=status, name=name, version='1.0.0',
    )
    db.add(product)
    db.flush()
    return product


def _tag(db, entity, entity_type, names):
    namespace = TagNamespaceDb(name=f'ns-{uuid.uuid4().hex[:6]}')
    db.add(namespace)
    db.flush()
    for name in names:
        tag = TagDb(name=name, namespace_id=namespace.id, status='active')
        db.add(tag)
        db.flush()
        db.add(EntityTagAssociationDb(
            tag_id=tag.id, entity_id=entity.id, entity_type=entity_type,
        ))
    db.flush()


def _run(db, policy):
    """{entity id: passed} of a compliance run; entities it doesn't select are absent."""
    with patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()):
        run = ComplianceManager().run_policy_inline(db, policy=policy)
    rows = db.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    return {r.object_id: r.passed for r in rows}


def _step(db, policy, entity_type, entity_id, payload, trigger_type=None):
    trigger = None
    if trigger_type is not None:
        trigger = TriggerContext(
            entity_type=entity_type, entity_id=entity_id, trigger_type=trigger_type,
            entity_data=payload, user_email='u@example.com',
        )
    context = StepContext(
        entity=payload, entity_type=entity_type, entity_id=entity_id,
        entity_name=payload.get('name'), user_email='u@example.com',
        trigger_context=trigger, execution_id='e', workflow_id='w',
        workflow_name='W', step_results={},
    )
    return PolicyCheckStepHandler(db, {'policy_id': policy.id}).execute(context)


def _on_create_payload(contract):
    # What the contract on_create trigger sends (data_contracts_routes)
    return {'contract_id': contract.id, 'name': contract.name, 'status': contract.status}


def test_where_excludes_a_draft_contract(db_session):
    policy = _policy(db_session, PURPOSE_RULE)
    draft = _contract(db_session, 'draft-long-purpose', 'draft', LONG)

    assert draft.id not in _run(db_session, policy)
    result = _step(db_session, policy, 'data_contract', draft.id, _on_create_payload(draft))

    assert result.passed is True
    assert result.data['not_applicable'] is True
    assert result.data['reason'] == 'where'


def test_where_excludes_an_untagged_product(db_session):
    policy = _policy(db_session, PII_RULE)
    untagged = _product(db_session, 'untagged')

    assert untagged.id not in _run(db_session, policy)
    result = _step(db_session, policy, 'data_product', untagged.id, {'name': untagged.name})

    assert result.passed is True
    assert result.data['not_applicable'] is True
    assert result.data['reason'] == 'where'


def test_a_contract_policy_does_not_apply_to_a_product(db_session):
    policy = _policy(db_session, STATUS_RULE)
    deprecated = _product(db_session, 'product-status-deprecated', 'deprecated')

    assert deprecated.id not in _run(db_session, policy)
    result = _step(db_session, policy, 'data_product', deprecated.id, {
        'product_id': deprecated.id, 'name': deprecated.name, 'status': 'deprecated',
    })

    assert result.passed is True
    assert result.data['not_applicable'] is True
    assert result.data['reason'] == 'match_type'


@pytest.mark.parametrize('rule, kind, purpose, tags, expected', [
    (PURPOSE_RULE, 'data_contract', LONG, [], True),
    (PURPOSE_RULE, 'data_contract', 'Short.', [], False),
    (PII_RULE, 'data_product', None, ['pii', 'gdpr'], True),
    (PII_RULE, 'data_product', None, ['pii'], False),
], ids=['active-long-purpose', 'active-short-purpose', 'pii+gdpr-tagged', 'pii-only-tagged'])
def test_the_step_agrees_with_a_compliance_run(db_session, rule, kind, purpose, tags, expected):
    policy = _policy(db_session, rule)
    if kind == 'data_contract':
        entity = _contract(db_session, 'contract', 'active', purpose)
        payload = _on_create_payload(entity)
    else:
        entity = _product(db_session, 'product')
        _tag(db_session, entity, 'data_product', tags)
        payload = {'product_id': entity.id, 'name': entity.name}

    run = _run(db_session, policy)
    result = _step(db_session, policy, kind, entity.id, payload)

    assert run[entity.id] is expected
    assert result.passed is expected
    assert 'not_applicable' not in result.data


def test_before_create_evaluates_the_payload(db_session):
    policy = _policy(db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('confidential')")
    # A stored entity with the id must not be read: before_create has none yet
    stored = _contract(db_session, 'stored', 'active', LONG)
    _tag(db_session, stored, 'data_contract', ['confidential'])
    payload = {'name': 'new-contract', 'status': 'active'}

    result = _step(
        db_session, policy, 'data_contract', stored.id, payload,
        trigger_type=TriggerType.BEFORE_CREATE,
    )

    assert result.passed is False
    assert 'not_applicable' not in result.data


def test_types_the_loader_does_not_read_are_evaluated_on_the_payload(db_session):
    # The retail naming-conventions gate runs on before_create table / view
    policy = _policy(
        db_session,
        "MATCH (obj:Object) WHERE obj.type IN ['table', 'view'] "
        "ASSERT obj.name = 'sales_orders'",
    )

    good = _step(db_session, policy, 'table', 'main.sales.sales_orders', {
        'type': 'table', 'name': 'sales_orders',
    })
    bad = _step(db_session, policy, 'table', 'main.sales.Orders', {
        'type': 'table', 'name': 'Orders',
    })

    assert good.passed is True
    assert bad.passed is False
    assert not (bad.data or {}).get('error_code')


def test_an_entity_the_loader_does_not_find_is_evaluated_on_the_payload(db_session):
    policy = _policy(db_session, "MATCH (p:data_product) ASSERT p.status = 'active'")

    result = _step(db_session, policy, 'data_product', str(uuid.uuid4()), {
        'name': 'p', 'status': 'active',
    })

    assert result.passed is True
    assert not (result.data or {}).get('error_code')


def _before_update_payload(**fields):
    # What the contract update route sends to before_update
    return DataContractUpdate(**fields).model_dump(exclude_unset=True)


def test_before_update_sees_the_proposed_purpose_and_status(db_session):
    policy = _policy(db_session, PURPOSE_RULE)
    contract = _contract(db_session, 'contract', 'active', 'Short.')

    longer = _step(
        db_session, policy, 'data_contract', contract.id,
        _before_update_payload(
            status='active', description=ContractDescription(purpose=LONG, usage='u'),
        ),
        trigger_type=TriggerType.BEFORE_UPDATE,
    )
    to_draft = _step(
        db_session, policy, 'data_contract', contract.id,
        _before_update_payload(status='draft'),
        trigger_type=TriggerType.BEFORE_UPDATE,
    )

    # description is the proposed purpose (a string), not the ODCS object
    assert longer.passed is True
    assert 'not_applicable' not in longer.data
    # The proposed status decides the WHERE
    assert to_draft.passed is True
    assert to_draft.data['reason'] == 'where'


def test_before_update_gates_see_only_the_proposed_change(db_session):
    # As decided for before_update gates (#1019): no stored value fills in for
    # a field the change clears or doesn't carry.
    policy = _policy(db_session, "MATCH (c:data_contract) ASSERT LENGTH(c.owner) > 0")
    contract = _contract(db_session, 'contract', 'active', LONG)
    contract.owner_team_id = 'team-1'
    db_session.flush()

    cleared = _step(
        db_session, policy, 'data_contract', contract.id,
        _before_update_payload(owner_team_id=None),
        trigger_type=TriggerType.BEFORE_UPDATE,
    )
    kept = _step(
        db_session, policy, 'data_contract', contract.id,
        _before_update_payload(owner_team_id='team-2'),
        trigger_type=TriggerType.BEFORE_UPDATE,
    )

    assert cleared.passed is False
    assert kept.passed is True


@pytest.mark.parametrize('name, expected', [('contract', True), ('other', False)])
def test_a_rule_that_does_not_parse_is_decided_by_its_assert(db_session, name, expected):
    # As before: the MATCH can't be read, so it doesn't make the policy not applicable
    policy = _policy(db_session, f"MATCH (c:data_contract ASSERT c.name = '{name}'")
    contract = _contract(db_session, 'contract', 'active', LONG)

    result = _step(db_session, policy, 'data_contract', contract.id, _on_create_payload(contract))

    assert result.passed is expected
    assert 'not_applicable' not in result.data


def test_a_where_that_cannot_be_evaluated_excludes_the_entity(db_session):
    # As in a compliance run (EntityIterator.iterate)
    policy = _policy(db_session, PURPOSE_RULE)
    contract = _contract(db_session, 'contract', 'active', LONG)

    with patch('src.common.compliance_dsl.Evaluator.evaluate', side_effect=RuntimeError('boom')):
        result = _step(
            db_session, policy, 'data_contract', contract.id, _on_create_payload(contract),
        )

    assert result.passed is True
    assert result.data['reason'] == 'where'


def test_on_update_sees_the_stored_contract_not_the_request_shapes(db_session):
    # on_update fires once the update is stored; its payload is the request
    # body, whose description is the ODCS object and tags are assignments.
    contract = _contract(db_session, 'contract', 'active', LONG)
    _tag(db_session, contract, 'data_contract', ['confidential'])
    payload = _before_update_payload(
        description=ContractDescription(purpose=LONG, usage='u'),
        tags=['other/confidential'],
    )
    purpose = _policy(db_session, PURPOSE_RULE)
    restricted = _policy(
        db_session,
        "MATCH (c:data_contract) WHERE HAS_TAG('confidential') ASSERT HAS_TAG('restricted')",
    )

    results = {
        policy.id: _step(
            db_session, policy, 'data_contract', contract.id, payload,
            trigger_type=TriggerType.ON_UPDATE,
        )
        for policy in (purpose, restricted)
    }

    assert _run(db_session, purpose)[contract.id] is True
    assert results[purpose.id].passed is True
    assert _run(db_session, restricted)[contract.id] is False
    assert results[restricted.id].passed is False
    assert 'not_applicable' not in results[restricted.id].data


def test_before_update_sees_the_proposed_tags(db_session):
    policy = _policy(db_session, "MATCH (c:data_contract) ASSERT HAS_TAG('confidential')")
    contract = _contract(db_session, 'contract', 'active', LONG)
    _tag(db_session, contract, 'data_contract', ['confidential'])
    namespace = TagNamespaceDb(name=f'ns-{uuid.uuid4().hex[:6]}')
    db_session.add(namespace)
    db_session.flush()
    by_id = TagDb(name='confidential', namespace_id=namespace.id, status='active')
    db_session.add(by_id)
    db_session.flush()

    def step(tags):
        return _step(
            db_session, policy, 'data_contract', contract.id, _before_update_payload(tags=tags),
            trigger_type=TriggerType.BEFORE_UPDATE,
        )

    assert step(['security/confidential']).passed is True
    assert step(['security/confidential', 'security/confidential']).passed is True
    assert step([{'tag_id': str(by_id.id)}]).passed is True
    # The stored tag doesn't count: the update replaces the tags
    assert step(['security/public']).passed is False


def test_a_load_failure_fails_the_step_and_keeps_the_transaction(db_session):
    # The repositories' get() rolls the whole transaction back on an error,
    # past the loader's savepoint; the workflow and its caller go on using it.
    policy = _policy(db_session, "MATCH (d:domain) ASSERT d.name != ''")
    domain = _domain(db_session)
    domain_id = domain.id
    db_session.expunge(domain)
    real_execute = db_session.execute

    def execute(statement, *args, **kwargs):
        if 'FROM data_domains' in str(statement):
            raise OperationalError(str(statement), {}, Exception('db down'))
        return real_execute(statement, *args, **kwargs)

    with patch.object(db_session, 'execute', side_effect=execute):
        result = _step(db_session, policy, 'domain', domain_id, {'name': 'd'})

    assert result.passed is False
    assert 'db down' not in result.error
    assert result.data['error_code'] == 'rule_entity_load_failed'
    assert result.data['error_params'] == {'entityType': 'domain', 'entityId': domain_id}
    assert db_session.query(DataDomain).filter_by(id=domain_id).count() == 1
    assert db_session.get(CompliancePolicyDb, policy.id) is not None


def _domain(db):
    domain = DataDomain(name=f'domain-{uuid.uuid4().hex[:6]}', created_by='u@example.com')
    db.add(domain)
    db.flush()
    _tag(db, domain, 'data_domain', ['finance'])
    return domain


def _review(db):
    review = DataAssetReviewRequestDb(
        requester_email='r@example.com', reviewer_email='s@example.com', status='queued',
    )
    db.add(review)
    db.flush()
    return review


@pytest.mark.parametrize('entity_type, create', [
    ('data_product', lambda db: _product(db, 'p')),
    ('data_contract', lambda db: _contract(db, 'c', 'active', LONG)),
    ('domain', _domain),
    ('review', _review),
])
def test_load_entity_gives_the_dict_load_entities_gives(db_session, entity_type, create):
    entity = create(db_session)
    loader = AppEntityLoader(db_session)

    listed = [e for e in loader.load_entities([entity_type]) if e['id'] == entity.id]

    assert listed and loader.load_entity(entity_type, entity.id) == listed[0]


def test_a_review_policy_applies_to_a_data_asset_review(db_session):
    # Workflows name the type data_asset_review; rules and the loader, review
    policy = _policy(db_session, "MATCH (r:review) ASSERT r.status = 'approved'")
    review = _review(db_session)
    review.status = 'approved'
    db_session.flush()

    # The status comes from the stored review: the payload doesn't carry it
    result = _step(db_session, policy, 'data_asset_review', review.id, {'id': review.id})

    assert result.passed is True
    assert 'not_applicable' not in result.data
