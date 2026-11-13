"""
Database models for data contract validations.

Stores results of validation runs on data contracts (schema drift, access, SLA, DQ checks).
"""

from datetime import datetime
from src.common.time_utils import utc_now
from sqlalchemy import Column, String, DateTime, Text, Boolean, ForeignKey, Integer, Float
from sqlalchemy.orm import relationship

from src.common.database import Base


class DataContractValidationRunDb(Base):
    """Store data contract validation runs"""
    __tablename__ = 'data_contract_validation_runs'

    id = Column(String, primary_key=True)
    contract_id = Column(String, ForeignKey('data_contracts.id'), nullable=False, index=True)
    status = Column(String, default='running', nullable=False, index=True)  # running|succeeded|failed
    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    checks_passed = Column(Integer, default=0, nullable=False)
    checks_failed = Column(Integer, default=0, nullable=False)
    score = Column(Float, default=0.0, nullable=False)
    error_message = Column(Text, nullable=True)

    # Relationship to results
    results = relationship("DataContractValidationResultDb", back_populates="run", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self):
        return f"<DataContractValidationRunDb(id='{self.id}', contract_id='{self.contract_id}', status='{self.status}', score={self.score})>"


class DataContractValidationResultDb(Base):
    """Store individual contract validation results"""
    __tablename__ = 'data_contract_validation_results'

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey('data_contract_validation_runs.id'), nullable=False, index=True)
    contract_id = Column(String, nullable=False, index=True)
    check_type = Column(String, nullable=False)  # schema_drift|access|sla|dq
    passed = Column(Boolean, default=False, nullable=False)
    message = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)  # JSON with specific violation details
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationship to run
    run = relationship("DataContractValidationRunDb", back_populates="results")

    def __repr__(self):
        return f"<DataContractValidationResultDb(id='{self.id}', check_type='{self.check_type}', passed={self.passed})>"
