"""Open approval notifications of a workflow execution.

Shared by the workflow routes and the managers that cancel or decide an
execution, so none of them repeats the query.
"""

import json
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy.orm import Session

from src.db_models.notifications import NotificationDb


def _payload(notification: Any) -> Dict[str, Any]:
    payload = notification.action_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    return payload if isinstance(payload, dict) else {}


def is_handled(notification: Any) -> bool:
    """Whether the approval notification's decision was already recorded."""
    return bool(_payload(notification).get('handled'))


def decided_by_users(notification: Any) -> Set[str]:
    """Who already decided the notification's step, lower-cased (``decided_by_users``, #1552).

    A require_all step takes one decision per person, while a role or group
    target is one row shared by its members: a member who decided the step
    through another target can't decide this row any more.
    """
    names = _payload(notification).get('decided_by_users')
    if not isinstance(names, list):
        return set()
    return {str(name).strip().lower() for name in names if name}


def add_decided_by_users(payload: Dict[str, Any], deciders: Iterable[Optional[str]]) -> bool:
    """Add ``deciders`` to the payload's ``decided_by_users``; whether it changed."""
    current = payload.get('decided_by_users')
    names = set(current) if isinstance(current, list) else set()
    merged = names | {str(d).strip().lower() for d in deciders if d}
    if merged == names:
        return False
    payload['decided_by_users'] = sorted(merged)
    return True


def has_decided(notification: Any, user_info: Any) -> bool:
    """Whether ``user_info`` (email or username) is in the notification's
    ``decided_by_users``."""
    if user_info is None:
        return False
    caller = {
        str(v).strip().lower()
        for v in (getattr(user_info, 'email', None), getattr(user_info, 'username', None)) if v
    }
    return bool(caller & decided_by_users(notification))


def execution_approvals(db: Session, execution_id: str) -> List[NotificationDb]:
    """The approval notifications of ``execution_id``, handled or not.

    The text filter (the quoted id) narrows the rows in SQL; callers check
    the payload's ``execution_id`` exactly.
    """
    return db.query(NotificationDb).filter(
        NotificationDb.action_type == 'workflow_approval',
        NotificationDb.action_payload.contains(json.dumps(execution_id)),
    ).all()


def open_execution_approvals(db: Session, execution_id: str) -> List[NotificationDb]:
    """The approval notifications of ``execution_id`` not handled yet, read or not."""
    return [n for n in execution_approvals(db, execution_id) if not is_handled(n)]


def open_approval_ids(db: Session, execution_id: str) -> Set[str]:
    """Ids of the approval notifications of ``execution_id`` open right now."""
    return {n.id for n in open_execution_approvals(db, execution_id)}
