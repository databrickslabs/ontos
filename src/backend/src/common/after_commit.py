"""Run side effects once a database transaction has committed.

A side effect outside the database (a Unity Catalog change, a Git file) can't be
rolled back with it. ``run_after_commit`` keeps the callback in ``Session.info``
and runs it when the session's outermost transaction commits; a rollback of that
transaction drops it, and a rolled-back savepoint drops only the callbacks queued
inside it.
"""

from typing import Callable

from sqlalchemy import event
from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)

_PENDING_KEY = "ontos_after_commit_callbacks"
_COMMITTED_KEY = "ontos_after_commit_root_committed"
_LISTENING_KEY = "ontos_after_commit_listening"
# A callback that queues another one in the same session: the chain stops here
_MAX_CALLBACKS_PER_COMMIT = 100


def _within(transaction, ancestor) -> bool:
    while transaction is not None:
        if transaction is ancestor:
            return True
        transaction = transaction.parent
    return False


def _mark_committed(session: Session) -> None:
    # ``after_commit`` also fires when a savepoint is released: the work isn't
    # committed until the outermost transaction is.
    if not session.in_nested_transaction():
        session.info[_COMMITTED_KEY] = True


def _transaction_ended(session: Session, transaction) -> None:
    """The root transaction is over (its connection is back in the pool):
    run the callbacks if it committed, drop them if it didn't (a rollback, or a
    ``close()`` that never committed)."""
    if transaction.parent is not None:
        return
    committed = session.info.pop(_COMMITTED_KEY, False)
    pending = session.info.pop(_PENDING_KEY, [])
    if not committed:
        if pending:
            logger.info("Transaction ended without a commit: %d after-commit callback(s) dropped",
                        len(pending))
        return
    # Callbacks queued by a callback join the same run (bounded); they are never
    # kept for an unrelated later commit.
    session.info[_PENDING_KEY] = pending
    ran = 0
    while session.info.get(_PENDING_KEY):
        if ran >= _MAX_CALLBACKS_PER_COMMIT:
            logger.warning("After-commit callbacks chained past %d: the rest are dropped",
                           _MAX_CALLBACKS_PER_COMMIT)
            break
        callback, _ = session.info[_PENDING_KEY].pop(0)
        ran += 1
        try:
            callback()
        except Exception:
            logger.warning("After-commit callback failed", exc_info=True)
    session.info.pop(_PENDING_KEY, None)


def _drop_pending(session: Session, previous_transaction) -> None:
    pending = session.info.get(_PENDING_KEY)
    if not pending:
        return
    if not previous_transaction.nested:
        session.info.pop(_PENDING_KEY, None)
        return
    pending[:] = [(callback, transaction) for callback, transaction in pending
                  if not _within(transaction, previous_transaction)]


def run_after_commit(db: Session, callback: Callable[[], None]) -> None:
    """Call ``callback`` once ``db``'s outermost transaction has committed and
    ended, best effort.

    It runs after the transaction's connection went back to the pool, so it can
    open a connection of its own even when the pool is small. It never runs when
    the transaction rolls back or the session is closed without a commit. A
    failure in it is logged, not raised, and doesn't stop the callbacks queued
    after it. A callback queued from inside a callback runs in the same pass.
    """
    # The innermost transaction it is queued in: a savepoint rolled back drops it
    transaction = db.get_nested_transaction() or db.get_transaction()
    db.info.setdefault(_PENDING_KEY, []).append((callback, transaction))
    if not db.info.get(_LISTENING_KEY):
        db.info[_LISTENING_KEY] = True
        event.listen(db, "after_commit", _mark_committed)
        event.listen(db, "after_transaction_end", _transaction_ended)
        event.listen(db, "after_soft_rollback", _drop_pending)
