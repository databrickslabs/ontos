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

Rules evaluate strictly (ARF, #1491-1): an absent operand is UNKNOWN and combines
with Kleene logic (``or: [a, b]`` holds when ``b`` does, even if ``a`` is absent).
An UNKNOWN top level fails closed. A constraint or check is not satisfied. A
prohibition is not known to be inapplicable, so it denies: this is a deliberate
deviation from ODRL, where a prohibition that cannot be shown to apply does not
block. An authority gate must not approve on an undecidable prohibition, and the
denial names the field to send. A duty stays unfulfilled. A ``ctx.<param>`` that is
absent is an AR configuration fault (a conflict), not a request fault.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from src.common.authority_resolution_dna import Criterion
from src.common.api_errors import CodedValueError


class RuleInvalidError(CodedValueError):
    """A domain context or rule the author must fix; the message says what.

    Same code as the manager's ``AuthorityInvalidError``, so routes answer 400
    with the message instead of a generic failure.
    """

    code = "authority_invalid"

# Criterion kinds: how the gate treats a failure.
KIND_CHECK = "check"              # a Compliance Check: failure denies
KIND_CONSTRAINT = "constraint"    # a permission constraint: failure denies
KIND_PROHIBITION = "prohibition"  # matched prohibition: denies
KIND_DUTY = "duty"                # unfulfilled duty: the permission is conditional

# Reserved evaluation namespaces (Compliance DSL ``ctx.x`` / ``req.x``).
NS_CTX = "ctx"
NS_REQ = "req"
# ARF 1.2.0: the cited policy reference's validity (cited, valid_from, valid_to, expired).
# A request field named ``policy_ref`` is dropped (anti-spoofing); a field named
# ``justification`` stays an ordinary ``obj.justification`` field.
NS_POLICY_REF = "policy_ref"
RESERVED_KEYS = (NS_CTX, NS_REQ, NS_POLICY_REF)
# What the checks see when no reference is cited, or none is known (a dry-run sample).
UNCITED_POLICY_REF: Dict[str, Any] = {"cited": False, "valid_from": None, "valid_to": None, "expired": False}

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


def ref_param_key(field_path: Any) -> Optional[str]:
    """The AR parameter a ``domain_context`` resource ref names, or None.

    ``domain_context.<key>`` and ``domain_context.params.<key>`` name ``ctx.<key>``
    (shared by the parameter check on save, the resolver's ``ctx`` and the ref writer).
    A single identifier-like segment only; the path is stripped first.
    """
    path = str(field_path or "").strip()
    for prefix in ("domain_context.params.", "domain_context."):
        if path.startswith(prefix):
            key = path[len(prefix):].strip()
            return key if key and "." not in key else None
    return None


def _check_name(name: str, what: str) -> None:
    """A name rules read as ``<ns>.<name>`` must be an identifier and no DSL keyword."""
    if not _IDENT_RE.match(name):
        raise RuleInvalidError(f"{what} '{name}' must be an identifier (letters, digits, _).")
    if name.upper() in _DSL_KEYWORDS:
        raise RuleInvalidError(f"{what} '{name}' is a reserved word of the rule language; choose another name.")


# --------------------------------------------------------------------------- #
# Operand names                                                               #
# --------------------------------------------------------------------------- #

def operand_key(left_operand: str) -> str:
    """The request-context key an operand reads: its local name
    (``arf:market`` -> ``market``, ``spatial`` -> ``spatial``)."""
    return left_operand.rsplit(":", 1)[-1]


def scope_key(left_operand: str) -> str:
    """The request key a scope operand reads. A typed field reads its canonical
    field (``arf:actor`` -> ``actor_identity``), the same as a rule's ``obj.`` read,
    so a caller can't pick the key by sending a same-named context value (#1491-2)."""
    return REQUEST_OPERANDS.get(left_operand) or operand_key(left_operand)


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
        raise RuleInvalidError("domain_context must be an object.")
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
        raise RuleInvalidError("domain_context.scope must be a list and domain_context.params an object.")
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
        key = scope_key(c["leftOperand"])
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

def checked_weight(value: Any, where: str) -> float:
    """A weight (of a facet or a check) is a finite number of 0 or more (#1491-5).

    Shared by rule facets and checks. A bool is refused, though it is an int in
    Python. A non-numeric weight used to be saved and then make every resolve a conflict.
    """
    if isinstance(value, bool):
        raise RuleInvalidError(f"{where}: weight must be a number of 0 or more, not a boolean.")
    try:
        weight = float(value)
    except (TypeError, ValueError):
        raise RuleInvalidError(f"{where}: weight must be a number of 0 or more, not '{value}'.")
    if not math.isfinite(weight) or weight < 0:
        raise RuleInvalidError(f"{where}: weight must be a finite number of 0 or more, not '{value}'.")
    return weight


def _facets(src: Dict[str, Any], where: str) -> Dict[str, Any]:
    """The presentational facets of an authored item, with the weight checked."""
    out = {k: src[k] for k in _FACETS if src.get(k) is not None}
    if "weight" in out:
        out["weight"] = checked_weight(out["weight"], where)
    return out


def _validate_constraint(
    c: Any, *, where: str, allow_reference: bool = True, allow_logical: bool = True,
) -> Dict[str, Any]:
    if not isinstance(c, dict):
        raise RuleInvalidError(f"{where}: a constraint must be an object.")
    for logical in ("or", "and"):
        if logical in c:
            if not allow_logical:
                raise RuleInvalidError(f"{where}: a scope lists plain constraints (all must hold), not '{logical}'.")
            parts = c[logical]
            if not isinstance(parts, list) or len(parts) < 2:
                raise RuleInvalidError(f"{where}: '{logical}' needs a list of at least two constraints.")
            out = {logical: [_validate_constraint(p, where=where, allow_reference=allow_reference)
                             for p in parts]}
            out.update(_facets(c, where))
            return out
    left = str(c.get("leftOperand") or "").strip()
    op = str(c.get("operator") or "").strip()
    if not _OPERAND_RE.match(left):
        raise RuleInvalidError(f"{where}: leftOperand '{left}' must be a name such as 'payAmount' or 'arf:market'.")
    if op not in OPERATORS:
        raise RuleInvalidError(f"{where}: operator '{op}' must be one of {', '.join(OPERATORS)}.")
    if left not in REQUEST_OPERANDS:
        _check_name(operand_key(left), f"{where}: context key")
    out = {"leftOperand": left, "operator": op}
    ref = c.get("rightOperandReference")
    if ref is not None:
        if not allow_reference:
            raise RuleInvalidError(f"{where}: a scope compares with values, not references.")
        m = _REFERENCE_RE.match(str(ref))
        if not m:
            raise RuleInvalidError(f"{where}: rightOperandReference '{ref}' must be ctx.<param> or req.<key>.")
        _check_name(m.group(2), f"{where}: reference")
        out["rightOperandReference"] = str(ref)
    else:
        if "rightOperand" not in c or c["rightOperand"] in (None, "", []):
            raise RuleInvalidError(f"{where}: constraint on '{left}' needs a rightOperand.")
        right = c["rightOperand"]
        if op in ("isAnyOf", "isNoneOf") and not isinstance(right, list):
            right = [right]
        if op not in ("isAnyOf", "isNoneOf") and isinstance(right, list):
            raise RuleInvalidError(f"{where}: '{op}' compares with one value, not a list.")
        for v in right if isinstance(right, list) else [right]:
            if not isinstance(v, (str, int, float, bool)):
                raise RuleInvalidError(f"{where}: rightOperand values must be strings, numbers or booleans.")
            if isinstance(v, float) and not math.isfinite(v):
                raise RuleInvalidError(f"{where}: rightOperand numbers must be finite.")
        out["rightOperand"] = right
    if c.get("unit"):
        out["unit"] = str(c["unit"])
    out.update(_facets(c, where))
    return out


def normalize_rule(rule: Any) -> Optional[Dict[str, Any]]:
    """Validate an authored rule; ``None`` / empty means no rule."""
    if not rule:
        return None
    if not isinstance(rule, dict):
        raise RuleInvalidError("rule must be an object.")
    perm = rule.get("permission") or {}
    if not isinstance(perm, dict):
        raise RuleInvalidError("rule.permission must be an object.")
    constraints = [_validate_constraint(c, where="rule.permission.constraint")
                   for c in perm.get("constraint") or []]
    duties = []
    for d in perm.get("duty") or []:
        if not isinstance(d, dict) or not str(d.get("action") or "").strip():
            raise RuleInvalidError("rule.permission.duty: each duty needs an action (e.g. arf:obtainCoApproval).")
        fulfilled_by = [_validate_constraint(c, where="rule.permission.duty") for c in d.get("constraint") or []]
        if not fulfilled_by:
            raise RuleInvalidError(f"rule.permission.duty '{d['action']}' needs a constraint that tells when it is fulfilled.")
        duty = {"action": str(d["action"]).strip(), "constraint": fulfilled_by}
        duty.update(_facets(d, "rule.permission.duty"))
        duties.append(duty)
    prohibitions = []
    for p in rule.get("prohibition") or []:
        if not isinstance(p, dict):
            raise RuleInvalidError("rule.prohibition: each prohibition must be an object.")
        when = [_validate_constraint(c, where="rule.prohibition.constraint") for c in p.get("constraint") or []]
        if not when:
            raise RuleInvalidError("rule.prohibition: each prohibition needs at least one constraint.")
        prohibition = {"constraint": when}
        prohibition.update(_facets(p, "rule.prohibition"))
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


def _numeric_form(v: Any) -> Any:
    """The number a numeric-looking string stands for, else None."""
    if isinstance(v, str) and _NUMBER_RE.match(v.strip()):
        text = v.strip()
        return float(text) if "." in text else int(text)
    return None


def _is_number_like(v: Any) -> bool:
    """A number, or a string that reads as one (not a boolean)."""
    return _numeric_form(v) is not None or (isinstance(v, (int, float)) and not isinstance(v, bool))


def _set_members(values: List[Any]) -> List[Any]:
    """Literals for a membership test, with each numeric value in both forms.

    A request value that reads as a number is held as one (``_number_or_text``), so
    ``'1234'`` in a rule must also match ``1234`` and the other way round (#1491-4).
    A boolean stays itself; only the numeric forms derived from a number are added.
    """
    members: List[Any] = []
    seen: set = set()
    for v in values:
        if isinstance(v, bool):
            forms = [v]
        else:
            forms = [v, _numeric_form(v)]
            if isinstance(v, (int, float)):
                forms.append(str(int(v)) if float(v).is_integer() else repr(v))
        for f in forms:
            if f is None:
                continue
            key = (type(f), f)
            if key not in seen:
                seen.add(key)
                members.append(f)
    return members


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
        values = v if isinstance(v, list) else [v]
        if op in ("isAnyOf", "isNoneOf") or (op in ("eq", "neq") and any(_is_number_like(x) for x in values)):
            # A membership test (#1491-4): ``eq '1234'`` is ``IN ['1234', 1234]``,
            # ``eq 1234`` is ``IN [1234, '1234']`` (a text field holds the number as text).
            test = f"{field} IN [" + ", ".join(_literal(x) for x in _set_members(values)) + "]"
            return test if op in ("isAnyOf", "eq") else f"NOT ({test})"
        if op in ("lt", "lteq", "gt", "gteq") and _numeric_form(v) is not None:
            v = _numeric_form(v)
        right = "[" + ", ".join(_literal(x) for x in v) + "]" if isinstance(v, list) else _literal(v)
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
# Parameter references                                                        #
# --------------------------------------------------------------------------- #

_CTX_REF_RE = re.compile(rf"\b{NS_CTX}\.([A-Za-z_][A-Za-z0-9_]*)")
_STRING_LITERAL_RE = re.compile(r"'(?:\\.|[^'\\])*'")


class UnknownParameterError(RuleInvalidError):
    """A rule or check reads ``ctx.<name>`` that the AR's parameters don't define (#1491-1)."""

    code = "authority_unknown_parameter"


def context_references(texts: Iterable[str]) -> Set[str]:
    """The names rules read as ``ctx.<name>``, in DSL rule text (string literals skipped)."""
    names: Set[str] = set()
    for text in texts:
        names.update(_CTX_REF_RE.findall(_STRING_LITERAL_RE.sub("''", text or "")))
    return names


def check_parameter_references(texts: Iterable[str], known: Iterable[str]) -> None:
    """Refuse a ``ctx.<name>`` read that no parameter (or domain-context ref) defines.

    Saved, so an AR can't end up with a rule that reads a parameter it no longer has.
    The names are in the error's ``parameters``.
    """
    unknown = sorted(context_references(texts) - set(known))
    if not unknown:
        return
    refs = ", ".join(f"{NS_CTX}.{n}" for n in unknown)
    verb = "is not a parameter" if len(unknown) == 1 else "are not parameters"
    raise UnknownParameterError(
        f"The rule reads {refs}, which {verb} of this Authority Relation. "
        "Add the parameter to the domain context, or fix the reference.",
        parameters=unknown,
    )


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
    *,
    policy_ref: Dict[str, Any],
) -> Dict[str, Any]:
    """The object rules evaluate against: the one builder for resolve, DNA and the validators.

    ``flat`` is the request (or an evidence row) as before, so existing
    ``obj.<field>`` rules read it unchanged; ``req`` is the same request as a
    namespace and ``ctx`` the AR's parameters plus ``extra_ctx`` (resolved refs).
    ``policy_ref`` is the cited reference's validity (``policy_ref.cited /
    valid_from / valid_to / expired``), fixed by the caller for the whole evaluation.
    Caller-supplied ``ctx`` / ``req`` / ``policy_ref`` keys (and any ``strip``
    prefixes) are dropped: a request can't impersonate the AR's own values.
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
    obj[NS_POLICY_REF] = dict(policy_ref)
    return obj
