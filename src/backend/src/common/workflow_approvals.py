"""Open approval notifications of a workflow execution.

Shared by the workflow routes and the managers that cancel or decide an
execution, so none of them repeats the query.
"""

import json
from typing import Any, List, Set

from sqlalchemy.orm import Session

from src.db_models.notifications import NotificationDb


def is_handled(notification: Any) -> bool:
    """Whether the approval notification's decision was already recorded."""
    payload = notification.action_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return False
    return isinstance(payload, dict) and bool(payload.get('handled'))


def open_execution_approvals(db: Session, execution_id: str) -> List[NotificationDb]:
    """The approval notifications of ``execution_id`` not handled yet, read or not.

    The text filter (the quoted id) narrows the rows in SQL; callers check
    the payload's ``execution_id`` exactly.
    """
    rows = db.query(NotificationDb).filter(
        NotificationDb.action_type == 'workflow_approval',
        NotificationDb.action_payload.contains(json.dumps(execution_id)),
    ).all()
    return [n for n in rows if not is_handled(n)]


def open_approval_ids(db: Session, execution_id: str) -> Set[str]:
    """Ids of the approval notifications of ``execution_id`` open right now."""
    return {n.id for n in open_execution_approvals(db, execution_id)}
