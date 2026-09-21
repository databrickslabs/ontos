"""ODCS v3.2.0 support: version-aware export/round-trip + in-app upgrade.

These tests exercise the manager layer directly against the (SQLite) test
session, so they do not depend on the HTTP/audit app-state wiring. They prove:

- A: v3.2.0 constructs (context, vector logicalTypeOptions, semanticType) are
     exported and validate against the v3.2.0 schema.
- B: a contract stored at an older apiVersion exports WITHOUT any v3.2.0-only
     fields and validates against that older version's schema (no field bleed).
- C: upgrade_contract_version produces a new draft in the same version family,
     bumps the apiVersion, and preserves the v3.2.0 data.
"""
from pathlib import Path

import pytest

from src.controller.data_contracts_manager import DataContractsManager
from src.common import odcs_versions
from src.common.odcs_validation import validate_odcs_contract
from src.db_models.data_contracts import (
    DataContractDb, SchemaObjectDb, SchemaPropertyDb,
    DataContractContextDb, DataContractContextVerifiedStatementDb,
    DataContractContextConstraintDb,
)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    mgr = DataContractsManager(data_dir=tmp_path)
    # Isolate from the search-index backend (not configured in unit tests).
    monkeypatch.setattr(mgr, "_update_search_index", lambda *a, **k: None)
    return mgr


def _make_contract(db, api_version="v3.2.0"):
    """Create a contract with a vector property, semanticType and context."""
    c = DataContractDb(
        name="cust", version="1.0.0", status="draft", api_version=api_version,
        kind="DataContract", version_family_id=None,
    )
    db.add(c)
    db.flush()

    so = SchemaObjectDb(contract_id=c.id, name="customers", logical_type="object")
    db.add(so)
    db.flush()

    prop = SchemaPropertyDb(
        object_id=so.id, name="embedding", logical_type="vector",
        logical_type_options_json='{"dimensions": 768, "elementType": "float32", "distanceMetric": "cosine"}',
        semantic_type="dimension",
    )
    db.add(prop)

    # schema-object-level context
    so_ctx = DataContractContextDb(schema_object_id=so.id, instructions="Treat as PII.")
    db.add(so_ctx)
    db.flush()
    db.add(DataContractContextVerifiedStatementDb(
        context_id=so_ctx.id, question="Is it deduplicated?", answer="Yes", position=0,
    ))

    # contract-level context
    c_ctx = DataContractContextDb(contract_id=c.id, instructions="Use for churn only.")
    db.add(c_ctx)
    db.flush()
    db.add(DataContractContextConstraintDb(
        context_id=c_ctx.id, constraint="Do not join to marketing_events.", position=0,
    ))

    db.commit()
    db.refresh(c)
    return c


def test_export_v320_includes_new_constructs_and_validates(manager, db_session):
    contract = _make_contract(db_session, api_version="v3.2.0")

    odcs = manager.build_odcs_from_db(contract, db_session)

    assert odcs["apiVersion"] == "v3.2.0"
    # contract-level context
    assert odcs.get("context", {}).get("instructions") == "Use for churn only."
    assert odcs["context"]["constraints"][0]["constraint"] == "Do not join to marketing_events."
    # schema-object-level context
    schema0 = odcs["schema"][0]
    assert schema0["context"]["instructions"] == "Treat as PII."
    assert schema0["context"]["verifiedStatements"][0]["question"] == "Is it deduplicated?"
    # vector property + nested logicalTypeOptions + semanticType
    prop0 = schema0["properties"][0]
    assert prop0["logicalType"] == "vector"
    assert prop0["logicalTypeOptions"]["dimensions"] == 768
    assert prop0["semanticType"] == "dimension"

    # Requirement A: the exported document validates against the v3.2.0 schema.
    validate_odcs_contract(odcs, strict=True)


@pytest.mark.parametrize("api_version", ["v3.0.1", "v3.0.2", "v3.1.0"])
def test_downlevel_export_omits_v320_fields_and_validates(manager, db_session, api_version):
    # Build with v3.2.0 data, then store at an older apiVersion (simulates a
    # contract that must round-trip down-level).
    contract = _make_contract(db_session, api_version=api_version)

    odcs = manager.build_odcs_from_db(contract, db_session)

    assert odcs["apiVersion"] == api_version
    # Requirement B: no v3.2.0-only field bleeds into an older-version export.
    assert "context" not in odcs
    schema0 = odcs["schema"][0]
    assert "context" not in schema0
    prop0 = schema0["properties"][0]
    assert prop0["logicalType"] != "vector"        # degraded, not emitted as vector
    assert "semanticType" not in prop0
    assert "logicalTypeOptions" not in prop0        # vector options dropped down-level

    # Validates against the OLDER version's own schema.
    validate_odcs_contract(odcs, strict=True)


def test_upgrade_creates_new_draft_in_same_family_preserving_data(manager, db_session):
    source = _make_contract(db_session, api_version="v3.1.0")
    source_family = source.version_family_id

    upgraded = manager.upgrade_contract_version(
        db_session, contract_id=source.id, target_api_version="v3.2.0",
        current_user="tester", version_bump="minor",
    )

    # Requirement C: new draft, same family, lineage, bumped version + apiVersion.
    assert upgraded.id != source.id
    assert upgraded.status == "draft"
    assert upgraded.api_version == "v3.2.0"
    assert upgraded.version == "1.1.0"
    assert upgraded.version_family_id == source_family
    assert upgraded.parent_contract_id == source.id

    # v3.2.0 data preserved through the clone, and now exportable at v3.2.0.
    odcs = manager.build_odcs_from_db(upgraded, db_session)
    assert odcs["context"]["instructions"] == "Use for churn only."
    prop0 = odcs["schema"][0]["properties"][0]
    assert prop0["logicalType"] == "vector"
    assert prop0["semanticType"] == "dimension"
    assert odcs["schema"][0]["context"]["instructions"] == "Treat as PII."
    validate_odcs_contract(odcs, strict=True)


def test_validator_selects_schema_by_apiversion():
    # A vector property is only valid at v3.2.0.
    doc = {
        "id": "x", "kind": "DataContract", "apiVersion": "v3.2.0", "version": "1.0.0",
        "status": "draft", "name": "n",
        "schema": [{"name": "t", "properties": [
            {"name": "e", "logicalType": "vector", "logicalTypeOptions": {"dimensions": 3}}
        ]}],
    }
    assert validate_odcs_contract(doc, strict=False, api_version="v3.2.0") is True
    # The same doc is invalid under the v3.0.2 schema (no vector type there).
    assert validate_odcs_contract(doc, strict=False, api_version="v3.0.2") is False


def test_upgrade_rejects_non_upgrade_target(manager, db_session):
    source = _make_contract(db_session, api_version="v3.2.0")
    with pytest.raises(ValueError):
        manager.upgrade_contract_version(
            db_session, contract_id=source.id, target_api_version="v3.0.1",
            current_user="tester",
        )
