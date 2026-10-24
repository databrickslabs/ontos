"""W3C ODRL 2.2 core for Access Policies: Ontos profile, normalization, validation, evaluation.

Pure module (no DB, no I/O) so it is unit-testable in isolation. The manager
resolves stored entities (Audiences, Asset Collections, inherited policies) and
hands plain dicts to these functions.

Spec references are to the ODRL Information Model 2.2 (W3C Rec 2018-02-15):

* §2.7 / §2.7.1 — compact policies (policy-level shared ``action``/``target``/
  ``assigner``/``assignee`` and multi-valued rule properties) are expanded to
  *atomic* rules before validation and evaluation (:func:`normalize_policy`).
* §2.9 — ``inheritFrom`` copies parent rules, profiles and conflict values into
  the child; must not be circular (:func:`resolve_inheritance`).
* §2.10 — the spec default conflict strategy is ``invalid``; Ontos-authored
  policies always set ``prohibit`` explicitly (see ``DEFAULT_AUTHORED_CONFLICT``).
* §2.4 — every action is ``includedIn`` ``use`` or ``transfer`` (transitively);
  a permission/prohibition of an encompassing action applies to included actions.
* §2.5.5 / §2.5.6 — a refined collection is referenced with ``source``, not ``uid``.
* §3.2 — a processor that does not recognise a declared profile MUST stop.

Canonical term keys: ODRL core/common terms are bare (``read``), Ontos profile
terms carry the ``ontos:`` prefix (``ontos:manage``).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

ODRL_NS = "http://www.w3.org/ns/odrl/2/"
ONTOS_NS = "http://ontos.app/ontology#"
ODRL_CONTEXT_URL = "http://www.w3.org/ns/odrl.jsonld"
ODRL_CORE_PROFILE = "http://www.w3.org/ns/odrl/2/core"
ONTOS_PROFILE = "http://ontos.app/odrl/profile/v1"
SUPPORTED_PROFILES = (ONTOS_PROFILE, ODRL_CORE_PROFILE)
JSONLD_CONTEXT: List[Any] = [ODRL_CONTEXT_URL, {"ontos": ONTOS_NS}]

# IRI scheme for Ontos-managed references inside policy bodies.
AUDIENCE_IRI_PREFIX = "urn:ontos:audience:"
ASSET_COLLECTION_IRI_PREFIX = "urn:ontos:asset-collection:"
POLICY_IRI_PREFIX = "urn:ontos:policy:"
# Unity Catalog securables: ``uc:<catalog>[.<schema>[.<object>]]``. A UC target
# covers its descendants (UC privilege inheritance), see :func:`_asset_ref_matches`.
UC_PREFIX = "uc:"

POLICY_TYPES = ("Set", "Offer", "Agreement")
RULE_KINDS = ("permission", "prohibition", "obligation")
CONFLICT_TERMS = ("perm", "prohibit", "invalid")
SPEC_DEFAULT_CONFLICT = "invalid"
DEFAULT_AUTHORED_CONFLICT = "prohibit"
LOGICAL_OPERANDS = ("and", "or", "xone", "andSequence")

ENFORCEMENT_PLATFORM = "platform"
ENFORCEMENT_WORKFLOW = "workflow"
ENFORCEMENT_ADVISORY = "advisory"


# --------------------------------------------------------------------- profile

@dataclass(frozen=True)
class ActionDef:
    key: str
    label: str
    included_in: Optional[str]
    description: str
    implies: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LeftOperandDef:
    key: str
    label: str
    # Where the constraint ends up being enforced once compiled for a target.
    enforcement: str
    # Which construct the operand describes: rule context, party, or asset.
    subject: str
    datatype: str
    description: str


ACTIONS: Dict[str, ActionDef] = {a.key: a for a in (
    ActionDef("use", "Use", None, "Any usage of the asset (ODRL top-level action)."),
    ActionDef("transfer", "Transfer", None, "Transfer of ownership (ODRL top-level action)."),
    ActionDef("read", "Read", "use", "Read/query the data (UC SELECT, READ VOLUME, EXECUTE)."),
    ActionDef("modify", "Modify", "use", "Change the data (UC MODIFY, WRITE VOLUME)."),
    ActionDef("ontos:browse", "Browse", "use", "See metadata without reading data (UC BROWSE)."),
    ActionDef("ontos:create", "Create", "use", "Create child objects (UC CREATE TABLE/VIEW/FUNCTION/VOLUME)."),
    ActionDef("ontos:manage", "Manage", "use", "Manage grants and properties (UC MANAGE)."),
    ActionDef("distribute", "Distribute", "use", "Share the data with third parties."),
    ActionDef("derive", "Derive", "use", "Create derived data from the asset."),
    ActionDef("aggregate", "Aggregate", "use", "Use the data only in aggregated form."),
    # Duty actions (used in duty/obligation/remedy rules).
    ActionDef("ontos:acknowledgeTerms", "Acknowledge terms", "use", "Accept the asset's terms of use (workflow)."),
    ActionDef("ontos:obtainApproval", "Obtain approval", "use", "Obtain an approval or authority decision (workflow)."),
    ActionDef("ontos:recertify", "Re-certify access", "use", "Periodically re-confirm the need for access (workflow)."),
    ActionDef("delete", "Delete", "use", "Permanently remove all copies of the asset."),
    ActionDef("anonymize", "Anonymize", "use", "Anonymize all or part of the asset."),
    ActionDef("inform", "Inform", "use", "Inform a party about the use (notification)."),
)}

LEFT_OPERANDS: Dict[str, LeftOperandDef] = {o.key: o for o in (
    LeftOperandDef("dateTime", "Date/time", ENFORCEMENT_PLATFORM, "context", "xsd:dateTime",
                   "Point in time of use; compiles to grant expiry/activation."),
    LeftOperandDef("elapsedTime", "Elapsed time", ENFORCEMENT_PLATFORM, "context", "xsd:duration",
                   "Duration of access; compiles to a time-bound grant."),
    LeftOperandDef("purpose", "Purpose", ENFORCEMENT_WORKFLOW, "context", "xsd:string",
                   "Declared purpose of use; attested via workflow, not technically enforced."),
    LeftOperandDef("recipient", "Recipient", ENFORCEMENT_WORKFLOW, "context", "xsd:string",
                   "Party receiving the result of the use."),
    LeftOperandDef("spatial", "Region", ENFORCEMENT_PLATFORM, "context", "xsd:string",
                   "Geographic region of use; compiles to a row filter where supported."),
    LeftOperandDef("ontos:classification", "Classification", ENFORCEMENT_PLATFORM, "asset", "xsd:string",
                   "Asset data classification; compiles to tag-based ABAC where supported."),
    LeftOperandDef("ontos:tag", "Tag", ENFORCEMENT_PLATFORM, "asset", "xsd:string",
                   "Asset tag (namespace/key[=value]); compiles to tag-based ABAC where supported."),
    LeftOperandDef("ontos:domain", "Domain", ENFORCEMENT_PLATFORM, "asset", "xsd:string",
                   "Ontos domain of the asset; materialized into concrete grants."),
    LeftOperandDef("ontos:dataProduct", "Data product", ENFORCEMENT_PLATFORM, "asset", "xsd:string",
                   "Data product the asset belongs to; materialized into concrete grants."),
    LeftOperandDef("ontos:columnTag", "Column tag", ENFORCEMENT_PLATFORM, "asset", "xsd:string",
                   "Column-level tag; compiles to a column mask where supported."),
    LeftOperandDef("ontos:rowCondition", "Row condition", ENFORCEMENT_PLATFORM, "context", "xsd:string",
                   "Row-level predicate; compiles to a row filter where supported."),
    LeftOperandDef("ontos:businessRole", "Business role", ENFORCEMENT_PLATFORM, "party", "xsd:string",
                   "Ontos Business Role of the principal (Audience refinement)."),
    LeftOperandDef("ontos:group", "Group", ENFORCEMENT_PLATFORM, "party", "xsd:string",
                   "Identity-provider group membership of the principal."),
    LeftOperandDef("ontos:principalAttribute", "Principal attribute", ENFORCEMENT_PLATFORM, "party", "xsd:string",
                   "Directory attribute of the principal (stub: future IdP/Lakebase sources)."),
    LeftOperandDef("ontos:remark", "Remark", ENFORCEMENT_ADVISORY, "context", "xsd:string",
                   "Free-text condition shown to consumers; not enforced."),
)}

OPERATORS: Dict[str, str] = {
    "eq": "equal to", "neq": "not equal to",
    "gt": "greater than", "gteq": "greater than or equal to",
    "lt": "less than", "lteq": "less than or equal to",
    "isA": "is a", "hasPart": "has part", "isPartOf": "is part of",
    "isAllOf": "is all of", "isAnyOf": "is any of", "isNoneOf": "is none of",
}


def profile_vocabulary() -> Dict[str, Any]:
    """The Ontos ODRL profile as a JSON-friendly dict (for the UI and MCP)."""
    return {
        "profile": ONTOS_PROFILE,
        "policy_types": list(POLICY_TYPES),
        "conflict_terms": list(CONFLICT_TERMS),
        "default_conflict": DEFAULT_AUTHORED_CONFLICT,
        "actions": [
            {"key": a.key, "label": a.label, "included_in": a.included_in,
             "implies": list(a.implies), "description": a.description}
            for a in ACTIONS.values()
        ],
        "left_operands": [
            {"key": o.key, "label": o.label, "enforcement": o.enforcement,
             "subject": o.subject, "datatype": o.datatype, "description": o.description}
            for o in LEFT_OPERANDS.values()
        ],
        "operators": [{"key": k, "label": v} for k, v in OPERATORS.items()],
        "logical_operands": list(LOGICAL_OPERANDS),
    }


def term_key(term: Any) -> Optional[str]:
    """Canonical key for an ODRL/Ontos term given as ``read``, ``odrl:read``, an IRI or ``{"@id": ...}``."""
    if isinstance(term, dict):
        term = term.get("@id") or term.get("rdf:value") or term.get("id")
        if isinstance(term, dict):
            term = term.get("@id")
    if not isinstance(term, str) or not term:
        return None
    t = term.strip()
    if t.startswith(ODRL_NS):
        return t[len(ODRL_NS):]
    if t.startswith(ONTOS_NS):
        return "ontos:" + t[len(ONTOS_NS):]
    if t.startswith("odrl:"):
        return t[len("odrl:"):]
    return t


def action_ancestors(action: str) -> List[str]:
    """``action`` followed by every action it is transitively ``includedIn``."""
    out: List[str] = []
    cur: Optional[str] = action
    while cur and cur not in out:
        out.append(cur)
        cur = ACTIONS[cur].included_in if cur in ACTIONS else None
    return out


def action_covers(rule_action: str, requested: str) -> bool:
    """True if a rule on ``rule_action`` applies to ``requested`` (§2.4 includedIn inheritance)."""
    return rule_action in action_ancestors(requested)


# --------------------------------------------------------------- normalization

def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, dict) and "@list" in value:
        return list(value["@list"] or [])
    if isinstance(value, list):
        return list(value)
    return [value]


def _normalize_right_operand(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_right_operand(v) for v in value]
    if isinstance(value, dict):
        if "@list" in value:
            return [_normalize_right_operand(v) for v in value["@list"]]
        if "@id" in value:
            return value["@id"]
        if "@value" in value:
            raw, typ = value["@value"], str(value.get("@type") or "")
            return _cast_literal(raw, typ)
    return value


def _cast_literal(raw: Any, typ: str) -> Any:
    typ = typ.replace("http://www.w3.org/2001/XMLSchema#", "xsd:")
    try:
        if typ in ("xsd:integer", "xsd:int", "xsd:long"):
            return int(raw)
        if typ in ("xsd:decimal", "xsd:double", "xsd:float"):
            return float(raw)
        if typ == "xsd:boolean":
            return str(raw).lower() in ("true", "1")
    except (TypeError, ValueError):
        return raw
    return raw


def normalize_constraint(c: Any) -> Dict[str, Any]:
    """Normalize a Constraint or LogicalConstraint to a plain dict."""
    if not isinstance(c, dict):
        return {"invalid": True, "raw": c}
    # Already-normalized logical form (re-normalizing a stored body must be a no-op).
    if c.get("logical") in LOGICAL_OPERANDS:
        return {"logical": c["logical"], "constraints": [normalize_constraint(x) for x in _as_list(c.get("constraints"))],
                **({"uid": c["uid"]} if c.get("uid") else {})}
    for op in LOGICAL_OPERANDS:
        if op in c:
            return {"logical": op, "constraints": [normalize_constraint(x) for x in _as_list(c[op])],
                    **({"uid": c["uid"]} if c.get("uid") else {})}
    out: Dict[str, Any] = {
        "leftOperand": term_key(c.get("leftOperand")),
        "operator": term_key(c.get("operator")),
    }
    if "rightOperand" in c:
        out["rightOperand"] = _normalize_right_operand(c["rightOperand"])
    if "rightOperandReference" in c:
        out["rightOperandReference"] = c["rightOperandReference"]
    for k in ("dataType", "unit", "status", "uid"):
        if c.get(k) is not None:
            out[k] = c[k]
    return out


def _normalize_collection(ref: Any, kind: str) -> Any:
    """Asset/Party reference: an IRI string or an inline (refined) collection dict."""
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        if set(ref.keys()) <= {"@id"}:
            return ref.get("@id")
        types = [term_key(t) for t in _as_list(ref.get("@type"))]
        out: Dict[str, Any] = {"@type": f"{kind}Collection" if f"{kind}Collection" in types else kind}
        for k in ("uid", "source", "@id"):
            if ref.get(k):
                out["uid" if k == "@id" else k] = ref[k]
        if ref.get("refinement") is not None:
            out["refinement"] = [normalize_constraint(x) for x in _as_list(ref["refinement"])]
        if ref.get("members") is not None:
            out["members"] = _as_list(ref["members"])
        return out
    return ref


def _normalize_action(action: Any) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    if isinstance(action, dict) and ("rdf:value" in action or "refinement" in action):
        return term_key(action.get("rdf:value")), [normalize_constraint(x) for x in _as_list(action.get("refinement"))]
    return term_key(action), []


_SHARED_RULE_PROPS = ("action", "target", "assigner", "assignee")


def _atomize_rule(rule: Dict[str, Any], shared: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    merged = dict(rule)
    for prop in _SHARED_RULE_PROPS:
        if prop not in merged and prop in shared:
            merged[prop] = shared[prop]
    actions = _as_list(merged.get("action")) or [None]
    targets = _as_list(merged.get("target")) or [None]
    assignees = _as_list(merged.get("assignee")) or [None]
    assigners = _as_list(merged.get("assigner")) or [None]
    atoms: List[Dict[str, Any]] = []
    for action, target, assignee, assigner in itertools.product(actions, targets, assignees, assigners):
        act, refinement = _normalize_action(action)
        # Already-atomic rules keep their refinement in ``action_refinement``.
        refinement = refinement or [normalize_constraint(x) for x in _as_list(merged.get("action_refinement"))]
        atom: Dict[str, Any] = {
            "action": act,
            "target": _normalize_collection(target, "Asset") if target is not None else None,
            "assignee": _normalize_collection(assignee, "Party") if assignee is not None else None,
            "assigner": _normalize_collection(assigner, "Party") if assigner is not None else None,
            "constraint": [normalize_constraint(x) for x in _as_list(merged.get("constraint"))],
        }
        if refinement:
            atom["action_refinement"] = refinement
        if merged.get("uid"):
            atom["uid"] = merged["uid"]
        # Duties inherit the referring rule's functional roles when they declare none (§2.6.5).
        inherited = {k: atom[k] for k in ("assigner", "assignee") if atom.get(k) is not None}
        for sub in ("duty", "remedy", "consequence"):
            if merged.get(sub):
                subs: List[Dict[str, Any]] = []
                for d in _as_list(merged[sub]):
                    if isinstance(d, dict):
                        subs.extend(_atomize_rule(d, inherited, "duty"))
                atom[sub] = subs
        atoms.append(atom)
    return atoms


def normalize_policy(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Expand a (possibly compact) ODRL policy into its atomic form (§2.7)."""
    doc = doc or {}
    ptype = term_key(doc.get("@type") or doc.get("type")) or "Set"
    if ptype == "Policy":
        ptype = "Set"
    shared = {k: doc[k] for k in _SHARED_RULE_PROPS if k in doc}
    out: Dict[str, Any] = {
        "uid": doc.get("uid") or doc.get("@id"),
        "type": ptype,
        "profile": [p for p in _as_list(doc.get("profile")) if p],
        "conflict": term_key(doc.get("conflict")),
        "inheritFrom": [p for p in _as_list(doc.get("inheritFrom")) if p],
    }
    for kind in RULE_KINDS:
        rules: List[Dict[str, Any]] = []
        for r in _as_list(doc.get(kind)):
            if isinstance(r, dict):
                rules.extend(_atomize_rule(r, shared, kind))
        out[kind] = rules
    return out


