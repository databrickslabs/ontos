"""Access Grants as ODRL Agreements (Phase 3).

An approved Access Grant is a concrete deal between the approving admin
(``assigner``) and the requester (``assignee``) — an ``odrl:Agreement``. Recording
it as an Access Policy makes it part of the one permission model:

* it is **active** right away — the access-request approval *is* its review
  (``submitted_by`` = requester, ``approved_by`` = approver, separation of duties held);
* its permissions target the entity's UC assets (Data Product → output ports'
  ``asset_identifier``) with action from the permission level and
  ``dateTime lteq expires_at``, so compiled grants carry the expiry and the Grant
  Ledger sweep revokes them on time;
* every normal release includes it; with ``ACCESS_AGREEMENTS_AUTO_DELIVER`` (off by
  default) it is also shipped immediately as an **agreement-scoped release** (only
  this Agreement's grants, expiry updates included — unrelated pending policy
  changes never ride along);
* revoking or expiring the grant retires the Agreement and, with
  ``ACCESS_AGREEMENTS_AUTO_REVOKE`` (on by default), ships the matching revocation
  right away. That can only ever remove grants Ontos applied (Grant Ledger), so it
  is safe on installs that never delivered Agreements.

Everything here is best-effort from the Access Grants flow's point of view: a
failure is logged and never blocks approving or revoking a grant.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common import odrl
from src.common import uc_policy_adapter as uc
from src.common.config import get_settings
from src.common.logging import get_logger
from src.controller.access_policies_manager import (
    KIND_POLICY,
    STATUS_ACTIVE,
    STATUS_RETIRED,
    AccessPoliciesManager,
)
from src.db_models.access_policies import AccessPolicyDb, AccessPolicyReleaseDb

logger = get_logger(__name__)

KIND_AGREEMENT_RELEASE = "agreement"

# Access Grant permission level → profile actions. Levels are cumulative: write implies read.
PERMISSION_ACTIONS = {"READ": ("read",), "WRITE": ("read", "modify"), "MANAGE": ("read", "modify", "ontos:manage")}
_INACTIVE_PORT_STATUSES = {"deprecated", "retired", "inactive"}
# Output-port asset types that are UC objects (catalog.schema.object).
_UC_OBJECT_TYPES = {"table", "view", "materialized_view", "streaming_table", "volume", "function", "model",
                    "uc_table", "uc_view", "uc_volume", "uc_function", "uc_model"}
# Entity types an Access Grant may name directly, with the UC name depth they require.
_DIRECT_ENTITY_DEPTH = {"catalog": 1, "schema": 2, "table": 3, "view": 3, "volume": 3,
                        "asset": 3, "uc_asset": 3, "dataset": 3}


def _uc_name(value: Optional[str], depth: int) -> Optional[str]:
    """A dotted UC name with exactly ``depth`` non-empty parts (no wildcards), else None."""
    parts = (value or "").strip().split(".")
    if len(parts) != depth or not all(p.strip() and "*" not in p and " " not in p.strip() for p in parts):
        return None
    return ".".join(p.strip() for p in parts)


def entity_targets(db: Session, entity_type: str, entity_id: str) -> List[str]:
    """UC securable refs an Access Grant on this entity covers (empty if none are known).

    Strict on purpose: a wrong guess (a topic name read as a catalog) would over-grant.
    """
    entity_type = (entity_type or "").lower()
    if entity_type == "data_product":
        from src.db_models.data_products import OutputPortDb

        refs: List[str] = []
        for port in db.query(OutputPortDb).filter(OutputPortDb.product_id == entity_id).all():
            if (port.status or "").lower() in _INACTIVE_PORT_STATUSES:
                continue
            if port.asset_type and port.asset_type.lower() not in _UC_OBJECT_TYPES:
                continue
            name = _uc_name(port.asset_identifier, 3)
            if name and odrl.UC_PREFIX + name not in refs:
                refs.append(odrl.UC_PREFIX + name)
        return refs
    depth = _DIRECT_ENTITY_DEPTH.get(entity_type)
    name = _uc_name(str(entity_id), depth) if depth else None
    return [odrl.UC_PREFIX + name] if name else []


class AgreementService:
    def __init__(self, policies: Optional[AccessPoliciesManager] = None):
        self.policies = policies or AccessPoliciesManager()

    # ------------------------------------------------------------ lifecycle

    def for_grant(self, db: Session, grant_id: Any) -> List[AccessPolicyDb]:
        return db.query(AccessPolicyDb).filter(AccessPolicyDb.access_grant_id == str(grant_id)).all()

    def create_for_grant(self, db: Session, grant: Any, *, requested_by: Optional[str],
                         approved_by: Optional[str]) -> AccessPolicyDb:
        """Record an approved Access Grant as an active ``odrl:Agreement``."""
        targets = entity_targets(db, grant.entity_type, grant.entity_id)
        if not targets:
            # Keep the deal on record; the compiler reports the non-UC target and grants nothing.
            targets = [f"urn:ontos:{grant.entity_type}:{grant.entity_id}"]
        actions = PERMISSION_ACTIONS.get(str(grant.permission_level).upper(), ("read",))
        expires = grant.expires_at.isoformat().replace("+00:00", "Z") if grant.expires_at else None
        constraint = [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": expires}] if expires else []
        rules = {"permission": [
            {"target": t, "action": a, "assignee": f"user:{grant.grantee_email}",
             **({"assigner": f"user:{approved_by}"} if approved_by else {}), "constraint": constraint}
            for t in targets for a in actions
        ]}
        label = grant.entity_name or grant.entity_id
        # The product's terms (its active Offers) bind this consumer. An Agreement records the deal as
        # concluded, so the terms are snapshotted (ODRL inheritance resolved once, Offer-aware: the
        # Offers' prohibitions / obligations bound to the grantee, never their permissions) — a later
        # Offer change or retirement doesn't silently rewrite existing Agreements.
        offers = self.policies.offers_for(db, grant.entity_type, grant.entity_id)
        body = self.policies._normalize_rules("Agreement", odrl.DEFAULT_AUTHORED_CONFLICT, [], rules)
        conflict = odrl.DEFAULT_AUTHORED_CONFLICT
        notes: List[str] = []
        if offers:
            # Each Offer as compiled (its own inheritFrom resolved), so inherited baseline terms count too.
            by_uid: Dict[str, Dict[str, Any]] = {}
            for o in offers:
                doc, errs = self.policies._policy_doc(db, o)
                notes.extend(f"{o.name}: {e}" for e in errs)
                by_uid[o.uid] = {**doc, "type": "Offer", "inheritFrom": []}
            merged, errors = odrl.resolve_inheritance(
                {"uid": "urn:ontos:policy:new", "type": "Agreement", "conflict": None,
                 "profile": [odrl.ONTOS_PROFILE], "inheritFrom": list(by_uid), **body}, by_uid.get)
            notes.extend(errors)
            # Keep the terms' meaning: the Offers' conflict strategy (spec rules for differing ones).
            conflict = merged.get("conflict") or odrl.DEFAULT_AUTHORED_CONFLICT
            body = {k: merged.get(k) or [] for k in odrl.RULE_KINDS}
            for perm in body["permission"]:
                # The access-request approval is the approval the terms ask for.
                if any(d.get("action") == "ontos:obtainApproval" for d in perm.get("duty") or []):
                    perm["duty"] = [d for d in perm["duty"] if d.get("action") != "ontos:obtainApproval"]
                    notes.append("ontos:obtainApproval fulfilled by the Access Grant approval")
            if any(p.get("duty") for p in body["permission"]):
                notes.append("open duties from the product's terms — access is granted once they are fulfilled")
        terms = "; terms from " + ", ".join(f"{o.name} v{o.version}" for o in offers) if offers else ""
        row = AccessPolicyDb(
            name=f"Agreement: {grant.grantee_email} → {label}",
            description=f"Access Grant {grant.id}: {grant.permission_level} on {grant.entity_type} '{label}'"
                        + (f" until {expires}" if expires else "") + terms,
            status=STATUS_ACTIVE, policy_type="Agreement", conflict=conflict,
            inherit_from=[], body=body,
            access_grant_id=str(grant.id),
            created_by=approved_by, submitted_by=requested_by, approved_by=approved_by,
        )
        db.add(row)
        db.flush()
        self.policies._rebuild_index(db, row)
        self.policies._log_timeline(db, KIND_POLICY, row.id,
                                    f"Agreement recorded from approved Access Grant {grant.id}"
                                    + (" — " + "; ".join(dict.fromkeys(notes)) if notes else ""), approved_by)
        return row

    def retire_for_grant(self, db: Session, grant_id: Any, user: Optional[str], reason: str) -> List[AccessPolicyDb]:
        """The grant was revoked or expired: retire its Agreement(s) (system transition)."""
        retired = []
        for row in self.for_grant(db, grant_id):
            if row.status == STATUS_RETIRED:
                continue
            row.status, row.updated_by = STATUS_RETIRED, user
            self.policies._log_timeline(db, KIND_POLICY, row.id, f"Agreement retired: {reason}", user)
            retired.append(row)
        db.flush()
        return retired

    # ------------------------------------------------------------ delivery

    def prepare_release(self, db: Session, agreements: List[AccessPolicyDb], user: Optional[str], *,
                        revoke: bool = False) -> Optional[AccessPolicyReleaseDb]:
        """An auto-approved release with only these Agreements' changes (None if there is nothing to ship).

        Uses the regular compile-vs-ledger diff and keeps the entries whose provenance includes one
        of the Agreements: grants to add (or expiry updates, e.g. a renewal) when provisioning; grants
        to revoke / stop tracking when revoking.
        """
        from src.controller.access_policy_releases_manager import R_APPROVED, PolicyReleaseManager

        uids = {a.uid for a in agreements}
        if not uids:
            return None
        rm = PolicyReleaseManager(self.policies)
        compiled = rm.compile(db, uc.TARGET_UC)
        changes = compiled["changes"]

        def mine(cat: str) -> List[uc.UCGrant]:
            return [g for g in (uc.UCGrant.from_dict(d) for d in changes.get(cat) or [])
                    if any(s.get("policy_uid") in uids for s in g.sources or [])]

        if revoke:
            # Removed grants no longer carry the (retired) Agreement in the compile: match on the ledger's provenance.
            scoped = uc.GrantDiff(remove=mine("remove"), untrack=mine("untrack"))
        else:
            scoped = uc.GrantDiff(add=mine("add"), update=mine("update"))
        if scoped.empty:
            return None
        out = scoped.to_dict()
        out["sql"] = uc.render_sql(scoped)
        names = ", ".join(a.name for a in agreements)
        row = rm._insert(db, AccessPolicyReleaseDb(
            target=uc.TARGET_UC, release_kind=KIND_AGREEMENT_RELEASE, status=R_APPROVED,
            notes=f"{'Revocation of' if revoke else 'Provisioning'} {names}",
            plan={"compiled_at": compiled["plan"]["compiled_at"]},
            changes=out, issues=[], ledger_fingerprint=compiled["ledger_fingerprint"],
            source_policies=[{"id": a.id, "uid": a.uid, "name": a.name, "version": a.version} for a in agreements],
            created_by=user, submitted_by=agreements[0].submitted_by, approved_by=agreements[0].approved_by,
        ))
        rm._log_timeline(db, row, f"Release #{row.sequence} created for {names}", user)
        return row

    def deliver(self, db: Session, agreements: List[AccessPolicyDb], user: Optional[str], delivery_service: Any, *,
                revoke: bool = False) -> Optional[AccessPolicyReleaseDb]:
        """Prepare and deliver in one transaction (tests / callers that own the commit)."""
        from src.controller.access_policy_releases_manager import PolicyReleaseManager

        row = self.prepare_release(db, agreements, user, revoke=revoke)
        return PolicyReleaseManager(self.policies).deliver(db, row.id, user, delivery_service) if row else None


# ---------------------------------------------------------------- duties

# Duties only the Agreement's assignee can fulfil (a consumer's own acceptance).
ASSIGNEE_DUTIES = {"ontos:acknowledgeTerms"}


def _assignee_emails(agreement: AccessPolicyDb, *, as_stored: bool = False) -> List[str]:
    """The Agreement's user assignees — lower-cased for comparison, or as stored (for delivery)."""
    out = []
    for r in (agreement.body or {}).get("permission") or []:
        a = r.get("assignee")
        if isinstance(a, str) and a.lower().startswith(("user:", "mailto:")):
            email = a.split(":", 1)[1]
            email = email if as_stored else email.lower()
            if email not in out:
                out.append(email)
    return out


