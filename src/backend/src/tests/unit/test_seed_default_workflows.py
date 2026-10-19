"""Startup seeding of the default workflows (``requests_only_active``).

At startup the app creates the default workflows that don't exist yet. Only
request workflows (``on_request_*``) keep the YAML's ``is_active``; workflows
that run on their own events and the ``for_*`` UI wizards are created
inactive, and existing workflows are never changed.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
import yaml

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import ProcessWorkflowDb


def _workflow(name, trigger, is_active=True):
    return {
        'name': name, 'trigger': {'type': trigger, 'entity_types': ['data_product']},
        'scope': {'type': 'all'}, 'is_active': is_active, 'is_default': True,
        'steps': [{'id': 'done', 'name': 'Done', 'type': 'pass'}],
    }


def _write(tmp_path, workflows):
    path = tmp_path / 'workflows.yaml'
    path.write_text(yaml.safe_dump({'workflows': workflows}))
    return str(path)


def _active(db):
    return {wf.name: wf.is_active for wf in db.query(ProcessWorkflowDb).all()}


def test_only_request_workflows_are_created_active(db_session, tmp_path):
    path = _write(tmp_path, [
        _workflow('Review request', 'on_request_review'),
        _workflow('Disabled request', 'on_request_access', is_active=False),
        _workflow('Naming check', 'on_create'),
        _workflow('Subscribe wizard', 'for_subscribe'),
        _workflow('Gate', 'before_status_change'),
    ])

    result = WorkflowsManager(db_session).load_from_yaml(path, requests_only_active=True)

    assert result == {'created': 5, 'updated': 0, 'skipped': 0}
    assert _active(db_session) == {
        'Review request': True,
        'Disabled request': False,
        'Naming check': False,
        'Subscribe wizard': False,
        'Gate': False,
    }


def test_existing_workflows_are_left_untouched(db_session, tmp_path):
    first = _write(tmp_path, [_workflow('Naming check', 'on_create')])
    WorkflowsManager(db_session).load_from_yaml(first)  # Load defaults: YAML state
    assert _active(db_session) == {'Naming check': True}

    result = WorkflowsManager(db_session).load_from_yaml(first, requests_only_active=True)

    assert result == {'created': 0, 'updated': 0, 'skipped': 1}
    assert _active(db_session) == {'Naming check': True}


def test_load_defaults_keeps_the_yaml_state(db_session, tmp_path):
    path = _write(tmp_path, [_workflow('Naming check', 'on_create')])

    WorkflowsManager(db_session).load_from_yaml(path)

    assert _active(db_session) == {'Naming check': True}


def test_seeding_twice_creates_each_default_once(db_session, tmp_path):
    path = _write(tmp_path, [_workflow('Review request', 'on_request_review')])

    WorkflowsManager(db_session).load_from_yaml(path, requests_only_active=True)
    WorkflowsManager(db_session).load_from_yaml(path, requests_only_active=True)

    assert db_session.query(ProcessWorkflowDb).filter_by(name='Review request').count() == 1


def test_postgres_seeding_holds_an_advisory_lock(tmp_path):
    # Concurrent startups (replicas, rolling deploys) are serialized by a
    # Postgres advisory lock held on its own connection, released on errors.
    from unittest.mock import MagicMock

    db = MagicMock()
    engine = db.get_bind.return_value
    engine.dialect.name = 'postgresql'
    conn = engine.connect.return_value.__enter__.return_value
    manager = WorkflowsManager(db)
    manager._load_workflows = MagicMock(side_effect=RuntimeError('boom'))
    path = _write(tmp_path, [_workflow('Review request', 'on_request_review')])

    with pytest.raises(RuntimeError):
        manager.load_from_yaml(path, requests_only_active=True)

    statements = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert statements == ['SELECT pg_advisory_lock(:key)', 'SELECT pg_advisory_unlock(:key)']
