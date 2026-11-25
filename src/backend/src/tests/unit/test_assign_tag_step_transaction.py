"""A database error in an Assign Tag step's tag lookup or write fails the step, and
the run still records that step. The same holds for a Remove Tag step (which passes,
context only, as before) and for the tag lookup of workflow validation.

On PostgreSQL a failed statement aborts the transaction: every later statement in it
fails until a rollback. Without a savepoint around the tag operation, the executor's
write of the failed step result hit that aborted transaction, so the run raised
instead of recording the failure. On SQLite a failed flush leaves the SQLAlchemy
session needing a rollback, with the same effect. The SQLite cases always run; the
PostgreSQL ones run when ``ONTOS_TEST_PG_DSN`` names a throwaway database (a
``postgresql+psycopg2://`` URL); each makes and drops its own schema.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.common.database import Base
from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import WorkflowStepExecutionDb
from src.db_models.tags import EntityTagAssociationDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.process_workflows_repository import process_workflow_repo
from src.repositories.tags_repository import (
    EntityTagAssociationRepository,
    TagRepository,
    seed_default_tags,
)

PG_DSN = os.environ.get('ONTOS_TEST_PG_DSN')


@pytest.fixture
def pg_session():
    if not PG_DSN:
        pytest.skip('ONTOS_TEST_PG_DSN not set; the PostgreSQL case needs a live database')
    schema = f'wf_tag_tx_{uuid.uuid4().hex[:8]}'
    admin = create_engine(PG_DSN, future=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(
        PG_DSN, future=True, connect_args={'options': f'-csearch_path={schema}'},
    )
    session = None
    try:
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine, autoflush=False)()
        yield session
    finally:
        if session is not None:
            session.close()
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


@pytest.fixture(params=['sqlite', 'postgresql'])
def db(request):
    if request.param == 'sqlite':
        return request.getfixturevalue('db_session')
    return request.getfixturevalue('pg_session')


def _failing_lookup(self, db, *, fqn):
    # A statement the database refuses: on PostgreSQL it aborts the transaction
    db.execute(text('SELECT missing_column FROM tags'))


def _failing_write(self, db, *, tag_id, entity_id, entity_type, **_kwargs):
    # A row the database refuses at flush (entity_id is NOT NULL)
    db.add(EntityTagAssociationDb(tag_id=tag_id, entity_id=None, entity_type=entity_type))
    db.flush()


def _break(monkeypatch, failure, write_method='add_tag_to_entity'):
    if failure == 'lookup':
        monkeypatch.setattr(TagRepository, 'get_by_fully_qualified_name', _failing_lookup)
    else:
        monkeypatch.setattr(EntityTagAssociationRepository, write_method, _failing_write)


def _workflow(step_type):
    return ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.TABLE]),
        steps=[WorkflowStepCreate(step_id='tag', step_type=step_type, config={'key': 'owner'})],
    )


def _run(db, workflow_id):
    workflow = WorkflowsManager(db).get_workflow(workflow_id)
    return WorkflowExecutor(db).execute_workflow(
        workflow=workflow,
        entity={'id': 't-1', 'name': 'orders'},
        entity_type='table',
        entity_id='t-1',
        entity_name='orders',
        user_email='pat@example.com',
        trigger_context=TriggerContext(
            entity_type='table', entity_id='t-1', entity_name='orders',
            trigger_type=TriggerType.MANUAL, user_email='pat@example.com',
        ),
    )


def _stored_steps(db, execution_id):
    # Read back after the run's commits: stored, not only returned
    db.expire_all()
    rows = db.query(WorkflowStepExecutionDb).filter_by(execution_id=execution_id).all()
    return [(s.step_key, s.passed) for s in rows]


@pytest.mark.parametrize('failure', ['lookup', 'write'])
def test_a_tag_database_error_fails_the_step_and_the_run_records_it(db, monkeypatch, failure):
    seed_default_tags(db)
    db.commit()
    workflow_id = process_workflow_repo.create(db, _workflow(StepType.ASSIGN_TAG)).id
    _break(monkeypatch, failure)

    execution = _run(db, workflow_id)

    assert execution.status.value == 'failed'
    [step] = execution.step_executions
    assert step.step_key == 'tag'
    assert step.passed is False
    assert step.error_message == "Could not assign tag 'owner'"
    assert _stored_steps(db, execution.id) == [('tag', False)]
    # The refused write left nothing behind
    assert db.query(EntityTagAssociationDb).filter_by(entity_id='t-1').count() == 0


@pytest.mark.parametrize('failure', ['lookup', 'write'])
def test_a_remove_tag_database_error_still_lets_the_run_record_the_step(
    db, monkeypatch, failure,
):
    [owner, _pii] = seed_default_tags(db)
    db.add(EntityTagAssociationDb(tag_id=owner.id, entity_id='t-1', entity_type='table'))
    db.commit()
    workflow_id = process_workflow_repo.create(db, _workflow(StepType.REMOVE_TAG)).id
    _break(monkeypatch, failure, 'remove_tag_from_entity')

    execution = _run(db, workflow_id)

    # As before: a Remove Tag step that could not persist passes, context only
    [step] = execution.step_executions
    assert step.passed is True
    assert step.result_data['persisted'] is False
    assert _stored_steps(db, execution.id) == [('tag', True)]
    # The assignment is still there
    assert db.query(EntityTagAssociationDb).filter_by(entity_id='t-1').count() == 1


def test_a_failed_tag_lookup_in_validate_leaves_the_session_usable(db, monkeypatch):
    workflow = _workflow(StepType.ASSIGN_TAG)
    _break(monkeypatch, 'lookup')

    result = WorkflowsManager(db).validate_workflow(workflow)

    # The lookup is skipped (logged): no warning, and the save that follows works
    assert 'assign_tag_key_unknown' not in {w.code for w in result.warning_issues}
    saved = process_workflow_repo.create(db, workflow)
    assert WorkflowsManager(db).get_workflow(saved.id).name == workflow.name
