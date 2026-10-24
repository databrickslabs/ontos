"""Access Policies manager (W3C ODRL 2.2).

Owns the governed lifecycle of the three Access Policy entity kinds — policies
(``odrl:Set``/``Offer``/``Agreement``), Audiences (``odrl:PartyCollection``) and
Asset Collections (``odrl:AssetCollection``) — and the policy-level operations:
validation, JSON-LD import/export and access evaluation ("can P do A on T?").

Design notes:
* Stateless singleton; the DB session is passed per call (mirrors other managers).
* ODRL semantics live in the pure ``src.common.odrl`` module; this manager only
  resolves stored entities into the plain dicts it consumes.
* Lifecycle parity with Data Products: status workflow, semantic version
  families (``version_family_id`` + ``parent_id``), owner team / project /
  personal draft, multi-domain, tags, and the Comments timeline.
* References inside policy bodies use the family-level IRI (``uid``), so a
  policy keeps pointing at "the Analysts audience" across audience versions;
  evaluation resolves each IRI to the family's active version.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from sqlalchemy.orm import Session

from src.common import odrl
from src.common.logging import get_logger
from src.common.version_visibility import collapse_by_family, family_counts
from src.db_models.access_policies import (
    ENTITY_TYPE_ASSET_COLLECTION,
    ENTITY_TYPE_AUDIENCE,
    ENTITY_TYPE_POLICY,
    AccessAssetCollectionDb,
    AccessAudienceDb,
    AccessPolicyDb,
)
from src.repositories.access_policies_repository import access_policy_index_repo, repo_for
from src.repositories.entity_domain_association_repository import entity_domain_repo

logger = get_logger(__name__)

KIND_POLICY = "policy"
KIND_AUDIENCE = "audience"
KIND_ASSET_COLLECTION = "asset_collection"

STATUS_DRAFT = "draft"
STATUS_UNDER_REVIEW = "under_review"
STATUS_APPROVED = "approved"
STATUS_ACTIVE = "active"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_DEPRECATED = "deprecated"
STATUS_RETIRED = "retired"

# Allowed lifecycle transitions (same for all three kinds).
TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    STATUS_DRAFT: (STATUS_UNDER_REVIEW,),
    STATUS_UNDER_REVIEW: (STATUS_APPROVED, STATUS_DRAFT),
    STATUS_APPROVED: (STATUS_ACTIVE, STATUS_DRAFT),
    STATUS_ACTIVE: (STATUS_NEEDS_REVIEW, STATUS_DEPRECATED),
    STATUS_NEEDS_REVIEW: (STATUS_ACTIVE, STATUS_UNDER_REVIEW, STATUS_DEPRECATED),
    STATUS_DEPRECATED: (STATUS_ACTIVE, STATUS_RETIRED),
    STATUS_RETIRED: (),
}
# Content (rules / membership) is only editable in draft: what gets reviewed is what gets
# activated. Under review → send back to draft to change it; approved and later → new version.
EDITABLE_STATUSES = (STATUS_DRAFT,)
DELETABLE_STATUSES = (STATUS_DRAFT, STATUS_RETIRED)


@dataclass(frozen=True)
class KindSpec:
    kind: str
    model: Type
    entity_type: str
    label: str


KINDS: Dict[str, KindSpec] = {
    KIND_POLICY: KindSpec(KIND_POLICY, AccessPolicyDb, ENTITY_TYPE_POLICY, "Access Policy"),
    KIND_AUDIENCE: KindSpec(KIND_AUDIENCE, AccessAudienceDb, ENTITY_TYPE_AUDIENCE, "Audience"),
    KIND_ASSET_COLLECTION: KindSpec(KIND_ASSET_COLLECTION, AccessAssetCollectionDb, ENTITY_TYPE_ASSET_COLLECTION, "Asset Collection"),
}

_LIFECYCLE_COPY = ("name", "description", "owner_team_id", "project_id", "uid")
_KIND_COPY = {
    KIND_POLICY: ("policy_type", "conflict", "inherit_from", "body", "access_grant_id",
                  "subject_entity_type", "subject_entity_id"),
    KIND_AUDIENCE: ("members", "refinement"),
    KIND_ASSET_COLLECTION: ("members", "refinement"),
}


class AccessPolicyError(ValueError):
    """Author-visible validation / lifecycle error (routes map it to 400/409)."""

    def __init__(self, message: str, status_code: int = 400, details: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


# ----------------------------------------------------------- principal attributes

class PrincipalAttributeSource:
    """Supplies party attributes (keyed by ODRL leftOperand) for dynamic Audiences."""

    name = "base"

    def attributes(self, db: Session, principal: str) -> Dict[str, List[str]]:  # pragma: no cover - interface
        raise NotImplementedError

    def principals(self, db: Session) -> List[str]:
        """Principals this source knows (compile-time expansion of attribute-refined Audiences)."""
        return []

    def all_attributes(self, db: Session) -> Dict[str, Dict[str, List[str]]]:
        """Attributes of every known principal; override with a single query to avoid N+1."""
        return {p: self.attributes(db, p) for p in self.principals(db)}


class BusinessRoleAttributeSource(PrincipalAttributeSource):
    """v1 source: the Ontos Business Roles a principal actively holds (via business owners)."""

    name = "ontos_business_roles"

    def attributes(self, db: Session, principal: str) -> Dict[str, List[str]]:
        from src.db_models.business_owners import BusinessOwnerDb
        from src.db_models.business_roles import BusinessRoleDb

        rows = (
            db.query(BusinessRoleDb.name)
            .join(BusinessOwnerDb, BusinessOwnerDb.role_id == BusinessRoleDb.id)
            .filter(BusinessOwnerDb.user_email.ilike(principal), BusinessOwnerDb.is_active.is_(True))
            .distinct()
            .all()
        )
        return {"ontos:businessRole": sorted({r[0] for r in rows if r[0]})}

    def principals(self, db: Session) -> List[str]:
        return sorted(self.all_attributes(db))

    def all_attributes(self, db: Session) -> Dict[str, Dict[str, List[str]]]:
        from src.db_models.business_owners import BusinessOwnerDb
        from src.db_models.business_roles import BusinessRoleDb

        rows = (
            db.query(BusinessOwnerDb.user_email, BusinessRoleDb.name)
            .join(BusinessRoleDb, BusinessOwnerDb.role_id == BusinessRoleDb.id)
            .filter(BusinessOwnerDb.is_active.is_(True))
            .distinct()
            .all()
        )
        out: Dict[str, set] = {}
        for email, role in rows:
            if email:
                out.setdefault(email.lower(), set()).update([role] if role else [])
        return {p: {"ontos:businessRole": sorted(r)} for p, r in out.items()}


class DirectoryAttributeSource(PrincipalAttributeSource):
    """Stub: principal attributes from an external directory (Entra ID / IdP via REST
    connection, or a Lakebase table) through the Directory layer
    (``src.controller.directory_manager``). Not wired in v1 — returns nothing."""

    name = "directory"

    def __init__(self, provider_type: str):
        self.provider_type = provider_type

    def attributes(self, db: Session, principal: str) -> Dict[str, List[str]]:
        return {}


DEFAULT_ATTRIBUTE_SOURCES: List[PrincipalAttributeSource] = [BusinessRoleAttributeSource()]


def log_timeline(db: Session, entity_type: str, entity_id: str, message: str, user: Optional[str] = None) -> None:
    """Best-effort timeline (Comments) entry that never commits the caller's transaction.

    ``CommentsManager.create_comment`` commits; the repository only flushes, and the savepoint
    keeps a failing insert from poisoning the request's session.
    """
    try:
        from src.models.comments import CommentCreate
        from src.repositories.comments_repository import comments_repo
        with db.begin_nested():
            comments_repo.create_with_audience(
                db, obj_in=CommentCreate(entity_type=entity_type, entity_id=entity_id, comment=message),
                created_by=user or "system@ontos",
            )
    except Exception as e:  # pragma: no cover - timeline logging is best-effort
        logger.warning(f"Could not write timeline comment for {entity_type} {entity_id}: {e}")


# ------------------------------------------------------------------- the manager

class AccessPoliciesManager:
    def __init__(self, attribute_sources: Optional[List[PrincipalAttributeSource]] = None):
        self.attribute_sources = attribute_sources if attribute_sources is not None else DEFAULT_ATTRIBUTE_SOURCES

    # --------------------------------------------------------------- helpers

    @staticmethod
    def spec(kind: str) -> KindSpec:
        if kind not in KINDS:
            raise AccessPolicyError(f"Unknown kind '{kind}'", 404)
        return KINDS[kind]

    def _log_timeline(self, db: Session, kind: str, entity_id: str, message: str, user: Optional[str] = None) -> None:
        """Best-effort: append a system comment to the entity's Comments timeline."""
        log_timeline(db, self.spec(kind).entity_type, entity_id, message, user)

    def _set_tags(self, db: Session, kind: str, entity_id: str, tags: Optional[List[Any]], user: Optional[str]) -> None:
        if tags is None:
            return
        try:
            from src.controller.tags_manager import TagsManager
            TagsManager().set_tags_for_entity(
                db, entity_id=entity_id, entity_type=self.spec(kind).entity_type, tags=list(tags), user_email=user,
            )
        except Exception as e:  # pragma: no cover - tag write is best-effort
            logger.warning(f"Could not set tags for {kind} {entity_id}: {e}")

    def _set_domains(self, db: Session, kind: str, entity_id: str, domain_ids: Optional[List[str]],
                     primary_domain_id: Optional[str], user: Optional[str]) -> None:
        if domain_ids is None:
            return
        entity_domain_repo.set_domains_for_entity(
            db, entity_type=self.spec(kind).entity_type, entity_id=entity_id,
            domain_ids=domain_ids, primary_domain_id=primary_domain_id, assigned_by=user,
        )

    @staticmethod
    def _visible(row: Any, viewer: Optional[str], is_admin: bool) -> bool:
        owner = getattr(row, "draft_owner_id", None)
        return not owner or is_admin or (viewer is not None and owner.lower() == viewer.lower())

    # ------------------------------------------------------------- policy body

    def _normalize_rules(self, policy_type: str, conflict: Optional[str], inherit_from: List[str],
                         rules: Dict[str, Any]) -> Dict[str, Any]:
        doc = {"@type": policy_type or "Set", "uid": "urn:ontos:policy:draft", "conflict": conflict,
               "inheritFrom": inherit_from or [], **{k: rules.get(k) for k in odrl.RULE_KINDS if rules.get(k)}}
        # Policy-level shared properties are allowed in the editor's JSON too (compact form).
        for shared in ("action", "target", "assignee", "assigner"):
            if rules.get(shared) is not None:
                doc[shared] = rules[shared]
        norm = odrl.normalize_policy(doc)
        return {k: norm[k] for k in odrl.RULE_KINDS}

    def _known_ref(self, db: Session, kind: str) -> Callable[[str], bool]:
        prefix = odrl.AUDIENCE_IRI_PREFIX if kind == KIND_AUDIENCE else odrl.ASSET_COLLECTION_IRI_PREFIX
        repo = repo_for(kind)

        def known(ref: str) -> bool:
            if not ref.startswith(prefix):
                return True
            return bool(repo.get_family_by_uid(db, ref))
        return known

    def validate_body(self, db: Session, policy_type: str, conflict: Optional[str],
                      inherit_from: List[str], rules: Dict[str, Any]) -> List[Dict[str, str]]:
        body = self._normalize_rules(policy_type, conflict, inherit_from, rules)
        doc = {"type": policy_type or "Set", "uid": "x", "profile": [odrl.ONTOS_PROFILE],
               "conflict": conflict, "inheritFrom": inherit_from or [], **body}
        issues = [i.to_dict() for i in odrl.validate_policy(
            doc, known_party=self._known_ref(db, KIND_AUDIENCE), known_asset=self._known_ref(db, KIND_ASSET_COLLECTION))]
        for parent in inherit_from or []:
            if not repo_for(KIND_POLICY).get_family_by_uid(db, parent):
                issues.append({"severity": "error", "path": "inheritFrom", "message": f"Parent policy {parent} not found"})
        if conflict == odrl.SPEC_DEFAULT_CONFLICT:
            issues.append({"severity": "warning", "path": "conflict",
                           "message": "conflict=invalid voids the whole policy if any permission and prohibition clash"})
        return issues

    def _rebuild_index(self, db: Session, policy: AccessPolicyDb) -> None:
        access_policy_index_repo.replace_for_policy(db, policy.id, odrl.index_terms(policy.body or {}))

    # ------------------------------------------------------------------- CRUD

    def create(self, db: Session, kind: str, payload: Any, current_user: Optional[str],
               can_manage_subject: Optional[Callable[[Any], bool]] = None) -> Any:
        spec = self.spec(kind)
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        fields: Dict[str, Any] = {
            "name": data["name"],
            "description": data.get("description"),
            "status": STATUS_DRAFT,
            "version": data.get("version") or "1.0.0",
            "owner_team_id": data.get("owner_team_id"),
            "project_id": data.get("project_id"),
            "draft_owner_id": current_user if data.get("personal_draft") else None,
            "created_by": current_user,
            "updated_by": current_user,
        }
        if kind == KIND_POLICY:
            ptype = data.get("policy_type") or "Set"
            if ptype not in odrl.POLICY_TYPES:
                raise AccessPolicyError(f"Unsupported policy type '{ptype}'")
            conflict = data.get("conflict") or odrl.DEFAULT_AUTHORED_CONFLICT
            if conflict not in odrl.CONFLICT_TERMS:
                raise AccessPolicyError(f"Unknown conflict strategy '{conflict}'")
            fields.update(self._subject(db, ptype, data.get("subject_entity_type"), data.get("subject_entity_id"),
                                        can_manage_subject))
            fields.update({
                "policy_type": ptype, "conflict": conflict,
                "inherit_from": data.get("inherit_from") or [],
                "body": self._normalize_rules(ptype, conflict, data.get("inherit_from") or [], data.get("rules") or {}),
            })
        else:
            fields.update({"members": _clean_members(data.get("members")),
                           "refinement": [odrl.normalize_constraint(c) for c in data.get("refinement") or []]})
        row = repo_for(kind).create(db, obj_in=fields)
        if kind == KIND_POLICY:
            self._rebuild_index(db, row)
        self._set_domains(db, kind, row.id, data.get("domain_ids") or [], data.get("primary_domain_id"), current_user)
        self._set_tags(db, kind, row.id, data.get("tags"), current_user)
        self._log_timeline(db, kind, row.id, f"{spec.label} created (version {row.version}, draft).", current_user)
        db.flush()
        return row

    @staticmethod
    def _subject(db: Session, policy_type: Optional[str], entity_type: Optional[str], entity_id: Optional[str],
                 can_manage: Optional[Callable[[Any], bool]] = None) -> Dict[str, Optional[str]]:
        """Validate the entity a policy is about: Offers only, the entity must exist, and the caller
        must be allowed to state its terms (``can_manage(product)``; omitted = not re-checked)."""
        if not entity_type and not entity_id:
            return {"subject_entity_type": None, "subject_entity_id": None}
        from src.models.access_policies import SUBJECT_ENTITY_TYPES
        if policy_type != "Offer":
            raise AccessPolicyError("Only an Offer can state the terms for an entity")
        if entity_type not in SUBJECT_ENTITY_TYPES or not entity_id:
            raise AccessPolicyError(f"A policy subject needs a type ({', '.join(SUBJECT_ENTITY_TYPES)}) and an id")
        from src.repositories.data_products_repository import data_product_repo
        product = data_product_repo.get(db, entity_id)
        if product is None:
            raise AccessPolicyError(f"Data product '{entity_id}' not found", 404)
        if can_manage is not None and not can_manage(product):
            raise AccessPolicyError("Only the product's owners (owner team / project) or an admin can state its "
                                    "terms of use", 403)
        return {"subject_entity_type": entity_type, "subject_entity_id": entity_id}

    def offers_for(self, db: Session, entity_type: str, entity_id: str, *, active_only: bool = True) -> List[AccessPolicyDb]:
        """Offers (terms of use) stated for an entity; with inactive ones, one row per version family."""
        rows = repo_for(KIND_POLICY).list_offers_for(db, entity_type, entity_id, active_only=active_only)
        return rows if active_only else collapse_by_family(rows, elevated_family_ids=set(), is_admin=True)

    def get(self, db: Session, kind: str, entity_id: str) -> Optional[Any]:
        return repo_for(kind).get(db, entity_id)

    def require(self, db: Session, kind: str, entity_id: str) -> Any:
        row = self.get(db, kind, entity_id)
        if not row:
            raise AccessPolicyError(f"{self.spec(kind).label} not found", 404)
        return row

    def require_visible(self, db: Session, kind: str, entity_id: str, viewer: Optional[str], is_admin: bool) -> Any:
        """Like :meth:`require`, but other users' personal drafts are reported as not found."""
        row = self.require(db, kind, entity_id)
        if not self._visible(row, viewer, is_admin):
            raise AccessPolicyError(f"{self.spec(kind).label} not found", 404)
        return row

    def list(self, db: Session, kind: str, *, include_history: bool = False, status: Optional[str] = None,
             viewer: Optional[str] = None, is_admin: bool = False) -> List[Any]:
        rows = [r for r in repo_for(kind).list_all(db) if self._visible(r, viewer, is_admin)]
        if status:
            rows = [r for r in rows if r.status == status]
        if include_history:
            return rows
        counts = family_counts(rows)
        collapsed = collapse_by_family(rows, elevated_family_ids=set(), is_admin=True)
        for r in collapsed:
            r._version_count = counts.get(r.version_family_id or r.id, 1)
        return collapsed

    def update(self, db: Session, kind: str, entity_id: str, payload: Any, current_user: Optional[str],
               can_manage_subject: Optional[Callable[[Any], bool]] = None) -> Any:
        row = self.require(db, kind, entity_id)
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
        content_keys = {"rules", "policy_type", "conflict", "inherit_from", "members", "refinement",
                        "subject_entity_type", "subject_entity_id"}
        if content_keys & set(data) and row.status not in EDITABLE_STATUSES:
            raise AccessPolicyError(
                f"A {row.status} {self.spec(kind).label.lower()} can't be edited — create a new version instead.", 409)
        for f in ("name", "description", "owner_team_id", "project_id", "change_summary"):
            if f in data:
                setattr(row, f, data[f])
        if kind == KIND_POLICY:
            if "policy_type" in data and data["policy_type"]:
                if data["policy_type"] not in odrl.POLICY_TYPES:
                    raise AccessPolicyError(f"Unsupported policy type '{data['policy_type']}'")
                row.policy_type = data["policy_type"]
            if "conflict" in data and data["conflict"]:
                if data["conflict"] not in odrl.CONFLICT_TERMS:
                    raise AccessPolicyError(f"Unknown conflict strategy '{data['conflict']}'")
                row.conflict = data["conflict"]
            if "inherit_from" in data and data["inherit_from"] is not None:
                row.inherit_from = data["inherit_from"]
            if {"subject_entity_type", "subject_entity_id", "policy_type"} & set(data):
                new_type, new_id = (data.get("subject_entity_type", row.subject_entity_type),
                                    data.get("subject_entity_id", row.subject_entity_id))
                if row.policy_type != "Offer":
                    new_type = new_id = None  # Only Offers state terms for an entity.
                changed = (new_type, new_id) != (row.subject_entity_type, row.subject_entity_id)
                subj = self._subject(db, row.policy_type, new_type, new_id, can_manage_subject if changed else None)
                row.subject_entity_type, row.subject_entity_id = subj["subject_entity_type"], subj["subject_entity_id"]
            if "rules" in data and data["rules"] is not None:
                row.body = self._normalize_rules(row.policy_type, row.conflict, row.inherit_from or [], data["rules"])
            self._rebuild_index(db, row)
        else:
            if "members" in data and data["members"] is not None:
                row.members = _clean_members(data["members"])
            if "refinement" in data and data["refinement"] is not None:
                row.refinement = [odrl.normalize_constraint(c) for c in data["refinement"]]
        row.updated_by = current_user
        if "domain_ids" in data:
            self._set_domains(db, kind, row.id, data.get("domain_ids") or [], data.get("primary_domain_id"), current_user)
        self._set_tags(db, kind, row.id, data.get("tags"), current_user)
        db.add(row)
        db.flush()
        return row

    def delete(self, db: Session, kind: str, entity_id: str, current_user: Optional[str]) -> None:
        row = self.require(db, kind, entity_id)
        if row.status not in DELETABLE_STATUSES:
            raise AccessPolicyError(
                f"Only draft or retired versions can be deleted (this one is {row.status}).", 409)
        if kind != KIND_POLICY:
            users = self.policies_referencing(db, row.uid)
            live = [p for p in users if p.status not in (STATUS_RETIRED,)]
            if live and len(repo_for(kind).get_family_versions(db, family_id=row.version_family_id)) <= 1:
                raise AccessPolicyError(
                    f"Still referenced by {len(live)} policy version(s): " + ", ".join(p.name for p in live[:5]), 409)
        entity_domain_repo.set_domains_for_entity(
            db, entity_type=self.spec(kind).entity_type, entity_id=row.id, domain_ids=[], assigned_by=current_user)
        repo_for(kind).remove(db, id=row.id)

    def policies_referencing(self, db: Session, uid: str) -> List[AccessPolicyDb]:
        ids = access_policy_index_repo.policy_ids_for_value(db, uid)
        return repo_for(KIND_POLICY).list_by_ids(db, ids)

    # ------------------------------------------------------------- versioning

    def versions(self, db: Session, kind: str, entity_id: str) -> List[Any]:
        row = self.require(db, kind, entity_id)
        return repo_for(kind).get_family_versions(db, family_id=row.version_family_id or row.id)

    def create_new_version(self, db: Session, kind: str, entity_id: str, new_version: str,
                           change_summary: Optional[str], current_user: Optional[str]) -> Any:
        src = self.require(db, kind, entity_id)
        family = repo_for(kind).get_family_versions(db, family_id=src.version_family_id or src.id)
        if any(v.version == new_version for v in family):
            raise AccessPolicyError(f"Version {new_version} already exists in this family", 409)
        fields = {f: getattr(src, f) for f in _LIFECYCLE_COPY + _KIND_COPY[kind]}
        fields.update({
            "status": STATUS_DRAFT, "version": new_version, "change_summary": change_summary,
            "version_family_id": src.version_family_id or src.id, "parent_id": src.id,
            "created_by": current_user, "updated_by": current_user,
        })
        row = repo_for(kind).create(db, obj_in=fields)
        if kind == KIND_POLICY:
            self._rebuild_index(db, row)
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=self.spec(kind).entity_type, entity_id=src.id)
        if domains:
            primary = next((d.domain_id for d in domains if getattr(d, "is_primary", False)), None)
            self._set_domains(db, kind, row.id, [str(d.domain_id) for d in domains],
                              str(primary) if primary else None, current_user)
        try:
            from src.controller.tags_manager import TagsManager
            from src.models.tags import AssignedTagCreate
            tm = TagsManager()
            tags = tm.list_assigned_tags(db, entity_id=src.id, entity_type=self.spec(kind).entity_type)
            if tags:
                tm.set_tags_for_entity(
                    db, entity_id=row.id, entity_type=self.spec(kind).entity_type, user_email=current_user,
                    tags=[AssignedTagCreate(tag_id=t.tag_id, assigned_value=t.assigned_value) for t in tags])
        except Exception as e:  # pragma: no cover - best-effort
            logger.warning(f"Could not copy tags to new version {row.id}: {e}")
        self._log_timeline(db, kind, row.id, f"Version {new_version} created from {src.version}."
                           + (f" {change_summary}" if change_summary else ""), current_user)
        self._log_timeline(db, kind, src.id, f"New version {new_version} drafted.", current_user)
        db.flush()
        return row

    # --------------------------------------------------------------- lifecycle

    def change_status(self, db: Session, kind: str, entity_id: str, new_status: str,
                      current_user: Optional[str], comment: Optional[str] = None, *, is_admin: bool = False) -> Any:
        row = self.require(db, kind, entity_id)
        allowed = TRANSITIONS.get(row.status, ())
        if new_status not in allowed:
            raise AccessPolicyError(
                f"Can't move from {row.status} to {new_status} (allowed: {', '.join(allowed) or 'none'}).", 409)
        if new_status == STATUS_APPROVED and not is_admin:
            # Separation of duties: whoever submitted (or authored) a version can't approve it.
            me = (current_user or "").lower()
            authors = {(row.submitted_by or "").lower(), (row.created_by or "").lower()} - {""}
            if not me or me in authors:
                raise AccessPolicyError(
                    "A version can't be approved by its author or submitter — ask another steward.", 403)
        if new_status == STATUS_ACTIVE:
            problems = self.activation_problems(db, kind, row)
            if problems:
                raise AccessPolicyError("Not ready to activate: " + "; ".join(problems), 409, details=problems)
        if new_status in (STATUS_DEPRECATED, STATUS_RETIRED) and kind != KIND_POLICY:
            # Taking an audience/collection out of service silently disables every rule that uses it.
            live = [p for p in self.policies_referencing(db, row.uid) if p.status == STATUS_ACTIVE]
            if live and not self._other_active_version(db, kind, row):
                raise AccessPolicyError(
                    "Still used by active policies (deprecate or re-point them first): "
                    + ", ".join(p.name for p in live[:5]), 409)
        old = row.status
        row.status = new_status
        row.updated_by = current_user
        if new_status == STATUS_UNDER_REVIEW:
            row.submitted_by = current_user
        elif new_status == STATUS_APPROVED:
            row.approved_by = current_user
        if new_status == STATUS_ACTIVE:
            row.draft_owner_id = None
            # One active version per family: the previously active one is deprecated.
            for v in repo_for(kind).get_family_versions(db, family_id=row.version_family_id):
                if v.id != row.id and v.status == STATUS_ACTIVE:
                    v.status = STATUS_DEPRECATED
                    db.add(v)
                    self._log_timeline(db, kind, v.id, f"Deprecated — superseded by version {row.version}.", current_user)
        db.add(row)
        db.flush()
        msg = f"Status changed from {old} to {new_status}."
        if comment:
            msg += f" {comment}"
        self._log_timeline(db, kind, row.id, msg, current_user)
        if new_status == STATUS_UNDER_REVIEW:
            self._fire_review_requested(db, kind, row, current_user, comment)
        return row

    def _other_active_version(self, db: Session, kind: str, row: Any) -> bool:
        return any(v.id != row.id and v.status == STATUS_ACTIVE
                   for v in repo_for(kind).get_family_versions(db, family_id=row.version_family_id))

    def activation_problems(self, db: Session, kind: str, row: Any) -> List[str]:
        if kind != KIND_POLICY:
            if kind == KIND_AUDIENCE and not row.members and not row.refinement:
                return ["An audience needs members or a refinement (an empty audience means everyone)"]
            if kind == KIND_ASSET_COLLECTION and not row.members and not row.refinement:
                return ["An asset collection needs members or a refinement"]
            return []
        problems = [i["message"] for i in self.validate_body(
            db, row.policy_type, row.conflict, row.inherit_from or [], row.body or {}) if i["severity"] == "error"]
        for ref_kind, prefix in ((KIND_AUDIENCE, odrl.AUDIENCE_IRI_PREFIX),
                                 (KIND_ASSET_COLLECTION, odrl.ASSET_COLLECTION_IRI_PREFIX)):
            for value in {v for _, _, v in odrl.index_terms(row.body or {}) if v.startswith(prefix)}:
                if not repo_for(ref_kind).get_active_by_uid(db, value):
                    problems.append(f"{KINDS[ref_kind].label} {value} has no active version")
        return problems

    def _fire_review_requested(self, db: Session, kind: str, row: Any, user: Optional[str], comment: Optional[str]) -> None:
        """Best-effort: fire the on_request_review workflow trigger for the entity."""
        try:
            from src.common.workflow_triggers import get_trigger_registry
            from src.models.process_workflows import EntityType
            get_trigger_registry(db).on_request_review(
                entity_type=EntityType.ACCESS_POLICY,
                entity_id=row.id,
                entity_name=row.name,
                entity_data={"kind": kind, "version": row.version, "message": comment, "requester": user},
                user_email=user,
                blocking=False,
            )
        except Exception as e:  # pragma: no cover - env dependent
            logger.warning(f"Could not fire review trigger for {kind} {row.id}: {e}")

    # ---------------------------------------------------------------- JSON-LD

    def to_jsonld(self, db: Session, policy: AccessPolicyDb) -> Dict[str, Any]:
        meta = {
            "dc:title": policy.name,
            "dc:description": policy.description,
            "dc:creator": policy.created_by,
            "dc:issued": policy.created_at.isoformat() if policy.created_at else None,
            "dc:modified": policy.updated_at.isoformat() if policy.updated_at else None,
            "ontos:version": policy.version,
            "ontos:status": policy.status,
        }
        doc = odrl.to_jsonld(uid=policy.uid, policy_type=policy.policy_type, conflict=policy.conflict,
                             rules=policy.body or {}, inherit_from=policy.inherit_from or [], metadata=meta)
        return doc

    def import_jsonld(self, db: Session, request: Any, current_user: Optional[str]) -> AccessPolicyDb:
        doc = request.document or {}
        norm = odrl.normalize_policy(doc)
        profile_errors = [i.message for i in odrl.validate_policy(norm) if "profile" in i.path]
        if profile_errors:
            raise AccessPolicyError(profile_errors[0])
        if norm["type"] not in odrl.POLICY_TYPES:
            raise AccessPolicyError(f"Unsupported policy type '{norm['type']}'")
        from src.models.access_policies import AccessPolicyCreate
        payload = AccessPolicyCreate(
            name=request.name or doc.get("dc:title") or doc.get("title") or norm.get("uid") or "Imported policy",
            description=request.description or doc.get("dc:description"),
            owner_team_id=request.owner_team_id, project_id=request.project_id, domain_ids=request.domain_ids,
            policy_type=norm["type"],
            # Imported policies keep their declared strategy; absent means the spec default.
            conflict=norm.get("conflict") or odrl.SPEC_DEFAULT_CONFLICT,
            inherit_from=norm.get("inheritFrom") or [],
            rules={k: norm[k] for k in odrl.RULE_KINDS},
        )
        row = self.create(db, KIND_POLICY, payload, current_user)
        if norm.get("uid"):
            self._log_timeline(db, KIND_POLICY, row.id, f"Imported from ODRL policy {norm['uid']}.", current_user)
        return row

    # ------------------------------------------------------------- evaluation

    def _collection_defs(self, db: Session, kind: str, *, prefer_active: bool = True) -> Dict[str, odrl.CollectionDef]:
        out: Dict[str, odrl.CollectionDef] = {}
        rows = repo_for(kind).list_all(db)
        by_uid: Dict[str, Any] = {}
        for r in rows:
            cur = by_uid.get(r.uid)
            if cur is None or (r.status == STATUS_ACTIVE and cur.status != STATUS_ACTIVE):
                by_uid[r.uid] = r
        for uid, r in by_uid.items():
            if prefer_active and r.status != STATUS_ACTIVE:
                continue
            out[uid] = odrl.CollectionDef(uid=uid, name=r.name, members=list(r.members or []),
                                          refinement=list(r.refinement or []))
        return out

    def _policy_doc(self, db: Session, policy: AccessPolicyDb) -> Tuple[Dict[str, Any], List[str]]:
        doc = {"uid": policy.uid, "name": f"{policy.name} v{policy.version}", "type": policy.policy_type,
               "conflict": policy.conflict, "profile": [odrl.ONTOS_PROFILE],
               "inheritFrom": policy.inherit_from or [], **(policy.body or {})}
        if not doc["inheritFrom"]:
            return doc, []

        def lookup(uid: str) -> Optional[Dict[str, Any]]:
            parent = repo_for(KIND_POLICY).get_active_by_uid(db, uid)
            if not parent:
                return None
            return {"uid": parent.uid, "type": parent.policy_type, "conflict": parent.conflict,
                    "profile": [odrl.ONTOS_PROFILE], "inheritFrom": parent.inherit_from or [], **(parent.body or {})}
        return odrl.resolve_inheritance(doc, lookup)

    def principal_attributes(self, db: Session, principal: str) -> Dict[str, List[str]]:
        attrs: Dict[str, List[str]] = {}
        for source in self.attribute_sources:
            try:
                for k, v in (source.attributes(db, principal) or {}).items():
                    attrs.setdefault(k, [])
                    attrs[k].extend(x for x in v if x not in attrs[k])
            except Exception as e:  # pragma: no cover - a failing source never breaks evaluation
                logger.warning(f"Principal attribute source {source.name} failed: {e}")
        return attrs

    def known_principals(self, db: Session) -> List[Tuple[str, Dict[str, List[str]]]]:
        """Every principal any attribute source knows, with its resolved attributes."""
        merged: Dict[str, Dict[str, List[str]]] = {}
        for source in self.attribute_sources:
            try:
                for p, attrs in (source.all_attributes(db) or {}).items():
                    target = merged.setdefault(p.lower(), {})
                    for k, v in attrs.items():
                        target.setdefault(k, [])
                        target[k].extend(x for x in v if x not in target[k])
            except Exception as e:  # pragma: no cover - a failing source never breaks compilation
                logger.warning(f"Principal attribute source {source.name} failed to enumerate: {e}")
        return sorted(merged.items())

    def check_access(self, db: Session, request: Any, *, viewer: Optional[str] = None, is_admin: bool = True) -> Dict[str, Any]:
        what_if = bool(request.policy_ids)
        if what_if:
            policies = [p for p in (repo_for(KIND_POLICY).get(db, pid) for pid in request.policy_ids)
                        if p and self._visible(p, viewer, is_admin)]
        else:
            policies = [p for p in repo_for(KIND_POLICY).list_all(db) if p.status == STATUS_ACTIVE]
        docs: List[Dict[str, Any]] = []
        warnings: List[str] = []
        for p in policies:
            doc, errs = self._policy_doc(db, p)
            warnings.extend(f"{p.name}: {e}" for e in errs)
            docs.append(doc)
        attrs = {k: list(v) if isinstance(v, list) else [v] for k, v in (request.principal_attributes or {}).items()}
        resolved: Dict[str, List[str]] = {}
        if request.resolve_business_roles:
            principal = request.principal.split(":", 1)[1] if request.principal.lower().startswith(("user:", "mailto:")) else request.principal
            resolved = self.principal_attributes(db, principal)
            for k, v in resolved.items():
                attrs.setdefault(k, [])
                attrs[k].extend(x for x in v if x not in attrs[k])
        resolver = odrl.Resolver(
            audiences=self._collection_defs(db, KIND_AUDIENCE, prefer_active=not what_if),
            asset_collections=self._collection_defs(db, KIND_ASSET_COLLECTION, prefer_active=not what_if),
        )
        req = odrl.AccessRequest(
            principal=request.principal, action=odrl.term_key(request.action) or request.action, asset=request.asset,
            principal_groups=list(request.principal_groups or []), principal_attributes=attrs,
            asset_attributes=dict(request.asset_attributes or {}), context=dict(request.context or {}),
            fulfilled_duties=[odrl.term_key(d) or d for d in request.fulfilled_duties or []],
        )
        decision = odrl.evaluate(docs, req, resolver).to_dict()
        decision.update({
            "evaluated_policies": [{"id": p.id, "uid": p.uid, "name": p.name, "version": p.version,
                                    "status": p.status} for p in policies],
            "resolved_principal_attributes": resolved,
            "warnings": warnings,
            "mode": "what_if" if what_if else "active",
        })
        return decision

    # ------------------------------------------------------------ read model

    @staticmethod
    def prefetch_subject_names(db: Session, rows: List[Any]) -> None:
        """One query for the subject names of many rows (list views), cached on the rows."""
        from src.db_models.data_products import DataProductDb
        ids = {r.subject_entity_id for r in rows
               if getattr(r, "subject_entity_type", None) == "data_product" and r.subject_entity_id}
        names = dict(db.query(DataProductDb.id, DataProductDb.name).filter(DataProductDb.id.in_(ids)).all()) if ids else {}
        for r in rows:
            if hasattr(r, "subject_entity_id"):
                r._subject_name = names.get(r.subject_entity_id)

    @staticmethod
    def _subject_name(db: Session, row: Any) -> Optional[str]:
        if row.subject_entity_type != "data_product" or not row.subject_entity_id:
            return None
        if hasattr(row, "_subject_name"):
            return row._subject_name
        from src.repositories.data_products_repository import data_product_repo
        dp = data_product_repo.get(db, row.subject_entity_id)
        return dp.name if dp else None

    def to_read_dict(self, db: Session, kind: str, row: Any) -> Dict[str, Any]:
        spec = self.spec(kind)
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=spec.entity_type, entity_id=row.id)
        tags: List[Dict[str, Any]] = []
        try:
            from src.controller.tags_manager import TagsManager
            for t in TagsManager().list_assigned_tags(db, entity_id=row.id, entity_type=spec.entity_type):
                tags.append(t.model_dump(mode="json") if hasattr(t, "model_dump") else dict(t))
        except Exception as e:  # pragma: no cover - best-effort
            logger.warning(f"Could not read tags for {kind} {row.id}: {e}")
        out: Dict[str, Any] = {
            "id": row.id, "kind": kind, "entity_type": spec.entity_type, "uid": row.uid,
            "name": row.name, "description": row.description, "status": row.status,
            "allowed_transitions": list(TRANSITIONS.get(row.status, ())),
            "editable": row.status in EDITABLE_STATUSES,
            "version": row.version, "version_family_id": row.version_family_id,
            "parent_id": row.parent_id, "change_summary": row.change_summary,
            "draft_owner_id": row.draft_owner_id,
            "version_count": getattr(row, "_version_count", None),
            "owner_team_id": row.owner_team_id, "project_id": row.project_id,
            "maturity_level_order": row.maturity_level_order,
            "domains": [d.dict() if hasattr(d, "dict") else d for d in domains],
            "tags": tags,
            "created_by": row.created_by, "updated_by": row.updated_by,
            "submitted_by": row.submitted_by, "approved_by": row.approved_by,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }
        if kind == KIND_POLICY:
            body = row.body or {}
            out.update({
                "policy_type": row.policy_type, "conflict": row.conflict,
                "access_grant_id": row.access_grant_id,
                "subject_entity_type": row.subject_entity_type, "subject_entity_id": row.subject_entity_id,
                "subject_name": self._subject_name(db, row),
                "inherit_from": row.inherit_from or [], "rules": body,
                "rule_counts": {k: len(body.get(k) or []) for k in odrl.RULE_KINDS},
            })
        else:
            out.update({"members": row.members or [], "refinement": row.refinement or []})
            out["used_by"] = [{"id": p.id, "name": p.name, "version": p.version, "status": p.status}
                              for p in self.policies_referencing(db, row.uid)]
        return out


def _clean_members(members: Optional[List[str]]) -> List[str]:
    seen: List[str] = []
    for m in members or []:
        m = (m or "").strip()
        if m and m not in seen:
            seen.append(m)
    return seen
