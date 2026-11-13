"""
Integration regression test for #1526: GET /api/notifications must list a pending
approval that is older than the first 1,000 rows of the notifications table.
"""
import json
import uuid
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db_models.notifications import NotificationDb

FLOOD = 1_200


def test_pending_approval_is_listed_after_more_than_1000_notifications(
    client: TestClient, db_session: Session,
):
    now = datetime(2026, 11, 1, 12, 0, 0)
    db_session.execute(NotificationDb.__table__.insert(), [
        dict(id=str(uuid.uuid4()), type='info', title=f'Noise {i}', created_at=now, read=False,
             can_delete=True, recipient=f'other{i}@example.com')
        for i in range(FLOOD)
    ])
    approval_id = str(uuid.uuid4())
    db_session.execute(NotificationDb.__table__.insert(), [dict(
        id=approval_id, type='action_required', title='Approval required',
        created_at=datetime(2020, 1, 1, 12, 0, 0), read=False, can_delete=False,
        recipient='test@example.com', action_type='workflow_approval',
        action_payload=json.dumps({'execution_id': 'exec-1', 'step_id': 'approve'}),
    )])
    db_session.flush()

    response = client.get('/api/notifications')

    assert response.status_code == 200, response.text
    assert approval_id in [n['id'] for n in response.json()]
