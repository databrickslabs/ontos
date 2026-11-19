"""Map a physical (Databricks / BigQuery / SQL) column type to an ODCS v3.1 logical type."""
import re
from typing import Any, Dict, List, Optional

ODCS_LOGICAL_TYPES = frozenset({
    "string", "date", "timestamp", "time", "number", "integer", "object", "array", "boolean",
})

_BY_BASE_TYPE = {
    "date": "date",
    "timestamp": "timestamp",
    "timestamp_ntz": "timestamp",
    "timestamp_ltz": "timestamp",
    "datetime": "timestamp",
    "datetime2": "timestamp",
    "smalldatetime": "timestamp",
    "datetimeoffset": "timestamp",
    "timestamptz": "timestamp",
    "timestamp_tz": "timestamp",
    "timestamp_s": "timestamp",
    "timestamp_ms": "timestamp",
    "timestamp_ns": "timestamp",
    "time": "time",
    "timetz": "time",
    "time_tz": "time",
    "tinyint": "integer",
    "byte": "integer",
    "smallint": "integer",
    "short": "integer",
    "int": "integer",
    "integer": "integer",
    "bigint": "integer",
    "long": "integer",
    "mediumint": "integer",
    "int1": "integer",
    "int2": "integer",
    "int4": "integer",
    "int8": "integer",
    "int16": "integer",
    "int32": "integer",
    "int64": "integer",
    "uint": "integer",
    "uint8": "integer",
    "uint16": "integer",
    "uint32": "integer",
    "uint64": "integer",
    "utinyint": "integer",
    "usmallint": "integer",
    "uinteger": "integer",
    "ubigint": "integer",
    "unsigned": "integer",
    "signed": "integer",
    "float": "number",
    "real": "number",
    "double": "number",
    "float4": "number",
    "float8": "number",
    "float16": "number",
    "float32": "number",
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


# Logical types ODCS added in v3.1.0; the v3.0.x and v2.2.x schemas don't list them.
_V31_ONLY_FALLBACK = {"timestamp": "date", "time": "string"}


def has_v31_logical_types(api_version: Optional[str]) -> bool:
    """Whether a contract with ``api_version`` may use ``timestamp`` and ``time``.

    ``None`` or a value that isn't a version (``v3.1.0``, ``3.0.2``) counts as the
    current version, v3.1.0 being the default of a new contract.
    """
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.\d+)?", (api_version or "").strip().lower())
    if not match:
        return True
    return (int(match.group(1)), int(match.group(2))) >= (3, 1)


def logical_type_for_version(logical_type: str, api_version: Optional[str]) -> str:
    """``logical_type`` as the ODCS version ``api_version`` lists it.

    Below v3.1.0, ``timestamp`` becomes ``date`` and ``time`` becomes ``string``.
    """
    if has_v31_logical_types(api_version):
        return logical_type
    return _V31_ONLY_FALLBACK.get(logical_type, logical_type)


def odcs_column_logical_type(
    stored: Optional[str], physical_type: Optional[str], api_version: Optional[str],
) -> str:
    """ODCS logical type of a column for a contract with ``api_version``."""
    return logical_type_for_version(column_logical_type(stored, physical_type), api_version)


def schemas_for_version(
    schemas: List[Dict[str, Any]], api_version: Optional[str],
) -> List[Dict[str, Any]]:
    """Inferred ``schemas`` with each property's ``logicalType`` valid for ``api_version``."""
    if has_v31_logical_types(api_version):
        return schemas
    for schema in schemas:
        for prop in schema.get("properties") or []:
            if isinstance(prop.get("logicalType"), str):
                prop["logicalType"] = logical_type_for_version(prop["logicalType"], api_version)
    return schemas
