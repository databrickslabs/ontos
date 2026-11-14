from __future__ import annotations
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


# ============================================================================
# Entity Types Pattern
# ============================================================================
ENTITY_TYPE_PATTERN = r"^(data_domain|data_product|data_contract|dataset|asset)$"


# ============================================================================
# Rich Text Models
# ============================================================================

class RichTextBase(BaseModel):
    entity_id: str
    entity_type: str = Field(..., pattern=ENTITY_TYPE_PATTERN)
    title: str = Field(..., min_length=1, max_length=255)
    short_description: Optional[str] = Field(None, max_length=1000)
    content_markdown: str
    # Sharing and inheritance
    is_shared: bool = Field(False, description="If true, this is a shared asset that can be attached to multiple entities")
    level: int = Field(50, ge=0, le=999, description="Display/inheritance ordering level (lower = higher priority)")
    inheritable: bool = Field(True, description="Can this be inherited by child entities (DP/DS from DC)?")


class RichTextCreate(RichTextBase):
    pass


class RichTextUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    short_description: Optional[str] = Field(None, max_length=1000)
    content_markdown: Optional[str] = None
    level: Optional[int] = Field(None, ge=0, le=999)
    inheritable: Optional[bool] = None


class RichText(RichTextBase):
    id: UUID
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


# ============================================================================
# Link Models
# ============================================================================

class LinkBase(BaseModel):
    entity_id: str
    entity_type: str = Field(..., pattern=ENTITY_TYPE_PATTERN)
    title: str = Field(..., min_length=1, max_length=255)
    short_description: Optional[str] = Field(None, max_length=1000)
    url: str = Field(..., min_length=1)
    # Sharing and inheritance
    is_shared: bool = Field(False, description="If true, this is a shared asset")
    level: int = Field(50, ge=0, le=999, description="Display/inheritance ordering level")
    inheritable: bool = Field(True, description="Can this be inherited by child entities?")


class LinkCreate(LinkBase):
    pass


class LinkUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    short_description: Optional[str] = Field(None, max_length=1000)
    url: Optional[str] = Field(None, min_length=1)
    level: Optional[int] = Field(None, ge=0, le=999)
    inheritable: Optional[bool] = None


class Link(LinkBase):
    id: UUID
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


# ============================================================================
# Document Models
# ============================================================================

class DocumentBase(BaseModel):
    entity_id: str
    entity_type: str = Field(..., pattern=ENTITY_TYPE_PATTERN)
    title: str = Field(..., min_length=1, max_length=255)
    short_description: Optional[str] = Field(None, max_length=1000)
    # Sharing and inheritance
    is_shared: bool = Field(False, description="If true, this is a shared document stored in shared folder")
    level: int = Field(50, ge=0, le=999, description="Display/inheritance ordering level")
    inheritable: bool = Field(True, description="Can this be inherited by child entities?")


class DocumentCreate(DocumentBase):
    # These are filled during upload processing
    pass


class Document(DocumentBase):
    id: UUID
    original_filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    storage_path: str
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


# ============================================================================
# Metadata Attachment Models (for attaching shared assets to entities)
# ============================================================================

class MetadataAttachmentCreate(BaseModel):
    """Request to attach a shared metadata asset to an entity."""
    asset_type: str = Field(..., pattern=r"^(rich_text|link|document)$", description="Type of metadata asset")
    asset_id: str = Field(..., description="UUID of the shared asset to attach")
    level_override: Optional[int] = Field(None, ge=0, le=999, description="Optional level override for this attachment")


class MetadataAttachment(BaseModel):
    """A metadata attachment linking a shared asset to an entity."""
    id: UUID
    entity_id: str
    entity_type: str
    asset_type: str
    asset_id: str
    level_override: Optional[int] = None
    created_by: Optional[str] = None
    created_at: datetime

    model_config = {
        "from_attributes": True
    }


# ============================================================================
# Shared Asset List Response
# ============================================================================

class SharedAssetListResponse(BaseModel):
    """Response containing lists of shared assets by type."""
    rich_texts: List[RichText] = Field(default_factory=list)
    links: List[Link] = Field(default_factory=list)
    documents: List[Document] = Field(default_factory=list)


# ============================================================================
# Merged Metadata Response (includes inherited metadata)
# ============================================================================

class MergedMetadataResponse(BaseModel):
    """Response containing merged metadata with inheritance applied.
    
    This includes:
    - Direct metadata attached to the entity
    - Inherited metadata from its contracts and assets (filtered by level and inheritable flag)
    """
    rich_texts: List[RichText] = Field(default_factory=list)
    links: List[Link] = Field(default_factory=list)
    documents: List[Document] = Field(default_factory=list)
    # Source tracking
    sources: dict = Field(default_factory=dict, description="Mapping of asset IDs to their source entity")
    source_names: dict = Field(default_factory=dict, description="Display names of inheritance sources, keyed like `sources` values (contract:<id>, asset:<id>)")

from pydantic import BaseModel

# Structure for returning metastore table info
class MetastoreTableInfo(BaseModel):
    catalog_name: str
    schema_name: str
    table_name: str
    full_name: str # Helper for display/selection

# Add other metadata models here later (e.g., CatalogInfo, SchemaInfo, ClusterInfo) 