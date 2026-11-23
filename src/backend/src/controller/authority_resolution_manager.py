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
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.exc import UnmappedInstanceError

from src.common.api_errors import CodedValueError, client_failure
from src.common.review_access import AUTHORITY_RELATION_FQN_PREFIX, authority_relation_fqn
from src.common.timestamps import utc_now
from src.common.logging import get_logger
from src.models.tags import AssignedTagCreate
from src.models.authority_resolution import EvidenceBinding, EvidenceSource
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.common import authority_definition as definition
from src.common import authority_resolution_dna as authority_dna
from src.common.authority_resolution_dna import Criterion, DIR_NONE
from src.common.authority_check_templates import get_template
from src.common.compliance_dsl import evaluate_rule_strict
from src.common import authority_rule as arule
from src.common import mcp_resolver
from src.controller import authority_policy_manager as apol
from src.common.mcp_resolver import Deadline, McpHttpClient, McpResolverError
from src.db_models.authority_resolution import (
    AuthorityRelationDb,
    AuthorityAffirmationDb,
    AuthorityDecisionDb,
    AuthorityDnaRunDb,
)
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.metadata import LinkMetadataDb, RichTextMetadataDb
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
from src.repositories.authority_policy_repository import authority_policy_repo

logger = get_logger(__name__)


class AuthorityInvalidError(CodedValueError):
    """An Authority Relation definition the author must fix; the message says what."""

    code = "authority_invalid"


class AuthorityPermissionError(CodedValueError, PermissionError):
    """The caller's Authority Resolution level, or their named role, does not allow this.

    Also a ``PermissionError``, so callers that catch the built-in keep working.
    """

    code = "authority_permission_denied"


class AuthorityNotNamedError(AuthorityPermissionError):
    """The caller is not the principal the participant row names."""

    code = "authority_not_named_participant"


class AuthorityReviewerNotApproverError(AuthorityPermissionError):
    """An affirmation was sent for a reviewer row, which only reviews."""

    code = "authority_reviewer_not_approver"


class AuthorityReviewOutcomeError(CodedValueError):
    """A review outcome other than approve or needs clarification."""

    code = "authority_invalid_review_outcome"


class AuthorityNotAReviewerError(AuthorityPermissionError):
    """A review was submitted for a participant that is not a reviewer."""

    code = "authority_not_a_reviewer"


class AuthorityImmutableError(CodedValueError):
    """An edit to an active, retired or earlier version. Create a New Version instead (B6)."""

    code = "authority_immutable"
    http_status = 409


class AuthorityStatusError(CodedValueError):
    """A status change the lifecycle refuses; ``params.reason`` says which gate failed (S3, B5, B6)."""

    code = "authority_status_conflict"
    http_status = 409


class AuthorityInvalidVersionError(AuthorityInvalidError):
    """A version string that is not X.Y.Z."""

    code = "authority_invalid_version"


class AuthorityDuplicateVersionError(CodedValueError):
    """A version string the family already has (N6)."""

    code = "authority_duplicate_version"
    http_status = 409


class AuthorityHasHistoryError(CodedValueError):
    """A delete refused because the version has decisions or DNA runs (S1). Retire it instead."""

    code = "authority_has_history"
    http_status = 409


class AuthoritySelfAffirmationError(AuthorityPermissionError):
    """The signed-in user created, or last changed, the definition they would affirm (B4)."""

    code = "authority_self_affirmation"


def client_failure_text(tag: str, exc: BaseException) -> str:
    """The text a client may see for a failed run.

    Our own validation messages go out as they are. Anything else (SQL, warehouse
    or workspace errors) is logged once with an error id and answered with a
    generic message, so the exception text never reaches a user, an MCP client or
    the ``error_message`` column read back by the DNA run list. The id is kept on
    the exception, so the route that re-raises it reports the same id.
    """
    if isinstance(exc, CodedValueError):
        return str(exc)
    payload = client_failure(
        tag, exc, code="",
        message="The " + tag + " failed (error id {errorId}); see the server log.",
    )
    return payload["message"]


ENTITY_TYPE = "authority_relation"
# A version string is MAJOR.MINOR.PATCH (N6).
_SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")
FEATURE_ID = "authority-resolution"  # search feature filter (common/features.py)

# Verdicts returned by the runtime gate.
VERDICT_APPROVED = "approved"
VERDICT_DENIED = "denied"
VERDICT_NO_AUTHORITY = "no_authority"
VERDICT_CONFLICT = "conflict"
# Permitted, with duties still to fulfil (e.g. a pending co-approval).
VERDICT_CONDITIONAL = "conditional"

# AR lifecycle statuses.
STATUS_DRAFT = "draft"
STATUS_ACTIVE = "active"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_RETIRED = "retired"

# Allowed status changes (S3), in one place. A status not listed is refused.
# Leaving needs_review for draft is refused once the version was activated (it would
# make a published snapshot editable). Retiring clears the affirmations, so a
# retired version comes back only with fresh ones.
_ALLOWED_TRANSITIONS = {
    STATUS_DRAFT: {STATUS_NEEDS_REVIEW, STATUS_ACTIVE, STATUS_RETIRED},
    STATUS_NEEDS_REVIEW: {STATUS_DRAFT, STATUS_ACTIVE, STATUS_RETIRED},
    STATUS_ACTIVE: {STATUS_NEEDS_REVIEW, STATUS_RETIRED},
    STATUS_RETIRED: {STATUS_ACTIVE},
}

# Reason code and message when an AR has no enabled decision check (B5).
REASON_NO_ENABLED_CHECKS = "no_enabled_checks"
REASON_MISSING_OPERAND = "missing_operand"      # a request value a rule reads is absent (denied)
REASON_MISSING_PARAMETER = "missing_parameter"  # an AR parameter a rule reads is absent (conflict)
NO_ENABLED_CHECKS_MESSAGE = "This Authority Relation has no enabled decision checks."

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
_UNSET = object()  # "not passed" for optional kwargs whose None is meaningful


def ref_key(field_path: str) -> str:
    return REF_KEY_PREFIX + re.sub(r"[^A-Za-z0-9_]", "_", field_path)


DEFAULT_DNA_CEILING = 0.3
# Compliance category of reusable checks written in Compliance for Authority Resolution.
ARF_CHECK_CATEGORY = "Authority Decision"
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
        raise AuthorityInvalidError(f"Evidence table '{fqn}' must be a plain catalog.schema.table name.")
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
        raise AuthorityInvalidError("Evidence row_filter may not contain backslashes.")
    pos, prev_ident = 0, False
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        m = _FILTER_TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise AuthorityInvalidError(f"Evidence row_filter has unsupported syntax near: {text[pos:pos + 20]!r}")
        ident = m.group("ident")
        if ident is not None and not ident.startswith("`"):
            word = ident.upper()
            if word in _FILTER_FORBIDDEN:
                raise AuthorityInvalidError(f"Evidence row_filter may not use '{ident}'.")
        if m.group("punct") == "(" and prev_ident:
            raise AuthorityInvalidError("Evidence row_filter may not call functions.")
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


def _without_clause(c: Any) -> Any:
    if hasattr(c, "policy_clause_ref"):
        c.policy_clause_ref = None
        return c
    return {**dict(c), "policy_clause_ref": None}


