"""SQL script step placeholders: what can be bound, and the bound statement.

``check_sql_placeholders`` lists the placeholders a SQL step can't bind (refused on
save and at run time); ``bind_sql_placeholders`` turns the others into named
parameters (``:p0``, ``:p1``...) so a value is never pasted into the SQL text.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest

from src.common.workflow_sql_params import (
    SQL_PLACEHOLDER_AS_LIST,
    SQL_PLACEHOLDER_IN_IDENTIFIER,
    SQL_PLACEHOLDER_IN_QUOTES,
    SQL_PLACEHOLDER_TYPED_LITERAL,
    bind_sql_placeholders,
    check_sql_placeholders,
)


def _issues(code):
    return [(i['code'], i['params']['placeholder']) for i in check_sql_placeholders(code)]


# --- check_sql_placeholders: placeholders that can be bound ---------------------

@pytest.mark.parametrize('code', [
    'SELECT 1',
    '',
    'SELECT * FROM ${entity_id}',
    'select * from {{entity_id}} t',
    'SELECT 1 FROM a JOIN ${other} b ON a.id = b.id',
    'INSERT INTO ${target} VALUES (${value})',
    'UPDATE ${target} SET owner = ${user_email}',
    'SELECT * FROM t WHERE name = ${entity_name}',
    "SELECT * FROM t WHERE name = '${entity_name}'",
    'SELECT * FROM IDENTIFIER(${entity_id})',
    "SELECT * FROM IDENTIFIER(concat('main.', ${schema}, '.t'))",
    "SELECT * FROM t WHERE name LIKE concat('%', ${entity_name}, '%')",
    'SELECT * FROM t WHERE id IN (${a}, ${b})',
    'SELECT * FROM t WHERE id IN (${a}, 1)',
    # {{x}} spelling with spaces around the name
    'SELECT * FROM t WHERE name = {{ entity_name }}',
])
def test_a_placeholder_that_can_be_bound_has_no_issue(code):
    assert check_sql_placeholders(code) == []


def test_none_code_has_no_issue():
    assert check_sql_placeholders(None) == []


# --- check_sql_placeholders: placeholders that can't ---------------------------

@pytest.mark.parametrize('code, expected', [
    # inside a longer quoted text
    ("SELECT * FROM t WHERE name LIKE '%${n}%'", [(SQL_PLACEHOLDER_IN_QUOTES, '${n}')]),
    ("SELECT * FROM t WHERE name LIKE '%{{n}}%'", [(SQL_PLACEHOLDER_IN_QUOTES, '{{n}}')]),
    ("SELECT * FROM t WHERE name = 'x ${n}'", [(SQL_PLACEHOLDER_IN_QUOTES, '${n}')]),
    # an escaped quote does not end the text
    ("SELECT * FROM t WHERE name = 'it\\'s ${n}'", [(SQL_PLACEHOLDER_IN_QUOTES, '${n}')]),
    # double quotes and backticks, even for a whole-text placeholder
    ('SELECT * FROM t WHERE name = "${n}"', [(SQL_PLACEHOLDER_IN_QUOTES, '${n}')]),
    ('SELECT * FROM `${n}`', [(SQL_PLACEHOLDER_IN_QUOTES, '${n}')]),
    # glued to name text
    ('SELECT * FROM main.${schema}', [(SQL_PLACEHOLDER_IN_IDENTIFIER, '${schema}')]),
    ('SELECT * FROM {{schema}}.t', [(SQL_PLACEHOLDER_IN_IDENTIFIER, '{{schema}}')]),
    ('SELECT * FROM t_${suffix}', [(SQL_PLACEHOLDER_IN_IDENTIFIER, '${suffix}')]),
    ('SELECT * FROM ${a}${b}', [
        (SQL_PLACEHOLDER_IN_IDENTIFIER, '${a}'), (SQL_PLACEHOLDER_IN_IDENTIFIER, '${b}'),
    ]),
    # the whole list of an IN (...)
    ('SELECT * FROM t WHERE id IN (${ids})', [(SQL_PLACEHOLDER_AS_LIST, '${ids}')]),
    ('SELECT * FROM t WHERE id in ( {{ids}} )', [(SQL_PLACEHOLDER_AS_LIST, '{{ids}}')]),
])
def test_a_placeholder_that_cannot_be_bound_is_reported(code, expected):
    assert _issues(code) == expected


@pytest.mark.parametrize('code, keyword', [
    ("SELECT * FROM t WHERE d = DATE '${d}'", 'DATE'),
    ("SELECT * FROM t WHERE d > timestamp '${t}'", 'timestamp'),
    ("SELECT TIMESTAMP_NTZ\n'${t}'", 'TIMESTAMP_NTZ'),
    ("SELECT INTERVAL '${n}' DAY", 'INTERVAL'),
    ("SELECT X'${h}'", 'X'),
    ("SELECT DATE'${d}'", 'DATE'),
    ("SELECT r'${s}'", 'r'),
    ("SELECT b'${s}'", 'b'),
])
def test_a_typed_or_prefixed_literal_is_refused_with_its_keyword(code, keyword):
    [issue] = check_sql_placeholders(code)

    assert issue['code'] == SQL_PLACEHOLDER_TYPED_LITERAL
    assert issue['params']['keyword'] == keyword
    assert issue['params']['placeholder'].startswith('${')
    assert 'CAST(' in issue['message']


@pytest.mark.parametrize('code', [
    "SELECT CAST('${d}' AS DATE)",
    "SELECT * FROM t WHERE d = CAST('{{d}}' AS TIMESTAMP)",
    "SELECT * FROM t WHERE name = '${n}'",
    "SELECT * FROM t WHERE name LIKE '${n}'",
    "SELECT '${n}' AS date",
    "-- date\nSELECT '${n}'",
    "SELECT 'a date', '${n}'",
])
def test_a_plain_literal_after_other_words_is_still_bound(code):
    assert check_sql_placeholders(code) == []


def test_cast_of_a_quoted_placeholder_binds_cleanly():
    statement, params = bind_sql_placeholders(
        "SELECT CAST('${d}' AS DATE)", _resolver({'d': '2025-01-31'}),
    )

    assert statement == 'SELECT CAST(:p0 AS DATE)'
    assert params == [('p0', '2025-01-31')]


def test_an_issue_carries_the_placeholder_and_an_english_message():
    [issue] = check_sql_placeholders("SELECT * FROM t WHERE name LIKE '%${n}%'")

    assert issue['code'] == SQL_PLACEHOLDER_IN_QUOTES
    assert issue['params'] == {'placeholder': '${n}'}
    assert '${n}' in issue['message']


def test_the_same_placeholder_written_the_same_wrong_way_is_reported_once():
    code = "SELECT * FROM t WHERE a LIKE '%${n}%' OR b LIKE '${n}%' OR c = 'x ${n}'"

    assert _issues(code) == [(SQL_PLACEHOLDER_IN_QUOTES, '${n}')]


def test_two_different_placeholders_are_both_reported():
    code = "SELECT * FROM t WHERE a LIKE '%${n}%' OR b LIKE '%${m}%'"

    assert _issues(code) == [
        (SQL_PLACEHOLDER_IN_QUOTES, '${n}'), (SQL_PLACEHOLDER_IN_QUOTES, '${m}'),
    ]


def test_the_same_placeholder_wrong_in_two_ways_is_reported_for_each():
    code = "SELECT * FROM main.${n} WHERE a LIKE '%${n}%'"

    assert sorted(code_ for code_, _ in _issues(code)) == [
        SQL_PLACEHOLDER_IN_IDENTIFIER, SQL_PLACEHOLDER_IN_QUOTES,
    ]


@pytest.mark.parametrize('code', [
    'SELECT 1 -- main.${n}\n',
    'SELECT 1 -- IN (${n})',
    "SELECT 1 /* LIKE '%${n}%' */",
    "SELECT 1 /* unterminated '%${n}%'",
])
def test_a_placeholder_in_a_comment_is_left_alone(code):
    assert check_sql_placeholders(code) == []


def test_code_after_a_comment_is_still_checked():
    code = "-- a note\n/* another */ SELECT * FROM t WHERE a LIKE '%${n}%'"

    assert _issues(code) == [(SQL_PLACEHOLDER_IN_QUOTES, '${n}')]


# --- bind_sql_placeholders --------------------------------------------------------

def _resolver(values):
    return lambda name: values.get(name)


def test_a_value_is_bound_as_a_parameter():
    statement, params = bind_sql_placeholders(
        'SELECT * FROM audit WHERE name = ${entity_name}',
        _resolver({'entity_name': 'orders'}),
    )

    assert statement == 'SELECT * FROM audit WHERE name = :p0'
    assert params == [('p0', 'orders')]


def test_a_whole_quoted_literal_loses_its_quotes():
    statement, params = bind_sql_placeholders(
        "SELECT * FROM audit WHERE name = '${entity_name}'",
        _resolver({'entity_name': "x'; DROP TABLE t; --"}),
    )

    assert statement == 'SELECT * FROM audit WHERE name = :p0'
    assert params == [('p0', "x'; DROP TABLE t; --")]


@pytest.mark.parametrize('code, statement', [
    ('SELECT * FROM ${t}', 'SELECT * FROM IDENTIFIER(:p0)'),
    ('select * from {{t}} x', 'select * from IDENTIFIER(:p0) x'),
    ('SELECT * FROM a JOIN ${t} b', 'SELECT * FROM a JOIN IDENTIFIER(:p0) b'),
    ('INSERT INTO ${t} VALUES (1)', 'INSERT INTO IDENTIFIER(:p0) VALUES (1)'),
    ('UPDATE ${t} SET a = 1', 'UPDATE IDENTIFIER(:p0) SET a = 1'),
    ('SELECT IDENTIFIER(${t})', 'SELECT IDENTIFIER(:p0)'),
])
def test_a_table_is_bound_through_identifier(code, statement):
    assert bind_sql_placeholders(code, _resolver({'t': 'main.sales.orders'})) == (
        statement, [('p0', 'main.sales.orders')],
    )


@pytest.mark.parametrize('code, statement', [
    ('SELECT * FROM t WHERE a IS DISTINCT FROM ${v}',
     'SELECT * FROM t WHERE a IS DISTINCT FROM :p0'),
    ('SELECT * FROM t WHERE a IS NOT DISTINCT FROM ${v}',
     'SELECT * FROM t WHERE a IS NOT DISTINCT FROM :p0'),
    ('SELECT EXTRACT(YEAR FROM ${v})', 'SELECT EXTRACT(YEAR FROM :p0)'),
    ("SELECT TRIM(BOTH ' ' FROM ${v})", "SELECT TRIM(BOTH ' ' FROM :p0)"),
    ('SELECT SUBSTRING(s FROM ${v})', 'SELECT SUBSTRING(s FROM :p0)'),
    ('SELECT * FROM ${v}', 'SELECT * FROM IDENTIFIER(:p0)'),
    ('SELECT * FROM (SELECT * FROM ${v})', 'SELECT * FROM (SELECT * FROM IDENTIFIER(:p0))'),
    ('SELECT * FROM t WHERE x IN (WITH c AS (SELECT 1) SELECT a FROM ${v})',
     'SELECT * FROM t WHERE x IN (WITH c AS (SELECT 1) SELECT a FROM IDENTIFIER(:p0))'),
    # a closed function call before the FROM does not hide it
    ('SELECT EXTRACT(YEAR FROM d), (SELECT 1 FROM ${v})',
     'SELECT EXTRACT(YEAR FROM d), (SELECT 1 FROM IDENTIFIER(:p0))'),
    ('SELECT max(x) FROM ${v}', 'SELECT max(x) FROM IDENTIFIER(:p0)'),
])
def test_from_names_a_table_only_where_a_table_can_stand(code, statement):
    assert bind_sql_placeholders(code, _resolver({'v': 'val'}))[0] == statement


@pytest.mark.parametrize('code, statement', [
    ('SELECT * FROM ${v}, ${v}', 'SELECT * FROM IDENTIFIER(:p0), IDENTIFIER(:p1)'),
    ('SELECT * FROM a, ${v} WHERE a.id = 1', 'SELECT * FROM a, IDENTIFIER(:p0) WHERE a.id = 1'),
    ('SELECT * FROM a x, b y, ${v} z', 'SELECT * FROM a x, b y, IDENTIFIER(:p0) z'),
    ('SELECT * FROM (SELECT * FROM a, ${v})', 'SELECT * FROM (SELECT * FROM a, IDENTIFIER(:p0))'),
    ('CREATE TABLE IF NOT EXISTS ${v} (a INT)',
     'CREATE TABLE IF NOT EXISTS IDENTIFIER(:p0) (a INT)'),
    ('DROP TABLE IF EXISTS ${v}', 'DROP TABLE IF EXISTS IDENTIFIER(:p0)'),
    ('MERGE INTO x USING ${v} ON x.id = 1', 'MERGE INTO x USING IDENTIFIER(:p0) ON x.id = 1'),
    ('INSERT OVERWRITE ${v} SELECT 1', 'INSERT OVERWRITE IDENTIFIER(:p0) SELECT 1'),
    ('OPTIMIZE ${v}', 'OPTIMIZE IDENTIFIER(:p0)'),
    ('VACUUM ${v}', 'VACUUM IDENTIFIER(:p0)'),
    ('DESCRIBE ${v}', 'DESCRIBE IDENTIFIER(:p0)'),
    ('DESCRIBE TABLE ${v}', 'DESCRIBE TABLE IDENTIFIER(:p0)'),
    ('DESCRIBE EXTENDED ${v}', 'DESCRIBE EXTENDED IDENTIFIER(:p0)'),
    ('DESCRIBE DETAIL ${v}', 'DESCRIBE DETAIL IDENTIFIER(:p0)'),
    ('DESCRIBE HISTORY ${v}', 'DESCRIBE HISTORY IDENTIFIER(:p0)'),
    ('ANALYZE TABLE ${v} COMPUTE STATISTICS', 'ANALYZE TABLE IDENTIFIER(:p0) COMPUTE STATISTICS'),
])
def test_more_table_positions_bind_through_identifier(code, statement):
    assert bind_sql_placeholders(code, _resolver({'v': 'val'}))[0] == statement


@pytest.mark.parametrize('code, statement', [
    # an explicit IDENTIFIER keeps working: bound inside, not wrapped twice
    ('SELECT * FROM IDENTIFIER(${v})', 'SELECT * FROM IDENTIFIER(:p0)'),
    ('SELECT * FROM a, IDENTIFIER(${v})', 'SELECT * FROM a, IDENTIFIER(:p0)'),
    ('OPTIMIZE IDENTIFIER(${v})', 'OPTIMIZE IDENTIFIER(:p0)'),
    # commas elsewhere are values
    ('SELECT a, ${v} FROM t', 'SELECT a, :p0 FROM t'),
    ('SELECT * FROM t WHERE a IN (1, ${v})', 'SELECT * FROM t WHERE a IN (1, :p0)'),
    ('SELECT * FROM t WHERE a = 1 AND b IN (SELECT 1), ${v}',
     'SELECT * FROM t WHERE a = 1 AND b IN (SELECT 1), :p0'),
    ('SELECT concat(a, ${v}) FROM t', 'SELECT concat(a, :p0) FROM t'),
    ('SELECT EXTRACT(YEAR FROM a), ${v} FROM t', 'SELECT EXTRACT(YEAR FROM a), :p0 FROM t'),
    ('CREATE TABLE t USING delta LOCATION ${v}', 'CREATE TABLE t USING delta LOCATION :p0'),
    ('SELECT * FROM a JOIN b USING (id) WHERE x = ${v}',
     'SELECT * FROM a JOIN b USING (id) WHERE x = :p0'),
])
def test_other_positions_stay_values(code, statement):
    assert bind_sql_placeholders(code, _resolver({'v': 'val'}))[0] == statement


def test_an_unresolved_placeholder_is_left_as_written_and_takes_no_number():
    statement, params = bind_sql_placeholders(
        "SELECT * FROM t WHERE a = ${known} AND b = ${missing} AND c = {{known}}",
        _resolver({'known': 'k'}),
    )

    assert statement == 'SELECT * FROM t WHERE a = :p0 AND b = ${missing} AND c = :p1'
    assert params == [('p0', 'k'), ('p1', 'k')]


def test_an_unresolved_whole_literal_drops_its_quotes():
    statement, params = bind_sql_placeholders(
        "SELECT * FROM t WHERE a = '${missing}'", _resolver({}),
    )

    assert statement == 'SELECT * FROM t WHERE a = ${missing}'
    assert params == []


def test_a_placeholder_in_a_comment_is_left_as_written():
    statement, params = bind_sql_placeholders(
        "SELECT * FROM t -- by ${user_email}\nWHERE a = ${a} /* ${a} */",
        _resolver({'user_email': 'u@x.io', 'a': 'A'}),
    )

    assert statement == 'SELECT * FROM t -- by ${user_email}\nWHERE a = :p0 /* ${a} */'
    assert params == [('p0', 'A')]


def test_placeholders_are_numbered_left_to_right_across_both_spellings():
    statement, params = bind_sql_placeholders(
        "SELECT * FROM ${t} WHERE a = {{a}} AND b = '${b}' AND c = ${c}",
        _resolver({'t': 'cat.sch.t', 'a': 'A', 'b': 'B', 'c': 'C'}),
    )

    assert statement == (
        'SELECT * FROM IDENTIFIER(:p0) WHERE a = :p1 AND b = :p2 AND c = :p3'
    )
    assert params == [('p0', 'cat.sch.t'), ('p1', 'A'), ('p2', 'B'), ('p3', 'C')]


def test_a_placeholder_written_twice_is_bound_twice():
    statement, params = bind_sql_placeholders(
        'SELECT ${a}, ${a}', _resolver({'a': 'A'}),
    )

    assert statement == 'SELECT :p0, :p1'
    assert params == [('p0', 'A'), ('p1', 'A')]


def test_a_placeholder_that_cannot_be_bound_is_left_as_written():
    code = "SELECT * FROM t WHERE a LIKE '%${n}%' AND b = ${n}"

    statement, params = bind_sql_placeholders(code, _resolver({'n': 'N'}))

    assert statement == "SELECT * FROM t WHERE a LIKE '%${n}%' AND b = :p0"
    assert params == [('p0', 'N')]


def test_the_name_is_stripped_before_it_is_resolved():
    seen = []

    def resolve(name):
        seen.append(name)
        return 'V'

    statement, _ = bind_sql_placeholders('SELECT {{ entity_name }}', resolve)

    assert seen == ['entity_name']
    assert statement == 'SELECT :p0'


def test_code_without_placeholders_is_unchanged():
    code = "SELECT 'a${' FROM t"

    assert bind_sql_placeholders(code, _resolver({})) == (code, [])
