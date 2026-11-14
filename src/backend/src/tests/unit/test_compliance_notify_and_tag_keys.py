"""Compliance DSL: NOTIFY sends in-app notifications (#1425); tag actions take namespaced
and key-only keys (#1423)."""

import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.common.compliance_actions import ActionContext, AssignTagAction, NotifyAction, RemoveTagAction
from src.common.compliance_dsl import parse_rule
from src.common.compliance_notifications import ComplianceRunNotifier
from src.common.notification_audience import NotifyAudience
from src.controller.compliance_manager import ComplianceManager, TagsManagerTagAdapter
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.settings import AppRoleDb
from src.db_models.notifications import NotificationDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.repositories.tags_repository import entity_tag_repo, tag_namespace_repo


# --- Parser ---------------------------------------------------------------

def _actions(rule_tail: str):
    return parse_rule(f"MATCH (obj:Object)\nASSERT obj.status = 'active'\nON_FAIL {rule_tail}")['on_fail_actions']


class TestTagActionGrammar:
    def test_bare_identifier_with_value_still_parses(self):
        assert _actions("ASSIGN_TAG reviewed: 'yes'") == [{'type': 'ASSIGN_TAG', 'key': 'reviewed', 'value': 'yes'}]

    def test_quoted_namespaced_key_with_value(self):
        assert _actions("ASSIGN_TAG 'governance/classification': 'confidential'") == [
            {'type': 'ASSIGN_TAG', 'key': 'governance/classification', 'value': 'confidential'}
        ]

    @pytest.mark.parametrize('tail', ["ASSIGN_TAG 'pii'", "ASSIGN_TAG pii"])
    def test_key_only_assign(self, tail):
        assert _actions(tail) == [{'type': 'ASSIGN_TAG', 'key': 'pii', 'value': None}]

    def test_empty_value_clears(self):
        assert _actions("ASSIGN_TAG 'governance/classification': ''") == [
            {'type': 'ASSIGN_TAG', 'key': 'governance/classification', 'value': ''}
        ]

    @pytest.mark.parametrize('tail, key', [
        ("REMOVE_TAG 'governance/classification'", 'governance/classification'),
        ("REMOVE_TAG pii", 'pii'),
    ])
    def test_remove_tag_keys(self, tail, key):
        assert _actions(tail) == [{'type': 'REMOVE_TAG', 'key': key}]

    def test_key_only_assign_is_followed_by_more_actions(self):
        assert _actions("ASSIGN_TAG 'pii' NOTIFY 'owner@example.com' FAIL 'Untagged'") == [
            {'type': 'ASSIGN_TAG', 'key': 'pii', 'value': None},
            {'type': 'NOTIFY', 'recipients': 'owner@example.com'},
            {'type': 'FAIL', 'message': 'Untagged'},
        ]


# --- Tag adapter ------------------------------------------------------------

@pytest.fixture
def namespaced_tag(db_session):
    namespace = TagNamespaceDb(name=f'gov{uuid.uuid4().hex[:6]}', created_by='t')
    db_session.add(namespace)
    db_session.flush()
    tag = TagDb(
        name='classification', namespace_id=namespace.id, status='active',
        possible_values=['public', 'internal', 'confidential'],
    )
    db_session.add(tag)
    db_session.flush()
    return tag, f'{namespace.name}/classification'


@pytest.fixture
def default_tag(db_session):
    namespace = tag_namespace_repo.get_or_create_default_namespace(db_session, user_email='admin@example.com')
    tag = TagDb(name=f'pii_{uuid.uuid4().hex[:6]}', namespace_id=namespace.id, status='active')
    db_session.add(tag)
    db_session.flush()
    return tag


def _context(tag_manager=None, notification_manager=None, entity_id='prod-1', passed=False, name='Orders'):
    return ActionContext(
        entity={'type': 'data_product', 'id': entity_id, 'name': name},
        entity_type='data_product',
        entity_id=entity_id,
        rule_id='rule-1',
        rule_name='Classified products',
        passed=passed,
        tag_manager=tag_manager,
        notification_manager=notification_manager,
    )


