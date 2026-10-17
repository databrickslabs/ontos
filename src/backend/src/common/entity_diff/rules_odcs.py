"""ODCS (data contract) diff profile and semver rules.

Rules are written from the consumer's point of view: anything that can break
an existing reader or pipeline is MAJOR, backward-compatible additions are
MINOR, documentation/metadata is PATCH, lifecycle/format bookkeeping is NONE.

Deliberate divergences from the legacy ``ContractChangeAnalyzer``:
- Removing an *optional* property is MAJOR (it was a patch-level "fix"),
  because readers that select the column break regardless of nullability.
- Its "compatible" type pairs (double→float, long→int, timestamp→date) are
  dropped: they are lossy narrowings, and double/float/long/int aren't ODCS
  logical types anyway. Only the widening integer→number is MINOR.
"""

import hashlib
import json
import re
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

# Quality-check fields that don't change what the check enforces.
_QUALITY_COSMETIC = {
    "id", "description", "dimension", "businessImpact", "schedule", "scheduler",
    "severity", "tags", "authoritativeDefinitions", "customProperties", "name",
}


def _strip(shape: str, value: Any) -> bool:
    if shape in _VOLATILE_TOP_LEVEL:
        return True
    if shape.endswith("customProperties[]") and isinstance(value, dict):
        return value.get("property") in _VOLATILE_CUSTOM_PROPERTIES
    return False


def _ignore(shape: str) -> bool:
    # Nested `id`s are ODCS stable ids: used for matching (see _identity), but
    # identity metadata rather than content, so never reported as changes.
    return shape.endswith(".id")


def _quality_identity(item: Dict[str, Any]) -> str:
    """Stable id, else library rule, else name, else a hash of what the check
    enforces — so cosmetic edits (description, severity, adding a name to a
    library check) keep the same key and classify as metadata changes."""
    if item.get("id"):
        return str(item["id"])
    if item.get("rule"):
        return f"{item.get('type', 'library')}:{item['rule']}"
    if item.get("name"):
        return item["name"]
    definition = {k: v for k, v in item.items() if k not in _QUALITY_COSMETIC}
    digest = hashlib.sha1(json.dumps(definition, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:8]
    return f"{item.get('type', 'check')}#{digest}"


def _identity(item: Dict[str, Any], shape: str) -> Optional[str]:
    leaf = shape.rsplit(".", 1)[-1].removesuffix("[]")
    if leaf in ("schema", "properties"):
        return item.get("name")
    if leaf == "quality":
        return _quality_identity(item)
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


ODCS_PROFILE = DiffProfile(identity=_identity, strip=_strip, ignore=_ignore)

# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------

# Widenings every existing value still satisfies.
_WIDENING_TYPE_CHANGES = {("integer", "number")}

# logicalTypeOptions bounds: raising a lower bound / lowering an upper bound
# rejects previously-valid data (MAJOR); the reverse only widens (MINOR).
_LOWER_BOUNDS = {"minLength", "minimum", "exclusiveMinimum", "minItems", "minProperties"}
_UPPER_BOUNDS = {"maxLength", "maximum", "exclusiveMaximum", "maxItems", "maxProperties"}

# SLA properties by which direction is a stronger guarantee for consumers.
_SLA_HIGHER_IS_STRONGER = {"availability", "generalAvailability", "retention", "endOfSupport", "endOfLife"}
_SLA_LOWER_IS_STRONGER = {"latency", "frequency", "timeToDetect", "timeToNotify", "timeToRepair"}


def _type_change_bump(change: FieldChange) -> Bump:
    if change.op == "modified" and (str(change.old).lower(), str(change.new).lower()) in _WIDENING_TYPE_CHANGES:
        return Bump.MINOR
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
    # ODCS v3.0.2 exclusiveMinimum/exclusiveMaximum are booleans: turning
    # exclusivity on tightens the bound, turning it off relaxes it. (bool is
    # checked before the numeric path because float(True) == 1.0.)
    if isinstance(change.old, bool) or isinstance(change.new, bool):
        return Bump.MAJOR if change.new is True else Bump.MINOR
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


_SLA_KEY = re.compile(r"slaProperties\[([^\]:]+)")


def _sla_value_bump(change: FieldChange) -> Bump:
    """Weaker guarantee → MAJOR, stronger → MINOR; unknown direction → MAJOR."""
    match = _SLA_KEY.search(change.path)
    prop = match.group(1) if match else ""
    try:
        old, new = float(change.old), float(change.new)
    except (TypeError, ValueError):
        return Bump.MAJOR
    if prop in _SLA_HIGHER_IS_STRONGER:
        return Bump.MAJOR if new < old else Bump.MINOR
    if prop in _SLA_LOWER_IS_STRONGER:
        return Bump.MAJOR if new > old else Bump.MINOR
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

    # Properties (any nesting depth, including array `items`)
    Rule("property-removed", "*.properties[]", Bump.MAJOR, "Property removed", ops=("removed",)),
    Rule("property-added", "*.properties[]", _added_property_bump, "Property added", ops=("added",)),
    Rule("property-logical-type", "*.logicalType", _type_change_bump, "Logical type changed"),
    Rule("property-physical-type", "*.physicalType", Bump.MAJOR, "Physical type changed"),
    Rule("property-physical-name", "*.physicalName", Bump.MAJOR, "Physical name changed"),
    Rule("property-required", "*.required", _became_true, "Required flag changed"),
    Rule("property-unique", "*.unique", _became_true, "Unique flag changed"),
    Rule("property-primary-key", "*.primaryKey", Bump.MAJOR, "Primary key changed"),
    Rule("property-primary-key-position", "*.primaryKeyPosition", Bump.MAJOR, "Primary key position changed"),
    Rule("property-type-options", "*.logicalTypeOptions.*", _bound_bump, "Type constraint changed"),

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
    Rule("sla-removed", "slaProperties[]", Bump.MAJOR, "Service level removed", ops=("removed",)),
    Rule("sla-added", "slaProperties[]", Bump.MINOR, "Service level added", ops=("added",)),
    Rule("sla-value", "slaProperties[].value", _sla_value_bump, "Service level value changed", ops=("modified",)),
    Rule("sla-changed", "slaProperties[].*", Bump.MAJOR, "Service level definition changed"),
])
