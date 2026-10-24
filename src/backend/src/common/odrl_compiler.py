"""Compile active ODRL Access Policies into a platform-neutral Entitlement IR.

Pure module (no DB, no I/O), like :mod:`src.common.odrl`. The manager resolves
stored policies / Audiences / Asset Collections and hands plain dicts in; target
adapters (``src.common.uc_policy_adapter``) turn the IR into platform artifacts.

What the IR can express is deliberately narrow — static, unconditional (or
time-bound) grants of an action on a concrete securable to a concrete principal.
Everything else is never silently widened into a grant:

* **Gated** permissions — duties, workflow operands (``purpose``), action
  refinements, ABAC-only operands, refined asset collections — are not compiled
  into grants. They are listed in :attr:`EntitlementPlan.gated` with the reason;
  Agreements (Phase 3) or ABAC adapters pick them up.
* **Prohibitions** subtract from permissions (any deny wins across policies; a
  policy's own conflict strategy decides within it). Targets platforms have no
  DENY, so a prohibition that only *partially* overlaps a grant (narrower
  securable, narrower action, user vs. group) can't be enforced by removing the
  grant — that is a blocking ``error`` the author must resolve.
* **Inexact** party/asset sets (unresolvable references, refinements that need a
  directory or asset metadata) shrink permissions and block releases when they
  appear in prohibitions (fail closed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from src.common import odrl

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

GATE_WORKFLOW = "workflow"
GATE_ABAC = "abac"
GATE_UNSUPPORTED = "unsupported"

EVERYONE = "everyone"

# Party operands a static RBAC compile can resolve itself (groups) vs. via the
# principal directory (per-principal attributes).
_GROUP_OPERAND = "ontos:group"
_GROUP_OPERATORS = ("eq", "isAnyOf")


@dataclass(frozen=True)
class RuleRef:
    """Where an IR element came from."""
    policy_uid: str
    policy_id: Optional[str]
    policy_name: str
    policy_version: Optional[str]
    rule_kind: str
    rule_index: int
    rule_uid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def label(self) -> str:
        return f"{self.policy_name} {self.rule_kind} #{self.rule_index + 1}"


@dataclass
class CompileIssue:
    severity: str
    code: str
    message: str
    source: Optional[RuleRef] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.source:
            out["source"] = self.source.to_dict()
        return out


@dataclass
class Entitlement:
    """One atomic grant: ``principal`` may perform ``action`` on ``securable``."""
    principal: str  # typed: user:<email> | group:<name> | sp:<id> | everyone
    action: str
    securable: str  # target-native ref, e.g. uc:main.sales.orders
    expires_at: Optional[str] = None  # ISO 8601 (from dateTime lt/lteq)
    advisories: List[str] = field(default_factory=list)
    source: Optional[RuleRef] = None
    # Region a row filter restricts this grant to (spatial permission under the ABAC strategy).
    row_filter: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"principal": self.principal, "action": self.action, "securable": self.securable,
                               "expires_at": self.expires_at, "enforcement": odrl.ENFORCEMENT_PLATFORM}
        if self.advisories:
            out["advisories"] = list(self.advisories)
        if self.source:
            out["source"] = self.source.to_dict()
        return out


@dataclass
class GatedRule:
    """A permission that is not compiled into grants, and why."""
    source: RuleRef
    gate: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source.to_dict(), "gate": self.gate, "reason": self.reason}


@dataclass(frozen=True)
class AbacConfig:
    """Which attribute-based constructs the target can enforce (UC ABAC row filters / column masks).

    A strategy is enabled only when its UDF is configured: the function's signature and return
    types depend on the customer's columns, so Ontos never guesses one.
    """
    mask_function: Optional[str] = None  # catalog.schema.fn(col) -> masked value
    row_filter_function: Optional[str] = None  # catalog.schema.fn(col, value) -> BOOLEAN
    spatial_tag: str = "region"  # governed column tag carrying the region for ``spatial``
    # table full name -> True if it has a column carrying ``spatial_tag`` (None = can't tell).
    # A row filter only restricts tables with such a column, so without a confirmed column the
    # permission stays gated (fail closed) instead of becoming an unfiltered grant.
    has_tagged_column: Optional[Callable[[str, str], Optional[bool]]] = field(default=None, compare=False)


@dataclass
class AbacRule:
    """A content restriction the platform enforces at query time."""
    kind: str  # column_mask | row_filter
    principals: List[str]  # typed principals the policy applies TO
    securables: List[str]  # uc refs the policy is attached ON
    tag_key: str
    tag_value: Optional[str] = None
    value: Optional[str] = None  # row filter: the allowed value (e.g. the region)
    source: Optional[RuleRef] = None
    conflict: str = "prohibit"  # the source policy's conflict strategy

    def to_dict(self) -> Dict[str, Any]:
        out = {"kind": self.kind, "principals": list(self.principals), "securables": list(self.securables),
               "tag_key": self.tag_key, "tag_value": self.tag_value, "value": self.value,
               "enforcement": odrl.ENFORCEMENT_PLATFORM}
        if self.source:
            out["source"] = self.source.to_dict()
        return out


@dataclass
class EntitlementPlan:
    entitlements: List[Entitlement] = field(default_factory=list)
    abac: List[AbacRule] = field(default_factory=list)
    gated: List[GatedRule] = field(default_factory=list)
    obligations: List[Dict[str, Any]] = field(default_factory=list)
    issues: List[CompileIssue] = field(default_factory=list)
    compiled_at: str = ""

    @property
    def has_errors(self) -> bool:
        return any(i.severity == SEVERITY_ERROR for i in self.issues)

    def issue(self, severity: str, code: str, message: str, source: Optional[RuleRef] = None) -> None:
        self.issues.append(CompileIssue(severity, code, message, source))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compiled_at": self.compiled_at,
            "entitlements": [e.to_dict() for e in self.entitlements],
            "abac": [a.to_dict() for a in self.abac],
            "gated": [g.to_dict() for g in self.gated],
            "obligations": list(self.obligations),
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class PolicyInput:
    """An active policy, inheritance already resolved by the caller."""
    doc: Dict[str, Any]
    id: Optional[str] = None
    name: str = ""
    version: Optional[str] = None
    # Duty actions recorded as fulfilled on this policy (Agreements).
    fulfilled_duties: Set[str] = field(default_factory=set)


# A principal directory enumerates known principals with their attributes, for
# Audiences refined by principal attributes (v1: Ontos Business Roles).
PrincipalDirectory = Callable[[], Iterable[Tuple[str, Dict[str, List[str]]]]]


# --------------------------------------------------------------- party sets

@dataclass
class PartySet:
    principals: Set[str] = field(default_factory=set)
    everyone: bool = False
    # Why the set is not exact (only a subset could be determined); None = exact.
    inexact: Optional[str] = None


def typed_principal(ref: str) -> str:
    """``user:``/``mailto:``/``sp:``/``group:`` refs keep their kind; bare refs are users if they look like an email.

    User emails are lower-cased; group / SP names keep their case for display."""
    s = (ref or "").strip()
    low = s.lower()
    if low.startswith("mailto:"):
        return "user:" + low[len("mailto:"):]
    if low.startswith("user:"):
        return low  # Emails are case-insensitive.
    for prefix in ("sp:", "group:"):
        if low.startswith(prefix):
            return prefix + s[len(prefix):]
    return ("user:" + low) if "@" in s else ("group:" + s)


def principal_key(typed: str) -> str:
    """Comparison key: principals match case-insensitively (UC resolves them that way)."""
    return typed.lower()


def _split_party_refinement(refinement: List[Dict[str, Any]]) -> Tuple[Optional[Set[str]], List[Dict[str, Any]], bool]:
    """→ (groups required by ``ontos:group eq/isAnyOf``, other constraints, has_unsupported_group_constraint)."""
    groups: Optional[Set[str]] = None
    others: List[Dict[str, Any]] = []
    unsupported = False
    for c in refinement or []:
        if not c.get("logical") and c.get("leftOperand") == _GROUP_OPERAND:
            if c.get("operator") in _GROUP_OPERATORS:
                vals = {str(v) for v in odrl._as_list(c.get("rightOperand"))}
                groups = vals if groups is None else groups & vals
            else:
                unsupported = True
        else:
            others.append(c)
    return groups, others, unsupported


class _Parties:
    def __init__(self, audiences: Dict[str, odrl.CollectionDef], directory: Optional[PrincipalDirectory]):
        self.audiences = audiences
        self._directory = directory
        self._dir_cache: Optional[List[Tuple[str, Dict[str, List[str]]]]] = None

    def directory(self) -> List[Tuple[str, Dict[str, List[str]]]]:
        if self._dir_cache is None:
            self._dir_cache = list(self._directory()) if self._directory else []
        return self._dir_cache

    def resolve(self, ref: Any, depth: int = 0) -> PartySet:
        if ref is None:
            return PartySet(everyone=True)
        if depth > 8:
            return PartySet(inexact="collection nesting too deep")
        if isinstance(ref, dict):
            source = ref.get("source") or ref.get("uid")
            if source:
                base = self.resolve(source, depth + 1)
                return self._refine(base, ref.get("refinement") or []) if ref.get("refinement") else base
            return self._collection(list(ref.get("members") or []), list(ref.get("refinement") or []), "inline collection")
        if not isinstance(ref, str):
            return PartySet(inexact=f"unsupported party reference {ref!r}")
        if ref in self.audiences:
            aud = self.audiences[ref]
            return self._collection(list(aud.members), list(aud.refinement), f"audience '{aud.name}'")
        if ref.startswith(odrl.AUDIENCE_IRI_PREFIX):
            return PartySet(inexact=f"audience {ref} has no active version")
        return PartySet(principals={typed_principal(ref)})

    def _collection(self, members: List[str], refinement: List[Dict[str, Any]], label: str) -> PartySet:
        if not members and not refinement:
            return PartySet()  # Empty collection = nobody.
        if members:
            base = PartySet(principals={typed_principal(m) for m in members})
            return self._refine(base, refinement, label) if refinement else base
        groups, others, unsupported = _split_party_refinement(refinement)
        if unsupported:
            return PartySet(inexact=f"{label}: group constraint needs a directory to expand")
        if groups is not None and not others:
            return PartySet(principals={f"group:{g}" for g in groups})
        if groups is not None:
            return PartySet(inexact=f"{label}: combines group membership with principal attributes "
                                    "(needs directory group expansion or ABAC)")
        out = PartySet()
        for principal, attrs in self.directory():
            if odrl.evaluate_constraints(others, attrs).satisfied:
                out.principals.add(typed_principal(principal))
        return out

    def _refine(self, base: PartySet, refinement: List[Dict[str, Any]], label: str = "collection") -> PartySet:
        if base.everyone:
            return self._collection([], refinement, label)
        groups, others, unsupported = _split_party_refinement(refinement)
        if unsupported:
            return PartySet(inexact=f"{label}: group constraint needs a directory to expand")
        attrs_by_user = {principal_key(typed_principal(p)): a for p, a in self.directory()} if others else {}
        out = PartySet(inexact=base.inexact)
        for p in base.principals:
            kind = p.split(":", 1)[0]
            if kind == "group":
                if others or (groups is not None and p.split(":", 1)[1] not in groups):
                    if others:
                        out.inexact = f"{label}: principal-attribute refinement can't be applied to {p}"
                    continue
                out.principals.add(p)
                continue
            if groups is not None:
                out.inexact = f"{label}: group refinement can't be checked for {p} without a directory"
                continue
            if not others or odrl.evaluate_constraints(others, attrs_by_user.get(principal_key(p), {})).satisfied:
                out.principals.add(p)
        return out


# --------------------------------------------------------------- asset sets

@dataclass
class AssetSet:
    securables: Set[str] = field(default_factory=set)
    # Refs the UC compile can't target (non-UC IRIs).
    foreign: Set[str] = field(default_factory=set)
    inexact: Optional[str] = None


def canonical_securable(ref: str) -> Optional[str]:
    """``uc:Main.Sales.*`` → ``uc:main.sales``; non-UC refs → None."""
    if not isinstance(ref, str) or not ref.startswith(odrl.UC_PREFIX):
        return None
    name = ref[len(odrl.UC_PREFIX):].strip()
    if name.endswith(".*"):
        name = name[:-2]
    parts = [p for p in name.split(".") if p]
    if not parts or len(parts) > 3:
        return None
    return odrl.UC_PREFIX + ".".join(p.lower() for p in parts)


def securable_covers(outer: str, inner: str) -> bool:
    """UC privilege inheritance: a grant on ``outer`` reaches ``inner``."""
    o = outer[len(odrl.UC_PREFIX):].split(".")
    i = inner[len(odrl.UC_PREFIX):].split(".")
    return len(o) <= len(i) and i[: len(o)] == o


class _Assets:
    def __init__(self, collections: Dict[str, odrl.CollectionDef]):
        self.collections = collections

    def resolve(self, ref: Any, depth: int = 0) -> AssetSet:
        if ref is None:
            return AssetSet(inexact="rule has no target")
        if depth > 8:
            return AssetSet(inexact="collection nesting too deep")
        if isinstance(ref, dict):
            source = ref.get("source") or ref.get("uid")
            if source:
                base = self.resolve(source, depth + 1)
            else:
                base = self._members(list(ref.get("members") or []))
            if ref.get("refinement"):
                base.inexact = base.inexact or "inline asset collection refinement needs asset metadata (ABAC)"
            return base
        if not isinstance(ref, str):
            return AssetSet(inexact=f"unsupported asset reference {ref!r}")
        if ref in self.collections:
            col = self.collections[ref]
            out = self._members(list(col.members))
            if col.refinement:
                out.inexact = f"asset collection '{col.name}' is refined by asset attributes (needs ABAC)"
            return out
        if ref.startswith(odrl.ASSET_COLLECTION_IRI_PREFIX):
            return AssetSet(inexact=f"asset collection {ref} has no active version")
        return self._members([ref])

    @staticmethod
    def _members(members: List[str]) -> AssetSet:
        out = AssetSet()
        for m in members:
            c = canonical_securable(m)
            if c:
                out.securables.add(c)
            else:
                out.foreign.add(m)
        return out


# --------------------------------------------------------------- constraints

def _time_window(constraints: List[Dict[str, Any]]) -> Tuple[Optional[datetime], Optional[datetime], List[Dict[str, Any]]]:
    """Pull ``dateTime`` bounds out of a conjunction → (not_before, expires_at, remaining)."""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    rest: List[Dict[str, Any]] = []
    for c in constraints or []:
        if c.get("logical") or c.get("leftOperand") != "dateTime" or c.get("operator") not in ("lt", "lteq", "gt", "gteq"):
            rest.append(c)
            continue
        value = odrl._to_comparable(c.get("rightOperand"))
        if not isinstance(value, datetime):
            rest.append(c)
            continue
        if c["operator"] in ("lt", "lteq"):
            end = value if end is None else min(end, value)
        else:
            start = value if start is None else max(start, value)
    return start, end, rest


def _classify(constraints: List[Dict[str, Any]]) -> Tuple[List[str], Optional[Tuple[str, str]]]:
    """→ (advisory notes, first blocking gate as (gate, reason)) for non-time constraints."""
    advisories: List[str] = []
    for c in constraints:
        if c.get("logical"):
            return advisories, (GATE_ABAC, f"logical constraint ({c['logical']}) can't be expressed as a static grant")
        lo = c.get("leftOperand")
        spec = odrl.LEFT_OPERANDS.get(lo or "")
        if spec and spec.enforcement == odrl.ENFORCEMENT_ADVISORY:
            advisories.append(f"{spec.label}: {odrl._as_list(c.get('rightOperand'))}")
            continue
        if spec and spec.enforcement == odrl.ENFORCEMENT_WORKFLOW:
            return advisories, (GATE_WORKFLOW, f"'{spec.label}' is attested via workflow — granted through an Agreement")
        label = spec.label if spec else (lo or "?")
        return advisories, (GATE_ABAC, f"'{label}' constraint needs attribute-based enforcement (ABAC)")
    return advisories, None


def _iso(d: Optional[datetime]) -> Optional[str]:
    return d.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if d else None


# --------------------------------------------------------------- compile

@dataclass
class _Prohibition:
    parties: PartySet
    action: str
    securables: Set[str]
    source: RuleRef
    conflict: str
    # A prohibition that only takes effect later: overlapping grants get it as their expiry.
    starts_at: Optional[datetime] = None


def compile_policies(
    policies: List[PolicyInput],
    audiences: Optional[Dict[str, odrl.CollectionDef]] = None,
    asset_collections: Optional[Dict[str, odrl.CollectionDef]] = None,
    directory: Optional[PrincipalDirectory] = None,
    now: Optional[datetime] = None,
    abac: Optional[AbacConfig] = None,
) -> EntitlementPlan:
    """Active policies → :class:`EntitlementPlan` (see the module docstring for the semantics)."""
    now = now or datetime.now(timezone.utc)
    plan = EntitlementPlan(compiled_at=_iso(now) or "")
    parties = _Parties(audiences or {}, directory)
    assets = _Assets(asset_collections or {})

    candidates: List[Entitlement] = []
    prohibitions: List[_Prohibition] = []
    invalid_policies: Set[str] = set()

    for p in policies:
        norm = odrl.normalize_policy(p.doc)
        uid = norm.get("uid") or p.id or "?"
        conflict = norm.get("conflict") or odrl.SPEC_DEFAULT_CONFLICT

        is_offer = norm.get("type") == "Offer"
        for i, rule in enumerate(norm.get("permission") or []):
            src = _rule_ref(p, uid, "permission", i, rule)
            if is_offer:
                # Offered terms entitle nobody; access comes from the Agreement concluded on them.
                plan.gated.append(GatedRule(src, GATE_WORKFLOW, "offered — granted through an Agreement"))
                continue
            candidates.extend(_compile_permission(rule, src, parties, assets, now, plan, p.fulfilled_duties, abac))
        for i, rule in enumerate(norm.get("prohibition") or []):
            src = _rule_ref(p, uid, "prohibition", i, rule)
            if is_offer and rule.get("assignee") is None:
                # A product's terms bind its consumers through their Agreements (snapshotted there).
                plan.issue(SEVERITY_INFO, "offer_term", f"{src.label()} binds consumers via their Agreements", src)
                continue
            pro = _compile_prohibition(rule, src, conflict, parties, assets, now, plan, abac)
            if pro:
                prohibitions.append(pro)
        for i, rule in enumerate(norm.get("obligation") or []):
            src = _rule_ref(p, uid, "obligation", i, rule)
            plan.obligations.append({"source": src.to_dict(), "action": rule.get("action"),
                                     "enforcement": odrl.ENFORCEMENT_WORKFLOW})

    # Pass 1 — a policy under the 'invalid' strategy whose own permission and prohibition conflict
    # is void: none of its rules (prohibitions included) has any effect.
    for pro in prohibitions:
        if pro.conflict != "invalid" or pro.source.policy_uid in invalid_policies:
            continue
        if any(e.source and e.source.policy_uid == pro.source.policy_uid and _overlap(e, pro) is not None
               for e in candidates):
            invalid_policies.add(pro.source.policy_uid)
            plan.issue(SEVERITY_ERROR, "policy_conflict_invalid",
                       f"{pro.source.policy_name}: permission and prohibition conflict under the 'invalid' "
                       "strategy — the policy is void and has no effect", pro.source)
    prohibitions = [p for p in prohibitions if p.source.policy_uid not in invalid_policies]
    candidates = [e for e in candidates if not (e.source and e.source.policy_uid in invalid_policies)]

    # Pass 2 — prohibitions subtract from permissions (any deny wins across policies).
    kept: List[Entitlement] = []
    for e in candidates:
        denied = False
        for pro in prohibitions:
            verdict = _overlap(e, pro)
            if verdict is None:
                continue
            same_policy = e.source is not None and e.source.policy_uid == pro.source.policy_uid
            if same_policy and pro.conflict == "perm":
                continue  # Within a perm-strategy policy, permissions override its prohibitions.
            if verdict == "full" and pro.starts_at is not None:
                # Scheduled deny: end the grant when the prohibition starts (the expiry sweep revokes it).
                cap = pro.starts_at
                cur = odrl._to_comparable(e.expires_at) if e.expires_at else None
                if not isinstance(cur, datetime) or cap < cur:
                    e.expires_at = _iso(cap)
                    plan.issue(SEVERITY_INFO, "expires_at_prohibition",
                               f"{e.principal} {e.action} {e.securable} expires at {_iso(cap)} when "
                               f"{pro.source.label()} takes effect", e.source)
                continue
            if verdict == "full":
                plan.issue(SEVERITY_INFO, "denied_by_prohibition",
                           f"{e.principal} {e.action} {e.securable} removed by {pro.source.label()}", e.source)
            else:
                plan.issue(SEVERITY_ERROR, "prohibition_unenforceable",
                           f"{pro.source.label()} only partly overlaps the grant {e.principal} {e.action} "
                           f"{e.securable} ({verdict}); the platform has no DENY — narrow the permission or "
                           "the prohibition", pro.source)
            denied = True
            break
        if not denied:
            kept.append(e)
    plan.entitlements = _apply_abac_semantics(plan, kept, candidates, invalid_policies)
    return plan


def _apply_abac_semantics(plan: EntitlementPlan, kept: List[Entitlement], candidates: List[Entitlement],
                          invalid: Set[str]) -> List[Entitlement]:
    """Give ABAC rules the semantics the rules they come from have.

    * Masks of void policies vanish; under ``perm`` a policy's own permission overrides its mask.
    * Row filters exist only for grants that survived the prohibition pass. ODRL permissions add
      up: an unconditional permission for the same principal on the same (or a parent) securable
      makes the filter moot. Several regions for one principal on one table can't be expressed by
      a single-value filter — those grants are withheld (fail closed), never left unfiltered.
    """
    masks: List[AbacRule] = []
    for rule in plan.abac:
        if rule.kind != "column_mask" or (rule.source and rule.source.policy_uid in invalid):
            continue
        if rule.conflict == "perm" and rule.source and any(
                e.source and e.source.policy_uid == rule.source.policy_uid
                and principal_key(e.principal) in {principal_key(p) for p in rule.principals}
                and any(securable_covers(s, e.securable) or securable_covers(e.securable, s) for s in rule.securables)
                for e in candidates):
            plan.issue(SEVERITY_INFO, "mask_overridden",
                       f"{rule.source.label()}: the policy's own permission overrides the mask (conflict=perm)", rule.source)
            continue
        masks.append(rule)

    unconditional = [e for e in kept if e.row_filter is None]
    by_cell: Dict[Tuple[str, str], List[Entitlement]] = {}
    for e in kept:
        if e.row_filter is not None:
            by_cell.setdefault((principal_key(e.principal), e.securable), []).append(e)
    out = list(unconditional)
    filters: List[AbacRule] = []
    for (pkey, securable), items in sorted(by_cell.items()):
        if any(principal_key(u.principal) == pkey and securable_covers(u.securable, securable) and
               odrl.action_covers(u.action, items[0].action) for u in unconditional):
            for e in items:
                out.append(Entitlement(e.principal, e.action, e.securable, e.expires_at, e.advisories, e.source))
            continue  # Unfiltered access already granted: no filter (permissions add up).
        regions = sorted({e.row_filter for e in items})
        if len(regions) > 1:
            for e in items:
                if e.source:
                    plan.gated.append(GatedRule(e.source, GATE_ABAC, f"several regions ({', '.join(regions)}) for "
                                                f"{e.principal} on {e.securable} can't be one row filter"))
            continue  # Withheld: never an unfiltered grant.
        out.extend(items)
        first = items[0]
        filters.append(AbacRule("row_filter", [first.principal], [securable], "", None, regions[0], first.source))
    plan.abac = masks + filters
    return out


def _rule_ref(p: PolicyInput, uid: str, kind: str, i: int, rule: Dict[str, Any]) -> RuleRef:
    return RuleRef(uid, p.id, p.name or uid, p.version, kind, i, rule.get("uid"))


def _compile_permission(rule: Dict[str, Any], src: RuleRef, parties: _Parties, assets: _Assets,
                        now: datetime, plan: EntitlementPlan,
                        fulfilled: Optional[Set[str]] = None,
                        abac: Optional[AbacConfig] = None) -> List[Entitlement]:
    action = rule.get("action")
    if not action:
        plan.gated.append(GatedRule(src, GATE_UNSUPPORTED, "rule has no action"))
        return []
    open_duties = [d.get("action") or "?" for d in rule.get("duty") or [] if d.get("action") not in (fulfilled or set())]
    if open_duties:
        plan.gated.append(GatedRule(src, GATE_WORKFLOW,
                                    f"conditional on duties ({', '.join(open_duties)}) — granted once fulfilled"))
        return []
    if rule.get("action_refinement"):
        plan.gated.append(GatedRule(src, GATE_ABAC, "action refinement can't be expressed as a static grant"))
        return []
    start, end, rest = _time_window(rule.get("constraint") or [])
    region = _single_eq(rest, "spatial") if abac and abac.row_filter_function else None
    if region is not None:
        problem = _row_filter_problem(assets.resolve(rule.get("target")), abac)
        if problem:
            plan.gated.append(GatedRule(src, GATE_ABAC, problem))
            return []
        rest = []  # Enforced by a row filter on the granted table (below).
    advisories, gate = _classify(rest)
    if gate:
        plan.gated.append(GatedRule(src, gate[0], gate[1]))
        return []
    if end is not None and end <= now:
        plan.issue(SEVERITY_INFO, "expired", f"{src.label()} expired at {_iso(end)} — not granted", src)
        return []
    if start is not None and start > now:
        plan.issue(SEVERITY_INFO, "not_yet_active", f"{src.label()} starts at {_iso(start)} — not granted yet", src)
        return []

    party = parties.resolve(rule.get("assignee"))
    if party.inexact:
        plan.issue(SEVERITY_WARNING, "assignee_inexact",
                   f"{src.label()}: {party.inexact} — only the resolvable principals are granted", src)
    asset = assets.resolve(rule.get("target"))
    if asset.inexact:
        plan.gated.append(GatedRule(src, GATE_ABAC, asset.inexact))
        return []
    for f in sorted(asset.foreign):
        plan.issue(SEVERITY_WARNING, "foreign_target", f"{src.label()}: {f} is not a Unity Catalog securable — skipped", src)

    principals = [EVERYONE] if party.everyone else sorted(party.principals)
    if not principals and not party.inexact:
        plan.issue(SEVERITY_INFO, "no_principals", f"{src.label()}: the assignee resolves to nobody", src)
    out: List[Entitlement] = []
    for principal in principals:
        for securable in sorted(asset.securables):
            out.append(Entitlement(principal, action, securable, _iso(end), list(advisories), src,
                                   str(region) if region is not None else None))
    return out


def _row_filter_problem(asset: "AssetSet", abac: AbacConfig) -> Optional[str]:
    """Why a spatial permission can't become grant + row filter (None if it can)."""
    if asset.inexact or asset.foreign or not asset.securables:
        return "a row filter needs concrete Unity Catalog tables"
    for s in asset.securables:
        name = s[len(odrl.UC_PREFIX):]
        if len(name.split(".")) != 3:
            return f"a row filter needs table targets ({name} is a catalog/schema)"
        verdict = abac.has_tagged_column(name, abac.spatial_tag) if abac.has_tagged_column else None
        if verdict is not True:
            return (f"{name} has no column tagged '{abac.spatial_tag}'" if verdict is False else
                    f"can't verify that {name} has a column tagged '{abac.spatial_tag}'") + " — kept gated"
    return None


