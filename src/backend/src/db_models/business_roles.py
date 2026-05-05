import uuid
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class BusinessRoleDb(Base):
    """Business Role: a named role users can hold (Data Owner, Domain Owner, etc.)."""
    __tablename__ = "business_roles"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True, index=True)  # governance, technical, business, operational
    is_system = Column(Boolean, nullable=False, default=False)  # Built-in vs user-defined
    status = Column(String, nullable=False, default="active", index=True)  # active, deprecated
    is_approver = Column(Boolean, nullable=False, default=False, index=True)  # Show in workflow approver dropdown

    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<BusinessRoleDb(id={self.id}, name='{self.name}')>"
