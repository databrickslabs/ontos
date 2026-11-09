"""Tests for the data product types manager (CRUD, default and in-use rules)."""

import uuid

import pytest
from pydantic import ValidationError

from src.controller.data_product_types_manager import (
    DataProductTypeInUseError,
    DataProductTypeKeyExistsError,
    DataProductTypeNotFoundError,
    DataProductTypesManager,
    DefaultDataProductTypeInactiveError,
    SeededDataProductTypeDeleteError,
)
from src.db_models.data_products import DataProductDb
from src.models.data_product_types import DataProductTypeCreate, DataProductTypeUpdate
from src.repositories.data_product_types_repository import data_product_types_repo


@pytest.fixture
def manager():
    return DataProductTypesManager()


@pytest.fixture
def seeded(db_session):
    data_product_types_repo.seed_defaults(db_session)
    db_session.flush()


def _type(db_session, key):
    return data_product_types_repo.get_by_key(db_session, key)


def _default_keys(manager, db_session):
    return [t.key for t in manager.list_types(db_session) if t.is_default]


def _add_product(db_session, type_key):
    product = DataProductDb(
        id=str(uuid.uuid4()),
        name="Typed Product",
        version="1.0.0",
        status="draft",
        product_type_id=_type(db_session, type_key).id,
    )
    db_session.add(product)
    db_session.flush()
    return product


# --- list ---


def test_list_marks_seeded_types_and_counts_usage(manager, db_session, seeded):
    manager.create_type(db_session, DataProductTypeCreate(key="custom", label="Custom"))
    _add_product(db_session, "aggregate")
    _add_product(db_session, "aggregate")

    by_key = {t.key: t for t in manager.list_types(db_session)}

    assert by_key["aggregate"].is_seeded and by_key["aggregate"].usage_count == 2
    assert by_key["sink"].usage_count == 0
    assert not by_key["custom"].is_seeded


def test_list_active_only_hides_inactive_types(manager, db_session, seeded):
    manager.update_type(db_session, _type(db_session, "sink").id, DataProductTypeUpdate(is_active=False))

    keys = [t.key for t in manager.list_types(db_session, active_only=True)]

    assert "sink" not in keys
    assert len(keys) == 4


# --- create ---


def test_create_appends_after_last_type(manager, db_session, seeded):
    created = manager.create_type(db_session, DataProductTypeCreate(key="custom", label="Custom"))

    assert created.sort_order == 6
    assert created.is_active and not created.is_default and not created.is_imported
    assert [t.key for t in manager.list_types(db_session)][-1] == "custom"


def test_create_rejects_duplicate_key(manager, db_session, seeded):
    with pytest.raises(DataProductTypeKeyExistsError):
        manager.create_type(db_session, DataProductTypeCreate(key="aggregate", label="Again"))


def test_create_as_default_replaces_previous_default(manager, db_session, seeded):
    manager.create_type(
        db_session, DataProductTypeCreate(key="custom", label="Custom", is_default=True)
    )

    assert _default_keys(manager, db_session) == ["custom"]


def test_create_rejects_inactive_default(manager, db_session, seeded):
    with pytest.raises(DefaultDataProductTypeInactiveError):
        manager.create_type(
            db_session,
            DataProductTypeCreate(key="custom", label="Custom", is_default=True, is_active=False),
        )


@pytest.mark.parametrize("key", ["Source Aligned", "sourceAligned", "-lead", "trail-", "a--b"])
def test_create_model_rejects_keys_that_are_not_kebab_case(key):
    with pytest.raises(ValidationError):
        DataProductTypeCreate(key=key, label="X")


# --- update ---


def test_update_renames_and_keeps_key(manager, db_session, seeded):
    type_id = _type(db_session, "aggregate").id

    updated = manager.update_type(db_session, type_id, DataProductTypeUpdate(label="Composite"))

    assert updated.label == "Composite"
    assert updated.key == "aggregate"


def test_update_model_rejects_key_change():
    with pytest.raises(ValidationError):
        DataProductTypeUpdate(key="renamed")


def test_update_deactivates_type_in_use(manager, db_session, seeded):
    _add_product(db_session, "sink")

    updated = manager.update_type(
        db_session, _type(db_session, "sink").id, DataProductTypeUpdate(is_active=False)
    )

    assert not updated.is_active
    assert updated.usage_count == 1


def test_update_making_default_unsets_old_default(manager, db_session, seeded):
    manager.update_type(
        db_session, _type(db_session, "aggregate").id, DataProductTypeUpdate(is_default=True)
    )

    assert _default_keys(manager, db_session) == ["aggregate"]


def test_update_can_leave_no_default(manager, db_session, seeded):
    manager.update_type(
        db_session, _type(db_session, "source-aligned").id, DataProductTypeUpdate(is_default=False)
    )

    assert _default_keys(manager, db_session) == []


def test_update_refuses_to_deactivate_default(manager, db_session, seeded):
    with pytest.raises(DefaultDataProductTypeInactiveError):
        manager.update_type(
            db_session,
            _type(db_session, "source-aligned").id,
            DataProductTypeUpdate(is_active=False),
        )


def test_update_refuses_inactive_type_as_default(manager, db_session, seeded):
    sink_id = _type(db_session, "sink").id
    manager.update_type(db_session, sink_id, DataProductTypeUpdate(is_active=False))

    with pytest.raises(DefaultDataProductTypeInactiveError):
        manager.update_type(db_session, sink_id, DataProductTypeUpdate(is_default=True))
    assert _default_keys(manager, db_session) == ["source-aligned"]


def test_update_unknown_id_raises_not_found(manager, db_session, seeded):
    with pytest.raises(DataProductTypeNotFoundError):
        manager.update_type(db_session, uuid.uuid4(), DataProductTypeUpdate(label="X"))


# --- reorder ---


def test_reorder_sets_new_order(manager, db_session, seeded):
    order_map = {
        _type(db_session, "sink").id: 1,
        _type(db_session, "source-aligned").id: 5,
    }

    keys = [t.key for t in manager.reorder_types(db_session, order_map)]

    assert keys[0] == "sink"
    assert keys[-1] == "source-aligned"


def test_reorder_unknown_id_raises_not_found(manager, db_session, seeded):
    with pytest.raises(DataProductTypeNotFoundError):
        manager.reorder_types(db_session, {uuid.uuid4(): 1})


# --- delete ---


def test_delete_custom_unused_type(manager, db_session, seeded):
    created = manager.create_type(db_session, DataProductTypeCreate(key="custom", label="Custom"))

    manager.delete_type(db_session, created.id)

    assert _type(db_session, "custom") is None


def test_delete_refuses_type_in_use(manager, db_session, seeded):
    created = manager.create_type(db_session, DataProductTypeCreate(key="custom", label="Custom"))
    _add_product(db_session, "custom")

    with pytest.raises(DataProductTypeInUseError) as exc_info:
        manager.delete_type(db_session, created.id)
    assert exc_info.value.params == {"key": "custom", "count": 1}
    assert _type(db_session, "custom") is not None


@pytest.mark.parametrize("key", ["source-aligned", "aggregate", "consumer-aligned", "source", "sink"])
def test_delete_refuses_seeded_types_even_when_unused(manager, db_session, seeded, key):
    with pytest.raises(SeededDataProductTypeDeleteError):
        manager.delete_type(db_session, _type(db_session, key).id)


def test_delete_unknown_id_raises_not_found(manager, db_session, seeded):
    with pytest.raises(DataProductTypeNotFoundError):
        manager.delete_type(db_session, uuid.uuid4())
