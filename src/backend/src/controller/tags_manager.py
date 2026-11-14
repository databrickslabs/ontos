from typing import Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from src.common.logging import get_logger
from src.repositories.tags_repository import (
    tag_namespace_repo, tag_repo, tag_namespace_permission_repo, entity_tag_repo,
    TagNamespaceRepository, TagRepository, TagNamespacePermissionRepository, EntityTagAssociationRepository
)
from src.models.tags import (
    Tag, TagCreate, TagUpdate, TagStatus,
    TagNamespace, TagNamespaceCreate, TagNamespaceUpdate,
    TagNamespacePermission, TagNamespacePermissionCreate, TagNamespacePermissionUpdate, TagAccessLevel,
    AssignedTagCreate, AssignedTag,
    DEFAULT_NAMESPACE_NAME, TAG_NAMESPACE_SEPARATOR
)
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.db_models.assets import AssetDb
from src.common.asset_search_item import build_asset_search_item
from src.repositories.entity_domain_association_repository import entity_domain_repo

from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.common.search_registry import searchable_asset
from src.common.database import get_session_factory
from src.common.delivery_mixin import DeliveryMixin
from typing import Any

logger = get_logger(__name__)


@searchable_asset
class TagsManager(DeliveryMixin, SearchableAsset):
    """Manager for Tags and Tag Namespaces.
    
    Inherits DeliveryMixin to support automatic delivery of changes
    to configured delivery modes (Direct, Indirect, Manual).
    """
    
    # DeliveryMixin configuration
    DELIVERY_ENTITY_TYPE = "TagNamespace"
    
    def __init__(
        self,
        namespace_repo: TagNamespaceRepository = tag_namespace_repo,
        tag_repository: TagRepository = tag_repo,
        permission_repo: TagNamespacePermissionRepository = tag_namespace_permission_repo,
        entity_assoc_repo: EntityTagAssociationRepository = entity_tag_repo
    ):
        self._namespace_repo = namespace_repo
        self._tag_repo = tag_repository
        self._permission_repo = permission_repo
        self._entity_assoc_repo = entity_assoc_repo

    # --- Namespace Methods ---
    def create_namespace(
        self,
        db: Session,
        *,
        namespace_in: TagNamespaceCreate,
        user_email: Optional[str],
        background_tasks: Optional[Any] = None,
    ) -> TagNamespace:
        """Create a new tag namespace.
        
        Args:
            db: Database session
            namespace_in: Namespace creation data
            user_email: User creating the namespace
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
        """
        from src.controller.delivery_service import DeliveryChangeType
        
        existing_namespace = self._namespace_repo.get_by_name(db, name=namespace_in.name)
        if existing_namespace:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
                                detail=f"Tag namespace '{namespace_in.name}' already exists.")
        db_namespace = self._namespace_repo.create(db, obj_in=namespace_in, user_email=user_email)
        db.commit()
        db.refresh(db_namespace)
        
        result = TagNamespace.from_orm(db_namespace)
        
        # Queue delivery for active modes
        self._queue_delivery(
            entity=db_namespace,
            change_type=DeliveryChangeType.TAG_CREATE,
            user=user_email,
            background_tasks=background_tasks,
        )
        
        return result

    def get_namespace(self, db: Session, *, namespace_id: UUID) -> Optional[TagNamespace]:
        db_namespace = self._namespace_repo.get(db, id=namespace_id)
        return TagNamespace.from_orm(db_namespace) if db_namespace else None

    def get_namespace_by_name(self, db: Session, *, name: str) -> Optional[TagNamespace]:
        db_namespace = self._namespace_repo.get_by_name(db, name=name)
        return TagNamespace.from_orm(db_namespace) if db_namespace else None

    def list_namespaces(self, db: Session, *, skip: int = 0, limit: Optional[int] = None) -> List[TagNamespace]:
        db_namespaces = self._namespace_repo.get_multi(db, skip=skip, limit=limit)
        return [TagNamespace.from_orm(ns) for ns in db_namespaces]

    def update_namespace(
        self,
        db: Session,
        *,
        namespace_id: UUID,
        namespace_in: TagNamespaceUpdate,
        user_email: Optional[str],
        background_tasks: Optional[Any] = None,
    ) -> Optional[TagNamespace]:
        """Update an existing tag namespace.
        
        Args:
            db: Database session
            namespace_id: Namespace ID to update
            namespace_in: Update data
            user_email: User updating the namespace
            background_tasks: Optional FastAPI BackgroundTasks for async delivery
        """
        from src.controller.delivery_service import DeliveryChangeType
        
        db_namespace = self._namespace_repo.get(db, id=namespace_id)
        if not db_namespace:
            return None
        if namespace_in.name:
            existing_namespace_with_name = self._namespace_repo.get_by_name(db, name=namespace_in.name)
            if existing_namespace_with_name and existing_namespace_with_name.id != namespace_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
                                    detail=f"Tag namespace name '{namespace_in.name}' is already in use.")
        
        updated_db_namespace = self._namespace_repo.update(db, db_obj=db_namespace, obj_in=namespace_in, user_email=user_email)
        db.commit()
        db.refresh(updated_db_namespace)
        
        result = TagNamespace.from_orm(updated_db_namespace)
        
        # Queue delivery for active modes
        self._queue_delivery(
            entity=updated_db_namespace,
            change_type=DeliveryChangeType.TAG_UPDATE,
            user=user_email,
            background_tasks=background_tasks,
        )
        
        return result

    def delete_namespace(self, db: Session, *, namespace_id: UUID) -> bool:
        # Ensure it's not the default namespace
        db_namespace = self._namespace_repo.get(db, id=namespace_id)
        if db_namespace and db_namespace.name == DEFAULT_NAMESPACE_NAME:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, 
                                detail=f"Cannot delete the default namespace '{DEFAULT_NAMESPACE_NAME}'.")
        # Add check for existing tags in namespace before deletion if strict policy needed
        # tags_in_namespace = self._tag_repo.get_multi_with_filters(db, namespace_id=namespace_id, limit=1)
        # if tags_in_namespace:
        #     raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Namespace not empty. Delete tags first.")
        
        deleted_count = self._namespace_repo.remove(db, id=namespace_id)
        if deleted_count:
            db.commit()
            return True
        return False

    # --- Entity Tagging Methods (generic across entity types) ---
    @staticmethod
    def _check_possible_value(tag_db: TagDb, value: Optional[str]) -> None:
        """Refuse a value outside the tag's possible_values (422). ``None`` keeps the
        stored value and ``""`` clears it, so neither is checked."""
        allowed = tag_db.possible_values or []
        if value and allowed and value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "tag_value_not_allowed",
                    "message": f"Value '{value}' is not one of the possible values of tag '{tag_db.name}'.",
                    "params": {"tag": tag_db.name, "value": value, "allowed": list(allowed)},
                },
            )

    def check_assigned_values(
        self, db: Session, tags: List[Any], *, entity_id: Optional[str] = None, entity_type: Optional[str] = None,
    ) -> None:
        """Refuse out-of-list values before anything is written. Takes FQN strings, dicts
        or AssignedTagCreate; entries that don't parse are left to the caller's own handling.
        With an entity, a value the entity already stores is not checked again (#1421)."""
        stored: Dict[UUID, Optional[str]] = {}
        if entity_id is not None and entity_type is not None:
            stored = {
                t.tag_id: t.assigned_value
                for t in self.list_assigned_tags(db, entity_id=str(entity_id), entity_type=entity_type)
            }
        for tag_in in tags:
            try:
                if isinstance(tag_in, str):
                    tag_in = AssignedTagCreate(tag_fqn=tag_in)
                elif isinstance(tag_in, dict):
                    tag_in = AssignedTagCreate(**tag_in)
            except (ValueError, TypeError):
                continue
            if not tag_in.assigned_value:
                continue
            tag_db = (
                self._tag_repo.get(db, id=tag_in.tag_id) if tag_in.tag_id
                else self._tag_repo.get_by_fully_qualified_name(db, fqn=tag_in.tag_fqn) if tag_in.tag_fqn
                else None
            )
            if tag_db and stored.get(tag_db.id) != tag_in.assigned_value:
                self._check_possible_value(tag_db, tag_in.assigned_value)

    def unknown_tag_namespaces(self, db: Session, tags: List[Any]) -> List[str]:
        """Namespaces named by the FQNs of ``tags`` that don't exist. ``set_tags_for_entity``
        would raise for them; callers check first to refuse the request (422) or the
        import row before anything is written. ``default`` is always there."""
        missing: List[str] = []
        for tag_in in tags or []:
            fqn = tag_in.tag_fqn if isinstance(tag_in, AssignedTagCreate) else (
                tag_in.get('tag_fqn') if isinstance(tag_in, dict) else tag_in if isinstance(tag_in, str) else None
            )
            if not fqn or TAG_NAMESPACE_SEPARATOR not in fqn:
                continue
            namespace_name = fqn.split(TAG_NAMESPACE_SEPARATOR, 1)[0]
            if namespace_name == DEFAULT_NAMESPACE_NAME or namespace_name in missing:
                continue
            if self._namespace_repo.get_by_name(db, name=namespace_name) is None:
                missing.append(namespace_name)
        return missing

    def list_assigned_tags(self, db: Session, *, entity_id: str, entity_type: str) -> List[AssignedTag]:
        return self._entity_assoc_repo.get_assigned_tags_for_entity(db, entity_id=entity_id, entity_type=entity_type)

    def list_assigned_tags_for_entities(
        self, db: Session, *, entity_ids: List[str], entity_type: str,
    ) -> Dict[str, List[AssignedTag]]:
        """Tags of several entities in one query: ``{entity_id: [AssignedTag, ...]}``."""
        return self._entity_assoc_repo.get_assigned_tags_for_entities(db, entity_ids=entity_ids, entity_type=entity_type)

    def set_tags_for_entity(
        self, db: Session, *, entity_id: str, entity_type: str,
        tags: List[AssignedTagCreate], user_email: Optional[str], commit: bool = True,
    ) -> List[AssignedTag]:
        """Replace the tags of an entity. With ``commit=False`` (a batch import,
        inside the savepoint of the entity) the change is only flushed."""
        self.check_assigned_values(db, tags, entity_id=str(entity_id), entity_type=entity_type)
        before = {t.tag_id: t.assigned_value for t in self.list_assigned_tags(db, entity_id=str(entity_id), entity_type=entity_type)}
        ns_repo = self._namespace_repo
        assigned = self._entity_assoc_repo.set_tags_for_entity(
            db,
            entity_id=entity_id,
            entity_type=entity_type,
            tags_data=tags,
            user_email=user_email,
            tag_repo=self._tag_repo,
            ns_repo=ns_repo,
        )
        
        # Log to change log for timeline, only when the set of tags or values changed
        changed = before != {t.tag_id: t.assigned_value for t in assigned}
        if tags and changed:
            try:
                from src.controller.change_log_manager import change_log_manager
                tag_names = [t.tag_fqn if hasattr(t, 'tag_fqn') else str(t) for t in tags[:5]]
                tag_summary = ", ".join(tag_names)
                if len(tags) > 5:
                    tag_summary += f", ... ({len(tags)} total)"
                details = {
                    "tag_count": len(tags),
                    "tags": tag_summary,
                    "summary": f"Tags updated: {tag_summary}"
                               + (f" by {user_email}" if user_email else ""),
                }
                if commit:
                    change_log_manager.log_change_with_details(
                        db, entity_type=entity_type, entity_id=str(entity_id),
                        action="TAGS_SET", username=user_email, details=details,
                    )
                else:
                    # A failed write mustn't abort the caller's transaction (Postgres)
                    with db.begin_nested():
                        change_log_manager.log_change_with_details(
                            db, entity_type=entity_type, entity_id=str(entity_id),
                            action="TAGS_SET", username=user_email, details=details,
                            commit=False,
                        )
            except Exception as log_err:
                logger.warning(f"Failed to log change for tag set: {log_err}")

        if commit:
            db.commit()
            self._after_asset_tag_write(db, entity_type, entity_id)
        else:
            db.flush()
        return assigned

    def add_tag_to_entity(self, db: Session, *, entity_id: str, entity_type: str, tag_id: UUID, assigned_value: Optional[str], user_email: Optional[str]) -> AssignedTag:
        tag_to_assign = self._tag_repo.get(db, id=tag_id)
        if tag_to_assign:
            self._check_possible_value(tag_to_assign, assigned_value)
        previous = (
            db.query(EntityTagAssociationDb.assigned_value)
            .filter_by(entity_id=entity_id, entity_type=entity_type, tag_id=tag_id)
            .first()
        )
        assoc = self._entity_assoc_repo.add_tag_to_entity(
            db,
            entity_id=entity_id,
            entity_type=entity_type,
            tag_id=tag_id,
            assigned_value=assigned_value,
            assigned_by=user_email,
        )
        
        # Build AssignedTag result
        tag_db = self._tag_repo.get(db, id=tag_id)
        ns = self._namespace_repo.get(db, id=tag_db.namespace_id) if tag_db and tag_db.namespace_id else None
        tag_fqn = f"{(ns.name if ns else DEFAULT_NAMESPACE_NAME)}{TAG_NAMESPACE_SEPARATOR}{tag_db.name}"
        
        # Log to change log for timeline, with the stored value, and only when the
        # assignment changed: re-adding a tag without a value keeps it (#1420)
        stored_value = assoc.assigned_value
        if previous is None or previous[0] != stored_value:
            try:
                from src.controller.change_log_manager import change_log_manager
                change_log_manager.log_change_with_details(
                    db,
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    action="TAG_ASSIGN",
                    username=user_email,
                    details={
                        "tag": tag_fqn,
                        "assigned_value": stored_value,
                        "summary": f"Tag '{tag_fqn}' assigned" + (f" with value '{stored_value}'" if stored_value else "") + (f" by {user_email}" if user_email else ""),
                    },
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for tag assign: {log_err}")
        
        db.commit()
        self._after_asset_tag_write(db, entity_type, entity_id)
        
        return AssignedTag(
            tag_id=tag_db.id,
            tag_name=tag_db.name,
            namespace_id=tag_db.namespace_id,
            namespace_name=ns.name if ns else DEFAULT_NAMESPACE_NAME,
            status=TagStatus(tag_db.status),
            fully_qualified_name=tag_fqn,
            assigned_value=assoc.assigned_value,
            assigned_by=assoc.assigned_by,
            assigned_at=assoc.assigned_at,
        )

    def remove_tag_from_entity(self, db: Session, *, entity_id: str, entity_type: str, tag_id: UUID, user_email: Optional[str] = None) -> bool:
        # Get tag info before removal for change log
        tag_db = self._tag_repo.get(db, id=tag_id)
        tag_fqn = None
        if tag_db:
            ns = self._namespace_repo.get(db, id=tag_db.namespace_id) if tag_db.namespace_id else None
            tag_fqn = f"{(ns.name if ns else DEFAULT_NAMESPACE_NAME)}{TAG_NAMESPACE_SEPARATOR}{tag_db.name}"
        
        ok = self._entity_assoc_repo.remove_tag_from_entity(db, entity_id=entity_id, entity_type=entity_type, tag_id=tag_id)
        if ok:
            # Log to change log for timeline
            try:
                from src.controller.change_log_manager import change_log_manager
                change_log_manager.log_change_with_details(
                    db,
                    entity_type=entity_type,
                    entity_id=str(entity_id),
                    action="TAG_REMOVE",
                    username=user_email,
                    details={
                        "tag": tag_fqn or str(tag_id),
                        "summary": f"Tag '{tag_fqn or str(tag_id)}' removed" + (f" by {user_email}" if user_email else ""),
                    },
                )
            except Exception as log_err:
                logger.warning(f"Failed to log change for tag removal: {log_err}")
            db.commit()
            self._after_asset_tag_write(db, entity_type, entity_id)
        return ok

    # --- Asset search entries: an asset's index entry carries its tag names and FQNs ---
    def _after_asset_tag_write(self, db: Session, entity_type: str, entity_id: str) -> None:
        """Shared hook for every committed tag write on an asset (routes, MCP tools, workflow steps).
        Writes that defer their commit (``commit=False``) refresh the entry after their own commit."""
        if entity_type == "asset":
            self._refresh_asset_search(db, [str(entity_id)])

    def _asset_ids_for_tag(self, db: Session, tag_id: UUID) -> List[str]:
        return [a["entity_id"] for a in self.get_entities_for_tag(db, tag_id=tag_id, entity_type="asset")]

    def _refresh_asset_search(self, db: Session, asset_ids: List[str]) -> None:
        """Re-index assets in one batch: one query each for the assets, their tags and their
        domains per chunk of 500, then one upsert. Call after the write is committed; a failure
        is logged, never raised, because the tag change itself already stands."""
        if not asset_ids or self._search_manager is None:
            return
        try:
            items: List[SearchIndexItem] = []
            for start in range(0, len(asset_ids), 500):
                chunk = [UUID(str(asset_id)) for asset_id in asset_ids[start:start + 500]]
                rows = db.query(AssetDb).options(joinedload(AssetDb.asset_type)).filter(AssetDb.id.in_(chunk)).all()
                ids = [str(asset.id) for asset in rows]
                tags_map = self.list_assigned_tags_for_entities(db, entity_ids=ids, entity_type="asset")
                domains_map = entity_domain_repo.get_domains_for_entities(db, entity_type="asset", entity_ids=ids)
                for asset in rows:
                    item = build_asset_search_item(
                        asset, self,
                        preloaded_domains=domains_map.get(str(asset.id), []),
                        preloaded_tags=tags_map.get(str(asset.id), []),
                    )
                    if item is not None:
                        items.append(item)
            self._search_manager.upsert_items(items)
        except Exception as e:
            logger.warning(f"Search refresh failed for {len(asset_ids)} asset(s): {e}")

    def get_or_create_default_namespace(self, db: Session, *, user_email: Optional[str]) -> TagNamespaceDb:
        """Ensures the default namespace exists, creating it if necessary."""
        # This method returns the DB object, used primarily during startup.
        return self._namespace_repo.get_or_create_default_namespace(db, user_email=user_email)

    # --- Tag Methods ---
    def create_tag(self, db: Session, *, tag_in: TagCreate, user_email: Optional[str]) -> Tag:
        namespace_id_to_use: Optional[UUID] = tag_in.namespace_id
        
        if not namespace_id_to_use:
            ns_name = tag_in.namespace_name or DEFAULT_NAMESPACE_NAME
            namespace_db = self._namespace_repo.get_by_name(db, name=ns_name)
            if not namespace_db:
                if ns_name == DEFAULT_NAMESPACE_NAME:
                    # This should have been created at startup, but as a fallback:
                    namespace_db = self._namespace_repo.get_or_create_default_namespace(db, user_email=user_email)
                else:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Namespace '{ns_name}' not found.")
            namespace_id_to_use = namespace_db.id
        else: # namespace_id was provided
            namespace_db = self._namespace_repo.get(db, id=namespace_id_to_use)
            if not namespace_db:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Namespace with ID '{namespace_id_to_use}' not found.")

        if tag_in.parent_id:
            parent_tag = self._tag_repo.get(db, id=tag_in.parent_id)
            if not parent_tag:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Parent tag with ID '{tag_in.parent_id}' not found.")
            if parent_tag.namespace_id != namespace_id_to_use:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent tag must be in the same namespace.")

        # Check for existing tag with the same name in the resolved namespace
        existing_tag = db.query(TagDb).filter(TagDb.namespace_id == namespace_id_to_use, TagDb.name == tag_in.name).first()
        if existing_tag:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
                                detail=f"Tag '{tag_in.name}' already exists in namespace '{namespace_db.name if namespace_db else namespace_id_to_use}'.")

        db_tag = self._tag_repo.create_with_namespace(db, obj_in=tag_in, namespace_id=namespace_id_to_use, user_email=user_email)
        db.commit()
        db.refresh(db_tag)
        # Eager load namespace for the response model
        db.refresh(db_tag, attribute_names=['namespace'])
        self._update_search_index(db_tag)
        return Tag.from_orm(db_tag)

    def get_tag(self, db: Session, *, tag_id: UUID) -> Optional[Tag]:
        db_tag = self._tag_repo.get(db, id=tag_id) # get() in repo now eager loads namespace, parent, children
        return Tag.from_orm(db_tag) if db_tag else None

    def get_tag_by_fqn(self, db: Session, *, fqn: str) -> Optional[Tag]:
        db_tag = self._tag_repo.get_by_fully_qualified_name(db, fqn=fqn)
        return Tag.from_orm(db_tag) if db_tag else None

    def list_tags(
        self, db: Session, *, 
        skip: int = 0, limit: Optional[int] = None, 
        namespace_id: Optional[UUID] = None,
        namespace_name: Optional[str] = None, 
        name_contains: Optional[str] = None,
        status: Optional[TagStatus] = None,
        parent_id: Optional[UUID] = None,
        is_root: Optional[bool] = None
    ) -> List[Tag]:
        db_tags = self._tag_repo.get_multi_with_filters(
            db, skip=skip, limit=limit, 
            namespace_id=namespace_id, namespace_name=namespace_name,
            name_contains=name_contains, status=status,
            parent_id=parent_id, is_root=is_root
        )
        return [Tag.from_orm(tag) for tag in db_tags]

    def update_tag(self, db: Session, *, tag_id: UUID, tag_in: TagUpdate, user_email: Optional[str]) -> Optional[Tag]:
        db_tag = self._tag_repo.get(db, id=tag_id)
        if not db_tag:
            return None
        # A rename changes the tag names in the search entries of the assets that carry it
        renamed = bool(tag_in.name) and tag_in.name != db_tag.name
        carrying_assets = self._asset_ids_for_tag(db, tag_id) if renamed else []
        
        # If name is being changed, check for conflict within the same namespace
        if tag_in.name and tag_in.name != db_tag.name:
            existing_tag_with_name = db.query(TagDb).filter(TagDb.namespace_id == db_tag.namespace_id, TagDb.name == tag_in.name, TagDb.id != tag_id).first()
            if existing_tag_with_name:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
                                    detail=f"Tag name '{tag_in.name}' already exists in this namespace.")

        if tag_in.parent_id and tag_in.parent_id != db_tag.parent_id:
            parent_tag = self._tag_repo.get(db, id=tag_in.parent_id)
            if not parent_tag:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"New parent tag with ID '{tag_in.parent_id}' not found.")
            if parent_tag.namespace_id != db_tag.namespace_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New parent tag must be in the same namespace.")
            # Prevent circular dependencies (simple check: new parent cannot be self or one of its children)
            if tag_in.parent_id == tag_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot set tag as its own parent.")
            # Deeper circular check might be needed if hierarchies are complex

        updated_db_tag = self._tag_repo.update(db, db_obj=db_tag, obj_in=tag_in, user_email=user_email)
        db.commit()
        db.refresh(updated_db_tag)
        db.refresh(updated_db_tag, attribute_names=['namespace']) # Ensure namespace is loaded for FQN
        self._update_search_index(updated_db_tag)
        self._refresh_asset_search(db, carrying_assets)
        return Tag.from_orm(updated_db_tag)

    def delete_tag(self, db: Session, *, tag_id: UUID) -> bool:
        # Check if tag is a parent to any other tags
        children_count = db.query(func.count(TagDb.id)).filter(TagDb.parent_id == tag_id).scalar()
        if children_count > 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
                                detail=f"Tag ID '{tag_id}' is a parent to {children_count} other tag(s). Delete children first or reassign parent.")
        
        # Check if tag is associated with any entities (future enhancement)
        # assoc_count = db.query(func.count(EntityTagAssociationDb.id)).filter(EntityTagAssociationDb.tag_id == tag_id).scalar()
        # if assoc_count > 0:
        #     raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Tag is associated with {assoc_count} entities. Remove associations first.")

        carrying_assets = self._asset_ids_for_tag(db, tag_id)
        deleted_count = self._tag_repo.remove(db, id=tag_id)
        if deleted_count:
            self._notify_index_remove(f"tag::{tag_id}")
            db.commit()
            self._refresh_asset_search(db, carrying_assets)
            return True
        return False

    # --- Namespace Permission Methods ---
    def add_permission_to_namespace(self, db: Session, *, namespace_id: UUID, perm_in: TagNamespacePermissionCreate, user_email: Optional[str]) -> TagNamespacePermission:
        ns = self._namespace_repo.get(db, id=namespace_id)
        if not ns:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Namespace with ID '{namespace_id}' not found.")
        
        existing_perm = self._permission_repo.get_by_namespace_and_group(db, namespace_id=namespace_id, group_id=perm_in.group_id)
        if existing_perm:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
                                detail=f"Permission for group '{perm_in.group_id}' on namespace '{namespace_id}' already exists.")
        
        perm_in.namespace_id = namespace_id # Ensure namespace_id is set if not already
        db_perm = self._permission_repo.create(db, obj_in=perm_in, user_email=user_email)
        db.commit()
        db.refresh(db_perm)
        return TagNamespacePermission.from_orm(db_perm)

    def get_namespace_permission(self, db: Session, *, perm_id: UUID) -> Optional[TagNamespacePermission]:
        db_perm = self._permission_repo.get(db, id=perm_id)
        return TagNamespacePermission.from_orm(db_perm) if db_perm else None

    def list_permissions_for_namespace(self, db: Session, *, namespace_id: UUID, skip: int = 0, limit: Optional[int] = None) -> List[TagNamespacePermission]:
        # Add skip/limit to repository method if needed, for now fetching all for a namespace.
        db_perms = self._permission_repo.get_permissions_for_namespace(db, namespace_id=namespace_id)
        # Apply skip/limit here if repo doesn't support it directly for this specific query
        return [TagNamespacePermission.from_orm(p) for p in db_perms[skip : skip + limit if limit is not None else None]]

    def update_namespace_permission(self, db: Session, *, perm_id: UUID, perm_in: TagNamespacePermissionUpdate, user_email: Optional[str]) -> Optional[TagNamespacePermission]:
        db_perm = self._permission_repo.get(db, id=perm_id)
        if not db_perm:
            return None
        
        # If group_id is changing, ensure it doesn't conflict with an existing perm for the new group_id on the same namespace
        if perm_in.group_id and perm_in.group_id != db_perm.group_id:
            existing_perm_for_new_group = self._permission_repo.get_by_namespace_and_group(
                db, namespace_id=db_perm.namespace_id, group_id=perm_in.group_id
            )
            if existing_perm_for_new_group and existing_perm_for_new_group.id != perm_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, 
                                    detail=f"A permission for group '{perm_in.group_id}' on this namespace already exists.")

        updated_db_perm = self._permission_repo.update(db, db_obj=db_perm, obj_in=perm_in) # user_email not used in CRUDBase.update
        db.commit()
        db.refresh(updated_db_perm)
        return TagNamespacePermission.from_orm(updated_db_perm)

    def remove_permission_from_namespace(self, db: Session, *, perm_id: UUID) -> bool:
        deleted_count = self._permission_repo.remove(db, id=perm_id)
        if deleted_count:
            db.commit()
            return True
        return False

    # --- Entity-Tag Relationship Methods ---
    def get_entities_for_tag(
        self, 
        db: Session, 
        *, 
        tag_id: UUID, 
        entity_type: Optional[str] = None
    ) -> List[dict]:
        """Get all entities that have a specific tag assigned.
        
        Returns a list of dicts containing entity_id, entity_type, assigned_value, 
        assigned_by, and assigned_at.
        """
        from src.db_models.tags import EntityTagAssociationDb
        
        query = db.query(EntityTagAssociationDb).filter(EntityTagAssociationDb.tag_id == tag_id)
        if entity_type:
            query = query.filter(EntityTagAssociationDb.entity_type == entity_type)
        
        associations = query.all()
        return [
            {
                "entity_id": assoc.entity_id,
                "entity_type": assoc.entity_type,
                "assigned_value": assoc.assigned_value,
                "assigned_by": assoc.assigned_by,
                "assigned_at": assoc.assigned_at.isoformat() if assoc.assigned_at else None
            }
            for assoc in associations
        ]

    # --- SearchableAsset Implementation ---
    def _build_search_index_item(self, tag_db_obj: TagDb) -> Optional[SearchIndexItem]:
        """Build a SearchIndexItem from a TagDb model."""
        if not tag_db_obj.id or not tag_db_obj.name or not tag_db_obj.namespace:
            logger.warning(
                f"Skipping tag for search indexing due to missing id, name, or namespace: {tag_db_obj}"
            )
            return None
        tag_api_model = Tag.from_orm(tag_db_obj)
        extra_data = {
            "category": tag_api_model.namespace_name or DEFAULT_NAMESPACE_NAME,
            "status": tag_api_model.status.value if tag_api_model.status else "",
        }
        search_query = f"tag:{tag_api_model.fully_qualified_name}"
        return SearchIndexItem(
            id=f"tag::{tag_api_model.id}",
            type="tag",
            feature_id="tags",
            title=tag_api_model.fully_qualified_name,
            description=tag_api_model.description
            or f"Tag: {tag_api_model.name} in namespace {tag_api_model.namespace_name}",
            link=f"/search?tab=app&app_query={search_query}",
            tags=[
                tag_api_model.name,
                tag_api_model.namespace_name or DEFAULT_NAMESPACE_NAME,
                f"status:{tag_api_model.status.value}",
            ],
            extra_data=extra_data,
        )

    def _update_search_index(self, tag_db_obj: TagDb) -> None:
        """Upsert a single tag into the search index."""
        item = self._build_search_index_item(tag_db_obj)
        if item:
            self._notify_index_upsert(item)

    def get_search_index_items(self) -> List[SearchIndexItem]:
        logger.info("TagsManager: Fetching tags for search indexing...")
        items: List[SearchIndexItem] = []
        try:
            session_factory = get_session_factory()
            if not session_factory:
                logger.warning("Session factory not available; cannot index tags.")
                return []

            with session_factory() as db:
                # Fetch all tags with their namespaces for FQN
                db_tags = self._tag_repo.get_multi_with_filters(db, limit=10000)

                for tag_db_obj in db_tags:
                    item = self._build_search_index_item(tag_db_obj)
                    if item:
                        items.append(item)

            logger.info(f"TagsManager: Prepared {len(items)} tags for search index.")
            return items
        except Exception as e:
            logger.error(
                f"TagsManager: Error fetching or mapping tags for search: {e}", exc_info=True
            )
            return []