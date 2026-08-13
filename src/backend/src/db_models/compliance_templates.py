"""Database models for admin-defined Compliance Templates.

Three tables implement a typed, grouped governance-field schema bound to an
entity type, plus per-entity filled-in values stored polymorphically:

- ``compliance_templates``        — the template definition (name, bound entity
  type, active flag). At most one active template per
  ``(entity_type, scope_type, scope_id)`` is enforced by a partial unique index;
  v1 only ever uses ``scope_type = 'all'``. The ``scope_*`` columns exist now so
  domain/project scoping can be added later without a migration.
- ``compliance_template_fields``  — typed fields belonging to a template. Groups
  are denormalized onto the field (``group_title`` + ``group_order``) rather than
  living in their own table. ``constraints`` is reserved for future
  input-validation rules and is unused in v1.
- ``compliance_template_values``  — per-entity filled-in values, keyed
  polymorphically by ``(entity_type, entity_id)`` and unique per field. Mirrors
  the ``entity_tag_associations`` pattern.
"""
import uuid

from sqlalchemy import (
    JSON,
    TIMESTAMP,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.common.database import Base

# Default scope for an active template. v1 only uses "all"; the scope columns
# exist to allow domain/project/catalog scoping later without a schema change.
DEFAULT_SCOPE_TYPE = "all"
DEFAULT_SCOPE_ID = ""


class ComplianceTemplateDb(Base):
    """An admin-defined, typed, grouped field schema bound to an entity type.

    Exactly one template may be active per ``(entity_type, scope_type,
    scope_id)`` — enforced by the ``uq_compliance_template_active_scope``
    partial unique index (only rows with ``is_active = true`` participate).
    """
    __tablename__ = "compliance_templates"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # The entity type this template governs (e.g. "data_product"). Kept as a
    # free string to stay entity-agnostic — the feature never imports host
    # entity code.
    entity_type = Column(String(100), nullable=False, index=True)

    # Scoping columns — v1 always uses ("all", ""). Reserved for future
    # domain/project scoping of active templates.
    scope_type = Column(String(50), nullable=False, default=DEFAULT_SCOPE_TYPE, server_default=DEFAULT_SCOPE_TYPE)
    scope_id = Column(String(255), nullable=False, default=DEFAULT_SCOPE_ID, server_default="")

    is_active = Column(Boolean, nullable=False, default=False, server_default="false", index=True)
    version = Column(Integer, nullable=False, default=1, server_default="1")

    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    fields = relationship(
        "ComplianceTemplateFieldDb",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ComplianceTemplateFieldDb.group_order, ComplianceTemplateFieldDb.field_order",
    )

    __table_args__ = (
        # At most one ACTIVE template per (entity_type, scope_type, scope_id).
        # Partial index so inactive templates don't collide.
        Index(
            "uq_compliance_template_active_scope",
            "entity_type",
            "scope_type",
            "scope_id",
            unique=True,
            postgresql_where=Column("is_active"),
        ),
    )

    def __repr__(self):
        return f"<ComplianceTemplateDb(id={self.id}, name='{self.name}', entity_type='{self.entity_type}', active={self.is_active})>"


class ComplianceTemplateFieldDb(Base):
    """A typed field within a template, denormalized into a titled group.

    ``value_type`` is one of the supported types (String, Numeric, Enum,
    MultiEnum, Date, Range, Boolean). ``possible_values`` holds the controlled
    vocabulary for Enum/MultiEnum. ``reference_id`` is a validated slug, unique
    per template, referenced elsewhere as ``${template.<reference_id>}``.
    """
    __tablename__ = "compliance_template_fields"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(PG_UUID(as_uuid=True), ForeignKey("compliance_templates.id", ondelete="CASCADE"), nullable=False, index=True)

    # Group denormalized onto the field.
    group_title = Column(String(255), nullable=False, default="", server_default="")
    group_order = Column(Integer, nullable=False, default=0, server_default="0")

    # Stable machine key + human label.
    key = Column(String(255), nullable=False)
    label = Column(String(255), nullable=False)
    # Slug referenced by ${template.<reference_id>}; unique per template, mutable in v1.
    reference_id = Column(String(255), nullable=False)

    value_type = Column(String(50), nullable=False)
    # Controlled vocabulary for Enum / MultiEnum (list of strings). Null otherwise.
    possible_values = Column(JSON, nullable=True)
    # Default value stored as JSON to accommodate every value type uniformly.
    default_value = Column(JSON, nullable=True)
    hint_text = Column(Text, nullable=True)
    is_mandatory = Column(Boolean, nullable=False, default=False, server_default="false")
    field_order = Column(Integer, nullable=False, default=0, server_default="0")

    # Reserved for future input-validation rules (regex, min/max, …). Unused in v1.
    constraints = Column(JSON, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    template = relationship("ComplianceTemplateDb", back_populates="fields")
    values = relationship(
        "ComplianceTemplateValueDb",
        back_populates="field",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("template_id", "reference_id", name="uq_compliance_field_reference_id"),
        UniqueConstraint("template_id", "key", name="uq_compliance_field_key"),
    )

    def __repr__(self):
        return f"<ComplianceTemplateFieldDb(id={self.id}, ref='{self.reference_id}', type='{self.value_type}')>"


class ComplianceTemplateValueDb(Base):
    """A per-entity filled-in value for a template field.

    Polymorphic: keyed by ``(entity_type, entity_id)`` so the same mechanism
    extends to Data Contracts and Assets later with no schema change. Value is
    stored as JSON so every value type shares one column. Unique per
    ``(field_id, entity_type, entity_id)``.
    """
    __tablename__ = "compliance_template_values"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id = Column(PG_UUID(as_uuid=True), ForeignKey("compliance_template_fields.id", ondelete="CASCADE"), nullable=False, index=True)

    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(255), nullable=False, index=True)

    value = Column(JSON, nullable=True)

    filled_by = Column(String, nullable=True)
    filled_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    field = relationship("ComplianceTemplateFieldDb", back_populates="values")

    __table_args__ = (
        UniqueConstraint("field_id", "entity_type", "entity_id", name="uq_compliance_value_field_entity"),
    )

    def __repr__(self):
        return f"<ComplianceTemplateValueDb(id={self.id}, field_id='{self.field_id}', entity_type='{self.entity_type}', entity_id='{self.entity_id}')>"
