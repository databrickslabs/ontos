"""Unit tests: compliance template keys on compliance rule and maturity gate objects.

``template_applicable``, ``template_mandatory_missing_count``,
``template_complete`` and ``template_field_<reference id>`` are added to the
objects that compliance runs (``AppEntityLoader``) and maturity gates
(``build_data_product_dict``) evaluate. Uses the in-memory SQLite session.
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.compliance_dsl import evaluate_rule_on_object
from src.common.compliance_entities import AppEntityLoader
from src.controller.compliance_templates_manager import (
    compliance_templates_manager,
    rule_field_key,
)
from src.controller.entity_dict_builder import build_data_product_dict
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
