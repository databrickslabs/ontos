"""SQLAlchemy model for a Policy reference (the ARF justification metadata).

A **Policy reference** points at the source document an Authority Relation's
authority rests on (a delegation-of-authority schedule, a board mandate, a
regulation, an SOP). Ontos keeps the reference only: name, external id,
description, version, validity window, an optional link out and the owner team.
The document itself stays where it is, and the AR's approvers check it there.

References are **not enforced** (ARF 1.2.0, #1294 decision): an expired or
superseded reference does not change what an AR decides. Validity is exposed to
Compliance Checks as ``justification.*`` (see ``controller/authority_policy_manager``).

Versions: each source-document version is its own row in a version family
(``version_family_id``); ``parent_policy_id`` links a new version to the one it
replaces. ARs cite one row (``authority_relations.authority_policy_id``), and many
ARs can cite the same reference.
"""

from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, ForeignKey, JSON

from src.common.database import Base


class AuthorityPolicyDb(Base):
    __tablename__ = 'authority_policies'

    id = Column(String, primary_key=True)
    # The external id (e.g. POL-DOA-2026); versions of one document share it.
    policy_key = Column(String, nullable=False, index=True)
    version = Column(String, nullable=False, default='1')
    version_family_id = Column(String, nullable=True, index=True)
    parent_policy_id = Column(String, nullable=True, index=True)  # the version it replaces
    change_summary = Column(Text, nullable=True)

    title = Column(String, nullable=False)  # the name
    summary = Column(Text, nullable=True)  # the description
    owner_team_id = Column(String, ForeignKey('teams.id', ondelete='SET NULL'), nullable=True, index=True)
    # Link out to the source document (http or https only).
    url = Column(String, nullable=True)

    # The validity window the source document states. Informational: not enforced.
    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_to = Column(DateTime(timezone=True), nullable=True)

    # Optional clause labels, offered as suggestions in the AR's clause picker.
    # Not validated against anything: an AR's clause labels are free text.
    clauses = Column(JSON, nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
