"""The product type lives on data_products.product_type_id and travels as the
``productType`` custom property (#1209): create, update, read, ODPS export and
import, new versions and clones all go through the FK."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager, UnknownDataProductTypeError
from src.db_models.data_products import CustomPropertyDb, DataProductDb
from src.models.data_products import NewVersionRequest
from src.repositories.data_product_types_repository import (
    data_product_types_repo,
    normalize_type_key,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "odps-json-schema-v1.0.0.json"


@pytest.fixture
def manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )


@pytest.fixture
def seeded(db_session):
    data_product_types_repo.seed_defaults(db_session)
    db_session.flush()


def _product(name="Typed Product", product_type=None, status="draft", **extra):
    data = {
        "name": name,
        "version": "1.0.0",
        "status": status,
        "description": {"purpose": "Product type tests"},
        "outputPorts": [{"name": "out", "version": "1.0.0", "contractId": "c-out"}],
        **extra,
    }
    if product_type is not None:
        data["customProperties"] = [
            {"property": "owner", "value": "team-a"},
            {"property": "productType", "value": product_type},
        ]
    return data


def _type_key(db_session, product_id):
    db_session.expire_all()
    product = db_session.get(DataProductDb, product_id)
    return product.product_type.key if product.product_type else None


def _product_type_props(api_or_dict):
    props = (
        api_or_dict.get("customProperties")
        if isinstance(api_or_dict, dict)
        else [cp.model_dump() for cp in api_or_dict.customProperties or []]
    )
    return [cp["value"] for cp in props or [] if cp["property"] == "productType"]


def _stored_product_type_rows(db_session, product_id):
    return (
        db_session.query(CustomPropertyDb)
        .filter(CustomPropertyDb.product_id == product_id, CustomPropertyDb.property == "productType")
        .count()
    )


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("sourceAligned", "source-aligned"),
        ('"aggregate"', "aggregate"),
        ("SOURCE_ALIGNED", "source-aligned"),
        (" Consumer Aligned ", "consumer-aligned"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_type_key(raw, key):
    assert normalize_type_key(raw) == key


# --- create ---


def test_create_moves_custom_property_onto_fk(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="sourceAligned"), db=db_session)

    assert _type_key(db_session, created.id) == "source-aligned"
    assert _stored_product_type_rows(db_session, created.id) == 0
    # The read model carries the key, other custom properties are kept
    assert _product_type_props(created) == ["source-aligned"]
    assert {cp.property for cp in created.customProperties} == {"owner", "productType"}


def test_create_accepts_root_product_type(manager, db_session, seeded):
    created = manager.create_product(_product(productType="consumerAligned"), db=db_session)

    assert _type_key(db_session, created.id) == "consumer-aligned"


def test_create_without_type_leaves_it_empty(manager, db_session, seeded):
    created = manager.create_product(_product(), db=db_session)

    assert _type_key(db_session, created.id) is None
    assert _product_type_props(created) == []


def test_create_with_unknown_type_is_rejected(manager, db_session, seeded):
    """A plain create doesn't add reference data (settings-data-product-types does)."""
    with pytest.raises(UnknownDataProductTypeError) as err:
        manager.create_product(_product(product_type="Typo Tyep"), db=db_session)

    assert err.value.code == "unknown_data_product_type"
    assert err.value.params == {"key": "Typo Tyep"}
    assert data_product_types_repo.get_by_key(db_session, "typo-tyep") is None


def test_create_with_deactivated_type_is_rejected(manager, db_session, seeded):
    data_product_types_repo.get_by_key(db_session, "sink").is_active = False
    db_session.flush()

    with pytest.raises(UnknownDataProductTypeError):
        manager.create_product(_product(product_type="sink"), db=db_session)


def test_import_with_unknown_type_creates_imported_type(manager, db_session, seeded):
    created = manager.create_product(
        _product(product_type="Golden Record"), db=db_session, create_missing_type=True,
    )

    imported = data_product_types_repo.get_by_key(db_session, "golden-record")
    assert imported.is_imported and imported.is_active and not imported.is_default
    assert imported.label == "Golden Record"
    assert imported.sort_order == 6
    assert _type_key(db_session, created.id) == "golden-record"


# --- update ---


def test_update_changes_type(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="aggregate"), db=db_session)

    updated = manager.update_product(
        created.id,
        {"customProperties": [{"property": "productType", "value": "sink"}]},
        db=db_session,
    )

    assert _type_key(db_session, created.id) == "sink"
    assert _product_type_props(updated) == ["sink"]
    assert _stored_product_type_rows(db_session, created.id) == 0


