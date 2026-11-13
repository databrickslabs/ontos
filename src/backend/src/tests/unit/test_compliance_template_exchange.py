"""Compliance template values in ODCS and ODPS export and import.

ODCS carries a table's or view's values on the schema object that is the asset;
ODPS carries a data product's values on the product. Both use one
``ontosComplianceValues`` custom property (reference id -> value); what an
import can't write is kept apart in ``ontosComplianceValuesUnmatched``. The
managers run on the test database; the permission checks are given or mocked.
"""
import asyncio
import contextlib
import copy
import json
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
from src.db_models.data_products import DataProductDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.compliance_templates import (
    ComplianceFieldCreate,
    ComplianceTemplateCreate,
    ComplianceValueWrite,
)
from src.repositories.data_contracts_repository import data_contract_repo

PROP = cte.COMPLIANCE_VALUES_PROPERTY
UNMATCHED = cte.UNMATCHED_VALUES_PROPERTY
IMPORTER = "importer@example.com"
CAN_READ_ALL = cte.ValuesReadAccess(values=True, assets_rw=True)


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


def _asset(db: Session, location, type_name: str = "Table", name: str | None = None):
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


def _entry(props, name: str = PROP) -> dict | None:
    return cte.read_entry(props, name)


def _importer(values: bool = True, assets: bool = True) -> cte.ComplianceImport:
    return cte.ComplianceImport(
        user_email=IMPORTER, can_write_values=values, can_write_assets=values and assets,
    )


def _schema(physical_name, values: dict | None = None, unmatched: dict | None = None) -> dict:
    schema = {
        "name": "orders", "physicalName": physical_name, "logicalType": "object",
        "properties": [{"name": "id", "logicalType": "integer"}],
        "customProperties": [{"property": "owner", "value": "sales"}],
    }
    if values is not None:
        schema["customProperties"].append({"property": PROP, "value": values})
    if unmatched is not None:
        schema["customProperties"].append({"property": UNMATCHED, "value": unmatched})
    return schema


def _contract_doc(physical_name, values: dict | None = None) -> dict:
    return {
        "kind": "DataContract", "apiVersion": "v3.0.2", "id": str(uuid.uuid4()),
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0", "status": "draft",
        "schema": [_schema(physical_name, values)],
    }


@pytest.fixture(autouse=True)
def _commit_is_flush(db_session: Session, monkeypatch):
    """Keep the managers' commits in the test transaction, so they roll back with it."""
    monkeypatch.setattr(db_session, "commit", db_session.flush)


@pytest.fixture
def contracts(tmp_path: Path):
    return DataContractsManager(data_dir=tmp_path)


def _import_contract(contracts, db: Session, doc: dict, imp):
    with patch.object(DataContractsManager, "_update_search_index"):
        return contracts.create_from_upload(
            db, copy.deepcopy(doc), current_user="importer", compliance_import=imp,
        )


def _export_contract(contracts, db: Session, contract_id: str, access=CAN_READ_ALL) -> dict:
    """``build_odcs_from_db``; its own semantic-links session reuses the test session."""
    @contextlib.contextmanager
    def _same_session():
        yield db

    db.expire_all()
    with patch("src.common.database.get_db_session", _same_session):
        return contracts.build_odcs_from_db(
            data_contract_repo.get_with_all(db, id=contract_id), db, compliance_read=access,
        )


