"""Quartz cron expressions: the one cron format of Ontos (#941).

Workflow schedules (``scheduled`` triggers) and Databricks job schedules use the
Quartz format of Databricks Jobs: ``sec min hour day-of-month month day-of-week
[year]``. Expressions are evaluated with ``croniter`` (``second_at_beginning``),
which supports a subset of Quartz. This module accepts exactly that subset:

- 6 or 7 fields; the seconds field must be ``0`` (runs are minute-aligned).
- ``?`` (no specific value) is read as ``*``.
- ``W``, ``L`` and ``#`` are rejected, and so is an expression that restricts
  both day-of-month and day-of-week (Quartz needs ``?`` in one of them; croniter
  would OR the two).
- Day-of-week numbers are Quartz's ``1-7`` = ``SUN-SAT``; croniter counts
  ``0-6`` from Sunday, so numbers are shifted by one before evaluation. Names
  (``MON-FRI``) mean the same in both.
- Anything else croniter rejects is rejected.

Runs are computed in an IANA timezone (``zoneinfo``). In the hour a DST change
skips, a run moves to the first valid time after it; in the hour a DST change
repeats, a run in that hour happens in both occurrences (croniter's behaviour,
covered by the tests).

Errors are ``QuartzCronError`` (a ``CodedValueError``) with a code and params, so
the UI can translate them.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterError, croniter

from src.common.api_errors import CodedValueError

DEFAULT_TIMEZONE = 'UTC'
# The shortest time allowed between two runs of a schedule, so the app database
# (Lakebase) can idle between runs.
MIN_INTERVAL = timedelta(minutes=5)
# How many upcoming runs the minimum-interval check compares. A Quartz schedule
# repeats by day, and at most 288 runs fit in a day at the minimum interval, so
# this covers several days; a close pair that first occurs later (one that only
# exists on 29 February, say) is not caught.
INTERVAL_CHECK_RUNS = 1000

_EXAMPLE = '0 30 2 * * ?'
_FIELDS = ('second', 'minute', 'hour', 'day_of_month', 'month', 'day_of_week', 'year')
_NAMES = re.compile(r'JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|SUN|MON|TUE|WED|THU|FRI|SAT')
_UNSUPPORTED = ('W', 'L', '#')
_NUMBER = re.compile(r'\d+')


class QuartzCronError(CodedValueError):
    """A cron expression or timezone this module doesn't accept, with a code for the UI."""

    def __init__(self, message: str, code: str, **params):
        super().__init__(message, **params)
        self.code = code


def _fields(expr: Optional[str]) -> List[str]:
    fields = (expr or '').split()
    if len(fields) not in (6, 7):
        raise QuartzCronError(
            f"schedule must be a Quartz cron expression with 6 or 7 fields "
            f"(e.g. '{_EXAMPLE}'), got {len(fields)}",
            'cron_field_count', expression=expr or '', fields=len(fields),
        )
    return fields


def _check_subset(fields: List[str]) -> None:
    if fields[0] != '0':
        raise QuartzCronError(
            "The seconds field of a Quartz cron expression must be 0",
            'cron_seconds_not_zero', value=fields[0],
        )
    for name, value in zip(_FIELDS, fields):
        bare = _NAMES.sub('', value.upper())
        for char in _UNSUPPORTED:
            if char in bare:
                raise QuartzCronError(
                    f"'{char}' in the {name.replace('_', '-')} field is not supported",
                    'cron_unsupported_character', field=name, character=char,
                )
    if fields[3] not in ('?', '*') and fields[5] not in ('?', '*'):
        raise QuartzCronError(
            "A Quartz cron expression can't restrict both day-of-month and day-of-week; "
            "use '?' in one of them",
            'cron_day_fields_conflict',
        )


def _croniter_day_of_week(value: str) -> str:
    """Quartz day-of-week numbers (1-7 = SUN-SAT) in croniter's form (0-6 = SUN-SAT)."""
    parts = []
    for item in value.split(','):
        base, slash, step = item.partition('/')

        def shift(match: re.Match) -> str:
            number = int(match.group())
            if not 1 <= number <= 7:
                raise QuartzCronError(
                    "Day-of-week numbers in a Quartz cron expression are 1-7 (SUN-SAT)",
                    'cron_day_of_week_out_of_range', value=number,
                )
            return str(number - 1)

        parts.append(_NUMBER.sub(shift, base) + slash + step)
    return ','.join(parts)