def _own_assignees(child: Dict[str, Any]) -> List[Any]:
    out: List[Any] = []
    for r in child.get("permission") or []:
        if r.get("assignee") is not None and r["assignee"] not in out:
            out.append(r["assignee"])
    return out


def _inherited_rules(parent: Dict[str, Any], child: Dict[str, Any], kind: str,
                     assignees: List[Any]) -> List[Dict[str, Any]]:
    """Rules a child takes over from ``parent``.

    An Offer proposes terms: a non-Offer child (Set / Agreement) inherits its prohibitions and
    obligations — bound to the child's *own* assignees (``assignees``, taken from the child before
    any merge, so the result doesn't depend on parent order) when the term names none — but never
    its permissions, which would otherwise entitle everyone. The child states what it grants; the
    Offer's permission duties are attached to it by :func:`_attach_offer_duties`.
    """
    rules = [dict(r) for r in parent.get(kind) or []]
    child_type = term_key(child.get("type") or child.get("@type")) or "Set"
    if term_key(parent.get("type") or parent.get("@type")) != "Offer" or child_type == "Offer":
        return rules
    if kind == "permission":
        return []
    out: List[Dict[str, Any]] = []
    for r in rules:
        if r.get("assignee") is not None or not assignees:
            out.append(r)  # Unbound term with nobody to bind it to: applies to everyone (fail-safe).
        else:
            out.extend({**r, "assignee": a} for a in assignees)
    return out


