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
    from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
    try:
        db_session.rollback()
        for model in (
            ReviewedAssetDb,
            DataAssetReviewRequestDb,
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


class _FakeReviewsManager:
    """Minimal stand-in for DataAssetReviewManager.create_review_request.

    Persists a real review + reviewed asset so dedup can query the DB.
    """
    def __init__(self, db):
        self._db = db
        self.created = []

    def create_review_request(self, request, db=None):
        import uuid as _uuid
        from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
        session = db or self._db
        rid = str(_uuid.uuid4())
        req = DataAssetReviewRequestDb(
            id=rid, requester_email=request.requester_email,
            reviewer_email=request.reviewer_email, title=request.title,
            status="queued", notes=request.notes,
        )
        session.add(req)
        session.flush()
        for fqn in request.asset_fqns:
            session.add(ReviewedAssetDb(
                id=str(_uuid.uuid4()), review_request_id=rid,
                asset_fqn=fqn, asset_type="data_contract", status="pending",
            ))
        session.flush()
        self.created.append(rid)
        return SimpleNamespace(id=rid)


class TestDriftReviewCreation:
    def test_creates_review_for_drift(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        reviews = _FakeReviewsManager(db_session)
        drift = ContractDriftManager(cm, asset_reviews_manager=reviews)
        analysis = {"version_bump": "minor", "summary": "Added column", "new_features": ["Added optional field: orders.currency"]}
        rid = drift.create_drift_review(
            db_session, contract_with_schema, "main.sales.orders", analysis,
            reviewer_email="steward@example.com", requester_email="system@example.com",
        )
        assert rid is not None
        assert reviews.created == [rid]

    def test_dedupes_open_review(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        reviews = _FakeReviewsManager(db_session)
        drift = ContractDriftManager(cm, asset_reviews_manager=reviews)
        analysis = {"version_bump": "minor", "summary": "Added column"}
        first = drift.create_drift_review(
            db_session, contract_with_schema, "main.sales.orders", analysis,
            reviewer_email="steward@example.com", requester_email="system@example.com",
        )
        second = drift.create_drift_review(
            db_session, contract_with_schema, "main.sales.orders", analysis,
            reviewer_email="steward@example.com", requester_email="system@example.com",
        )
        assert first is not None
        assert second is None  # deduped against the open review
        assert reviews.created == [first]

    def test_no_reviews_manager_returns_none(self, db_session, contract_with_schema):
        cm = _contracts_manager()
        drift = ContractDriftManager(cm)  # no reviews manager
        rid = drift.create_drift_review(
            db_session, contract_with_schema, "main.sales.orders",
            {"version_bump": "minor"},
            reviewer_email="s@example.com", requester_email="sys@example.com",
        )
        assert rid is None
