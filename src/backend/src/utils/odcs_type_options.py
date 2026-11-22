"""A column's ODCS type options (``format``, ``maxLength``, ``timezone`` ...).

They are stored together in ``logical_type_options_json``. ODCS v3.1.0 puts
them under the property's ``logicalTypeOptions`` (the property schema allows
no other keys there); older Ontos exports and the editors write them flat on
the property. The export nests them from v3.1.0 on (a v3.0.x contract keeps
the flat shape it always had); the import reads both.
"""
from typing import Any, Dict, Optional

NESTED_FROM_VERSION = 'v3.1.0'


def nests_type_options(api_version: Optional[str]) -> bool:
    """Whether an export of a contract with this ``apiVersion`` writes the options
    under ``logicalTypeOptions`` (no version: v3.1.0, as the export defaults)."""
    return (api_version or NESTED_FROM_VERSION) >= NESTED_FROM_VERSION


def read_type_options(prop: Dict[str, Any]) -> Dict[str, Any]:
    """The options a property's ``logicalTypeOptions`` holds (a copy; empty when it
    has none). The caller adds the flat keys of legacy input, which win."""
    nested = prop.get('logicalTypeOptions')
    if not isinstance(nested, dict):
        return {}
    return {key: value for key, value in nested.items() if value is not None}
