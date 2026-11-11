"""In-app notifications for the compliance DSL ``NOTIFY`` action.

A policy run can match thousands of entities, so NOTIFY does not send one
notification per entity. ``ComplianceRunNotifier`` collects, per resolved
recipient, the entities the action ran for during one run, and ``flush`` creates
**one notification per recipient per run** when the run ends. It gives the run's
failed and passed totals, names up to ``MAX_LISTED`` of the recipient's entities
(each once, however many NOTIFY actions reached the recipient), counts the rest,
and links to the run's results page. Only the entities the recipient can read are
named (see ``_ReadChecks``); the others are only counted.

Recipients resolve as in workflow notification steps (``_resolve_role_to_users``):
emails, ``group:<name>`` (the group is stored as the recipient, as for workflows),
app role names or ids, ``entity_owner`` / ``domain_owners`` / ``business:<id>``, and
comma-separated lists of these. Recipient keywords match without case, spaces and
underscores (``Owner``, ``Entity Owner``). Any other name that is not an app role
fails the action (``notify_unknown_recipient``) instead of becoming a recipient no
user matches. ``domain_owners`` / ``DomainOwner`` and ``ContractApprover`` are the
owners of the entity's domain / of the entity, without the approval rules of workflow
steps: the run user is kept, and nobody is put in place of missing owners.
``owner`` means the entity's owners, as ``entity_owner``, for app entities (their
compliance ``owner`` field holds a team id, which is no recipient), and the UC owner
for Unity Catalog objects. Recipients
that don't depend on the entity are resolved once per run. ``requester`` /
``trigger_user`` is the user who started the run, so it resolves to nobody for
scheduled runs of the compliance-checks job.

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
from src.common.notification_i18n import notification_i18n_data

logger = get_logger(__name__)

# Recipient tokens whose users depend on the entity (resolved per entity, not cached),
# compared without case, spaces and underscores
_ENTITY_TOKENS = {'entityowner', 'owner', 'reviewer', 'domainowner', 'domainowners', 'contractapprover'}


# Owner tokens resolved without the approval rules (normalized as above)
_OWNER_TOKENS = {
    'domainowner': 'DomainOwner',
    'domainowners': 'DomainOwner',
    'contractapprover': 'ContractApprover',
}


# Recipient keywords of ``_resolve_role_to_users`` (normalized as above) -> its spelling
_KEYWORDS = {
    'requester': 'requester',
    'triggeruser': 'trigger_user',
    'entityowner': 'entity_owner',
    'owner': 'owner',
    'reviewer': 'reviewer',
    'datastewards': 'data_stewards',
    'datasteward': 'data_steward',
    'admins': 'admins',
    'projectowners': 'project_owners',
}

_GROUP_PREFIX = 'group:'


def _normalized(token: str) -> str:
    return token.strip().lower().replace(' ', '').replace('_', '')


def _entity_dependent(token: str) -> bool:
    normalized = token.strip().lower()
    return (
        normalized.replace(' ', '').replace('_', '') in _ENTITY_TOKENS
        or normalized.startswith('business:')
    )


class _Bucket:
    """The entities one recipient is notified about, each once, by outcome: id -> name,
    or None when the recipient can't read the entity (counted, not named)."""

    def __init__(self) -> None:
        self.failed: Dict[str, Optional[str]] = {}
        self.passed: Dict[str, Optional[str]] = {}


