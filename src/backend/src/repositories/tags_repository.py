from typing import List, Optional, Tuple, Union, Dict, Any, Type
from uuid import UUID
import json # For converting possible_values to JSON string for DB

from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import select, func, delete, update

from src.common.repository import CRUDBase
from src.db_models.tags import TagDb, TagNamespaceDb, TagNamespacePermissionDb, EntityTagAssociationDb
from src.models.tags import (
    TagCreate, TagUpdate, TagStatus, TagNamespaceCreate, TagNamespaceUpdate,
    TagNamespacePermissionCreate, TagNamespacePermissionUpdate, TagAccessLevel,
    AssignedTagCreate, AssignedTag, DEFAULT_NAMESPACE_NAME, TAG_NAMESPACE_SEPARATOR
)
from src.common.logging import get_logger
from pydantic import BaseModel

logger = get_logger(__name__)

class TagNamespaceRepository(CRUDBase[TagNamespaceDb, TagNamespaceCreate, TagNamespaceUpdate]):
    def get_by_name(self, db: Session, *, name: str) -> Optional[TagNamespaceDb]:
        return db.query(TagNamespaceDb).filter(TagNamespaceDb.name == name).first()

    def get_or_create_default_namespace(self, db: Session, *, user_email: Optional[str]) -> TagNamespaceDb:
        default_ns = self.get_by_name(db, name=DEFAULT_NAMESPACE_NAME)
        if not default_ns:
            logger.info(f"Default namespace '{DEFAULT_NAMESPACE_NAME}' not found, creating it.")
            default_ns_create = TagNamespaceCreate(name=DEFAULT_NAMESPACE_NAME, description="Default system namespace")
            default_ns = self.create(db, obj_in=default_ns_create, user_email=user_email)
            db.commit() # Commit immediately after creating default
            logger.info(f"Default namespace '{DEFAULT_NAMESPACE_NAME}' created with ID {default_ns.id}.")
        return default_ns

    def create(self, db: Session, *, obj_in: TagNamespaceCreate, user_email: Optional[str]) -> TagNamespaceDb:
        db_obj = TagNamespaceDb(
            **obj_in.model_dump(),
            created_by=user_email
        )
        db.add(db_obj)
        # db.commit() # Commit is handled by the caller/manager
        # db.refresh(db_obj)
        return db_obj

    def update(
        self, db: Session, *, db_obj: TagNamespaceDb, obj_in: Union[TagNamespaceUpdate, Dict[str, Any]], user_email: Optional[str]
    ) -> TagNamespaceDb:
        db_obj = super().update(db, db_obj=db_obj, obj_in=obj_in) # user_email is not part of CRUDBase.update
        # updated_at is handled by DB onupdate, created_by not changed on update
        return db_obj


