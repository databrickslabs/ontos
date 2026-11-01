"""API models of the KPI consistency views over metric view measures (#1263, phase 1).

Definitions (the normalized expression, source, filter, joins, window,
parameters and the per-component differences) are only returned for metric
views the user can read in Unity Catalog; for the others a measure carries
only Ontos-level metadata: the asset, the measure's name, its linked concepts
and the verdict.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal[
    'duplicate', 'link_conflict', 'unrecognized_duplicate', 'variant', 'conflict',
    'near_duplicate',
]
Level = Literal['expression', 'scope', 'full']
ConceptVerdict = Literal['none', 'consistent', 'conflict']


class MeasureRef(BaseModel):
    """A measure of a metric view, as Ontos knows it."""
    asset_id: Optional[str] = None
    asset_name: Optional[str] = None
    view: str
    name: str
    display_name: Optional[str] = None
    # catalog.schema.view.field: the entity id of its uc_column links
    entity_id: str
    concepts: List[str] = Field(default_factory=list)
    # Whether the user can read the view's definition in Unity Catalog
    readable: bool = False


class MeasureDefinition(BaseModel):
    """The normalized components a measure's fingerprint is built from."""
    expression: str
    source: str
    filter: List[str] = Field(default_factory=list)
    joins: List[Dict[str, Any]] = Field(default_factory=list)
    window: List[Dict[str, Any]] = Field(default_factory=list)
    parameters: List[Dict[str, Any]] = Field(default_factory=list)


class ComponentDiff(BaseModel):
    """What only one side of a pair has, for one component."""
    component: str
    only_a: List[str] = Field(default_factory=list)
    only_b: List[str] = Field(default_factory=list)


class MeasureMatch(BaseModel):
    """Another measure with the same or a similar definition, or a conflicting link."""
    measure: MeasureRef
    verdict: Verdict
    first_level: Optional[Level] = None
    score: Optional[float] = None
    # None when either definition can't be shown to the user
    differences: Optional[List[ComponentDiff]] = None


class MeasureConsistency(BaseModel):
    """One measure of a metric view and its matches across the stored metric views."""
    measure: MeasureRef
    # Why the measure has no fingerprint (reference_cycle, reference_depth, no_expression)
    error: Optional[str] = None
    matches: List[MeasureMatch] = Field(default_factory=list)


class FingerprintGroup(BaseModel):
    """Measures linked to a concept that share a full fingerprint."""
    full_digest: str
    measures: List[MeasureRef] = Field(default_factory=list)
    # None when the user can read none of the group's views
    definition: Optional[MeasureDefinition] = None
    # Other concepts linked to measures with this definition (link conflicts)
    other_concepts: List[str] = Field(default_factory=list)
    # Compared with the first group (the largest); None on the first group
    first_level: Optional[Level] = None
    score: Optional[float] = None
    differences: Optional[List[ComponentDiff]] = None


class MetricViewConsistency(BaseModel):
    """``GET /api/metric-views/consistency``: by concept (groups) or by asset (measures)."""
    concept_iri: Optional[str] = None
    asset_id: Optional[str] = None
    verdict: Optional[ConceptVerdict] = None
    groups: List[FingerprintGroup] = Field(default_factory=list)
    # Linked measures without a stored fingerprint (view not imported, field
    # not a measure, or a definition Ontos can't fingerprint)
    unresolved: List[MeasureRef] = Field(default_factory=list)
    measures: List[MeasureConsistency] = Field(default_factory=list)
    threshold: float


class LinkWarning(BaseModel):
    """A coded, non-blocking warning about a concept link (translated by the UI)."""
    code: str
    message: str
    params: Dict[str, Any] = Field(default_factory=dict)


class LinkCheck(BaseModel):
    """``GET /api/metric-views/consistency/link-check``: warnings for a prospective link."""
    entity_id: str
    iri: str
    warnings: List[LinkWarning] = Field(default_factory=list)
