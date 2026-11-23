"""Tag actions on an LLM_CHECK rule are refused when a run starts and in the YAML
load, not only on the API save, so a rule stored another way writes no tag (#1479)."""
import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.tests.helpers import FakeLlm, llm_reply

GRAIN = 'states the grain of the table'
TAG_RULE = (
    "MATCH (d:domain)\n"
    f"ASSERT LLM_CHECK(d.description, '{GRAIN}')\n"
    "ON_FAIL ASSIGN_TAG needs_docs: 'yes'"
)


@pytest.fixture(autouse=True)
def short_texts(monkeypatch):
    from src.common import compliance_llm_check

    monkeypatch.setattr(compliance_llm_check, 'LLM_CHECK_MIN_TEXT_CHARS', 1)


def _policy(db, rule, **extra):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name=f'p-{uuid.uuid4()}', rule=rule,
                                **extra)
    db.add(policy)
    db.flush()
    return policy


def _settings():
    return SimpleNamespace(
        LLM_ENABLED=True, LLM_ENDPOINT='test-endpoint', COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN=10,
    )


def _run(db, policy, entities, fake, tag_manager):
    iterator = MagicMock()
    iterator.iterate.side_effect = lambda *a, **k: iter(entities)
    with patch('src.controller.compliance_manager.create_entity_iterator',
               return_value=iterator) as factory, \
            patch('src.controller.compliance_manager.TagsManagerTagAdapter',
                  return_value=tag_manager), \
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()), \
            patch('src.common.config.get_settings', return_value=_settings()), \
            patch('src.common.llm_client.create_openai_client', return_value=fake), \
            patch('src.controller.compliance_manager.served_model_of',
                  return_value='test-model:1'):
        return ComplianceManager().run_policy_inline(db, policy=policy), factory


# --- Tag actions at run time -------------------------------------------------------

def test_a_stored_llm_check_rule_with_tag_actions_fails_its_run_and_writes_no_tag(db_session):
    # Stored without the API save (an older save, the database): the run refuses it
    policy = _policy(db_session, TAG_RULE)
    fake = FakeLlm(answer=lambda kwargs: llm_reply('FAIL: no grain'))
    tag_manager = MagicMock()

    run, factory = _run(db_session, policy, [
        {'type': 'domain', 'id': 'd1', 'name': 'sales', 'description': 'some text'},
    ], fake, tag_manager)

    assert run.status == 'failed'
    assert run.error_code == 'llm_check_tag_action'
    assert '"actions": "ASSIGN_TAG"' in (run.error_params or '')
    # Refused before any entity is read or judged: no model call, no result, no tag
    factory.assert_not_called()
    assert fake.calls == []
    assert db_session.query(ComplianceResultDb).filter_by(run_id=run.id).count() == 0
    assert tag_manager.mock_calls == []


def test_the_refused_run_error_reaches_readers_as_its_code():
    from src.common.compliance_errors import public_run_error

    assert public_run_error('failed', 'llm_check_tag_action', {'actions': 'REMOVE_TAG'}) == (
        'llm_check_tag_action', {'actions': 'REMOVE_TAG'},
    )


def test_an_llm_check_rule_with_notify_still_runs(db_session):
    rule = (
        "MATCH (d:domain)\n"
        f"ASSERT LLM_CHECK(d.description, '{GRAIN}')\n"
        "ON_FAIL FAIL 'Grain missing'"
    )
    policy = _policy(db_session, rule)
    fake = FakeLlm(answer=lambda kwargs: llm_reply('FAIL: no grain'))

    run, _ = _run(db_session, policy, [
        {'type': 'domain', 'id': 'd1', 'name': 'sales', 'description': 'some text'},
    ], fake, MagicMock())

    assert run.status == 'succeeded'
    assert run.failure_count == 1


def test_a_tag_rule_without_llm_check_still_writes_tags(db_session):
    rule = "MATCH (d:domain)\nASSERT d.name = 'other'\nON_FAIL ASSIGN_TAG checked: 'yes'"
    policy = _policy(db_session, rule)
    tag_manager = MagicMock()

    run, _ = _run(db_session, policy, [
        {'type': 'domain', 'id': 'd1', 'name': 'sales'},
    ], FakeLlm(answer=lambda kwargs: llm_reply('PASS: x')), tag_manager)

    assert run.status == 'succeeded'
    assert run.error_code is None


# --- Tag actions in the YAML load --------------------------------------------------

def _write_yaml(tmp_path, policies):
    import yaml

    path = tmp_path / 'compliance_policies.yaml'
    path.write_text(yaml.safe_dump(policies))
    return str(path)


def test_the_yaml_load_skips_an_llm_check_rule_with_tag_actions(db_session, tmp_path):
    ok_rule = f"MATCH (d:domain)\nASSERT LLM_CHECK(d.description, '{GRAIN}')"
    tags_id, ok_id = str(uuid.uuid4()), str(uuid.uuid4())
    path = _write_yaml(tmp_path, [
        {'id': tags_id, 'name': 'Tags on a verdict', 'description': 'd', 'rule': TAG_RULE},
        {'id': ok_id, 'name': 'Verdict only', 'description': 'd', 'rule': ok_rule},
    ])

    ComplianceManager().load_from_yaml(db_session, path)

    assert db_session.get(CompliancePolicyDb, tags_id) is None
    assert db_session.get(CompliancePolicyDb, ok_id).rule == ok_rule


def test_the_yaml_load_does_not_overwrite_a_stored_policy_with_such_a_rule(
    db_session, tmp_path,
):
    stored = _policy(db_session, "MATCH (d:domain)\nASSERT d.name != ''")
    path = _write_yaml(tmp_path, [
        {'id': stored.id, 'name': 'Changed', 'description': 'd', 'rule': TAG_RULE},
    ])

    ComplianceManager().load_from_yaml(db_session, path)

    db_session.refresh(stored)
    assert stored.rule == "MATCH (d:domain)\nASSERT d.name != ''"
