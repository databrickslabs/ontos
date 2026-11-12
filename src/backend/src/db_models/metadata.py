import uuid
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func
from sqlalchemy import TIMESTAMP, Index

from src.common.database import Base


class RichTextMetadataDb(Base):
    """Rich text metadata that can be attached to entities.
    
    Supports:
    - Entity-specific or shared (is_shared=True, entity_id='__shared__')
    - Level ordering for display/inheritance
    - Inheritable flag for cascading to child entities
    """
    __tablename__ = "rich_text_metadata"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String, nullable=False, index=True)  # '__shared__' for shared assets
    entity_type = Column(String, nullable=False, index=True)  # data_domain | data_product | data_contract | dataset

    title = Column(String, nullable=False)
    short_description = Column(Text, nullable=True)
    content_markdown = Column(Text, nullable=False)

    # Sharing and inheritance fields
    is_shared = Column(Boolean, nullable=False, default=False, index=True)
    level = Column(Integer, nullable=False, default=50)  # Ordering level (lower = higher priority)
    inheritable = Column(Boolean, nullable=False, default=True)  # Can this be inherited by child entities?

    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_rich_text_entity", "entity_type", "entity_id"),
        Index("ix_rich_text_shared", "is_shared"),
    )


class LinkMetadataDb(Base):
    """Link metadata that can be attached to entities.
    
    Supports:
    - Entity-specific or shared (is_shared=True, entity_id='__shared__')
    - Level ordering for display/inheritance
    - Inheritable flag for cascading to child entities
    """
    __tablename__ = "link_metadata"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String, nullable=False, index=True)  # '__shared__' for shared assets
    entity_type = Column(String, nullable=False, index=True)

    title = Column(String, nullable=False)
    short_description = Column(Text, nullable=True)
    url = Column(String, nullable=False)

    # Sharing and inheritance fields
    is_shared = Column(Boolean, nullable=False, default=False, index=True)
    level = Column(Integer, nullable=False, default=50)
    inheritable = Column(Boolean, nullable=False, default=True)

    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_link_entity", "entity_type", "entity_id"),
        Index("ix_link_shared", "is_shared"),
    )


class DocumentMetadataDb(Base):
    """Document metadata that can be attached to entities.
    
    Supports:
    - Entity-specific or shared (is_shared=True, entity_id='__shared__')
    - Level ordering for display/inheritance
    - Inheritable flag for cascading to child entities
    
    For shared documents, files are stored in a shared folder rather than per-entity folders.
    """
    __tablename__ = "document_metadata"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(String, nullable=False, index=True)  # '__shared__' for shared assets
    entity_type = Column(String, nullable=False, index=True)

    title = Column(String, nullable=False)
    short_description = Column(Text, nullable=True)

    original_filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    storage_path = Column(String, nullable=False)  # Path in Databricks Volume
    content_sha256 = Column(String(64), nullable=True)  # hex digest of the uploaded bytes

    # Sharing and inheritance fields
    is_shared = Column(Boolean, nullable=False, default=False, index=True)
    level = Column(Integer, nullable=False, default=50)
    inheritable = Column(Boolean, nullable=False, default=True)

    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_document_entity", "entity_type", "entity_id"),
        Index("ix_document_shared", "is_shared"),
    )


class MetadataAttachmentDb(Base):
    """Junction table for attaching shared metadata assets to entities.
    
    When a shared asset is attached to an entity, this creates a link between them
    without duplicating the actual content.
    """
    __tablename__ = "metadata_attachments"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # The entity this attachment belongs to
    entity_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False, index=True)  # data_domain | data_product | data_contract | dataset
    
    # The shared metadata asset being attached
    asset_type = Column(String, nullable=False, index=True)  # 'rich_text' | 'link' | 'document'
    asset_id = Column(String, nullable=False, index=True)  # UUID of the shared asset
    
    # Override level for this attachment (optional - if null, use the asset's default level)
    level_override = Column(Integer, nullable=True)
    
    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_attachment_entity", "entity_type", "entity_id"),
        Index("ix_attachment_asset", "asset_type", "asset_id"),
    )


