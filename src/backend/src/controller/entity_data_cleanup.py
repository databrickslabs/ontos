"""Remove (or move) what an entity stores in the polymorphic tables when it is deleted.

Notes, links, documents, attachments, cost items and tag assignments are keyed
by ``(entity_type, entity_id)`` with no foreign key to the entity, so each
delete path removes them itself (#1431). Every entity kind that renders the
metadata or cost panels, or can be tagged, calls ``remove_entity_data`` (or
``remove_entities_data`` for many ids) from its delete, inside the delete's
transaction. Shared library records are stored under the shared id, not the
entity's, and stay.
"""
from typing import Dict, Iterable, List, Optional, Tuple

from databricks.sdk import WorkspaceClient
from sqlalchemy.orm import Session

from src.controller.metadata_manager import MetadataManager
from src.db_models.costs import CostItemDb
from src.db_models.metadata import (
    DocumentMetadataDb,
    LinkMetadataDb,
    MetadataAttachmentDb,
    RichTextMetadataDb,
)
from src.db_models.tags import EntityTagAssociationDb

# Count key -> table. Documents are read first for their volume paths.
_TABLES = (
    ("rich_texts", RichTextMetadataDb),
    ("links", LinkMetadataDb),
    ("documents", DocumentMetadataDb),
    ("attachments", MetadataAttachmentDb),
    ("cost_items", CostItemDb),
    ("tags", EntityTagAssociationDb),
)
# Keeps each IN list well under the bind-parameter limits of Postgres and SQLite.
_CHUNK_SIZE = 500


def _unique_ids(entity_ids: Iterable) -> List[str]:
    return list(dict.fromkeys(str(entity_id) for entity_id in entity_ids if entity_id))


def remove_entities_rows(
    db: Session, *, entity_type: str, entity_ids: Iterable,
) -> Tuple[Dict[str, int], List[str]]:
    """Delete the rows of these entities in ``db``'s transaction (no commit).

    Returns the rows removed per kind and the volume paths of the removed
    documents. Callers that delete inside a savepoint queue the paths with
    ``MetadataManager.delete_document_files_after_commit`` once the savepoint
    is released, so a rolled-back savepoint keeps the files.
    """
    ids = _unique_ids(entity_ids)
    removed = {key: 0 for key, _ in _TABLES}
    paths: List[str] = []
    for start in range(0, len(ids), _CHUNK_SIZE):
        chunk = ids[start:start + _CHUNK_SIZE]
        paths.extend(
            path for (path,) in db.query(DocumentMetadataDb.storage_path).filter(
                DocumentMetadataDb.entity_type == entity_type,
                DocumentMetadataDb.entity_id.in_(chunk),
            ).all() if path
        )
        for key, model in _TABLES:
            removed[key] += db.query(model).filter(
                model.entity_type == entity_type, model.entity_id.in_(chunk),
            ).delete(synchronize_session=False)
    return removed, paths


def remove_entity_rows(
    db: Session, *, entity_type: str, entity_id: str,
) -> Tuple[Dict[str, int], List[str]]:
    """``remove_entities_rows`` for one entity."""
    return remove_entities_rows(db, entity_type=entity_type, entity_ids=[entity_id])


def remove_entities_data(
    db: Session,
    *,
    entity_type: str,
    entity_ids: Iterable,
    ws: Optional[WorkspaceClient] = None,
    metadata_manager: Optional[MetadataManager] = None,
) -> Dict[str, int]:
    """Delete the entities' rows in ``db``'s transaction and their document files after the commit.

    The files are kept if the transaction rolls back. Returns the rows removed per kind.
    """
    removed, paths = remove_entities_rows(db, entity_type=entity_type, entity_ids=entity_ids)
    (metadata_manager or MetadataManager()).delete_document_files_after_commit(db, paths, ws)
    return removed


def remove_entity_data(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    ws: Optional[WorkspaceClient] = None,
    metadata_manager: Optional[MetadataManager] = None,
) -> Dict[str, int]:
    """``remove_entities_data`` for one entity."""
    return remove_entities_data(
        db, entity_type=entity_type, entity_ids=[entity_id], ws=ws, metadata_manager=metadata_manager,
    )


def move_entity_data(db: Session, *, entity_type: str, from_id: str, to_id: str) -> Dict[str, int]:
    """Re-key an entity's rows to another id of the same kind, in ``db``'s transaction.

    For an entity that is recreated under a new id (a concept migrated to
    another collection) before its old id is deleted: its notes, links,
    documents (the files stay where they are), cost items and tags go with it
    instead of being deleted with the old id. Returns the rows moved per kind.
    """
    moved = {}
    for key, model in _TABLES:
        moved[key] = db.query(model).filter(
            model.entity_type == entity_type, model.entity_id == str(from_id),
        ).update({model.entity_id: str(to_id)}, synchronize_session=False)
    return moved
