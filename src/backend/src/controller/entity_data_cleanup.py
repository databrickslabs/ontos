"""Remove what an entity stores in the polymorphic metadata and cost tables when it is deleted.

Notes, links, documents, attachments and cost items are keyed by
``(entity_type, entity_id)`` with no foreign key to the entity, so each delete
path removes them itself (#1431). Every entity kind that renders the metadata
or cost panels calls ``remove_entity_data`` from its delete, inside the
delete's transaction.
"""
from typing import Dict, List, Optional, Tuple

from databricks.sdk import WorkspaceClient
from sqlalchemy.orm import Session

from src.controller.costs_manager import CostsManager
from src.controller.metadata_manager import MetadataManager


def remove_entity_rows(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    metadata_manager: Optional[MetadataManager] = None,
    costs_manager: Optional[CostsManager] = None,
) -> Tuple[Dict[str, int], List[str]]:
    """Delete the entity's rows in ``db``'s transaction; return the counts per kind and the document paths.

    For callers that delete inside a savepoint: queue the returned paths with
    ``MetadataManager.delete_document_files_after_commit`` once the savepoint
    is released, so a rolled-back savepoint keeps the files.
    """
    metadata_manager = metadata_manager or MetadataManager()
    costs_manager = costs_manager or CostsManager()
    entity_id = str(entity_id)
    counts, paths = metadata_manager.remove_all_for_entity(db, entity_type=entity_type, entity_id=entity_id)
    removed = dict(counts)
    removed["cost_items"] = costs_manager.remove_all_for_entity(db, entity_type=entity_type, entity_id=entity_id)
    return removed, paths


def remove_entity_data(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    ws: Optional[WorkspaceClient] = None,
    metadata_manager: Optional[MetadataManager] = None,
    costs_manager: Optional[CostsManager] = None,
) -> Dict[str, int]:
    """Delete an entity's notes, links, documents, attachments and cost items, in ``db``'s transaction.

    Shared library records are not the entity's (they're stored under the
    shared id) and stay. The documents' files are deleted from the volume once
    ``db`` commits and kept if it rolls back. Returns the rows removed per kind.
    """
    metadata_manager = metadata_manager or MetadataManager()
    removed, paths = remove_entity_rows(
        db, entity_type=entity_type, entity_id=entity_id,
        metadata_manager=metadata_manager, costs_manager=costs_manager,
    )
    metadata_manager.delete_document_files_after_commit(db, paths, ws)
    return removed
