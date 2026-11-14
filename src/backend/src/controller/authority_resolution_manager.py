"""Authority Resolution manager (ARF).

Owns the Authority Relation lifecycle, evidence-bound DNA-Coefficient
computation, the N-functional affirmation gate, and the deterministic runtime
resolution used by both the MCP tool and Ontos-native flows.

Design notes:
* The manager is a stateless singleton (mirrors ``ComplianceManager``); the DB
  session is passed per call.
* The DNAco scoring itself is a pure function in ``src.common.authority_resolution_dna`` so
  it is unit-testable without a DB or a warehouse. Evidence reading is
  best-effort and isolated in ``_read_evidence_rows``.
* Runtime resolution is deterministic — it evaluates request parameters against
  the AR's compiled ``decision_logic`` and never (re)computes the DNAco. The
  DNAco is an *activation-time* gate only.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.common import authority_resolution_dna as authority_dna
from src.common.authority_resolution_dna import Criterion, DIR_NONE
from src.common.compliance_dsl import evaluate_rule_on_object
from src.common import mcp_resolver
from src.common.mcp_resolver import Deadline, McpHttpClient, McpResolverError
from src.db_models.authority_resolution import (
    AuthorityRelationDb,
    AuthorityAffirmationDb,
    AuthorityDecisionDb,
    AuthorityDnaRunDb,
)
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.projects import ProjectDb
from src.db_models.teams import TeamDb
from src.repositories.authority_resolution_repository import (
    authority_relation_repo,
    authority_affirmation_repo,
    authority_criterion_repo,
    authority_dna_run_repo,
    authority_decision_repo,
    authority_prerequisite_repo,
    authority_resource_ref_repo,
)
from src.repositories.entity_domain_association_repository import entity_domain_repo

logger = get_logger(__name__)

ENTITY_TYPE = "authority_relation"
FEATURE_ID = "authority-resolution"  # search feature filter (common/features.py)

# Verdicts returned by the runtime gate.
VERDICT_APPROVED = "approved"
VERDICT_DENIED = "denied"
VERDICT_NO_AUTHORITY = "no_authority"
VERDICT_CONFLICT = "conflict"

# AR lifecycle statuses.
STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_RETIRED = "retired"

# Controlled vocabulary for the Action element (ARF §3.2 business domain).
ACTION_VOCAB = {"approve", "escalate", "override", "delegate", "veto"}

_MODEL_COLUMNS = {c.name for c in AuthorityRelationDb.__table__.columns}

RESOLVER_AUTH_OBO = "obo"
RESOLVER_AUTH_APP_SP = "app_sp"
_RESOLVER_AUTH_VALUES = (RESOLVER_AUTH_OBO, RESOLVER_AUTH_APP_SP)
RESOLVE_BUDGET_S = 10.0
# Criteria see each materialised ref as ``obj.ref_<field_path>``; callers may
# not supply keys in this namespace.
REF_KEY_PREFIX = "ref_"


def ref_key(field_path: str) -> str:
    return REF_KEY_PREFIX + re.sub(r"[^A-Za-z0-9_]", "_", field_path)


DEFAULT_DNA_CEILING = 0.3
_ALLOWED_STATUSES = ("draft", "active", "needs_review", "retired")

# Evidence SQL runs as the app service principal, so table names and row
# filters are restricted to a grammar that cannot reach other tables.
_FQN_PART = r"(?:[A-Za-z0-9_\-]+|`[^`]+`)"
_FQN_RE = re.compile(rf"^{_FQN_PART}(?:\.{_FQN_PART}){{0,2}}$")
_FILTER_TOKEN_RE = re.compile(
    r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?\d+(?:\.\d+)?)|(?P<op><>|!=|<=|>=|=|<|>)"
    r"|(?P<punct>[(),])|(?P<ident>`[^`]+`|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*))"
)
_FILTER_KEYWORDS = {"AND", "OR", "NOT", "IS", "NULL", "IN", "LIKE", "BETWEEN", "TRUE", "FALSE"}
_FILTER_FORBIDDEN = {
    "SELECT", "UNION", "FROM", "JOIN", "WITH", "INSERT", "UPDATE", "DELETE", "DROP", "CREATE",
    "ALTER", "GRANT", "REVOKE", "MERGE", "INTO", "TABLE", "VALUES", "CALL", "EXEC", "EXECUTE",
    "INTERSECT", "EXCEPT", "LATERAL", "USE", "SET", "SHOW", "DESCRIBE",
}


def validate_table_fqn(fqn: str) -> str:
    fqn = (fqn or "").strip()
    if not _FQN_RE.match(fqn):
        raise ValueError(f"Evidence table '{fqn}' must be a plain catalog.schema.table name.")
    return fqn


def validate_row_filter(row_filter: Optional[str]) -> Optional[str]:
    """Allow only simple predicates: columns, literals, comparison operators,
    AND/OR/NOT/IS/NULL/IN/LIKE/BETWEEN and parentheses. No subqueries, no
    function calls, no statement separators or comments."""
    if row_filter is None or not str(row_filter).strip():
        return None
    text = str(row_filter)
    if "\\" in text:
        # Databricks SQL honours backslash escapes in literals; ANSI-only lexing
        # here could disagree on where a string ends.
        raise ValueError("Evidence row_filter may not contain backslashes.")
    pos, prev_ident = 0, False
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _FILTER_TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ValueError(f"Evidence row_filter has unsupported syntax near: {text[pos:pos + 20]!r}")
        ident = m.group("ident")
        if ident is not None and not ident.startswith("`"):
            word = ident.upper()
            if word in _FILTER_FORBIDDEN:
                raise ValueError(f"Evidence row_filter may not use '{ident}'.")
        if m.group("punct") == "(" and prev_ident:
            raise ValueError("Evidence row_filter may not call functions.")
        prev_ident = ident is not None and ident.upper() not in _FILTER_KEYWORDS
        pos = m.end()
    return text


def _validate_evidence(binding: Optional[Dict[str, Any]], sources: Optional[List[Any]]) -> None:
    if binding and binding.get("source_table_fqn"):
        validate_table_fqn(binding["source_table_fqn"])
        validate_row_filter(binding.get("row_filter"))
    for src in sources or []:
        s = src.dict() if hasattr(src, "dict") else dict(src or {})
        if (s.get("type") or "delta_table") in ("delta_table", "asset") and s.get("ref"):
            validate_table_fqn(s["ref"])
        validate_row_filter(s.get("row_filter"))


def principal_matches(principal: Optional[str], principal_type: Optional[str], user: Any) -> bool:
    """Is ``user`` (UserInfo-like: email/username/user/groups) the participant?"""
    if not principal or user is None:
        return False
    want = principal.strip().casefold()
    if (principal_type or "user") == "group":
        return any(str(g).strip().casefold() == want for g in (getattr(user, "groups", None) or []))
    ids = {getattr(user, k, None) for k in ("email", "username", "user")}
    return any(i and str(i).strip().casefold() == want for i in ids)


@dataclass
class _ResolveCtx:
    semantic_models_manager: Optional[Any] = None
    obo_ws_factory: Optional[Callable[[], Any]] = None
    app_ws_factory: Optional[Callable[[], Any]] = None
    mcp_client_factory: Callable[..., Any] = McpHttpClient
    deadline: Optional[Deadline] = None
    # Only recorded (production) resolves refresh cached_label.
    write_cache: bool = False


class AuthorityResolutionManager(SearchableAsset):
    # ------------------------------------------------------- search index
    # One index entry per version family (the representative row the list
    # view shows), keyed by family id so new versions don't duplicate hits.

    @staticmethod
    def _search_id(family_id: str) -> str:
        return f"authority-relation::{family_id}"

    def _build_search_index_item(self, db: Session, relation: AuthorityRelationDb) -> Optional[SearchIndexItem]:
        if not getattr(relation, "id", None) or not getattr(relation, "name", None):
            return None
        family_id = getattr(relation, "version_family_id", None) or relation.id
        tags: List[str] = []
        try:
            from src.controller.tags_manager import TagsManager
            tags = [t.fully_qualified_name for t in TagsManager().list_assigned_tags(
                db, entity_id=relation.id, entity_type=ENTITY_TYPE) if getattr(t, "fully_qualified_name", None)]
        except Exception:  # pragma: no cover - tags are best-effort for search
            pass
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation.id)
        primary = next((d for d in domains if getattr(d, "is_primary", False)), domains[0] if domains else None)
        return SearchIndexItem(
            id=self._search_id(family_id),
            type="authority-relation",
            feature_id=FEATURE_ID,
            title=relation.name,
            description=relation.description or "",
            link=f"/authority-resolution/{relation.id}",
            tags=tags,
            extra_data={
                "status": relation.status,
                "version": relation.version,
                "slug": relation.slug,
                "domain": getattr(primary, "domain_name", None) if primary else None,
                "owner": self._name_of(db, TeamDb, getattr(relation, "owner_team_id", None)),
                "project": self._name_of(db, ProjectDb, getattr(relation, "project_id", None)),
            },
        )

    def _reindex_family(self, db: Session, family_id: str) -> None:
        """Upsert the family's representative row, or drop the entry if the family is gone."""
        try:
            from src.common.version_visibility import collapse_by_family
            rows = authority_relation_repo.get_family_versions(db, family_id=family_id)
            rows = collapse_by_family(rows, elevated_family_ids=set(), is_admin=True)
            item = self._build_search_index_item(db, rows[0]) if rows else None
            if item:
                self._notify_index_upsert(item)
            else:
                self._notify_index_remove(self._search_id(family_id))
        except Exception as e:  # pragma: no cover - index refresh is best-effort
            logger.debug(f"Failed to refresh search entry for AR family {family_id}: {e}")

    def _reindex(self, db: Session, relation: Optional[AuthorityRelationDb]) -> None:
        if relation is not None:
            self._reindex_family(db, getattr(relation, "version_family_id", None) or relation.id)

    def get_search_index_items(self) -> List[SearchIndexItem]:
        from src.common.database import get_session_factory
        session_factory = get_session_factory()
        if not session_factory:
            return []
        items: List[SearchIndexItem] = []
        try:
            with session_factory() as db:
                for relation in self.list_relations(db):
                    item = self._build_search_index_item(db, relation)
                    if item:
                        items.append(item)
        except Exception as e:
            logger.error(f"Error preparing Authority Relations for search: {e}", exc_info=True)
        return items

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    def _load_criteria(self, relation: AuthorityRelationDb) -> List[Criterion]:
        """The AR's enabled decision criteria as engine ``Criterion`` objects.

        Each links a Compliance Check (its DSL ``ASSERT`` rule is the condition);
        ``direction``/``weight`` are the ARF divergence facets on the link. Drives
        both the runtime gate and the DNA-Coefficient engine — one definition.
        """
        out: List[Criterion] = []
        for c in sorted(relation.criteria or [], key=lambda x: (x.display_order or 0)):
            if not getattr(c, "enabled", True):
                continue
            policy = getattr(c, "compliance_policy", None)
            if not policy or not policy.rule:
                continue
            out.append(Criterion(
                # Human-readable label (name) preferred so DNAco divergence reasons
                # and the timeline read cleanly; falls back to slug/id.
                code=(policy.name or policy.slug or c.id),
                rule=policy.rule,
                direction=c.direction or "neutral",
                weight=c.weight if c.weight is not None else 1.0,
                dimension=getattr(c, "dimension", None) or "people",
                message=policy.failure_message or None,
            ))
        return out

    # Essential elements an AR definition should carry; each missing one raises the
    # 'structural' DNAco dimension. Extensible — add checks here.
    def _structural_score(self, relation: AuthorityRelationDb) -> float:
        """Score the AR *definition's* completeness (0.0 = complete, higher = more
        essentials missing). This is the ``structural`` DNAco dimension — evaluated
        on the AR itself, not on evidence rows."""
        checks = [
            bool(relation.justification_chain),                       # documented basis
            bool(relation.object_id),                                 # governs a concrete object
            bool(relation.evidence_sources
                 or (relation.evidence_binding or {}).get("source_table_fqn")),  # evidence bound
            len(relation.criteria or []) > 0,                         # has decision criteria
            any(getattr(a, "is_approver", True) for a in (relation.affirmations or [])),  # has an approver
        ]
        missing = sum(1 for ok in checks if not ok)
        return round(missing / len(checks), 4)

    # ------------------------------------------------------------------ CRUD

    def create_relation(self, db: Session, payload, current_user: Optional[str] = None) -> AuthorityRelationDb:
        data = payload.dict() if hasattr(payload, "dict") else dict(payload)
        rel_id = str(uuid.uuid4())

        evidence = data.get("evidence_binding")
        if evidence is not None and hasattr(evidence, "dict"):
            evidence = evidence.dict()
        _validate_evidence(evidence, data.get("evidence_sources"))
        self._validate_scoping(db, data)

        fields = {
            "id": rel_id,
            "slug": data.get("slug"),
            "name": data["name"],
            "description": data.get("description"),
            "status": STATUS_DRAFT,
            "version": data.get("version") or "1.0.0",
            "version_family_id": rel_id,
            "base_name": data.get("name"),
            "actor_role": data.get("actor_role"),
            "actor_identity": data.get("actor_identity"),
            "actor_since": data.get("actor_since"),
            "action": data.get("action"),
            "object_type": data.get("object_type"),
            "object_id": data.get("object_id"),
            "object_resolves_to": data.get("object_resolves_to"),
            "domain_context": data.get("domain_context"),
            "justification_chain": data.get("justification_chain"),
            "evidence_binding": evidence,
            "evidence_sources": data.get("evidence_sources"),
            "dna_max_threshold": data.get("dna_max_threshold", 0.3),
            "dna_scoring_config": data.get("dna_scoring_config"),
            "schedule_cron": data.get("schedule_cron"),
            "decision_logic": data.get("decision_logic"),
            "resolver_auth": self._validate_resolver_auth(data.get("resolver_auth")),
            "owner_team_id": data.get("owner_team_id") or None,
            "project_id": data.get("project_id") or None,
            "created_by": current_user,
        }

        relation = authority_relation_repo.create(db, obj_in={k: v for k, v in fields.items() if k in _MODEL_COLUMNS})

        # Domains (multi-domain, mirrors contracts/products/teams).
        domain_ids = data.get("domain_ids") or []
        if domain_ids:
            entity_domain_repo.set_domains_for_entity(
                db, entity_type=ENTITY_TYPE, entity_id=rel_id,
                domain_ids=domain_ids, primary_domain_id=data.get("primary_domain_id"),
                assigned_by=current_user,
            )

        # N-functional affirmation stakeholders.
        self._replace_affirmations(db, rel_id, data.get("affirmations") or [])
        # Author-configurable decision criteria (Compliance Checks).
        self._replace_criteria(db, rel_id, data.get("criteria") or [])
        # Prerequisite chain (per-family-slug edges).
        prereqs = data.get("prerequisites")
        if prereqs is not None:
            self._replace_prerequisites(db, relation, prereqs)
        # Typed resource refs (where canonical fields' values come from).
        refs = data.get("resource_refs")
        if refs is not None:
            self._replace_resource_refs(db, rel_id, refs)
        # Polymorphic tags.
        self._set_tags(db, rel_id, getattr(payload, "tags", None), current_user)
        self._reindex(db, relation)
        return relation

    def _set_tags(self, db: Session, relation_id: str, tags: Optional[List[Any]], user_email: Optional[str]) -> None:
        """Best-effort: replace the AR's assigned tags (generic polymorphic tags)."""
        if tags is None:
            return
        try:
            from src.controller.tags_manager import TagsManager
            TagsManager().set_tags_for_entity(
                db, entity_id=relation_id, entity_type=ENTITY_TYPE, tags=list(tags), user_email=user_email,
            )
        except Exception as e:  # pragma: no cover - tag write is best-effort
            logger.warning(f"Could not set tags for AR {relation_id}: {e}")

    def get_relation(self, db: Session, relation_id: str) -> Optional[AuthorityRelationDb]:
        return authority_relation_repo.get(db, relation_id)

    def get_relation_by_slug(self, db: Session, slug: str) -> Optional[AuthorityRelationDb]:
        return authority_relation_repo.get_by_slug(db, slug)

    def _family_active_version(
        self, db: Session, anchor: AuthorityRelationDb
    ) -> Optional[AuthorityRelationDb]:
        """The newest ``active`` version in the anchor's version family, or None."""
        family_id = getattr(anchor, "version_family_id", None) or anchor.id
        versions = authority_relation_repo.get_family_versions(db, family_id=family_id)
        # get_family_versions is created_at desc, so the first active is the newest.
        for v in versions:
            if v.status == STATUS_ACTIVE:
                return v
        return None

    def _family_slug_of(
        self, db: Session, relation: AuthorityRelationDb
    ) -> Optional[str]:
        """The family-level slug for this AR.

        The slug is the stable, family-level ``@id`` an agent uses, but it
        physically lives on one version row (new versions start with no slug
        of their own). Scan sibling versions when the current row has none
        so prerequisite walks, concept lookups and read-dict output stay
        consistent across version bumps.
        """
        if relation.slug:
            return relation.slug
        fam_id = getattr(relation, "version_family_id", None) or relation.id
        for v in authority_relation_repo.get_family_versions(db, family_id=fam_id):
            if v.slug:
                return v.slug
        return None

    @staticmethod
    def _validate_scoping(db: Session, data: Dict[str, Any]) -> None:
        """Normalise ``""`` to ``None`` (the dialogs' "none" choice) and reject
        unknown team/project ids with a ValueError (400) instead of an FK error."""
        for key, model, label in (("owner_team_id", TeamDb, "Team"), ("project_id", ProjectDb, "Project")):
            if key not in data:
                continue
            value = data[key] or None
            data[key] = value
            if value and db.get(model, value) is None:
                raise ValueError(f"{label} '{value}' not found")

    @staticmethod
    def _name_of(db: Session, model, entity_id: Optional[str]) -> Optional[str]:
        if not entity_id:
            return None
        row = db.get(model, entity_id)
        return getattr(row, "name", None) if row else None

    @staticmethod
    def _validate_resolver_auth(value: Optional[str]) -> str:
        value = value or RESOLVER_AUTH_OBO
        if value not in _RESOLVER_AUTH_VALUES:
            raise ValueError(
                f"resolver_auth must be one of {_RESOLVER_AUTH_VALUES}, got '{value}'."
            )
        return value

    def list_family_slugs(self, db: Session) -> List[Dict[str, Any]]:
        """One ``{family_slug, name, status, version}`` row per slug-carrying
        family, sorted by name. Feeds the Requires picker."""
        slug_by_family: Dict[str, str] = {}
        for r in authority_relation_repo.list_all(db):
            fid = getattr(r, "version_family_id", None) or r.id
            if r.slug and fid not in slug_by_family:
                slug_by_family[fid] = r.slug
        out: List[Dict[str, Any]] = []
        for r in self.list_relations(db):
            fid = getattr(r, "version_family_id", None) or r.id
            family_slug = slug_by_family.get(fid)
            if family_slug:
                out.append({
                    "family_slug": family_slug, "name": r.name,
                    "status": r.status, "version": r.version,
                })
        out.sort(key=lambda x: x["name"].lower())
        return out

    def resolve_relation_ref(
        self, db: Session, ref: str, *, prefer_active: bool = True
    ) -> Optional[AuthorityRelationDb]:
        """Resolve an AR reference the way agents address it.

        * A **UUID** pins an exact version (agents that want a specific revision).
        * A **slug** is the stable, family-level ``@id``: it resolves to the
          family's newest **active** version (``prefer_active``), so an agent
          calling ``ar-promo-emea-north`` always hits the current active rule
          regardless of which version row physically carries the slug. Falls
          back to the anchor row when the family has no active version.
        """
        by_id = authority_relation_repo.get(db, ref)
        if by_id is not None:
            return by_id
        anchor = authority_relation_repo.get_by_slug(db, ref)
        if anchor is None:
            return None
        if prefer_active:
            return self._family_active_version(db, anchor) or anchor
        return anchor

    def list_relations(
        self,
        db: Session,
        domain_ids: Optional[List[str]] = None,
        include_history: bool = False,
        project_id: Optional[str] = None,
        owner_team_id: Optional[str] = None,
    ) -> List[AuthorityRelationDb]:
        """List Authority Relations. By default one representative row per version
        family (latest/best-ranked); ``include_history`` returns every version.

        Each returned row carries a transient ``_version_count`` attribute (the
        number of versions in its family) so ``to_read_dict`` can surface the
        version-count badge without a per-row query.
        """
        if domain_ids:
            ids = entity_domain_repo.find_entity_ids_by_domains(
                db, domain_ids=domain_ids, entity_type=ENTITY_TYPE
            )
            rows = authority_relation_repo.list_by_ids(db, ids)
        else:
            rows = authority_relation_repo.list_all(db)
        if project_id:
            rows = [r for r in rows if r.project_id == project_id]
        if owner_team_id:
            rows = [r for r in rows if r.owner_team_id == owner_team_id]

        from src.common.version_visibility import collapse_by_family, family_counts
        counts = family_counts(rows)
        if not include_history:
            # Governance authoring surface: everyone sees every family member,
            # so collapse with elevated (admin) semantics — draft-first, newest.
            rows = collapse_by_family(rows, elevated_family_ids=set(), is_admin=True)
        for r in rows:
            fid = getattr(r, "version_family_id", None) or r.id
            setattr(r, "_version_count", counts.get(fid, 1))
        return rows

    def update_relation(self, db: Session, relation_id: str, payload, current_user: Optional[str] = None) -> Optional[AuthorityRelationDb]:
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        data = payload.dict(exclude_unset=True) if hasattr(payload, "dict") else dict(payload)

        domain_ids = data.pop("domain_ids", None)
        primary_domain_id = data.pop("primary_domain_id", None)
        affirmations = data.pop("affirmations", None)
        criteria = data.pop("criteria", None)
        prerequisites = data.pop("prerequisites", None)
        resource_refs = data.pop("resource_refs", None)

        evidence = data.get("evidence_binding")
        if evidence is not None and hasattr(evidence, "dict"):
            data["evidence_binding"] = evidence.dict()
        _validate_evidence(data.get("evidence_binding"), data.get("evidence_sources"))

        self._validate_scoping(db, data)
        if "resolver_auth" in data:
            data["resolver_auth"] = self._validate_resolver_auth(data["resolver_auth"])
        update_data = {k: v for k, v in data.items() if k in _MODEL_COLUMNS}

        # Versioning parity with Data Products / Contracts: edits mutate the
        # current row in place (no auto-bump). A new immutable snapshot is
        # created only via the explicit "New Version" action (create_new_version).
        # Keep base_name in step with a renamed AR so the family label stays right.
        if "name" in update_data:
            update_data.setdefault("base_name", update_data["name"])
        relation = authority_relation_repo.update(db, db_obj=relation, obj_in=update_data)

        if domain_ids is not None:
            entity_domain_repo.set_domains_for_entity(
                db, entity_type=ENTITY_TYPE, entity_id=relation_id,
                domain_ids=domain_ids, primary_domain_id=primary_domain_id,
                assigned_by=current_user,
            )
        if affirmations is not None:
            self._replace_affirmations(db, relation_id, affirmations)
        if criteria is not None:
            self._replace_criteria(db, relation_id, criteria)
        if prerequisites is not None:
            self._replace_prerequisites(db, relation, prerequisites)
        if resource_refs is not None:
            self._replace_resource_refs(db, relation_id, resource_refs)
        # Polymorphic tags (only when the caller supplied the field).
        self._set_tags(db, relation_id, getattr(payload, "tags", None), current_user)

        # Replace helpers bulk-delete without session sync; drop the stale
        # selectin-loaded collections so the recompute scores the new definition.
        db.flush()
        db.expire(relation, ["criteria", "affirmations"])

        # Re-created participants start unaffirmed: an active AR can't stay active
        # without its required affirmations.
        if (relation.status == STATUS_ACTIVE and affirmations is not None
                and not self.is_fully_affirmed(db, relation_id)):
            relation = authority_relation_repo.update(db, db_obj=relation, obj_in={"status": STATUS_NEEDS_REVIEW})
            self._log_timeline(db, relation_id, "Participants changed; status set to needs_review until re-affirmed.")

        # Changing an active AR triggers recompute + re-review (best-effort recompute).
        if relation.status == STATUS_ACTIVE:
            try:
                self.compute_dnaco(db, relation_id)
            except Exception as e:  # pragma: no cover - evidence read is environment-dependent
                logger.warning(f"DNAco recompute after update failed for {relation_id}: {e}")
        self._reindex(db, relation)
        return relation

    def delete_relation(self, db: Session, relation_id: str) -> bool:
        """Delete one AR version without breaking its family's identity.

        The family anchor (``id == version_family_id``) can only go once it is the
        last version, because semantic links key on it. A slug on a deleted
        non-anchor row moves to the newest remaining version. Deleting the last
        version also removes its prerequisite edges and concept links, and is
        refused while other ARs still require its slug. Raises ``ValueError``.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return False
        family_id = getattr(relation, "version_family_id", None) or relation.id
        others = [v for v in authority_relation_repo.get_family_versions(db, family_id=family_id)
                  if v.id != relation.id]
        if others:
            if relation.id == family_id:
                raise ValueError(
                    "This is the first version of its family; delete the newer versions first."
                )
            if relation.slug:
                slug = relation.slug
                relation.slug = None
                db.flush()
                others[0].slug = slug
                db.flush()
        else:
            slug = self._family_slug_of(db, relation)
            if slug:
                dependents = sorted({e.relation_family_slug for e in authority_prerequisite_repo.list_dependents(
                    db, prerequisite_family_slug=slug)})
                if dependents:
                    raise ValueError(
                        f"Authority Relation '{slug}' is a prerequisite of {', '.join(dependents)}; "
                        "remove those edges first."
                    )
                authority_prerequisite_repo.delete_for_family(db, relation_family_slug=slug)
            from src.db_models.semantic_links import EntitySemanticLinkDb
            db.query(EntitySemanticLinkDb).filter(
                EntitySemanticLinkDb.entity_type == ENTITY_TYPE,
                EntitySemanticLinkDb.entity_id == family_id,
            ).delete(synchronize_session=False)
        entity_domain_repo.remove_all_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation_id)
        authority_relation_repo.remove(db, id=relation_id)
        db.flush()
        self._reindex_family(db, family_id)
        return True

    # --------------------------------------------------------- versioning

    # Definition fields carried onto a new version snapshot (everything that
    # describes the *rule*, not its measured/observed state). DNAco results,
    # usage counters, maturity cache and lifecycle status are deliberately
    # reset so the new draft starts unmeasured.
    _VERSION_COPY_FIELDS = (
        "actor_role", "actor_identity", "actor_since", "action",
        "object_type", "object_id", "object_resolves_to",
        "domain_context", "justification_chain", "decision_logic",
        "evidence_binding", "evidence_sources",
        "dna_max_threshold", "dna_scoring_config", "schedule_cron",
        "resolver_auth", "owner_team_id", "project_id",
    )

    def get_relation_versions(self, db: Session, relation_id: str) -> List[AuthorityRelationDb]:
        """Every version in the AR's family, newest first (mirrors get_product_versions)."""
        source = authority_relation_repo.get(db, relation_id)
        if not source:
            raise ValueError("Authority Relation not found")
        family_id = getattr(source, "version_family_id", None) or source.id
        return authority_relation_repo.get_family_versions(db, family_id=family_id)

    def create_new_version(
        self,
        db: Session,
        relation_id: str,
        new_version: str,
        change_summary: Optional[str] = None,
        current_user: Optional[str] = None,
    ) -> Optional[AuthorityRelationDb]:
        """Snapshot an AR into a new immutable version (DP/DC parity).

        Deep-clones the definition into a fresh row in the same version family:
        the ARF tuple + evidence + config fields, plus the criteria, affirmations,
        domains and tags. DNAco results, usage counters and maturity cache are
        reset and the new version starts as a ``draft``. The source row is left
        untouched. Returns ``None`` if the source AR does not exist.
        """
        source = authority_relation_repo.get(db, relation_id)
        if not source:
            return None

        new_id = str(uuid.uuid4())
        family_id = getattr(source, "version_family_id", None) or source.id
        base_name = getattr(source, "base_name", None) or source.name

        fields = {
            "id": new_id,
            "slug": None,  # slug is unique; a new version gets its own (author can set later)
            "name": source.name,
            "description": source.description,
            "status": STATUS_DRAFT,
            "version": new_version,
            "version_family_id": family_id,
            "parent_relation_id": source.id,
            "base_name": base_name,
            "change_summary": change_summary,
            "created_by": current_user,
        }
        for f in self._VERSION_COPY_FIELDS:
            fields[f] = getattr(source, f, None)

        relation = authority_relation_repo.create(
            db, obj_in={k: v for k, v in fields.items() if k in _MODEL_COLUMNS}
        )

        # Carry the source's domain assignments onto the new version.
        domains = entity_domain_repo.get_domains_for_entity(
            db, entity_type=ENTITY_TYPE, entity_id=source.id
        )
        if domains:
            domain_ids = [getattr(d, "id", None) or (d.get("id") if isinstance(d, dict) else None) for d in domains]
            domain_ids = [d for d in domain_ids if d]
            primary = next(
                (getattr(d, "id", None) or (d.get("id") if isinstance(d, dict) else None)
                 for d in domains
                 if getattr(d, "is_primary", None) or (isinstance(d, dict) and d.get("is_primary"))),
                None,
            )
            if domain_ids:
                entity_domain_repo.set_domains_for_entity(
                    db, entity_type=ENTITY_TYPE, entity_id=new_id,
                    domain_ids=domain_ids, primary_domain_id=primary, assigned_by=current_user,
                )

        # Clone decision criteria (reuse the reusable Compliance Checks; only the
        # ARF facet link is per-version).
        src_criteria = authority_criterion_repo.list_for_relation(db, relation_id=source.id)
        for c in src_criteria:
            authority_criterion_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": new_id,
                "compliance_policy_id": c.compliance_policy_id,
                "direction": c.direction,
                "weight": c.weight,
                "dimension": getattr(c, "dimension", "people"),
                "display_order": c.display_order,
                "enabled": c.enabled,
            })

        # Clone affirmation participants, resetting their affirmed/review state.
        src_affs = authority_affirmation_repo.list_for_relation(db, relation_id=source.id)
        for a in src_affs:
            is_reviewer = getattr(a, "is_reviewer", False)
            authority_affirmation_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": new_id,
                "role": a.role,
                "business_role_id": getattr(a, "business_role_id", None),
                "role_category": getattr(a, "role_category", None),
                "principal": a.principal,
                "principal_type": a.principal_type,
                "is_approver": getattr(a, "is_approver", True),
                "is_reviewer": is_reviewer,
                "required": a.required,
                "affirmed": False,
                "review_status": "pending" if is_reviewer else "na",
                "sort_order": a.sort_order,
            })

        # Clone typed resource refs (definition, not cache).
        for r in authority_resource_ref_repo.list_for_relation(db, relation_id=source.id):
            authority_resource_ref_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": new_id,
                "field_path": r.field_path,
                "ref_type": r.ref_type,
                "literal_value": r.literal_value,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "mcp_service_name": r.mcp_service_name,
                "mcp_tool_name": r.mcp_tool_name,
                "mcp_params": r.mcp_params,
                "mcp_result_pointer": r.mcp_result_pointer or "$",
            })

        # Clone polymorphic tags (best-effort).
        try:
            from src.controller.tags_manager import TagsManager
            tm = TagsManager()
            assigned = tm.list_assigned_tags(db, entity_id=source.id, entity_type=ENTITY_TYPE)
            tags_payload = [
                {"fully_qualified_name": getattr(t, "fully_qualified_name", None),
                 "assigned_value": getattr(t, "assigned_value", None)}
                for t in assigned
                if getattr(t, "fully_qualified_name", None)
            ]
            if tags_payload:
                self._set_tags(db, new_id, tags_payload, current_user)
        except Exception as e:  # pragma: no cover - tag clone is best-effort
            logger.warning(f"Could not clone tags onto new AR version {new_id}: {e}")

        self._log_timeline(
            db, new_id,
            f"Version {new_version} created from {source.version} (family {family_id}).",
        )
        self._reindex(db, relation)
        return relation

    # ------------------------------------------------------- affirmations

    @staticmethod
    def _participant_key(principal: Any, principal_type: Any, role_id: Any, role: Any,
                         is_approver: Any, is_reviewer: Any) -> Tuple:
        return (str(principal or "").strip().casefold(), principal_type or "user",
                role_id or role, bool(is_approver), bool(is_reviewer))

    def _replace_affirmations(self, db: Session, relation_id: str, affirmations: List[Any]) -> None:
        """Replace participants, carrying affirmation/review state over for any
        participant that is unchanged (same principal, type, role and duties), so
        re-saving an AR doesn't wipe its sign-offs."""
        prior = {}
        for old in authority_affirmation_repo.list_for_relation(db, relation_id=relation_id):
            prior[self._participant_key(
                old.principal, old.principal_type, getattr(old, "business_role_id", None), old.role,
                getattr(old, "is_approver", True), getattr(old, "is_reviewer", False),
            )] = old
        carried = {
            k: {f: getattr(o, f, None) for f in (
                "affirmed", "affirmed_by", "affirmed_at", "notes",
                "review_status", "review_answers", "review_request_id",
            )}
            for k, o in prior.items()
        }
        authority_affirmation_repo.delete_for_relation(db, relation_id=relation_id)
        for idx, aff in enumerate(affirmations):
            a = aff.dict() if hasattr(aff, "dict") else dict(aff)
            is_reviewer = a.get("is_reviewer", False)
            keep = carried.get(self._participant_key(
                a["principal"], a.get("principal_type", "user"), a.get("business_role_id"), a["role"],
                a.get("is_approver", True), is_reviewer,
            )) or {}
            authority_affirmation_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation_id,
                "role": a["role"],
                "business_role_id": a.get("business_role_id"),
                "role_category": a.get("role_category"),
                "principal": a["principal"],
                "principal_type": a.get("principal_type", "user"),
                "is_approver": a.get("is_approver", True),
                "is_reviewer": is_reviewer,
                "required": a.get("required", True),
                "affirmed": bool(keep.get("affirmed")),
                "affirmed_by": keep.get("affirmed_by"),
                "affirmed_at": keep.get("affirmed_at"),
                "notes": keep.get("notes"),
                "review_status": keep.get("review_status") or ("pending" if is_reviewer else "na"),
                "review_answers": keep.get("review_answers"),
                "review_request_id": keep.get("review_request_id"),
                "sort_order": a.get("sort_order", idx),
            })

    # ------------------------------------------------------- decision criteria

    def _replace_criteria(self, db: Session, relation_id: str, criteria: List[Any]) -> None:
        """Replace the AR's decision-criteria links. Each input either references an
        existing Compliance Check (``policy_id``) or authors a new one inline
        (``name`` + ``rule``). Mirrors ``_replace_affirmations``; re-run on each
        version bump so the criteria travel with the AR version.
        """
        authority_criterion_repo.delete_for_relation(db, relation_id=relation_id)
        for idx, item in enumerate(criteria):
            c = item.dict() if hasattr(item, "dict") else dict(item)
            policy_id = c.get("policy_id") or self._create_criterion_policy(db, c, relation_id, idx)
            if not policy_id:
                continue
            authority_criterion_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation_id,
                "compliance_policy_id": policy_id,
                "direction": c.get("direction") or "neutral",
                "weight": c.get("weight") if c.get("weight") is not None else 1.0,
                "dimension": c.get("dimension") or "people",
                "display_order": c.get("order", idx),
                "enabled": c.get("enabled", True),
            })

    def _create_criterion_policy(self, db: Session, c: Dict[str, Any], relation_id: str, idx: int) -> Optional[str]:
        """Author a new Compliance Check for an inline criterion and return its id.

        The rule is a Compliance-DSL ``ASSERT`` condition (the ``ASSERT`` keyword is
        prepended if the author omitted it). Category ``Authority Decision`` mirrors
        how the Maturity feature tags its seeded policies (``Maturity``).
        """
        rule = (c.get("rule") or "").strip()
        if not rule:
            return None
        if not authority_dna.has_assert_clause(rule):
            rule = "ASSERT " + rule
        parse_error = authority_dna.rule_parse_error(rule)
        if parse_error:
            raise ValueError(f"Criterion rule {rule!r} does not parse: {parse_error}")
        pid = str(uuid.uuid4())
        policy = CompliancePolicyDb(
            id=pid,
            slug=f"ar-criterion-{pid[:12]}",
            name=c.get("name") or f"Authority criterion {idx + 1}",
            description=f"Authority decision criterion for Authority Relation {relation_id}",
            failure_message=c.get("failure_message") or None,
            rule=rule,
            category="Authority Decision",
            severity="high",
            is_active=True,
        )
        db.add(policy)
        db.flush()
        return pid

    # --------------------------------------------------------- prerequisites

    def _cycle_would_close(
        self, db: Session, head_slug: str, candidate_prereq_slug: str,
    ) -> bool:
        """Would adding (``head_slug`` → ``candidate_prereq_slug``) close a cycle?

        Walks the candidate upstream slug's transitive prerequisites via
        ``list_for_family``; if ``head_slug`` appears in that closure the new
        edge would form a cycle. Called on save so authors never land an
        edge the resolve-time detector would have to abort on.
        """
        if head_slug == candidate_prereq_slug:
            return True
        seen = {candidate_prereq_slug}
        stack = [candidate_prereq_slug]
        while stack:
            s = stack.pop()
            for e in authority_prerequisite_repo.list_for_family(
                db, relation_family_slug=s,
            ):
                if e.prerequisite_family_slug == head_slug:
                    return True
                if e.prerequisite_family_slug not in seen:
                    seen.add(e.prerequisite_family_slug)
                    stack.append(e.prerequisite_family_slug)
        return False

    def _replace_prerequisites(
        self, db: Session, relation: AuthorityRelationDb, prerequisites: List[Any],
    ) -> None:
        """Replace the AR's declared prerequisite chain.

        Edges are keyed by family slug (per the pin — agents never see
        version UUIDs), so the AR must carry a slug for this to be meaningful.
        Rejects self-loops and any edge whose upstream family already depends
        on ``head`` through its own transitive prerequisites.
        """
        head_slug = self._family_slug_of(db, relation)
        if head_slug is None:
            if prerequisites:
                raise ValueError(
                    "Authority Relation needs a slug before prerequisites can be set "
                    "— edges are keyed by the stable family-level @id."
                )
            return
        # Deduplicate by candidate slug (last writer wins its required/order).
        normalised: Dict[str, Dict[str, Any]] = {}
        for idx, item in enumerate(prerequisites):
            p = item.dict() if hasattr(item, "dict") else dict(item)
            slug = (p.get("prerequisite_family_slug") or "").strip()
            if not slug:
                continue
            if slug == head_slug:
                raise ValueError(
                    f"An Authority Relation cannot require itself ({slug})."
                )
            if authority_relation_repo.get_by_slug(db, slug) is None:
                raise ValueError(
                    f"Prerequisite '{slug}' does not match any Authority Relation slug."
                )
            if self._cycle_would_close(db, head_slug, slug):
                raise ValueError(
                    f"Adding '{slug}' as a prerequisite of '{head_slug}' would close a cycle."
                )
            normalised[slug] = {
                "required": bool(p.get("required", True)),
                "display_order": int(p.get("display_order", idx)),
                "notes": p.get("notes"),
            }
        authority_prerequisite_repo.delete_for_family(
            db, relation_family_slug=head_slug,
        )
        for slug, cfg in normalised.items():
            authority_prerequisite_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_family_slug": head_slug,
                "prerequisite_family_slug": slug,
                "required": cfg["required"],
                "display_order": cfg["display_order"],
                "notes": cfg["notes"],
            })

    def list_prerequisites(
        self, db: Session, relation: AuthorityRelationDb,
    ) -> List[Dict[str, Any]]:
        """The AR's declared prerequisites with each upstream slug resolved
        for display (name + status of the active family version)."""
        head_slug = self._family_slug_of(db, relation)
        if head_slug is None:
            return []
        edges = authority_prerequisite_repo.list_for_family(
            db, relation_family_slug=head_slug,
        )
        out: List[Dict[str, Any]] = []
        for e in edges:
            target = self.resolve_relation_ref(db, e.prerequisite_family_slug)
            out.append({
                "prerequisite_family_slug": e.prerequisite_family_slug,
                "required": e.required,
                "display_order": e.display_order,
                "notes": e.notes,
                "name": target.name if target else None,
                "status": target.status if target else None,
                "version": target.version if target else None,
                "resolved_id": target.id if target else None,
            })
        return out

    # --------------------------------------------------------- resource refs

    # Author-selectable ref types; ``mcp_tool`` is accepted but stays a
    # no-op resolve until the MCP resolver lands (ARF v2 commit 4).
    _REF_TYPES = ("literal", "ontos_entity", "mcp_tool")
    # Ontos entity types we know how to resolve against today. The dispatch
    # in :meth:`_resolve_ontos_entity` is a thin table so adding another
    # type later is a two-line change.
    _ONTOS_ENTITY_TYPES = ("business_concept", "data_product", "data_domain")

    def _replace_resource_refs(
        self, db: Session, relation_id: str, refs: List[Any],
    ) -> None:
        """Replace the AR's typed resource refs (delete + recreate).

        Mirrors ``_replace_criteria`` / ``_replace_prerequisites``:
        validates each row, dedupes by ``field_path`` (last writer wins),
        and persists. The AR's own scalar columns stay untouched — ref
        rows record *where* a value came from, not *what* it currently is.
        Call sites: ``create_relation`` and ``update_relation``.
        """
        normalised: Dict[str, Dict[str, Any]] = {}
        for item in refs:
            r = item.dict() if hasattr(item, "dict") else dict(item)
            field_path = (r.get("field_path") or "").strip()
            ref_type = (r.get("ref_type") or "").strip()
            if not field_path:
                continue
            if ref_type not in self._REF_TYPES:
                raise ValueError(
                    f"Resource ref for '{field_path}' has unknown ref_type "
                    f"'{ref_type}' — expected one of {self._REF_TYPES}."
                )
            if ref_type == "literal":
                # literal_value may legitimately be an empty string, but
                # ``None`` is treated as "no ref row" by the resolver, so
                # catch that at the write boundary.
                if r.get("literal_value") is None:
                    raise ValueError(
                        f"Literal resource ref for '{field_path}' is missing literal_value."
                    )
            elif ref_type == "ontos_entity":
                entity_type = (r.get("entity_type") or "").strip()
                entity_id = (r.get("entity_id") or "").strip()
                if not entity_type or not entity_id:
                    raise ValueError(
                        f"Ontos-entity resource ref for '{field_path}' needs both "
                        "entity_type and entity_id."
                    )
                if entity_type not in self._ONTOS_ENTITY_TYPES:
                    raise ValueError(
                        f"Ontos-entity resource ref for '{field_path}' has unsupported "
                        f"entity_type '{entity_type}' — expected one of {self._ONTOS_ENTITY_TYPES}."
                    )
            elif ref_type == "mcp_tool":
                service = (r.get("mcp_service_name") or "").strip()
                tool = (r.get("mcp_tool_name") or "").strip()
                if not service.startswith(mcp_resolver.SERVICE_PREFIX) or not tool:
                    raise ValueError(
                        f"MCP resource ref for '{field_path}' needs mcp_service_name "
                        f"('{mcp_resolver.SERVICE_PREFIX}…') and mcp_tool_name."
                    )
                if r.get("mcp_params") is not None and not isinstance(r["mcp_params"], dict):
                    raise ValueError(f"MCP resource ref for '{field_path}': mcp_params must be an object.")
                pointer = (r.get("mcp_result_pointer") or "$").strip()
                if not pointer.startswith("$"):
                    raise ValueError(
                        f"MCP resource ref for '{field_path}': mcp_result_pointer must start with '$'."
                    )
            normalised[field_path] = r
        # Validate everything before touching existing rows.
        authority_resource_ref_repo.delete_for_relation(db, relation_id=relation_id)
        for field_path, r in normalised.items():
            authority_resource_ref_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation_id,
                "field_path": field_path,
                "ref_type": r["ref_type"],
                "literal_value": r.get("literal_value"),
                "entity_type": r.get("entity_type"),
                "entity_id": r.get("entity_id"),
                "mcp_service_name": r.get("mcp_service_name"),
                "mcp_tool_name": r.get("mcp_tool_name"),
                "mcp_params": r.get("mcp_params"),
                "mcp_result_pointer": r.get("mcp_result_pointer") or "$",
            })

    def _resolve_ontos_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        semantic_models_manager: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Look up an Ontos entity by (type, id) and return ``{value, iri?}``.

        * ``business_concept`` — ``entity_id`` *is* the concept IRI; its label
          is read from the semantic graph when a manager is available, and
          the raw IRI is returned verbatim as both the value *and* the IRI
          when it isn't (unit tests, cold-start resolve).
        * ``data_product`` / ``data_domain`` — a direct repo read; the
          entity's ``name`` becomes the value.

        Any lookup failure returns ``{value: None, iri: None, error: '…'}``
        so the caller can decide between fallback and surfacing. Nothing
        here raises; a dangling ref row must never crash a resolve.
        """
        if entity_type == "business_concept":
            # The IRI itself is both the id and the semantic key; a label
            # from the graph is a nice-to-have.
            if semantic_models_manager is not None:
                try:
                    concept = semantic_models_manager.get_concept_details(entity_id)
                    label = getattr(concept, "label", None) if concept else None
                    if label:
                        return {"value": label, "iri": entity_id}
                except Exception as e:  # pragma: no cover - RDF read is best-effort
                    logger.warning(f"Concept lookup failed for {entity_id}: {e}")
            return {"value": entity_id, "iri": entity_id}
        if entity_type == "data_product":
            try:
                from src.repositories.data_products_repository import data_product_repo
                dp = data_product_repo.get(db, entity_id)
                if dp is not None:
                    return {"value": getattr(dp, "name", None) or entity_id, "iri": None}
            except Exception as e:  # pragma: no cover - optional dep
                logger.warning(f"Data product lookup failed for {entity_id}: {e}")
            return {"value": None, "iri": None, "error": "data_product not found"}
        if entity_type == "data_domain":
            try:
                from src.repositories.data_domain_repository import data_domain_repo
                dd = data_domain_repo.get(db, entity_id)
                if dd is not None:
                    return {"value": getattr(dd, "name", None) or entity_id, "iri": None}
            except Exception as e:  # pragma: no cover - optional dep
                logger.warning(f"Data domain lookup failed for {entity_id}: {e}")
            return {"value": None, "iri": None, "error": "data_domain not found"}
        return {
            "value": None, "iri": None,
            "error": f"unsupported entity_type '{entity_type}'",
        }

    def _materialise_refs(
        self,
        db: Session,
        relation: AuthorityRelationDb,
        req: Dict[str, Any],
        rctx: "_ResolveCtx",
    ) -> List[Dict[str, Any]]:
        """Walk the AR's resource refs and resolve each to a concrete value.

        Returns one entry per ref row shaped
        ``{field_path, ref_type, value, iri?, source, error?}``. The row's
        ``cached_label`` / ``cached_at`` are updated so a later cold read
        (list view, provenance audit) can show the last-known resolved
        value without re-walking the graph.

        ``mcp_tool`` refs are invoked live (see :meth:`_resolve_mcp_ref`); a
        failure leaves ``value=None`` and sets ``error`` + ``error_kind`` so the
        caller can turn it into a ``no_authority`` verdict.
        """
        rows = authority_resource_ref_repo.list_for_relation(db, relation_id=relation.id)
        resolved: List[Dict[str, Any]] = []
        for row in rows:
            entry: Dict[str, Any] = {
                "field_path": row.field_path,
                "ref_type": row.ref_type,
            }
            value: Optional[str] = None
            iri: Optional[str] = None
            source = row.ref_type
            if row.ref_type == "literal":
                value = row.literal_value
            elif row.ref_type == "ontos_entity":
                lookup = self._resolve_ontos_entity(
                    db,
                    entity_type=row.entity_type or "",
                    entity_id=row.entity_id or "",
                    semantic_models_manager=rctx.semantic_models_manager,
                )
                value = lookup.get("value")
                iri = lookup.get("iri")
                if lookup.get("error"):
                    entry["error"] = lookup["error"]
            elif row.ref_type == "mcp_tool":
                try:
                    value = self._resolve_mcp_ref(relation, row, req, rctx)
                except McpResolverError as e:
                    entry["error"] = str(e)
                    entry["error_kind"] = e.kind
            entry["value"] = value
            if iri is not None:
                entry["iri"] = iri
            entry["source"] = source
            resolved.append(entry)
            # Rows are session-attached; the decision write flushes this too.
            # OBO MCP results are caller-scoped data, so they are never cached
            # where other users (or other callers' concept lookups) could see them.
            caller_scoped = row.ref_type == "mcp_tool" and (
                getattr(relation, "resolver_auth", None) or RESOLVER_AUTH_OBO
            ) == RESOLVER_AUTH_OBO
            if rctx.write_cache and value is not None and not caller_scoped:
                row.cached_label = value
                row.cached_at = self._now()
        return resolved

    def _resolve_mcp_ref(
        self,
        relation: AuthorityRelationDb,
        row: Any,
        req: Dict[str, Any],
        rctx: "_ResolveCtx",
    ) -> Optional[str]:
        """Invoke the ref's MCP tool and return the pointer-selected value as a string.

        Credentials follow the AR's ``resolver_auth``: ``obo`` uses the caller's
        token and never silently falls back to the app SP (a missing caller
        token is a permission failure); ``app_sp`` uses the Ontos app's SP.
        """
        auth = getattr(relation, "resolver_auth", None) or RESOLVER_AUTH_OBO
        factory = rctx.app_ws_factory if auth == RESOLVER_AUTH_APP_SP else rctx.obo_ws_factory
        if factory is None:
            raise McpResolverError(
                "no caller (OBO) credentials available for an obo-authenticated MCP ref"
                if auth == RESOLVER_AUTH_OBO else "app service principal client unavailable",
                kind="permission",
            )
        try:
            ws = factory()
        except Exception as e:
            raise McpResolverError(f"could not build workspace client: {e}", kind="permission")
        if ws is None:
            raise McpResolverError(f"no workspace client for resolver_auth={auth}", kind="permission")
        deadline = rctx.deadline or Deadline(RESOLVE_BUDGET_S)
        template_ctx = {
            **req,
            "request": req,
            "ar": {
                "slug": relation.slug,
                "actor_role": relation.actor_role,
                "actor_identity": relation.actor_identity,
                "action": relation.action,
                "object_type": relation.object_type,
                "object_id": relation.object_id,
                "domain_context": relation.domain_context or {},
            },
        }
        arguments = mcp_resolver.render_params(row.mcp_params or {}, template_ctx)
        try:
            client = rctx.mcp_client_factory(ws, row.mcp_service_name, deadline=deadline)
            raw = client.call_tool(row.mcp_tool_name, arguments)
        except McpResolverError:
            raise
        except Exception as e:
            raise McpResolverError(f"MCP call failed: {e}")
        return mcp_resolver.stringify(
            mcp_resolver.apply_result_pointer(raw, row.mcp_result_pointer),
        )

    def list_resource_refs(
        self, db: Session, relation: AuthorityRelationDb,
    ) -> List[Dict[str, Any]]:
        """Flat read of the AR's declared refs for ``to_read_dict``.

        Does *not* re-resolve — detail views show what the author configured
        plus the last cached label. A live re-materialise happens inside
        :meth:`_resolve_internal` on every ``resolve`` call.
        """
        rows = authority_resource_ref_repo.list_for_relation(db, relation_id=relation.id)
        return [
            {
                "id": r.id,
                "field_path": r.field_path,
                "ref_type": r.ref_type,
                "literal_value": r.literal_value,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "mcp_service_name": r.mcp_service_name,
                "mcp_tool_name": r.mcp_tool_name,
                "mcp_params": r.mcp_params,
                "mcp_result_pointer": r.mcp_result_pointer,
                "cached_label": r.cached_label,
                "cached_at": r.cached_at,
            }
            for r in rows
        ]

    def affirm(
        self, db: Session, affirmation_id: str, affirmed_by: str,
        notes: Optional[str] = None, user: Any = None,
    ) -> Optional[AuthorityAffirmationDb]:
        """Record an affirmation. Only the participant's own principal (or a
        member of its group) may affirm; raises ``PermissionError`` otherwise."""
        aff = authority_affirmation_repo.get(db, affirmation_id)
        if not aff:
            return None
        if not getattr(aff, "is_approver", True):
            raise PermissionError("This participant is a reviewer, not an approver.")
        if not principal_matches(aff.principal, aff.principal_type, user):
            raise PermissionError("Only the named participant can record this affirmation.")
        return authority_affirmation_repo.update(db, db_obj=aff, obj_in={
            "affirmed": True, "affirmed_by": affirmed_by, "affirmed_at": self._now(), "notes": notes,
        })

    def is_fully_affirmed(self, db: Session, relation_id: str) -> bool:
        # Only APPROVER participants count toward the affirmation gate; pure
        # reviewers/interviewees do not. (is_approver defaults True for rows
        # created before the reviewer/approver split.)
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation_id)
        required = [a for a in affs if a.required and getattr(a, "is_approver", True)]
        return len(required) > 0 and all(a.affirmed for a in required)

    # ------------------------------------------------------- review process

    # Default structured-elicitation questionnaire per reviewer role. Business /
    # interviewee reviewers answer these; technical reviewers instead inspect the
    # AR details (evidence + decision logic); governance confirms proportionality.
    _QUESTIONNAIRE: Dict[str, List[str]] = {
        "business": [
            "Who is actually consulted before this decision is made?",
            "Does the documented policy match how the decision is really made in practice?",
            "Does someone other than the documented approver effectively drive this decision?",
            "What informal factors influence this decision?",
        ],
        "interviewee": [
            "Who is actually consulted before this decision is made?",
            "Does the documented policy match how the decision is really made in practice?",
            "What informal factors influence this decision?",
        ],
        "technical": [
            "Is the bound evidence complete and unaltered?",
            "Does the compiled decision logic faithfully represent the rule?",
        ],
        "governance": [
            "Is the intended use of this Authority Relation proportionate to the stakes?",
            "Does activating it create any new, unreviewed concentration of authority?",
        ],
    }

    def _questionnaire_for(self, role: str, category: Optional[str] = None) -> List[Dict[str, str]]:
        """Pick the role-specific questionnaire. Prefer the Business Role's
        ``category`` (governance|technical|business|operational); fall back to the
        role name, then to the business questionnaire. ``operational`` maps to the
        business questionnaire (no distinct set yet)."""
        key = (category or role or "").lower()
        if key == "operational":
            key = "business"
        questions = self._QUESTIONNAIRE.get(key, self._QUESTIONNAIRE["business"])
        return [{"id": f"q{i+1}", "text": q} for i, q in enumerate(questions)]

    def start_review(
        self,
        db: Session,
        relation_id: str,
        owner: Optional[str] = None,
        reviews_manager: Optional[Any] = None,
        message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Start the review process.

        For each reviewer participant we (a) pre-create a per-reviewer Asset
        Review targeting that principal — its ``asset_fqn`` is
        ``authority-relation://{id}`` so the reviewer's task opens the
        role-specific AR review editor, and creating it fires the standard
        data-asset-review workflow (notification + approval) — and (b) mark the
        participant ``in_review`` and store the Asset Review's id so the owner
        can track and link to it. We then fire the AR-level ``on_request_review``
        trigger, which the ``authority-relation-review-request`` default workflow
        consumes to record the overall review process. All workflow/review side
        effects are best-effort and never break the request. Returns None if the
        AR does not exist.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation_id)
        reviewers = [a for a in affs if getattr(a, "is_reviewer", False)]
        # The Asset Review requester must be an email (EmailStr). The AR owner is
        # typically an email, but in local/dev it can be a bare username — fall
        # back to the reviewer principal (always an email/group id) in that case.
        requester_email = owner if (owner and "@" in owner) else None
        reviews_created = 0
        for a in reviewers:
            review_request_id: Optional[str] = None
            if reviews_manager is not None:
                try:
                    from src.models.data_asset_reviews import DataAssetReviewRequestCreate
                    req = reviews_manager.create_review_request(
                        DataAssetReviewRequestCreate(
                            requester_email=requester_email or a.principal,
                            reviewer_email=a.principal,
                            asset_fqns=[f"authority-relation://{relation_id}"],
                            title=f"Authority Relation review: {relation.name}",
                            notes=(
                                f"Confirm whether this Authority Relation reflects reality (reviewer role: {a.role})."
                                + (f"\n\nOwner note: {message.strip()}" if message and message.strip() else "")
                            ),
                        ),
                        db=db,
                    )
                    review_request_id = getattr(req, "id", None)
                    reviews_created += 1
                except Exception as e:  # pragma: no cover - env/validation dependent
                    logger.warning(f"Could not create Asset Review for reviewer {a.principal} on AR {relation_id}: {e}")
            authority_affirmation_repo.update(db, db_obj=a, obj_in={
                "review_status": "in_review",
                "review_request_id": review_request_id or f"authority-relation://{relation_id}#{a.id}",
            })
        # Fire the AR-level workflow trigger (best-effort — never breaks the request).
        try:
            from src.common.workflow_triggers import fire_trigger_safe
            from src.models.process_workflows import EntityType
            fire_trigger_safe(
                db, "on_request_review",
                entity_type=EntityType.AUTHORITY_RELATION,
                entity_id=relation_id,
                entity_name=relation.name,
                entity_data={
                    "asset_fqn": f"authority-relation://{relation_id}",
                    "reviewers": [{"principal": a.principal, "role": a.role} for a in reviewers],
                    "status": relation.status,
                },
                user_email=owner,
            )
        except Exception as e:  # pragma: no cover - trigger is environment-dependent
            logger.warning(f"on_request_review trigger failed for AR {relation_id}: {e}")
        return {
            "relation_id": relation_id,
            "reviewers_notified": len(reviewers),
            "reviews_created": reviews_created,
        }

    def get_review_context(
        self, db: Session, relation_id: str, reviewer: str, user: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """Build the role-specific review context for a reviewer of this AR.
        Raises ``PermissionError`` unless ``user`` is that reviewer."""
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation_id)
        participant = next((a for a in affs if a.principal == reviewer and getattr(a, "is_reviewer", False)), None)
        if participant is None:
            return None
        if not principal_matches(participant.principal, participant.principal_type, user):
            raise PermissionError("Only the named reviewer can open this review.")
        role = participant.role
        ctx: Dict[str, Any] = {
            "participant_id": participant.id,
            "role": role,
            "review_status": getattr(participant, "review_status", "na"),
            "questionnaire": self._questionnaire_for(role, getattr(participant, "role_category", None)),
            "existing_answers": getattr(participant, "review_answers", None),
            "ar_name": relation.name,
        }
        # Technical/governance reviewers inspect the compiled rule + evidence.
        if (role or "").lower() in ("technical", "governance"):
            ctx["details"] = {
                "actor_identity": relation.actor_identity,
                "action": relation.action,
                "domain_context": relation.domain_context,
                "criteria": [
                    {
                        "name": c.compliance_policy.name if c.compliance_policy else None,
                        "rule": c.compliance_policy.rule if c.compliance_policy else None,
                        "direction": c.direction, "weight": c.weight, "enabled": c.enabled,
                    }
                    for c in sorted(relation.criteria or [], key=lambda x: (x.display_order or 0))
                ],
                "evidence_binding": relation.evidence_binding,
                "evidence_sources": relation.evidence_sources,
                "justification_chain": relation.justification_chain,
            }
        return ctx

    def submit_review(
        self, db: Session, participant_id: str, answers: Dict[str, Any],
        reviewer: Optional[str] = None, user: Any = None,
    ) -> Optional[AuthorityAffirmationDb]:
        """Persist a reviewer's elicited answers and mark their review complete.
        Raises ``PermissionError`` unless ``user`` is that reviewer."""
        participant = authority_affirmation_repo.get(db, participant_id)
        if not participant:
            return None
        if not getattr(participant, "is_reviewer", False):
            raise PermissionError("This participant is not a reviewer.")
        if not principal_matches(participant.principal, participant.principal_type, user):
            raise PermissionError("Only the named reviewer can submit this review.")
        return authority_affirmation_repo.update(db, db_obj=participant, obj_in={
            "review_answers": answers,
            "review_status": "completed",
        })

    def get_review_tracking(self, db: Session, relation_id: str, reviews_manager: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """Owner-facing tracking for an AR's review process: per-reviewer Asset
        Review status (+ the review id to link to) and the workflow execution(s)
        recording the process (the AR-level ``authority-relation-review-request``
        run plus each per-reviewer data-asset-review run). Returns None if the AR
        does not exist. All external lookups are best-effort.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation_id)
        reviewers = [a for a in affs if getattr(a, "is_reviewer", False)]
        review_ids: set = set()
        reviews: List[Dict[str, Any]] = []
        for a in reviewers:
            rid = getattr(a, "review_request_id", None)
            # Only real Asset Review ids are linkable; the synthetic fallback
            # marker (used when no Asset Review could be created) is not.
            linkable = bool(rid) and not str(rid).startswith("authority-relation://")
            request_status = None
            request_title = None
            if linkable:
                review_ids.add(rid)
                if reviews_manager is not None:
                    try:
                        req = reviews_manager.get_review_request(rid)
                        if req is not None:
                            request_status = req.status.value if hasattr(req.status, "value") else str(req.status)
                            request_title = req.title
                    except Exception as e:  # pragma: no cover - env dependent
                        logger.warning(f"Could not load Asset Review {rid} for AR {relation_id}: {e}")
            reviews.append({
                "participant_id": a.id,
                "principal": a.principal,
                "role": a.role,
                "review_status": getattr(a, "review_status", "na"),
                "review_request_id": rid if linkable else None,
                "request_status": request_status,
                "request_title": request_title,
            })
        # Workflow executions recording the process: match the AR itself or any
        # of the per-reviewer Asset Reviews by their trigger-context entity id.
        workflows: List[Dict[str, Any]] = []
        try:
            import json as _json
            from src.repositories.process_workflows_repository import workflow_execution_repo
            target_ids = {relation_id} | review_ids
            for exe in workflow_execution_repo.list_all(db, limit=100):
                entity_id = None
                tc = getattr(exe, "trigger_context", None)
                if tc:
                    try:
                        tcd = _json.loads(tc) if isinstance(tc, str) else tc
                        entity_id = tcd.get("entity_id")
                    except Exception:
                        entity_id = None
                if entity_id in target_ids:
                    wf = getattr(exe, "workflow", None)
                    workflows.append({
                        "execution_id": exe.id,
                        "workflow_id": exe.workflow_id,
                        "workflow_name": wf.name if wf else None,
                        "status": exe.status,
                        "current_step": getattr(exe, "current_step_id", None),
                        "entity_id": entity_id,
                        "started_at": exe.started_at,
                    })
        except Exception as e:  # pragma: no cover - env dependent
            logger.warning(f"Could not load workflow executions for AR {relation_id}: {e}")
        # Always surface the governing AR-review workflow *definition* so the owner
        # can open the process even when no execution row has been materialized.
        try:
            from src.repositories.process_workflows_repository import process_workflow_repo
            gov = process_workflow_repo.get_by_trigger_type(
                db, "on_request_review", entity_type="authority_relation", active_only=True,
            )
            if gov is not None and not any(w.get("workflow_id") == gov.id for w in workflows):
                workflows.append({
                    "execution_id": None,
                    "workflow_id": gov.id,
                    "workflow_name": gov.name,
                    "status": "defined",
                    "current_step": None,
                    "entity_id": relation_id,
                    "started_at": None,
                })
        except Exception as e:  # pragma: no cover - env dependent
            logger.warning(f"Could not load governing workflow for AR {relation_id}: {e}")
        return {"relation_id": relation_id, "reviews": reviews, "workflows": workflows}

    # ------------------------------------------------------- DNA-Coefficient

    def _log_timeline(self, db: Session, relation_id: str, message: str) -> None:
        """Best-effort: append a system comment to the AR's Comments timeline.

        The Comments subsystem is the entity timeline; DNAco runs and automated
        status changes are recorded here so the history is visible on the detail
        view. Never breaks the caller.
        """
        try:
            from src.controller.comments_manager import CommentsManager
            from src.models.comments import CommentCreate
            CommentsManager().create_comment(
                db,
                data=CommentCreate(entity_type=ENTITY_TYPE, entity_id=relation_id, comment=message),
                user_email="system@ontos",
                is_admin=True,
            )
        except Exception as e:  # pragma: no cover - timeline logging is best-effort
            logger.warning(f"Could not write AR timeline comment for {relation_id}: {e}")

    def compute_dnaco(self, db: Session, relation_id: str, rows: Optional[List[Dict[str, Any]]] = None) -> Optional[AuthorityDnaRunDb]:
        """Compute the DNA-Coefficient over the AR's bound evidence.

        ``rows`` may be supplied directly (used by tests); otherwise they are
        read best-effort from the bound Delta table.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None

        run = authority_dna_run_repo.create(db, obj_in={
            "id": str(uuid.uuid4()),
            "relation_id": relation_id,
            "status": "running",
            "started_at": self._now(),
        })

        try:
            if rows is None:
                # Read + normalise across all bound evidence sources (falls back to
                # the legacy single ``evidence_binding``); rows are keyed by the
                # canonical request fields the criteria rules reference.
                rows = self._collect_evidence(relation)
            if not rows:
                raise ValueError("No evidence rows were read; the DNA-Coefficient cannot be measured.")
            criteria = self._load_criteria(relation)
            broken = [c.code for c in criteria if authority_dna.rule_parse_error(c.rule)]
            if broken:
                raise ValueError(f"Criteria with malformed rules: {', '.join(broken)}; fix them before measuring.")
            result = authority_dna.compute_dnaco(criteria, rows)

            # Combine the evidence-based dimensions with the definition-based
            # 'structural' dimension; overall = probabilistic union (noisy-OR),
            # which scales into [0,1] instead of merely clipping a sum.
            dimensions = dict(result.dimensions)
            dimensions["structural"] = self._structural_score(relation)
            overall = authority_dna.combine_dimensions(dimensions.values())

            # Persist per-row divergences as evidence AR Decisions (the DNAco sample).
            for rd in result.rows:
                if not rd.diverged:
                    continue
                authority_decision_repo.create(db, obj_in={
                    "id": str(uuid.uuid4()),
                    "relation_id": relation_id,
                    "relation_version": relation.version,
                    "source": "evidence",
                    "dna_run_id": run.id,
                    "actor_identity": rd.actor_identity,
                    "action": rd.action,
                    "object_id": rd.object_id,
                    "verdict": None,
                    "reason": ", ".join(rd.reasons),
                    "divergence_magnitude": 1.0,
                    "direction": None,
                })

            run = authority_dna_run_repo.update(db, db_obj=run, obj_in={
                "status": "succeeded",
                "finished_at": self._now(),
                "sampled_count": result.sampled_count,
                "divergent_count": result.divergent_count,
                "magnitude": overall,
                "direction": result.direction,
                "per_dimension_scores": dimensions,
            })

            # Roll the run up onto the Definition's aggregate DNAco.
            agg = {
                "dna_magnitude": overall,
                "dna_direction": result.direction,
                "dna_dimensions": dimensions,
                "dna_measured_at": self._now(),
            }
            # An active AR whose divergence exceeded its ceiling is auto-flagged.
            auto_flagged = False
            if relation.status == STATUS_ACTIVE and overall > self._ceiling(relation):
                agg["status"] = STATUS_NEEDS_REVIEW
                auto_flagged = True
            authority_relation_repo.update(db, db_obj=relation, obj_in=agg)

            # Record the run on the entity timeline (Comments).
            dims_str = ", ".join(f"{k} {v:.2f}" for k, v in sorted(dimensions.items()))
            msg = (
                f"DNA-Coefficient computed: {overall:.2f} "
                f"({result.divergent_count}/{result.sampled_count} divergent; {dims_str})."
            )
            if auto_flagged:
                msg += f" Exceeded the ceiling ({relation.dna_max_threshold}); status auto-changed to needs_review."
                self._reindex(db, relation)
            self._log_timeline(db, relation_id, msg)
            return run
        except Exception as e:
            logger.error(f"DNAco computation failed for {relation_id}: {e}", exc_info=True)
            authority_dna_run_repo.update(db, db_obj=run, obj_in={
                "status": "failed", "finished_at": self._now(), "error_message": str(e),
            })
            raise

    def recompute_scheduled(self, db: Session) -> Dict[str, Any]:
        """Recompute the DNA-Coefficient for every AR that has a ``schedule_cron``.

        Invoked by the scheduled ``authority_dna_recompute`` Databricks workflow
        (its own cron drives cadence) and by the manual trigger endpoint. Each
        recompute is isolated; one failure does not abort the batch. Results land
        on each AR's dna-runs, aggregate DNAco, and Comments timeline, and an
        active AR that drifts past its ceiling is auto-flagged ``needs_review``.
        """
        relations = authority_relation_repo.list_all(db)
        due = [r for r in relations if getattr(r, "schedule_cron", None)]
        results: List[Dict[str, Any]] = []
        for r in due:
            try:
                run = self.compute_dnaco(db, r.id)
                results.append({
                    "relation_id": r.id,
                    "run_id": run.id if run else None,
                    "status": run.status if run else "skipped",
                    "magnitude": run.magnitude if run else None,
                })
            except Exception as e:
                logger.warning(f"Scheduled DNAco recompute failed for {r.id}: {e}")
                results.append({"relation_id": r.id, "status": "failed", "error": str(e)})
        return {"scheduled": len(due), "results": results}

    # Canonical request fields the criteria rules reference (``obj.<field>``); the
    # evidence column_map normalises each source's columns onto these names, so the
    # same criterion evaluates against a live request and a historical evidence row.
    _CANONICAL_ELEMENTS = (
        "actor_identity", "action", "value", "escalated", "cosign_present", "object_id",
    )

    def _resolve_evidence_sources(self, relation: AuthorityRelationDb) -> List[Dict[str, Any]]:
        """Resolve an AR's bound evidence to a list of readable Delta tables.

        Each entry is ``{table_fqn, column_map, row_filter}``. ``delta_table`` and
        ``asset`` sources resolve to their ``ref`` (a table/view FQN); ``data_product``
        sources are declared-only in v1 (logged, not read). Falls back to the legacy
        single ``evidence_binding`` when no sources are declared.
        """
        out: List[Dict[str, Any]] = []
        for s in (relation.evidence_sources or []):
            stype = (s or {}).get("type") or "delta_table"
            ref = (s or {}).get("ref")
            if not ref:
                continue
            if stype in ("delta_table", "asset"):
                out.append({"table_fqn": ref, "column_map": s.get("column_map") or {}, "row_filter": s.get("row_filter")})
            elif stype == "data_product":
                logger.info(f"AR evidence source data_product '{ref}' is declared-only in v1 (not read).")
        if not out:
            b = relation.evidence_binding or {}
            if b.get("source_table_fqn"):
                out.append({"table_fqn": b["source_table_fqn"], "column_map": b.get("column_map") or {}, "row_filter": b.get("row_filter")})
        return out

    def _collect_evidence(self, relation: AuthorityRelationDb) -> List[Dict[str, Any]]:
        """Read rows from every resolvable evidence source and normalise them to the
        canonical request fields (with types coerced), so an author's criterion
        rules evaluate against evidence rows exactly as against a live request.
        """
        sources = self._resolve_evidence_sources(relation)
        combined: List[Dict[str, Any]] = []
        for src in sources:
            cm = src.get("column_map") or {}
            raw = self._read_evidence_rows({"source_table_fqn": src["table_fqn"], "row_filter": src.get("row_filter")})
            for r in raw:
                # Keep the source's own columns (rules may reference them directly)
                # and overlay each column_map alias -> source column.
                row = dict(r)
                for alias, col in cm.items():
                    row[alias] = r.get(col)
                combined.append(authority_dna.normalize_row(row))
        return combined

    def _read_evidence_rows(self, binding: Dict[str, Any], limit: int = 500) -> List[Dict[str, Any]]:
        """Read the bound UC Delta table via the SQL warehouse.

        Raises on any failure (no warehouse, missing table, permission denied,
        invalid filter) so ``compute_dnaco`` records a failed run instead of a
        fabricated 0.0 from an empty sample.
        """
        table = (binding or {}).get("source_table_fqn")
        if not table:
            return []
        table = validate_table_fqn(table)
        row_filter = validate_row_filter((binding or {}).get("row_filter"))
        from src.common.config import get_settings
        from src.common.workspace_client import get_workspace_client

        settings = get_settings()
        warehouse_id = (
            getattr(settings, "DATABRICKS_WAREHOUSE_ID", None)
            or getattr(settings, "DATABRICKS_SQL_WAREHOUSE_ID", None)
        )
        if not warehouse_id:
            raise RuntimeError("No SQL warehouse configured; cannot read AR evidence.")
        try:
            ws = get_workspace_client(settings)
            where = f" WHERE {row_filter}" if row_filter else ""
            stmt = f"SELECT * FROM {table}{where} LIMIT {int(limit)}"
            resp = ws.statement_execution.execute_statement(
                warehouse_id=warehouse_id, statement=stmt, wait_timeout="30s",
            )
            manifest = getattr(resp, "manifest", None)
            result = getattr(resp, "result", None)
            if not manifest or not result or not getattr(result, "data_array", None):
                return []
            columns = [c.name for c in manifest.schema.columns]
            return [dict(zip(columns, r)) for r in result.data_array]
        except Exception as e:  # pragma: no cover - depends on live warehouse
            raise RuntimeError(f"Evidence read failed for table '{table}': {e}") from e

    # ------------------------------------------------------------- lifecycle

    @staticmethod
    def _ceiling(relation: AuthorityRelationDb) -> float:
        t = relation.dna_max_threshold
        return DEFAULT_DNA_CEILING if t is None else t

    def set_status(self, db: Session, relation_id: str, status: str) -> Tuple[Optional[AuthorityRelationDb], Optional[str]]:
        """Transition an AR's status. Returns (relation, error_message)."""
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None, "not_found"
        if status not in _ALLOWED_STATUSES:
            return relation, f"Unknown status '{status}' — expected one of {_ALLOWED_STATUSES}."
        if status == STATUS_ACTIVE:
            # Activation gate: DNAco measured & within ceiling, AND fully affirmed.
            if relation.dna_magnitude is None:
                return relation, "DNA-Coefficient has not been measured yet."
            if relation.dna_magnitude > self._ceiling(relation):
                return relation, (
                    f"DNA-Coefficient {relation.dna_magnitude} exceeds the maximum "
                    f"{self._ceiling(relation)}."
                )
            if not self.is_fully_affirmed(db, relation_id):
                return relation, "All required affirmations must be completed before activation."
        previous = relation.status
        updated = authority_relation_repo.update(db, db_obj=relation, obj_in={"status": status})
        if previous != status:
            self._log_timeline(db, relation_id, f"Status changed from {previous} to {status}.")
        self._reindex(db, updated)
        return updated, None

    # --------------------------------------------------------- runtime gate

    def _evaluate_decision(
        self,
        relation: AuthorityRelationDb,
        req: Dict[str, Any],
        resolved_refs: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, str]:
        """Deterministic evaluation of request params against the AR's author-configured
        decision criteria. Each enabled criterion's DSL rule is run against the request;
        the first that fails denies (with its failure message). No criteria = an
        unconstrained gate (approve).
        """
        obj = {k: v for k, v in req.items() if not str(k).startswith(REF_KEY_PREFIX)}
        for r in resolved_refs or []:
            obj[ref_key(r["field_path"])] = r.get("value")
            if r.get("iri"):
                obj[ref_key(r["field_path"]) + "_iri"] = r["iri"]
        norm = authority_dna.normalize_row(obj)
        for c in self._load_criteria(relation):
            parse_error = authority_dna.rule_parse_error(c.rule)
            if parse_error:
                # Fail closed, and say it's the AR's configuration, not the request.
                return VERDICT_CONFLICT, f"Criterion '{c.code}' has a malformed rule: {parse_error}"
            try:
                passed, msg = evaluate_rule_on_object(c.rule, norm)
            except Exception as e:  # pragma: no cover - malformed author rule
                logger.warning(f"Criterion '{c.code}' failed to evaluate on AR {relation.id}: {e}")
                continue
            if not passed:
                return VERDICT_DENIED, (c.message or msg or f"Criterion '{c.code}' failed")
        return VERDICT_APPROVED, "all checks passed"

    def resolve(
        self,
        db: Session,
        ar_ref: str,
        req: Dict[str, Any],
        record: bool = True,
        require_active: bool = True,
        semantic_models_manager: Optional[Any] = None,
        obo_ws_factory: Optional[Callable[[], Any]] = None,
        app_ws_factory: Optional[Callable[[], Any]] = None,
        mcp_client_factory: Optional[Callable[..., Any]] = None,
    ) -> Dict[str, Any]:
        """Deterministically resolve a decision against an AR (by id or slug).

        Production/MCP use requires the AR to be ``active`` and records the
        decision (``require_active=True``, ``record=True``). The detail-view
        **Test** dry-run passes ``require_active=False, record=False`` so an author
        can preview the verdict for a draft/needs_review AR without affecting the
        usage counters. Returns ``no_authority`` when the AR does not exist, or
        (in production mode) is not active.

        Walks any declared ``authority_prerequisites`` depth-first before
        materialising ``authority_resource_refs`` and evaluating the AR's own
        criteria; a required prerequisite that comes back non-approved
        short-circuits the outer verdict to ``denied`` (``conflict`` on a
        cycle). The chain and the resolved refs are attached to the response
        and persisted together on the decision's ``provenance`` column.

        ``semantic_models_manager`` is optional — when a route supplies it,
        ``ontos_entity`` refs targeting Business Concepts can look up a
        label from the semantic graph; otherwise the IRI is passed through
        verbatim (safe for unit tests and cold-start resolves).

        ``obo_ws_factory`` / ``app_ws_factory`` lazily build the caller-scoped
        and app-SP WorkspaceClients for ``mcp_tool`` refs (picked per AR by
        ``resolver_auth``). All MCP calls in one resolve, prerequisites
        included, share a ``RESOLVE_BUDGET_S`` deadline; an MCP failure or
        timeout makes that AR's verdict ``no_authority``.
        """
        rctx = _ResolveCtx(
            semantic_models_manager=semantic_models_manager,
            obo_ws_factory=obo_ws_factory,
            app_ws_factory=app_ws_factory,
            mcp_client_factory=mcp_client_factory or McpHttpClient,
            deadline=Deadline(RESOLVE_BUDGET_S),
            write_cache=record,
        )
        return self._resolve_internal(
            db, ar_ref, req, visited=set(),
            record=record, require_active=require_active, rctx=rctx,
        )

    def _resolve_internal(
        self,
        db: Session,
        ar_ref: str,
        req: Dict[str, Any],
        *,
        visited: set,
        record: bool,
        require_active: bool,
        rctx: _ResolveCtx,
    ) -> Dict[str, Any]:
        # By slug this resolves to the family's active version (the stable @id
        # agents call); by UUID it pins the exact version.
        relation = self.resolve_relation_ref(db, ar_ref)
        if not relation or (require_active and relation.status != STATUS_ACTIVE):
            reason = (
                "no Authority Relation matches the supplied id" if not relation
                else f"Authority Relation is '{relation.status}', not active"
            )
            return {
                "verdict": VERDICT_NO_AUTHORITY,
                "reason": reason,
                "relation_id": relation.id if relation else None,
                "relation_slug": relation.slug if relation else None,
                "prerequisite_chain": [],
                "resolved_refs": [],
            }

        head_slug = self._family_slug_of(db, relation)
        chain: List[Dict[str, Any]] = []
        if head_slug is not None:
            # Entry-time cycle guard: the walker added our head when it recursed in.
            if head_slug in visited:
                return self._finalize_resolve(
                    db, relation, req,
                    VERDICT_CONFLICT,
                    f"cycle detected at {head_slug}",
                    chain, [], record=False,
                )
            visited.add(head_slug)
            try:
                outer_verdict, blocker_reason, chain = self._walk_prerequisites(
                    db, head_slug, req, visited,
                    require_active=require_active, rctx=rctx,
                )
            finally:
                visited.discard(head_slug)
            if outer_verdict is not None:
                # A blocked outer still materialises its own refs — the
                # provenance audit trail wants to show *what the AR was
                # pointing at* even when the chain short-circuited.
                resolved_refs = self._materialise_refs(db, relation, req, rctx)
                out = self._finalize_resolve(
                    db, relation, req, outer_verdict, blocker_reason,
                    chain, resolved_refs, record,
                )
                if outer_verdict == VERDICT_NO_AUTHORITY:
                    out["resolver_failure"] = True
                return out

        resolved_refs = self._materialise_refs(db, relation, req, rctx)
        mcp_failure = next(
            (r for r in resolved_refs if r["ref_type"] == "mcp_tool" and r.get("error")), None,
        )
        if mcp_failure is not None:
            reason = (
                "resolver_timeout" if mcp_failure.get("error_kind") == "timeout"
                else f"MCP ref {mcp_failure['field_path']} failed: {mcp_failure['error']}"
            )
            out = self._finalize_resolve(
                db, relation, req, VERDICT_NO_AUTHORITY, reason, chain, resolved_refs, record,
            )
            out["resolver_failure"] = True
            return out
        verdict, reason = self._evaluate_decision(relation, req, resolved_refs)
        return self._finalize_resolve(
            db, relation, req, verdict, reason, chain, resolved_refs, record,
        )

    def _walk_prerequisites(
        self,
        db: Session,
        head_slug: str,
        req: Dict[str, Any],
        visited: set,
        *,
        require_active: bool,
        rctx: _ResolveCtx,
    ) -> Tuple[Optional[str], Optional[str], List[Dict[str, Any]]]:
        """Depth-first walk over the AR's declared prerequisite edges.

        Each edge is recursed through :meth:`_resolve_internal` with
        ``record=False`` — inner decisions never count on the upstream AR's
        usage metrics — and inherits the outer call's ``require_active``:
        production walks demand each upstream AR be active, while the
        detail-view **Test** dry-run previews the chain against draft rows.
        The ``visited`` set carries family slugs currently on the stack so a
        cycle that the write-time check somehow missed is still caught here.
        Returns ``(blocked_verdict, blocker_reason, chain)``: ``blocked_verdict``
        is ``None`` when every required edge approved, ``conflict`` when the
        blocking edge hit a cycle, ``no_authority`` when it hit an MCP resolver
        failure, else ``denied``. ``chain`` is the full walk
        order (always populated for the caller to persist).
        """
        chain: List[Dict[str, Any]] = []
        edges = authority_prerequisite_repo.list_for_family(
            db, relation_family_slug=head_slug,
        )
        for e in edges:
            pre_slug = e.prerequisite_family_slug
            inner = self._resolve_internal(
                db, pre_slug, req,
                visited=visited, record=False, require_active=require_active,
                rctx=rctx,
            )
            chain.append({
                "slug": pre_slug,
                "version": inner.get("relation_version"),
                "verdict": inner["verdict"],
                "reason": inner.get("reason"),
                "required": e.required,
            })
            # Carry the inner's own chain forward so provenance records the full walk.
            inner_chain = inner.get("prerequisite_chain") or []
            if inner_chain:
                chain.extend(inner_chain)
            if e.required and inner["verdict"] != VERDICT_APPROVED:
                reason = (
                    f"blocked by prerequisite ar:{pre_slug} — "
                    f"{inner.get('reason') or inner['verdict']}"
                )
                # A resolver (MCP) failure upstream is "can't decide", not a denial.
                if inner["verdict"] == VERDICT_CONFLICT:
                    blocked = VERDICT_CONFLICT
                elif inner.get("resolver_failure"):
                    blocked = VERDICT_NO_AUTHORITY
                else:
                    blocked = VERDICT_DENIED
                return blocked, reason, chain
        return None, None, chain

    def _finalize_resolve(
        self,
        db: Session,
        relation: AuthorityRelationDb,
        req: Dict[str, Any],
        verdict: str,
        reason: str,
        chain: List[Dict[str, Any]],
        resolved_refs: List[Dict[str, Any]],
        record: bool,
    ) -> Dict[str, Any]:
        provenance: Optional[Dict[str, Any]] = None
        if chain or resolved_refs:
            provenance = {}
            if chain:
                provenance["chain"] = chain
            if resolved_refs:
                provenance["resolved_refs"] = resolved_refs
        if record:
            authority_decision_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation.id,
                "relation_version": relation.version,
                "source": "mcp",
                "actor_identity": req.get("actor_identity"),
                "action": req.get("action"),
                "object_id": req.get("object_id"),
                "request_params": req,
                "verdict": verdict,
                "reason": reason,
                "provenance": provenance,
            })
            counters = {"usage_count": (relation.usage_count or 0) + 1}
            if verdict == VERDICT_APPROVED:
                counters["approved_count"] = (relation.approved_count or 0) + 1
            elif verdict == VERDICT_DENIED:
                counters["denied_count"] = (relation.denied_count or 0) + 1
            authority_relation_repo.update(db, db_obj=relation, obj_in=counters)

        return {
            "verdict": verdict,
            "reason": reason,
            "relation_id": relation.id,
            "relation_slug": relation.slug,
            "relation_version": relation.version,
            "dna_magnitude": relation.dna_magnitude,
            "dna_direction": relation.dna_direction,
            "prerequisite_chain": chain,
            "resolved_refs": resolved_refs,
        }

    # ------------------------------------------------------- concept lookup

    def _concept_hops(
        self, concept_iri: str, semantic_models_manager: Optional[Any],
    ) -> Dict[str, int]:
        """``{iri: hops}`` — the concept itself (0) plus its broader/related
        concepts one hop out (1), when a semantic graph is available."""
        hops = {concept_iri: 0}
        if semantic_models_manager is None:
            return hops
        try:
            concept = semantic_models_manager.get_concept_details(concept_iri)
        except Exception as e:  # pragma: no cover - RDF read is best-effort
            logger.warning(f"Concept expansion failed for {concept_iri}: {e}")
            return hops
        if concept is not None:
            for iri in list(getattr(concept, "parent_concepts", []) or []) + \
                    list(getattr(concept, "related_concepts", []) or []):
                hops.setdefault(str(iri), 1)
        return hops

    def _caller_equivalents(
        self, value: Any, semantic_models_manager: Optional[Any],
    ) -> set:
        """Casefolded strings a caller-supplied context value is equivalent to:
        the value itself plus the IRI of any concept whose label matches it."""
        text = str(value).strip()
        out = {text.casefold()}
        if semantic_models_manager is None or not text or "://" in text or text.startswith("urn:"):
            return out
        lookup = getattr(semantic_models_manager, "find_concept_iris_by_label", None)
        if lookup is None:
            return out
        try:
            out.update(str(iri).casefold() for iri in lookup(text))
        except Exception as e:  # pragma: no cover - RDF read is best-effort
            logger.warning(f"Concept label lookup failed for {text!r}: {e}")
        return out

    def _ar_context_values(
        self, db: Session, relation: AuthorityRelationDb, rctx: _ResolveCtx,
    ) -> Dict[str, set]:
        """Per ``domain_context`` key, the casefolded values this AR accepts:
        the literal column value plus any ``domain_context.<key>`` ref's value and
        IRI. MCP refs contribute their last cached label (no live call here)."""
        values: Dict[str, set] = {}
        for k, v in (relation.domain_context or {}).items():
            if v is not None and not isinstance(v, (dict, list)):
                values.setdefault(k, set()).add(str(v).strip().casefold())
        for row in authority_resource_ref_repo.list_for_relation(db, relation_id=relation.id):
            if not row.field_path.startswith("domain_context."):
                continue
            key = row.field_path.split(".", 1)[1]
            found: List[Optional[str]] = []
            if row.ref_type == "literal":
                found.append(row.literal_value)
            elif row.ref_type == "ontos_entity":
                lookup = self._resolve_ontos_entity(
                    db, entity_type=row.entity_type or "", entity_id=row.entity_id or "",
                    semantic_models_manager=rctx.semantic_models_manager,
                )
                found += [lookup.get("value"), lookup.get("iri")]
            else:
                found.append(row.cached_label)
            for f in found:
                if f:
                    values.setdefault(key, set()).add(str(f).strip().casefold())
        return values

    def find_authority_for_concept(
        self,
        db: Session,
        concept_iri: str,
        context: Optional[Dict[str, Any]] = None,
        domains: Optional[List[str]] = None,
        request: Optional[Dict[str, Any]] = None,
        *,
        semantic_models_manager: Optional[Any] = None,
        obo_ws_factory: Optional[Callable[[], Any]] = None,
        app_ws_factory: Optional[Callable[[], Any]] = None,
        mcp_client_factory: Optional[Callable[..., Any]] = None,
    ) -> Dict[str, Any]:
        """Which active AR governs ``concept_iri`` in this context?

        Candidates are active ARs whose version family is semantically linked
        (``entity_semantic_links``, entity_type ``authority_relation``, entity_id
        = ``version_family_id``) to the concept or to a concept one broader/
        related hop away. Survivors are pruned in order: drop ARs whose
        ``domain_context`` contradicts the caller's context; keep ARs in a
        requested domain (if any match); keep the nearest hop; keep the highest
        context overlap; prefer ARs whose required prerequisites pass a dry run;
        then highest maturity, then lowest DNA divergence. ``resolved`` is set
        only when exactly one prerequisite-viable AR survives — otherwise the
        agent gets the ranked candidates and ``reason`` (``ambiguous`` /
        ``prerequisites_unmet`` / ``no_authority``).
        """
        from src.repositories.semantic_links_repository import entity_semantic_links_repo

        context = {k: v for k, v in (context or {}).items() if v not in (None, "")}
        wanted_domains = {str(d).strip().casefold() for d in (domains or []) if str(d).strip()}
        rctx = _ResolveCtx(
            semantic_models_manager=semantic_models_manager,
            obo_ws_factory=obo_ws_factory,
            app_ws_factory=app_ws_factory,
            mcp_client_factory=mcp_client_factory or McpHttpClient,
            deadline=Deadline(RESOLVE_BUDGET_S),
        )

        hops_by_iri = self._concept_hops(concept_iri, semantic_models_manager)
        family_hops: Dict[str, Tuple[int, str]] = {}
        for iri, hop in hops_by_iri.items():
            for link in entity_semantic_links_repo.list_for_iri(db, iri=iri):
                if link.entity_type != ENTITY_TYPE:
                    continue
                prev = family_hops.get(link.entity_id)
                if prev is None or hop < prev[0]:
                    family_hops[link.entity_id] = (hop, iri)

        caller_equiv = {k: self._caller_equivalents(v, semantic_models_manager) for k, v in context.items()}
        req = dict(request or {})
        candidates: List[Dict[str, Any]] = []
        for family_id, (hop, via_iri) in family_hops.items():
            anchor = authority_relation_repo.get(db, family_id)
            relation = self._family_active_version(db, anchor) if anchor else None
            if relation is None:
                continue
            slug = self._family_slug_of(db, relation)

            ar_values = self._ar_context_values(db, relation, rctx)
            matches, conflicts = [], []
            for key, equiv in caller_equiv.items():
                accepted = ar_values.get(key)
                if not accepted:
                    continue
                (matches if accepted & equiv else conflicts).append(key)

            assigned = entity_domain_repo.get_domains_for_entity(
                db, entity_type=ENTITY_TYPE, entity_id=relation.id,
            )
            domain_overlap = [
                getattr(d, "domain_name", None) for d in assigned
                if {str(getattr(d, "domain_id", "")).casefold(),
                    str(getattr(d, "domain_name", "")).casefold()} & wanted_domains
            ]

            unmet: List[str] = []
            if slug:
                visited = {slug}
                _, _, chain = self._walk_prerequisites(
                    db, slug, req, visited, require_active=True, rctx=rctx,
                )
                unmet = [e["slug"] for e in chain if e["required"] and e["verdict"] != VERDICT_APPROVED]

            candidates.append({
                "family_slug": slug,
                "relation_id": relation.id,
                "name": relation.name,
                "version": relation.version,
                "matched_via": via_iri,
                "hops": hop,
                "match_score": round(len(matches) / len(context), 4) if context else 0.0,
                "context_matches": matches,
                "context_conflicts": conflicts,
                "domain_overlap": domain_overlap,
                "unmet_prerequisites": unmet,
                "maturity_level_order": relation.maturity_level_order,
                "dna_magnitude": relation.dna_magnitude,
            })

        def _rank(c: Dict[str, Any]) -> Tuple:
            return (
                bool(c["context_conflicts"]),
                bool(c["unmet_prerequisites"]),
                not c["domain_overlap"],
                c["hops"],
                -c["match_score"],
                -(c["maturity_level_order"] if c["maturity_level_order"] is not None else -1),
                c["dna_magnitude"] if c["dna_magnitude"] is not None else float("inf"),
                c["family_slug"] or c["relation_id"],
            )
        candidates.sort(key=_rank)

        def _keep_best(rows: List[Dict[str, Any]], key: Callable[[Dict[str, Any]], Any]) -> List[Dict[str, Any]]:
            if not rows:
                return rows
            best = min(key(r) for r in rows)
            return [r for r in rows if key(r) == best]

        pool = [c for c in candidates if not c["context_conflicts"]]
        if wanted_domains and any(c["domain_overlap"] for c in pool):
            pool = [c for c in pool if c["domain_overlap"]]
        # Unmet prerequisites demote: a viable AR beats a nearer blocked one.
        viable = [c for c in pool if not c["unmet_prerequisites"]]
        pool = viable or pool
        pool = _keep_best(pool, lambda c: c["hops"])
        pool = _keep_best(pool, lambda c: -c["match_score"])
        pool = _keep_best(pool, lambda c: -(c["maturity_level_order"] if c["maturity_level_order"] is not None else -1))
        pool = _keep_best(pool, lambda c: c["dna_magnitude"] if c["dna_magnitude"] is not None else float("inf"))

        if not pool:
            return {"candidates": candidates, "resolved": None, "reason": "no_authority"}
        if not viable:
            return {"candidates": candidates, "resolved": None, "reason": "prerequisites_unmet"}
        if len(pool) > 1:
            return {"candidates": candidates, "resolved": None, "reason": "ambiguous"}
        winner = pool[0]
        return {
            "candidates": candidates,
            "resolved": winner["family_slug"] or winner["relation_id"],
            "reason": "unique match",
        }

    # --------------------------------------------------------- read assembly

    def to_read_dict(self, db: Session, relation: AuthorityRelationDb) -> Dict[str, Any]:
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation.id)
        # Load criteria via the repo (not relation.criteria) so a create/update
        # response reflects rows just written in the same transaction.
        criteria = authority_criterion_repo.list_for_relation(db, relation_id=relation.id)
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation.id)
        fully_affirmed = self.is_fully_affirmed(db, relation.id)
        # The slug is the family-level agent @id but physically lives on one
        # version row (new versions have none). Surface the family's slug on
        # every version so it stays visible as the stable identifier.
        family_slug = relation.slug
        if not family_slug:
            fam_id = getattr(relation, "version_family_id", None) or relation.id
            for v in authority_relation_repo.get_family_versions(db, family_id=fam_id):
                if v.slug:
                    family_slug = v.slug
                    break
        # Polymorphic tags (best-effort — never break the read).
        tags: List[Dict[str, Any]] = []
        try:
            from src.controller.tags_manager import TagsManager
            for t in TagsManager().list_assigned_tags(db, entity_id=relation.id, entity_type=ENTITY_TYPE):
                tags.append({
                    "fully_qualified_name": getattr(t, "fully_qualified_name", None),
                    "assigned_value": getattr(t, "assigned_value", None),
                })
        except Exception as e:  # pragma: no cover - tag read is best-effort
            logger.warning(f"Could not read tags for AR {relation.id}: {e}")
        return {
            "id": relation.id,
            "slug": relation.slug,
            "family_slug": family_slug,
            "name": relation.name,
            "description": relation.description,
            "status": relation.status,
            # Maturity now comes from the shared compliance-gated Maturity Level
            # feature (cached order + timestamp; full report via the maturity API).
            "maturity_level_order": relation.maturity_level_order,
            "maturity_evaluated_at": relation.maturity_evaluated_at,
            "version": relation.version,
            "version_family_id": relation.version_family_id,
            "parent_relation_id": getattr(relation, "parent_relation_id", None),
            "base_name": getattr(relation, "base_name", None),
            "change_summary": getattr(relation, "change_summary", None),
            "draft_owner_id": getattr(relation, "draft_owner_id", None),
            "owner_team_id": getattr(relation, "owner_team_id", None),
            "owner_team_name": self._name_of(db, TeamDb, getattr(relation, "owner_team_id", None)),
            "project_id": getattr(relation, "project_id", None),
            "project_name": self._name_of(db, ProjectDb, getattr(relation, "project_id", None)),
            # Transient family size set by list_relations; absent on single reads.
            "version_count": getattr(relation, "_version_count", None),
            "actor_role": relation.actor_role,
            "actor_identity": relation.actor_identity,
            "actor_since": relation.actor_since,
            "action": relation.action,
            "object_type": relation.object_type,
            "object_id": relation.object_id,
            "object_resolves_to": relation.object_resolves_to,
            "domain_context": relation.domain_context,
            "justification_chain": relation.justification_chain,
            "decision_logic": relation.decision_logic,
            "evidence_binding": relation.evidence_binding,
            "evidence_sources": relation.evidence_sources,
            "dna_magnitude": relation.dna_magnitude,
            "dna_direction": relation.dna_direction,
            "dna_dimensions": relation.dna_dimensions,
            "dna_measured_at": relation.dna_measured_at,
            "dna_max_threshold": relation.dna_max_threshold,
            "schedule_cron": relation.schedule_cron,
            "resolver_auth": getattr(relation, "resolver_auth", None) or RESOLVER_AUTH_OBO,
            "fully_affirmed": fully_affirmed,
            "usage_count": relation.usage_count,
            "approved_count": relation.approved_count,
            "denied_count": relation.denied_count,
            "domains": [d.dict() if hasattr(d, "dict") else d for d in domains],
            "affirmations": [
                {
                    "id": a.id, "role": a.role, "principal": a.principal,
                    "business_role_id": getattr(a, "business_role_id", None),
                    "role_category": getattr(a, "role_category", None),
                    "principal_type": a.principal_type, "required": a.required,
                    "affirmed": a.affirmed, "affirmed_by": a.affirmed_by,
                    "affirmed_at": a.affirmed_at, "sort_order": a.sort_order,
                    "is_approver": getattr(a, "is_approver", True),
                    "is_reviewer": getattr(a, "is_reviewer", False),
                    "review_status": getattr(a, "review_status", "na"),
                    "review_request_id": getattr(a, "review_request_id", None),
                }
                for a in affs
            ],
            "criteria": [
                {
                    "id": c.id,
                    "policy_id": c.compliance_policy_id,
                    "name": c.compliance_policy.name if c.compliance_policy else None,
                    "rule": c.compliance_policy.rule if c.compliance_policy else None,
                    "failure_message": c.compliance_policy.failure_message if c.compliance_policy else None,
                    "category": c.compliance_policy.category if c.compliance_policy else None,
                    "direction": c.direction,
                    "weight": c.weight,
                    "dimension": getattr(c, "dimension", "people"),
                    "order": c.display_order,
                    "enabled": c.enabled,
                }
                for c in criteria
            ],
            "prerequisites": self.list_prerequisites(db, relation),
            "resource_refs": self.list_resource_refs(db, relation),
            "tags": tags,
            "created_at": relation.created_at,
            "updated_at": relation.updated_at,
            "created_by": relation.created_by,
        }