@pytest.mark.parametrize("value", ["Typo Tyep", "sink"])
def test_update_to_unknown_or_deactivated_type_is_rejected(manager, db_session, seeded, value):
    created = manager.create_product(_product(product_type="aggregate"), db=db_session)
    data_product_types_repo.get_by_key(db_session, "sink").is_active = False
    db_session.flush()

    # update_product rolls the session back on the error, so nothing is written
    with pytest.raises(UnknownDataProductTypeError):
        manager.update_product(
            created.id,
            {"customProperties": [{"property": "productType", "value": value}]},
            db=db_session,
        )


def test_update_keeps_the_current_type_after_it_is_deactivated(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="sink"), db=db_session)
    data_product_types_repo.get_by_key(db_session, "sink").is_active = False
    db_session.flush()

    manager.update_product(
        created.id,
        {"customProperties": [{"property": "productType", "value": "sink"}]},
        db=db_session,
    )

    assert _type_key(db_session, created.id) == "sink"


def test_update_custom_properties_without_type_clears_it(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="aggregate"), db=db_session)

    manager.update_product(
        created.id, {"customProperties": [{"property": "owner", "value": "team-b"}]}, db=db_session,
    )

    assert _type_key(db_session, created.id) is None


def test_update_without_custom_properties_keeps_type(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="aggregate"), db=db_session)

    manager.update_product(created.id, {"name": "Renamed"}, db=db_session)

    assert _type_key(db_session, created.id) == "aggregate"


# --- reads ---


def test_list_and_get_carry_the_type(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="source"), db=db_session)

    assert _product_type_props(manager.get_product(created.id)) == ["source"]
    listed = [p for p in manager.list_products(is_admin=True) if p.id == created.id]
    assert _product_type_props(listed[0]) == ["source"]


def test_renaming_a_type_keeps_the_exported_key(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="aggregate"), db=db_session)
    data_product_types_repo.get_by_key(db_session, "aggregate").label = "Composite"
    db_session.flush()

    export = manager.build_odps_export(created.id, db=db_session)

    assert _product_type_props(export) == ["aggregate"]


# --- ODPS export / import ---


def _schema_errors(document):
    schema = json.loads(SCHEMA_PATH.read_text())
    return [e.message for e in jsonschema.Draft7Validator(schema).iter_errors(document)]


def test_export_writes_type_as_custom_property(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="consumer-aligned"), db=db_session)

    export = manager.build_odps_export(created.id, db=db_session)

    assert _product_type_props(export) == ["consumer-aligned"]
    assert "productType" not in export
    assert _schema_errors(export) == []


def test_export_without_type_has_no_product_type_property(manager, db_session, seeded):
    created = manager.create_product(_product(), db=db_session)

    assert _product_type_props(manager.build_odps_export(created.id, db=db_session)) == []


def test_odps_round_trip_keeps_the_type(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="aggregate"), db=db_session)
    export = manager.build_odps_export(created.id, db=db_session)

    reimported = manager.create_product(dict(export, name="Re-imported"), db=db_session, adopt_ids=False)

    assert reimported.id != created.id
    assert _type_key(db_session, reimported.id) == "aggregate"
    assert _product_type_props(manager.build_odps_export(reimported.id, db=db_session)) == [
        "aggregate"
    ]


def test_odps_import_of_unknown_type_into_another_install(manager, db_session, seeded):
    """A type made on one install arrives as an imported type on another."""
    document = _product(name="Foreign Product", product_type="golden-record")

    created = manager.create_product(document, db=db_session, create_missing_type=True)

    assert data_product_types_repo.get_by_key(db_session, "golden-record").is_imported
    assert _product_type_props(manager.build_odps_export(created.id, db=db_session)) == [
        "golden-record"
    ]


def test_batch_upload_of_unknown_type_creates_imported_type(manager, db_session, seeded):
    content = json.dumps([_product(name="Uploaded", product_type="Golden Record")]).encode()

    created, errors = manager.upload_products_batch(content, "products.json")

    assert errors == []
    assert data_product_types_repo.get_by_key(db_session, "golden-record").is_imported
    assert _type_key(db_session, created[0].id) == "golden-record"


# --- new version / clone ---


def test_new_version_keeps_the_type(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="sink"), db=db_session)

    new_version = manager.create_new_version(created.id, NewVersionRequest(new_version="2.0.0"))

    assert _type_key(db_session, new_version.id) == "sink"
    assert _product_type_props(new_version) == ["sink"]
    assert _stored_product_type_rows(db_session, new_version.id) == 0


def test_personal_draft_clone_keeps_the_type(manager, db_session, seeded):
    created = manager.create_product(_product(product_type="sink", status="active"), db=db_session)

    draft = manager.clone_product_for_editing(db_session, created.id, "editor@example.com")

    assert _type_key(db_session, draft.id) == "sink"
    assert _product_type_props(draft) == ["sink"]
