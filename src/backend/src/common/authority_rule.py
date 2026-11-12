"""Scoped domain context and the ODRL-shaped rule of an Authority Relation.

Pure and DB-free, like ``authority_resolution_dna``. An AR's decision has two
layers (see GitHub issue #1294):

* **ODRL** carries the normative rule: the scope the authority holds in
  (``domain_context.scope``), value bounds and other constraints, duties such as
  a co-approval, and prohibitions (``authority_relations.rule``).
* **Compliance Checks** (the AR's criteria, Compliance-DSL ``ASSERT`` rules)
  carry derived and aggregate predicates.

Shapes, ODRL-compatible so they can later be evaluated by ``common/odrl.py``
("shape now, wire later")::

    domain_context = {"scope": [Constraint], "params": {key: value}}
    rule = {
        "permission": {"constraint": [Constraint | Logical], "duty": [Duty]},
        "prohibition": [{"name", "message", "constraint": [Constraint | Logical]}],
    }
    Constraint = {"leftOperand", "operator", "rightOperand" | "rightOperandReference",
                  "unit"?, "name"?, "message"?, "direction"?, "weight"?, "dimension"?}
    Logical    = {"or" | "and": [Constraint, ...], facets as above}
    Duty       = {"action", "name"?, "message"?, "constraint": [...] (fulfilled when they
                  hold), facets as above}

The scope is checked against the request context before anything else (a
missing key or a value outside the scope means the AR does not apply). The rule
is compiled into Compliance-DSL criteria, so the runtime gate and the DNA engine
evaluate it exactly like the AR's checks. Rules read the request as
``obj.<field>`` / ``req.<key>`` and the AR's parameters as ``ctx.<key>``.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from src.common.authority_resolution_dna import Criterion

# Criterion kinds: how the gate treats a failure.
KIND_CHECK = "check"              # a Compliance Check: failure denies
KIND_CONSTRAINT = "constraint"    # a permission constraint: failure denies
KIND_PROHIBITION = "prohibition"  # matched prohibition: denies
KIND_DUTY = "duty"                # unfulfilled duty: the permission is conditional

# Reserved evaluation namespaces (Compliance DSL ``ctx.x`` / ``req.x``).
NS_CTX = "ctx"
NS_REQ = "req"
RESERVED_KEYS = (NS_CTX, NS_REQ)

OPERATORS = ("eq", "neq", "lt", "lteq", "gt", "gteq", "isAnyOf", "isNoneOf")
_DSL_OPS = {"eq": "=", "neq": "!=", "lt": "<", "lteq": "<=", "gt": ">", "gteq": ">="}

# Left operands that name a canonical request field (ODRL core where one fits).
REQUEST_OPERANDS = {
    "payAmount": "value",
    "arf:value": "value",
    "arf:actor": "actor_identity",
    "arf:action": "action",
    "arf:objectId": "object_id",
    "arf:escalated": "escalated",
    "arf:cosignPresent": "cosign_present",
}
# ODRL core context operands a scope may use by their own name.
ODRL_CONTEXT_OPERANDS = ("spatial", "purpose", "dateTime", "industry", "language", "product")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPERAND_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_-]*:)?[A-Za-z_][A-Za-z0-9_]*$")
_REFERENCE_RE = re.compile(rf"^({NS_CTX}|{NS_REQ})\.([A-Za-z_][A-Za-z0-9_]*)$")
# ``clause`` cites the Authority Policy clause the item implements (e.g. "§7.1").
_FACETS = ("name", "message", "direction", "weight", "dimension", "clause")
# Compliance-DSL keywords can't follow ``req.`` / ``ctx.`` / ``obj.`` in a rule.
_DSL_KEYWORDS = frozenset({
    "MATCH", "WHERE", "ASSERT", "ON_PASS", "ON_FAIL", "CASE", "WHEN", "THEN", "ELSE", "END",
    "MATCHES", "IN", "CONTAINS", "AND", "OR", "NOT", "HAS_TAG", "TAG", "LENGTH", "UPPER",
    "LOWER", "PASS", "FAIL", "ASSIGN_TAG", "REMOVE_TAG", "NOTIFY", "TRUE", "FALSE",
})


def _check_name(name: str, what: str) -> None:
    """A name rules read as ``<ns>.<name>`` must be an identifier and no DSL keyword."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"{what} '{name}' must be an identifier (letters, digits, _).")
    if name.upper() in _DSL_KEYWORDS:
        raise ValueError(f"{what} '{name}' is a reserved word of the rule language; choose another name.")


