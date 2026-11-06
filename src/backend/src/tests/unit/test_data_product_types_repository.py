"""Tests for the data product types repository (seeding)."""

from src.db_models.data_product_types import DataProductTypeDb
from src.repositories.data_product_types_repository import (
    SEEDED_TYPE_KEYS,
    data_product_types_repo,
)


def test_seed_defaults_fills_empty_table(db_session):
    created = data_product_types_repo.seed_defaults(db_session)

    assert [t.key for t in created] == [
        "source-aligned",
        "aggregate",
        "consumer-aligned",
        "source",
        "sink",
    ]
    assert {t.key for t in data_product_types_repo.get_all_ordered(db_session)} == SEEDED_TYPE_KEYS
    assert all(t.is_active and not t.is_imported for t in created)


def test_seed_defaults_marks_exactly_one_default(db_session):
    data_product_types_repo.seed_defaults(db_session)

    defaults = (
        db_session.query(DataProductTypeDb).filter(DataProductTypeDb.is_default.is_(True)).all()
    )
    assert [t.key for t in defaults] == ["source-aligned"]


def test_seed_defaults_is_idempotent(db_session):
    data_product_types_repo.seed_defaults(db_session)
    data_product_types_repo.seed_defaults(db_session)

    assert db_session.query(DataProductTypeDb).count() == len(SEEDED_TYPE_KEYS)


def test_seed_defaults_leaves_existing_types_alone(db_session):
    data_product_types_repo.create(db_session, key="custom", label="Custom", sort_order=1)

    data_product_types_repo.seed_defaults(db_session)

    assert [t.key for t in data_product_types_repo.get_all_ordered(db_session)] == ["custom"]
    assert data_product_types_repo.get_by_key(db_session, "aggregate") is None
