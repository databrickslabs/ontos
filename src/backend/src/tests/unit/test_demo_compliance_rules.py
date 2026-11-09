"""The compliance rules shipped with the demo presets evaluate real entities.

Most demo rules matched types no loader yields (Dataset, Account, Part, ...)
and some used syntax the DSL doesn't support (IS NOT NULL, datetime()),
which the parser silently dropped (#952). Each rule must also select at least
one entity of its own preset, or it reports green while checking nothing.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

from src.common.compliance_dsl import Lexer, Parser, TokenType, parse_actions, parse_rule
from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.common.compliance_entities import (
    AppEntityLoader,
    EntityIterator,
    UnityCatalogLoader,
    parse_entity_filter,
)

DATA_DIR = Path(__file__).resolve().parents[2] / 'data'
PRESETS = ['fsi', 'hls', 'auto', 'mfg', 'retail']
SUPPORTED_TYPES = (
    set(AppEntityLoader(None).get_supported_types())
    | set(UnityCatalogLoader(None).get_supported_types())
    | {'Object'}
)


def _sql_string(raw: str) -> str:
    if raw.startswith("E'"):
        return raw[2:-1].replace("''", "'").encode().decode('unicode_escape')
    return raw[1:-1].replace("''", "'")


def _preset_rules(preset):
    sql = (DATA_DIR / f'demo_data_{preset}.sql').read_text()
    start = sql.index('INSERT INTO compliance_policies')
    block = sql[start:sql.index('ON CONFLICT', start)]
    rules = []
    for raw in re.findall(r"E?'(?:[^']|'')*'", block):
        rule = _sql_string(raw)
        if rule.lstrip().startswith('MATCH'):
            rules.append(rule)
    return rules


def _demo_rules():
    return [
        pytest.param(rule, id=f'{preset}:{rule[:40]}')
        for preset in PRESETS for rule in _preset_rules(preset)
    ]


def _parse_fully(rule: str):
    """Parse like parse_rule, then require that nothing is left over."""
    parser = Parser(Lexer(rule).tokenize())
    parser.expect(TokenType.MATCH)
    parser.expect(TokenType.LPAREN)
    parser.expect(TokenType.IDENTIFIER)
    parser.expect(TokenType.COLON)
    match_type = parser.expect(TokenType.IDENTIFIER).value
    parser.expect(TokenType.RPAREN)
    for clause in (TokenType.WHERE, TokenType.ASSERT):
        if parser.current().type == clause:
            parser.advance()
            parser.parse_expression()
    for clause in (TokenType.ON_PASS, TokenType.ON_FAIL):
        if parser.current().type == clause:
            parser.advance()
            parse_actions(parser)
    leftover = parser.current()
    assert leftover.type == TokenType.EOF, (
        f'unparsed input at line {leftover.line}, column {leftover.column}: {leftover.value!r}'
    )
    return match_type


def test_every_preset_ships_compliance_rules():
    assert len(_demo_rules()) == 21


@pytest.mark.parametrize('rule', _demo_rules())
def test_demo_rule_parses_completely(rule):
    _parse_fully(rule)


@pytest.mark.parametrize('rule', _demo_rules())
def test_demo_rule_matches_a_loaded_entity_type(rule):
    assert _parse_fully(rule) in SUPPORTED_TYPES


# The tables AppEntityLoader reads for data products, contracts and domains
# (with their tags and primary domain)
ENTITY_TABLES = (
    'data_domains', 'data_products', 'data_contracts', 'tag_namespaces', 'tags',
    'entity_tag_associations', 'entity_domain_associations',
)


def _load_preset_entities(db, preset):
    """Run the preset's INSERTs for ENTITY_TABLES on the SQLite test database."""
    sql = (DATA_DIR / f'demo_data_{preset}.sql').read_text()
    for statement, table in re.findall(r'^(INSERT INTO (\w+) \(.*?;)$', sql, re.M | re.S):
        if table not in ENTITY_TABLES:
            continue
        statement = re.sub(r'\bON CONFLICT\b.*?DO NOTHING', '', statement, flags=re.S)
        statement = statement.replace('INSERT INTO', 'INSERT OR IGNORE INTO', 1)
        db.execute(text(statement.replace('NOW()', 'CURRENT_TIMESTAMP')))
    db.flush()


