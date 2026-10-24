"""Unity Catalog target adapter: Entitlement IR → UC privilege grants (RBAC).

Pure module. Strategy for v1 is plain RBAC: each IR entitlement becomes direct
GRANTs to the principal, plus the implied ``USE CATALOG`` / ``USE SCHEMA`` on the
parents (UC requires them to reach a child securable). ABAC (governed tags, row
filters / column masks) is a later strategy for the rules the compiler gates.

Grants are keyed by ``(principal, securable_type, securable_name, privilege)``.
That key is what the Grant Ledger stores and what release diffs are computed on,
so an implied ``USE CATALOG`` shared by several grants is only revoked once no
desired grant needs it anymore.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.common import odrl
from src.common.odrl_compiler import (
    EVERYONE,
    GATE_UNSUPPORTED,
    SEVERITY_WARNING,
    EntitlementPlan,
    GatedRule,
)

TARGET_UC = "uc"
# UC's built-in group that contains every account user.
UC_EVERYONE_GROUP = "account users"

KIND_CATALOG = "catalog"
KIND_SCHEMA = "schema"
KIND_TABLE = "table"
KIND_VOLUME = "volume"
KIND_FUNCTION = "function"
KIND_MODEL = "model"

# Profile action → UC privileges per securable kind. Missing entries = not expressible.
_READ_CONTAINER = ("SELECT", "READ_VOLUME", "EXECUTE")
PRIVILEGE_MAP: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "read": {
        KIND_CATALOG: ("USE_CATALOG", "USE_SCHEMA") + _READ_CONTAINER,
        KIND_SCHEMA: ("USE_SCHEMA",) + _READ_CONTAINER,
        KIND_TABLE: ("SELECT",),
        KIND_VOLUME: ("READ_VOLUME",),
        KIND_FUNCTION: ("EXECUTE",),
        KIND_MODEL: ("EXECUTE",),
    },
    "modify": {
        KIND_CATALOG: ("USE_CATALOG", "USE_SCHEMA", "MODIFY", "WRITE_VOLUME"),
        KIND_SCHEMA: ("USE_SCHEMA", "MODIFY", "WRITE_VOLUME"),
        KIND_TABLE: ("MODIFY",),
        KIND_VOLUME: ("WRITE_VOLUME",),
    },
    "ontos:browse": {
        KIND_CATALOG: ("BROWSE",),
    },
    "ontos:create": {
        KIND_CATALOG: ("USE_CATALOG", "CREATE_SCHEMA"),
        KIND_SCHEMA: ("USE_SCHEMA", "CREATE_TABLE", "CREATE_VOLUME", "CREATE_FUNCTION", "CREATE_MODEL"),
    },
    "ontos:manage": dict.fromkeys((KIND_CATALOG, KIND_SCHEMA, KIND_TABLE, KIND_VOLUME, KIND_FUNCTION, KIND_MODEL), ("MANAGE",)),
    "use": dict.fromkeys((KIND_CATALOG, KIND_SCHEMA, KIND_TABLE, KIND_VOLUME, KIND_FUNCTION, KIND_MODEL), ("ALL_PRIVILEGES",)),
}

# SQL keyword per securable kind for the runbook.
_SQL_KIND = {KIND_CATALOG: "CATALOG", KIND_SCHEMA: "SCHEMA", KIND_TABLE: "TABLE", KIND_VOLUME: "VOLUME",
             KIND_FUNCTION: "FUNCTION", KIND_MODEL: "MODEL"}

# Resolves the kind of a 3-part name (table/view → "table", volume, function, model).
ObjectKindResolver = Callable[[str], Optional[str]]

GrantKey = Tuple[str, str, str, str]


@dataclass
class UCGrant:
    principal: str  # UC principal name: email, group name, or SP application id
    securable_type: str
    securable_name: str  # catalog[.schema[.object]]
    privilege: str
    expires_at: Optional[str] = None
    implied: bool = False
    sources: List[Dict[str, Any]] = field(default_factory=list)
    # Ledger only: the grant already existed on the platform when Ontos first applied it,
    # so Ontos stops tracking it instead of revoking it.
    preexisting: bool = False

    @property
    def key(self) -> GrantKey:
        return (self.principal, self.securable_type, self.securable_name, self.privilege)

    def to_dict(self) -> Dict[str, Any]:
        out = {"principal": self.principal, "securable_type": self.securable_type,
               "securable_name": self.securable_name, "privilege": self.privilege,
               "expires_at": self.expires_at, "implied": self.implied, "sources": self.sources}
        if self.preexisting:
            out["preexisting"] = True
        return out

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UCGrant":
        return cls(d["principal"], d["securable_type"], d["securable_name"], d["privilege"],
                   d.get("expires_at"), bool(d.get("implied")), list(d.get("sources") or []),
                   bool(d.get("preexisting")))


def uc_principal(typed: str) -> str:
    if typed == EVERYONE:
        return UC_EVERYONE_GROUP
    return typed.split(":", 1)[1] if ":" in typed else typed


def securable_kind(name: str, resolve_object_kind: Optional[ObjectKindResolver] = None) -> str:
    depth = len(name.split("."))
    if depth == 1:
        return KIND_CATALOG
    if depth == 2:
        return KIND_SCHEMA
    kind = resolve_object_kind(name) if resolve_object_kind else None
    return kind if kind in (KIND_TABLE, KIND_VOLUME, KIND_FUNCTION, KIND_MODEL) else KIND_TABLE


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """ISO 8601 (``...Z`` allowed) → aware UTC datetime; None for empty / unparseable."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _merge_expiry(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """Unbounded wins; otherwise the later expiry (compared as instants, not strings)."""
    if a is None or b is None:
        return None
    pa, pb = parse_iso(a), parse_iso(b)
    if pa is None or pb is None:
        return None  # Unparseable expiry: treat as unbounded rather than revoke early.
    return a if pa >= pb else b


def build_grants(plan: EntitlementPlan, resolve_object_kind: Optional[ObjectKindResolver] = None) -> List[UCGrant]:
    """IR → aggregated UC grants (including implied parent USE privileges). Mutates ``plan`` with gated/issues."""
    grants: Dict[GrantKey, UCGrant] = {}

    def add(principal: str, kind: str, name: str, privilege: str, expires: Optional[str], implied: bool,
            source: Optional[Dict[str, Any]]) -> None:
        key = (principal, kind, name, privilege)
        g = grants.get(key)
        if g is None:
            grants[key] = UCGrant(principal, kind, name, privilege, expires, implied, [source] if source else [])
            return
        g.expires_at = _merge_expiry(g.expires_at, expires)
        g.implied = g.implied and implied
        if source and source not in g.sources:
            g.sources.append(source)

    broad_warned = set()
    for e in plan.entitlements:
        name = e.securable[len(odrl.UC_PREFIX):]
        kind = securable_kind(name, resolve_object_kind)
        privileges = PRIVILEGE_MAP.get(e.action, {}).get(kind)
        if not privileges:
            if e.source:
                plan.gated.append(GatedRule(e.source, GATE_UNSUPPORTED,
                                            f"action '{e.action}' has no Unity Catalog privilege on a {kind}"))
            continue
        if e.action == "use" and e.source and e.source.policy_uid not in broad_warned:
            broad_warned.add(e.source.policy_uid)
            plan.issue(SEVERITY_WARNING, "broad_grant",
                       f"{e.source.label()}: 'use' compiles to ALL PRIVILEGES", e.source)
        principal = uc_principal(e.principal)
        src = e.source.to_dict() if e.source else None
        for priv in privileges:
            add(principal, kind, name, priv, e.expires_at, False, src)
        parts = name.split(".")
        if kind != KIND_CATALOG:
            add(principal, KIND_CATALOG, parts[0], "USE_CATALOG", e.expires_at, True, src)
        if len(parts) == 3:
            add(principal, KIND_SCHEMA, ".".join(parts[:2]), "USE_SCHEMA", e.expires_at, True, src)
    # An explicit grant subsumes the same privilege implied elsewhere (already merged by key).
    return sorted(grants.values(), key=lambda g: g.key)


# ------------------------------------------------------------------ diff

@dataclass
class GrantDiff:
    add: List[UCGrant] = field(default_factory=list)
    remove: List[UCGrant] = field(default_factory=list)
    # No longer desired but pre-existing on the platform: dropped from the ledger, never revoked.
    untrack: List[UCGrant] = field(default_factory=list)
    # Same grant, different expiry: ledger-only update, no platform action.
    update: List[UCGrant] = field(default_factory=list)
    unchanged: int = 0

    @property
    def empty(self) -> bool:
        return not (self.add or self.remove or self.update or self.untrack)

    def to_dict(self) -> Dict[str, Any]:
        return {"add": [g.to_dict() for g in self.add], "remove": [g.to_dict() for g in self.remove],
                "update": [g.to_dict() for g in self.update], "untrack": [g.to_dict() for g in self.untrack],
                "unchanged": self.unchanged}


def diff_grants(desired: Iterable[UCGrant], current: Iterable[UCGrant]) -> GrantDiff:
    """Desired state vs. what Ontos believes is applied (the Grant Ledger).

    Never touches unmanaged grants: grants that were already on the platform before
    Ontos applied them (``preexisting``) are only dropped from the ledger.
    """
    want = {g.key: g for g in desired}
    have = {g.key: g for g in current}
    out = GrantDiff()
    for key, g in want.items():
        cur = have.get(key)
        if cur is None:
            out.add.append(g)
        elif cur.expires_at != g.expires_at:
            out.update.append(g)
        else:
            out.unchanged += 1
    gone = [g for key, g in have.items() if key not in want]
    out.remove = [g for g in gone if not g.preexisting]
    out.untrack = [g for g in gone if g.preexisting]
    for lst in (out.add, out.remove, out.update, out.untrack):
        lst.sort(key=lambda g: g.key)
    return out


def group_for_apply(grants: Iterable[UCGrant]) -> List[Dict[str, Any]]:
    """Aggregate per (principal, securable) into ``GrantManager.apply_grant/apply_revoke`` payloads."""
    buckets: Dict[Tuple[str, str, str], List[str]] = {}
    for g in grants:
        buckets.setdefault((g.principal, g.securable_type, g.securable_name), []).append(g.privilege)
    return [{"principal": p, "securable_type": t, "securable_name": n, "privileges": sorted(privs)}
            for (p, t, n), privs in sorted(buckets.items())]


# ------------------------------------------------------------------ live state

def live_diff(managed: Iterable[UCGrant], desired: Iterable[UCGrant],
              live_by_securable: Dict[Tuple[str, str], List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Compare desired grants with live UC grants on the same securables (report-only).

    ``live_by_securable[(type, name)]`` = ``[{"principal", "privileges"}]`` from ``GrantManager.get_grants``.
    """
    def norm(key: GrantKey) -> GrantKey:
        # UC resolves principals case-insensitively and may echo a different case.
        return ((key[0] or "").lower(), key[1], key[2], key[3])

    desired_keys = {norm(g.key) for g in desired}
    managed_keys = {norm(g.key) for g in managed}
    live: set = set()
    for (stype, sname), rows in live_by_securable.items():
        for row in rows or []:
            for priv in row.get("privileges") or []:
                live.add(norm((row.get("principal"), stype, sname, str(priv).upper().replace(" ", "_"))))
    missing = sorted(desired_keys - live)
    unmanaged = sorted(k for k in live - desired_keys if k not in managed_keys)
    stale = sorted(k for k in live & managed_keys if k not in desired_keys)

    def rows(keys: List[GrantKey]) -> List[Dict[str, str]]:
        return [{"principal": p, "securable_type": t, "securable_name": n, "privilege": v} for p, t, n, v in keys]
    return {"missing": rows(missing), "unmanaged": rows(unmanaged), "stale": rows(stale),
            "in_sync": not missing and not stale}


