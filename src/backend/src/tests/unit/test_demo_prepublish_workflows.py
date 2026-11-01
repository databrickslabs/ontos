"""The demo pre-publish gates ship inactive, marked as examples (#996).

Their ``before_publish`` trigger isn't a ``TriggerType`` (the API loads them as
``manual``), so they never run. Until a blocking pre-publish trigger exists
(#997), the packs say so instead of presenting them as active gates.
"""
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from src.db_models.process_workflows import ProcessWorkflowDb
from src.utils.demo_data_sql import _HEAD_RE, _find_statement_end

DATA_DIR = Path(__file__).resolve().parents[2] / 'data'
PACKS = sorted(DATA_DIR.glob('demo_data_*.sql'))
GATE_IDS = {
    '02a00101-0002-4000-8000-000000000001',  # FSI  BCBS 239 Pre-Publish Attestation
    '02a00101-0004-4000-8000-000000000001',  # AUTO OTA / Connected Services Release Gate
    '02a00101-0001-4000-8000-000000000001',  # HLS  IRB Approval Gate
    '02a00102-0001-4000-8000-000000000002',  # HLS  HIPAA PHI Pre-Publish Check
}


def workflow_inserts(pack: Path):
    """The pack's process_workflows INSERTs, runnable on the test database."""
    sql = pack.read_text(encoding='utf-8')
    for m in _HEAD_RE.finditer(sql):
        if m.group('table') == 'process_workflows':
            statement = sql[m.start():_find_statement_end(sql, m.end())]
            yield re.sub(r'\bNOW\(\)', 'CURRENT_TIMESTAMP', statement)


def load_pack_workflows(db, pack: Path):
    for statement in workflow_inserts(pack):
        db.execute(text(statement))
    db.flush()


def test_the_packs_are_found():
    assert {p.stem for p in PACKS} >= {
        'demo_data_auto', 'demo_data_fsi', 'demo_data_hls', 'demo_data_mfg', 'demo_data_retail',
    }


@pytest.mark.parametrize('pack', PACKS, ids=lambda p: p.stem)
def test_no_pack_ships_an_active_before_publish_workflow(db_session, pack):
    load_pack_workflows(db_session, pack)

    rows = db_session.query(ProcessWorkflowDb).all()
    gates = [r for r in rows if json.loads(r.trigger_config)['type'] == 'before_publish']
    assert {r.id for r in gates} <= GATE_IDS
    for row in gates:
        assert row.is_active is False, row.name
        assert 'Example only, inactive' in row.description, row.name
        assert '#997' in row.description, row.name


def test_all_four_gates_are_still_shipped(db_session):
    for pack in PACKS:
        load_pack_workflows(db_session, pack)

    found = db_session.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.id.in_(GATE_IDS)).all()
    assert len(found) == 4


def test_the_other_demo_workflows_keep_their_state(db_session):
    load_pack_workflows(db_session, DATA_DIR / 'demo_data_fsi.sql')

    aml = db_session.get(ProcessWorkflowDb, '02a00102-0002-4000-8000-000000000002')
    assert aml.name == 'AML Model Validation Gate'
    assert aml.is_active is True


# --- Installs that loaded an earlier version of a pack ----------------------------
# The INSERTs are ON CONFLICT DO NOTHING, so a reload doesn't change existing rows;
# the packs deactivate a gate in place only while it is still the shipped one.

DEACTIVATION = re.compile(
    r"^UPDATE process_workflows SET is_active = false\nWHERE id = '(?P<id>[^']+)'\n.*?;$",
    re.M | re.S,
)
NOTE = re.compile(
    r"^UPDATE process_workflows SET description = '(?:[^']|'')*'\nWHERE id = '(?P<id>[^']+)'\n"
    r".*?;$",
    re.M | re.S,
)
DESCRIPTION_CASE = re.compile(
    r"^UPDATE process_workflows SET description = CASE\n.*?\n  ELSE description END\n"
    r"WHERE id IN \([^)]*\);$",
    re.M | re.S,
)
EARLIER = {  # id -> (pack, name, trigger, description an earlier version shipped)
    '02a00101-0002-4000-8000-000000000001': (
        'fsi', 'BCBS 239 Pre-Publish Attestation',
        '{"type": "before_publish", "entity_types": ["data_product"]}',
        'Requires CRO sign-off before any risk product is published, per BCBS 239 principles.'),
    '02a00101-0004-4000-8000-000000000001': (
        'auto', 'OTA / Connected Services Release Gate',
        '{"type": "before_publish", "entity_types": ["data_product"]}',
        'Multi-stage approval gate before any connected-vehicle release: cybersecurity '
        'review, functional safety sign-off, program manager approval.'),
    '02a00101-0001-4000-8000-000000000001': (
        'hls', 'IRB Approval Gate',
        '{"type": "before_publish", "entity_types": ["data_product"]}',
        'Block publishing of clinical research data products until IRB approval is on file.'),
    '02a00102-0001-4000-8000-000000000002': (
        'hls', 'HIPAA PHI Pre-Publish Check',
        '{"type": "before_publish", "entity_types": ["data_product", "data_contract"]}',
        'Checks that HIPAA-scoped data products are tagged as de-identified, then requires '
        'Privacy Officer review, before any HLS data product is exposed to consumers.'),
}
HIPAA_OLDEST = ('Validates that PHI is de-identified or covered by a signed BAA before any '
                'HLS data product is exposed to consumers.')


