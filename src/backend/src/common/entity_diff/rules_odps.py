"""ODPS (data product) diff profile and semver rules.

Consumers of a data product depend on its **output ports** (and the contracts
behind them); input ports, management ports, team and support describe how the
product is built and run. Rules follow that split.

Kept from the legacy ``ProductChangeAnalyzer``: output port removed / contract
swapped = MAJOR, output or management port added = MINOR, input port added
(optional) = MINOR, input port removed (optional) or its contract changed =
PATCH, support channel added = MINOR, removed = PATCH.

Deliberate divergences:
- Team changes are PATCH. The legacy analyzer made removing an owner-role
  member breaking; ownership is governance metadata, not part of what
  consumers read.
- An output port's ``version`` change maps to the size of that version jump
  (a port moving to a new major contract version is MAJOR), instead of always
  patch.
"""

from typing import Any, Dict, Optional

from .engine import DiffProfile, FieldChange
from .semver import Bump, Rule, RuleSet, version_bump_between

# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

_VOLATILE_CUSTOM_PROPERTIES = {"ontosEntityId"}
_VOLATILE_TOP_LEVEL = {"id", "version", "productCreatedTs"}


def _strip(shape: str, value: Any) -> bool:
    if shape in _VOLATILE_TOP_LEVEL:
        return True
    if shape.endswith("customProperties[]") and isinstance(value, dict):
        return value.get("property") in _VOLATILE_CUSTOM_PROPERTIES
    return False


def _ignore(shape: str) -> bool:
    # Nested ids (port ids, etc.) are row identifiers, not content.
    return shape.endswith(".id")


def _identity(item: Dict[str, Any], shape: str) -> Optional[str]:
    leaf = shape.rsplit(".", 1)[-1].removesuffix("[]")
    if leaf in ("inputPorts", "outputPorts", "managementPorts"):
        return item.get("name")
    if leaf == "members":
        return item.get("username") or item.get("name")
    if leaf == "support":
        return item.get("channel") or item.get("url")
    if leaf == "customProperties":
        return item.get("property")
    if leaf == "authoritativeDefinitions":
        return f"{item.get('type')}:{item.get('url')}" if item.get("url") else None
    if leaf == "datasets":
        return item.get("contractId") or item.get("name")
    if leaf == "tables":
        return item.get("location") or item.get("name")
    if leaf == "inputContracts":
        return item.get("id") or item.get("contractId")
    if leaf == "sbom":
        return item.get("url")
    return item.get("name")


ODPS_PROFILE = DiffProfile(identity=_identity, strip=_strip, ignore=_ignore)

# ---------------------------------------------------------------------------
# Rule helpers
# ---------------------------------------------------------------------------


def _required(change: FieldChange) -> bool:
    port = change.new if change.op == "added" else change.old
    return isinstance(port, dict) and port.get("required") is True


def _input_port_added(change: FieldChange) -> Bump:
    # Producers must now provide a required input.
    return Bump.MAJOR if _required(change) else Bump.MINOR


def _input_port_removed(change: FieldChange) -> Bump:
    return Bump.MAJOR if _required(change) else Bump.PATCH


def _port_version_bump(change: FieldChange) -> Bump:
    """Size of the output port's version jump; a downgrade or an unparseable
    version is treated as breaking."""
    if change.op != "modified":
        return Bump.MAJOR
    applied = version_bump_between(change.old, change.new)
    return applied if applied is not None else Bump.MAJOR


def _became_true(change: FieldChange) -> Bump:
    return Bump.MAJOR if change.new is True else Bump.PATCH


# ---------------------------------------------------------------------------
# Rules (first match wins; unmatched → PATCH)
# ---------------------------------------------------------------------------

ODPS_RULES = RuleSet(rules=[
    # Lifecycle / format bookkeeping
    Rule("status", "status", Bump.NONE, "Status changed (lifecycle, not content)"),
    Rule("api-version", "apiVersion", Bump.NONE, "ODPS format version changed"),

    # Output ports — what consumers read
    Rule("output-port-removed", "outputPorts[]", Bump.MAJOR, "Output port removed", ops=("removed",)),
    Rule("output-port-added", "outputPorts[]", Bump.MINOR, "Output port added", ops=("added",)),
    Rule("output-port-contract", "outputPorts[].contractId", Bump.MAJOR, "Output port contract changed"),
    Rule("output-port-version", "outputPorts[].version", _port_version_bump, "Output port version changed"),
    Rule("output-port-type", "outputPorts[].type", Bump.MAJOR, "Output port type changed"),
    Rule("output-port-server", "outputPorts[].server*", Bump.MAJOR, "Output port location changed"),
    Rule("output-port-pii", "outputPorts[].containsPii", _became_true, "Output port PII flag changed"),
    Rule("output-port-status", "outputPorts[].status", Bump.NONE, "Output port status changed"),

    # Input ports — how the product is built
    Rule("input-port-added", "inputPorts[]", _input_port_added, "Input port added", ops=("added",)),
    Rule("input-port-removed", "inputPorts[]", _input_port_removed, "Input port removed", ops=("removed",)),
    Rule("input-port-required", "inputPorts[].required", _became_true, "Input port required flag changed"),

    # Management ports & support
    Rule("management-port-added", "managementPorts[]", Bump.MINOR, "Management port added", ops=("added",)),
    Rule("support-added", "support[]", Bump.MINOR, "Support channel added", ops=("added",)),
])
