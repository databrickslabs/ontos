"""
Regression tests for #1526: notifications were read at most 1,000 rows, unordered.

Once the table held more than 1,000 rows, a pending approval that was not among the
first rows the database happened to return vanished from My actions and the bell.
Covered here:
- an old pending approval, for the user or for a role the user is in, is listed after
  more than 1,000 newer rows of other users;
- the bell keeps every actionable item and caps only the informational history;
- the action-type lookups (dedup, mark handled, pending deliveries) are not capped.
"""
import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy.orm import Session

from src.controller.notifications_manager import NotificationsManager
from src.db_models.notifications import NotificationDb
from src.models.users import UserInfo

# More than the old 1,000-row read (and the old 5,000-row lookups for the action types)
FLOOD = 1_200
# The bell's history: the newest rows of this many that are not pending are shown
BELL_HISTORY_LIMIT = 500
NOW = datetime(2026, 11, 1, 12, 0, 0)
OLD = datetime(2020, 1, 1, 12, 0, 0)

ANA = UserInfo(
    email='ana@example.com', username='ana@example.com', user='ana@example.com',
    ip='127.0.0.1', groups=['analysts'],
)
REVIEWERS = SimpleNamespace(
    id='22222222-2222-2222-2222-222222222222', name='Reviewers',
    assigned_groups=['analysts'], assigned_users=[],
)
ORPHAN = SimpleNamespace(
    id='33333333-3333-3333-3333-333333333333', name='Orphan',
    assigned_groups=[], assigned_users=[],
)
ADMIN = SimpleNamespace(
    id='44444444-4444-4444-4444-444444444444', name='Admin',
    assigned_groups=['admins'], assigned_users=[],
)


def _row(**fields) -> dict:
    row = dict(
        id=str(uuid.uuid4()), type='info', title='Notification', created_at=NOW,
        read=False, can_delete=True, recipient=None, recipient_role_id=None,
        action_type=None, action_payload=None,
    )
    row.update(fields)
    return row


def _insert(db: Session, rows: list) -> None:
    if rows:
        db.execute(NotificationDb.__table__.insert(), rows)
    db.flush()


def _flood(db: Session, count: int = FLOOD, **fields) -> None:
    """Rows of other users (and other action types), newer than the target rows."""
    _insert(db, [
        _row(recipient=f'other{i}@example.com', title=f'Noise {i}', **fields)
        for i in range(count)
    ])


def _manager(roles=()) -> NotificationsManager:
    settings = Mock()
    settings.list_app_roles.return_value = list(roles)
    return NotificationsManager(settings_manager=settings)


def _approval(**fields) -> dict:
    return _row(
        type='action_required', title='Approval required', action_type='workflow_approval',
        action_payload=json.dumps({'execution_id': 'exec-1', 'step_id': 'approve'}),
        created_at=OLD, **fields,
    )