class _ReadChecks:
    """Whether a recipient can read an entity, so that a notification may name it.

    Data products and contracts use the read gates of the lineage routes
    (``build_lineage_access``: the gate of ``GET /data-products/{id}`` and the
    visibility of the contract list), checked for each user recipient. A role or a
    group is many users, so it is only told the names every reader sees: published
    (active or deprecated) products and contracts. Domains are named to everyone, as
    the domain list shows them all; other entity types (Unity Catalog objects,
    reviews) only to their owner. The recipient's groups and app roles are not known
    here, so admin rights that come from them don't count. Fails closed.
    """

    def __init__(self, db: Session):
        self._db = db
        self._rows: Dict[Tuple[str, str], object] = {}
        self._access: Dict[str, object] = {}
        self._checked: Dict[Tuple[str, Optional[str], str, str], bool] = {}

    def can_read(self, recipient: str, role_id: Optional[str], context: ActionContext) -> bool:
        key = (recipient, role_id, context.entity_type, str(context.entity_id))
        if key not in self._checked:
            try:
                with self._db.begin_nested():
                    self._checked[key] = self._check(recipient, role_id, context)
            except Exception:
                logger.exception(
                    "Read check of %s %s for a NOTIFY recipient failed; not naming it",
                    context.entity_type, context.entity_id,
                )
                self._checked[key] = False
        return self._checked[key]

    def _check(self, recipient: str, role_id: Optional[str], context: ActionContext) -> bool:
        entity_type = context.entity_type
        if entity_type == 'domain':
            return True
        if entity_type in ('data_product', 'data_contract'):
            from src.common.version_visibility import is_admin_only_status, is_visible_consumer

            row = self._row(entity_type, str(context.entity_id))
            if row is None:
                return False
            if role_id or '@' not in recipient:
                return not is_admin_only_status(row) and is_visible_consumer(row)
            access = self._access_for(recipient)
            if entity_type == 'data_product':
                return bool(access.can_read_product(row))
            return bool(access.can_read_contract(row))
        owner = (context.entity or {}).get('owner')
        return bool(owner) and str(owner).strip().lower() == recipient.strip().lower()

    def _row(self, entity_type: str, entity_id: str):
        key = (entity_type, entity_id)
        if key not in self._rows:
            from src.db_models.data_contracts import DataContractDb
            from src.db_models.data_products import DataProductDb

            model = DataProductDb if entity_type == 'data_product' else DataContractDb
            self._rows[key] = self._db.query(model).filter(model.id == entity_id).first()
        return self._rows[key]

    def _access_for(self, email: str):
        if email not in self._access:
            from types import SimpleNamespace

            from src.models.users import UserInfo
            from src.routes.business_lineage_routes import build_lineage_access

            user = UserInfo(email=email, username=email, user=email, ip=None, groups=[])
            # No request: the gates find no app-level managers and use the database only
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
            self._access[email] = build_lineage_access(request, self._db, user, False)
        return self._access[email]


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
        self._cache: Dict[str, List[Tuple[str, Optional[str]]]] = {}
        self._reads = _ReadChecks(db)

    def _step_context(self, context: ActionContext):
        from src.common.workflow_executor import StepContext

        entity = dict(context.entity or {})
        if context.entity_type in APP_ENTITY_TYPES:
            # The 'owner' of an app entity is the owner team's id; drop it so 'owner'
            # resolves to the entity's owners (as 'entity_owner'), not to a team id.
            # A Unity Catalog object's 'owner' is its UC owner, the recipient.
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

    def _owner_recipients(
        self, owner_role: str, token: str, step_context,
    ) -> List[Tuple[str, Optional[str]]]:
        """'DomainOwner' / 'ContractApprover' for a notice: an app role of that name, or of
        the token as written, wins (as in workflows), else the owners of the entity's
        domain / of the entity.

        Not ``_owner_approvers``: its approval rules drop the requester and put the Data
        Stewards and admins in place of missing owners, which a notice must not do.
        """
        from src.common.workflow_executor import _underlying_entity
        from src.db_models.settings import AppRoleDb
        from src.repositories.entity_owners_repository import (
            resolve_domain_owner_emails,
            resolve_owner_emails,
        )

        names = {owner_role.lower(), _normalized(token)}
        for role in self._db.query(AppRoleDb).all():
            if _normalized(role.name) in names:
                return [(role.name, role.id)]
        entity_type, entity_id = _underlying_entity(step_context)
        if owner_role == 'DomainOwner':
            emails = resolve_domain_owner_emails(self._db, entity_type, entity_id)
        else:
            emails = resolve_owner_emails(self._db, entity_type, entity_id)
        return [(email, None) for email in emails if email]

    def _resolve_token(self, token: str, step_context) -> List[Tuple[str, Optional[str]]]:
        from src.common.workflow_executor import _resolve_role_to_users

        def resolve(spec: str) -> List[Tuple[str, Optional[str]]]:
            return [(i, r) for i, r in _resolve_role_to_users(self._db, spec, step_context) if i]

        lowered = token.lower()
        if lowered.startswith(_GROUP_PREFIX):
            group = token[len(_GROUP_PREFIX):].strip()
            return [(group, None)] if group else self._unknown(token)
        normalized = _normalized(token)
        owner_role = _OWNER_TOKENS.get(normalized)
        if owner_role:
            return self._owner_recipients(owner_role, token, step_context)
        if normalized in _KEYWORDS:
            return resolve(_KEYWORDS[normalized])
        bare = token[len('user:'):].strip() if lowered.startswith('user:') else token
        if '@' in bare:
            return [(bare, None)]
        if lowered.startswith('business:'):
            return resolve('business:' + token[len('business:'):].strip())
        # An app role (by id or name); the resolver echoes any other name back as a
        # recipient without a role, which no user would match
        roles = [(i, r) for i, r in resolve(bare) if r]
        return roles or self._unknown(token)

    @staticmethod
    def _unknown(token: str) -> List[Tuple[str, Optional[str]]]:
        raise ActionError(
            'notify_unknown_recipient',
            f"NOTIFY recipient '{token}' is not an email, a group:<name>, an app role "
            "or a recipient keyword",
            recipient=token,
        )

    def _resolve(self, recipients: str, context: ActionContext) -> List[Tuple[str, Optional[str]]]:

        resolved: List[Tuple[str, Optional[str]]] = []
        step_context = None
        for token in (t.strip() for t in recipients.split(',')):
            if not token:
                continue
            cacheable = not _entity_dependent(token)
            if cacheable and token in self._cache:
                resolved.extend(self._cache[token])
                continue
            if step_context is None:
                step_context = self._step_context(context)
            # A failed lookup must not abort the run's transaction (Postgres)
            with self._db.begin_nested():
                users = self._resolve_token(token, step_context)
            if cacheable:
                self._cache[token] = users
            resolved.extend(users)
        return list(dict.fromkeys(resolved))

    def notify(self, recipients: str, context: ActionContext) -> None:
        """Queue the entity for every recipient ``recipients`` resolves to."""
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
            readable = self._reads.can_read(key[0], key[1], context)
            (bucket.passed if context.passed else bucket.failed)[entity_id] = (
                name if readable else None
            )

    def _listed(self, names: List[Optional[str]]) -> Tuple[str, Dict[str, object]]:
        """The readable names as English text, and as an i18n param ("…, and N more"
        translated); None stands for an entity the recipient can't read, only counted."""
        readable = [name for name in names if name is not None]
        hidden = len(names) - len(readable)
        if not readable:
            text = f"{hidden} you can't see"
            return text, {
                'key': 'notifications:complianceRunVisibility.notShown',
                'text': text,
                'params': {'count': str(hidden)},
            }
        shown = ', '.join(readable[: self.MAX_LISTED])
        rest = len(names) - min(len(readable), self.MAX_LISTED)
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
        if created:
            logger.info(
                "Compliance run %s of policy %s: %d notification(s) created",
                self._run_id, self._policy_id, created,
            )
        return created
