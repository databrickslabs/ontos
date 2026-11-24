"""The delivery outbox (#1688): a row per change and mode, tried after the commit, retried.

The rows are written in the change's transaction; the attempt after the commit and
the scheduler's worker read the entity in a session of their own.
"""
import os

os.environ['TESTING'] = 'true'

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
import yaml
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, object_session

from src.controller import delivery_outbox_manager as outbox
from src.controller.data_products_manager import DataProductsManager
from src.controller.delivery_outbox_manager import (
    MAX_ATTEMPTS,
    RETENTION,
    DeliveryEntityNotFoundError,
    DeliveryEntityTypeUnsupportedError,
    DeliveryNoActiveModeError,
    DeliveryOutboxWorker,
    delivery_outbox_manager,
)
from src.controller.delivery_service import DeliveryMode, DeliveryResult, DeliveryResults
from src.controller.workflow_scheduler import WorkflowScheduler, notify_delivery_queued
from src.db_models.data_products import DataProductDb
from src.db_models.delivery_outbox import DeliveryOutboxDb
from src.db_models.scheduler_claims import SchedulerClaimDb
from src.repositories.delivery_outbox_repository import delivery_outbox_repo

UTC = timezone.utc


def _now():
    return datetime.now(UTC)


def _utc(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class _Service:
    """A delivery service; a mode in ``failing`` fails with that code."""

    def __init__(self, modes=('indirect',)):
        self.modes = list(modes)
        self.failing = {}
        self.calls = []

    def get_active_modes(self):
        return [DeliveryMode(mode) for mode in self.modes]

    def deliver(self, payload, modes=None):
        results = DeliveryResults()
        entity = payload.data['entity']
        for mode in modes:
            # Read the way a file model does, relationships included
            assert entity.output_ports is not None and entity.support_channels is not None
            self.calls.append((entity.name, mode.value, object_session(entity)))
            code = self.failing.get(mode.value)
            results.add(DeliveryResult(
                success=code is None, mode=mode, change_type=payload.change_type,
                entity_type=payload.entity_type, entity_id=payload.entity_id,
                details={'error_code': code} if code else {},
            ))
        return results


@pytest.fixture
def service(monkeypatch):
    fake = _Service()
    monkeypatch.setattr('src.controller.delivery_service.get_delivery_service', lambda: fake)
    return fake


@pytest.fixture
def sessions(db_session):
    """New sessions on the test connection whose commits are kept (as savepoints)."""
    opened = []

    def factory():
        session = Session(bind=db_session.connection(), join_transaction_mode='create_savepoint')
        opened.append(session)
        return session

    yield factory
    # The newest first: closing one ends the savepoints opened after it
    for session in reversed(opened):
        try:
            session.close()
        except OperationalError:
            pass  # its savepoint already ended with an older one's


@pytest.fixture
def manager(sessions, service) -> DataProductsManager:
    return DataProductsManager(db=sessions(), tags_manager=MagicMock())


def _odps(name):
    return {
        'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'name': name, 'version': '1.0.0',
        'status': 'draft', 'productType': 'sourceAligned', 'owner': 'test@example.com',
    }


def _import(manager, *names):
    content = yaml.safe_dump([_odps(name) for name in names]).encode('utf-8')
    return manager.create_products_from_files([('p.yaml', content)], user='a@b.com')


def _rows(sessions):
    db = sessions()
    return db.query(DeliveryOutboxDb).order_by(DeliveryOutboxDb.created_at,
                                               DeliveryOutboxDb.mode).all()


def _row(sessions, row_id):
    return sessions().get(DeliveryOutboxDb, row_id)


class TestRowsOfTheChange:
    def test_a_rolled_back_product_leaves_no_row_and_the_others_are_delivered(
        self, manager, sessions, service, monkeypatch,
    ):
        real = manager._fire_create_trigger

        def trigger(db, product, *args, **kwargs):
            if product.name == 'P B':
                raise RuntimeError('fails after its outbox row was written')
            return real(db, product, *args, **kwargs)

        monkeypatch.setattr(manager, '_fire_create_trigger', trigger)

        result = _import(manager, 'P A', 'P B', 'P C')

        assert (result.created, result.failed) == (2, 1)
        rows = _rows(sessions)
        assert sorted(row.entity_id for row in rows) == sorted(result.created_ids)
        assert {(row.status, row.attempts, row.mode, row.change_type) for row in rows} == {
            ('delivered', 1, 'indirect', 'product_create')}
        assert {row.queued_by for row in rows} == {'a@b.com'}
        assert [name for name, _, _ in service.calls] == ['P A', 'P C']

    def test_no_row_when_no_mode_is_active(self, manager, sessions, service):
        service.modes = []

        result = _import(manager, 'P A')

        assert result.items[0].delivery is None
        assert _rows(sessions) == []

    def test_one_row_per_mode_and_a_retry_runs_only_the_failed_one(
        self, manager, sessions, service,
    ):
        service.modes = ['indirect', 'manual']
        service.failing = {'indirect': 'delivery_git_unavailable'}

        result = _import(manager, 'P A')

        delivery = result.items[0].delivery
        assert (delivery.status, delivery.code, delivery.params) == (
            'failed', 'delivery_git_unavailable', {'mode': 'indirect'})
        assert result.delivery_failed == 1
        by_mode = {row.mode: row for row in _rows(sessions)}
        assert (by_mode['manual'].status, by_mode['manual'].attempts) == ('delivered', 1)
        indirect = by_mode['indirect']
        assert (indirect.status, indirect.attempts, indirect.code) == (
            'pending', 1, 'delivery_git_unavailable')
        assert _utc(indirect.next_attempt_at) - _utc(indirect.last_attempt_at) == timedelta(
            minutes=1)

        service.failing = {}
        service.calls.clear()
        tried = DeliveryOutboxWorker().run(sessions, _now() + timedelta(minutes=2))

        assert tried == 1
        assert [(name, mode) for name, mode, _ in service.calls] == [('P A', 'indirect')]
        assert _row(sessions, indirect.id).status == 'delivered'

    def test_a_row_held_elsewhere_is_reported_pending(self, manager, sessions, monkeypatch):
        monkeypatch.setattr(delivery_outbox_repo, 'claim', lambda db, row_id: None)

        delivery = _import(manager, 'P A').items[0].delivery

        assert (delivery.status, delivery.code, delivery.params) == (
            'pending', 'delivery_pending', {'mode': 'indirect'})


class TestAttempts:
    def test_retries_back_off_and_stop_at_the_limit(self, manager, sessions, service):
        service.failing = {'indirect': 'delivery_git_write_failed'}
        _import(manager, 'P A')
        row_id = _rows(sessions)[0].id
        worker = DeliveryOutboxWorker()
        delays = []
        for _ in range(MAX_ATTEMPTS - 1):
            row = _row(sessions, row_id)
            due = _utc(row.next_attempt_at)
            delays.append(due - _utc(row.last_attempt_at))
            # Not before it is due
            assert worker.run(sessions, due - timedelta(seconds=1)) == 0
            assert worker.run(sessions, due) == 1

        row = _row(sessions, row_id)
        assert delays == [timedelta(minutes=m) for m in (1, 4, 16, 64)]
        assert (row.status, row.attempts, row.next_attempt_at, row.code) == (
            'failed', MAX_ATTEMPTS, None, 'delivery_git_write_failed')
        calls = len(service.calls)
        assert worker.run(sessions, _now() + timedelta(days=1)) == 0
        assert len(service.calls) == calls

    def test_a_mode_turned_off_meanwhile_is_not_delivered(self, manager, sessions, service):
        service.failing = {'indirect': 'delivery_git_unavailable'}
        _import(manager, 'P A')
        service.modes = ['manual']
        service.calls.clear()

        DeliveryOutboxWorker().run(sessions, _now() + timedelta(minutes=2))

        row = _rows(sessions)[0]
        assert (row.status, row.code, row.attempts) == ('delivered', 'delivery_mode_inactive', 1)
        assert service.calls == []

    def test_a_row_whose_entity_is_gone_fails_without_retries(self, manager, sessions, service):
        service.failing = {'indirect': 'delivery_git_unavailable'}
        result = _import(manager, 'P A')
        db = sessions()
        db.query(DataProductDb).filter(DataProductDb.id == result.created_ids[0]).delete()
        db.commit()

        DeliveryOutboxWorker().run(sessions, _now() + timedelta(minutes=2))

        row = _rows(sessions)[0]
        assert (row.status, row.code, row.next_attempt_at) == (
            'failed', 'delivery_entity_not_found', None)

    def test_a_delivery_that_raises_is_a_failed_attempt(self, manager, sessions, service,
                                                         monkeypatch):
        def broken(payload, modes=None):
            raise OSError('disk full')

        monkeypatch.setattr(service, 'deliver', broken)

        delivery = _import(manager, 'P A').items[0].delivery

        assert (delivery.status, delivery.code) == ('failed', 'delivery_failed')
        assert (_rows(sessions)[0].status, _rows(sessions)[0].attempts) == ('pending', 1)

    def test_the_entity_is_read_in_the_attempts_own_session(self, manager, sessions, service):
        """Never the request's object: expired after its commit, detached once closed."""
        service.failing = {'indirect': 'delivery_git_unavailable'}
        _import(manager, 'P A')
        request_session = manager._db
        request_session.close()
        service.failing = {}

        DeliveryOutboxWorker().run(sessions, _now() + timedelta(minutes=2))

        owners = [owner for _, _, owner in service.calls]
        assert len(owners) == 2 and all(owner is not None for owner in owners)
        assert all(owner is not request_session for owner in owners)
        assert _rows(sessions)[0].status == 'delivered'


class TestOutcome:
    def _row(self, status, mode='indirect', code=None, attempts=1, params=None):
        return DeliveryOutboxDb(status=status, mode=mode, code=code, attempts=attempts,
                                params=params)

    def test_outcomes(self):
        assert outbox.outcome_of([]) is None
        delivered = outbox.outcome_of([self._row('delivered'), self._row('delivered', 'manual')])
        assert (delivered.status, delivered.params) == (
            'delivered', {'modes': ['indirect', 'manual']})
        skipped = outbox.outcome_of([self._row('delivered', code='delivery_not_applicable'),
                                     self._row('delivered', code='delivery_mode_inactive')])
        assert (skipped.status, skipped.code) == ('skipped', 'delivery_not_applicable')
        pending = outbox.outcome_of([self._row('delivered'), self._row('pending', 'manual',
                                                                     attempts=0)])
        assert (pending.status, pending.params) == ('pending', {'mode': 'manual'})
        retried = outbox.outcome_of([self._row('pending', code='delivery_git_unavailable',
                                               params={'mode': 'indirect'})])
        assert (retried.status, retried.code) == ('failed', 'delivery_git_unavailable')


class TestRedeliver:
    def test_open_rows_start_over_and_are_delivered(self, manager, sessions, service):
        service.failing = {'indirect': 'delivery_git_unavailable'}
        product_id = _import(manager, 'P A').created_ids[0]
        row_id = _rows(sessions)[0].id
        service.failing = {}
        db = sessions()

        ids = delivery_outbox_manager.redeliver(db, 'DataProduct', product_id, user='admin')
        rows = outbox.attempt_all(sessions, ids)

        assert ids == [row_id]
        assert [(row.status, row.attempts, row.queued_by) for row in rows] == [
            ('delivered', 1, 'admin')]
        assert outbox.outcome_of(rows).status == 'delivered'

    def test_without_open_rows_a_row_per_active_mode_is_added(self, manager, sessions, service):
        product_id = _import(manager, 'P A').created_ids[0]
        service.modes = ['indirect', 'manual']
        db = sessions()

        ids = delivery_outbox_manager.redeliver(db, 'DataProduct', product_id, user='admin')

        rows = delivery_outbox_repo.by_ids(sessions(), ids)
        assert [(row.mode, row.change_type, row.status) for row in rows] == [
            ('indirect', 'product_update', 'pending'), ('manual', 'product_update', 'pending')]

    def test_refusals(self, manager, sessions, service):
        product_id = _import(manager, 'P A').created_ids[0]
        db = sessions()
        with pytest.raises(DeliveryEntityTypeUnsupportedError):
            delivery_outbox_manager.redeliver(db, 'Nothing', product_id, user='admin')
        with pytest.raises(DeliveryEntityNotFoundError) as missing:
            delivery_outbox_manager.redeliver(db, 'DataProduct', 'missing', user='admin')
        assert missing.value.code == 'delivery_entity_not_found'
        service.modes = []
        with pytest.raises(DeliveryNoActiveModeError):
            delivery_outbox_manager.redeliver(db, 'DataProduct', product_id, user='admin')


class TestWorkerSchedule:
    def test_passes_without_polling(self, manager, sessions, service):
        clock = {'now': _now()}
        worker = DeliveryOutboxWorker(clock=lambda: clock['now'])
        assert worker.due(clock['now'])  # the first pass
        worker.run(sessions, clock['now'])
        assert not worker.due(clock['now'])
        assert worker.next_deadline() is None  # no pending row: no deadline
        # A request in the same slot asks for nothing; one in a later slot asks for a pass
        assert worker.note_activity() is False
        clock['now'] += outbox.SWEEP_INTERVAL
        assert worker.note_activity() is True
        assert worker.due(clock['now'])

    def test_the_next_pending_row_is_the_deadline(self, manager, sessions, service):
        service.failing = {'indirect': 'delivery_git_unavailable'}
        _import(manager, 'P A')
        row = _rows(sessions)[0]
        worker = DeliveryOutboxWorker()

        worker.run(sessions, _now())

        assert worker.next_deadline() == _utc(row.next_attempt_at)

    def test_a_failed_pass_is_retried_later(self, sessions):
        def broken():
            raise RuntimeError('database unreachable')

        worker = DeliveryOutboxWorker()
        now = _now()
        assert worker.run(broken, now) == 0
        assert worker.next_deadline() == now + outbox.ERROR_RETRY
        assert worker.run(broken, now) == 0
        assert worker.next_deadline() == now + 2 * outbox.ERROR_RETRY

    def test_the_scheduler_sleeps_until_the_outbox_deadline(self, sessions):
        scheduler = WorkflowScheduler(sessions, instance_id='a')
        now = _now()
        assert scheduler._sleep_seconds(now) is None

        notify_delivery_queued(now + timedelta(minutes=4))

        assert scheduler._sleep_seconds(now) == pytest.approx(240.5)
        assert scheduler._wake.is_set()
        assert WorkflowScheduler(sessions, deliver_outbox=False).run_outbox(now) == 0

    def test_with_the_workflow_scheduler_off_the_outbox_is_still_retried(
        self, manager, sessions, service, monkeypatch,
    ):
        service.failing = {'indirect': 'delivery_git_unavailable'}
        _import(manager, 'P A')
        service.failing = {}
        clock = {'now': _now()}
        scheduler = WorkflowScheduler(sessions, instance_id='a', run_workflows=False,
                                      clock=lambda: clock['now'])

        def no_workflows(*args, **kwargs):
            raise AssertionError('no workflow is read or run')

        monkeypatch.setattr(scheduler, 'run_once', no_workflows)
        monkeypatch.setattr(scheduler, '_refresh', no_workflows)

        delay = scheduler._tick()  # the first pass: the row isn't due yet
        assert _rows(sessions)[0].status == 'pending'
        assert 0 < delay <= 61
        clock['now'] += timedelta(minutes=2)

        assert scheduler._tick() is None  # delivered: nothing left to wake up for
        assert _rows(sessions)[0].status == 'delivered'

    def test_delivered_rows_are_pruned_once_a_day(self, manager, sessions, service):
        _import(manager, 'P A', 'P B')
        service.failing = {'indirect': 'delivery_git_unavailable'}
        _import(manager, 'P C')
        db = sessions()
        old, recent = db.query(DeliveryOutboxDb).filter(
            DeliveryOutboxDb.status == 'delivered').all()
        now = _now()
        old.delivered_at = now - RETENTION - timedelta(minutes=1)
        old_id, recent_id = old.id, recent.id
        db.commit()
        worker = DeliveryOutboxWorker()

        worker.run(sessions, now)

        left = {row.id: row.status for row in _rows(sessions)}
        assert old_id not in left and recent_id in left and 'pending' in left.values()
        claim = sessions().query(SchedulerClaimDb).filter(
            SchedulerClaimDb.task_key == outbox.PRUNE_TASK_KEY).one()
        assert claim.outcome == {'status': 'done', 'deleted': 1}
        # Not again the same day
        db = sessions()
        db.get(DeliveryOutboxDb, recent_id).delivered_at = now - RETENTION - timedelta(minutes=1)
        db.commit()
        worker.run(sessions, now + timedelta(minutes=1))
        assert recent_id in {row.id for row in _rows(sessions)}
