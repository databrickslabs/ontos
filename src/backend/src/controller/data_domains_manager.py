from typing import Dict, List, Optional, Tuple
from uuid import UUID
import json # Import json

from sqlalchemy.orm import Session, joinedload, selectinload # Added joinedload, selectinload
from sqlalchemy.exc import IntegrityError # Import IntegrityError

from src.repositories.data_domain_repository import DataDomainRepository
from src.repositories.entity_domain_association_repository import entity_domain_repo
from src.models.data_domains import DataDomainCreate, DataDomainUpdate, DataDomainRead, DataDomainBasicInfo # Added DataDomainBasicInfo
from src.db_models.data_domains import DataDomain
from src.common.errors import ConflictError, NotFoundError, AppError # Import custom errors, AppError for validation
from src.controller.change_log_manager import change_log_manager
from src.controller.comments_manager import CommentsManager
from src.controller.tags_manager import TagsManager
# from src.controller.audit_log_manager import AuditLogManager # Placeholder

# Search indexing interfaces
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.common.search_registry import searchable_asset
from src.common.database import get_session_factory
from src.common.delivery_mixin import DeliveryMixin
from typing import Any

from src.common.logging import get_logger
logger = get_logger(__name__)


@searchable_asset
class DataDomainManager(DeliveryMixin, SearchableAsset):
    """Manager for Data Domains.
    
    Inherits DeliveryMixin to support automatic delivery of changes
    to configured delivery modes (Direct, Indirect, Manual).
    """
    
    # DeliveryMixin configuration
    DELIVERY_ENTITY_TYPE = "DataDomain"
    
    def __init__(self, repository: DataDomainRepository, tags_manager: Optional[TagsManager] = None):
        self.repository = repository
        self.tags_manager = tags_manager or TagsManager()
        # self.audit_log_manager = AuditLogManager() # Placeholder: Inject later
        logger.debug("DataDomainManager initialized.")

    def _convert_db_to_read_model(self, db_domain: DataDomain, db: Optional[Session] = None) -> DataDomainRead:
        """Helper to convert DB model to Read model, populating parent_name and children_count."""
        parent_name = None
        parent_info_data: Optional[DataDomainBasicInfo] = None
        if db_domain.parent: # Assuming parent is loaded
            parent_name = db_domain.parent.name
            parent_info_data = DataDomainBasicInfo.model_validate(db_domain.parent) # Use model_validate for Pydantic v2

        children_count = len(db_domain.children) # Assuming children are loaded or counted
        children_info_data: List[DataDomainBasicInfo] = []
        if db_domain.children:
            for child_db_obj in db_domain.children:
                children_info_data.append(DataDomainBasicInfo.model_validate(child_db_obj))

        # Load tags from TagsManager
        tags_list = []
        if db:
            try:
                assigned_tags = self.tags_manager.list_assigned_tags(
                    db, entity_id=db_domain.id, entity_type="data_domain"
                )
                tags_list = assigned_tags
            except Exception as e:
                logger.warning(f"Failed to load tags for data domain {db_domain.id}: {e}")
                tags_list = []

        return DataDomainRead(
            id=db_domain.id,
            name=db_domain.name,
            description=db_domain.description,
            tags=tags_list,
            parent_id=db_domain.parent_id,
            created_at=db_domain.created_at,
            updated_at=db_domain.updated_at,
            created_by=db_domain.created_by,
            parent_name=parent_name,
            children_count=children_count,
            parent_info=parent_info_data,
            children_info=children_info_data
        )

    def create_domain(
        self,
        db: Session,
        domain_in: DataDomainCreate,
        current_user_id: str,
        background_tasks: Optional[Any] = None,
    ) -> DataDomainRead:
        """Creates a new data domain.
        
        Args:
            db: Database session
            domain_in: Domain creation data
            current_user_id: Username of creator
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
        """
        from src.controller.delivery_service import DeliveryChangeType
        
        logger.debug(f"Attempting to create data domain: {domain_in.name}")
        
        if domain_in.parent_id:
            parent_domain = self.repository.get(db, domain_in.parent_id)
            if not parent_domain:
                raise NotFoundError(f"Parent domain with id '{domain_in.parent_id}' not found.")

        db_obj_data = domain_in.model_dump(exclude_unset=True, exclude={'tags'}) # Use model_dump for Pydantic v2
        db_obj_data['created_by'] = current_user_id

        # Tags are now handled by TagsManager - no serialization needed

        db_domain = DataDomain(**db_obj_data)

        try:
            db.add(db_domain)
            db.flush() 
            db.refresh(db_domain, attribute_names=['id', 'parent']) # Refresh to get ID and potentially loaded parent
            # Eagerly load children for count, or rely on lazy load if simple len() is fine.
            # For now, let's assume session context handles children for len()
            # If specific loading is needed: db.refresh(db_domain, attribute_names=['children'])
            # but this loads all children objects, which might be heavy.
            # A subquery for count in repository.get might be better for children_count.
            # For now, using len(db_domain.children) implicitly assumes they are accessible.

            logger.debug(f"Successfully created data domain '{db_domain.name}' with id: {db_domain.id}")
            
            # Log the change (commit will be handled by the route)
            try:
                change_log_manager.log_change(
                    db,
                    entity_type="data_domain",
                    entity_id=str(db_domain.id),
                    action="CREATE",
                    username=current_user_id
                )
            except Exception as log_error:
                logger.warning(f"Failed to log change for domain creation: {log_error}")
            
            # Load parent again to ensure its name is available for the read model conversion
            # This is needed if the initial refresh didn't fully populate it or if not using joinedload in repo.
            if db_domain.parent_id and not db_domain.parent:
                 # This might be redundant if db.refresh already handled it or if repo.get loads parent.
                 # This specific refresh for parent might not be needed if the relationship is configured correctly (e.g. lazy='joined')
                 # or if the repo method that fetches it does a joinedload.
                 # For now, let's explicitly fetch the parent if parent_id exists but parent object is not loaded.
                 # This explicit query ensures parent.name is available for _convert_db_to_read_model.
                 parent_obj = db.query(DataDomain).filter(DataDomain.id == db_domain.parent_id).one_or_none()
                 db_domain.parent = parent_obj # Assign it to the instance

            # Explicitly load children to count them. This can be inefficient.
            # A better approach would be a COUNT subquery in the repository layer.
            # For simplicity here, assume children relationship can be counted via len().
            # db.refresh(db_domain, with_for_update=None, attribute_names=['children']) # This reloads ALL children objects.

            result = self._convert_db_to_read_model(db_domain, db)
            
            # Queue delivery for active modes
            self._queue_delivery(
                entity=db_domain,
                change_type=DeliveryChangeType.DOMAIN_CREATE,
                user=current_user_id,
                background_tasks=background_tasks,
            )
            
            self._update_search_index(db_domain)
            return result
        except IntegrityError as e:
            db.rollback()
            logger.warning(f"Integrity error creating data domain '{domain_in.name}': {e}")
            if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                raise ConflictError(f"Data domain with name '{domain_in.name}' already exists.")
            else:
                raise 
        except Exception as e:
            db.rollback()
            logger.exception(f"Error creating data domain '{domain_in.name}': {e}")
            raise

    def get_domain_by_id(self, db: Session, domain_id: UUID) -> Optional[DataDomainRead]:
        """Gets a data domain by its ID, including parent name and children count."""
        logger.debug(f"Fetching data domain with id: {domain_id}")
        # Modify repository call or logic here to ensure parent and children (for count) are loaded
        # Using options for joinedload for parent and potentially a subquery for children count in repo is best.
        # For now, we rely on lazy loading and direct access, which might cause N+1 queries if not careful.
        db_domain = self.repository.get_with_details(db, domain_id) # Assume repo method loads parent and children for count
        
        if not db_domain:
            logger.warning(f"Data domain with id {domain_id} not found.")
            return None
        return self._convert_db_to_read_model(db_domain, db)

    def get_all_domains(self, db: Session, skip: int = 0, limit: int = 100) -> List[DataDomainRead]:
        """Gets a list of all data domains, including parent name and children count."""
        logger.debug(f"Fetching all data domains with skip={skip}, limit={limit}")
        # Same as get_domain_by_id, ensure repository loads necessary data efficiently.
        db_domains = self.repository.get_multi_with_details(db, skip=skip, limit=limit) # Assume repo method loads details
        return [self._convert_db_to_read_model(domain, db) for domain in db_domains]

    def update_domain(
        self,
        db: Session,
        domain_id: UUID,
        domain_in: DataDomainUpdate,
        current_user_id: str,
        background_tasks: Optional[Any] = None,
    ) -> Optional[DataDomainRead]:
        """Updates an existing data domain.
        
        Args:
            db: Database session
            domain_id: Domain ID to update
            domain_in: Update data
            current_user_id: Username of updater
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
        """
        from src.controller.delivery_service import DeliveryChangeType
        
        logger.debug(f"Attempting to update data domain with id: {domain_id}")
        db_domain = self.repository.get(db, domain_id) # Get the raw domain first
        if not db_domain:
            logger.warning(f"Data domain with id {domain_id} not found for update.")
            raise NotFoundError(f"Data domain with id '{domain_id}' not found.")

        if domain_in.parent_id:
            if domain_in.parent_id == domain_id:
                 raise AppError(f"Cannot set a domain as its own parent.") # Use a more specific error like ValidationError or BadRequest
            parent_domain = self.repository.get(db, domain_in.parent_id)
            if not parent_domain:
                raise NotFoundError(f"Parent domain with id '{domain_in.parent_id}' not found.")
        
        # obj_in here is Pydantic model, repository.update expects a dict or Pydantic model
        update_data = domain_in.model_dump(exclude_unset=True)

        # Tags are now handled by TagsManager - no serialization needed

        try:
            # The CRUDBase update method takes obj_in which can be a dict or Pydantic model.
            # It iterates fields and sets them on db_obj.
            updated_db_domain = self.repository.update(db=db, db_obj=db_domain, obj_in=update_data)
            # After update, refresh to get potentially updated relationships or counts
            db.flush()
            db.refresh(updated_db_domain, attribute_names=['parent']) # Ensure parent is loaded if parent_id changed
            # db.refresh(updated_db_domain, attribute_names=['children']) # if children count could change indirectly

            logger.debug(f"Successfully updated data domain '{updated_db_domain.name}' (id: {domain_id})")
            
            # Log the change (commit will be handled by the route)
            try:
                change_log_manager.log_change(
                    db,
                    entity_type="data_domain",
                    entity_id=str(domain_id),
                    action="UPDATE",
                    username=current_user_id
                )
            except Exception as log_error:
                logger.warning(f"Failed to log change for domain update: {log_error}")
            
            result = self._convert_db_to_read_model(updated_db_domain, db)
            
            # Queue delivery for active modes
            self._queue_delivery(
                entity=updated_db_domain,
                change_type=DeliveryChangeType.DOMAIN_UPDATE,
                user=current_user_id,
                background_tasks=background_tasks,
            )
            
            self._update_search_index(updated_db_domain)
            return result
        except IntegrityError as e:
             db.rollback()
             logger.warning(f"Integrity error updating data domain {domain_id}: {e}")
             if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                 raise ConflictError(f"Data domain name '{domain_in.name}' is already in use by another domain.")
             else:
                 raise
        except AppError as e: # Catch our custom validation error
            db.rollback()
            raise # Re-raise it to be caught by FastAPI error handling (e.g., return 400)
        except Exception as e:
            db.rollback()
            logger.exception(f"Error updating data domain {domain_id}: {e}")
            raise

    @staticmethod
    def _collect_domain_and_descendant_ids(domain: DataDomain) -> List[str]:
        """Return the domain's id plus every descendant id (children cascade-delete)."""
        ids = [str(domain.id)]
        for child in (domain.children or []):
            ids.extend(DataDomainManager._collect_domain_and_descendant_ids(child))
        return ids

    def get_domain_deletion_impact(self, db: Session, domain_id: UUID) -> Dict[str, Any]:
        """Report which entities would block deletion of a domain and the assignment counts.

        Returns ``{"domain_id", "domain_name", "deletable" (bool), "primary_assignments":
        [{entity_type, entity_id}], "assignment_counts": {entity_type: {primary, additional}}}``.
        Lets the UI warn before attempting a delete (which 409s if primary anywhere)."""
        db_domain = self.repository.get_with_details(db, domain_id)
        if not db_domain:
            raise NotFoundError(f"Data domain with id '{domain_id}' not found.")

        affected_domain_ids = self._collect_domain_and_descendant_ids(db_domain)
        primary_entities: List[Tuple[str, str]] = []
        assignment_counts: Dict[str, Dict[str, int]] = {}
        for did in affected_domain_ids:
            primary_entities.extend(
                entity_domain_repo.get_entities_with_primary_domain(db, domain_id=did)
            )
            for etype, bucket in entity_domain_repo.get_assignment_counts_for_domain(db, domain_id=did).items():
                agg = assignment_counts.setdefault(etype, {"primary": 0, "additional": 0})
                agg["primary"] += bucket.get("primary", 0)
                agg["additional"] += bucket.get("additional", 0)

        return {
            "domain_id": str(domain_id),
            "domain_name": db_domain.name,
            "deletable": len(primary_entities) == 0,
            "primary_assignments": [
                {"entity_type": etype, "entity_id": eid} for etype, eid in primary_entities
            ],
            "assignment_counts": assignment_counts,
        }

    def delete_domain(self, db: Session, domain_id: UUID, current_user_id: str) -> Optional[DataDomainRead]:
        """Deletes a data domain by its ID."""
        logger.debug(f"Attempting to delete data domain with id: {domain_id}")
        
        db_domain_to_delete = self.repository.get_with_details(db, domain_id) # Load details for return
        if not db_domain_to_delete:
             logger.warning(f"Data domain with id {domain_id} not found for deletion.")
             raise NotFoundError(f"Data domain with id '{domain_id}' not found.")

        # Check for children - prevent deletion if domain has children, or handle cascading based on policy
        # The cascade="all, delete-orphan" on DB model will delete children.
        # If we want to prevent deletion of parents with children, we add a check here.
        if db_domain_to_delete.children:
            # Current cascade rule will delete children. If this is not desired, raise error.
            # logger.warning(f"Attempt to delete domain {domain_id} which has {len(db_domain_to_delete.children)} children. Deletion allowed due to cascade rule.")
            # To prevent deletion:
            # raise ConflictError(f"Cannot delete domain '{db_domain_to_delete.name}' because it has child domains. Please delete or re-parent children first.")
            pass # Current setup allows cascade delete.

        # Multi-domain assignment (#520): a domain (or any descendant that would be
        # cascade-deleted with it) that is the PRIMARY domain for any entity cannot be
        # deleted — the primary feeds single-value integrations (ODCS domain, UC tag).
        # Domains that are only ever *additional* can be deleted; their association rows
        # are cleaned up below (the junction FK has no ON DELETE CASCADE).
        affected_domain_ids = self._collect_domain_and_descendant_ids(db_domain_to_delete)
        primary_entities: List[Tuple[str, str]] = []
        for did in affected_domain_ids:
            primary_entities.extend(
                entity_domain_repo.get_entities_with_primary_domain(db, domain_id=did)
            )
        if primary_entities:
            assignment_counts: Dict[str, Dict[str, int]] = {}
            for did in affected_domain_ids:
                for etype, bucket in entity_domain_repo.get_assignment_counts_for_domain(db, domain_id=did).items():
                    agg = assignment_counts.setdefault(etype, {"primary": 0, "additional": 0})
                    agg["primary"] += bucket.get("primary", 0)
                    agg["additional"] += bucket.get("additional", 0)
            logger.warning(
                "Blocking deletion of domain %s ('%s'): primary for %d entity assignment(s).",
                domain_id, db_domain_to_delete.name, len(primary_entities),
            )
            raise ConflictError(detail={
                "code": "domain_primary_in_use",
                "message": (
                    f"Cannot delete domain '{db_domain_to_delete.name}': it is the primary domain "
                    f"for {len(primary_entities)} entity assignment(s). Reassign those entities to a "
                    f"different primary domain (or remove the assignment) before deleting."
                ),
                "domain_id": str(domain_id),
                "domain_name": db_domain_to_delete.name,
                "primary_assignments": [
                    {"entity_type": etype, "entity_id": eid} for etype, eid in primary_entities
                ],
                "assignment_counts": assignment_counts,
            })

        read_model_of_deleted = self._convert_db_to_read_model(db_domain_to_delete, db)

        try:
            # Clean up any additional-only association rows first (FK to data_domains has
            # no ON DELETE CASCADE), across the domain and its cascade-deleted descendants.
            for did in affected_domain_ids:
                entity_domain_repo.remove_all_for_domain(db, domain_id=did)
            # The repository.remove(db, id) should work.
            # The actual object `db_domain_to_delete` will become stale after deletion from session.
            self.repository.remove(db=db, id=domain_id)
            self._notify_index_remove(f"domain::{domain_id}")
            
            # Log the change before commit
            try:
                change_log_manager.log_change(
                    db,
                    entity_type="data_domain",
                    entity_id=str(domain_id),
                    action="DELETE",
                    username=current_user_id
                )
            except Exception as log_error:
                logger.warning(f"Failed to log change for domain deletion: {log_error}")
            
            # db.commit() is handled by the route typically
            logger.debug(f"Successfully marked data domain '{read_model_of_deleted.name}' (id: {domain_id}) for deletion.")
            return read_model_of_deleted 
        except Exception as e:
            db.rollback()
            logger.exception(f"Error deleting data domain {domain_id}: {e}")
            raise

    def create_domain_internal(self, db: Session, domain_in: DataDomainCreate, current_user_id: str, perform_commit: bool = True, log_change: bool = False) -> DataDomain:
        """Internal method to create domain."""
        if domain_in.parent_id:
            parent_domain = self.repository.get(db, domain_in.parent_id)
            if not parent_domain:
                raise NotFoundError(f"Parent domain with id '{domain_in.parent_id}' not found.")

        db_obj_data = domain_in.model_dump(exclude_unset=True, exclude={'tags'})
        db_obj_data['created_by'] = current_user_id
        # Tags are now handled by TagsManager - no serialization needed
        
        db_domain = DataDomain(**db_obj_data)
        try:
            db.add(db_domain)
            if perform_commit:
                db.commit()
                db.refresh(db_domain)
            else:
                db.flush() # Flush to get ID if not committing
                db.refresh(db_domain, attribute_names=['id'])
            
            # Log the change if requested
            if log_change:
                try:
                    change_log_manager.log_change(
                        db,
                        entity_type="data_domain",
                        entity_id=str(db_domain.id),
                        action="CREATE",
                        username=current_user_id
                    )
                    if perform_commit:
                        db.commit()  # Commit the change log entry too
                except Exception as log_error:
                    logger.warning(f"Failed to log change for demo domain creation: {log_error}")
            
            return db_domain
        except IntegrityError as e:
            db.rollback()
            if "unique constraint" in str(e).lower() or "duplicate key" in str(e).lower():
                raise ConflictError(f"Data domain with name '{domain_in.name}' already exists.")
            raise
        except Exception as e:
            db.rollback()
            raise 

    # --- SearchableAsset Implementation ---
    def _build_search_index_item(self, db_domain: DataDomain) -> Optional[SearchIndexItem]:
        """Build a SearchIndexItem from a DataDomain DB model."""
        if not getattr(db_domain, 'id', None) or not getattr(db_domain, 'name', None):
            logger.warning(f"Skipping domain due to missing id or name: {db_domain}")
            return None
        extra_data = {
            "owner": getattr(db_domain, 'created_by', '') or "",
            "status": getattr(db_domain, 'status', 'active') or "active",
        }
        return SearchIndexItem(
            id=f"domain::{db_domain.id}",
            type="data-domain",
            feature_id="data-domains",
            title=db_domain.name,
            description=getattr(db_domain, 'description', '') or "",
            link=f"/data-domains/{db_domain.id}",
            tags=[],
            extra_data=extra_data,
        )

    def _update_search_index(self, db_domain: DataDomain) -> None:
        """Upsert a single data domain into the search index."""
        item = self._build_search_index_item(db_domain)
        if item:
            self._notify_index_upsert(item)

    def get_search_index_items(self) -> List[SearchIndexItem]:
        """Fetch data domains and map them to SearchIndexItem format for global search."""
        logger.info("Fetching data domains for search indexing...")
        items: List[SearchIndexItem] = []
        try:
            session_factory = get_session_factory()
            if not session_factory:
                logger.warning("Session factory not available; cannot index data domains.")
                return []

            with session_factory() as db:
                db_domains = self.repository.get_multi(db=db, limit=10000)
                for db_domain in db_domains:
                    item = self._build_search_index_item(db_domain)
                    if item:
                        items.append(item)

            logger.info(f"Prepared {len(items)} data domains for search index.")
            return items
        except Exception as e:
            logger.error(f"Error fetching or mapping data domains for search: {e}", exc_info=True)
            return []