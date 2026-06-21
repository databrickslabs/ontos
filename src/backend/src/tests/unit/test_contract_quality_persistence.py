"""Unit tests for column-level (property) quality-rule persistence.

Regression coverage for ONT-CUJ-008: quality rules authored on a schema
column were accepted by the UI but silently dropped on save because
``_create_schema_objects`` never read ``properties[].quality``. These tests
exercise the manager's schema-object builder directly against the in-memory
DB so they stay fast and dependency-free.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import (
    DataContractDb,
    DataQualityCheckDb,
    SchemaObjectDb,
    SchemaPropertyDb,
)


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


@pytest.fixture
def contract(db_session: Session):
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name="C", version="1.0.0", status="draft"))
    db_session.commit()
    return cid


def _schema_with_column_rule():
    return [
        {
            "name": "orders",
            "properties": [
                {
                    "name": "amount",
                    "logicalType": "number",
                    "quality": [
                        {
                            "name": "non_negative",
                            "type": "library",
                            "rule": "rangeCheck",
                            "dimension": "accuracy",
                            "severity": "error",
                            "description": "amount must be >= 0",
                            "mustBeGe": "0",
                        }
                    ],
                }
            ],
        }
    ]


class TestColumnQualityPersistence:
    def test_property_quality_rule_is_persisted(self, db_session: Session, contract):
        manager = _manager()
        manager._create_schema_objects(db_session, contract, _schema_with_column_rule())
        db_session.commit()

        prop = db_session.query(SchemaPropertyDb).filter_by(name="amount").one()
        checks = (
            db_session.query(DataQualityCheckDb)
            .filter(DataQualityCheckDb.property_id == prop.id)
            .all()
        )
        assert len(checks) == 1
        check = checks[0]
        # Bound to the column, not just the table.
        assert check.property_id == prop.id
        assert check.object_id is not None
        assert check.level == "property"
        # ODCS fields round-trip through the shared builder.
        assert check.name == "non_negative"
        assert check.rule == "rangeCheck"
        assert check.dimension == "accuracy"
        assert check.severity == "error"
        assert check.must_be_ge == "0"

    def test_column_without_quality_creates_no_checks(self, db_session: Session, contract):
        manager = _manager()
        manager._create_schema_objects(
            db_session,
            contract,
            [{"name": "t", "properties": [{"name": "c", "logicalType": "string"}]}],
        )
        db_session.commit()
        assert db_session.query(DataQualityCheckDb).count() == 0

    def test_object_and_property_checks_coexist(self, db_session: Session, contract):
        """Object-level (qualityRules) and property-level checks are distinct
        rows distinguishable by property_id."""
        manager = _manager()
        manager._create_schema_objects(db_session, contract, _schema_with_column_rule())
        db_session.flush()
        # Object-level rule attaches to the first schema object (property_id NULL).
        manager._create_quality_checks(
            db_session, contract, [{"name": "row_count", "type": "sql", "query": "SELECT 1"}]
        )
        db_session.commit()

        all_checks = db_session.query(DataQualityCheckDb).all()
        assert len(all_checks) == 2
        property_level = [c for c in all_checks if c.property_id is not None]
        object_level = [c for c in all_checks if c.property_id is None]
        assert len(property_level) == 1
        assert len(object_level) == 1
        assert object_level[0].name == "row_count"
