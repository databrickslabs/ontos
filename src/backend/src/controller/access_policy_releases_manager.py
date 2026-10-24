"""Access Policy releases: compile → review → deliver → track (Phase 2).

A release is the compiled desired state of *all active* Access Policies for one
target, plus its diff against the Grant Ledger. It is reviewed like any other
governed artifact (separation of duties on approval), then shipped through the
Ontos Delivery Modes the admin picks:

* **Direct** — ``GrantManager`` applies GRANT/REVOKE via the SDK; per-item
  success is written to the ledger and a fully applied release is ``applied``.
* **Indirect** — Ontos YAML in the Git repo (``AccessPolicyReleaseFileModel``).
* **Manual** — an admin notification with a SQL runbook.

Indirect / Manual releases stay ``delivered`` until an admin confirms they were
applied; only then does the ledger change. *Applying* grants and *tracking*
them are separate: the ledger is what drives time-bound (GDPR) revocation —
:meth:`PolicyReleaseManager.revoke_expired` ships expired grants as a revocation
release through the same Delivery Modes.
"""
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.common import policy_targets as pt
from src.common import uc_policy_adapter as uc
from src.common.logging import get_logger
from src.common.odrl_compiler import PolicyInput, compile_policies
from src.controller.access_policies_manager import (
    KIND_ASSET_COLLECTION,
    KIND_AUDIENCE,
    KIND_POLICY,
    KIND_TARGET,
    STATUS_ACTIVE,
    STATUS_DEPRECATED,
    STATUS_NEEDS_REVIEW,
    AccessPoliciesManager,
    AccessPolicyError,
    log_timeline,
)
from src.db_models.access_policies import (
    ENTITY_TYPE_RELEASE,
    AccessGrantLedgerDb,
    AccessPolicyReleaseDb,
)
from src.repositories.access_policies_repository import repo_for

logger = get_logger(__name__)

# Default target while no Unity Catalog Access Target is configured.
TARGETS = (pt.BUILTIN_UC.key,)

KIND_POLICY_RELEASE = "policy"
KIND_REVOCATION = "revocation"
KIND_AGREEMENT = "agreement"

R_DRAFT = "draft"
R_UNDER_REVIEW = "under_review"
R_APPROVED = "approved"
R_DELIVERED = "delivered"
R_APPLIED = "applied"
R_FAILED = "failed"
R_SUPERSEDED = "superseded"
R_DISCARDED = "discarded"

# Transitions reachable through change_status; delivered/applied/failed are set by deliver()/confirm_applied().
RELEASE_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    R_DRAFT: (R_UNDER_REVIEW, R_DISCARDED),
    R_UNDER_REVIEW: (R_APPROVED, R_DRAFT),
    R_APPROVED: (R_DRAFT, R_DISCARDED),
    # A delivered release that was never applied (CI didn't run, runbook rejected) can be discarded.
    R_DELIVERED: (R_DISCARDED,),
    R_FAILED: (R_DISCARDED,),
    R_APPLIED: (),
    R_SUPERSEDED: (),
    R_DISCARDED: (),
}
OPEN_STATUSES = (R_DRAFT, R_UNDER_REVIEW, R_APPROVED, R_DELIVERED, R_FAILED)
# Applying a release makes these stale (they were diffed against an older ledger). Delivered
# releases are not among them: their artifact may still be applied (CI, runbook) and must stay
# confirmable so the ledger learns about it.
SUPERSEDABLE_STATUSES = (R_DRAFT, R_UNDER_REVIEW, R_APPROVED, R_FAILED)
DELIVERABLE_STATUSES = (R_APPROVED, R_DELIVERED, R_FAILED)

LEDGER_ACTIVE = "active"
LEDGER_REVOKED = "revoked"
# Pre-existing platform grant no longer desired: Ontos stops tracking it but never revokes it.
LEDGER_RELEASED = "released"

LIVE_DIFF_MAX_SECURABLES = 200


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ledger_grant(row: AccessGrantLedgerDb) -> uc.UCGrant:
    return uc.UCGrant(row.principal, row.securable_type, row.securable_name, row.privilege,
                      row.expires_at, bool(row.implied), list(row.sources or []), bool(row.preexisting),
                      row.spec)


def _key(row: Any) -> uc.GrantKey:
    return (row.principal, row.securable_type, row.securable_name, row.privilege)


def abac_config() -> Any:
    """UC ABAC strategies enabled by configuration (off unless the UDFs are configured)."""
    from src.common.config import get_settings
    from src.common.odrl_compiler import AbacConfig

    st = get_settings()
    row_filter = getattr(st, "ACCESS_POLICIES_ABAC_ROW_FILTER_FUNCTION", None) or None
    return AbacConfig(mask_function=getattr(st, "ACCESS_POLICIES_ABAC_MASK_FUNCTION", None) or None,
                      row_filter_function=row_filter,
                      spatial_tag=getattr(st, "ACCESS_POLICIES_SPATIAL_COLUMN_TAG", None) or "region",
                      has_tagged_column=column_tag_checker(st) if row_filter else None)


