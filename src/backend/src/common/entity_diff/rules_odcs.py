"""ODCS (data contract) diff profile and semver rules.

Rules are written from the consumer's point of view: anything that can break
an existing reader or pipeline is MAJOR, backward-compatible additions are
MINOR, documentation/metadata is PATCH, lifecycle/format bookkeeping is NONE.

Deliberate divergence from the legacy ``ContractChangeAnalyzer``: removing an
*optional* property is MAJOR here (it was a patch-level "fix"), because readers
that select the column break regardless of nullability.
"""

from typing import Any, Dict, Optional

from .engine import DiffProfile, FieldChange
from .semver import Bump, Rule, RuleSet

# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

# Custom properties Ontos writes per row (differ between versions by design).
_VOLATILE_CUSTOM_PROPERTIES = {"ontosEntityId"}

# Top-level fields that identify a row/version rather than describe content.
_VOLATILE_TOP_LEVEL = {"id", "version", "contractCreatedTs"}


def _strip(shape: str, value: Any) -> bool:
    if shape in _VOLATILE_TOP_LEVEL:
        return True
    # Nested `id`s are DB identifiers that change on every clone.
    if shape.endswith(".id"):
        return True
    if shape.endswith("customProperties[]") and isinstance(value, dict):
        return value.get("property") in _VOLATILE_CUSTOM_PROPERTIES
    return False


def _identity(item: Dict[str, Any], shape: str) -> Optional[str]:
    leaf = shape.rsplit(".", 1)[-1].removesuffix("[]")
    if leaf in ("schema", "properties"):
        return item.get("name")
    if leaf == "quality":
        # No stable id in ODCS exports; name, else type + rule/metric. An
        # unkeyable check falls back to a content hash, so editing it reads as
        # removed + added (conservative: classified like a new check).
        if item.get("name"):
            return item["name"]
        kind = item.get("rule") or item.get("metric")
        return f"{item.get('type', 'library')}:{kind}" if kind else None
    if leaf == "servers":
        return item.get("server")
    if leaf == "roles":
        return item.get("role")
    if leaf == "slaProperties":
        prop = item.get("property")
        return f"{prop}:{item['element']}" if prop and item.get("element") else prop
    if leaf in ("team", "members"):
        return item.get("username") or item.get("name")
    if leaf == "support":
        return item.get("channel") or item.get("url")
    if leaf == "customProperties":
        return item.get("property")
    if leaf == "authoritativeDefinitions":
        return f"{item.get('type')}:{item.get('url')}" if item.get("url") else None
    return item.get("name")


ODCS_PROFILE = DiffProfile(identity=_identity, strip=_strip)

# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------

# Kept from ContractChangeAnalyzer so commit-dialog suggestions don't shift.
_COMPATIBLE_TYPE_CHANGES = {
    ("double", "float"),
    ("long", "int"),
    ("timestamp", "date"),
}

# Quality-check fields that don't change what the check enforces.
_QUALITY_COSMETIC = {
    "description", "dimension", "businessImpact", "schedule", "scheduler",
    "severity", "tags", "authoritativeDefinitions", "customProperties", "name",
}

# logicalTypeOptions bounds: raising a lower bound / lowering an upper bound
# rejects previously-valid data (MAJOR); the reverse only widens (MINOR).
_LOWER_BOUNDS = {"minLength", "minimum", "exclusiveMinimum", "minItems", "minProperties"}
_UPPER_BOUNDS = {"maxLength", "maximum", "exclusiveMaximum", "maxItems", "maxProperties"}


def _type_change_bump(change: FieldChange) -> Bump:
    if change.op == "modified" and (str(change.old).lower(), str(change.new).lower()) in _COMPATIBLE_TYPE_CHANGES:
        return Bump.PATCH
    return Bump.MAJOR


def _became_true(change: FieldChange) -> Bump:
    # required/unique: tightening (→ True) breaks writers/readers; relaxing is a fix.
    return Bump.MAJOR if change.new is True else Bump.PATCH


def _added_property_bump(change: FieldChange) -> Bump:
    new = change.new if isinstance(change.new, dict) else {}
    return Bump.MAJOR if new.get("required") is True else Bump.MINOR


