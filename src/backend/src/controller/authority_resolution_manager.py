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
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common import authority_resolution_dna as authority_dna
from src.common.authority_resolution_dna import Criterion, DIR_NONE
from src.common.compliance_dsl import evaluate_rule_on_object
from src.db_models.authority_resolution import (
    AuthorityRelationDb,
    AuthorityAffirmationDb,
    AuthorityDecisionDb,
    AuthorityDnaRunDb,
)
from src.db_models.compliance import CompliancePolicyDb
from src.repositories.authority_resolution_repository import (
    authority_relation_repo,
    authority_affirmation_repo,
    authority_criterion_repo,
    authority_dna_run_repo,
    authority_decision_repo,
)
from src.repositories.entity_domain_association_repository import entity_domain_repo

logger = get_logger(__name__)

ENTITY_TYPE = "authority_relation"

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


class AuthorityResolutionManager:
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
        # Polymorphic tags.
        self._set_tags(db, rel_id, getattr(payload, "tags", None), current_user)
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

        evidence = data.get("evidence_binding")
        if evidence is not None and hasattr(evidence, "dict"):
            data["evidence_binding"] = evidence.dict()

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
        # Polymorphic tags (only when the caller supplied the field).
        self._set_tags(db, relation_id, getattr(payload, "tags", None), current_user)

        # Changing an active AR triggers recompute + re-review (best-effort recompute).
        if relation.status == STATUS_ACTIVE:
            try:
                self.compute_dnaco(db, relation_id)
            except Exception as e:  # pragma: no cover - evidence read is environment-dependent
                logger.warning(f"DNAco recompute after update failed for {relation_id}: {e}")
        return relation

    def delete_relation(self, db: Session, relation_id: str) -> bool:
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return False
        entity_domain_repo.remove_all_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation_id)
        authority_relation_repo.remove(db, id=relation_id)
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
        return relation

    # ------------------------------------------------------- affirmations

    def _replace_affirmations(self, db: Session, relation_id: str, affirmations: List[Any]) -> None:
        authority_affirmation_repo.delete_for_relation(db, relation_id=relation_id)
        for idx, aff in enumerate(affirmations):
            a = aff.dict() if hasattr(aff, "dict") else dict(aff)
            is_reviewer = a.get("is_reviewer", False)
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
                "affirmed": False,
                "review_status": "pending" if is_reviewer else "na",
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
        if not rule.upper().startswith("ASSERT"):
            rule = "ASSERT " + rule
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

    def affirm(self, db: Session, affirmation_id: str, affirmed_by: str, notes: Optional[str] = None) -> Optional[AuthorityAffirmationDb]:
        aff = authority_affirmation_repo.get(db, affirmation_id)
        if not aff:
            return None
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

    def get_review_context(self, db: Session, relation_id: str, reviewer: str) -> Optional[Dict[str, Any]]:
        """Build the role-specific review context for a reviewer of this AR."""
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation_id)
        participant = next((a for a in affs if a.principal == reviewer and getattr(a, "is_reviewer", False)), None)
        if participant is None:
            return None
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

    def submit_review(self, db: Session, participant_id: str, answers: Dict[str, Any], reviewer: Optional[str] = None) -> Optional[AuthorityAffirmationDb]:
        """Persist a reviewer's elicited answers and mark their review complete."""
        participant = authority_affirmation_repo.get(db, participant_id)
        if not participant:
            return None
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
            result = authority_dna.compute_dnaco(self._load_criteria(relation), rows)

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
            if relation.status == STATUS_ACTIVE and overall > (relation.dna_max_threshold or 0.3):
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
                row = {k: r.get(cm[k]) for k in self._CANONICAL_ELEMENTS if k in cm}
                combined.append(authority_dna.normalize_row(row))
        return combined

    def _read_evidence_rows(self, binding: Dict[str, Any], limit: int = 500) -> List[Dict[str, Any]]:
        """Best-effort read of the bound UC Delta table via the SQL warehouse.

        Isolated and defensive: any failure returns an empty sample rather than
        breaking the run (the manager surfaces the failure via the run status).
        """
        table = (binding or {}).get("source_table_fqn")
        if not table:
            return []
        try:
            from src.common.config import get_settings
            from src.common.workspace_client import get_workspace_client

            settings = get_settings()
            warehouse_id = (
                getattr(settings, "DATABRICKS_WAREHOUSE_ID", None)
                or getattr(settings, "DATABRICKS_SQL_WAREHOUSE_ID", None)
            )
            if not warehouse_id:
                logger.warning("No SQL warehouse configured; cannot read AR evidence table.")
                return []
            ws = get_workspace_client(settings)
            row_filter = (binding or {}).get("row_filter")
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
            logger.warning(f"Evidence read failed for table '{table}': {e}")
            return []

    # ------------------------------------------------------------- lifecycle

    def set_status(self, db: Session, relation_id: str, status: str) -> Tuple[Optional[AuthorityRelationDb], Optional[str]]:
        """Transition an AR's status. Returns (relation, error_message)."""
        relation = authority_relation_repo.get(db, relation_id)
        if not relation:
            return None, "not_found"
        if status == STATUS_ACTIVE:
            # Activation gate: DNAco measured & within ceiling, AND fully affirmed.
            if relation.dna_magnitude is None:
                return relation, "DNA-Coefficient has not been measured yet."
            if relation.dna_magnitude > (relation.dna_max_threshold or 0.3):
                return relation, (
                    f"DNA-Coefficient {relation.dna_magnitude} exceeds the maximum "
                    f"{relation.dna_max_threshold}."
                )
            if not self.is_fully_affirmed(db, relation_id):
                return relation, "All required affirmations must be completed before activation."
        updated = authority_relation_repo.update(db, db_obj=relation, obj_in={"status": status})
        return updated, None

    # --------------------------------------------------------- runtime gate

    def _evaluate_decision(self, relation: AuthorityRelationDb, req: Dict[str, Any]) -> Tuple[str, str]:
        """Deterministic evaluation of request params against the AR's author-configured
        decision criteria. Each enabled criterion's DSL rule is run against the request;
        the first that fails denies (with its failure message). No criteria = an
        unconstrained gate (approve).
        """
        norm = authority_dna.normalize_row(req)
        for c in self._load_criteria(relation):
            try:
                passed, msg = evaluate_rule_on_object(c.rule, norm)
            except Exception as e:  # pragma: no cover - malformed author rule
                logger.warning(f"Criterion '{c.code}' failed to evaluate on AR {relation.id}: {e}")
                continue
            if not passed:
                return VERDICT_DENIED, (c.message or msg or f"Criterion '{c.code}' failed")
        return VERDICT_APPROVED, "all checks passed"

    def resolve(self, db: Session, ar_ref: str, req: Dict[str, Any], record: bool = True, require_active: bool = True) -> Dict[str, Any]:
        """Deterministically resolve a decision against an AR (by id or slug).

        Production/MCP use requires the AR to be ``active`` and records the
        decision (``require_active=True``, ``record=True``). The detail-view
        **Test** dry-run passes ``require_active=False, record=False`` so an author
        can preview the verdict for a draft/needs_review AR without affecting the
        usage counters. Returns ``no_authority`` when the AR does not exist, or
        (in production mode) is not active.
        """
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
            }

        verdict, reason = self._evaluate_decision(relation, req)

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
        }

    # --------------------------------------------------------- read assembly

    def to_read_dict(self, db: Session, relation: AuthorityRelationDb) -> Dict[str, Any]:
        affs = authority_affirmation_repo.list_for_relation(db, relation_id=relation.id)
        # Load criteria via the repo (not relation.criteria) so a create/update
        # response reflects rows just written in the same transaction.
        criteria = authority_criterion_repo.list_for_relation(db, relation_id=relation.id)
        domains = entity_domain_repo.get_domains_for_entity(db, entity_type=ENTITY_TYPE, entity_id=relation.id)
        fully_affirmed = self.is_fully_affirmed(db, relation.id)
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
            "tags": tags,
            "created_at": relation.created_at,
            "updated_at": relation.updated_at,
            "created_by": relation.created_by,
        }
