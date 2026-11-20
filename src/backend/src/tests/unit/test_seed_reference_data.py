"""The app's startup seeds the reference data a fresh database gets no migration
for (create_all() + stamp): certification levels, data product types (#1209)
and maturity levels. Runs the function `startup_event` calls."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.common.database as database
import src.db_models  # noqa: F401  (registers every model on Base.metadata)
from src.app import _seed_reference_data
from src.common.database import Base
from src.db_models.certification_levels import CertificationLevelDb
from src.db_models.data_product_types import DataProductTypeDb
from src.db_models.maturity import MaturityLevelDb


@pytest.fixture
def fresh_database(monkeypatch):
    """An empty database built like a fresh install, used by the startup code."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "get_session_factory", lambda: session_factory)
    yield session_factory
    engine.dispose()


def test_a_fresh_database_gets_the_built_in_data_product_types(fresh_database):
    _seed_reference_data()

    with fresh_database() as db:
        types = db.query(DataProductTypeDb).order_by(DataProductTypeDb.sort_order).all()
        assert [(t.key, t.is_default) for t in types] == [
            ("source-aligned", True),
            ("aggregate", False),
            ("consumer-aligned", False),
            ("source", False),
            ("sink", False),
        ]


def test_it_seeds_every_reference_table(fresh_database):
    _seed_reference_data()

    with fresh_database() as db:
        assert db.query(CertificationLevelDb).count() > 0
        assert db.query(MaturityLevelDb).count() > 0


def test_running_it_again_changes_nothing(fresh_database):
    _seed_reference_data()
    _seed_reference_data()

    with fresh_database() as db:
        assert db.query(DataProductTypeDb).count() == 5
