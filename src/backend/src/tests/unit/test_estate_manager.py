"""EstateManager: DB-backed singleton CRUD for estates (#146)."""
import pytest

from src.controller.estate_manager import EstateManager, EstateNameConflictError
from src.models.estate import Estate, SharingPolicy


def _estate(name="EU Analytics", **overrides):
    data = dict(
        name=name,
        description="Analytics workspace",
        workspace_url="https://eu.cloud.databricks.com",
        cloud_type="azure",
        metastore_name="eu_analytics",
    )
    data.update(overrides)
    return Estate(**data)


@pytest.fixture
def manager():
    return EstateManager()


def test_a_created_estate_is_found_by_a_new_manager(db_session, manager):
    created = manager.create_estate(db_session, _estate(), user="admin@example.com")

    # A manager without in-memory state (as after a restart) reads it from the database.
    fetched = EstateManager().get_estate(db_session, created.id)
    assert fetched is not None
    assert fetched.name == "EU Analytics"
    assert fetched.cloud_type.value == "azure"
    assert [e.id for e in EstateManager().list_estates(db_session)] == [created.id]


def test_export_and_import_policies_come_back_separately(db_session, manager):
    created = manager.create_estate(db_session, _estate(
        export_policies=[SharingPolicy(name="Products", resource_type="data_product")],
        import_policies=[
            SharingPolicy(name="Domains", resource_type="data_domain"),
            SharingPolicy(name="Concepts", resource_type="concept"),
        ],
    ))

    assert [p.name for p in created.export_policies] == ["Products"]
    assert [p.name for p in created.import_policies] == ["Domains", "Concepts"]
    assert all(p.id for p in created.export_policies + created.import_policies)


def test_legacy_sharing_policies_and_business_glossary_are_accepted(db_session, manager):
    payload = {
        "name": "Legacy client",
        "description": "Sends the old shape",
        "workspace_url": "https://legacy.cloud.databricks.com",
        "cloud_type": "gcp",
        "metastore_name": "legacy",
        "sharing_policies": [
            {"name": "Glossary", "resource_type": "business_glossary", "rules": []},
        ],
    }
    created = manager.create_estate(db_session, Estate(**payload))

    assert [(p.name, p.resource_type.value) for p in created.export_policies] == [
        ("Glossary", "business_term"),
    ]
    assert created.import_policies == []
    assert "sharing_policies" not in created.model_dump()


def test_update_changes_fields_and_keeps_created_at(db_session, manager):
    created = manager.create_estate(db_session, _estate())

    updated = manager.update_estate(
        db_session, created.id, _estate(description="Moved", sync_schedule="0 6 * * *", is_enabled=False),
        user="admin@example.com",
    )

    assert updated.description == "Moved"
    assert updated.sync_schedule == "0 6 * * *"
    assert updated.is_enabled is False
    assert updated.created_at == created.created_at
    assert manager.get_estate(db_session, created.id).description == "Moved"


def test_update_and_delete_of_an_unknown_estate(db_session, manager):
    assert manager.update_estate(db_session, "missing", _estate()) is None
    assert manager.delete_estate(db_session, "missing") is False


def test_delete_removes_the_estate(db_session, manager):
    created = manager.create_estate(db_session, _estate())

    assert manager.delete_estate(db_session, created.id) is True
    assert manager.get_estate(db_session, created.id) is None
    assert manager.list_estates(db_session) == []


def test_a_second_estate_with_the_same_name_is_refused(db_session, manager):
    manager.create_estate(db_session, _estate())
    other = manager.create_estate(db_session, _estate(name="Other"))

    with pytest.raises(EstateNameConflictError) as exc:
        manager.create_estate(db_session, _estate())
    assert exc.value.code == "estate_name_conflict"
    assert exc.value.params == {"name": "EU Analytics"}

    with pytest.raises(EstateNameConflictError):
        manager.update_estate(db_session, other.id, _estate())


def test_a_name_taken_after_the_check_still_gets_the_coded_conflict_on_create(
    db_session, manager, monkeypatch
):
    # Two requests can both pass the pre-check; the second one then hits the
    # unique constraint and must still get the 409, not a 500.
    manager.create_estate(db_session, _estate())
    monkeypatch.setattr(manager, "_check_name_free", lambda *a, **k: None)

    with pytest.raises(EstateNameConflictError) as exc:
        manager.create_estate(db_session, _estate())
    assert exc.value.code == "estate_name_conflict"
    assert exc.value.params == {"name": "EU Analytics"}


def test_a_name_taken_after_the_check_still_gets_the_coded_conflict_on_rename(
    db_session, manager, monkeypatch
):
    manager.create_estate(db_session, _estate())
    other = manager.create_estate(db_session, _estate(name="Other"))
    monkeypatch.setattr(manager, "_check_name_free", lambda *a, **k: None)

    with pytest.raises(EstateNameConflictError):
        manager.update_estate(db_session, other.id, _estate())


def test_other_integrity_errors_are_not_reported_as_a_name_conflict():
    from sqlalchemy.exc import IntegrityError

    error = IntegrityError("INSERT ...", {}, Exception("NOT NULL constraint failed: estates.metastore_name"))
    assert EstateManager._is_name_conflict(error) is False
    assert EstateManager._is_name_conflict(
        IntegrityError("INSERT ...", {}, Exception('duplicate key value violates unique constraint "estates_name_key"'))
    ) is True


def test_sync_records_its_status(db_session, manager):
    created = manager.create_estate(db_session, _estate())
    disabled = manager.create_estate(db_session, _estate(name="Off", is_enabled=False))

    assert manager.sync_estate(db_session, created.id) is True
    synced = manager.get_estate(db_session, created.id)
    assert synced.last_sync_status.value == "success"
    assert synced.last_sync_time is not None

    assert manager.sync_estate(db_session, disabled.id) is False
    assert manager.sync_estate(db_session, "missing") is False


def test_the_route_dependency_returns_the_app_state_singleton():
    from types import SimpleNamespace

    from fastapi import HTTPException

    from src.common.manager_dependencies import get_estate_manager

    singleton = EstateManager()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(estate_manager=singleton)))
    assert get_estate_manager(request) is singleton
    assert get_estate_manager(request) is singleton

    with pytest.raises(HTTPException) as exc:
        get_estate_manager(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())))
    assert exc.value.status_code == 503