def _app_entity_rules():
    app_types = set(AppEntityLoader(None).get_supported_types())
    return [
        pytest.param(preset, rule, id=f'{preset}:{rule[:40]}')
        for preset in PRESETS for rule in _preset_rules(preset)
        if _parse_fully(rule) in app_types
    ]


def test_every_app_entity_rule_is_checked_for_coverage():
    # Only retail's naming rule targets Unity Catalog objects, which need a workspace
    assert len(_app_entity_rules()) == 20


@pytest.mark.parametrize('preset,rule', _app_entity_rules())
def test_demo_rule_selects_entities_of_its_preset(db_session, preset, rule):
    _load_preset_entities(db_session, preset)

    selected = list(EntityIterator([AppEntityLoader(db_session)]).iterate(
        parse_entity_filter(rule, parsed=parse_rule(rule)),
    ))

    assert selected, 'the rule selects no entity of its preset, so it can never fail'


# --- Installs that loaded an earlier version of a preset -------------------

UPGRADE = re.compile(
    r"^(UPDATE compliance_policies SET\n.*?"
    r"WHERE id = '([0-9a-f-]+)'\n  AND rule = ('(?:[^']|'')*');)$",
    re.M | re.S,
)


def _upgrades(preset):
    sql = (DATA_DIR / f'demo_data_{preset}.sql').read_text()
    return [(stmt, pid, _sql_string(old)) for stmt, pid, old in UPGRADE.findall(sql)]


def _shipped_name(statement):
    return _sql_string(re.search(r"name = CASE WHEN name = ('(?:[^']|'')*')", statement).group(1))


def _policy(db, pid, name, rule):
    db.execute(
        text(
            "INSERT INTO compliance_policies (id, name, rule, category, severity, is_active,"
            " created_at, updated_at)"
            " VALUES (:id, :name, :rule, 'Governance', 'high', 1, CURRENT_TIMESTAMP,"
            " CURRENT_TIMESTAMP)"
        ),
        {'id': pid, 'name': name, 'rule': rule},
    )


def _run(db, statement):
    db.execute(text(statement.replace('NOW()', 'CURRENT_TIMESTAMP')))


def _row(db, pid):
    return db.execute(
        text('SELECT name, rule FROM compliance_policies WHERE id = :id'), {'id': pid}
    ).one()


@pytest.mark.parametrize('preset', PRESETS)
def test_every_rewritten_rule_has_an_upgrade(preset):
    # Each preset rewrote four rules (retail keeps its naming rule)
    assert len({pid for _, pid, _ in _upgrades(preset)}) == 4


@pytest.mark.parametrize('preset', PRESETS)
def test_an_earlier_demo_policy_is_upgraded_in_place(db_session, preset):
    for statement, pid, old_rule in _upgrades(preset):
        _policy(db_session, pid, _shipped_name(statement), old_rule)

        _run(db_session, statement)

        name, rule = _row(db_session, pid)
        assert rule != old_rule and rule in _preset_rules(preset)
        assert name != _shipped_name(statement)


@pytest.mark.parametrize('preset', PRESETS)
def test_a_policy_an_admin_edited_is_kept(db_session, preset):
    for statement, pid, old_rule in _upgrades(preset):
        edited = old_rule + " AND obj.name != 'x'"
        _policy(db_session, pid, 'Our own rule', edited)

        _run(db_session, statement)

        assert tuple(_row(db_session, pid)) == ('Our own rule', edited)


# --- Sample runs and results ----------------------------------------------
#
# The presets insert sample compliance runs and results. They describe a run of
# the policies of their own preset, so a rename or a rewritten rule must not
# leave them showing the old checks. The ones on app entities are compared with
# a real run of the policy over the preset's entities.

LITERAL = r"'(?:[^']|'')*'"
RUN_ROW = re.compile(
    r"^\('([^']+)', '([^']+)', '(\w+)', NOW\(\) - INTERVAL '[^']+', "
    r"NOW\(\) - INTERVAL '[^']+' \+ INTERVAL '[^']+',\s*(\d+),\s*(\d+),\s*([\d.]+)\)",
    re.M,
)
RESULT_ROW = re.compile(
    rf"^\('([^']+)', '([^']+)', '(\w+)', ({LITERAL}), ({LITERAL}), (true|false), "
    rf"(NULL|{LITERAL}), (?:NOW\(\)[^)]*)\)",
    re.M,
)


