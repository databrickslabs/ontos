"""Compliance NOTIFY audience and Notification Recipients (#1450).

Non-admin authors may notify themselves, the entity's owners and the recipients their
roles are allowed; admins may notify anyone. Checked at save and at run time.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from src.common.compliance_actions import ActionContext, ActionError
from src.common.compliance_dsl import parse_rule
from src.common.compliance_notifications import ComplianceRunNotifier
from src.common.features import FeatureAccessLevel
from src.common.notification_audience import audience_for, violations
from src.controller.compliance_manager import ComplianceManager
from src.controller.notification_recipients_manager import (
    NotificationRecipientNameTakenError,
    NotificationRecipientTargetError,
    NotificationRecipientsManager,
)
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.notification_recipients import NotificationRecipientDb
from src.db_models.notifications import NotificationDb
from src.common.features import ACCESS_LEVEL_ORDER
from src.db_models.settings import AppRoleDb
from src.models.notification_recipients import NotificationRecipientCreate, NotificationRecipientUpdate


STEWARD_GROUP = 'nr-test-stewards'
ADMIN_GROUP = 'nr-test-admins'
PRODUCTS = [
    {'type': 'data_product', 'id': 'p1', 'name': 'Orders', 'status': 'draft', 'owner': 'team-1'},
]


# --- Parser ---------------------------------------------------------------

def _notify(tail: str):
    return parse_rule(f"MATCH (obj:Object)\nASSERT obj.status = 'active'\nON_FAIL {tail}")['on_fail_actions']


class TestRecipientReferenceGrammar:
    def test_identifier_and_quoted_names_parse_to_the_same_reference(self):
        assert _notify("NOTIFY recipient:'Data Stewards'") == [{'type': 'NOTIFY', 'recipients': 'recipient:Data Stewards'}]
        assert _notify("NOTIFY recipient:privacy") == [{'type': 'NOTIFY', 'recipients': 'recipient:privacy'}]
        assert _notify("NOTIFY 'recipient:Data Stewards'") == [{'type': 'NOTIFY', 'recipients': 'recipient:Data Stewards'}]

    def test_plain_string_recipients_are_unchanged(self):
        assert _notify("NOTIFY 'self, entity_owner'") == [{'type': 'NOTIFY', 'recipients': 'self, entity_owner'}]

    def test_empty_name_is_a_parse_error(self):
        with pytest.raises(ValueError):
            _notify("NOTIFY recipient:''")


# --- Fixtures -------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_up(db_session):
    """Rows are committed by the managers under test; remove them so tests don't see each other's."""
    yield
    db_session.rollback()
    db_session.query(NotificationRecipientDb).delete()
    db_session.query(NotificationDb).delete()
    db_session.query(AppRoleDb).filter(AppRoleDb.name.like('NR %')).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def roles(db_session):
    """A Data Steward, a Security Officer and an Admin, each with compliance access by group."""
    suffix = uuid.uuid4().hex[:8]
    steward = AppRoleDb(name=f'NR Data Steward {suffix}', assigned_groups=json.dumps([STEWARD_GROUP]),
                        feature_permissions=json.dumps({'compliance': 'Read/Write'}))
    security = AppRoleDb(name=f'NR Security Officer {suffix}', assigned_groups=json.dumps(['nr-test-security']),
                         feature_permissions=json.dumps({'compliance': 'Read/Write'}))
    admin = AppRoleDb(name=f'NR Admin {suffix}', assigned_groups=json.dumps([ADMIN_GROUP]),
                      feature_permissions=json.dumps({'compliance': 'Admin'}), is_admin=True)
    db_session.add_all([steward, security, admin])
    db_session.flush()
    return {'steward': steward, 'security': security, 'admin': admin}


def _recipient(db, name, allowed_roles, targets=('stewards@example.com',), is_active=True):
    row = NotificationRecipientDb(
        id=str(uuid.uuid4()), name=name, targets=json.dumps(list(targets)),
        allowed_role_ids=json.dumps([str(r.id) for r in allowed_roles]), is_active=is_active,
    )
    db.add(row)
    db.flush()
    return row


def _policy(db, rule, author_email=None, author_groups=(STEWARD_GROUP,)):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name='Classified products', is_active=True, rule=rule,
        rule_author_email=author_email, rule_author_groups=json.dumps(list(author_groups)),
    )
    db.add(policy)
    db.flush()
    return policy


def _run(db, policy, current_user=None, entities=None):
    iterator = MagicMock()
    iterator.iterate.return_value = iter(entities if entities is not None else PRODUCTS)
    with (
        patch('src.controller.compliance_manager.create_entity_iterator', return_value=iterator),
        patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()),
    ):
        return ComplianceManager().run_policy_inline(db, policy=policy, current_user=current_user)


def _rule(*notify_targets):
    """A rule with one NOTIFY per target; targets are the DSL strings, e.g. 'self' or 'recipient:Privacy'."""
    actions = ' '.join(f"NOTIFY '{t}'" for t in notify_targets)
    return f"MATCH (p:data_product)\nASSERT p.status = 'active'\nON_FAIL {actions}"


STEWARD_EMAIL = 'steward@example.com'


def _steward(db):
    return audience_for(db, STEWARD_EMAIL, [STEWARD_GROUP])


# --- Audience -------------------------------------------------------------

class TestAudience:
    def test_admin_may_notify_anyone(self, db_session, roles):
        audience = audience_for(db_session, 'boss@example.com', [ADMIN_GROUP])
        assert audience.is_admin
        assert violations(db_session, "someone@example.com, Any Group, user:x@example.com", audience) == []

    def test_writer_may_notify_self_and_the_entity_owners(self, db_session, roles):
        audience = _steward(db_session)
        assert not audience.is_admin
        assert violations(db_session, f"self, entity_owner, owner, {STEWARD_EMAIL}", audience) == []

    def test_writer_is_refused_any_other_target(self, db_session, roles):
        [(code, target, params)] = violations(db_session, "other@example.com", _steward(db_session))
        assert (code, target, params) == ('notify_target_not_allowed', 'other@example.com', {'target': 'other@example.com'})

    def test_writer_is_refused_a_group_or_a_role_directly(self, db_session, roles):
        codes = [c for c, _t, _p in violations(db_session, "Data Stewards, requester", _steward(db_session))]
        assert codes == ['notify_target_not_allowed', 'notify_target_not_allowed']

    def test_writer_may_use_a_recipient_allowed_for_their_role(self, db_session, roles):
        _recipient(db_session, 'Data Stewards', [roles['steward']])
        assert violations(db_session, "recipient:Data Stewards", _steward(db_session)) == []

    def test_writer_is_refused_a_recipient_not_allowed_for_their_roles(self, db_session, roles):
        _recipient(db_session, 'Privacy', [roles['security']])
        [(code, _t, params)] = violations(db_session, 'recipient:Privacy', _steward(db_session))
        assert (code, params) == ('notify_recipient_not_allowed', {'recipient': 'Privacy'})

    def test_unknown_recipient_is_refused_for_everyone(self, db_session, roles):
        [(code, _t, _p)] = violations(db_session, 'recipient:Nobody', audience_for(db_session, 'boss@example.com', [ADMIN_GROUP]))
        assert code == 'notify_recipient_not_found'

    def test_a_policy_without_an_author_may_only_notify_the_entity_owners(self, db_session, roles):
        audience = audience_for(db_session, None, [])
        assert violations(db_session, 'entity_owner', audience) == []
        assert violations(db_session, 'self', audience) == []  # nobody to resolve to; the run has no recipient
        assert violations(db_session, STEWARD_EMAIL, audience)

    def test_a_workspace_admin_group_alone_is_not_a_notify_admin(self, db_session, roles):
        # Admin is the compliance feature level only: no workspace-group shortcut. A workspace admin
        # is an admin when their roles grant compliance ADMIN (the admin role in the fixture does)
        audience = audience_for(db_session, 'ws-admin@example.com', ['admins'])
        assert not audience.is_admin
        assert violations(db_session, "Anyone Else", audience)

    def test_a_role_flagged_is_admin_without_compliance_admin_is_not_an_admin(self, db_session, roles):
        db_session.add(AppRoleDb(
            name=f'NR Flagged {uuid.uuid4().hex[:8]}', assigned_groups=json.dumps(['nr-flagged']),
            feature_permissions=json.dumps({'compliance': 'Read/Write'}), is_admin=True,
        ))
        db_session.flush()
        audience = audience_for(db_session, 'flagged@example.com', ['nr-flagged'])
        assert not audience.is_admin
        assert violations(db_session, "Anyone Else", audience)

    def test_a_team_role_granting_compliance_admin_is_an_admin_at_run_time(self, db_session, roles):
        # The run path has no request: the team role override is read from the database
        team_admin = AppRoleDb(name=f'NR Team Admin {uuid.uuid4().hex[:8]}', assigned_groups=json.dumps([]),
                               feature_permissions=json.dumps({'compliance': 'Admin'}))
        db_session.add(team_admin)
        db_session.flush()
        with patch('src.controller.teams_manager.TeamsManager.get_teams_for_user', return_value=[]), \
                patch('src.common.team_role_override.pick_team_role_override', return_value=team_admin.name):
            audience = audience_for(db_session, 'member@example.com', [])
        assert audience.is_admin
        assert violations(db_session, "Anyone Else", audience) == []

    def test_self_is_matched_without_case(self, db_session, roles):
        assert violations(db_session, "Self", _steward(db_session)) == []

    @pytest.mark.parametrize('spelling', ['Entity Owner', 'entity_owner', 'ENTITY OWNER', 'Owner', 'owner', 'SELF', 'Self', 's_e_l_f'])
    def test_owner_and_self_spellings_are_one_token(self, db_session, roles, spelling):
        # The same spellings are resolved by the notifier (test_compliance_notify_followups)
        assert violations(db_session, spelling, _steward(db_session)) == []

    def test_role_by_email_assignment_counts(self, db_session, roles):
        roles['steward'].assigned_groups = json.dumps([])
        roles['steward'].assigned_users = json.dumps(['by-email@example.com'])
        db_session.flush()
        audience = audience_for(db_session, 'by-email@example.com', [])
        assert audience.role_ids == frozenset({str(roles['steward'].id)})


# --- Run time -------------------------------------------------------------

class TestRunTime:
    def test_a_refused_target_fails_its_action_and_the_run_carries_on(self, db_session, roles):
        _recipient(db_session, 'Privacy', [roles['security']])
        policy = _policy(db_session, _rule("Privacy", "recipient:Privacy", "self"), author_email=STEWARD_EMAIL)
        run = _run(db_session, policy, current_user='someone-else@example.com')

        assert run.status == 'succeeded'
        notes = {n.recipient for n in db_session.query(NotificationDb).all()}
        assert notes == {STEWARD_EMAIL}  # self only; the refused targets sent nothing

    def test_narrowing_the_allow_list_refuses_the_action_and_keeps_the_policy(self, db_session, roles):
        recipient = _recipient(db_session, 'Data Stewards', [roles['steward']])
        policy = _policy(db_session, _rule('recipient:Data Stewards'), author_email=STEWARD_EMAIL)
        recipient.allowed_role_ids = json.dumps([str(roles['admin'].id)])
        db_session.flush()

        run = _run(db_session, policy)
        results = [r for r in run.results if r.details_json]
        actions = json.loads(results[0].details_json)['actions']
        assert actions[0]['success'] is False
        assert actions[0]['code'] == 'notify_recipient_not_allowed'
        assert db_session.get(CompliancePolicyDb, policy.id).rule == policy.rule

    def test_a_withdrawn_role_grant_is_refused_at_run_time(self, db_session, roles):
        _recipient(db_session, 'Data Stewards', [roles['steward']])
        policy = _policy(db_session, _rule('recipient:Data Stewards'), author_email=STEWARD_EMAIL)
        roles['steward'].assigned_groups = json.dumps([])
        db_session.flush()

        run = _run(db_session, policy)
        assert run.status == 'succeeded'
        assert db_session.query(NotificationDb).count() == 0
        results = [r for r in run.results if r.details_json]
        assert json.loads(results[0].details_json)['actions'][0]['code'] == 'notify_recipient_not_allowed'

    def test_a_disabled_recipient_fails_with_a_reason(self, db_session, roles):
        _recipient(db_session, 'Data Stewards', [roles['steward']], is_active=False)
        policy = _policy(db_session, _rule('recipient:Data Stewards'), author_email=STEWARD_EMAIL)

        run = _run(db_session, policy)
        results = [r for r in run.results if r.details_json]
        action = json.loads(results[0].details_json)['actions'][0]
        assert (action['success'], action['code']) == (False, 'notify_recipient_disabled')

    def test_self_is_the_author_not_the_user_who_runs_the_policy(self, db_session, roles):
        policy = _policy(db_session, _rule('self'), author_email=STEWARD_EMAIL)
        _run(db_session, policy, current_user='runner@example.com')

        assert {n.recipient for n in db_session.query(NotificationDb).all()} == {STEWARD_EMAIL}

    def test_a_scheduled_run_checks_the_author_not_a_user(self, db_session, roles):
        policy = _policy(db_session, _rule("Anyone Else"), author_email=STEWARD_EMAIL)
        run = _run(db_session, policy, current_user=None)

        results = [r for r in run.results if r.details_json]
        assert json.loads(results[0].details_json)['actions'][0]['code'] == 'notify_target_not_allowed'

    def test_an_admin_author_may_notify_any_target(self, db_session, roles):
        policy = _policy(db_session, _rule("group:Anyone Else"), author_email='boss@example.com', author_groups=(ADMIN_GROUP,))
        _run(db_session, policy)

        assert db_session.query(NotificationDb).filter_by(recipient='Anyone Else').count() == 1

    def test_the_notifier_refuses_before_resolving(self, db_session, roles):
        notifier = ComplianceRunNotifier(
            db_session, policy_id='p', policy_name='P', run_id='r', audience=_steward(db_session),
        )
        context = ActionContext(
            entity=PRODUCTS[0], entity_type='data_product', entity_id='p1', rule_id='p', rule_name='P',
            passed=False, notification_manager=notifier,
        )
        with pytest.raises(ActionError) as exc:
            notifier.notify("'Anyone Else'", context)
        assert exc.value.code == 'notify_target_not_allowed'


# --- Routes ---------------------------------------------------------------

def _persona_permissions(groups):
    if ADMIN_GROUP in groups:
        return {'compliance': FeatureAccessLevel.ADMIN, 'settings-roles': FeatureAccessLevel.ADMIN}
    return {'compliance': FeatureAccessLevel.READ_WRITE, 'settings-roles': FeatureAccessLevel.READ_ONLY}


@pytest.fixture
def http(db_session):
    from fastapi import FastAPI

    from src.common.authorization import get_user_details_from_sdk
    from src.common.dependencies import get_current_user_details_for_audit
    from src.common.manager_dependencies import get_audit_manager, get_auth_manager
    from src.models.users import UserInfo
    from src.routes import compliance_routes, notification_recipients_routes

    app = FastAPI()
    app.include_router(compliance_routes.router)
    app.include_router(notification_recipients_routes.router)
    state = {'user': UserInfo(email=STEWARD_EMAIL, username='steward', user='S', ip='127.0.0.1', groups=[STEWARD_GROUP])}

    async def _user():
        return state['user']

    app.dependency_overrides[get_user_details_from_sdk] = _user
    app.dependency_overrides[get_current_user_details_for_audit] = _user
    auth = MagicMock()
    # The real order of access levels, applied to the persona's permissions
    auth.has_permission.side_effect = lambda perms, feature, level: (
        ACCESS_LEVEL_ORDER[perms.get(feature, FeatureAccessLevel.NONE)] >= ACCESS_LEVEL_ORDER[level]
    )
    app.dependency_overrides[get_auth_manager] = lambda: auth
    app.dependency_overrides[get_audit_manager] = lambda: MagicMock()

    async def _permissions(email, groups, request, auth_manager=None):
        return _persona_permissions(groups or [])

    from fastapi.testclient import TestClient as _TC
    with (
        patch('src.common.authorization.resolve_effective_permissions', side_effect=_permissions),
        patch.object(compliance_routes, 'manager') as manager,
    ):
        # Auth lookups by role are real; the permission check is the persona's table above
        manager.get_policy.return_value = None
        yield SimpleNamespace(client=_TC(app), manager=manager, state=state)


def _payload(rule, name='P'):
    return {'name': name, 'description': 'd', 'category': 'Governance', 'severity': 'low', 'rule': rule, 'is_active': True}


class TestRoutes:
    def test_writer_saves_a_notify_to_self_and_an_allowed_recipient(self, http, db_session, roles):
        _recipient(db_session, 'Data Stewards', [roles['steward']])
        response = http.client.post('/api/compliance/policies', json=_payload(_rule('self', 'recipient:Data Stewards')))

        assert response.status_code == 200, response.text
        assert http.manager.create_policy.call_args.kwargs['author'] == (STEWARD_EMAIL, [STEWARD_GROUP])

    def test_writer_is_refused_a_recipient_not_allowed_for_them(self, http, db_session, roles):
        _recipient(db_session, 'Privacy', [roles['security']])
        response = http.client.post('/api/compliance/policies', json=_payload(_rule("recipient:Privacy")))

        assert response.status_code == 400
        detail = response.json()['detail']
        assert detail['code'] == 'notify_recipient_not_allowed'
        assert detail['params'] == {'recipient': 'Privacy'}
        http.manager.create_policy.assert_not_called()

    def test_writer_is_refused_every_disallowed_target_with_its_code(self, http, db_session, roles):
        response = http.client.post('/api/compliance/policies', json=_payload(_rule("Other Group", "x@example.com")))

        detail = response.json()['detail']
        assert response.status_code == 400
        assert [v['target'] for v in detail['violations']] == ['Other Group', 'x@example.com']
        assert {v['code'] for v in detail['violations']} == {'notify_target_not_allowed'}

    def test_writer_cannot_retarget_a_policy_to_a_disallowed_target(self, http, db_session, roles):
        pid = str(uuid.uuid4())
        http.manager.get_policy.return_value = SimpleNamespace(
            id=pid, name='P', description='d', rule=_rule("Admin Only Group"), rule_author_email='boss@example.com',
            rule_author_groups='[]', failure_message=None, is_active=True, severity='low', category='Governance',
        )
        response = http.client.put(f'/api/compliance/policies/{pid}', json={
            **_payload(_rule("Someone Else")), 'id': pid,
        })

        assert response.status_code == 400
        http.manager.update_policy.assert_not_called()

    def test_writer_cannot_rename_an_admin_notify_policy(self, http, db_session, roles):
        """The reviewer's scenario: the name titles the notifications, so a rename re-checks the editor."""
        pid = str(uuid.uuid4())
        rule = _rule("all-staff")
        http.manager.get_policy.return_value = SimpleNamespace(
            id=pid, name='P', description='d', rule=rule, rule_author_email='boss@example.com', rule_author_groups='[]',
            failure_message=None, is_active=True, severity='low', category='Governance',
        )
        response = http.client.put(f'/api/compliance/policies/{pid}', json={
            **_payload(rule, name='URGENT reset your password at evil.example'), 'id': pid,
        })

        assert response.status_code == 400
        detail = response.json()['detail']
        assert detail['code'] == 'notify_target_not_allowed'
        assert detail['params'] == {'target': 'all-staff'}
        http.manager.update_policy.assert_not_called()

    def test_writer_cannot_edit_the_description_of_an_admin_notify_policy(self, http, db_session, roles):
        pid = str(uuid.uuid4())
        rule = _rule("all-staff")
        http.manager.get_policy.return_value = SimpleNamespace(
            id=pid, name='P', description='d', rule=rule, rule_author_email='boss@example.com', rule_author_groups='[]',
            failure_message=None, is_active=True, severity='low', category='Governance',
        )
        response = http.client.put(f'/api/compliance/policies/{pid}', json={
            **_payload(rule), 'id': pid, 'description': 'changed',
        })

        assert response.status_code == 400
        http.manager.update_policy.assert_not_called()

    def test_writer_renaming_a_policy_they_may_notify_becomes_its_author(self, http, db_session, roles):
        pid = str(uuid.uuid4())
        rule = _rule("self")
        http.manager.get_policy.return_value = SimpleNamespace(
            id=pid, name='P', description='d', rule=rule, rule_author_email='boss@example.com', rule_author_groups='[]',
            failure_message=None, is_active=True, severity='low', category='Governance',
        )
        http.manager.update_policy.return_value = CompliancePolicyDb(
            id=pid, name='Renamed', description='d', rule=rule, category='Governance', severity='low',
            is_active=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        response = http.client.put(f'/api/compliance/policies/{pid}', json={**_payload(rule, name='Renamed'), 'id': pid})

        assert response.status_code == 200, response.text
        assert http.manager.update_policy.call_args.kwargs['author'] == (STEWARD_EMAIL, [STEWARD_GROUP])

    def test_writer_renaming_a_policy_without_notify_keeps_the_author(self, http, db_session, roles):
        pid = str(uuid.uuid4())
        rule = "MATCH (p:data_product)\nASSERT p.status = 'active'\nON_FAIL FAIL 'x'"
        http.manager.get_policy.return_value = SimpleNamespace(
            id=pid, name='P', description='d', rule=rule, rule_author_email='boss@example.com', rule_author_groups='[]',
            failure_message=None, is_active=True, severity='low', category='Governance',
        )
        http.manager.update_policy.return_value = CompliancePolicyDb(
            id=pid, name='Renamed', description='d', rule=rule, category='Governance', severity='low',
            is_active=True, created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
        )
        response = http.client.put(f'/api/compliance/policies/{pid}', json={**_payload(rule, name='Renamed'), 'id': pid})

        assert response.status_code == 200, response.text
        assert http.manager.update_policy.call_args.kwargs['author'] is None

    def test_admin_may_save_any_target_and_becomes_the_author(self, http, db_session, roles):
        http.state['user'] = http.state['user'].model_copy(update={'email': 'boss@example.com', 'groups': [ADMIN_GROUP]})
        response = http.client.post('/api/compliance/policies', json=_payload(_rule("Anyone")))

        assert response.status_code == 200, response.text
        assert http.manager.create_policy.call_args.kwargs['author'] == ('boss@example.com', [ADMIN_GROUP])

    def test_run_is_not_refused_at_the_route_for_a_notify_policy(self, http, db_session, roles):
        pid = str(uuid.uuid4())
        http.manager.get_policy.return_value = SimpleNamespace(id=pid, name='P', rule=_rule("Anyone"))
        http.manager.run_policy_inline.return_value = SimpleNamespace(
            id='run-1', policy_id=pid, status='succeeded', started_at=None, finished_at=None,
            success_count=0, failure_count=0, score=0.0, error_message=None,
            error_code=None, error_params=None, warning_code=None, warning_params=None,
        )
        response = http.client.post(f'/api/compliance/policies/{pid}/runs', json={})

        assert response.status_code == 200, response.text


class TestRecipientRoutes:
    def test_only_admins_manage_recipients(self, http, db_session, roles):
        payload = {'name': 'Stewards', 'targets': ['a@example.com'], 'allowed_role_ids': [], 'is_active': True}
        assert http.client.post('/api/settings/notification-recipients', json=payload).status_code == 403
        assert http.client.get('/api/settings/notification-recipients').status_code == 403

        http.state['user'] = http.state['user'].model_copy(update={'groups': [ADMIN_GROUP]})
        created = http.client.post('/api/settings/notification-recipients', json=payload)
        assert created.status_code == 201, created.text
        assert http.client.get('/api/settings/notification-recipients').json()[0]['name'] == 'Stewards'

    def test_writers_see_only_the_recipients_their_roles_may_use(self, http, db_session, roles):
        _recipient(db_session, 'Data Stewards', [roles['steward']])
        _recipient(db_session, 'Privacy', [roles['security']])
        names = [r['name'] for r in http.client.get('/api/compliance/notification-recipients/available').json()]
        assert names == ['Data Stewards']

    def test_a_target_that_depends_on_the_entity_is_refused(self, db_session):
        with pytest.raises(NotificationRecipientTargetError):
            NotificationRecipientsManager().create(
                db_session, NotificationRecipientCreate(name='Owners', targets=['entity_owner']), username='admin',
            )

    def test_names_are_unique_without_case_and_safe_for_the_dsl(self, db_session):
        manager = NotificationRecipientsManager()
        manager.create(db_session, NotificationRecipientCreate(name='Privacy Office', targets=['x@example.com']), username='a')
        with pytest.raises(NotificationRecipientNameTakenError):
            manager.create(db_session, NotificationRecipientCreate(name='privacy office'), username='a')
        with pytest.raises(ValueError):
            manager.create(db_session, NotificationRecipientCreate(name="Bad'Name"), username='a')

    def test_disabling_a_recipient_keeps_it_for_reference(self, db_session):
        manager = NotificationRecipientsManager()
        created = manager.create(db_session, NotificationRecipientCreate(name='Privacy', targets=['x@example.com']), username='a')
        updated = manager.update(
            db_session, created.id, NotificationRecipientUpdate(name='Privacy', targets=['x@example.com'], is_active=False),
            username='a',
        )
        assert updated.is_active is False
        assert manager.get(db_session, created.id) is not None

    def test_a_rejected_edit_changes_nothing(self, db_session):
        manager = NotificationRecipientsManager()
        created = manager.create(db_session, NotificationRecipientCreate(name='Privacy', targets=['x@example.com']), username='a')
        with pytest.raises(NotificationRecipientTargetError):
            manager.update(
                db_session, created.id, NotificationRecipientUpdate(name='Renamed', targets=['owner'], is_active=False),
                username='b',
            )
        # Validation runs before any attribute is set, so the row is untouched even before a rollback
        row = manager.get(db_session, created.id)
        assert (row.name, row.is_active, row.updated_by) == ('Privacy', True, 'a')

    def test_a_name_taken_at_commit_is_the_coded_error(self, db_session):
        manager = NotificationRecipientsManager()
        manager.create(db_session, NotificationRecipientCreate(name='Taken', targets=['x@example.com']), username='a')
        with patch.object(db_session, 'commit', side_effect=IntegrityError('insert', {}, Exception('uq'))):
            with pytest.raises(NotificationRecipientNameTakenError):
                manager.create(db_session, NotificationRecipientCreate(name='Other', targets=['y@example.com']), username='a')
