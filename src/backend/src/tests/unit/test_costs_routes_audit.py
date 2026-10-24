"""Creating a cost item writes a JSON-serializable audit entry."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.models.costs import CostItemCreate
from src.models.users import UserInfo
from src.routes import costs_routes

USER = UserInfo(email='alice@example.com', username='alice', user='Alice',
                ip='127.0.0.1', groups=[])


class _RecordingAudit:
    def __init__(self):
        self.entries = []

    def log_action(self, **kwargs):
        # The real manager stores details in a JSON column
        json.dumps(kwargs['details'])
        self.entries.append(kwargs)


def test_creating_a_cost_item_writes_an_audit_entry():
    item_id = uuid.uuid4()
    manager = MagicMock()
    manager.create.return_value = SimpleNamespace(id=item_id)
    audit = _RecordingAudit()
    payload = CostItemCreate(
        entity_type='data_product', entity_id='p-1', title='Compute',
        cost_center='INFRASTRUCTURE', amount_cents=100, currency='USD',
        start_month='2026-01-01',
    )

    asyncio.run(costs_routes.create_cost_item(
        entity_type='data_product', entity_id='p-1', payload=payload, request=MagicMock(),
        db=MagicMock(), current_user=USER, audit_manager=audit, audit_user=USER,
        manager=manager, _=True,
    ))

    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry['action'] == 'CREATE' and entry['success'] is True
    assert entry['details']['cost_item_id'] == str(item_id)
