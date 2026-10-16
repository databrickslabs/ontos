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

import pytest
from sqlalchemy import text

from src.common.compliance_dsl import Lexer, Parser, TokenType, parse_actions, parse_rule
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
