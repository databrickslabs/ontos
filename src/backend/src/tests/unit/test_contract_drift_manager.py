"""Unit tests for contract drift detection and adoption (nebw #2).

Exercises ContractDriftManager against the in-memory DB using the real
DataContractsManager for ODCS build / compare / clone / schema-replace.
"""
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.controller.contract_drift_manager import ContractDriftManager, DriftAdoptionMode
from src.common.errors import ConflictError
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb, SchemaPropertyDb


def _contracts_manager():
    return DataContractsManager(data_dir=Path("/tmp"))


@pytest.fixture(autouse=True)
def _isolate_committed_contracts(db_session: Session):
    """Purge contracts after each test.

    Adoption exercises ``clone_contract_for_new_version`` / ``replace_contract_schema``,
    which call ``db.commit()`` internally. That commits the shared in-memory
    connection's outer transaction, so the session-fixture's rollback no longer
    undoes rows created here — they would otherwise leak into later tests in the
    same process. Explicitly remove them (schema objects/properties cascade).
    """
    yield
    # SQLite bulk DELETE does not honor FK cascade, so purge children first.
    from src.db_models.data_contracts import (
        DataQualityCheckDb,
        SchemaPropertyRelationshipDb,
        SchemaObjectRelationshipDb,
    )
    try:
        db_session.rollback()
        for model in (
            DataQualityCheckDb,
            SchemaPropertyRelationshipDb,
            SchemaObjectRelationshipDb,
            SchemaPropertyDb,
            SchemaObjectDb,
            DataContractDb,
        ):
            db_session.query(model).delete(synchronize_session=False)
        db_session.commit()
    except Exception:
        db_session.rollback()


def _col(name, data_type="string", nullable=True):
    return SimpleNamespace(
        name=name, data_type=data_type, logical_type=data_type, nullable=nullable
    )


def _schema_info(columns, primary_key=None):
    return SimpleNamespace(columns=columns, primary_key=primary_key or [], foreign_keys=[])


@pytest.fixture
def contract_with_schema(db_session: Session):
    """A 1.0.0 contract with an 'orders' table: id (required), amount."""
    cm = _contracts_manager()
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name="orders", version="1.0.0", status="active"))
    db_session.commit()
    cm._create_schema_objects(db_session, cid, [
        {
            "name": "orders",
            "properties": [
                {"name": "id", "logicalType": "string", "required": True,
                 "primaryKey": True, "primaryKeyPosition": 0},
                {"name": "amount", "logicalType": "number", "required": False},
            ],
        }
    ])
    db_session.commit()
    return cid


class TestDriftDetection:
    def test_no_drift_when_schema_matches(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        # Same columns as the contract -> no drift.
        si = _schema_info(
            [_col("id", "string", nullable=False), _col("amount", "number")],
            primary_key=["id"],
        )
        result = drift.analyze_contract_drift(db_session, contract_with_schema, si)
        assert result["version_bump"] == "none"

    def test_added_optional_column_is_minor(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        si = _schema_info(
            [_col("id", "string", nullable=False), _col("amount", "number"),
             _col("currency", "string", nullable=True)],
            primary_key=["id"],
        )
        result = drift.analyze_contract_drift(db_session, contract_with_schema, si)
        assert result["version_bump"] == "minor"

    def test_removed_required_column_is_breaking(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        # Drop the required 'id' -> breaking.
        si = _schema_info([_col("amount", "number")])
        result = drift.analyze_contract_drift(db_session, contract_with_schema, si)
        assert result["version_bump"] == "major"


class TestDriftAdoption:
    def test_new_version_adoption_bumps_and_applies_schema(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        si = _schema_info(
            [_col("id", "string", nullable=False), _col("amount", "number"),
             _col("currency", "string")],
            primary_key=["id"],
        )
        out = drift.adopt_drift(
            db_session, contract_with_schema, si,
            mode=DriftAdoptionMode.NEW_VERSION, current_user="tester",
        )
        db_session.commit()
        assert out["version_bump"] == "minor"
        assert out["new_version"] == "1.1.0"
        assert out["contract_id"] != contract_with_schema
        # New contract carries the drifted column set.
        new_props = (
            db_session.query(SchemaPropertyDb)
            .join(SchemaObjectDb, SchemaPropertyDb.object_id == SchemaObjectDb.id)
            .filter(SchemaObjectDb.contract_id == out["contract_id"]).all()
        )
        assert {p.name for p in new_props} == {"id", "amount", "currency"}

    def test_in_place_adoption_for_non_breaking(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        si = _schema_info(
            [_col("id", "string", nullable=False), _col("amount", "number"),
             _col("currency", "string")],
            primary_key=["id"],
        )
        out = drift.adopt_drift(
            db_session, contract_with_schema, si,
            mode=DriftAdoptionMode.IN_PLACE, current_user="tester",
        )
        db_session.commit()
        assert out["contract_id"] == contract_with_schema
        assert out["new_version"] == "1.1.0"
        props = (
            db_session.query(SchemaPropertyDb)
            .join(SchemaObjectDb, SchemaPropertyDb.object_id == SchemaObjectDb.id)
            .filter(SchemaObjectDb.contract_id == contract_with_schema).all()
        )
        assert {p.name for p in props} == {"id", "amount", "currency"}

    def test_in_place_rejected_for_breaking(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        si = _schema_info([_col("amount", "number")])  # drops required id -> breaking
        with pytest.raises(ConflictError):
            drift.adopt_drift(
                db_session, contract_with_schema, si,
                mode=DriftAdoptionMode.IN_PLACE, current_user="tester",
            )

    def test_bump_override_cannot_weaken_severity(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        si = _schema_info([_col("amount", "number")])  # breaking -> requires major
        with pytest.raises(ConflictError):
            drift.adopt_drift(
                db_session, contract_with_schema, si,
                mode=DriftAdoptionMode.NEW_VERSION, bump_override="patch",
                current_user="tester",
            )

    def test_no_drift_adoption_raises(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)
        si = _schema_info(
            [_col("id", "string", nullable=False), _col("amount", "number")],
            primary_key=["id"],
        )
        with pytest.raises(ConflictError):
            drift.adopt_drift(
                db_session, contract_with_schema, si,
                mode=DriftAdoptionMode.NEW_VERSION, current_user="tester",
            )
