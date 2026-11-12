"""run_policy_inline with LLM_CHECK rules: reasons, cache across runs, budget (#1479)."""
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.tests.helpers import FakeLlm, llm_reply as _reply

GRAIN = 'states the grain of the table'
RULE = f"MATCH (d:domain)\nASSERT LLM_CHECK(d.description, '{GRAIN}')"


def _policy(db, rule=RULE):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Grain documented', rule=rule)
    db.add(policy)
    db.flush()
    return policy


def _domain(i, description):
    return {'type': 'domain', 'id': f'd{i}', 'name': f'domain_{i}', 'description': description}


def _run(db, policy, entities, fake, settings=None):
    iterator = MagicMock()
    iterator.iterate.side_effect = lambda *a, **k: iter(entities)
    with patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator), \
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()), \
            patch('src.common.config.get_settings', return_value=settings or _settings()), \
            patch('src.common.llm_client.create_openai_client', return_value=fake):
        return ComplianceManager().run_policy_inline(db, policy=policy)


def _results(db, run):
    rows = db.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    return {r.object_id: r for r in rows}


def _settings(**overrides):
    values = {
        'LLM_ENABLED': True, 'LLM_ENDPOINT': 'test-endpoint',
        'COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN': 200,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _grain_llm():
    """A fake endpoint: PASS for texts that say "per", FAIL for the others."""
    def answer(kwargs):
        if ' per ' in kwargs['messages'][1]['content']:
            return _reply('PASS: one row per order')
        return _reply('FAIL: does not say what one row is')
    return FakeLlm(answer=answer)


def test_failed_result_carries_the_reason(db_session):
    policy = _policy(db_session)
    fake = _grain_llm()

    run = _run(db_session, policy, [
        _domain(1, 'One row per order and day.'), _domain(2, 'table with data'),
    ], fake)

    assert (run.status, run.success_count, run.failure_count) == ('succeeded', 1, 1)
    results = _results(db_session, run)
    assert results['d1'].passed is True
    failed = results['d2']
    assert failed.passed is False
    assert json.loads(failed.details_json) == {'llm_checks': [{
        'criterion': GRAIN, 'passed': False, 'reason': 'does not say what one row is',
        'code': None, 'cached': False,
    }]}


def test_second_run_with_unchanged_text_makes_no_call(db_session):
    policy = _policy(db_session)
    entities = [_domain(1, 'One row per order.'), _domain(2, 'table with data')]
    first = _grain_llm()
    _run(db_session, policy, entities, first)
    assert len(first.calls) == 2

    second = _grain_llm()
    run = _run(db_session, policy, entities, second)

    assert second.calls == []
    assert (run.success_count, run.failure_count) == (1, 1)
    details = json.loads(_results(db_session, run)['d2'].details_json)
    assert details['llm_checks'][0]['cached'] is True

    # Changed text is asked again
    third = _grain_llm()
    _run(db_session, policy, [_domain(1, 'One row per order and region.')], third)
    assert len(third.calls) == 1


def test_no_endpoint_fails_every_entity_with_a_code(db_session):
    policy = _policy(db_session)
    fake = _grain_llm()

    run = _run(
        db_session, policy, [_domain(1, 'One row per order.')], fake,
        settings=_settings(LLM_ENDPOINT=None),
    )

    assert (run.status, run.success_count, run.failure_count) == ('succeeded', 0, 1)
    result = _results(db_session, run)['d1']
    assert result.passed is False
    assert json.loads(result.details_json)['llm_checks'][0]['code'] == 'llm_check_no_endpoint'
    assert fake.calls == []


def test_budget_exceeded_is_counted_in_the_run(db_session):
    policy = _policy(db_session, rule=(
        f"MATCH (d:domain)\nASSERT NOT LLM_CHECK(d.description, 'names a person')"
    ))
    fake = FakeLlm(_reply('FAIL: no person named'))
    entities = [_domain(i, f'text {i}') for i in range(5)]

    run = _run(
        db_session, policy, entities, fake,
        settings=_settings(COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN=2),
    )

    assert len(fake.calls) == 2
    # NOT does not turn a check that was not run into a pass
    assert (run.success_count, run.failure_count) == (2, 3)
    assert run.warning_code == 'llm_check_budget_exceeded'
    assert json.loads(run.warning_params) == {'count': 3, 'budget': 2}
    codes = [
        json.loads(r.details_json)['llm_checks'][0]['code']
        for r in _results(db_session, run).values() if not r.passed
    ]
    assert codes == ['llm_check_budget_exceeded'] * 3


def test_rules_without_llm_check_make_no_call_and_no_details(db_session):
    policy = _policy(db_session, rule="MATCH (d:domain)\nASSERT d.name = 'domain_1'")
    fake = _grain_llm()

    run = _run(db_session, policy, [_domain(1, 'x'), _domain(2, 'y')], fake)

    assert fake.calls == []
    assert run.warning_code is None
    assert all(r.details_json is None for r in _results(db_session, run).values())
