"""Notifications must be stamped with timezone-aware UTC (#1449).

A naive ``datetime.utcnow()`` stored in a ``DateTime(timezone=True)`` column is read by
Postgres in the session time zone, so the UTC wall clock ends up shifted by the server's
UTC offset.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from src.controller.notifications_manager import NotificationsManager

SRC = Path(__file__).resolve().parents[2]


def _is_naive_utcnow(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == 'utcnow'
    )


def test_no_notification_is_built_with_naive_utcnow():
    offenders = []
    for path in SRC.rglob('*.py'):
        if 'tests' in path.relative_to(SRC).parts:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            naive_names = {
                t.id
                for n in ast.walk(func)
                if isinstance(n, ast.Assign) and _is_naive_utcnow(n.value)
                for t in n.targets
                if isinstance(t, ast.Name)
            }
            for node in ast.walk(func):
                if not (
                    isinstance(node, ast.Call)
                    and getattr(node.func, 'id', None) == 'Notification'
                ):
                    continue
                for kw in node.keywords:
                    if kw.arg not in ('created_at', 'updated_at'):
                        continue
                    naive_name = isinstance(kw.value, ast.Name) and kw.value.id in naive_names
                    if _is_naive_utcnow(kw.value) or naive_name:
                        offenders.append(f"{path.relative_to(SRC)}:{kw.value.lineno}")
    assert offenders == []


def test_create_user_notification_is_timezone_aware():
    manager = NotificationsManager(settings_manager=MagicMock())
    repo = manager._repo = MagicMock()
    repo.create.side_effect = lambda db, obj_in: obj_in
    asyncio.run(manager.create_user_notification(db=MagicMock(), user_id='a@b.c', title='t'))
    created = repo.create.call_args.kwargs['obj_in']
    assert created.created_at.tzinfo is not None
    assert created.created_at.utcoffset().total_seconds() == 0


def test_completed_delivery_notification_is_stamped_with_aware_utc():
    from datetime import datetime

    manager = NotificationsManager(settings_manager=MagicMock())
    repo = manager._repo = MagicMock()
    repo.get.return_value = MagicMock(action_payload=None)
    repo.update.side_effect = lambda db, db_obj, obj_in: obj_in
    try:
        manager.complete_delivery_notification(db=MagicMock(), notification_id='n', completed_by='x')
    except Exception:
        pass
    update_data = repo.update.call_args.kwargs['obj_in']
    assert update_data['updated_at'].utcoffset().total_seconds() == 0
    completed_at = datetime.fromisoformat(update_data['action_payload']['completed_at'])
    assert completed_at.utcoffset().total_seconds() == 0


def test_timestamptz_columns_do_not_default_to_naive_utcnow():
    offenders = []
    for path in (SRC / 'db_models').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg in ('default', 'onupdate'):
                v = node.value
                if isinstance(v, ast.Attribute) and v.attr == 'utcnow':
                    offenders.append(f"{path.name}:{v.lineno}")
    assert offenders == []
