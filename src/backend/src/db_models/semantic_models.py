from sqlalchemy import Column, String, DateTime, Text, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from src.common.database import Base


class SemanticModelDb(Base):
    """Business glossary / semantic model: RDFS or SKOS content stored as text; used by SemanticModelsManager for ontology and taxonomy storage."""
    __tablename__ = "semantic_models"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    format = Column(String, nullable=False, index=True)  # 'rdfs' | 'skos'
    original_filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(String, nullable=True)
    content_text = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)

    def __repr__(self):
        return f"<SemanticModelDb(id='{self.id}', name='{self.name}', format='{self.format}')>"


