"""Column fields for Unity Catalog tables and views in compliance rules.

Pure helper: it reads only what ``tables.list`` already returns on a ``TableInfo``
(``columns`` with ``name``, ``type_text``/``type_name``, ``comment`` and
``partition_index``) and ``table_constraints``, so it makes no API call. The
compliance loader uses it for ``MATCH (t:table)`` / ``MATCH (v:view)``; other
entity dicts that point to a UC table can reuse it with the same object.
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
    by_name = {c['name']: c for c in columns}
    primary = _key_column_names(table, 'primary_key_constraint')
    foreign = _key_column_names(table, 'foreign_key_constraint')
    return {
        'columns': columns,
        'column_count': count,
        'columns_without_comment_count': len(undocumented),
        'column_comment_ratio': (count - len(undocumented)) / count if count else None,
        'partition_column_count': len(partition),
        'partition_columns_without_comment_count': sum(
            1 for c in partition if not _has_comment(c['comment'])
        ),
        'primary_key_columns': primary,
        'foreign_key_columns': foreign,
        # A key column the table doesn't list has no comment either
        'primary_key_columns_without_comment_count': sum(
            1 for n in primary if not _has_comment((by_name.get(n) or {}).get('comment'))
        ),
        'foreign_key_columns_without_comment_count': sum(
            1 for n in foreign if not _has_comment((by_name.get(n) or {}).get('comment'))
        ),
    }