def _duty_label(action: str) -> str:
    spec = odrl.ACTIONS.get(action)
    return spec.label if spec else action


def duty_status(agreement: AccessPolicyDb, viewer: Optional[str], is_admin: bool) -> List[Dict[str, Any]]:
    """Every duty action on the Agreement's permissions, whether it's fulfilled, and if ``viewer`` may fulfil it."""
    done = {d.get("action"): d for d in agreement.fulfilled_duties or []}
    actions: List[str] = []
    for r in (agreement.body or {}).get("permission") or []:
        for d in r.get("duty") or []:
            if d.get("action") and d["action"] not in actions:
                actions.append(d["action"])
    is_assignee = bool(viewer) and viewer.lower() in _assignee_emails(agreement)
    out = []
    for a in actions:
        rec = done.get(a)
        # Separation of duties: an admin can't fulfil the admin-only duties of their own Agreement.
        can = rec is None and agreement.status == STATUS_ACTIVE and (
            is_assignee if a in ASSIGNEE_DUTIES else (is_admin and not is_assignee))
        out.append({"action": a, "label": _duty_label(a), "fulfilled": rec is not None, "fulfilled_by": (rec or {}).get("fulfilled_by"),
                    "fulfilled_at": (rec or {}).get("fulfilled_at"), "note": (rec or {}).get("note"),
                    "can_fulfill": can, "fulfilled_by_assignee_only": a in ASSIGNEE_DUTIES})
    return out


