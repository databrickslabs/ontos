"""API models of the description reset (Unity Catalog comment) and history of an asset."""
from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.models.assets import CodedWarning


class UcCommentPreview(BaseModel):
    """The Ontos description of a table, view or column asset next to its Unity Catalog comment."""
    asset_id: UUID
    target: str = Field(..., description="The Unity Catalog object: catalog.schema.table[.column]")
    object_type: str = Field(..., description="table, view or column")
    description: Optional[str] = Field(None, description="The description in Ontos")
    uc_comment: Optional[str] = Field(
        None, description="The comment in Unity Catalog, as the user reads it")
    in_sync: bool = Field(..., description="Both texts are the same (as Unity Catalog stores them)")
    table_type: Optional[str] = Field(None, description="The Unity Catalog table type")


class DescriptionResetRequest(BaseModel):
    """The reset of a description. ``expected_uc_comment``, when sent, is the comment the user saw
    in the diff: the reset is refused (409) when Unity Catalog has another one by now."""
    expected_uc_comment: Optional[str] = None


class DescriptionResetResult(BaseModel):
    asset_id: UUID
    target: str
    changed: bool = Field(..., description="The Ontos description was replaced")
    previous_description: Optional[str] = None
    description: Optional[str] = None
    warnings: List[CodedWarning] = Field(default_factory=list)


class DescriptionHistoryEntry(BaseModel):
    """One change of the description of an asset."""
    id: str
    timestamp: datetime
    username: Optional[str] = None
    source: Optional[str] = Field(
        None, description="manual, uc_import, bulk_import, uc_reset, restore (more may come)")
    object_type: Optional[str] = None
    before: Optional[str] = None
    after: Optional[str] = None
    restored_from: Optional[str] = Field(None, description="The entry a restore came from")


class DescriptionHistory(BaseModel):
    asset_id: UUID
    total: int
    items: List[DescriptionHistoryEntry]


class DescriptionRestoreRequest(BaseModel):
    """Restore the text an entry set (``after``) or the one it replaced (``before``)."""
    entry_id: str
    version: Literal['after', 'before'] = 'after'
