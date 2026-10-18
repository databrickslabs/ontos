"""SQLAlchemy models for the Authority Resolution feature (ARF).

An **Authority Relation (AR)** is realised as two entities, mirroring the
Data-Contract-definition vs. compliance-run/result split already in the codebase:

* :class:`AuthorityRelationDb` — the reusable authority *rule* (the Definition;
  the entity shown in the list view and called by agents via MCP).
* :class:`AuthorityDecisionDb` — one record per runtime evaluation or per sampled
  evidence row (the ARF JSON-LD ``ar-instance`` shape), carrying its own
  divergence and the AR *version* that decided it.

Supporting tables:

* :class:`AuthorityAffirmationDb` — the N-functional affirmation stakeholders
  (default the ARF Business/Technical/Governance trio; customer-tunable).
* :class:`AuthorityDnaRunDb` — a single DNA-Coefficient computation over the
  bound evidence (mirrors ``compliance_runs``); its per-row results are the
  ``AuthorityDecisionDb`` rows tagged with ``dna_run_id``.

DNA-Coefficient polarity follows the ARF paper: it is a **divergence**,
``0.0`` = documented authority exactly matches lived practice, higher = worse.
"""

from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, Text, Boolean, ForeignKey, Integer, Float, JSON,
    CheckConstraint, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from src.common.database import Base


class AuthorityRelationDb(Base):
    """An Authority Relation *Definition* — the reusable, agent-callable rule."""
    __tablename__ = 'authority_relations'

    id = Column(String, primary_key=True)
    # Stable, human-meaningful key an agent passes to the MCP tool (the ARF @id).
    slug = Column(String, nullable=True, index=True, unique=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Lifecycle status is operational; maturity_level (L0-L5) is derived in the manager.
    status = Column(String, default='draft', nullable=False, index=True)  # draft|active|needs_review|retired

    # Versioning (full DP/DC snapshot parity): each version is an immutable row;
    # version_family_id groups the family, parent_relation_id is the lineage edge.
    version = Column(String, default='1.0.0', nullable=False)  # semantic version string
    version_family_id = Column(String, nullable=True, index=True)
    parent_relation_id = Column(String, nullable=True, index=True)  # source row this version was cloned from
    base_name = Column(String, nullable=True)          # stable family display name
    change_summary = Column(Text, nullable=True)       # what changed in this version
    draft_owner_id = Column(String, nullable=True, index=True)  # personal-draft owner (mirrors DP/DC)

    # Ownership & scoping (parity with Data Products / Contracts).
    owner_team_id = Column(String, ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)
    project_id = Column(String, ForeignKey('projects.id', ondelete='SET NULL'), nullable=True, index=True)

    # --- ARF tuple: Actor ---------------------------------------------------
    actor_role = Column(String, nullable=True)        # arf:actor OrganizationalRole
    actor_identity = Column(String, nullable=True)    # arf:heldBy (principal)
    actor_since = Column(DateTime(timezone=True), nullable=True)  # arf:since

    # --- ARF tuple: Action --------------------------------------------------
    action = Column(String, nullable=True)            # controlled vocab: approve|escalate|override|delegate|veto

    # --- ARF tuple: Object (binds to an existing catalog entity) ------------
    object_type = Column(String, nullable=True)       # e.g. data_product | data_contract
    object_id = Column(String, nullable=True)
    object_resolves_to = Column(JSON, nullable=True)  # cross-domain anchors (list of URIs)

    # --- ARF tuple: Domain-Context (the evaluable predicate bag) ------------
    domain_context = Column(JSON, nullable=True)      # {threshold, currency, market, ...}

    # --- ARF tuple: Justification-Chain -------------------------------------
    justification_chain = Column(JSON, nullable=True)  # {policy_id, effective_date, derived_from, doc_url}

    # --- Ontos-compiled deterministic runtime rule --------------------------
    decision_logic = Column(JSON, nullable=True)      # {allowed_principals, threshold, required_affirmations, ...}

    # --- Evidence binding (v1: a single UC Delta table + column map) --------
    evidence_binding = Column(JSON, nullable=True)    # legacy single source: {source_table_fqn, column_map, row_filter}
    # Multiple typed evidence sources: [{type: delta_table|data_product|asset, ref, column_map, row_filter}]
    evidence_sources = Column(JSON, nullable=True)

    # --- DNA-Coefficient (aggregate, rolled up from decisions/evidence) -----
    dna_magnitude = Column(Float, nullable=True)      # 0.0 = best; higher = worse (additive over dimensions)
    dna_direction = Column(String, nullable=True)     # actual-exceeds-documented | documented-exceeds-actual | balanced
    dna_dimensions = Column(JSON, nullable=True)      # {dimension: score} incl. structural + evidence dims
    dna_measured_at = Column(DateTime(timezone=True), nullable=True)
    dna_max_threshold = Column(Float, default=0.3, nullable=False)  # activation ceiling (magnitude must be <= this)
    dna_scoring_config = Column(JSON, nullable=True)  # admin/per-domain tunable weights

    # Optional scheduled recompute (background job reads this).
    schedule_cron = Column(String, nullable=True)

    # ARF v2: how MCP calls made while resolving this AR are authenticated.
    # 'obo'    — on-behalf-of the calling agent's token (default; correct for
    #            actor-identity-style resolution where context matters).
    # 'app_sp' — the Ontos app's own service principal (author pins this when
    #            stability matters more than per-caller context).
    resolver_auth = Column(String, nullable=False, default='obo', server_default='obo')

    # --- Maturity (shared, compliance-gated Maturity Level feature) ----------
    maturity_level_order = Column(Integer, nullable=True)   # cache of achieved level_order
    maturity_evaluated_at = Column(DateTime(timezone=True), nullable=True)

    # Denormalised usage metrics (detail tiles / list badges).
    usage_count = Column(Integer, default=0, nullable=False)
    approved_count = Column(Integer, default=0, nullable=False)
    denied_count = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String, nullable=True)

    affirmations = relationship(
        "AuthorityAffirmationDb", back_populates="relation",
        cascade="all, delete-orphan", lazy="selectin",
    )
    criteria = relationship(
        "AuthorityCriterionDb", back_populates="relation",
        cascade="all, delete-orphan", lazy="selectin",
        order_by="AuthorityCriterionDb.display_order",
    )
    decisions = relationship(
        "AuthorityDecisionDb", back_populates="relation",
        cascade="all, delete-orphan", lazy="select",
    )
    dna_runs = relationship(
        "AuthorityDnaRunDb", back_populates="relation",
        cascade="all, delete-orphan", lazy="select",
    )
    resource_refs = relationship(
        "AuthorityResourceRefDb", back_populates="relation",
        cascade="all, delete-orphan", lazy="selectin",
    )


