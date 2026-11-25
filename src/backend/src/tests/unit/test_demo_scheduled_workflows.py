"""Demo packs ship no active scheduled workflow: loading demo data starts no runs (#941)."""
import json

import pytest

from src.db_models.process_workflows import ProcessWorkflowDb
from src.tests.unit.test_demo_prepublish_workflows import PACKS, load_pack_workflows


@pytest.mark.parametrize('pack', PACKS, ids=lambda p: p.stem)
def test_no_pack_ships_an_active_scheduled_workflow(db_session, pack):
    load_pack_workflows(db_session, pack)

    rows = db_session.query(ProcessWorkflowDb).all()
    scheduled = [r for r in rows if json.loads(r.trigger_config)['type'] == 'scheduled']
    for row in scheduled:
        assert row.is_active is False, row.name
