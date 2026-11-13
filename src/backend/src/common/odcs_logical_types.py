"""Map a physical (Databricks / BigQuery / SQL) column type to an ODCS v3.1 logical type."""
import re
from typing import Optional

ODCS_LOGICAL_TYPES = frozenset({
    "string", "date", "timestamp", "time", "number", "integer", "object", "array", "boolean",
})

_BY_BASE_TYPE = {
    "date": "date",
    "timestamp": "timestamp",
    "timestamp_ntz": "timestamp",
    "timestamp_ltz": "timestamp",
    "datetime": "timestamp",
    "time": "time",
    "tinyint": "integer",
    "byte": "integer",
    "smallint": "integer",
    "short": "integer",
    "int": "integer",
    "integer": "integer",
    "bigint": "integer",
    "long": "integer",
    "int64": "integer",
    "float": "number",
    "real": "number",
    "double": "number",
    "float64": "number",
    "decimal": "number",
    "dec": "number",
    "numeric": "number",
    "bignumeric": "number",
    "number": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "struct": "object",
    "map": "object",
    "variant": "object",
    "record": "object",
    "json": "object",
    "object": "object",
}


def odcs_logical_type(physical_type: Optional[str]) -> str:
    """ODCS logical type of ``physical_type`` (``DECIMAL(10,2)`` -> ``number``).

    Matches the base type name (before ``(``, ``<`` or a space), so ``INTERVAL``
    isn't taken for an integer. Unknown types (strings, binary, interval) are
    ``string``.
    """
    if not physical_type:
        return "string"
    base = re.split(r"[\s(<]", physical_type.strip().lower(), maxsplit=1)[0]
    return _BY_BASE_TYPE.get(base, "string")


def column_logical_type(stored: Optional[str], physical_type: Optional[str]) -> str:
    """ODCS logical type of a column asset from its stored ``logical_type`` and ``data_type``.

    Connectors store other things as ``logical_type``: the Databricks one the
    Unity Catalog type name (``LONG``, ``DECIMAL``), BigQuery the field mode
    (``NULLABLE``). So the stored value is kept only when it is an ODCS logical
    type; otherwise the physical type is mapped, and when that says no more than
    ``string`` the stored value is mapped as a type name (``LONG`` -> integer).
    """
    if stored and stored.strip().lower() in ODCS_LOGICAL_TYPES:
        return stored.strip().lower()
    mapped = odcs_logical_type(physical_type)
    if mapped == "string" and stored:
        return odcs_logical_type(stored)
    return mapped
