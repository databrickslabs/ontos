"""Comparison operators of ODCS data quality rules.

ODCS v3.x names them ``mustBe``, ``mustNotBe``, ``mustBeGreaterThan``,
``mustBeGreaterOrEqualTo``, ``mustBeLessThan``, ``mustBeLessOrEqualTo``,
``mustBeBetween`` and ``mustNotBeBetween`` (the last two take ``[min, max]``).
The contract wizard and API use shorter names (``mustBeGt``,
``mustBeBetweenMin`` ...). Both are read; the ODCS export writes the ODCS names.
Values are stored as text (``0`` included) and exported as numbers again when
they are numbers.
"""
import json
from typing import Any, Dict, Optional

# column -> accepted keys (ODCS name first)
_SCALAR_OPERATORS = {
    'must_be': ('mustBe', 'must_be'),
    'must_not_be': ('mustNotBe', 'must_not_be'),
    'must_be_gt': ('mustBeGreaterThan', 'mustBeGt', 'must_be_gt'),
    'must_be_ge': ('mustBeGreaterOrEqualTo', 'mustBeGe', 'must_be_ge'),
    'must_be_lt': ('mustBeLessThan', 'mustBeLt', 'must_be_lt'),
    'must_be_le': ('mustBeLessOrEqualTo', 'mustBeLe', 'must_be_le'),
}
# (min column, max column) -> (ODCS [min, max] key, API min keys, API max keys)
_RANGE_OPERATORS = {
    ('must_be_between_min', 'must_be_between_max'): (
        'mustBeBetween', ('mustBeBetweenMin', 'must_be_between_min'),
        ('mustBeBetweenMax', 'must_be_between_max'),
    ),
    ('must_not_between_min', 'must_not_between_max'): (
        'mustNotBeBetween', ('mustNotBeBetweenMin', 'must_not_between_min'),
        ('mustNotBeBetweenMax', 'must_not_between_max'),
    ),
}


def _first(rule: Dict[str, Any], keys) -> Any:
    for key in keys:
        if rule.get(key) is not None:
            return rule[key]
    return None


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value)


def _as_value(text: Optional[str]) -> Any:
    """A stored value as exported: numbers (and other JSON) decoded, text as is."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def operator_columns(rule: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Column values for the operators of an incoming rule (any accepted naming)."""
    columns = {column: _as_text(_first(rule, keys)) for column, keys in _SCALAR_OPERATORS.items()}
    for (min_column, max_column), (odcs_key, min_keys, max_keys) in _RANGE_OPERATORS.items():
        low, high = _first(rule, min_keys), _first(rule, max_keys)
        pair = rule.get(odcs_key)
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            low, high = pair
        columns[min_column], columns[max_column] = _as_text(low), _as_text(high)
    return columns


def odcs_operators(check: Any) -> Dict[str, Any]:
    """The operators of a stored check, with their ODCS names."""
    out: Dict[str, Any] = {}
    for column, keys in _SCALAR_OPERATORS.items():
        value = getattr(check, column, None)
        if value is not None:
            out[keys[0]] = _as_value(value)
    for (min_column, max_column), (odcs_key, _, _) in _RANGE_OPERATORS.items():
        low, high = getattr(check, min_column, None), getattr(check, max_column, None)
        if low is not None or high is not None:
            out[odcs_key] = [_as_value(low), _as_value(high)]
    return out


def _uses_metric(api_version: Optional[str]) -> bool:
    """ODCS v3.1.0 renamed a library check's `rule` to `metric` (and requires
    it); v3.0.x only has `rule`."""
    parts = (api_version or 'v3.1.0').lstrip('vV').split('.')
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0) >= (3, 1)
    except ValueError:
        return True


# column -> ODCS key, in the order the export writes them
_CHECK_FIELDS = (
    ('stable_id', 'id'), ('description', 'description'), ('dimension', 'dimension'),
    ('business_impact', 'businessImpact'), ('severity', 'severity'), ('method', 'method'),
    ('schedule', 'schedule'), ('scheduler', 'scheduler'), ('unit', 'unit'), ('tags', 'tags'),
    ('query', 'query'), ('engine', 'engine'), ('implementation', 'implementation'),
)


def odcs_quality_check(check: Any, api_version: Optional[str]) -> Dict[str, Any]:
    """A stored quality check in ODCS form. Its name goes out as `name`, and
    the library metric as `metric` (v3.1.0) or `rule` (v3.0.x)."""
    out: Dict[str, Any] = {'type': check.type}
    if check.name:
        out['name'] = check.name
    if check.rule:
        out['metric' if _uses_metric(api_version) else 'rule'] = check.rule
    for column, key in _CHECK_FIELDS:
        value = getattr(check, column, None)
        if value:
            out[key] = value
    out.update(odcs_operators(check))
    return out
