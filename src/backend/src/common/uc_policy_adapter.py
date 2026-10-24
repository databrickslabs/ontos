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
    SEVERITY_ERROR,
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
    # ABAC policies (securable_type == ABAC_POLICY): the policy definition to create.
    spec: Optional[Dict[str, Any]] = None

    @property
    def key(self) -> GrantKey:
        return (self.principal, self.securable_type, self.securable_name, self.privilege)

    def to_dict(self) -> Dict[str, Any]:
        out = {"principal": self.principal, "securable_type": self.securable_type,
               "securable_name": self.securable_name, "privilege": self.privilege,
               "expires_at": self.expires_at, "implied": self.implied, "sources": self.sources}
        if self.preexisting:
            out["preexisting"] = True
        if self.spec:
            out["spec"] = self.spec
        return out

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UCGrant":
        return cls(d["principal"], d["securable_type"], d["securable_name"], d["privilege"],
                   d.get("expires_at"), bool(d.get("implied")), list(d.get("sources") or []),
                   bool(d.get("preexisting")), d.get("spec"))


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


class GrantAccumulator:
    """Merges grants by key across entitlements (shared by every target adapter).

    The same grant from several rules keeps the latest expiry, stays ``implied`` only if every
    contribution was implied, and lists each source once.
    """

    def __init__(self) -> None:
        self.grants: Dict[GrantKey, UCGrant] = {}

    def add(self, principal: str, kind: str, name: str, privilege: str, expires: Optional[str], implied: bool,
            source: Optional[Dict[str, Any]]) -> None:
        key = (principal, kind, name, privilege)
        g = self.grants.get(key)
        if g is None:
            self.grants[key] = UCGrant(principal, kind, name, privilege, expires, implied, [source] if source else [])
            return
        g.expires_at = _merge_expiry(g.expires_at, expires)
        g.implied = g.implied and implied
        if source and source not in g.sources:
            g.sources.append(source)

    def sorted(self) -> List[UCGrant]:
        return sorted(self.grants.values(), key=lambda g: g.key)


def build_grants(plan: EntitlementPlan, resolve_object_kind: Optional[ObjectKindResolver] = None) -> List[UCGrant]:
    """IR → aggregated UC grants (including implied parent USE privileges). Mutates ``plan`` with gated/issues."""
    acc = GrantAccumulator()
    add = acc.add

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
    return acc.sorted()


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
        if g.securable_type == ABAC_POLICY:
            continue
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

    # ABAC policies aren't visible through grants; only grants are compared here.
    desired_keys = {norm(g.key) for g in desired if g.securable_type != ABAC_POLICY}
    managed_keys = {norm(g.key) for g in managed if g.securable_type != ABAC_POLICY}
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
    """CREATE POLICY / GRANT / REVOKE / DROP POLICY statements for the runbook and Git artifacts.

    Order is fail-safe: new restrictions (masks, filters) first, then revokes, grants, and only
    then dropping restrictions that are no longer wanted.
    """
    out: List[str] = [abac_create_sql(g.spec) for g in diff.add if g.securable_type == ABAC_POLICY and g.spec]
    for verb, prep, grants in (("REVOKE", "FROM", diff.remove), ("GRANT", "TO", diff.add)):
        for item in group_for_apply(grants):
            privs = ", ".join(_sql_privilege(p) for p in item["privileges"])
            principal = item["principal"].replace("`", "``")
            out.append(f"{verb} {privs} ON {_SQL_KIND[item['securable_type']]} "
                       f"{_quote_name(item['securable_name'])} {prep} `{principal}`;")
    out.extend(abac_drop_sql(abac_ref(g)) for g in diff.remove if g.securable_type == ABAC_POLICY)
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


# ------------------------------------------------------------------ ABAC (row filters, column masks)

ABAC_POLICY = "abac_policy"
ABAC_PRINCIPAL = "(abac)"
_ABAC_ON = {KIND_CATALOG: "CATALOG", KIND_SCHEMA: "SCHEMA", KIND_TABLE: "TABLE"}


