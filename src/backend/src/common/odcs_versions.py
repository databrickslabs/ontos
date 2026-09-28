"""
ODCS version registry and feature-capability gating.

Single source of truth for which Open Data Contract Standard (ODCS) apiVersions
this app supports, which vendored JSON schema validates each version, and which
ODCS features are available at a given apiVersion. Used to keep import/export
strictly version-aware so that a contract stored as (say) v3.0.1 always round-trips
back as v3.0.1 and never emits fields that its schema version does not allow.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Tuple

# Ordered oldest -> newest. The last entry is the latest/default for new contracts.
SUPPORTED_ODCS_VERSIONS = [
    "v2.2.0", "v2.2.1", "v2.2.2",
    "v3.0.0", "v3.0.1", "v3.0.2",
    "v3.1.0",
    "v3.2.0",
]

LATEST_ODCS_VERSION = "v3.2.0"
# Default apiVersion assigned to newly-created contracts (see user decision).
DEFAULT_ODCS_VERSION = "v3.2.0"

_SCHEMA_DIR = Path(__file__).parent.parent / "schemas"

# Map each apiVersion to the vendored schema file that validates it. Versions
# without a dedicated schema fall back to the closest available family schema
# (the pre-3.2.0 behaviour used the v3.1.0 schema for everything).
SCHEMA_FILE_BY_VERSION: Dict[str, Path] = {
    "v3.2.0": _SCHEMA_DIR / "odcs-json-schema-v3.2.0.json",
    "v3.1.0": _SCHEMA_DIR / "odcs-json-schema-v3.1.0.json",
    "v3.0.2": _SCHEMA_DIR / "odcs-json-schema-v3.0.2.json",
    "v3.0.1": _SCHEMA_DIR / "odcs-json-schema-v3.0.2.json",
    "v3.0.0": _SCHEMA_DIR / "odcs-json-schema-v3.0.2.json",
    # No vendored v2.x schema; validate against the oldest v3 family schema.
    "v2.2.2": _SCHEMA_DIR / "odcs-json-schema-v3.0.2.json",
    "v2.2.1": _SCHEMA_DIR / "odcs-json-schema-v3.0.2.json",
    "v2.2.0": _SCHEMA_DIR / "odcs-json-schema-v3.0.2.json",
}

# Minimum apiVersion at which each app-visible ODCS feature becomes valid.
# Features NOT listed here are assumed valid at every supported version.
# Verified against the vendored schemas: context/vector/map/semanticType/string
# ports are all new in v3.2.0; contractCreatedTs has existed since v3.0.x.
_FEATURE_MIN_VERSION: Dict[str, str] = {
    "context": "v3.2.0",           # RFC-0038 context block (contract + schema object)
    "vector": "v3.2.0",            # RFC-0042 vector logicalType
    "map": "v3.2.0",               # RFC-0030 map logicalType
    "semantic_type": "v3.2.0",     # property semanticType
    "string_port": "v3.2.0",       # RFC-0050 runtime-variable port (string ${VAR})
}


def _parse(version: str) -> Tuple[int, ...]:
    """Parse 'v3.2.0' -> (3, 2, 0) for correct numeric ordering.

    Robust to a missing leading 'v' and to fewer/more segments; non-numeric
    input sorts as (0,) so it compares below any real version.
    """
    if not version:
        return (0,)
    cleaned = version.lstrip("vV").strip()
    parts = re.split(r"[.\-+]", cleaned)
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
        else:
            break
    return tuple(nums) if nums else (0,)


def normalize(version: Optional[str]) -> str:
    """Return a supported apiVersion string, defaulting unknown/empty to latest."""
    if version and version in SUPPORTED_ODCS_VERSIONS:
        return version
    return DEFAULT_ODCS_VERSION


def is_supported(version: Optional[str]) -> bool:
    return bool(version) and version in SUPPORTED_ODCS_VERSIONS


def at_least(version: Optional[str], minimum: str) -> bool:
    """True if `version` is >= `minimum` by numeric ordering."""
    return _parse(normalize(version)) >= _parse(minimum)


def supports(feature: str, version: Optional[str]) -> bool:
    """True if `feature` is valid at the given apiVersion.

    Unknown features are treated as always-available (fail open for fields that
    predate the registry); gated features require version >= their minimum.
    """
    minimum = _FEATURE_MIN_VERSION.get(feature)
    if minimum is None:
        return True
    return at_least(version, minimum)


def schema_path_for(version: Optional[str]) -> Path:
    """Vendored JSON schema file that validates the given apiVersion."""
    return SCHEMA_FILE_BY_VERSION.get(normalize(version), SCHEMA_FILE_BY_VERSION[LATEST_ODCS_VERSION])


def upgrade_targets(current: Optional[str]) -> list[str]:
    """Supported versions strictly newer than `current` (offered as upgrade targets)."""
    cur = _parse(normalize(current))
    return [v for v in SUPPORTED_ODCS_VERSIONS if _parse(v) > cur]