def _attach_offer_duties(offer: Dict[str, Any], merged: Dict[str, Any]) -> None:
    """An Offer's permission duties (attribution, acknowledging terms…) are the conditions of use:
    they bind every permission of the child that the offered permission covers (target + action)."""
    for op in offer.get("permission") or []:
        duties = [dict(d) for d in op.get("duty") or []]
        target, action = op.get("target"), op.get("action")
        if not duties or not action:
            continue
        for cp in merged.get("permission") or []:
            ct = cp.get("target")
            covers = target is None or (isinstance(target, str) and isinstance(ct, str) and _asset_ref_matches(target, ct))
            if covers and cp.get("action") and action_covers(action, cp["action"]):
                existing = cp.setdefault("duty", [])
                for d in duties:
                    if all(d.get("action") != e.get("action") for e in existing):
                        existing.append(d)


def resolve_inheritance(
    doc: Dict[str, Any], lookup: Callable[[str], Optional[Dict[str, Any]]]
) -> Tuple[Dict[str, Any], List[str]]:
    """Merge parent policies into a normalized child (§2.9). Returns (merged, errors)."""
    errors: List[str] = []
    merged = {k: ([dict(x) if isinstance(x, dict) else x for x in v] if isinstance(v, list) else v)
              for k, v in doc.items()}
    conflicts = [doc["conflict"]] if doc.get("conflict") else []
    own_assignees = _own_assignees(doc)

    def walk(policy: Dict[str, Any], seen: Tuple[str, ...]) -> None:
        for parent_uid in policy.get("inheritFrom") or []:
            if parent_uid in seen:
                errors.append(f"Circular inheritance via {parent_uid}")
                continue
            parent = lookup(parent_uid)
            if parent is None:
                errors.append(f"Parent policy {parent_uid} not found")
                continue
            parent = normalize_policy(parent) if "permission" not in parent or "type" not in parent else parent
            for kind in RULE_KINDS:
                merged[kind] = list(merged.get(kind) or []) + _inherited_rules(parent, merged, kind, own_assignees)
            if (term_key(parent.get("type") or parent.get("@type")) == "Offer"
                    and term_key(merged.get("type") or merged.get("@type")) != "Offer"):
                _attach_offer_duties(parent, merged)
            for p in parent.get("profile") or []:
                if p not in merged["profile"]:
                    merged["profile"].append(p)
            if parent.get("conflict"):
                conflicts.append(parent["conflict"])
            walk(parent, seen + (parent_uid,))

    walk(doc, (doc.get("uid") or "",))
    distinct = sorted(set(conflicts))
    # Multiple differing conflict values after a merge void the policy on conflict (§2.10 rule 4).
    merged["conflict"] = distinct[0] if len(distinct) == 1 else ("invalid" if distinct else None)
    return merged, errors


