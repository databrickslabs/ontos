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
_LISTENING_KEY = "ontos_after_commit_listening"


def _within(transaction, ancestor) -> bool:
    while transaction is not None:
        if transaction is ancestor:
            return True
        transaction = transaction.parent
    return False


def _run_pending(session: Session) -> None:
    # ``after_commit`` also fires when a savepoint is released: the work isn't
    # committed until the outermost transaction is.
    if session.in_nested_transaction():
        return
    for callback, _ in session.info.pop(_PENDING_KEY, []):
        try:
            callback()
        except Exception:
            logger.warning("After-commit callback failed", exc_info=True)


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
    """Call ``callback`` once ``db``'s transaction commits, best effort.

    It never runs when the transaction rolls back. A failure in it is logged,
    not raised, and doesn't stop the callbacks queued after it.
    """
    # The innermost transaction it is queued in: a savepoint rolled back drops it
    transaction = db.get_nested_transaction() or db.get_transaction()
    db.info.setdefault(_PENDING_KEY, []).append((callback, transaction))
    if not db.info.get(_LISTENING_KEY):
        db.info[_LISTENING_KEY] = True
        event.listen(db, "after_commit", _run_pending)
        event.listen(db, "after_soft_rollback", _drop_pending)
