"""Test fakes for Unity Catalog comments (#1477)."""
from unittest.mock import MagicMock


def reads_back_comment_writes(ws: MagicMock) -> MagicMock:
    """Make ``ws.tables.get`` answer with the comment the last successful statement wrote.

    As Unity Catalog does: after ``COMMENT ON TABLE|COLUMN ... IS ...`` on a table succeeds, it
    (or that column) reads with the new comment. Before any write to it, or when the
    statement's response is not SUCCEEDED, it answers with ``tables.get.return_value``.
    """
    import re
    from types import SimpleNamespace
    from unittest.mock import DEFAULT

    from databricks.sdk.service.sql import StatementState

    statement_re = re.compile(r"^COMMENT ON (TABLE|COLUMN) (.+?) IS (NULL|'(.*)')$", re.DOTALL)

    def last_write(full_name):
        """``(kind, target, literal)`` of the last statement on ``full_name``, or None."""
        table = '.'.join('`' + part.replace('`', '``') + '`' for part in full_name.split('.'))
        for call in reversed(ws.statement_execution.execute_statement.call_args_list):
            match = statement_re.match(call.kwargs.get('statement', ''))
            if match and (match.group(2) == table or match.group(2).startswith(table + '.')):
                return match.group(1), match.group(2), match.group(4)
        return None

    def read(full_name=None, **kwargs):
        status = getattr(ws.statement_execution.execute_statement.return_value, 'status', None)
        written = last_write(full_name or '')
        if written is None or getattr(status, 'state', None) != StatementState.SUCCEEDED:
            return DEFAULT
        kind, target, literal = written
        text = re.sub(r'\\(.)', r'\1', literal, flags=re.DOTALL) if literal is not None else None
        info = ws.tables.get.return_value
        if kind == 'TABLE':
            return SimpleNamespace(**{**vars(info), 'comment': text})
        column = re.search(r'\.`((?:[^`]|``)*)`$', target).group(1).replace('``', '`')
        columns = [SimpleNamespace(**{**vars(c), 'comment': text}) if c.name == column else c
                   for c in info.columns or []]
        return SimpleNamespace(**{**vars(info), 'columns': columns})

    ws.tables.get.side_effect = read
    return ws
