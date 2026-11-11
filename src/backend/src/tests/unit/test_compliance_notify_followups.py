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
