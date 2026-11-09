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

# Definitions longer than this aren't parsed (the raw YAML is still shown)
MAX_DEFINITION_LENGTH = 256 * 1024
# Joins listed at most; YAML aliases can repeat a list of joins many times
MAX_JOINS = 1000


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


def _joins(entries: Any) -> List[Dict[str, Any]]:
    """Joins as ``{name, source, on, using}``, nested joins flattened after their parent.

    Walked with a stack rather than recursion, so deep nesting can't exhaust the
    call stack; a list of joins seen before (a YAML alias, possibly to itself)
    isn't walked again.
    """
    joins: List[Dict[str, Any]] = []
    seen = set()
    stack = [entries]
    while stack and len(joins) < MAX_JOINS:
        entry = stack.pop()
        if isinstance(entry, list):
            if id(entry) in seen:
                continue
            seen.add(id(entry))
            stack.extend(reversed(entry))
            continue
        if not isinstance(entry, dict):
            continue
        using = entry.get('using')
        joins.append({
            'name': entry.get('name'),
            'source': entry.get('source'),
            # YAML 1.1 reads a bare `on:` key as the boolean True
            'on': entry.get('on', entry.get(True)),
            'using': [str(c) for c in using] if isinstance(using, list) else None,
        })
        stack.append(entry.get('joins'))
    return joins


def _materialization(spec: Any) -> Optional[Dict[str, Any]]:
    """The materialization block as ``{schedule, mode, materialized_views: [{name, type}]}``."""
    if not isinstance(spec, dict):
        return None
    views = [
        {'name': v.get('name'), 'type': v.get('type')}
        for v in spec.get('materialized_views') or [] if isinstance(v, dict)
    ]
    return {'schedule': spec.get('schedule'), 'mode': spec.get('mode'), 'materialized_views': views}


def parse_metric_view_definition(definition: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a metric view's YAML definition.

    Returns ``{version, source, filter, joins, dimensions, measures,
    materialization}`` (joins as ``{name, source, on, using}``), or None when the
    definition is missing, longer than ``MAX_DEFINITION_LENGTH``, nested too
    deeply for the YAML parser, or isn't a YAML mapping. ``fields`` is read as a
    synonym of ``dimensions`` (the term the current metric view docs use).
    """
    if not definition or not definition.strip():
        return None
    if len(definition) > MAX_DEFINITION_LENGTH:
        logger.warning("Metric view definition not parsed: %d characters (limit %d)",
                       len(definition), MAX_DEFINITION_LENGTH)
        return None
    try:
        spec = yaml.safe_load(definition)
    except yaml.YAMLError as e:
        logger.warning("Metric view definition is not valid YAML: %s", e)
        return None
    except RecursionError:
        # PyYAML composes nested nodes recursively: a few hundred levels exhaust the stack
        logger.warning("Metric view definition not parsed: nested too deeply")
        return None
    if not isinstance(spec, dict):
        return None
    dimensions = spec.get('dimensions') if spec.get('dimensions') is not None else spec.get('fields')
    return {
        'version': None if spec.get('version') is None else str(spec['version']),
        'source': spec.get('source'),
        'filter': spec.get('filter'),
        'joins': _joins(spec.get('joins')),
        'dimensions': _fields(dimensions),
        'measures': _fields(spec.get('measures')),
        'materialization': _materialization(spec.get('materialization')),
    }
