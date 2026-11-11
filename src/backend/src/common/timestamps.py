"""Timestamps for timezone-aware columns.

Most timestamp columns are ``DateTime(timezone=True)``. Postgres reads a naive
value written into one in the session's time zone, so a naive UTC value
(``datetime.utcnow()``) is stored shifted by that zone's offset (#1449). Write
``utc_now()`` instead.
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """The current time in UTC, timezone-aware."""
    return datetime.now(timezone.utc)
