"""erwin physical model → draft contracts bound to UC (PRD #1718, slices 3 #1721 and 4 #1722)."""
import hashlib
import io
from pathlib import Path
from uuid import uuid4

import pytest

from src.controller.data_contracts_manager import DataContractsManager
from src.controller.model_import_manager import ModelImportManager
from src.controller.semantic_links_manager import SemanticLinksManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_contracts import (
    DataContractCustomPropertyDb,
    DataContractDb,
    SchemaObjectDb,
    SchemaObjectRelationshipDb,
)
from src.models.model_import import CatalogMapping, ModelImportOptions
from src.tests.integration.test_model_import_concepts import semantic  # noqa: F401  (fixture)

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "erwin" / "sales_dw_standard.xml"
XML = FIXTURE.read_text(encoding="utf-8")
ACTOR = "steward@example.com"
MAPPING = [CatalogMapping(source="SALES", target="main.sales"), CatalogMapping(source="MDM", target="main.mdm")]


@pytest.fixture
def contracts(tmp_path):
    return DataContractsManager(data_dir=tmp_path)


@pytest.fixture
def manager(semantic, contracts):  # noqa: F811
    return ModelImportManager(semantic_models_manager=semantic, data_contracts_manager=contracts)


def _table_asset(db, fqn, columns):
    t = db.query(AssetTypeDb).filter(AssetTypeDb.name == "Table").first()
    if t is None:
        t = AssetTypeDb(id=uuid4(), name="Table")
        db.add(t)
        db.flush()
    a = AssetDb(
        id=uuid4(), name=fqn.split(".")[-1], asset_type_id=t.id, location=fqn,
        properties={"schema": {"columns": [{"name": n, "data_type": dt, "nullable": nl} for n, dt, nl in columns]}},
    )
    db.add(a)
    db.commit()
    return a


def _stage(manager, db, xml=XML, **opts):
    data = xml.encode("utf-8")
    opts.setdefault("catalog_mappings", MAPPING)
    return manager.create_run(
        db, stream=io.BytesIO(data), filename="sales_dw.xml", size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), user_id=ACTOR, options=ModelImportOptions(**opts),
    )


def _import(manager, db, xml=XML, **opts):
    run = _stage(manager, db, xml, **opts)
    run = manager.confirm_run(db, run, run.confirm_token, ACTOR, run_inline=True)
    assert run.status == "completed", run.error
    return run


def _contract_ids(run):
    return {c["name"]: c["contract_id"] for c in run.result["physical"]["contracts"]}


def _schema(db, contract_id, name):
    return db.query(SchemaObjectDb).filter(
        SchemaObjectDb.contract_id == contract_id, SchemaObjectDb.name == name,
    ).first()


@pytest.fixture
def uc(db_session):
    return _table_asset(db_session, "main.sales.customer", [
        ("customer_id", "bigint", False), ("customer_name", "string", False),
        ("email_address", "string", True), ("customer_since", "timestamp", True),
        ("party_id", "bigint", True),
    ]), _table_asset(db_session, "main.sales.orders", [
        ("order_id", "bigint", False), ("customer_id", "bigint", False), ("order_date", "timestamp", False),
        ("order_status", "string", False), ("total_amount", "decimal(10,2)", True), ("channel", "string", True),
    ])


class TestPreview:
    def test_physical_preview(self, manager, db_session, uc):
        run = _stage(manager, db_session)
        phys = run.preview["physical"]
        assert phys["counts"]["create"] == 2
        assert {c["name"] for c in phys["contracts"]} == {"Sales DW – Sales", "Sales DW – Party"}
        assert phys["uc"]["resolved"] == 2
        assert phys["uc"]["unresolved"] == 6
        orders = next(t for t in phys["uc"]["tables"] if t["table"] == "ORDERS")
        assert orders["drift"]["extra_in_uc"] == ["channel"]
        assert orders["drift"]["type_mismatches"][0]["column"] == "TOTAL_AMOUNT"
        assert any("did not resolve" in w for w in run.preview["warnings"])
        assert db_session.query(DataContractDb).count() == 0


