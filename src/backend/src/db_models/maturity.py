"""Database models for configurable maturity levels."""
import uuid
from sqlalchemy import (
    Column, String, Integer, Text, Boolean, TIMESTAMP, ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from src.common.database import Base


class MaturityLevelDb(Base):
    """Admin-configurable ordered maturity levels, scoped per entity type.

    Example seed: Accessible (1), Described (2), Defined (3), Monitored (4), Trusted (5).
    """
    __tablename__ = "maturity_levels"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    level_order = Column(Integer, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(100), nullable=True)
    color = Column(String(50), nullable=True)
    # "DataProduct", "DataContract", or "all"
    entity_type = Column(String(50), nullable=False, default="all", index=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    gates = relationship("MaturityGateDb", back_populates="maturity_level",
                         cascade="all, delete-orphan", lazy="selectin",
                         order_by="MaturityGateDb.display_order")

    __table_args__ = (
        UniqueConstraint("entity_type", "level_order", name="uq_maturity_level_entity_order"),
        UniqueConstraint("entity_type", "name", name="uq_maturity_level_entity_name"),
    )

    def __repr__(self):
        return f"<MaturityLevelDb(order={self.level_order}, name='{self.name}', entity_type='{self.entity_type}')>"


class MaturityGateDb(Base):
    """Links a maturity level to a compliance policy that must pass for level achievement."""
    __tablename__ = "maturity_gates"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    maturity_level_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("maturity_levels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    compliance_policy_id = Column(
        String,
        ForeignKey("compliance_policies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    required = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    maturity_level = relationship("MaturityLevelDb", back_populates="gates")
    compliance_policy = relationship("CompliancePolicyDb", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("maturity_level_id", "compliance_policy_id",
                         name="uq_maturity_gate_level_policy"),
    )

    def __repr__(self):
        return f"<MaturityGateDb(level={self.maturity_level_id}, policy={self.compliance_policy_id})>"


class MaturitySnapshotDb(Base):
    """Timestamped evaluation result for maturity tracking over time."""
    __tablename__ = "maturity_snapshots"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    achieved_level_order = Column(Integer, nullable=True)
    achieved_level_name = Column(String(255), nullable=True)
    total_levels = Column(Integer, nullable=False, default=0)
    gates_passed = Column(Integer, nullable=False, default=0)
    gates_total = Column(Integer, nullable=False, default=0)
    gate_results_json = Column(Text, nullable=True)
    evaluated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    evaluated_by = Column(String, nullable=True)

    def __repr__(self):
        return (
            f"<MaturitySnapshotDb(entity={self.entity_type}:{self.entity_id}, "
            f"level={self.achieved_level_order})>"
        )
