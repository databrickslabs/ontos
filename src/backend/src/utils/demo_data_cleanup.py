"""Clear rows that reference demo data before the demo rows are deleted.

The demo teardown deletes the rows listed in the demo packs. Rows created
after the demo was loaded (a custom property added to a demo product, a
compliance run of a demo policy, a team member re-created by an edit) have
their own ids, so they are not in the packs, and a foreign key without
``ON DELETE`` action from them blocks deleting the demo rows.

``clear_references`` applies what ``ON DELETE CASCADE`` / ``SET NULL`` would:
rows that require the demo row (non-nullable foreign key) are deleted, after
their own references are cleared; rows that only optionally reference it get
the reference set to NULL. Foreign keys that already have an ``ON DELETE``
action are left to the database.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import String, cast, delete, select, update
from sqlalchemy.orm import Session

from src.common.database import Base

# parent table -> [(child table, child column, referenced column, nullable)]
_References = Dict[str, List[Tuple[object, str, str, bool]]]
_references: Optional[_References] = None


def _load_models() -> None:
    import src.db_models as models
    for module in pkgutil.iter_modules(models.__path__):
        importlib.import_module(f"{models.__name__}.{module.name}")


def _referencing_foreign_keys() -> _References:
    global _references
    if _references is None:
        _load_models()
        refs: _References = defaultdict(list)
        for table in Base.metadata.tables.values():
            for fk in table.foreign_keys:
                if (fk.ondelete or "").upper() in ("CASCADE", "SET NULL"):
                    continue
                refs[fk.column.table.name].append(
                    (table, fk.parent.name, fk.column.name, bool(fk.parent.nullable))
                )
        _references = refs
    return _references


def clear_references(
    db: Session,
    table_name: str,
    column: str,
    values: List[str],
    _seen: Optional[Set[Tuple[str, str]]] = None,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Delete or detach the rows referencing ``table_name.column IN values``.

    Returns ``(deleted, nulled)`` row counts per table. The caller commits.
    """
    deleted: Dict[str, int] = defaultdict(int)
    nulled: Dict[str, int] = defaultdict(int)
    if not values:
        return {}, {}
    seen = set(_seen or ())
    seen.add((table_name, column))
    for child, child_column, referenced, nullable in _referencing_foreign_keys().get(table_name, []):
        if referenced != column:
            continue
        matches = cast(child.c[child_column], String).in_(values)
        primary_key = list(child.primary_key.columns)
        if child.name == table_name and len(primary_key) == 1:
            # Self-reference (e.g. a domain's parent): rows deleted in the
            # same statement are not dependents
            matches = matches & ~cast(primary_key[0], String).in_(values)
        if nullable:
            result = db.execute(update(child).where(matches).values({child_column: None}))
            nulled[child.name] += result.rowcount or 0
            continue
        if len(primary_key) == 1 and (child.name, primary_key[0].name) not in seen:
            child_ids = [
                str(v) for v in db.execute(select(primary_key[0]).where(matches)).scalars()
            ]
            if child_ids:
                sub_deleted, sub_nulled = clear_references(
                    db, child.name, primary_key[0].name, child_ids, seen
                )
                for name, count in sub_deleted.items():
                    deleted[name] += count
                for name, count in sub_nulled.items():
                    nulled[name] += count
        result = db.execute(delete(child).where(matches))
        deleted[child.name] += result.rowcount or 0
    return (
        {name: count for name, count in deleted.items() if count},
        {name: count for name, count in nulled.items() if count},
    )
