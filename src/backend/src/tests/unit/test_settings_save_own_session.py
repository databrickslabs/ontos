"""A settings save in the threadpool uses its own DB session, one save at a time.

The manager singletons share one Session with the handlers on the event loop.
A Session is not thread-safe, so the threaded save binds its own Session to its
thread, and the loop keeps the shared one.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.controller.jobs_manager import JobsManager
from src.controller.settings_manager import SettingsManager


def _managers():
    shared = MagicMock(name='shared_session')
    manager = SettingsManager.__new__(SettingsManager)
    jobs = JobsManager.__new__(JobsManager)
    manager._db = shared
    jobs._db = shared
    manager._jobs = jobs
    return manager, jobs, shared


def _factory(sessions):
    def make():
        session = MagicMock(name=f'save_session_{len(sessions)}')
        sessions.append(session)
        return session
    return make


def test_a_threaded_save_has_its_own_session_and_the_loop_keeps_the_shared_one():
    manager, jobs, shared = _managers()
    sessions = []
    inside = threading.Event()
    release = threading.Event()
    seen = {}

    def save(payload):
        seen['settings'], seen['jobs'] = manager._db, jobs._db
        inside.set()
        assert release.wait(5)
        return 'saved', []

    manager.update_settings_with_warnings = save
    result = {}
    with patch('src.common.database.get_session_factory', return_value=_factory(sessions)):
        worker = threading.Thread(
            target=lambda: result.setdefault('r', manager.update_settings_off_loop({})),
        )
        worker.start()
        assert inside.wait(5)
        # A handler on the loop thread, during the save
        loop_side = (manager._db, jobs._db)
        release.set()
        worker.join(5)

    assert loop_side == (shared, shared)
    assert len(sessions) == 1
    assert seen == {'settings': sessions[0], 'jobs': sessions[0]}
    assert result['r'] == ('saved', [])
    sessions[0].commit.assert_called_once()
    sessions[0].close.assert_called_once()
    shared.commit.assert_not_called()


def test_concurrent_saves_run_one_at_a_time():
    manager, _, _ = _managers()
    active, peak = [0], [0]
    lock = threading.Lock()

    def save(payload):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        threading.Event().wait(0.05)
        with lock:
            active[0] -= 1
        return 'saved', []

    manager.update_settings_with_warnings = save
    with patch('src.common.database.get_session_factory', return_value=_factory([])):
        threads = [
            threading.Thread(target=manager.update_settings_off_loop, args=({},))
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)

    assert peak[0] == 1


def test_a_failed_save_rolls_back_its_session_and_unbinds_it():
    manager, _, shared = _managers()
    sessions = []

    def save(payload):
        raise ValueError('invalid branding URL')

    manager.update_settings_with_warnings = save
    with patch('src.common.database.get_session_factory', return_value=_factory(sessions)), \
            pytest.raises(ValueError):
        manager.update_settings_off_loop({})

    sessions[0].rollback.assert_called_once()
    sessions[0].commit.assert_not_called()
    sessions[0].close.assert_called_once()
    assert manager._db is shared
