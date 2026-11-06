"""The two levels of Quartz cron checks, and what croniter does with Quartz (#941).

The first group pins croniter's own behaviour, the facts the in-app subset is built
on ("confirm the supported subset with tests"); then level 1 (full Quartz syntax,
for Databricks job schedules) and level 2 (the in-app subset) of
``common/quartz_cron``.
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
    validate_in_app_cron,
    validate_quartz_syntax,
    validate_schedule,
)

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)  # a Thursday


def _croniter_next(expr, start=START, count=2, **kwargs):
    iterator = croniter(expr, start, **kwargs)
    return [iterator.get_next(datetime) for _ in range(count)]


def _code(expr, tz=None, schedule=False):
    with pytest.raises(QuartzCronError) as info:
        validate_schedule(expr, tz, now=START) if schedule else validate_in_app_cron(expr)
    return info.value.code, info.value.params


def _syntax_code(expr):
    with pytest.raises(QuartzCronError) as info:
        validate_quartz_syntax(expr)
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


# --- level 1: full Quartz syntax (Databricks job schedules) -----------------------

# Every schedule in the job YAMLs (src/backend/src/workflows/*/*.yaml), the default
# of #1095's reindex job and the examples of #1095's tests.
STORED_JOB_SCHEDULES = [
    '0 0 2 * * ?', '0 0 */4 * * ?', '0 0 4 * * ?', '0 0 3 * * ?', '0 0 1 * * ?',
    '0 30 2 * * ?', '0 0 */6 * * ? *', '  0 15 3 ? * MON  ', '0 0 */6 * * ?', '0  0 1 * * ?',
]


@pytest.mark.parametrize('expr', STORED_JOB_SCHEDULES)
def test_stored_job_schedules_pass_level_one(expr):
    assert validate_quartz_syntax(expr) == ' '.join(expr.split())


def test_every_job_yaml_schedule_passes_level_one():
    import pathlib

    import yaml

    root = pathlib.Path(__file__).resolve().parents[2] / 'workflows'
    found = []
    for path in sorted(root.glob('*/*.yaml')):
        schedule = (yaml.safe_load(path.read_text()) or {}).get('schedule')
        if isinstance(schedule, dict) and schedule.get('quartz_cron_expression'):
            found.append(schedule['quartz_cron_expression'])
    assert found
    for expr in found:
        assert validate_quartz_syntax(expr) == ' '.join(expr.split())


QUARTZ_ONLY = [
    '0 0 0 15W * ?', '0 0 0 L * ?', '0 0 0 LW * ?', '0 0 0 L-3 * ?', '0 0 0 L-3W * ?',
    '0 0 0 ? * 6L', '0 0 0 ? * L', '0 0 0 ? * 2#1', '0 0 9 ? * FRI#3',
    '30 15 10 ? * MON-FRI', '*/10 * * * * ?',
]


@pytest.mark.parametrize('expr', QUARTZ_ONLY + [
    '0 0 22-2 * * ?', '0 0 9 ? * fri-mon', '0 0 0 1 1 ? 2030-2031', '0 0 9 ? jan,Jul MON',
    '0 5/15 8-18 ? * 2-6 *', '0 0 0 1,15 * ?',
])
def test_level_one_accepts_the_quartz_grammar(expr):
    assert validate_quartz_syntax(expr) == ' '.join(expr.split())


@pytest.mark.parametrize(('expr', 'field'), [
    ('0 60 * * * ?', 'minute'), ('60 0 * * * ?', 'second'), ('0 0 24 * * ?', 'hour'),
    ('0 0 0 32 * ?', 'day_of_month'), ('0 0 0 0 * ?', 'day_of_month'),
    ('0 0 0 ? 13 *', 'month'), ('0 0 0 ? FOO *', 'month'),
    ('0 0 0 ? * 8', 'day_of_week'), ('0 0 0 ? * 0', 'day_of_week'),
    ('0 0 0 * * ? 1969', 'year'), ('0 0 0 * * ? 2031-2030', 'year'),
    ('0 0 ? * * *', 'hour'), ('0 a * * * ?', 'minute'), ('0 */0 * * * ?', 'minute'),
    ('0 0 0 ? * MON/8', 'day_of_week'), ('0 0 0 L-31 * ?', 'day_of_month'),
    ('0 0 0 32W * ?', 'day_of_month'), ('0 0 0 ? * 1#6', 'day_of_week'),
    ('0 0 0 ? * 8L', 'day_of_week'), ('0 0 0 ? * L,2', 'day_of_week'),
    ('0 0 0 ? * 1#1,2#2', 'day_of_week'), ('0 0 0 ? * 2W', 'day_of_week'),
    ('0 0 0 ?,1 * *', 'day_of_month'),
])
def test_level_one_rejects_what_quartz_cannot_parse(expr, field):
    code, params = _syntax_code(expr)
    assert (code, params['field']) == ('cron_invalid_field', field)


@pytest.mark.parametrize('expr', ['0 0 9 * * *', '0 0 9 1 * MON', '0 0 9 ? * ?', '0 0 0 L * 2'])
def test_level_one_needs_question_mark_in_exactly_one_day_field(expr):
    assert _syntax_code(expr)[0] == 'cron_day_fields_conflict'


@pytest.mark.parametrize('expr', ['', '30 2 * * *', 'daily', '0 30 2 * * ? * extra', None])
def test_level_one_checks_the_field_count(expr):
    assert _syntax_code(expr)[0] == 'cron_field_count'


# --- level 2: the in-app subset (scheduled workflow triggers) ------------------------

@pytest.mark.parametrize('expr', [
    '0 30 2 * * ?', '0 0 */6 * * ? *', '  0 15 3 ? * MON  ', '0 0 9 ? * MON-FRI',
    '0 0 0 1 JAN ?', '0 0 12 * * ? 2030', '0 0/15 * * * ?', '0 0 9 ? JUL WED',
])
def test_accepted_expressions_come_back_normalised(expr):
    assert validate_in_app_cron(expr) == ' '.join(expr.split())


@pytest.mark.parametrize('expr', ['', '30 2 * * *', 'daily', '0 30 2 * * ? * extra', None])
def test_the_field_count_is_checked(expr):
    with pytest.raises(ValueError, match='Quartz'):
        validate_in_app_cron(expr)
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


@pytest.mark.parametrize('expr', QUARTZ_ONLY)
def test_level_two_refuses_what_only_level_one_accepts(expr):
    validate_quartz_syntax(expr)
    assert _code(expr)[0] in ('cron_unsupported_character', 'cron_seconds_not_zero')
    assert _code(expr, schedule=True)[0] in (
        'cron_unsupported_character', 'cron_seconds_not_zero',
    )


@pytest.mark.parametrize('expr', ['0 0 9 1 * MON', '0 0 9 * * *'])
def test_day_fields_without_exactly_one_question_mark_are_rejected(expr):
    assert _code(expr)[0] == 'cron_day_fields_conflict'


def test_day_of_week_numbers_follow_quartz():
    # Quartz 1 = Sunday ... 7 = Saturday; START is a Thursday.
    days = {n: next_runs(f'0 0 9 ? * {n}', after=START, count=1)[0].weekday() for n in range(1, 8)}
    assert days == {1: 6, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4, 7: 5}
    assert [r.weekday() for r in next_runs('0 0 9 ? * 2-6', after=START, count=5)] == [
        3, 4, 0, 1, 2]
    assert [r.weekday() for r in next_runs('0 0 9 ? * 2/3', after=START, count=2)] == [3, 0]
    assert _code('0 0 9 ? * 8') == ('cron_invalid_field', {'field': 'day_of_week', 'value': '8'})
    assert _code('0 0 9 ? * 0')[0] == 'cron_invalid_field'


@pytest.mark.parametrize('expr', ['0 99 * * * ?', '0 0 25 * * ?', '0 0 0 ? FOO *', '0 a * * * ?'])
def test_out_of_range_values_are_rejected_at_level_one(expr):
    assert _code(expr)[0] == 'cron_invalid_field'


def test_what_croniter_rejects_is_rejected():
    # Quartz years go up to 2199; croniter stops at 2099.
    validate_quartz_syntax('0 0 0 1 1 ? 2150')
    assert _code('0 0 0 1 1 ? 2150')[0] == 'cron_invalid'


def test_wrapping_ranges_run_at_level_two():
    runs = next_runs('0 0 22-2 * * ?', after=START, count=4)
    assert [r.hour for r in runs] == [1, 2, 22, 23]


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


# --- DST and the interval check ----------------------------------------------------

def test_a_schedule_stays_valid_just_before_a_dst_change():
    # New York skips 02:00-03:00 on 2026-03-08 and repeats 01:00-02:00 on 2026-11-01.
    for now in (datetime(2026, 3, 8, 6, 55, tzinfo=UTC), datetime(2026, 10, 31, 23, tzinfo=UTC)):
        for expr in ('0 0/30 * * * ?', '0 0/30 2 * * ?', '0 0/5 * * * ?'):
            assert validate_schedule(expr, 'America/New_York', now=now) == expr


def test_runs_on_the_same_instant_count_once(monkeypatch):
    """Should croniter map several wall-clock runs to one instant, it is one run."""
    from src.common import quartz_cron

    instants = [datetime(2026, 3, 8, 7, tzinfo=UTC)] * 3 + [
        datetime(2026, 3, 8, 7, 30, tzinfo=UTC), datetime(2026, 3, 8, 7, 15, tzinfo=UTC),
        datetime(2026, 3, 8, 8, tzinfo=UTC),
    ]

    class Fake:
        def __init__(self):
            self._runs = iter(instants)

        def get_next(self, _type):
            try:
                return next(self._runs)
            except StopIteration:
                raise CroniterError('no more') from None

    monkeypatch.setattr(quartz_cron, '_iterator', lambda cron, start: Fake())
    expr = '0 0/30 * * * ?'
    assert next_runs(expr, 'America/New_York', after=START, count=5) == [
        datetime(2026, 3, 8, 7, tzinfo=UTC), datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
        datetime(2026, 3, 8, 8, tzinfo=UTC),
    ]
    assert validate_schedule(expr, 'America/New_York', now=START) == expr
    end = datetime(2026, 3, 9, tzinfo=UTC)
    assert count_runs(expr, 'America/New_York', START, end, limit=100) == 3
