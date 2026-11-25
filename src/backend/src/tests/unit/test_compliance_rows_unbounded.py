"""A compliance run reads every stored row, in a deterministic order.

``AppEntityLoader._rows`` used to call ``get_multi(limit=1000)`` with no ORDER BY,
so a run over more than 1,000 rows silently checked an arbitrary 1,000 of them.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.common.compliance_entities import AppEntityLoader


def test_rows_reads_all_rows_in_id_order():
    rows = [SimpleNamespace(id=i) for i in ('c', 'a', 'b')]
    repo = MagicMock()
    repo.get_multi.return_value = rows

    loader = AppEntityLoader(MagicMock())
    result = loader._rows(repo, None, is_admin=True)

    assert [r.id for r in result] == ['a', 'b', 'c']
    repo.get_multi.assert_called_once()
    kwargs = repo.get_multi.call_args.kwargs
    assert kwargs.get('limit') is None
    assert kwargs.get('is_admin') is True
