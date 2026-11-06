"""Quartz cron expressions: the one cron format of Ontos (#941).

Workflow schedules (``scheduled`` triggers) and Databricks job schedules use the
Quartz format of Databricks Jobs: ``sec min hour day-of-month month day-of-week
[year]``. There are two levels of checks:

1. ``validate_quartz_syntax``: the full Quartz grammar, for Databricks job
   schedules. Databricks evaluates those itself, so ``L``, ``W``, ``#`` and
   non-zero seconds are fine; this level only refuses what Quartz can't parse:
   - 6 or 7 fields; seconds and minutes 0-59, hours 0-23, day-of-month 1-31,
     month 1-12 or ``JAN-DEC``, day-of-week 1-7 (``SUN-SAT``), year 1970-2199;
     names in any case.
   - Items are ``*``, values, ranges (``a-b``, which may wrap, e.g. ``FRI-MON``;
     not in the year field) and increments (``*/n``, ``a/n``, ``a-b/n``),
     separated by commas.
   - ``?`` is a whole field, in exactly one of day-of-month and day-of-week
     (Quartz refuses an expression that sets both, or neither).
   - Day-of-month also takes ``L``, ``L-n`` (n up to 30), ``LW``, ``L-nW`` and
     ``nW``; day-of-week takes ``L``, ``nL`` and ``n#k`` (k 1-5). ``L`` in
     day-of-week can't be combined with other days, and only one ``#`` item is
     allowed.
2. The in-app level, for ``scheduled`` workflow triggers that Ontos runs itself
   with ``croniter`` (``second_at_beginning``), which supports a subset of
   Quartz. ``validate_in_app_cron`` adds to level 1:
   - the seconds field must be ``0`` (runs are minute-aligned);
   - ``W``, ``L`` and ``#`` are rejected;
   - anything else croniter rejects is rejected (``?`` is read as ``*``).
   ``validate_schedule`` also checks the timezone and that runs are at least
   ``MIN_INTERVAL`` (5 minutes) apart.

Day-of-week numbers are Quartz's ``1-7`` = ``SUN-SAT``; croniter counts ``0-6``
from Sunday, so numbers are shifted by one before evaluation. Names (``MON-FRI``)
mean the same in both.

Runs are computed in an IANA timezone (``zoneinfo``). In the hour a DST change
skips, a run moves to the first valid time after it; in the hour a DST change
repeats, a run in that hour happens in both occurrences (croniter's behaviour,
covered by the tests). Runs that land on the same instant count once.

Errors are ``QuartzCronError`` (a ``CodedValueError``) with a code and params, so
the UI can translate them.
"""
import re
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Iterator, List, Optional, Tuple
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
_MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
_DAYS = ('SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT')
# Per field: lowest and highest value, the names (value = position + lowest), and
# the largest increment Quartz takes (``checkIncrementRange``; None = no limit).
_SPECS = {
    'second': (0, 59, (), 59),
    'minute': (0, 59, (), 59),
    'hour': (0, 23, (), 23),
    'day_of_month': (1, 31, (), 31),
    'month': (1, 12, _MONTHS, 12),
    'day_of_week': (1, 7, _DAYS, 7),
    'year': (1970, 2199, (), None),
}
# Quartz's MAX_LAST_DAY_OFFSET: ``L-n`` in day-of-month.
_MAX_LAST_DAY_OFFSET = 30
_VALUE = r'(?:\d+|[A-Z]{3})'
_ITEM = re.compile(
    rf'(?:(?P<all>\*)|(?P<start>{_VALUE})(?:-(?P<end>{_VALUE}))?)(?:/(?P<step>\d+))?'
)
_DOM_LAST = re.compile(r'L(?:-(?P<offset>\d+))?W?')
_DOM_WEEKDAY = re.compile(r'(?P<day>\d+)W')
_DOW_LAST = re.compile(rf'(?P<day>{_VALUE})?L')
_DOW_NTH = re.compile(rf'(?P<day>{_VALUE})#(?P<nth>\d+)')
_NAMES = re.compile('|'.join(_MONTHS + _DAYS))
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


def _invalid(name: str, value: str) -> QuartzCronError:
    return QuartzCronError(
        f"'{value}' is not valid in the {name.replace('_', '-')} field of a Quartz cron "
        f"expression",
        'cron_invalid_field', field=name, value=value,
    )


def _value(name: str, token: str, item: str) -> int:
    """``token`` (a number or, in month and day-of-week, a name) as a number in range."""
    low, high, names, _ = _SPECS[name]
    if token.isdigit():
        number = int(token)
    elif token in names:
        number = names.index(token) + low
    else:
        raise _invalid(name, item)
    if not low <= number <= high:
        raise _invalid(name, item)
    return number


def _check_item(name: str, item: str) -> None:
    """One comma-separated item of a field, upper-cased."""
    if name == 'day_of_month':
        last = _DOM_LAST.fullmatch(item)
        if last:
            if last.group('offset') and int(last.group('offset')) > _MAX_LAST_DAY_OFFSET:
                raise _invalid(name, item)
            return
        weekday = _DOM_WEEKDAY.fullmatch(item)
        if weekday:
            _value(name, weekday.group('day'), item)
            return
    if name == 'day_of_week':
        last = _DOW_LAST.fullmatch(item)
        if last:
            if last.group('day'):
                _value(name, last.group('day'), item)
            return
        nth = _DOW_NTH.fullmatch(item)
        if nth:
            _value(name, nth.group('day'), item)
            if not 1 <= int(nth.group('nth')) <= 5:
                raise _invalid(name, item)
            return
    match = _ITEM.fullmatch(item)
    if not match:
        raise _invalid(name, item)
    if match.group('start'):
        start = _value(name, match.group('start'), item)
        if match.group('end'):
            end = _value(name, match.group('end'), item)
            # Quartz ranges wrap (``FRI-MON``, ``22-2``), except in the year field.
            if name == 'year' and end < start:
                raise _invalid(name, item)
    step = match.group('step')
    if step is not None:
        largest = _SPECS[name][3]
        if int(step) < 1 or (largest is not None and int(step) > largest):
            raise _invalid(name, item)


