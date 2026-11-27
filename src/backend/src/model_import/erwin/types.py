"""Data type mapping for erwin models.

erwin attributes carry a logical type (DBMS-neutral, e.g. ``VARCHAR(100)``)
and a physical type in the dialect of the model's target DBMS (e.g. Oracle
``VARCHAR2(100)``). From them we derive:

- the XSD range of the concept's datatype property,
- the ODCS ``logicalType`` of the contract property,
- the Databricks SQL type, used in migration mode and for drift checks
  against Unity Catalog columns.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from rdflib.namespace import XSD

# Normalized DBMS keys. erwin writes the target either as a name or as a
# numeric code; codes map to "other" unless the user picks the dialect.
DBMS_KEYS = (
    "oracle", "sqlserver", "teradata", "db2", "postgresql", "mysql", "snowflake",
    "databricks", "other",
)

_DBMS_ALIASES = (
    ("databricks", "databricks"), ("spark", "databricks"), ("delta", "databricks"),
    ("oracle", "oracle"), ("sql server", "sqlserver"), ("sqlserver", "sqlserver"),
    ("azure sql", "sqlserver"), ("synapse", "sqlserver"), ("teradata", "teradata"),
    ("db2", "db2"), ("postgres", "postgresql"), ("redshift", "postgresql"),
    ("mysql", "mysql"), ("mariadb", "mysql"), ("snowflake", "snowflake"),
)


def normalize_dbms(name: Optional[str]) -> str:
    if not name:
        return "other"
    n = name.strip().lower()
    for alias, key in _DBMS_ALIASES:
        if alias in n:
            return key
    return "other"


_TYPE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ ]*?)\s*(?:\(\s*([^)]*)\))?\s*$")


def split_type(type_str: Optional[str]) -> Tuple[str, Tuple[int, ...]]:
    """``NUMBER(12,2)`` → (``NUMBER``, (12, 2)); unknown args are dropped."""
    if not type_str:
        return "", ()
    m = _TYPE_RE.match(type_str)
    if not m:
        return type_str.strip().upper(), ()
    base = re.sub(r"\s+", " ", m.group(1).strip().upper())
    args = []
    for part in (m.group(2) or "").split(","):
        part = part.strip().split(" ")[0]
        if part.isdigit():
            args.append(int(part))
    return base, tuple(args)


# Base type → family. Families drive all three mappings.
_FAMILIES = {
    "integer": {
        "INT", "INTEGER", "SMALLINT", "TINYINT", "BIGINT", "BYTEINT", "INT2", "INT4", "INT8",
        "SERIAL", "BIGSERIAL", "LONG", "PLS_INTEGER", "BINARY_INTEGER",
    },
    "decimal": {"DECIMAL", "NUMERIC", "NUMBER", "DEC", "MONEY", "SMALLMONEY"},
    "float": {
        "FLOAT", "REAL", "DOUBLE", "DOUBLE PRECISION", "BINARY_FLOAT", "BINARY_DOUBLE",
        "FLOAT4", "FLOAT8",
    },
    "string": {
        "CHAR", "VARCHAR", "VARCHAR2", "NCHAR", "NVARCHAR", "NVARCHAR2", "TEXT", "NTEXT",
        "STRING", "CLOB", "NCLOB", "LONG VARCHAR", "CHARACTER", "CHARACTER VARYING",
        "UNIQUEIDENTIFIER", "UUID", "XML", "JSON", "JSONB", "GRAPHIC", "VARGRAPHIC",
        "TINYTEXT", "MEDIUMTEXT", "LONGTEXT", "ENUM", "SET",
    },
    "date": {"DATE"},
    "timestamp": {
        "TIMESTAMP", "DATETIME", "DATETIME2", "SMALLDATETIME", "DATETIMEOFFSET",
        "TIMESTAMP WITH TIME ZONE", "TIMESTAMP WITH LOCAL TIME ZONE", "TIMESTAMPTZ",
        "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "TIMESTAMP_TZ",
    },
    "time": {"TIME", "TIMETZ"},
    "boolean": {"BOOLEAN", "BOOL", "BIT"},
    "binary": {
        "BLOB", "BINARY", "VARBINARY", "RAW", "LONG RAW", "BYTEA", "IMAGE", "BYTE", "VARBYTE",
        "TINYBLOB", "MEDIUMBLOB", "LONGBLOB",
    },
    "array": {"ARRAY"},
    "map": {"MAP"},
    "struct": {"STRUCT"},
}
_FAMILY_BY_BASE = {b: fam for fam, bases in _FAMILIES.items() for b in bases}


def type_family(type_str: Optional[str]) -> Optional[str]:
    base, args = split_type(type_str)
    if not base:
        return None
    fam = _FAMILY_BY_BASE.get(base)
    if fam is None:
        for prefix, f in (("TIMESTAMP", "timestamp"), ("INTERVAL", "string"), ("VARCHAR", "string")):
            if base.startswith(prefix):
                return f
        return None
    # Oracle NUMBER without scale is an integer; NUMBER(p,0) too.
    if fam == "decimal" and base == "NUMBER" and (len(args) <= 1):
        return "integer" if args else "decimal"
    if fam == "decimal" and len(args) == 2 and args[1] == 0 and base in ("NUMBER", "NUMERIC", "DECIMAL"):
        return "integer"
    return fam


_XSD_BY_FAMILY = {
    "integer": XSD.integer, "decimal": XSD.decimal, "float": XSD.double, "string": XSD.string,
    "date": XSD.date, "timestamp": XSD.dateTime, "time": XSD.time, "boolean": XSD.boolean,
    "binary": XSD.base64Binary,
}


def xsd_range(logical_type: Optional[str], physical_type: Optional[str] = None):
    fam = type_family(logical_type) or type_family(physical_type)
    return _XSD_BY_FAMILY.get(fam, XSD.string)


# ODCS v3.1 logicalType values: string, date, timestamp, time, number, integer,
# object, array, boolean
_ODCS_BY_FAMILY = {
    "integer": "integer", "decimal": "number", "float": "number", "string": "string",
    "date": "date", "timestamp": "timestamp", "time": "time", "boolean": "boolean",
    "binary": "string", "array": "array", "map": "object", "struct": "object",
}


def odcs_logical_type(logical_type: Optional[str], physical_type: Optional[str] = None) -> str:
    fam = type_family(logical_type) or type_family(physical_type)
    return _ODCS_BY_FAMILY.get(fam, "string")


def databricks_type(type_str: Optional[str], logical_fallback: Optional[str] = None) -> Optional[str]:
    """The Databricks SQL type for a modeled type, or None when unknown."""
    src = type_str or logical_fallback
    base, args = split_type(src)
    fam = type_family(src)
    if fam is None:
        return None
    if base in ("ARRAY", "MAP", "STRUCT"):
        return src.strip().upper()
    if fam == "integer":
        if base in ("SMALLINT", "INT2"):
            return "SMALLINT"
        if base in ("TINYINT", "BYTEINT"):
            return "TINYINT"
        if base in ("BIGINT", "INT8", "BIGSERIAL", "LONG"):
            return "BIGINT"
        if base in ("NUMBER", "NUMERIC", "DECIMAL") and args:
            p = args[0]
            if p <= 4:
                return "SMALLINT"
            if p <= 9:
                return "INT"
            if p <= 18:
                return "BIGINT"
            return f"DECIMAL({min(p, 38)},0)"
        return "INT"
    if fam == "decimal":
        if base in ("MONEY",):
            return "DECIMAL(19,4)"
        if base == "SMALLMONEY":
            return "DECIMAL(10,4)"
        if len(args) == 2:
            return f"DECIMAL({min(args[0], 38)},{min(args[1], 38)})"
        if len(args) == 1:
            return f"DECIMAL({min(args[0], 38)},0)"
        return "DECIMAL(38,10)"
    if fam == "float":
        return "FLOAT" if base in ("REAL", "FLOAT4", "BINARY_FLOAT") else "DOUBLE"
    if fam == "string":
        return "STRING"
    if fam == "date":
        return "DATE"
    if fam == "timestamp":
        return "TIMESTAMP_NTZ" if base in ("DATETIME", "DATETIME2", "SMALLDATETIME", "TIMESTAMP_NTZ") else "TIMESTAMP"
    if fam == "time":
        return "STRING"
    if fam == "boolean":
        return "BOOLEAN"
    if fam == "binary":
        return "BINARY"
    return None


def migration_warning(type_str: Optional[str], dbms: str) -> Optional[str]:
    """A note when the Databricks type is not a like-for-like mapping."""
    base, _ = split_type(type_str)
    if dbms == "oracle" and base == "DATE":
        return "Oracle DATE carries a time of day; mapped to TIMESTAMP."
    if type_family(type_str) == "time":
        return f"{base} has no Databricks equivalent; mapped to STRING."
    return None


def databricks_type_for(type_str: Optional[str], dbms: str, logical_fallback: Optional[str] = None) -> Optional[str]:
    """Databricks type with DBMS-specific semantics (Oracle DATE is a timestamp)."""
    base, _ = split_type(type_str)
    if dbms == "oracle" and base == "DATE":
        return "TIMESTAMP"
    return databricks_type(type_str, logical_fallback)


def same_type(modeled: Optional[str], actual: Optional[str], dbms: str) -> bool:
    """Whether a modeled physical type matches a UC column type, for drift checks.

    Compares the normalized Databricks types; if either side is unknown, the
    families are compared instead.
    """
    if not modeled or not actual:
        return True
    a = databricks_type_for(modeled, dbms)
    b = databricks_type(actual)
    if a and b:
        if a == b:
            return True
        # INT vs BIGINT etc. are the same family: report only real changes.
        fam_a, fam_b = type_family(a), type_family(b)
        if fam_a == fam_b == "integer":
            return True
        if a.startswith("DECIMAL") and b.startswith("DECIMAL"):
            return split_type(a)[1] == split_type(b)[1]
        if {a, b} <= {"TIMESTAMP", "TIMESTAMP_NTZ"}:
            return True
        return False
    return type_family(modeled) == type_family(actual)