class TestPendingApprovalsSurviveTheRowCap:

    def test_old_approval_for_the_user_is_listed_after_more_than_1000_rows(
        self, db_session: Session,
    ):
        _flood(db_session)
        target = _approval(recipient='ana@example.com')
        _insert(db_session, [target])

        listed = _manager().get_notifications(db_session, ANA)

        assert target['id'] in [n.id for n in listed]

    def test_old_approval_for_a_role_the_user_is_in_is_listed(self, db_session: Session):
        _flood(db_session)
        target = _approval(recipient='Reviewers', recipient_role_id=REVIEWERS.id)
        _insert(db_session, [target])

        listed = _manager([REVIEWERS]).get_notifications(db_session, ANA)

        assert target['id'] in [n.id for n in listed]

    def test_old_approval_for_a_group_the_user_is_in_is_listed(self, db_session: Session):
        _flood(db_session)
        target = _approval(recipient='analysts')
        _insert(db_session, [target])

        listed = _manager().get_notifications(db_session, ANA)

        assert target['id'] in [n.id for n in listed]

    def test_bell_keeps_every_actionable_item_and_caps_only_the_history(self, db_session: Session):
        history = [
            _row(recipient='ana@example.com', title=f'History {i}',
                 created_at=NOW - timedelta(minutes=i))
            for i in range(FLOOD + BELL_HISTORY_LIMIT)
        ]
        _insert(db_session, history)
        target = _approval(recipient='ana@example.com')
        _insert(db_session, [target])

        listed = _manager().get_notifications(db_session, ANA)
        ids = [n.id for n in listed]

        assert target['id'] in ids
        plain = [n for n in listed if n.action_type is None]
        assert len(plain) == BELL_HISTORY_LIMIT
        # The newest informational notifications are the ones kept
        assert {n.title for n in plain} == {f'History {i}' for i in range(BELL_HISTORY_LIMIT)}
        # Newest first
        created = [n.created_at for n in listed]
        assert created == sorted(created, reverse=True)

    def test_an_opened_but_undecided_approval_is_kept(self, db_session: Session):
        # Opening a notification in the bell sets read; the approval is still pending
        _flood(db_session)
        target = _approval(recipient='ana@example.com', read=True)
        _insert(db_session, [target])

        listed = _manager().get_notifications(db_session, ANA)

        assert target['id'] in [n.id for n in listed]

    def test_decided_approvals_count_toward_the_history_cap(self, db_session: Session):
        decided = [
            _row(type='action_required', title=f'Decided {i}', action_type='workflow_approval',
                 action_payload=json.dumps({'execution_id': f'e-{i}', 'handled': True}),
                 recipient='ana@example.com', read=True,
                 created_at=NOW - timedelta(minutes=i))
            for i in range(BELL_HISTORY_LIMIT + 100)
        ]
        _insert(db_session, decided)
        pending = _approval(recipient='ana@example.com')
        _insert(db_session, [pending])

        listed = _manager().get_notifications(db_session, ANA)
        ids = {n.id for n in listed}

        assert pending['id'] in ids
        assert len([n for n in listed if n.title.startswith('Decided')]) == BELL_HISTORY_LIMIT

    def test_requests_decided_through_the_handle_path_are_history(self, db_session: Session):
        payload = {'kind': 'role'}
        _insert(db_session, [
            _row(type='action_required', title=f'Role request {i}',
                 action_type='handle_role_request',
                 action_payload=json.dumps(payload), recipient='ana@example.com',
                 created_at=NOW - timedelta(minutes=i))
            for i in range(BELL_HISTORY_LIMIT + 100)
        ])
        pending = _approval(recipient='ana@example.com')
        _insert(db_session, [pending])
        manager = _manager()

        assert manager.handle_actionable_notification(
            db_session, 'handle_role_request', payload) is True
        listed = manager.get_notifications(db_session, ANA)

        assert pending['id'] in [n.id for n in listed]
        requests = [n for n in listed if n.action_type == 'handle_role_request']
        assert len(requests) == BELL_HISTORY_LIMIT

    def test_anonymous_listing_keeps_only_broadcasts(self, db_session: Session):
        _flood(db_session)
        _insert(db_session, [_row(title='Broadcast', created_at=OLD)])

        listed = _manager().get_notifications(db_session, None)

        assert [n.title for n in listed] == ['Broadcast']


class TestActionTypeLookupsAreNotCapped:

    def test_unread_request_older_than_5000_rows_is_found_for_dedup(self, db_session: Session):
        _flood(db_session, count=5_100, action_type='other_action')
        payload = {'job': 'compliance'}
        _insert(db_session, [_row(
            type='action_required', title='Run job', action_type='request_background_job',
            action_payload=json.dumps(payload), created_at=OLD,
        )])

        assert _manager().has_unhandled_actionable_notification(
            db_session, 'request_background_job', payload) is True

    def test_a_handled_request_is_not_pending_any_more(self, db_session: Session):
        payload = {'job': 'compliance'}
        _insert(db_session, [_row(
            type='action_required', title='Run job', action_type='request_background_job',
            action_payload=json.dumps(payload), created_at=OLD, read=True,
        )])

        assert _manager().has_unhandled_actionable_notification(
            db_session, 'request_background_job', payload) is False

    def test_only_the_unread_deliveries_are_pending(self, db_session: Session):
        payload = json.dumps({'change_type': 'grant'})
        handled = _row(type='action_required', title='Done', action_type='delivery_manual',
                       action_payload=payload, created_at=NOW, read=True)
        pending = _row(type='action_required', title='Open', action_type='delivery_manual',
                       action_payload=payload, created_at=OLD)
        _insert(db_session, [handled, pending])

        ids = [n.id for n in _manager().get_pending_delivery_notifications(
            db_session, change_type='grant')]

        assert ids == [pending['id']]

    def test_old_request_is_marked_handled_after_5000_rows(self, db_session: Session):
        _flood(db_session, count=5_100, action_type='other_action')
        payload = {'job': 'compliance'}
        target = _row(
            type='action_required', title='Run job', action_type='request_background_job',
            action_payload=json.dumps(payload), created_at=OLD,
        )
        _insert(db_session, [target])

        assert _manager().handle_actionable_notification(
            db_session, 'request_background_job', payload) is True
        assert db_session.get(NotificationDb, target['id']).read is True

    def test_pending_delivery_older_than_1000_rows_is_listed(self, db_session: Session):
        _flood(db_session, action_type='delivery_manual',
               action_payload=json.dumps({'change_type': 'grant'}))
        target = _row(
            type='action_required', title='Grant access', action_type='delivery_manual',
            action_payload=json.dumps({'change_type': 'grant', 'entity_id': 'e-1'}),
            created_at=OLD,
        )
        _insert(db_session, [target])

        pending = _manager().get_pending_delivery_notifications(db_session, change_type='grant')

        assert target['id'] in [n.id for n in pending]


