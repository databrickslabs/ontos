"""An imported product is delivered (Unity Catalog / Git) after its commit (#1385).

Delivering inside the import's savepoint left a change in Unity Catalog or Git
for a product a later failure rolled back.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.orm import Session, object_session

from src.common.after_commit import run_after_commit
from src.controller.data_products_manager import DataProductsManager


def _odps(name: str) -> dict:
    return {
        "apiVersion": "v1.0.0", "kind": "DataProduct", "name": name, "version": "1.0.0",
        "status": "draft", "productType": "sourceAligned", "owner": "test@example.com",
    }


@pytest.fixture
def committing_session(db_session):
    """A session whose commits are kept and whose rollback drops only what
    wasn't committed, as on a real database."""
    session = Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")
    yield session
    session.close()


@pytest.fixture
def events(committing_session, monkeypatch):
    """The order of commits and deliveries, with delivery modes active."""
    log = []
    real_commit = committing_session.commit

    def commit():
        log.append("commit")
        return real_commit()

    monkeypatch.setattr(committing_session, "commit", commit)

    def deliver(payload):
        entity = payload.data["entity"]
        # Read the way a file model does, relationships included
        assert entity.output_ports is not None and entity.support_channels is not None
        assert object_session(entity) is not committing_session
        log.append(f"deliver:{entity.name}")
        return SimpleNamespace(all_success=True)

    service = SimpleNamespace(get_active_modes=lambda: ["direct"], deliver=deliver)
    monkeypatch.setattr("src.controller.delivery_service.get_delivery_service", lambda: service)
    return log


@pytest.fixture
def manager(committing_session, events) -> DataProductsManager:
    return DataProductsManager(db=committing_session, tags_manager=MagicMock())


def _import(manager, *names):
    content = yaml.safe_dump([_odps(name) for name in names]).encode("utf-8")
    return manager.create_products_from_files([("p.yaml", content)], user="a@b.com")


def test_a_committed_product_is_delivered_once_after_its_commit(manager, events):
    result = _import(manager, "P A", "P B")

    assert result.created == 2
    assert events == ["commit", "deliver:P A", "commit", "deliver:P B", "commit"]


def test_a_rolled_back_product_is_not_delivered_and_the_others_are(
    manager, events, monkeypatch,
):
    real = manager._fire_create_trigger

    def trigger(db, product, *args, **kwargs):
        if product.name == "P B":
            raise RuntimeError("fails after the delivery was queued")
        return real(db, product, *args, **kwargs)

    monkeypatch.setattr(manager, "_fire_create_trigger", trigger)

    result = _import(manager, "P A", "P B", "P C")

    assert (result.created, result.failed) == (2, 1)
    assert events == ["commit", "deliver:P A", "commit", "deliver:P C", "commit"]


def test_a_product_whose_commit_fails_is_not_delivered(
    manager, committing_session, events, monkeypatch,
):
    real_commit = committing_session.commit
    calls = []

    def commit():
        calls.append(1)
        if len(calls) == 2:  # the commit of P B
            raise RuntimeError("commit failed")
        return real_commit()

    monkeypatch.setattr(committing_session, "commit", commit)

    result = _import(manager, "P A", "P B", "P C")

    assert (result.created, result.failed) == (2, 1)
    assert "deliver:P B" not in events
    assert [e for e in events if e.startswith("deliver:")] == ["deliver:P A", "deliver:P C"]


def test_a_failing_delivery_does_not_fail_the_import(manager, monkeypatch):
    def broken():
        raise RuntimeError("unity catalog is down")

    monkeypatch.setattr("src.controller.delivery_service.get_delivery_service", broken)

    assert _import(manager, "P A").created == 1