class TestFirstImport:
    def test_contracts_with_keys_links_and_uc(self, manager, db_session, uc):
        run = _import(manager, db_session)
        ids = _contract_ids(run)
        sales = db_session.query(DataContractDb).filter(DataContractDb.id == ids["Sales DW – Sales"]).first()
        assert sales.status == "draft"

        cust = _schema(db_session, sales.id, "CUSTOMER")
        assert cust.physical_name == "main.sales.customer"
        assert cust.business_name == "Customer"
        cid = next(p for p in cust.properties if p.name == "CUSTOMER_ID")
        assert cid.primary_key and cid.primary_key_position == 1 and cid.required

        line = _schema(db_session, sales.id, "ORDER_LINE")
        assert line.physical_name is None  # not in UC
        rels = db_session.query(SchemaObjectRelationshipDb).filter(
            SchemaObjectRelationshipDb.schema_object_id == line.id).all()
        assert {(r.from_value, r.to_value) for r in rels} == {
            ("ORDER_LINE.ORDER_ID", "ORDERS.ORDER_ID"), ("ORDER_LINE.PRODUCT_ID", "PRODUCT.PRODUCT_ID"),
        }

        links = SemanticLinksManager(db_session).list_for_entity(
            entity_id=f"{sales.id}#CUSTOMER", entity_type="data_contract_schema")
        assert [l.iri for l in links] == ["urn:ontology:sales-dw/customer"]

        assert run.result["physical"]["uc"]["resolved"] == 2

    def test_drift_note_on_contract(self, manager, db_session, uc):
        from src.controller.metadata_manager import MetadataManager
        run = _import(manager, db_session)
        sales_id = _contract_ids(run)["Sales DW – Sales"]
        notes = MetadataManager().list_rich_texts(db_session, entity_type="data_contract", entity_id=sales_id)
        [note] = [n for n in notes if n.title == "erwin model drift"]
        assert "channel" in note.content_markdown
        party_id = _contract_ids(run)["Sales DW – Party"]
        assert not MetadataManager().list_rich_texts(db_session, entity_type="data_contract", entity_id=party_id)

    def test_physical_only_run_links_to_earlier_concepts(self, manager, db_session, uc):
        _import(manager, db_session, import_physical=False)
        run = _import(manager, db_session, import_logical=False)
        sales_id = _contract_ids(run)["Sales DW – Sales"]
        links = SemanticLinksManager(db_session).list_for_entity(
            entity_id=f"{sales_id}#CUSTOMER", entity_type="data_contract_schema")
        assert [l.iri for l in links] == ["urn:ontology:sales-dw/customer"]