class TestOdcsExport:

    @pytest.fixture
    def documented(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders")
        _fill(db_session, template, "asset", table.id, {
            "limitacoes": "Atualização diária", "refresh-hours": 24,
        })
        created = _import_contract(
            contracts, db_session, _contract_doc("`MAIN`.sales.orders "), None,
        )
        return table, created.id

    def test_the_table_values_go_on_its_schema_object(self, db_session, contracts, documented):
        _, contract_id = documented
        exported = _export_contract(contracts, db_session, contract_id)
        assert _entry(exported["schema"][0].get("customProperties")) == {
            "limitacoes": "Atualização diária", "refresh-hours": 24,
        }

    @pytest.mark.parametrize("access", [
        None,
        cte.ValuesReadAccess(),
        cte.ValuesReadAccess(values=True, assets_rw=False),
        cte.ValuesReadAccess(values=True, asset_accessible=lambda asset: False),
    ])
    def test_omitted_without_the_read_rights(self, db_session, contracts, documented, access):
        _, contract_id = documented
        exported = _export_contract(contracts, db_session, contract_id, access=access)
        assert _entry(exported["schema"][0].get("customProperties")) is None

    def test_a_reader_of_a_linked_product_sees_them(self, db_session, contracts, documented):
        table, contract_id = documented
        seen = []

        def _accessible(asset):
            seen.append(asset.id)
            return True

        access = cte.ValuesReadAccess(values=True, asset_accessible=_accessible)
        exported = _export_contract(contracts, db_session, contract_id, access=access)
        assert _entry(exported["schema"][0].get("customProperties")) is not None
        assert seen == [table.id]

    def test_a_bare_table_name_matches_no_asset(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, None, name="orders_by_name")
        _fill(db_session, template, "asset", table.id, {"limitacoes": "x"})
        created = _import_contract(contracts, db_session, _contract_doc("orders_by_name"), None)
        exported = _export_contract(contracts, db_session, created.id)
        assert _entry(exported["schema"][0].get("customProperties")) is None


class TestOdcsImport:

    def test_writes_the_values_to_the_table_and_audits_them(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_in")
        doc = _contract_doc(
            "main.sales.orders_in",
            {"limitacoes": "Sem histórico", "refresh-hours": "6", "unknown": "x"},
        )
        imp = _importer()
        created = _import_contract(contracts, db_session, doc, imp)

        assert _stored(db_session, template, "asset", table.id) == {
            "limitacoes": "Sem histórico", "refresh-hours": 6,
        }
        assert imp.written == [{
            "entityType": "asset", "entityId": str(table.id),
            "referenceIds": ["limitacoes", "refresh-hours"],
        }]
        exported = _export_contract(contracts, db_session, created.id)
        assert _entry(exported["schema"][0].get("customProperties")) == {
            "limitacoes": "Sem histórico", "refresh-hours": 6,
        }

    def test_merges_overwrites_and_never_clears(self, db_session):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_over")
        _fill(db_session, template, "asset", table.id, {"limitacoes": "old", "refresh-hours": 1})
        schema = [_schema("main.sales.orders_over", {"limitacoes": "new", "refresh-hours": None})]
        cte.import_schema_entries(db_session, schema, _importer())
        rows = db_session.query(ComplianceTemplateValueDb).filter_by(
            entity_type="asset", entity_id=str(table.id),
        ).all()
        by_field = {r.field_id: (r.value, r.filled_by) for r in rows}
        assert by_field == {
            _field_id(template, "limitacoes"): ("new", IMPORTER),
            _field_id(template, "refresh-hours"): (1, "owner@example.com"),
        }

    def test_matches_by_location_only(self, db_session):
        template = _template(db_session, "asset")
        named = _asset(db_session, None, name="orders")
        schema = [_schema("orders", {"limitacoes": "x"})]
        cte.import_schema_entries(db_session, schema, _importer())
        assert _stored(db_session, template, "asset", named.id) == {}
        assert _entry(schema[0]["customProperties"], UNMATCHED) == {"limitacoes": "x"}

    def test_unwritten_values_are_kept_apart(self, db_session):
        _template(db_session, "asset")
        _asset(db_session, "main.sales.orders_rest")
        schema = [
            _schema(
                "main.sales.orders_rest",
                {"limitacoes": "ok", "refresh-hours": "soon", "unknown": 1},
                unmatched={"older": "kept"},
            ),
            _schema("main.sales.not_registered", {"limitacoes": "no table"}),
        ]
        cte.import_schema_entries(db_session, schema, _importer())
        first, second = (s["customProperties"] for s in schema)
        assert _entry(first) is None
        assert _entry(first, UNMATCHED) == {"older": "kept", "refresh-hours": "soon", "unknown": 1}
        assert _entry(second, UNMATCHED) == {"limitacoes": "no table"}
        assert first[0] == {"property": "owner", "value": "sales"}

    def test_a_reimported_unmatched_entry_is_never_written(self, db_session):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_again")
        schema = [_schema("main.sales.orders_again", unmatched={"limitacoes": "leftover"})]
        cte.import_schema_entries(db_session, schema, _importer())
        assert _stored(db_session, template, "asset", table.id) == {}
        assert _entry(schema[0]["customProperties"], UNMATCHED) == {"limitacoes": "leftover"}

    def test_values_rw_without_asset_edit_keeps_them_unwritten(self, db_session):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_ro")
        schema = [_schema("main.sales.orders_ro", {"limitacoes": "x"})]
        cte.import_schema_entries(db_session, schema, _importer(assets=False))
        assert _stored(db_session, template, "asset", table.id) == {}
        assert _entry(schema[0]["customProperties"], UNMATCHED) == {"limitacoes": "x"}

    def test_without_values_rw_everything_is_dropped(self, db_session, contracts):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_none")
        schema = [_schema("main.sales.orders_none", {"limitacoes": "x"}, unmatched={"a": 1})]
        cte.import_schema_entries(db_session, schema, _importer(values=False))
        assert _stored(db_session, template, "asset", table.id) == {}
        assert schema[0]["customProperties"] == [{"property": "owner", "value": "sales"}]

    def test_a_failed_write_keeps_the_values_unwritten(self, db_session):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_fail")
        schema = [_schema("main.sales.orders_fail", {"limitacoes": "x"})]
        imp = _importer()
        with patch.object(cte, "apply_imported_values", side_effect=RuntimeError("boom")):
            cte.import_schema_entries(db_session, schema, imp)
        assert _stored(db_session, template, "asset", table.id) == {}
        assert imp.written == []
        assert _entry(schema[0]["customProperties"], UNMATCHED) == {"limitacoes": "x"}

    def test_an_oversized_entry_is_ignored(self, db_session):
        template = _template(db_session, "asset")
        table = _asset(db_session, "main.sales.orders_big")
        big = {f"k{i}": i for i in range(cte.MAX_ENTRY_KEYS + 1)}
        big["limitacoes"] = "x"
        schema = [_schema("main.sales.orders_big", big)]
        cte.import_schema_entries(db_session, schema, _importer())
        assert _stored(db_session, template, "asset", table.id) == {}
        assert schema[0]["customProperties"] == [{"property": "owner", "value": "sales"}]


class TestFindSchemaAsset:

    def test_matches_the_normalized_location(self, db_session):
        asset = _asset(db_session, " `Cat`.`Sch`.Orders_Loc ")
        assert cte.find_schema_asset(db_session, physical_name="cat.sch.orders_loc") is asset
        assert cte.find_schema_asset(db_session, physical_name="`CAT`.sch.`ORDERS_LOC`") is asset

    def test_name_ambiguous_or_other_asset_types_do_not_match(self, db_session):
        _asset(db_session, None, name="orders_by_name")
        _asset(db_session, "cat.sch.twice")
        _asset(db_session, "cat.sch.twice", type_name="View")
        _asset(db_session, "cat.sch.dash", type_name="Dashboard")
        for name in ("orders_by_name", "cat.sch.twice", "cat.sch.dash", "  ", None):
            assert cte.find_schema_asset(db_session, physical_name=name) is None

    def test_the_auto_link_wins_over_the_location(self, db_session):
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


def _product_doc(values: dict | None, unmatched: dict | None = None) -> dict:
    doc = {
        "apiVersion": "v1.0.0", "kind": "DataProduct", "id": str(uuid.uuid4()),
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0", "status": "draft",
        "customProperties": [{"property": "tier", "value": "gold"}],
    }
    if values is not None:
        doc["customProperties"].append({"property": PROP, "value": values})
    if unmatched is not None:
        doc["customProperties"].append({"property": UNMATCHED, "value": unmatched})
    return doc


def _upload(db: Session, doc: dict, imp):
    manager = DataProductsManager(db=db)
    created, errors = manager.upload_products_batch(
        yaml.safe_dump(doc).encode(), "product.yaml", compliance_import=imp,
    )
    assert errors == []
    return manager, created[0].id


def _export_product(
    manager: DataProductsManager, db: Session, product_id: str, access=CAN_READ_ALL
) -> dict:
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
        return manager.build_odps_export(product_id, db=db, compliance_read=access)


def _product_props(db: Session, product_id: str) -> dict:
    db.expire_all()
    return {p.property: p.value for p in db.get(DataProductDb, product_id).custom_properties}


class TestOdps:

    def test_import_then_export_round_trip(self, db_session):
        template = _template(db_session, "data_product")
        imp = _importer()
        manager, product_id = _upload(
            db_session, _product_doc({"limitacoes": "Só PJ", "refresh-hours": 12}), imp,
        )
        assert _stored(db_session, template, "data_product", product_id) == {
            "limitacoes": "Só PJ", "refresh-hours": 12,
        }
        assert imp.written == [{
            "entityType": "data_product", "entityId": str(product_id),
            "referenceIds": ["limitacoes", "refresh-hours"],
        }]
        assert list(_product_props(db_session, product_id)) == ["tier"]

        exported = _export_product(manager, db_session, product_id)
        assert _entry(exported["customProperties"]) == {"limitacoes": "Só PJ", "refresh-hours": 12}
        assert {"property": "tier", "value": "gold"} in exported["customProperties"]

    @pytest.mark.parametrize("access", [None, cte.ValuesReadAccess()])
    def test_export_omits_them_without_the_values_read_right(self, db_session, access):
        _template(db_session, "data_product")
        manager, product_id = _upload(
            db_session, _product_doc({"limitacoes": "x", "unknown": 1}), _importer(),
        )
        exported = _export_product(manager, db_session, product_id, access=access)
        assert _entry(exported["customProperties"]) is None
        assert _entry(exported["customProperties"], UNMATCHED) is None
        assert exported["customProperties"] == [{"property": "tier", "value": "gold"}]

    def test_export_reflects_values_filled_in_the_app(self, db_session):
        template = _template(db_session, "data_product")
        manager, product_id = _upload(db_session, _product_doc(None), _importer())
        assert _entry(_export_product(manager, db_session, product_id)["customProperties"]) is None

        _fill(db_session, template, "data_product", product_id, {"limitacoes": "Revisado"})
        exported = _export_product(manager, db_session, product_id)
        assert _entry(exported["customProperties"]) == {"limitacoes": "Revisado"}

    def test_unwritten_values_are_kept_apart_and_exported_apart(self, db_session):
        template = _template(db_session, "data_product")
        manager, product_id = _upload(
            db_session,
            _product_doc({"limitacoes": "ok", "refresh-hours": "soon", "unknown": 1, "n": None}),
            _importer(),
        )
        assert _stored(db_session, template, "data_product", product_id) == {"limitacoes": "ok"}
        props = _product_props(db_session, product_id)
        assert PROP not in props
        assert json.loads(props[UNMATCHED]) == {"refresh-hours": "soon", "unknown": 1}

        exported = _export_product(manager, db_session, product_id)
        assert _entry(exported["customProperties"]) == {"limitacoes": "ok"}
        assert _entry(exported["customProperties"], UNMATCHED) == {
            "refresh-hours": "soon", "unknown": 1,
        }

    def test_a_reimported_unmatched_entry_is_never_written(self, db_session):
        template = _template(db_session, "data_product")
        _, product_id = _upload(
            db_session, _product_doc(None, unmatched={"limitacoes": "leftover"}), _importer(),
        )
        assert _stored(db_session, template, "data_product", product_id) == {}
        assert json.loads(_product_props(db_session, product_id)[UNMATCHED]) == {
            "limitacoes": "leftover",
        }

    def test_a_failed_write_keeps_the_product_and_the_values_apart(self, db_session):
        template = _template(db_session, "data_product")
        imp = _importer()
        with patch.object(cte, "apply_imported_values", side_effect=RuntimeError("boom")):
            _, product_id = _upload(db_session, _product_doc({"limitacoes": "x"}), imp)
        assert _stored(db_session, template, "data_product", product_id) == {}
        assert imp.written == []
        assert json.loads(_product_props(db_session, product_id)[UNMATCHED]) == {"limitacoes": "x"}

    def test_a_failure_after_the_product_is_stored_keeps_the_product(self, db_session):
        template = _template(db_session, "data_product")
        with patch.object(cte, "import_product_values", side_effect=RuntimeError("boom")):
            _, product_id = _upload(db_session, _product_doc({"limitacoes": "x"}), _importer())
        assert list(_product_props(db_session, product_id)) == ["tier"]
        assert _stored(db_session, template, "data_product", product_id) == {}

    def test_without_values_rw_nothing_is_written_or_kept(self, db_session):
        template = _template(db_session, "data_product")
        _, product_id = _upload(
            db_session, _product_doc({"limitacoes": "x"}, unmatched={"a": 1}),
            _importer(values=False),
        )
        assert _stored(db_session, template, "data_product", product_id) == {}
        assert list(_product_props(db_session, product_id)) == ["tier"]

    def test_without_an_active_template_the_values_are_kept_apart(self, db_session):
        _drop_templates(db_session, "data_product")
        manager, product_id = _upload(
            db_session, _product_doc({"limitacoes": "kept"}), _importer(),
        )
        exported = _export_product(manager, db_session, product_id)
        assert _entry(exported["customProperties"], UNMATCHED) == {"limitacoes": "kept"}
        assert _entry(exported["customProperties"]) is None


class TestDocumentHelpers:

    def test_apply_to_document(self):
        doc = {"customProperties": [
            {"property": PROP, "value": {"stale": 1}},
            {"property": UNMATCHED, "value": {"u": 1}},
            {"property": "x"},
        ]}
        cte.apply_to_document(doc, {"a": 2}, readable=True)
        assert doc["customProperties"] == [
            {"property": "x"},
            {"property": UNMATCHED, "value": {"u": 1}},
            {"property": PROP, "value": {"a": 2}},
        ]
        cte.apply_to_document(doc, None, readable=True)
        assert doc["customProperties"] == [
            {"property": "x"}, {"property": UNMATCHED, "value": {"u": 1}},
        ]
        cte.apply_to_document(doc, {"a": 2}, readable=False)
        assert doc["customProperties"] == [{"property": "x"}]
        only = {"customProperties": [{"property": PROP, "value": {"a": 1}}]}
        cte.apply_to_document(only, {}, readable=True)
        assert "customProperties" not in only

    def test_read_and_strip_the_entries(self):
        props = [
            {"property": "x", "value": 1},
            {"property": PROP, "value": {"a": 1}},
            {"property": UNMATCHED, "value": '{"b": 2}'},
        ]
        assert cte.read_entry(props) == {"a": 1}
        assert cte.read_entry(props, UNMATCHED) == {"b": 2}
        assert cte.without_entries(props) == [{"property": "x", "value": 1}]
        assert cte.read_entry({PROP: {"a": 1}, "x": 1}) == {"a": 1}
        assert cte.without_entries({PROP: {"a": 1}, UNMATCHED: {}, "x": 1}) == {"x": 1}
        assert cte.read_entry([{"property": PROP, "value": "not a mapping"}]) is None
        assert cte.read_entry(None) is None

    def test_the_entry_size_is_capped(self):
        too_many = {f"k{i}": i for i in range(cte.MAX_ENTRY_KEYS + 1)}
        too_big = {"k": "x" * cte.MAX_ENTRY_BYTES}
        assert cte.read_entry([{"property": PROP, "value": too_many}]) is None
        assert cte.read_entry([{"property": PROP, "value": too_big}]) is None
        assert cte.read_entry([{"property": PROP, "value": json.dumps(too_big)}]) is None

    def test_imported_values_skip_nulls_and_report_the_rest(self, db_session):
        template = _template(db_session, "data_product")
        written, rest = cte.apply_imported_values(
            db_session, entity_type="data_product", entity_id="p-1",
            values={
                "refresh-hours": "soon", "limitacoes": "ok", "other": 1, "nothing": None,
            },
            user_email="u@example.com",
        )
        assert written == ["limitacoes"]
        assert rest == {"refresh-hours": "soon", "other": 1}
        assert _stored(db_session, template, "data_product", "p-1") == {"limitacoes": "ok"}

    @pytest.mark.parametrize("bad", ["NaN", "Infinity", "1e999", float("inf")])
    def test_non_finite_numbers_are_not_written(self, db_session, bad):
        template = _template(db_session, "data_product")
        written, rest = cte.apply_imported_values(
            db_session, entity_type="data_product", entity_id="p-2",
            values={"refresh-hours": bad}, user_email="u@example.com",
        )
        assert (written, list(rest)) == ([], ["refresh-hours"])
        assert _stored(db_session, template, "data_product", "p-2") == {}


def _checker(log: list, denied: dict):
    """A ``PermissionChecker`` stand-in: records the checks, raises for ``denied``."""
    def _make(feature_id, level):
        async def _check(request, user, auth_manager):
            log.append((feature_id, level.value))
            if feature_id in denied:
                raise HTTPException(status_code=denied[feature_id])
        return _check
    return _make


_USER = SimpleNamespace(email="u@example.com", username="u")


class TestAccess:

    @pytest.mark.parametrize("denied,values,assets", [
        ({}, True, True),
        ({"assets": 403}, True, False),
        ({"compliance-template-values": 403}, False, False),
    ])
    def test_import_needs_read_write(self, denied, values, assets):
        log: list = []
        with patch("src.common.authorization.PermissionChecker", side_effect=_checker(log, denied)):
            imp = asyncio.run(cte.import_access(None, _USER, None))
        assert (imp.can_write_values, imp.can_write_assets) == (values, assets)
        assert imp.user_email == "u@example.com"
        assert all(level == "Read/Write" for _, level in log)
        assert log[0][0] == "compliance-template-values"

    def test_read_needs_the_values_feature_read_only(self):
        log: list = []
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        with patch("src.common.authorization.PermissionChecker", side_effect=_checker(log, {})):
            access = asyncio.run(cte.read_access(request, _USER, None, None))
        assert log == [("compliance-template-values", "Read-only"), ("assets", "Read/Write")]
        assert access.values and access.assets_rw and access.may_read_product()

    def test_read_of_a_table_without_asset_edit_follows_the_product_links(self):
        asset = SimpleNamespace(id=uuid.uuid4())
        denied = {"assets": 403}

        def _read(state):
            request = SimpleNamespace(app=SimpleNamespace(state=state))
            with patch(
                "src.common.authorization.PermissionChecker", side_effect=_checker([], denied),
            ):
                return asyncio.run(cte.read_access(request, _USER, None, "db"))

        assert _read(SimpleNamespace()).may_read_asset(asset) is False

        dpm = object()
        calls = []

        def _accessible(db, *, asset_id, data_products_manager, is_admin):
            calls.append((db, asset_id, data_products_manager, is_admin))
            return True

        access = _read(SimpleNamespace(data_products_manager=dpm))
        with patch(
            "src.controller.assets_manager.assets_manager.is_asset_accessible",
            side_effect=_accessible,
        ):
            assert access.may_read_asset(asset) is True
        assert calls == [("db", asset.id, dpm, False)]

    def test_read_without_the_values_feature_reads_nothing(self):
        log: list = []
        denied = {"compliance-template-values": 403}
        with patch("src.common.authorization.PermissionChecker", side_effect=_checker(log, denied)):
            access = asyncio.run(cte.read_access(None, _USER, None, None))
        assert not access.may_read_product()
        assert not access.may_read_asset(SimpleNamespace(id=uuid.uuid4()))

    def test_other_errors_propagate(self):
        with patch(
            "src.common.authorization.PermissionChecker",
            side_effect=_checker([], {"compliance-template-values": 500}),
        ):
            with pytest.raises(HTTPException):
                asyncio.run(cte.import_access(None, _USER, None))


class TestRoutes:
    """The routes pass the user's rights to the managers and audit what was written."""

    def test_odcs_export_passes_the_read_access(self):
        from src.routes import data_contracts_routes as routes

        access = cte.ValuesReadAccess(values=True)
        manager = SimpleNamespace(build_odcs_from_db=lambda db_obj, db, compliance_read: (
            {"kind": "DataContract", "seen": compliance_read is access}
        ))
        db_obj = SimpleNamespace(name="Orders")

        async def _read(request, user, auth_manager, db):
            return access

        with patch.object(cte, "read_access", side_effect=_read), \
                patch.object(routes.data_contract_repo, "get_with_all", return_value=db_obj):
            resp = asyncio.run(routes.export_odcs(
                "c-1", request=None, db=None, manager=manager, _=True, user=_USER,
                auth_manager=None,
            ))
        assert yaml.safe_load(resp.body)["seen"] is True

    def test_odcs_upload_audits_the_values_written(self):
        from src.routes import data_contracts_routes as routes

        imp = cte.ComplianceImport(user_email="u@example.com", can_write_values=True)
        logged = {}

        def _create(db, parsed_odcs, current_user, compliance_import):
            assert compliance_import is imp
            imp.record("asset", "a-1", ["limitacoes"])
            return SimpleNamespace(id="c-1")

        async def _access(request, user, auth_manager):
            return imp

        manager = SimpleNamespace(
            parse_uploaded_file=lambda **kw: {}, validate_odcs=lambda parsed, strict: [],
            create_from_upload=_create, _build_contract_api_model=lambda db, obj: {"id": "c-1"},
        )
        audit = SimpleNamespace(log_action=lambda **kw: logged.update(kw))

        class _File:
            filename = "c.yaml"
            content_type = "application/x-yaml"

            async def read(self):
                return b"kind: DataContract"

        request = SimpleNamespace(client=None)
        with patch.object(cte, "import_access", side_effect=_access), \
                patch.object(routes.data_contract_repo, "get_with_all", return_value=None):
            asyncio.run(routes.upload_contract(
                request, db=None, audit_manager=audit, current_user=_USER, file=_File(),
                manager=manager, _=True, user=_USER, auth_manager=None,
            ))
        assert logged["details"]["compliance_values_written"] == [
            {"entityType": "asset", "entityId": "a-1", "referenceIds": ["limitacoes"]},
        ]