# ------------------------------------------------------------------ runbook

def _quote_name(name: str) -> str:
    return ".".join(f"`{part.replace('`', '``')}`" for part in name.split("."))


def _sql_privilege(priv: str) -> str:
    return priv.replace("_", " ")


def render_sql(diff: GrantDiff) -> List[str]:
    """GRANT / REVOKE statements for the manual runbook and Git artifacts."""
    out: List[str] = []
    for verb, prep, grants in (("REVOKE", "FROM", diff.remove), ("GRANT", "TO", diff.add)):
        for item in group_for_apply(grants):
            privs = ", ".join(_sql_privilege(p) for p in item["privileges"])
            principal = item["principal"].replace("`", "``")
            out.append(f"{verb} {privs} ON {_SQL_KIND[item['securable_type']]} "
                       f"{_quote_name(item['securable_name'])} {prep} `{principal}`;")
    return out


def read_live_grants(securables: Iterable[Tuple[str, str]], get_grants: Callable[[str, str], Dict[str, Any]],
                     max_workers: int = 8) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """``get_grants`` for many securables in parallel (SDK calls are I/O-bound). Errors become failed results."""
    from concurrent.futures import ThreadPoolExecutor

    items = list(securables)

    def one(item: Tuple[str, str]) -> Dict[str, Any]:
        try:
            return get_grants(*item) or {}
        except Exception as e:  # pragma: no cover - platform read is best-effort
            return {"success": False, "error": type(e).__name__}

    if not items:
        return {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        return dict(zip(items, pool.map(one, items)))