class AuthorityAffirmationDb(Base):
    """A participant on an AR — an **approver** (affirmation gate), a **reviewer**
    (interviewee for the review process), or both.

    A DNA-Coefficient is *valid-for-use* only once every required **approver**
    affirmation is complete (ARF §4.5 tri-functional gate, generalised to N).
    **Reviewers** are the principals who must be interviewed to confirm the AR
    reflects real-world practice; each gets an Asset Review task and their
    elicited answers are captured here. A principal may be both.
    """
    __tablename__ = 'authority_affirmations'

    id = Column(String, primary_key=True)
    relation_id = Column(String, ForeignKey('authority_relations.id'), nullable=False, index=True)
    role = Column(String, nullable=False)             # Business Role name (cached label)
    # Reference to the Settings Business Role (organizational role, NOT an app RBAC role).
    business_role_id = Column(String, nullable=True)
    role_category = Column(String, nullable=True)     # governance|technical|business|operational (drives the questionnaire)
    principal = Column(String, nullable=False)        # email or group identifier
    principal_type = Column(String, default='user', nullable=False)  # user|group

    # A participant can be an approver, a reviewer, or both (not mutually exclusive).
    is_approver = Column(Boolean, default=True, nullable=False)   # counts toward the affirmation gate
    is_reviewer = Column(Boolean, default=False, nullable=False)  # must be interviewed in the review process

    # Approver facet (the affirmation gate).
    required = Column(Boolean, default=True, nullable=False)
    affirmed = Column(Boolean, default=False, nullable=False)
    affirmed_by = Column(String, nullable=True)
    affirmed_at = Column(DateTime(timezone=True), nullable=True)

    # Reviewer facet (the review process / structured elicitation).
    review_status = Column(String, default='na', nullable=False)  # na|pending|in_review|completed
    review_answers = Column(JSON, nullable=True)                  # elicited questionnaire responses
    review_request_id = Column(String, nullable=True, index=True)  # linked DataAssetReviewRequest id

    notes = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)

    relation = relationship("AuthorityRelationDb", back_populates="affirmations")


