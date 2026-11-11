"""The tags the shipped default workflows assign exist on a fresh install.

``owner`` (Naming Convention Validation, Data Contract Schema Validation) and
``contains_pii`` (PII Detection) are seeded in the default namespace at startup,
like the other reference data. The seed is idempotent and never changes a tag
that already exists.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path

import yaml

from src.common.workflow_executor import AssignTagStepHandler, StepContext
from src.db_models.tags import TagDb
from src.repositories.tags_repository import seed_default_tags, tag_namespace_repo

DEFAULT_WORKFLOWS = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'


def _default_step(workflow_id: str, step_id: str) -> dict:
    workflows = yaml.safe_load(DEFAULT_WORKFLOWS.read_text(encoding='utf-8'))['workflows']
    workflow = next(w for w in workflows if w['id'] == workflow_id)
    return next(s for s in workflow['steps'] if s['id'] == step_id)


def _context(entity_id: str) -> StepContext:
    return StepContext(
        entity={'name': 'orders'}, entity_type='table', entity_id=entity_id,
        entity_name='orders', user_email='analyst@example.com', trigger_context=None,
        execution_id='exec-1', workflow_id='wf-1', workflow_name='W', step_results={},
    )


def _tags_named(db, name):
    default = tag_namespace_repo.get_or_create_default_namespace(db, user_email=None)
    return db.query(TagDb).filter_by(namespace_id=default.id, name=name).all()


def test_a_fresh_install_runs_the_naming_convention_assign_step(db_session):
    seed_default_tags(db_session)
    step = _default_step('naming-convention-check', 'auto-fix-owner-tag')

    result = AssignTagStepHandler(db_session, step['config']).execute(_context(f'tbl-{uuid.uuid4().hex[:8]}'))

    assert result.passed is True, result.error
    assert result.data['persisted'] is True


def test_a_fresh_install_runs_the_pii_detection_assign_step(db_session):
    seed_default_tags(db_session)
    step = _default_step('pii-detection', 'tag-pii')

    result = AssignTagStepHandler(db_session, step['config']).execute(_context(f'tbl-{uuid.uuid4().hex[:8]}'))

    assert result.passed is True, result.error
    assert result.data['persisted'] is True


def test_the_seed_creates_the_two_default_tags_in_the_default_namespace(db_session):
    seed_default_tags(db_session)

    for name in ('owner', 'contains_pii'):
        [tag] = _tags_named(db_session, name)
        assert tag.status == 'active'
        assert tag.description


def test_the_seed_is_idempotent(db_session):
    seed_default_tags(db_session)
    seed_default_tags(db_session)

    assert len(_tags_named(db_session, 'owner')) == 1
    assert len(_tags_named(db_session, 'contains_pii')) == 1


def test_the_seed_keeps_a_tag_the_user_already_edited(db_session):
    default = tag_namespace_repo.get_or_create_default_namespace(db_session, user_email=None)
    db_session.add(TagDb(
        name='owner', description='Our team owner', status='draft',
        namespace_id=default.id, possible_values=['alice', 'bob'],
    ))
    db_session.flush()

    seed_default_tags(db_session)

    [tag] = _tags_named(db_session, 'owner')
    assert tag.description == 'Our team owner'
    assert tag.status == 'draft'
    assert tag.possible_values == ['alice', 'bob']
