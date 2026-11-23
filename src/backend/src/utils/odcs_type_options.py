"""A column's ODCS type options (``format``, ``maxLength``, ``timezone`` ...).

They are stored together in ``logical_type_options_json``. ODCS v3.x puts them
under the property's ``logicalTypeOptions``, with a fixed set of keys per
``logicalType``; the property schema allows no other keys (bundled schemas:
v3.0.2 and v3.1.0, ``unevaluatedProperties: false``). Older Ontos exports and
the editors write them flat on the property.

The export writes:
- the options ODCS defines for the column's type under ``logicalTypeOptions``;
- an array's item type as ``items.logicalType`` (the ODCS place for it);
- any other stored option (``precision``, ``customFormat`` ...) as a column
  custom property ``ontos.<option>``, so the export validates and the import
  reads it back.
The import reads all of these, and the flat keys of older exports.
"""
from typing import Any, Dict, List, Optional, Tuple

OPTION_PROPERTY_PREFIX = 'ontos.'
# How an object column's `logicalTypeOptions.required` (property names) is stored: the
# contract API shows the options flat, where `required` is the column's own flag
OBJECT_REQUIRED_KEY = 'requiredProperties'
# ODCS options the schema editor neither shows nor sends: an editor save keeps them
# (utils/schema_editor_fields); the contract API and a flat save carry them as is
EDITOR_UNSENT_OPTIONS = ('exclusiveMinimum', 'exclusiveMaximum', 'uniqueItems',
                         'minProperties', 'maxProperties', OBJECT_REQUIRED_KEY,
                         'defaultTimezone')

# ODCS logicalType values (an `items.logicalType` must be one of them)
LOGICAL_TYPES = frozenset(
    ('string', 'date', 'timestamp', 'time', 'number', 'integer', 'object', 'array', 'boolean'))

_NUMERIC = frozenset(('multipleOf', 'maximum', 'exclusiveMaximum', 'minimum', 'exclusiveMinimum',
                      'format'))
_DATE = frozenset(('format', 'exclusiveMaximum', 'maximum', 'exclusiveMinimum', 'minimum'))
# The keys `logicalTypeOptions` allows per logicalType (from the bundled schemas); a type
# not listed has no restriction.
_ALLOWED_V302 = {
    'string': frozenset(('minLength', 'maxLength', 'pattern', 'format')),
    'date': _DATE,
    'integer': _NUMERIC,
    'number': _NUMERIC,
    'object': frozenset(('maxProperties', 'minProperties', 'required')),
    'array': frozenset(('maxItems', 'minItems', 'uniqueItems')),
}
_ALLOWED_V310 = {
    **_ALLOWED_V302,
    'timestamp': _DATE | {'timezone', 'defaultTimezone'},
    'time': _DATE | {'timezone', 'defaultTimezone'},
}


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _number(v: Any) -> bool:
    return _int(v) or isinstance(v, float)


def _text(v: Any) -> bool:
    return isinstance(v, str)


# Every option a column stores, with the values it can hold (the ColumnProperty field
# types); other keys, and values of another type, are not stored (one bad value would
# make the contract API fail to read the whole contract).
_OPTION_CHECKS = {
    'minLength': _int, 'maxLength': _int, 'pattern': _text,
    # numbers, or date-time text on a date / timestamp / time column
    'minimum': lambda v: _number(v) or _text(v), 'maximum': lambda v: _number(v) or _text(v),
    'exclusiveMinimum': lambda v: isinstance(v, bool) or _number(v) or _text(v),
    'exclusiveMaximum': lambda v: isinstance(v, bool) or _number(v) or _text(v),
    'multipleOf': _number, 'precision': _int,
    'format': _text, 'timezone': lambda v: isinstance(v, (bool, str)), 'customFormat': _text,
    'defaultTimezone': _text,
    'itemType': _text, 'minItems': _int, 'maxItems': _int,
    'uniqueItems': lambda v: isinstance(v, bool),
    'minProperties': _int, 'maxProperties': _int,
    OBJECT_REQUIRED_KEY: lambda v: isinstance(v, list) and all(isinstance(i, str) for i in v),
}


