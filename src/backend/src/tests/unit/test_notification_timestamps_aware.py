"""Notifications are stamped with aware UTC times (#1449).

Notification columns are ``DateTime(timezone=True)``. Postgres reads a naive
value written into one in the session's time zone, so ``datetime.utcnow()``
stored notifications shifted by the server's UTC offset and the bell showed
them as "in 1 hour" (or an hour old). The suite runs on SQLite, which drops the
offset, so this guards the source instead: no ``Notification(...)`` takes its
``created_at`` / ``updated_at`` from ``datetime.utcnow()``, directly or through
a local variable.
"""
import ast
from datetime import timezone
from pathlib import Path

from src.common.timestamps import utc_now

SRC = Path(__file__).resolve().parents[2]


def _is_utcnow(node) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'utcnow'
    )


def _naive_notification_stamps(tree):
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        naive_names = {
            target.id
            for node in ast.walk(func) if isinstance(node, ast.Assign) and _is_utcnow(node.value)
            for target in node.targets if isinstance(target, ast.Name)
        }
        for node in ast.walk(func):
            if not (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'Notification'):
                continue
            for kw in node.keywords:
                if kw.arg not in ('created_at', 'updated_at'):
                    continue
                if _is_utcnow(kw.value) or (isinstance(kw.value, ast.Name) and kw.value.id in naive_names):
                    yield node.lineno


def test_no_notification_is_stamped_with_a_naive_time():
    offenders = []
    for path in SRC.rglob('*.py'):
        if 'tests' in path.relative_to(SRC).parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        offenders += [f'{path.relative_to(SRC)}:{line}' for line in _naive_notification_stamps(tree)]

    assert offenders == []


def test_utc_now_is_aware_utc():
    now = utc_now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timezone.utc.utcoffset(now)


def test_the_guard_finds_both_spellings():
    tree = ast.parse(
        'def f():\n'
        '    now = datetime.utcnow()\n'
        '    Notification(id="1", created_at=now)\n'
        '    Notification(id="2", created_at=datetime.utcnow())\n'
        '    Notification(id="3", created_at=utc_now())\n'
    )

    assert list(_naive_notification_stamps(tree)) == [3, 4]


# --- Cutoffs and the session time zone ----------------------------------------

from datetime import timedelta  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from urllib.parse import unquote  # noqa: E402

from src.common.config import Settings  # noqa: E402
from src.common.database import get_db_url  # noqa: E402
from src.db_models.llm_sessions import LLMSessionDb  # noqa: E402
from src.db_models.process_workflows import WorkflowExecutionDb  # noqa: E402
from src.repositories.llm_sessions_repository import llm_sessions_repository as llm_sessions_repo  # noqa: E402
from src.repositories.process_workflows_repository import workflow_execution_repo  # noqa: E402


def test_old_llm_sessions_expire_by_an_aware_cutoff(db_session):
    old = LLMSessionDb(user_id='u@example.com', updated_at=utc_now() - timedelta(hours=48))
    fresh = LLMSessionDb(user_id='u@example.com', updated_at=utc_now() - timedelta(minutes=5))
    db_session.add_all([old, fresh])
    db_session.commit()

    deleted = llm_sessions_repo.cleanup_old_sessions(db_session, max_age_hours=24)

    assert deleted == 1
    assert [s.id for s in db_session.query(LLMSessionDb).all()] == [fresh.id]


def test_old_workflow_executions_are_deleted_by_an_aware_cutoff(db_session):
    old = WorkflowExecutionDb(workflow_id='wf-1', status='succeeded', started_at=utc_now() - timedelta(days=10))
    fresh = WorkflowExecutionDb(workflow_id='wf-1', status='succeeded', started_at=utc_now() - timedelta(hours=1))
    db_session.add_all([old, fresh])
    db_session.commit()

    deleted = workflow_execution_repo.delete_bulk(db_session, older_than_days=7)

    assert deleted == 1
    assert [e.id for e in db_session.query(WorkflowExecutionDb).all()] == [fresh.id]


def test_postgres_sessions_run_in_utc():
    """Naive UTC values (column defaults, older call sites) are read as UTC, not local time."""
    settings = MagicMock(spec=Settings)
    settings.PGHOST, settings.PGPORT, settings.PGDATABASE = 'localhost', 5432, 'app'
    settings.PGUSER, settings.PGPASSWORD, settings.PGSCHEMA = 'role', 'secret', 'app_schema'
    settings.ENV, settings.DB_USE_PASSWORD_AUTH = 'LOCAL', False

    url = unquote(get_db_url(settings))

    assert '-ctimezone=UTC' in url
    assert '-csearch_path=app_schema' in url
