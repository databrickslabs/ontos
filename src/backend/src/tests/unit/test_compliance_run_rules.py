"""run_policy_inline: rule parsing and FAIL messages with repeated ON_FAIL clauses."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock, patch

from src.common import compliance_dsl
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb


def _policy(db, rule, name='Test policy'):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name=name, rule=rule, is_active=True)
    db.add(policy)
    db.flush()
    return policy


def _run(db, policy, entities):
    iterator = MagicMock()
    iterator.iterate.return_value = iter(entities)
    with patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator), \
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()):
        return ComplianceManager().run_policy_inline(db, policy=policy)


PRODUCT = {
    'type': 'data_product', 'id': 'prod-1', 'name': 'Orders', 'status': 'active', 'owner': '',
}


def test_all_fail_messages_are_kept_in_order(db_session):
    policy = _policy(db_session, (
        "MATCH (prod:data_product)\n"
        "ASSERT prod.status = 'retired'\n"
        "ON_FAIL FAIL 'Missing owner'\n"
        "ON_FAIL FAIL 'Missing description'"
    ))

    run = _run(db_session, policy, [PRODUCT])

    [result] = db_session.query(ComplianceResultDb).filter_by(run_id=run.id).all()
    assert result.passed is False
    assert result.message == 'Missing owner; Missing description'


def test_rule_is_parsed_once_per_run(db_session):
    policy = _policy(db_session, "MATCH (prod:data_product)\nASSERT prod.status = 'active'")
    spy = MagicMock(wraps=compliance_dsl.parse_rule)

    with patch('src.controller.compliance_manager.parse_rule', spy), \
            patch('src.common.compliance_dsl.parse_rule', spy):
        _run(db_session, policy, [PRODUCT])

    assert spy.call_count == 1


def test_trailing_input_warning_names_the_policy(db_session, caplog):
    policy = _policy(
        db_session,
        "MATCH (prod:data_product)\nASSERT prod.owner IS NOT NULL",
        name='Owner required',
    )

    with caplog.at_level('WARNING', logger='src.common.compliance_dsl'):
        _run(db_session, policy, [PRODUCT])

    warnings = [
        r.getMessage() for r in caplog.records if 'unparsed trailing input' in r.getMessage()
    ]
    assert len(warnings) == 1
    assert f"policy 'Owner required' ({policy.id})" in warnings[0]
