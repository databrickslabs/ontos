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
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, 'id', None) == 'Notification'
            ):
                for kw in node.keywords:
                    if kw.arg in ('created_at', 'updated_at') and _is_naive_utcnow(kw.value):
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