def column_tag_checker(settings: Any) -> Any:
    """table -> has a column with the tag? via information_schema on the configured warehouse.

    None (can't tell) when no workspace client / warehouse is available; callers fail closed.
    """
    cache: Dict[Tuple[str, str], Optional[bool]] = {}

    def check(table: str, tag: str) -> Optional[bool]:
        if (table, tag) in cache:
            return cache[(table, tag)]
        verdict: Optional[bool] = None
        try:
            from databricks.sdk.service.sql import StatementParameterListItem

            from src.controller.grant_manager import get_grant_manager
            ws = get_grant_manager().workspace_client
            warehouse = getattr(settings, "DATABRICKS_WAREHOUSE_ID", None)
            if ws and warehouse:
                catalog, schema, name = table.split(".")
                res = ws.statement_execution.execute_statement(
                    statement=(f"SELECT count(*) FROM `{catalog.replace('`', '``')}`.information_schema.column_tags "
                               "WHERE schema_name = :s AND table_name = :t AND tag_name = :g"),
                    warehouse_id=warehouse, wait_timeout="30s",
                    parameters=[StatementParameterListItem(name="s", value=schema),
                                StatementParameterListItem(name="t", value=name),
                                StatementParameterListItem(name="g", value=tag)])
                rows = (res.result.data_array if res and res.result else None) or []
                verdict = bool(rows) and int(rows[0][0]) > 0
        except Exception as e:  # can't tell → fail closed upstream
            logger.warning("Column tag check for %s failed: %s", table, e)
        cache[(table, tag)] = verdict
        return verdict
    return check


