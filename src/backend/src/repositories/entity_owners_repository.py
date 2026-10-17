"""Who owns a data product or data contract, as notification recipients."""
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)

_ENTITY_KINDS = {
    'data_product': 'data_product', 'dataproduct': 'data_product',
    'data_contract': 'data_contract', 'datacontract': 'data_contract',
    # Assets' Business Owners are stored as object_type='asset'.
    'dataset': 'asset', 'asset': 'asset',
}
# ODPS / ODCS team roles that mean "owner" (compared lowercased).
_OWNER_TEAM_ROLES = (
    'owner', 'product owner', 'product_owner', 'productowner', 'data owner', 'data_owner',
)
# Business roles merged into the team as "owner" (see
# DataProductsManager.BUSINESS_ROLE_TO_TEAM_ROLE).
_OWNER_BUSINESS_ROLES = ('owner', 'data owner')


def _as_date(value):
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return value


def _still_member(date_in, date_out, replaced_by) -> bool:
    """A team member holds the role from ``date_in`` through ``date_out``."""
    date_in, date_out = _as_date(date_in), _as_date(date_out)
    if date_in and date_in > date.today():
        return False
    if date_out:
        return date_out >= date.today()
    return not replaced_by


def resolve_owner_emails(db: Session, entity_type: str, entity_id: str) -> list[str]:
    """Emails (or usernames) of the users who own an entity.

    Owners, in this order and without exact duplicates: for data
    products and contracts, the user members of the owner team
    (``owner_team_id``) and the current members of the ODPS / ODCS team whose
    role is ``owner``; for any entity type, its active Business Owners holding
    the "Data Owner" role. Group members are skipped: notifications are shown
    to a user by email, username or app role, never by group.

    Read-only: nothing is flushed, and database errors propagate to the
    caller (workflow steps and the agreement deliver step handle them).
    """
    from src.db_models.business_owners import BusinessOwnerDb
    from src.db_models.business_roles import BusinessRoleDb
    from src.db_models.data_contracts import DataContractDb, DataContractTeamDb
    from src.db_models.data_products import (
        DataProductDb,
        DataProductTeamDb,
        DataProductTeamMemberDb,
    )
    from src.db_models.teams import TeamMemberDb

    raw_type = (entity_type or '').strip().lower()
    kind = _ENTITY_KINDS.get(raw_type.replace(' ', ''), raw_type)

    owner_team_id, team, inline = None, [], []
    if kind in ('data_product', 'data_contract'):
        model = DataProductDb if kind == 'data_product' else DataContractDb
        owner_team_id = db.query(model.owner_team_id).filter(model.id == entity_id).scalar()
        if owner_team_id:
            team = (
                db.query(TeamMemberDb.member_type, TeamMemberDb.member_identifier)
                .filter(TeamMemberDb.team_id == owner_team_id)
                .all()
            )
        if kind == 'data_product':
            member = DataProductTeamMemberDb
            inline_query = (
                db.query(member.username, member.date_in, member.date_out,
                         member.replaced_by_username)
                .join(DataProductTeamDb, DataProductTeamDb.id == member.team_id)
                .filter(DataProductTeamDb.product_id == entity_id)
            )
        else:
            member = DataContractTeamDb
            inline_query = (
                db.query(member.username, member.date_in, member.date_out,
                         member.replaced_by_username)
                .filter(member.contract_id == entity_id)
            )
        inline = inline_query.filter(func.lower(member.role).in_(_OWNER_TEAM_ROLES)).all()

    # Business Owners count when their role is an owner role (every Business
    # Owner has a role: role_id is required and a foreign key)
    business = (
        db.query(BusinessOwnerDb.user_email)
        .join(BusinessRoleDb, BusinessRoleDb.id == BusinessOwnerDb.role_id)
        .filter(BusinessOwnerDb.object_type == kind)
        .filter(BusinessOwnerDb.object_id == entity_id)
        .filter(BusinessOwnerDb.is_active.is_(True))
        .filter(func.lower(BusinessRoleDb.name).in_(_OWNER_BUSINESS_ROLES))
        .all()
    )

    candidates = (
        [identifier for member_type, identifier in team if member_type == 'user']
        + [row.username for row in inline
           if _still_member(row.date_in, row.date_out, row.replaced_by_username)]
        + [row.user_email for row in business]
    )
    # Exact dedup only: notifications match recipients case-sensitively, so
    # dropping a differently-cased spelling could drop the one that matches.
    emails = list(dict.fromkeys(identifier for identifier in candidates if identifier))

    if not emails and kind in ('data_product', 'data_contract', 'asset'):
        groups = [identifier for member_type, identifier in team if member_type == 'group']
        logger.warning(
            "No owner users for %s %s (owner team: %s; group members not notified: %s)",
            kind, entity_id, owner_team_id or 'none', ', '.join(groups) or 'none',
        )
    return emails


def resolve_domain_owner_emails(db: Session, entity_type: str, entity_id: str) -> list[str]:
    """Emails of the owners of an entity's domain.

    The domain is the entity's primary domain, or all its domains when none
    is primary. Its owners are all the domain's active Business Owners: the
    domain page lists them under "Owners", whatever their business role.
    Read-only, like ``resolve_owner_emails``.
    """
    from src.db_models.business_owners import BusinessOwnerDb
    from src.db_models.domain_associations import EntityDomainAssociationDb

    raw_type = (entity_type or '').strip().lower()
    kind = _ENTITY_KINDS.get(raw_type.replace(' ', ''), raw_type)

    links = (
        db.query(EntityDomainAssociationDb.domain_id, EntityDomainAssociationDb.is_primary)
        .filter(EntityDomainAssociationDb.entity_type == kind)
        .filter(EntityDomainAssociationDb.entity_id == entity_id)
        .all()
    )
    domain_ids = [link.domain_id for link in links if link.is_primary] or [
        link.domain_id for link in links
    ]
    if not domain_ids:
        logger.warning("No domain assigned to %s %s", kind, entity_id)
        return []

    rows = (
        db.query(BusinessOwnerDb.user_email)
        .filter(BusinessOwnerDb.object_type == 'data_domain')
        .filter(BusinessOwnerDb.object_id.in_(domain_ids))
        .filter(BusinessOwnerDb.is_active.is_(True))
        .order_by(BusinessOwnerDb.assigned_at)
        .all()
    )
    emails = list(dict.fromkeys(row.user_email for row in rows if row.user_email))
    if not emails:
        logger.warning("No owners for the domain(s) of %s %s: %s",
                       kind, entity_id, ', '.join(domain_ids))
    return emails