def _assoc(db, entity_id='prod-1'):
    return db.query(EntityTagAssociationDb).filter_by(entity_type='data_product', entity_id=entity_id).all()


class TestTagKeys:
    def test_namespaced_key_resolves_by_fqn(self, db_session, namespaced_tag):
        tag, fqn = namespaced_tag
        result = AssignTagAction(fqn, 'confidential').execute(_context(TagsManagerTagAdapter(db_session)))

        assert result.success is True
        [assoc] = _assoc(db_session)
        assert (assoc.tag_id, assoc.assigned_value) == (tag.id, 'confidential')

    def test_value_outside_possible_values_is_a_coded_failure(self, db_session, namespaced_tag):
        _, fqn = namespaced_tag
        result = AssignTagAction(fqn, 'secret').execute(_context(TagsManagerTagAdapter(db_session)))

        assert result.success is False
        assert result.code == 'tag_value_not_allowed'
        assert result.params == {'tag': fqn, 'value': 'secret', 'allowed': 'public, internal, confidential'}
        assert _assoc(db_session) == []

    def test_unknown_tag_is_a_coded_failure(self, db_session):
        result = AssignTagAction('nope/missing', 'x').execute(_context(TagsManagerTagAdapter(db_session)))

        assert result.success is False
        assert result.code == 'tag_not_found'
        assert result.params == {'tag': 'nope/missing'}

    def test_key_only_assigns_without_a_value(self, db_session, default_tag):
        result = AssignTagAction(default_tag.name, None).execute(_context(TagsManagerTagAdapter(db_session)))

        assert result.success is True
        [assoc] = _assoc(db_session)
        assert assoc.assigned_value is None

    def test_key_only_keeps_an_existing_value(self, db_session, namespaced_tag):
        tag, fqn = namespaced_tag
        entity_tag_repo.add_tag_to_entity(
            db_session, entity_id='prod-1', entity_type='data_product', tag_id=tag.id,
            assigned_value='internal', assigned_by='someone-else@example.com',
        )
        db_session.flush()

        result = AssignTagAction(fqn, None).execute(
            _context(TagsManagerTagAdapter(db_session, user_email='steward@example.com'))
        )

        assert result.success is True
        [assoc] = _assoc(db_session)
        assert (assoc.assigned_value, assoc.assigned_by) == ('internal', 'someone-else@example.com')

    def test_empty_value_clears_an_existing_value(self, db_session, namespaced_tag):
        tag, fqn = namespaced_tag
        entity_tag_repo.add_tag_to_entity(
            db_session, entity_id='prod-1', entity_type='data_product', tag_id=tag.id, assigned_value='internal',
        )
        db_session.flush()

        assert AssignTagAction(fqn, '').execute(_context(TagsManagerTagAdapter(db_session))).success is True
        [assoc] = _assoc(db_session)
        assert assoc.assigned_value is None  # '' clears; stored as no value (#1434)

    def test_remove_namespaced_tag(self, db_session, namespaced_tag):
        tag, fqn = namespaced_tag
        entity_tag_repo.add_tag_to_entity(db_session, entity_id='prod-1', entity_type='data_product', tag_id=tag.id)
        db_session.flush()

        assert RemoveTagAction(fqn).execute(_context(TagsManagerTagAdapter(db_session))).success is True
        assert _assoc(db_session) == []

    def test_unsupported_entity_type_is_a_coded_failure(self, db_session, default_tag):
        context = _context(TagsManagerTagAdapter(db_session))
        context.entity_type = 'table'

        result = AssignTagAction(default_tag.name, 'x').execute(context)

        assert result.code == 'tag_entity_type_unsupported'
        assert result.params['entityType'] == 'table'


# --- NOTIFY -----------------------------------------------------------------

@pytest.fixture
def readable():
    """The recipients can read every entity (read checks: test_compliance_notify_followups)."""
    with patch('src.common.compliance_notifications._ReadChecks.can_read', return_value=True):
        yield