# ------------------------------------------------------------------ validation

@dataclass
class Issue:
    severity: str  # "error" | "warning"
    path: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return {"severity": self.severity, "path": self.path, "message": self.message}


def _validate_constraint(c: Dict[str, Any], path: str, issues: List[Issue], subject: Optional[str] = None) -> None:
    if c.get("invalid"):
        issues.append(Issue("error", path, "Constraint must be an object"))
        return
    if c.get("logical"):
        members = c.get("constraints") or []
        if len(members) < 1:
            issues.append(Issue("error", path, f"Logical constraint '{c['logical']}' needs at least one operand"))
        for i, m in enumerate(members):
            _validate_constraint(m, f"{path}.{c['logical']}[{i}]", issues, subject)
        return
    lo, op = c.get("leftOperand"), c.get("operator")
    if not lo:
        issues.append(Issue("error", path, "Constraint is missing leftOperand"))
    elif lo not in LEFT_OPERANDS:
        issues.append(Issue("error", path, f"Unknown leftOperand '{lo}' (not in the Ontos profile)"))
    elif subject and LEFT_OPERANDS[lo].subject not in (subject, "context"):
        issues.append(Issue("warning", path, f"leftOperand '{lo}' describes a {LEFT_OPERANDS[lo].subject}, not a {subject}"))
    if not op:
        issues.append(Issue("error", path, "Constraint is missing operator"))
    elif op not in OPERATORS:
        issues.append(Issue("error", path, f"Unknown operator '{op}'"))
    has_ro, has_ref = "rightOperand" in c, "rightOperandReference" in c
    if has_ro == has_ref:
        issues.append(Issue("error", path, "Constraint needs exactly one of rightOperand / rightOperandReference"))


def _validate_ref(ref: Any, path: str, kind: str, issues: List[Issue],
                  known: Optional[Callable[[str], bool]]) -> None:
    if ref is None:
        return
    if isinstance(ref, str):
        if known is not None and not known(ref):
            issues.append(Issue("error", path, f"Unknown {kind} reference '{ref}'"))
        return
    if isinstance(ref, dict):
        refined = bool(ref.get("refinement"))
        if refined and ref.get("uid"):
            issues.append(Issue("error", path, f"A refined {kind} collection must use 'source', not 'uid' (ODRL §2.5.5/§2.5.6)"))
        if ref.get("source") and known is not None and not known(ref["source"]):
            issues.append(Issue("error", path, f"Unknown {kind} collection source '{ref['source']}'"))
        for i, c in enumerate(ref.get("refinement") or []):
            _validate_constraint(c, f"{path}.refinement[{i}]", issues, "party" if kind == "party" else "asset")