def _insert_block(preset, table):
    sql = (DATA_DIR / f'demo_data_{preset}.sql').read_text()
    start = sql.index(f'INSERT INTO {table} ')
    return sql[start:sql.index('ON CONFLICT', start)]


def _preset_policies(preset):
    """id -> (name, rule) of the policies the preset inserts."""
    literals = [_sql_string(raw) for raw in re.findall(
        r"E?'(?:[^']|'')*'", _insert_block(preset, 'compliance_policies'))]
    # id, name, description, failure_message, rule, category, severity
    return {row[0]: (row[1], row[4]) for row in zip(*[iter(literals)] * 7)}


def _sample_runs(preset):
    return [
        {'id': i, 'policy_id': pid, 'status': status, 'success': int(ok),
         'failure': int(failed), 'score': float(score)}
        for i, pid, status, ok, failed, score
        in RUN_ROW.findall(_insert_block(preset, 'compliance_runs'))
    ]


def _sample_results(preset):
    return [
        {'id': i, 'run_id': run_id, 'type': otype, 'object_id': _sql_string(oid),
         'name': _sql_string(name), 'passed': passed == 'true',
         'message': None if message == 'NULL' else _sql_string(message)}
        for i, run_id, otype, oid, name, passed, message
        in RESULT_ROW.findall(_insert_block(preset, 'compliance_results'))
    ]


@pytest.mark.parametrize('preset', PRESETS)
def test_every_sample_run_and_result_is_parsed(preset):
    runs, results = _sample_runs(preset), _sample_results(preset)
    assert runs and results
    assert len(runs) == _insert_block(preset, 'compliance_runs').count("\n('")
    assert len(results) == _insert_block(preset, 'compliance_results').count("\n('")


@pytest.mark.parametrize('preset', PRESETS)
def test_sample_runs_and_results_belong_to_the_preset(preset):
    policies, runs = _preset_policies(preset), _sample_runs(preset)
    assert {run['policy_id'] for run in runs} <= set(policies)
    assert {res['run_id'] for res in _sample_results(preset)} <= {run['id'] for run in runs}


def _sample_run_cases():
    app_types = set(AppEntityLoader(None).get_supported_types())
    return [
        pytest.param(preset, run['id'], id=f"{preset}:{run['id'][:8]}-{run['id'][-3:]}")
        for preset in PRESETS for run in _sample_runs(preset)
        if _parse_fully(_preset_policies(preset)[run['policy_id']][1]) in app_types
    ]


def test_sample_runs_of_app_entity_policies_are_covered():
    # Retail's two runs of its naming policy describe Unity Catalog objects,
    # which need a workspace
    assert len(_sample_run_cases()) == 14


@pytest.mark.parametrize('preset,run_id', _sample_run_cases())
def test_sample_run_matches_a_real_run_of_its_policy(db_session, preset, run_id):
    _load_preset_entities(db_session, preset)
    run = next(r for r in _sample_runs(preset) if r['id'] == run_id)
    name, rule = _preset_policies(preset)[run['policy_id']]
    policy = CompliancePolicyDb(
        id=run['policy_id'], name=name, rule=rule, category='Governance', severity='high',
        is_active=True,
    )
    db_session.add(policy)
    db_session.flush()

    with patch('src.common.workspace_client.get_workspace_client', return_value=None):
        real = ComplianceManager().run_policy_inline(db_session, policy=policy)

    def outcome(rows):
        return sorted(
            (r['type'], r['object_id'], r['name'], r['passed'], r['message']) for r in rows
        )

    samples = [r for r in _sample_results(preset) if r['run_id'] == run_id]
    actual = [
        {'type': r.object_type, 'object_id': r.object_id, 'name': r.object_name,
         'passed': r.passed, 'message': r.message}
        for r in real.results
    ]
    assert outcome(samples) == outcome(actual)
    assert (run['status'], run['success'], run['failure']) == (
        real.status, real.success_count, real.failure_count)
    assert run['score'] == pytest.approx(real.score)