def _field_after(shape: str, marker: str) -> str:
    tail = shape.rsplit(marker, 1)[-1]
    return tail.split(".", 1)[0].removesuffix("[]")


def _quality_is_cosmetic(change: FieldChange) -> bool:
    return _field_after(change.shape, "quality[].") in _QUALITY_COSMETIC


def _bound_bump(change: FieldChange) -> Bump:
    option = _field_after(change.shape, "logicalTypeOptions.")
    if change.op == "removed":
        return Bump.MINOR  # constraint dropped → accepts more
    if change.op == "added":
        return Bump.MAJOR  # new constraint → may reject existing data
    try:
        old, new = float(change.old), float(change.new)
    except (TypeError, ValueError):
        return Bump.MAJOR  # pattern/format/etc. changed — can't judge direction
    if option in _LOWER_BOUNDS:
        return Bump.MAJOR if new > old else Bump.MINOR
    if option in _UPPER_BOUNDS:
        return Bump.MAJOR if new < old else Bump.MINOR
    return Bump.MAJOR


# ---------------------------------------------------------------------------
# Rules (first match wins; unmatched → PATCH)
# ---------------------------------------------------------------------------

ODCS_RULES = RuleSet(rules=[
    # Lifecycle / format bookkeeping
    Rule("status", "status", Bump.NONE, "Status changed (lifecycle, not content)"),
    Rule("api-version", "apiVersion", Bump.NONE, "ODCS format version changed"),

    # Schema objects
    Rule("schema-removed", "schema[]", Bump.MAJOR, "Schema object removed", ops=("removed",)),
    Rule("schema-added", "schema[]", Bump.MINOR, "Schema object added", ops=("added",)),
    Rule("schema-physical-name", "schema[].physicalName", Bump.MAJOR, "Schema object physical name changed"),

    # Properties (any nesting depth)
    Rule("property-removed", "*.properties[]", Bump.MAJOR, "Property removed", ops=("removed",)),
    Rule("property-added", "*.properties[]", _added_property_bump, "Property added", ops=("added",)),
    Rule("property-logical-type", "*.properties[].logicalType", _type_change_bump, "Property logical type changed"),
    Rule("property-physical-type", "*.properties[].physicalType", Bump.MAJOR, "Property physical type changed"),
    Rule("property-physical-name", "*.properties[].physicalName", Bump.MAJOR, "Property physical name changed"),
    Rule("property-required", "*.properties[].required", _became_true, "Property required flag changed"),
    Rule("property-unique", "*.properties[].unique", _became_true, "Property unique flag changed"),
    Rule("property-primary-key", "*.properties[].primaryKey", Bump.MAJOR, "Primary key changed"),
    Rule("property-primary-key-position", "*.properties[].primaryKeyPosition", Bump.MAJOR, "Primary key position changed"),
    Rule("property-type-options", "*.properties[].logicalTypeOptions.*", _bound_bump, "Property type constraint changed"),

    # Quality checks (contract-, schema- or property-level)
    Rule("quality-added", "*quality[]", Bump.MAJOR, "Quality check added", ops=("added",)),
    Rule("quality-removed", "*quality[]", Bump.PATCH, "Quality check removed", ops=("removed",)),
    Rule("quality-metadata", "*quality[].*", Bump.PATCH, "Quality check metadata changed", when=_quality_is_cosmetic),
    Rule("quality-changed", "*quality[].*", Bump.MAJOR, "Quality check definition changed"),

    # Servers
    Rule("server-removed", "servers[]", Bump.MAJOR, "Server removed", ops=("removed",)),
    Rule("server-added", "servers[]", Bump.MINOR, "Server added", ops=("added",)),
    Rule("server-description", "servers[].description", Bump.PATCH, "Server description changed"),
    Rule("server-changed", "servers[].*", Bump.MAJOR, "Server connection details changed"),

    # Access & service levels
    Rule("role-removed", "roles[]", Bump.MAJOR, "Role removed", ops=("removed",)),
    Rule("role-added", "roles[]", Bump.MINOR, "Role added", ops=("added",)),
    Rule("sla-changed", "slaProperties*", Bump.MINOR, "Service level changed"),
])
