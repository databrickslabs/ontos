from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


SemanticFormat = Literal["rdfs", "skos"]


class SemanticModel(BaseModel):
    id: str
    name: str
    display_name: Optional[str] = None
    format: SemanticFormat  # legacy parse branch in DB; use serialization for display
    serialization: Optional[str] = Field(
        default=None,
        description="RDF serialization (Turtle, RDF/XML, …), not vocabulary.",
    )
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    enabled: bool = True
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: Optional[datetime] = Field(default=None, alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")


class SemanticModelCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    format: SemanticFormat
    content_text: str
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    enabled: Optional[bool] = True


class SemanticModelUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    enabled: Optional[bool] = None


class SemanticModelPreview(BaseModel):
    id: str
    name: str
    format: SemanticFormat
    preview: str


class CoverageSchemeRow(BaseModel):
    """Per-scheme semantic enrichment coverage metrics."""
    scheme: str  # source_context (e.g., 'enterprise-glossary')
    label: Optional[str] = None  # human-readable scheme name
    concepts: int  # total concepts in this scheme
    coverage_pct: int  # % of concepts with >=1 semantic link, 0-100
    products: int  # distinct data_product links across the scheme
    contracts: int  # distinct data_contract* links across the scheme
    assets: int  # distinct physical layer (uc_*/asset) links across the scheme
    suggested: int = 0  # suggested matches (not yet implemented; placeholder)


class CoverageResponse(BaseModel):
    """Batch coverage metrics for all schemes."""
    schemes: list[CoverageSchemeRow]
    totals: CoverageSchemeRow  # aggregate across all schemes


