"""The Quartz cron subset Ontos accepts, and what croniter does with Quartz (#941).

The first group pins croniter's own behaviour, the facts the subset is built on
("confirm the supported subset with tests"); the rest test ``common/quartz_cron``.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from croniter import CroniterError, croniter

from src.common.quartz_cron import (
    MIN_INTERVAL,
    QuartzCronError,
    count_runs,
    next_runs,
    previous_run,
    resolve_timezone,
    validate_quartz_cron,
    validate_schedule,
)

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)  # a Thursday


def _croniter_next(expr, start=START, count=2, **kwargs):
    iterator = croniter(expr, start, **kwargs)
    return [iterator.get_next(datetime) for _ in range(count)]


def _code(expr, tz=None, schedule=False):
    with pytest.raises(QuartzCronError) as info:
        validate_schedule(expr, tz, now=START) if schedule else validate_quartz_cron(expr)
    return info.value.code, info.value.params


# --- croniter facts --------------------------------------------------------------

def test_croniter_reads_six_fields_seconds_last_unless_told_otherwise():
    # Quartz puts seconds first; croniter's default reads six fields as
    # ``min hour dom month dow sec``, so the minute field (30) lands in the hour.
    with pytest.raises(CroniterError):
        croniter('0 30 2 * * *', START)
    assert _croniter_next('0 30 2 * * *', second_at_beginning=True) == [
        datetime(2026, 1, 1, 2, 30, tzinfo=UTC), datetime(2026, 1, 2, 2, 30, tzinfo=UTC),
    ]


def test_croniter_accepts_question_mark_and_the_year_field():
    assert _croniter_next('0 30 2 ? * *', second_at_beginning=True)[0] == datetime(
        2026, 1, 1, 2, 30, tzinfo=UTC)
    assert _croniter_next('0 30 2 * * ? 2027', second_at_beginning=True)[0] == datetime(
        2027, 1, 1, 2, 30, tzinfo=UTC)


def test_croniter_counts_day_of_week_from_zero_unlike_quartz():
    # croniter: 1 = Monday (Quartz: 1 = Sunday), and 7 is out of range.
    assert _croniter_next('0 0 9 * * 1', second_at_beginning=True)[0].weekday() == 0
    with pytest.raises(CroniterError):
        croniter('0 0 9 * * 7', START, second_at_beginning=True)


def test_croniter_takes_w_l_and_hash_which_the_subset_rejects():
    for expr in ('0 0 0 15W * *', '0 0 0 L * *', '0 0 0 * * 2#1'):
        assert croniter.is_valid(expr, second_at_beginning=True), expr


# --- the subset ------------------------------------------------------------------

@pytest.mark.parametrize('expr', [
    '0 30 2 * * ?', '0 0 */6 * * ? *', '  0 15 3 ? * MON  ', '0 0 9 ? * MON-FRI',
    '0 0 0 1 JAN ?', '0 0 12 * * ? 2030', '0 0/15 * * * ?', '0 0 9 ? JUL WED',
    '0 0 9 * * *',
])
def test_accepted_expressions_come_back_normalised(expr):
    assert validate_quartz_cron(expr) == ' '.join(expr.split())


@pytest.mark.parametrize('expr', ['', '30 2 * * *', 'daily', '0 30 2 * * ? * extra', None])
def test_the_field_count_is_checked(expr):
    with pytest.raises(ValueError, match='Quartz'):
        validate_quartz_cron(expr)
    assert _code(expr)[0] == 'cron_field_count'


def test_seconds_must_be_zero():
    assert _code('30 0 * * * ?') == ('cron_seconds_not_zero', {'value': '30'})
    assert _code('*/10 * * * * ?')[0] == 'cron_seconds_not_zero'


@pytest.mark.parametrize(('expr', 'field', 'char'), [
    ('0 0 0 15W * ?', 'day_of_month', 'W'),
    ('0 0 0 L * ?', 'day_of_month', 'L'),
    ('0 0 0 LW * ?', 'day_of_month', 'W'),
    ('0 0 0 ? * 6L', 'day_of_week', 'L'),
    ('0 0 0 ? * 2#1', 'day_of_week', '#'),
])
def test_w_l_and_hash_are_rejected(expr, field, char):
    code, params = _code(expr)
    assert code == 'cron_unsupported_character'
    assert params['field'] == field
    assert params['character'] in ('W', 'L', '#') and char in expr


def test_both_day_fields_restricted_is_rejected():
    assert _code('0 0 9 1 * MON')[0] == 'cron_day_fields_conflict'


def test_day_of_week_numbers_follow_quartz():
    # Quartz 1 = Sunday ... 7 = Saturday; START is a Thursday.
    days = {n: next_runs(f'0 0 9 ? * {n}', after=START, count=1)[0].weekday() for n in range(1, 8)}
    assert days == {1: 6, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5}
    assert [r.weekday() for r in next_runs('0 0 9 ? * 2-6', after=START, count=5)] == [
        3, 4, 0, 1, 2]
    assert [r.weekday() for r in next_runs('0 0 9 ? * 2/3', after=START, count=2)] == [3, 0]
    assert _code('0 0 9 ? * 8') == ('cron_day_of_week_out_of_range', {'value': 8})
    assert _code('0 0 9 ? * 0')[0] == 'cron_day_of_week_out_of_range'


@pytest.mark.parametrize('expr', ['0 99 * * * ?', '0 0 25 * * ?', '0 0 0 ? FOO *', '0 a * * * ?'])
def test_what_croniter_rejects_is_rejected(expr):
    assert _code(expr)[0] == 'cron_invalid'


# --- timezones -------------------------------------------------------------------

def test_timezones():
    assert resolve_timezone(None) == ZoneInfo('UTC')
    assert resolve_timezone(' ') == ZoneInfo('UTC')
    assert resolve_timezone('Europe/Berlin') == ZoneInfo('Europe/Berlin')
    with pytest.raises(QuartzCronError) as info:
        resolve_timezone('Mars/Base')
    assert (info.value.code, info.value.params) == ('timezone_invalid', {'timezone': 'Mars/Base'})
    assert _code('0 0 9 * * ?', 'Not/AZone', schedule=True)[0] == 'timezone_invalid'


def test_next_runs_follow_the_timezone_across_dst():
    # Berlin switches to summer time on 2026-03-29: 09:00 local is 08:00Z, then 07:00Z.
    runs = next_runs('0 0 9 * * ?', 'Europe/Berlin', after=datetime(2026, 3, 27, tzinfo=UTC))
    assert runs == [
        datetime(2026, 3, 27, 8, tzinfo=UTC), datetime(2026, 3, 28, 8, tzinfo=UTC),
        datetime(2026, 3, 29, 7, tzinfo=UTC),
    ]


def test_a_run_in_the_skipped_dst_hour_moves_to_the_first_valid_time():
    # New York skips 02:00-03:00 on 2026-03-08: 02:30 runs at 03:00 EDT (07:00Z).
    runs = next_runs('0 30 2 * * ?', 'America/New_York', after=datetime(2026, 3, 7, 12, tzinfo=UTC))
    assert runs[:2] == [
        datetime(2026, 3, 8, 7, tzinfo=UTC), datetime(2026, 3, 9, 6, 30, tzinfo=UTC),
    ]


def test_a_run_in_the_repeated_dst_hour_runs_in_both_occurrences():
    # New York repeats 01:00-02:00 on 2026-11-01: 01:30 EDT (05:30Z) and 01:30 EST (06:30Z).
    after = datetime(2026, 10, 31, 12, tzinfo=UTC)
    runs = next_runs('0 30 1 * * ?', 'America/New_York', after=after)
    assert runs == [
        datetime(2026, 11, 1, 5, 30, tzinfo=UTC), datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
        datetime(2026, 11, 2, 6, 30, tzinfo=UTC),
    ]


def test_previous_run_and_count_runs():
    at = datetime(2026, 1, 1, 10, 31, tzinfo=UTC)
    assert previous_run('0 0/5 * * * ?', None, at) == datetime(2026, 1, 1, 10, 30, tzinfo=UTC)
    assert previous_run('0 0/5 * * * ?', None, at.replace(minute=30)) == at.replace(minute=30)
    after = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert count_runs('0 0/5 * * * ?', None, after, at, limit=100) == 6
    assert count_runs('0 0/5 * * * ?', None, after, at, limit=4) == 4


# --- the 5-minute rule -----------------------------------------------------------

@pytest.mark.parametrize('expr', [
    '0 0,2 * * * ?',      # two runs per hour, 2 minutes apart
    '0 0/4 * * * ?',      # every 4 minutes
    '0 * * * * ?',        # every minute
    '0 0,58 0,23 * * ?',  # 23:58 and 00:00 the next day
])
def test_runs_closer_than_five_minutes_are_rejected(expr):
    code, params = _code(expr, schedule=True)
    assert code == 'cron_interval_too_short'
    assert params['minutes'] == MIN_INTERVAL.total_seconds() // 60
    first, second = (datetime.fromisoformat(params[k]) for k in ('first', 'second'))
    assert second - first < MIN_INTERVAL


@pytest.mark.parametrize('expr', ['0 0/5 * * * ?', '0 0 * * * ?', '0 30 2 * * ?', '0 0,5 * * * ?'])
def test_runs_five_minutes_apart_are_accepted(expr):
    assert validate_schedule(expr, 'Europe/Berlin', now=START) == expr


def test_a_schedule_without_upcoming_runs_is_rejected():
    assert _code('0 0 0 * * ? 2020', schedule=True)[0] == 'cron_no_upcoming_runs'


def test_the_interval_check_is_fast_enough_for_every_save():
    started = datetime.now()
    validate_schedule('0 0/5 * * * ?', 'UTC', now=START)
    assert datetime.now() - started < timedelta(seconds=2)