def _column_condition(tag_key: str, tag_value: Optional[str]) -> str:
    esc = lambda v: v.replace("'", "''")  # noqa: E731
    return f"has_tag_value('{esc(tag_key)}', '{esc(tag_value)}')" if tag_value else f"has_tag('{esc(tag_key)}')"


def build_abac(plan: EntitlementPlan, abac: Any,
               resolve_object_kind: Optional[ObjectKindResolver] = None) -> List[UCGrant]:
    """IR ABAC rules → one UC ABAC policy per (rule, securable), as ledger-shaped rows.

    Names are deterministic over the definition, so a changed rule is a new policy (old one
    dropped) and an unchanged one is left alone.
    """
    import hashlib
    import json

    rows: Dict[GrantKey, UCGrant] = {}
    for rule in plan.abac:
        function = abac.mask_function if rule.kind == "column_mask" else abac.row_filter_function
        principals = sorted({uc_principal(p) for p in rule.principals})
        if not function or not principals:
            continue
        for securable in rule.securables:
            name = securable[len(odrl.UC_PREFIX):]
            kind = securable_kind(name, resolve_object_kind)
            if kind not in _ABAC_ON:
                # The rule relied on this restriction (a mask replaced a deny, a filter narrows a
                # grant): not being able to build it must block the release, never fail open.
                plan.issue(SEVERITY_ERROR, "abac_unsupported_target",
                           f"{rule.source.label() if rule.source else rule.kind}: ABAC policies apply to "
                           f"tables, not to a {kind} ({name})", rule.source)
                continue
            on_type = _ABAC_ON[kind]
            spec: Dict[str, Any] = {
                "kind": rule.kind, "on_securable_type": on_type, "on_securable_fullname": name,
                "to_principals": principals, "function_name": function,
                "match_condition": _column_condition(rule.tag_key or abac.spatial_tag, rule.tag_value),
                "alias": "c",
            }
            if rule.kind == "row_filter":
                spec["using"] = [{"alias": "c"}, {"constant": rule.value}]
            else:
                spec["using"] = []
            digest = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
            spec["name"] = f"ontos_{rule.kind}_{digest}"
            spec["comment"] = f"Ontos Access Policies: {rule.source.label() if rule.source else rule.kind}"
            row = UCGrant(ABAC_PRINCIPAL, ABAC_POLICY, f"{on_type}:{name}:{spec['name']}", rule.kind.upper(),
                          None, False, [rule.source.to_dict()] if rule.source else [], False, spec)
            existing = rows.get(row.key)
            if existing and rule.source and rule.source.to_dict() not in existing.sources:
                existing.sources.append(rule.source.to_dict())
            else:
                rows.setdefault(row.key, row)
    return sorted(rows.values(), key=lambda g: g.key)


def abac_ref(g: UCGrant) -> Dict[str, str]:
    """What identifies an ABAC policy for dropping it: (on type, on name, policy name)."""
    on_type, rest = g.securable_name.split(":", 1)
    on_name, _, name = rest.rpartition(":")
    return {"on_securable_type": on_type, "on_securable_fullname": on_name, "name": name}


def abac_create_sql(spec: Dict[str, Any]) -> str:
    to = ", ".join(f"`{p.replace('`', '``')}`" for p in spec["to_principals"])
    on = f"{spec['on_securable_type']} {_quote_name(spec['on_securable_fullname'])}"
    comment = spec.get("comment", "").replace("'", "''")
    if spec["kind"] == "column_mask":
        body = (f"COLUMN MASK {_quote_name(spec['function_name'])} TO {to} FOR TABLES "
                f"MATCH COLUMNS {spec['match_condition']} AS c ON COLUMN c")
    else:
        value = str(spec["using"][1]["constant"]).replace("'", "''")
        body = (f"ROW FILTER {_quote_name(spec['function_name'])} TO {to} FOR TABLES "
                f"MATCH COLUMNS {spec['match_condition']} AS c USING COLUMNS (c, '{value}')")
    return f"CREATE POLICY `{spec['name']}` ON {on} COMMENT '{comment}' {body};"


def abac_drop_sql(ref: Dict[str, str]) -> str:
    return (f"DROP POLICY `{ref['name']}` ON {ref['on_securable_type']} "
            f"{_quote_name(ref['on_securable_fullname'])};")
