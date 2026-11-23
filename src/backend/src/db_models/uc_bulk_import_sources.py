"""What the UC Bulk Import job imported into each data product and contract.

The job adds an output port (product) or schema object (contract) per tagged
Unity Catalog table. It records the table here, keyed by the entity's version
family, so a deliverable a user deletes in the app stays deleted: the next run
skips every table it has a row for, whether or not the deliverable still exists.
Only the job (raw SQL) writes this table; the app doesn't read it.
"""
from sqlalchemy import Column, DateTime, String, UniqueConstraint
from sqlalchemy.sql import func

from src.common.database import Base


class UcBulkImportSourceDb(Base):
    __tablename__ = "uc_bulk_import_sources"
    __table_args__ = (
        UniqueConstraint(
            "entity_type", "version_family_id", "source_key",
            name="uq_uc_bulk_import_sources_entity_source",
        ),
    )

    id = Column(String, primary_key=True)
    # 'data_product' or 'data_contract'
    entity_type = Column(String, nullable=False)
    # version_family_id of the product or contract: versions share what was imported
    version_family_id = Column(String, nullable=False)
    # Qualified Unity Catalog table name (catalog.schema.table)
    source_key = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
