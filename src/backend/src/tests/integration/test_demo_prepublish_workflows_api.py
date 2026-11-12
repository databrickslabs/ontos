"""What the API shows for the demo pre-publish gates after a pack is loaded (#996)."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.utils.demo_data_sql import _HEAD_RE, _find_statement_end

DATA_DIR = Path(__file__).resolve().parents[2] / 'data'
GATES = {
    'demo_data_fsi': ['BCBS 239 Pre-Publish Attestation'],
    'demo_data_auto': ['OTA / Connected Services Release Gate'],
    'demo_data_hls': ['IRB Approval Gate', 'HIPAA PHI Pre-Publish Check'],
}


def _load_workflows(db, pack: str):
    """Run the pack's process_workflows and workflow_steps INSERTs on the test DB."""
    sql = (DATA_DIR / f'{pack}.sql').read_text(encoding='utf-8')
    for m in _HEAD_RE.finditer(sql):
        if m.group('table') in ('process_workflows', 'workflow_steps'):
            statement = sql[m.start():_find_statement_end(sql, m.end())]
            db.execute(text(re.sub(r'\bNOW\(\)', 'CURRENT_TIMESTAMP', statement)))
    db.flush()


@pytest.mark.parametrize('pack', sorted(GATES))
def test_the_gates_are_listed_inactive_with_the_example_note(client: TestClient, db_session,
                                                             pack):
    _load_workflows(db_session, pack)

    response = client.get('/api/workflows')

    assert response.status_code == 200, response.text
    by_name = {w['name']: w for w in response.json()['workflows']}
    for name in GATES[pack]:
        workflow = by_name[name]
        assert workflow['is_active'] is False
        assert 'Example only, inactive' in workflow['description']
        assert workflow['steps'], name


@pytest.mark.parametrize('pack', sorted(GATES))
def test_the_active_filter_leaves_the_gates_out(client: TestClient, db_session, pack):
    _load_workflows(db_session, pack)

    response = client.get('/api/workflows', params={'is_active': 'true'})

    assert response.status_code == 200, response.text
    names = {w['name'] for w in response.json()['workflows']}
    assert names.isdisjoint(GATES[pack])