class _FullScan:
    """The repository read with no SQL prefilter and no cap: the reference for the row check."""

    def __init__(self, repo):
        self._repo = repo

    def get_addressed_to(self, db, *, keys, history_limit):
        return self._repo.get_multi(db, limit=10_000_000)


class TestPrefilterNeverDropsAVisibleRow:
    """The SQL prefilter is a superset of what the per-row check shows (#1526)."""


    @staticmethod
    def _rows() -> list:
        return [
            _row(title='broadcast'),
            _row(title='broadcast, deleted role', recipient_role_id='dead-id'),
            _row(title='identity, other case', recipient='ANA@example.com'),
            _row(title='identity, padded', recipient=' ana@example.com '),
            _row(title='group', recipient='analysts'),
            _row(title='group, deleted role', recipient='analysts', recipient_role_id='dead-id'),
            _row(title='role by id', recipient_role_id=REVIEWERS.id),
            _row(title='role by id, other recipient', recipient='someone@example.com',
                 recipient_role_id=REVIEWERS.id),
            _row(title='legacy role name', recipient='Reviewers'),
            _row(title='orphan role (admins only)', recipient_role_id=ORPHAN.id),
            _row(title='orphan role name', recipient='Orphan'),
            _row(title='admin role', recipient_role_id=ADMIN.id),
            _row(title='someone else', recipient='other@example.com'),
            _row(title='other role', recipient='other@example.com', recipient_role_id='dead-id'),
        ]

    def _visible(self, db, manager, user):
        full = NotificationsManager(settings_manager=manager._settings_manager)
        full._repo = _FullScan(manager._repo)
        reference = {n.title for n in full.get_notifications(db, user)}
        filtered = {n.title for n in manager.get_notifications(db, user)}
        return filtered, reference

    def test_member_sees_the_same_rows_as_a_full_scan(self, db_session: Session):
        _insert(db_session, self._rows())
        manager = _manager([REVIEWERS, ORPHAN, ADMIN])

        filtered, reference = self._visible(db_session, manager, ANA)

        assert filtered == reference
        assert 'role by id' in filtered and 'identity, padded' in filtered
        assert 'orphan role (admins only)' not in filtered

    def test_admin_sees_the_same_rows_as_a_full_scan(self, db_session: Session):
        _insert(db_session, self._rows())
        manager = _manager([REVIEWERS, ORPHAN, ADMIN])
        admin = UserInfo(email='root@example.com', username='root@example.com',
                         user='root@example.com', ip='127.0.0.1', groups=['admins'])

        filtered, reference = self._visible(db_session, manager, admin)

        assert filtered == reference
        assert 'orphan role (admins only)' in filtered and 'admin role' in filtered

    def test_no_roles_loaded_shows_the_same_rows_as_a_full_scan(self, db_session: Session):
        _insert(db_session, self._rows())
        manager = _manager([])

        filtered, reference = self._visible(db_session, manager, ANA)

        assert filtered == reference
