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
