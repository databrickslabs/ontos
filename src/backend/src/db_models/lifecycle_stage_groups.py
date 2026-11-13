"""Lifecycle Stage Groups: configurable lifecycles of products, contracts and assets.

A group belongs to one entity type and is an ordered set of stages, each mapped
to a fixed Stage Category, plus the allowed transitions between them. One group
per entity type is its default. An entity stores its group in
``lifecycle_stage_group_id`` and its stage key in ``status``.
"""
import uuid

from sqlalchemy import (
    Boolean, Column, ForeignKey, Index, Integer, String, Text, TIMESTAMP, UniqueConstraint,
    false, text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.common.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class LifecycleStageGroupDb(Base):
    __tablename__ = 'lifecycle_stage_groups'

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # data_product | data_contract | asset
    entity_type = Column(String(50), nullable=False, index=True)
    is_default_for_type = Column(Boolean, nullable=False, default=False, server_default=false())
    created_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    stages = relationship(
        'LifecycleStageDb', back_populates='group', cascade='all, delete-orphan',
        order_by='LifecycleStageDb.order', lazy='selectin',
    )
    transitions = relationship(
        'LifecycleStageTransitionDb', back_populates='group', cascade='all, delete-orphan',
        lazy='selectin',
    )

    __table_args__ = (
        UniqueConstraint('entity_type', 'name', name='uq_lifecycle_stage_groups_type_name'),
        # At most one default group per entity type
        Index(
            'uq_lifecycle_stage_groups_default', 'entity_type', unique=True,
            postgresql_where=text('is_default_for_type'),
            sqlite_where=text('is_default_for_type'),
        ),
    )


class LifecycleStageDb(Base):
    __tablename__ = 'lifecycle_stages'

    id = Column(String, primary_key=True, default=_uuid)
    group_id = Column(
        String, ForeignKey('lifecycle_stage_groups.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # Immutable: entities store it in ``status``, workflow rules match on it
    key = Column(String(64), nullable=False)
    label = Column(String(255), nullable=False)
    # draft | review | active | deprecated | retired
    category = Column(String(20), nullable=False)
    color = Column(String(32), nullable=True)
    order = Column(Integer, nullable=False, default=0)
    # The stage a new entity (or a group change) starts in
    is_initial = Column(Boolean, nullable=False, default=False, server_default=false())

    group = relationship('LifecycleStageGroupDb', back_populates='stages')

    __table_args__ = (
        UniqueConstraint('group_id', 'key', name='uq_lifecycle_stages_group_key'),
    )


class LifecycleStageTransitionDb(Base):
    __tablename__ = 'lifecycle_stage_transitions'

    id = Column(String, primary_key=True, default=_uuid)
    group_id = Column(
        String, ForeignKey('lifecycle_stage_groups.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    from_stage_id = Column(
        String, ForeignKey('lifecycle_stages.id', ondelete='CASCADE'), nullable=False,
    )
    to_stage_id = Column(
        String, ForeignKey('lifecycle_stages.id', ondelete='CASCADE'), nullable=False,
    )

    group = relationship('LifecycleStageGroupDb', back_populates='transitions')
    from_stage = relationship('LifecycleStageDb', foreign_keys=[from_stage_id])
    to_stage = relationship('LifecycleStageDb', foreign_keys=[to_stage_id])

    __table_args__ = (
        UniqueConstraint('from_stage_id', 'to_stage_id', name='uq_lifecycle_stage_transitions'),
    )
