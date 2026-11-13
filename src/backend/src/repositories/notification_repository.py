from dataclasses import dataclass
from sqlalchemy.orm import Session
from typing import Any, Dict, FrozenSet, Union, Optional, List
import json # For handling JSON strings
from sqlalchemy import and_, func, not_, or_, true

from src.common.repository import CRUDBase
from src.db_models.notifications import NotificationDb # SQLAlchemy model
from src.models.notifications import Notification as NotificationApi, NotificationType # API model and NotificationType enum
from src.common.logging import get_logger

logger = get_logger(__name__)

# Use NotificationApi for create/update types for simplicity
NotificationCreate = NotificationApi
NotificationUpdate = Union[NotificationApi, Dict[str, Any]]


@dataclass(frozen=True)
class RecipientKeys:
    """What one user can match in a notification's recipient fields, for the SQL prefilter.

    The prefilter selects a superset of the rows the user can see; NotificationsManager
    still decides each row, so an extra row is harmless and a missing one is the bug (#1526).
    """
    identities: FrozenSet[str] = frozenset()      # the user's email and username, lower-cased
    names: FrozenSet[str] = frozenset()           # groups and legacy role names the user is in
    role_ids: FrozenSet[str] = frozenset()        # app role ids the user is a member of
    known_role_ids: FrozenSet[str] = frozenset()  # every app role id that exists


def _no_recipient():
    return or_(NotificationDb.recipient.is_(None), NotificationDb.recipient == '')


def _is_actionable():
    return and_(NotificationDb.action_type.isnot(None), NotificationDb.action_type != '')


def _is_decided():
    """Decided: the ``handled`` marker that approval and request decisions write into
    ``action_payload``, or a delivery's ``completed`` marker (json.dumps spacing). Opening a
    notification sets ``read`` too, so ``read`` alone does not say a request is decided (#1526)."""
    payload = func.coalesce(NotificationDb.action_payload, '')
    return or_(payload.contains('"handled": true'), payload.contains('"completed": true'))


def _is_pending_actionable():
    """Actionable and not decided yet: never capped, so it stays in My actions and the bell."""
    return and_(_is_actionable(), not_(_is_decided()))


def _addressed_to(keys: Optional[RecipientKeys]):
    """Rows that may be addressed to the user: the user, a group or role they are in, or a
    broadcast. ``keys=None`` selects the rows with no recipient (no user to match)."""
    if keys is None:
        return _no_recipient()
    clauses = []
    if keys.identities:
        clauses.append(func.lower(func.trim(NotificationDb.recipient)).in_(sorted(keys.identities)))
    if keys.names:
        clauses.append(NotificationDb.recipient.in_(sorted(keys.names)))
    if keys.role_ids:
        clauses.append(NotificationDb.recipient_role_id.in_(sorted(keys.role_ids)))
    # Broadcast: no recipient and no app role it names (a role that no longer exists included)
    if keys.known_role_ids:
        unknown_role = or_(
            NotificationDb.recipient_role_id.is_(None),
            NotificationDb.recipient_role_id == '',
            NotificationDb.recipient_role_id.notin_(sorted(keys.known_role_ids)),
        )
    else:
        unknown_role = true()
    clauses.append(and_(_no_recipient(), unknown_role))
    return or_(*clauses)