class TagRepository(CRUDBase[TagDb, TagCreate, TagUpdate]):
    def get_by_fully_qualified_name(self, db: Session, *, fqn: str) -> Optional[TagDb]:
        parts = fqn.split(TAG_NAMESPACE_SEPARATOR, 1)
        if len(parts) == 2:
            namespace_name, tag_name = parts
        else:
            namespace_name = DEFAULT_NAMESPACE_NAME
            tag_name = fqn
        
        return (
            db.query(TagDb)
            .join(TagNamespaceDb, TagDb.namespace_id == TagNamespaceDb.id)
            .filter(TagNamespaceDb.name == namespace_name, TagDb.name == tag_name)
            .options(joinedload(TagDb.namespace)) # Eager load namespace
            .first()
        )

    def create_with_namespace(self, db: Session, *, obj_in: TagCreate, namespace_id: UUID, user_email: Optional[str]) -> TagDb:
        # obj_in.possible_values is already a list from Pydantic model validation
        db_obj_data = obj_in.model_dump(exclude_none=True, exclude={'namespace_name', 'namespace_id'})
        db_obj = TagDb(
            **db_obj_data,
            namespace_id=namespace_id,
            created_by=user_email,
        )
        db.add(db_obj)
        # db.commit() # Commit handled by caller/manager
        # db.refresh(db_obj)
        return db_obj
    
    def find_or_create_tag(
        self, db: Session, *, 
        tag_name: str, 
        namespace_name: Optional[str], 
        user_email: Optional[str],
        default_namespace_id: UUID,
        description: Optional[str] = None,
        status: TagStatus = TagStatus.ACTIVE,
        possible_values: Optional[List[str]] = None
    ) -> TagDb:
        """Finds a tag by name and namespace name, or creates it if not found."""
        effective_namespace_name = namespace_name or DEFAULT_NAMESPACE_NAME
        
        tag_db = (
            db.query(TagDb)
            .join(TagNamespaceDb, TagDb.namespace_id == TagNamespaceDb.id)
            .filter(TagNamespaceDb.name == effective_namespace_name, TagDb.name == tag_name)
            .options(selectinload(TagDb.namespace)) # Eager load for potential fqn construction
            .first()
        )

        if tag_db:
            return tag_db
        else:
            logger.info(f"Tag '{tag_name}' not found in namespace '{effective_namespace_name}'. Creating it.")
            
            # Determine the namespace_id to use for creation
            if namespace_name:
                ns_repo = TagNamespaceRepository(TagNamespaceDb)
                namespace_db_obj = ns_repo.get_by_name(db, name=namespace_name)
                if not namespace_db_obj: # Should not happen if namespace_name is validated before this call
                    raise ValueError(f"Namespace '{namespace_name}' not found during tag creation.")
                ns_id_to_use = namespace_db_obj.id
            else:
                ns_id_to_use = default_namespace_id

            tag_create_model = TagCreate(
                name=tag_name,
                namespace_id=ns_id_to_use, # Provide namespace_id directly
                description=description,
                status=status,
                possible_values=possible_values
            )
            return self.create_with_namespace(db, obj_in=tag_create_model, namespace_id=ns_id_to_use, user_email=user_email)

    def get_multi_with_filters(
        self, db: Session, *, 
        skip: int = 0, limit: int = 100, 
        namespace_id: Optional[UUID] = None,
        namespace_name: Optional[str] = None,
        name_contains: Optional[str] = None,
        status: Optional[TagStatus] = None,
        parent_id: Optional[UUID] = None,
        is_root: Optional[bool] = None # True to fetch only root tags (parent_id is None)
    ) -> List[TagDb]:
        query = db.query(TagDb).options(selectinload(TagDb.namespace), selectinload(TagDb.parent), selectinload(TagDb.children))

        if namespace_id:
            query = query.filter(TagDb.namespace_id == namespace_id)
        if namespace_name:
            query = query.join(TagNamespaceDb, TagDb.namespace_id == TagNamespaceDb.id).filter(TagNamespaceDb.name == namespace_name)
        if name_contains:
            query = query.filter(TagDb.name.ilike(f"%{name_contains}%"))
        if status:
            query = query.filter(TagDb.status == status)
        if parent_id:
            query = query.filter(TagDb.parent_id == parent_id)
        if is_root is not None:
            if is_root:
                query = query.filter(TagDb.parent_id.is_(None))
            else:
                 query = query.filter(TagDb.parent_id.isnot(None))
                 
        return query.order_by(TagDb.name).offset(skip).limit(limit).all()
    
    def get(self, db: Session, id: Any) -> Optional[TagDb]:
        return db.query(self.model).options(
            selectinload(self.model.namespace),
            selectinload(self.model.parent),
            selectinload(self.model.children)
            ).filter(self.model.id == id).first()

    def update(
        self, db: Session, *, db_obj: TagDb, obj_in: Union[TagUpdate, Dict[str, Any]], user_email: Optional[str]
    ) -> TagDb:
        obj_data = obj_in if isinstance(obj_in, dict) else obj_in.model_dump(exclude_unset=True)
        
        # Handle possible_values conversion if it's a string (already handled by Pydantic model but good to be robust)
        if 'possible_values' in obj_data and isinstance(obj_data['possible_values'], list):
            pass # Already a list
        elif 'possible_values' in obj_data and obj_data['possible_values'] is None:
            pass # Explicitly setting to None
        # Pydantic model should have handled string to list conversion for possible_values

        # Prevent changing namespace_id directly via generic update
        if 'namespace_id' in obj_data:
            del obj_data['namespace_id']
        if 'namespace_name' in obj_data:
             del obj_data['namespace_name']

        return super().update(db, db_obj=db_obj, obj_in=obj_data)


