"""In-app notifications for the compliance DSL ``NOTIFY`` action.

A policy run can match thousands of entities, so NOTIFY does not send one
notification per entity. ``ComplianceRunNotifier`` collects, per resolved
recipient, the entities the action ran for during one run, and ``flush`` creates
**one notification per recipient per run** when the run ends. It gives the run's
failed and passed totals, names up to ``MAX_LISTED`` of the recipient's entities
(each once, however many NOTIFY actions reached the recipient), counts the rest,
and links to the run's results page.

Recipients resolve as in workflow notification steps (``_resolve_role_to_users``):
emails, groups (stored as the recipient, as for workflows), app role names or ids,
``entity_owner`` / ``domain_owners`` / ``business:<id>``, and comma-separated
lists of these. ``owner`` means the entity's owners, as ``entity_owner``: the
compliance ``owner`` field holds a team id, which is no recipient. Recipients
that don't depend on the entity are resolved once per run. ``requester`` /
``trigger_user`` is the user who started the run, so it resolves to nobody for
scheduled runs of the compliance-checks job.

``self`` is the policy's author, and ``recipient:<name>`` expands to the targets of a
Notification Recipient (#1450). Each NOTIFY is first checked against the author's
audience (``notification_audience``); a target the author may not use fails that action
with a coded reason, and the run carries on.

Notifications are flushed into the run's session; the run's own commit stores
them. Only the in-app channel is used.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy.orm import Session

from src.common.compliance_actions import APP_ENTITY_TYPES, ActionContext, ActionError
from src.common.logging import get_logger
from src.common.notification_audience import NotifyAudience, RECIPIENT_PREFIX, SELF_TOKEN, violation_text, violations
from src.common.notification_i18n import notification_i18n_data
from src.repositories.notification_recipient_repository import json_list, notification_recipient_repo

logger = get_logger(__name__)

# Recipient tokens whose users depend on the entity (resolved per entity, not cached),
# compared without case, spaces and underscores
_ENTITY_TOKENS = {'entityowner', 'owner', 'reviewer', 'domainowner', 'domainowners', 'contractapprover'}


def _entity_dependent(token: str) -> bool:
    normalized = token.strip().lower()
    return (
        normalized.replace(' ', '').replace('_', '') in _ENTITY_TOKENS
        or normalized.startswith('business:')
    )


class _Bucket:
    """The entities one recipient is notified about, each once (id -> name), by outcome."""

    def __init__(self) -> None:
        self.failed: Dict[str, str] = {}
        self.passed: Dict[str, str] = {}


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
        audience: NotifyAudience,
        run_user: Optional[str] = None,
    ):
        self._db = db
        self._policy_id = policy_id
        self._policy_name = policy_name
        self._run_id = run_id
        self._audience = audience
        self._run_user = run_user
        self._buckets: Dict[Tuple[str, Optional[str]], _Bucket] = {}
        self._cache: Dict[str, List[Tuple[str, Optional[str]]]] = {}
        self._checked: Dict[str, list] = {}
        # Notifications created by flush(): a count for the run's change log
        self.sent = 0

    def _step_context(self, context: ActionContext):
        from src.common.workflow_executor import StepContext

        entity = dict(context.entity or {})
        # The compliance 'owner' is the owner team's id; drop it so 'owner' resolves
        # to the entity's owners (as 'entity_owner') instead of to a team id.
        entity.pop('owner', None)
        return StepContext(
            entity=entity,
            entity_type=APP_ENTITY_TYPES.get(context.entity_type, context.entity_type),
            entity_id=str(context.entity_id),
            entity_name=entity.get('name'),
            user_email=self._run_user,
            trigger_context=None,
            execution_id=self._run_id,
            workflow_id=self._policy_id,
            workflow_name=self._policy_name,
            step_results={},
        )

    def _resolve_recipient(self, name: str, context: ActionContext) -> List[Tuple[str, Optional[str]]]:
        """The users of a Notification Recipient: its targets, resolved as recipients."""
        key = f'{RECIPIENT_PREFIX}{name.strip().lower()}'
        if key in self._cache:
            return self._cache[key]
        recipient = notification_recipient_repo.get_by_name(self._db, name)
        if recipient is None:
            raise ActionError(
                'notify_recipient_not_found', f"Notification recipient '{name}' does not exist", recipient=name,
            )
        if not recipient.is_active:
            raise ActionError(
                'notify_recipient_disabled', f"Notification recipient '{recipient.name}' is disabled",
                recipient=recipient.name,
            )
        targets = ','.join(json_list(recipient.targets))
        self._cache[key] = self._resolve(targets, context) if targets else []
        return self._cache[key]

    def _resolve(self, recipients: str, context: ActionContext) -> List[Tuple[str, Optional[str]]]:
        from src.common.workflow_executor import _resolve_role_to_users

        resolved: List[Tuple[str, Optional[str]]] = []
        step_context = None
        for token in (t.strip() for t in recipients.split(',')):
            if not token:
                continue
            if token.lower().startswith(RECIPIENT_PREFIX):
                resolved.extend(self._resolve_recipient(token[len(RECIPIENT_PREFIX):].strip(), context))
                continue
            if token.lower() == SELF_TOKEN:
                # The policy's author, not the user who runs it (a scheduled run has none)
                if self._audience.email:
                    resolved.append((self._audience.email, None))
                continue
            cacheable = not _entity_dependent(token)
            if cacheable and token in self._cache:
                resolved.extend(self._cache[token])
                continue
            if step_context is None:
                step_context = self._step_context(context)
            # A failed lookup must not abort the run's transaction (Postgres)
            with self._db.begin_nested():
                users = [(i, r) for i, r in _resolve_role_to_users(self._db, token, step_context) if i]
            if cacheable:
                self._cache[token] = users
            resolved.extend(users)
        return list(dict.fromkeys(resolved))

    def notify(self, recipients: str, context: ActionContext) -> None:
        """Queue the entity for every recipient ``recipients`` resolves to.

        Raises ActionError (coded) if the policy's author may not notify a target.
        """
        if recipients not in self._checked:
            self._checked[recipients] = violations(self._db, recipients, self._audience)
        for code, _target, params in self._checked[recipients]:
            raise ActionError(code, violation_text(code, params), **params)
        resolved = self._resolve(recipients, context)
        if not resolved:
            raise ActionError(
                'notify_no_recipients',
                f"NOTIFY '{recipients}' resolved to no recipient for this entity",
                recipients=recipients,
            )
        entity_id = str(context.entity_id)
        name = (context.entity or {}).get('name') or entity_id
        for key in resolved:
            bucket = self._buckets.setdefault(key, _Bucket())
            (bucket.passed if context.passed else bucket.failed)[entity_id] = name

    def _listed(self, names: List[str]) -> Tuple[str, Dict[str, object]]:
        """The names as English text, and as an i18n param ("…, and N more" translated)."""
        shown = ', '.join(names[: self.MAX_LISTED])
        rest = len(names) - self.MAX_LISTED
        if rest <= 0:
            return shown, {'text': shown}
        text = f"{shown} and {rest} more"
        return text, {
            'key': 'notifications:complianceRun.namesWithMore',
            'text': text,
            'params': {'names': shown, 'count': str(rest)},
        }

    def _description(self, bucket: _Bucket, failed: int, passed: int) -> Tuple[str, Dict[str, object]]:
        """English description and its i18n data (``descriptionLines``, one text per line)."""
        summary = f"Policy '{self._policy_name}': {failed} failed, {passed} passed."
        lines = [summary]
        i18n_lines: List[Dict[str, object]] = [{
            'key': 'notifications:complianceRun.summary',
            'text': summary,
            'params': {'policyName': self._policy_name, 'failedCount': str(failed), 'passedCount': str(passed)},
        }]
        for names, key, label in (
            (list(bucket.failed.values()), 'notifications:complianceRun.failedEntities', 'Failed'),
            (list(bucket.passed.values()), 'notifications:complianceRun.passedEntities', 'Passed'),
        ):
            if not names:
                continue
            text, names_param = self._listed(names)
            lines.append(f"{label}: {text}")
            i18n_lines.append({'key': key, 'text': f"{label}: {text}", 'params': {'names': names_param}})
        data = notification_i18n_data(
            'notifications:complianceRun.title',
            policyName=self._policy_name, failedCount=failed, passedCount=passed,
        )
        data['i18n']['descriptionLines'] = i18n_lines
        return "\n".join(lines), data

    def flush(self, *, failed: int, passed: int) -> int:
        """Create the queued notifications (one per recipient); returns how many were created.

        ``failed`` / ``passed`` are the run's totals, shown in every notification.
        """
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo

        created = 0
        buckets, self._buckets = self._buckets, {}
        for (recipient, role_id), bucket in buckets.items():
            description, data = self._description(bucket, failed, passed)
            notification = Notification(
                id=str(uuid4()),
                # Aware UTC: the column is timezone-aware, a naive value would read as local time
                created_at=datetime.now(timezone.utc),
                type=NotificationType.WARNING if bucket.failed else NotificationType.INFO,
                title=f"Compliance: {self._policy_name}",
                description=description,
                link=f"/compliance/runs/{self._run_id}",
                recipient=recipient,
                recipient_role_id=role_id,
                can_delete=True,
                read=False,
                data=data,
            )
            notification_repo.create(db=self._db, obj_in=notification)
            created += 1
        self.sent += created
        if created:
            logger.info(
                "Compliance run %s of policy %s: %d notification(s) created",
                self._run_id, self._policy_id, created,
            )
        return created