def _single_eq(constraints: List[Dict[str, Any]], operand: str) -> Optional[Any]:
    """The value if ``constraints`` is exactly one ``operand eq value`` constraint, else None."""
    if len(constraints) != 1:
        return None
    c = constraints[0]
    if c.get("logical") or c.get("leftOperand") != operand or c.get("operator") != "eq":
        return None
    value = c.get("rightOperand")
    return value if isinstance(value, (str, int, float)) and str(value).strip() else None


def _compile_prohibition(rule: Dict[str, Any], src: RuleRef, conflict: str, parties: _Parties, assets: _Assets,
                         now: datetime, plan: EntitlementPlan,
                         abac: Optional[AbacConfig] = None) -> Optional[_Prohibition]:
    action = rule.get("action")
    if not action:
        return None
    start, end, rest = _time_window(rule.get("constraint") or [])
    if end is not None and end <= now:
        plan.issue(SEVERITY_INFO, "prohibition_inactive", f"{src.label()} ended at {_iso(end)}", src)
        return None
    scheduled = start if start is not None and start > now else None
    if scheduled is not None:
        plan.issue(SEVERITY_INFO, "prohibition_scheduled",
                   f"{src.label()} takes effect at {_iso(scheduled)} — overlapping grants expire then", src)
    column_tag = _single_eq(rest, "ontos:columnTag") if abac and abac.mask_function else None
    # Only an exact read prohibition becomes a mask: a broader one (``use``) still denies the other
    # actions it covers, so it keeps the fail-closed treatment below.
    if column_tag is not None and not rule.get("action_refinement") and action == "read":
        party = parties.resolve(rule.get("assignee"))
        asset = assets.resolve(rule.get("target"))
        if party.inexact or asset.inexact or party.everyone:
            reason = party.inexact or asset.inexact or "a column mask for everyone needs explicit principals"
            plan.issue(SEVERITY_ERROR, "prohibition_inexact",
                       f"{src.label()}: {reason}; a column mask must name its principals and securables", src)
            return None
        key, _, value = str(column_tag).partition("=")
        plan.abac.append(AbacRule("column_mask", sorted(party.principals), sorted(asset.securables),
                                  key.strip(), value.strip() or None, None, src, conflict))
        scheduled = start if start is not None and start > now else None
        plan.issue(SEVERITY_INFO, "column_mask",
                   f"{src.label()} is enforced as a column mask"
                   + (f" (applied now — a mask can't wait for its start at {_iso(scheduled)})" if scheduled else ""), src)
        return None  # Masks the matching columns instead of denying the whole securable.
    if rest or rule.get("action_refinement"):
        # Fail closed: an unenforceable condition never lets a prohibition lapse.
        plan.issue(SEVERITY_WARNING, "prohibition_unconditional",
                   f"{src.label()}: its constraints can't be enforced statically — applied unconditionally", src)
    party = parties.resolve(rule.get("assignee"))
    asset = assets.resolve(rule.get("target"))
    for what, reason in (("assignee", party.inexact), ("target", asset.inexact)):
        if reason:
            plan.issue(SEVERITY_ERROR, "prohibition_inexact",
                       f"{src.label()}: {what} — {reason}; a prohibition must be exact to be enforced", src)
    if party.inexact or asset.inexact:
        return None
    return _Prohibition(party, action, set(asset.securables), src, conflict, scheduled)