class TagNamespacePermissionRepository(CRUDBase[TagNamespacePermissionDb, TagNamespacePermissionCreate, TagNamespacePermissionUpdate]):
    def get_by_namespace_and_group(self, db: Session, *, namespace_id: UUID, group_id: str) -> Optional[TagNamespacePermissionDb]:
        return db.query(TagNamespacePermissionDb).filter(
            TagNamespacePermissionDb.namespace_id == namespace_id,
            TagNamespacePermissionDb.group_id == group_id
        ).first()

    def get_permissions_for_namespace(self, db: Session, *, namespace_id: UUID) -> List[TagNamespacePermissionDb]:
        return db.query(TagNamespacePermissionDb).filter(TagNamespacePermissionDb.namespace_id == namespace_id).all()

    def get_permissions_for_user(self, db: Session, *, namespace_id: UUID, user_groups: List[str]) -> Optional[TagAccessLevel]:
        """Determines the highest access level for a user based on their group memberships for a specific namespace."""
        if not user_groups:
            return None

        permissions = (
            db.query(TagNamespacePermissionDb.access_level)
            .filter(
                TagNamespacePermissionDb.namespace_id == namespace_id,
                TagNamespacePermissionDb.group_id.in_(user_groups)
            )
            .all()
        )
        
        access_levels_found = [TagAccessLevel(p[0]) for p in permissions]
        if not access_levels_found:
            return None

        # Determine highest permission (Admin > Read/Write > Read-Only)
        if TagAccessLevel.ADMIN in access_levels_found:
            return TagAccessLevel.ADMIN
        if TagAccessLevel.READ_WRITE in access_levels_found:
            return TagAccessLevel.READ_WRITE
        if TagAccessLevel.READ_ONLY in access_levels_found:
            return TagAccessLevel.READ_ONLY
        return None
    
    def create(self, db: Session, *, obj_in: TagNamespacePermissionCreate, user_email: Optional[str]) -> TagNamespacePermissionDb:
        db_obj_data = obj_in.model_dump()
        # namespace_id might be part of obj_in or might need to be passed if creating via /namespaces/{ns_id}/permissions
        # For now, assuming it's in obj_in or handled by manager before calling repo.
        db_obj = TagNamespacePermissionDb(**db_obj_data, created_by=user_email)
        db.add(db_obj)
        return db_obj


