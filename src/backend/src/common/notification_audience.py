"""Who a compliance policy's NOTIFY action may notify (#1450).

Admins (compliance Admin, or a role flagged as admin) may notify anyone. Other policy
authors may notify:

- ``self``: the policy's author (also by their own email);
- ``entity_owner`` / ``owner``: the entity's owners;
- ``recipient:<name>``: a Notification Recipient whose allow-list contains one of the
  author's app roles.

Anything else is refused with a code the UI translates. Roles match as in
AuthorizationManager: a role matches when one of the user's groups is in its
``assigned_groups``, or the user's email is in its ``assigned_users`` (case-insensitive).

The same check runs when a rule is saved (against the editor) and when it runs (against
the policy's recorded author and that author's groups at their last rule change), so a
scheduled run with no user is checked too.
"""
import json
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.features import FeatureAccessLevel
from src.db_models.settings import AppRoleDb
from src.repositories.notification_recipient_repository import json_list, notification_recipient_repo

RECIPIENT_PREFIX = 'recipient:'
SELF_TOKEN = 'self'


def normalized(token: str) -> str:
    """A token compared without case, spaces and underscores (``Entity Owner`` -> ``entityowner``).

    The notifier resolves tokens with the same function, so every spelling means the same.
    """
    return token.strip().lower().replace(' ', '').replace('_', '')


# The entity's owners (normalized): what a non-admin author may notify without a recipient
OWNER_TOKENS = {'entityowner', 'owner'}
# Tokens whose users depend on the entity or the run; a Notification Recipient can't name them
ENTITY_DEPENDENT_TOKENS = OWNER_TOKENS | {
    'self', 'requester', 'triggeruser', 'reviewer', 'domainowner', 'domainowners', 'contractapprover',
    'assetowner', 'assetowners',
}


@dataclass(frozen=True)
class NotifyAudience:
    """What a policy author may notify: their email, whether they're an admin, and their app roles."""
    email: Optional[str]
    is_admin: bool
    role_ids: FrozenSet[str]


Violation = Tuple[str, Dict[str, str]]


def audience_for(db: Session, email: Optional[str], groups: Optional[Iterable[str]]) -> NotifyAudience:
    """The audience of a user with these groups and email, from the roles as they are now."""
    from src.common.authorization import is_user_admin
    from src.common.config import get_settings

    group_set = {g.lower() for g in (groups or []) if g}
    email_norm = (email or '').strip().lower() or None
    role_ids = set()
    # Workspace admins (APP_ADMIN_DEFAULT_GROUPS) are admins here too, as elsewhere in the app
    is_admin = bool(groups) and is_user_admin(list(groups), get_settings())
    for role in db.query(AppRoleDb).all():
        role_groups = {g.lower() for g in json_list(role.assigned_groups)}
        role_users = {u.lower() for u in json_list(role.assigned_users)}
        if not (group_set & role_groups or (email_norm and email_norm in role_users)):
            continue
        role_ids.add(str(role.id))
        try:
            permissions = json.loads(role.feature_permissions or '{}')
        except (TypeError, ValueError):
            permissions = {}
        if not isinstance(permissions, dict):
            permissions = {}
        if role.is_admin or permissions.get('compliance') == FeatureAccessLevel.ADMIN.value:
            is_admin = True
    return NotifyAudience(email=email, is_admin=is_admin, role_ids=frozenset(role_ids))


def target_violation(db: Session, token: str, audience: NotifyAudience) -> Optional[Violation]:
    """Why the audience may not notify this NOTIFY target, or None if it may.

    A recipient reference that doesn't exist is refused for everyone. A disabled recipient
    is allowed here and fails at run time, so a policy can be saved before it's enabled.
    """
    if token.lower().startswith(RECIPIENT_PREFIX):
        name = token[len(RECIPIENT_PREFIX):].strip()
        recipient = notification_recipient_repo.get_by_name(db, name)
        if recipient is None:
            return 'notify_recipient_not_found', {'recipient': name}
        if audience.is_admin or audience.role_ids.intersection(json_list(recipient.allowed_role_ids)):
            return None
        return 'notify_recipient_not_allowed', {'recipient': recipient.name}
    if audience.is_admin:
        return None
    if normalized(token) == SELF_TOKEN or (audience.email and token.strip().lower() == audience.email.strip().lower()):
        return None
    if normalized(token) in OWNER_TOKENS:
        return None
    return 'notify_target_not_allowed', {'target': token.strip()}


def violation_text(code: str, params: Dict[str, str]) -> str:
    """The English text of a violation (the UI shows its code and parameters)."""
    if code == 'notify_recipient_not_found':
        return f"Notification recipient '{params['recipient']}' does not exist"
    if code == 'notify_recipient_not_allowed':
        return f"The policy's author may not notify recipient '{params['recipient']}'"
    return f"The policy's author may not notify '{params['target']}'"


def violations(db: Session, recipients: str, audience: NotifyAudience) -> List[Tuple[str, str, Dict[str, str]]]:
    """(code, target, params) for every target of a NOTIFY action the audience may not use."""
    found = []
    for token in (t.strip() for t in recipients.split(',')):
        if not token:
            continue
        violation = target_violation(db, token, audience)
        if violation:
            code, params = violation
            found.append((code, token, params))
    return found
