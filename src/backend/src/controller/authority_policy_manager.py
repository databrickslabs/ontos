"""Authority Policy manager (ARF justification basis).

An Authority Policy is the documented basis an Authority Relation derives its
authority from (ARF paper §3.7, ADM ``policy_authority_basis``). ARs cite one
policy *version* and the clauses they implement; checks cite the clause they
enforce. The resolver refuses (``no_authority``) when the cited policy is not
a valid root: missing, draft, withdrawn, not yet effective or expired (ADM
``POLICY_ROOT_MISSING``).

Lifecycle: ``draft`` → ``approved`` → ``superseded`` (a successor version was
approved; the old one stays valid until the successor takes effect) or
``withdrawn``. Only drafts are editable. Withdrawing a policy, or a policy
reaching its ``effective_to``, flips the active ARs citing it to
``needs_review``. Source documents are Metadata documents on the policy
(``entity_type = authority_policy``) and carry their SHA-256.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.db_models.authority_policy import AuthorityPolicyDb
from src.db_models.authority_resolution import AuthorityRelationDb
from src.db_models.teams import TeamDb
from src.repositories.authority_policy_repository import authority_policy_repo

logger = get_logger(__name__)

ENTITY_TYPE = "authority_policy"
FEATURE_ID = "authority-resolution"

POLICY_TYPES = ("DOA", "BOARD_MANDATE", "REGULATION", "PROCUREMENT_POLICY", "SOP", "EXCEPTION")

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_SUPERSEDED = "superseded"
STATUS_WITHDRAWN = "withdrawn"
POLICY_STATUSES = (STATUS_DRAFT, STATUS_APPROVED, STATUS_SUPERSEDED, STATUS_WITHDRAWN)
# Statuses a policy can be a valid root in (inside its effective window).
_ROOT_STATUSES = (STATUS_APPROVED, STATUS_SUPERSEDED)

# The effective window is set per version (at approval), so it isn't copied.
_COPY_FIELDS = (
    "policy_key", "title", "policy_type", "summary", "owner_team_id", "jurisdiction", "clauses",
)
_EDITABLE = (
    "title", "policy_type", "summary", "owner_team_id", "jurisdiction",
    "effective_from", "effective_to", "clauses",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Stored timestamps come back naive from SQLite and aware from Postgres."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    """In UTC, so a date shown from the ISO string is the date it was set to."""
    return _aware(dt).astimezone(timezone.utc) if dt else None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _utc(dt).isoformat() if dt else None


def normalize_clauses(clauses: Any) -> List[Dict[str, Any]]:
    """Validate clauses (unique, non-empty ``ref``) into their stored shape."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in clauses or []:
        if hasattr(c, "model_dump"):
            c = c.model_dump()
        if not isinstance(c, dict):
            raise ValueError("Each clause must be an object with a 'ref'.")
        ref = str(c.get("ref") or "").strip()
        if not ref:
            raise ValueError("Each clause needs a reference (e.g. '§7.1').")
        if ref.casefold() in seen:
            raise ValueError(f"Clause '{ref}' appears twice.")
        seen.add(ref.casefold())
        clause: Dict[str, Any] = {"ref": ref}
        for k in ("title", "text"):
            v = str(c.get(k) or "").strip()
            if v:
                clause[k] = v
        limits = {k: v for k, v in (c.get("limits") or {}).items() if v not in (None, "")}
        if limits:
            clause["limits"] = limits
        conditions = [str(x).strip() for x in c.get("conditions") or [] if str(x).strip()]
        if conditions:
            clause["conditions"] = conditions
        out.append(clause)
    return out


def clause_refs(policy: Optional[AuthorityPolicyDb]) -> List[str]:
    return [c.get("ref") for c in (getattr(policy, "clauses", None) or []) if c.get("ref")]


