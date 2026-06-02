import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from pydantic import ValidationError, parse_obj_as
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

# Import Databricks SDK components
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import TableInfo, FunctionInfo, SchemaInfo, CatalogInfo, TableType
from databricks.sdk.errors import NotFound, PermissionDenied, DatabricksError
import os
# from openai import OpenAI # Removed OpenAI client
# NOTE: Avoid importing MLflow at module import time to prevent optional
# dependency issues during app startup. We'll import lazily when needed.

# Import API models
from src.models.data_asset_reviews import (
    DataAssetReviewRequest as DataAssetReviewRequestApi,
    DataAssetReviewRequestCreate,
    DataAssetReviewRequestUpdate,
    DataAssetReviewRequestUpdateStatus,
    ReviewedAsset as ReviewedAssetApi,
    ReviewedAssetUpdate,
    ReviewRequestStatus, ReviewedAssetStatus, AssetType,
    AssetAnalysisRequest, AssetAnalysisResponse # Added LLM models
)
# Import Repository
from src.repositories.data_asset_reviews_repository import data_asset_review_repo

# Import Notification Manager (Assuming NotificationsManager is in this path)
from src.controller.notifications_manager import NotificationsManager
# Import correct enum from notifications model
from src.models.notifications import Notification, NotificationType

# Import Search Interfaces
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
# Import the registry decorator
from src.common.search_registry import searchable_asset

from src.common.config import Settings, get_settings # Added Settings and get_settings
from src.common.sanitization import sanitize_markdown_input # Import shared sanitization function

from src.common.logging import get_logger
logger = get_logger(__name__)


def _short_asset_label(fqn: Optional[str]) -> str:
    """Return a compact human-readable label for an asset FQN.

    - UC objects (``catalog.schema.object``) → last segment (``object``).
    - Notebook / volume paths → final path segment.
    - ``mdm://config/run/candidate`` → ``candidate``.
    - Otherwise → the FQN unchanged.
    """
    if not fqn:
        return "asset"
    if fqn.startswith("mdm://"):
        tail = fqn[len("mdm://"):].rstrip("/")
        last = tail.rsplit("/", 1)[-1] if tail else ""
        return last or "MDM match"
    if "/" in fqn:
        last = fqn.rstrip("/").rsplit("/", 1)[-1]
        return last or fqn
    return fqn.split(".")[-1] or fqn


def derive_review_title(review: Any) -> str:
    """Compute a human-readable title for a review request.

    Uses the user-set ``title`` when present (and non-empty); otherwise derives a
    label from the request contents. Accepts either a Pydantic API model or a
    SQLAlchemy DB row — anything with ``title``, ``requester_email``, and an
    ``assets`` iterable of objects exposing ``asset_fqn``.
    """
    raw_title = getattr(review, "title", None)
    if isinstance(raw_title, str) and raw_title.strip():
        return raw_title.strip()

    assets = list(getattr(review, "assets", None) or [])
    requester = getattr(review, "requester_email", None) or ""

    if len(assets) == 1:
        return f"Review of {_short_asset_label(getattr(assets[0], 'asset_fqn', None))}"
    if len(assets) > 1:
        first_label = _short_asset_label(getattr(assets[0], "asset_fqn", None))
        return f"Review of {first_label} (+{len(assets) - 1} more)"
    if requester:
        return f"Review request by {requester}"
    return "Review request"


