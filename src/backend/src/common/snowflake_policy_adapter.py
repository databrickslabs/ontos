"""Snowflake target adapter: Entitlement IR → Snowflake role grants (RBAC). Pure module.

Snowflake grants object privileges to *roles* only, and a grant on a container does
not reach its children. The adapter bridges both, as an implementation detail of
the target (Lars, 2026-10-17: "joint groups are an adapter detail"):

* **Principals → roles.** ``group:X`` → the role ``X`` (SCIM provisioning creates a
  role per IdP group with the group's name); everyone → ``PUBLIC``; a user or
  service principal gets a derived role ``ONTOS_U_<hash>`` per target that Ontos creates and
  grants to that user. Role memberships are ledger rows (securable_type ``role``)
  like any grant, so they are diffed, revoked and expire the same way.
* **Containers → ALL + FUTURE grants.** ``read`` on a schema becomes SELECT on all
  existing and future tables and views in it (database: in every schema), plus the
  ``USAGE`` on the parents a role needs to reach them.

Identifiers are rendered upper-cased and double-quoted: that is how Snowflake stores
unquoted names, and quoting keeps every name safe in SQL. Mixed-case (quoted) object
names aren't supported — Ontos refs are case-insensitive.

No Direct delivery: there's no Snowflake connection in Ontos yet, so releases ship
Indirect (Git, for the customer's CI) or Manual (runbook).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from src.common import odrl
from src.common import uc_policy_adapter as uc
from src.common.odrl_compiler import (
    EVERYONE,
    GATE_UNSUPPORTED,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    EntitlementPlan,
    GatedRule,
)
from src.common.policy_targets import TargetAdapter

SYSTEM = "snowflake"
PUBLIC_ROLE = "PUBLIC"
DERIVED_ROLE_PREFIX = "ONTOS_U_"

KIND_DATABASE = "database"
KIND_SCHEMA = "schema"
KIND_TABLE = "table"
KIND_VIEW = "view"
KIND_ROLE = "role"  # role membership rows: principal = user, securable_name = role
PRIV_MEMBER = "MEMBER"

# Bulk securables: "<scope kind>:<object plural>:<all|future>", e.g. schema:tables:future on db.s.
_PLURALS = ("tables", "views")

_READ = {
    KIND_TABLE: [("table", "SELECT")],
    KIND_SCHEMA: [(f"schema:{p}:{w}", "SELECT") for p in _PLURALS for w in ("all", "future")],
    KIND_DATABASE: [(f"database:{p}:{w}", "SELECT") for p in _PLURALS for w in ("all", "future")],
}
_WRITE_PRIVS = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
PRIVILEGE_MAP: Dict[str, Dict[str, List[Tuple[str, str]]]] = {
    "read": {**_READ, KIND_VIEW: [("view", "SELECT")]},
    "modify": {
        KIND_TABLE: [("table", p) for p in _WRITE_PRIVS],
        KIND_SCHEMA: [(f"schema:tables:{w}", p) for w in ("all", "future") for p in _WRITE_PRIVS],
        KIND_DATABASE: [(f"database:tables:{w}", p) for w in ("all", "future") for p in _WRITE_PRIVS],
    },
    "ontos:create": {
        KIND_SCHEMA: [("schema", "CREATE TABLE"), ("schema", "CREATE VIEW")],
        KIND_DATABASE: [("database", "CREATE SCHEMA")],
    },
    "use": {
        KIND_TABLE: [("table", "ALL PRIVILEGES")],
        KIND_VIEW: [("view", "ALL PRIVILEGES")],
    },
}


def _kind(name: str) -> str:
    return {1: KIND_DATABASE, 2: KIND_SCHEMA}.get(len(name.split(".")), KIND_TABLE)


def ident(name: str) -> str:
    """``main.sales`` → ``"MAIN"."SALES"`` (how Snowflake stores unquoted names; always safe to quote)."""
    return ".".join('"' + part.upper().replace('"', '""') + '"' for part in name.split("."))


def derived_role(principal: str, target_key: str = "") -> str:
    """One role per (user, target): targets with disjoint scopes never share (or revoke) a membership."""
    seed = f"{target_key}|{odrl.strip_principal_prefix(principal)}"
    return DERIVED_ROLE_PREFIX + hashlib.sha1(seed.encode()).hexdigest()[:10].upper()


def role_for(principal: str, target_key: str = "") -> Tuple[str, Optional[str]]:
    """(role that receives the grants, user to grant the role to — None for groups / PUBLIC)."""
    if principal == EVERYONE:
        return PUBLIC_ROLE, None
    low = principal.lower()
    if low.startswith("group:"):
        return principal.split(":", 1)[1].upper(), None
    user = principal.split(":", 1)[1] if ":" in principal else principal
    return derived_role(principal, target_key), user


def _on_clause(securable_type: str, name: str) -> str:
    if securable_type in (KIND_TABLE, KIND_VIEW, KIND_SCHEMA, KIND_DATABASE):
        return f"{securable_type.upper()} {ident(name)}"
    scope, plural, which = securable_type.split(":")
    bulk = "ALL" if which == "all" else "FUTURE"
    return f"{bulk} {plural.upper()} IN {scope.upper()} {ident(name)}"


class SnowflakeAdapter(TargetAdapter):
    system = SYSTEM
    label = "Snowflake"
    asset_prefix = odrl.SNOWFLAKE_PREFIX
    capabilities = frozenset()  # no Direct apply / live read / ABAC yet
    implied_privileges = ("USAGE",)

    def scope_name(self, grant: uc.UCGrant) -> Optional[str]:
        # A membership in this target's own derived role belongs to this target.
        return None if grant.securable_type == KIND_ROLE else grant.securable_name

    def assume_preexisting(self, grant: uc.UCGrant) -> bool:
        # Only plain USAGE for a group / PUBLIC role is plausibly granted outside Ontos; bulk
        # (ALL / FUTURE) grants and anything on an Ontos-derived role are Ontos-made → revocable.
        return (grant.implied and grant.securable_type in (KIND_DATABASE, KIND_SCHEMA)
                and not grant.principal.startswith(DERIVED_ROLE_PREFIX))

    def build(self, plan: EntitlementPlan, abac: Any, resolve_object_kind: Any = None,
              target: Any = None) -> List[uc.UCGrant]:
        for rule in plan.abac:
            # A mask stands in for a denial, a row filter narrows a grant: dropping either fails open.
            plan.issue(SEVERITY_ERROR, "abac_unsupported_target",
                       f"{rule.source.label() if rule.source else rule.kind}: Snowflake targets can't enforce "
                       f"{rule.kind.replace('_', ' ')}s yet", rule.source)
        key = target.key if target is not None else ""
        connection = (target.connection if target is not None else None) or {}
        views = {str(v).strip().lower() for v in connection.get("views") or []}
        acc = uc.GrantAccumulator()
        add = acc.add
        for e in plan.entitlements:
            name = self.native_name(e.securable)
            kind = KIND_VIEW if name in views else _kind(name)
            privileges = PRIVILEGE_MAP.get(e.action, {}).get(kind)
            if not privileges:
                if e.source:
                    plan.gated.append(GatedRule(e.source, GATE_UNSUPPORTED,
                                                f"action '{e.action}' has no Snowflake privilege on a {kind}"))
                continue
            role, user = role_for(e.principal, key)
            src = e.source.to_dict() if e.source else None
            for stype, priv in privileges:
                add(role, stype, name, priv, e.expires_at, False, src)
            parts = name.split(".")
            add(role, KIND_DATABASE, parts[0], "USAGE", e.expires_at, True, src)
            if len(parts) >= 2:
                add(role, KIND_SCHEMA, ".".join(parts[:2]), "USAGE", e.expires_at, True, src)
            else:
                # A database grant reaches tables in every schema: the role needs USAGE on all of them.
                add(role, "database:schemas:all", parts[0], "USAGE", e.expires_at, True, src)
                add(role, "database:schemas:future", parts[0], "USAGE", e.expires_at, True, src)
            if user:
                # Explicit, not implied: Ontos made the derived role, so the membership is revoked with it.
                add(user, KIND_ROLE, role, PRIV_MEMBER, e.expires_at, False, src)
        self._future_precedence(acc, plan)
        if any(_kind(self.native_name(e.securable)) == KIND_TABLE and self.native_name(e.securable) not in views
               for e in plan.entitlements):
            plan.issue(SEVERITY_INFO, "snowflake_objects_as_tables",
                       "Snowflake objects are granted as tables; list views in the target's connection "
                       "('views') so they are granted ON VIEW")
        return acc.sorted()

    @staticmethod
    def _future_precedence(acc: uc.GrantAccumulator, plan: EntitlementPlan) -> None:
        """Schema-level FUTURE grants override database-level ones for that schema (Snowflake rule):
        repeat each database-level future grant on the schemas that have their own."""
        schema_future = {(n, t.split(":")[1]) for (_, t, n, _) in acc.grants if t.startswith("schema:") and t.endswith(":future")}
        copied = 0
        for g in list(acc.grants.values()):
            if not (g.securable_type.startswith("database:") and g.securable_type.endswith(":future")):
                continue
            plural = g.securable_type.split(":")[1]
            if plural == "schemas":
                continue
            for schema, p in schema_future:
                if p == plural and schema.split(".")[0] == g.securable_name:
                    for s in g.sources or [None]:
                        acc.add(g.principal, f"schema:{plural}:future", schema, g.privilege, g.expires_at, False, s)
                    copied += 1
        if copied:
            plan.issue(SEVERITY_INFO, "snowflake_future_precedence",
                       f"{copied} database-level future grant(s) repeated on schemas with their own future grants "
                       "(Snowflake applies only the schema-level ones there)")

    def render_sql(self, diff: uc.GrantDiff) -> List[str]:
        """Runbook / CI script, fail-safe order: memberships off, revokes, roles, grants, memberships on."""
        out: List[str] = []
        members_off = [g for g in diff.remove if g.securable_type == KIND_ROLE]
        members_on = [g for g in diff.add if g.securable_type == KIND_ROLE]
        out += [f"REVOKE ROLE {ident(g.securable_name)} FROM USER {ident_user(g.principal)};" for g in members_off]
        for verb, prep, grants in (("REVOKE", "FROM", diff.remove), ("GRANT", "TO", diff.add)):
            objects = [g for g in grants if g.securable_type != KIND_ROLE]
            if verb == "GRANT":
                derived = sorted({g.principal for g in objects if g.principal.startswith(DERIVED_ROLE_PREFIX)})
                out += [f"CREATE ROLE IF NOT EXISTS {ident(r)};" for r in derived]
            for item in uc.group_for_apply(objects):
                privs = ", ".join(item["privileges"])
                out.append(f"{verb} {privs} ON {_on_clause(item['securable_type'], item['securable_name'])} "
                           f"{prep} ROLE {ident(item['principal'])};")
        out += [f"GRANT ROLE {ident(g.securable_name)} TO USER {ident_user(g.principal)};" for g in members_on]
        return out


def ident_user(login: str) -> str:
    """A user name, quoted and upper-cased like an unquoted identifier (Ontos principals are lower-cased).

    Unverified assumption: SCIM-provisioned users carry the upper-cased e-mail as their name.
    """
    return '"' + login.upper().replace('"', '""') + '"'
