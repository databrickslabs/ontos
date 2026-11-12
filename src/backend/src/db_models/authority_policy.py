"""SQLAlchemy model for the Authority Policy (ARF justification basis).

An **Authority Policy** is the documented basis an Authority Relation's
authority derives from: a delegation-of-authority schedule, a board mandate,
a regulation, a procurement policy, an SOP or a recorded exception (ARF paper
§3.7 ``arf:PolicyDocument``; ADM ``policy_authority_basis``). ARs cite one
policy *version* plus the clauses they implement; the source documents are
Metadata documents on the policy, stored with their SHA-256.

Versions are immutable once approved: each is a row in a version family
(``version_family_id``), ``parent_policy_id`` is the PROV ``wasDerivedFrom``
edge. Approving a successor supersedes its parent.
"""

from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON

from src.common.database import Base


class AuthorityPolicyDb(Base):
    __tablename__ = 'authority_policies'

    id = Column(String, primary_key=True)
    # Stable per family (e.g. POL-DOA-2026); versions share it.
    policy_key = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, default='1')
    version_family_id = Column(String, nullable=True, index=True)
    parent_policy_id = Column(String, nullable=True, index=True)  # prov:wasDerivedFrom
    change_summary = Column(Text, nullable=True)

    title = Column(String, nullable=False)
    # DOA | BOARD_MANDATE | REGULATION | PROCUREMENT_POLICY | SOP | EXCEPTION
    policy_type = Column(String, nullable=False, default='DOA')
    summary = Column(Text, nullable=True)
    owner_team_id = Column(String, ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)
    # The scope the policy covers, e.g. {"market": ["DE", "AT"], "legal_entity": "NBG-CH"}.
    jurisdiction = Column(JSON, nullable=True)

    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)

    # draft | approved | superseded | withdrawn
    status = Column(String, nullable=False, default='draft', index=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    # A Metadata document on this policy that evidences the approval (minutes, signed memo).
    approval_evidence_document_id = Column(String, nullable=True)
    withdrawn_reason = Column(Text, nullable=True)

    # [{ref: "§7.1", title, text, limits: {amount, currency}, conditions: [str]}]
    clauses = Column(JSON, nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
