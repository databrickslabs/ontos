"""Shared result models for batch entity imports (ODCS contracts / ODPS products).

A single import operation may span several uploaded files, each holding one entity
or an array of entities. Every entity produces one :class:`ImportItemResult`; the
:class:`BatchImportResult` carries the truthful per-batch summary ("N created,
M skipped, K failed") that the frontend renders, mirroring the demo-data loader's
report pattern. A single bad entity is recorded as a failed item and never aborts
the batch.

The ``skipped`` status and the ``source_id``/``entity_id`` provenance fields are
intentionally part of this contract from the start so the sibling import features
(#851 domain reconciliation, #853 UUID-as-PK duplicate handling) can populate them
without another response-shape change.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ImportItemStatus = Literal["created", "skipped", "failed"]


class ImportItemResult(BaseModel):
    """Outcome of importing a single entity within a batch."""

    index: int = Field(..., description="Zero-based position of the entity within the whole batch")
    source_file: Optional[str] = Field(None, description="Originating filename (multi-file uploads)")
    source_id: Optional[str] = Field(None, description="Entity id as written in the source YAML/JSON, if any")
    entity_id: Optional[str] = Field(None, description="Created Ontos entity id (None when skipped/failed)")
    name: Optional[str] = Field(None, description="Entity name, best-effort")
    status: ImportItemStatus = Field(..., description="created | skipped | failed")
    message: Optional[str] = Field(None, description="Skip reason, error detail or note")
    code: Optional[str] = Field(None, description="Code of the message, for the UI to translate")
    params: Optional[Dict[str, Any]] = Field(None, description="Parameters of the coded message")
    notes: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Further coded notes ({code, params, message}) when an item has more than one",
    )


class BatchImportResult(BaseModel):
    """Aggregate summary of a single (possibly multi-file, multi-entity) import."""

    created: int = 0
    skipped: int = 0
    failed: int = 0
    total: int = 0
    items: List[ImportItemResult] = Field(default_factory=list)
    created_ids: List[str] = Field(default_factory=list, description="Ids of successfully created entities")

    def add(self, item: ImportItemResult) -> None:
        """Record one entity result and update the counters."""
        self.items.append(item)
        self.total += 1
        if item.status == "created":
            self.created += 1
            if item.entity_id:
                self.created_ids.append(item.entity_id)
        elif item.status == "skipped":
            self.skipped += 1
        else:
            self.failed += 1