class NotificationRepository(CRUDBase[NotificationDb, NotificationCreate, NotificationUpdate]):
    """Repository for Notification CRUD operations.

    Note: JSON field deserialization (action_payload, data, target_roles) is handled
    by Pydantic field_validator decorators in the Notification model when converting
    DB objects to API models via model_validate(). The repository keeps JSON fields
    as strings in the database to avoid mutating tracked ORM objects.
    """

    def get(self, db: Session, id: Any) -> Optional[NotificationDb]:
        """Get notification by ID. Pydantic validators handle JSON deserialization."""
        return super().get(db, id)

    def get_multi(self, db: Session, *, skip: int = 0, limit: int = 100) -> List[NotificationDb]:
        """Get multiple notifications. Pydantic validators handle JSON deserialization."""
        return super().get_multi(db, skip=skip, limit=limit)

    def get_addressed_to(
        self, db: Session, *, keys: Optional[RecipientKeys], history_limit: int,
    ) -> List[NotificationDb]:
        """Rows that may be addressed to one user, newest first.

        Every pending actionable row (an action type, not decided yet) is returned, so an
        approval or request never drops out of My actions or the bell. The other rows, decided
        actionable ones included, are capped at the newest ``history_limit``. ``keys=None``:
        the rows with no recipient.
        """
        visible = _addressed_to(keys)
        pending = db.query(NotificationDb).filter(
            visible, _is_pending_actionable(),
        ).order_by(NotificationDb.created_at.desc()).all()
        history = db.query(NotificationDb).filter(
            visible, not_(_is_pending_actionable()),
        ).order_by(NotificationDb.created_at.desc()).limit(history_limit).all()
        return pending + history

    def get_by_action_type(
        self, db: Session, action_type: str, *, unread_only: bool = False,
    ) -> List[NotificationDb]:
        """Every row of one action type, newest first, optionally only the unread ones.

        Not capped: a pending request or delivery must be found whatever its age.
        """
        query = db.query(NotificationDb).filter(NotificationDb.action_type == action_type)
        if unread_only:
            query = query.filter(NotificationDb.read == False)  # noqa: E712
        return query.order_by(NotificationDb.created_at.desc()).all()

    # Override create and update to handle potential JSON string conversion for payload
    # and explicit Enum -> String conversion for the 'type' field.
    def create(self, db: Session, *, obj_in: NotificationCreate) -> NotificationDb:
        logger.debug(f"Creating Notification (DB layer)")
        obj_in_data = obj_in.model_dump(exclude_unset=True) 

        # Convert dict/list fields to JSON strings if present
        if 'action_payload' in obj_in_data and isinstance(obj_in_data['action_payload'], dict):
            obj_in_data['action_payload'] = json.dumps(obj_in_data['action_payload'])

        if 'data' in obj_in_data and isinstance(obj_in_data['data'], dict):
            obj_in_data['data'] = json.dumps(obj_in_data['data'])

        if 'target_roles' in obj_in_data and isinstance(obj_in_data['target_roles'], list):
            obj_in_data['target_roles'] = json.dumps(obj_in_data['target_roles'])

        # Explicitly convert Enum to its string value
        if 'type' in obj_in_data and isinstance(obj_in_data['type'], NotificationType):
            obj_in_data['type'] = obj_in_data['type'].value
            
        # Ensure 'read' field has a boolean value
        if 'read' not in obj_in_data:
            obj_in_data['read'] = False 
        elif obj_in_data['read'] is None: 
            obj_in_data['read'] = False
            
        db_obj = self.model(**obj_in_data)
        db.add(db_obj)
        # --- Flush and Refresh ---
        db.flush()  # Send pending changes to DB (assigns defaults like 'read')
        db.refresh(db_obj) # Update the db_obj instance with DB state
        # Return db_obj without deserializing to avoid mutating tracked ORM object
        # Pydantic validators will handle JSON deserialization when model_validate() is called
        return db_obj

    def update(self, db: Session, *, db_obj: NotificationDb, obj_in: NotificationUpdate) -> NotificationDb:
        logger.debug(f"Updating Notification (DB layer) with id: {db_obj.id}")
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True) 

        # Convert dict/list fields to JSON strings if present in update data
        if 'action_payload' in update_data and isinstance(update_data['action_payload'], dict):
            update_data['action_payload'] = json.dumps(update_data['action_payload'])

        if 'data' in update_data and isinstance(update_data['data'], dict):
            update_data['data'] = json.dumps(update_data['data'])

        if 'target_roles' in update_data and isinstance(update_data['target_roles'], list):
            update_data['target_roles'] = json.dumps(update_data['target_roles'])

        # Explicitly convert Enum to its string value
        if 'type' in update_data and isinstance(update_data['type'], NotificationType):
            update_data['type'] = update_data['type'].value
            
        # --- Ensure 'read' field is boolean if provided in update --- 
        if 'read' in update_data and update_data['read'] is None:
             # If an update explicitly tries to set read to None, either raise error or force False
             logger.warning(f"Attempted to set 'read' to None during update for Notification {db_obj.id}. Setting to False instead.")
             update_data['read'] = False 
             # Alternatively: raise ValueError("'read' field cannot be set to None")

        return super().update(db, db_obj=db_obj, obj_in=update_data)
    
    def is_empty(self, db: Session) -> bool:
        """Checks if the notifications table is empty."""
        return db.query(self.model).first() is None

# Create a singleton instance for the manager to use
notification_repo = NotificationRepository(NotificationDb) 