def _strip_rule_clauses(rule: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The rule without its items' ``clause`` citations."""
    if not isinstance(rule, dict):
        return rule
    perm = rule.get("permission") or {}
    drop = lambda items: [{k: v for k, v in i.items() if k != "clause"} for i in items or []]  # noqa: E731
    out = {"permission": {"constraint": drop(perm.get("constraint")), "duty": drop(perm.get("duty"))}}
    if rule.get("prohibition"):
        out["prohibition"] = drop(rule["prohibition"])
    return out


def _cite(reason: str, clause: Optional[str], policy_label: Optional[str]) -> str:
    """A denial reason naming the policy clause it enforces, if any."""
    if not clause:
        return reason
    return f"{reason} [{policy_label} {clause}]" if policy_label else f"{reason} [{clause}]"


# The two outcomes of an AR review (#859 review, decided 2026-11-22)
AR_REVIEW_APPROVE = "approve"
AR_REVIEW_NEEDS_CLARIFICATION = "needs_clarification"
AR_REVIEW_OUTCOMES = (AR_REVIEW_APPROVE, AR_REVIEW_NEEDS_CLARIFICATION)


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
    # Concept-label equivalents per context value, shared by every hop of one
    # resolve (each lookup reads the semantic graph).
    equivalents: Dict[str, set] = field(default_factory=dict)


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

    # ------------------------------------------------ definition and hash (B6)

    @staticmethod
    def _version_tuple(version: Any) -> Tuple[int, ...]:
        parts = [int(p) for p in str(version or "").split(".") if p.isdigit()]
        return tuple(parts) or (0,)

    def _latest_version(self, db: Session, relation: AuthorityRelationDb) -> Optional[AuthorityRelationDb]:
        """The family's highest version string (ties go to the newest row)."""
        family_id = getattr(relation, "version_family_id", None) or relation.id
        best: Optional[AuthorityRelationDb] = None
        for v in authority_relation_repo.get_family_versions(db, family_id=family_id):
            if best is None or self._version_tuple(v.version) > self._version_tuple(best.version):
                best = v
        return best

    def is_editable(self, db: Session, relation: AuthorityRelationDb) -> bool:
        """Only a draft that was never activated, and is the family's latest version, can be edited.

        Active, retired and needs_review versions, and every older version, are
        immutable: a change goes through New Version (B6).
        """
        if relation.status != STATUS_DRAFT or getattr(relation, "activated_at", None) is not None:
            return False
        latest = self._latest_version(db, relation)
        return latest is None or latest.id == relation.id

    @staticmethod
    def _normal_scalars(scalars: Dict[str, Any]) -> Dict[str, Any]:
        """Run the nested evidence values through their models, so a payload that leaves a
        default out and a stored row that holds it are the same definition (review #2)."""
        out = dict(scalars)
        # Scope/params and the rule are hashed in their normalised form, so a re-sent
        # unchanged definition (or a legacy flat blob) is the same definition.
        if out.get("domain_context") is not None:
            out["domain_context"] = arule.normalize_domain_context(out["domain_context"])
        if out.get("rule") is not None:
            out["rule"] = arule.normalize_rule(out["rule"])
        if out.get("evidence_sources") is not None:
            out["evidence_sources"] = [
                EvidenceSource(**(e if isinstance(e, dict) else e.dict())).dict()
                for e in out["evidence_sources"]
            ]
        if out.get("evidence_binding") is not None:
            b = out["evidence_binding"]
            out["evidence_binding"] = EvidenceBinding(**(b if isinstance(b, dict) else b.dict())).dict()
        return out

    @staticmethod
    def _criterion_dict(c: Any) -> Dict[str, Any]:
        return {
            "name": c.name, "rule": c.rule, "failure_message": c.failure_message,
            "direction": c.direction, "weight": c.weight, "dimension": c.dimension,
            "display_order": c.display_order, "enabled": c.enabled,
            "policy_clause_ref": getattr(c, "policy_clause_ref", None),
        }

    def _stored_view(self, db: Session, relation: AuthorityRelationDb) -> Dict[str, Any]:
        """The definition as it is stored (see ``authority_definition`` for what it covers)."""
        criteria = [self._criterion_dict(c) for c in authority_criterion_repo.list_for_relation(
            db, relation_id=relation.id)]
        prerequisites = [
            {"prerequisite_family_slug": e.prerequisite_family_slug,
             "required": e.required, "display_order": e.display_order}
            for e in authority_prerequisite_repo.list_for_relation(db, relation_id=relation.id)
        ]
        refs = [
            {**{k: getattr(r, k) for k in definition.RESOURCE_REF_KEYS},
             "mcp_result_pointer": r.mcp_result_pointer or "$"}
            for r in authority_resource_ref_repo.list_for_relation(db, relation_id=relation.id)
        ]
        participants = [
            {k: getattr(a, k, None) for k in definition.PARTICIPANT_KEYS}
            for a in authority_affirmation_repo.list_for_relation(db, relation_id=relation.id)
        ]
        scalars = self._normal_scalars({k: getattr(relation, k, None) for k in ("name", *definition.DEFINITION_FIELDS)})
        return definition.definition_view(scalars, criteria, prerequisites, refs, participants)

    def definition_hash(self, db: Session, relation: AuthorityRelationDb) -> str:
        """The hash of the AR's current definition. Runs and affirmations store it."""
        return definition.definition_hash(self._stored_view(db, relation))

    def _incoming_view(
        self, db: Session, relation: AuthorityRelationDb, data: Dict[str, Any],
        criteria_rows: Optional[List[Dict[str, Any]]], affirmations: Optional[List[Any]],
        prerequisites: Optional[List[Any]], resource_refs: Optional[List[Any]],
    ) -> Dict[str, Any]:
        """The definition a PUT would produce, in the same canonical form as the stored one.

        A list the PUT doesn't carry is taken from the stored definition.
        """
        stored = self._stored_view(db, relation)
        scalars = self._normal_scalars({k: (data[k] if k in data else getattr(relation, k, None))
                                        for k in ("name", *definition.DEFINITION_FIELDS)})
        if "resolver_auth" in data:
            scalars["resolver_auth"] = data["resolver_auth"] or RESOLVER_AUTH_OBO
        if "dna_max_threshold" in data and data["dna_max_threshold"] is None:
            scalars["dna_max_threshold"] = DEFAULT_DNA_CEILING
        crit = stored["criteria"] if criteria_rows is None else criteria_rows
        prereqs = stored["prerequisites"] if prerequisites is None else list(
            self._prerequisite_rows(prerequisites).values())
        refs = stored["resource_refs"] if resource_refs is None else self._resource_ref_rows(resource_refs)
        parts = stored["participants"] if affirmations is None else [
            self._participant_row(a) for a in affirmations]
        return definition.definition_view(scalars, crit, prereqs, refs, parts)

    @staticmethod
    def _participant_row(item: Any) -> Dict[str, Any]:
        a = item.dict() if hasattr(item, "dict") else dict(item)
        return {
            "principal": a.get("principal"), "principal_type": a.get("principal_type") or "user",
            "role": a.get("role"), "business_role_id": a.get("business_role_id"),
            "role_category": a.get("role_category"),
            "is_approver": a.get("is_approver", True), "is_reviewer": a.get("is_reviewer", False),
            "required": a.get("required", True),
        }

    @staticmethod
    def _prerequisite_rows(prerequisites: List[Any]) -> Dict[str, Dict[str, Any]]:
        """Prerequisite edges as they will be stored: one per slug, the last one wins."""
        rows: Dict[str, Dict[str, Any]] = {}
        for idx, item in enumerate(prerequisites):
            p = item.dict() if hasattr(item, "dict") else dict(item)
            slug = (p.get("prerequisite_family_slug") or "").strip()
            if not slug:
                continue
            rows[slug] = {
                "prerequisite_family_slug": slug,
                "required": bool(p.get("required", True)),
                "display_order": int(p.get("display_order", idx)),
            }
        return rows

    @staticmethod
    def _resource_ref_rows(refs: List[Any]) -> List[Dict[str, Any]]:
        rows: Dict[str, Dict[str, Any]] = {}
        for item in refs:
            r = item.dict() if hasattr(item, "dict") else dict(item)
            field_path = (r.get("field_path") or "").strip()
            if not field_path:
                continue
            rows[field_path] = {
                **{k: r.get(k) for k in definition.RESOURCE_REF_KEYS},
                "field_path": field_path,
                "mcp_result_pointer": r.get("mcp_result_pointer") or "$",
            }
        return list(rows.values())

    def _load_criteria(self, relation: AuthorityRelationDb) -> List[Criterion]:
        """The AR's enabled decision checks as engine ``Criterion`` objects.

        Each check is owned by this AR version (ARF 1.2.0): its DSL ``ASSERT`` rule is
        the condition, and ``direction``/``weight``/``dimension`` are the ARF divergence
        facets. Drives both the runtime gate and the DNA-Coefficient engine.
        """
        out: List[Criterion] = []
        for c in sorted(relation.criteria or [], key=lambda x: (x.display_order or 0)):
            if not getattr(c, "enabled", True):
                continue
            out.append(Criterion(
                # Human-readable label (name) preferred so DNAco divergence reasons
                # and the timeline read cleanly; falls back to the row id.
                code=(c.name or c.id),
                rule=c.rule,
                direction=c.direction or "neutral",
                weight=c.weight if c.weight is not None else 1.0,
                dimension=getattr(c, "dimension", None) or "people",
                message=c.failure_message or None,
                clause=getattr(c, "policy_clause_ref", None) or None,
            ))
        return out

    # Essential elements an AR definition should carry; each missing one raises the
    # 'structural' DNAco dimension. Extensible — add checks here.
    def _structural_score(self, relation: AuthorityRelationDb) -> float:
        """Score the AR *definition's* completeness (0.0 = complete, higher = more
        essentials missing). This is the ``structural`` DNAco dimension — evaluated
        on the AR itself, not on evidence rows."""
        checks = [
            self._has_justification(relation),                        # documented basis
            bool(relation.object_id),                                 # governs a concrete object
            bool(relation.evidence_sources
                 or (relation.evidence_binding or {}).get("source_table_fqn")),  # evidence bound
            any(getattr(c, "enabled", True) for c in (relation.criteria or [])) or arule.has_rule(getattr(relation, "rule", None)),  # has an enabled decision check or rule
            any(getattr(a, "is_approver", True) for a in (relation.affirmations or [])),  # has an approver
        ]
        missing = sum(1 for ok in checks if not ok)
        return round(missing / len(checks), 4)

    @staticmethod
    def _has_justification(relation: AuthorityRelationDb) -> bool:
        """A cited policy reference is the documented basis. Its validity doesn't
        change this (ARF 1.2.0: references are metadata); without a reference the
        legacy free-form justification chain counts."""
        if getattr(relation, "authority_policy_id", None):
            return True
        return bool(relation.justification_chain)

    def _validate_citation(
        self, db: Session, policy_id: Optional[str], clause_refs: Optional[List[str]],
        criteria: Optional[List[Any]], rule: Optional[Dict[str, Any]],
    ) -> Optional[List[str]]:
        """Check an AR's policy reference; returns the cleaned clause labels.

        The reference must exist. Its validity is not checked: a reference is
        metadata (ARF 1.2.0), and a check can enforce validity if the author adds
        one. Clause labels are free text, checked against nothing; they need a
        reference to be cited against.
        """
        refs = [str(r).strip() for r in clause_refs or [] if str(r).strip()]
        cited = list(refs)
        cited += [str((c.dict() if hasattr(c, "dict") else c).get("policy_clause_ref") or "").strip()
                  for c in criteria or []]
        cited += apol._rule_clauses(rule)
        if not policy_id:
            if any(cited):
                raise AuthorityInvalidError("Cite a policy reference before citing its clauses.")
            return refs or None
        if authority_policy_repo.get(db, policy_id) is None:
            raise AuthorityInvalidError(f"Policy reference '{policy_id}' not found.")
        return list(dict.fromkeys(refs)) or None

    # ------------------------------------------------------------------ CRUD

    def create_relation(
        self, db: Session, payload, current_user: Optional[str] = None, caller_is_admin: bool = False,
    ) -> AuthorityRelationDb:
        data = payload.dict() if hasattr(payload, "dict") else dict(payload)
        self._refuse_admin_only_changes(data, None, caller_is_admin)
        self._check_version_format(data.get("version") or "1.0.0")
        self._validate_ceiling(data.get("dna_max_threshold", 0.3))
        self._validate_business_roles(db, data.get("affirmations") or [])
        rel_id = str(uuid.uuid4())

        evidence = data.get("evidence_binding")
        if evidence is not None and hasattr(evidence, "dict"):
            evidence = evidence.dict()
        _validate_evidence(evidence, data.get("evidence_sources"))
        self._validate_scoping(db, data)

        domain_context = arule.normalize_domain_context(data.get("domain_context"), strict=True)
        rule = arule.normalize_rule(data.get("rule"))
        # A new AR has no stored checks: its rows are computed once, without a query for its id.
        criteria_rows = self._criteria_rows(db, rel_id, data.get("criteria") or [], existing=[])
        self._check_parameter_references(
            db, rel_id, domain_context=domain_context, rule=rule,
            criteria_rows=criteria_rows, resource_refs=data.get("resource_refs") or [],
        )

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
            "domain_context": domain_context,
            "rule": rule,
            "justification_chain": data.get("justification_chain"),
            "authority_policy_id": data.get("authority_policy_id") or None,
            "policy_clause_refs": self._validate_citation(
                db, data.get("authority_policy_id") or None, data.get("policy_clause_refs"),
                data.get("criteria"), arule.normalize_rule(data.get("rule")),
            ),
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
            "definition_edited_by": current_user,
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
        self._replace_criteria(db, rel_id, criteria_rows)
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
        # The collections were loaded (empty) when the row was created; reload
        # them so a resolve in the same session sees the criteria just written.
        db.flush()
        db.expire(relation, ["criteria", "affirmations", "resource_refs"])
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
                raise AuthorityInvalidError(f"{label} '{value}' not found")

    @staticmethod
    def _name_of(db: Session, model, entity_id: Optional[str]) -> Optional[str]:
        if not entity_id:
            return None
        row = db.get(model, entity_id)
        return getattr(row, "name", None) if row else None

    # Settings only an Admin may set or change (permission matrix, ARF 1.2.0):
    # the MCP identity, the DNA ceiling and the recompute schedule.
    _ADMIN_ONLY_FIELDS = ("resolver_auth", "dna_max_threshold", "schedule_cron")

    @staticmethod
    def _refuse_admin_only_changes(
        data: Dict[str, Any], current: Optional[AuthorityRelationDb], caller_is_admin: bool,
    ) -> None:
        """Refuse a change to an Admin-only setting by a non-Admin.

        ``current`` is None on create, so the baseline is the column default. A
        value that is merely re-sent unchanged is not a change, which keeps an
        Admin's settings editable by a Read-write author.
        """
        if caller_is_admin:
            return

        def normal(field: str, value: Any) -> Any:
            if field == "resolver_auth":
                return value or RESOLVER_AUTH_OBO
            if field == "dna_max_threshold":
                return DEFAULT_DNA_CEILING if value is None else float(value)
            return value or None

        for field in AuthorityResolutionManager._ADMIN_ONLY_FIELDS:
            if field not in data:
                continue
            old = getattr(current, field, None) if current is not None else None
            if normal(field, data[field]) == normal(field, old):
                continue
            raise AuthorityPermissionError(
                f"Only an Admin can change '{field}' on an Authority Relation.",
                field=field, required_level="Admin",
            )

    @staticmethod
    def _check_version_format(version: Any) -> str:
        text = str(version or "")
        if not _SEMVER_RE.fullmatch(text):
            raise AuthorityInvalidVersionError(
                f"Version '{text}' must look like 1.0.0 (major.minor.patch).", version=text,
            )
        return text

    @staticmethod
    def _validate_ceiling(value: Any) -> None:
        """The DNA ceiling is a fraction in [0, 1]; NaN and infinities are refused (B4)."""
        if value is None:
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise AuthorityInvalidError("The DNA-Coefficient ceiling must be a number between 0 and 1.")
        if not math.isfinite(number) or number < 0 or number > 1:
            raise AuthorityInvalidError(
                "The DNA-Coefficient ceiling must be between 0 and 1.", value=number,
            )

    @staticmethod
    def _validate_business_roles(db: Session, affirmations: List[Any]) -> None:
        """Each participant's Business Role must exist in Settings (B4)."""
        for item in affirmations or []:
            a = item.dict() if hasattr(item, "dict") else dict(item)
            role_id = a.get("business_role_id")
            if not role_id:
                continue
            try:
                parsed = uuid.UUID(str(role_id))
            except (TypeError, ValueError):
                raise AuthorityInvalidError(f"Business role '{role_id}' does not exist.", role=str(role_id))
            if db.get(BusinessRoleDb, parsed) is None:
                raise AuthorityInvalidError(f"Business role '{role_id}' does not exist.", role=str(role_id))

    @staticmethod
    def _validate_resolver_auth(value: Optional[str]) -> str:
        value = value or RESOLVER_AUTH_OBO
        if value not in _RESOLVER_AUTH_VALUES:
            raise AuthorityInvalidError(
                f"resolver_auth must be one of {_RESOLVER_AUTH_VALUES}, got '{value}'."
            )
        return value

    def list_reusable_checks(
        self, db: Session, category: Optional[str] = None, caller_can_read_compliance: bool = False,
    ) -> List[CompliancePolicyDb]:
        """Active Compliance Checks an author can reuse as criteria (S13).

        Without Compliance read only the ARF checks ("Authority Decision") are
        listed; the Compliance library is not exposed to Authority Resolution.
        """
        q = db.query(CompliancePolicyDb).filter(CompliancePolicyDb.is_active == True)  # noqa: E712
        if not caller_can_read_compliance:
            q = q.filter(CompliancePolicyDb.category == ARF_CHECK_CATEGORY)
        if category:
            q = q.filter(CompliancePolicyDb.category == category)
        return q.order_by(CompliancePolicyDb.name.asc()).all()

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

    def update_relation(
        self, db: Session, relation_id: str, payload, current_user: Optional[str] = None,
        caller_is_admin: bool = False,
    ) -> Optional[AuthorityRelationDb]:
        """Edit an AR. Only a draft's definition can change (B6).

        A change to the definition of an active, retired, needs-review or older
        version is refused with ``authority_immutable`` (409): create a New Version.
        Metadata (description, owner, project, domains, tags) can change on any
        version. On a draft, a change to the behaviour hash clears the DNA
        measurement; the affirmations of the earlier definition stop counting
        because their hash no longer matches.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        data = payload.dict(exclude_unset=True) if hasattr(payload, "dict") else dict(payload)
        self._refuse_admin_only_changes(data, relation, caller_is_admin)
        if "dna_max_threshold" in data:
            self._validate_ceiling(data["dna_max_threshold"])
        if data.get("affirmations") is not None:
            self._validate_business_roles(db, data["affirmations"])

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
        if "domain_context" in data:
            # Each part sent (scope / params) replaces that part; the other stays.
            data["domain_context"] = arule.merge_domain_context(relation.domain_context, data["domain_context"])
        if "rule" in data:
            data["rule"] = arule.normalize_rule(data["rule"])
        if {"authority_policy_id", "policy_clause_refs", "rule"} & data.keys() or criteria is not None:
            if "authority_policy_id" in data:
                data["authority_policy_id"] = data["authority_policy_id"] or None
            policy_id = data.get("authority_policy_id", relation.authority_policy_id)
            # Dropping the policy drops every clause citation with it: the AR's,
            # its rule items' and its checks'.
            refs = data.get("policy_clause_refs", relation.policy_clause_refs if policy_id else None)
            if not policy_id:
                refs = None
                data["rule"] = _strip_rule_clauses(data["rule"] if "rule" in data else relation.rule)
                if criteria is not None:
                    criteria = [_without_clause(c) for c in criteria]
                else:
                    for c in relation.criteria or []:
                        c.policy_clause_ref = None
            existing_criteria = [{"policy_clause_ref": c.policy_clause_ref} for c in relation.criteria or []]
            data["policy_clause_refs"] = self._validate_citation(
                db, policy_id, refs,
                criteria if criteria is not None else existing_criteria,
                data["rule"] if "rule" in data else relation.rule,
            )

        before = self._stored_view(db, relation)
        criteria_rows = None if criteria is None else self._criteria_rows(db, relation_id, criteria)
        incoming = self._incoming_view(db, relation, data, criteria_rows, affirmations, prerequisites, resource_refs)
        definition_changes = definition.definition_fingerprint(before) != definition.definition_fingerprint(incoming)
        editable = self.is_editable(db, relation)
        if editable and definition_changes:
            self._check_parameter_references(
                db, relation_id,
                domain_context=data.get("domain_context", relation.domain_context),
                rule=data["rule"] if "rule" in data else getattr(relation, "rule", None),
                criteria_rows=criteria_rows, resource_refs=resource_refs,
            )
        if not editable:
            if definition_changes:
                raise AuthorityImmutableError(
                    "Only a draft can be edited. Create a New Version to change this Authority Relation.",
                    status=relation.status, version=relation.version,
                )
            # Metadata only: the definition is unchanged, so nothing in it is written.
            for key in ("name", *definition.DEFINITION_FIELDS):
                data.pop(key, None)
            criteria = criteria_rows = affirmations = prerequisites = resource_refs = None

        update_data = {k: v for k, v in data.items() if k in _MODEL_COLUMNS}
        # Keep base_name in step with a renamed AR so the family label stays right.
        if "name" in update_data:
            update_data.setdefault("base_name", update_data["name"])
        if editable and definition_changes:
            update_data["definition_edited_by"] = current_user
        relation = authority_relation_repo.update(db, db_obj=relation, obj_in=update_data)

        if domain_ids is not None:
            entity_domain_repo.set_domains_for_entity(
                db, entity_type=ENTITY_TYPE, entity_id=relation_id,
                domain_ids=domain_ids, primary_domain_id=primary_domain_id,
                assigned_by=current_user,
            )
        if affirmations is not None:
            self._replace_affirmations(db, relation_id, affirmations)
        if criteria_rows is not None:
            self._replace_criteria(db, relation_id, criteria_rows)
        if prerequisites is not None:
            self._replace_prerequisites(db, relation, prerequisites)
        if resource_refs is not None:
            self._replace_resource_refs(db, relation_id, resource_refs)
        # Polymorphic tags (only when the caller supplied the field).
        self._set_tags(db, relation_id, getattr(payload, "tags", None), current_user)

        # Replace helpers bulk-delete without session sync; drop the stale
        # selectin-loaded collections before comparing the stored definition again.
        db.flush()
        db.expire(relation, ["criteria", "affirmations"])
        if editable and definition_changes:
            after = self._stored_view(db, relation)
            if definition.definition_hash(after) != definition.definition_hash(before):
                relation = authority_relation_repo.update(db, db_obj=relation, obj_in={
                    "dna_magnitude": None, "dna_direction": None,
                    "dna_dimensions": None, "dna_measured_at": None,
                })
                self._log_timeline(
                    db, relation_id,
                    "Definition changed: the DNA-Coefficient and the affirmations of the earlier "
                    "definition no longer count. Measure and affirm this draft again.",
                )
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
        # Recorded decisions (resolves made with record=true) and any activation are history.
        # A DNA measurement is not: an abandoned draft can be deleted, and its runs and
        # evidence rows go with it (review #8).
        recorded = db.query(AuthorityDecisionDb).filter(
            AuthorityDecisionDb.relation_id == relation_id, AuthorityDecisionDb.source == "mcp",
        ).count()
        # activated_at is set on the first activation; a version retired straight from draft
        # was never activated and stays deletable.
        ever_active = getattr(relation, "activated_at", None) is not None or relation.status == STATUS_ACTIVE
        if recorded or ever_active:
            raise AuthorityHasHistoryError(
                "This version has recorded decisions or was activated, so it cannot be deleted. "
                "Retire it instead, so its history is kept.",
                decisions=recorded, activated=ever_active,
            )
        for row in db.query(AuthorityDecisionDb).filter(AuthorityDecisionDb.relation_id == relation_id).all():
            db.delete(row)
        for row in db.query(AuthorityDnaRunDb).filter(AuthorityDnaRunDb.relation_id == relation_id).all():
            db.delete(row)
        db.flush()
        family_id = getattr(relation, "version_family_id", None) or relation.id
        others = [v for v in authority_relation_repo.get_family_versions(db, family_id=family_id)
                  if v.id != relation.id]
        if others:
            if relation.id == family_id:
                raise AuthorityInvalidError(
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
                dependents = sorted({
                    self._family_slug_of(db, owner)
                    for owner in (authority_relation_repo.get(db, e.relation_id)
                                  for e in authority_prerequisite_repo.list_dependents(
                                      db, prerequisite_family_slug=slug))
                    if owner is not None and owner.id != relation.id
                } - {None})
                if dependents:
                    raise AuthorityInvalidError(
                        f"Authority Relation '{slug}' is a prerequisite of {', '.join(dependents)}; "
                        "remove those edges first."
                    )
            from src.db_models.semantic_links import EntitySemanticLinkDb
            db.query(EntitySemanticLinkDb).filter(
                EntitySemanticLinkDb.entity_type == ENTITY_TYPE,
                EntitySemanticLinkDb.entity_id == family_id,
            ).delete(synchronize_session=False)
        authority_prerequisite_repo.delete_for_relation(db, relation_id=relation_id)
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
        "domain_context", "rule", "justification_chain", "authority_policy_id", "policy_clause_refs",
        "decision_logic",
        "evidence_binding", "evidence_sources",
        "dna_max_threshold", "dna_scoring_config", "schedule_cron",
        "resolver_auth", "owner_team_id", "project_id",
    )

    def get_relation_versions(self, db: Session, relation_id: str) -> List[AuthorityRelationDb]:
        """Every version in the AR's family, newest first (mirrors get_product_versions)."""
        source = authority_relation_repo.get(db, relation_id)
        if not source:
            raise AuthorityInvalidError("Authority Relation not found")
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
        new_version = self._check_version_format(new_version)
        family_id = getattr(source, "version_family_id", None) or source.id
        if any(v.version == new_version for v in authority_relation_repo.get_family_versions(db, family_id=family_id)):
            raise AuthorityDuplicateVersionError(
                f"Version {new_version} already exists in this family.", version=new_version,
            )

        new_id = str(uuid.uuid4())
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
            "definition_edited_by": current_user,
        }
        for f in self._VERSION_COPY_FIELDS:
            fields[f] = getattr(source, f, None)

        relation = authority_relation_repo.create(
            db, obj_in={k: v for k, v in fields.items() if k in _MODEL_COLUMNS}
        )

        # Carry the source's domain assignments onto the new version (primary flag kept).
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=ENTITY_TYPE, entity_id=source.id)
        if domains:
            entity_domain_repo.set_domains_for_entity(
                db, entity_type=ENTITY_TYPE, entity_id=new_id,
                domain_ids=[d.domain_id for d in domains],
                primary_domain_id=next((d.domain_id for d in domains if d.is_primary), None),
                assigned_by=current_user,
            )

        # Clone the version's own decision checks (each version owns its copy).
        for c in authority_criterion_repo.list_for_relation(db, relation_id=source.id):
            authority_criterion_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": new_id,
                "name": c.name,
                "rule": c.rule,
                "failure_message": c.failure_message,
                "direction": c.direction,
                "weight": c.weight,
                "dimension": getattr(c, "dimension", "people"),
                "display_order": c.display_order,
                "enabled": c.enabled,
                "copied_from": c.copied_from,
                "policy_clause_ref": getattr(c, "policy_clause_ref", None),
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

        # Clone the tags with their values. A failed copy fails the new version: a version
        # without the tags its source had would be a different snapshot.
        from src.controller.tags_manager import TagsManager
        tm = TagsManager()
        tags_payload = [
            AssignedTagCreate(tag_fqn=t.fully_qualified_name, assigned_value=t.assigned_value)
            for t in tm.list_assigned_tags(db, entity_id=source.id, entity_type=ENTITY_TYPE)
            if getattr(t, "fully_qualified_name", None)
        ]
        if tags_payload:
            tm.set_tags_for_entity(db, entity_id=new_id, entity_type=ENTITY_TYPE, tags=tags_payload,
                                   user_email=current_user, commit=False)

        # Owners and metadata (rich text and links; documents stay with their source).
        for owner in db.query(BusinessOwnerDb).filter(
            BusinessOwnerDb.object_type == ENTITY_TYPE,
            BusinessOwnerDb.object_id == source.id,
            BusinessOwnerDb.is_active.is_(True),
        ).all():
            db.add(BusinessOwnerDb(
                id=uuid.uuid4(), object_type=ENTITY_TYPE, object_id=new_id,
                user_email=owner.user_email, user_name=owner.user_name,
                role_id=owner.role_id, is_active=True,
            ))
        for row in db.query(RichTextMetadataDb).filter(
            RichTextMetadataDb.entity_type == ENTITY_TYPE,
            RichTextMetadataDb.entity_id == source.id,
            RichTextMetadataDb.is_shared.is_(False),
        ).all():
            db.add(RichTextMetadataDb(
                id=uuid.uuid4(), entity_id=new_id, entity_type=ENTITY_TYPE, title=row.title,
                short_description=row.short_description, content_markdown=row.content_markdown,
                is_shared=False, level=row.level, inheritable=row.inheritable,
                created_by=current_user, updated_by=current_user,
            ))
        for row in db.query(LinkMetadataDb).filter(
            LinkMetadataDb.entity_type == ENTITY_TYPE,
            LinkMetadataDb.entity_id == source.id,
            LinkMetadataDb.is_shared.is_(False),
        ).all():
            db.add(LinkMetadataDb(
                id=uuid.uuid4(), entity_id=new_id, entity_type=ENTITY_TYPE, title=row.title,
                short_description=row.short_description, url=row.url, is_shared=False,
                level=row.level, inheritable=row.inheritable,
                created_by=current_user, updated_by=current_user,
            ))
        db.flush()

        # The prerequisite edges this version declares are copied; the copy is its own.
        for edge in authority_prerequisite_repo.list_for_relation(db, relation_id=source.id):
            authority_prerequisite_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": new_id,
                "prerequisite_family_slug": edge.prerequisite_family_slug,
                "prerequisite_version_id": edge.prerequisite_version_id,
                "required": edge.required,
                "display_order": edge.display_order,
                "notes": edge.notes,
            })

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
                "affirmed", "affirmed_by", "affirmed_at", "notes", "definition_hash",
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
                "definition_hash": keep.get("definition_hash"),
                "notes": keep.get("notes"),
                "review_status": keep.get("review_status") or ("pending" if is_reviewer else "na"),
                "review_answers": keep.get("review_answers"),
                "review_request_id": keep.get("review_request_id"),
                "sort_order": a.get("sort_order", idx),
            })

    # ------------------------------------------------------- decision criteria

    # Direction values the DNA engine signs; anything else is refused on save.
    _CRITERION_DIRECTIONS = ("actual-exceeds-documented", "documented-exceeds-actual", "neutral")
    # Provenance kinds the system writes: copied from Compliance, from an ARF template, or
    # migrated from a Compliance link by ak6 (the UI echoes that one back).
    _COPIED_KINDS = ("compliance", "template", "migrated")

    @staticmethod
    def _checked_weight(value: Any) -> float:
        """A check weight, validated by the rule module's weight check (N5, #1491-5). 0 stays 0; None is 1.0."""
        if value is None:
            return 1.0
        try:
            return arule.checked_weight(value, "A check")
        except arule.RuleInvalidError as e:
            raise AuthorityInvalidError(str(e)) from e

    @classmethod
    @classmethod
    def _copied_from(cls, value: Any) -> Optional[Dict[str, str]]:
        """Provenance for a copied check: ``{kind, label, id?, key?}``. Stored, never linked.

        Every kind the system writes is accepted (compliance, template, and migrated from
        ak6, which the UI echoes back). A matched existing check keeps its stored value
        (see ``_normalise_criterion``).
        """
        if not value:
            return None
        kind = str(value.get("kind") or "")
        if kind not in cls._COPIED_KINDS:
            raise AuthorityInvalidError(f"Unknown check provenance '{kind}'.")
        out = {"kind": kind, "label": str(value.get("label") or "")[:200]}
        if value.get("id"):
            out["id"] = str(value["id"])[:64]
        if value.get("key"):
            out["key"] = str(value["key"])[:64]
        return out
    def _normalise_criterion(self, item: Any, idx: int, existing: Optional[Any] = None) -> Dict[str, Any]:
        """One check as the row it is stored as. Validates it; raises AuthorityInvalidError.

        ``existing`` is the stored row this input matches, if any. For an ARF template the
        rule and failure message come from the registry only when the check is first added;
        a saved check keeps its stored rule (review #6: the template key is provenance).
        A matched check also keeps its stored provenance. ``order`` defaults to the position.
        """
        c = item.dict() if hasattr(item, "dict") else dict(item)
        template = None
        if c.get("template_key"):
            template = get_template(c["template_key"])
            if template is None:
                raise AuthorityInvalidError(f"Unknown ARF check template '{c['template_key']}'.")
        stored_provenance = dict(existing.copied_from) if existing is not None and existing.copied_from else None
        if template is not None:
            # A saved row of this template keeps its stored rule, message, dimension and provenance.
            kept = existing is not None and bool(stored_provenance) and stored_provenance.get("key") == template.key
            rule = existing.rule if kept else template.rule
            failure_message = existing.failure_message if kept else template.failure_message
            copied_from: Optional[Dict[str, str]] = stored_provenance if kept else {
                "kind": "template", "label": template.name, "key": template.key}
            direction = c.get("direction") or (existing.direction if kept else template.direction)
            dimension = c.get("dimension") or (existing.dimension if kept else template.dimension)
            name = (c.get("name") or "").strip() or template.name
        else:
            rule = (c.get("rule") or "").strip()
            failure_message = c.get("failure_message") or None
            copied_from = stored_provenance or self._copied_from(c.get("copied_from"))
            direction = c.get("direction") or "neutral"
            dimension = c.get("dimension") or "people"
            name = (c.get("name") or "").strip() or f"Check {idx + 1}"
        if not rule:
            raise AuthorityInvalidError(f"Check {idx + 1} needs a rule.")
        if not authority_dna.has_assert_clause(rule):
            rule = "ASSERT " + rule
        parse_error = authority_dna.rule_parse_error(rule)
        if parse_error:
            raise AuthorityInvalidError(f"Check rule {rule!r} does not parse: {parse_error}")
        if direction not in self._CRITERION_DIRECTIONS:
            raise AuthorityInvalidError(f"Check direction '{direction}' is not one of {self._CRITERION_DIRECTIONS}.")
        order = c.get("order")
        return {
            "name": name[:200],
            "rule": rule,
            "failure_message": failure_message,
            "direction": direction,
            "weight": self._checked_weight(c.get("weight")),
            "dimension": dimension,
            "display_order": idx if order is None else int(order),
            "enabled": bool(c.get("enabled", True)),
            "copied_from": copied_from,
            "policy_clause_ref": (c.get("policy_clause_ref") or "").strip() or None,
        }

    def _criteria_rows(
        self, db: Session, relation_id: str, criteria: List[Any], existing: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """The stored form of each input check, matched to the AR's existing checks.

        A check matches by its ``id``, or for a template by its template key (the first
        unmatched one). The save computes these rows once and uses them for the
        definition hash, the parameter check and the write. ``existing`` is None to read
        the stored checks; a new AR passes ``[]`` and reads nothing.
        """
        if existing is None:
            existing = list(authority_criterion_repo.list_for_relation(db, relation_id=relation_id))
        by_id = {e.id: e for e in existing}
        used: set = set()
        rows: List[Dict[str, Any]] = []
        for idx, item in enumerate(criteria):
            c = item.dict() if hasattr(item, "dict") else dict(item)
            match = None
            if c.get("id") and c["id"] in by_id and c["id"] not in used:
                match = by_id[c["id"]]
            elif c.get("template_key"):
                match = next((e for e in existing if e.id not in used
                              and (e.copied_from or {}).get("kind") == "template"
                              and (e.copied_from or {}).get("key") == c["template_key"]), None)
            if match is not None:
                used.add(match.id)
            rows.append(self._normalise_criterion(item, idx, existing=match))
        return rows

    def _check_parameter_references(
        self, db: Session, relation_id: str, *, domain_context: Any, rule: Any,
        criteria_rows: Optional[List[Dict[str, Any]]], resource_refs: Optional[List[Any]],
    ) -> None:
        """Refuse a ``ctx.<name>`` in the rule or a check that the AR doesn't define (#1491-1).

        Defined: a domain-context parameter, or a ``domain_context.<name>`` resource ref
        (both are ``ctx.<name>`` at resolve time). ``criteria_rows`` (the save's rows) and
        ``resource_refs`` (the input) are the new state; ``None`` reads the stored ones.
        """
        known = set(arule.normalize_domain_context(domain_context)["params"])
        if resource_refs is None:
            fields = [r.field_path for r in authority_resource_ref_repo.list_for_relation(db, relation_id=relation_id)]
        else:
            fields = [(item.dict() if hasattr(item, "dict") else dict(item)).get("field_path") for item in resource_refs]
        known.update(k for k in (arule.ref_param_key(f) for f in fields) if k)
        texts = [c.rule for c in arule.compile_rule(rule)]
        if criteria_rows is None:
            texts += [row.rule for row in authority_criterion_repo.list_for_relation(db, relation_id=relation_id)]
        else:
            texts += [row["rule"] for row in criteria_rows]
        arule.check_parameter_references(texts, known)

    def _replace_criteria(self, db: Session, relation_id: str, rows: List[Dict[str, Any]]) -> None:
        """Replace the AR version's own decision checks with the save's rows (ARF 1.2.0, B7 / S12).

        Each check is stored on this version's row, so no Compliance Check is created
        or linked: saving the AR never duplicates checks, and a Compliance edit can't
        change it. ``rows`` come from :meth:`_criteria_rows`, already validated.
        """
        authority_criterion_repo.delete_for_relation(db, relation_id=relation_id)
        for row in rows:
            authority_criterion_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation_id,
                **row,
            })

    def _cycle_would_close(
        self, db: Session, head_slug: str, candidate_prereq_slug: str,
    ) -> bool:
        """Would adding (``head_slug`` → ``candidate_prereq_slug``) close a cycle?

        Walks the candidate upstream family's own edges, through each family's
        active version; if ``head_slug`` appears in that closure the new edge
        would form a cycle. Called on save so authors never land an edge the
        resolve-time detector would have to abort on.
        """
        if head_slug == candidate_prereq_slug:
            return True
        seen = {candidate_prereq_slug}
        stack = [candidate_prereq_slug]
        while stack:
            slug = stack.pop()
            upstream = self.resolve_relation_ref(db, slug)
            if upstream is None:
                continue
            for e in authority_prerequisite_repo.list_for_relation(db, relation_id=upstream.id):
                if e.prerequisite_family_slug == head_slug:
                    return True
                if e.prerequisite_family_slug not in seen:
                    seen.add(e.prerequisite_family_slug)
                    stack.append(e.prerequisite_family_slug)
        return False

    def _replace_prerequisites(
        self, db: Session, relation: AuthorityRelationDb, prerequisites: List[Any],
    ) -> None:
        """Replace the prerequisite edges this AR version declares (B7).

        Each edge is owned by ``relation``, so another version's edges are never
        touched. The target is a family slug, resolved to its active version at
        eval time; ``prerequisite_version_id`` records the version seen at save.
        Rejects self-loops and any edge whose upstream family already depends on
        this one through its own prerequisites. The AR needs a family slug first,
        since other ARs name it by that slug.
        """
        head_slug = self._family_slug_of(db, relation)
        if head_slug is None:
            if prerequisites:
                raise AuthorityInvalidError(
                    "Authority Relation needs a slug before prerequisites can be set "
                    "— other Authority Relations name it by that stable family-level @id."
                )
            return
        normalised: Dict[str, Dict[str, Any]] = {}
        for idx, item in enumerate(prerequisites):
            p = item.dict() if hasattr(item, "dict") else dict(item)
            slug = (p.get("prerequisite_family_slug") or "").strip()
            if not slug:
                continue
            if slug == head_slug:
                raise AuthorityInvalidError(
                    f"An Authority Relation cannot require itself ({slug})."
                )
            target = authority_relation_repo.get_by_slug(db, slug)
            if target is None:
                raise AuthorityInvalidError(
                    f"Prerequisite '{slug}' does not match any Authority Relation slug."
                )
            if self._cycle_would_close(db, head_slug, slug):
                raise AuthorityInvalidError(
                    f"Adding '{slug}' as a prerequisite of '{head_slug}' would close a cycle."
                )
            upstream = self.resolve_relation_ref(db, slug)
            normalised[slug] = {
                "required": bool(p.get("required", True)),
                "display_order": int(p.get("display_order", idx)),
                "notes": p.get("notes"),
                "prerequisite_version_id": upstream.id if upstream is not None else None,
            }
        authority_prerequisite_repo.delete_for_relation(db, relation_id=relation.id)
        for slug, cfg in normalised.items():
            authority_prerequisite_repo.create(db, obj_in={
                "id": str(uuid.uuid4()),
                "relation_id": relation.id,
                "prerequisite_family_slug": slug,
                **cfg,
            })

    def list_prerequisites(
        self, db: Session, relation: AuthorityRelationDb,
    ) -> List[Dict[str, Any]]:
        """The AR's declared prerequisites with each upstream slug resolved
        for display (name + status of the active family version)."""
        edges = authority_prerequisite_repo.list_for_relation(db, relation_id=relation.id)
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
            if field_path.startswith("domain_context.") and arule.ref_param_key(field_path) is None:
                raise AuthorityInvalidError(
                    f"Resource ref '{field_path}' must name one parameter: domain_context.<name>.")
            if ref_type not in self._REF_TYPES:
                raise AuthorityInvalidError(
                    f"Resource ref for '{field_path}' has unknown ref_type "
                    f"'{ref_type}' — expected one of {self._REF_TYPES}."
                )
            if ref_type == "literal":
                # literal_value may legitimately be an empty string, but
                # ``None`` is treated as "no ref row" by the resolver, so
                # catch that at the write boundary.
                if r.get("literal_value") is None:
                    raise AuthorityInvalidError(
                        f"Literal resource ref for '{field_path}' is missing literal_value."
                    )
            elif ref_type == "ontos_entity":
                entity_type = (r.get("entity_type") or "").strip()
                entity_id = (r.get("entity_id") or "").strip()
                if not entity_type or not entity_id:
                    raise AuthorityInvalidError(
                        f"Ontos-entity resource ref for '{field_path}' needs both "
                        "entity_type and entity_id."
                    )
                if entity_type not in self._ONTOS_ENTITY_TYPES:
                    raise AuthorityInvalidError(
                        f"Ontos-entity resource ref for '{field_path}' has unsupported "
                        f"entity_type '{entity_type}' — expected one of {self._ONTOS_ENTITY_TYPES}."
                    )
            elif ref_type == "mcp_tool":
                service = (r.get("mcp_service_name") or "").strip()
                tool = (r.get("mcp_tool_name") or "").strip()
                if not service.startswith(mcp_resolver.SERVICE_PREFIX) or not tool:
                    raise AuthorityInvalidError(
                        f"MCP resource ref for '{field_path}' needs mcp_service_name "
                        f"('{mcp_resolver.SERVICE_PREFIX}…') and mcp_tool_name."
                    )
                if r.get("mcp_params") is not None and not isinstance(r["mcp_params"], dict):
                    raise AuthorityInvalidError(f"MCP resource ref for '{field_path}': mcp_params must be an object.")
                pointer = (r.get("mcp_result_pointer") or "$").strip()
                if not pointer.startswith("$"):
                    raise AuthorityInvalidError(
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
        ar_values = {
            "slug": relation.slug,
            "actor_role": relation.actor_role,
            "actor_identity": relation.actor_identity,
            "action": relation.action,
            "object_type": relation.object_type,
            "object_id": relation.object_id,
            # Flat view (params plus scope values by key), so templates such
            # as ``{{ ar.domain_context.market }}`` keep working.
            "domain_context": self._flat_domain_context(relation),
            "params": arule.normalize_domain_context(relation.domain_context)["params"],
        }
        if auth == RESOLVER_AUTH_APP_SP:
            # An app_sp call runs with the app's own rights, so only values the
            # author defined reach its params (B2): the AR fields and its scope
            # parameters, never the caller's request.
            template_ctx = {"ar": ar_values, "ctx": ar_values["params"]}
        else:
            template_ctx = {**req, "request": req, "ar": ar_values}
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
            raise AuthorityReviewerNotApproverError("This participant is a reviewer, not an approver.")
        if not principal_matches(aff.principal, aff.principal_type, user):
            raise AuthorityNotNamedError("Only the named participant can record this affirmation.")
        relation = authority_relation_repo.get(db, aff.relation_id)
        if relation is not None and self._is_definition_author(relation, affirmed_by):
            raise AuthoritySelfAffirmationError(
                "The creator or last editor of this definition cannot affirm it.",
            )
        return authority_affirmation_repo.update(db, db_obj=aff, obj_in={
            "affirmed": True, "affirmed_by": affirmed_by, "affirmed_at": self._now(), "notes": notes,
            "definition_hash": self.definition_hash(db, relation) if relation is not None else None,
        })

    @staticmethod
    def _is_definition_author(relation: AuthorityRelationDb, user: Optional[str]) -> bool:
        """True when ``user`` created this AR version or last changed its definition (B4)."""
        if not user:
            return False
        who = user.strip().casefold()
        return who in {
            (value or "").strip().casefold()
            for value in (getattr(relation, "created_by", None), getattr(relation, "definition_edited_by", None))
            if value
        }

    @staticmethod
    def _approvers(db: Session, relation_id: str) -> List[AuthorityAffirmationDb]:
        """Only APPROVER participants count toward the affirmation gate; pure
        reviewers/interviewees do not. (is_approver defaults True for rows
        created before the reviewer/approver split.)"""
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation_id)
        return [a for a in affs if a.required and getattr(a, "is_approver", True)]

    @staticmethod
    def _latest_succeeded_run(db: Session, relation_id: str) -> Optional[AuthorityDnaRunDb]:
        """The newest successful DNA run of a version (the one the activation gate and the read model use)."""
        return next(
            (r for r in authority_dna_run_repo.list_for_relation(db, relation_id=relation_id, limit=50)
             if r.status == "succeeded"),
            None,
        )

    def _dna_is_current(self, db: Session, relation: AuthorityRelationDb, current_hash: Optional[str] = None) -> bool:
        """True when the version is measured and its latest successful run is on the current definition."""
        if relation.dna_magnitude is None:
            return False
        run = self._latest_succeeded_run(db, relation.id)
        expected = current_hash if current_hash is not None else self.definition_hash(db, relation)
        return run is not None and run.definition_hash == expected

    def is_fully_affirmed(self, db: Session, relation_id: str, current_hash: Optional[str] = None) -> bool:
        """Every required approver has affirmed the AR's *current* definition (B6).

        An affirmation of an earlier draft does not count.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if relation is None:
            return False
        approvers = self._approvers(db, relation_id)
        # A caller that already has the hash passes it in, so it is computed once per read.
        current = current_hash if current_hash is not None else self.definition_hash(db, relation)
        return bool(approvers) and all(a.affirmed and a.definition_hash == current for a in approvers)

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

        For each reviewer participant we (a) pre-create a per-reviewer Asset Review
        targeting that principal (its ``asset_fqn`` is ``authority-relation://{id}``, so
        the reviewer's task opens the role-specific AR review editor), and (b) mark the
        participant ``in_review`` and store the Asset Review's id so the owner can track
        it. The per-reviewer Asset Reviews fire no trigger of their own.

        Then the AR-level ``on_request_review`` trigger fires once, with the AR's id,
        asset FQN and the reviewers in ``entity_data``. The
        ``authority-relation-review-request`` default workflow notifies those reviewers
        (one notification each, no DataSteward approval, #859 review B10, S8). When no
        workflow runs, each reviewer gets a direct notification. Side effects are
        best-effort. Returns None if the AR does not exist.
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
                            asset_fqns=[authority_relation_fqn(relation_id)],
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
                "review_request_id": review_request_id or f"{AUTHORITY_RELATION_FQN_PREFIX}{relation_id}#{a.id}",
            })
        reviewer_refs = [{"principal": a.principal, "role": a.role} for a in reviewers]
        notified = self._notify_reviewers(db, relation, reviewer_refs, owner)
        return {
            "relation_id": relation_id,
            "reviewers_notified": len(reviewers),
            "reviews_created": reviews_created,
            "notifications_sent": notified,
        }

    @staticmethod
    def _notify_reviewers(db: Session, relation: Any, reviewers: List[Dict[str, Any]], owner: Optional[str]) -> int:
        """Fire the AR-level review trigger once; direct notifications when no workflow runs.

        Returns the number of reviewers notified directly (0 when the workflow notified them).
        Best-effort: a failure is logged and the review still starts.
        """
        relation_id = relation.id
        executions: List[Any] = []
        try:
            from src.common.workflow_triggers import get_trigger_registry
            from src.models.process_workflows import EntityType
            executions = get_trigger_registry(db).on_request_review(
                entity_type=EntityType.AUTHORITY_RELATION,
                entity_id=relation_id,
                entity_name=relation.name,
                entity_data={
                    "id": relation_id,
                    "asset_fqn": authority_relation_fqn(relation_id),
                    "reviewers": reviewers,
                    "status": relation.status,
                },
                user_email=owner,
                blocking=False,
            )
        except Exception as e:  # pragma: no cover - trigger is environment-dependent
            logger.warning(f"on_request_review trigger failed for AR {relation_id}: {e}")
        if executions:
            return 0
        direct = 0
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo
        for reviewer in reviewers:
            try:
                notification_repo.create(db=db, obj_in=Notification(
                    id=str(uuid.uuid4()),
                    type=NotificationType.INFO,
                    title=f"Review requested: {relation.name}",
                    description=f"You have been asked to review Authority Relation '{relation.name}'.",
                    recipient=reviewer["principal"],
                    link=f"/authority-resolution/{relation_id}",
                    created_at=utc_now(),
                    read=False,
                    can_delete=True,
                ))
                direct += 1
            except Exception as e:  # pragma: no cover - best-effort
                logger.warning(f"Could not notify reviewer {reviewer['principal']} for AR {relation_id}: {e}")
        return direct

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
            raise AuthorityNotNamedError("Only the named reviewer can open this review.")
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
                "domain_context": arule.normalize_domain_context(relation.domain_context),
                "rule": getattr(relation, "rule", None),
                "criteria": [
                    {
                        "name": c.name,
                        "rule": c.rule,
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
        reviews_manager: Optional[Any] = None, outcome: str = AR_REVIEW_APPROVE,
    ) -> Optional[AuthorityAffirmationDb]:
        """Persist a reviewer's answers and their outcome, and close their Asset Review.

        ``outcome`` is ``approve`` (the default) or ``needs_clarification`` (the AR does
        not match practice). The Asset Review's ReviewedAsset takes that status and the
        request closes with it (#859 review B10). Ordering: the Asset Review is closed
        first, so a failure there raises before the answers are recorded and the
        reviewer can retry. The close is idempotent. Raises ``PermissionError`` unless
        ``user`` is that reviewer.
        """
        participant = authority_affirmation_repo.get(db, participant_id)
        if not participant:
            return None
        if not getattr(participant, "is_reviewer", False):
            raise AuthorityNotAReviewerError("This participant is not a reviewer.")
        if not principal_matches(participant.principal, participant.principal_type, user):
            raise AuthorityNotNamedError("Only the named reviewer can submit this review.")
        if outcome not in AR_REVIEW_OUTCOMES:
            raise AuthorityReviewOutcomeError(
                f"Unknown review outcome '{outcome}'; use approve or needs_clarification.",
                outcome=outcome,
            )
        self._close_asset_review(
            db, participant.review_request_id, participant.relation_id, outcome, reviews_manager,
        )
        return authority_affirmation_repo.update(db, db_obj=participant, obj_in={
            "review_answers": {**(answers or {}), "outcome": outcome},
            "review_status": "completed",
        })

    @staticmethod
    def _close_asset_review(
        db: Session, request_id: Optional[str], relation_id: str, outcome: str, reviews_manager: Optional[Any],
    ) -> None:
        """Set the AR's ReviewedAsset in a per-reviewer Asset Review to the outcome, and close the request.

        Runs on the request's session (``db``): the review repositories only flush, so the
        Asset Review writes and the affirmation write below commit or roll back together
        with the request. Nothing is swallowed: a failure propagates, so the answers are
        not recorded without the Asset Review closed. A synthetic request id (no Asset
        Review was created) or no manager is a no-op.
        """
        if reviews_manager is None or not request_id or str(request_id).startswith(AUTHORITY_RELATION_FQN_PREFIX):
            return
        from src.models.data_asset_reviews import (
            DataAssetReviewRequestUpdateStatus,
            ReviewedAssetStatus,
            ReviewedAssetUpdate,
            ReviewRequestStatus,
        )
        approved = outcome == AR_REVIEW_APPROVE
        asset_status = ReviewedAssetStatus.APPROVED if approved else ReviewedAssetStatus.NEEDS_CLARIFICATION
        request_status = ReviewRequestStatus.APPROVED if approved else ReviewRequestStatus.NEEDS_REVIEW
        request = reviews_manager.get_review_request(request_id, db=db)
        if request is None:
            return
        fqn = authority_relation_fqn(relation_id)
        for asset in request.assets:
            if asset.asset_fqn == fqn and asset.status != asset_status:
                reviews_manager.update_reviewed_asset_status(
                    request_id, asset.id, ReviewedAssetUpdate(status=asset_status), db=db,
                )
        if request.status != request_status:
            reviews_manager.update_review_request_status(
                request_id, DataAssetReviewRequestUpdateStatus(status=request_status), db=db,
            )

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
            linkable = bool(rid) and not str(rid).startswith(AUTHORITY_RELATION_FQN_PREFIX)
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
            # Filtered in SQL by the ids (S10); the exact entity_id check below stays
            for exe in workflow_execution_repo.list_for_entity_ids(db, sorted(target_ids)):
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
        all_reviewed = bool(reviewers) and all(
            getattr(a, "review_status", None) == "completed" for a in reviewers
        )
        return {
            "relation_id": relation_id,
            "reviews": reviews,
            "workflows": workflows,
            "all_reviewed": all_reviewed,
        }

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
            "definition_hash": self.definition_hash(db, relation),
        })

        try:
            if rows is None:
                # Read + normalise across all bound evidence sources (falls back to
                # the legacy single ``evidence_binding``); rows are keyed by the
                # canonical request fields the criteria rules reference.
                rows = self._collect_evidence(relation)
            if not rows:
                raise AuthorityInvalidError("No evidence rows were read; the DNA-Coefficient cannot be measured.")
            # The ODRL rule and the checks, evaluated per row: every failure
            # (a constraint, a prohibition, an unfulfilled duty, a check) diverges.
            criteria = self._rule_criteria(relation) + self._load_criteria(relation)
            broken = [c.code for c in criteria if authority_dna.rule_parse_error(c.rule)]
            if broken:
                raise AuthorityInvalidError(f"Criteria with malformed rules: {', '.join(broken)}; fix them before measuring.")
            # A ctx.<param> the checks read must exist for the run (#1491-1): a configuration
            # fault fails the run, it is not a divergence on every row.
            ctx = self._run_ctx(db, relation)
            absent = sorted(arule.context_references(c.rule for c in criteria) - {k for k, v in ctx.items() if v is not None})
            if absent:
                raise AuthorityInvalidError(
                    f"The checks read {', '.join('ctx.' + k for k in absent)}, which the Authority Relation "
                    "does not define (no parameter or domain-context ref). Fix the configuration, then measure again.",
                    parameters=absent,
                )
            rows, out_of_scope = self._scoped_evidence(relation, rows, ctx)
            if not rows:
                raise AuthorityInvalidError(
                    f"All {out_of_scope} evidence rows are outside the Authority Relation's scope; "
                    "the DNA-Coefficient cannot be measured."
                )
            result = authority_dna.compute_dnaco(criteria, rows)
            if result.sampled_count == 0:
                raise AuthorityInvalidError(
                    f"No evidence row carries the operands the rule and checks read ({result.skipped_count} skipped); "
                    "the DNA-Coefficient cannot be measured."
                )

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
                # Coming back to active needs fresh affirmations (S3).
                self._clear_affirmations(db, relation_id)
            authority_relation_repo.update(db, db_obj=relation, obj_in=agg)

            # Record the run on the entity timeline (Comments).
            dims_str = ", ".join(f"{k} {v:.2f}" for k, v in sorted(dimensions.items()))
            msg = (
                f"DNA-Coefficient computed: {overall:.2f} "
                f"({result.divergent_count}/{result.sampled_count} divergent; {dims_str})."
            )
            if out_of_scope:
                msg += f" {out_of_scope} evidence rows outside the scope were skipped."
            if result.skipped_count:
                msg += f" {result.skipped_count} evidence rows missing an operand the checks read were skipped."
            if auto_flagged:
                msg += f" Exceeded the ceiling ({relation.dna_max_threshold}); status auto-changed to needs_review."
                self._reindex(db, relation)
            self._log_timeline(db, relation_id, msg)
            return run
        except Exception as e:
            authority_dna_run_repo.update(db, db_obj=run, obj_in={
                "status": "failed", "finished_at": self._now(),
                "error_message": client_failure_text("DNA-Coefficient computation", e),
            })
            raise

    def _run_ctx(self, db: Session, relation: AuthorityRelationDb) -> Dict[str, Any]:
        """The ``ctx`` of an evidence run: the AR's parameters plus its domain-context refs,
        resolved once for the run (as a resolve resolves them)."""
        params = arule.normalize_domain_context(relation.domain_context)["params"]
        resolved = self._materialise_refs(db, relation, {}, _ResolveCtx())
        return {**params, **self._ref_ctx(resolved)}

    def _scoped_evidence(
        self, relation: AuthorityRelationDb, rows: List[Dict[str, Any]], ctx: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Evidence rows as rules see them, and how many fell outside the scope.

        A row is skipped when it carries a scope key with a value outside the
        scope; a row without that column is kept (it can't be placed). Each kept
        row is the rules' evaluation object: the row is both ``obj`` and
        ``req``, and ``ctx`` is the run's parameters (:meth:`_run_ctx`).
        """
        dc = arule.normalize_domain_context(relation.domain_context)
        by_key = [(arule.scope_key(c["leftOperand"]), c) for c in dc["scope"]]
        kept: List[Dict[str, Any]] = []
        skipped = 0
        for row in rows:
            norm = authority_dna.normalize_row(row)
            if any(
                norm.get(key) not in (None, "")
                and not arule.compare_value(norm[key], c["operator"], c["rightOperand"])
                for key, c in by_key
            ):
                skipped += 1
                continue
            kept.append(arule.evaluation_object(norm, ctx))
        return kept, skipped

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
                results.append({
                    "relation_id": r.id, "status": "failed",
                    "error": client_failure_text("scheduled DNA-Coefficient recompute", e),
                })
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

    @staticmethod
    def _clear_affirmations(db: Session, relation_id: str) -> None:
        for aff in authority_affirmation_repo.list_for_relation(db, relation_id=relation_id):
            authority_affirmation_repo.update(db, db_obj=aff, obj_in={
                "affirmed": False, "affirmed_by": None, "affirmed_at": None,
            })

    @staticmethod
    def _check_transition(relation: AuthorityRelationDb, status: str) -> None:
        """The allowed status changes, from ``_ALLOWED_TRANSITIONS`` (S3)."""
        current = relation.status
        allowed = status in _ALLOWED_TRANSITIONS.get(current, set())
        if current == STATUS_NEEDS_REVIEW and status == STATUS_DRAFT and getattr(relation, "activated_at", None):
            allowed = False
        if not allowed:
            raise AuthorityStatusError(
                f"An Authority Relation cannot go from '{current}' to '{status}'.",
                reason="transition_not_allowed", **{"from": current, "to": status},
            )

    def _check_activation(self, db: Session, relation: AuthorityRelationDb) -> None:
        """The gates for activation: an enabled check (B5); a measurement and the
        approvals of the current definition (B6); the ceiling. Raises AuthorityStatusError."""
        if not self._load_criteria(relation):
            raise AuthorityStatusError(
                "Add at least one enabled decision check before activating this version.",
                reason="no_enabled_checks",
            )
        if relation.dna_magnitude is None:
            raise AuthorityStatusError("The DNA-Coefficient has not been measured yet.", reason="not_measured")
        current = self.definition_hash(db, relation)
        latest_ok = self._latest_succeeded_run(db, relation.id)
        if latest_ok is None or latest_ok.definition_hash != current:
            raise AuthorityStatusError(
                "The DNA-Coefficient was measured on an earlier draft. Measure this definition again.",
                reason="dna_stale",
            )
        ceiling = self._ceiling(relation)
        if relation.dna_magnitude > ceiling:
            raise AuthorityStatusError(
                f"DNA-Coefficient {relation.dna_magnitude} exceeds the maximum {ceiling}.",
                reason="ceiling_exceeded", magnitude=relation.dna_magnitude, ceiling=ceiling,
            )
        # Upstream versions may have changed since this version's edges were saved (review #7):
        # re-check every edge against the upstream families' active versions now.
        head = self._family_slug_of(db, relation)
        if head:
            for edge in authority_prerequisite_repo.list_for_relation(db, relation_id=relation.id):
                if self._cycle_would_close(db, head, edge.prerequisite_family_slug):
                    raise AuthorityStatusError(
                        f"Activating this version would close a prerequisite cycle through "
                        f"'{edge.prerequisite_family_slug}'.",
                        reason="prerequisite_cycle", prerequisite=edge.prerequisite_family_slug,
                    )
        approvers = self._approvers(db, relation.id)
        if not approvers:
            raise AuthorityStatusError(
                "Name at least one required approver before activation.", reason="affirmations_missing",
            )
        if any(a.affirmed and a.definition_hash != current for a in approvers):
            raise AuthorityStatusError(
                "An approver affirmed an earlier draft. Affirm this definition again.",
                reason="affirmations_stale",
            )
        if not all(a.affirmed for a in approvers):
            raise AuthorityStatusError(
                "All required affirmations must be completed before activation.",
                reason="affirmations_missing",
            )

    def set_status(
        self, db: Session, relation_id: str, status: str, caller_is_admin: bool = False,
    ) -> Optional[AuthorityRelationDb]:
        """Move an AR to another status. Returns None when the AR does not exist.

        Taking an AR into or out of service (active or retired, either side) is
        Admin-only; a Read-write author moves it between draft and needs_review.
        Refusals raise ``AuthorityStatusError`` with the failed gate as ``reason``.
        """
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        in_service = (STATUS_ACTIVE, STATUS_RETIRED)
        if (status in in_service or relation.status in in_service) and not caller_is_admin:
            raise AuthorityPermissionError(
                f"Only an Admin can change an Authority Relation from '{relation.status}' "
                f"to '{status}'.",
                **{"from": relation.status, "to": status, "required_level": "Admin"},
            )
        if status not in _ALLOWED_STATUSES:
            raise AuthorityInvalidError(f"Unknown status '{status}' — expected one of {_ALLOWED_STATUSES}.")
        if status == relation.status:
            return relation
        self._check_transition(relation, status)
        if status == STATUS_ACTIVE:
            self._check_activation(db, relation)

        previous = relation.status
        changes: Dict[str, Any] = {"status": status}
        if status == STATUS_ACTIVE and getattr(relation, "activated_at", None) is None:
            changes["activated_at"] = self._now()
        updated = authority_relation_repo.update(db, db_obj=relation, obj_in=changes)
        if status == STATUS_RETIRED:
            self._clear_affirmations(db, relation_id)
        if status == STATUS_ACTIVE:
            self._retire_other_active_versions(db, updated)
        self._log_timeline(db, relation_id, f"Status changed from {previous} to {status}.")
        self._reindex(db, updated)
        return updated

    def _retire_other_active_versions(self, db: Session, relation: AuthorityRelationDb) -> None:
        """Activating a version retires the family's other active ones (S2), so a pinned
        UUID can't keep answering with a superseded verdict. Each gets a timeline entry."""
        family_id = getattr(relation, "version_family_id", None) or relation.id
        for other in authority_relation_repo.get_family_versions(db, family_id=family_id):
            if other.id == relation.id or other.status != STATUS_ACTIVE:
                continue
            authority_relation_repo.update(db, db_obj=other, obj_in={"status": STATUS_RETIRED})
            self._clear_affirmations(db, other.id)
            self._log_timeline(db, other.id, f"Retired: version {relation.version} was activated in its place.")
            self._log_timeline(db, relation.id, f"Retired the earlier active version {other.version}.")

    # --------------------------------------------------------- runtime gate

    def _policy_citation(self, db: Session, relation: AuthorityRelationDb) -> Optional[Dict[str, Any]]:
        return apol.AuthorityPolicyManager().citation(db, relation)

    @staticmethod
    def _flat_domain_context(relation: AuthorityRelationDb) -> Dict[str, Any]:
        """Params plus each ``eq`` / ``isAnyOf`` scope value by key."""
        dc = arule.normalize_domain_context(relation.domain_context)
        flat = dict(dc["params"])
        for c in dc["scope"]:
            if c.get("operator") in ("eq", "isAnyOf"):
                flat.setdefault(arule.scope_key(c["leftOperand"]), c.get("rightOperand"))
        return flat

    def _rule_criteria(self, relation: AuthorityRelationDb) -> List[Criterion]:
        """The AR's ODRL rule compiled to engine criteria (prohibitions,
        constraints, duties). Raises ValueError on a malformed stored rule."""
        return arule.compile_rule(getattr(relation, "rule", None))

    @staticmethod
    def _ref_ctx(resolved_refs: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """``domain_context.<key>`` / ``domain_context.params.<key>`` refs as ``ctx.<key>``."""
        out: Dict[str, Any] = {}
        for r in resolved_refs or []:
            key = arule.ref_param_key(r.get("field_path"))
            if key:
                out[key] = r.get("value")
        return out

    def _evaluation_object(
        self,
        relation: AuthorityRelationDb,
        req: Dict[str, Any],
        resolved_refs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """The request as rules see it: ``obj.<field>`` (normalised), ``req.<key>``,
        ``ctx.<param>`` and ``obj.ref_<field_path>``. Request keys in the
        ``ref_`` / ``ctx`` / ``req`` namespaces are dropped (anti-spoofing)."""
        flat = {k: v for k, v in req.items() if not str(k).startswith(REF_KEY_PREFIX)}
        for r in resolved_refs or []:
            flat[ref_key(r["field_path"])] = r.get("value")
            if r.get("iri"):
                flat[ref_key(r["field_path"]) + "_iri"] = r["iri"]
        params = arule.normalize_domain_context(relation.domain_context)["params"]
        obj = arule.evaluation_object(
            authority_dna.normalize_row(flat), params, extra_ctx=self._ref_ctx(resolved_refs),
        )
        # ARF 1.2.0: the cited reference's validity, read as the checks see it
        # (``justification.cited / valid_from / valid_to / expired``), computed now.
        # It overrides any request key of the same name.
        # A dry-run probe (validate route) isn't a mapped row: it reads as uncited.
        try:
            db = object_session(relation)
        except UnmappedInstanceError:
            db = None
        obj[arule.NS_JUSTIFICATION] = (
            apol.AuthorityPolicyManager().justification(db, relation) if db is not None
            else apol.justification_view(None)
        )
        return obj

    def _evaluate_decision(
        self,
        relation: AuthorityRelationDb,
        req: Dict[str, Any],
        resolved_refs: Optional[List[Dict[str, Any]]] = None,
        policy_label: Optional[str] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """``(verdict, reason, pending_duties)`` of :meth:`_decide`, without its reason code."""
        verdict, reason, pending, _ = self._decide(relation, req, resolved_refs, policy_label)
        return verdict, reason, pending

    @staticmethod
    def _unknown_outcome(c: Criterion, missing: Tuple[Tuple[str, str], ...]) -> Tuple[str, str, List[Dict[str, Any]], str]:
        """A criterion that can't be decided, because an operand it reads is absent (#1491-1).

        A missing ``ctx.<param>`` is the AR's own configuration, so it is a conflict (the
        answer to a malformed rule). Otherwise the request lacks a value the rule needs:
        a denial naming the fields to send. Kleene evaluation already made the unknown
        decide the rule (see ``compliance_dsl.evaluate_rule_strict``).
        """
        params = list(dict.fromkeys(k for ns, k in missing if ns == arule.NS_CTX))
        fields = list(dict.fromkeys(k for ns, k in missing if ns != arule.NS_CTX))
        if params:
            names = ", ".join(f"'{k}'" for k in params)
            return (VERDICT_CONFLICT,
                    f"The Authority Relation's parameter {names} is missing, so '{c.code}' cannot be decided.",
                    [], REASON_MISSING_PARAMETER)
        names = ", ".join(f"'{k}'" for k in fields)
        return (VERDICT_DENIED,
                f"The request has no value for {names}, so '{c.code}' cannot be decided.",
                [], REASON_MISSING_OPERAND)

    def _decide(
        self,
        relation: AuthorityRelationDb,
        req: Dict[str, Any],
        resolved_refs: Optional[List[Dict[str, Any]]] = None,
        policy_label: Optional[str] = None,
    ) -> Tuple[str, str, List[Dict[str, Any]], Optional[str]]:
        """Deterministic evaluation of the request against the AR's rule and checks.

        Order: prohibitions and permission constraints (ODRL rule), then the
        Compliance Checks; the first failure denies with its message. Duties
        come last: an unfulfilled duty makes the decision ``conditional`` and
        is returned in the pending list. No rule and no checks = an
        unconstrained gate (approve). A failure whose item cites a policy clause
        names it (``[POL v3 §7.2]``).

        Rules evaluate with three-valued strict semantics (#1491-1, see
        ``compliance_dsl.evaluate_rule_strict``). An UNKNOWN criterion fails closed:
        a constraint, check or prohibition denies with a reason naming the absent
        fields, a missing parameter is a conflict. An UNKNOWN duty stays unfulfilled.
        Returns ``(verdict, reason, pending_duties, reason_code)``.
        """
        obj = self._evaluation_object(relation, req, resolved_refs)
        try:
            rule_criteria = self._rule_criteria(relation)
        except ValueError as e:
            return VERDICT_CONFLICT, f"The Authority Relation's rule is malformed: {e}", [], None
        if not rule_criteria and not self._load_criteria(relation):
            # B5: a version with no rule and no enabled check approves nothing.
            return VERDICT_NO_AUTHORITY, NO_ENABLED_CHECKS_MESSAGE, [], None
        duties = [c for c in rule_criteria if c.kind == arule.KIND_DUTY]
        gating = [c for c in rule_criteria if c.kind != arule.KIND_DUTY] + self._load_criteria(relation)
        for c in gating:
            parse_error = authority_dna.rule_parse_error(c.rule)
            if parse_error:
                # Fail closed, and say it's the AR's configuration, not the request.
                return VERDICT_CONFLICT, f"Criterion '{c.code}' has a malformed rule: {parse_error}", [], None
            outcome = evaluate_rule_strict(c.rule, obj)
            if outcome.passed is None:
                verdict, reason, pending, code = self._unknown_outcome(c, outcome.missing)
                return verdict, _cite(reason, c.clause, policy_label), pending, code
            if not outcome.passed:
                return VERDICT_DENIED, _cite(c.message or outcome.message or f"Criterion '{c.code}' failed",
                                             c.clause, policy_label), [], None
        pending: List[Dict[str, Any]] = []
        for c in duties:
            outcome = evaluate_rule_strict(c.rule, obj)
            if outcome.passed is None and any(ns == arule.NS_CTX for ns, _ in outcome.missing):
                verdict, reason, pending_, code = self._unknown_outcome(c, outcome.missing)
                return verdict, _cite(reason, c.clause, policy_label), pending_, code
            if outcome.passed is not True:
                duty = {"duty": c.code, "message": c.message}
                if c.clause:
                    duty["clause"] = c.clause
                pending.append(duty)
        if pending:
            return VERDICT_CONDITIONAL, "permitted once duties are fulfilled: " + ", ".join(
                d["message"] or d["duty"] for d in pending), pending, None
        return VERDICT_APPROVED, "all checks passed", [], None

    def _check_scope(
        self, relation: AuthorityRelationDb, req: Dict[str, Any], rctx: "_ResolveCtx",
    ) -> Tuple[bool, str, List[Dict[str, Any]]]:
        """The request context against the AR's scope (``domain_context.scope``).
        A value also matches through concept-label equivalence (label ↔ IRI)."""
        context = {k: v for k, v in req.items()
                   if k not in arule.RESERVED_KEYS and not str(k).startswith(REF_KEY_PREFIX)}
        def equivalents(v: Any) -> set:
            key = str(v)
            if key not in rctx.equivalents:
                rctx.equivalents[key] = self._caller_equivalents(v, rctx.semantic_models_manager)
            return rctx.equivalents[key]

        return arule.check_scope(relation.domain_context, context, equivalents=equivalents)

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
        out = self._resolve_internal(
            db, ar_ref, req, visited=set(),
            record=record, require_active=require_active, rctx=rctx,
        )
        out.pop("own_pending_duties", None)
        return out

    def test_relation(
        self,
        db: Session,
        relation_id: str,
        req: Dict[str, Any],
        *,
        caller_can_write: bool,
        caller_is_admin: bool,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """The author's Test dialog: a dry run that records nothing.

        Needs Read-write (B2), and an ``app_sp`` AR is dry-run only by an Admin,
        since the dry run calls the MCP tool as the app service principal.
        """
        if not caller_can_write:
            raise AuthorityPermissionError(
                "Testing an Authority Relation needs Read-write on Authority Resolution.",
                required_level="Read/Write",
            )
        relation = self.resolve_relation_ref(db, relation_id)
        if relation is not None and not caller_is_admin:
            sp_slug = self._app_sp_in_prerequisite_walk(db, relation)
            if sp_slug is not None:
                raise AuthorityPermissionError(
                    "Only an Admin can test an Authority Relation whose chain resolves as the app "
                    "service principal.",
                    required_level="Admin", ar=sp_slug,
                )
        return self.resolve(db, relation_id, req, record=False, require_active=False, **kwargs)

    def _app_sp_in_prerequisite_walk(self, db: Session, relation: AuthorityRelationDb) -> Optional[str]:
        """The slug (or id) of the first app_sp AR in this AR's prerequisite walk, itself included.

        A dry run walks the prerequisites and calls their MCP refs as the app SP,
        so one app_sp AR anywhere in the chain counts (B2). Each version walks its
        own edges, and an upstream family is walked through its active version.
        """
        seen: set = set()
        stack = [relation]
        while stack:
            current = stack.pop()
            if current.resolver_auth == RESOLVER_AUTH_APP_SP:
                return current.slug or current.id
            if current.id in seen:
                continue
            seen.add(current.id)
            for edge in authority_prerequisite_repo.list_for_relation(db, relation_id=current.id):
                upstream = self.resolve_relation_ref(db, edge.prerequisite_family_slug)
                if upstream is not None:
                    stack.append(upstream)
        return None

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
                "scope_check": [],
                "pending_duties": [],
                "policy": None,
            }

        citation = self._policy_citation(db, relation)
        policy_label = f"{citation['policy_key']} v{citation['version']}" if citation and citation.get("policy_key") else None

        # The AR applies only inside its scope; outside it there is no authority
        # to decide with (prerequisites are gated by their own scope).
        in_scope, scope_reason, scope_results = self._check_scope(relation, req, rctx)
        if not in_scope:
            return self._finalize_resolve(
                db, relation, req, VERDICT_NO_AUTHORITY, scope_reason, [], [], record,
                scope_check=scope_results,
                policy=citation,
            )

        head_slug = self._family_slug_of(db, relation)
        # Edges belong to the version, so walk them by its id even when the family has no slug.
        head_key = head_slug or relation.id
        chain: List[Dict[str, Any]] = []
        # Entry-time cycle guard: the walker added our head when it recursed in.
        if head_key in visited:
            return self._finalize_resolve(
                db, relation, req,
                VERDICT_CONFLICT,
                f"cycle detected at {head_key}",
                chain, [], record=False, policy=citation,
            )
        visited.add(head_key)
        try:
            outer_verdict, blocker_reason, chain = self._walk_prerequisites(
                db, relation.id, head_key, req, visited,
                require_active=require_active, rctx=rctx,
            )
        finally:
            visited.discard(head_key)
        if outer_verdict is not None:
            # A blocked outer still materialises its own refs — the
            # provenance audit trail wants to show *what the AR was
            # pointing at* even when the chain short-circuited.
            resolved_refs = self._materialise_refs(db, relation, req, rctx)
            out = self._finalize_resolve(
                db, relation, req, outer_verdict, blocker_reason,
                chain, resolved_refs, record, scope_check=scope_results, policy=citation,
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
                scope_check=scope_results,
                policy=citation,
            )
            out["resolver_failure"] = True
            return out
        verdict, reason, own_pending, decision_code = self._decide(relation, req, resolved_refs, policy_label)
        # A conditional prerequisite's duties are this decision's duties too.
        pending = [d for e in chain for d in (e.get("pending_duties") or [])] + own_pending
        if verdict == VERDICT_APPROVED and pending:
            verdict = VERDICT_CONDITIONAL
            reason = "permitted once duties are fulfilled: " + ", ".join(
                d.get("message") or d["duty"] for d in pending)
        out = self._finalize_resolve(
            db, relation, req, verdict, reason, chain, resolved_refs, record,
            scope_check=scope_results, pending_duties=pending, own_pending_duties=own_pending,
            policy=citation,
        )
        if decision_code:
            out["reason_code"] = decision_code
        if verdict == VERDICT_NO_AUTHORITY and reason == NO_ENABLED_CHECKS_MESSAGE:
            out["reason_code"] = REASON_NO_ENABLED_CHECKS
        return out

    def _walk_prerequisites(
        self,
        db: Session,
        owner_id: str,
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
        # The version being resolved owns the edges: another version's edges never apply.
        edges = authority_prerequisite_repo.list_for_relation(db, relation_id=owner_id)
        for e in edges:
            pre_slug = e.prerequisite_family_slug
            inner = self._resolve_internal(
                db, pre_slug, req,
                visited=visited, record=False, require_active=require_active,
                rctx=rctx,
            )
            hop = {
                "slug": pre_slug,
                "version": inner.get("relation_version"),
                "verdict": inner["verdict"],
                "reason": inner.get("reason"),
                "required": e.required,
            }
            # Only the prerequisite's own duties: its chain entries below carry theirs.
            own_duties = inner.get("own_pending_duties") or []
            if own_duties and e.required:
                hop["pending_duties"] = own_duties
            chain.append(hop)
            # Carry the inner's own chain forward so provenance records the full walk.
            inner_chain = inner.get("prerequisite_chain") or []
            if inner_chain:
                chain.extend(inner_chain)
            if e.required and inner["verdict"] not in (VERDICT_APPROVED, VERDICT_CONDITIONAL):
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

    @staticmethod
    def _bump_usage_counters(db: Session, relation: AuthorityRelationDb, verdict: str) -> None:
        """Increment the usage counters in one SQL UPDATE.

        Read-modify-write on the ORM object loses increments when two resolves
        overlap; ``col = col + 1`` is applied by the database itself (S14).
        """
        values = {AuthorityRelationDb.usage_count: AuthorityRelationDb.usage_count + 1}
        if verdict == VERDICT_APPROVED:
            values[AuthorityRelationDb.approved_count] = AuthorityRelationDb.approved_count + 1
        elif verdict == VERDICT_DENIED:
            values[AuthorityRelationDb.denied_count] = AuthorityRelationDb.denied_count + 1
        db.query(AuthorityRelationDb).filter(AuthorityRelationDb.id == relation.id).update(
            values, synchronize_session=False,
        )
        db.expire(relation, ["usage_count", "approved_count", "denied_count"])

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
        *,
        scope_check: Optional[List[Dict[str, Any]]] = None,
        pending_duties: Optional[List[Dict[str, Any]]] = None,
        own_pending_duties: Optional[List[Dict[str, Any]]] = None,
        policy: Any = _UNSET,
    ) -> Dict[str, Any]:
        pending_duties = pending_duties or []
        # The cited reference and its clause labels: what the decision was grounded in,
        # as it stood at decision time.
        if policy is _UNSET:
            policy = self._policy_citation(db, relation)
        provenance: Optional[Dict[str, Any]] = None
        if chain or resolved_refs or scope_check or pending_duties or policy:
            provenance = {}
            if policy:
                provenance["policy"] = policy
            if chain:
                provenance["chain"] = chain
            if resolved_refs:
                provenance["resolved_refs"] = resolved_refs
            if scope_check:
                provenance["scope_check"] = scope_check
            if pending_duties:
                provenance["pending_duties"] = pending_duties
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
            self._bump_usage_counters(db, relation, verdict)

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
            "scope_check": scope_check or [],
            "pending_duties": pending_duties,
            "policy": policy or None,
            # Internal (popped by ``resolve``): this AR's own duties, without the
            # ones inherited from prerequisites (the walker records those per hop).
            "own_pending_duties": own_pending_duties or [],
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
        """Per context key outside the AR's scope, the casefolded values the AR
        names: its scalar params plus any ``domain_context.<key>`` ref's value
        and IRI (scope keys are compared by their constraints instead). MCP refs
        contribute their last cached label (no live call here)."""
        dc = arule.normalize_domain_context(relation.domain_context)
        values: Dict[str, set] = {}
        for k, v in dc["params"].items():
            if v is not None and not isinstance(v, (dict, list)):
                values.setdefault(k, set()).add(str(v).strip().casefold())
        for row in authority_resource_ref_repo.list_for_relation(db, relation_id=relation.id):
            if not row.field_path.startswith("domain_context."):
                continue
            key = row.field_path.split(".", 1)[1]
            if "." in key:
                continue
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
        # The prerequisite dry run sees the caller's context, as a resolve would.
        req = {**context, **(request or {})}
        candidates: List[Dict[str, Any]] = []
        for family_id, (hop, via_iri) in family_hops.items():
            anchor = authority_relation_repo.get(db, family_id)
            relation = self._family_active_version(db, anchor) if anchor else None
            if relation is None:
                continue
            slug = self._family_slug_of(db, relation)

            ar_values = self._ar_context_values(db, relation, rctx)
            scope = arule.normalize_domain_context(relation.domain_context)["scope"]
            matches, conflicts = [], []
            for key, equiv in caller_equiv.items():
                constraints = [c for c in scope if arule.scope_key(c["leftOperand"]) == key]
                if constraints:
                    # Every operator, as the scope gate checks it at resolve time.
                    ok = all(arule.compare_value(context[key], c["operator"], c["rightOperand"],
                                                 lambda _v, e=equiv: e) for c in constraints)
                    (matches if ok else conflicts).append(key)
                    continue
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
            head_key = slug or relation.id
            _, _, chain = self._walk_prerequisites(
                db, relation.id, head_key, req, {head_key}, require_active=True, rctx=rctx,
            )
            # A conditional prerequisite passes (its duties carry over), as in resolve.
            unmet = [e["slug"] for e in chain
                     if e["required"] and e["verdict"] not in (VERDICT_APPROVED, VERDICT_CONDITIONAL)]

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

    def to_read_dict(self, db: Session, relation: AuthorityRelationDb, include_state: bool = True) -> Dict[str, Any]:
        """The AR as the API returns it. ``include_state=False`` (the list view) skips the
        per-row lookups for ``editable`` (a family scan) and ``dna_current`` (the runs)."""
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation.id)
        # Load criteria via the repo (not relation.criteria) so a create/update
        # response reflects rows just written in the same transaction.
        criteria = authority_criterion_repo.list_for_relation(db, relation_id=relation.id)
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation.id)
        current_hash = self.definition_hash(db, relation)
        fully_affirmed = self.is_fully_affirmed(db, relation.id, current_hash=current_hash)
        dna_current = self._dna_is_current(db, relation, current_hash) if include_state else None
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
            "domain_context": arule.normalize_domain_context(relation.domain_context),
            "rule": getattr(relation, "rule", None),
            "justification_chain": relation.justification_chain,
            "authority_policy_id": getattr(relation, "authority_policy_id", None),
            "policy_clause_refs": getattr(relation, "policy_clause_refs", None) or [],
            "policy": self._policy_citation(db, relation),
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
            "definition_hash": current_hash,
            "definition_edited_by": getattr(relation, "definition_edited_by", None),
            "activated_at": getattr(relation, "activated_at", None),
            "editable": self.is_editable(db, relation) if include_state else None,
            "dna_current": dna_current,
            "enabled_check_count": sum(1 for c in criteria if c.enabled),
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
                    "definition_hash": a.definition_hash,
                    "stale": bool(a.affirmed and a.definition_hash != current_hash),
                }
                for a in affs
            ],
            "criteria": [
                {
                    "id": c.id,
                    "name": c.name,
                    "rule": c.rule,
                    "failure_message": c.failure_message,
                    "direction": c.direction,
                    "weight": c.weight,
                    "dimension": getattr(c, "dimension", "people"),
                    "order": c.display_order,
                    "enabled": c.enabled,
                    "copied_from": c.copied_from,
                    "policy_clause_ref": getattr(c, "policy_clause_ref", None),
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