class PolicyReleaseManager:
    def __init__(self, policies: Optional[AccessPoliciesManager] = None):
        self.policies = policies or AccessPoliciesManager()

    # ------------------------------------------------------------ helpers

    @staticmethod
    def targets(db: Session, *, include_deprecated: bool = False) -> List[pt.ResolvedTarget]:
        """Configured targets (active Access Targets) plus the built-in UC one while no UC target is active.

        ``include_deprecated`` adds targets whose families are only deprecated: they take no new
        compiles but must still deliver pending releases and revoke what they track.
        """
        live = (STATUS_ACTIVE, STATUS_NEEDS_REVIEW)
        rows = [t for t in repo_for(KIND_TARGET).list_all(db) if t.status in live + (STATUS_DEPRECATED,)]
        by_key: Dict[str, Any] = {}
        for t in rows:
            if t.status in live or include_deprecated:
                cur = by_key.get(t.key)
                if cur is None or (cur.status not in live and t.status in live):
                    by_key[t.key] = t
        out: List[pt.ResolvedTarget] = []
        for key in sorted(by_key):
            t = by_key[key]
            adapter = pt.get_adapter(t.system)
            if adapter is None:
                logger.warning("Access target %s uses unknown system %s — skipped", key, t.system)
                continue
            out.append(pt.ResolvedTarget(
                key=key, label=t.name, adapter=adapter, scope=list(t.scope or []),
                delivery_modes=list(t.delivery_modes or []), reconcile_schedule=t.reconcile_schedule,
                drift_policy=t.drift_policy or pt.DRIFT_REPORT, entity_id=t.id))
        # The unscoped built-in only stands in while no UC target exists at all: a deprecated one
        # still owns its securables, and bringing back "everything, any mode" would bypass it.
        if not any(t.system == pt.BUILTIN_UC.adapter.system for t in rows):
            out.insert(0, pt.BUILTIN_UC)
        return out

    def resolve(self, db: Session, key: str, *, include_deprecated: bool = False) -> pt.ResolvedTarget:
        options = self.targets(db, include_deprecated=include_deprecated)
        found = next((t for t in options if t.key == key), None)
        if found is None:
            raise AccessPolicyError(f"Unknown target '{key}'. Available: {', '.join(t.key for t in options)}", 400)
        return found

    def target_for(self, db: Session, system: str, name: str, *,
                   include_deprecated: bool = False) -> Optional[pt.ResolvedTarget]:
        """The target of ``system`` whose scope covers ``name`` (a native securable name)."""
        for t in self.targets(db, include_deprecated=include_deprecated):
            if t.adapter.system == system and (not t.scope or any(pt.inside(name, s) for s in t.scope)):
                return t
        return None

    def require(self, db: Session, release_id: str) -> AccessPolicyReleaseDb:
        row = db.get(AccessPolicyReleaseDb, release_id)
        if not row:
            raise AccessPolicyError("Release not found", 404)
        return row

    def _log_timeline(self, db: Session, row: AccessPolicyReleaseDb, message: str, user: Optional[str]) -> None:
        # Via the repository (flush only) inside a savepoint: CommentsManager.create_comment commits,
        # which would make a half-done request (e.g. a release created before delivery fails) permanent.
        log_timeline(db, ENTITY_TYPE_RELEASE, row.id, message, user)

    def active_ledger(self, db: Session, target: str) -> List[AccessGrantLedgerDb]:
        return (db.query(AccessGrantLedgerDb)
                .filter(AccessGrantLedgerDb.target == target, AccessGrantLedgerDb.status == LEDGER_ACTIVE)
                .all())

    def _fingerprint(self, db: Session, target: str) -> str:
        keys = sorted(f"{r.principal}|{r.securable_type}|{r.securable_name}|{r.privilege}|{r.expires_at or ''}"
                      for r in self.active_ledger(db, target))
        return hashlib.sha256("\n".join(keys).encode()).hexdigest()

    # ------------------------------------------------------------ compile

    def _active_policy_inputs(self, db: Session) -> Tuple[List[PolicyInput], List[Dict[str, Any]], List[str]]:
        inputs: List[PolicyInput] = []
        sources: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for p in repo_for(KIND_POLICY).list_all(db):
            if p.status != STATUS_ACTIVE:
                continue
            doc, errs = self.policies._policy_doc(db, p)
            warnings.extend(f"{p.name}: {e}" for e in errs)
            # One source for fulfilled duties: the policy doc the evaluator reads too.
            inputs.append(PolicyInput(doc=doc, id=p.id, name=p.name, version=p.version,
                                      fulfilled_duties=set(doc.get("fulfilledDuties") or [])))
            sources.append({"id": p.id, "uid": p.uid, "name": p.name, "version": p.version})
        return inputs, sources, warnings

    def compile(self, db: Session, target: str, *,
                resolve_object_kind: Optional[uc.ObjectKindResolver] = None,
                now: Optional[datetime] = None, include_deprecated: bool = False) -> Dict[str, Any]:
        """Compile active policies for ``target`` and diff against the ledger (no writes).

        Only the target's scope is compiled; tracked grants that fell out of scope (the scope
        was narrowed) are released from tracking, never revoked — another target or nobody owns
        them now. Time-bound ones stay tracked until they expire, so the expiry sweep still revokes them.
        ``include_deprecated``: re-base / revoke on a deprecated target (no new policy releases).
        """
        resolved = self.resolve(db, target, include_deprecated=include_deprecated)
        adapter = resolved.adapter
        abac = abac_config()
        inputs, sources, warnings = self._active_policy_inputs(db)
        plan = compile_policies(
            inputs,
            audiences=self.policies._collection_defs(db, KIND_AUDIENCE),
            asset_collections=self.policies._collection_defs(db, KIND_ASSET_COLLECTION),
            directory=lambda: self.policies.known_principals(db),
            now=now,
            abac=abac,
        )
        for w in warnings:
            plan.issue("error", "inheritance", w)
        pt.restrict(plan, resolved)
        grants = adapter.build(plan, abac, resolve_object_kind)
        tracked = [_ledger_grant(r) for r in self.active_ledger(db, target)]
        desired = {g.key for g in grants}
        outside = [g for g in tracked if not adapter.grant_in_scope(g, resolved.scope)]
        # A parent USE grant that an out-of-scope grant of the same principal still needs isn't
        # revoked either — unless the in-scope compile wants it anyway (then it stays tracked).
        below = {(g.principal, g.securable_name) for g in outside}
        outside += [g for g in tracked if g.privilege in pt.IMPLIED_PRIVILEGES and g.key not in desired
                    and adapter.grant_in_scope(g, resolved.scope)
                    and any(p == g.principal and pt.inside(n, g.securable_name) for p, n in below)]
        expiring = [g for g in outside if g.expires_at]
        untrack = [g for g in outside if not g.expires_at]
        skip = {g.key for g in outside}
        diff = uc.diff_grants(grants, [g for g in tracked if g.key not in skip])
        if untrack:
            diff.untrack = sorted(diff.untrack + untrack, key=lambda g: g.key)
            plan.issue("warning", "untracked_outside_scope",
                       f"{len(untrack)} tracked grant(s) are outside the target's scope and will no longer be "
                       "tracked (they stay on the platform)")
        if expiring:
            plan.issue("warning", "expiring_outside_scope",
                       f"{len(expiring)} time-bound grant(s) are outside the target's scope; they stay tracked "
                       "here until they expire and are revoked")
        changes = diff.to_dict()
        changes["sql"] = adapter.render_sql(diff)
        ir = plan.to_dict()
        return {
            "target": target,
            "plan": {"grants": [g.to_dict() for g in grants], "entitlements": ir["entitlements"], "abac": ir["abac"],
                     "gated": ir["gated"], "obligations": ir["obligations"], "compiled_at": ir["compiled_at"]},
            "changes": changes,
            "issues": ir["issues"],
            "has_errors": plan.has_errors,
            "source_policies": sources,
            "ledger_fingerprint": self._fingerprint(db, target),
        }

    @staticmethod
    def _insert(db: Session, row: AccessPolicyReleaseDb, attempts: int = 5) -> AccessPolicyReleaseDb:
        """Insert with the next per-target sequence number; retries if a concurrent insert took it."""
        for _ in range(attempts):
            row.sequence = (db.query(func.max(AccessPolicyReleaseDb.sequence))
                            .filter(AccessPolicyReleaseDb.target == row.target).scalar() or 0) + 1
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                return row
            except IntegrityError:
                continue
        raise AccessPolicyError("Could not allocate a release number — please retry", 409)

    def create_release(self, db: Session, target: str, user: Optional[str], notes: Optional[str] = None, *,
                       resolve_object_kind: Optional[uc.ObjectKindResolver] = None) -> AccessPolicyReleaseDb:
        compiled = self.compile(db, target, resolve_object_kind=resolve_object_kind)
        row = self._insert(db, AccessPolicyReleaseDb(
            target=target, release_kind=KIND_POLICY_RELEASE, status=R_DRAFT, notes=notes,
            plan=compiled["plan"], changes=compiled["changes"], issues=compiled["issues"],
            source_policies=compiled["source_policies"], ledger_fingerprint=compiled["ledger_fingerprint"],
            created_by=user,
        ))
        self._log_timeline(db, row, f"Release #{row.sequence} compiled from {len(compiled['source_policies'])} active "
                                    f"policies: {self._summary(row)}", user)
        return row

    def recompile(self, db: Session, release_id: str, user: Optional[str], *,
                  resolve_object_kind: Optional[uc.ObjectKindResolver] = None) -> AccessPolicyReleaseDb:
        row = self.require(db, release_id)
        if row.status != R_DRAFT or row.release_kind != KIND_POLICY_RELEASE:
            raise AccessPolicyError("Only draft policy releases can be recompiled", 409)
        compiled = self.compile(db, row.target, resolve_object_kind=resolve_object_kind)
        row.plan, row.changes, row.issues = compiled["plan"], compiled["changes"], compiled["issues"]
        row.source_policies, row.ledger_fingerprint = compiled["source_policies"], compiled["ledger_fingerprint"]
        db.flush()
        self._log_timeline(db, row, f"Recompiled: {self._summary(row)}", user)
        return row

    # ------------------------------------------------------------ lifecycle

    def change_status(self, db: Session, release_id: str, new_status: str, user: Optional[str],
                      comment: Optional[str] = None, *, is_admin: bool = False) -> AccessPolicyReleaseDb:
        row = self.require(db, release_id)
        if new_status not in RELEASE_TRANSITIONS.get(row.status, ()):
            raise AccessPolicyError(f"Cannot move a release from '{row.status}' to '{new_status}'", 409)
        if new_status == R_UNDER_REVIEW:
            if any(i.get("severity") == "error" for i in row.issues or []):
                raise AccessPolicyError("Release has compile errors — fix the policies and recompile", 409,
                                        [i["message"] for i in row.issues if i.get("severity") == "error"])
            if self._is_empty(row):
                raise AccessPolicyError("Release has no changes to deliver", 409)
            row.submitted_by = user
        if new_status == R_APPROVED:
            if not is_admin and user and user.lower() in {(row.created_by or "").lower(), (row.submitted_by or "").lower()}:
                raise AccessPolicyError("Separation of duties: the author or submitter can't approve this release", 403)
            self._rebase_if_stale(db, row, user)
            row.approved_by = user
        if new_status == R_DRAFT:
            row.approved_by = None
        row.status = new_status
        db.flush()
        self._log_timeline(db, row, f"Status → {new_status}" + (f": {comment}" if comment else ""), user)
        return row

    @staticmethod
    def _is_empty(row: AccessPolicyReleaseDb) -> bool:
        ch = row.changes or {}
        return not (ch.get("add") or ch.get("remove") or ch.get("update") or ch.get("untrack"))

    @staticmethod
    def _summary(row: AccessPolicyReleaseDb) -> str:
        ch = row.changes or {}

        def n(cat: str, abac: bool) -> int:
            return sum(1 for g in ch.get(cat) or [] if (g.get("securable_type") == uc.ABAC_POLICY) == abac)
        out = (f"{n('add', False)} to grant, {n('remove', False)} to revoke, "
               f"{len(ch.get('update') or [])} expiry updates")
        if n("add", True) or n("remove", True):
            out += f", {n('add', True)} ABAC policies to create, {n('remove', True)} to drop"
        return out

    # ------------------------------------------------------------ delivery

    def _remaining(self, db: Session, row: AccessPolicyReleaseDb) -> Tuple[List[uc.UCGrant], List[uc.UCGrant], List[uc.UCGrant]]:
        """Changes not yet reflected in the ledger (all of them on first delivery; the rest on re-delivery)."""
        have = {_key(r) for r in self.active_ledger(db, row.target)}
        ch = row.changes or {}
        adds = [g for g in (uc.UCGrant.from_dict(d) for d in ch.get("add") or []) if g.key not in have]
        removes = [g for g in (uc.UCGrant.from_dict(d) for d in ch.get("remove") or []) if g.key in have]
        untracks = [g for g in (uc.UCGrant.from_dict(d) for d in ch.get("untrack") or []) if g.key in have]
        return adds, removes, untracks

    @staticmethod
    def _preexisting(adds: List[uc.UCGrant], get_grants: Optional[Callable[[str, str], Dict[str, Any]]]) -> Tuple[List[str], bool]:
        """Which grants to add already exist on the platform (→ never revoked by Ontos later).

        Securables whose live grants can't be read fall back to the conservative rule: implied
        ``USE CATALOG`` / ``USE SCHEMA`` count as pre-existing (they are commonly granted outside
        Ontos, e.g. to ``account users``), explicit privileges as Ontos-made.
        """
        live: Dict[Tuple[str, str], Optional[set]] = {}
        securables = sorted({(g.securable_type, g.securable_name) for g in adds if g.securable_type != uc.ABAC_POLICY})
        results = uc.read_live_grants(securables[:LIVE_DIFF_MAX_SECURABLES], get_grants) if get_grants else {}
        for (stype, sname), res in results.items():
            if res.get("success"):
                live[(stype, sname)] = {(row.get("principal") or "").lower() + "|" + str(p).upper().replace(" ", "_")
                                        for row in res.get("grants") or [] for p in row.get("privileges") or []}
        out: List[str] = []
        for g in adds:
            granted = live.get((g.securable_type, g.securable_name))
            known = granted is not None
            if (known and f"{g.principal.lower()}|{g.privilege}" in granted) or (not known and g.implied):
                out.append("|".join(g.key))
        return out, bool(live) and len(live) == len(securables)

    @staticmethod
    def _delivery_modes(delivery_service: Any, modes: Optional[List[str]],
                        allowed: Optional[List[str]] = None) -> List[Any]:
        from src.controller.delivery_service import DeliveryMode

        if delivery_service is None:
            raise AccessPolicyError("Delivery service is not configured", 503)
        active = delivery_service.get_active_modes()
        if allowed:
            # The target restricts how its releases may ship (e.g. Indirect only: Git + CI apply).
            if modes and (bad := [m for m in modes if m not in allowed]):
                raise AccessPolicyError(f"Delivery mode(s) not allowed for this target: {', '.join(bad)}", 400)
            active = [m for m in active if m.value in allowed]
        if modes:
            try:
                chosen = [DeliveryMode(m) for m in modes]
            except ValueError as e:
                raise AccessPolicyError(str(e), 400) from e
            not_enabled = [m.value for m in chosen if m not in active]
            if not_enabled:
                raise AccessPolicyError(f"Delivery mode(s) not enabled in Settings: {', '.join(not_enabled)}", 400)
        else:
            chosen = active
        if not chosen:
            raise AccessPolicyError("No delivery mode is enabled in Settings → Delivery", 409)
        return chosen

    def deliver(self, db: Session, release_id: str, user: Optional[str], delivery_service: Any,
                modes: Optional[List[str]] = None,
                get_grants: Optional[Callable[[str, str], Dict[str, Any]]] = None) -> AccessPolicyReleaseDb:
        from src.controller.delivery_service import (
            DeliveryChangeType,
            DeliveryMode,
            DeliveryPayload,
        )

        row = self.require(db, release_id)
        if row.status not in DELIVERABLE_STATUSES:
            raise AccessPolicyError(f"Only approved, delivered or failed releases can be delivered; this one is '{row.status}'", 409)
        # Revocation / agreement releases are computed against the ledger at delivery time
        # (``_remaining``), so a moved ledger never makes them stale; policy releases are re-based.
        resolved = self.resolve(db, row.target, include_deprecated=True)
        if row.status == R_APPROVED:
            self._rebase_if_stale(db, row, user)
        chosen = self._delivery_modes(delivery_service, modes, resolved.delivery_modes)
        if get_grants is None:
            get_grants = getattr(getattr(delivery_service, "grant_manager", None), "get_grants", None)

        adds, removes, untracks = self._remaining(db, row)
        preexisting, live_checked = self._preexisting(adds, get_grants)
        diff = uc.GrantDiff(add=adds, remove=removes, untrack=untracks)
        changes = diff.to_dict()
        changes["sql"] = resolved.adapter.render_sql(diff)
        # Indirect mode serializes this snapshot, so the Git artifact matches what Direct/Manual ship.
        entity = SimpleNamespace(
            id=row.id, name=f"{row.target}-release-{row.sequence}", target=row.target, sequence=row.sequence,
            release_kind=row.release_kind, approved_by=row.approved_by, notes=row.notes,
            source_policies=row.source_policies, plan=row.plan, changes=changes,
            created_at=row.created_at, updated_at=row.updated_at,
        )
        payload = DeliveryPayload(
            change_type=DeliveryChangeType.POLICY_RELEASE,
            entity_type="AccessPolicyRelease",
            entity_id=row.id,
            data={
                "entity": entity,
                "target": row.target,
                "sequence": row.sequence,
                "summary": f"Access Policy release #{row.sequence} for {row.target}: "
                           f"{len(adds)} to grant, {len(removes)} to revoke.",
                "grant": uc.group_for_apply(adds),
                "revoke": uc.group_for_apply(removes),
                "abac_create": [{**g.spec, "ledger_key": list(g.key)} for g in adds
                                if g.securable_type == uc.ABAC_POLICY and g.spec],
                "abac_drop": [{**uc.abac_ref(g), "ledger_key": list(g.key)} for g in removes
                              if g.securable_type == uc.ABAC_POLICY],
                "sql": changes["sql"],
                "link": f"/access-policies/releases/{row.id}",
            },
            user=user,
            db=db,
        )
        results = delivery_service.deliver(payload, chosen)
        result_dicts = [r.to_dict() for r in results.results]
        row.delivery_modes = [m.value for m in chosen]
        row.delivery_results = (row.delivery_results or []) + [{"at": _now().isoformat(), "by": user,
                                                                "results": result_dicts,
                                                                "preexisting": preexisting,
                                                                "live_checked": live_checked}]
        row.delivered_by, row.delivered_at = user, _now()

        direct = next((r for r in results.results if r.mode == DeliveryMode.DIRECT), None)
        applied_directly = direct is not None and not direct.details.get("dry_run") and not direct.details.get("skipped")
        if applied_directly:
            ok_add, ok_remove = self._succeeded_items(direct.details.get("items") or [], adds, removes)
            self._apply_to_ledger(db, row, ok_add, ok_remove, untracks, set(preexisting))
            if len(ok_add) == len(adds) and len(ok_remove) == len(removes):
                self._mark_applied(db, row, user, "applied directly via the Databricks SDK")
            else:
                row.status = R_FAILED
                self._log_timeline(db, row, f"Direct delivery partially failed: {len(ok_add)}/{len(adds)} grants, "
                                            f"{len(ok_remove)}/{len(removes)} revokes applied", user)
        else:
            failed = [r for r in results.results if not r.success]
            row.status = R_FAILED if failed and len(failed) == len(results.results) else R_DELIVERED
            self._log_timeline(db, row, f"Delivered via {', '.join(m.value for m in chosen)} — "
                                        + ("awaiting confirmation that it was applied" if row.status == R_DELIVERED
                                           else "; ".join(r.error or "failed" for r in failed)), user)
        db.flush()
        return row

    @staticmethod
    def _succeeded_items(items: List[Dict[str, Any]], adds: List[uc.UCGrant],
                         removes: List[uc.UCGrant]) -> Tuple[List[uc.UCGrant], List[uc.UCGrant]]:
        ok: Dict[str, set] = {"grant": set(), "revoke": set()}
        for it in items:
            if not it.get("success"):
                continue
            if it["op"] in ("abac_create", "abac_drop"):
                ok["grant" if it["op"] == "abac_create" else "revoke"].add(tuple(it.get("ledger_key") or ()))
                continue
            for priv in it.get("privileges") or []:
                ok[it["op"]].add((it["principal"], it["securable_type"], it["securable_name"], priv))
        return [g for g in adds if g.key in ok["grant"]], [g for g in removes if g.key in ok["revoke"]]

    def confirm_applied(self, db: Session, release_id: str, user: Optional[str],
                        comment: Optional[str] = None) -> AccessPolicyReleaseDb:
        """An admin confirms an Indirect / Manual release was applied on the target → update the ledger."""
        row = self.require(db, release_id)
        if row.status != R_DELIVERED:
            raise AccessPolicyError("Only delivered releases can be confirmed as applied", 409)
        adds, removes, untracks = self._remaining(db, row)
        last = (row.delivery_results or [{}])[-1]
        self._apply_to_ledger(db, row, adds, removes, untracks, set(last.get("preexisting") or []))
        self._mark_applied(db, row, user, "confirmed applied" + (f": {comment}" if comment else ""))
        db.flush()
        return row

    def _rebase_if_stale(self, db: Session, row: AccessPolicyReleaseDb, user: Optional[str]) -> None:
        """A policy release diffed against an older ledger (e.g. an Agreement was applied since).

        Recompute the diff against the current ledger; keep the review only if nothing new would
        ship (every change is one that was already reviewed). Otherwise a recompile + review is needed.
        """
        if row.release_kind != KIND_POLICY_RELEASE or row.ledger_fingerprint == self._fingerprint(db, row.target):
            return
        compiled = self.compile(db, row.target, include_deprecated=True)
        old, new = row.changes or {}, compiled["changes"]

        def keys(ch: Dict[str, Any], cat: str) -> set:
            return {(g["principal"], g["securable_type"], g["securable_name"], g["privilege"],
                     g.get("expires_at") if cat == "update" else None) for g in ch.get(cat) or []}

        if any(not keys(new, cat) <= keys(old, cat) for cat in ("add", "remove", "update", "untrack")):
            raise AccessPolicyError("The Grant Ledger changed since this release was compiled and the release "
                                    "would now ship unreviewed changes — send it back to draft and recompile", 409)
        row.plan, row.changes = compiled["plan"], new
        row.ledger_fingerprint = compiled["ledger_fingerprint"]
        self._log_timeline(db, row, f"Re-based onto the current Grant Ledger (subset of the reviewed changes): "
                                    f"{self._summary(row)}", user)

    def _mark_applied(self, db: Session, row: AccessPolicyReleaseDb, user: Optional[str], how: str) -> None:
        row.status, row.applied_by, row.applied_at = R_APPLIED, user, _now()
        # Only a full policy release replaces other open ones; agreement / revocation releases
        # ship their own changes and leave reviewed policy releases alone.
        supersedes = row.release_kind == KIND_POLICY_RELEASE
        for other in [] if not supersedes else (db.query(AccessPolicyReleaseDb)
                      .filter(AccessPolicyReleaseDb.target == row.target, AccessPolicyReleaseDb.id != row.id,
                              AccessPolicyReleaseDb.release_kind == KIND_POLICY_RELEASE,
                              AccessPolicyReleaseDb.status.in_(SUPERSEDABLE_STATUSES)).all()):
            other.status = R_SUPERSEDED
            self._log_timeline(db, other, f"Superseded by release #{row.sequence}", user)
        self._log_timeline(db, row, f"Release {how}", user)

    def _apply_to_ledger(self, db: Session, row: AccessPolicyReleaseDb, adds: List[uc.UCGrant],
                         removes: List[uc.UCGrant], untracks: List[uc.UCGrant], preexisting: set) -> None:
        active = {_key(r): r for r in self.active_ledger(db, row.target)}
        now = _now()
        for status, grants in ((LEDGER_REVOKED, removes), (LEDGER_RELEASED, untracks)):
            for g in grants:
                r = active.pop(g.key, None)
                if r:
                    r.status, r.revoked_at, r.revoked_release_id = status, now, row.id
        for g in adds:
            if g.key in active:
                continue
            entry = AccessGrantLedgerDb(target=row.target, principal=g.principal, securable_type=g.securable_type,
                                        securable_name=g.securable_name, privilege=g.privilege, implied=g.implied,
                                        expires_at=g.expires_at, sources=g.sources, status=LEDGER_ACTIVE,
                                        preexisting="|".join(g.key) in preexisting, spec=g.spec,
                                        granted_release_id=row.id)
            db.add(entry)
            active[g.key] = entry
        if row.release_kind == KIND_POLICY_RELEASE:
            # Ledger-only refresh (expiry, provenance) for every desired grant of the reviewed state.
            refresh = (row.plan or {}).get("grants") or []
        else:
            # Scoped releases only touch their own expiry updates — never unreleased policy edits.
            refresh = (row.changes or {}).get("update") or []
        for d in refresh:
            g = uc.UCGrant.from_dict(d)
            r = active.get(g.key)
            if r is not None:
                r.expires_at, r.sources, r.implied = g.expires_at, g.sources, g.implied
        db.flush()

    # ------------------------------------------------------------ expiry (GDPR)

    def expired_grants(self, db: Session, target: str, now: Optional[datetime] = None) -> List[AccessGrantLedgerDb]:
        now = now or _now()
        return [r for r in self.active_ledger(db, target)
                if (exp := uc.parse_iso(r.expires_at)) is not None and exp <= now]

    def revoke_expired(self, db: Session, target: str, user: Optional[str], delivery_service: Any,
                       now: Optional[datetime] = None) -> Optional[AccessPolicyReleaseDb]:
        """Ship a revocation release for every expired ledger grant (auto-approved: revocation is mandatory)."""
        resolved = self.resolve(db, target, include_deprecated=True)
        expired = self.expired_grants(db, target, now)
        if not expired:
            return None
        # Validate delivery before writing anything, so a misconfiguration leaves no orphaned release.
        self._delivery_modes(delivery_service, None, resolved.delivery_modes)
        open_revocations = (db.query(AccessPolicyReleaseDb)
                            .filter(AccessPolicyReleaseDb.target == target,
                                    # Agreement revocations awaiting confirmation cover grants too.
                                    AccessPolicyReleaseDb.release_kind.in_((KIND_REVOCATION, KIND_AGREEMENT)),
                                    AccessPolicyReleaseDb.status.in_((R_APPROVED, R_DELIVERED, R_FAILED)))
                            .order_by(AccessPolicyReleaseDb.sequence.desc()).all())
        retry = next((r for r in open_revocations
                      if r.release_kind == KIND_REVOCATION and r.status in (R_APPROVED, R_FAILED)), None)
        if retry is not None:
            # Finish the undelivered / failed one first; the next sweep covers anything newer.
            return self.deliver(db, retry.id, user, delivery_service)
        # Grants already in a delivered revocation awaiting confirmation aren't shipped twice,
        # but grants that expired since get a release of their own.
        pending = {(g["principal"], g["securable_type"], g["securable_name"], g["privilege"])
                   for r in open_revocations
                   for g in (r.changes or {}).get("remove", []) + (r.changes or {}).get("untrack", [])}
        expired = [r for r in expired if _key(r) not in pending]
        if not expired:
            return open_revocations[0] if open_revocations else None
        expired_keys = {_key(r) for r in expired}
        remaining = [_ledger_grant(r) for r in self.active_ledger(db, target) if _key(r) not in expired_keys]
        gone = sorted((_ledger_grant(r) for r in expired), key=lambda g: g.key)
        diff = uc.GrantDiff(remove=[g for g in gone if not g.preexisting], untrack=[g for g in gone if g.preexisting])
        changes = diff.to_dict()
        changes["sql"] = resolved.adapter.render_sql(diff)
        row = AccessPolicyReleaseDb(
            target=target, release_kind=KIND_REVOCATION, status=R_APPROVED,
            notes=f"Automatic revocation of {len(expired)} expired grant(s)",
            plan={"grants": [g.to_dict() for g in remaining]}, changes=changes, issues=[],
            source_policies=[], ledger_fingerprint=self._fingerprint(db, target),
            created_by=user, submitted_by=user, approved_by=user,
        )
        self._insert(db, row)
        self._log_timeline(db, row, f"Revocation release #{row.sequence} created for {len(expired)} expired grant(s)", user)
        return self.deliver(db, row.id, user, delivery_service)

    # ------------------------------------------------------------ live state

    def live_diff(self, db: Session, release_id: str, get_grants: Callable[[str, str], Dict[str, Any]]) -> Dict[str, Any]:
        """Report-only comparison of the release's desired grants with live UC grants."""
        row = self.require(db, release_id)
        desired = [uc.UCGrant.from_dict(d) for d in (row.plan or {}).get("grants") or []]
        managed = [_ledger_grant(r) for r in self.active_ledger(db, row.target)]
        securables = sorted({(g.securable_type, g.securable_name) for g in desired + managed
                             if g.securable_type != uc.ABAC_POLICY})
        truncated = len(securables) > LIVE_DIFF_MAX_SECURABLES
        live: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        errors: List[str] = []
        for (stype, sname), res in uc.read_live_grants(securables[:LIVE_DIFF_MAX_SECURABLES], get_grants).items():
            if res.get("success"):
                live[(stype, sname)] = res.get("grants") or []
            else:
                errors.append(f"{stype} {sname}: {res.get('error') or 'unreadable'}")
        checked = set(live)
        report = uc.live_diff([g for g in managed if (g.securable_type, g.securable_name) in checked],
                              [g for g in desired if (g.securable_type, g.securable_name) in checked], live)
        report.update({"checked_at": _now().isoformat(), "securables_checked": len(checked),
                       "truncated": truncated, "errors": errors})
        row.live_diff = report
        db.flush()
        return report

    # ------------------------------------------------------------ read model

    def list(self, db: Session, target: Optional[str] = None, status: Optional[str] = None) -> List[AccessPolicyReleaseDb]:
        q = db.query(AccessPolicyReleaseDb)
        if target:
            q = q.filter(AccessPolicyReleaseDb.target == target)
        if status:
            q = q.filter(AccessPolicyReleaseDb.status == status)
        return q.order_by(AccessPolicyReleaseDb.target, AccessPolicyReleaseDb.sequence.desc()).all()

    def ledger(self, db: Session, target: Optional[str] = None, status: Optional[str] = LEDGER_ACTIVE,
               principal: Optional[str] = None) -> List[Dict[str, Any]]:
        q = db.query(AccessGrantLedgerDb)
        if target:
            q = q.filter(AccessGrantLedgerDb.target == target)
        if status:
            q = q.filter(AccessGrantLedgerDb.status == status)
        if principal:
            q = q.filter(func.lower(AccessGrantLedgerDb.principal) == principal.strip().lower())
        now = _now()
        out = []
        for r in q.order_by(AccessGrantLedgerDb.securable_name, AccessGrantLedgerDb.principal,
                            AccessGrantLedgerDb.privilege).all():
            exp = uc.parse_iso(r.expires_at)
            out.append({
                "id": r.id, "target": r.target, "principal": r.principal, "securable_type": r.securable_type,
                "securable_name": r.securable_name, "privilege": r.privilege, "implied": bool(r.implied),
                "expires_at": r.expires_at, "expired": bool(exp and exp <= now), "sources": r.sources or [],
                "preexisting": bool(r.preexisting),
                "legal_basis": r.legal_basis, "status": r.status,
                "granted_release_id": r.granted_release_id, "revoked_release_id": r.revoked_release_id,
                "granted_at": r.granted_at, "revoked_at": r.revoked_at,
            })
        return out

    def to_read_dict(self, row: AccessPolicyReleaseDb) -> Dict[str, Any]:
        ch = row.changes or {}
        issues = row.issues or []
        return {
            "id": row.id, "entity_type": ENTITY_TYPE_RELEASE, "target": row.target, "sequence": row.sequence,
            "name": f"{row.target.upper()} release #{row.sequence}",
            "release_kind": row.release_kind, "status": row.status, "notes": row.notes,
            "allowed_transitions": list(RELEASE_TRANSITIONS.get(row.status, ())),
            "deliverable": row.status in DELIVERABLE_STATUSES,
            "confirmable": row.status == R_DELIVERED,
            "counts": {"add": len(ch.get("add") or []), "remove": len(ch.get("remove") or []),
                       "update": len(ch.get("update") or []), "untrack": len(ch.get("untrack") or []),
                       "unchanged": ch.get("unchanged", 0),
                       "grants": len((row.plan or {}).get("grants") or []),
                       "gated": len((row.plan or {}).get("gated") or []),
                       "errors": sum(1 for i in issues if i.get("severity") == "error"),
                       "warnings": sum(1 for i in issues if i.get("severity") == "warning")},
            "plan": row.plan or {}, "changes": ch, "issues": issues,
            "source_policies": row.source_policies or [],
            "delivery_modes": row.delivery_modes or [], "delivery_results": row.delivery_results or [],
            "live_diff": row.live_diff,
            "created_by": row.created_by, "submitted_by": row.submitted_by, "approved_by": row.approved_by,
            "delivered_by": row.delivered_by, "delivered_at": row.delivered_at,
            "applied_by": row.applied_by, "applied_at": row.applied_at,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }


def uc_object_kind_resolver(ws: Any) -> uc.ObjectKindResolver:
    """Resolve 3-part UC names to table / volume / function / model via the SDK (cached; defaults to table)."""
    cache: Dict[str, Optional[str]] = {}

    def resolve(name: str) -> Optional[str]:
        if name in cache:
            return cache[name]
        kind: Optional[str] = None
        for k, fn in ((uc.KIND_TABLE, lambda: ws.tables.get(name)),
                      (uc.KIND_VOLUME, lambda: ws.volumes.read(name)),
                      (uc.KIND_FUNCTION, lambda: ws.functions.get(name)),
                      (uc.KIND_MODEL, lambda: ws.registered_models.get(name))):
            try:
                fn()
                kind = k
                break
            except Exception:
                continue
        cache[name] = kind
        return kind
    return resolve