def valid_type_options(options: Dict[str, Any]) -> Dict[str, Any]:
    """The options a column can store: known keys with a value of their type."""
    return {k: v for k, v in options.items()
            if k in _OPTION_CHECKS and v is not None and _OPTION_CHECKS[k](v)}


def nests_type_options(api_version: Optional[str]) -> bool:
    """Whether an export of a contract with this ``apiVersion`` writes the options
    under ``logicalTypeOptions``: every ODCS v3.x (and no version, which the export
    writes as v3.1.0). The nested form is the spec form in v3.0.2 as well, which
    defines ``logicalTypeOptions`` on the property. The flat keys fail the bundled
    v3.0.2 schemas (plain and ``-strict``: ``unevaluatedProperties: false`` on the
    property) under a 2019-09 validator."""
    return not api_version or api_version >= 'v3'


def _allowed(logical_type: Optional[str], api_version: Optional[str]):
    table = _ALLOWED_V302 if (api_version or 'v3.1.0') < 'v3.1.0' else _ALLOWED_V310
    return table.get(logical_type or 'string')


def split_type_options(
    logical_type: Optional[str], options: Dict[str, Any], api_version: Optional[str],
) -> Tuple[Dict[str, Any], Optional[str], List[Dict[str, Any]]]:
    """The stored options as the export writes them: ``(logicalTypeOptions, item
    type for items.logicalType, ontos.* custom properties)``."""
    allowed = _allowed(logical_type, api_version)
    nested: Dict[str, Any] = {}
    extra: List[Dict[str, Any]] = []
    item_type = None
    for key, value in options.items():
        if value is None:
            continue
        if key == OBJECT_REQUIRED_KEY and logical_type == 'object':
            key = 'required'
        if key == 'itemType' and logical_type == 'array' and value in LOGICAL_TYPES:
            item_type = value
        elif key != 'itemType' and (allowed is None or key in allowed):
            nested[key] = value
        else:
            extra.append({'property': f'{OPTION_PROPERTY_PREFIX}{key}', 'value': value})
    return nested, item_type, extra


def read_type_options(prop: Dict[str, Any]) -> Dict[str, Any]:
    """The options of a property that aren't flat on it: its ``logicalTypeOptions``,
    ``items.logicalType`` (as ``itemType``) and ``ontos.*`` custom properties. The
    caller adds the flat keys of legacy input, which win."""
    options: Dict[str, Any] = {}
    nested = prop.get('logicalTypeOptions')
    if isinstance(nested, dict):
        options.update({k: v for k, v in nested.items() if v is not None})
        if 'required' in options:
            # an object's required property names; `required` is the column's flag
            options[OBJECT_REQUIRED_KEY] = options.pop('required')
    items = prop.get('items')
    if isinstance(items, dict) and isinstance(items.get('logicalType'), str):
        options['itemType'] = items['logicalType']
    for key, value in option_properties(prop.get('customProperties')).items():
        options.setdefault(key, value)
    return options


def _is_option_property(name: Any) -> bool:
    """An ``ontos.<option>`` custom property of a known option (any other stays a
    custom property)."""
    return isinstance(name, str) and name.startswith(OPTION_PROPERTY_PREFIX) \
        and name[len(OPTION_PROPERTY_PREFIX):] in _OPTION_CHECKS


def option_properties(custom_properties: Any) -> Dict[str, Any]:
    """The ``ontos.*`` options in a column's custom properties (list or map form)."""
    if isinstance(custom_properties, dict):
        items = list(custom_properties.items())
    elif isinstance(custom_properties, list):
        items = [(cp.get('property'), cp.get('value'))
                 for cp in custom_properties if isinstance(cp, dict)]
    else:
        return {}
    return {name[len(OPTION_PROPERTY_PREFIX):]: value
            for name, value in items if _is_option_property(name) and value is not None}


def without_option_properties(custom_properties: Any) -> Any:
    """The column's custom properties without the ``ontos.*`` options (stored as
    type options, not as custom properties)."""
    if isinstance(custom_properties, dict):
        return {k: v for k, v in custom_properties.items() if not _is_option_property(k)}
    if isinstance(custom_properties, list):
        return [cp for cp in custom_properties
                if not (isinstance(cp, dict) and _is_option_property(cp.get('property')))]
    return custom_properties