def _overlap(e: Entitlement, pro: _Prohibition) -> Optional[str]:
    """None = no overlap; 'full' = the grant is entirely denied; otherwise why it's only partial."""
    if odrl.action_covers(pro.action, e.action):
        action_full = True
    elif odrl.action_covers(e.action, pro.action):
        action_full = False
    else:
        return None

    if pro.parties.everyone or principal_key(e.principal) in {principal_key(p) for p in pro.parties.principals}:
        party_full = True
    elif not pro.parties.principals:
        return None
    else:
        # A user prohibition vs. a group/everyone grant (or vice versa): membership is unknown here.
        g_kind = e.principal.split(":", 1)[0]
        p_kinds = {p.split(":", 1)[0] for p in pro.parties.principals}
        if g_kind == "user" and p_kinds <= {"user", "sp"}:
            return None
        if g_kind == "sp" and p_kinds <= {"user", "sp"}:
            return None
        party_full = False

    securable_full = any(securable_covers(s, e.securable) for s in pro.securables)
    securable_partial = not securable_full and any(securable_covers(e.securable, s) for s in pro.securables)
    if not securable_full and not securable_partial:
        return None

    if action_full and party_full and securable_full:
        return "full"
    reasons = []
    if not securable_full:
        reasons.append("prohibition targets a narrower securable")
    if not action_full:
        reasons.append("prohibition covers a narrower action")
    if not party_full:
        reasons.append("prohibited principal may be a member of the granted group")
    return "; ".join(reasons)
