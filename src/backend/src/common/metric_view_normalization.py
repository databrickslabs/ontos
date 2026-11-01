"""A normalized form and a digest of a metric view definition.

Unity Catalog rewrites the YAML it stores: ``fields`` becomes ``dimensions``,
the top-level ``comment`` becomes the view's comment, and ``display_name`` and
``format`` are not kept in the stored text (#1079). Comparing the raw text
would report changes nobody made, so definitions are compared in this form:

- the spec parsed by ``parse_metric_view_definition``, which already reads
  ``fields`` as ``dimensions`` and drops the top-level ``comment``;
- without ``display_name`` and ``format`` on dimensions and measures;
- with runs of whitespace in expressions (``source``, ``filter``, a join's
  ``on`` and ``source``, a field's ``expr``, a window's ``order``, ``range``
  and ``offset``) collapsed to one space and trimmed;
- without keys whose value is None, so an unset key equals a missing one;
- as JSON with sorted keys, so key order doesn't count.

List order is kept: reordering dimensions, measures or joins changes the
order of the view's columns, which consumers see.

The digest is the SHA-256 (hex) of that JSON, serialized compactly
(``sort_keys``, ``(',', ':')`` separators, UTF-8 without ASCII escapes): a
standard hash any verifier can recompute from the stored normalized JSON.

Pure functions, no database: the drift check of #1124 and the KPI
fingerprint of #1263 share them.
"""
import hashlib
import json
import re
from typing import Any, Dict, Optional

from src.common.metric_views import parse_metric_view_definition

# Keys Unity Catalog doesn't keep in the stored text, left out of the comparison
EXCLUDED_FIELD_KEYS = frozenset({'display_name', 'format'})
# Keys holding SQL expressions, whose whitespace doesn't count
EXPRESSION_KEYS = frozenset({'source', 'filter', 'on', 'expr', 'order', 'range', 'offset'})

_WHITESPACE = re.compile(r'\s+')


def collapse_whitespace(text: str) -> str:
    """``text`` with each run of whitespace replaced by one space, trimmed."""
    return _WHITESPACE.sub(' ', text).strip()


def _clean(value: Any, key: Optional[str] = None) -> Any:
    """``value`` without None entries, with expression whitespace collapsed."""
    if isinstance(value, dict):
        return {k: _clean(v, k) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str) and key in EXPRESSION_KEYS:
        return collapse_whitespace(value)
    return value


def _field(field: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in field.items() if k not in EXCLUDED_FIELD_KEYS}


def normalize_metric_view(spec: Dict[str, Any]) -> Dict[str, Any]:
    """The normalized form of a parsed spec (``parse_metric_view_definition``)."""
    normalized = dict(spec)
    for kind in ('dimensions', 'measures'):
        normalized[kind] = [
            _field(f) for f in spec.get(kind) or [] if isinstance(f, dict)
        ]
    return _clean(normalized)


def canonical_json(normalized: Dict[str, Any]) -> str:
    """The JSON text the digest is computed on."""
    return json.dumps(
        normalized, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str,
    )


def definition_digest(normalized: Dict[str, Any]) -> str:
    """The SHA-256 hex digest of a normalized definition."""
    return hashlib.sha256(canonical_json(normalized).encode('utf-8')).hexdigest()


def normalize_definition(definition: Optional[str]) -> Optional[Dict[str, Any]]:
    """The normalized form of a YAML definition, or None when it can't be parsed."""
    spec = parse_metric_view_definition(definition)
    return normalize_metric_view(spec) if spec is not None else None