def _to_croniter(fields: List[str]) -> str:
    converted = ['*' if field == '?' else field for field in fields]
    converted[5] = _croniter_day_of_week(converted[5])
    return ' '.join(converted)


def _iterator(cron: str, start: datetime) -> croniter:
    return croniter(cron, start, second_at_beginning=True)


def _parse(expr: Optional[str]) -> Tuple[str, str]:
    """(normalised Quartz expression, croniter expression), checked against the subset."""
    fields = _fields(expr)
    _check_subset(fields)
    cron = _to_croniter(fields)
    try:
        croniter(cron, second_at_beginning=True)
    except (CroniterError, ValueError, KeyError) as e:
        raise QuartzCronError(
            "Not a valid Quartz cron expression", 'cron_invalid', expression=' '.join(fields),
        ) from e
    return ' '.join(fields), cron


def validate_quartz_cron(expr: str) -> str:
    """Check a Quartz cron expression against the supported subset; return it normalised.

    Normalised = fields joined by single spaces. Raises ``QuartzCronError`` (a
    ``ValueError``). The timezone and the minimum interval are checked by
    ``validate_schedule``.
    """
    return _parse(expr)[0]


def resolve_timezone(name: Optional[str]) -> ZoneInfo:
    """The IANA timezone ``name`` (``UTC`` when empty)."""
    key = (name or '').strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise QuartzCronError(
            f"Unknown timezone '{key}' (use an IANA name such as 'Europe/Berlin')",
            'timezone_invalid', timezone=key,
        ) from e


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def next_runs(
    expr: str, tz: Optional[str] = None, *, after: Optional[datetime] = None, count: int = 3,
) -> List[datetime]:
    """The next ``count`` runs strictly after ``after`` (default now), as UTC datetimes."""
    _, cron = _parse(expr)
    zone = resolve_timezone(tz)
    start = _as_utc(after or datetime.now(timezone.utc)).astimezone(zone)
    iterator = _iterator(cron, start)
    runs = []
    try:
        for _ in range(count):
            runs.append(_as_utc(iterator.get_next(datetime)))
    except CroniterError:
        pass  # e.g. a year field that has no later year
    return runs


def previous_run(expr: str, tz: Optional[str], at: datetime) -> Optional[datetime]:
    """The latest run at or before ``at`` (UTC), or None."""
    _, cron = _parse(expr)
    zone = resolve_timezone(tz)
    # croniter's get_prev is strictly before its start: start one second later.
    start = (_as_utc(at) + timedelta(seconds=1)).astimezone(zone)
    try:
        return _as_utc(_iterator(cron, start).get_prev(datetime))
    except CroniterError:
        return None


def count_runs(expr: str, tz: Optional[str], after: datetime, until: datetime, limit: int) -> int:
    """How many runs fall in ``(after, until]``, counting at most ``limit``."""
    _, cron = _parse(expr)
    zone = resolve_timezone(tz)
    end = _as_utc(until)
    iterator = _iterator(cron, _as_utc(after).astimezone(zone))
    count = 0
    try:
        while count < limit and _as_utc(iterator.get_next(datetime)) <= end:
            count += 1
    except CroniterError:
        pass
    return count


def validate_schedule(
    expr: str, tz: Optional[str] = None, *, now: Optional[datetime] = None,
) -> str:
    """Check a workflow schedule: the expression, its timezone and the minimum interval.

    Raises ``QuartzCronError`` when the expression has no upcoming run, or when two
    consecutive upcoming runs (of the next ``INTERVAL_CHECK_RUNS``) are less than
    ``MIN_INTERVAL`` apart. Returns the normalised expression.
    """
    normalised = validate_quartz_cron(expr)
    resolve_timezone(tz)
    runs = next_runs(normalised, tz, after=now, count=INTERVAL_CHECK_RUNS)
    if not runs:
        raise QuartzCronError(
            "The cron expression has no upcoming run", 'cron_no_upcoming_runs',
            expression=normalised,
        )
    for earlier, later in zip(runs, runs[1:]):
        if later - earlier < MIN_INTERVAL:
            minutes = int(MIN_INTERVAL.total_seconds() // 60)
            raise QuartzCronError(
                f"Scheduled runs must be at least {minutes} minutes apart "
                f"({earlier.isoformat()} and {later.isoformat()} are not)",
                'cron_interval_too_short', minutes=minutes,
                first=earlier.isoformat(), second=later.isoformat(),
            )
    return normalised
