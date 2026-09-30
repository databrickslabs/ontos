from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text
# Remove UUID import as we'll use String
# from sqlalchemy.dialects.postgresql import UUID 
from sqlalchemy.sql import func
# Remove local declarative_base import and local Base definition
# from sqlalchemy.orm import declarative_base

# Import the shared Base from the common database module
from src.common.database import Base 
from sqlalchemy import ForeignKey # Added
from sqlalchemy.orm import relationship # Added

# Base = declarative_base()

class DataDomain(Base):
    """Hierarchical data domain: name, description, parent_id; used for governance grouping and team assignment (DataDomainsManager)."""
    __tablename__ = 'data_domains'

    # Use String for ID, default generates UUID string
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    # tags: Moved to EntityTagAssociationDb for rich tag support

    parent_id = Column(String, ForeignKey('data_domains.id'), nullable=True)

    # Unity Catalog domain id this domain is synced with (#761). Nullable; indexed
    # (not unique — a deleted+recreated UC domain can reuse a name but gets a new id,
    # and unsynced domains have none). Used to match idempotently across sync runs.
    uc_domain_id = Column(String, nullable=True, index=True)

    # Relationships
    parent = relationship("DataDomain", remote_side=[id], back_populates="children", lazy="select")
    children = relationship("DataDomain", back_populates="parent", lazy="select", cascade="all, delete-orphan")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=False) # Store user ID (e.g., email)

    def __repr__(self):
        return f"<DataDomain(id={self.id}, name='{self.name}')>" 