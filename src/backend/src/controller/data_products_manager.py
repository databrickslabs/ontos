"""
ODPS v1.0.0 Data Products Manager

This module implements the business logic layer for ODPS v1.0.0 Data Products.
Handles product creation, updates, versioning, contract integration, and search indexing.
"""

import asyncio
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

SOURCE_ID_PROPERTY = "sourceId"


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, PermissionDenied

from src.models.data_products import (
    DataProduct as DataProductApi,
    DataProductCreate,
    DataProductUpdate,
    DataProductStatus,
    Description,
    AuthoritativeDefinition,
    CustomProperty,
    InputPort,
    OutputPort,
    ManagementPort,
    Support,
    Team,
    TeamMember,
    GenieSpaceRequest,
    NewVersionRequest,
    Subscription,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriberInfo,
    SubscribersListResponse,
    OnBehalfOf,
)
from src.models.users import UserInfo
from src.repositories.data_products_repository import data_product_repo, subscription_repo
from src.repositories.teams_repository import team_repo
from src.repositories.genie_spaces_repository import genie_space_repo
from src.models.genie_spaces import GenieSpaceCreate
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.common.search_registry import searchable_asset
from src.controller.notifications_manager import NotificationsManager
from src.controller.tags_manager import TagsManager
from src.repositories.tags_repository import entity_tag_repo
from src.models.tags import AssignedTagCreate
from src.common.logging import get_logger
from src.common.database import get_session_factory
from src.common import genie_client
from src.common.delivery_mixin import DeliveryMixin
from src.repositories.entity_relationships_repository import entity_relationship_repo
from src.repositories.assets_repository import asset_repo

logger = get_logger(__name__)


