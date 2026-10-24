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


@dataclass
class EntitlementPlan:
    entitlements: List[Entitlement] = field(default_factory=list)
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
            candidates.extend(_compile_permission(rule, src, parties, assets, now, plan))
        for i, rule in enumerate(norm.get("prohibition") or []):
            src = _rule_ref(p, uid, "prohibition", i, rule)
            if is_offer and rule.get("assignee") is None:
                # A product's terms bind its consumers through their Agreements (snapshotted there).
                plan.issue(SEVERITY_INFO, "offer_term", f"{src.label()} binds consumers via their Agreements", src)
                continue
            pro = _compile_prohibition(rule, src, conflict, parties, assets, now, plan)
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
    plan.entitlements = kept
    return plan


def _rule_ref(p: PolicyInput, uid: str, kind: str, i: int, rule: Dict[str, Any]) -> RuleRef:
    return RuleRef(uid, p.id, p.name or uid, p.version, kind, i, rule.get("uid"))


def _compile_permission(rule: Dict[str, Any], src: RuleRef, parties: _Parties, assets: _Assets,
                        now: datetime, plan: EntitlementPlan) -> List[Entitlement]:
    action = rule.get("action")
    if not action:
        plan.gated.append(GatedRule(src, GATE_UNSUPPORTED, "rule has no action"))
        return []
    if rule.get("duty"):
        duties = ", ".join(d.get("action") or "?" for d in rule["duty"])
        plan.gated.append(GatedRule(src, GATE_WORKFLOW, f"conditional on duties ({duties}) — granted through an Agreement"))
        return []
    if rule.get("action_refinement"):
        plan.gated.append(GatedRule(src, GATE_ABAC, "action refinement can't be expressed as a static grant"))
        return []
    start, end, rest = _time_window(rule.get("constraint") or [])
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
            out.append(Entitlement(principal, action, securable, _iso(end), list(advisories), src))
    return out


def _compile_prohibition(rule: Dict[str, Any], src: RuleRef, conflict: str, parties: _Parties, assets: _Assets,
                         now: datetime, plan: EntitlementPlan) -> Optional[_Prohibition]:
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
