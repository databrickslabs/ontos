"""Parsing helpers for the self-contained demo-data SQL packs.

The demo packs (``src/data/demo_data_*.sql``) are plain ``INSERT`` scripts. Both
loading and teardown need to know *what rows a pack inserts* — historically the
teardown maintained a hand-written list of ``DELETE ... WHERE id LIKE '<prefix>%'``
statements that silently drifted out of sync with the packs (columns and tables
change under migrations, the prefix list does not), leaving orphaned rows behind.

Instead we derive teardown from the packs themselves: parse each ``INSERT`` to
recover ``(table, pk_column, [pk_values])`` in insertion order, then delete those
exact primary keys in reverse order. Deleting by the precise keys the pack wrote
is both drift-proof and safer than prefix matching (it can never touch a built-in
row that merely shares an id prefix).

The parser is a small SQL tokenizer aware of single-quoted strings (with ``''``
escapes), ``--`` line comments, and ``()``/``[]`` nesting (so ``COALESCE((SELECT
...))`` and JSON payloads containing commas parse correctly).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass
class DemoInsert:
    table: str
    pk_column: str
    pk_values: List[str]


def _strip_line_comments(s: str) -> str:
    """Remove ``-- ...`` comments that fall outside single-quoted strings."""
    out: List[str] = []
    in_q = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if in_q:
            out.append(c)
            if c == "'":
                if i + 1 < n and s[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_q = False
        else:
            if c == "'":
                in_q = True
                out.append(c)
            elif c == "-" and i + 1 < n and s[i + 1] == "-":
                j = s.find("\n", i)
                if j == -1:
                    break
                i = j
                continue
            else:
                out.append(c)
        i += 1
    return "".join(out)


def _first_field(row_inner: str) -> str:
    """Return the first top-level comma-separated field of a ``(...)`` row body,
    honoring quotes and nesting."""
    depth = 0
    in_q = False
    i, n = 0, len(row_inner)
    while i < n:
        c = row_inner[i]
        if in_q:
            if c == "'":
                if i + 1 < n and row_inner[i + 1] == "'":
                    i += 2
                    continue
                in_q = False
        else:
            if c == "'":
                in_q = True
            elif c in "([":
                depth += 1
            elif c in ")]":
                depth -= 1
            elif c == "," and depth == 0:
                return row_inner[:i].strip()
        i += 1
    return row_inner.strip()


def _iter_rows(values_region: str):
    """Yield the inner text of each top-level ``(...)`` group in a VALUES region."""
    values_region = _strip_line_comments(values_region)
    depth = 0
    in_q = False
    start = None
    i, n = 0, len(values_region)
    while i < n:
        c = values_region[i]
        if in_q:
            if c == "'":
                if i + 1 < n and values_region[i + 1] == "'":
                    i += 2
                    continue
                in_q = False
        else:
            if c == "'":
                in_q = True
            elif c == "(":
                if depth == 0:
                    start = i + 1
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0 and start is not None:
                    yield values_region[start:i]
                    start = None
        i += 1


def _unquote(tok: str) -> str:
    t = tok.strip()
    if len(t) >= 2 and t[0] == "'" and t[-1] == "'":
        return t[1:-1].replace("''", "'")
    return t


# Locate each statement head; the VALUES body and terminating ';' are found with
# a quote/paren-aware scan (NOT regex), because demo rows legitimately contain ';'
# inside quoted strings (e.g. contract descriptions), which a regex tail would
# mis-terminate on.
_HEAD_RE = re.compile(
    r"INSERT\s+INTO\s+(?P<table>[a-zA-Z_][\w]*)\s*"
    r"\((?P<cols>[^)]*)\)\s*VALUES",
    re.I,
)


def _find_statement_end(sql: str, start: int) -> int:
    """Return the index just past the ';' terminating the statement that begins at
    ``start``, scanning past ';' that appear inside single-quoted strings."""
    in_q = False
    i, n = start, len(sql)
    while i < n:
        c = sql[i]
        if in_q:
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    i += 2
                    continue
                in_q = False
        else:
            if c == "'":
                in_q = True
            elif c == ";":
                return i + 1
        i += 1
    return n


def parse_demo_inserts(sql: str) -> List[DemoInsert]:
    """Parse a demo-data SQL pack into an ordered list of ``DemoInsert``.

    Order mirrors the physical INSERT order in the file, which the packs keep
    FK-safe (parents before children); callers deleting for teardown should walk
    the result in reverse. The primary-key column is taken as the first column of
    each INSERT's column list (all packs lead with the row's own key, e.g. ``id``,
    or ``project_id`` for the ``project_teams`` junction).
    """
    inserts: List[DemoInsert] = []
    for m in _HEAD_RE.finditer(sql):
        cols = [c.strip() for c in m.group("cols").split(",") if c.strip()]
        if not cols:
            continue
        end = _find_statement_end(sql, m.end())
        values_region = sql[m.end():end]
        # Trim the trailing "ON CONFLICT (...) ..." clause so its parenthesised
        # column list is not mistaken for a VALUES row.
        oc = re.search(r"\bON\s+CONFLICT\b", values_region, re.I)
        if oc:
            values_region = values_region[:oc.start()]
        pk_col = cols[0]
        pk_values = [_unquote(_first_field(row)) for row in _iter_rows(values_region)]
        pk_values = [v for v in pk_values if v]
        if pk_values:
            inserts.append(DemoInsert(table=m.group("table"), pk_column=pk_col, pk_values=pk_values))
    return inserts
