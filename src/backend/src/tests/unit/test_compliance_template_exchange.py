"""Compliance template values in ODCS and ODPS export and import.

ODCS carries a table's or view's values on the schema object whose physicalName
is the asset; ODPS carries a data product's values on the product. Both use one
``ontosComplianceValues`` custom property (reference id -> value). The managers
run on the test database; the route permission check is mocked.
"""
import asyncio
import copy
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.controller import compliance_template_exchange as cte
from src.controller.compliance_templates_manager import compliance_templates_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.compliance_templates import ComplianceTemplateValueDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.compliance_templates import (
    ComplianceFieldCreate,
    ComplianceTemplateCreate,
    ComplianceValueWrite,
)
from src.repositories.data_contracts_repository import data_contract_repo

PROP = cte.COMPLIANCE_VALUES_PROPERTY


def _drop_templates(db: Session, entity_type: str) -> None:
    # SQLite ignores the partial (active-only) unique index: drop earlier templates.
    for old in compliance_templates_manager.list_templates(db, entity_type=entity_type):
        compliance_templates_manager.delete_template(db, template_id=old.id)


def _template(db: Session, entity_type: str):
    _drop_templates(db, entity_type)
    created = compliance_templates_manager.create_template(
        db,
        payload=ComplianceTemplateCreate(
            name=f"Documentation {entity_type}",
            entity_type=entity_type,
            fields=[
                ComplianceFieldCreate(
                    key="limitacoes", label="Limitações", reference_id="limitacoes",
                ),
                ComplianceFieldCreate(
                    key="refresh_hours", label="Refresh (hours)", reference_id="refresh-hours",
                    value_type="numeric", field_order=1,
                ),
            ],
        ),
        user_email="admin@example.com",
    )
    return compliance_templates_manager.set_active(db, template_id=created.id, active=True)


def _field_id(template, reference_id: str):
    return next(f.id for f in template.fields if f.reference_id == reference_id)


def _fill(db: Session, template, entity_type: str, entity_id, values: dict) -> None:
    compliance_templates_manager.replace_values(
        db, entity_type=entity_type, entity_id=str(entity_id),
        writes=[
            ComplianceValueWrite(field_id=_field_id(template, ref), value=value)
            for ref, value in values.items()
        ],
        user_email="owner@example.com",
    )


def _stored(db: Session, template, entity_type: str, entity_id) -> dict:
    db.expire_all()
    rows = db.query(ComplianceTemplateValueDb).filter_by(
        entity_type=entity_type, entity_id=str(entity_id)
    ).all()
    ref_by_id = {f.id: f.reference_id for f in template.fields}
    return {ref_by_id[r.field_id]: r.value for r in rows}


