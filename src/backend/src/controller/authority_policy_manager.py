"""Policy reference manager (ARF justification metadata, ARF 1.2.0, #1294 batch 5).

A Policy reference is the source document an Authority Relation's authority rests
on, carried as metadata: name, external id, description, version, validity window,
an optional link out and the owner team. Ontos does not read the document, and
nothing about a reference is enforced: a draft, expired or superseded reference
does not change what an AR decides, and it does not gate activation. The AR's
approvers check the document themselves.

Validity is exposed to Compliance Checks (``policy_ref.*`` in the evaluation
object, see :func:`policy_ref_view`) so an author can add a check that enforces
it at resolve, or run one on a schedule.

Versions: a new version is a new record in the same family (``version_family_id``)
that points at the one it replaces (``parent_policy_id``). Many ARs can cite one
reference; the reference lists them (the cited-by list), and a reference cited by
an AR version can't be deleted.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.authority_rule import UNCITED_POLICY_REF
from src.common.logging import get_logger
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.db_models.authority_policy import AuthorityPolicyDb
from src.db_models.authority_resolution import AuthorityRelationDb
from src.db_models.teams import TeamDb
from src.repositories.authority_policy_repository import authority_policy_repo

logger = get_logger(__name__)

ENTITY_TYPE = "authority_policy"
FEATURE_ID = "authority-resolution"

# A new version starts with its own validity window; the rest is carried over.
_COPY_FIELDS = ("policy_key", "title", "summary", "owner_team_id", "url", "clauses")
_EDITABLE = ("title", "summary", "owner_team_id", "url", "valid_from", "valid_to", "clauses")


class AuthorityPolicyError(CodedValueError):
    """A reference the author must fix; the message says what. Coded for the UI."""

    code = "authority_policy_invalid"
    http_status = 400


class AuthorityPolicyNotFoundError(AuthorityPolicyError):
    code = "authority_policy_not_found"
    http_status = 404


class AuthorityPolicyConflictError(AuthorityPolicyError):
    """A change that the reference's current state refuses (409)."""

    code = "authority_policy_conflict"
    http_status = 409


class AuthorityPolicyInUseError(AuthorityPolicyConflictError):
    code = "authority_policy_in_use"


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
    """Clause labels (unique, non-empty ``ref``) in their stored shape."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in clauses or []:
        if hasattr(c, "model_dump"):
            c = c.model_dump()
        if not isinstance(c, dict):
            raise AuthorityPolicyError("Each clause must be an object with a 'ref'.")
        ref = str(c.get("ref") or "").strip()
        if not ref:
            raise AuthorityPolicyError("Each clause needs a reference (e.g. '§7.1').")
        if ref.casefold() in seen:
            raise AuthorityPolicyError(f"Clause '{ref}' appears twice.", ref=ref)
        seen.add(ref.casefold())
        clause: Dict[str, Any] = {"ref": ref}
        for k in ("title", "text"):
            v = str(c.get(k) or "").strip()
            if v:
                clause[k] = v
        out.append(clause)
    return out


def policy_ref_from_citation(citation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The ``policy_ref`` view of a citation already loaded for this resolve (no second lookup)."""
    if not citation or "policy_key" not in citation:
        return dict(UNCITED_POLICY_REF)
    return {
        "cited": True,
        "valid_from": citation.get("valid_from"),
        "valid_to": citation.get("valid_to"),
        "expired": bool(citation.get("expired")),
    }


def _rule_clauses(rule: Any) -> List[str]:
    """Clause labels cited on an AR rule's constraints, duties and prohibitions."""
    if not isinstance(rule, dict):
        return []
    perm = rule.get("permission") or {}
    items = list(perm.get("constraint") or []) + list(perm.get("duty") or []) + list(rule.get("prohibition") or [])
    return [str(i["clause"]) for i in items if isinstance(i, dict) and i.get("clause")]


def policy_ref_view(policy: Optional[AuthorityPolicyDb], at: Optional[datetime] = None) -> Dict[str, Any]:
    """What Compliance Checks see as ``policy_ref`` (ARF 1.2.0).

    ``cited`` is False when no reference is cited, so a check that requires one
    fails with its own message. ``expired`` is computed at ``at`` (default now) and
    is False without a reference or without a ``valid_to``. Nothing here is enforced
    by the reference itself.
    """
    if policy is None:
        return dict(UNCITED_POLICY_REF)
    end = _aware(policy.valid_to)
    at = _aware(at) or utcnow()
    return {
        "cited": True,
        "valid_from": _iso(policy.valid_from),
        "valid_to": _iso(policy.valid_to),
        "expired": bool(end is not None and at >= end),
    }