def validate_policy(
    doc: Dict[str, Any],
    *,
    known_party: Optional[Callable[[str], bool]] = None,
    known_asset: Optional[Callable[[str], bool]] = None,
) -> List[Issue]:
    """Validate a policy document (compact or atomic) against ODRL 2.2 + the Ontos profile."""
    issues: List[Issue] = []
    norm = normalize_policy(doc) if "type" not in doc or "permission" not in doc else doc
    if norm["type"] not in POLICY_TYPES:
        issues.append(Issue("error", "@type", f"Unsupported policy type '{norm['type']}'"))
    for p in norm.get("profile") or []:
        if p not in SUPPORTED_PROFILES:
            issues.append(Issue("error", "profile", f"Unrecognised ODRL profile '{p}' — policy cannot be processed (ODRL §3.2)"))
    if norm.get("conflict") and norm["conflict"] not in CONFLICT_TERMS:
        issues.append(Issue("error", "conflict", f"Unknown conflict strategy '{norm['conflict']}'"))
    if not any(norm.get(k) for k in RULE_KINDS):
        issues.append(Issue("error", "", "A policy needs at least one permission, prohibition or obligation"))

    def check_rule(r: Dict[str, Any], path: str, kind: str) -> None:
        act = r.get("action")
        if not act:
            issues.append(Issue("error", f"{path}.action", "Rule is missing an action"))
        elif act not in ACTIONS:
            issues.append(Issue("error", f"{path}.action", f"Unknown action '{act}' (not in the Ontos profile)"))
        if kind in ("permission", "prohibition") and r.get("target") is None:
            issues.append(Issue("error", f"{path}.target", f"A {kind} needs a target asset"))
        if norm["type"] in ("Offer", "Agreement") and kind != "duty" and r.get("assigner") is None:
            issues.append(Issue("error", f"{path}.assigner", f"An {norm['type']} needs an assigner on every rule"))
        if norm["type"] == "Agreement" and kind != "duty" and r.get("assignee") is None:
            issues.append(Issue("error", f"{path}.assignee", "An Agreement needs an assignee on every rule"))
        _validate_ref(r.get("target"), f"{path}.target", "asset", issues, known_asset)
        _validate_ref(r.get("assignee"), f"{path}.assignee", "party", issues, known_party)
        _validate_ref(r.get("assigner"), f"{path}.assigner", "party", issues, None)
        for i, c in enumerate(r.get("constraint") or []):
            _validate_constraint(c, f"{path}.constraint[{i}]", issues)
        for i, c in enumerate(r.get("action_refinement") or []):
            _validate_constraint(c, f"{path}.action.refinement[{i}]", issues)
        for sub in ("duty", "remedy", "consequence"):
            if sub == "duty" and kind not in ("permission",) and r.get(sub):
                issues.append(Issue("error", f"{path}.{sub}", "Only permissions may carry duties (use 'remedy' on prohibitions)"))
            if sub == "remedy" and kind != "prohibition" and r.get(sub):
                issues.append(Issue("error", f"{path}.{sub}", "Only prohibitions may carry remedies"))
            for i, d in enumerate(r.get(sub) or []):
                check_rule(d, f"{path}.{sub}[{i}]", "duty")

    for kind in RULE_KINDS:
        for i, r in enumerate(norm.get(kind) or []):
            check_rule(r, f"{kind}[{i}]", kind)
    return issues


# ------------------------------------------------------------------ evaluation

@dataclass
class AccessRequest:
    """What is being asked: can ``principal`` perform ``action`` on ``asset``?"""
    principal: str
    action: str
    asset: str
    principal_groups: List[str] = field(default_factory=list)
    # Party attributes keyed by leftOperand (e.g. {"ontos:businessRole": ["Analyst"]}).
    principal_attributes: Dict[str, Any] = field(default_factory=dict)
    # Asset attributes keyed by leftOperand (e.g. {"ontos:domain": ["Sales"], "ontos:tag": [...]}).
    asset_attributes: Dict[str, Any] = field(default_factory=dict)
    # Rule context keyed by leftOperand (e.g. {"purpose": "analytics", "dateTime": "..."}).
    context: Dict[str, Any] = field(default_factory=dict)
    # Duty actions the caller asserts are fulfilled (e.g. ["ontos:acknowledgeTerms"]).
    fulfilled_duties: List[str] = field(default_factory=list)


@dataclass
class CollectionDef:
    """A resolved Audience (party) or Asset Collection: static members + refinement."""
    uid: str
    name: str
    members: List[str] = field(default_factory=list)
    refinement: List[Dict[str, Any]] = field(default_factory=list)


# Pending duty reported for a permission that is only offered (odrl:Offer): obtain an Agreement.
OFFER_DUTY = "ontos:obtainApproval"

VERDICT_ALLOW = "allow"
VERDICT_DENY = "deny"
VERDICT_CONDITIONAL = "conditional"
VERDICT_NOT_APPLICABLE = "not_applicable"


def _to_comparable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v if isinstance(v, datetime) else datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
            try:
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            except ValueError:
                return s
        return s
    return v


def _norm_str(v: Any) -> Any:
    return v.strip().lower() if isinstance(v, str) else v


