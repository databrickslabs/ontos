"""The ak9 data migration updates the shipped review-flow defaults (#859 review S7, B10, S8)."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, text

_NAME = 'ak9_default_workflow_review_flow'
_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def migration():
    path = _ROOT / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def conn(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ak9.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE process_workflows (id VARCHAR PRIMARY KEY, name VARCHAR, "
            "description TEXT, is_default BOOLEAN, is_customized BOOLEAN)"
        ))
        connection.execute(text(
            "CREATE TABLE workflow_steps (id VARCHAR PRIMARY KEY, workflow_id VARCHAR, step_id VARCHAR, "
            "name VARCHAR, step_type VARCHAR, config TEXT, on_pass VARCHAR, on_fail VARCHAR, "
            "\"order\" INTEGER, position TEXT, created_at TEXT, updated_at TEXT)"
        ))
        yield connection


def _workflow(conn, wf_id, name, *, default=True, customized=False):
    conn.execute(text(
        "INSERT INTO process_workflows (id, name, description, is_default, is_customized) "
        "VALUES (:id, :name, 'old description', :d, :c)"
    ), {'id': wf_id, 'name': name, 'd': default, 'c': customized})


def _step(conn, wf_id, step_id, step_type, config, on_pass=None, on_fail=None):
    conn.execute(text(
        "INSERT INTO workflow_steps VALUES (:id, :wf, :sid, :name, :type, :config, :on_pass, :on_fail, "
        "0, NULL, NULL, NULL)"
    ), {'id': f'{wf_id}-{step_id}', 'wf': wf_id, 'sid': step_id, 'name': step_id, 'type': step_type,
        'config': json.dumps(config), 'on_pass': on_pass, 'on_fail': on_fail})


def _steps(conn, wf_id):
    rows = conn.execute(text(
        "SELECT step_id, step_type, config, on_pass FROM workflow_steps WHERE workflow_id = :wf "
        "ORDER BY step_id"
    ), {'wf': wf_id}).all()
    return {sid: (stype, json.loads(cfg), on_pass) for sid, stype, cfg, on_pass in rows}


def _seed_old_ar(conn, wf_id='ar', customized=False):
    _workflow(conn, wf_id, 'Authority Relation Review Request', customized=customized)
    _step(conn, wf_id, 'notify-owner', 'notification',
          {'recipients': 'requester', 'template': 'request_submitted'}, on_pass='success')
    _step(conn, wf_id, 'success', 'pass', {})


def _seed_old_data_asset(conn, wf_id='da', customized=False):
    _workflow(conn, wf_id, 'Data Asset Review Request', customized=customized)
    _step(conn, wf_id, 'notify-reviewer', 'notification',
          {'recipients': 'owner', 'template': 'request_submitted'}, on_pass='request-approval')
    _step(conn, wf_id, 'request-approval', 'approval', {'approvers': 'DataSteward'},
          on_pass='notify-approved', on_fail='notify-rejected')
    _step(conn, wf_id, 'notify-approved', 'notification', {'recipients': 'requester'}, on_pass='success')
    _step(conn, wf_id, 'notify-rejected', 'notification', {'recipients': 'requester'}, on_pass='fail-rejected')
    _step(conn, wf_id, 'success', 'pass', {})
    _step(conn, wf_id, 'fail-rejected', 'fail', {'message': 'needs changes'})


def test_ar_default_is_replaced_by_the_reviewer_notification_only(conn, migration):
    _seed_old_ar(conn)

    counts = migration.apply_review_flow_defaults(conn)

    assert counts['ar_workflow_steps_replaced'] == 1
    steps = _steps(conn, 'ar')
    assert set(steps) == {'notify-reviewer', 'success'}
    stype, config, on_pass = steps['notify-reviewer']
    assert stype == 'notification'
    assert config['recipients'] == 'reviewers'
    assert config['fail_flow_on_failure'] is False
    assert conn.execute(text("SELECT description FROM process_workflows WHERE id = 'ar'")).scalar() == (
        migration.AR_WORKFLOW_DESCRIPTION
    )
    assert on_pass == 'success'
    assert steps['success'][0] == 'pass'


def test_customised_ar_default_is_left_alone(conn, migration):
    _seed_old_ar(conn, customized=True)

    counts = migration.apply_review_flow_defaults(conn)

    assert counts['ar_workflow_steps_replaced'] == 0
    assert set(_steps(conn, 'ar')) == {'notify-owner', 'success'}


def test_data_asset_default_notifies_the_reviewer_and_is_best_effort(conn, migration):
    _seed_old_data_asset(conn)

    counts = migration.apply_review_flow_defaults(conn)

    assert counts['data_asset_steps_updated'] == 3
    steps = _steps(conn, 'da')
    assert steps['notify-reviewer'][1] == {'recipients': 'reviewer', 'template': 'request_submitted',
                                           'fail_flow_on_failure': False}
    assert steps['notify-approved'][1]['fail_flow_on_failure'] is False
    assert steps['notify-rejected'][1]['fail_flow_on_failure'] is False
    # The DataSteward approval of a generic data-asset review is unchanged
    assert steps['request-approval'][0] == 'approval'
    assert steps['request-approval'][1] == {'approvers': 'DataSteward'}


def test_customised_data_asset_default_is_left_alone(conn, migration):
    _seed_old_data_asset(conn, customized=True)

    counts = migration.apply_review_flow_defaults(conn)

    assert counts['data_asset_steps_updated'] == 0
    assert _steps(conn, 'da')['notify-reviewer'][1]['recipients'] == 'owner'


def test_an_unreadable_step_config_is_left_untouched(conn, migration, caplog):
    """A config that doesn't parse is never rewritten: the row is left as it is, and a warning is logged."""
    _seed_old_data_asset(conn)
    conn.execute(text("UPDATE workflow_steps SET config = 'not json {' WHERE id = 'da-notify-reviewer'"))

    with caplog.at_level('WARNING'):
        counts = migration.apply_review_flow_defaults(conn)

    assert conn.execute(text("SELECT config FROM workflow_steps WHERE id = 'da-notify-reviewer'")).scalar() == 'not json {'
    assert counts['data_asset_steps_updated'] == 2  # the two readable notifications still updated
    assert 'unreadable config' in caplog.text