class TestReimport:
    def test_identical_reimport_is_unchanged(self, manager, db_session, uc):
        first = _import(manager, db_session)
        run = _stage(manager, db_session)
        assert run.preview["physical"]["counts"]["unchanged"] == 2
        run = manager.confirm_run(db_session, run, run.confirm_token, ACTOR, run_inline=True)
        assert _contract_ids(run) == _contract_ids(first)
        assert db_session.query(DataContractDb).count() == 2

    def test_change_updates_draft_in_place(self, manager, db_session, uc):
        first = _import(manager, db_session)
        sales_id = _contract_ids(first)["Sales DW – Sales"]
        db_session.add(DataContractCustomPropertyDb(contract_id=sales_id, property="steward.note", value="keep me"))
        db_session.commit()
        changed = XML.replace("An item offered for sale.", "Anything we sell.")
        run = _stage(manager, db_session, changed)
        sales = next(c for c in run.preview["physical"]["contracts"] if c["name"] == "Sales DW – Sales")
        assert sales["action"] == "update"
        assert sales["diff"]["tables_changed"] == [{
            "table": "PRODUCT", "columns_added": [], "columns_removed": [], "columns_changed": [],
            "fields": ["description"],
        }]
        run = manager.confirm_run(db_session, run, run.confirm_token, ACTOR, run_inline=True)
        assert _contract_ids(run)["Sales DW – Sales"] == sales_id
        assert _schema(db_session, sales_id, "PRODUCT").description == "Anything we sell."
        props = {p.property: p.value for p in db_session.query(DataContractCustomPropertyDb).filter(
            DataContractCustomPropertyDb.contract_id == sales_id)}
        assert props["steward.note"] == "keep me"
        assert props["erwin.groupKey"].startswith("sa:")

    def test_change_to_approved_contract_makes_new_version(self, manager, db_session, uc):
        first = _import(manager, db_session)
        sales_id = _contract_ids(first)["Sales DW – Sales"]
        contract = db_session.query(DataContractDb).filter(DataContractDb.id == sales_id).first()
        contract.status = "approved"
        db_session.commit()
        changed = XML.replace("An item offered for sale.", "Anything we sell.")
        run = _stage(manager, db_session, changed)
        sales = next(c for c in run.preview["physical"]["contracts"] if c["name"] == "Sales DW – Sales")
        assert sales["action"] == "new_version"
        run = manager.confirm_run(db_session, run, run.confirm_token, ACTOR, run_inline=True)
        entry = next(c for c in run.result["physical"]["contracts"] if c["name"] == "Sales DW – Sales")
        assert entry["status"] == "ok", entry.get("error")
        assert entry["previous_contract_id"] == sales_id
        new = db_session.query(DataContractDb).filter(DataContractDb.id == entry["contract_id"]).first()
        assert new.status == "draft" and new.version == "1.1.0"
        assert _schema(db_session, new.id, "PRODUCT").description == "Anything we sell."
        db_session.refresh(contract)
        assert contract.status == "approved"
        assert _schema(db_session, sales_id, "PRODUCT").description == "An item offered for sale."

        # The next import targets the new version.
        again = _stage(manager, db_session, changed)
        sales = next(c for c in again.preview["physical"]["contracts"] if c["name"] == "Sales DW – Sales")
        assert sales["action"] == "unchanged"
        assert sales["existing_contract_id"] == new.id

    def test_removed_group_is_flagged(self, manager, db_session, uc):
        first = _import(manager, db_session)
        party_id = _contract_ids(first)["Sales DW – Party"]
        start = XML.index('<EMX:Subject_Area id="{SA-PARTY}+00000000"')
        end = XML.index("</EMX:Subject_Area>", start) + len("</EMX:Subject_Area>")
        without_party_area = XML[:start] + XML[end:]
        run = _stage(manager, db_session, without_party_area)
        assert [r["contract_id"] for r in run.preview["physical"]["removed"]] == [party_id]
        run = manager.confirm_run(db_session, run, run.confirm_token, ACTOR, run_inline=True)
        assert run.result["physical"]["removed"][0]["contract_id"] == party_id
        flag = db_session.query(DataContractCustomPropertyDb).filter(
            DataContractCustomPropertyDb.contract_id == party_id,
            DataContractCustomPropertyDb.property == "erwin.removedInSource").first()
        assert flag is not None and flag.value == "true"
        # The orphaned tables land in "Unassigned" now.
        assert "Sales DW – Unassigned" in _contract_ids(run)

    def test_scoped_run_never_flags_removed(self, manager, db_session, uc):
        _import(manager, db_session)
        run = _stage(manager, db_session, subject_area_ids=["{SA-SALES}+00000000"])
        assert run.preview["physical"]["removed"] == []


def test_grouping_change_creates_new_groups(manager, db_session, uc):
    _import(manager, db_session)
    run = _stage(manager, db_session, contract_grouping="schema")
    counts = run.preview["physical"]["counts"]
    assert counts["create"] == 2 and counts["removed"] == 2