def compare(left: Any, operator: str, right: Any) -> bool:
    """Evaluate ``left operator right``. ``left`` may be multi-valued (list = set of values)."""
    lefts = [_to_comparable(x) for x in _as_list(left)]
    rights = [_to_comparable(x) for x in _as_list(right)]
    ls = {_norm_str(x) for x in lefts if not isinstance(x, (list, dict))}
    rs = {_norm_str(x) for x in rights if not isinstance(x, (list, dict))}
    if operator in ("eq", "isA"):
        return bool(ls & rs) if len(rs) == 1 else ls == rs
    if operator == "neq":
        return not (ls & rs)
    if operator == "isAnyOf":
        return bool(ls & rs)
    if operator == "isAllOf":
        return rs <= ls
    if operator == "isNoneOf":
        return not (ls & rs)
    if operator in ("hasPart",):
        return rs <= ls
    if operator in ("isPartOf",):
        return bool(ls) and ls <= rs
    if operator in ("gt", "gteq", "lt", "lteq"):
        if not lefts or len(rights) != 1:
            return False
        r = rights[0]
        try:
            for lv in lefts:
                if operator == "gt" and not lv > r:
                    return False
                if operator == "gteq" and not lv >= r:
                    return False
                if operator == "lt" and not lv < r:
                    return False
                if operator == "lteq" and not lv <= r:
                    return False
            return True
        except TypeError:
            return False
    return False


@dataclass
class ConstraintResult:
    satisfied: bool
    unknown: List[str] = field(default_factory=list)
    detail: List[str] = field(default_factory=list)


def evaluate_constraints(constraints: Sequence[Dict[str, Any]], env: Dict[str, Any]) -> ConstraintResult:
    """All constraints must be satisfied (conjunction, §2.5). Missing operand values → not satisfied."""
    res = ConstraintResult(True)
    for c in constraints or []:
        ok = _eval_one(c, env, res)
        if not ok:
            res.satisfied = False
    return res


def _eval_one(c: Dict[str, Any], env: Dict[str, Any], res: ConstraintResult) -> bool:
    if c.get("logical"):
        outcomes = [_eval_one(m, env, res) for m in c.get("constraints") or []]
        op = c["logical"]
        if op in ("and", "andSequence"):
            return all(outcomes)
        if op == "or":
            return any(outcomes)
        if op == "xone":
            return sum(1 for o in outcomes if o) == 1
        return False
    lo, op = c.get("leftOperand"), c.get("operator")
    right = c.get("rightOperand", c.get("rightOperandReference"))
    if lo not in env or env.get(lo) in (None, [], ""):
        res.unknown.append(lo or "?")
        res.detail.append(f"{lo} {op} {right!r}: no value supplied")
        return False
    ok = compare(env[lo], op or "", right)
    res.detail.append(f"{lo} {op} {right!r}: {'satisfied' if ok else 'not satisfied'} (value {env[lo]!r})")
    return ok


def _uc_covers(target: str, asset: str) -> bool:
    if not (target.startswith(UC_PREFIX) and asset.startswith(UC_PREFIX)):
        return False
    t = target[len(UC_PREFIX):].lower().split(".")
    a = asset[len(UC_PREFIX):].lower().split(".")
    return len(t) <= len(a) and a[: len(t)] == t


def _asset_ref_matches(ref: str, asset: str) -> bool:
    if ref == asset:
        return True
    if ref.endswith(".*") and ref.startswith(UC_PREFIX):
        return _uc_covers(ref[:-2], asset)
    return _uc_covers(ref, asset)


def strip_principal_prefix(value: str) -> str:
    """``user:a@x`` / ``mailto:a@x`` / ``sp:id`` / ``group:g`` → bare lower-case identifier."""
    low = (value or "").strip().lower()
    for prefix in ("user:", "mailto:", "sp:", "group:"):
        if low.startswith(prefix):
            return low[len(prefix):]
    return low


class Resolver:
    """Resolves named Audiences / Asset Collections for evaluation.

    Fail-safe semantics:
    * A collection with neither members nor refinement is the empty set.
    * A named reference that can't be resolved (unknown, or no active version)
      never widens access: it matches nothing for permissions but still
      matches for prohibitions (``fail_closed``), and is reported in ``unresolved``.
    """

    def __init__(
        self,
        audiences: Optional[Dict[str, CollectionDef]] = None,
        asset_collections: Optional[Dict[str, CollectionDef]] = None,
    ):
        self.audiences = audiences or {}
        self.asset_collections = asset_collections or {}
        self.unresolved: List[str] = []

    def _unresolved(self, ref: str, trail: List[str], fail_closed: bool) -> bool:
        if ref not in self.unresolved:
            self.unresolved.append(ref)
        trail.append(f"{ref} has no active definition — treated as {'matching (prohibition)' if fail_closed else 'not matching'}")
        return fail_closed

    # -- parties
    def party_matches(self, ref: Any, req: AccessRequest, trail: List[str], depth: int = 0,
                      fail_closed: bool = False) -> bool:
        if ref is None:
            return True  # No assignee: the rule applies to every party.
        if depth > 8:
            return False
        if isinstance(ref, dict):
            source = ref.get("source") or ref.get("uid")
            if not source and not ref.get("members") and not ref.get("refinement"):
                return False  # Empty collection.
            members_ok = True
            if source:
                members_ok = self.party_matches(source, req, trail, depth + 1, fail_closed)
            elif ref.get("members"):
                members_ok = any(self._principal_is(m, req) for m in ref["members"])
            if not members_ok:
                return False
            if ref.get("refinement"):
                r = evaluate_constraints(ref["refinement"], self._party_env(req))
                trail.extend(f"party refinement: {d}" for d in r.detail)
                return r.satisfied
            return True
        if ref in self.audiences:
            aud = self.audiences[ref]
            if not aud.members and not aud.refinement:
                trail.append(f"audience '{aud.name}' is empty")
                return False
            if aud.members and not any(self._principal_is(m, req) for m in aud.members):
                trail.append(f"not a member of audience '{aud.name}'")
                return False
            if aud.refinement:
                r = evaluate_constraints(aud.refinement, self._party_env(req))
                trail.extend(f"audience '{aud.name}' refinement: {d}" for d in r.detail)
                if not r.satisfied:
                    return False
            trail.append(f"member of audience '{aud.name}'")
            return True
        if isinstance(ref, str) and ref.startswith(AUDIENCE_IRI_PREFIX):
            return self._unresolved(ref, trail, fail_closed)
        return self._principal_is(ref, req)

    @staticmethod
    def _principal_is(ref: str, req: AccessRequest) -> bool:
        low = (ref or "").strip().lower()
        principal = strip_principal_prefix(req.principal)
        groups = {strip_principal_prefix(g) for g in req.principal_groups}
        for prefix in ("user:", "mailto:", "sp:"):
            if low.startswith(prefix):
                return low[len(prefix):] == principal
        if low.startswith("group:"):
            return low[len("group:"):] in groups
        return low == principal or low in groups

    @staticmethod
    def _party_env(req: AccessRequest) -> Dict[str, Any]:
        env = dict(req.principal_attributes)
        env.setdefault("ontos:group", list(req.principal_groups))
        return env

    # -- assets
    def asset_matches(self, ref: Any, req: AccessRequest, trail: List[str], depth: int = 0,
                      fail_closed: bool = False) -> bool:
        if ref is None:
            return False
        if depth > 8:
            return False
        if isinstance(ref, dict):
            source = ref.get("source") or ref.get("uid")
            if not source and not ref.get("members") and not ref.get("refinement"):
                return False  # Empty collection.
            members_ok = True
            if source:
                members_ok = self.asset_matches(source, req, trail, depth + 1, fail_closed)
            elif ref.get("members"):
                members_ok = any(_asset_ref_matches(m, req.asset) for m in ref["members"])
            if not members_ok:
                return False
            if ref.get("refinement"):
                r = evaluate_constraints(ref["refinement"], req.asset_attributes)
                trail.extend(f"asset refinement: {d}" for d in r.detail)
                return r.satisfied
            return True
        if ref in self.asset_collections:
            col = self.asset_collections[ref]
            if not col.members and not col.refinement:
                return False
            if col.members and not any(_asset_ref_matches(m, req.asset) for m in col.members):
                return False
            if col.refinement:
                r = evaluate_constraints(col.refinement, req.asset_attributes)
                trail.extend(f"collection '{col.name}' refinement: {d}" for d in r.detail)
                if not r.satisfied:
                    return False
            trail.append(f"in asset collection '{col.name}'")
            return True
        if isinstance(ref, str) and ref.startswith(ASSET_COLLECTION_IRI_PREFIX):
            return self._unresolved(ref, trail, fail_closed)
        return _asset_ref_matches(ref, req.asset)


