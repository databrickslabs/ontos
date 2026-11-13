"""Map a physical (Databricks / SQL) column type to an ODCS v3.1 logical type."""
import re
from typing import Optional

_BY_BASE_TYPE = {
    "date": "date",
    "timestamp": "timestamp",
    "timestamp_ntz": "timestamp",
    "timestamp_ltz": "timestamp",
    "datetime": "timestamp",
    "tinyint": "integer",
    "byte": "integer",
    "smallint": "integer",
    "short": "integer",
    "int": "integer",
    "integer": "integer",
    "bigint": "integer",
    "long": "integer",
    "float": "number",
    "real": "number",
    "double": "number",
    "decimal": "number",
    "dec": "number",
    "numeric": "number",
    "number": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "array": "array",
    "struct": "object",
    "map": "object",
    "variant": "object",
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
