"""
Database models for data quality checks.

Stores results of data quality check runs on data contracts.
"""

from datetime import datetime
from src.common.time_utils import utc_now
from sqlalchemy import Column, String, DateTime, Text, Boolean, ForeignKey, Integer, Float
from sqlalchemy.orm import relationship

from src.common.database import Base


class DataQualityCheckRunDb(Base):
    """Store data quality check runs per contract"""
    __tablename__ = 'data_quality_check_runs'

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
    results = relationship("DataQualityCheckResultDb", back_populates="run", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self):
        return f"<DataQualityCheckRunDb(id='{self.id}', contract_id='{self.contract_id}', status='{self.status}', score={self.score})>"


class DataQualityCheckResultDb(Base):
    """Store individual data quality check results"""
    __tablename__ = 'data_quality_check_results'

    id = Column(String, primary_key=True)
    run_id = Column(String, ForeignKey('data_quality_check_runs.id'), nullable=False, index=True)
    contract_id = Column(String, nullable=False, index=True)
    object_name = Column(String, nullable=False)  # Table name
    check_type = Column(String, nullable=False)  # required|unique|range|length|pattern
    column_name = Column(String, nullable=True)
    passed = Column(Boolean, default=False, nullable=False)
    violations_count = Column(Integer, default=0, nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationship to run
    run = relationship("DataQualityCheckRunDb", back_populates="results")

    def __repr__(self):
        return f"<DataQualityCheckResultDb(id='{self.id}', check_type='{self.check_type}', passed={self.passed})>"
