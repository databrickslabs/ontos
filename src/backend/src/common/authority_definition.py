"""The canonical definition of an Authority Relation, and its hash (ARF 1.2.0, #859 review B6).

A DNA-Coefficient measures a definition, and an affirmation vouches for one. Each
carries the hash of the definition it was made on; activation requires the latest
measurement and every required affirmation to match the AR's current hash.

What the hash covers (anything that changes what the AR decides, or what the
DNA-Coefficient and the approval gate measure):

* the ARF tuple and scope: ``actor_role``, ``actor_identity``, ``actor_since``,
  ``action``, ``object_type``, ``object_id``, ``object_resolves_to``,
  ``domain_context``;
* the rule: ``justification_chain``, ``decision_logic``;
* the evidence: ``evidence_binding``, ``evidence_sources``;
* the measurement: ``dna_max_threshold`` (the ceiling), ``dna_scoring_config``,
  ``schedule_cron``;
* the identity the resolver calls with: ``resolver_auth``;
* the decision checks: name, rule, failure message, direction, weight, dimension,
  display order and enabled (provenance ``copied_from`` is excluded);
* the prerequisite edges (family slug, required, display order);
* the resource refs (field path, ref type, literal, entity, MCP service, tool,
  params and result pointer);
* the participants (principal, principal type, role, Business Role, role
  category, approver and reviewer flags, required).

Not covered (metadata; editable on any version): ``description``, owner team,
project, domain assignments, tags, notes, the review answers and affirmation
state. The AR's ``name`` is part of the immutability check but not of the hash,
so a rename of a draft neither resets its measurement nor its affirmations.

Values are canonicalised before hashing: ``""`` is ``None``; numbers are floats;
datetimes are UTC ISO strings; lists of rows are sorted by their canonical JSON,
so the order a client sends them in does not change the hash.
"""
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping

# The AR's own columns that change behaviour (see the module docstring).
DEFINITION_FIELDS = (
    "actor_role", "actor_identity", "actor_since", "action",
    "object_type", "object_id", "object_resolves_to", "domain_context",
    "justification_chain", "decision_logic", "evidence_binding", "evidence_sources",
    "dna_max_threshold", "dna_scoring_config", "schedule_cron", "resolver_auth",
)

CRITERION_KEYS = ("name", "rule", "failure_message", "direction", "weight", "dimension",
                  "display_order", "enabled")
PREREQUISITE_KEYS = ("prerequisite_family_slug", "required", "display_order")
RESOURCE_REF_KEYS = ("field_path", "ref_type", "literal_value", "entity_type", "entity_id",
                     "mcp_service_name", "mcp_tool_name", "mcp_params", "mcp_result_pointer")
PARTICIPANT_KEYS = ("principal", "principal_type", "role", "business_role_id", "role_category",
                    "is_approver", "is_reviewer", "required")


def canonical(value: Any) -> Any:
    """One value in the form it is hashed in."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value != "" else None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else str(number)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return str(value)


def _rows(items: Iterable[Mapping[str, Any]], keys: Iterable[str]) -> List[Dict[str, Any]]:
    """Canonical rows, each reduced to ``keys``, in a stable order."""
    out = [{k: canonical(row.get(k)) for k in keys} for row in items]
    return sorted(out, key=lambda row: json.dumps(row, sort_keys=True))


def definition_view(
    scalars: Mapping[str, Any],
    criteria: Iterable[Mapping[str, Any]] = (),
    prerequisites: Iterable[Mapping[str, Any]] = (),
    resource_refs: Iterable[Mapping[str, Any]] = (),
    participants: Iterable[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """The whole definition, canonical, including ``name`` (for the immutability check)."""
    return {
        "scalars": {k: canonical(scalars.get(k)) for k in ("name", *DEFINITION_FIELDS)},
        "criteria": _rows(criteria, CRITERION_KEYS),
        "prerequisites": _rows(prerequisites, PREREQUISITE_KEYS),
        "resource_refs": _rows(resource_refs, RESOURCE_REF_KEYS),
        "participants": _rows(participants, PARTICIPANT_KEYS),
    }


def definition_fingerprint(view: Mapping[str, Any]) -> str:
    """A string that differs whenever the definition differs, name included."""
    return json.dumps(view, sort_keys=True, separators=(",", ":"))


def definition_hash(view: Mapping[str, Any]) -> str:
    """SHA-256 of the behaviour part of the definition (the name is left out)."""
    scalars = {k: v for k, v in view["scalars"].items() if k != "name"}
    behaviour = {**view, "scalars": scalars}
    return hashlib.sha256(definition_fingerprint(behaviour).encode("utf-8")).hexdigest()
