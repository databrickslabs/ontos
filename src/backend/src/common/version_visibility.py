"""Version-family visibility ranking (PRD #442).

Two ranking tables, picked per (caller × family):

* **Elevated** — caller is admin, draft_owner of some row in the family,
  member of the owner_team, or (products only) a subscriber. Drafts and
  in-flight versions surface first so producers/subscribers preview
  upcoming changes:

      DRAFT > PROPOSED > UNDER_REVIEW > APPROVED > ACTIVE > DEPRECATED

* **Consumer** — caller has no elevated relationship with the family.
  Only published lifecycle stages are visible; the active version wins:

      ACTIVE > DEPRECATED   (all other statuses filtered out entirely)

``RETIRED`` and unknown statuses sit below both rankings and are only
visible to admins (the manager applies that final guard).

The functions in this module take plain ORM rows (or row-like objects
that expose ``status``, ``draft_owner_id``, ``owner_team_id``,
``version_family_id``, ``created_at``) so they're equally usable from
the contracts and products managers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Set


# Lower rank wins (think: "preferred"). Statuses absent from the dict
# never rank — the consumer filter drops them before ranking starts.
_STATUS_RANK_ELEVATED: dict[str, int] = {
    "draft": 0,
    "proposed": 1,
    "under_review": 2,
    "approved": 3,
    "active": 4,
    "deprecated": 5,
}

_STATUS_RANK_CONSUMER: dict[str, int] = {
    "active": 0,
    "deprecated": 1,
}

# Statuses visible to admins only (filtered out for everyone else).
_ADMIN_ONLY_STATUSES: frozenset[str] = frozenset({"retired"})


def _normalize_status(row: Any) -> str:
    return (getattr(row, "status", "") or "").strip().lower()


def is_visible_consumer(row: Any) -> bool:
    """A consumer sees only published lifecycle stages."""
    return _normalize_status(row) in _STATUS_RANK_CONSUMER


def is_admin_only_status(row: Any) -> bool:
    return _normalize_status(row) in _ADMIN_ONLY_STATUSES


def compute_rank(row: Any, *, has_elevated_access: bool) -> tuple:
    """Sort key for rep-picking inside a family (lower = preferred).

    Tie-breaks by created_at DESC so newer rows win when the status rank
    is the same. ``has_elevated_access`` selects the rank table; the
    caller is expected to have already filtered out invisible rows
    (consumer rows with non-published statuses, retired rows for
    non-admins, etc.).
    """
    status = _normalize_status(row)
    table = _STATUS_RANK_ELEVATED if has_elevated_access else _STATUS_RANK_CONSUMER
    # Unknown statuses sit below every known one. They should normally
    # have been filtered out already; this just guarantees deterministic
    # ordering rather than a KeyError.
    status_rank = table.get(status, 999)

    created_at = getattr(row, "created_at", None)
    # Negate the epoch so DESC sort falls out of a plain ascending key.
    epoch = (
        created_at.timestamp()
        if isinstance(created_at, datetime)
        else 0.0
    )
    return (status_rank, -epoch)


def collapse_by_family(
    rows: Iterable[Any],
    *,
    elevated_family_ids: Set[str],
    is_admin: bool,
) -> list[Any]:
    """Collapse rows to one rep per ``version_family_id``.

    Steps, in order:

    1. Drop rows the caller can't see at all (retired-for-non-admins,
       non-published-statuses for non-elevated families).
    2. For each remaining family, pick the row with the best
       :func:`compute_rank`.

    Personal-draft visibility (``draft_owner_id``) is enforced at the
    query layer and is NOT re-checked here; rows passed in are already
    visibility-filtered for the personal-draft case.
    """
    # First pass: drop invisible rows.
    survivors: list[Any] = []
    for row in rows:
        fid = getattr(row, "version_family_id", None) or getattr(row, "id", None)
        if fid is None:
            # Defensive: rows without family_id collapse to themselves
            # (treated as singleton families).
            survivors.append(row)
            continue
        if not is_admin and is_admin_only_status(row):
            continue
        if fid in elevated_family_ids or is_admin:
            survivors.append(row)
        elif is_visible_consumer(row):
            survivors.append(row)
        # else: consumer-level access to a family whose row isn't
        # published — drop silently.

    # Second pass: pick rep.
    picked: dict[str, Any] = {}
    for row in survivors:
        fid = getattr(row, "version_family_id", None) or getattr(row, "id", None)
        has_elevated = is_admin or fid in elevated_family_ids
        rank = compute_rank(row, has_elevated_access=has_elevated)
        current = picked.get(fid)
        if current is None:
            picked[fid] = (rank, row)
        else:
            current_rank, _current_row = current
            if rank < current_rank:
                picked[fid] = (rank, row)
    return [row for _rank, row in picked.values()]


def family_counts(rows: Iterable[Any]) -> dict[str, int]:
    """Helper used alongside :func:`collapse_by_family` so callers can
    surface a ``versionCount`` badge on the surviving row. Counts are
    taken from the *post-visibility-filter* row set — see the route
    docstrings for why that matters.
    """
    counts: dict[str, int] = {}
    for row in rows:
        fid = getattr(row, "version_family_id", None) or getattr(row, "id", None)
        if fid is None:
            continue
        counts[fid] = counts.get(fid, 0) + 1
    return counts


__all__ = [
    "collapse_by_family",
    "compute_rank",
    "family_counts",
    "is_admin_only_status",
    "is_visible_consumer",
]