@searchable_asset # Register this manager with the search system
class DataAssetReviewManager(SearchableAsset): # Inherit from SearchableAsset
    def __init__(self, db: Session, ws_client: WorkspaceClient, notifications_manager: NotificationsManager):
        """
        Initializes the DataAssetReviewManager.

        Args:
            db: SQLAlchemy Session for database operations.
            ws_client: Databricks WorkspaceClient for SDK operations.
            notifications_manager: Manager for creating notifications.
        """
        self._db = db
        self._ws_client = ws_client
        self._repo = data_asset_review_repo
        self._notifications_manager = notifications_manager
        if not self._ws_client:
             logger.warning("WorkspaceClient was not provided to DataAssetReviewManager. SDK operations will fail.")

    def _determine_asset_type(self, fqn: str) -> AssetType:
        """Tries to determine the asset type using the Databricks SDK."""
        # Handle special protocol-based FQNs
        if fqn.startswith('mdm://'):
            return AssetType.MDM_MATCH
        if fqn.startswith('term-mapping://'):
            return AssetType.CONCEPT_MAPPING_SUGGESTION

        if not self._ws_client:
            logger.warning(f"Cannot determine asset type for {fqn}: WorkspaceClient not available.")
            # Default or raise error? For now, default to TABLE as a fallback.
            return AssetType.TABLE

        parts = fqn.split('.')
        if len(parts) != 3:
            logger.warning(f"Invalid FQN format for asset type determination: {fqn}. Defaulting to TABLE.")
            return AssetType.TABLE
        
        catalog_name, schema_name, object_name = parts

        try:
            # Try fetching as Table first (most common)
            try:
                table_info = self._ws_client.tables.get(full_name=fqn)
                if table_info.table_type == TableType.VIEW or table_info.table_type == TableType.MATERIALIZED_VIEW:
                    return AssetType.VIEW
                else:
                    return AssetType.TABLE
            except DatabricksError as e:
                # If not found or permission denied as table, try function
                if "NOT_FOUND" not in str(e) and "PERMISSION_DENIED" not in str(e):
                    raise # Re-raise unexpected errors
            
            # Try fetching as Function
            try:
                self._ws_client.functions.get(name=fqn)
                return AssetType.FUNCTION
            except DatabricksError as e:
                if "NOT_FOUND" not in str(e) and "PERMISSION_DENIED" not in str(e):
                     raise

            # Try fetching as Model (assuming registered models have FQN like catalog.schema.model_name)
            try:
                # Note: This might need adjustment based on how models are registered and accessed.
                # The Python SDK might have a dedicated function for models.
                # For now, assuming a hypothetical `get_model` exists or it falls under tables/functions.
                # If a dedicated model client exists, use that.
                # Example: self._ws_client.models.get(name=fqn)
                # If it doesn't exist, we might need more info or skip model detection.
                pass # Placeholder for model check
            except DatabricksError as e:
                 if "NOT_FOUND" not in str(e) and "PERMISSION_DENIED" not in str(e):
                    raise
            
            logger.warning(f"Could not determine asset type for FQN: {fqn} using SDK checks. Defaulting to TABLE.")
            return AssetType.TABLE # Default if not found as table or function

        except PermissionDenied:
             logger.warning(f"Permission denied while trying to determine asset type for {fqn}. Defaulting to TABLE.")
             return AssetType.TABLE
        except Exception as e:
            logger.error(f"Unexpected SDK error determining asset type for {fqn}: {e}. Defaulting to TABLE.", exc_info=True)
            return AssetType.TABLE

    def create_review_request(self, request_data: DataAssetReviewRequestCreate, db: Optional[Session] = None) -> DataAssetReviewRequestApi:
        """Creates a new data asset review request.
        
        Args:
            request_data: The review request data
            db: Optional database session. If not provided, uses the manager's internal session.
        """
        # Use provided db session or fall back to instance session
        db_session = db if db is not None else self._db
        
        try:
            request_id = str(uuid.uuid4())
            assets_to_review: List[ReviewedAssetApi] = []
            processed_fqns = set() # Track processed FQNs to avoid duplicates

            for fqn in request_data.asset_fqns:
                if fqn in processed_fqns:
                    logger.warning(f"Duplicate FQN '{fqn}' in request, skipping.")
                    continue
                
                asset_type = self._determine_asset_type(fqn)
                assets_to_review.append(
                    ReviewedAssetApi(
                        id=str(uuid.uuid4()),
                        asset_fqn=fqn,
                        asset_type=asset_type,
                        status=ReviewedAssetStatus.PENDING, # Start as pending
                        updated_at=datetime.utcnow()
                    )
                )
                processed_fqns.add(fqn)
            
            if not assets_to_review:
                 raise ValueError("No valid or unique assets provided for review.")
                 
            # Normalize the user-supplied title: trim whitespace; treat blank as None.
            raw_title = (request_data.title or "").strip() if request_data.title else None
            normalized_title = raw_title if raw_title else None

            # Prepare the full API model for the repository
            full_request = DataAssetReviewRequestApi(
                id=request_id,
                requester_email=request_data.requester_email,
                reviewer_email=request_data.reviewer_email,
                title=normalized_title,
                status=ReviewRequestStatus.QUEUED,
                notes=request_data.notes,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                assets=assets_to_review
            )

            # Use the repository to create the request and its assets in DB
            created_db_obj = self._repo.create_with_assets(db=db_session, obj_in=full_request)

            # Convert DB object back to API model for response and ensure `title` is
            # always populated for downstream consumers (notifications, search, UI).
            created_api_obj = DataAssetReviewRequestApi.from_orm(created_db_obj)
            if not (created_api_obj.title and created_api_obj.title.strip()):
                created_api_obj.title = derive_review_title(created_api_obj)
            display_title = created_api_obj.title

            # --- Trigger workflow for review request --- #
            try:
                from src.common.workflow_triggers import get_trigger_registry
                from src.models.process_workflows import EntityType
                
                trigger_registry = get_trigger_registry(db_session)
                entity_data = {
                    "id": created_api_obj.id,
                    "requester_email": created_api_obj.requester_email,
                    "reviewer_email": created_api_obj.reviewer_email,
                    "status": created_api_obj.status.value,
                    "notes": created_api_obj.notes,
                    "asset_count": len(created_api_obj.assets),
                    "asset_fqns": [a.asset_fqn for a in created_api_obj.assets],
                }
                
                executions = trigger_registry.on_request_review(
                    entity_type=EntityType.DATA_ASSET_REVIEW,
                    entity_id=created_api_obj.id,
                    entity_name=display_title,
                    entity_data=entity_data,
                    user_email=created_api_obj.requester_email,
                    blocking=False,  # Don't block on notification workflows
                )
                
                if executions:
                    logger.info(f"Triggered {len(executions)} workflow(s) for review request {created_api_obj.id}")
                else:
                    # Fallback to direct notification if no workflow configured
                    notification = Notification(
                        id=str(uuid.uuid4()),
                        recipient=created_api_obj.reviewer_email,
                        title=f"New review request: {display_title}",
                        description=f"Assigned to you by {created_api_obj.requester_email}.",
                        type=NotificationType.INFO,
                        link=f"/data-asset-reviews/{created_api_obj.id}",
                        created_at=datetime.utcnow(),
                    )
                    self._notifications_manager.create_notification(notification)
                    logger.info(f"No workflow configured; sent direct notification to {created_api_obj.reviewer_email}")
            except Exception as workflow_err:
                # Log error but don't fail the request creation
                logger.error(f"Failed to trigger workflow for review request {created_api_obj.id}: {workflow_err}", exc_info=True)

            self._update_search_index(created_api_obj)
            return created_api_obj

        except SQLAlchemyError as e:
            logger.error(f"Database error creating review request: {e}")
            raise
        except ValidationError as e:
            logger.error(f"Validation error creating review request: {e}")
            raise ValueError(f"Invalid data for review request: {e}")
        except ValueError as e:
            logger.error(f"Value error creating review request: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating review request: {e}")
            raise

    def get_review_request(self, request_id: str) -> Optional[DataAssetReviewRequestApi]:
        """Gets a review request by its ID."""
        try:
            request_db = self._repo.get(db=self._db, id=request_id)
            if request_db:
                api_obj = DataAssetReviewRequestApi.from_orm(request_db)
                if not (api_obj.title and api_obj.title.strip()):
                    api_obj.title = derive_review_title(api_obj)
                return api_obj
            return None
        except SQLAlchemyError as e:
            logger.error(f"Database error getting review request {request_id}: {e}")
            raise
        except ValidationError as e:
            logger.error(f"Validation error mapping DB object for request {request_id}: {e}")
            raise ValueError(f"Internal data mapping error for request {request_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting review request {request_id}: {e}")
            raise

    def list_review_requests(self, skip: int = 0, limit: int = 100) -> List[DataAssetReviewRequestApi]:
        """Lists all review requests."""
        try:
            requests_db = self._repo.get_multi(db=self._db, skip=skip, limit=limit)
            # Use parse_obj_as for lists
            requests_api: List[DataAssetReviewRequestApi] = parse_obj_as(List[DataAssetReviewRequestApi], requests_db)
            for req in requests_api:
                if not (req.title and req.title.strip()):
                    req.title = derive_review_title(req)
            return requests_api
        except SQLAlchemyError as e:
            logger.error(f"Database error listing review requests: {e}")
            raise
        except ValidationError as e:
            logger.error(f"Validation error mapping list of DB objects for review requests: {e}")
            raise ValueError(f"Internal data mapping error during list: {e}")
        except Exception as e:
            logger.error(f"Unexpected error listing review requests: {e}")
            raise

    def update_review_request_status(self, request_id: str, update_data: DataAssetReviewRequestUpdateStatus) -> Optional[DataAssetReviewRequestApi]:
        """Updates the overall status of a review request."""
        try:
            db_obj = self._repo.get(db=self._db, id=request_id)
            if not db_obj:
                logger.warning(f"Attempted to update status for non-existent review request: {request_id}")
                return None
            
            from_status = db_obj.status.value if hasattr(db_obj.status, 'value') else str(db_obj.status)
            updated_db_obj = self._repo.update_request_status(db=self._db, db_obj=db_obj, status=update_data.status, notes=update_data.notes)
            to_status = updated_db_obj.status.value if hasattr(updated_db_obj.status, 'value') else str(updated_db_obj.status)
            
            # --- Trigger workflow for status change --- #
            final_statuses = [ReviewRequestStatus.APPROVED, ReviewRequestStatus.NEEDS_REVIEW, ReviewRequestStatus.DENIED]
            if updated_db_obj.status in final_statuses:
                try:
                    from src.common.workflow_triggers import get_trigger_registry
                    from src.models.process_workflows import EntityType, TriggerType
                    
                    trigger_registry = get_trigger_registry(self._db)
                    entity_data = {
                        "id": updated_db_obj.id,
                        "requester_email": updated_db_obj.requester_email,
                        "reviewer_email": updated_db_obj.reviewer_email,
                        "status": to_status,
                        "notes": update_data.notes,
                    }
                    
                    display_title = derive_review_title(updated_db_obj)

                    executions = trigger_registry.on_status_change(
                        entity_type=EntityType.DATA_ASSET_REVIEW,
                        entity_id=updated_db_obj.id,
                        from_status=from_status,
                        to_status=to_status,
                        entity_name=display_title,
                        entity_data=entity_data,
                        user_email=updated_db_obj.reviewer_email,
                        blocking=False,
                    )
                    
                    if executions:
                        logger.info(f"Triggered {len(executions)} workflow(s) for review status change {updated_db_obj.id}")
                    else:
                        # Fallback to direct notification if no workflow configured
                        notification_message = f"\"{display_title}\" status updated to {to_status} by {updated_db_obj.reviewer_email}."
                        notification_type = NotificationType.INFO if updated_db_obj.status == ReviewRequestStatus.APPROVED else NotificationType.WARNING

                        notification = Notification(
                            id=str(uuid.uuid4()),
                            user_email=updated_db_obj.requester_email,
                            title=f"Review {to_status.capitalize()}: {display_title}",
                            description=notification_message,
                            type=notification_type,
                            link=f"/data-asset-reviews/{updated_db_obj.id}"
                        )
                        self._notifications_manager.create_notification(notification)
                        logger.info(f"No workflow configured; sent direct notification to {updated_db_obj.requester_email}")
                except Exception as workflow_err:
                    logger.error(f"Failed to trigger workflow for review status update {updated_db_obj.id}: {workflow_err}", exc_info=True)
            
            result = DataAssetReviewRequestApi.from_orm(updated_db_obj)
            if not (result.title and result.title.strip()):
                result.title = derive_review_title(result)
            self._update_search_index(result)
            return result
        except SQLAlchemyError as e:
             logger.error(f"Database error updating status for request {request_id}: {e}")
             raise
        except ValidationError as e:
             logger.error(f"Validation error mapping updated DB object for request {request_id}: {e}")
             raise ValueError(f"Internal mapping error after update {request_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating status for request {request_id}: {e}")
            raise

    def update_review_request(
        self, request_id: str, update_data: DataAssetReviewRequestUpdate
    ) -> Optional[DataAssetReviewRequestApi]:
        """Updates editable fields (title, notes) on a review request.

        Returns ``None`` if the request does not exist.
        """
        try:
            db_obj = self._repo.get(db=self._db, id=request_id)
            if not db_obj:
                logger.warning(f"Attempted to update non-existent review request: {request_id}")
                return None

            payload = update_data.dict(exclude_unset=True)
            title_set = "title" in payload
            notes_set = "notes" in payload

            normalized_title: Optional[str] = None
            if title_set:
                raw = payload.get("title")
                if isinstance(raw, str):
                    raw = raw.strip()
                normalized_title = raw if raw else None

            updated_db_obj = self._repo.update_request_fields(
                db=self._db,
                db_obj=db_obj,
                title=normalized_title,
                notes=payload.get("notes") if notes_set else None,
                title_set=title_set,
                notes_set=notes_set,
            )

            api_obj = DataAssetReviewRequestApi.from_orm(updated_db_obj)
            if not (api_obj.title and api_obj.title.strip()):
                api_obj.title = derive_review_title(api_obj)
            self._update_search_index(api_obj)
            return api_obj
        except SQLAlchemyError as e:
            logger.error(f"Database error updating review request {request_id}: {e}")
            raise
        except ValidationError as e:
            logger.error(f"Validation error mapping updated review request {request_id}: {e}")
            raise ValueError(f"Internal mapping error after update {request_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating review request {request_id}: {e}")
            raise

    def update_reviewed_asset_status(self, request_id: str, asset_id: str, update_data: ReviewedAssetUpdate) -> Optional[ReviewedAssetApi]:
        """Updates the status and comments of a specific asset within a review."""
        try:
            db_asset_obj = self._repo.get_asset(db=self._db, request_id=request_id, asset_id=asset_id)
            if not db_asset_obj:
                logger.warning(f"Attempted to update non-existent asset {asset_id} in request {request_id}")
                return None
            
            updated_db_asset_obj = self._repo.update_asset_status(db=self._db, db_asset_obj=db_asset_obj, status=update_data.status, comments=update_data.comments)
            
            # TODO: Check if all assets are reviewed and potentially update overall request status?
            
            return ReviewedAssetApi.from_orm(updated_db_asset_obj)
        except SQLAlchemyError as e:
             logger.error(f"Database error updating asset {asset_id} status in request {request_id}: {e}")
             raise
        except ValidationError as e:
             logger.error(f"Validation error mapping updated DB asset {asset_id}: {e}")
             raise ValueError(f"Internal mapping error after asset update {asset_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating asset {asset_id} status: {e}")
            raise

    def update_asset_status_by_id(self, asset_id: str, status: ReviewedAssetStatus, db: Optional[Session] = None) -> bool:
        """Update the status of a reviewed asset by ID only.
        
        This is a simplified method for syncing status from external sources
        (e.g., MDM match candidate updates).
        
        Args:
            asset_id: The reviewed asset ID
            status: The new status
            db: Optional database session. If not provided, uses the manager's internal session.
            
        Returns:
            True if asset was found and updated, False otherwise
        """
        db_session = db if db is not None else self._db
        try:
            return self._repo.update_asset_status_by_id(db_session, asset_id, status)
        except SQLAlchemyError as e:
            logger.error(f"Database error updating asset {asset_id} status to {status}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error updating asset {asset_id} status to {status}: {e}")
            raise

    def delete_review_request(self, request_id: str) -> bool:
        """Deletes a review request and its associated assets."""
        try:
            deleted_obj = self._repo.remove(db=self._db, id=request_id)
            if deleted_obj is not None:
                self._notify_index_remove(f"review::{request_id}")
            return deleted_obj is not None
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting review request {request_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error deleting review request {request_id}: {e}")
            raise
    
    def get_reviewed_asset(self, request_id: str, asset_id: str) -> Optional[ReviewedAssetApi]:
        """Gets a specific reviewed asset by its ID and its parent request ID."""
        try:
            asset_db = self._repo.get_asset(db=self._db, request_id=request_id, asset_id=asset_id)
            if asset_db:
                return ReviewedAssetApi.from_orm(asset_db)
            return None
        except SQLAlchemyError as e:
            logger.error(f"Database error getting reviewed asset {asset_id} for request {request_id}: {e}")
            raise
        except ValidationError as e:
            logger.error(f"Validation error mapping DB object for asset {asset_id}: {e}")
            raise ValueError(f"Internal data mapping error for asset {asset_id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting reviewed asset {asset_id}: {e}")
            raise
    
    def analyze_asset_content(self, request_id: str, asset_id: str, asset_content: str, asset_type: AssetType, user_token: Optional[str] = None) -> Optional[AssetAnalysisResponse]:
        """
        Analyzes asset content using LLM with two-phased security verification.

        Phase 1: Security check for injection attempts
        Phase 2: Content analysis with configured prompt (only if phase 1 passes)

        Args:
            request_id: Review request ID
            asset_id: Asset ID within the request
            asset_content: Content to analyze
            asset_type: Type of asset
            user_token: Per-user access token from x-forwarded-access-token header (Databricks Apps)
        """
        try:
            # Import LLM service
            from src.common.llm_service import get_llm_service

            llm_service = get_llm_service()

            # Check if LLM is enabled
            if not llm_service.is_enabled():
                logger.warning("LLM analysis requested but LLM is disabled in settings")
                return None

            logger.info(f"Analyzing asset {asset_id} (type: {asset_type.value}) content with LLM (two-phased)")

            # Call the two-phased analysis with user token
            result = llm_service.analyze_content(asset_content, user_token=user_token)

            if not result.success and not result.phase1_passed:
                # Phase 1 failed - return with security warning
                # The result.content contains the security warning message
                logger.warning(f"Phase 1 security check failed for asset {asset_id}: {result.error_message}")
                return AssetAnalysisResponse(
                    request_id=request_id,
                    asset_id=asset_id,
                    analysis_summary=sanitize_markdown_input(result.content),  # Sanitize security warning
                    llm_model_used=result.llm_model_used,
                    timestamp=result.timestamp,
                    phase1_passed=False,
                    render_as_markdown=False  # Must display as plain text
                )

            if not result.success:
                # Phase 2 failed or other error
                logger.error(f"LLM analysis failed for asset {asset_id}: {result.error_message}")
                return None

            # Success: Both phases passed
            logger.info(f"LLM analysis successful for asset {asset_id} (both phases passed)")
            return AssetAnalysisResponse(
                request_id=request_id,
                asset_id=asset_id,
                analysis_summary=sanitize_markdown_input(result.content),  # Sanitize LLM output
                llm_model_used=result.llm_model_used,
                timestamp=result.timestamp,
                phase1_passed=True,
                render_as_markdown=True  # Safe to render as markdown
            )

        except Exception as e:
            logger.error(f"Error during LLM analysis for asset {asset_id} (request {request_id}): {e}", exc_info=True)
            return None

    # Add methods for getting asset content (text/data preview) using ws_client
    async def get_asset_definition(self, asset_fqn: str, asset_type: AssetType) -> Optional[str]:
        """Fetches the definition (e.g., SQL) for a view or function."""
        settings: Settings = get_settings()
        is_demo_mode = settings.APP_DEMO_MODE

        def _load_sample_from_file(sample_filename: str) -> Optional[str]:
            try:
                base_dir = Path(__file__).parent.parent # api/
                file_path = base_dir / "data" / sample_filename
                if file_path.is_file():
                    return file_path.read_text()
                else:
                    logger.warning(f"Sample data file not found: {file_path}")
                    return None
            except Exception as e:
                logger.error(f"Error loading sample data file {sample_filename}: {e}", exc_info=True)
                return None

        def _try_load_sample_for_demo(current_asset_type: AssetType, current_asset_fqn: str, reason_for_fallback: str) -> Optional[str]:
            """Attempts to load sample content if in demo mode, logs appropriately."""
            if is_demo_mode:
                logger.info(f"{reason_for_fallback} for asset {current_asset_fqn} (type: {current_asset_type.value}). In demo mode, attempting to load sample content.")
                sample_filename = None
                if current_asset_type == AssetType.VIEW:
                    sample_filename = "sample_view_definition.sql"
                elif current_asset_type == AssetType.FUNCTION:
                    sample_filename = "sample_function_definition.py"
                elif current_asset_type == AssetType.NOTEBOOK:
                    sample_filename = "sample_notebook_definition.py"
                
                if sample_filename:
                    sample_content = _load_sample_from_file(sample_filename)
                    if sample_content:
                        logger.info(f"Returning sample content for {current_asset_type.value} {current_asset_fqn}.")
                        return sample_content
                    else:
                        logger.warning(f"Failed to load sample content from {sample_filename} for {current_asset_type.value} {current_asset_fqn} after {reason_for_fallback}.")
                else:
                    logger.warning(f"No sample file defined for asset type {current_asset_type.value} during fallback for {current_asset_fqn}.")
            else:
                logger.info(f"{reason_for_fallback} for asset {current_asset_fqn} (type: {current_asset_type.value}). Not in demo mode, so no sample will be loaded.")
            return None

        if not self._ws_client:
            logger.warning(f"Cannot fetch definition for {asset_fqn}: WorkspaceClient not available.")
            return _try_load_sample_for_demo(asset_type, asset_fqn, "WorkspaceClient not available")
            
        if asset_type not in [AssetType.VIEW, AssetType.FUNCTION, AssetType.NOTEBOOK]:
            logger.info(f"Definition fetch only supported for VIEW/FUNCTION/NOTEBOOK, not {asset_type} ({asset_fqn})")
            return None # No sample data for unsupported types in this context
            
        try:
            definition = None
            if asset_type == AssetType.VIEW:
                 table_info = self._ws_client.tables.get(full_name=asset_fqn)
                 definition = table_info.view_definition
            elif asset_type == AssetType.FUNCTION:
                 func_info = self._ws_client.functions.get(name=asset_fqn)
                 definition = func_info.definition
            elif asset_type == AssetType.NOTEBOOK:
                try:
                    notebook_path = asset_fqn # This might need adjustment
                    logger.info(f"Attempting to export notebook from workspace path: {notebook_path}")
                    exported_content = self._ws_client.workspace.export_notebook(notebook_path)
                    definition = exported_content
                    logger.info(f"Successfully exported notebook {asset_fqn}.")
                except Exception as nb_export_error:
                    logger.error(f"SDK error exporting notebook {asset_fqn}: {nb_export_error}", exc_info=True)
                    definition = None 

            if definition is not None:
                logger.info(f"Successfully fetched live definition for {asset_type.value} {asset_fqn}.")
                return definition
            else:
                # SDK call returned None or notebook export failed
                logger.warning(f"Live definition for {asset_type.value} {asset_fqn} was None or an SDK export/get operation returned None.")
                return _try_load_sample_for_demo(asset_type, asset_fqn, "SDK returned None or export failure")

        except AttributeError as e:
            logger.error(f"AttributeError fetching definition for {asset_fqn} (type: {asset_type}): {e}. Likely SDK object mismatch or issue with returned data structure.")
            return _try_load_sample_for_demo(asset_type, asset_fqn, f"AttributeError: {e}")
        except NotFound:
            logger.warning(f"Asset {asset_fqn} (type: {asset_type.value}) not found by SDK when fetching definition.")
            return _try_load_sample_for_demo(asset_type, asset_fqn, "Asset NotFound by SDK")
        except PermissionDenied:
            logger.warning(f"Permission denied by SDK when fetching definition for {asset_fqn} (type: {asset_type.value}).")
            return _try_load_sample_for_demo(asset_type, asset_fqn, "PermissionDenied by SDK")
        except DatabricksError as de:
            logger.error(f"Databricks SDK error fetching definition for {asset_fqn} (type: {asset_type.value}): {de}", exc_info=True)
            return _try_load_sample_for_demo(asset_type, asset_fqn, f"DatabricksError: {de}")
        except Exception as e:
            logger.error(f"Unexpected error fetching definition for {asset_fqn} (type: {asset_type.value}): {e}", exc_info=True)
            return _try_load_sample_for_demo(asset_type, asset_fqn, f"Unexpected error: {e}")
        
    async def get_table_preview(self, table_fqn: str, limit: int = 25) -> Optional[Dict[str, Any]]:
        """Fetches a preview of data from a table."""
        if not self._ws_client:
            logger.warning(f"Cannot fetch preview for {table_fqn}: WorkspaceClient not available.")
            return None
            
        try:
             # Use ws_client.tables.read - Note: This might require specific permissions
             # and connection setup if running outside Databricks runtime.
             # The exact method might vary based on SDK version and context.
             # This is a conceptual example.
             # Example using a hypothetical direct read or via execute_statement
             # data = self._ws_client.tables.read(name=table_fqn, max_rows=limit)
             # return data.to_dict() # Or format as needed
             
             # --- Attempting preview via sql.execute --- #
            try:
                table_info = self._ws_client.tables.get(full_name=table_fqn)
                schema = table_info.columns
                formatted_schema = [{"name": col.name, "type": col.type_text, "nullable": col.nullable} for col in schema]
                
                # Try executing a SELECT query
                # Note: This requires ws_client to be configured with appropriate
                # credentials and potentially a host/warehouse for SQL execution.
                # It might fail if only configured for workspace APIs.
                result = self._ws_client.sql.execute(
                    statement=f"SELECT * FROM {table_fqn} LIMIT {limit}",
                    # warehouse_id="YOUR_WAREHOUSE_ID" # Usually required
                )
                
                # Assuming result.rows gives a list of rows (actual structure might vary)
                data = result.rows if result and hasattr(result, 'rows') else []
                
                # Get total rows (may not be accurate from LIMIT query)
                total_rows = table_info.properties.get("numRows", 0) if table_info.properties else 0
                
                logger.info(f"Successfully fetched preview for {table_fqn} via sql.execute.")
                return {"schema": formatted_schema, "data": data, "total_rows": total_rows}

            except DatabricksError as sql_error:
                 # Specific handling if sql.execute fails (e.g., permissions, config)
                 logger.warning(f"sql.execute failed for {table_fqn}: {sql_error}. Falling back to schema-only.")
                 # Fallback: Return schema only if data fetch fails
                 if 'table_info' in locals(): # Ensure table_info was fetched before error
                      schema = table_info.columns
                      formatted_schema = [{"name": col.name, "type": col.type_text, "nullable": col.nullable} for col in schema]
                      total_rows = table_info.properties.get("numRows", 0) if table_info.properties else 0
                      return {"schema": formatted_schema, "data": [], "total_rows": total_rows}
                 else:
                     raise sql_error # Re-raise if we couldn't even get schema
            except Exception as exec_err:
                 # Catch other potential errors during execution or data processing
                 logger.error(f"Unexpected error during sql.execute or processing for {table_fqn}: {exec_err}", exc_info=True)
                 # Fallback as above
                 if 'table_info' in locals():
                      schema = table_info.columns
                      formatted_schema = [{"name": col.name, "type": col.type_text, "nullable": col.nullable} for col in schema]
                      total_rows = table_info.properties.get("numRows", 0) if table_info.properties else 0
                      return {"schema": formatted_schema, "data": [], "total_rows": total_rows}
                 else:
                    logger.error(f"Could not get schema info for {table_fqn} before execution error.")
                    return None # Return None if schema couldn't be fetched either
            # --- End of sql.execute attempt --- #

        except NotFound:
            logger.warning(f"Table {table_fqn} not found when fetching preview.")
            return None
        except PermissionDenied:
            logger.warning(f"Permission denied when fetching preview for {table_fqn}.")
            return None
        except Exception as e:
            logger.error(f"Error fetching preview for {table_fqn}: {e}", exc_info=True)
            return None
        
    # TODO: Add methods for running automated checks (similar to Compliance)
    # This would involve defining check types, potentially creating/running Databricks jobs
    # and updating the asset status based on results. 

    # --- Implementation of SearchableAsset ---
    def _build_search_index_item(self, review: DataAssetReviewRequestApi) -> Optional[SearchIndexItem]:
        """Build a SearchIndexItem from a DataAssetReviewRequestApi model."""
        if not review.id:
            logger.warning(f"Skipping review due to missing id: {review}")
            return None
        title = derive_review_title(review)
        tags = [review.status.value]
        tags.append(f"reviewer:{review.reviewer_email}")
        tags.append(f"requester:{review.requester_email}")
        if review.assets:
            tags.extend([asset.status.value for asset in review.assets])
            tags.extend([asset.asset_fqn for asset in review.assets])
            tags.extend([asset.asset_type.value for asset in review.assets])
        extra_data = {
            "requester": review.requester_email or "",
            "reviewer": review.reviewer_email or "",
            "status": review.status.value if review.status else "",
        }
        return SearchIndexItem(
            id=f"review::{review.id}",
            type="data-asset-review",
            feature_id="data-asset-reviews",
            title=title,
            description=review.notes or f"Review request by {review.requester_email}",
            link=f"/data-asset-reviews/{review.id}",
            tags=list(set(tags)),
            extra_data=extra_data,
        )

    def _update_search_index(self, review: DataAssetReviewRequestApi) -> None:
        """Upsert a single review request into the search index."""
        item = self._build_search_index_item(review)
        if item:
            self._notify_index_upsert(item)

    def get_search_index_items(self) -> List[SearchIndexItem]:
        """Fetches data asset review requests and maps them to SearchIndexItem format."""
        logger.info("Fetching data asset review requests for search indexing...")
        items = []
        try:
            # Fetch all review requests (adjust limit if needed)
            reviews_api = self.list_review_requests(limit=10000) # Fetch Pydantic models

            for review in reviews_api:
                item = self._build_search_index_item(review)
                if item:
                    items.append(item)
            logger.info(f"Prepared {len(items)} data asset reviews for search index.")
            return items
        except Exception as e:
            logger.error(f"Error fetching or mapping data asset reviews for search: {e}", exc_info=True)
            return [] # Return empty list on error 