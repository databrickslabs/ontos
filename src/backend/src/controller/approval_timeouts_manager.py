"""Overdue approval steps: one reminder when ``timeout_days`` pass (#1119).

An approval step's ``timeout_days`` (default 7, copied into each approval notification's
payload) is "notify only": when the step's approvers haven't decided within it, the step is
marked overdue and its approvers and the requester get one reminder each. The workflow stays
paused: nothing is approved, rejected or escalated.

Idempotent: the step's open approval notifications get ``overdue_since`` in their payload, and
a step that has it is never reminded again. A step that is asked again (a workflow looping back
into it) opens new notifications and so a new period. Run by the workflow scheduler
(``WorkflowScheduler``), at most once per claimed slot across instances.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.timestamps import utc_now
from src.common.notification_i18n import notification_i18n_data
from src.common.workflow_approvals import open_execution_approvals
from src.db_models.process_workflows import WorkflowExecutionDb
from src.models.notifications import Notification, NotificationType
from src.repositories.notification_repository import notification_repo

logger = get_logger(__name__)

# The approval step's default (``ApprovalStepHandler``)
DEFAULT_TIMEOUT_DAYS = 7

APPROVER_TITLE = "Approval overdue"
REQUESTER_TITLE = "Your request is still waiting"


def _payload(notification: Any) -> Dict[str, Any]:
    payload = notification.action_payload
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    return payload if isinstance(payload, dict) else {}


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def timeout_days_of(payload: Dict[str, Any]) -> Optional[int]:
    """The step's ``timeout_days``; None when it has none (0, negative, not a number)."""
    value = payload.get('timeout_days', DEFAULT_TIMEOUT_DAYS)
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    return None


def _step_round(db: Session, execution: WorkflowExecutionDb) -> List[Any]:
    """The open approval notifications of the step the execution is paused at."""
    step_id = execution.current_step_id
    return [
        n for n in open_execution_approvals(db, execution.id)
        if _payload(n).get('execution_id') == execution.id
        and _payload(n).get('step_id') in (None, step_id)
    ]


def _targets(rows: Iterable[Any]) -> List[Tuple[Optional[str], Optional[str]]]:
    """The step's approvers as notified: (recipient, recipient_role_id), once each."""
    seen: List[Tuple[Optional[str], Optional[str]]] = []
    for row in rows:
        target = (row.recipient, row.recipient_role_id)
        if (target[0] or target[1]) and target not in seen:
            seen.append(target)
    return seen


def _i18n(title_key: str, description_key: str, name: str, days: int) -> Dict[str, Any]:
    """The reminder's i18n keys; ``count`` stays a number, so the texts can be plural."""
    data = notification_i18n_data(title_key, description_key, name=name)
    data['i18n']['params']['count'] = days
    return data


def _reminder(
    recipient: Optional[str], role_id: Optional[str], title: str, description: str,
    i18n: Dict[str, Any], payload: Dict[str, Any], subtitle: Optional[str],
) -> Notification:
    return Notification(
        id=str(uuid4()),
        created_at=utc_now(),
        type=NotificationType.WARNING,
        title=title,
        subtitle=subtitle,
        description=description,
        recipient=recipient,
        recipient_role_id=role_id,
        can_delete=True,
        read=False,
        data={**i18n, 'approval_overdue': {
            'execution_id': payload.get('execution_id'),
            'step_id': payload.get('step_id'),
        }},
    )


def remind_overdue_approvals(db: Session, now: Optional[datetime] = None) -> int:
    """Mark the approval steps past their ``timeout_days`` overdue and remind once.

    Returns the number of steps reminded; commits when there is one.
    """
    now = _utc(now) or datetime.now(timezone.utc)
    reminded = 0
    paused = db.query(WorkflowExecutionDb).filter(WorkflowExecutionDb.status == 'paused').all()
    for execution in paused:
        rows = _step_round(db, execution)
        if not rows:
            continue
        payloads = [_payload(row) for row in rows]
        if any(p.get('overdue_since') for p in payloads):
            continue  # reminded already
        days = timeout_days_of(payloads[0])
        asked_at = min((_utc(row.created_at) for row in rows if row.created_at), default=None)
        if days is None or asked_at is None or now < asked_at + timedelta(days=days):
            continue
        _remind(db, execution, rows, payloads[0], days, now)
        reminded += 1
    if reminded:
        db.commit()
        logger.info(f"Reminded {reminded} overdue approval step(s)")
    return reminded


def _remind(
    db: Session, execution: WorkflowExecutionDb, rows: List[Any], payload: Dict[str, Any],
    days: int, now: datetime,
) -> None:
    since = now.isoformat()
    for row in rows:
        marked = {**_payload(row), 'overdue_since': since}
        row.action_payload = json.dumps(marked)
    workflow = payload.get('workflow_name') or ''
    # Approvers see the entity as the approval names it; the requester by the name the
    # request was made with (never one looked up for them)
    approver_name = (
        payload.get('underlying_entity_name') or payload.get('entity_name')
        or payload.get('underlying_entity_id') or payload.get('entity_id') or ''
    )
    requester_name = (
        payload.get('entity_name') or payload.get('underlying_entity_id')
        or payload.get('entity_id') or ''
    )
    unit = 'day' if days == 1 else 'days'
    approver_text = (
        f"The approval of '{approver_name}' has waited more than {days} {unit}. "
        "Decide it in My Actions."
    )
    approver_i18n = _i18n(
        'notifications:approvalOverdue.approverTitle',
        'notifications:approvalOverdue.approverDescription', approver_name, days,
    )
    for recipient, role_id in _targets(rows):
        notification_repo.create(db=db, obj_in=_reminder(
            recipient, role_id, APPROVER_TITLE, approver_text, approver_i18n, payload,
            workflow or None,
        ))
    requester = payload.get('requester_email')
    if requester:
        requester_text = (
            f"Your request for '{requester_name}' has waited more than {days} {unit} "
            "for a decision. The approvers were reminded."
        )
        requester_i18n = _i18n(
            'notifications:approvalOverdue.requesterTitle',
            'notifications:approvalOverdue.requesterDescription', requester_name, days,
        )
        notification_repo.create(db=db, obj_in=_reminder(
            requester, None, REQUESTER_TITLE, requester_text, requester_i18n, payload,
            workflow or None,
        ))
    logger.info(
        f"Approval step {payload.get('step_id')} of execution {execution.id} is overdue "
        f"({days} day(s)); reminded its approvers and the requester"
    )
