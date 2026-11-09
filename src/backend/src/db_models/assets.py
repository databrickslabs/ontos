import uuid
from sqlalchemy import Column, String, Text, Boolean, Integer, TIMESTAMP, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.common.database import Base


class AssetTypeDb(Base):
    """Asset Type: reusable template/class that assets belong to (Table, Dashboard, API, etc.)."""
    __tablename__ = "asset_types"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True, index=True)  # data, analytics, infrastructure, application
    icon = Column(String, nullable=True)  # Icon identifier for UI display
    required_fields = Column(JSON, nullable=True)  # JSON schema for required metadata fields
    optional_fields = Column(JSON, nullable=True)  # JSON schema for optional metadata fields
    allowed_relationships = Column(JSON, nullable=True)  # What relationship types are valid
    is_system = Column(Boolean, nullable=False, default=False)  # Built-in vs user-defined
    status = Column(String, nullable=False, default="active", index=True)  # active, deprecated

    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    assets = relationship("AssetDb", back_populates="asset_type", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<AssetTypeDb(id={self.id}, name='{self.name}')>"


class AssetDb(Base):
    """Asset: a concrete cataloged thing (table, dashboard, API, file, etc.)."""
    __tablename__ = "assets"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    asset_type_id = Column(PG_UUID(as_uuid=True), ForeignKey("asset_types.id"), nullable=False, index=True)
    platform = Column(String, nullable=True)  # e.g., Databricks, Power BI, Salesforce
    location = Column(String, nullable=True)  # FQDN, URL, path
    # Domain assignment is polymorphic via entity_domain_associations (entity_type='asset');
    # the legacy domain_id column was removed in favour of multi-domain assignment.
    properties = Column(JSON, nullable=True)  # Type-specific metadata following type's schema
    tags = Column(JSON, nullable=True)  # Quick tags/classifications
    status = Column(String, nullable=False, default="active", index=True)

    # Certification
    certification_level = Column(Integer, nullable=True, index=True)
    inherited_certification_level = Column(Integer, nullable=True)
    certified_at = Column(TIMESTAMP(timezone=True), nullable=True)
    certified_by = Column(String, nullable=True)
    certification_expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    certification_notes = Column(Text, nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    asset_type = relationship("AssetTypeDb", back_populates="assets")
    source_relationships = relationship(
        "AssetRelationshipDb",
        foreign_keys="AssetRelationshipDb.source_asset_id",
        back_populates="source_asset",
        cascade="all, delete-orphan",
    )
    target_relationships = relationship(
        "AssetRelationshipDb",
        foreign_keys="AssetRelationshipDb.target_asset_id",
        back_populates="target_asset",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("name", "asset_type_id", "platform", "location", name="uq_asset_identity"),
    )

    def __repr__(self):
        return f"<AssetDb(id={self.id}, name='{self.name}', type_id='{self.asset_type_id}')>"


class AssetRelationshipDb(Base):
    """DEPRECATED: Use EntityRelationshipDb instead. Kept for migration compatibility."""
    __tablename__ = "asset_relationships"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_asset_id = Column(PG_UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    target_asset_id = Column(PG_UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True)
    relationship_type = Column(String, nullable=False, index=True)  # hasColumn, belongsToSystem, consumesFrom, etc.
    properties = Column(JSON, nullable=True)  # Additional relationship metadata

    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    source_asset = relationship("AssetDb", foreign_keys=[source_asset_id], back_populates="source_relationships")
    target_asset = relationship("AssetDb", foreign_keys=[target_asset_id], back_populates="target_relationships")

    __table_args__ = (
        UniqueConstraint("source_asset_id", "target_asset_id", "relationship_type", name="uq_asset_relationship"),
    )

    def __repr__(self):
        return f"<AssetRelationshipDb(id={self.id}, src='{self.source_asset_id}', tgt='{self.target_asset_id}', type='{self.relationship_type}')>"
