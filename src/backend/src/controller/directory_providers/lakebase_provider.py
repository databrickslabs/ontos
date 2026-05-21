"""Postgres / Lakebase-backed directory provider.

Reads principals from a Postgres table sitting on the app's primary
database (Lakebase in production, any Postgres in dev). The table
shape is:

  CREATE TABLE <fqn> (
    type         TEXT NOT NULL,    -- 'user' | 'group'
    id           TEXT NOT NULL,    -- UPN/email for users, displayName for groups
    display_name TEXT NOT NULL,
    sub_label    TEXT
  );

The fully-qualified name (``catalog.schema.table`` or
``schema.table``) is stored in the ``DIRECTORY_LAKEBASE_TABLE``
setting. We validate the identifier syntax at query-build time to
avoid SQL injection via the table name; column values are always
passed as bind parameters.
"""

from __future__ import annotations

import re
from typing import Any, List

from sqlalchemy import text

from src.common.logging import get_logger
from src.controller.directory_providers.base import (
    DirectoryError,
    DirectoryProvider,
    DirectoryProviderConfig,
    DirectoryProviderContext,
)
from src.models.directory import Principal, PrincipalType

logger = get_logger(__name__)


# Postgres identifier rules we accept: alphanumeric + underscore + optional
# dotted parts. Anything else triggers DirectoryError so the table name
# never enters SQL untrusted.
_IDENT_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_fqn(fqn: str) -> str:
    """Return ``fqn`` quoted segment-by-segment, or raise on invalid input.

    The setting is operator-supplied so we don't need to handle every
    legal Postgres identifier (mixed case, embedded dots, etc.) -- the
    UI tells users to use ``catalog.schema.table`` or ``schema.table``.
    """

    if not fqn:
        raise DirectoryError("Lakebase table name is required")
    parts = fqn.split(".")
    if not (1 <= len(parts) <= 3):
        raise DirectoryError(
            f"Lakebase table FQN must have 1–3 dotted parts, got {len(parts)}"
        )
    for part in parts:
        if not _IDENT_PART.match(part):
            raise DirectoryError(
                f"Lakebase table FQN segment {part!r} is not a valid identifier"
            )
    # Quote each part so reserved words still work; we already
    # validated charset so the quoted form is safe.
    return ".".join(f'"{p}"' for p in parts)


class LakebaseProvider(DirectoryProvider):
    """Provider that reads principals from a Postgres table."""

    def __init__(
        self,
        ctx: DirectoryProviderContext,
        config: DirectoryProviderConfig,
    ) -> None:
        if ctx.db_engine is None:
            raise DirectoryError("Database engine is required for Lakebase provider")
        self._engine = ctx.db_engine
        # Validate at construction time so misconfiguration is caught
        # at startup / test rather than on the first search call.
        self._table = _validate_fqn(config.lakebase_table or "")

    # ----- DirectoryProvider --------------------------------------------------

    def search_users(self, prefix: str, top: int) -> List[Principal]:
        return self._search("user", prefix, top)

    def search_groups(self, prefix: str, top: int) -> List[Principal]:
        return self._search("group", prefix, top)

    def get_user(self, id: str) -> Principal:
        return self._get("user", id)

    def get_group(self, id: str) -> Principal:
        return self._get("group", id)

    def test(self) -> None:
        # Cheapest possible probe: confirm the table exists and is readable.
        # ``LIMIT 1`` keeps the row scan tiny.
        sql = text(f"SELECT 1 FROM {self._table} LIMIT 1")
        try:
            with self._engine.connect() as conn:
                conn.execute(sql)
        except Exception as exc:
            raise DirectoryError(f"Lakebase test query failed: {exc}") from exc

    # ----- internals ----------------------------------------------------------

    def _search(self, kind: str, prefix: str, top: int) -> List[Principal]:
        if not prefix:
            return []
        # ``LOWER(col) LIKE LOWER(:p)`` is case-insensitive on both
        # Postgres and SQLite (ASCII) without needing dialect-specific
        # ILIKE. The LIKE wildcards ``%`` / ``_`` in user input are
        # escaped (with ``\`` as escape char) so a raw ``%`` doesn't
        # open a directory dump.
        safe_prefix = (
            prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        sql = text(
            f"SELECT type, id, display_name, sub_label "
            f"FROM {self._table} "
            f"WHERE type = :kind "
            f"  AND ("
            f"      LOWER(display_name) LIKE LOWER(:p) ESCAPE '\\' "
            f"      OR LOWER(id) LIKE LOWER(:p) ESCAPE '\\'"
            f"  ) "
            f"ORDER BY display_name "
            f"LIMIT :n"
        )
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(
                    sql,
                    {"kind": kind, "p": f"{safe_prefix}%", "n": int(top)},
                ).fetchall()
        except Exception as exc:
            raise DirectoryError(f"Lakebase search failed: {exc}") from exc
        return [_row_to_principal(r) for r in rows]

    def _get(self, kind: str, id: str) -> Principal:
        if not id:
            raise DirectoryError(f"Empty {kind} id")
        sql = text(
            f"SELECT type, id, display_name, sub_label "
            f"FROM {self._table} "
            f"WHERE type = :kind AND id = :id "
            f"LIMIT 1"
        )
        try:
            with self._engine.connect() as conn:
                row = conn.execute(sql, {"kind": kind, "id": id}).fetchone()
        except Exception as exc:
            raise DirectoryError(f"Lakebase lookup failed: {exc}") from exc
        if row is None:
            raise DirectoryError(f"{kind.capitalize()} {id!r} not found")
        return _row_to_principal(row)


def _row_to_principal(row: Any) -> Principal:
    """Map a Postgres row to a Principal, tolerating raw types.

    SQLAlchemy ``Row`` objects support both name and index access; we
    use names to keep the mapping explicit.
    """

    kind = (row.type or "").lower()
    ptype = PrincipalType.USER if kind == "user" else (
        PrincipalType.GROUP if kind == "group" else PrincipalType.UNKNOWN
    )
    return Principal(
        type=ptype,
        id=row.id or "",
        display_name=row.display_name or row.id or "",
        sub_label=row.sub_label or None,
    )