class TestNotifyAction:
    def test_without_a_notifier_is_a_coded_failure(self):
        result = NotifyAction('a@example.com').execute(_context())

        assert (result.success, result.code) == (False, 'notification_manager_unavailable')

    def test_notifier_collects_one_notification_per_recipient_per_run(self, db_session, readable):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='Classified products', run_id='run-1', audience=ADMIN_AUDIENCE)

        for i in range(25):
            result = NotifyAction('a@example.com, b@example.com').execute(
                _context(notification_manager=notifier, entity_id=f'p{i}', name=f'Product {i}')
            )
            assert result.success is True
        NotifyAction('a@example.com').execute(_context(notification_manager=notifier, entity_id='ok', passed=True))

        assert db_session.query(NotificationDb).count() == 0  # nothing until the run ends
        assert notifier.flush(failed=25, passed=1) == 2

        rows = {n.recipient: n for n in db_session.query(NotificationDb).all()}
        assert set(rows) == {'a@example.com', 'b@example.com'}
        a = rows['a@example.com']
        assert a.link == '/compliance/runs/run-1'
        i18n = json.loads(a.data)['i18n']
        assert i18n['title'] == 'notifications:complianceRun.title'
        assert i18n['params'] == {'policyName': 'Classified products', 'failedCount': '25', 'passedCount': '1'}
        summary, failed_line, passed_line = i18n['descriptionLines']
        assert summary['key'] == 'notifications:complianceRun.summary'
        assert summary['params']['failedCount'] == '25'
        # The failed line names a bounded number of entities, then counts the rest
        names = failed_line['params']['names']
        assert names['key'] == 'notifications:complianceRun.namesWithMore'
        assert names['params']['count'] == '15'
        assert 'Product 9' in names['params']['names'] and 'Product 10' not in names['params']['names']
        assert passed_line['params']['names'] == {'text': 'Orders'}
        # The English text is the fallback for clients that don't translate
        assert 'Product 9' in a.description and 'Product 10' not in a.description and '15 more' in a.description

    def test_flush_twice_does_not_send_again(self, db_session):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)
        NotifyAction('a@example.com').execute(_context(notification_manager=notifier))

        assert notifier.flush(failed=1, passed=0) == 1
        assert notifier.flush(failed=1, passed=0) == 0

    def test_an_entity_reached_by_several_notify_actions_is_listed_once(self, db_session, readable):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)
        context = _context(notification_manager=notifier)

        NotifyAction('a@example.com').execute(context)
        NotifyAction('a@example.com, a@example.com').execute(context)
        notifier.flush(failed=1, passed=0)

        [row] = db_session.query(NotificationDb).all()
        failed_line = json.loads(row.data)['i18n']['descriptionLines'][1]
        assert failed_line['params']['names'] == {'text': 'Orders'}

    def test_counts_are_the_run_totals(self, db_session):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)
        NotifyAction('a@example.com').execute(_context(notification_manager=notifier))

        notifier.flush(failed=5, passed=900)

        params = json.loads(db_session.query(NotificationDb).one().data)['i18n']['params']
        assert (params['failedCount'], params['passedCount']) == ('5', '900')

    def test_entity_owner_of_a_domain_is_notified(self, db_session):
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
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)
        context = _context(notification_manager=notifier, entity_id='dom-1', name='Sales')
        context.entity_type = 'domain'
        # 'owner' is the owner team's id in a compliance entity; it must not become the recipient
        context.entity = {'type': 'domain', 'id': 'dom-1', 'name': 'Sales', 'owner': 'team-uuid-1'}

        assert NotifyAction('entity_owner').execute(context).success is True
        assert NotifyAction('owner').execute(context).success is True
        notifier.flush(failed=1, passed=0)

        assert [n.recipient for n in db_session.query(NotificationDb).all()] == ['domain-owner@example.com']

    def test_requester_is_the_user_who_started_the_run(self, db_session):
        notifier = ComplianceRunNotifier(
            db_session, policy_id='pol-1', policy_name='P', run_id='run-1', run_user='steward@example.com',
            audience=ADMIN_AUDIENCE,
        )
        NotifyAction('requester').execute(_context(notification_manager=notifier))
        notifier.flush(failed=1, passed=0)

        assert db_session.query(NotificationDb).one().recipient == 'steward@example.com'

    def test_entity_independent_recipients_are_resolved_once(self, db_session):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)
        found = [('Readers', 'role-1')]  # an app role; emails don't need the resolver
        resolver = 'src.common.workflow_executor._resolve_role_to_users'
        with patch(resolver, return_value=found) as resolve:
            for i in range(5):
                context = _context(notification_manager=notifier, entity_id=f'p{i}')
                NotifyAction('Readers').execute(context)

        assert resolve.call_count == 1

    def test_recipients_that_resolve_to_nobody_fail_the_action(self, db_session):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)

        result = NotifyAction('entity_owner').execute(_context(notification_manager=notifier))

        assert (result.success, result.code) == (False, 'notify_no_recipients')