def _check_window(valid_from: Any, valid_to: Any) -> None:
    start, end = _aware(valid_from), _aware(valid_to)
    if start and end and end <= start:
        raise AuthorityPolicyError("valid_to must be after valid_from.")


def _check_url(url: Optional[str]) -> Optional[str]:
    """Only http(s) links: the link is rendered as an anchor, so no other scheme."""
    value = (url or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AuthorityPolicyError("The link must be an http or https URL.", field="url")
    return value


class AuthorityPolicyManager(SearchableAsset):
    """Stateless. Reads and writes references; ARs read them through :meth:`citation`."""

    # ------------------------------------------------------------ search

    @staticmethod
    def _search_id(family_id: str) -> str:
        return f"authority-policy::{family_id}"

    def _build_search_index_item(self, db: Session, policy: AuthorityPolicyDb) -> Optional[SearchIndexItem]:
        if not getattr(policy, "id", None):
            return None
        family_id = policy.version_family_id or policy.id
        return SearchIndexItem(
            id=self._search_id(family_id),
            type="authority-policy",
            feature_id=FEATURE_ID,
            title=f"{policy.policy_key} — {policy.title}",
            description=policy.summary or "",
            link=f"/authority-resolution/policies/{policy.id}",
            tags=self._tag_names(db, policy.id),
            extra_data={
                "version": policy.version,
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
            logger.debug("Failed to refresh search entry for policy family %s: %s", family_id, e)

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
            logger.error("Error preparing Policy references for search: %s", e, exc_info=True)
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
            logger.warning("Could not set tags for policy %s: %s", policy_id, e)

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
            logger.warning("Could not write timeline comment for %s %s: %s", entity_type, entity_id, e)

    @staticmethod
    def _representative(versions: List[AuthorityPolicyDb]) -> Optional[AuthorityPolicyDb]:
        """The version a list shows for a family: the newest one."""
        return versions[0] if versions else None

    @staticmethod
    def _validate_fields(data: Dict[str, Any]) -> None:
        _check_window(data.get("valid_from"), data.get("valid_to"))
        if "url" in data:
            data["url"] = _check_url(data["url"])

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
            raise AuthorityPolicyNotFoundError("Policy reference not found.")
        return authority_policy_repo.get_family_versions(db, family_id=policy.version_family_id or policy.id)

    def create_policy(self, db: Session, payload, current_user: Optional[str] = None) -> AuthorityPolicyDb:
        data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        self._validate_fields(data)
        key = str(data["policy_key"]).strip()
        if any(p.policy_key == key for p in authority_policy_repo.list_all(db)):
            raise AuthorityPolicyConflictError(
                f"A reference with the external id '{key}' already exists; create a new version of it instead.",
                policy_key=key,
            )
        pid = str(uuid.uuid4())
        policy = authority_policy_repo.create(db, obj_in={
            "id": pid,
            "policy_key": key,
            "version": str(data.get("version") or "1").strip(),
            "version_family_id": pid,
            "title": data["title"].strip(),
            "summary": data.get("summary"),
            "owner_team_id": data.get("owner_team_id") or None,
            "url": data.get("url"),
            "valid_from": data.get("valid_from"),
            "valid_to": data.get("valid_to"),
            "clauses": normalize_clauses(data.get("clauses")),
            "created_by": current_user,
        })
        self._set_tags(db, pid, data.get("tags"), current_user)
        self._reindex(db, policy)
        return policy

    def update_policy(self, db: Session, policy_id: str, payload, current_user: Optional[str] = None) -> Optional[AuthorityPolicyDb]:
        """Corrections to a reference. A changed document is a new version (create_new_version)."""
        policy = authority_policy_repo.get(db, policy_id)
        if not policy:
            return None
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
        tags = data.pop("tags", None)
        merged = {k: getattr(policy, k) for k in ("valid_from", "valid_to")}
        merged.update({k: data[k] for k in ("valid_from", "valid_to") if k in data})
        self._validate_fields(merged)
        if "clauses" in data:
            data["clauses"] = normalize_clauses(data["clauses"])
        if "url" in data:
            data["url"] = _check_url(data["url"])
        update = {k: v for k, v in data.items() if k in _EDITABLE}
        if "title" in update and update["title"]:
            update["title"] = update["title"].strip()
        policy = authority_policy_repo.update(db, db_obj=policy, obj_in=update)
        self._set_tags(db, policy.id, tags, current_user)
        self._reindex(db, policy)
        return policy

    def delete_policy(self, db: Session, policy_id: str) -> bool:
        """Delete a reference that no AR version cites. Raises :class:`AuthorityPolicyError`."""
        policy = authority_policy_repo.get(db, policy_id)
        if not policy:
            return False
        citing = authority_policy_repo.list_citing_relations(db, policy_ids=[policy.id])
        if citing:
            names = ", ".join(sorted({r.name for r in citing}))
            raise AuthorityPolicyInUseError(
                f"The reference is cited by {names}; remove those citations first.",
                cited_by=sorted({r.name for r in citing}),
            )
        family_id = policy.version_family_id or policy.id
        others = [v for v in authority_policy_repo.get_family_versions(db, family_id=family_id) if v.id != policy.id]
        if others and policy.id == family_id:
            raise AuthorityPolicyConflictError(
                "This is the first version of its family; delete the newer versions first.",
            )
        # Successors keep their lineage pointing at what this version derived from.
        for child in authority_policy_repo.list_children(db, policy_id=policy.id):
            child.parent_policy_id = policy.parent_policy_id
        self._set_tags(db, policy.id, [], None)
        authority_policy_repo.remove(db, id=policy.id)
        db.flush()
        if others:
            self._reindex(db, others[0])
        else:
            self._notify_index_remove(self._search_id(family_id))
        return True

    def create_new_version(
        self, db: Session, policy_id: str, new_version: str,
        change_summary: Optional[str] = None, current_user: Optional[str] = None,
    ) -> Optional[AuthorityPolicyDb]:
        """A new record for a new version of the source document (``parent_policy_id`` = the source)."""
        source = authority_policy_repo.get(db, policy_id)
        if not source:
            return None
        family_id = source.version_family_id or source.id
        new_version = new_version.strip()
        if any(v.version == new_version for v in authority_policy_repo.get_family_versions(db, family_id=family_id)):
            raise AuthorityPolicyConflictError(
                f"Version {new_version} already exists for {source.policy_key}.",
                version=new_version,
            )
        fields = {f: getattr(source, f) for f in _COPY_FIELDS}
        fields.update({
            "id": str(uuid.uuid4()),
            "version": new_version,
            "version_family_id": family_id,
            "parent_policy_id": source.id,
            "change_summary": change_summary,
            "valid_from": None,
            "valid_to": None,
            "created_by": current_user,
        })
        policy = authority_policy_repo.create(db, obj_in=fields)
        tags = self._tag_names(db, source.id)
        if tags:
            self._set_tags(db, policy.id, [{"fully_qualified_name": t} for t in tags], current_user)
        self._reindex(db, policy)
        return policy

    # ------------------------------------------------------------- reads

    def dependents(self, db: Session, policy_id: str) -> List[Dict[str, Any]]:
        """The cited-by list: Authority Relations (any version) citing this reference."""
        return [{
            "id": r.id, "name": r.name, "version": r.version, "status": r.status,
            "clause_refs": r.policy_clause_refs or [],
        } for r in authority_policy_repo.list_citing_relations(db, policy_ids=[policy_id])]

    def policy_ref(self, db: Session, relation: AuthorityRelationDb, at: Optional[datetime] = None) -> Dict[str, Any]:
        """The ``policy_ref`` the checks see for this AR's reference, computed now (or at ``at``)."""
        policy_id = getattr(relation, "authority_policy_id", None)
        policy = authority_policy_repo.get(db, policy_id) if policy_id else None
        return policy_ref_view(policy, at)

    def citation(self, db: Session, relation: AuthorityRelationDb) -> Optional[Dict[str, Any]]:
        """What an AR cites, for its read view and decision provenance (no documents)."""
        if not getattr(relation, "authority_policy_id", None):
            return None
        policy = authority_policy_repo.get(db, relation.authority_policy_id)
        out: Dict[str, Any] = {
            "authority_policy_id": relation.authority_policy_id,
            "clause_refs": list(relation.policy_clause_refs or []),
        }
        if policy is None:
            return out
        view = policy_ref_view(policy)
        out.update({
            "policy_key": policy.policy_key, "version": policy.version, "title": policy.title,
            "url": policy.url, "parent_policy_id": policy.parent_policy_id,
            # ISO strings: the citation is stored in decision provenance (JSON).
            "valid_from": view["valid_from"], "valid_to": view["valid_to"], "expired": view["expired"],
        })
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
        view = policy_ref_view(policy)
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
            "summary": policy.summary,
            "owner_team_id": policy.owner_team_id,
            "owner_team_name": self._team_name(db, policy.owner_team_id),
            "url": policy.url,
            "valid_from": _utc(policy.valid_from),
            "valid_to": _utc(policy.valid_to),
            "expired": view["expired"],
            "clauses": policy.clauses or [],
            "dependent_count": len(authority_policy_repo.list_citing_relations(db, policy_ids=[policy.id])),
            "tags": tags,
            "created_by": policy.created_by,
            "created_at": policy.created_at,
            "updated_at": policy.updated_at,
        }
