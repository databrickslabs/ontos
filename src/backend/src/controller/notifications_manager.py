import uuid
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Dict
import json

from sqlalchemy.orm import Session # Import Session for type hinting
from pydantic import ValidationError # Import for error handling

from src.models.notifications import Notification, NotificationType # Import the enum too
# Import SettingsManager for role lookups
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.controller.settings_manager import SettingsManager
# Import UserInfo type hint
from src.models.users import UserInfo
# Import the repository
from src.repositories.notification_repository import notification_repo, NotificationRepository

# Set up logging
from src.common.logging import get_logger
logger = get_logger(__name__)

class NotificationNotFoundError(Exception):
    """Raised when a notification is not found."""


class _RecipientMembership:
    """Which notification recipients one user is: the user (email or
    username, ignoring case), a member of a group, or a member of an app role
    through its groups or its individually assigned users (``assigned_users``,
    #760). A role with neither falls back to the admins. Built once per user
    and check, so the roles are loaded once.
    """

    def __init__(self, user_info: UserInfo, roles: List[Any], roles_loaded: bool = True):
        self.roles_loaded = roles_loaded
        self._groups = set(user_info.groups or [])
        self._identities = {
            str(v).strip().lower() for v in (user_info.email, user_info.username) if v
        }
        # Role ids are UUIDs, notifications store the text form
        self.role_by_id: Dict[str, Any] = {str(role.id): role for role in roles}
        self._role_by_name: Dict[str, Any] = {}
        for role in roles:
            self._role_by_name[role.name] = role
            # Normalized variants (legacy recipients store a role name)
            self._role_by_name[role.name.lower().replace(' ', '')] = role
            self._role_by_name[''.join(word.capitalize() for word in role.name.split())] = role
        admin_role = self._role_by_name.get('Admin')
        self.is_admin = bool(admin_role is not None and self._assigned_to(admin_role))

    def _assigned_to(self, role: Any) -> bool:
        if self._groups.intersection(role.assigned_groups or []):
            return True
        users = {str(u).strip().lower() for u in (getattr(role, 'assigned_users', None) or [])}
        return bool(self._identities.intersection(users))

    def member_of(self, role: Any) -> bool:
        """Assigned to the role; a role nobody is assigned to: the admins."""
        if role.assigned_groups or getattr(role, 'assigned_users', None):
            return self._assigned_to(role)
        return self.is_admin

    def is_user(self, recipient: Optional[str]) -> bool:
        """Whether the recipient names the user (email or username)."""
        return bool(recipient) and recipient.strip().lower() in self._identities

    def role_of(self, recipient: Optional[str], recipient_role_id: Optional[str]) -> Optional[Any]:
        """The app role a recipient names: by id, else by name (legacy)."""
        if recipient_role_id and str(recipient_role_id) in self.role_by_id:
            return self.role_by_id[str(recipient_role_id)]
        return self._role_by_name.get(recipient) if recipient else None

    def is_recipient(self, recipient: Optional[str], recipient_role_id: Optional[str]) -> bool:
        """Whether the user is this recipient, without the broadcast and admin
        fallbacks of the access check."""
        if not (recipient or recipient_role_id):
            return False
        if self.is_user(recipient):
            return True
        role = self.role_of(recipient, recipient_role_id)
        if role is not None:
            return self.member_of(role)
        # Group picked as a recipient / approver (the Workflow Designer's
        # principal picker stores the group name)
        return bool(not recipient_role_id and recipient in self._groups)

