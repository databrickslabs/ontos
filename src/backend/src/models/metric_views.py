"""API models for Unity Catalog metric views and their concept links.

A metric view is linked to a concept as ``entity_type = uc_table`` with
``entity_id = catalog.schema.view``; a dimension or measure as ``uc_column``
with ``entity_id = catalog.schema.view.field`` (``field`` is the ``name`` in the
YAML spec). The links are the shared ``entity_semantic_links`` rows, so they
also show up on the concept's linked objects.
"""
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


class MetricViewRead(BaseModel):
    """A metric view's YAML, its parsed spec (None when unparseable) and its links."""
    definition: str
    metric_view: Optional[Dict[str, Any]] = None
    links: MetricViewLinks