def _earlier_gate(db, gate_id, **edit):
    _, name, trigger, description = EARLIER[gate_id]
    db.add(ProcessWorkflowDb(
        id=gate_id, name=edit.get('name', name), trigger_config=edit.get('trigger', trigger),
        description=edit.get('description', description), is_active=edit.get('active', True),
    ))
    db.flush()


def _reload_upgrades(db, pack):
    """The pack's in-place workflow upgrades, in file order (what a reload runs)."""
    sql = (DATA_DIR / f'demo_data_{pack}.sql').read_text(encoding='utf-8')
    statements = sorted(
        [(m.start(), m.group(0)) for m in DEACTIVATION.finditer(sql)]
        + [(m.start(), m.group(0)) for m in NOTE.finditer(sql)]
        + [(m.start(), m.group(0)) for m in DESCRIPTION_CASE.finditer(sql)]
    )
    for _, statement in statements:
        db.execute(text(statement))
    db.expire_all()


def test_every_gate_has_a_deactivation_and_a_note_update():
    found, noted = set(), set()
    for pack in {v[0] for v in EARLIER.values()}:
        sql = (DATA_DIR / f'demo_data_{pack}.sql').read_text(encoding='utf-8')
        found |= {m.group('id') for m in DEACTIVATION.finditer(sql)}
        noted |= {m.group('id') for m in NOTE.finditer(sql)}
    assert found == noted == GATE_IDS == set(EARLIER)


@pytest.mark.parametrize('gate_id', sorted(EARLIER))
def test_an_earlier_shipped_gate_is_deactivated_and_noted(db_session, gate_id):
    _earlier_gate(db_session, gate_id)

    _reload_upgrades(db_session, EARLIER[gate_id][0])

    row = db_session.get(ProcessWorkflowDb, gate_id)
    assert row.is_active is False
    assert row.description.startswith(EARLIER[gate_id][3])
    assert 'Example only, inactive' in row.description


def test_the_oldest_hipaa_text_is_upgraded_too(db_session):
    gate_id = '02a00102-0001-4000-8000-000000000002'
    _earlier_gate(db_session, gate_id, description=HIPAA_OLDEST)

    _reload_upgrades(db_session, 'hls')

    row = db_session.get(ProcessWorkflowDb, gate_id)
    assert row.is_active is False
    assert row.description.startswith(EARLIER[gate_id][3])
    assert 'Example only, inactive' in row.description


@pytest.mark.parametrize('gate_id', sorted(EARLIER))
@pytest.mark.parametrize('edit', [
    {'name': 'Our own gate'},
    {'trigger': '{"type": "on_request_publish", "entity_types": ["data_product"]}'},
    {'description': 'Our own text'},
], ids=['renamed', 're-triggered', 're-described'])
def test_a_gate_an_admin_edited_is_kept(db_session, gate_id, edit):
    _earlier_gate(db_session, gate_id, **edit)

    _reload_upgrades(db_session, EARLIER[gate_id][0])

    row = db_session.get(ProcessWorkflowDb, gate_id)
    assert row.is_active is True
    assert 'Example only' not in row.description


@pytest.mark.parametrize('gate_id', sorted(EARLIER))
def test_a_gate_re_activated_after_this_change_is_kept(db_session, gate_id):
    load_pack_workflows(db_session, DATA_DIR / f'demo_data_{EARLIER[gate_id][0]}.sql')
    row = db_session.get(ProcessWorkflowDb, gate_id)
    row.is_active = True
    db_session.flush()

    _reload_upgrades(db_session, EARLIER[gate_id][0])

    assert db_session.get(ProcessWorkflowDb, gate_id).is_active is True
