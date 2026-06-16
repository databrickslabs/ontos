"""Name normalisation + similarity helpers.

Ported from onyx_ontology/src/databricks_onyx/core/agents/mapping_suggester.py
(reason strings + scoring kept identical so behaviour stays reproducible
against the source's regression tests).

Adds an irregular-plurals table the source brief calls out explicitly — without
it, suggestions for tables named ``people``, ``children``, etc. silently
drop. See PRD bug 1.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_NORM_RE = re.compile(r"[^a-z0-9]+")

# Irregular plurals → singular. Looked up before the generic -ies / -s rules.
# Keep small and human-curated; this is not meant to be a full inflector.
_IRREGULAR_PLURALS: dict[str, str] = {
    "people": "person",
    "children": "child",
    "men": "man",
    "women": "woman",
    "feet": "foot",
    "teeth": "tooth",
    "geese": "goose",
    "mice": "mouse",
    "leaves": "leaf",
    "lives": "life",
    "knives": "knife",
    "selves": "self",
    "wives": "wife",
    "data": "data",          # mass noun — already singular semantically
    "criteria": "criterion",
    "phenomena": "phenomenon",
    "indices": "index",
    "matrices": "matrix",
    "vertices": "vertex",
}


def normalize(s: str) -> str:
    """Lowercase + strip every non-alphanumeric character.

    Used as the canonical comparable form for table/column/attribute names so
    snake_case / camelCase / kebab-case all collapse to the same string.
    """
    return _NORM_RE.sub("", (s or "").lower())


def depluralize(s: str) -> str:
    """Best-effort singularisation. Checks irregulars first, then the common
    -ies → -y and -s → '' rules. Never returns an empty string for non-empty
    input.
    """
    if not s:
        return s
    irregular = _IRREGULAR_PLURALS.get(s.lower())
    if irregular is not None:
        return irregular
    if len(s) > 3 and s.endswith("ies"):
        return s[:-3] + "y"
    if len(s) > 2 and s.endswith("s") and not s.endswith("ss"):
        return s[:-1]
    return s


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(a=a, b=b).ratio()


def local_name(uri: str) -> str:
    """Fragment / last-segment from an IRI. Survives URIs with neither '#' nor
    '/' by returning the whole string."""
    if not uri:
        return ""
    for sep in ("#", "/"):
        if sep in uri:
            return uri.rsplit(sep, 1)[-1]
    return uri


def to_pascal(s: str) -> str:
    parts = re.split(r"[_\s\-/]+", (s or "").strip())
    pas = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return depluralize(pas) or "Entity"


def to_camel(s: str) -> str:
    pas = to_pascal(s)
    return pas[:1].lower() + pas[1:] if pas else "field"


# ---------- Type compatibility ----------

_TYPE_GROUPS: dict[str, set[str]] = {
    "string": {"string", "varchar", "text", "char", "uuid"},
    "int": {"int", "integer", "smallint", "bigint", "long", "tinyint", "short"},
    "float": {"float", "double", "decimal", "numeric", "real"},
    "bool": {"boolean", "bool"},
    "date": {"date", "datetime", "timestamp", "time", "datetime2"},
}


def type_group(t: str) -> str:
    t = (t or "").lower()
    for group, members in _TYPE_GROUPS.items():
        if any(t.startswith(m) or t == m for m in members):
            return group
    return "string"


def simplify_xsd(s: str) -> str:
    """Drop the ``xsd:`` / namespace prefix from a typed range, leaving the
    primitive name (string, integer, dateTime…)."""
    if not s:
        return ""
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    if ":" in s:
        return s.rsplit(":", 1)[-1]
    return s


def types_compatible(column_type: str, attr_range: str) -> bool:
    """Loose type compatibility used by the heuristic engine.

    Returns True when groups match, or when the attribute's declared range is
    a string (everything can land as a string). Mirrors the source behaviour.
    """
    col_group = type_group(column_type)
    attr_group = type_group(simplify_xsd(attr_range))
    if attr_group == col_group:
        return True
    if attr_group == "string":
        return True
    return False


def xsd_for_column(column_type: str) -> str:
    return {
        "string": "xsd:string",
        "int": "xsd:long",
        "float": "xsd:double",
        "bool": "xsd:boolean",
        "date": "xsd:dateTime",
    }[type_group(column_type)]