# --- Demo workflows ---------------------------------------------------------
#
# The workflows call the renamed policies by id. Their names, step names and
# messages must say what those policies check.

WORKFLOW_PRESETS = ['fsi', 'hls', 'retail']
WORKFLOW_COUNTS = {  # workflows, steps (retail: the policy workflows, 02a/02b)
    'fsi': (2, 3), 'hls': (2, 4), 'auto': (1, 3), 'mfg': (1, 2), 'retail': (5, 21),
}
# The words of the checks the policies used to describe
STALE_WORDS = re.compile(
    r'encrypt|fresh|stale|access control|access failure|lineage coverage|document present'
    r'|phi classification|\bBAA\b',
    re.I,
)
# Retail's policies used to be data quality checks; in other presets "quality" is a role
STALE_RETAIL_WORDS = re.compile(r'quality', re.I)
WORKFLOW_UPDATE = re.compile(
    r"^UPDATE (process_workflows|workflow_steps) SET (\w+) = CASE\n(.*?)\n  ELSE \w+ END\n"
    r"WHERE id IN \([^)]*\);$",
    re.M | re.S,
)
WHEN = re.compile(rf"WHEN id = ({LITERAL}) AND \w+ = ({LITERAL}) THEN ({LITERAL})")


def _preset_sql(preset):
    return (DATA_DIR / f'demo_data_{preset}.sql').read_text()


def _shipped_workflow_rows(preset):
    """(table, id) -> values of what the preset inserts for its workflows and steps."""
    sql = _preset_sql(preset)
    rows = {}
    for table, columns in (
        ('process_workflows', ('id', 'name', 'description')),
        ('workflow_steps', ('id', 'workflow_id', 'step_id', 'name', 'step_type', 'config')),
    ):
        start = sql.index(f'INSERT INTO {table} ')
        block = sql[start:sql.index('ON CONFLICT', start)]
        for chunk in re.split(r"^(?=\('02[ab]0)", block, flags=re.M)[1:]:
            literals = [_sql_string(raw) for raw in re.findall(LITERAL, chunk)]
            values = dict(zip(columns, literals))
            rows[(table, values['id'])] = values
    return rows


@pytest.mark.parametrize('preset', PRESETS)
def test_the_workflows_and_steps_of_a_preset_are_parsed(preset):
    rows = _shipped_workflow_rows(preset)
    assert (
        len([k for k in rows if k[0] == 'process_workflows']),
        len([k for k in rows if k[0] == 'workflow_steps']),
    ) == WORKFLOW_COUNTS[preset]


@pytest.mark.parametrize('preset', PRESETS)
def test_workflows_do_not_describe_the_old_checks(preset):
    words = [STALE_WORDS] + ([STALE_RETAIL_WORDS] if preset == 'retail' else [])
    for (_, row_id), values in _shipped_workflow_rows(preset).items():
        for column in ('name', 'description', 'config'):
            for pattern in words:
                assert not pattern.search(values.get(column) or ''), (row_id, column)


@pytest.mark.parametrize('preset', PRESETS)
def test_policy_check_steps_call_policies_of_the_preset(preset):
    policies = _preset_policies(preset)
    called = {
        re.search(r'"policy_id": "([^"]+)"', v['config']).group(1)
        for (table, _), v in _shipped_workflow_rows(preset).items()
        if table == 'workflow_steps' and v['step_type'] == 'policy_check'
    }
    assert called <= set(policies)
    assert called or preset in ('auto', 'mfg')


def _workflow_updates(preset):
    return [
        (table, column, [tuple(_sql_string(x) for x in when) for when in WHEN.findall(body)])
        for table, column, body in WORKFLOW_UPDATE.findall(_preset_sql(preset))
    ]


@pytest.mark.parametrize('preset', WORKFLOW_PRESETS)
def test_every_renamed_workflow_text_has_an_upgrade(preset):
    updates = _workflow_updates(preset)
    assert len(updates) == {'fsi': 1, 'hls': 2, 'retail': 4}[preset]
    shipped = _shipped_workflow_rows(preset)
    for table, column, whens in updates:
        for row_id, old, new in whens:
            assert shipped[(table, row_id)][column] == new
            assert old != new


def _model(table):
    return ProcessWorkflowDb if table == 'process_workflows' else WorkflowStepDb


