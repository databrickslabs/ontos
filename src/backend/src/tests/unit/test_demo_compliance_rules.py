"""The compliance rules shipped with the demo presets evaluate real entities.

Most demo rules matched types no loader yields (Dataset, Account, Part, ...)
and some used syntax the DSL doesn't support (IS NOT NULL, datetime()),
which the parser silently dropped (#952).
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import re
from pathlib import Path

import pytest

from src.common.compliance_dsl import Lexer, Parser, TokenType, parse_actions
from src.common.compliance_entities import AppEntityLoader, UnityCatalogLoader

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


def _demo_rules():
    rules = []
    for preset in PRESETS:
        sql = (DATA_DIR / f'demo_data_{preset}.sql').read_text()
        start = sql.index('INSERT INTO compliance_policies')
        block = sql[start:sql.index('ON CONFLICT', start)]
        for raw in re.findall(r"E?'(?:[^']|'')*'", block):
            text = _sql_string(raw)
            if text.lstrip().startswith('MATCH'):
                rules.append(pytest.param(text, id=f'{preset}:{text[:40]}'))
    return rules


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
