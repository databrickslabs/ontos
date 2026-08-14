import uuid
from datetime import datetime
from typing import Any, List, Optional, Dict
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

        user_groups = set(user_info.groups or [])
        user_email = user_info.email
        user_name = user_info.username  # Also check username for matching

        # Pre-fetch all role definitions for efficient lookup
        # Create multiple mappings: by UUID, by name, and flexible name variants
        try:
            all_roles = self._settings_manager.list_app_roles()
            role_by_id: Dict[str, 'AppRole'] = {}  # UUID -> role
            role_by_name: Dict[str, 'AppRole'] = {}  # Name variants -> role
            for role in all_roles:
                # Map by UUID
                role_by_id[role.id] = role
                # Map by exact name
                role_by_name[role.name] = role
                # Also map by normalized name (no spaces, lowercase) for flexible matching
                normalized = role.name.lower().replace(' ', '')
                role_by_name[normalized] = role
                # Also try CamelCase variant
                camel_case = ''.join(word.capitalize() for word in role.name.split())
                role_by_name[camel_case] = role
        except Exception as e:
            logger.error(f"Failed to retrieve roles for notification filtering: {e}")
            role_by_id = {}
            role_by_name = {}

        # Check if user is an admin (member of Admin role's groups)
        is_admin = False
        admin_role = role_by_name.get('Admin')
        if admin_role and admin_role.assigned_groups:
            is_admin = any(group in user_groups for group in admin_role.assigned_groups)

        filtered_notifications = []
        for n in all_notifications_api:
            is_recipient = False
            target_role = None
            recipient = n.recipient
            
            # Check recipient_role_id first (new, preferred method)
            if n.recipient_role_id and n.recipient_role_id in role_by_id:
                target_role = role_by_id[n.recipient_role_id]
                # Populate role name for display
                n.recipient_role_name = target_role.name
            
            if not recipient and not target_role:  # Broadcast
                is_recipient = True
            elif user_email and recipient == user_email:  # Direct email match
                is_recipient = True
            elif user_name and recipient == user_name:  # Direct username match
                is_recipient = True
            elif target_role:  # Role matched by UUID
                if target_role.assigned_groups:
                    if any(group in user_groups for group in target_role.assigned_groups):
                        is_recipient = True
                else:
                    # Role has NO groups assigned - show to admins as fallback
                    if is_admin:
                        is_recipient = True
            elif recipient in role_by_name:  # Legacy: recipient matches role name
                target_role = role_by_name[recipient]
                n.recipient_role_name = target_role.name  # Populate for display
                if target_role.assigned_groups:
                    if any(group in user_groups for group in target_role.assigned_groups):
                        is_recipient = True
                else:
                    # Role has NO groups assigned - show to admins as fallback
                    if is_admin:
                        is_recipient = True

            if is_recipient:
                # Admins can delete any notification they can see
                if is_admin:
                    n.can_delete = True
                filtered_notifications.append(n)

        # Sort by created_at descending (using datetime objects)
        filtered_notifications.sort(key=lambda x: x.created_at, reverse=True)

        return filtered_notifications

    def can_user_access_notification(self, db: Session, notification: Notification, user_info: UserInfo) -> bool:
        """Check if a user can access/modify a specific notification.
        
        Uses the same logic as get_notifications for role-based access checks.
        
        Args:
            db: Database session
            notification: The notification to check access for
            user_info: The user's info including email and groups
            
        Returns:
            True if user can access the notification, False otherwise
        """
        if not user_info:
            return False
            
        user_groups = set(user_info.groups or [])
        user_email = user_info.email
        user_name = user_info.username
        
        # Pre-fetch all role definitions for efficient lookup
        try:
            all_roles = self._settings_manager.list_app_roles()
            role_by_id: Dict[str, Any] = {}
            role_by_name: Dict[str, Any] = {}
            for role in all_roles:
                role_by_id[role.id] = role
                role_by_name[role.name] = role
                # Normalized variants
                normalized = role.name.lower().replace(' ', '')
                role_by_name[normalized] = role
                camel_case = ''.join(word.capitalize() for word in role.name.split())
                role_by_name[camel_case] = role
        except Exception as e:
            logger.error(f"Failed to retrieve roles for notification access check: {e}")
            role_by_id = {}
            role_by_name = {}
        
        # Check if user is an admin
        is_admin = False
        admin_role = role_by_name.get('Admin')
        if admin_role and admin_role.assigned_groups:
            is_admin = any(group in user_groups for group in admin_role.assigned_groups)
        
        recipient = notification.recipient
        target_role = None
        
        # Check recipient_role_id first (new, preferred method)
        if notification.recipient_role_id and notification.recipient_role_id in role_by_id:
            target_role = role_by_id[notification.recipient_role_id]
        
        # Broadcast notification - anyone can access
        if not recipient and not target_role:
            return True
        
        # Direct email match
        if user_email and recipient == user_email:
            return True
        
        # Direct username match
        if user_name and recipient == user_name:
            return True
        
        # Role matched by UUID
        if target_role:
            if target_role.assigned_groups:
                if any(group in user_groups for group in target_role.assigned_groups):
                    return True
            elif is_admin:
                # Role has NO groups assigned - allow admins as fallback
                return True
        
        # Legacy: recipient matches role name
        if recipient in role_by_name:
            target_role = role_by_name[recipient]
            if target_role.assigned_groups:
                if any(group in user_groups for group in target_role.assigned_groups):
                    return True
            elif is_admin:
                return True
        
        # Admins can access any notification
        if is_admin:
            return True
        
        return False

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
            now = datetime.utcnow()
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

    def handle_actionable_notification(self, db: Session, action_type: str, action_payload: Dict) -> bool:
        """Finds notifications by action type/payload and marks them as read using the repository."""
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
                created_at=datetime.utcnow(),
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
                'updated_at': datetime.utcnow(),
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