def _check_field(name: str, value: str) -> None:
    upper = value.upper()
    if upper == '?':
        if name not in ('day_of_month', 'day_of_week'):
            raise _invalid(name, value)
        return
    items = upper.split(',')
    for item in items:
        _check_item(name, item)
    if name == 'day_of_week' and len(items) > 1:
        if any(_DOW_LAST.fullmatch(item) for item in items):
            raise _invalid(name, value)  # Quartz: 'L' with other days is not supported
        if sum('#' in item for item in items) > 1:
            raise _invalid(name, value)  # Quartz: one "nth" day only


def validate_quartz_syntax(expr: Optional[str]) -> str:
    """Level 1: check ``expr`` against the full Quartz grammar; return it normalised.

    For Databricks job schedules, which Databricks evaluates itself (``L``, ``W``,
    ``#`` and any seconds are accepted). Normalised = fields joined by single
    spaces, case kept. Raises ``QuartzCronError`` (a ``ValueError``).
    """
    fields = _fields(expr)
    for name, value in zip(_FIELDS, fields):
        _check_field(name, value)
    if (fields[3] == '?') == (fields[5] == '?'):
        raise QuartzCronError(
            "A Quartz cron expression needs '?' in exactly one of day-of-month and "
            "day-of-week",
            'cron_day_fields_conflict',
        )
    return ' '.join(fields)


def _check_in_app_subset(fields: List[str]) -> None:
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


def _croniter_day_of_week(value: str) -> str:
    """Quartz day-of-week numbers (1-7 = SUN-SAT) in croniter's form (0-6 = SUN-SAT).

    Level 1 has checked that the numbers are 1-7.
    """
    parts = []
    for item in value.split(','):
        base, slash, step = item.partition('/')
        shifted = _NUMBER.sub(lambda match: str(int(match.group()) - 1), base)
        parts.append(shifted + slash + step)
    return ','.join(parts)


def _to_croniter(fields: List[str]) -> str:
    converted = ['*' if field == '?' else field for field in fields]
    converted[5] = _croniter_day_of_week(converted[5])
    return ' '.join(converted)


def _iterator(cron: str, start: datetime) -> croniter:
    return croniter(cron, start, second_at_beginning=True)


def _parse(expr: Optional[str]) -> Tuple[str, str]:
    """(normalised Quartz expression, croniter expression), checked at the in-app level."""
    normalised = validate_quartz_syntax(expr)
    fields = normalised.split()
    _check_in_app_subset(fields)
    cron = _to_croniter(fields)
    try:
        croniter(cron, second_at_beginning=True)
    except (CroniterError, ValueError, KeyError) as e:
        raise QuartzCronError(
            "Not a valid Quartz cron expression", 'cron_invalid', expression=normalised,
        ) from e
    return normalised, cron


def validate_in_app_cron(expr: Optional[str]) -> str:
    """Level 2 without the interval: Quartz syntax plus the subset Ontos runs itself.

    For ``scheduled`` workflow triggers; returns the expression normalised. Raises
    ``QuartzCronError`` (a ``ValueError``). The timezone and the minimum interval
    are checked by ``validate_schedule``.
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


def _distinct_runs(cron: str, start: datetime) -> Iterator[datetime]:
    """Runs after ``start`` as UTC instants, each once and increasing.

    Around a DST change several wall-clock runs can map to one instant (or an
    earlier one); those are dropped, so a DST shift never reads as a 0-minute gap.
    """
    iterator = _iterator(cron, start)
    last: Optional[datetime] = None
    try:
        while True:
            run = _as_utc(iterator.get_next(datetime))
            if last is None or run > last:
                last = run
                yield run
    except CroniterError:
        return  # e.g. a year field that has no later year


def next_runs(
    expr: str, tz: Optional[str] = None, *, after: Optional[datetime] = None, count: int = 3,
) -> List[datetime]:
    """The next ``count`` runs strictly after ``after`` (default now), as UTC datetimes."""
    _, cron = _parse(expr)
    zone = resolve_timezone(tz)
    start = _as_utc(after or datetime.now(timezone.utc)).astimezone(zone)
    return list(islice(_distinct_runs(cron, start), count))


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
    runs = _distinct_runs(cron, _as_utc(after).astimezone(zone))
    count = 0
    for run in runs:
        if count >= limit or run > end:
            break
        count += 1
    return count


def validate_schedule(
    expr: str, tz: Optional[str] = None, *, now: Optional[datetime] = None,
) -> str:
    """Level 2: check an in-app workflow schedule, its timezone and the minimum interval.

    Raises ``QuartzCronError`` when the expression has no upcoming run, or when two
    consecutive upcoming runs (of the next ``INTERVAL_CHECK_RUNS``) are less than
    ``MIN_INTERVAL`` apart. Returns the normalised expression.
    """
    normalised = validate_in_app_cron(expr)
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
