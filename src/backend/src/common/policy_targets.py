"""Target adapter registry: which platforms Access Policies compile to (Phase 4).

An *adapter* turns the platform-neutral Entitlement IR (``odrl_compiler``) into one
platform's grants, runbook and apply payloads. A *target* is a configured place to
ship to — a governed Access Target entity (system + scope + allowed Delivery Modes +
reconcile schedule), or the built-in ``uc`` target while no Unity Catalog target is
configured. Releases and Grant Ledger rows are keyed by the target ``key``.

Scope is a list of securable prefixes (``main`` / ``main.sales``) the target manages;
empty means everything of its system. Two active targets of one system may not
overlap — a securable has exactly one target that tracks and revokes its grants.

Pure module: no DB, no SDK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence

from src.common import odrl
from src.common import uc_policy_adapter as uc
from src.common.odrl_compiler import SEVERITY_ERROR, SEVERITY_WARNING, EntitlementPlan

CAP_APPLY_GRANTS = "apply_grants"
CAP_READ_GRANTS = "read_grants"
CAP_ABAC = "abac"

# Parent privileges that only exist to reach a child securable.
IMPLIED_PRIVILEGES = ("USE_CATALOG", "USE_SCHEMA")

DRIFT_REPORT = "report"
DRIFT_POLICIES = (DRIFT_REPORT,)


def inside(name: str, prefix: str) -> bool:
    """``main.sales.orders`` is inside ``main.sales`` (segment-wise, case-insensitive)."""
    n, p = name.lower(), prefix.lower()
    return n == p or n.startswith(p + ".")


def normalize_scope(scope: Optional[Iterable[str]]) -> List[str]:
    out: List[str] = []
    for s in scope or []:
        s = (s or "").strip().lower().rstrip(".")
        if s.endswith(".*"):
            s = s[:-2]
        if s and s not in out:
            out.append(s)
    return out


def scopes_overlap(a: Sequence[str], b: Sequence[str]) -> bool:
    """Do two scopes share a securable? Empty = everything."""
    if not a or not b:
        return True
    return any(inside(x, y) or inside(y, x) for x in a for y in b)


class TargetAdapter:
    """One platform. Subclasses override the hooks; the release pipeline is shared."""

    system: str = ""
    label: str = ""
    asset_prefix: str = ""
    capabilities: FrozenSet[str] = frozenset()
    # Max segments of a securable name (catalog.schema.object = 3).
    name_depth: int = 3
    # Parent privileges that only exist to reach a child securable.
    implied_privileges: tuple = IMPLIED_PRIVILEGES

    def owns(self, ref: str) -> bool:
        return isinstance(ref, str) and ref.startswith(self.asset_prefix)

    def native_name(self, ref: str) -> str:
        return ref[len(self.asset_prefix):] if self.owns(ref) else ref

    def scope_problems(self, scope: Sequence[str]) -> List[str]:
        bad = [s for s in scope if not 1 <= len(s.split(".")) <= self.name_depth or "" in s.split(".")]
        return [f"Scope entry '{s}' is not a {self.label} securable name" for s in bad]

    def own_plan(self, plan: EntitlementPlan) -> None:
        """Keep only this platform's IR (in place): the compile covers every platform's refs."""
        plan.entitlements = [e for e in plan.entitlements if self.owns(e.securable)]
        kept = []
        for rule in plan.abac:
            rule.securables = [s for s in rule.securables if self.owns(s)]
            if rule.securables:
                kept.append(rule)
        plan.abac = kept

    def restrict_plan(self, plan: EntitlementPlan, scope: Sequence[str]) -> int:
        """Drop IR outside ``scope`` (in place); returns how many entitlements were dropped.

        A restriction (mask / filter) attached above the scope can't be built without managing
        securables this target doesn't own; it blocks the release instead of silently vanishing.
        """
        self.own_plan(plan)
        if not scope:
            return 0
        before = len(plan.entitlements)
        plan.entitlements = [e for e in plan.entitlements
                             if any(inside(self.native_name(e.securable), s) for s in scope)]
        kept = []
        for rule in plan.abac:
            names = [self.native_name(s) for s in rule.securables]
            above = [n for n in names if not any(inside(n, s) for s in scope) and any(inside(s, n) for s in scope)]
            if above:
                plan.issue(SEVERITY_ERROR, "abac_outside_scope",
                           f"{rule.source.label() if rule.source else rule.kind}: restriction on {', '.join(above)} "
                           f"reaches beyond this target's scope ({', '.join(scope)})", rule.source)
            rule.securables = [s for s, n in zip(rule.securables, names, strict=True) if any(inside(n, p) for p in scope)]
            if rule.securables:
                kept.append(rule)
        plan.abac = kept
        return before - len(plan.entitlements)

    def scope_name(self, grant: uc.UCGrant) -> Optional[str]:
        """The securable a ledger row is about, for scope checks (None = always in scope)."""
        return grant.securable_name

    def grant_in_scope(self, grant: uc.UCGrant, scope: Sequence[str]) -> bool:
        name = self.scope_name(grant)
        if not scope or name is None:
            return True
        if any(inside(name, s) for s in scope):
            return True
        # A parent privilege that only reaches an in-scope child (USE CATALOG / USAGE).
        return grant.privilege in self.implied_privileges and any(inside(s, name) for s in scope)

    def assume_preexisting(self, grant: uc.UCGrant) -> bool:
        """Without a live read: does a grant to add probably exist already (→ never revoked later)?"""
        return grant.implied

    # ---- hooks
    def build(self, plan: EntitlementPlan, abac: Any, resolve_object_kind: Any = None,
              target: Optional["ResolvedTarget"] = None) -> List[uc.UCGrant]:
        raise NotImplementedError

    def render_sql(self, diff: uc.GrantDiff) -> List[str]:
        raise NotImplementedError

    def describe(self) -> Dict[str, Any]:
        return {"system": self.system, "label": self.label, "asset_prefix": self.asset_prefix,
                "capabilities": sorted(self.capabilities)}


class UnityCatalogAdapter(TargetAdapter):
    system = uc.TARGET_UC
    label = "Unity Catalog"
    asset_prefix = odrl.UC_PREFIX
    capabilities = frozenset({CAP_APPLY_GRANTS, CAP_READ_GRANTS, CAP_ABAC})

    def scope_name(self, grant: uc.UCGrant) -> Optional[str]:
        if grant.securable_type == uc.ABAC_POLICY:
            return uc.abac_ref(grant)["on_securable_fullname"]
        return grant.securable_name

    def build(self, plan: EntitlementPlan, abac: Any, resolve_object_kind: Any = None,
              target: Optional["ResolvedTarget"] = None) -> List[uc.UCGrant]:
        return uc.build_grants(plan, resolve_object_kind) + uc.build_abac(plan, abac, resolve_object_kind)

    def render_sql(self, diff: uc.GrantDiff) -> List[str]:
        return uc.render_sql(diff)


_ADAPTERS: Dict[str, TargetAdapter] = {}


def register_adapter(adapter: TargetAdapter) -> TargetAdapter:
    _ADAPTERS[adapter.system] = adapter
    return adapter


def get_adapter(system: str) -> Optional[TargetAdapter]:
    _ensure_builtin_adapters()
    return _ADAPTERS.get(system)


def adapters() -> List[TargetAdapter]:
    _ensure_builtin_adapters()
    return [_ADAPTERS[k] for k in sorted(_ADAPTERS)]


def adapter_for_ref(ref: str) -> Optional[TargetAdapter]:
    return next((a for a in adapters() if a.owns(ref)), None)


register_adapter(UnityCatalogAdapter())
_builtins_loaded = False


def _ensure_builtin_adapters() -> None:
    """Register the adapters living in their own modules — lazily, so they can import this one."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    from src.common.snowflake_policy_adapter import SnowflakeAdapter
    if SnowflakeAdapter.system not in _ADAPTERS:
        register_adapter(SnowflakeAdapter())


