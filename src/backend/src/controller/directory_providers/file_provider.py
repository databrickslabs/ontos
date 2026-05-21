"""CSV-file-backed directory provider.

Primarily intended for tests, demos, and offline development. The
file path is taken from the ``DIRECTORY_FILE_PATH`` setting. Format:

  type,id,display_name,sub_label
  user,alice@example.com,Alice Liddell,alice@example.com
  group,Producers,Data Producers,producers-guid

The file is re-read from disk whenever its ``mtime`` advances. We do
not watch the filesystem -- the manager's per-request settings read
plus the existing 5-min cache TTL make polling unnecessary.
"""

from __future__ import annotations

import csv
import os
from threading import Lock
from typing import List, Optional

from src.common.logging import get_logger
from src.controller.directory_providers.base import (
    DirectoryError,
    DirectoryProvider,
    DirectoryProviderConfig,
    DirectoryProviderContext,
)
from src.models.directory import Principal, PrincipalType

logger = get_logger(__name__)


# Expected CSV columns. Extra columns are ignored.
_REQUIRED_COLUMNS = {"type", "id", "display_name"}


class FileProvider(DirectoryProvider):
    """Provider that reads principals from a CSV file on disk."""

    # Class-level cache keyed on file path so multiple provider
    # instances against the same file share the parsed contents.
    _cache: dict = {}
    _cache_lock = Lock()

    def __init__(
        self,
        ctx: DirectoryProviderContext,  # noqa: ARG002 - ctx is part of the contract
        config: DirectoryProviderConfig,
    ) -> None:
        if not config.file_path:
            raise DirectoryError("File path is required for File provider")
        self._path = config.file_path

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
        # Force a re-read so misconfigured paths / malformed CSVs
        # surface as DirectoryError immediately rather than at the
        # next search call.
        self._load(force_reload=True)

    # ----- internals ----------------------------------------------------------

    def _search(self, kind: str, prefix: str, top: int) -> List[Principal]:
        if not prefix:
            return []
        rows = self._load()
        needle = prefix.lower()
        out: List[Principal] = []
        for r in rows:
            if r.type.value != kind:
                continue
            if r.display_name.lower().startswith(needle) or r.id.lower().startswith(needle):
                out.append(r)
                if len(out) >= top:
                    break
        return out

    def _get(self, kind: str, id: str) -> Principal:
        if not id:
            raise DirectoryError(f"Empty {kind} id")
        for r in self._load():
            if r.type.value == kind and r.id == id:
                return r
        raise DirectoryError(f"{kind.capitalize()} {id!r} not found in CSV")

    def _load(self, force_reload: bool = False) -> List[Principal]:
        if not os.path.isfile(self._path):
            raise DirectoryError(f"CSV file not found: {self._path}")
        try:
            mtime = os.path.getmtime(self._path)
        except OSError as exc:
            raise DirectoryError(f"Cannot stat CSV file {self._path}: {exc}") from exc

        with FileProvider._cache_lock:
            entry = FileProvider._cache.get(self._path)
            if entry and not force_reload and entry[0] == mtime:
                return entry[1]

        rows = _read_csv(self._path)
        with FileProvider._cache_lock:
            FileProvider._cache[self._path] = (mtime, rows)
        return rows


def _read_csv(path: str) -> List[Principal]:
    """Parse the CSV. Raises ``DirectoryError`` on malformed input."""

    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise DirectoryError(f"CSV {path} has no header row")
            missing = _REQUIRED_COLUMNS - {c.strip() for c in reader.fieldnames}
            if missing:
                raise DirectoryError(
                    f"CSV {path} is missing required columns: {sorted(missing)}"
                )
            out: List[Principal] = []
            for idx, raw in enumerate(reader, start=2):  # header is row 1
                principal = _row_to_principal(raw, path=path, lineno=idx)
                if principal is not None:
                    out.append(principal)
            return out
    except DirectoryError:
        raise
    except Exception as exc:
        raise DirectoryError(f"Failed to read CSV {path}: {exc}") from exc


def _row_to_principal(
    row: dict, *, path: str, lineno: int,
) -> Optional[Principal]:
    """Best-effort row -> Principal mapping. Skips obviously empty rows."""

    raw_type = (row.get("type") or "").strip().lower()
    raw_id = (row.get("id") or "").strip()
    display_name = (row.get("display_name") or "").strip()
    sub_label = (row.get("sub_label") or "").strip() or None

    if not raw_id and not display_name and not raw_type:
        return None  # blank row -- skip silently
    if raw_type not in {"user", "group"}:
        raise DirectoryError(
            f"{path} line {lineno}: type must be 'user' or 'group', got {raw_type!r}"
        )
    if not raw_id:
        raise DirectoryError(f"{path} line {lineno}: id is required")
    if not display_name:
        display_name = raw_id

    return Principal(
        type=PrincipalType.USER if raw_type == "user" else PrincipalType.GROUP,
        id=raw_id,
        display_name=display_name,
        sub_label=sub_label,
    )


def _clear_cache_for_tests() -> None:
    """Used only by the test suite to reset between cases."""

    with FileProvider._cache_lock:
        FileProvider._cache.clear()