# --- Runs -------------------------------------------------------------------

# The notifier's audience: an admin may notify any target (#1450); the author is an admin
ADMIN_AUDIENCE = NotifyAudience(email=None, is_admin=True, role_ids=frozenset())


def _run(db, rule, entities, current_user='steward@example.com'):
    # Policies run with their author's audience; this one is authored by an admin
    group = f'old-admins-{uuid.uuid4().hex[:8]}'
    # Admin is the compliance feature level (not the is_admin flag): the author holds compliance ADMIN
    db.add(AppRoleDb(name=f'Old Admin {group}', assigned_groups=json.dumps([group]),
                     feature_permissions=json.dumps({'compliance': 'Admin'})))
    db.flush()
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Classified products', rule=rule, is_active=True,
        rule_author_email='admin@example.com', rule_author_groups=json.dumps([group]),
    )
    db.add(policy)
    db.flush()
    iterator = MagicMock()
    iterator.iterate.return_value = iter(entities)
    with (
        patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator),
        patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()),
    ):
        return ComplianceManager().run_policy_inline(db, policy=policy, current_user=current_user)


PRODUCTS = [
    {'type': 'data_product', 'id': 'p1', 'name': 'Orders', 'status': 'draft'},
    {'type': 'data_product', 'id': 'p2', 'name': 'Invoices', 'status': 'draft'},
    {'type': 'data_product', 'id': 'p3', 'name': 'Customers', 'status': 'active'},
]


class TestRuns:
    def test_run_notifies_each_recipient_once_and_records_action_outcomes(self, db_session, namespaced_tag):
        _, fqn = namespaced_tag
        run = _run(db_session, (
            "MATCH (p:data_product)\nASSERT p.status = 'active'\n"
            f"ON_FAIL NOTIFY 'owner@example.com' ASSIGN_TAG '{fqn}': 'secret'"
        ), PRODUCTS)

        assert run.status == 'succeeded'
        [notification] = db_session.query(NotificationDb).filter_by(recipient='owner@example.com').all()
        assert json.loads(notification.data)['i18n']['params']['failedCount'] == '2'

        results = {r.object_id: r for r in db_session.query(ComplianceResultDb).filter_by(run_id=run.id)}
        actions = json.loads(results['p1'].details_json)['actions']
        assert actions[0] == {'type': 'NOTIFY', 'success': True, 'target': 'owner@example.com'}
        assert actions[1]['type'] == 'ASSIGN_TAG'
        assert actions[1]['success'] is False
        assert actions[1]['code'] == 'tag_value_not_allowed'
        assert actions[1]['target'] == fqn
        # A passing entity without actions keeps details_json empty
        assert results['p3'].details_json is None

    def test_notification_failure_does_not_fail_the_run_but_warns(self, db_session):
        with patch.object(ComplianceRunNotifier, 'flush', side_effect=RuntimeError('db down')):
            run = _run(db_session, "MATCH (p:data_product)\nASSERT p.status = 'active'\nON_FAIL NOTIFY 'a@example.com'", PRODUCTS)

        assert run.status == 'succeeded'
        assert run.failure_count == 2
        assert run.warning_code == 'notifications_failed'

    def test_a_run_that_errors_still_sends_what_was_queued(self, db_session):
        def entities():
            yield PRODUCTS[0]
            raise RuntimeError('loader broke')

        policy = CompliancePolicyDb(
            id=str(uuid.uuid4()), name='P', is_active=True,
            rule="MATCH (p:data_product)\nASSERT p.status = 'active'\nON_FAIL NOTIFY 'a@example.com'",
            rule_author_email='admin@example.com', rule_author_groups=json.dumps(['old-admins-errors']),
        )
        db_session.add(AppRoleDb(name='Old Admin errors', assigned_groups='["old-admins-errors"]',
                                 feature_permissions='{"compliance": "Admin"}'))
        db_session.add(policy)
        db_session.flush()
        iterator = MagicMock()
        iterator.iterate.return_value = entities()
        with (
            patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator),
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()),
        ):
            run = ComplianceManager().run_policy_inline(db_session, policy=policy)

        assert run.status == 'failed'
        assert db_session.query(NotificationDb).filter_by(recipient='a@example.com').count() == 1

    def test_job_path_notifies(self, db_session):
        """The compliance-checks job calls run_policy_inline without a user."""
        _run(db_session, "MATCH (p:data_product)\nASSERT p.status = 'active'\nON_FAIL NOTIFY 'a@example.com'",
             PRODUCTS, current_user=None)

        assert db_session.query(NotificationDb).filter_by(recipient='a@example.com').count() == 1


