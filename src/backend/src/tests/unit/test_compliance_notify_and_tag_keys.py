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
from src.controller.compliance_manager import ComplianceManager, TagsManagerTagAdapter
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
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
        assert assoc.assigned_value == ''

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

class TestNotifyAction:
    def test_without_a_notifier_is_a_coded_failure(self):
        result = NotifyAction('a@example.com').execute(_context())

        assert (result.success, result.code) == (False, 'notification_manager_unavailable')

    def test_notifier_collects_one_notification_per_recipient_per_run(self, db_session):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='Classified products', run_id='run-1')

        for i in range(25):
            result = NotifyAction('a@example.com, b@example.com').execute(
                _context(notification_manager=notifier, entity_id=f'p{i}', name=f'Product {i}')
            )
            assert result.success is True
        NotifyAction('a@example.com').execute(_context(notification_manager=notifier, entity_id='ok', passed=True))

        assert db_session.query(NotificationDb).count() == 0  # nothing until the run ends
        assert notifier.flush() == 2

        rows = {n.recipient: n for n in db_session.query(NotificationDb).all()}
        assert set(rows) == {'a@example.com', 'b@example.com'}
        a = rows['a@example.com']
        assert a.link == '/compliance/runs/run-1'
        data = json.loads(a.data)
        assert data['i18n']['title'] == 'notifications:complianceRun.title'
        assert data['i18n']['params']['policyName'] == 'Classified products'
        assert data['i18n']['params']['failedCount'] == '25'
        assert data['i18n']['params']['passedCount'] == '1'
        # The description lists a bounded number of entities, then a count of the rest
        assert 'Product 0' in a.description and 'Product 9' in a.description
        assert 'Product 10' not in a.description and '15 more' in a.description

    def test_flush_twice_does_not_send_again(self, db_session):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1')
        NotifyAction('a@example.com').execute(_context(notification_manager=notifier))

        assert notifier.flush() == 1
        assert notifier.flush() == 0

    def test_recipients_that_resolve_to_nobody_fail_the_action(self, db_session):
        notifier = ComplianceRunNotifier(db_session, policy_id='pol-1', policy_name='P', run_id='run-1')

        result = NotifyAction('entity_owner').execute(_context(notification_manager=notifier))

        assert (result.success, result.code) == (False, 'notify_no_recipients')


# --- Runs -------------------------------------------------------------------

def _run(db, rule, entities, current_user='steward@example.com'):
    policy = CompliancePolicyDb(id=str(uuid.uuid4()), name='Classified products', rule=rule, is_active=True)
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

    def test_notification_failure_does_not_fail_the_run(self, db_session):
        with patch.object(ComplianceRunNotifier, 'flush', side_effect=RuntimeError('db down')):
            run = _run(db_session, "MATCH (p:data_product)\nASSERT p.status = 'active'\nON_FAIL NOTIFY 'a@example.com'", PRODUCTS)

        assert run.status == 'succeeded'
        assert run.failure_count == 2

    def test_job_path_notifies(self, db_session):
        """The compliance-checks job calls run_policy_inline without a user."""
        _run(db_session, "MATCH (p:data_product)\nASSERT p.status = 'active'\nON_FAIL NOTIFY 'a@example.com'",
             PRODUCTS, current_user=None)

        assert db_session.query(NotificationDb).filter_by(recipient='a@example.com').count() == 1
