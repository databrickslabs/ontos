"""Placeholders of a SQL script step, bound as statement parameters.

A SQL step's ``${name}`` / ``{{name}}`` placeholders never become SQL text: each
resolved value is sent as a named parameter (``:p0``, ``:p1``...). Where it is
written decides how:

- after ``FROM``, ``JOIN``, ``INTO``, ``UPDATE`` or ``TABLE`` it names a table:
  ``IDENTIFIER(:pN)``;
- as a whole quoted literal (``'${name}'``) it is that literal: ``:pN``;
- anywhere else (``= ${name}``, ``IDENTIFIER(${name})``, ``concat('%', ${name})``)
  it is a value: ``:pN``.

Three places can't hold a parameter, so a step that uses them is refused on save
and at run time (``check_sql_placeholders``):

- inside a longer quoted text, double quotes or backticks (``'%${name}%'``):
  the parameter would be part of the text, not its value;
- glued to other identifier text (``cat.${schema}.t``, ``t_${name}``);
- as the whole list of an ``IN (...)``: the value is one string, so
  ``IN (${ids})`` would compare with that one string. A list stored in the
  entity is JSON: ``array_contains(from_json(${ids}, 'array<string>'), col)``.

Placeholders in comments are left as written. A placeholder that doesn't resolve
is left as written too (without the quotes of a whole literal), so the warehouse
reports it.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

PLACEHOLDER_RE = re.compile(r'\$\{([^}]+)\}|\{\{([^}]+)\}\}')

SQL_PLACEHOLDER_IN_QUOTES = 'script_sql_placeholder_in_quotes'
SQL_PLACEHOLDER_IN_IDENTIFIER = 'script_sql_placeholder_in_identifier'
SQL_PLACEHOLDER_AS_LIST = 'script_sql_placeholder_as_list'

# Keywords after which a placeholder names a table.
_TABLE_KEYWORDS = ('FROM', 'JOIN', 'INTO', 'UPDATE', 'TABLE')
_TABLE_KEYWORD_BEFORE = re.compile(r'\b(?:' + '|'.join(_TABLE_KEYWORDS) + r')\s*$', re.IGNORECASE)
_IN_LIST_BEFORE = re.compile(r'\bIN\s*\(\s*$', re.IGNORECASE)
_LIST_END_AFTER = re.compile(r'^\s*\)')
_IDENTIFIER_CHAR = re.compile(r'[A-Za-z0-9_.]')

_ISSUE_TEXT = {
    SQL_PLACEHOLDER_IN_QUOTES: (
        "Placeholder {placeholder} is inside quotes or backticks, where its value can't be "
        "bound. Write it on its own: name = {placeholder}, concat('%', {placeholder}, '%') "
        "or IDENTIFIER({placeholder})"
    ),
    SQL_PLACEHOLDER_IN_IDENTIFIER: (
        "Placeholder {placeholder} is part of a longer name. Build the name in "
        "IDENTIFIER(...), for example IDENTIFIER(concat('main.', {placeholder}))"
    ),
    SQL_PLACEHOLDER_AS_LIST: (
        "Placeholder {placeholder} is the whole list of an IN (...): its value is one "
        "string. Use = {placeholder} for one value, or "
        "array_contains(from_json({placeholder}, 'array<string>'), column) for a JSON list"
    ),
}


@dataclass
class _Placeholder:
    start: int  # span replaced in the statement (a whole literal includes its quotes)
    end: int
    text: str  # the placeholder as written, e.g. "${entity_name}"
    name: str
    kind: str  # 'value' | 'table' | one of the issue codes


def _issue(code: str, placeholder: str) -> Dict[str, Any]:
    return {
        'code': code,
        'params': {'placeholder': placeholder},
        'message': _ISSUE_TEXT[code].format(placeholder=placeholder),
    }


def _string_end(code: str, start: int, quote: str) -> int:
    """Index after the quoted text that opens at ``start`` (backslash escapes a character)."""
    i = start + 1
    while i < len(code):
        if code[i] == '\\' and quote != '`':
            i += 2
            continue
        if code[i] == quote:
            return i + 1
        i += 1
    return len(code)


def _scan(code: str) -> List[_Placeholder]:
    """Every placeholder outside comments, with what its position allows."""
    found: List[_Placeholder] = []
    # ``plain`` is the code outside quotes and comments, other characters as
    # spaces: what precedes or follows a placeholder there decides its kind.
    plain = [' '] * len(code)
    i = 0
    while i < len(code):
        ch = code[i]
        if code.startswith('--', i):
            end = code.find('\n', i)
            i = len(code) if end < 0 else end
            continue
        if code.startswith('/*', i):
            end = code.find('*/', i + 2)
            i = len(code) if end < 0 else end + 2
            continue
        if ch in ("'", '"', '`'):
            end = _string_end(code, i, ch)
            inner = code[i + 1:end - 1]
            whole = PLACEHOLDER_RE.fullmatch(inner)
            if ch == "'" and whole:
                found.append(_Placeholder(i, end, whole.group(0), _name(whole), 'value'))
                plain[i:end] = ['x'] * (end - i)
            else:
                for match in PLACEHOLDER_RE.finditer(inner):
                    at = i + 1 + match.start()
                    found.append(_Placeholder(
                        at, at + len(match.group(0)), match.group(0), _name(match),
                        SQL_PLACEHOLDER_IN_QUOTES,
                    ))
            i = end
            continue
        match = PLACEHOLDER_RE.match(code, i)
        if match:
            found.append(_Placeholder(i, match.end(), match.group(0), _name(match), ''))
            plain[i:match.end()] = ['x'] * (match.end() - i)
            i = match.end()
            continue
        plain[i] = ch
        i += 1

    text = ''.join(plain)
    for placeholder in found:
        if placeholder.kind:
            continue
        before, after = text[:placeholder.start], text[placeholder.end:]
        glued = (
            (placeholder.start > 0 and _IDENTIFIER_CHAR.match(code[placeholder.start - 1]))
            or (placeholder.end < len(code) and _IDENTIFIER_CHAR.match(code[placeholder.end]))
            or (placeholder.start > 0 and code[placeholder.start - 1] in '}`')
            or PLACEHOLDER_RE.match(code, placeholder.end)
        )
        if glued:
            placeholder.kind = SQL_PLACEHOLDER_IN_IDENTIFIER
        elif _IN_LIST_BEFORE.search(before) and _LIST_END_AFTER.match(after):
            placeholder.kind = SQL_PLACEHOLDER_AS_LIST
        elif _TABLE_KEYWORD_BEFORE.search(before):
            placeholder.kind = 'table'
        else:
            placeholder.kind = 'value'
    return found


def _name(match: 're.Match[str]') -> str:
    return (match.group(1) or match.group(2) or '').strip()


def check_sql_placeholders(code: str) -> List[Dict[str, Any]]:
    """Issues (``code``, ``params.placeholder``, English ``message``) of the
    placeholders a SQL step can't bind; empty when every one can be bound.
    A placeholder written the same wrong way twice is reported once."""
    seen = set()
    issues = []
    for p in _scan(code or ''):
        if p.kind in ('value', 'table') or (p.kind, p.text) in seen:
            continue
        seen.add((p.kind, p.text))
        issues.append(_issue(p.kind, p.text))
    return issues


def bind_sql_placeholders(
    code: str, resolve: Callable[[str], Optional[str]],
) -> Tuple[str, List[Tuple[str, str]]]:
    """The statement with parameter markers, and the ``(name, value)`` parameters.

    ``resolve`` returns a placeholder name's value, or None when it doesn't
    resolve. Call ``check_sql_placeholders`` first: a placeholder it reports is
    left as written here.
    """
    parameters: List[Tuple[str, str]] = []
    parts: List[str] = []
    last = 0
    for placeholder in _scan(code):
        if placeholder.kind not in ('value', 'table'):
            continue
        value = resolve(placeholder.name)
        if value is None:
            replacement = placeholder.text
        else:
            marker = f":p{len(parameters)}"
            parameters.append((marker[1:], value))
            replacement = f"IDENTIFIER({marker})" if placeholder.kind == 'table' else marker
        parts.append(code[last:placeholder.start])
        parts.append(replacement)
        last = placeholder.end
    parts.append(code[last:])
    return ''.join(parts), parameters
