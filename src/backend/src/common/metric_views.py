"""Unity Catalog metric view definitions.

A metric view is a Unity Catalog table of type ``METRIC_VIEW`` whose
``view_definition`` holds its YAML spec: a ``source`` (table or query), an
optional ``filter`` and ``joins``, and the ``dimensions`` and ``measures``
built on it, e.g.::

    version: 1.1
    source: main.sales.orders
    dimensions:
      - name: Order Month
        expr: DATE_TRUNC('MONTH', order_date)
    measures:
      - name: Total Revenue
        expr: SUM(amount)
"""
from typing import Any, Dict, List, Optional

import yaml

from src.common.logging import get_logger

logger = get_logger(__name__)

# Optional keys a dimension or measure may carry besides name and expr
_FIELD_EXTRAS = ('display_name', 'comment', 'format', 'synonyms')


def _fields(entries: Any) -> List[Dict[str, Any]]:
    """Dimensions or measures as ``{name, expr, ...}`` dicts; entries without a name are skipped."""
    fields: List[Dict[str, Any]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get('name'):
            continue
        field: Dict[str, Any] = {'name': str(entry['name']), 'expr': entry.get('expr')}
        for key in _FIELD_EXTRAS:
            if entry.get(key) is not None:
                field[key] = entry[key]
        fields.append(field)
    return fields


def parse_metric_view_definition(definition: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a metric view's YAML definition.

    Returns ``{version, source, filter, joins, dimensions, measures}`` (joins
    as ``{name, source, on}``), or None when the definition is missing or isn't
    a YAML mapping.
    """
    if not definition or not definition.strip():
        return None
    try:
        spec = yaml.safe_load(definition)
    except yaml.YAMLError as e:
        logger.warning("Metric view definition is not valid YAML: %s", e)
        return None
    if not isinstance(spec, dict):
        return None
    # YAML 1.1 reads a bare `on:` key as the boolean True
    joins = [
        {'name': j.get('name'), 'source': j.get('source'), 'on': j.get('on', j.get(True))}
        for j in spec.get('joins') or [] if isinstance(j, dict)
    ]
    return {
        'version': None if spec.get('version') is None else str(spec['version']),
        'source': spec.get('source'),
        'filter': spec.get('filter'),
        'joins': joins,
        'dimensions': _fields(spec.get('dimensions')),
        'measures': _fields(spec.get('measures')),
    }
