from typing import List, Optional, Union, Dict, Any, Type

from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.common.repository import CRUDBase
from src.db_models.metadata import (
    RichTextMetadataDb, 
    LinkMetadataDb, 
    DocumentMetadataDb,
    MetadataAttachmentDb,
)
from src.models.metadata import (
    RichTextCreate, RichTextUpdate,
    LinkCreate, LinkUpdate,
    DocumentCreate,
    MetadataAttachmentCreate,
)


def _remove_all_for_entity(db: Session, model, *, entity_type: str, entity_id: str) -> int:
    """Delete every row of ``model`` stored for an entity (used when the entity is deleted)."""
    return (
        db.query(model)
        .filter(model.entity_type == entity_type, model.entity_id == entity_id)
        .delete(synchronize_session=False)
    )


class RichTextRepository(CRUDBase[RichTextMetadataDb, RichTextCreate, RichTextUpdate]):
    def remove_all_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> int:
        return _remove_all_for_entity(
            db, RichTextMetadataDb, entity_type=entity_type, entity_id=entity_id,
        )

    def list_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> List[RichTextMetadataDb]:
        """List rich texts directly attached to an entity (not shared assets attached via junction)."""
        return (
            db.query(RichTextMetadataDb)
            .filter(
                RichTextMetadataDb.entity_type == entity_type, 
                RichTextMetadataDb.entity_id == entity_id,
                RichTextMetadataDb.is_shared == False  # Direct attachments only
            )
            .order_by(RichTextMetadataDb.level.asc(), RichTextMetadataDb.created_at.desc())
            .all()
        )
    
    def list_shared(self, db: Session, *, entity_type: Optional[str] = None) -> List[RichTextMetadataDb]:
        """List all shared rich text assets, optionally filtered by entity type."""
        query = db.query(RichTextMetadataDb).filter(RichTextMetadataDb.is_shared == True)
        if entity_type:
            query = query.filter(RichTextMetadataDb.entity_type == entity_type)
        return query.order_by(RichTextMetadataDb.level.asc(), RichTextMetadataDb.title.asc()).all()
    
    def get_by_ids(self, db: Session, *, ids: List[str]) -> List[RichTextMetadataDb]:
        """Get multiple rich texts by their IDs."""
        if not ids:
            return []
        return db.query(RichTextMetadataDb).filter(RichTextMetadataDb.id.in_(ids)).all()
    
    def list_inheritable_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str, max_level: int
    ) -> List[RichTextMetadataDb]:
        """List rich texts that can be inherited (inheritable=True, level <= max_level)."""
        return (
            db.query(RichTextMetadataDb)
            .filter(
                RichTextMetadataDb.entity_type == entity_type,
                RichTextMetadataDb.entity_id == entity_id,
                RichTextMetadataDb.inheritable == True,
                RichTextMetadataDb.level <= max_level
            )
            .order_by(RichTextMetadataDb.level.asc(), RichTextMetadataDb.created_at.desc())
            .all()
        )


class LinkRepository(CRUDBase[LinkMetadataDb, LinkCreate, LinkUpdate]):
    def remove_all_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> int:
        return _remove_all_for_entity(
            db, LinkMetadataDb, entity_type=entity_type, entity_id=entity_id,
        )

    def list_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> List[LinkMetadataDb]:
        """List links directly attached to an entity."""
        return (
            db.query(LinkMetadataDb)
            .filter(
                LinkMetadataDb.entity_type == entity_type, 
                LinkMetadataDb.entity_id == entity_id,
                LinkMetadataDb.is_shared == False
            )
            .order_by(LinkMetadataDb.level.asc(), LinkMetadataDb.created_at.desc())
            .all()
        )
    
    def list_shared(self, db: Session, *, entity_type: Optional[str] = None) -> List[LinkMetadataDb]:
        """List all shared link assets."""
        query = db.query(LinkMetadataDb).filter(LinkMetadataDb.is_shared == True)
        if entity_type:
            query = query.filter(LinkMetadataDb.entity_type == entity_type)
        return query.order_by(LinkMetadataDb.level.asc(), LinkMetadataDb.title.asc()).all()
    
    def get_by_ids(self, db: Session, *, ids: List[str]) -> List[LinkMetadataDb]:
        """Get multiple links by their IDs."""
        if not ids:
            return []
        return db.query(LinkMetadataDb).filter(LinkMetadataDb.id.in_(ids)).all()
    
    def list_inheritable_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str, max_level: int
    ) -> List[LinkMetadataDb]:
        """List links that can be inherited."""
        return (
            db.query(LinkMetadataDb)
            .filter(
                LinkMetadataDb.entity_type == entity_type,
                LinkMetadataDb.entity_id == entity_id,
                LinkMetadataDb.inheritable == True,
                LinkMetadataDb.level <= max_level
            )
            .order_by(LinkMetadataDb.level.asc(), LinkMetadataDb.created_at.desc())
            .all()
        )


