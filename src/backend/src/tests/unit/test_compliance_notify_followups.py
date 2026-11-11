"""Compliance NOTIFY follow-ups (#1448 review): owner recipients without approval rules."""

import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

from src.common.compliance_actions import ActionContext, NotifyAction
from src.common.compliance_notifications import ComplianceRunNotifier
from src.db_models.notifications import NotificationDb

RUN_USER = 'steward@example.com'


def _notifier(db, run_user=RUN_USER):
    return ComplianceRunNotifier(
        db, policy_id='pol-1', policy_name='P', run_id='run-1', run_user=run_user,
    )


def _context(notifier, entity_type='data_product', entity_id='p1', name='Orders', **fields):
    return ActionContext(
        entity={'type': entity_type, 'id': entity_id, 'name': name, **fields},
        entity_type=entity_type,
        entity_id=entity_id,
        rule_id='rule-1',
        rule_name='P',
        passed=False,
        notification_manager=notifier,
    )


def _recipients(db):
    return sorted(n.recipient for n in db.query(NotificationDb).all())


def _domain_owners(db, entity_type, entity_id, emails):
    from src.db_models.business_owners import BusinessOwnerDb
    from src.db_models.business_roles import BusinessRoleDb
    from src.db_models.domain_associations import EntityDomainAssociationDb

    domain_id = f'dom-{uuid.uuid4().hex[:6]}'
    role = BusinessRoleDb(id=uuid.uuid4(), name=f'Steward {uuid.uuid4().hex[:4]}')
    db.add(role)
    db.add(EntityDomainAssociationDb(
        domain_id=domain_id, entity_id=entity_id, entity_type=entity_type, is_primary=True,
    ))
    db.flush()
    for email in emails:
        db.add(BusinessOwnerDb(
            id=uuid.uuid4(), object_type='data_domain', object_id=domain_id,
            user_email=email, role_id=role.id, is_active=True,
        ))
    db.flush()


# --- 1. domain_owners / ContractApprover: the owners, no approval rules -----------

class TestOwnerRecipients:
    def test_domain_owners_keep_the_run_user(self, db_session):
        _domain_owners(db_session, 'data_product', 'p1', [RUN_USER, 'other@example.com'])
        notifier = _notifier(db_session)

        assert NotifyAction('domain_owners').execute(_context(notifier)).success is True
        notifier.flush(failed=1, passed=0)

        assert _recipients(db_session) == ['other@example.com', RUN_USER]

    def test_contract_approver_without_owners_fails_without_a_fallback(self, db_session):
        notifier = _notifier(db_session)

        result = NotifyAction('ContractApprover').execute(
            _context(notifier, entity_type='data_contract', entity_id='c1'),
        )

        assert (result.success, result.code) == (False, 'notify_no_recipients')
        assert notifier.flush(failed=1, passed=0) == 0

    def test_domain_owners_without_owners_fails(self, db_session):
        notifier = _notifier(db_session)

        result = NotifyAction('domain_owners').execute(_context(notifier))

        assert (result.success, result.code) == (False, 'notify_no_recipients')
        assert _recipients(db_session) == []


# --- 2. names only of the entities the recipient can read ------------------------

def _product(db, status, draft_owner=None, name=None):
    from src.db_models.data_products import DataProductDb

    product_id = str(uuid.uuid4())
    db.add(DataProductDb(
        id=product_id, name=name or f'{status}-{product_id[:4]}', version='1.0.0',
        status=status, draft_owner_id=draft_owner, version_family_id=product_id,
    ))
    db.flush()
    return product_id


def _failed_names(db, recipient):
    import json

    row = db.query(NotificationDb).filter_by(recipient=recipient).one()
    lines = json.loads(row.data)['i18n']['descriptionLines']
    return row, lines[1]['params']['names']


def _notify_products(db, recipients, products, run_user=RUN_USER):
    notifier = _notifier(db, run_user=run_user)
    for product_id, name in products:
        result = NotifyAction(recipients).execute(
            _context(notifier, entity_id=product_id, name=name),
        )
        assert result.success is True
    notifier.flush(failed=len(products), passed=0)