def _earlier_rows(db, preset, edited=None):
    """The workflows and steps as an earlier install of the preset holds them."""
    shipped = _shipped_workflow_rows(preset)
    # The steps need their workflow
    for (table, row_id), values in shipped.items():
        if table == 'process_workflows':
            db.add(ProcessWorkflowDb(
                id=row_id, name=values['name'], description=values['description'],
                trigger_config='{}'))
    db.flush()
    for (table, row_id), values in shipped.items():
        if table == 'workflow_steps':
            db.add(WorkflowStepDb(
                id=row_id, workflow_id=values['workflow_id'], step_id=values['step_id'],
                name=values['name'], step_type=values['step_type'], config=values['config'],
                order=0))
    db.flush()
    for table, column, whens in _workflow_updates(preset):
        for row_id, old, _ in whens:
            setattr(db.get(_model(table), row_id), column, edited or old)
    db.flush()


def _upgrade_workflows(db, preset):
    for match in WORKFLOW_UPDATE.finditer(_preset_sql(preset)):
        db.execute(text(match.group(0)))
    db.expire_all()


@pytest.mark.parametrize('preset', WORKFLOW_PRESETS)
def test_an_earlier_workflow_is_renamed_in_place(db_session, preset):
    _earlier_rows(db_session, preset)
    _upgrade_workflows(db_session, preset)
    for table, column, whens in _workflow_updates(preset):
        for row_id, _, new in whens:
            assert getattr(db_session.get(_model(table), row_id), column) == new


@pytest.mark.parametrize('preset', WORKFLOW_PRESETS)
def test_a_workflow_text_an_admin_edited_is_kept(db_session, preset):
    _earlier_rows(db_session, preset, edited='Our own text')
    _upgrade_workflows(db_session, preset)
    for table, column, whens in _workflow_updates(preset):
        for row_id, _, _ in whens:
            assert getattr(db_session.get(_model(table), row_id), column) == 'Our own text'


# The Contract Purpose Gate (retail) is shipped disabled: its trigger never fires
GATE_ID = '02a00002-0000-4000-8000-000000000002'
GATE_TRIGGER = '{"type": "before_update", "entity_types": ["dataset"]}'
GATE_DEACTIVATION = re.compile(
    rf"^UPDATE process_workflows SET is_active = false\nWHERE id = '{GATE_ID}'\n.*?;$",
    re.M | re.S,
)


def _gate_insert():
    sql = _preset_sql('retail')
    start = sql.index(f"('{GATE_ID}'")
    return sql[start:sql.index('\n\n', start)]


def test_the_contract_purpose_gate_is_inserted_inactive():
    insert = _gate_insert()
    assert GATE_TRIGGER in insert
    # ..., scope_config, is_active, is_default, version, ...
    assert re.search(r"'\{\"type\": \"all\"\}',\s*false, true, 1,", insert)
    assert '#1149' in _shipped_workflow_rows('retail')[
        ('process_workflows', GATE_ID)]['description']


def _gate_row(db, name='Contract Purpose Gate', trigger=GATE_TRIGGER, active=True):
    db.add(ProcessWorkflowDb(
        id=GATE_ID, name=name, description='x', trigger_config=trigger, is_active=active))
    db.flush()


def _deactivate_gate(db):
    match = GATE_DEACTIVATION.search(_preset_sql('retail'))
    assert match
    db.execute(text(match.group(0)))
    db.expire_all()


@pytest.mark.parametrize('name', ['Contract Purpose Gate', 'Data Quality Gate'])
def test_an_earlier_contract_purpose_gate_is_deactivated(db_session, name):
    _gate_row(db_session, name=name)
    _deactivate_gate(db_session)
    assert db_session.get(ProcessWorkflowDb, GATE_ID).is_active is False


@pytest.mark.parametrize('edit', [
    {'name': 'Our own gate'},
    {'trigger': '{"type": "before_status_change", "entity_types": ["data_contract"]}'},
])
def test_a_contract_purpose_gate_an_admin_edited_is_kept(db_session, edit):
    _gate_row(db_session, **edit)
    _deactivate_gate(db_session)
    assert db_session.get(ProcessWorkflowDb, GATE_ID).is_active is True
