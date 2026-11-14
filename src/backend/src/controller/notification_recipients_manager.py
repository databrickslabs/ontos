"""Notification Recipients (#1450): named NOTIFY targets that admins define in Settings.

A recipient is usable by an author whose roles are on its allow-list (admins always can).
Targets are static: entity-dependent tokens (owners, requester, self, business roles,
other recipients) are refused, since a recipient is shared by every policy that names it.
"""
import json
import re
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.notification_audience import ENTITY_DEPENDENT_TOKENS, NotifyAudience, audience_for, normalized
from src.common.logging import get_logger
from src.db_models.notification_recipients import NotificationRecipientDb
from src.db_models.settings import AppRoleDb
from src.models.notification_recipients import NotificationRecipientCreate, NotificationRecipientUpdate
from src.repositories.notification_recipient_repository import json_list, notification_recipient_repo

logger = get_logger(__name__)

_MAX_TARGETS = 100
_MAX_TARGET_LENGTH = 256
_NAME_FORBIDDEN = re.compile(r"[,'\"\x00-\x1f]")


class NotificationRecipientError(CodedValueError):
    """A recipient that can't be saved as given (the message is the English fallback)."""


class NotificationRecipientNameTakenError(NotificationRecipientError):
    code = 'notification_recipient_name_taken'


class NotificationRecipientNameError(NotificationRecipientError):
    code = 'notification_recipient_name_invalid'


class NotificationRecipientTargetError(NotificationRecipientError):
    code = 'notification_recipient_target_invalid'


class NotificationRecipientRoleError(NotificationRecipientError):
    code = 'notification_recipient_role_unknown'


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or _NAME_FORBIDDEN.search(cleaned):
        raise NotificationRecipientNameError(
            "Name must not be empty, and must not contain commas, quotes or control characters",
        )
    return cleaned


def _clean_targets(targets: List[str]) -> List[str]:
    cleaned: List[str] = []
    for raw in targets:
        target = (raw or '').strip()
        if not target:
            continue
        if (
            len(target) > _MAX_TARGET_LENGTH
            or ',' in target
            or normalized(target) in ENTITY_DEPENDENT_TOKENS
            or target.lower().startswith(('business:', 'recipient:'))
        ):
            raise NotificationRecipientTargetError(
                f"'{target}' can't be a target: targets are fixed emails, groups or roles",
                target=target,
            )
        if target not in cleaned:
            cleaned.append(target)
    if len(cleaned) > _MAX_TARGETS:
        raise NotificationRecipientTargetError(f"A recipient has at most {_MAX_TARGETS} targets")
    return cleaned


def _clean_role_ids(db: Session, role_ids: List[str]) -> List[str]:
    cleaned: List[str] = []
    for role_id in (str(r).strip() for r in role_ids):
        if not role_id or role_id in cleaned:
            continue
        if db.query(AppRoleDb).filter(AppRoleDb.id == role_id).first() is None:
            raise NotificationRecipientRoleError(f"App role '{role_id}' does not exist", role=role_id)
        cleaned.append(role_id)
    return cleaned


class NotificationRecipientsManager:
    def list(self, db: Session) -> List[NotificationRecipientDb]:
        return notification_recipient_repo.list_all(db)

    def get(self, db: Session, recipient_id: str) -> Optional[NotificationRecipientDb]:
        return notification_recipient_repo.get(db, recipient_id)

    def _check_name(self, db: Session, name: str, exclude_id: Optional[str] = None) -> None:
        if notification_recipient_repo.get_by_name(db, name, exclude_id=exclude_id) is not None:
            raise NotificationRecipientNameTakenError(f"A notification recipient named '{name}' already exists")

    def create(self, db: Session, data: NotificationRecipientCreate, *, username: Optional[str]) -> NotificationRecipientDb:
        name = _clean_name(data.name)
        self._check_name(db, name)
        obj_in = {
            'name': name,
            'description': data.description,
            'targets': _dump(_clean_targets(data.targets)),
            'allowed_role_ids': _dump(_clean_role_ids(db, data.allowed_role_ids)),
            'is_active': data.is_active,
            'created_by': username,
            'updated_by': username,
        }
        created = notification_recipient_repo.create(db, obj_in=obj_in)
        self._commit(db)
        db.refresh(created)
        return created

    @staticmethod
    def _commit(db: Session) -> None:
        # Two concurrent creates of one name both pass _check_name; the case-insensitive unique index
        # keeps one, and the other is the coded name-taken error, not a 500
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            raise NotificationRecipientNameTakenError('A notification recipient with this name already exists') from e

    def update(
        self, db: Session, recipient_id: str, data: NotificationRecipientUpdate, *, username: Optional[str],
    ) -> Optional[NotificationRecipientDb]:
        existing = self.get(db, recipient_id)
        if existing is None:
            return None
        # Validate everything before touching the row, so a rejected edit leaves nothing half-applied
        name = _clean_name(data.name)
        self._check_name(db, name, exclude_id=recipient_id)
        targets = _dump(_clean_targets(data.targets))
        allowed_role_ids = _dump(_clean_role_ids(db, data.allowed_role_ids))
        existing.name = name
        existing.description = data.description
        existing.targets = targets
        existing.allowed_role_ids = allowed_role_ids
        existing.is_active = data.is_active
        existing.updated_by = username
        self._commit(db)
        db.refresh(existing)
        return existing

    def delete(self, db: Session, recipient_id: str) -> bool:
        existing = self.get(db, recipient_id)
        if existing is None:
            return False
        db.delete(existing)
        db.commit()
        return True

    def usable_by(self, db: Session, audience: NotifyAudience) -> List[NotificationRecipientDb]:
        """The active recipients this audience may name in a NOTIFY action."""
        return [
            recipient for recipient in notification_recipient_repo.list_all(db)
            if recipient.is_active and (
                audience.is_admin or audience.role_ids.intersection(json_list(recipient.allowed_role_ids))
            )
        ]

    def usable_by_user(self, db: Session, email: Optional[str], groups: Optional[List[str]]) -> List[NotificationRecipientDb]:
        return self.usable_by(db, audience_for(db, email, groups))


def _dump(values: List[str]) -> str:
    return json.dumps(values)


notification_recipients_manager = NotificationRecipientsManager()
