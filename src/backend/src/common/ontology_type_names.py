"""Canonical spelling of the entity type names that entity relationships store.

Writers used either an ontology class's local name ('LogicalEntity', 'MetricView')
or its label, which is also the asset type name ('Logical Entity', 'Metric View').
Lookups compare type strings exactly, so relationships are stored, and looked up,
by local name.
"""
import re
from typing import Optional

ONTOS_NS = "http://ontos.app/ontology#"

_WHITESPACE = re.compile(r"\s+")


def canonical_type_name(value: Optional[str]) -> Optional[str]:
    """Local name for an Ontos type given as label, local name or Ontos IRI.

    'Logical Entity' -> 'LogicalEntity', 'http://ontos.app/ontology#DataDomain' ->
    'DataDomain'. IRIs of other namespaces are kept as they are.
    """
    if value is None:
        return None
    value = value.strip()
    if value.startswith(ONTOS_NS):
        return value[len(ONTOS_NS):]
    if value.startswith(("http://", "https://")):
        return value
    return _WHITESPACE.sub("", value)
