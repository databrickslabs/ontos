from uuid import uuid4
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from src.common.database import Base


class TeamDb(Base):
    """Team: name, title, description; used for ownership and membership (TeamsManager, role resolution).

    Domain assignment is polymorphic via ``entity_domain_associations``
    (entity_type='team'); the legacy ``domain_id`` column was removed in favour of
    multi-domain assignment.
    """
    __tablename__ = 'teams'

    # Core Fields
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False, unique=True)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)

    # Metadata fields (stored as JSON strings)
    # tags: Moved to EntityTagAssociationDb for rich tag support
    extra_metadata = Column(String, nullable=True, default='{}')  # JSON object for links, images, etc.

    # Audit fields
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(String, nullable=False)  # User email/ID
    updated_by = Column(String, nullable=False)  # User email/ID

    # Relationships
    members = relationship("TeamMemberDb", back_populates="team", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self):
        return f"<TeamDb(id='{self.id}', name='{self.name}')>"


class TeamMemberDb(Base):
    """Team member: member_type (user/group), member_identifier, optional app_role_override; links users/groups to teams."""
    __tablename__ = 'team_members'

    # Core Fields
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    team_id = Column(String, ForeignKey('teams.id'), nullable=False)

    # Member identification
    member_type = Column(String, nullable=False)  # user or group
    member_identifier = Column(String, nullable=False)  # email for user, name for group

    # Optional app role override (takes precedence over group-based role)
    app_role_override = Column(String, nullable=True)

    # Audit fields
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    added_by = Column(String, nullable=False)  # User who added this member

    # Relationships
    team = relationship("TeamDb", back_populates="members")

    def __repr__(self):
        return f"<TeamMemberDb(id='{self.id}', team_id='{self.team_id}', member='{self.member_identifier}')>"