@dataclass
class RuleMatch:
    policy_uid: str
    policy_name: str
    kind: str
    index: int
    action: str
    target: Any
    assignee: Any
    effect: str  # "permit" | "prohibit" | "pending_duties" | "constraint_unmet"
    reasons: List[str] = field(default_factory=list)
    pending_duties: List[str] = field(default_factory=list)
    unenforceable: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_uid": self.policy_uid, "policy_name": self.policy_name, "kind": self.kind,
            "index": self.index, "action": self.action, "target": self.target, "assignee": self.assignee,
            "effect": self.effect, "reasons": self.reasons, "pending_duties": self.pending_duties,
            "unenforceable": self.unenforceable,
        }


@dataclass
class Decision:
    verdict: str
    allowed: bool
    explanation: List[str]
    matches: List[RuleMatch]
    void_policies: List[str]
    pending_duties: List[str]
    unresolved_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict, "allowed": self.allowed, "explanation": self.explanation,
            "matches": [m.to_dict() for m in self.matches], "void_policies": self.void_policies,
            "pending_duties": self.pending_duties, "unresolved_refs": self.unresolved_refs,
        }


def _non_platform_operands(constraints: Iterable[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for c in constraints or []:
        if c.get("logical"):
            out.extend(_non_platform_operands(c.get("constraints") or []))
            continue
        lo = c.get("leftOperand")
        if lo in LEFT_OPERANDS and LEFT_OPERANDS[lo].enforcement != ENFORCEMENT_PLATFORM:
            out.append(f"{lo} ({LEFT_OPERANDS[lo].enforcement})")
    return out


def evaluate(
    policies: Sequence[Dict[str, Any]],
    request: AccessRequest,
    resolver: Optional[Resolver] = None,
    *,
    now: Optional[datetime] = None,
) -> Decision:
    """Decide whether ``request`` is allowed by the given (normalized, inheritance-resolved) policies.

    Per policy: applicable prohibitions vs permissions are resolved with that
    policy's conflict strategy (``perm`` / ``prohibit`` / ``invalid`` → void).
    Across policies: any deny wins, then any allow, then conditional (allowed
    once pending duties are fulfilled), else not applicable (default deny).
    """
    resolver = resolver or Resolver()
    now = now or datetime.now(timezone.utc)
    env = dict(request.context)
    env.setdefault("dateTime", now.isoformat())
    env.update({k: v for k, v in request.asset_attributes.items() if k not in env})
    explanation: List[str] = []
    all_matches: List[RuleMatch] = []
    void: List[str] = []
    outcomes: List[str] = []
    pending: List[str] = []

    for pol in policies:
        uid = pol.get("uid") or "?"
        name = pol.get("name") or uid
        conflict = pol.get("conflict") or SPEC_DEFAULT_CONFLICT
        # An Offer proposes terms; it entitles nobody until an Agreement is concluded.
        is_offer = term_key(pol.get("type") or pol.get("@type")) == "Offer"
        permits: List[RuleMatch] = []
        conditionals: List[RuleMatch] = []
        prohibits: List[RuleMatch] = []
        for kind in ("permission", "prohibition"):
            for idx, rule in enumerate(pol.get(kind) or []):
                if is_offer and kind == "prohibition" and rule.get("assignee") is None:
                    continue  # A product's terms bind its consumers through their Agreements.
                act = rule.get("action")
                if not act or not action_covers(act, request.action):
                    continue
                trail: List[str] = []
                fail_closed = kind == "prohibition"
                if not resolver.asset_matches(rule.get("target"), request, trail, fail_closed=fail_closed):
                    continue
                if not resolver.party_matches(rule.get("assignee"), request, trail, fail_closed=fail_closed):
                    continue
                cons = list(rule.get("constraint") or []) + list(rule.get("action_refinement") or [])
                cres = evaluate_constraints(cons, env)
                trail.extend(cres.detail)
                m = RuleMatch(uid, name, kind, idx, act, rule.get("target"), rule.get("assignee"), "",
                              reasons=trail, unenforceable=_non_platform_operands(cons))
                if not cres.satisfied:
                    m.effect = "constraint_unmet"
                    all_matches.append(m)
                    continue
                if kind == "prohibition":
                    m.effect = "prohibit"
                    prohibits.append(m)
                else:
                    done = set(request.fulfilled_duties) | set(pol.get("fulfilledDuties") or [])
                    unmet = [d.get("action") for d in rule.get("duty") or [] if d.get("action") not in done]
                    if is_offer:
                        unmet.append(OFFER_DUTY)
                        trail.append(f"offered by '{name}' — access needs an Agreement (request access)")
                    if unmet:
                        m.effect = "pending_duties"
                        m.pending_duties = [u for u in unmet if u]
                        conditionals.append(m)
                    else:
                        m.effect = "permit"
                        permits.append(m)
                all_matches.append(m)

        if prohibits and (permits or conditionals):
            if conflict == "perm":
                explanation.append(f"Policy '{name}': permission overrides prohibition (conflict=perm).")
                prohibits = []
            elif conflict == "prohibit":
                explanation.append(f"Policy '{name}': prohibition overrides permission (conflict=prohibit).")
                permits, conditionals = [], []
            else:
                explanation.append(f"Policy '{name}' is void: conflicting rules and conflict=invalid.")
                void.append(uid)
                continue
        if prohibits:
            outcomes.append(VERDICT_DENY)
            explanation.append(f"Policy '{name}' prohibits '{request.action}'.")
        elif permits:
            outcomes.append(VERDICT_ALLOW)
            explanation.append(f"Policy '{name}' permits '{request.action}'.")
        elif conditionals:
            outcomes.append(VERDICT_CONDITIONAL)
            for c in conditionals:
                pending.extend(d for d in c.pending_duties if d not in pending)
            explanation.append(f"Policy '{name}' permits '{request.action}' once duties are fulfilled: "
                               f"{', '.join(pending)}.")

    if VERDICT_DENY in outcomes:
        verdict = VERDICT_DENY
    elif VERDICT_ALLOW in outcomes:
        verdict = VERDICT_ALLOW
    elif VERDICT_CONDITIONAL in outcomes:
        verdict = VERDICT_CONDITIONAL
    else:
        verdict = VERDICT_NOT_APPLICABLE
        explanation.append("No applicable permission — denied by default.")
    if resolver.unresolved:
        explanation.append("Unresolved references (no active definition): " + ", ".join(resolver.unresolved))
    return Decision(verdict, verdict == VERDICT_ALLOW, explanation, all_matches, void, pending, list(resolver.unresolved))


# ---------------------------------------------------------------- index / IO

def index_terms(norm: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """(rule_kind, role, value) tuples for the policy lookup index."""
    out: set = set()

    def ref_values(ref: Any) -> List[str]:
        if isinstance(ref, str):
            return [ref]
        if isinstance(ref, dict):
            vals = [ref[k] for k in ("source", "uid") if ref.get(k)]
            vals.extend(m for m in ref.get("members") or [] if isinstance(m, str))
            return vals
        return []

    for kind in RULE_KINDS:
        for r in norm.get(kind) or []:
            if r.get("action"):
                out.add((kind, "action", r["action"]))
            for role in ("target", "assignee", "assigner"):
                for v in ref_values(r.get(role)):
                    out.add((kind, role, v))
    return sorted(out)


def to_jsonld(
    *,
    uid: str,
    policy_type: str,
    conflict: Optional[str],
    rules: Dict[str, Any],
    inherit_from: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Serialize a stored policy body as an ODRL JSON-LD document."""
    doc: Dict[str, Any] = {
        "@context": [ODRL_CONTEXT_URL, {"ontos": ONTOS_NS, "dc": "http://purl.org/dc/terms/"}],
        "@type": policy_type or "Set",
        "uid": uid,
        "profile": ONTOS_PROFILE,
    }
    if conflict:
        doc["conflict"] = conflict
    if inherit_from:
        doc["inheritFrom"] = inherit_from if len(inherit_from) > 1 else inherit_from[0]
    for k, v in (metadata or {}).items():
        if v is not None:
            doc[k] = v
    for kind in RULE_KINDS:
        if rules.get(kind):
            doc[kind] = [_rule_to_jsonld(r) for r in rules[kind]]
    return doc


def _constraint_to_jsonld(c: Dict[str, Any]) -> Dict[str, Any]:
    if c.get("logical"):
        return {c["logical"]: {"@list": [_constraint_to_jsonld(x) for x in c.get("constraints") or []]}}
    return {k: v for k, v in c.items() if v is not None}


def _rule_to_jsonld(r: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    act = r.get("action")
    if r.get("action_refinement"):
        out["action"] = [{"rdf:value": {"@id": act if ":" in (act or "") else f"odrl:{act}"},
                          "refinement": [_constraint_to_jsonld(c) for c in r["action_refinement"]]}]
    else:
        out["action"] = act
    for role in ("target", "assignee", "assigner"):
        if r.get(role) is not None:
            ref = r[role]
            if isinstance(ref, dict):
                ref = {k: ([_constraint_to_jsonld(c) for c in v] if k == "refinement" else v)
                       for k, v in ref.items()}
            out[role] = ref
    if r.get("constraint"):
        out["constraint"] = [_constraint_to_jsonld(c) for c in r["constraint"]]
    for sub in ("duty", "remedy", "consequence"):
        if r.get(sub):
            out[sub] = [_rule_to_jsonld(d) for d in r[sub]]
    if r.get("uid"):
        out["uid"] = r["uid"]
    return out
