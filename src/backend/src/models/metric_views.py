"""API models for Unity Catalog metric views and their concept links.

A metric view is linked to a concept as ``entity_type = uc_table`` with
``entity_id = catalog.schema.view``; a dimension or measure as ``uc_column``
with ``entity_id = catalog.schema.view.field`` (``field`` is the ``name`` in the
YAML spec). The links are the shared ``entity_semantic_links`` rows, so they
also show up on the concept's linked objects.
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from src.models.semantic_links import EntitySemanticLink


class MetricViewFieldLinks(BaseModel):
    """The concept links of one dimension or measure."""
    name: str
    # None for a field that is no longer in the definition
    kind: Optional[Literal['dimension', 'measure']] = None
    entity_id: str
    links: List[EntitySemanticLink] = Field(default_factory=list)


class MetricViewLinks(BaseModel):
    """A metric view's concept links: the view's own and each field's."""
    view_entity_id: str
    view_links: List[EntitySemanticLink] = Field(default_factory=list)
    # The dimensions, then the measures, in the order of the definition
    fields: List[MetricViewFieldLinks] = Field(default_factory=list)
    # Fields with links that are no longer in the definition: the links are kept
    removed_fields: List[MetricViewFieldLinks] = Field(default_factory=list)


DriftState = Literal['in_sync', 'drifted', 'unknown']


class MetricViewBaseline(BaseModel):
    """The definition a metric view's drift is checked against (its digest).

    ``approved_at`` and ``request_id`` are None for a baseline recorded from the
    first definition Ontos read, before any approved change request.
    """
    digest: str
    approved_at: Optional[datetime] = None
    request_id: Optional[str] = None
    recorded_at: Optional[datetime] = None


class MetricViewDrift(BaseModel):
    """Whether the definition in Unity Catalog still matches the baseline."""
    state: DriftState = 'unknown'
    # Digest of the definition just read; None when it couldn't be parsed
    current_digest: Optional[str] = None
    last_checked_at: Optional[datetime] = None


class MetricViewRead(BaseModel):
    """A metric view's YAML, its parsed spec (None when unparseable) and its links.

    The asset route adds the baseline, the drift state and the refresh state
    (None on the review route, which doesn't check them).
    """
    definition: str
    metric_view: Optional[Dict[str, Any]] = None
    links: MetricViewLinks
    baseline: Optional[MetricViewBaseline] = None
    drift: Optional[MetricViewDrift] = None
