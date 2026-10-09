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
    suggested: int = 0  # pending term-mapping suggestions awaiting review, this scheme
    last_run_at: Optional[str] = None  # ISO ts of the latest term-mapping run targeting this scheme


class CoverageResponse(BaseModel):
    """Batch coverage metrics for all schemes."""
    schemes: list[CoverageSchemeRow]
    totals: CoverageSchemeRow  # aggregate across all schemes


class SchemePendingSuggestion(BaseModel):
    """One PENDING term-mapping suggestion whose target concept belongs to a
    scheme. Drives the Enrich Map "Review suggested matches" surface: it carries
    the suggestion id + run id so the FE can accept-all via
    POST /api/term-mappings/runs/{run_id}/decisions then apply via
    POST /api/term-mappings/runs/{run_id}/apply, without a separate run lookup."""
    id: str  # suggestion id
    run_id: str
    source_entity_type: str
    source_entity_id: str
    source_label: Optional[str] = None
    target_concept_iri: str
    target_concept_label: Optional[str] = None
    confidence: float
    reason: str


class TagPendingItem(BaseModel):
    """One eligible concept->asset link that is pending delivery (created since
    the last successful sync). Carries enough to render both sides linkably:
    the CONCEPT (+ its scheme) and the physical ASSET it will be tagged on."""
    entity_id: str  # the physical asset FQN / id (asset UUID, or uc FQN)
    entity_type: str  # asset / uc_table / uc_column / ...
    iri: str  # the concept IRI the asset is linked to
    label: Optional[str] = None  # concept label (link.label), if present
    created_at: Optional[str] = None  # ISO timestamp the link was created
    # Enrichment for the "Pending tag changes" UI (surfaces meaning, not raw IDs):
    scheme: Optional[str] = None        # the concept's source_context (scheme IRI)
    scheme_label: Optional[str] = None  # friendly scheme name
    asset_name: Optional[str] = None    # human name of the physical asset


class TagDeliveryStats(BaseModel):
    """Real tag-delivery stats for the Enrich Tags row.

    'synced vs pending' is derived honestly from data Ontos already has:
    eligible = concept->asset links (what semantic_assignment tags target);
    pending = those created since the last successful uc_tag_sync run (i.e. new
    links a re-run would deliver). No per-link delivery log exists, so this is a
    'changes since last sync' signal, not a UC-verified tag count. It catches
    new/removed links, not in-place edits (links carry no updated_at)."""
    eligible: int  # concept->asset semantic links eligible for tag delivery
    pending: int  # eligible links created since the last successful sync
    synced: int  # eligible - pending (delivered as of the last successful run)
    last_run_state: Optional[str] = None  # SUCCESS / FAILED / ... or None if never run
    last_run_at: Optional[str] = None  # ISO timestamp of the last run end, or None
    job_installed: bool = False  # whether uc_tag_sync is installed in this workspace
    pending_items: list[TagPendingItem] = []  # the actual pending links (for drill-in)


