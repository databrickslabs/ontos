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

Measures may carry a ``window`` (``order``, ``range``, ``semiadditive``,
``offset``), joins a ``cardinality``, and the view top-level ``parameters``
(``name``, ``data_type``, ``default``): see the YAML reference,
https://docs.databricks.com/aws/en/metric-views/data-modeling/syntax
"""
from datetime import date
from typing import Any, Dict, List, Optional

import yaml

from src.common.logging import get_logger

logger = get_logger(__name__)

# Optional keys a dimension or measure may carry besides name and expr
_FIELD_EXTRAS = ('display_name', 'comment', 'format', 'synonyms')
# The keys of a measure's window entry
_WINDOW_KEYS = ('order', 'range', 'semiadditive', 'offset')

# Definitions longer than this aren't parsed (the raw YAML is still shown)
MAX_DEFINITION_LENGTH = 256 * 1024
# Joins listed at most; YAML aliases can repeat a list of joins many times
MAX_JOINS = 1000


def _scalar(value: Any) -> Any:
    """A YAML scalar as JSON can hold it: YAML reads ``2024-01-01`` as a date."""
    return value.isoformat() if isinstance(value, date) else value


def _window(entries: Any) -> List[Dict[str, Any]]:
    """A measure's window as ``[{order, range, semiadditive, offset}]`` (None when not set).

    The docs define ``window`` as a list; a single mapping is read as a list of one.
    """
    if isinstance(entries, dict):
        entries = [entries]
    return [
        {key: _scalar(entry.get(key)) for key in _WINDOW_KEYS}
        for entry in entries if isinstance(entry, dict)
    ] if isinstance(entries, list) else []


def _fields(entries: Any) -> List[Dict[str, Any]]:
    """Dimensions or measures as ``{name, expr, ...}`` dicts; entries without a name are skipped.

    A field carries ``window`` only when its definition sets one.
    """
    fields: List[Dict[str, Any]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get('name'):
            continue
        field: Dict[str, Any] = {'name': str(entry['name']), 'expr': entry.get('expr')}
        for key in _FIELD_EXTRAS:
            if entry.get(key) is not None:
                field[key] = entry[key]
        if entry.get('window') is not None:
            field['window'] = _window(entry['window'])
        fields.append(field)
    return fields


def _parameters(entries: Any) -> List[Dict[str, Any]]:
    """The top-level parameters as ``{name, data_type, default}`` (entries need a name)."""
    return [
        {'name': str(entry['name']), 'data_type': entry.get('data_type'),
         'default': _scalar(entry.get('default'))}
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, dict) and entry.get('name')
    ]


def _joins(entries: Any) -> List[Dict[str, Any]]:
    """Joins as ``{name, source, on, using}``, nested joins flattened after their parent.

    A join carries ``cardinality`` (``many_to_one``, ``one_to_many``) only when its
    definition sets one.

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
        join = {
            'name': entry.get('name'),
            'source': entry.get('source'),
            # YAML 1.1 reads a bare `on:` key as the boolean True
            'on': entry.get('on', entry.get(True)),
            'using': [str(c) for c in using] if isinstance(using, list) else None,
        }
        if entry.get('cardinality') is not None:
            join['cardinality'] = str(entry['cardinality'])
        joins.append(join)
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
    materialization, parameters}`` (joins as ``{name, source, on, using}``, plus
    ``cardinality`` when set; a measure with a ``window`` carries it; ``parameters``
    is ``[]`` without any), or None when the
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
        'parameters': _parameters(spec.get('parameters')),
    }


def metric_view_entity_id(fqn: str) -> str:
    """The ``uc_table`` entity id of a metric view: its ``catalog.schema.view``.

    Unity Catalog names are case-insensitive and stored lower-case, so the
    view's name is lower-cased; a field's id appends its ``name`` as written in
    the definition (``catalog.schema.view.field``).
    """
    return fqn.strip().lower()