# --------------------------------------------------------------------------- #
# Operand names                                                               #
# --------------------------------------------------------------------------- #

def operand_key(left_operand: str) -> str:
    """The request-context key an operand reads: its local name
    (``arf:market`` -> ``market``, ``spatial`` -> ``spatial``)."""
    return left_operand.rsplit(":", 1)[-1]


def operand_for_key(key: str) -> str:
    """The operand an authoring key is stored as: an ODRL core context operand
    keeps its name, anything else gets the ``arf:`` profile prefix."""
    key = key.strip()
    if ":" in key or key in ODRL_CONTEXT_OPERANDS:
        return key
    return f"arf:{key}"


# --------------------------------------------------------------------------- #
# Domain context                                                              #
# --------------------------------------------------------------------------- #

def normalize_domain_context(value: Any, strict: bool = False) -> Dict[str, Any]:
    """``{scope, params}`` from a stored or authored domain context.

    Accepts the structured shape, a scope given as ``{key: value | [values]}``
    (stored as ``eq`` / ``isAnyOf`` constraints), or a legacy flat blob (all of
    it becomes params: it never gated anything, so it doesn't start to).
    ``strict`` (writes) also requires parameter names that ``ctx.<name>`` can read.
    """
    if not value:
        return {"scope": [], "params": {}}
    if not isinstance(value, dict):
        raise ValueError("domain_context must be an object.")
    if not is_structured(value):
        return {"scope": [], "params": dict(value)}
    scope = value.get("scope") or []
    if isinstance(scope, dict):
        scope = [
            {"leftOperand": operand_for_key(k),
             "operator": "isAnyOf" if isinstance(v, list) else "eq",
             "rightOperand": v}
            for k, v in scope.items()
        ]
    params = value.get("params") or {}
    if not isinstance(scope, list) or not isinstance(params, dict):
        raise ValueError("domain_context.scope must be a list and domain_context.params an object.")
    for k in params if strict else ():
        _check_name(str(k), "Parameter name")
    validated = [_validate_constraint(c, where="domain_context.scope", allow_reference=False,
                                      allow_logical=False)
                 for c in scope]
    return {"scope": validated, "params": dict(params)}


def is_structured(value: Any) -> bool:
    """Is ``value`` the ``{scope, params}`` shape (not a legacy flat blob)?

    Only ``scope`` / ``params`` keys, ``scope`` a list or mapping and ``params``
    a mapping: a legacy blob that happens to have a ``scope`` key (``"scope":
    "feature"``) next to others stays a blob, so it reads as params.
    """
    if not isinstance(value, dict) or not value or not set(value) <= {"scope", "params"}:
        return False
    return (value.get("scope") is None or isinstance(value["scope"], (list, dict))) and \
        (value.get("params") is None or isinstance(value["params"], dict))


def merge_domain_context(current: Any, update: Any) -> Dict[str, Any]:
    """Apply an update: each part it carries (``scope`` / ``params``) replaces
    that part; a part it leaves out is kept. A legacy flat update is params."""
    cur = normalize_domain_context(current)
    if update is None:
        # An explicit null clears the context.
        return {"scope": [], "params": {}}
    if is_structured(update):
        new = normalize_domain_context(update, strict=True)
        return {
            "scope": new["scope"] if "scope" in update else cur["scope"],
            "params": new["params"] if "params" in update else cur["params"],
        }
    return {"scope": cur["scope"], "params": normalize_domain_context(update, strict=True)["params"]}


