"""In-app notifications for the compliance DSL ``NOTIFY`` action.

A policy run can match thousands of entities, so NOTIFY does not send one
notification per entity. ``ComplianceRunNotifier`` collects, per resolved
recipient, the entities the action ran for during one run, and ``flush`` creates
**one notification per recipient per run** when the run ends. It names up to
``MAX_LISTED`` entities, counts the rest, and links to the run's results page.

Recipients resolve as in workflow notification steps (``_resolve_role_to_users``):
emails, groups (stored as the recipient, as for workflows), app role names or ids,
``entity_owner`` / ``owner`` / ``domain_owners``, and comma-separated lists of
these. Recipients that resolve per entity (``entity_owner``) are resolved for each
entity. ``requester`` / ``trigger_user`` is the user who started the run, so it
resolves to nobody for scheduled runs of the compliance-checks job.

Notifications are flushed into the run's session; the run's own commit stores
them. Only the in-app channel is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from src.common.compliance_actions import ActionContext, ActionError
from src.common.logging import get_logger
from src.common.notification_i18n import notification_i18n_data

logger = get_logger(__name__)

# Compliance entity types -> entity types owners and business owners are stored under
_OWNER_ENTITY_TYPES = {'domain': 'data_domain'}


@dataclass
class _Bucket:
    failed: List[str] = field(default_factory=list)
    passed: List[str] = field(default_factory=list)


class ComplianceRunNotifier:
    """Collects NOTIFY actions of one policy run and sends one notification per recipient."""

    MAX_LISTED = 10

    def __init__(
        self,
        db: Session,
        *,
        policy_id: str,
        policy_name: str,
        run_id: str,
        run_user: Optional[str] = None,
    ):
        self._db = db
        self._policy_id = policy_id
        self._policy_name = policy_name
        self._run_id = run_id
        self._run_user = run_user
        self._buckets: Dict[Tuple[str, Optional[str]], _Bucket] = {}

    def _step_context(self, context: ActionContext):
        from src.common.workflow_executor import StepContext

        return StepContext(
            entity=context.entity or {},
            entity_type=_OWNER_ENTITY_TYPES.get(context.entity_type, context.entity_type),
            entity_id=str(context.entity_id),
            entity_name=(context.entity or {}).get('name'),
            user_email=self._run_user,
            trigger_context=None,
            execution_id=self._run_id,
            workflow_id=self._policy_id,
            workflow_name=self._policy_name,
            step_results={},
        )

    def notify(self, recipients: str, context: ActionContext) -> None:
        """Queue the entity for every recipient ``recipients`` resolves to."""
        from src.common.workflow_executor import _resolve_role_to_users

        resolved = [
            (identifier, role_id)
            for identifier, role_id in _resolve_role_to_users(self._db, recipients, self._step_context(context))
            if identifier
        ]
        if not resolved:
            raise ActionError(
                'notify_no_recipients',
                f"NOTIFY '{recipients}' resolved to no recipient for this entity",
                recipients=recipients,
            )
        name = (context.entity or {}).get('name') or str(context.entity_id)
        for key in resolved:
            bucket = self._buckets.setdefault(key, _Bucket())
            (bucket.passed if context.passed else bucket.failed).append(name)

    def _listed(self, names: List[str]) -> str:
        shown = ', '.join(names[: self.MAX_LISTED])
        rest = len(names) - self.MAX_LISTED
        return f"{shown} and {rest} more" if rest > 0 else shown

    def flush(self) -> int:
        """Create the queued notifications (one per recipient); returns how many were created."""
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo

        created = 0
        buckets, self._buckets = self._buckets, {}
        for (recipient, role_id), bucket in buckets.items():
            failed, passed = len(bucket.failed), len(bucket.passed)
            lines = [f"Policy '{self._policy_name}': {failed} failed, {passed} passed."]
            if bucket.failed:
                lines.append(f"Failed: {self._listed(bucket.failed)}")
            if bucket.passed:
                lines.append(f"Passed: {self._listed(bucket.passed)}")
            notification = Notification(
                id=str(uuid4()),
                # Aware UTC: the column is timezone-aware, a naive value would read as local time
                created_at=datetime.now(timezone.utc),
                type=NotificationType.WARNING if failed else NotificationType.INFO,
                title=f"Compliance: {self._policy_name}",
                description="\n".join(lines),
                link=f"/compliance/runs/{self._run_id}",
                recipient=recipient,
                recipient_role_id=role_id,
                can_delete=True,
                read=False,
                data=notification_i18n_data(
                    'notifications:complianceRun.title',
                    'notifications:complianceRun.description',
                    policyName=self._policy_name,
                    failedCount=failed,
                    passedCount=passed,
                ),
            )
            notification_repo.create(db=self._db, obj_in=notification)
            created += 1
        if created:
            logger.info(
                "Compliance run %s of policy %s: %d notification(s) created",
                self._run_id, self._policy_id, created,
            )
        return created
