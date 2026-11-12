"""Time helpers."""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware current UTC time.

    Use instead of the naive ``datetime.utcnow()``: Postgres reads a naive value written to a
    ``timestamptz`` column in the session time zone and shifts it by the server's UTC offset.
    """
    return datetime.now(timezone.utc)