class DocumentRepository(CRUDBase[DocumentMetadataDb, DocumentCreate, DocumentCreate]):
    def remove_all_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str,
    ) -> List[str]:
        """Delete the entity's documents; returns the volume paths of their uploaded files.

        Imported Markdown documents point to their source file, which isn't the
        app's to delete: their paths are left out.
        """
        paths = [
            path for (path,) in db.query(DocumentMetadataDb.storage_path).filter(
                DocumentMetadataDb.entity_type == entity_type,
                DocumentMetadataDb.entity_id == entity_id,
                DocumentMetadataDb.source_path.is_(None),
            )
        ]
        _remove_all_for_entity(
            db, DocumentMetadataDb, entity_type=entity_type, entity_id=entity_id,
        )
        return paths

    def imported_ids_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str,
    ) -> List[str]:
        """Ids of the entity's imported Markdown documents (the ones in the search index)."""
        return [
            str(doc_id) for (doc_id,) in db.query(DocumentMetadataDb.id).filter(
                DocumentMetadataDb.entity_type == entity_type,
                DocumentMetadataDb.entity_id == entity_id,
                DocumentMetadataDb.source_path.isnot(None),
            )
        ]

    def list_by_source_path(self, db: Session, *, source_path: str) -> List[DocumentMetadataDb]:
        """Documents imported from one source file (one per linked entity)."""
        return (
            db.query(DocumentMetadataDb)
            .filter(DocumentMetadataDb.source_path == source_path)
            .all()
        )

    def list_imported(self, db: Session) -> List[DocumentMetadataDb]:
        """Every document imported from a Markdown file."""
        return (
            db.query(DocumentMetadataDb)
            .filter(DocumentMetadataDb.source_path.isnot(None))
            .all()
        )

    def list_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> List[DocumentMetadataDb]:
        """List documents directly attached to an entity."""
        return (
            db.query(DocumentMetadataDb)
            .filter(
                DocumentMetadataDb.entity_type == entity_type, 
                DocumentMetadataDb.entity_id == entity_id,
                DocumentMetadataDb.is_shared == False
            )
            .order_by(DocumentMetadataDb.level.asc(), DocumentMetadataDb.created_at.desc())
            .all()
        )
    
    def list_shared(self, db: Session, *, entity_type: Optional[str] = None) -> List[DocumentMetadataDb]:
        """List all shared document assets."""
        query = db.query(DocumentMetadataDb).filter(DocumentMetadataDb.is_shared == True)
        if entity_type:
            query = query.filter(DocumentMetadataDb.entity_type == entity_type)
        return query.order_by(DocumentMetadataDb.level.asc(), DocumentMetadataDb.title.asc()).all()
    
    def get_by_ids(self, db: Session, *, ids: List[str]) -> List[DocumentMetadataDb]:
        """Get multiple documents by their IDs."""
        if not ids:
            return []
        return db.query(DocumentMetadataDb).filter(DocumentMetadataDb.id.in_(ids)).all()
    
    def list_inheritable_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str, max_level: int
    ) -> List[DocumentMetadataDb]:
        """List documents that can be inherited."""
        return (
            db.query(DocumentMetadataDb)
            .filter(
                DocumentMetadataDb.entity_type == entity_type,
                DocumentMetadataDb.entity_id == entity_id,
                DocumentMetadataDb.inheritable == True,
                DocumentMetadataDb.level <= max_level
            )
            .order_by(DocumentMetadataDb.level.asc(), DocumentMetadataDb.created_at.desc())
            .all()
        )


class MetadataAttachmentRepository(CRUDBase[MetadataAttachmentDb, MetadataAttachmentCreate, MetadataAttachmentCreate]):
    """Repository for managing metadata attachments (shared asset links)."""
    
    def remove_all_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> int:
        return _remove_all_for_entity(
            db, MetadataAttachmentDb, entity_type=entity_type, entity_id=entity_id,
        )

    def list_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> List[MetadataAttachmentDb]:
        """List all attachments for an entity."""
        return (
            db.query(MetadataAttachmentDb)
            .filter(
                MetadataAttachmentDb.entity_type == entity_type,
                MetadataAttachmentDb.entity_id == entity_id
            )
            .order_by(MetadataAttachmentDb.created_at.desc())
            .all()
        )
    
    def list_for_entity_by_type(
        self, db: Session, *, entity_type: str, entity_id: str, asset_type: str
    ) -> List[MetadataAttachmentDb]:
        """List attachments for an entity filtered by asset type."""
        return (
            db.query(MetadataAttachmentDb)
            .filter(
                MetadataAttachmentDb.entity_type == entity_type,
                MetadataAttachmentDb.entity_id == entity_id,
                MetadataAttachmentDb.asset_type == asset_type
            )
            .order_by(MetadataAttachmentDb.created_at.desc())
            .all()
        )
    
    def get_attachment(
        self, db: Session, *, entity_type: str, entity_id: str, asset_type: str, asset_id: str
    ) -> Optional[MetadataAttachmentDb]:
        """Get a specific attachment by entity and asset."""
        return (
            db.query(MetadataAttachmentDb)
            .filter(
                MetadataAttachmentDb.entity_type == entity_type,
                MetadataAttachmentDb.entity_id == entity_id,
                MetadataAttachmentDb.asset_type == asset_type,
                MetadataAttachmentDb.asset_id == asset_id
            )
            .first()
        )
    
    def delete_attachment(
        self, db: Session, *, entity_type: str, entity_id: str, asset_type: str, asset_id: str
    ) -> bool:
        """Delete a specific attachment."""
        attachment = self.get_attachment(
            db, entity_type=entity_type, entity_id=entity_id, asset_type=asset_type, asset_id=asset_id
        )
        if attachment:
            db.delete(attachment)
            return True
        return False


# Instantiate repositories
rich_text_repo = RichTextRepository(RichTextMetadataDb)
link_repo = LinkRepository(LinkMetadataDb)
document_repo = DocumentRepository(DocumentMetadataDb)
attachment_repo = MetadataAttachmentRepository(MetadataAttachmentDb)