class NotificationsManager:
    def __init__(self, settings_manager: 'SettingsManager'):
        """Initialize the notification manager.

        Args:
            settings_manager: The SettingsManager instance to look up role details.
        """
        # self.notifications: List[Notification] = [] # REMOVE In-memory list
        self._repo = notification_repo # Use the repository instance
        self._settings_manager = settings_manager # Store the manager

    def get_notification_by_id(self, db: Session, notification_id: str) -> Optional[Notification]:
        """Get a single notification by ID."""
        try:
            db_obj = self._repo.get(db=db, id=notification_id)
            if not db_obj:
                return None
            return Notification.model_validate(db_obj)
        except Exception as e:
            logger.error(f"Error getting notification {notification_id}: {e}", exc_info=True)
            return None

    def get_notifications(self, db: Session, user_info: Optional[UserInfo] = None) -> List[Notification]:
        """Get notifications from the database, filtered for the user."""
        
        # Fetch all notifications from the repository
        all_notifications_db = self._repo.get_multi(db=db, limit=1000) # Adjust limit if needed
        
        # Convert DB models to Pydantic models (handling potential errors)
        all_notifications_api: List[Notification] = []
        for db_obj in all_notifications_db:
             try:
                 all_notifications_api.append(Notification.model_validate(db_obj))
             except ValidationError as e:
                 logger.error(f"Error validating Notification DB object (ID: {db_obj.id}): {e}")
                 continue # Skip this notification

        # --- Filtering logic (similar to before, but uses API models and SettingsManager) ---
        if not user_info:
            # Return only broadcast notifications if no user info
            return [n for n in all_notifications_api if not n.recipient]

        membership = self._membership(user_info, "notification filtering")
        filtered_notifications = []
        for n in all_notifications_api:
            target_role = membership.role_of(n.recipient, n.recipient_role_id)
            if target_role is not None:
                # Populate role name for display
                n.recipient_role_name = target_role.name
            # Broadcast: no recipient and no known role
            broadcast = not n.recipient and membership.role_of(None, n.recipient_role_id) is None
            if broadcast or membership.is_recipient(n.recipient, n.recipient_role_id):
                # Admins can delete any notification they can see
                if membership.is_admin:
                    n.can_delete = True
                filtered_notifications.append(n)

        # Sort by created_at descending (using datetime objects)
        filtered_notifications.sort(key=lambda x: x.created_at, reverse=True)

        return filtered_notifications

    def can_user_access_notification(
        self, db: Session, notification: Notification, user_info: UserInfo,
        *, strict: bool = False,
    ) -> bool:
        """Check if a user can access/modify a specific notification.
        
        Uses the same logic as get_notifications for role-based access checks
        (``_RecipientMembership``), plus admins, who access any notification.
        
        Args:
            db: Database session
            notification: The notification to check access for
            user_info: The user's info including email and groups
            strict: Fail closed, for decisions that grant access to something
                else (#1117): no broadcast, nothing when the roles can't be
                read, and when ``recipient_role_id`` names no app role (a
                business role, or a deleted role) only the user the
                notification names, not the admins. The default (the bell)
                treats an unresolvable role as a broadcast.
            
        Returns:
            True if user can access the notification, False otherwise
        """
        if not user_info:
            return False
        membership = self._membership(user_info, "notification access check")
        if strict and not membership.roles_loaded:
            return False
        recipient = notification.recipient
        role_id = notification.recipient_role_id
        if strict and role_id and membership.role_of(None, role_id) is None:
            # Not an app role: only the person the notification names. A
            # business role's notification names its owner; a role that no
            # longer exists names its role and so addresses nobody.
            return membership.is_user(recipient)
        # Broadcast notification - anyone can access
        if not recipient and membership.role_of(None, role_id) is None:
            return not strict
        if membership.is_recipient(recipient, role_id):
            return True
        # Admins can access any notification
        return membership.is_admin

    def _membership(self, user_info: UserInfo, purpose: str) -> _RecipientMembership:
        """The user's recipient membership, with the roles loaded once."""
        try:
            roles = list(self._settings_manager.list_app_roles())
        except Exception:
            logger.error("Failed to retrieve roles for %s", purpose, exc_info=True)
            return _RecipientMembership(user_info, [], roles_loaded=False)
        return _RecipientMembership(user_info, roles)

    def recipient_matcher(
        self, user_info: Optional[UserInfo],
    ) -> Callable[[Optional[str], Optional[str]], bool]:
        """``user_is_recipient`` for one user and many recipients, loading the
        roles once (e.g. the targets of a require_all approval, #1119)."""
        if not user_info:
            return lambda recipient, recipient_role_id: False
        return self._membership(user_info, "the recipient check").is_recipient

    def user_is_recipient(
        self, recipient: Optional[str], recipient_role_id: Optional[str], user_info: UserInfo,
    ) -> bool:
        """Whether the user is this recipient: the user, a member of the group,
        or a member of the role (by id, or by name for legacy recipients),
        through the role's groups or its assigned users.

        As ``can_user_access_notification`` without its admin and broadcast
        fallbacks: an admin is a recipient only of the Admin role, or of a role
        nobody is assigned to. Used to tell which approver a decision is for
        (#1119).
        """
        return self.recipient_matcher(user_info)(recipient, recipient_role_id)

    async def create_user_notification(
        self,
        db: Session,
        user_id: Optional[str] = None, # Add user_id (recipient or broadcast)
        title: str = "Notification",
        subtitle: Optional[str] = None,
        description: Optional[str] = None,
        link: Optional[str] = None,
        type: NotificationType = NotificationType.INFO,
        action_type: Optional[str] = None,
        action_payload: Optional[Dict] = None,
        can_delete: bool = True
    ) -> Notification:
        """Creates and saves a new notification using keyword arguments.

        NOTE: renamed from create_notification. The object-based
        create_notification(notification, db) defined later in this class
        shadowed this method, so every kwargs-style call raised
        TypeError (unexpected keyword argument 'user_id') and the
        notification was silently lost.
        """
        try:
            now = datetime.now(timezone.utc)
            notification_id = str(uuid.uuid4())
            
            # Construct the Notification Pydantic model internally
            notification_data = Notification(
                id=notification_id,
                recipient=user_id, # Use user_id as recipient (None for broadcast)
                title=title,
                subtitle=subtitle,
                description=description,
                link=link,
                type=type,
                action_type=action_type,
                action_payload=action_payload,
                can_delete=can_delete,
                created_at=now,
                read=False
            )

            logger.debug(f"Creating notification: {notification_data.dict()}")
            created_db_obj = self._repo.create(db=db, obj_in=notification_data)
            return Notification.from_orm(created_db_obj)
        except Exception as e:
             logger.error(f"Error creating notification in DB: {e}", exc_info=True)
             raise # Re-raise to be handled by the caller/route

    def delete_notification(self, db: Session, notification_id: str) -> bool:
        """Delete a notification by ID using the repository."""
        try:
             deleted_obj = self._repo.remove(db=db, id=notification_id)
             return deleted_obj is not None
        except Exception as e:
             logger.error(f"Error deleting notification {notification_id}: {e}", exc_info=True)
             raise

    def mark_notification_read(self, db: Session, notification_id: str) -> Optional[Notification]:
        """Mark a notification as read using the repository."""
        try:
            db_obj = self._repo.get(db=db, id=notification_id)
            if not db_obj:
                return None

            if db_obj.read: # Already read
                return Notification.from_orm(db_obj)

            # Update using the repository's update method
            updated_db_obj = self._repo.update(db=db, db_obj=db_obj, obj_in={"read": True})
            db.commit() # Commit the change to the database
            db.refresh(updated_db_obj) # Refresh to get the committed state
            return Notification.from_orm(updated_db_obj)
        except Exception as e:
            logger.error(f"Error marking notification {notification_id} as read: {e}", exc_info=True)
            db.rollback()
            raise

    def has_unhandled_actionable_notification(self, db: Session, action_type: str, action_payload: Dict) -> bool:
        """Return True if an unread notification already matches this action type/payload.

        Used to deduplicate user-triggered requests (e.g. asking an admin to enable a
        background job) so repeated clicks don't flood the admin notification bell.
        Matching mirrors handle_actionable_notification: the provided payload must be a
        subset of the stored payload.
        """
        try:
            for notification_db in self._repo.get_multi(db, limit=5000):
                if notification_db.action_type != action_type or notification_db.read:
                    continue

                payload_db = {}
                if notification_db.action_payload:
                    try:
                        payload_db = json.loads(notification_db.action_payload)
                    except json.JSONDecodeError:
                        logger.warning("Could not parse action_payload for notification %s", notification_db.id)
                        continue

                if all(item in payload_db.items() for item in action_payload.items()):
                    return True

            return False
        except Exception as e:
            logger.error("Error checking for existing actionable notification: %s", e, exc_info=True)
            # Fail open: a duplicate notification is preferable to silently dropping a request.
            return False

    def handle_actionable_notification(
        self, db: Session, action_type: str, action_payload: Dict,
    ) -> bool:
        """Finds notifications by action type/payload and marks them as read."""
        logger.debug(f"Attempting to handle notification: type={action_type}, payload={action_payload}")
        try:
            # Assuming repo has a method to find by action (might need creating)
            # Alternatively, get all matching type and filter here
            # Example: Fetch notifications matching action_type (needs repo method)
            # matching_notifications = self._repo.get_by_action_type(db, action_type=action_type)
            
            # Simplified: Get all and filter (less efficient for many notifications)
            all_notifications = self._repo.get_multi(db, limit=5000) 
            
            found_and_handled = False
            for notification_db in all_notifications:
                 # Convert payload string from DB back to dict for comparison
                 payload_db = {}
                 if notification_db.action_payload:
                     try:
                         payload_db = json.loads(notification_db.action_payload)
                     except json.JSONDecodeError:
                         logger.warning(f"Could not parse action_payload for notification {notification_db.id}")
                         continue

                 # Check for match
                 if (notification_db.action_type == action_type and
                     payload_db is not None and
                     # Check if provided payload is subset of DB payload
                     all(item in payload_db.items() for item in action_payload.items())):
                    
                    if not notification_db.read:
                        # Mark as read using the update method
                        self._repo.update(db=db, db_obj=notification_db, obj_in={"read": True})
                        logger.info(f"Marked actionable notification as read: ID={notification_db.id}, Type={action_type}")
                        found_and_handled = True
                        # Optional: break if only one notification should match
                        # break 
                    else:
                        logger.info(f"Actionable notification already read: ID={notification_db.id}, Type={action_type}")
                        # Still count as found
                        found_and_handled = True 
                        # break 
            
            if not found_and_handled:
                logger.warning(f"Could not find actionable notification to handle: type={action_type}, payload={action_payload}")
            
            db.commit() # Commit the changes made (marking as read)
            return found_and_handled
            
        except Exception as e:
             logger.error(f"Error handling actionable notification: {e}", exc_info=True)
             db.rollback() # Rollback on error
             return False

    def update_notification(self, db: Session, notification_id: str, *,
                            title: Optional[str] = None,
                            subtitle: Optional[str] = None,
                            description: Optional[str] = None,
                            link: Optional[str] = None,
                            type: Optional[NotificationType] = None,
                            action_type: Optional[str] = None,
                            action_payload: Optional[Dict] = None,
                            read: Optional[bool] = None,
                            can_delete: Optional[bool] = None) -> Optional[Notification]:
        """Update fields on an existing notification and return the updated API model."""
        try:
            db_obj = self._repo.get(db=db, id=notification_id)
            if not db_obj:
                return None

            update_data: Dict = {}
            if title is not None:
                update_data['title'] = title
            if subtitle is not None:
                update_data['subtitle'] = subtitle
            if description is not None:
                update_data['description'] = description
            if link is not None:
                update_data['link'] = link
            if type is not None:
                update_data['type'] = type
            if action_type is not None:
                update_data['action_type'] = action_type
            if action_payload is not None:
                update_data['action_payload'] = action_payload
            if read is not None:
                update_data['read'] = read
            if can_delete is not None:
                update_data['can_delete'] = can_delete

            updated = self._repo.update(db=db, db_obj=db_obj, obj_in=update_data)
            return Notification.from_orm(updated)
        except Exception as e:
            logger.error(f"Error updating notification {notification_id}: {e}", exc_info=True)
            db.rollback()
            return None

    def create_notification(self, notification: Notification, db: Session) -> Notification:
        """Create a notification from a Notification object."""
        try:
            logger.debug(f"Creating notification: {notification.model_dump()}")
            created_db_obj = self._repo.create(db=db, obj_in=notification)
            return Notification.model_validate(created_db_obj)
        except Exception as e:
            logger.error(f"Error creating notification in DB: {e}", exc_info=True)
            db.rollback()
            raise

    def update_notification(self, notification_id: str, update: 'NotificationUpdate', db: Session) -> Optional[Notification]:
        """Update a notification using a NotificationUpdate object."""
        try:
            from src.models.notifications import NotificationUpdate
            
            db_obj = self._repo.get(db=db, id=notification_id)
            if not db_obj:
                return None

            # Convert update model to dictionary, excluding None values
            update_data = {k: v for k, v in update.model_dump(exclude_none=True).items()}
            
            if update_data:
                updated = self._repo.update(db=db, db_obj=db_obj, obj_in=update_data)
                return Notification.model_validate(updated)
            
            return Notification.model_validate(db_obj)
            
        except Exception as e:
            logger.error(f"Error updating notification {notification_id}: {e}", exc_info=True)
            db.rollback()
            return None

    def create_delivery_notification(
        self,
        db: Session,
        *,
        change_type: str,
        entity_type: str,
        entity_id: str,
        data: Dict[str, Any],
        source_user: Optional[str] = None,
        recipient_role: str = "Admin",
    ) -> Optional[Notification]:
        """Create a notification for manual delivery mode.
        
        This creates an actionable notification for admins to manually
        apply governance changes in external systems.
        
        Args:
            db: Database session
            change_type: Type of change (grant, revoke, etc.)
            entity_type: Type of entity being changed
            entity_id: ID of the entity
            data: Change details
            source_user: User who triggered the change
            recipient_role: Role that should receive the notification
            
        Returns:
            Created Notification or None on failure
        """
        try:
            # Build title based on change type
            title_map = {
                'grant': f"Grant Access: {entity_type}",
                'revoke': f"Revoke Access: {entity_type}",
                'tag_assign': f"Assign Tag: {entity_type}",
                'tag_remove': f"Remove Tag: {entity_type}",
                'contract_update': "Update Data Contract",
                'product_update': "Update Data Product",
                'dataset_update': "Update Dataset",
                'role_update': "Update Role Permissions",
            }
            title = title_map.get(change_type, f"Action Required: {change_type}")
            
            # Build description based on change type
            description_parts = [f"Manual action required for {entity_type} (ID: {entity_id})."]
            
            if change_type == 'grant':
                principal = data.get('principal', 'Unknown')
                privileges = data.get('privileges', [])
                target = data.get('target', entity_id)
                description_parts.append(f"Grant {', '.join(privileges) if privileges else 'access'} to {principal} on {target}")
            elif change_type == 'revoke':
                principal = data.get('principal', 'Unknown')
                target = data.get('target', entity_id)
                description_parts.append(f"Revoke access from {principal} on {target}")
            else:
                description_parts.append(f"Change type: {change_type}")
            
            if source_user:
                description_parts.append(f"\nRequested by: {source_user}")
            
            description = "\n".join(description_parts)
            
            # Create the notification
            notification = Notification(
                id=str(uuid.uuid4()),
                type=NotificationType.ACTION_REQUIRED,
                title=title,
                description=description,
                recipient=recipient_role,
                action_type="delivery_manual",
                action_payload={
                    "change_type": change_type,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "data": data,
                },
                created_at=datetime.now(timezone.utc),
                read=False,
                can_delete=True,
            )
            
            created = self._repo.create(db=db, obj_in=notification)
            db.commit()
            return Notification.model_validate(created)
            
        except Exception as e:
            logger.error(f"Error creating delivery notification: {e}", exc_info=True)
            db.rollback()
            return None

    def complete_delivery_notification(
        self,
        db: Session,
        notification_id: str,
        completed_by: str,
        notes: Optional[str] = None,
    ) -> Optional[Notification]:
        """Mark a delivery notification as completed.
        
        This updates the notification to indicate the manual action
        has been performed by an admin.
        
        Args:
            db: Database session
            notification_id: ID of the notification to complete
            completed_by: User who completed the action
            notes: Optional notes about the completion
            
        Returns:
            Updated Notification or None on failure
        """
        try:
            db_obj = self._repo.get(db=db, id=notification_id)
            if not db_obj:
                raise NotificationNotFoundError(f"Notification {notification_id} not found")
            
            # Update the notification
            update_data = {
                'read': True,
                'updated_at': datetime.now(timezone.utc),
            }
            
            # Update action_payload with completion details
            existing_payload = {}
            if db_obj.action_payload:
                try:
                    existing_payload = json.loads(db_obj.action_payload) if isinstance(db_obj.action_payload, str) else db_obj.action_payload
                except json.JSONDecodeError:
                    existing_payload = {}
            
            existing_payload['completed'] = True
            existing_payload['completed_by'] = completed_by
            existing_payload['completed_at'] = datetime.utcnow().isoformat()
            if notes:
                existing_payload['completion_notes'] = notes
            
            update_data['action_payload'] = existing_payload
            
            updated = self._repo.update(db=db, db_obj=db_obj, obj_in=update_data)
            db.commit()
            
            logger.info(f"Delivery notification {notification_id} completed by {completed_by}")
            return Notification.model_validate(updated)
            
        except NotificationNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error completing delivery notification: {e}", exc_info=True)
            db.rollback()
            return None

    def get_pending_delivery_notifications(
        self,
        db: Session,
        change_type: Optional[str] = None,
    ) -> List[Notification]:
        """Get all pending (unread) delivery notifications.
        
        Args:
            db: Database session
            change_type: Optional filter by change type
            
        Returns:
            List of pending delivery notifications
        """
        try:
            all_notifications = self._repo.get_multi(db=db, limit=1000)
            
            pending = []
            for db_obj in all_notifications:
                if db_obj.action_type != "delivery_manual":
                    continue
                if db_obj.read:
                    continue
                
                # Parse action_payload to check change_type filter
                if change_type:
                    payload = {}
                    if db_obj.action_payload:
                        try:
                            payload = json.loads(db_obj.action_payload) if isinstance(db_obj.action_payload, str) else db_obj.action_payload
                        except json.JSONDecodeError:
                            continue
                    if payload.get('change_type') != change_type:
                        continue
                
                try:
                    pending.append(Notification.model_validate(db_obj))
                except Exception:
                    continue
            
            return pending
            
        except Exception as e:
            logger.error(f"Error getting pending delivery notifications: {e}", exc_info=True)
            return []
