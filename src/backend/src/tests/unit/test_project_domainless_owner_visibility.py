"""A project whose owning team has no domain is public, whatever other teams hold.

``get_projects_by_domain_relationship`` (the visibility of ``GET /api/projects``,
``/api/search``, the MCP project tools and the project routes) treats a project
without an owning team, or whose owning team has no domain, as visible to
everyone. That must not depend on whether some other team in the database has
a domain.
"""
import uuid

import pytest

from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.projects import ProjectDb
from src.db_models.teams import TeamDb, TeamMemberDb
from src.repositories.projects_repository import ProjectRepository

ADMIN = "admin@example.com"


def _team(db, name, member=None):
    team = TeamDb(id=str(uuid.uuid4()), name=f"{name}-{uuid.uuid4().hex[:8]}",
                  created_by=ADMIN, updated_by=ADMIN)
    db.add(team)
    db.flush()
    if member:
        db.add(TeamMemberDb(team_id=team.id, member_type="user",
                            member_identifier=member, added_by=ADMIN))
        db.flush()
    return team


def _give_domain(db, team):
    domain = DataDomain(id=str(uuid.uuid4()), name=f"domain-{uuid.uuid4().hex[:8]}",
                        created_by=ADMIN)
    db.add(domain)
    db.flush()
    db.add(EntityDomainAssociationDb(domain_id=domain.id, entity_type="team",
                                     entity_id=team.id, is_primary=True))
    db.flush()


@pytest.mark.parametrize("other_team_has_domain", [False, True])
@pytest.mark.parametrize("caller_in_a_team", [False, True])
def test_project_of_a_domainless_team_is_visible(db_session, other_team_has_domain,
                                                 caller_in_a_team):
    caller = "caller@example.com"
    owner = _team(db_session, "owner")
    if caller_in_a_team:
        _team(db_session, "callers-team", member=caller)
    if other_team_has_domain:
        _give_domain(db_session, _team(db_session, "governed"))
    project = ProjectDb(id=str(uuid.uuid4()), name=f"open-{uuid.uuid4().hex[:8]}",
                        project_type="TEAM", owner_team_id=owner.id,
                        created_by=ADMIN, updated_by=ADMIN)
    db_session.add(project)
    db_session.flush()
    teams_with_domain = db_session.query(EntityDomainAssociationDb).filter(
        EntityDomainAssociationDb.entity_type == "team").count()
    assert (teams_with_domain > 0) == other_team_has_domain

    visible = ProjectRepository().get_projects_by_domain_relationship(
        db_session, caller, [])
    assert project.id in {p.id for p in visible}


def test_project_of_a_team_with_a_domain_stays_hidden(db_session):
    owner = _team(db_session, "owner")
    _give_domain(db_session, owner)
    project = ProjectDb(id=str(uuid.uuid4()), name=f"secret-{uuid.uuid4().hex[:8]}",
                        project_type="TEAM", owner_team_id=owner.id,
                        created_by=ADMIN, updated_by=ADMIN)
    db_session.add(project)
    db_session.flush()

    visible = ProjectRepository().get_projects_by_domain_relationship(
        db_session, "caller@example.com", [])
    assert project.id not in {p.id for p in visible}