def _asset(db: Session, location: str, type_name: str = "Table", name: str | None = None):
    asset_type = db.query(AssetTypeDb).filter(AssetTypeDb.name == type_name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(id=uuid.uuid4(), name=type_name)
        db.add(asset_type)
        db.flush()
    asset = AssetDb(
        id=uuid.uuid4(), name=name or f"orders_{uuid.uuid4().hex[:6]}",
        asset_type_id=asset_type.id, location=location, status="active",
    )
    db.add(asset)
    db.flush()
    return asset


def _entry(props) -> dict | None:
    return next((p["value"] for p in props or [] if p.get("property") == PROP), None)


def _contract_doc(physical_name: str, values: dict | None = None) -> dict:
    schema = {
        "name": "orders", "physicalName": physical_name, "logicalType": "object",
        "properties": [{"name": "id", "logicalType": "integer"}],
    }
    if values is not None:
        schema["customProperties"] = [
            {"property": "owner", "value": "sales"},
            {"property": PROP, "value": values},
        ]
    return {
        "kind": "DataContract", "apiVersion": "v3.0.2", "id": str(uuid.uuid4()),
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0", "status": "draft",
        "schema": [schema],
    }


@pytest.fixture
def contracts(tmp_path: Path):
    return DataContractsManager(data_dir=tmp_path)


def _import_contract(contracts, db: Session, doc: dict, values_user: str | None):
    with patch.object(DataContractsManager, "_update_search_index"):
        return contracts.create_from_upload(
            db, copy.deepcopy(doc), current_user="importer",
            compliance_values_user=values_user,
        )


def _export_contract(contracts, db: Session, contract_id: str) -> dict:
    db.expire_all()
    return contracts.build_odcs_from_db(data_contract_repo.get_with_all(db, id=contract_id), db)


class TestOdcs:

    def test_export_puts_the_table_values_on_its_schema_object(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders")
        _fill(db_session, template, "asset", table.id, {
            "limitacoes": "Atualização diária", "refresh-hours": 24,
        })
        created = _import_contract(contracts, db_session, _contract_doc("MAIN.sales.orders"), None)

        exported = _export_contract(contracts, db_session, created.id)
        assert _entry(exported["schema"][0].get("customProperties")) == {
            "limitacoes": "Atualização diária", "refresh-hours": 24,
        }

    def test_import_writes_the_values_back_to_the_table(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_in")
        doc = _contract_doc(
            "main.sales.orders_in",
            {"limitacoes": "Sem histórico", "refresh-hours": "6", "unknown": "x"},
        )
        created = _import_contract(contracts, db_session, doc, "importer@example.com")

        assert _stored(db_session, template, "asset", table.id) == {
            "limitacoes": "Sem histórico", "refresh-hours": 6,
        }
        # The values live on the table, not as a stored schema custom property.
        contract = db_session.get(DataContractDb, created.id)
        assert PROP not in [p.property for p in contract.schema_objects[0].custom_properties]

        exported = _export_contract(contracts, db_session, created.id)
        assert _entry(exported["schema"][0]["customProperties"]) == {
            "limitacoes": "Sem histórico", "refresh-hours": 6,
        }

    def test_import_merges_with_values_already_on_the_table(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_merge")
        _fill(db_session, template, "asset", table.id, {"refresh-hours": 1})
        doc = _contract_doc("main.sales.orders_merge", {"limitacoes": "Nova"})
        _import_contract(contracts, db_session, doc, "importer@example.com")
        assert _stored(db_session, template, "asset", table.id) == {
            "limitacoes": "Nova", "refresh-hours": 1,
        }

    def test_unmatched_schema_object_keeps_the_entry(self, db_session):
        _template(db_session, "asset")
        matched = _asset(db_session, "main.sales.orders_known")
        schema = _contract_doc("main.sales.not_registered", {"limitacoes": "kept"})["schema"]
        schema += _contract_doc("main.sales.orders_known", {"limitacoes": "moved"})["schema"]

        pending = cte.take_schema_entries(db_session, schema)

        assert [(asset.id, values) for asset, values in pending] == [
            (matched.id, {"limitacoes": "moved"}),
        ]
        # The unmatched object keeps the entry as an ordinary custom property.
        assert cte.read_entry(schema[0]["customProperties"]) == {"limitacoes": "kept"}
        assert schema[1]["customProperties"] == [{"property": "owner", "value": "sales"}]

    def test_without_the_right_to_write_values_nothing_is_written(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_ro")
        doc = _contract_doc("main.sales.orders_ro", {"limitacoes": "x"})
        with patch.object(cte, "take_schema_entries") as take:
            _import_contract(contracts, db_session, doc, None)
        take.assert_not_called()
        assert _stored(db_session, template, "asset", table.id) == {}

    def test_without_an_active_template_nothing_is_taken(self, db_session):
        _drop_templates(db_session, "asset")
        _asset(db_session, "main.sales.orders_none")
        schema = _contract_doc("main.sales.orders_none", {"limitacoes": "kept"})["schema"]
        assert cte.take_schema_entries(db_session, schema) == []
        assert cte.read_entry(schema[0]["customProperties"]) == {"limitacoes": "kept"}

    def test_export_replaces_a_stored_entry_with_the_live_values(self):
        schema_dict = {"customProperties": [
            {"property": "owner", "value": "sales"},
            {"property": PROP, "value": {"limitacoes": "old"}},
        ]}
        cte.apply_to_document(schema_dict, {"limitacoes": "new"})
        assert schema_dict["customProperties"] == [
            {"property": "owner", "value": "sales"},
            {"property": PROP, "value": {"limitacoes": "new"}},
        ]


class TestFindSchemaAsset:

    def test_matches_the_location_then_the_name(self, db_session):
        by_location = _asset(db_session, "cat.sch.orders_loc")
        by_name = _asset(db_session, None, name="orders_by_name")
        assert cte.find_schema_asset(db_session, physical_name="CAT.SCH.ORDERS_LOC") is by_location
        assert cte.find_schema_asset(db_session, physical_name="orders_by_name") is by_name

    def test_ambiguous_or_other_asset_types_do_not_match(self, db_session):
        _asset(db_session, "cat.sch.twice")
        _asset(db_session, "cat.sch.twice", type_name="View")
        _asset(db_session, "cat.sch.dash", type_name="Dashboard")
        assert cte.find_schema_asset(db_session, physical_name="cat.sch.twice") is None
        assert cte.find_schema_asset(db_session, physical_name="cat.sch.dash") is None
        assert cte.find_schema_asset(db_session, physical_name="  ") is None

    def test_the_auto_link_wins_over_the_name(self, db_session):
        _asset(db_session, "cat.sch.linked")
        linked = _asset(db_session, "elsewhere.orders")
        db_session.add(EntityRelationshipDb(
            source_type="Table", source_id=str(linked.id), target_type="DataContract",
            target_id="c-1", relationship_type="implementsContract",
            properties={"schema_object_id": "s-1"},
        ))
        db_session.flush()
        found = cte.find_schema_asset(
            db_session, physical_name="cat.sch.linked", contract_id="c-1", schema_object_id="s-1",
        )
        assert found is linked


def _product_doc(values: dict | None) -> dict:
    doc = {
        "apiVersion": "v1.0.0", "kind": "DataProduct", "id": str(uuid.uuid4()),
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0", "status": "draft",
        "customProperties": [{"property": "tier", "value": "gold"}],
    }
    if values is not None:
        doc["customProperties"].append({"property": PROP, "value": values})
    return doc


def _upload(db: Session, doc: dict, values_user: str | None):
    manager = DataProductsManager(db=db)
    created, errors = manager.upload_products_batch(
        yaml.safe_dump(doc).encode(), "product.yaml", compliance_values_user=values_user,
    )
    assert errors == []
    return manager, created[0].id


def _export_product(manager: DataProductsManager, db: Session, product_id: str) -> dict:
    """``build_odps_export`` on a product read from the database.

    On this base the export reads snake_case attributes the API model doesn't
    have (``product.api_version``; fixed on development), so the product is
    handed over in that shape.
    """
    db.expire_all()
    row = db.get(DataProductDb, product_id)
    product = SimpleNamespace(
        kind="DataProduct", api_version="v1.0.0", id=row.id, status=row.status,
        name=row.name, version=row.version, tenant=None, description=None,
        input_ports=[], output_ports=[], support_channels=[], team=None,
        custom_properties=[
            SimpleNamespace(property=p.property, value=p.value) for p in row.custom_properties
        ],
        authoritative_definitions=[],
    )
    with patch.object(manager, "get_product", return_value=product), \
            patch.object(manager, "get_product_hierarchy", return_value={}):
        return manager.build_odps_export(product_id, db=db)


class TestOdps:

    def test_import_then_export_round_trip(self, db_session):
        template = _template(db_session, "data_product")
        manager, product_id = _upload(
            db_session, _product_doc({"limitacoes": "Só PJ", "refresh-hours": 12}),
            "importer@example.com",
        )
        assert _stored(db_session, template, "data_product", product_id) == {
            "limitacoes": "Só PJ", "refresh-hours": 12,
        }
        product = db_session.get(DataProductDb, product_id)
        assert [p.property for p in product.custom_properties] == ["tier"]

        exported = _export_product(manager, db_session, product_id)
        assert _entry(exported["customProperties"]) == {"limitacoes": "Só PJ", "refresh-hours": 12}
        assert {"property": "tier", "value": "gold"} in exported["customProperties"]

    def test_export_reflects_values_filled_in_the_app(self, db_session):
        template = _template(db_session, "data_product")
        manager, product_id = _upload(db_session, _product_doc(None), "importer@example.com")
        assert _entry(_export_product(manager, db_session, product_id)["customProperties"]) is None

        _fill(db_session, template, "data_product", product_id, {"limitacoes": "Revisado"})
        exported = _export_product(manager, db_session, product_id)
        assert _entry(exported["customProperties"]) == {"limitacoes": "Revisado"}

    def test_without_the_right_to_write_values_nothing_is_written(self, db_session):
        template = _template(db_session, "data_product")
        _, product_id = _upload(db_session, _product_doc({"limitacoes": "x"}), None)
        assert _stored(db_session, template, "data_product", product_id) == {}
        product = db_session.get(DataProductDb, product_id)
        assert PROP in [p.property for p in product.custom_properties]

    def test_without_an_active_template_the_entry_stays_a_custom_property(self, db_session):
        _drop_templates(db_session, "data_product")
        manager, product_id = _upload(
            db_session, _product_doc({"limitacoes": "kept"}), "importer@example.com",
        )
        exported = _export_product(manager, db_session, product_id)
        assert PROP in [p["property"] for p in exported["customProperties"]]


class TestDocumentHelpers:

    def test_apply_to_document(self):
        doc = {"customProperties": [{"property": PROP, "value": {"a": 1}}, {"property": "x"}]}
        cte.apply_to_document(doc, None)
        assert _entry(doc["customProperties"]) == {"a": 1}
        cte.apply_to_document(doc, {"b": 2})
        assert doc["customProperties"] == [
            {"property": "x"}, {"property": PROP, "value": {"b": 2}},
        ]
        cte.apply_to_document(doc, {})
        assert doc["customProperties"] == [{"property": "x"}]
        only = {"customProperties": [{"property": PROP, "value": {"a": 1}}]}
        cte.apply_to_document(only, {})
        assert "customProperties" not in only

    def test_read_and_strip_the_entry(self):
        props = [{"property": "x", "value": 1}, {"property": PROP, "value": {"a": 1}}]
        assert cte.read_entry(props) == {"a": 1}
        assert cte.without_entry(props) == [{"property": "x", "value": 1}]
        assert cte.read_entry({PROP: {"a": 1}, "x": 1}) == {"a": 1}
        assert cte.without_entry({PROP: {"a": 1}, "x": 1}) == {"x": 1}
        assert cte.read_entry([{"property": PROP, "value": "not a mapping"}]) is None
        assert cte.read_entry(None) is None

    def test_imported_values_that_do_not_fit_are_skipped(self, db_session):
        template = _template(db_session, "data_product")
        written = cte.apply_imported_values(
            db_session, entity_type="data_product", entity_id="p-1",
            values={"refresh-hours": "soon", "limitacoes": "ok", "other": 1},
            user_email="u@example.com",
        )
        assert written == ["limitacoes"]
        assert _stored(db_session, template, "data_product", "p-1") == {"limitacoes": "ok"}


class TestCanImportValues:

    @pytest.mark.parametrize("entity_type,features", [
        ("data_product", ["compliance-template-values"]),
        ("asset", ["compliance-template-values", "assets"]),
    ])
    def test_needs_the_values_feature_and_for_assets_asset_edit(self, entity_type, features):
        checked = []

        def _checker(feature_id, level):
            async def _check(request, user, auth_manager):
                checked.append((feature_id, level.value))
            return _check

        with patch("src.common.authorization.PermissionChecker", side_effect=_checker):
            allowed = asyncio.run(
                cte.can_import_values(None, None, None, entity_type=entity_type)
            )
        assert allowed is True
        assert [f for f, _ in checked] == features

    def test_forbidden_means_no_and_other_errors_propagate(self):
        def _deny(status_code):
            def _checker(feature_id, level):
                async def _check(request, user, auth_manager):
                    raise HTTPException(status_code=status_code)
                return _check
            return _checker

        with patch("src.common.authorization.PermissionChecker", side_effect=_deny(403)):
            assert asyncio.run(
                cte.can_import_values(None, None, None, entity_type="asset")
            ) is False
        with patch("src.common.authorization.PermissionChecker", side_effect=_deny(500)):
            with pytest.raises(HTTPException):
                asyncio.run(cte.can_import_values(None, None, None, entity_type="asset"))


class TestContractImportRoute:

    @pytest.mark.parametrize("allowed,expected", [(True, "u@example.com"), (False, None)])
    def test_values_user_follows_the_asset_rights(self, allowed, expected):
        from src.routes import data_contracts_routes as routes

        user = SimpleNamespace(email="u@example.com", username="u")

        async def _can(request, user_, auth_manager, *, entity_type):
            assert entity_type == "asset"
            return allowed

        with patch.object(cte, "can_import_values", side_effect=_can):
            assert asyncio.run(routes._compliance_values_user(None, user, None)) == expected