def check_scope(
    domain_context: Any,
    request_context: Dict[str, Any],
    equivalents: Optional[Callable[[Any], Set[str]]] = None,
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """Does the request fall inside the AR's scope?

    Every scope constraint must hold; a missing context key fails. String
    values compare casefolded; ``equivalents`` widens a request value to the
    strings it stands for (e.g. a concept label and its IRI). Returns
    ``(in_scope, reason, per-constraint results)``.
    """
    results: List[Dict[str, Any]] = []
    for c in normalize_domain_context(domain_context)["scope"]:
        key = operand_key(c["leftOperand"])
        entry = {"operand": c["leftOperand"], "operator": c["operator"],
                 "expected": c["rightOperand"], "actual": request_context.get(key)}
        if request_context.get(key) in (None, ""):
            entry["passed"] = False
            results.append(entry)
            return False, f"context.{key} missing", results
        entry["passed"] = compare_value(request_context[key], c["operator"], c["rightOperand"], equivalents)
        results.append(entry)
        if not entry["passed"]:
            return False, f"out of scope: {key}={request_context[key]}", results
    return True, "in scope", results


def _fold(v: Any) -> str:
    return str(v).strip().casefold()


def compare_value(actual: Any, op: str, expected: Any, equivalents: Optional[Callable[[Any], Set[str]]] = None) -> bool:
    """One scope comparison: casefolded strings (widened by ``equivalents``),
    numbers for the ordering operators."""
    if op in ("eq", "neq", "isAnyOf", "isNoneOf"):
        values = expected if isinstance(expected, list) else [expected]
        have = equivalents(actual) if equivalents else {_fold(actual)}
        hit = bool(have & {_fold(v) for v in values})
        return hit if op in ("eq", "isAnyOf") else not hit
    try:
        a, b = float(actual), float(expected)
    except (TypeError, ValueError):
        a, b = _fold(actual), _fold(expected)
    return {"lt": a < b, "lteq": a <= b, "gt": a > b, "gteq": a >= b}[op]


# --------------------------------------------------------------------------- #
# Rule validation and compilation                                             #
# --------------------------------------------------------------------------- #

def _validate_constraint(
    c: Any, *, where: str, allow_reference: bool = True, allow_logical: bool = True,
) -> Dict[str, Any]:
    if not isinstance(c, dict):
        raise ValueError(f"{where}: a constraint must be an object.")
    for logical in ("or", "and"):
        if logical in c:
            if not allow_logical:
                raise ValueError(f"{where}: a scope lists plain constraints (all must hold), not '{logical}'.")
            parts = c[logical]
            if not isinstance(parts, list) or len(parts) < 2:
                raise ValueError(f"{where}: '{logical}' needs a list of at least two constraints.")
            out = {logical: [_validate_constraint(p, where=where, allow_reference=allow_reference)
                             for p in parts]}
            out.update({k: c[k] for k in _FACETS if c.get(k) is not None})
            return out
    left = str(c.get("leftOperand") or "").strip()
    op = str(c.get("operator") or "").strip()
    if not _OPERAND_RE.match(left):
        raise ValueError(f"{where}: leftOperand '{left}' must be a name such as 'payAmount' or 'arf:market'.")
    if op not in OPERATORS:
        raise ValueError(f"{where}: operator '{op}' must be one of {', '.join(OPERATORS)}.")
    if left not in REQUEST_OPERANDS:
        _check_name(operand_key(left), f"{where}: context key")
    out = {"leftOperand": left, "operator": op}
    ref = c.get("rightOperandReference")
    if ref is not None:
        if not allow_reference:
            raise ValueError(f"{where}: a scope compares with values, not references.")
        m = _REFERENCE_RE.match(str(ref))
        if not m:
            raise ValueError(f"{where}: rightOperandReference '{ref}' must be ctx.<param> or req.<key>.")
        _check_name(m.group(2), f"{where}: reference")
        out["rightOperandReference"] = str(ref)
    else:
        if "rightOperand" not in c or c["rightOperand"] in (None, "", []):
            raise ValueError(f"{where}: constraint on '{left}' needs a rightOperand.")
        right = c["rightOperand"]
        if op in ("isAnyOf", "isNoneOf") and not isinstance(right, list):
            right = [right]
        if op not in ("isAnyOf", "isNoneOf") and isinstance(right, list):
            raise ValueError(f"{where}: '{op}' compares with one value, not a list.")
        for v in right if isinstance(right, list) else [right]:
            if not isinstance(v, (str, int, float, bool)):
                raise ValueError(f"{where}: rightOperand values must be strings, numbers or booleans.")
            if isinstance(v, float) and not math.isfinite(v):
                raise ValueError(f"{where}: rightOperand numbers must be finite.")
        out["rightOperand"] = right
    if c.get("unit"):
        out["unit"] = str(c["unit"])
    out.update({k: c[k] for k in _FACETS if c.get(k) is not None})
    return out


def normalize_rule(rule: Any) -> Optional[Dict[str, Any]]:
    """Validate an authored rule; ``None`` / empty means no rule."""
    if not rule:
        return None
    if not isinstance(rule, dict):
        raise ValueError("rule must be an object.")
    perm = rule.get("permission") or {}
    if not isinstance(perm, dict):
        raise ValueError("rule.permission must be an object.")
    constraints = [_validate_constraint(c, where="rule.permission.constraint")
                   for c in perm.get("constraint") or []]
    duties = []
    for d in perm.get("duty") or []:
        if not isinstance(d, dict) or not str(d.get("action") or "").strip():
            raise ValueError("rule.permission.duty: each duty needs an action (e.g. arf:obtainCoApproval).")
        fulfilled_by = [_validate_constraint(c, where="rule.permission.duty") for c in d.get("constraint") or []]
        if not fulfilled_by:
            raise ValueError(f"rule.permission.duty '{d['action']}' needs a constraint that tells when it is fulfilled.")
        duty = {"action": str(d["action"]).strip(), "constraint": fulfilled_by}
        duty.update({k: d[k] for k in _FACETS if d.get(k) is not None})
        duties.append(duty)
    prohibitions = []
    for p in rule.get("prohibition") or []:
        if not isinstance(p, dict):
            raise ValueError("rule.prohibition: each prohibition must be an object.")
        when = [_validate_constraint(c, where="rule.prohibition.constraint") for c in p.get("constraint") or []]
        if not when:
            raise ValueError("rule.prohibition: each prohibition needs at least one constraint.")
        prohibition = {"constraint": when}
        prohibition.update({k: p[k] for k in _FACETS if p.get(k) is not None})
        prohibitions.append(prohibition)
    if not (constraints or duties or prohibitions):
        return None
    out: Dict[str, Any] = {"permission": {"constraint": constraints, "duty": duties}}
    if prohibitions:
        out["prohibition"] = prohibitions
    return out


def _literal(v: Any) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        # Plain decimal notation (the DSL lexer reads no exponents).
        text = format(Decimal(repr(v)), "f")
        return text if "." in text else text + ".0"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _field(left_operand: str) -> str:
    canonical = REQUEST_OPERANDS.get(left_operand)
    if canonical:
        return f"obj.{canonical}"
    return f"{NS_REQ}.{operand_key(left_operand)}"


def constraint_expression(c: Dict[str, Any]) -> str:
    """The Compliance-DSL condition of a validated constraint (no ``ASSERT``)."""
    for logical in ("or", "and"):
        if logical in c:
            return "(" + f" {logical.upper()} ".join(constraint_expression(p) for p in c[logical]) + ")"
    field = _field(c["leftOperand"])
    op = c["operator"]
    right = c.get("rightOperandReference")
    if right is None:
        v = c["rightOperand"]
        right = "[" + ", ".join(_literal(x) for x in v) + "]" if isinstance(v, list) else _literal(v)
    if op == "isAnyOf":
        return f"{field} IN {right}"
    if op == "isNoneOf":
        return f"NOT ({field} IN {right})"
    return f"{field} {_DSL_OPS[op]} {right}"


def describe_constraint(c: Dict[str, Any]) -> str:
    """A short human label, e.g. ``payAmount lteq ctx.threshold``."""
    for logical in ("or", "and"):
        if logical in c:
            return f" {logical} ".join(describe_constraint(p) for p in c[logical])
    right = c.get("rightOperandReference")
    if right is None:
        v = c["rightOperand"]
        right = "[" + ", ".join(str(x) for x in v) + "]" if isinstance(v, list) else str(v)
    return f"{c['leftOperand']} {c['operator']} {right}"


def _criterion(kind: str, code: str, expr: str, facets: Dict[str, Any], default_direction: str) -> Criterion:
    return Criterion(
        code=str(facets.get("name") or code),
        rule=f"ASSERT {expr}",
        direction=str(facets.get("direction") or default_direction),
        weight=float(facets["weight"]) if facets.get("weight") is not None else 1.0,
        dimension=str(facets.get("dimension") or "policy"),
        message=facets.get("message") or None,
        kind=kind,
        clause=str(facets["clause"]) if facets.get("clause") else None,
    )


def compile_rule(rule: Any) -> List[Criterion]:
    """The rule as engine criteria, in gate order: prohibitions, permission
    constraints, then duties. A duty's rule is its fulfilment condition."""
    rule = normalize_rule(rule)
    if not rule:
        return []
    out: List[Criterion] = []
    for p in rule.get("prohibition") or []:
        when = " AND ".join(constraint_expression(c) for c in p["constraint"])
        label = " and ".join(describe_constraint(c) for c in p["constraint"])
        out.append(_criterion(KIND_PROHIBITION, f"prohibited: {label}", f"NOT ({when})", p,
                              "actual-exceeds-documented"))
    for c in rule["permission"]["constraint"]:
        out.append(_criterion(KIND_CONSTRAINT, describe_constraint(c), constraint_expression(c), c,
                              "actual-exceeds-documented"))
    for d in rule["permission"]["duty"]:
        expr = " AND ".join(constraint_expression(c) for c in d["constraint"])
        out.append(_criterion(KIND_DUTY, d["action"], expr, d, "documented-exceeds-actual"))
    return out


def has_rule(rule: Any) -> bool:
    return bool(normalize_rule(rule))


# --------------------------------------------------------------------------- #
# Evaluation object                                                           #
# --------------------------------------------------------------------------- #

_NUMBER_RE = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
# Canonical identity fields stay text even when they look numeric.
_TEXT_FIELDS = ("actor_identity", "action", "object_id")


def _number_or_text(key: str, value: Any) -> Any:
    """A context value sent as a numeric string (``"600000"``) as a number, so
    rules compare it the way the scope does; identity fields stay text."""
    if isinstance(value, str) and key not in _TEXT_FIELDS and _NUMBER_RE.match(value.strip()):
        text = value.strip()
        return float(text) if "." in text else int(text)
    return value


def evaluation_object(
    flat: Dict[str, Any],
    params: Dict[str, Any],
    extra_ctx: Optional[Dict[str, Any]] = None,
    strip: Iterable[str] = (),
) -> Dict[str, Any]:
    """The object rules evaluate against.

    ``flat`` is the request (or an evidence row) as before, so existing
    ``obj.<field>`` rules read it unchanged; ``req`` is the same request as a
    namespace and ``ctx`` the AR's parameters plus ``extra_ctx`` (resolved refs).
    Caller-supplied ``ctx`` / ``req`` keys (and any ``strip`` prefixes) are
    dropped: a request can't impersonate the AR's own values.
    """
    prefixes = tuple(strip)
    clean = {
        k: _number_or_text(k, v) for k, v in flat.items()
        if k not in RESERVED_KEYS and not (prefixes and str(k).startswith(prefixes))
    }
    ctx = dict(params or {})
    ctx.update(extra_ctx or {})
    obj = dict(clean)
    obj[NS_REQ] = {k: v for k, v in clean.items() if v is not None}
    obj[NS_CTX] = ctx
    return obj
