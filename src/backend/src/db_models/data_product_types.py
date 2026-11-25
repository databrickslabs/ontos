"""Database model for admin-configurable data product types."""

import uuid

from sqlalchemy import TIMESTAMP, Boolean, Column, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class DataProductTypeDb(Base):
    """Data product types configurable by admins.

    Products reference these through data_products.product_type_id.
    `key` is immutable and is the value exchanged in ODPS export/import.
    Default seed: source-aligned, aggregate, consumer-aligned, source, sink.
    """

    __tablename__ = "data_product_types"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key = Column(String(100), nullable=False, unique=True)
    label = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(100), nullable=True)
    color = Column(String(50), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)
    is_imported = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<DataProductTypeDb(key='{self.key}', label='{self.label}')>"
