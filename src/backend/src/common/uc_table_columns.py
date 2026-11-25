"""Column fields for Unity Catalog tables and views in compliance rules.

Pure helper: it makes no API call, it reads what the given ``TableInfo`` holds:
``columns`` (``name``, ``type_text``/``type_name``, ``comment``,
``partition_index``), which ``tables.list`` returns, and ``table_constraints``,
which ``tables.list`` does NOT return (only ``tables.get`` does: databricks-sdk
``TablesAPI.list`` docs). So the key fields are only valid on a ``TableInfo``
from ``tables.get``; the compliance loader, which lists tables, takes them from
``TableConstraintsReader`` (see ``uc_table_enrichment``) and leaves them out of
the listed entity. Other entity dicts that point to a UC table can reuse this
with a ``tables.get`` result.
"""

from typing import Any, Dict, List, Optional


def _has_comment(comment: Optional[str]) -> bool:
    # A whitespace-only comment documents nothing.
    return bool(comment and str(comment).strip())


def _column_type(column: Any) -> Optional[str]:
    type_text = getattr(column, 'type_text', None)
    if type_text:
        return type_text
    type_name = getattr(column, 'type_name', None)
    if type_name is None:
        return None
    return getattr(type_name, 'value', None) or str(type_name)


def _key_column_names(table: Any, kind: str) -> List[str]:
    """Names of the columns in the table's primary or foreign key constraints.

    ``kind`` is ``primary_key_constraint`` or ``foreign_key_constraint``; the names
    are the child columns, in constraint order, without repeats.
    """
    names: List[str] = []
    for constraint in (getattr(table, 'table_constraints', None) or []):
        key = getattr(constraint, kind, None)
        for name in (getattr(key, 'child_columns', None) or []):
            if name not in names:
                names.append(name)
    return names


# Fields that need ``table_constraints``, so a ``tables.get`` result
KEY_FIELDS = (
    'primary_key_columns',
    'foreign_key_columns',
    'primary_key_columns_without_comment_count',
    'foreign_key_columns_without_comment_count',
)


def key_column_fields(table: Any) -> Dict[str, Any]:
    """The ``KEY_FIELDS`` of one ``TableInfo`` that carries ``table_constraints``."""
    comments = {
        getattr(c, 'name', None): getattr(c, 'comment', None)
        for c in (getattr(table, 'columns', None) or [])
    }
    primary = _key_column_names(table, 'primary_key_constraint')
    foreign = _key_column_names(table, 'foreign_key_constraint')
    return {
        'primary_key_columns': primary,
        'foreign_key_columns': foreign,
        # A key column the table doesn't list has no comment either
        'primary_key_columns_without_comment_count': sum(
            1 for n in primary if not _has_comment(comments.get(n))
        ),
        'foreign_key_columns_without_comment_count': sum(
            1 for n in foreign if not _has_comment(comments.get(n))
        ),
    }


def table_column_fields(table: Any) -> Dict[str, Any]:
    """Return the column fields for one ``TableInfo``-like object.

    ``column_comment_ratio`` is ``None`` when the table has no columns: there is
    nothing to measure, so ``t.column_comment_ratio >= 0.8`` fails instead of
    passing on an empty or unreadable column list.
    """
    columns: List[Dict[str, Any]] = [
        {
            'name': getattr(column, 'name', None),
            'type': _column_type(column),
            'comment': getattr(column, 'comment', None),
            'is_partition_key': getattr(column, 'partition_index', None) is not None,
        }
        for column in (getattr(table, 'columns', None) or [])
    ]
    undocumented = [c for c in columns if not _has_comment(c['comment'])]
    partition = [c for c in columns if c['is_partition_key']]
    count = len(columns)
    return {
        'columns': columns,
        'column_count': count,
        'columns_without_comment_count': len(undocumented),
        'column_comment_ratio': (count - len(undocumented)) / count if count else None,
        'partition_column_count': len(partition),
        'partition_columns_without_comment_count': sum(
            1 for c in partition if not _has_comment(c['comment'])
        ),
        **key_column_fields(table),
    }
