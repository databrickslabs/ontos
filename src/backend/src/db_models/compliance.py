from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, false,
)
from sqlalchemy.orm import relationship

from src.common.database import Base
from src.common.timestamps import utc_now


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
    # None for a run without a score: it failed, or evaluated no entity
    score = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    # Stable code and JSON parameters of an app error, translated by the UI (error_message is the fallback)
    error_code = Column(String, nullable=True)
    error_params = Column(Text, nullable=True)
    # Code and JSON parameters of what a finished run has to report (a rule tail it ignored);
    # kept apart from error_code so a succeeded run never looks failed
    warning_code = Column(String, nullable=True)
    warning_params = Column(Text, nullable=True)
    # LLM_CHECK model calls the run made, and the verdicts it read from the cache
    # (None: a run from before they were counted)
    llm_calls = Column(Integer, nullable=True)
    llm_cache_hits = Column(Integer, nullable=True)
    # Entities without a verdict (an LLM_CHECK that couldn't run: budget, quota, no
    # endpoint...): neither passed nor failed, and not part of the score
    not_evaluated_count = Column(Integer, nullable=True)

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
    # No verdict: an LLM_CHECK couldn't run (passed is False, the run's counts and
    # score leave it out)
    not_evaluated = Column(Boolean, default=False, nullable=False, server_default=false())
    message = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    run = relationship("ComplianceRunDb", back_populates="results")




class ComplianceLlmCheckCacheDb(Base):
    """Cached LLM_CHECK verdict, keyed by a hash of the text, the criterion and the model.

    A rule run again over unchanged text reads the verdict here instead of calling
    the serving endpoint. Only verdicts are stored (PASS / FAIL with the model's
    reason); a check that failed with an error code is asked again next run.
    """
    __tablename__ = 'compliance_llm_check_cache'

    key = Column(String(64), primary_key=True)  # sha256 hex, see compliance_llm_check.cache_key
    model = Column(String, nullable=False)  # the serving endpoint
    # The model that answered (the reply's ``model``), for audits of old verdicts
    response_model = Column(String, nullable=True)
    passed = Column(Boolean, nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class ComplianceLlmCheckUsageDb(Base):
    """LLM_CHECK model calls a user started on one day (UTC), for the daily quota.

    Counted for the runs and rule tests a user starts; scheduled runs have no
    user and only the per-run budget.
    """
    __tablename__ = 'compliance_llm_check_usage'

    username = Column(String, primary_key=True)
    day = Column(Date, primary_key=True)
    calls = Column(Integer, nullable=False, default=0)
