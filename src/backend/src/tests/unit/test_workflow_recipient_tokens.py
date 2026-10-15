"""Recipient tokens used by the default workflows resolve to real people."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace

from src.common.workflow_executor import _resolve_role_to_users
from src.controller.agreement_wizard_manager import AgreementWizardManager
from src.db_models.data_contracts import DataContractDb, DataContractTeamDb
from src.db_models.data_products import DataProductDb, DataProductTeamDb, DataProductTeamMemberDb
from src.db_models.settings import AppRoleDb
from src.db_models.teams import TeamDb, TeamMemberDb
from src.repositories.entity_owners_repository import resolve_owner_emails


def _context(entity_type='data_product', entity_id='x', user_email='requester@example.com',
             entity=None):
    return SimpleNamespace(
        user_email=user_email, entity=entity or {}, entity_type=entity_type,
        entity_id=entity_id, entity_name='E',
    )


def _team(db, members):
    team = TeamDb(id=str(uuid.uuid4()), name=f'team-{uuid.uuid4().hex[:6]}',
                  created_by='admin', updated_by='admin')
    db.add(team)
    db.flush()
    for member_type, identifier in members:
        db.add(TeamMemberDb(
            id=str(uuid.uuid4()), team_id=team.id,
            member_type=member_type, member_identifier=identifier, added_by='admin',
        ))
    db.flush()
    return team


def _product(db, owner_team_id=None, odps_members=()):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name='p', version='1.0.0', owner_team_id=owner_team_id,
    )
    db.add(product)
    db.flush()
    if odps_members:
        odps_team = DataProductTeamDb(id=str(uuid.uuid4()), product_id=product.id)
        db.add(odps_team)
        db.flush()
        for username, role in odps_members:
            db.add(DataProductTeamMemberDb(
                id=str(uuid.uuid4()), team_id=odps_team.id, username=username, role=role,
            ))
        db.flush()
    return product


def _contract(db, owner_team_id=None, odcs_members=()):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='approved',
        version_family_id=str(uuid.uuid4()), owner_team_id=owner_team_id,
    )
    db.add(contract)
    db.flush()
    for username, role in odcs_members:
        db.add(DataContractTeamDb(
            id=str(uuid.uuid4()), contract_id=contract.id, username=username, role=role,
        ))
    db.flush()
    return contract


def test_trigger_user_is_the_requester(db_session):
    assert _resolve_role_to_users(db_session, 'trigger_user', _context()) == [
        ('requester@example.com', None),
    ]


def test_entity_owner_is_owner_team_users_plus_odps_owners(db_session):
    team = _team(db_session, [('user', 'owner1@example.com'), ('group', 'owners')])
    product = _product(db_session, owner_team_id=team.id, odps_members=[
        ('odps.owner@example.com', 'owner'), ('contributor@example.com', 'contributor'),
        ('owner1@example.com', 'owner'),
    ])

    resolved = _resolve_role_to_users(db_session, 'entity_owner', _context(entity_id=product.id))

    assert resolved == [('owner1@example.com', None), ('odps.owner@example.com', None)]


def test_entity_owner_of_a_data_contract(db_session):
    team = _team(db_session, [('user', 'team.owner@example.com')])
    contract = _contract(db_session, owner_team_id=team.id,
                         odcs_members=[('odcs.owner@example.com', 'owner')])

    resolved = _resolve_role_to_users(
        db_session, 'entity_owner', _context(entity_type='data_contract', entity_id=contract.id)
    )

    assert resolved == [('team.owner@example.com', None), ('odcs.owner@example.com', None)]


def test_entity_owner_uses_the_odps_team_without_owner_team(db_session):
    product = _product(db_session, odps_members=[('alice@example.com', 'owner')])

    resolved = _resolve_role_to_users(db_session, 'entity_owner', _context(entity_id=product.id))

    assert resolved == [('alice@example.com', None)]


def test_entity_owner_includes_a_requester_who_is_an_owner(db_session):
    # Same meaning as the agreement deliver step: the owners, whoever asked.
    team = _team(db_session, [('user', 'requester@example.com')])
    product = _product(db_session, owner_team_id=team.id)

    resolved = _resolve_role_to_users(db_session, 'entity_owner', _context(entity_id=product.id))

    assert resolved == [('requester@example.com', None)]


def test_group_only_owner_team_resolves_to_nobody_with_a_warning(db_session, caplog):
    team = _team(db_session, [('group', 'data-eng-owners')])
    product = _product(db_session, owner_team_id=team.id)

    with caplog.at_level('WARNING', logger='src.repositories.entity_owners_repository'):
        resolved = _resolve_role_to_users(
            db_session, 'entity_owner', _context(entity_id=product.id)
        )

    assert resolved == []
    assert any('group members not notified: data-eng-owners' in r.getMessage()
               for r in caplog.records)


def test_entity_owner_follows_access_grants_to_the_product(db_session):
    team = _team(db_session, [('user', 'owner@example.com')])
    product = _product(db_session, owner_team_id=team.id)
    context = _context(entity_type='access_grant', entity_id='grant-1',
                       entity={'entity_type': 'data_product', 'entity_id': product.id})

    assert _resolve_role_to_users(db_session, 'entity_owner', context) == [
        ('owner@example.com', None),
    ]


def test_entity_owner_for_other_entity_types_resolves_to_nobody(db_session):
    context = _context(entity_type='project', entity_id='proj-1')

    assert _resolve_role_to_users(db_session, 'entity_owner', context) == []


def test_tokens_work_inside_a_comma_separated_list(db_session):
    team = _team(db_session, [('user', 'owner@example.com')])
    product = _product(db_session, owner_team_id=team.id)

    resolved = _resolve_role_to_users(
        db_session, 'trigger_user,entity_owner', _context(entity_id=product.id)
    )

    assert resolved == [('requester@example.com', None), ('owner@example.com', None)]


def test_data_steward_singular_resolves_to_the_role(db_session):
    role = AppRoleDb(id=str(uuid.uuid4()), name='Data Steward', assigned_groups='["data-stewards"]')
    db_session.add(role)
    db_session.flush()

    assert _resolve_role_to_users(db_session, 'data_steward', _context()) == [
        ('Data Steward', role.id),
    ]


def test_agreement_deliver_uses_the_same_owners(db_session):
    team = _team(db_session, [('user', 'owner@example.com')])
    product = _product(db_session, owner_team_id=team.id)
    manager = AgreementWizardManager(db=db_session, storage_base_path=None)

    assert manager._resolve_entity_owners('data_product', product.id) == ['owner@example.com']
    assert resolve_owner_emails(db_session, 'asset', 'a-1') == []


def _business_owner(db, product, email, role_name, object_type='data_product', object_id=None):
    from src.db_models.business_owners import BusinessOwnerDb
    from src.db_models.business_roles import BusinessRoleDb

    role = db.query(BusinessRoleDb).filter(BusinessRoleDb.name == role_name).first()
    if not role:
        role = BusinessRoleDb(id=uuid.uuid4(), name=role_name)
        db.add(role)
        db.flush()
    db.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type=object_type, object_id=object_id or product.id,
        user_email=email, role_id=role.id, is_active=True,
    ))
    db.flush()


def test_entity_owner_includes_business_data_owners_only(db_session):
    product = _product(db_session)
    _business_owner(db_session, product, 'data.owner@example.com', 'Data Owner')
    _business_owner(db_session, product, 'cro@example.com', 'Chief Risk Officer')

    assert resolve_owner_emails(db_session, 'data_product', product.id) == [
        'data.owner@example.com',
    ]


def test_owner_role_matching_is_case_insensitive(db_session):
    product = _product(db_session, odps_members=[
        ('a@example.com', 'Owner'), ('b@example.com', 'product_owner'),
        ('c@example.com', 'Data Owner'),
    ])

    assert resolve_owner_emails(db_session, 'data_product', product.id) == [
        'a@example.com', 'b@example.com', 'c@example.com',
    ]


def test_former_team_owners_are_not_notified(db_session):
    contract = _contract(db_session, odcs_members=[('current@example.com', 'owner')])
    db_session.add_all([
        DataContractTeamDb(id=str(uuid.uuid4()), contract_id=contract.id, role='owner',
                           username='left@example.com', date_out='2020-01-01'),
        DataContractTeamDb(id=str(uuid.uuid4()), contract_id=contract.id, role='owner',
                           username='replaced@example.com',
                           replaced_by_username='current@example.com'),
    ])
    db_session.flush()

    assert resolve_owner_emails(db_session, 'data_contract', contract.id) == ['current@example.com']


def test_entity_type_spellings_are_normalized(db_session):
    team = _team(db_session, [('user', 'owner@example.com')])
    product = _product(db_session, owner_team_id=team.id)

    for spelling in ('dataproduct', ' data_product ', 'DataProduct'):
        assert resolve_owner_emails(db_session, spelling, product.id) == ['owner@example.com']


def test_differently_cased_spellings_are_all_kept(db_session):
    # Notifications match recipients case-sensitively; keep every spelling.
    team = _team(db_session, [('user', 'Owner@Example.com')])
    product = _product(db_session, owner_team_id=team.id,
                       odps_members=[('owner@example.com', 'owner')])

    assert resolve_owner_emails(db_session, 'data_product', product.id) == [
        'Owner@Example.com', 'owner@example.com',
    ]


def test_business_data_owners_of_assets_also_answer_for_datasets(db_session):
    # The asset page stores Business Owners as object_type='asset'.
    _business_owner(db_session, None, 'asset.owner@example.com', 'Data Owner',
                    object_type='asset', object_id='a-1')

    assert resolve_owner_emails(db_session, 'asset', 'a-1') == ['asset.owner@example.com']
    assert resolve_owner_emails(db_session, 'dataset', 'a-1') == ['asset.owner@example.com']


def test_team_members_hold_the_role_through_their_date_out(db_session):
    from datetime import date, timedelta

    today, later = date.today().isoformat(), (date.today() + timedelta(days=30)).isoformat()
    contract = _contract(db_session)
    db_session.add_all([
        DataContractTeamDb(id=str(uuid.uuid4()), contract_id=contract.id, role='owner',
                           username='leaves.today@example.com', date_out=today),
        DataContractTeamDb(id=str(uuid.uuid4()), contract_id=contract.id, role='owner',
                           username='handover.planned@example.com', date_out=later,
                           replaced_by_username='next@example.com'),
    ])
    db_session.flush()

    assert resolve_owner_emails(db_session, 'data_contract', contract.id) == [
        'leaves.today@example.com', 'handover.planned@example.com',
    ]


def test_agreement_owner_lookup_is_best_effort(db_session, monkeypatch):
    import src.repositories.entity_owners_repository as owners

    def boom(*args, **kwargs):
        raise RuntimeError('lookup failed')

    monkeypatch.setattr(owners, 'resolve_owner_emails', boom)
    manager = AgreementWizardManager(db=db_session, storage_base_path=None)

    assert manager._resolve_entity_owners('data_product', 'p-1') == []


def test_owner_token_uses_the_payload_owner_when_present(db_session):
    context = _context(entity={'owner': 'payload.owner@example.com'})

    assert _resolve_role_to_users(db_session, 'owner', context) == [
        ('payload.owner@example.com', None),
    ]


def test_owner_token_falls_back_to_the_entity_owners(db_session):
    # on_publish / on_unpublish payloads carry only name and status.
    team = _team(db_session, [('user', 'owner@example.com')])
    product = _product(db_session, owner_team_id=team.id)
    context = _context(entity_id=product.id, entity={'name': 'p', 'status': 'active'})

    assert _resolve_role_to_users(db_session, 'owner', context) == [('owner@example.com', None)]


def test_product_owner_with_a_space_is_an_owner(db_session):
    product = _product(db_session, odps_members=[('po@example.com', 'Product Owner')])

    assert resolve_owner_emails(db_session, 'data_product', product.id) == ['po@example.com']


def test_members_whose_start_date_is_in_the_future_are_not_owners_yet(db_session):
    from datetime import date, timedelta

    contract = _contract(db_session, odcs_members=[('now@example.com', 'owner')])
    db_session.add(DataContractTeamDb(
        id=str(uuid.uuid4()), contract_id=contract.id, role='owner', username='soon@example.com',
        date_in=(date.today() + timedelta(days=30)).isoformat(),
    ))
    db_session.flush()

    assert resolve_owner_emails(db_session, 'data_contract', contract.id) == ['now@example.com']


def test_access_grant_traversal_ignores_case_and_needs_type_and_id(db_session):
    team = _team(db_session, [('user', 'owner@example.com')])
    product = _product(db_session, owner_team_id=team.id)
    upper = _context(entity_type='ACCESS_GRANT', entity_id='grant-1',
                     entity={'entity_type': 'data_product', 'entity_id': product.id})
    no_type = _context(entity_type='access_grant', entity_id='grant-1',
                       entity={'entity_id': product.id})

    assert _resolve_role_to_users(db_session, 'entity_owner', upper) == [
        ('owner@example.com', None),
    ]
    assert _resolve_role_to_users(db_session, 'entity_owner', no_type) == []


def test_no_warning_for_entity_types_without_owners(db_session, caplog):
    with caplog.at_level('WARNING', logger='src.repositories.entity_owners_repository'):
        assert resolve_owner_emails(db_session, 'project', 'proj-1') == []

    assert not any('No owner users' in r.getMessage() for r in caplog.records)


def test_business_owner_with_a_dangling_role_is_not_an_owner(db_session):
    # role_id is a required foreign key, so this can't happen on Postgres;
    # without the role there is no owner role to match.
    from src.db_models.business_owners import BusinessOwnerDb

    product = _product(db_session)
    db_session.add(BusinessOwnerDb(
        id=uuid.uuid4(), object_type='data_product', object_id=product.id,
        user_email='dangling@example.com', role_id=uuid.uuid4(), is_active=True,
    ))
    db_session.flush()

    assert resolve_owner_emails(db_session, 'data_product', product.id) == []