def fulfill_duty(db: Session, agreement: AccessPolicyDb, action: str, user: Optional[str], is_admin: bool,
                 note: Optional[str] = None) -> AccessPolicyDb:
    """Record a fulfilled duty: terms are accepted by the grantee themself; other duties by an admin."""
    from datetime import datetime, timezone

    from src.controller.access_policies_manager import AccessPolicyError

    if agreement.policy_type != "Agreement":
        raise AccessPolicyError("Duties are fulfilled on Agreements (a concrete party's deal)", 409)
    action = odrl.term_key(action) or action
    if action not in odrl.ACTIONS and f"ontos:{action}" in odrl.ACTIONS:
        action = f"ontos:{action}"
    # Lock the row: concurrent fulfilments must not overwrite each other's JSON list.
    agreement = (db.query(AccessPolicyDb).filter(AccessPolicyDb.id == agreement.id)
                 .with_for_update().populate_existing().one())
    status = {d["action"]: d for d in duty_status(agreement, user, is_admin)}
    if action not in status:
        raise AccessPolicyError(f"'{action}' is not a duty of this Agreement", 404)
    if status[action]["fulfilled"]:
        raise AccessPolicyError(f"'{action}' is already fulfilled", 409)
    if not status[action]["can_fulfill"]:
        who = ("the Agreement's assignee" if action in ASSIGNEE_DUTIES
               else "an Access Policies admin other than the Agreement's assignee")
        raise AccessPolicyError(f"Only {who} can fulfil '{action}'", 403)
    agreement.fulfilled_duties = list(agreement.fulfilled_duties or []) + [{
        "action": action, "fulfilled_by": user, "note": note,
        "fulfilled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }]
    db.flush()
    AgreementService().policies._log_timeline(db, KIND_POLICY, agreement.id,
                                              f"Duty fulfilled: {action}" + (f" — {note}" if note else ""), user)
    return agreement


def _notify_open_duties(db: Session, agreement: AccessPolicyDb) -> None:
    """Tell the grantee which terms to accept before the access becomes live. Best-effort."""
    try:
        open_assignee = [d["action"] for d in duty_status(agreement, None, False)
                         if not d["fulfilled"] and d["fulfilled_by_assignee_only"]]
        if not open_assignee:
            return
        import uuid
        from datetime import datetime

        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo
        # As stored: the bell matches the recipient against the login email exactly.
        for email in _assignee_emails(agreement, as_stored=True):
            with db.begin_nested():
                notification_repo.create(db, obj_in=Notification(
                    id=str(uuid.uuid4()), type=NotificationType.ACTION_REQUIRED,
                    title="Accept the terms of use to activate your access",
                    description=f"{agreement.name}: your access is granted once you accept the product's terms.",
                    link=f"/access-terms/{agreement.id}", recipient=email,
                    created_at=datetime.utcnow(), read=False, can_delete=True,
                ))
    except Exception as e:  # pragma: no cover - notification is best-effort
        logger.warning("Could not notify about open duties on %s: %s", agreement.name, e)


# ---------------------------------------------------------------- Access Grants hooks

def _delivery_service() -> Any:
    try:
        from src.controller.delivery_service import get_delivery_service
        return get_delivery_service()
    except RuntimeError:
        return None


def on_grant_approved(db: Session, grant: Any, requested_by: Optional[str], approved_by: Optional[str]) -> Optional[AccessPolicyDb]:
    """Called inside the approval transaction. Never raises."""
    try:
        with db.begin_nested():
            agreement = AgreementService().create_for_grant(db, grant, requested_by=requested_by,
                                                            approved_by=approved_by)
    except Exception as e:
        logger.error("Could not record Agreement for Access Grant %s: %s", getattr(grant, 'id', '?'), e, exc_info=True)
        return None
    _notify_open_duties(db, agreement)  # never raises
    return agreement


def on_grant_ended(db: Session, grant_id: Any, user: Optional[str], reason: str) -> List[AccessPolicyDb]:
    """Called inside the revoke / expiry transaction. Never raises."""
    try:
        with db.begin_nested():
            return AgreementService().retire_for_grant(db, grant_id, user, reason)
    except Exception as e:
        logger.error("Could not retire Agreement for Access Grant %s: %s", grant_id, e, exc_info=True)
        return []


def auto_deliver(db: Session, agreements: List[AccessPolicyDb], user: Optional[str], *, revoke: bool) -> None:
    """After the grant transaction committed: ship one agreement-scoped release if enabled. Never raises.

    The release row is committed *before* anything reaches the platform: if delivery then fails
    halfway, the release is kept as ``failed`` (re-deliverable; GRANT / REVOKE are idempotent)
    instead of being rolled back while some grants may already be live.
    """
    settings = get_settings()
    enabled = settings.ACCESS_AGREEMENTS_AUTO_REVOKE if revoke else settings.ACCESS_AGREEMENTS_AUTO_DELIVER
    if not agreements or not enabled:
        return
    from src.controller.access_policy_releases_manager import R_FAILED, PolicyReleaseManager

    service = _delivery_service()
    if service is None or not service.get_active_modes():
        what = "revocation" if revoke else "provisioning"
        for a in agreements:
            AgreementService().policies._log_timeline(
                db, KIND_POLICY, a.id, f"No Delivery Mode is enabled — the {what} needs a policy release", user)
        db.commit()
        logger.warning("Agreement %s not delivered: no Delivery Mode available — a policy release is needed", what)
        return
    try:
        row = AgreementService().prepare_release(db, agreements, user, revoke=revoke)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Could not prepare the agreement release: %s", e, exc_info=True)
        return
    if row is None:
        return
    release_id = row.id
    try:
        PolicyReleaseManager().deliver(db, release_id, user, service)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Agreement release %s failed during delivery: %s", release_id, e, exc_info=True)
        try:
            failed = db.get(AccessPolicyReleaseDb, release_id)
            if failed is not None:
                failed.status = R_FAILED
                PolicyReleaseManager()._log_timeline(
                    db, failed, "Delivery failed partway — re-deliver it, then check the live state", user)
                db.commit()
        except Exception:  # pragma: no cover - best-effort bookkeeping
            db.rollback()


def open_duties(agreement: AccessPolicyDb) -> List[str]:
    return [d["action"] for d in duty_status(agreement, None, False) if not d["fulfilled"]]
