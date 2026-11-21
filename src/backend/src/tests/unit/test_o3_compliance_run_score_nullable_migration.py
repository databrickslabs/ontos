"""A compliance run without a score stores NULL (o3 migration, #1387 review).

The migration runs through Alembic on SQLite; the run tests check that a run
that failed or evaluated nothing stores None instead of 0.0.
"""
import importlib.util
import os
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb

_NAME = 'o3_compliance_run_score_nullable'


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(conn, step):
    with Operations.context(MigrationContext.configure(conn)):
        step()


def _score_nullable(conn):
    column = next(c for c in sa.inspect(conn).get_columns('compliance_runs')
                  if c['name'] == 'score')
    return column['nullable']


def _scores(conn):
    rows = conn.execute(text("SELECT id, score FROM compliance_runs")).all()
    return dict(rows)


def test_upgrade_stores_null_for_runs_without_a_score_and_downgrade_restores_zero(
    tmp_path, migration,
):
    assert migration.down_revision == 's2_document_markdown_import'
    engine = create_engine(f"sqlite:///{tmp_path / 'o3.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE compliance_runs (id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, "
            "success_count INTEGER NOT NULL, failure_count INTEGER NOT NULL, "
            "score FLOAT NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO compliance_runs VALUES "
            "('scored', 'succeeded', 4, 1, 80.0), ('all_failed', 'succeeded', 0, 3, 0.0), "
            "('empty', 'succeeded', 0, 0, 0.0), ('failed', 'failed', 2, 0, 0.0), "
            "('running', 'running', 0, 0, 0.0)"
        ))
        assert _score_nullable(conn) is False

        _apply(conn, migration.upgrade)
        assert _score_nullable(conn) is True
        assert _scores(conn) == {
            'scored': 80.0, 'all_failed': 0.0, 'empty': None, 'failed': None, 'running': 0.0,
        }

        _apply(conn, migration.downgrade)
        assert _score_nullable(conn) is False
        assert _scores(conn) == {
            'scored': 80.0, 'all_failed': 0.0, 'empty': 0.0, 'failed': 0.0, 'running': 0.0,
        }


def _policy(db, rule):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='p', is_active=True, rule=rule)
    db.add(policy)
    db.flush()
    return policy


def test_a_run_that_matched_nothing_stores_no_score(db_session):
    policy = _policy(db_session, "MATCH (p:data_product) ASSERT p.name != ''")

    run = ComplianceManager().run_policy_inline(db_session, policy=policy)
    db_session.expire(run)

    assert run.status == 'succeeded'
    assert (run.success_count, run.failure_count, run.score) == (0, 0, None)


def test_a_failed_run_stores_no_score(db_session):
    policy = _policy(db_session, "MATCH (p:data_product) ASSERT p.name != ''")

    with patch('src.controller.compliance_manager.parse_rule', side_effect=RuntimeError('x')):
        run = ComplianceManager().run_policy_inline(db_session, policy=policy)
    db_session.expire(run)

    assert run.status == 'failed'
    assert run.score is None
