"""A DB session bound to the current thread, for the manager singletons.

The manager singletons (``SettingsManager``, ``JobsManager``) share one
long-lived Session, which handlers on the event loop use. A Session is not
thread-safe, so work those managers run in a threadpool binds its own Session
with ``thread_session``: while it runs, ``_db`` on that thread is the new
Session, and every other thread still sees the shared one.
"""

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

_local = threading.local()


def bound_session() -> Optional[Any]:
    """The Session bound to the current thread, if any."""
    return getattr(_local, 'session', None)


@contextmanager
def thread_session(factory: Callable[[], Any]) -> Iterator[Any]:
    """Bind a new Session from ``factory`` to this thread; commit, or roll back on error."""
    session = factory()
    previous = bound_session()
    _local.session = session
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        _local.session = previous
        session.close()


class ThreadBoundDb:
    """Mixin: ``_db`` is the Session bound to this thread, else the shared one."""

    @property
    def _db(self) -> Any:
        session = bound_session()
        return session if session is not None else self.__dict__.get('_shared_db')

    @_db.setter
    def _db(self, value: Any) -> None:
        self.__dict__['_shared_db'] = value