@dataclass
class ResolvedTarget:
    """A target releases can compile for: an active Access Target, or the built-in default."""
    key: str
    label: str
    adapter: TargetAdapter
    scope: List[str] = field(default_factory=list)
    # Allowed Delivery Modes (values); empty = whatever is enabled in Settings.
    delivery_modes: List[str] = field(default_factory=list)
    reconcile_schedule: Optional[str] = None
    drift_policy: str = DRIFT_REPORT
    entity_id: Optional[str] = None
    builtin: bool = False
    # Non-secret adapter settings (e.g. Snowflake ``views``: object names to grant as views).
    connection: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "label": self.label, "system": self.adapter.system,
                "system_label": self.adapter.label, "scope": list(self.scope),
                "delivery_modes": list(self.delivery_modes), "reconcile_schedule": self.reconcile_schedule,
                "drift_policy": self.drift_policy, "entity_id": self.entity_id, "builtin": self.builtin,
                "capabilities": sorted(self.adapter.capabilities)}


BUILTIN_UC = ResolvedTarget(key=uc.TARGET_UC, label="Unity Catalog", adapter=_ADAPTERS[uc.TARGET_UC], builtin=True)


def cron_problem(expr: Optional[str]) -> Optional[str]:
    """Quartz (Databricks jobs) or 5-field cron — structural check only."""
    if not expr:
        return None
    parts = expr.split()
    if len(parts) not in (5, 6, 7):
        return f"'{expr}' is not a cron expression (expected 5–7 fields)"
    return None


def restrict(plan: EntitlementPlan, target: ResolvedTarget) -> None:
    """Apply ``target``'s scope to ``plan`` and note what was left to other targets."""
    dropped = target.adapter.restrict_plan(plan, target.scope)
    if dropped:
        plan.issue(SEVERITY_WARNING, "outside_scope",
                   f"{dropped} entitlement(s) are outside this target's scope ({', '.join(target.scope)}) "
                   "and ship with the target that covers them")