@searchable_asset
class DataProductsManager(DeliveryMixin, SearchableAsset):
    """Manager for ODPS v1.0.0 Data Products.
    
    Inherits DeliveryMixin to support automatic delivery of changes
    to configured delivery modes (Direct, Indirect, Manual).
    """
    
    # DeliveryMixin configuration
    DELIVERY_ENTITY_TYPE = "DataProduct"
    def __init__(
        self,
        db: Session,
        ws_client: Optional[WorkspaceClient] = None,
        notifications_manager: Optional[NotificationsManager] = None,
        tags_manager: Optional[TagsManager] = None
    ):
        """
        Initializes the DataProductsManager for ODPS v1.0.0.

        Args:
            db: SQLAlchemy Session for database operations.
            ws_client: Optional Databricks WorkspaceClient for SDK operations.
            notifications_manager: Optional NotificationsManager instance.
            tags_manager: Optional TagsManager for tag operations.
        """
        self._db = db
        self._ws_client = ws_client
        self._repo = data_product_repo
        self._notifications_manager = notifications_manager
        self._tags_manager = tags_manager
        self._entity_tag_repo = entity_tag_repo

        if not self._ws_client:
            logger.warning("WorkspaceClient not provided to DataProductsManager. SDK operations might fail.")
        if not self._notifications_manager:
            logger.warning("NotificationsManager not provided. Notifications will not be sent.")
        if not self._tags_manager:
            logger.warning("TagsManager not provided. Tag operations will not be available.")

    def get_statuses(self) -> List[str]:
        """Get all ODPS v1.0.0 status values."""
        return [s.value for s in DataProductStatus]

    def create_product(
        self,
        product_data: Dict[str, Any],
        db: Optional[Session] = None,
        user: Optional[str] = None,
        background_tasks: Optional[Any] = None,
        preserve_source_id: bool = False,
    ) -> DataProductApi:
        """Creates a new ODPS v1.0.0 data product via the repository.

        Args:
            product_data: Dictionary containing product data
            db: Optional database session to use. If not provided, uses self._db
            user: Optional user who created the product (for delivery tracking)
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
            preserve_source_id: If True, preserve the original non-UUID id as a
                sourceId custom property (used during batch upload/import)
        """
        from src.controller.delivery_service import DeliveryChangeType

        logger.debug(f"Manager creating ODPS product from data: {product_data}")
        # Use provided session or fall back to instance session
        db_session = db if db is not None else self._db
        try:
            # Preserve original external ID (e.g. URN) as a custom property
            # Only when explicitly requested (e.g. during batch upload/import)
            if preserve_source_id:
                original_id = product_data.get('id')
                if original_id and isinstance(original_id, str) and not _is_valid_uuid(original_id):
                    custom_props = product_data.get('customProperties', [])
                    if isinstance(custom_props, list):
                        custom_props.append({"property": SOURCE_ID_PROPERTY, "value": original_id})
                    elif isinstance(custom_props, dict):
                        custom_props[SOURCE_ID_PROPERTY] = original_id
                    product_data['customProperties'] = custom_props
                    logger.info(f"Preserved original ID '{original_id}' as {SOURCE_ID_PROPERTY} custom property")

            # Always generate a UUID for the product ID
            product_data['id'] = str(uuid.uuid4())
            logger.info(f"Generated ID {product_data['id']} for new product.")

            # Ensure ODPS required fields have defaults
            product_data.setdefault('apiVersion', 'v1.0.0')
            product_data.setdefault('kind', 'DataProduct')
            product_data.setdefault('status', DataProductStatus.DRAFT.value)

            # Validate
            try:
                product_api_model = DataProductCreate(**product_data)
            except ValidationError as e:
                logger.error(f"Validation failed for ODPS product: {e}")
                raise ValueError(f"Invalid ODPS product data: {e}") from e

            # Extract tags (handled separately)
            tags_data = product_data.get('tags', [])

            # Create via repository
            created_db_obj = self._repo.create(db=db_session, obj_in=product_api_model)

            # Handle tag assignments
            if tags_data and self._tags_manager:
                try:
                    self._assign_tags_to_product(created_db_obj.id, tags_data)
                except Exception as e:
                    logger.error(f"Failed to assign tags to product {created_db_obj.id}: {e}")

            # Load product with tags
            result = self._load_product_with_tags(created_db_obj)
            
            # Log to change log for timeline
            try:
                from src.controller.change_log_manager import change_log_manager
                change_log_manager.log_change_with_details(
                    db_session,
                    entity_type="data_product",
                    entity_id=str(created_db_obj.id),
                    action="CREATE",
                    username=user,
                    details={
                        "name": result.name,
                        "status": result.status.value if hasattr(result.status, 'value') else result.status,
                        "summary": f"Product '{result.name}' created" + (f" by {user}" if user else ""),
                    },
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for product creation: {log_err}")
            
            # Queue delivery for active modes
            self._queue_delivery(
                entity=created_db_obj,
                change_type=DeliveryChangeType.PRODUCT_CREATE,
                user=user,
                background_tasks=background_tasks,
            )
            
            self._update_search_index(result)
            return result

        except SQLAlchemyError as e:
            logger.error(f"Database error creating ODPS product: {e}")
            raise
        except ValueError as e:
            logger.error(f"Value error during ODPS product creation: {e}")
            raise

    def get_product(self, product_id: str) -> Optional[DataProductApi]:
        """Get an ODPS v1.0.0 data product by ID."""
        try:
            product_db = self._repo.get(db=self._db, id=product_id)
            if product_db:
                return self._load_product_with_tags(product_db)
            return None
        except SQLAlchemyError as e:
            logger.error(f"Database error getting product {product_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error getting product {product_id}: {e}")
            raise

    def list_products(
        self,
        skip: int = 0,
        limit: int = 100,
        project_id: Optional[str] = None,
        is_admin: bool = False
    ) -> List[DataProductApi]:
        """List ODPS v1.0.0 data products.

        Args:
            skip: Number of records to skip
            limit: Maximum number of records to return
            project_id: Optional project ID to filter by (ignored if is_admin=True)
            is_admin: If True, return all products regardless of project_id

        Returns:
            List of DataProduct API models
        """
        try:
            products_db = self._repo.get_multi(
                db=self._db,
                skip=skip,
                limit=limit,
                project_id=project_id,
                is_admin=is_admin
            )
            products_with_tags = []
            for product_db in products_db:
                product_with_tags = self._load_product_with_tags(product_db)
                products_with_tags.append(product_with_tags)
            return products_with_tags
        except SQLAlchemyError as e:
            logger.error(f"Database error listing products: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error listing products: {e}")
            raise

    def update_product(
        self,
        product_id: str,
        product_data_dict: Dict[str, Any],
        db: Optional[Session] = None,
        user: Optional[str] = None,
        background_tasks: Optional[Any] = None,
    ) -> Optional[DataProductApi]:
        """Update an existing ODPS v1.0.0 data product.
        
        Args:
            product_id: ID of product to update
            product_data_dict: Updated product data
            db: Optional database session. If not provided, uses self._db
            user: Optional user who updated the product (for delivery tracking)
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
        """
        from src.controller.delivery_service import DeliveryChangeType
        
        logger.debug(f"Manager updating ODPS product {product_id}")
        logger.debug(f"Update payload keys: {product_data_dict.keys()}")
        logger.debug(f"owner_team_id in payload: {product_data_dict.get('owner_team_id')}")
        logger.debug(f"project_id in payload: {product_data_dict.get('project_id')}")
        db_session = db if db is not None else self._db
        try:
            # VALIDATE FIRST - before acquiring any database locks
            # Extract tags (handled separately)
            tags_data = product_data_dict.pop('tags', None)

            # Prepare update payload
            update_payload = product_data_dict.copy()
            update_payload['id'] = product_id

            # Validate input data before DB operations
            try:
                product_update_model = DataProductUpdate(**update_payload)
            except ValidationError as e:
                logger.error(f"Validation error for ODPS update: {e}")
                raise ValueError(f"Invalid ODPS update data: {e}") from e

            # NOW do database operations after validation passes
            db_obj = self._repo.get(db=db_session, id=product_id)
            if not db_obj:
                logger.warning(f"Attempted to update non-existent product: {product_id}")
                return None

            # Update via repository
            updated_db_obj = self._repo.update(db=db_session, db_obj=db_obj, obj_in=product_update_model)

            # Handle tag updates
            if tags_data is not None and self._tags_manager:
                try:
                    self._assign_tags_to_product(product_id, tags_data)
                except Exception as e:
                    logger.error(f"Failed to update tags for product {product_id}: {e}")
                    # Rollback on tag assignment failure
                    db_session.rollback()
                    raise

            # Load product with tags
            result = self._load_product_with_tags(updated_db_obj)
            
            # Log to change log for timeline
            try:
                from src.controller.change_log_manager import change_log_manager
                change_log_manager.log_change_with_details(
                    db_session,
                    entity_type="data_product",
                    entity_id=str(product_id),
                    action="UPDATE",
                    username=user,
                    details={
                        "name": result.name,
                        "status": result.status.value if hasattr(result.status, 'value') else result.status,
                        "summary": f"Product '{result.name}' updated" + (f" by {user}" if user else ""),
                    },
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for product update: {log_err}")
            
            # Queue delivery for active modes
            self._queue_delivery(
                entity=updated_db_obj,
                change_type=DeliveryChangeType.PRODUCT_UPDATE,
                user=user,
                background_tasks=background_tasks,
            )
            
            self._update_search_index(result)
            return result

        except SQLAlchemyError as e:
            logger.error(f"Database error updating ODPS product {product_id}: {e}")
            db_session.rollback()
            raise
        except ValueError as e:
            logger.error(f"Value error updating ODPS product {product_id}: {e}")
            db_session.rollback()
            raise

    def update_product_with_auth(
        self,
        product_id: str,
        product_data_dict: Dict[str, Any],
        user_email: str,
        user_groups: List[str],
        db: Optional[Session] = None,
        background_tasks: Optional[Any] = None,
    ) -> Optional[DataProductApi]:
        """
        Update a data product with project membership authorization check.

        If the product belongs to a project, verifies that the user is a member
        of that project before allowing the update.

        Args:
            product_id: ID of product to update
            product_data_dict: Updated product data
            user_email: Email of user making the update
            user_groups: List of groups the user belongs to
            db: Optional database session. If not provided, uses self._db
            background_tasks: Optional FastAPI BackgroundTasks for async delivery

        Returns:
            Updated product if successful, None if not found

        Raises:
            PermissionError: If user is not a project member (when product has project_id)
            ValueError: If validation fails
            SQLAlchemyError: If database operation fails
        """
        logger.debug(f"Updating product {product_id} with auth check for user {user_email}")
        db_session = db if db is not None else self._db

        try:
            # Get existing product to check project membership
            existing_product_db = self._repo.get(db=db_session, id=product_id)
            if not existing_product_db:
                logger.warning(f"Product not found for update: {product_id}")
                return None

            # Check project membership if product belongs to a project
            if existing_product_db.project_id:
                from src.controller.projects_manager import projects_manager
                from src.common.config import get_settings

                settings = get_settings()
                is_member = projects_manager.is_user_project_member(
                    db=db_session,
                    user_identifier=user_email,
                    user_groups=user_groups,
                    project_id=existing_product_db.project_id,
                    settings=settings
                )

                if not is_member:
                    logger.warning(
                        f"User {user_email} denied update access to product {product_id} "
                        f"(project: {existing_product_db.project_id}) - not a project member"
                    )
                    raise PermissionError(
                        "You must be a member of the project to edit this data product"
                    )

            # Perform update (validation happens inside update_product)
            return self.update_product(
                product_id,
                product_data_dict,
                db=db_session,
                user=user_email,
                background_tasks=background_tasks,
            )
        
        except PermissionError:
            # Don't rollback for permission errors as no data was modified
            raise
        except Exception as e:
            logger.error(f"Error in update_product_with_auth for {product_id}: {e}")
            db_session.rollback()
            raise

    def delete_product(self, product_id: str, user: Optional[str] = None) -> bool:
        """Delete an ODPS v1.0.0 data product."""
        try:
            # Get product info before deletion for change log
            product_db = self._repo.get(db=self._db, id=product_id)
            product_name = product_db.name if product_db else None
            
            deleted_obj = self._repo.remove(db=self._db, id=product_id)
            
            if deleted_obj:
                # Log to change log for timeline
                try:
                    from src.controller.change_log_manager import change_log_manager
                    change_log_manager.log_change_with_details(
                        self._db,
                        entity_type="data_product",
                        entity_id=str(product_id),
                        action="DELETE",
                        username=user,
                        details={
                            "name": product_name,
                            "summary": f"Product '{product_name}' deleted" + (f" by {user}" if user else ""),
                        },
                    )
                except Exception as log_err:
                    logger.warning(f"Failed to log change for product deletion: {log_err}")
                
                self._notify_index_remove(f"product::{product_id}")
            
            return deleted_obj is not None
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting product {product_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error deleting product {product_id}: {e}")
            raise

    # ==================== Lifecycle Transition Methods ====================

    def transition_status(
        self,
        product_id: str,
        new_status: str,
        current_user: Optional[str] = None
    ) -> DataProductApi:
        """
        Transition product status with validation.
        
        Validates the transition is allowed per ODPS lifecycle rules (aligned with ODCS),
        then updates the product status.
        
        Lifecycle: draft → [sandbox] → proposed → under_review → approved → active → certified → deprecated → retired
        
        Args:
            product_id: ID of the product
            new_status: Target status
            current_user: Username for audit trail
            
        Returns:
            Updated product
            
        Raises:
            ValueError: If transition is invalid or product not found
            SQLAlchemyError: If database operation fails
        """
        # Certification is now a separate dimension — removed from status transitions
        from src.models.lifecycle import DATA_PRODUCT_TRANSITIONS
        valid_transitions = DATA_PRODUCT_TRANSITIONS
        
        try:
            product_db = self._repo.get(db=self._db, id=product_id)
            if not product_db:
                raise ValueError(f"Data product with ID {product_id} not found")
            
            # Normalize statuses
            current_status = (product_db.status or 'draft').lower()
            new_status_lower = new_status.lower()
            
            # Validate transition
            allowed = valid_transitions.get(current_status, [])
            if new_status_lower not in allowed:
                raise ValueError(
                    f"Invalid status transition from '{current_status}' to '{new_status_lower}'. "
                    f"Allowed transitions: {', '.join(allowed) if allowed else 'none'}"
                )
            
            # Run before_status_change workflows (gating)
            try:
                from src.common.workflow_triggers import get_trigger_registry
                from src.models.process_workflows import EntityType as WFEntityType
                trigger_registry = get_trigger_registry(self._db)
                gate_passed, gate_executions = trigger_registry.before_status_change(
                    entity_type=WFEntityType.DATA_PRODUCT,
                    entity_id=product_id,
                    from_status=current_status,
                    to_status=new_status_lower,
                    entity_name=product_db.name,
                    entity_data={"name": product_db.name, "status": current_status},
                    user_email=current_user,
                )
                if not gate_passed:
                    failed = [e for e in gate_executions if e.status.value != 'succeeded']
                    reasons = "; ".join(
                        e.step_results.get(e.current_step_id or '', {}).get('error', e.status.value)
                        for e in failed
                        if e.step_results
                    ) or "Workflow validation failed"
                    raise ValueError(
                        f"Status transition from '{current_status}' to '{new_status_lower}' "
                        f"blocked by workflow: {reasons}"
                    )
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f"before_status_change trigger error (non-fatal): {e}")
            
            # Update status
            old_status = product_db.status
            product_db.status = new_status_lower
            self._db.add(product_db)
            self._db.commit()
            
            logger.info(
                f"Product {product_id} status transitioned: {old_status} → {new_status_lower}"
                + (f" by {current_user}" if current_user else "")
            )
            
            # Log to change log for timeline
            try:
                from src.controller.change_log_manager import change_log_manager
                change_log_manager.log_change_with_details(
                    self._db,
                    entity_type="data_product",
                    entity_id=str(product_id),
                    action="STATUS_CHANGE",
                    username=current_user,
                    details={
                        "name": product_db.name,
                        "from_status": old_status,
                        "to_status": new_status_lower,
                        "summary": f"Status changed from '{old_status}' to '{new_status_lower}'" + (f" by {current_user}" if current_user else ""),
                    },
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for product status transition: {log_err}")
            
            # Notify subscribers about important status changes
            self._notify_subscribers_of_status_change(
                product_id=product_id,
                product_name=product_db.name or product_id,
                old_status=old_status,
                new_status=new_status_lower
            )
            
            # Fire on_status_change workflow trigger
            from src.common.workflow_triggers import fire_trigger_safe
            from src.models.process_workflows import EntityType
            fire_trigger_safe(
                self._db, "on_status_change",
                entity_type=EntityType.DATA_PRODUCT,
                entity_id=product_id,
                from_status=current_status,
                to_status=new_status_lower,
                entity_name=product_db.name,
                entity_data={"name": product_db.name, "status": new_status_lower},
                user_email=current_user,
            )

            result = self._load_product_with_tags(product_db)
            self._update_search_index(result)
            return result

        except SQLAlchemyError as e:
            logger.error(f"Database error transitioning product {product_id} status: {e}")
            raise
        except ValueError as e:
            logger.error(f"Validation error transitioning product {product_id}: {e}")
            raise

    def move_to_sandbox(self, product_id: str, current_user: Optional[str] = None) -> DataProductApi:
        """
        Move a draft product to sandbox for testing (draft → sandbox).

        Args:
            product_id: ID of the product to move
            current_user: Username for audit trail

        Returns:
            Updated product with 'sandbox' status

        Raises:
            ValueError: If product not found or invalid status transition
            SQLAlchemyError: If database operation fails
        """
        return self.transition_status(product_id, 'sandbox', current_user)

    def submit_for_review(self, product_id: str, current_user: Optional[str] = None) -> DataProductApi:
        """Submit a draft/sandbox product for review (draft/sandbox → proposed)."""
        return self.transition_status(product_id, 'proposed', current_user)

    # Backward-compatible alias
    submit_for_certification = submit_for_review

    def approve_product(self, product_id: str, current_user: Optional[str] = None) -> DataProductApi:
        """
        Approve a product under review (under_review → approved).

        Args:
            product_id: ID of the product to approve
            current_user: Username for audit trail

        Returns:
            Updated product with 'approved' status

        Raises:
            ValueError: If product not found or invalid status transition
            SQLAlchemyError: If database operation fails
        """
        return self.transition_status(product_id, 'approved', current_user)

    def reject_product(self, product_id: str, current_user: Optional[str] = None) -> DataProductApi:
        """
        Reject a product review, returning to draft (under_review → draft).

        Args:
            product_id: ID of the product to reject
            current_user: Username for audit trail

        Returns:
            Updated product with 'draft' status

        Raises:
            ValueError: If product not found or invalid status transition
            SQLAlchemyError: If database operation fails
        """
        return self.transition_status(product_id, 'draft', current_user)

    def publish_product(self, product_id: str, current_user: Optional[str] = None) -> DataProductApi:
        """
        Publish an approved product (approved → active).

        ODPS lifecycle (aligned with ODCS): Publishes a product to make it active and available
        in the marketplace. Validates that all output ports have data contracts assigned.

        Args:
            product_id: ID of the product to publish
            current_user: Username for audit trail

        Returns:
            Updated product with 'active' status

        Raises:
            ValueError: If product not found, invalid status, or validation fails
            SQLAlchemyError: If database operation fails
        """
        try:
            product_db = self._repo.get(db=self._db, id=product_id)
            if not product_db:
                raise ValueError(f"Data product with ID {product_id} not found")

            # Validate that all output ports have data contracts
            if product_db.output_ports:
                ports_without_contracts = [
                    port.name for port in product_db.output_ports
                    if not port.data_contract_id
                ]
                if ports_without_contracts:
                    raise ValueError(
                        f"Cannot publish product: Output ports {', '.join(ports_without_contracts)} "
                        f"must have data contracts assigned"
                    )

                # Validate that all linked contracts are in an approved status
                from src.repositories.data_contracts_repository import data_contract_repo
                
                valid_contract_statuses = ['approved', 'active']
                contracts_not_approved = []
                
                for port in product_db.output_ports:
                    if port.data_contract_id:
                        contract = data_contract_repo.get(db=self._db, id=port.data_contract_id)
                        if contract:
                            contract_status = (contract.status or '').lower()
                            if contract_status not in valid_contract_statuses:
                                contracts_not_approved.append(
                                    f"{port.name} -> {contract.name} (status: {contract.status})"
                                )
                
                if contracts_not_approved:
                    raise ValueError(
                        f"Cannot publish product: These output ports have unapproved contracts: "
                        f"{', '.join(contracts_not_approved)}. Contracts must be approved first."
                    )

            # Use transition_status for validation and update
            result = self.transition_status(product_id, 'active', current_user)

            # Set publication scope
            from datetime import datetime, timezone
            product_db.publication_scope = "organization"
            product_db.published_at = datetime.now(timezone.utc)
            product_db.published_by = current_user
            self._db.add(product_db)
            self._db.commit()

            # Fire on_publish trigger
            try:
                from src.common.workflow_triggers import get_trigger_registry
                from src.models.process_workflows import EntityType as WFEntityType
                trigger_registry = get_trigger_registry(self._db)
                trigger_registry.on_publish(
                    entity_type=WFEntityType.DATA_PRODUCT,
                    entity_id=product_id,
                    entity_name=product_db.name,
                    entity_data={"name": product_db.name, "status": "active"},
                    user_email=current_user,
                )
            except Exception as e:
                logger.warning(f"on_publish trigger error (non-fatal): {e}")

            return result

        except ValueError as e:
            logger.error(f"Validation error publishing product {product_id}: {e}")
            raise

    def certify_product(self, product_id: str, current_user: Optional[str] = None) -> DataProductApi:
        """DEPRECATED: certification is now a separate dimension. Use the certify endpoint instead.
        
        Kept for backward compatibility — raises informative error.
        """
        raise ValueError(
            "Status-based certification is removed. "
            "Use POST /api/data-products/{id}/certify with a certification_level instead."
        )

    def deprecate_product(self, product_id: str, current_user: Optional[str] = None) -> DataProductApi:
        """
        Deprecate an active product (active → deprecated).

        ODPS lifecycle: Marks a product as deprecated, signaling
        it will be retired soon and consumers should migrate.

        Args:
            product_id: ID of the product to deprecate
            current_user: Username for audit trail

        Returns:
            Updated product with 'deprecated' status

        Raises:
            ValueError: If product not found or invalid status transition
            SQLAlchemyError: If database operation fails
        """
        return self.transition_status(product_id, 'deprecated', current_user)

    # ==================== Status Change Request/Approval Methods ====================

    def _get_allowed_status_transitions(self, current_status: str) -> List[Dict[str, str]]:
        """Get allowed status transitions for a given status.
        
        Args:
            current_status: Current product status
            
        Returns:
            List of allowed transitions with target and label
        """
        transitions = {
            'draft': [
                {'target': 'sandbox', 'label': 'Move to Sandbox'},
                {'target': 'proposed', 'label': 'Submit for Review'},
            ],
            'sandbox': [
                {'target': 'draft', 'label': 'Return to Draft'},
                {'target': 'proposed', 'label': 'Submit for Review'},
            ],
            'proposed': [
                {'target': 'draft', 'label': 'Return to Draft'},
                {'target': 'under_review', 'label': 'Start Review'},
            ],
            'under_review': [
                {'target': 'approved', 'label': 'Approve'},
                {'target': 'draft', 'label': 'Reject (Return to Draft)'},
            ],
            'approved': [
                {'target': 'active', 'label': 'Publish/Activate'},
                {'target': 'draft', 'label': 'Return to Draft'},
            ],
            'active': [
                {'target': 'certified', 'label': 'Certify'},
                {'target': 'deprecated', 'label': 'Deprecate'},
            ],
            'certified': [
                {'target': 'deprecated', 'label': 'Deprecate'},
            ],
            'deprecated': [
                {'target': 'retired', 'label': 'Retire'},
                {'target': 'active', 'label': 'Reactivate'},
            ],
            'retired': []  # Terminal state
        }
        return transitions.get(current_status.lower(), [])

    def request_status_change(
        self,
        db: Session,
        notifications_manager: NotificationsManager,
        product_id: str,
        target_status: str,
        justification: str,
        requester_email: str,
        current_user: Optional[str] = None
    ) -> Dict[str, str]:
        """Request a status change for a product via workflow.
        
        Fires ON_REQUEST_STATUS_CHANGE trigger to execute configured workflows
        for notifications and approvals.
        
        Args:
            db: Database session
            notifications_manager: NotificationsManager instance (kept for backward compat)
            product_id: ID of product to change
            target_status: Requested target status
            justification: Reason for the status change
            requester_email: Email of user requesting the change
            current_user: Username of requester
            
        Returns:
            Dict with success message and workflow execution info
            
        Raises:
            ValueError: If product not found or invalid transition
        """
        from datetime import datetime
        from uuid import uuid4
        from src.common.workflow_triggers import get_trigger_registry
        from src.models.process_workflows import EntityType
        from src.controller.change_log_manager import change_log_manager
        
        product = data_product_repo.get(db, id=product_id)
        if not product:
            raise ValueError("Product not found")
        
        from_status = (product.status or 'draft').lower()
        target_status_lower = target_status.lower()
        
        # Validate transition is allowed
        allowed_transitions = self._get_allowed_status_transitions(from_status)
        if target_status_lower not in [t['target'] for t in allowed_transitions]:
            raise ValueError(f"Invalid status transition from '{from_status}' to '{target_status}'.")
        
        now = datetime.utcnow()
        request_id = str(uuid4())
        
        # Fire the ON_REQUEST_STATUS_CHANGE trigger
        trigger_registry = get_trigger_registry(db)
        executions = trigger_registry.on_request_status_change(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id=product_id,
            from_status=from_status,
            to_status=target_status_lower,
            entity_name=product.name,
            entity_data={
                "product_id": product_id,
                "product_name": product.name,
                "from_status": from_status,
                "target_status": target_status_lower,
                "justification": justification,
                "request_id": request_id,
            },
            user_email=requester_email,
        )
        
        # Log to change_log
        change_log_manager.log_change_with_details(
            db,
            entity_type="data_product",
            entity_id=product_id,
            action="status_change_requested",
            username=current_user or "anonymous",
            details={
                "requester_email": requester_email,
                "from_status": from_status,
                "target_status": target_status,
                "justification": justification,
                "timestamp": now.isoformat(),
                "summary": f"Status change requested from {from_status} to {target_status} by {current_user}",
                "workflow_triggered": len(executions) > 0,
            },
        )
        
        # Build response
        result = {
            "message": "Status change request submitted successfully",
            "request_id": request_id,
        }
        
        if executions:
            execution = executions[0]
            result["execution_id"] = execution.id
            result["workflow_status"] = execution.status.value
        
        return result

    def handle_status_change_response(
        self,
        db: Session,
        notifications_manager: NotificationsManager,
        product_id: str,
        approver_email: str,
        decision: str,
        target_status: str,
        message: Optional[str] = None,
        current_user: Optional[str] = None
    ) -> Dict[str, str]:
        """Handle a status change request decision (approve/deny/clarify).
        
        Args:
            db: Database session
            notifications_manager: NotificationsManager instance
            product_id: ID of product
            approver_email: Email of approver
            decision: 'approve', 'deny', or 'clarify'
            target_status: The target status that was requested
            message: Optional message from approver
            current_user: Username of approver
            
        Returns:
            Dict with result message
            
        Raises:
            ValueError: If product not found or invalid decision
        """
        from datetime import datetime
        from uuid import uuid4
        from src.models.notifications import NotificationType, Notification
        from src.controller.change_log_manager import change_log_manager
        
        product = data_product_repo.get(db, id=product_id)
        if not product:
            raise ValueError("Product not found")
        
        decision = decision.lower()
        if decision not in ('approve', 'deny', 'clarify'):
            raise ValueError("Decision must be 'approve', 'deny', or 'clarify'")
        
        now = datetime.utcnow()
        notification_title = ""
        notification_desc = ""
        
        # Find requester from change log
        requester_email = None
        try:
            recent_changes = change_log_manager.get_changes_for_entity(db, "data_product", product_id)
            for change in recent_changes:
                if change.action == "status_change_requested":
                    requester_email = change.details.get("requester_email")
                    break
        except Exception:
            pass
        
        if decision == 'approve':
            # Apply the status change directly
            self.transition_status(product_id, target_status, current_user)
            notification_title = "Product Status Change Approved"
            notification_desc = f"Your request to change the status of '{product.name}' to '{target_status}' has been approved by '{approver_email}'."
        elif decision == 'deny':
            notification_title = "Product Status Change Denied"
            notification_desc = f"Your request to change the status of '{product.name}' to '{target_status}' has been denied by '{approver_email}'."
        elif decision == 'clarify':
            notification_title = "Product Status Change - Clarification Needed"
            notification_desc = f"Your request to change the status of '{product.name}' to '{target_status}' requires clarification from '{approver_email}'."
        
        if message:
            notification_desc += f"\n\nApprover message: {message}"
        
        # Notify requester
        if requester_email:
            requester_note = Notification(
                id=str(uuid4()),
                created_at=now,
                type=NotificationType.INFO,
                title=notification_title,
                subtitle=f"Product: {product.name}",
                description=notification_desc,
                recipient=requester_email,
                can_delete=True,
            )
            notifications_manager.create_notification(notification=requester_note, db=db)
        
        # Mark actionable notification as handled
        try:
            notifications_manager.handle_actionable_notification(
                db=db,
                action_type="handle_product_status_change",
                action_payload={"product_id": product_id, "target_status": target_status},
            )
        except Exception:
            pass
        
        # Change log entry
        change_log_manager.log_change_with_details(
            db,
            entity_type="data_product",
            entity_id=product_id,
            action=f"status_change_{decision}",
            username=current_user or "anonymous",
            details={
                "approver_email": approver_email,
                "decision": decision,
                "target_status": target_status,
                "message": message,
                "timestamp": now.isoformat(),
                "summary": f"Status change {decision} by {approver_email}" + (f": {message}" if message else ""),
            },
        )
        
        return {"message": f"Status change request {decision} recorded successfully"}

    def request_review(
        self,
        product_id: str,
        reviewer_email: str,
        requester_email: str,
        message: Optional[str] = None,
        current_user: Optional[str] = None
    ) -> dict:
        """
        Request a data steward review for a product via workflow.
        
        Transitions DRAFT/SANDBOX → PROPOSED → UNDER_REVIEW, fires ON_REQUEST_REVIEW
        trigger to execute configured workflows for notifications and approvals.
        
        Args:
            product_id: Product ID to request review for
            reviewer_email: Email of the reviewer
            requester_email: Email of user requesting review
            message: Optional message to reviewer
            current_user: Username requesting review
            
        Returns:
            Dict with status, message, and workflow execution info
            
        Raises:
            ValueError: If product not found or invalid status
        """
        from datetime import datetime
        from uuid import uuid4
        from src.common.workflow_triggers import get_trigger_registry
        from src.models.process_workflows import EntityType
        from src.models.data_asset_reviews import AssetType, ReviewedAssetStatus
        
        product_db = self._repo.get(db=self._db, id=product_id)
        if not product_db:
            raise ValueError("Product not found")
        
        from_status = (product_db.status or '').lower()
        if from_status not in ('draft', 'sandbox'):
            raise ValueError(f"Cannot request review from status {product_db.status}. Must be DRAFT or SANDBOX.")
        
        # Transition to PROPOSED first
        self.transition_status(product_id, 'proposed', current_user)
        
        # Then transition to UNDER_REVIEW
        self.transition_status(product_id, 'under_review', current_user)
        
        now = datetime.utcnow()
        request_id = str(uuid4())
        
        # Create asset review record
        try:
            from src.controller.data_asset_reviews_manager import DataAssetReviewManager
            from src.models.data_asset_reviews import ReviewedAsset as ReviewedAssetApi
            
            if not self._notifications_manager:
                logger.warning("NotificationsManager not available for review workflow")
            
            review_manager = DataAssetReviewManager(
                db=self._db, 
                ws_client=self._ws_client, 
                notifications_manager=self._notifications_manager
            )
            
            review_asset = ReviewedAssetApi(
                id=str(uuid4()),
                asset_fqn=f"product:{product_id}",
                asset_type=AssetType.DATA_PRODUCT,
                status=ReviewedAssetStatus.PENDING,
                updated_at=now
            )
            logger.info(f"Created asset review record for product {product_id}")
        except Exception as e:
            logger.warning(f"Failed to create asset review record: {e}", exc_info=True)
        
        # Fire the ON_REQUEST_REVIEW trigger
        trigger_registry = get_trigger_registry(self._db)
        executions = trigger_registry.on_request_review(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id=product_id,
            entity_name=product_db.name,
            entity_data={
                "product_id": product_id,
                "product_name": product_db.name,
                "from_status": from_status,
                "to_status": "under_review",
                "message": message,
                "reviewer_email": reviewer_email,
                "request_id": request_id,
            },
            user_email=requester_email,
        )
        
        # Build response
        result = {
            "status": "success",
            "message": f"Review request created for product {product_db.name or product_id}",
            "request_id": request_id,
        }
        
        if executions:
            execution = executions[0]
            result["execution_id"] = execution.id
            result["workflow_status"] = execution.status.value
        
        return result

    def get_published_products(
        self, skip: int = 0, limit: int = 100, scope: Optional[str] = None
    ) -> List[DataProductApi]:
        """
        Get data products published to the marketplace (by publication scope).

        Returns products with a non-none publication_scope. Optionally filter to one scope.

        Args:
            skip: Number of products to skip (for pagination)
            limit: Maximum number of products to return
            scope: If set, only products whose publication_scope matches (case-insensitive)

        Returns:
            List of marketplace-visible data products

        Raises:
            SQLAlchemyError: If database operation fails
        """
        try:
            all_products = self.list_products(skip=skip, limit=limit)
            published_products = [
                product for product in all_products
                if product.publication_scope and product.publication_scope.lower() != 'none'
            ]
            if scope:
                published_products = [
                    p for p in published_products
                    if p.publication_scope and p.publication_scope.lower() == scope.lower()
                ]
            logger.info(
                f"Retrieved {len(published_products)} published products (scope={scope or 'all'})"
            )
            return published_products
        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving published products: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error retrieving published products: {e}")
            raise

    def upload_products_batch(
        self,
        file_content: bytes,
        filename: str
    ) -> tuple[List[DataProductApi], List[Dict[str, Any]]]:
        """
        Process and create multiple data products from uploaded YAML/JSON file.

        Handles:
        - File format detection and parsing (YAML/JSON)
        - ID generation for products without IDs
        - Duplicate detection
        - Validation
        - Batch creation with error collection

        Args:
            file_content: Raw file bytes
            filename: Original filename (used to detect format)

        Returns:
            Tuple of (created_products, errors_list)
            - created_products: List of successfully created products
            - errors_list: List of error dicts with 'id' and 'error' keys

        Raises:
            ValueError: If file format is invalid or parsing fails
        """
        logger.info(f"Processing batch upload from file: {filename}")

        # Parse file content
        try:
            if filename.endswith('.yaml') or filename.endswith('.yml'):
                import yaml
                data = yaml.safe_load(file_content)
            elif filename.endswith('.json'):
                import json
                data = json.loads(file_content)
            else:
                raise ValueError(f"Unsupported file type: {filename}. Must be .yaml, .yml, or .json")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML format: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}")

        # Normalize to list
        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            raise ValueError("File must contain a JSON object/array or YAML mapping/list of data products")

        # Process each product
        created_products: List[DataProductApi] = []
        errors: List[Dict[str, Any]] = []

        for idx, product_data in enumerate(data_list):
            if not isinstance(product_data, dict):
                errors.append({
                    "index": idx,
                    "error": "Item is not a dictionary/object",
                    "item_preview": str(product_data)[:100]
                })
                continue

            try:
                # create_product() always generates a UUID; preserve_source_id=True
                # stores any non-UUID original id as a sourceId custom property
                created_product = self.create_product(product_data, preserve_source_id=True)
                created_products.append(created_product)
                logger.info(f"Successfully created product {created_product.id} from batch upload")

            except Exception as e:
                error_id = product_data.get('id', f"index_{idx}")
                errors.append({
                    "id": error_id,
                    "index": idx,
                    "error": f"Creation failed: {str(e)}"
                })
                logger.error(f"Failed to create product at index {idx}: {e}")

        logger.info(
            f"Batch upload complete: {len(created_products)} created, "
            f"{len(errors)} errors from {len(data_list)} total items"
        )
        return created_products, errors

    def create_new_version(self, original_product_id: str, request: NewVersionRequest) -> DataProductApi:
        """Creates a new version of an ODPS v1.0.0 data product."""
        logger.info(f"Creating new ODPS version '{request.new_version}' from product {original_product_id}")

        original_product = self.get_product(original_product_id)
        if not original_product:
            raise ValueError(f"Original data product with ID {original_product_id} not found.")

        # Create new product data (exclude id, created_at, updated_at)
        new_product_data = original_product.model_dump(
            exclude={'id', 'created_at', 'updated_at'}
        )

        # Generate new ID and set new version
        new_product_data['id'] = str(uuid.uuid4())
        new_product_data['version'] = request.new_version

        # Link new version back to the original product
        new_product_data['parent_product_id'] = original_product_id

        # Reset status to DRAFT
        new_product_data['status'] = DataProductStatus.DRAFT.value
        logger.info(f"Resetting status to DRAFT for new version {new_product_data['id']}")

        try:
            # Validate and create
            new_product_api_model = DataProductCreate(**new_product_data)
            created_db_obj = self._repo.create(db=self._db, obj_in=new_product_api_model)

            logger.info(f"Successfully created new version {request.new_version} (ID: {created_db_obj.id})")
            result = DataProductApi.model_validate(created_db_obj)
            self._update_search_index(result)
            return result

        except ValidationError as e:
            logger.error(f"Validation error creating new ODPS version: {e}")
            raise ValueError(f"Validation error creating new version: {e}")
        except SQLAlchemyError as e:
            logger.error(f"Database error creating new version: {e}")
            raise

    # ==================== Versioned Editing Methods ====================

    def clone_product_for_new_version(
        self,
        db: Session,
        product_id: str,
        new_version: str,
        change_summary: Optional[str] = None,
        current_user: Optional[str] = None,
        as_personal_draft: bool = False
    ) -> DataProductApi:
        """Clone a product to create a new version with full deep copy.
        
        Creates a complete copy of the product including all nested entities:
        - Description, Authoritative definitions, Custom properties
        - Input ports, Output ports, Management ports
        - Support channels, Team members
        
        Args:
            db: Database session
            product_id: Source product ID to clone
            new_version: Semantic version string (e.g., "2.0.0") or placeholder
            change_summary: Optional summary of changes in this version
            current_user: Username creating the clone
            as_personal_draft: If True, creates a personal draft visible only to owner
            
        Returns:
            The newly created product API model
            
        Raises:
            ValueError: If product not found or version format invalid
        """
        import re
        from src.db_models.data_products import (
            DataProductDb, DescriptionDb, AuthoritativeDefinitionDb,
            CustomPropertyDb, InputPortDb, OutputPortDb, ManagementPortDb,
            SupportDb, DataProductTeamDb, DataProductTeamMemberDb,
            SBOMDb, InputContractDb
        )
        
        # Validate semantic version format (allow -draft suffix for personal drafts)
        if as_personal_draft:
            if not re.match(r'^\d+\.\d+\.\d+(-draft)?$', new_version):
                raise ValueError("new_version must be in format X.Y.Z or X.Y.Z-draft")
        else:
            if not re.match(r'^\d+\.\d+\.\d+$', new_version):
                raise ValueError("new_version must be in format X.Y.Z (e.g., 2.0.0)")
        
        # Get source product with all relationships
        source_product = data_product_repo.get(db, id=product_id)
        if not source_product:
            raise ValueError("Product not found")
        
        try:
            # Generate new ID
            new_id = str(uuid.uuid4())
            
            # Extract base_name from source (strip version suffix if present)
            base_name = source_product.base_name or source_product.name
            
            # Create new product with core fields
            new_product = DataProductDb(
                id=new_id,
                api_version=source_product.api_version,
                kind=source_product.kind,
                status='draft' if as_personal_draft else DataProductStatus.DRAFT.value,
                name=source_product.name,
                version=new_version,
                domain=source_product.domain,
                tenant=source_product.tenant,
                project_id=source_product.project_id,
                owner_team_id=source_product.owner_team_id,
                max_level_inheritance=source_product.max_level_inheritance,
                # Versioning fields
                draft_owner_id=current_user if as_personal_draft else None,
                parent_product_id=product_id,
                base_name=base_name,
                change_summary=change_summary,
            )
            db.add(new_product)
            db.flush()
            
            # Clone Description (One-to-One)
            if source_product.description:
                src_desc = source_product.description
                new_desc = DescriptionDb(
                    product_id=new_id,
                    purpose=src_desc.purpose,
                    limitations=src_desc.limitations,
                    usage=src_desc.usage
                )
                db.add(new_desc)
                
                # Clone description's authoritative definitions
                if hasattr(src_desc, 'authoritative_definitions') and src_desc.authoritative_definitions:
                    for auth_def in src_desc.authoritative_definitions:
                        new_auth_def = AuthoritativeDefinitionDb(
                            description_id=new_desc.id,
                            type=auth_def.type,
                            url=auth_def.url,
                            description=auth_def.description
                        )
                        db.add(new_auth_def)
            
            # Clone Authoritative Definitions (product-level)
            if source_product.authoritative_definitions:
                for auth_def in source_product.authoritative_definitions:
                    new_auth_def = AuthoritativeDefinitionDb(
                        product_id=new_id,
                        type=auth_def.type,
                        url=auth_def.url,
                        description=auth_def.description
                    )
                    db.add(new_auth_def)
            
            # Clone Custom Properties
            if source_product.custom_properties:
                for prop in source_product.custom_properties:
                    new_prop = CustomPropertyDb(
                        product_id=new_id,
                        property=prop.property,
                        value=prop.value,
                        description=prop.description
                    )
                    db.add(new_prop)
            
            # Clone Input Ports
            if source_product.input_ports:
                for port in source_product.input_ports:
                    new_port = InputPortDb(
                        product_id=new_id,
                        name=port.name,
                        version=port.version,
                        contract_id=port.contract_id
                    )
                    db.add(new_port)
                    db.flush()
                    
                    # Clone input contracts
                    if hasattr(port, 'input_contracts') and port.input_contracts:
                        for ic in port.input_contracts:
                            new_ic = InputContractDb(
                                input_port_id=new_port.id,
                                contract_id=ic.contract_id
                            )
                            db.add(new_ic)
            
            # Clone Output Ports
            if source_product.output_ports:
                for port in source_product.output_ports:
                    new_port = OutputPortDb(
                        product_id=new_id,
                        name=port.name,
                        version=port.version,
                        contract_id=port.contract_id,
                        expectation=port.expectation,
                        dataset_name=port.dataset_name
                    )
                    db.add(new_port)
                    db.flush()
                    
                    # Clone SBOMs
                    if hasattr(port, 'sboms') and port.sboms:
                        for sbom in port.sboms:
                            new_sbom = SBOMDb(
                                output_port_id=new_port.id,
                                spdx_version=sbom.spdx_version,
                                spdx_id=sbom.spdx_id,
                                name=sbom.name,
                                creation_info_created=sbom.creation_info_created
                            )
                            db.add(new_sbom)
            
            # Clone Management Ports
            if source_product.management_ports:
                for port in source_product.management_ports:
                    new_port = ManagementPortDb(
                        product_id=new_id,
                        name=port.name,
                        type=port.type,
                        description=port.description,
                        server=port.server,
                        endpoint=port.endpoint
                    )
                    db.add(new_port)
            
            # Clone Support Channels
            if source_product.support_channels:
                for channel in source_product.support_channels:
                    new_channel = SupportDb(
                        product_id=new_id,
                        type=channel.type,
                        url=channel.url,
                        description=channel.description
                    )
                    db.add(new_channel)
            
            # Clone Team
            if source_product.team:
                src_team = source_product.team
                new_team = DataProductTeamDb(
                    product_id=new_id,
                    name=src_team.name,
                    description=src_team.description
                )
                db.add(new_team)
                db.flush()
                
                # Clone team members
                if hasattr(src_team, 'members') and src_team.members:
                    for member in src_team.members:
                        new_member = DataProductTeamMemberDb(
                            team_id=new_team.id,
                            name=member.name,
                            email=member.email,
                            role=member.role
                        )
                        db.add(new_member)
            
            # Clone tags via entity_tag_repo
            try:
                source_tags = entity_tag_repo.get_tags_for_entity(
                    db, entity_type='data_product', entity_id=product_id
                )
                for tag_assignment in source_tags:
                    entity_tag_repo.assign_tag_to_entity(
                        db,
                        obj_in=AssignedTagCreate(tag_id=tag_assignment.tag_id),
                        entity_type='data_product',
                        entity_id=new_id
                    )
            except Exception as e:
                logger.warning(f"Could not clone tags: {e}")
            
            db.commit()
            db.refresh(new_product)
            
            logger.info(f"Successfully cloned product {product_id} to new version {new_version} (ID: {new_id})")
            return DataProductApi.model_validate(new_product)
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error cloning product: {e}", exc_info=True)
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Error cloning product: {e}", exc_info=True)
            raise

    def clone_product_for_editing(
        self,
        db: Session,
        product_id: str,
        current_user: str
    ) -> DataProductApi:
        """Create a personal draft copy of a product for editing.
        
        This is a convenience method that clones the product as a personal draft
        with a placeholder version (e.g., "1.0.0-draft").
        
        Args:
            db: Database session
            product_id: Source product ID to clone
            current_user: Username creating the draft
            
        Returns:
            The newly created personal draft product
        """
        # Get source product to extract current version
        source_product = data_product_repo.get(db, id=product_id)
        if not source_product:
            raise ValueError("Product not found")
        
        # Check if source is in an editable state - if so, don't clone
        if source_product.status and source_product.status.lower() in ['draft', 'proposed']:
            raise ValueError("Product is already in an editable state. Edit directly instead of cloning.")
        
        # Use current version with -draft suffix
        draft_version = f"{source_product.version or '0.0.0'}-draft"
        
        return self.clone_product_for_new_version(
            db=db,
            product_id=product_id,
            new_version=draft_version,
            change_summary="Personal draft for editing",
            current_user=current_user,
            as_personal_draft=True
        )

    def commit_personal_draft(
        self,
        db: Session,
        draft_id: str,
        new_version: str,
        change_summary: str,
        current_user: str
    ) -> DataProductApi:
        """Commit a personal draft to team/project visibility (tier 2).
        
        This promotes a personal draft from tier 1 (only owner sees it) to 
        tier 2 (team/project members can see it). The product is NOT published
        to the marketplace - that's a separate action.
        
        Args:
            db: Database session
            draft_id: ID of the personal draft to commit
            new_version: Final version string (e.g., "1.1.0")
            change_summary: Summary of changes made
            current_user: Username committing the draft
            
        Returns:
            The committed product
            
        Raises:
            ValueError: If draft not found
            PermissionError: If user is not the draft owner
        """
        import re
        
        # Validate version format
        if not re.match(r'^\d+\.\d+\.\d+$', new_version):
            raise ValueError("new_version must be in format X.Y.Z (e.g., 1.1.0)")
        
        draft = data_product_repo.get(db, id=draft_id)
        if not draft:
            raise ValueError("Draft product not found")
        if draft.draft_owner_id != current_user:
            raise PermissionError("Not owner of this draft")
        
        try:
            # Update the draft to remove personal ownership (promote to tier 2)
            draft.version = new_version
            draft.change_summary = change_summary
            draft.draft_owner_id = None  # Remove personal draft ownership
            # publication_scope stays none until an explicit marketplace publish

            db.commit()
            db.refresh(draft)
            
            logger.info(f"Committed personal draft {draft_id} as version {new_version}")
            return DataProductApi.model_validate(draft)
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error committing draft: {e}", exc_info=True)
            raise

    def discard_personal_draft(
        self,
        db: Session,
        draft_id: str,
        current_user: str
    ) -> bool:
        """Discard (delete) a personal draft.
        
        Args:
            db: Database session
            draft_id: ID of the personal draft to discard
            current_user: Username discarding the draft
            
        Returns:
            True if successfully discarded
            
        Raises:
            ValueError: If draft not found
            PermissionError: If user is not the draft owner
        """
        draft = data_product_repo.get(db, id=draft_id)
        if not draft:
            raise ValueError("Draft product not found")
        if draft.draft_owner_id != current_user:
            raise PermissionError("Not owner of this draft")
        
        try:
            data_product_repo.remove(db, id=draft_id)
            db.commit()
            logger.info(f"Discarded personal draft {draft_id}")
            return True
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error discarding draft: {e}", exc_info=True)
            raise

    def get_diff_from_parent(
        self,
        db: Session,
        product_id: str
    ) -> Dict[str, Any]:
        """Compare a draft product to its parent and suggest a version bump.
        
        Args:
            db: Database session
            product_id: ID of the draft product
            
        Returns:
            Dict with parent_version, suggested_bump, suggested_version, and analysis
            
        Raises:
            ValueError: If product or parent not found
        """
        product = data_product_repo.get(db, id=product_id)
        if not product:
            raise ValueError("Product not found")
        if not product.parent_product_id:
            raise ValueError("Product has no parent to compare against")
        
        parent = data_product_repo.get(db, id=product.parent_product_id)
        if not parent:
            raise ValueError("Parent product not found")
        
        # Convert to dicts for comparison
        product_dict = self._product_db_to_dict(product)
        parent_dict = self._product_db_to_dict(parent)
        
        # Run comparison analysis
        analysis_result = self.compare_products(parent_dict, product_dict)
        
        # Calculate suggested version
        suggested_version = self._calculate_next_version(
            parent.version or "0.0.0",
            analysis_result.get("version_bump", "patch")
        )
        
        return {
            "parent_version": parent.version or "0.0.0",
            "suggested_bump": analysis_result.get("version_bump", "patch"),
            "suggested_version": suggested_version,
            "analysis": analysis_result
        }

    def _calculate_next_version(self, current_version: str, bump_type: str) -> str:
        """Calculate the next semantic version based on bump type.
        
        Args:
            current_version: Current version string (e.g., "1.2.3")
            bump_type: Type of bump ("major", "minor", or "patch")
            
        Returns:
            Next version string
        """
        import re
        
        # Handle version with -draft suffix
        version = current_version.replace('-draft', '')
        
        # Parse version components
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version)
        if not match:
            return "0.0.1"
        
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        
        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:  # patch
            return f"{major}.{minor}.{patch + 1}"

    async def initiate_genie_space_creation(self, request: GenieSpaceRequest, user_info: UserInfo, db: Session):
        """Initiates Genie Space creation for selected ODPS data products."""
        if not self._notifications_manager:
            logger.error("Cannot initiate Genie Space creation: NotificationsManager not configured.")
            raise RuntimeError("Notification system is not available.")

        user_email = user_info.email
        product_ids_str = ", ".join(request.product_ids)
        logger.info(f"Initiating Genie Space for products: {product_ids_str} by {user_email}")

        # Send initial notification
        try:
            await self._notifications_manager.create_notification(
                db=db,
                user_id=user_email,
                title="Genie Space Creation Started",
                description=f"Genie Space creation for Data Product(s) {product_ids_str} initiated. "
                           "You will be notified when it's ready.",
                status="info"
            )
        except Exception as e:
            logger.error(f"Failed to send initial Genie Space notification: {e}", exc_info=True)

        # Schedule background task
        asyncio.create_task(self._create_genie_space_task(request.product_ids, user_email))
        logger.info(f"Genie Space creation task scheduled for: {product_ids_str}")

    async def _create_genie_space_task(self, product_ids: List[str], user_email: str):
        """Real Genie Space creation with Databricks API."""
        logger.info(f"Starting Genie Space creation for products: {product_ids}")

        # Get new database session for background task
        session_factory = get_session_factory()
        if not session_factory:
            logger.error("Cannot create Genie Space: Database session factory not available.")
            return

        try:
            with session_factory() as db:
                # Step 1: Collect datasets from output ports
                logger.info("Collecting datasets from output ports...")
                datasets = genie_client.collect_datasets_from_products(product_ids, db)

                if not datasets:
                    logger.warning("No datasets found in output ports")
                    raise ValueError("No datasets found to add to Genie Space")

                logger.info(f"Found {len(datasets)} datasets: {datasets}")

                # Step 2: Collect rich text metadata
                logger.info("Collecting rich text metadata...")
                metadata_map = genie_client.collect_rich_text_metadata(product_ids, db)

                # Step 3: Get product details for formatting
                products = [self._repo.get(db, id=pid) for pid in product_ids if self._repo.get(db, id=pid)]

                # Step 4: Format metadata as instructions
                instructions = genie_client.format_metadata_for_genie(metadata_map, products)
                logger.info(f"Formatted {len(instructions)} characters of metadata")

                # Step 5: Create Genie Space via API
                space_name = f"Data Product Space ({len(products)} products)"
                if len(products) == 1:
                    space_name = f"{products[0].name} - Genie Space"

                logger.info(f"Creating Genie Space: {space_name}")
                result = await genie_client.create_genie_space(
                    ws_client=self._ws_client,
                    name=space_name,
                    datasets=datasets,
                    description=f"Genie Space for {len(products)} Data Product(s)",
                    instructions=instructions
                )

                # Step 6: Persist to database
                genie_space_create = GenieSpaceCreate(
                    space_id=result['space_id'],
                    space_name=space_name,
                    space_url=result['space_url'],
                    status=result['status'],
                    datasets=datasets,
                    product_ids=product_ids,
                    instructions=instructions,
                    created_by=user_email
                )
                genie_space_db = genie_space_repo.create(db, obj_in=genie_space_create)
                db.commit()

                logger.info(f"Genie Space persisted: {genie_space_db.id}")

                # Step 7: Send success notification
                if self._notifications_manager:
                    await self._notifications_manager.create_notification(
                        db=db,
                        user_id=user_email,
                        title="Genie Space Ready",
                        description=f"Your Genie Space '{space_name}' has been created with {len(datasets)} datasets.",
                        link=result['space_url'],
                        status="success"
                    )

        except Exception as e:
            logger.error(f"Failed to create Genie Space: {e}", exc_info=True)

            # Send failure notification
            if self._notifications_manager:
                try:
                    with session_factory() as db:
                        await self._notifications_manager.create_notification(
                            db=db,
                            user_id=user_email,
                            title="Genie Space Creation Failed",
                            description=f"Failed to create Genie Space: {str(e)}",
                            status="error"
                        )
                except Exception as notify_error:
                    logger.error(f"Failed to send error notification: {notify_error}")

            # Persist failed attempt
            try:
                with session_factory() as db:
                    genie_space_create = GenieSpaceCreate(
                        space_id=f"failed-{uuid.uuid4()}",
                        space_name="Failed Space",
                        status="failed",
                        product_ids=product_ids,
                        created_by=user_email,
                        error_message=str(e)
                    )
                    genie_space_repo.create(db, obj_in=genie_space_create)
                    db.commit()
            except Exception as persist_error:
                logger.error(f"Failed to persist error: {persist_error}")

    def save_to_yaml(self, yaml_path: str) -> bool:
        """Save current ODPS v1.0.0 data products to a YAML file."""
        try:
            all_products_api = self.list_products(limit=10000)
            products_list = [p.model_dump(by_alias=True) for p in all_products_api]

            with open(yaml_path, 'w') as file:
                yaml.dump(products_list, file, default_flow_style=False, sort_keys=False)

            logger.info(f"Saved {len(products_list)} ODPS products to {yaml_path}")
            return True

        except Exception as e:
            logger.error(f"Error saving ODPS products to YAML {yaml_path}: {e}")
            return False

    # --- ODPS-specific query helpers ---

    def get_distinct_domains(self) -> List[str]:
        """Get distinct domain values from ODPS products."""
        try:
            return self._repo.get_distinct_domains(db=self._db)
        except Exception as e:
            logger.error(f"Error getting distinct domains: {e}", exc_info=True)
            return []

    def get_distinct_tenants(self) -> List[str]:
        """Get distinct tenant values from ODPS products."""
        try:
            return self._repo.get_distinct_tenants(db=self._db)
        except Exception as e:
            logger.error(f"Error getting distinct tenants: {e}", exc_info=True)
            return []

    def get_distinct_statuses(self) -> List[str]:
        """Get all distinct ODPS status values."""
        try:
            return self._repo.get_distinct_statuses(db=self._db)
        except Exception as e:
            logger.error(f"Error getting distinct statuses: {e}", exc_info=True)
            return []

    def get_distinct_product_types(self) -> List[str]:
        """Get distinct product types from output ports."""
        try:
            return self._repo.get_distinct_product_types(db=self._db)
        except Exception as e:
            logger.error(f"Error getting distinct product types: {e}", exc_info=True)
            return []

    def get_distinct_owners(self) -> List[str]:
        """Get distinct owner names from product teams."""
        try:
            return self._repo.get_distinct_owners(db=self._db)
        except Exception as e:
            logger.error(f"Error getting distinct owners: {e}", exc_info=True)
            return []

    # --- SearchableAsset implementation ---

    def _build_search_index_item(self, product: DataProductApi) -> Optional[SearchIndexItem]:
        """Convert a single DataProduct API model to a SearchIndexItem."""
        if not product.id or not product.name:
            return None

        description = ""
        if product.description:
            parts = []
            if product.description.purpose:
                parts.append(product.description.purpose)
            if product.description.usage:
                parts.append(product.description.usage)
            description = " | ".join(parts)

        tag_strings: List[str] = []
        try:
            for t in (product.tags or []):
                if hasattr(t, 'fully_qualified_name') and t.fully_qualified_name:
                    tag_strings.append(t.fully_qualified_name)
                elif isinstance(t, dict):
                    fqn = t.get('fully_qualified_name') or t.get('tag_fqn')
                    if fqn:
                        tag_strings.append(str(fqn))
                elif hasattr(t, 'tag_name') and t.tag_name:
                    tag_strings.append(str(t.tag_name))
                else:
                    tag_strings.append(str(t))
        except Exception:
            tag_strings = []

        owner_team_name = ""
        if product.owner_team_id:
            try:
                from uuid import UUID
                owner_team = team_repo.get(self._db, id=UUID(product.owner_team_id))
                if owner_team:
                    owner_team_name = owner_team.name or ""
            except Exception as e:
                logger.debug(f"Could not resolve owner_team_id {product.owner_team_id}: {e}")

        product_team_name = product.team.name if product.team and product.team.name else ""
        team_member_names: List[str] = []
        if product.team and product.team.members:
            for member in product.team.members:
                if member.name:
                    team_member_names.append(member.name)
                if member.username and member.username != member.name:
                    team_member_names.append(member.username)

        extra_data = {
            "status": product.status or "",
            "version": product.version or "",
            "domain": product.domain or "",
            "owner": owner_team_name or product_team_name,
            "owner_team": owner_team_name,
            "product_team": product_team_name,
            "team_members": ", ".join(team_member_names),
        }

        return SearchIndexItem(
            id=f"product::{product.id}",
            type="data-product",
            feature_id="data-products",
            title=product.name,
            description=description,
            link=f"/data-products/{product.id}",
            tags=tag_strings,
            extra_data=extra_data,
        )

    def _update_search_index(self, product: DataProductApi) -> None:
        """Build a SearchIndexItem from a product and upsert it into the index."""
        item = self._build_search_index_item(product)
        if item:
            self._notify_index_upsert(item)

    def get_search_index_items(self) -> List[SearchIndexItem]:
        """Fetches ODPS v1.0.0 data products and maps them to SearchIndexItem format."""
        logger.info("Fetching ODPS products for search indexing...")
        items = []
        try:
            products_api = self.list_products(limit=10000)
            for product in products_api:
                item = self._build_search_index_item(product)
                if item:
                    items.append(item)
            logger.info(f"Prepared {len(items)} ODPS products for search index.")
            return items
        except Exception as e:
            logger.error(f"Error fetching/mapping ODPS products for search: {e}", exc_info=True)
            return []

    # --- Tag integration helpers ---

    def _assign_tags_to_product(self, product_id: str, tags_data: List[Dict[str, Any]]) -> None:
        """Helper to assign tags to an ODPS data product."""
        if not self._tags_manager:
            logger.warning("TagsManager not available, cannot assign tags")
            return

        try:
            assigned_tags = []
            for tag_data in tags_data:
                if isinstance(tag_data, dict):
                    try:
                        assigned_tag = AssignedTagCreate(**tag_data)
                        assigned_tags.append(assigned_tag)
                    except Exception as e:
                        logger.warning(f"Failed to parse tag data {tag_data}: {e}")
                else:
                    try:
                        assigned_tag = AssignedTagCreate(tag_fqn=str(tag_data), assigned_value=None)
                        assigned_tags.append(assigned_tag)
                    except Exception as e:
                        logger.warning(f"Failed to create AssignedTagCreate from string {tag_data}: {e}")

            if not assigned_tags:
                logger.debug(f"No valid tags to assign to ODPS product {product_id}")
                return

            self._tags_manager.set_tags_for_entity(
                db=self._db,
                entity_id=product_id,
                entity_type="data_product",
                tags=assigned_tags,
                user_email="system"
            )
            logger.debug(f"Successfully assigned {len(assigned_tags)} tags to ODPS product {product_id}")

        except Exception as e:
            logger.error(f"Failed to assign tags to ODPS product {product_id}: {e}", exc_info=True)

    def _load_product_with_tags(self, db_obj) -> DataProductApi:
        """Helper to load an ODPS data product with its associated tags."""
        try:
            product_api = DataProductApi.model_validate(db_obj)

            if self._tags_manager:
                try:
                    assigned_tags = self._entity_tag_repo.get_assigned_tags_for_entity(
                        db=self._db,
                        entity_id=db_obj.id,
                        entity_type="data_product"
                    )
                    product_api.tags = assigned_tags
                except Exception as e:
                    logger.error(f"Failed to load tags for ODPS product {db_obj.id}: {e}")
                    product_api.tags = []
            else:
                product_api.tags = []

            # Resolve owner team name
            if product_api.owner_team_id:
                try:
                    from uuid import UUID
                    owner_team = team_repo.get(self._db, id=UUID(product_api.owner_team_id))
                    product_api.owner_team_name = owner_team.name if owner_team else None
                except Exception as e:
                    logger.debug(f"Could not resolve owner_team: {e}")

            # Resolve project name
            if product_api.project_id:
                try:
                    from src.repositories.projects_repository import project_repo
                    project = project_repo.get(self._db, id=product_api.project_id)
                    product_api.project_name = project.name if project else None
                except Exception as e:
                    logger.debug(f"Could not resolve project: {e}")

            # Resolve contract names and delivery method names for output ports
            if product_api.outputPorts:
                from src.repositories.data_contracts_repository import data_contract_repo
                from src.repositories.delivery_methods_repository import delivery_method_repo
                for port in product_api.outputPorts:
                    if port.contractId:
                        try:
                            contract = data_contract_repo.get(self._db, id=port.contractId)
                            port.contractName = contract.name if contract else None
                        except Exception as e:
                            logger.debug(f"Could not resolve contract: {e}")
                    if port.deliveryMethodId:
                        try:
                            dm = delivery_method_repo.get(self._db, port.deliveryMethodId)
                            port.deliveryMethodName = dm.name if dm else None
                        except Exception as e:
                            logger.debug(f"Could not resolve delivery method: {e}")

            return product_api

        except Exception as e:
            logger.error(f"Failed to load ODPS product with tags: {e}")
            return DataProductApi.model_validate(db_obj)

    def assign_tag_to_product(self, product_id: str, tag_id: str, assigned_value: Optional[str] = None,
                              assigned_by: str = "system") -> bool:
        """Public method to assign a tag to an ODPS data product."""
        if not self._tags_manager:
            logger.error("TagsManager not available, cannot assign tag")
            return False

        try:
            self._entity_tag_repo.add_tag_to_entity(
                db=self._db,
                tag_id=tag_id,
                entity_id=product_id,
                entity_type="data_product",
                assigned_value=assigned_value,
                assigned_by=assigned_by
            )
            return True
        except Exception as e:
            logger.error(f"Failed to assign tag {tag_id} to ODPS product {product_id}: {e}")
            return False

    def remove_tag_from_product(self, product_id: str, tag_id: str) -> bool:
        """Public method to remove a tag from an ODPS data product."""
        if not self._tags_manager:
            logger.error("TagsManager not available, cannot remove tag")
            return False

        try:
            return self._entity_tag_repo.remove_tag_from_entity(
                db=self._db,
                tag_id=tag_id,
                entity_id=product_id,
                entity_type="data_product"
            )
        except Exception as e:
            logger.error(f"Failed to remove tag {tag_id} from ODPS product {product_id}: {e}")
            return False

    def get_product_tags(self, product_id: str) -> List[Dict[str, Any]]:
        """Public method to get all tags assigned to an ODPS data product."""
        if not self._tags_manager:
            logger.warning("TagsManager not available, returning empty tags list")
            return []

        try:
            return self._entity_tag_repo.get_assigned_tags_for_entity(
                db=self._db,
                entity_id=product_id,
                entity_type="data_product"
            )
        except Exception as e:
            logger.error(f"Failed to get tags for ODPS product {product_id}: {e}")
            return []

    def _preprocess_tags_for_yaml_loading(self, product_dict: Dict[str, Any]) -> None:
        """Convert tag_fqn format in YAML to AssignedTagCreate format."""
        def process_tags_in_dict(obj: Dict[str, Any]):
            if 'tags' in obj and isinstance(obj['tags'], list):
                new_tags = []
                for tag_item in obj['tags']:
                    if isinstance(tag_item, dict) and 'tag_fqn' in tag_item:
                        if 'assigned_value' not in tag_item:
                            tag_item['assigned_value'] = None
                        new_tags.append(tag_item)
                    elif isinstance(tag_item, str):
                        new_tags.append({"tag_fqn": tag_item, "assigned_value": None})
                    else:
                        if isinstance(tag_item, dict) and 'assigned_value' not in tag_item:
                            tag_item['assigned_value'] = None
                        new_tags.append(tag_item)
                obj['tags'] = new_tags

            for key, value in obj.items():
                if isinstance(value, dict):
                    process_tags_in_dict(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            process_tags_in_dict(item)

        process_tags_in_dict(product_dict)

    # --- Contract-Product Integration (ODPS v1.0.0) ---

    def create_from_contract(
        self,
        contract_id: str,
        product_name: str,
        version: str,
        output_port_name: Optional[str] = None
    ) -> DataProductApi:
        """
        Creates a new ODPS v1.0.0 Data Product from an existing Data Contract.

        The contract governs one output port of the product. Inherits domain,
        owner team, and project from the contract.

        Args:
            contract_id: ID of the contract to create product from
            product_name: Name for the new data product
            version: Version string for the product
            output_port_name: Optional name for the output port

        Returns:
            Created DataProduct API model

        Raises:
            ValueError: If contract doesn't exist or is not in valid status
        """
        logger.info(f"Creating ODPS Data Product '{product_name}' from contract {contract_id}")

        from src.repositories.data_contracts_repository import data_contract_repo

        # Validate contract exists
        contract_db = data_contract_repo.get(db=self._db, id=contract_id)
        if not contract_db:
            raise ValueError(f"Data Contract with ID {contract_id} not found")

        # Validate contract status
        valid_statuses = ['active', 'approved', 'certified']
        if contract_db.status and contract_db.status.lower() not in valid_statuses:
            raise ValueError(
                f"Cannot create product from contract in status '{contract_db.status}'. "
                f"Contract must be in one of: {', '.join(valid_statuses)}"
            )

        # Create ODPS product data
        product_id = str(uuid.uuid4())
        product_data = {
            'id': product_id,
            'apiVersion': 'v1.0.0',
            'kind': 'DataProduct',
            'name': product_name,
            'version': version,
            'status': DataProductStatus.DRAFT.value,
            'domain': contract_db.domain_id,  # Inherit from contract
            'description': {
                'purpose': f"Data Product created from contract: {contract_db.name}",
                'limitations': None,
                'usage': None
            },
            'inputPorts': [],
            'outputPorts': [
                {
                    'name': output_port_name or contract_db.name,
                    'version': version,
                    'description': f"Output governed by contract: {contract_db.name}",
                    'contractId': contract_id  # Link to contract
                }
            ]
        }

        # TODO: Add team members from contract owner
        if contract_db.owner_team_id:
            product_data['team'] = {
                'name': f"Team from contract {contract_db.name}",
                'members': []  # Could populate from contract owner
            }

        # Create the product
        created_product = self.create_product(product_data)
        logger.info(f"Successfully created ODPS Data Product {product_id} from contract {contract_id}")
        return created_product

    def get_products_by_contract(self, contract_id: str) -> List[DataProductApi]:
        """
        Get all ODPS Data Products that use a specific Data Contract.

        Args:
            contract_id: ID of the contract to search for

        Returns:
            List of DataProduct API models with output ports linked to this contract
        """
        logger.debug(f"Fetching ODPS products linked to contract {contract_id}")

        try:
            all_products = self.list_products(limit=10000)
            linked_products = []

            for product in all_products:
                if product.outputPorts:
                    for port in product.outputPorts:
                        if port.contractId == contract_id:
                            linked_products.append(product)
                            break

            logger.info(f"Found {len(linked_products)} ODPS products linked to contract {contract_id}")
            return linked_products

        except Exception as e:
            logger.error(f"Error fetching ODPS products by contract {contract_id}: {e}")
            raise

    def get_contracts_for_product(self, product_id: str) -> List[str]:
        """
        Get all Data Contract IDs associated with an ODPS Data Product's output ports.

        Args:
            product_id: ID of the product

        Returns:
            List of contract IDs (may be empty)
        """
        logger.debug(f"Fetching contracts for ODPS product {product_id}")

        try:
            product = self.get_product(product_id)
            if not product:
                raise ValueError(f"Product with ID {product_id} not found")

            contract_ids = []
            if product.outputPorts:
                for port in product.outputPorts:
                    if port.contractId and port.contractId not in contract_ids:
                        contract_ids.append(port.contractId)

            logger.info(f"Found {len(contract_ids)} contracts for ODPS product {product_id}")
            return contract_ids

        except Exception as e:
            logger.error(f"Error fetching contracts for ODPS product {product_id}: {e}")
            raise

    # ------------------------------------------------------------------
    # Dataset hierarchy (Phase 5 — asset-backed datasets)
    # ------------------------------------------------------------------

    def get_product_datasets(
        self,
        product_id: str,
        db: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        """Return Dataset assets linked to this product via hasDataset relationships.

        Each entry contains the asset summary plus the relationship ID.
        """
        session = db or self._db
        rels = entity_relationship_repo.query_filtered(
            session,
            source_type="DataProduct",
            source_id=product_id,
            relationship_type="hasDataset",
        )
        results = []
        for r in rels:
            asset = asset_repo.get(session, r.target_id)
            if asset:
                results.append({
                    "relationship_id": str(r.id),
                    "dataset_id": str(asset.id),
                    "name": asset.name,
                    "description": asset.description,
                    "status": asset.status,
                    "properties": asset.properties or {},
                    "tags": asset.tags or [],
                    "created_at": asset.created_at.isoformat() if asset.created_at else None,
                })
        return results

    def get_product_hierarchy(
        self,
        product_id: str,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Resolve the full DP > Dataset > Table/View > Column hierarchy.

        Returns a nested dict:
        {
          "product_id": "...",
          "product_name": "...",
          "datasets": [
            {
              "dataset_id": "...", "name": "...", "status": "...",
              "tables": [ { "id", "name", "location", "columns": [...] } ],
              "views": [ { "id", "name", "location", "columns": [...] } ],
              "contract": { "id", "type" } | null
            }, ...
          ]
        }
        """
        session = db or self._db

        product = self.get_product(product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        datasets_out = []
        ds_rels = entity_relationship_repo.query_filtered(
            session,
            source_type="DataProduct",
            source_id=product_id,
            relationship_type="hasDataset",
        )

        for ds_rel in ds_rels:
            ds_asset = asset_repo.get(session, ds_rel.target_id)
            if not ds_asset:
                continue

            ds_entry: Dict[str, Any] = {
                "dataset_id": str(ds_asset.id),
                "name": ds_asset.name,
                "description": ds_asset.description,
                "status": ds_asset.status,
                "properties": ds_asset.properties or {},
                "tables": [],
                "views": [],
                "contract": None,
            }

            child_rels = entity_relationship_repo.query_filtered(
                session,
                source_type="Dataset",
                source_id=str(ds_asset.id),
            )

            for child_rel in child_rels:
                if child_rel.relationship_type == "governedBy":
                    ds_entry["contract"] = {
                        "id": child_rel.target_id,
                        "type": child_rel.target_type,
                    }
                    continue

                child_asset = asset_repo.get(session, child_rel.target_id)
                if not child_asset:
                    continue

                child_entry = {
                    "id": str(child_asset.id),
                    "name": child_asset.name,
                    "location": child_asset.location,
                    "status": child_asset.status,
                    "properties": child_asset.properties or {},
                    "columns": [],
                }

                col_rels = entity_relationship_repo.query_filtered(
                    session,
                    source_type=child_rel.target_type,
                    source_id=child_rel.target_id,
                    relationship_type="hasColumn",
                )
                for col_rel in col_rels:
                    col_asset = asset_repo.get(session, col_rel.target_id)
                    if col_asset:
                        child_entry["columns"].append({
                            "id": str(col_asset.id),
                            "name": col_asset.name,
                            "properties": col_asset.properties or {},
                        })

                if child_rel.relationship_type == "hasTable":
                    ds_entry["tables"].append(child_entry)
                elif child_rel.relationship_type == "hasView":
                    ds_entry["views"].append(child_entry)

            datasets_out.append(ds_entry)

        return {
            "product_id": product_id,
            "product_name": product.name or product_id,
            "datasets": datasets_out,
        }

    def build_odps_export(
        self,
        product_id: str,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Build a full ODPS v1.0.0-compatible YAML export of a Data Product.

        Includes the standard ODPS structure plus entity relationship-based
        dataset hierarchy as an extension section.
        """
        session = db or self._db
        product = self.get_product(product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        odps: Dict[str, Any] = {
            "kind": product.kind or "DataProduct",
            "apiVersion": product.api_version or "v1.0.0",
            "id": product.id,
            "status": product.status,
        }

        if product.name:
            odps["name"] = product.name
        if product.version:
            odps["version"] = product.version
        if product.domain:
            odps["domain"] = product.domain
        if product.tenant:
            odps["tenant"] = product.tenant

        if product.description:
            desc: Dict[str, Any] = {}
            if product.description.purpose:
                desc["purpose"] = product.description.purpose
            if product.description.usage:
                desc["usage"] = product.description.usage
            if product.description.limitations:
                desc["limitations"] = product.description.limitations
            if desc:
                odps["description"] = desc

        if product.input_ports:
            odps["inputPorts"] = [
                {k: v for k, v in {
                    "name": p.name, "version": p.version,
                    "contractId": p.contract_id,
                }.items() if v}
                for p in product.input_ports
            ]

        if product.output_ports:
            odps["outputPorts"] = [
                {k: v for k, v in {
                    "name": p.name, "version": p.version,
                    "contractId": p.contract_id,
                    "status": p.status,
                }.items() if v}
                for p in product.output_ports
            ]

        if product.support_channels:
            odps["support"] = [
                {k: v for k, v in {
                    "channel": s.channel, "url": s.url,
                    "tool": s.tool, "scope": s.scope,
                }.items() if v}
                for s in product.support_channels
            ]

        if product.team and product.team.members:
            odps["team"] = {
                "name": product.team.name,
                "members": [
                    {k: v for k, v in {
                        "username": m.username, "role": m.role,
                    }.items() if v}
                    for m in product.team.members
                ],
            }

        if product.custom_properties:
            odps["customProperties"] = [
                {"property": cp.property, "value": cp.value}
                for cp in product.custom_properties
            ]

        if product.authoritative_definitions:
            odps["authoritativeDefinitions"] = [
                {"url": ad.url, "type": ad.type}
                for ad in product.authoritative_definitions
            ]

        # Extension: include entity relationship-based dataset hierarchy
        try:
            hierarchy = self.get_product_hierarchy(product_id, db=session)
            if hierarchy.get("datasets"):
                datasets_export = []
                for ds in hierarchy["datasets"]:
                    ds_export: Dict[str, Any] = {
                        "name": ds["name"],
                        "status": ds.get("status"),
                    }
                    if ds.get("contract"):
                        ds_export["contractId"] = ds["contract"]["id"]
                    if ds.get("tables"):
                        ds_export["tables"] = [
                            {"name": t["name"], "location": t.get("location")}
                            for t in ds["tables"]
                        ]
                    if ds.get("views"):
                        ds_export["views"] = [
                            {"name": v["name"], "location": v.get("location")}
                            for v in ds["views"]
                        ]
                    datasets_export.append(ds_export)
                odps["datasets"] = datasets_export
        except Exception as e:
            logger.warning(f"Failed to include dataset hierarchy in ODPS export: {e}")

        return odps

    def link_dataset(
        self,
        product_id: str,
        dataset_asset_id: str,
        current_user: str,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Link a Dataset asset to this product via hasDataset relationship."""
        from src.db_models.entity_relationships import EntityRelationshipDb

        session = db or self._db
        product = self.get_product(product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")

        ds_asset = asset_repo.get(session, dataset_asset_id)
        if not ds_asset:
            raise ValueError(f"Dataset asset {dataset_asset_id} not found")

        existing = entity_relationship_repo.find_existing(
            session,
            source_type="DataProduct",
            source_id=product_id,
            target_type="Dataset",
            target_id=dataset_asset_id,
            relationship_type="hasDataset",
        )
        if existing:
            raise ValueError("Dataset is already linked to this product")

        rel = EntityRelationshipDb(
            source_type="DataProduct",
            source_id=product_id,
            target_type="Dataset",
            target_id=dataset_asset_id,
            relationship_type="hasDataset",
            created_by=current_user,
        )
        session.add(rel)
        session.commit()
        session.refresh(rel)

        return {
            "relationship_id": str(rel.id),
            "dataset_id": dataset_asset_id,
            "dataset_name": ds_asset.name,
        }

    def unlink_dataset(
        self,
        product_id: str,
        dataset_asset_id: str,
        db: Optional[Session] = None,
    ) -> bool:
        """Remove a hasDataset relationship between a product and a dataset."""
        session = db or self._db
        existing = entity_relationship_repo.find_existing(
            session,
            source_type="DataProduct",
            source_id=product_id,
            target_type="Dataset",
            target_id=dataset_asset_id,
            relationship_type="hasDataset",
        )
        if not existing:
            return False
        session.delete(existing)
        session.commit()
        return True

    def get_team_members_for_import(
        self,
        product_id: str,
        team_id: str,
        current_user: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get team members formatted for import into product ODPS team array.
        
        Business logic:
        - Validates product exists and user has access
        - Fetches team and validates it exists
        - Maps team members to ODPS-compatible format
        - Enriches with suggested roles from app_role_override
        
        Args:
            product_id: Data product ID
            team_id: Team ID to fetch members from
            current_user: Optional username for authorization
            
        Returns:
            List of dicts with member info: [{
                'member_identifier': str,
                'member_name': str,
                'member_type': str,
                'suggested_role': str
            }]
            
        Raises:
            ValueError: If product or team not found
        """
        # Validate product exists
        product = self.get_product(product_id)
        if not product:
            raise ValueError(f"Product {product_id} not found")
        
        # Fetch team with members
        team = team_repo.get_with_members(self._db, id=team_id)
        if not team:
            raise ValueError(f"Team {team_id} not found")
        
        # Map team members to ODPS-compatible format
        result = []
        for member in team.members:
            # Use app_role_override if set, otherwise suggest a default role
            suggested_role = member.app_role_override or "team_member"
            
            result.append({
                'member_identifier': member.member_identifier,
                'member_name': member.member_identifier,  # Will be same as identifier; UI can enhance
                'member_type': member.member_type,  # 'user' or 'group'
                'suggested_role': suggested_role,
            })
        
        logger.info(f"Retrieved {len(result)} team members from team {team_id} for product {product_id} import")
        return result

    def compare_products(self, old_product: Dict, new_product: Dict) -> Dict:
        """
        Compare two product versions and analyze changes.
        
        Args:
            old_product: Previous version (dict representation)
            new_product: New version (dict representation)
            
        Returns:
            Dict with change analysis results
        """
        from src.utils.product_change_analyzer import ProductChangeAnalyzer
        
        analyzer = ProductChangeAnalyzer()
        result = analyzer.analyze(old_product, new_product)
        
        return {
            'change_type': result.change_type.value,
            'version_bump': result.version_bump,
            'summary': result.summary,
            'breaking_changes': result.breaking_changes,
            'new_features': result.new_features,
            'fixes': result.fixes,
            'port_changes': [
                {
                    'change_type': pc.change_type,
                    'port_type': pc.port_type,
                    'port_name': pc.port_name,
                    'field_name': pc.field_name,
                    'old_value': pc.old_value,
                    'new_value': pc.new_value,
                    'severity': pc.severity.value
                }
                for pc in result.port_changes
            ],
            'team_changes': result.team_changes,
            'support_changes': result.support_changes
        }

    def analyze_update_impact(
        self,
        product_id: str,
        proposed_changes: Dict,
        db: Optional[Session] = None
    ) -> Dict:
        """
        Analyze the impact of proposed changes to a product.
        
        Classifies changes as metadata vs child entities and determines
        if versioning is required based on breaking changes.
        
        Args:
            product_id: ID of product being updated
            proposed_changes: Dict with proposed field changes
            db: Optional database session (uses self.db if not provided)
            
        Returns:
            Dict with analysis results:
            {
                'requires_versioning': bool,
                'change_analysis': {...},
                'recommended_action': 'clone' | 'update_in_place',
                'metadata_changes': List[str],
                'child_entity_changes': List[str]
            }
        """
        session = db or self.db
        
        # Fetch current product
        current_product_db = data_product_repo.get(session, id=product_id)
        if not current_product_db:
            raise ValueError(f"Product {product_id} not found")
        
        # Convert current DB model to dict for comparison
        current_product_dict = self._product_db_to_dict(current_product_db)
        
        # Run change analysis
        analysis = self.compare_products(current_product_dict, proposed_changes)
        
        # Classify changes
        metadata_changes = []
        child_entity_changes = []
        
        # Metadata fields (top-level, non-nested)
        metadata_fields = ['name', 'version', 'status', 'domain', 'tenant']
        for field in metadata_fields:
            if field in proposed_changes and proposed_changes.get(field) != current_product_dict.get(field):
                metadata_changes.append(field)
        
        # Child entity changes (nested structures)
        child_entity_fields = ['inputPorts', 'outputPorts', 'managementPorts', 'team', 'support', 'description']
        for field in child_entity_fields:
            if field in proposed_changes and proposed_changes.get(field) != current_product_dict.get(field):
                child_entity_changes.append(field)
        
        # Determine if versioning is required
        has_breaking_changes = len(analysis['breaking_changes']) > 0
        requires_versioning = has_breaking_changes
        
        return {
            'requires_versioning': requires_versioning,
            'change_analysis': analysis,
            'recommended_action': 'clone' if has_breaking_changes else 'update_in_place',
            'metadata_changes': metadata_changes,
            'child_entity_changes': child_entity_changes
        }

    def _product_db_to_dict(self, product_db) -> Dict:
        """
        Convert product DB model to dict for comparison.
        
        Args:
            product_db: DataProductDb instance
            
        Returns:
            Dict representation of product
        """
        # Use the existing get_product logic which returns API model
        product_api = self.get_product(product_db.id)
        if product_api:
            return product_api.model_dump(by_alias=True)
        return {}

    # ==================== Subscription Methods ====================

    def subscribe(
        self,
        product_id: str,
        subscriber_email: str,
        reason: Optional[str] = None,
        on_behalf_of: Optional[OnBehalfOf] = None,
        db: Optional[Session] = None
    ) -> SubscriptionResponse:
        """
        Subscribe a user to a data product.

        Args:
            product_id: ID of the product to subscribe to
            subscriber_email: Email of the subscriber
            reason: Optional reason for subscribing
            on_behalf_of: Optional principal that the subscription is for
                (). When set, ``type`` ∈ {user, group,
                service_principal} and ``value`` is validated against the
                workspace SCIM directory for non-user types. ``user`` accepts
                arbitrary strings to cover new hires not yet indexed.
            db: Optional database session

        Returns:
            SubscriptionResponse with subscription details

        Raises:
            ValueError: If product not found, not in subscribable status, or
                ``on_behalf_of`` references an unknown group / SP.
        """
        db_session = db if db is not None else self._db
        if on_behalf_of:
            logger.info(
                "User %s subscribing to product %s on behalf of %s '%s'",
                subscriber_email, product_id, on_behalf_of.type, on_behalf_of.value,
            )
        else:
            logger.info(f"User {subscriber_email} subscribing to product {product_id}")

        try:
            # Validate product exists and is subscribable
            product = self.get_product(product_id)
            if not product:
                raise ValueError(f"Product {product_id} not found")

            # Check if product is in a subscribable status
            subscribable_statuses = ['active', 'certified']
            if product.status and product.status.lower() not in subscribable_statuses:
                raise ValueError(
                    f"Cannot subscribe to product in status '{product.status}'. "
                    f"Product must be in one of: {', '.join(subscribable_statuses)}"
                )

            # Validate on_behalf_of principal exists in workspace SCIM (groups,
            # service principals). User type is intentionally not validated —
            # covers new hires not yet indexed (explicit ask).
            if on_behalf_of and on_behalf_of.type in ('group', 'service_principal'):
                self._validate_on_behalf_of_principal(on_behalf_of)

            # Check if already subscribed
            existing = subscription_repo.get_by_product_and_user(
                db_session,
                product_id=product_id,
                subscriber_email=subscriber_email
            )

            if existing:
                logger.info(f"User {subscriber_email} already subscribed to product {product_id}")
                response = SubscriptionResponse(
                    subscribed=True,
                    subscription=Subscription.model_validate(existing)
                )
                # Fire on_subscribe trigger even for the duplicate path so all
                # subscribe call sites consistently surface the event (matches
                # the prior route-handler behavior that fired regardless of
                # new vs. duplicate). See _fire_on_subscribe_trigger.
                self._fire_on_subscribe_trigger(
                    db_session=db_session,
                    product=product,
                    product_id=product_id,
                    subscriber_email=subscriber_email,
                    reason=reason,
                    on_behalf_of=on_behalf_of,
                    subscription_id=getattr(existing, 'id', None),
                )
                return response

            # Create subscription
            subscription_db = subscription_repo.create(
                db_session,
                product_id=product_id,
                subscriber_email=subscriber_email,
                reason=reason,
                on_behalf_of_type=on_behalf_of.type if on_behalf_of else None,
                on_behalf_of_value=on_behalf_of.value if on_behalf_of else None,
            )

            # Log to change log for audit
            self._log_subscription_change(
                db_session,
                product_id=product_id,
                subscriber_email=subscriber_email,
                action="SUBSCRIBE",
                reason=reason
            )

            db_session.commit()

            logger.info(f"User {subscriber_email} subscribed to product {product_id}")
            response = SubscriptionResponse(
                subscribed=True,
                subscription=Subscription.model_validate(subscription_db)
            )
            # Fire on_subscribe trigger after successful persistence (Option A:
            # moved from the route handler so the wizard auto-subscribe path
            # — agreement_wizard_manager._complete_session → dp_manager.subscribe
            # — also fires it. Wrapped in try/except inside the helper so a
            # transient trigger error does not break the subscribe response.
            self._fire_on_subscribe_trigger(
                db_session=db_session,
                product=product,
                product_id=product_id,
                subscriber_email=subscriber_email,
                reason=reason,
                on_behalf_of=on_behalf_of,
                subscription_id=getattr(subscription_db, 'id', None),
            )
            return response

        except ValueError as e:
            logger.error(f"Validation error subscribing to product {product_id}: {e}")
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error subscribing to product {product_id}: {e}")
            db_session.rollback()
            raise

    # ------------------------------------------------------------------
    # on_subscribe trigger firing (Option A — moved from route handler)
    # ------------------------------------------------------------------
    def _fire_on_subscribe_trigger(
        self,
        *,
        db_session: Session,
        product: Any,
        product_id: str,
        subscriber_email: str,
        reason: Optional[str],
        on_behalf_of: Optional[OnBehalfOf],
        subscription_id: Optional[Any],
    ) -> None:
        """Fire the on_subscribe workflow trigger.

        Centralized here so every subscribe call site (route handler + wizard
        auto-subscribe via agreement_wizard_manager._complete_session +
        any future caller) consistently fires the trigger. Previously this
        lived in data_product_routes.subscribe_to_product, which meant the
        wizard path silently bypassed the trigger.

        Builds the entity_data payload that the executor flattens into
        StepContext (.on_behalf_of for ${context.on_behalf_of.value} in
        webhook bodies / grant_permissions principals; .consumer_principals
        for ${entity.consumer_principals}).

        Wrapped in try/except — a trigger fire failure must not break the
        subscribe response.
        """
        try:
            from src.common.workflow_triggers import fire_trigger_safe
            from src.models.process_workflows import EntityType

            entity_data: Dict[str, Any] = {
                "product_id": product_id,
                "subscriber_email": subscriber_email,
                "reason": reason,
            }
            if on_behalf_of:
                obo_dict: Dict[str, Any] = {
                    "type": on_behalf_of.type,
                    "value": on_behalf_of.value,
                }
                # Resolved display string for human-friendly templates
                if on_behalf_of.type == 'user':
                    obo_dict["display"] = on_behalf_of.value
                elif on_behalf_of.type == 'group':
                    obo_dict["display"] = f"Group: {on_behalf_of.value}"
                else:  # service_principal
                    obo_dict["display"] = f"SP: {on_behalf_of.value}"
                entity_data["on_behalf_of"] = obo_dict

            # Surface consumer_principals so workflow webhook bodies can pipe
            # them via ${entity.consumer_principals}. Each principal is dumped
            # to a plain {type, value} dict so _render_template_value's JSON
            # serializer produces a clean array of objects in the rendered
            # webhook body.
            principals = getattr(product, 'consumer_principals', None) if product is not None else None
            if principals:
                entity_data["consumer_principals"] = [
                    p.model_dump() if hasattr(p, 'model_dump') else p
                    for p in principals
                ]

            # Fire with entity_type=DATA_PRODUCT (NOT SUBSCRIPTION). Process
            # workflows register with entity_types=["data_product"] because
            # the docstring on TriggerRegistry.on_subscribe explicitly states
            # the type is "(dataset, data_product)" — i.e. the entity the
            # user is subscribing TO. The prior route-handler code used
            # EntityType.SUBSCRIPTION, which is why the cross-workflow E2E
            # never matched any workflow even on the route path. Using
            # DATA_PRODUCT makes the on_subscribe trigger actually wire up
            # to the registered workflows. The entity_id is the product id
            # so workflows can resolve ${entity.product_id} consistently.
            fire_trigger_safe(
                db_session, "on_subscribe",
                entity_type=EntityType.DATA_PRODUCT,
                entity_id=product_id,
                entity_name=product_id,
                entity_data=entity_data,
                user_email=subscriber_email,
            )
        except Exception as e:
            # Non-fatal — never break the subscribe response on trigger errors.
            logger.warning("on_subscribe trigger fire failed (non-fatal): %s", e)

    # ------------------------------------------------------------------
    # on_behalf_of validation
    # ------------------------------------------------------------------
    def _validate_on_behalf_of_principal(self, on_behalf_of: OnBehalfOf) -> None:
        """Look up the principal in the workspace SCIM directory.

        Raises ValueError (caller maps to HTTP 400) if not found. Underlying
        SDK calls go through ``CachingWorkspaceClient`` which already caches
        SCIM responses — no manager-side cache needed (per PR #315 review).
        """
        try:
            # Late import: workspace_client is heavyweight and may be mocked
            # in unit tests via dependency override.
            from src.common.workspace_client import get_workspace_client
            ws = get_workspace_client()
        except Exception as e:
            # Workspace client not available in dev / tests — skip validation
            # rather than reject. This mirrors how grant_permissions handles
            # missing SP credentials (see GrantPermissionsStepHandler).
            logger.warning(
                "on_behalf_of validation skipped (workspace client unavailable): %s", e,
            )
            return

        try:
            if on_behalf_of.type == 'group':
                # SCIM filter — exact displayName match
                results = list(ws.groups.list(filter=f'displayName eq "{on_behalf_of.value}"'))
            else:  # service_principal
                # Allow either applicationId or displayName
                results = list(ws.service_principals.list(
                    filter=f'displayName eq "{on_behalf_of.value}"'
                ))
                if not results:
                    results = list(ws.service_principals.list(
                        filter=f'applicationId eq "{on_behalf_of.value}"'
                    ))
            exists = bool(results)
        except Exception as e:
            logger.warning(
                "on_behalf_of SCIM lookup failed for %s '%s': %s — treating as not found",
                on_behalf_of.type, on_behalf_of.value, e,
            )
            exists = False

        if not exists:
            raise ValueError(
                f"{on_behalf_of.type} '{on_behalf_of.value}' not found in workspace directory"
            )

    def unsubscribe(
        self,
        product_id: str,
        subscriber_email: str,
        db: Optional[Session] = None
    ) -> SubscriptionResponse:
        """
        Unsubscribe a user from a data product.
        
        Args:
            product_id: ID of the product to unsubscribe from
            subscriber_email: Email of the subscriber
            db: Optional database session
            
        Returns:
            SubscriptionResponse indicating unsubscribed
        """
        db_session = db if db is not None else self._db
        logger.info(f"User {subscriber_email} unsubscribing from product {product_id}")
        
        try:
            deleted = subscription_repo.delete_by_product_and_user(
                db_session,
                product_id=product_id,
                subscriber_email=subscriber_email
            )
            
            if deleted:
                # Log to change log for audit
                self._log_subscription_change(
                    db_session,
                    product_id=product_id,
                    subscriber_email=subscriber_email,
                    action="UNSUBSCRIBE"
                )
                db_session.commit()
                logger.info(f"User {subscriber_email} unsubscribed from product {product_id}")
            else:
                logger.info(f"User {subscriber_email} was not subscribed to product {product_id}")
            
            return SubscriptionResponse(subscribed=False, subscription=None)
            
        except SQLAlchemyError as e:
            logger.error(f"Database error unsubscribing from product {product_id}: {e}")
            db_session.rollback()
            raise

    def get_subscription_status(
        self,
        product_id: str,
        subscriber_email: str,
        db: Optional[Session] = None
    ) -> SubscriptionResponse:
        """
        Check if a user is subscribed to a product.
        
        Args:
            product_id: ID of the product
            subscriber_email: Email of the user
            db: Optional database session
            
        Returns:
            SubscriptionResponse with subscription status
        """
        db_session = db if db is not None else self._db
        
        subscription = subscription_repo.get_by_product_and_user(
            db_session,
            product_id=product_id,
            subscriber_email=subscriber_email
        )
        
        if subscription:
            return SubscriptionResponse(
                subscribed=True,
                subscription=Subscription.model_validate(subscription)
            )
        return SubscriptionResponse(subscribed=False, subscription=None)

    def get_subscribers(
        self,
        product_id: str,
        skip: int = 0,
        limit: int = 100,
        db: Optional[Session] = None
    ) -> SubscribersListResponse:
        """
        Get all subscribers for a product.
        
        Args:
            product_id: ID of the product
            skip: Number of records to skip
            limit: Maximum number of records to return
            db: Optional database session
            
        Returns:
            SubscribersListResponse with subscriber information
        """
        db_session = db if db is not None else self._db
        logger.debug(f"Fetching subscribers for product {product_id}")
        
        subscriptions = subscription_repo.get_subscribers_for_product(
            db_session,
            product_id=product_id,
            skip=skip,
            limit=limit
        )
        
        count = subscription_repo.count_subscribers_for_product(
            db_session,
            product_id=product_id
        )
        
        subscribers = [
            SubscriberInfo(
                email=sub.subscriber_email,
                subscribed_at=sub.subscribed_at,
                reason=sub.subscription_reason
            )
            for sub in subscriptions
        ]
        
        return SubscribersListResponse(
            product_id=product_id,
            subscriber_count=count,
            subscribers=subscribers
        )

    def get_user_subscriptions(
        self,
        subscriber_email: str,
        skip: int = 0,
        limit: int = 100,
        db: Optional[Session] = None
    ) -> List[DataProductApi]:
        """
        Get all products a user is subscribed to.
        
        Args:
            subscriber_email: Email of the subscriber
            skip: Number of records to skip
            limit: Maximum number of records to return
            db: Optional database session
            
        Returns:
            List of DataProduct API models the user is subscribed to
        """
        db_session = db if db is not None else self._db
        logger.debug(f"Fetching subscriptions for user {subscriber_email}")
        
        # Get product IDs the user is subscribed to
        product_ids = subscription_repo.get_product_ids_for_user(
            db_session,
            subscriber_email=subscriber_email
        )
        
        if not product_ids:
            return []
        
        # Fetch the actual products with pagination
        products = []
        for pid in product_ids[skip:skip + limit]:
            product = self.get_product(pid)
            if product:
                products.append(product)
        
        return products

    def get_subscriber_count(self, product_id: str, db: Optional[Session] = None) -> int:
        """Get the number of subscribers for a product."""
        db_session = db if db is not None else self._db
        return subscription_repo.count_subscribers_for_product(
            db_session,
            product_id=product_id
        )

    def notify_subscribers(
        self,
        product_id: str,
        title: str,
        description: str,
        notification_type: str = "INFO",
        link: Optional[str] = None,
        db: Optional[Session] = None
    ) -> int:
        """
        Send a notification to all subscribers of a product.
        
        Args:
            product_id: ID of the product
            title: Notification title
            description: Notification description
            notification_type: Type of notification (INFO, WARNING, ACTION_REQUIRED)
            link: Optional link to include
            db: Optional database session
            
        Returns:
            Number of notifications sent
        """
        if not self._notifications_manager:
            logger.warning("NotificationsManager not available, cannot notify subscribers")
            return 0
        
        db_session = db if db is not None else self._db
        
        # Get all subscriber emails
        subscriber_emails = subscription_repo.get_subscriber_emails_for_product(
            db_session,
            product_id=product_id
        )
        
        if not subscriber_emails:
            logger.debug(f"No subscribers to notify for product {product_id}")
            return 0
        
        from src.models.notifications import NotificationType, Notification
        
        # Map string to enum
        type_map = {
            "INFO": NotificationType.INFO,
            "WARNING": NotificationType.WARNING,
            "ACTION_REQUIRED": NotificationType.ACTION_REQUIRED,
            "SUCCESS": NotificationType.SUCCESS,
            "ERROR": NotificationType.ERROR
        }
        notif_type = type_map.get(notification_type.upper(), NotificationType.INFO)
        
        notifications_sent = 0
        for email in subscriber_emails:
            try:
                notification = Notification(
                    id=str(uuid.uuid4()),
                    created_at=datetime.utcnow(),
                    type=notif_type,
                    title=title,
                    description=description,
                    recipient=email,
                    link=link or f"/data-products/{product_id}",
                    can_delete=True
                )
                self._notifications_manager.create_notification(
                    notification=notification,
                    db=db_session
                )
                notifications_sent += 1
            except Exception as e:
                logger.error(f"Failed to send notification to {email}: {e}")
        
        logger.info(f"Sent {notifications_sent} notifications for product {product_id}")
        return notifications_sent

    def _log_subscription_change(
        self,
        db: Session,
        product_id: str,
        subscriber_email: str,
        action: str,
        reason: Optional[str] = None
    ) -> None:
        """
        Log subscription changes to the change log for audit purposes.
        
        Args:
            db: Database session
            product_id: ID of the product
            subscriber_email: Email of the subscriber
            action: Action type (SUBSCRIBE or UNSUBSCRIBE)
            reason: Optional reason for the action
        """
        try:
            from src.controller.change_log_manager import change_log_manager
            import json
            
            details = {
                "subscriber_email": subscriber_email,
                "action": action,
                "timestamp": datetime.utcnow().isoformat()
            }
            if reason:
                details["reason"] = reason
            
            change_log_manager.log_change(
                db,
                entity_type="data_product",
                entity_id=product_id,
                action=action,
                username=subscriber_email,
                details_json=json.dumps(details)
            )
            logger.debug(f"Logged subscription change: {action} for product {product_id}")
        except Exception as e:
            # Don't fail the subscription operation if logging fails
            logger.error(f"Failed to log subscription change: {e}")

    def _notify_subscribers_of_status_change(
        self,
        product_id: str,
        product_name: str,
        old_status: str,
        new_status: str
    ) -> None:
        """
        Notify subscribers when a product's status changes to a notable state.
        
        Subscribers are notified for:
        - Deprecation (deprecated status)
        - Retirement (retired status)
        - Activation (active status from non-active)
        - New certification (certified status)
        
        Args:
            product_id: ID of the product
            product_name: Name of the product
            old_status: Previous status
            new_status: New status
        """
        # Define which status changes warrant notifications
        notification_configs = {
            'deprecated': {
                'title': f"Product '{product_name}' has been deprecated",
                'description': (
                    f"The data product '{product_name}' has been marked as deprecated. "
                    "Please plan to migrate to an alternative product or contact the owner for more information."
                ),
                'notification_type': 'WARNING'
            },
            'retired': {
                'title': f"Product '{product_name}' has been retired",
                'description': (
                    f"The data product '{product_name}' has been retired and is no longer available. "
                    "If you were using this product, please migrate to an alternative immediately."
                ),
                'notification_type': 'ACTION_REQUIRED'
            },
            'active': {
                'title': f"Product '{product_name}' is now active",
                'description': (
                    f"The data product '{product_name}' has been activated and is now available for use."
                ),
                'notification_type': 'INFO'
            },
            'certified': {
                'title': f"Product '{product_name}' has been certified",
                'description': (
                    f"The data product '{product_name}' has achieved certified status, "
                    "indicating it meets all quality and compliance requirements."
                ),
                'notification_type': 'SUCCESS'
            }
        }
        
        # Check if this status change warrants notification
        config = notification_configs.get(new_status)
        if not config:
            logger.debug(f"No notification needed for status change to {new_status}")
            return
        
        try:
            count = self.notify_subscribers(
                product_id=product_id,
                title=config['title'],
                description=config['description'],
                notification_type=config['notification_type'],
                link=f"/data-products/{product_id}"
            )
            logger.info(
                f"Notified {count} subscribers about product {product_id} status change "
                f"({old_status} → {new_status})"
            )
        except Exception as e:
            # Don't fail the status transition if notification fails
            logger.error(f"Failed to notify subscribers of status change: {e}")