class TestListedNamesAreReadable:
    def test_a_consumer_sees_published_names_and_a_count_of_the_rest(self, db_session):
        active = _product(db_session, 'active')
        draft = _product(db_session, 'draft')
        personal = _product(db_session, 'draft', draft_owner='someone@example.com')

        _notify_products(db_session, 'consumer@example.com', [
            (active, 'Orders'), (draft, 'Secret draft'), (personal, 'Personal draft'),
        ])

        row, names = _failed_names(db_session, 'consumer@example.com')
        assert names['key'] == 'notifications:complianceRun.namesWithMore'
        assert names['params'] == {'names': 'Orders', 'count': '2'}
        assert 'Secret draft' not in row.description and 'Personal draft' not in row.description
        assert row.link == '/compliance/runs/run-1'

    def test_the_draft_owner_sees_their_draft(self, db_session):
        mine = _product(db_session, 'draft', draft_owner='me@example.com')

        _notify_products(db_session, 'me@example.com', [(mine, 'My draft')])

        _, names = _failed_names(db_session, 'me@example.com')
        assert names == {'text': 'My draft'}

    def test_only_hidden_entities_are_only_counted(self, db_session):
        draft = _product(db_session, 'draft')

        _notify_products(db_session, 'consumer@example.com', [(draft, 'Secret draft')])

        row, names = _failed_names(db_session, 'consumer@example.com')
        assert names['key'] == 'notifications:complianceRunVisibility.notShown'
        assert names['params'] == {'count': '1'}
        assert 'Secret draft' not in row.description

    def test_a_role_recipient_sees_only_what_every_reader_sees(self, db_session):
        from src.db_models.settings import AppRoleDb

        role = AppRoleDb(id=str(uuid.uuid4()), name=f'Readers {uuid.uuid4().hex[:4]}')
        db_session.add(role)
        db_session.flush()
        active = _product(db_session, 'active')
        draft = _product(db_session, 'draft')

        _notify_products(db_session, role.name, [(active, 'Orders'), (draft, 'Secret draft')])

        _, names = _failed_names(db_session, role.name)
        assert names['params'] == {'names': 'Orders', 'count': '1'}

    def test_each_resolved_user_is_checked_on_their_own(self, db_session):
        mine = _product(db_session, 'draft', draft_owner='me@example.com')

        _notify_products(
            db_session, 'me@example.com, consumer@example.com', [(mine, 'My draft')],
        )

        assert _failed_names(db_session, 'me@example.com')[1] == {'text': 'My draft'}
        assert _failed_names(db_session, 'consumer@example.com')[1]['params'] == {'count': '1'}

    def test_contracts_use_the_contract_list_visibility(self, db_session):
        from src.db_models.data_contracts import DataContractDb

        ids = {}
        for status in ('active', 'draft'):
            ids[status] = str(uuid.uuid4())
            db_session.add(DataContractDb(
                id=ids[status], name=status, version='1.0.0', status=status,
                version_family_id=ids[status],
            ))
        db_session.flush()
        notifier = _notifier(db_session)
        for status, name in (('active', 'Orders contract'), ('draft', 'Draft contract')):
            assert NotifyAction('consumer@example.com').execute(
                _context(notifier, entity_type='data_contract', entity_id=ids[status], name=name),
            ).success is True
        notifier.flush(failed=2, passed=0)

        _, names = _failed_names(db_session, 'consumer@example.com')
        assert names['params'] == {'names': 'Orders contract', 'count': '1'}


# --- 3. 'owner' of a Unity Catalog object is its UC owner -------------------------

class TestUnityCatalogOwner:
    def test_owner_of_a_table_is_its_uc_owner(self, db_session):
        notifier = _notifier(db_session)
        context = _context(
            notifier, entity_type='table', entity_id='main.sales.orders', name='orders',
            owner='uc-owner@example.com',
        )

        result = NotifyAction('owner').execute(context)
        notifier.flush(failed=1, passed=0)

        assert result.success is True
        _, names = _failed_names(db_session, 'uc-owner@example.com')
        assert names == {'text': 'orders'}  # the owner can read the table

    def test_another_user_is_not_told_the_table_name(self, db_session):
        notifier = _notifier(db_session)
        context = _context(
            notifier, entity_type='table', entity_id='main.sales.orders', name='orders',
            owner='uc-owner@example.com',
        )

        assert NotifyAction('consumer@example.com').execute(context).success is True
        notifier.flush(failed=1, passed=0)

        assert _failed_names(db_session, 'consumer@example.com')[1]['params'] == {'count': '1'}


# --- 4. recipient keywords ignore case; unknown names fail --------------------------

class TestRecipientTokens:
    def test_keywords_match_without_case(self, db_session):
        from src.db_models.business_owners import BusinessOwnerDb
        from src.db_models.business_roles import BusinessRoleDb

        role = BusinessRoleDb(id=uuid.uuid4(), name='Data Owner')
        db_session.add(role)
        db_session.flush()
        db_session.add(BusinessOwnerDb(
            id=uuid.uuid4(), object_type='data_domain', object_id='dom-1',
            user_email='domain-owner@example.com', role_id=role.id, is_active=True,
        ))
        db_session.flush()
        notifier = _notifier(db_session)
        context = _context(notifier, entity_type='domain', entity_id='dom-1', name='Sales')

        for token in ('Owner', 'Entity_Owner', 'ENTITY OWNER', 'Requester'):
            assert NotifyAction(token).execute(context).success is True, token
        notifier.flush(failed=1, passed=0)

        assert _recipients(db_session) == ['domain-owner@example.com', RUN_USER]

    def test_an_unknown_name_is_a_coded_failure(self, db_session):
        notifier = _notifier(db_session)

        result = NotifyAction('a@example.com, nobody-here').execute(_context(notifier))

        assert (result.success, result.code) == (False, 'notify_unknown_recipient')
        assert result.params == {'recipient': 'nobody-here'}
        assert notifier.flush(failed=1, passed=0) == 0

    def test_a_group_is_written_with_its_prefix(self, db_session):
        notifier = _notifier(db_session)

        assert NotifyAction('group:data-engineers').execute(_context(notifier)).success is True
        notifier.flush(failed=1, passed=0)

        assert _recipients(db_session) == ['data-engineers']

    def test_an_app_role_name_still_resolves(self, db_session):
        from src.db_models.settings import AppRoleDb

        role = AppRoleDb(id=str(uuid.uuid4()), name='Data Readers')
        db_session.add(role)
        db_session.flush()
        notifier = _notifier(db_session)

        assert NotifyAction('data_readers').execute(_context(notifier)).success is True
        notifier.flush(failed=1, passed=0)

        row = db_session.query(NotificationDb).one()
        assert (row.recipient, row.recipient_role_id) == ('Data Readers', role.id)