class TestFailureCodes:
    def test_unexpected_errors_are_reported_without_their_text(self, db_session, default_tag):
        adapter = TagsManagerTagAdapter(db_session)
        with patch.object(adapter, 'assign_tag', side_effect=RuntimeError('secret db detail')):
            result = AssignTagAction(default_tag.name, 'x').execute(_context(adapter))

        assert (result.code, result.error) == ('action_failed', 'Action failed')
        assert 'secret db detail' not in json.dumps(result.__dict__)


# --- Review follow-ups --------------------------------------------------------


class TestNotifyResolution:
    def test_each_owner_hears_only_about_their_own_entity(self, db_session):
        from src.db_models.business_owners import BusinessOwnerDb
        from src.db_models.business_roles import BusinessRoleDb

        role = BusinessRoleDb(id=uuid.uuid4(), name='Data Owner')
        db_session.add(role)
        db_session.flush()
        for domain_id, email in (('dom-a', 'a-owner@example.com'), ('dom-b', 'b-owner@example.com')):
            db_session.add(BusinessOwnerDb(
                id=uuid.uuid4(), object_type='data_domain', object_id=domain_id,
                user_email=email, role_id=role.id, is_active=True,
            ))
        db_session.flush()
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)
        for domain_id, name in (('dom-a', 'Sales'), ('dom-b', 'Finance')):
            context = _context(notification_manager=notifier, entity_id=domain_id, name=name)
            context.entity_type = 'domain'
            assert NotifyAction('entity_owner').execute(context).success is True
        notifier.flush(failed=2, passed=0)

        listed = {
            n.recipient: json.loads(n.data)['i18n']['descriptionLines'][1]['params']['names']['text']
            for n in db_session.query(NotificationDb).all()
        }
        assert listed == {'a-owner@example.com': 'Sales', 'b-owner@example.com': 'Finance'}

    def test_a_failed_lookup_fails_that_action_only(self, db_session, default_tag):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1', audience=ADMIN_AUDIENCE)
        calls = {'n': 0}

        def resolve(db, token, context):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('lookup broke')
            return [('a@example.com', None)]

        with patch('src.common.workflow_executor._resolve_role_to_users', side_effect=resolve):
            first = NotifyAction('entity_owner').execute(_context(notification_manager=notifier, entity_id='p1'))
            second = NotifyAction('entity_owner').execute(_context(notification_manager=notifier, entity_id='p2'))

        assert (first.success, first.code) == (False, 'action_failed')
        assert second.success is True
        # The session is still usable after the failed lookup
        assert AssignTagAction(default_tag.name, None).execute(_context(TagsManagerTagAdapter(db_session))).success
        assert notifier.flush(failed=2, passed=0) == 1