class AuthorityCriterionDb(Base):
    """An author-configurable decision criterion attached to an AR.

    Mirrors the Maturity-Level → Compliance-Policy link (``MaturityGateDb``): each
    row binds a reusable **Compliance Check** (its DSL ``ASSERT`` rule is the
    condition) to an Authority Relation. The gate approves only when every enabled
    criterion passes; the DNA-Coefficient engine treats a criterion that *fails*
    for an evidence row as a divergence, weighted by ``weight`` and signed by
    ``direction`` (the ARF ``arf:direction``). ``direction``/``weight`` are the
    ARF-specific facets a plain pass/fail check cannot carry, so they live here on
    the link rather than on the shared policy. Scoped to the versioned AR row; the
    manager re-creates the links on each version bump.
    """
    __tablename__ = 'authority_criteria'

    id = Column(String, primary_key=True)
    relation_id = Column(
        String, ForeignKey('authority_relations.id', ondelete="CASCADE"),
        nullable=False, index=True,
    )
    compliance_policy_id = Column(
        String, ForeignKey('compliance_policies.id', ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # actual-exceeds-documented | documented-exceeds-actual | neutral
    direction = Column(String, nullable=False, default='neutral')
    weight = Column(Float, nullable=False, default=1.0)
    # DNAco dimension this criterion contributes to (people|policy|...); structural
    # is a separate definition-completeness evaluator, not a criterion dimension.
    dimension = Column(String, nullable=False, default='people')
    display_order = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    relation = relationship("AuthorityRelationDb", back_populates="criteria")
    compliance_policy = relationship("CompliancePolicyDb", lazy="selectin")


class AuthorityDnaRunDb(Base):
    """A single DNA-Coefficient computation over an AR's bound evidence."""
    __tablename__ = 'authority_dna_runs'

    id = Column(String, primary_key=True)
    relation_id = Column(String, ForeignKey('authority_relations.id'), nullable=False, index=True)
    status = Column(String, default='queued', nullable=False, index=True)  # queued|running|succeeded|failed
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    sampled_count = Column(Integer, default=0, nullable=False)
    divergent_count = Column(Integer, default=0, nullable=False)
    magnitude = Column(Float, default=0.0, nullable=False)
    direction = Column(String, nullable=True)
    per_dimension_scores = Column(JSON, nullable=True)  # {dimension: score} for this run
    error_message = Column(Text, nullable=True)

    relation = relationship("AuthorityRelationDb", back_populates="dna_runs")


class AuthorityDecisionDb(Base):
    """A single AR decision: a runtime MCP evaluation, an evidence-row comparison, or a test.

    This is the ARF JSON-LD ``ar-instance`` shape at the relational layer; it records
    the AR *version* that produced it so any decision is reproducible against the
    rule as it then stood.
    """
    __tablename__ = 'authority_decisions'

    id = Column(String, primary_key=True)
    relation_id = Column(String, ForeignKey('authority_relations.id'), nullable=False, index=True)
    relation_version = Column(String, nullable=True)  # semantic version of the AR that decided it
    source = Column(String, default='mcp', nullable=False, index=True)  # mcp|evidence|test
    dna_run_id = Column(String, ForeignKey('authority_dna_runs.id'), nullable=True, index=True)

    actor_identity = Column(String, nullable=True)    # who signed off in this decision
    action = Column(String, nullable=True)
    object_id = Column(String, nullable=True)
    request_params = Column(JSON, nullable=True)

    verdict = Column(String, nullable=True)           # approved|denied|no_authority|conflict
    reason = Column(Text, nullable=True)

    divergence_magnitude = Column(Float, nullable=True)  # per-row divergence (evidence rows)
    direction = Column(String, nullable=True)

    # ARF v2 provenance: records the prerequisite chain the resolver walked
    # and the resource-ref values it materialised to reach this verdict.
    # Shape (nullable to stay compatible with existing rows):
    #   {
    #     "chain":          [{"ar_slug": "...", "version": "x.y.z", "verdict": "..."}],
    #     "resolved_refs":  [{"field_path": "...", "ref_type": "...",
    #                         "value": "...", "source": "..." }]
    #   }
    provenance = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False, index=True)

    relation = relationship("AuthorityRelationDb", back_populates="decisions")


class AuthorityResourceRefDb(Base):
    """A typed pointer that backs one of an AR's canonical fields.

    The AR row's own ``actor_identity`` / ``object_id`` / ``domain_context``
    columns continue to hold the resolved *string* so existing list views,
    search, and REST responses keep working unchanged; this row records
    where that string came from and lets the resolver re-materialise it
    on demand.

    ``ref_type`` selects which branch is populated:

    * ``literal``       — ``literal_value`` is the answer; nothing to resolve.
    * ``ontos_entity``  — points at another Ontos entity (Business Concept /
                          Term / Data Domain / Data Product / asset / …).
                          Resolution reuses the existing semantic-link +
                          entity-domain-association plumbing to fetch the
                          canonical label and IRI.
    * ``mcp_tool``      — invoked at eval time via the Databricks MCP SDK.
                          ``mcp_service_name`` is the SDK's full service
                          name (``mcp-services/system.ai.github`` etc.);
                          ``mcp_params`` is a Jinja template over the
                          resolve-time request; ``mcp_result_pointer`` is
                          a JSONPath into the tool response (default
                          ``$`` — take the whole value).
    """
    __tablename__ = 'authority_resource_refs'

    id = Column(String, primary_key=True)
    relation_id = Column(
        String, ForeignKey('authority_relations.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # JSON-pointer-ish path on the AR, e.g. ``actor_identity``,
    # ``object_id``, ``domain_context.brand``.
    field_path = Column(String, nullable=False)
    ref_type = Column(String, nullable=False)  # literal|ontos_entity|mcp_tool

    literal_value = Column(Text, nullable=True)

    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)

    mcp_service_name = Column(String, nullable=True)
    mcp_tool_name = Column(String, nullable=True)
    mcp_params = Column(JSON, nullable=True)
    mcp_result_pointer = Column(String, nullable=False, default='$', server_default='$')

    cached_label = Column(Text, nullable=True)
    cached_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint('relation_id', 'field_path', name='uq_authority_resource_refs_field'),
    )

    relation = relationship("AuthorityRelationDb", back_populates="resource_refs")


class AuthorityPrerequisiteDb(Base):
    """A ``requires_prior_authority`` edge between two Authority Relations.

    Both endpoints are per-family slugs (never version UUIDs) — the resolver
    walks these edges at eval time and resolves each slug to its family's
    active version via :func:`AuthorityResolutionManager.resolve_relation_ref`.
    Keying by family means a published AR survives version bumps of its
    prerequisites; the tradeoff is that *replacing* an upstream AR with a
    new active version can transitively change what the downstream AR
    does. Cycle detection is enforced at write time; a defensive check
    also runs during resolve.

    A required prerequisite that comes back ``denied`` / ``no_authority``
    short-circuits the outer AR to ``denied`` with the chain recorded on
    ``AuthorityDecisionDb.provenance``. Optional prerequisites surface as
    advisory warnings on the response but do not block.
    """
    __tablename__ = 'authority_prerequisites'

    id = Column(String, primary_key=True)
    relation_family_slug = Column(String, nullable=False, index=True)
    prerequisite_family_slug = Column(String, nullable=False, index=True)
    required = Column(Boolean, nullable=False, default=True, server_default='true')
    display_order = Column(Integer, nullable=False, default=0, server_default='0')
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            'relation_family_slug', 'prerequisite_family_slug',
            name='uq_authority_prerequisites_edge',
        ),
        CheckConstraint(
            'relation_family_slug <> prerequisite_family_slug',
            name='ck_authority_prerequisites_no_self_loop',
        ),
    )
