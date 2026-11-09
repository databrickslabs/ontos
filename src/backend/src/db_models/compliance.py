from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, DateTime, Text, Boolean, ForeignKey, Integer, Float
from sqlalchemy.orm import relationship

from src.common.database import Base


class CompliancePolicyDb(Base):
    """Compliance rule definition: name, DSL rule, category, severity; evaluated by ComplianceManager and compliance workflows."""
    __tablename__ = 'compliance_policies'

    id = Column(String, primary_key=True)
    slug = Column(String, nullable=True, index=True, unique=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    failure_message = Column(Text, nullable=True)  # Human-readable message shown when policy fails
    rule = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    severity = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    runs = relationship("ComplianceRunDb", back_populates="policy", cascade="all, delete-orphan", lazy="selectin")


class ComplianceRunDb(Base):
    """Single execution of a compliance policy: status, success/failure counts, score, optional error message."""
    __tablename__ = 'compliance_runs'

    id = Column(String, primary_key=True)
    policy_id = Column(String, ForeignKey('compliance_policies.id'), nullable=False, index=True)
    status = Column(String, default='queued', nullable=False, index=True)  # queued|running|succeeded|failed
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    success_count = Column(Integer, default=0, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    error_message = Column(Text, nullable=True)
    # Stable code and JSON parameters of an app error, translated by the UI (error_message is the fallback)
    error_code = Column(String, nullable=True)
    error_params = Column(Text, nullable=True)

    policy = relationship("CompliancePolicyDb", back_populates="runs")
    results = relationship("ComplianceResultDb", back_populates="run", cascade="all, delete-orphan", lazy="selectin")


class ComplianceResultDb(Base):
    """Per-entity result of a compliance run: object_type, object_id, passed/failed, message, optional details_json."""
    __tablename__ = 'compliance_results'

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey('compliance_runs.id'), nullable=False, index=True)
    object_type = Column(String, nullable=False)
    object_id = Column(String, nullable=False)
    object_name = Column(String, nullable=True)
    passed = Column(Boolean, default=False, nullable=False)
    message = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    run = relationship("ComplianceRunDb", back_populates="results")