class EntityTagAssociationRepository(CRUDBase[EntityTagAssociationDb, BaseModel, BaseModel]): # No standard Pydantic models for create/update yet
    def add_tag_to_entity(
        self, db: Session, *, 
        entity_id: str, 
        entity_type: str, 
        tag_id: UUID, 
        assigned_value: Optional[str] = None,
        assigned_by: Optional[str] = None
    ) -> EntityTagAssociationDb:
        # Check if association already exists to prevent duplicates by unique constraint
        existing_assoc = db.query(EntityTagAssociationDb).filter_by(
            entity_id=entity_id, 
            entity_type=entity_type, 
            tag_id=tag_id
            # Not filtering by assigned_value for existence check, as one tag per entity
        ).first()
        
        if existing_assoc:
            # If it exists, update assigned_value and assigned_by if different
            if (assigned_value is not None and existing_assoc.assigned_value != assigned_value) or \
               (assigned_by is not None and existing_assoc.assigned_by != assigned_by):
                existing_assoc.assigned_value = assigned_value
                existing_assoc.assigned_by = assigned_by
                # assigned_at is automatically updated by onupdate=func.now() if that was set, else set manually
                # existing_assoc.assigned_at = func.now() # if needed
                db.add(existing_assoc)
            return existing_assoc
        
        assoc = EntityTagAssociationDb(
            entity_id=entity_id,
            entity_type=entity_type,
            tag_id=tag_id,
            assigned_value=assigned_value,
            assigned_by=assigned_by
        )
        db.add(assoc)
        # db.commit() # Handled by manager
        # db.refresh(assoc)
        return assoc

    def remove_tag_from_entity(self, db: Session, *, entity_id: str, entity_type: str, tag_id: UUID) -> bool:
        assoc = db.query(EntityTagAssociationDb).filter_by(
            entity_id=entity_id, 
            entity_type=entity_type, 
            tag_id=tag_id
        ).first()
        if assoc:
            db.delete(assoc)
            # db.commit() # Handled by manager
            return True
        return False

    def get_tags_for_entity(self, db: Session, *, entity_id: str, entity_type: str) -> List[TagDb]:
        return (
            db.query(TagDb)
            .join(EntityTagAssociationDb, TagDb.id == EntityTagAssociationDb.tag_id)
            .filter(
                EntityTagAssociationDb.entity_id == entity_id,
                EntityTagAssociationDb.entity_type == entity_type
            )
            .options(selectinload(TagDb.namespace)) # Eager load namespace for FQN
            .all()
        )
    
    def get_assigned_tags_for_entity(self, db: Session, *, entity_id: str, entity_type: str) -> List[AssignedTag]:
        results = (
            db.query(
                TagDb.id,
                TagDb.name,
                TagDb.namespace_id,
                TagNamespaceDb.name.label("namespace_name"),
                TagDb.status,
                EntityTagAssociationDb.assigned_value,
                EntityTagAssociationDb.assigned_by,
                EntityTagAssociationDb.assigned_at
            )
            .join(EntityTagAssociationDb, TagDb.id == EntityTagAssociationDb.tag_id)
            .join(TagNamespaceDb, TagDb.namespace_id == TagNamespaceDb.id)
            .filter(
                EntityTagAssociationDb.entity_id == entity_id,
                EntityTagAssociationDb.entity_type == entity_type
            )
            .all()
        )
        
        assigned_tags = []
        for row in results:
            fqn = f"{row.namespace_name}{TAG_NAMESPACE_SEPARATOR}{row.name}"
            assigned_tags.append(
                AssignedTag(
                    tag_id=row.id,
                    tag_name=row.name,
                    namespace_id=row.namespace_id,
                    namespace_name=row.namespace_name,
                    status=TagStatus(row.status), # Ensure status is cast to Enum
                    fully_qualified_name=fqn,
                    assigned_value=row.assigned_value,
                    assigned_by=row.assigned_by,
                    assigned_at=row.assigned_at
                )
            )
        return assigned_tags

    def get_assigned_tags_for_entities(self, db: Session, *, entity_ids: List[str], entity_type: str) -> dict:
        """Batch-load tags for multiple entities. Returns {entity_id: [AssignedTag, ...]}."""
        if not entity_ids:
            return {}
        results = (
            db.query(
                EntityTagAssociationDb.entity_id,
                TagDb.id,
                TagDb.name,
                TagDb.namespace_id,
                TagNamespaceDb.name.label("namespace_name"),
                TagDb.status,
                EntityTagAssociationDb.assigned_value,
                EntityTagAssociationDb.assigned_by,
                EntityTagAssociationDb.assigned_at
            )
            .join(EntityTagAssociationDb, TagDb.id == EntityTagAssociationDb.tag_id)
            .join(TagNamespaceDb, TagDb.namespace_id == TagNamespaceDb.id)
            .filter(
                EntityTagAssociationDb.entity_id.in_(entity_ids),
                EntityTagAssociationDb.entity_type == entity_type
            )
            .all()
        )
        tags_map: dict = {eid: [] for eid in entity_ids}
        for row in results:
            fqn = f"{row.namespace_name}{TAG_NAMESPACE_SEPARATOR}{row.name}"
            tags_map.setdefault(row.entity_id, []).append(
                AssignedTag(
                    tag_id=row.id,
                    tag_name=row.name,
                    namespace_id=row.namespace_id,
                    namespace_name=row.namespace_name,
                    status=TagStatus(row.status),
                    fully_qualified_name=fqn,
                    assigned_value=row.assigned_value,
                    assigned_by=row.assigned_by,
                    assigned_at=row.assigned_at
                )
            )
        return tags_map

    def get_entities_for_tag(self, db: Session, *, tag_id: UUID, entity_type: Optional[str] = None) -> List[Tuple[str, str]]:
        query = db.query(EntityTagAssociationDb.entity_id, EntityTagAssociationDb.entity_type).filter(
            EntityTagAssociationDb.tag_id == tag_id
        )
        if entity_type:
            query = query.filter(EntityTagAssociationDb.entity_type == entity_type)
        return query.all()
    
    def set_tags_for_entity(
        self, 
        db: Session, *, 
        entity_id: str, 
        entity_type: str, 
        tags_data: List[AssignedTagCreate], 
        user_email: Optional[str],
        tag_repo: 'TagRepository', # Pass TagRepository instance
        ns_repo: 'TagNamespaceRepository' # Pass TagNamespaceRepository instance
    ) -> List[AssignedTag]:
        """Replaces all tags for an entity with the provided list."""
        # 1. Get current tags for the entity
        current_assocs = db.query(EntityTagAssociationDb).filter_by(entity_id=entity_id, entity_type=entity_type).all()
        current_tag_ids = {assoc.tag_id: assoc for assoc in current_assocs}

        updated_tag_ids = set()
        final_assigned_tags: List[AssignedTag] = []
        default_namespace = ns_repo.get_or_create_default_namespace(db, user_email=user_email)

        for tag_assign_data in tags_data:
            tag_db_obj: Optional[TagDb] = None
            if tag_assign_data.tag_id:
                tag_db_obj = tag_repo.get(db, id=tag_assign_data.tag_id)
                if not tag_db_obj:
                    logger.warning(f"Tag with ID {tag_assign_data.tag_id} not found. Skipping.")
                    continue # Or raise error
            elif tag_assign_data.tag_fqn:
                parts = tag_assign_data.tag_fqn.split(TAG_NAMESPACE_SEPARATOR, 1)
                tag_name_from_fqn = parts[-1]
                namespace_name_from_fqn = parts[0] if len(parts) > 1 else None
                
                tag_db_obj = tag_repo.find_or_create_tag(
                    db,
                    tag_name=tag_name_from_fqn,
                    namespace_name=namespace_name_from_fqn,
                    user_email=user_email,
                    default_namespace_id=default_namespace.id
                )
                # Flush to get database-generated values if tag was just created
                db.flush()
            else:
                # Should be caught by Pydantic validator, but good to be safe
                logger.warning(f"Skipping tag assignment for {entity_id} due to missing tag_id or tag_fqn.")
                continue

            if not tag_db_obj:
                 logger.warning(f"Could not find or create tag for FQN {tag_assign_data.tag_fqn} or ID {tag_assign_data.tag_id}. Skipping.")
                 continue
            
            updated_tag_ids.add(tag_db_obj.id)
            assoc = self.add_tag_to_entity(
                db,
                entity_id=entity_id,
                entity_type=entity_type,
                tag_id=tag_db_obj.id,
                assigned_value=tag_assign_data.assigned_value,
                assigned_by=user_email
            )

            # Flush to get database-generated values (like assigned_at timestamp)
            db.flush()

            # Re-fetch namespace if it wasn't loaded on tag_db_obj (e.g. from create)
            if not tag_db_obj.namespace:
                tag_db_obj.namespace = ns_repo.get(db, id=tag_db_obj.namespace_id)
                
            final_assigned_tags.append(AssignedTag(
                tag_id=tag_db_obj.id,
                tag_name=tag_db_obj.name,
                namespace_id=tag_db_obj.namespace_id,
                namespace_name=tag_db_obj.namespace.name if tag_db_obj.namespace else DEFAULT_NAMESPACE_NAME,
                status=TagStatus(tag_db_obj.status),
                fully_qualified_name=f"{(tag_db_obj.namespace.name if tag_db_obj.namespace else DEFAULT_NAMESPACE_NAME)}{TAG_NAMESPACE_SEPARATOR}{tag_db_obj.name}",
                assigned_value=assoc.assigned_value,
                assigned_by=assoc.assigned_by,
                assigned_at=assoc.assigned_at
            ))

        # 2. Remove tags that were previously associated but are not in the new list
        for tag_id_to_remove, assoc_to_remove in current_tag_ids.items():
            if tag_id_to_remove not in updated_tag_ids:
                db.delete(assoc_to_remove)
        
        # db.commit() # Handled by manager
        return final_assigned_tags


# Instantiate repositories (can be done here or in a central place like dependencies.py)
tag_namespace_repo = TagNamespaceRepository(TagNamespaceDb)
tag_repo = TagRepository(TagDb)
tag_namespace_permission_repo = TagNamespacePermissionRepository(TagNamespacePermissionDb)
entity_tag_repo = EntityTagAssociationRepository(EntityTagAssociationDb) 