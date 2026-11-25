"""GET /api/access-grants/my-requests?status=: the caller's requests of one status."""
from datetime import datetime, timedelta, timezone

import pytest

from src.db_models.access_grants import AccessGrantRequestDb

ME = 'test@example.com'  # the client fixture's mock_test_user
URL = '/api/access-grants/my-requests'


@pytest.fixture
def requests_of_me(db_session):
    """Three old pending requests of mine, under 120 newer approved ones, and a stranger's."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def make(i, status, email=ME):
        return AccessGrantRequestDb(
            requester_email=email, entity_type='asset', entity_id=f'e{i}', entity_name=f'n{i}',
            requested_duration_days=7, status=status, created_at=base + timedelta(minutes=i),
        )

    rows = [make(i, 'pending') for i in range(3)]
    rows += [make(10 + i, 'approved') for i in range(120)]
    rows.append(make(500, 'pending', 'other@example.com'))
    db_session.add_all(rows)
    db_session.flush()


def test_status_filter_counts_and_lists_only_that_status(client, requests_of_me):
    res = client.get(URL, params={'status': 'pending'})
    assert res.status_code == 200
    body = res.json()
    assert body['total'] == 3
    assert {r['status'] for r in body['requests']} == {'pending'}
    assert {r['requester_email'] for r in body['requests']} == {ME}


def test_without_a_filter_the_newest_page_hides_older_pending_requests(client, requests_of_me):
    body = client.get(URL).json()
    assert body['total'] == 123
    assert len(body['requests']) == 100
    assert 'pending' not in {r['status'] for r in body['requests']}


def test_unknown_status_is_refused(client, requests_of_me):
    assert client.get(URL, params={'status': 'nope'}).status_code == 422
