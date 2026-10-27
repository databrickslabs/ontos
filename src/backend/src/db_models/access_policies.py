"""SQLAlchemy models for Access Policies (W3C ODRL 2.2).

* :class:`AccessPolicyDb` — an ODRL Policy (``Set`` / ``Offer`` / ``Agreement``).
  The rules live in ``body`` as normalized (atomic) ODRL JSON — the canonical
  source of truth; :class:`AccessPolicyIndexDb` is a derived lookup index
  ("which policies touch asset X / principal Y").
* :class:`AccessAudienceDb` — a named ``odrl:PartyCollection``: who.
* :class:`AccessAssetCollectionDb` — a named ``odrl:AssetCollection``: what.

All three are first-class governed entities and share the lifecycle columns in
:class:`GovernedEntityMixin` (status, semantic version family, ownership via
team/project/draft owner, maturity cache) — the same shape as Data Products.
Domains, tags, comments and metadata attach polymorphically by entity type.
"""
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, event, func
from sqlalchemy.orm import declared_attr

from src.common.database import Base

ENTITY_TYPE_POLICY = "access_policy"
ENTITY_TYPE_AUDIENCE = "access_audience"
ENTITY_TYPE_ASSET_COLLECTION = "access_asset_collection"


class GovernedEntityMixin:
    """Lifecycle columns shared by every Access Policy entity."""

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    # Stable ODRL IRI of the family (urn:ontos:<kind>:<family-id>); referenced from policy bodies.
    uid = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    # draft, under_review, approved, active, needs_review, deprecated, retired
    status = Column(String, nullable=False, default="draft", index=True)

    # Versioning (Data Product / Contract parity).
    version = Column(String, nullable=False, default="1.0.0")
    version_family_id = Column(String, nullable=False, index=True)
    change_summary = Column(Text, nullable=True)
    # Personal draft owner — if set, visible only to the owner / project team.
    draft_owner_id = Column(String, nullable=True, index=True)

    # Maturity (shared compliance-gated Maturity Level subsystem cache).
    maturity_level_order = Column(Integer, nullable=True)
    maturity_evaluated_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    # Review trail of the current version (separation of duties: approver != submitter/author).
    submitted_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    @declared_attr
    def owner_team_id(cls):  # noqa: N805
        return Column(String, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True)

    @declared_attr
    def project_id(cls):  # noqa: N805
        return Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)

    @declared_attr
    def parent_id(cls):  # noqa: N805
        return Column(String, ForeignKey(f"{cls.__tablename__}.id", ondelete="SET NULL"), nullable=True, index=True)


class AccessPolicyDb(GovernedEntityMixin, Base):
    __tablename__ = "access_policies"

    # ODRL policy subclass: Set | Offer | Agreement.
    policy_type = Column(String, nullable=False, default="Set")
    # ODRL conflict strategy: perm | prohibit | invalid.
    conflict = Column(String, nullable=False, default="prohibit")
    # Parent policy IRIs (ODRL inheritFrom).
    inherit_from = Column(JSON, nullable=True)
    # Normalized atomic rules: {"permission": [...], "prohibition": [...], "obligation": [...]}.
    body = Column(JSON, nullable=False, default=dict)

    def __repr__(self):
        return f"<AccessPolicyDb(id='{self.id}', name='{self.name}', status='{self.status}')>"


class AccessPolicyIndexDb(Base):
    """Derived (rule_kind, role, value) lookup rows; rebuilt on every policy write."""
    __tablename__ = "access_policy_index"
    __table_args__ = (UniqueConstraint("policy_id", "rule_kind", "role", "value", name="uq_access_policy_index"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    policy_id = Column(String, ForeignKey("access_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_kind = Column(String, nullable=False)  # permission | prohibition | obligation
    role = Column(String, nullable=False)  # action | target | assignee | assigner
    value = Column(String, nullable=False, index=True)


class AccessAudienceDb(GovernedEntityMixin, Base):
    """A named ``odrl:PartyCollection``.

    ``members`` is the collection source (typed principals ``user:``/``group:``/
    ``sp:``); empty means "every principal". ``refinement`` narrows it by
    principal attributes (ODRL §2.5.6). v1 attribute source = Ontos Business Roles.
    """
    __tablename__ = "access_audiences"

    members = Column(JSON, nullable=False, default=list)
    refinement = Column(JSON, nullable=False, default=list)


class AccessAssetCollectionDb(GovernedEntityMixin, Base):
    """A named ``odrl:AssetCollection``: member asset refs + refinement (ODRL §2.5.5)."""
    __tablename__ = "access_asset_collections"

    members = Column(JSON, nullable=False, default=list)
    refinement = Column(JSON, nullable=False, default=list)


UID_PREFIXES = {
    AccessPolicyDb: "urn:ontos:policy:",
    AccessAudienceDb: "urn:ontos:audience:",
    AccessAssetCollectionDb: "urn:ontos:asset-collection:",
}


def _seed_family(_mapper, _connection, target):
    """Guarantee id / version_family_id / uid regardless of insert path (mirrors DataProductDb)."""
    if not getattr(target, "id", None):
        target.id = str(uuid4())
    if not getattr(target, "version_family_id", None):
        target.version_family_id = target.id
    if not getattr(target, "uid", None):
        target.uid = UID_PREFIXES[type(target)] + target.version_family_id


for _model in UID_PREFIXES:
    event.listen(_model, "before_insert", _seed_family)