class TestRunAfterCommit:
    def test_a_released_savepoint_does_not_run_it(self, committing_session):
        ran = []
        savepoint = committing_session.begin_nested()
        run_after_commit(committing_session, lambda: ran.append(1))
        savepoint.commit()
        assert ran == []
        committing_session.commit()
        assert ran == [1]

    def test_a_rolled_back_savepoint_drops_only_its_own(self, committing_session):
        ran = []
        run_after_commit(committing_session, lambda: ran.append("outer"))
        savepoint = committing_session.begin_nested()
        run_after_commit(committing_session, lambda: ran.append("inner"))
        savepoint.rollback()
        committing_session.commit()
        assert ran == ["outer"]

    def test_a_rollback_drops_everything(self, committing_session):
        ran = []
        committing_session.execute(text("SELECT 1"))
        run_after_commit(committing_session, lambda: ran.append(1))
        committing_session.rollback()
        committing_session.commit()
        assert ran == []

    def test_a_failing_callback_does_not_stop_the_next(self, committing_session):
        ran = []

        def broken():
            raise RuntimeError("boom")

        run_after_commit(committing_session, broken)
        run_after_commit(committing_session, lambda: ran.append(1))
        committing_session.commit()
        assert ran == [1]


class TestRunAfterCommitOwnEngine:
    """Sessions of a small pool: the callbacks run once the connection is back."""

    @pytest.fixture
    def engine(self, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import QueuePool

        engine = create_engine(
            f"sqlite:///{tmp_path / 'pool.db'}", poolclass=QueuePool,
            pool_size=1, max_overflow=0, pool_timeout=1,
        )
        yield engine
        engine.dispose()

    def test_a_callback_can_open_a_connection_with_a_pool_of_one(self, engine):
        seen = []

        def callback():
            with Session(engine) as other:
                seen.append(other.execute(text("SELECT 1")).scalar())

        session = Session(engine)
        session.execute(text("SELECT 1"))
        run_after_commit(session, callback)
        session.commit()
        session.close()

        assert seen == [1]

    def test_a_closed_session_without_a_commit_does_not_run_them_later(self, engine):
        ran = []
        session = Session(engine)
        session.execute(text("SELECT 1"))
        run_after_commit(session, lambda: ran.append("stale"))
        session.close()

        session.execute(text("SELECT 1"))
        session.commit()

        assert ran == []
        assert "ontos_after_commit_callbacks" not in session.info
        session.close()

    def test_a_callback_queued_by_a_callback_runs_in_the_same_pass(self, engine):
        ran = []
        session = Session(engine)

        def first():
            ran.append("first")
            run_after_commit(session, lambda: ran.append("second"))

        session.execute(text("SELECT 1"))
        run_after_commit(session, first)
        session.commit()

        assert ran == ["first", "second"]
        session.execute(text("SELECT 1"))
        session.commit()
        assert ran == ["first", "second"]
        session.close()

    def test_a_chain_of_callbacks_is_bounded(self, engine):
        ran = []
        session = Session(engine)

        def again():
            ran.append(1)
            run_after_commit(session, again)

        session.execute(text("SELECT 1"))
        run_after_commit(session, again)
        session.commit()

        # The queued callback plus 100 chained ones
        assert len(ran) == 101
        session.execute(text("SELECT 1"))
        session.commit()
        assert len(ran) == 101
        session.close()

    def test_more_than_the_bound_queued_by_the_transaction_all_run(self, engine):
        ran = []
        session = Session(engine)
        session.execute(text("SELECT 1"))
        for i in range(150):
            run_after_commit(session, lambda i=i: ran.append(i))
        session.commit()
        session.close()

        assert ran == list(range(150))

    def test_a_failed_flush_in_a_savepoint_keeps_the_outer_callbacks(self, engine):
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

        class _Base(DeclarativeBase):
            pass

        class _Row(_Base):
            __tablename__ = "after_commit_rows"
            id: Mapped[int] = mapped_column(primary_key=True)

        _Base.metadata.create_all(engine)
        ran = []
        session = Session(engine)
        session.execute(text("SELECT 1"))
        run_after_commit(session, lambda: ran.append("outer"))
        savepoint = session.begin_nested()
        session.add(_Row(id=1))
        session.flush()
        session.expunge_all()
        session.add(_Row(id=1))
        with pytest.raises(IntegrityError):
            session.flush()
        savepoint.rollback()
        session.commit()
        session.close()

        assert ran == ["outer"]
