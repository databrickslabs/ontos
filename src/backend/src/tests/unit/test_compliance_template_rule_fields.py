"""Unit tests: compliance template keys on compliance rule and maturity gate objects.

``template_applicable``, ``template_mandatory_missing_count``,
``template_complete`` and ``template_field_<reference id>`` are added to the
objects that compliance runs (``AppEntityLoader``) and maturity gates
(``build_data_product_dict``) evaluate. Uses the in-memory SQLite session.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.compliance_dsl import evaluate_rule_on_object
from src.common.compliance_entities import (
    AppEntityLoader,
    EntityFilter,
    UnityCatalogLoader,
    create_entity_iterator,
)
from src.controller.compliance_templates_manager import (
    compliance_templates_manager,
    rule_field_key,
)
from src.controller.entity_dict_builder import (
    _add_compliance_template_fields,
    build_data_product_dict,
)
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.compliance_templates import (
    ComplianceTemplateDb,
    ComplianceTemplateFieldDb,
    ComplianceTemplateValueDb,
)
from src.db_models.data_products import DataProductDb


def _product(db: Session) -> str:
    product_id = str(uuid.uuid4())
    db.add(DataProductDb(
        id=product_id, name=f"p_{product_id[:6]}", status="draft",
        version_family_id=product_id,
    ))
    db.flush()
    return product_id


def _template(db: Session, *, entity_type: str = "data_product", active: bool = True):
    db.query(ComplianceTemplateDb).filter_by(entity_type=entity_type).delete()
    template = ComplianceTemplateDb(
        id=uuid.uuid4(), name="Docs", entity_type=entity_type, is_active=active,
    )
    db.add(template)
    db.flush()
    fields = {
        "limitations": ComplianceTemplateFieldDb(
            id=uuid.uuid4(), template_id=template.id, key="limitations",
            label="Limitations", reference_id="limitations", value_type="string",
            is_mandatory=True, field_order=0,
        ),
        "intended-use": ComplianceTemplateFieldDb(
            id=uuid.uuid4(), template_id=template.id, key="intended_use",
            label="Intended use", reference_id="intended-use", value_type="enum",
            possible_values=["analytics", "ml"], default_value="analytics",
            is_mandatory=True, field_order=1,
        ),
        "reviewed": ComplianceTemplateFieldDb(
            id=uuid.uuid4(), template_id=template.id, key="reviewed",
            label="Reviewed", reference_id="reviewed", value_type="boolean",
            field_order=2,
        ),
    }
    db.add_all(fields.values())
    db.flush()
    return template, fields


def _value(db: Session, field, entity_id: str, value, entity_type: str = "data_product"):
    db.add(ComplianceTemplateValueDb(
        id=uuid.uuid4(), field_id=field.id, entity_type=entity_type,
        entity_id=entity_id, value=value,
    ))
    db.flush()


class TestRuleFieldsForEntities:

    def test_no_active_template(self, db_session: Session):
        _template(db_session, active=False)
        product_id = _product(db_session)
        fields = compliance_templates_manager.rule_fields_for_entities(
            db_session, entity_type="data_product", entity_ids=[product_id]
        )
        assert fields == {product_id: {
            "template_applicable": False,
            "template_mandatory_missing_count": 0,
            "template_complete": True,
        }}

    def test_missing_mandatory_field_and_effective_values(self, db_session: Session):
        _, f = _template(db_session)
        product_id = _product(db_session)
        _value(db_session, f["reviewed"], product_id, False)
        keys = compliance_templates_manager.rule_fields_for_entities(
            db_session, entity_type="data_product", entity_ids=[product_id]
        )[product_id]
        assert keys == {
            "template_applicable": True,
            "template_mandatory_missing_count": 1,  # limitations; intended-use has a default
            "template_complete": False,
            "template_field_limitations": None,
            "template_field_intended_use": "analytics",
            "template_field_reviewed": False,
        }

    def test_batch_reads_each_entity_separately(self, db_session: Session):
        _, f = _template(db_session)
        filled, empty = _product(db_session), _product(db_session)
        _value(db_session, f["limitations"], filled, "Daily refresh")
        _value(db_session, f["intended-use"], filled, "ml")
        # A blank stored value falls back to the default, as in the publish gate.
        _value(db_session, f["intended-use"], empty, "")
        keys = compliance_templates_manager.rule_fields_for_entities(
            db_session, entity_type="data_product", entity_ids=[filled, empty]
        )
        assert keys[filled]["template_complete"] is True
        assert keys[filled]["template_field_intended_use"] == "ml"
        assert keys[empty]["template_mandatory_missing_count"] == 1
        assert keys[empty]["template_field_intended_use"] == "analytics"

    def test_other_entity_types_are_not_mixed_in(self, db_session: Session):
        _, f = _template(db_session)
        product_id = _product(db_session)
        _value(db_session, f["limitations"], product_id, "x", entity_type="asset")
        keys = compliance_templates_manager.rule_fields_for_entities(
            db_session, entity_type="data_product", entity_ids=[product_id]
        )[product_id]
        assert keys["template_field_limitations"] is None
        assert keys["template_complete"] is False

    def test_rule_field_key_maps_hyphens(self):
        assert rule_field_key("intended-use") == "template_field_intended_use"
        assert rule_field_key("pii_2") == "template_field_pii_2"


class TestRuleObjects:

    @pytest.fixture
    def product_with_values(self, db_session: Session):
        _, f = _template(db_session)
        product_id = _product(db_session)
        _value(db_session, f["limitations"], product_id, "Daily refresh")
        return product_id

    def test_maturity_dict_has_template_keys(self, db_session: Session, product_with_values):
        d = build_data_product_dict(db_session, product_with_values)
        assert d["template_complete"] is True
        assert d["template_mandatory_missing_count"] == 0
        assert d["template_field_limitations"] == "Daily refresh"
        # The maturity gate rule from the docs passes on this dict.
        assert evaluate_rule_on_object(
            "MATCH (p:data_product) ASSERT p.template_applicable AND p.template_complete", d
        ) == (True, None)
        assert evaluate_rule_on_object(
            "ASSERT p.template_mandatory_missing_count = 0", d
        ) == (True, None)

    def test_maturity_gate_fails_while_a_field_is_missing(self, db_session: Session):
        _template(db_session)
        d = build_data_product_dict(db_session, _product(db_session))
        passed, message = evaluate_rule_on_object("ASSERT p.template_complete", d)
        assert passed is False
        assert message.startswith("Assertion failed")

    def test_compliance_loader_adds_template_keys(self, db_session: Session, product_with_values):
        loaded = {
            str(e["id"]): e
            for e in AppEntityLoader(db_session).load_entities(["data_product"])
        }
        entity = loaded[product_with_values]
        assert entity["template_applicable"] is True
        assert entity["template_complete"] is True
        assert entity["template_field_intended_use"] == "analytics"

    def test_compliance_loader_still_loads_when_template_keys_fail(
        self, db_session: Session, product_with_values, monkeypatch
    ):
        def _bad_query(db, **kwargs):
            db.execute(text("SELECT * FROM no_such_compliance_table"))

        monkeypatch.setattr(compliance_templates_manager, "rule_fields_for_entities", _bad_query)
        loaded = {
            str(e["id"]): e
            for e in AppEntityLoader(db_session).load_entities(["data_product", "domain"])
        }
        assert "template_complete" not in loaded[product_with_values]
        assert db_session.get(DataProductDb, product_with_values) is not None

    def test_maturity_dict_without_template_keys_when_they_fail(
        self, db_session: Session, product_with_values, monkeypatch
    ):
        def _bad_query(db, **kwargs):
            db.execute(text("SELECT * FROM no_such_compliance_table"))

        monkeypatch.setattr(compliance_templates_manager, "rule_fields_for_entities", _bad_query)
        d = build_data_product_dict(db_session, product_with_values)
        assert d is not None and d["name"]
        assert "template_complete" not in d
        # The failed read was rolled back to its savepoint; the session still works.
        assert db_session.get(DataProductDb, product_with_values) is not None


def _table_asset(db: Session, location: str, type_name: str = "Table") -> str:
    asset_type = db.query(AssetTypeDb).filter(AssetTypeDb.name == type_name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(id=uuid.uuid4(), name=type_name)
        db.add(asset_type)
        db.flush()
    asset = AssetDb(
        id=uuid.uuid4(), name=f"t_{uuid.uuid4().hex[:6]}", asset_type_id=asset_type.id,
        location=location, status="active",
    )
    db.add(asset)
    db.flush()
    return str(asset.id)


def _workspace(*full_names: str):
    """A workspace client whose Unity Catalog lists the given ``catalog.schema.table``s."""
    tables = [
        SimpleNamespace(
            name=n.split(".")[2], full_name=n,
            table_type="VIEW" if n.endswith("_v") else "MANAGED",
        )
        for n in full_names
    ]
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name="main")]
    ws.schemas.list.return_value = [SimpleNamespace(name="sales")]
    ws.tables.list.return_value = tables
    return ws


class TestTableObjects:
    """Tables and views: the keys of the Ontos table or view asset of the UC table."""

    @pytest.fixture
    def documented_table(self, db_session: Session):
        _, f = _template(db_session, entity_type="asset")
        asset_id = _table_asset(db_session, "main.sales.orders")
        _value(db_session, f["limitations"], asset_id, "Daily refresh", entity_type="asset")
        return asset_id

    def test_uc_loader_adds_the_asset_template_keys(self, db_session: Session, documented_table):
        _table_asset(db_session, "MAIN.SALES.PENDING_V", type_name="View")
        ws = _workspace("main.sales.orders", "main.sales.pending_v", "main.sales.unregistered")
        loaded = {
            e["full_name"]: e
            for e in UnityCatalogLoader(ws, db=db_session).load_entities(["table", "view"])
        }
        orders = loaded["main.sales.orders"]
        assert orders["template_complete"] is True
        assert orders["template_field_limitations"] == "Daily refresh"
        assert orders["template_field_intended_use"] == "analytics"
        pending = loaded["main.sales.pending_v"]
        assert pending["type"] == "view"
        assert pending["template_mandatory_missing_count"] == 1
        # A table with no Ontos asset has no template keys (rules on them see None).
        assert "template_complete" not in loaded["main.sales.unregistered"]

    def test_compliance_rule_on_a_table(self, db_session: Session, documented_table):
        ws = _workspace("main.sales.orders")
        entities = list(
            create_entity_iterator(db=db_session, workspace_client=ws).iterate(
                EntityFilter(entity_types=["table"])
            )
        )
        assert [e["full_name"] for e in entities] == ["main.sales.orders"]
        assert evaluate_rule_on_object(
            "MATCH (t:table) ASSERT t.template_applicable AND t.template_complete", entities[0]
        ) == (True, None)

    def test_uc_loader_without_a_database_has_no_template_keys(self, documented_table):
        entities = list(
            UnityCatalogLoader(_workspace("main.sales.orders")).load_entities(["table"])
        )
        assert "template_complete" not in entities[0]

    def test_uc_loader_still_loads_when_template_keys_fail(
        self, db_session: Session, documented_table, monkeypatch
    ):
        def _bad_query(db, **kwargs):
            db.execute(text("SELECT * FROM no_such_compliance_table"))

        monkeypatch.setattr(compliance_templates_manager, "rule_fields_for_entities", _bad_query)
        entities = list(
            UnityCatalogLoader(_workspace("main.sales.orders"), db=db_session)
            .load_entities(["table"])
        )
        assert [e["full_name"] for e in entities] == ["main.sales.orders"]
        assert "template_complete" not in entities[0]

    def test_location_is_matched_without_backticks_spaces_or_case(self, db_session: Session):
        _, f = _template(db_session, entity_type="asset")
        asset_id = _table_asset(db_session, " `Main`.`Sales`.`Spaced` ")
        _value(db_session, f["limitations"], asset_id, "ok", entity_type="asset")
        entities = list(
            UnityCatalogLoader(_workspace("main.sales.spaced"), db=db_session)
            .load_entities(["table"])
        )
        assert entities[0]["template_field_limitations"] == "ok"

    def test_ambiguous_location_gets_no_keys(self, db_session: Session, documented_table):
        _table_asset(db_session, "main.sales.orders", type_name="View")
        entities = list(
            UnityCatalogLoader(_workspace("main.sales.orders"), db=db_session)
            .load_entities(["table"])
        )
        assert "template_complete" not in entities[0]

    def test_maturity_gate_on_a_table_asset(self, db_session: Session, documented_table):
        """The keys a table or view asset's maturity dict gets (see the PR notes)."""
        d: dict = {}
        _add_compliance_template_fields(db_session, d, "asset", documented_table)
        assert evaluate_rule_on_object("ASSERT obj.template_complete", d) == (True, None)
        assert d["template_field_limitations"] == "Daily refresh"