def test_a_user_workflow_with_the_same_step_names_is_untouched(conn, migration):
    _workflow(conn, 'mine', 'My review', default=False)
    _step(conn, 'mine', 'notify-reviewer', 'notification', {'recipients': 'owner'})

    migration.apply_review_flow_defaults(conn)

    assert _steps(conn, 'mine')['notify-reviewer'][1] == {'recipients': 'owner'}


def test_running_twice_changes_nothing_further(conn, migration):
    _seed_old_ar(conn)
    _seed_old_data_asset(conn)
    migration.apply_review_flow_defaults(conn)
    before = _steps(conn, 'ar'), _steps(conn, 'da')

    migration.apply_review_flow_defaults(conn)

    assert (_steps(conn, 'ar'), _steps(conn, 'da')) == before


def test_migration_steps_match_the_shipped_yaml(migration):
    data = yaml.safe_load((_ROOT / 'src' / 'data' / 'default_workflows.yaml').read_text())
    workflows = data['workflows'] if isinstance(data, dict) else data
    ar = next(w for w in workflows if w['name'] == migration.AR_WORKFLOW_NAME)

    expected = [(s['id'], s['name'], s['type'], s.get('config', {}), s.get('on_pass')) for s in ar['steps']]
    assert list(migration.AR_STEPS) == expected
    assert migration.AR_WORKFLOW_DESCRIPTION == ar['description']


def test_revision_chains_on_ak8(migration):
    assert migration.revision == _NAME
    assert migration.down_revision == 'ak8_authority_prerequisites_by_version'
