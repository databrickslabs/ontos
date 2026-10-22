from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text, Boolean, Integer, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from src.common.database import Base


class EstateDb(Base):
    """Estate: another Ontos instance (workspace) this instance shares metadata with (PRD #143)."""
    __tablename__ = 'estates'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    workspace_url = Column(String, nullable=False)
    cloud_type = Column(String(16), nullable=False)
    metastore_name = Column(String, nullable=False)
    connection_type = Column(String(32), nullable=False, default='delta_share')
    is_enabled = Column(Boolean, nullable=False, default=True)
    sync_schedule = Column(String, nullable=False, default='0 0 * * *')
    last_sync_time = Column(DateTime(timezone=True), nullable=True)
    last_sync_status = Column(String(16), nullable=True)
    last_sync_error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)

    policies = relationship(
        "SharingPolicyDb",
        back_populates="estate",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="SharingPolicyDb.position",
    )

    def __repr__(self):
        return f"<EstateDb(id='{self.id}', name='{self.name}')>"


class SharingPolicyDb(Base):
    """Export or import policy of an estate: which entities of one type are shared."""
    __tablename__ = 'estate_sharing_policies'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    estate_id = Column(String, ForeignKey('estates.id', ondelete='CASCADE'), nullable=False, index=True)
    direction = Column(String(8), nullable=False)  # 'export' or 'import'
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    resource_type = Column(String(32), nullable=False)
    is_enabled = Column(Boolean, nullable=False, default=True)
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    estate = relationship("EstateDb", back_populates="policies")
    rules = relationship(
        "SharingRuleDb",
        back_populates="policy",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="SharingRuleDb.position",
    )


class SharingRuleDb(Base):
    """Filter rule of a sharing policy (filter type, operator, value)."""
    __tablename__ = 'estate_sharing_rules'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    policy_id = Column(String, ForeignKey('estate_sharing_policies.id', ondelete='CASCADE'), nullable=False, index=True)
    filter_type = Column(String, nullable=False)
    operator = Column(String(16), nullable=False)
    filter_value = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0)

    policy = relationship("SharingPolicyDb", back_populates="rules")