def policy_root_problem(policy: Optional[AuthorityPolicyDb], at: Optional[datetime] = None) -> Optional[str]:
    """Why ``policy`` can't ground an authority at ``at`` (default now), or None."""
    if policy is None:
        return "policy root missing"
    label = f"{policy.policy_key} v{policy.version}"
    if policy.status == STATUS_WITHDRAWN:
        return f"policy root withdrawn: {label}"
    if policy.status not in _ROOT_STATUSES:
        return f"policy root not approved: {label} is '{policy.status}'"
    at = _aware(at) or utcnow()
    start, end = _aware(policy.effective_from), _aware(policy.effective_to)
    if start is None or at < start:
        return f"policy root not yet effective: {label}"
    if end is not None and at >= end:
        return f"policy root expired: {label} ended {end.date().isoformat()}"
    return None


class AuthorityPolicyManager(SearchableAsset):
    """Stateless; ``relation_manager`` (the AR manager) flags dependent ARs."""

    def __init__(self, relation_manager: Optional[Any] = None):
        self.relation_manager = relation_manager

    # ------------------------------------------------------------ search

    @staticmethod
    def _search_id(family_id: str) -> str:
        return f"authority-policy::{family_id}"

    def _build_search_index_item(self, db: Session, policy: AuthorityPolicyDb) -> Optional[SearchIndexItem]:
        if not getattr(policy, "id", None):
            return None
        family_id = policy.version_family_id or policy.id
        clauses = " ".join(f"{c.get('ref')} {c.get('title') or ''}" for c in policy.clauses or [])
        return SearchIndexItem(
            id=self._search_id(family_id),
            type="authority-policy",
            feature_id=FEATURE_ID,
            title=f"{policy.policy_key} — {policy.title}",
            description=" ".join(x for x in (policy.summary or "", clauses) if x).strip(),
            link=f"/authority-resolution/policies/{policy.id}",
            tags=self._tag_names(db, policy.id),
            extra_data={
                "status": policy.status,
                "version": policy.version,
                "policy_type": policy.policy_type,
                "owner": self._team_name(db, policy.owner_team_id),
            },
        )

    def _reindex(self, db: Session, policy: Optional[AuthorityPolicyDb]) -> None:
        if policy is None:
            return
        family_id = policy.version_family_id or policy.id
        try:
            rep = self._representative(authority_policy_repo.get_family_versions(db, family_id=family_id))
            item = self._build_search_index_item(db, rep) if rep else None
            if item:
                self._notify_index_upsert(item)
            else:
                self._notify_index_remove(self._search_id(family_id))
        except Exception as e:  # pragma: no cover - index refresh is best-effort
            logger.debug(f"Failed to refresh search entry for policy family {family_id}: {e}")

    def get_search_index_items(self) -> List[SearchIndexItem]:
        from src.common.database import get_session_factory
        session_factory = get_session_factory()
        if not session_factory:
            return []
        items: List[SearchIndexItem] = []
        try:
            with session_factory() as db:
                for policy in self.list_policies(db):
                    item = self._build_search_index_item(db, policy)
                    if item:
                        items.append(item)
        except Exception as e:
            logger.error(f"Error preparing Authority Policies for search: {e}", exc_info=True)
        return items

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _team_name(db: Session, team_id: Optional[str]) -> Optional[str]:
        if not team_id:
            return None
        team = db.get(TeamDb, team_id)
        return getattr(team, "name", None) if team else None

    @staticmethod
    def _tag_names(db: Session, policy_id: str) -> List[str]:
        try:
            from src.controller.tags_manager import TagsManager
            return [t.fully_qualified_name for t in TagsManager().list_assigned_tags(
                db, entity_id=policy_id, entity_type=ENTITY_TYPE) if getattr(t, "fully_qualified_name", None)]
        except Exception:  # pragma: no cover - tags are best-effort
            return []

    def _set_tags(self, db: Session, policy_id: str, tags: Optional[List[Any]], user: Optional[str]) -> None:
        if tags is None:
            return
        try:
            from src.controller.tags_manager import TagsManager
            TagsManager().set_tags_for_entity(
                db, entity_id=policy_id, entity_type=ENTITY_TYPE, tags=list(tags), user_email=user,
            )
        except Exception as e:  # pragma: no cover - tag write is best-effort
            logger.warning(f"Could not set tags for policy {policy_id}: {e}")

    def _log_timeline(self, db: Session, entity_type: str, entity_id: str, message: str) -> None:
        """Best-effort system comment on the entity's Comments timeline."""
        try:
            from src.controller.comments_manager import CommentsManager
            from src.models.comments import CommentCreate
            CommentsManager().create_comment(
                db, data=CommentCreate(entity_type=entity_type, entity_id=entity_id, comment=message),
                user_email="system@ontos", is_admin=True,
            )
        except Exception as e:  # pragma: no cover - timeline logging is best-effort
            logger.warning(f"Could not write timeline comment for {entity_type} {entity_id}: {e}")

    @staticmethod
    def _representative(versions: List[AuthorityPolicyDb]) -> Optional[AuthorityPolicyDb]:
        """The version a list shows for a family: newest approved, else newest."""
        if not versions:
            return None
        return next((v for v in versions if v.status == STATUS_APPROVED), versions[0])

    @staticmethod
    def _validate_fields(data: Dict[str, Any]) -> None:
        ptype = data.get("policy_type")
        if ptype is not None and ptype not in POLICY_TYPES:
            raise ValueError(f"Unknown policy type '{ptype}'; expected one of {', '.join(POLICY_TYPES)}.")
        start, end = _aware(data.get("effective_from")), _aware(data.get("effective_to"))
        if start and end and end <= start:
            raise ValueError("effective_to must be after effective_from.")

    # -------------------------------------------------------------- CRUD

    def list_policies(self, db: Session, include_history: bool = False) -> List[AuthorityPolicyDb]:
        rows = authority_policy_repo.list_all(db)
        if include_history:
            return rows
        families: Dict[str, List[AuthorityPolicyDb]] = {}
        for r in sorted(rows, key=lambda r: _aware(r.created_at) or utcnow(), reverse=True):
            families.setdefault(r.version_family_id or r.id, []).append(r)
        out = []
        for versions in families.values():
            rep = self._representative(versions)
            rep._version_count = len(versions)
            out.append(rep)
        return sorted(out, key=lambda r: _aware(r.updated_at) or utcnow(), reverse=True)

    def get_policy(self, db: Session, policy_id: str) -> Optional[AuthorityPolicyDb]:
        return authority_policy_repo.get(db, policy_id)

    def get_versions(self, db: Session, policy_id: str) -> List[AuthorityPolicyDb]:
        policy = authority_policy_repo.get(db, policy_id)
        if not policy:
            raise ValueError("Authority Policy not found")
        return authority_policy_repo.get_family_versions(db, family_id=policy.version_family_id or policy.id)

    def create_policy(self, db: Session, payload, current_user: Optional[str] = None) -> AuthorityPolicyDb:
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        data["policy_type"] = data.get("policy_type") or "DOA"
        self._validate_fields(data)
        key = str(data["policy_key"]).strip()
        if any(p.policy_key == key for p in authority_policy_repo.list_all(db)):
            raise ValueError(f"A policy with key '{key}' already exists; create a new version of it instead.")
        pid = str(uuid.uuid4())
        policy = authority_policy_repo.create(db, obj_in={
            "id": pid,
            "policy_key": key,
            "version": str(data.get("version") or "1").strip(),
            "version_family_id": pid,
            "title": data["title"].strip(),
            "policy_type": data["policy_type"],
            "summary": data.get("summary"),
            "owner_team_id": data.get("owner_team_id") or None,
            "jurisdiction": data.get("jurisdiction"),
            "effective_from": data.get("effective_from"),
            "effective_to": data.get("effective_to"),
            "status": STATUS_DRAFT,
            "clauses": normalize_clauses(data.get("clauses")),
            "created_by": current_user,
        })
        self._set_tags(db, pid, data.get("tags"), current_user)
        self._reindex(db, policy)
        return policy

    def update_policy(self, db: Session, policy_id: str, payload, current_user: Optional[str] = None) -> Optional[AuthorityPolicyDb]:
        policy = authority_policy_repo.get(db, policy_id)
        if not policy:
            return None
        if policy.status != STATUS_DRAFT:
            raise PermissionError(
                f"Policy {policy.policy_key} v{policy.version} is {policy.status}; "
                "create a new version to change it."
            )
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
        tags = data.pop("tags", None)
        merged = {k: getattr(policy, k) for k in ("policy_type", "effective_from", "effective_to")}
        merged.update(data)
        self._validate_fields(merged)
        if "clauses" in data:
            data["clauses"] = normalize_clauses(data["clauses"])
            dropped = set(clause_refs(policy)) - {c["ref"] for c in data["clauses"]}
            cited = self._cited_refs(db, [policy.id]) & dropped
            if cited:
                raise ValueError(
                    f"Clause(s) {', '.join(sorted(cited))} are cited by Authority Relations; "
                    "remove the citations first."
                )
        update = {k: v for k, v in data.items() if k in _EDITABLE}
        if "title" in update and update["title"]:
            update["title"] = update["title"].strip()
        policy = authority_policy_repo.update(db, db_obj=policy, obj_in=update)
        self._set_tags(db, policy.id, tags, current_user)
        self._reindex(db, policy)
        return policy

    def delete_policy(self, db: Session, policy_id: str) -> bool:
        """Delete a draft or withdrawn version that no AR cites. Raises ``ValueError``."""
        policy = authority_policy_repo.get(db, policy_id)
        if not policy:
            return False
        if policy.status in _ROOT_STATUSES:
            raise ValueError("An approved policy can't be deleted; withdraw it first.")
        citing = authority_policy_repo.list_citing_relations(db, policy_ids=[policy.id])
        if citing:
            names = ", ".join(sorted({r.name for r in citing}))
            raise ValueError(f"The policy is cited by {names}; remove those citations first.")
        family_id = policy.version_family_id or policy.id
        others = [v for v in authority_policy_repo.get_family_versions(db, family_id=family_id) if v.id != policy.id]
        if others and policy.id == family_id:
            raise ValueError("This is the first version of its family; delete the newer versions first.")
        # Successors keep their lineage pointing at what this version derived from.
        for child in authority_policy_repo.list_children(db, policy_id=policy.id):
            child.parent_policy_id = policy.parent_policy_id
        from src.controller.metadata_manager import MetadataManager
        metadata = MetadataManager()
        _, paths = metadata.remove_all_for_entity(db, entity_type=ENTITY_TYPE, entity_id=policy.id)
        self._set_tags(db, policy.id, [], None)
        authority_policy_repo.remove(db, id=policy.id)
        db.flush()
        metadata.delete_document_files_after_commit(db, paths)
        if others:
            self._reindex(db, others[0])
        else:
            self._notify_index_remove(self._search_id(family_id))
        return True

    def create_new_version(
        self, db: Session, policy_id: str, new_version: str,
        change_summary: Optional[str] = None, current_user: Optional[str] = None,
    ) -> Optional[AuthorityPolicyDb]:
        """A draft successor (``wasDerivedFrom`` the source) with the source's clauses."""
        source = authority_policy_repo.get(db, policy_id)
        if not source:
            return None
        family_id = source.version_family_id or source.id
        new_version = new_version.strip()
        if any(v.version == new_version for v in authority_policy_repo.get_family_versions(db, family_id=family_id)):
            raise ValueError(f"Version {new_version} already exists for {source.policy_key}.")
        fields = {f: getattr(source, f) for f in _COPY_FIELDS}
        fields.update({
            "id": str(uuid.uuid4()),
            "version": new_version,
            "version_family_id": family_id,
            "parent_policy_id": source.id,
            "change_summary": change_summary,
            "status": STATUS_DRAFT,
            "created_by": current_user,
        })
        policy = authority_policy_repo.create(db, obj_in=fields)
        tags = self._tag_names(db, source.id)
        if tags:
            self._set_tags(db, policy.id, [{"fully_qualified_name": t} for t in tags], current_user)
        self._log_timeline(db, ENTITY_TYPE, policy.id,
                           f"Version {new_version} drafted from v{source.version}.")
        self._reindex(db, policy)
        return policy

    # --------------------------------------------------------- lifecycle

    def set_status(
        self, db: Session, policy_id: str, payload, current_user: Optional[str] = None,
    ) -> Tuple[Optional[AuthorityPolicyDb], Optional[str]]:
        """Approve or withdraw a policy version. Returns ``(policy, error)``."""
        policy = authority_policy_repo.get(db, policy_id)
        if not policy:
            return None, "not_found"
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
        status = data.get("status")
        if status == STATUS_APPROVED:
            return self._approve(db, policy, data, current_user)
        if status == STATUS_WITHDRAWN:
            return self._withdraw(db, policy, data.get("reason"), current_user)
        return policy, f"Status '{status}' can't be set directly; expected '{STATUS_APPROVED}' or '{STATUS_WITHDRAWN}'."

    def _approve(self, db: Session, policy: AuthorityPolicyDb, data: Dict[str, Any], user: Optional[str]):
        if policy.status != STATUS_DRAFT:
            return policy, f"Only a draft can be approved; this version is {policy.status}."
        if not policy.clauses:
            return policy, "A policy needs at least one clause before it can be approved."
        start = _aware(data.get("effective_from") or policy.effective_from)
        # An explicit null clears an end date the draft carries.
        end = _aware(data["effective_to"] if "effective_to" in data else policy.effective_to)
        if start is None:
            return policy, "Approval needs an effective date."
        if end is not None and end <= start:
            return policy, "effective_to must be after effective_from."
        approver = (data.get("approved_by") or user or "").strip()
        if not approver:
            return policy, "Approval needs an approver."
        evidence_id = data.get("approval_evidence_document_id") or policy.approval_evidence_document_id
        if evidence_id and not any(d["id"] == str(evidence_id) for d in self.documents(db, policy.id)):
            return policy, "The approval evidence must be a document attached to this policy."

        policy = authority_policy_repo.update(db, db_obj=policy, obj_in={
            "status": STATUS_APPROVED, "approved_by": approver, "approved_at": utcnow(),
            "effective_from": start, "effective_to": end,
            "approval_evidence_document_id": str(evidence_id) if evidence_id else None,
        })
        # ``approved_by`` names the approving person or body (it may differ from
        # who records it); the timeline keeps the authenticated recorder.
        recorder = f" (recorded by {user})" if user and user != approver else ""
        self._log_timeline(db, ENTITY_TYPE, policy.id,
                           f"Approved by {approver}{recorder}, effective {start.date().isoformat()}.")

        # One approved version per family: every other approved version is
        # superseded and stays a valid root until this one takes effect.
        family_id = policy.version_family_id or policy.id
        for older in authority_policy_repo.get_family_versions(db, family_id=family_id):
            if older.id == policy.id or older.status != STATUS_APPROVED:
                continue
            older_end = _aware(older.effective_to)
            new_end = start if older_end is None or older_end > start else older_end
            authority_policy_repo.update(db, db_obj=older, obj_in={
                "status": STATUS_SUPERSEDED, "effective_to": new_end,
            })
            self._log_timeline(db, ENTITY_TYPE, older.id,
                               f"Superseded by v{policy.version} from {start.date().isoformat()}.")
            label = f"{older.policy_key} v{older.version}"
            if new_end <= utcnow():
                # A backdated successor ends the old window now: flag at once.
                self._flag_dependents(db, [older], f"Cited policy {label} was superseded by "
                                      f"v{policy.version} (effective {start.date().isoformat()})")
                continue
            for rel in authority_policy_repo.list_citing_relations(db, policy_ids=[older.id]):
                self._log_timeline(
                    db, "authority_relation", rel.id,
                    f"Cited policy {label} is superseded by v{policy.version} from "
                    f"{start.date().isoformat()}; cite the new version before then, "
                    "or this Authority Relation loses its policy root.",
                )
        self._reindex(db, policy)
        return policy, None

    def _withdraw(self, db: Session, policy: AuthorityPolicyDb, reason: Optional[str], user: Optional[str]):
        if policy.status not in _ROOT_STATUSES:
            return policy, f"Only an approved or superseded policy can be withdrawn; this version is {policy.status}."
        policy = authority_policy_repo.update(db, db_obj=policy, obj_in={
            "status": STATUS_WITHDRAWN, "withdrawn_reason": (reason or "").strip() or None,
        })
        label = f"{policy.policy_key} v{policy.version}"
        self._log_timeline(db, ENTITY_TYPE, policy.id,
                           f"Withdrawn by {user or 'unknown'}" + (f": {reason.strip()}" if reason and reason.strip() else "."))
        self._flag_dependents(db, [policy], f"Cited policy {label} was withdrawn")
        self._reindex(db, policy)
        return policy, None

    def _flag_dependents(self, db: Session, policies: List[AuthorityPolicyDb], why: str) -> List[str]:
        """Active ARs citing ``policies`` → ``needs_review`` (with a timeline note)."""
        from src.repositories.authority_resolution_repository import authority_relation_repo
        flagged: List[str] = []
        for rel in authority_policy_repo.list_citing_relations(db, policy_ids=[p.id for p in policies]):
            if rel.status != "active":
                continue
            authority_relation_repo.update(db, db_obj=rel, obj_in={"status": "needs_review"})
            self._log_timeline(db, "authority_relation", rel.id,
                               f"{why}; status set to needs_review until it cites a valid policy.")
            flagged.append(rel.id)
            if self.relation_manager is not None:
                self.relation_manager._reindex(db, rel)
        return flagged

    def sweep_expired(self, db: Session, at: Optional[datetime] = None) -> Dict[str, Any]:
        """Flag active ARs whose cited policy has reached its ``effective_to``."""
        at = _aware(at) or utcnow()
        expired = [p for p in authority_policy_repo.list_all(db)
                   if p.status in _ROOT_STATUSES and p.effective_to is not None and _aware(p.effective_to) <= at]
        flagged: List[str] = []
        for p in expired:
            flagged += self._flag_dependents(
                db, [p], f"Cited policy {p.policy_key} v{p.version} expired on {_aware(p.effective_to).date().isoformat()}")
        return {"expired_policies": [p.id for p in expired], "flagged_relations": flagged}

    # ------------------------------------------------------------- reads

    def _cited_refs(self, db: Session, policy_ids: List[str]) -> set:
        """Clause refs the citing ARs (and their checks) use."""
        refs = set()
        for rel in authority_policy_repo.list_citing_relations(db, policy_ids=policy_ids):
            refs.update(rel.policy_clause_refs or [])
            refs.update(c.policy_clause_ref for c in rel.criteria or [] if getattr(c, "policy_clause_ref", None))
            refs.update(_rule_clauses(rel.rule))
        return refs

    def documents(self, db: Session, policy_id: str) -> List[Dict[str, Any]]:
        """The policy's source documents with their SHA-256 (the hashed evidence)."""
        from src.db_models.metadata import DocumentMetadataDb
        rows = (db.query(DocumentMetadataDb)
                .filter(DocumentMetadataDb.entity_type == ENTITY_TYPE, DocumentMetadataDb.entity_id == policy_id)
                .order_by(DocumentMetadataDb.created_at.asc()).all())
        return [{
            "id": str(d.id), "title": d.title, "filename": d.original_filename,
            "content_type": d.content_type, "size_bytes": d.size_bytes,
            "sha256": getattr(d, "content_sha256", None),
        } for d in rows]

    def dependents(self, db: Session, policy_id: str) -> List[Dict[str, Any]]:
        return [{
            "id": r.id, "name": r.name, "version": r.version, "status": r.status,
            "clause_refs": r.policy_clause_refs or [],
        } for r in authority_policy_repo.list_citing_relations(db, policy_ids=[policy_id])]

    def citation(self, db: Session, relation: AuthorityRelationDb, *, with_documents: bool = True) -> Optional[Dict[str, Any]]:
        """What an AR cites, for its read view and decision provenance."""
        if not getattr(relation, "authority_policy_id", None):
            return None
        policy = authority_policy_repo.get(db, relation.authority_policy_id)
        refs = list(relation.policy_clause_refs or [])
        out: Dict[str, Any] = {
            "authority_policy_id": relation.authority_policy_id, "clause_refs": refs,
            "problem": policy_root_problem(policy),
        }
        if policy is None:
            return out
        by_ref = {c.get("ref"): c for c in policy.clauses or []}
        out.update({
            "policy_key": policy.policy_key, "version": policy.version, "title": policy.title,
            "status": policy.status, "policy_type": policy.policy_type,
            # ISO strings: the citation is stored in decision provenance (JSON).
            "effective_from": _iso(policy.effective_from), "effective_to": _iso(policy.effective_to),
            "parent_policy_id": policy.parent_policy_id,
            "clauses": [by_ref[r] for r in refs if r in by_ref],
        })
        if with_documents:
            out["documents"] = [{"id": d["id"], "filename": d["filename"], "sha256": d["sha256"]}
                                for d in self.documents(db, policy.id)]
        return out

    def to_read_dict(self, db: Session, policy: AuthorityPolicyDb) -> Dict[str, Any]:
        parent = authority_policy_repo.get(db, policy.parent_policy_id) if policy.parent_policy_id else None
        tags = []
        try:
            from src.controller.tags_manager import TagsManager
            tags = [{"fully_qualified_name": getattr(t, "fully_qualified_name", None),
                     "assigned_value": getattr(t, "assigned_value", None)}
                    for t in TagsManager().list_assigned_tags(db, entity_id=policy.id, entity_type=ENTITY_TYPE)]
        except Exception:  # pragma: no cover - tags are best-effort
            pass
        return {
            "id": policy.id,
            "policy_key": policy.policy_key,
            "version": policy.version,
            "version_family_id": policy.version_family_id,
            "version_count": getattr(policy, "_version_count", None),
            "parent_policy_id": policy.parent_policy_id,
            "parent_version": parent.version if parent else None,
            "change_summary": policy.change_summary,
            "title": policy.title,
            "policy_type": policy.policy_type,
            "summary": policy.summary,
            "owner_team_id": policy.owner_team_id,
            "owner_team_name": self._team_name(db, policy.owner_team_id),
            "jurisdiction": policy.jurisdiction,
            "effective_from": _utc(policy.effective_from),
            "effective_to": _utc(policy.effective_to),
            "status": policy.status,
            "root_problem": policy_root_problem(policy),
            "approved_by": policy.approved_by,
            "approved_at": _utc(policy.approved_at),
            "approval_evidence_document_id": policy.approval_evidence_document_id,
            "withdrawn_reason": policy.withdrawn_reason,
            "clauses": policy.clauses or [],
            "documents": self.documents(db, policy.id),
            "dependent_count": len(authority_policy_repo.list_citing_relations(db, policy_ids=[policy.id])),
            "tags": tags,
            "created_by": policy.created_by,
            "created_at": policy.created_at,
            "updated_at": policy.updated_at,
        }


def _rule_clauses(rule: Any) -> List[str]:
    """Clause refs cited on an AR rule's constraints, duties and prohibitions."""
    if not isinstance(rule, dict):
        return []
    perm = rule.get("permission") or {}
    items = list(perm.get("constraint") or []) + list(perm.get("duty") or []) + list(rule.get("prohibition") or [])
    return [str(i["clause"]) for i in items if isinstance(i, dict) and i.get("clause")]
