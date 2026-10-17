"""Version-diff service: manager ``diff_versions`` + response rendering (PRD #1086 slice 4)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from src.common.entity_diff.render import build_diff_response, to_plain, unified_yaml_diff
from src.common.entity_diff.rules_odcs import ODCS_PROFILE, ODCS_RULES
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import (
    DataContractDb,
    SchemaObjectDb,
    SchemaPropertyDb,
)
from src.models.entity_diff import EntityDiffResponse


def _contract(db, family_id, version, props, parent_id=None):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name="orders", version=version, status="active",
        version_family_id=family_id, parent_contract_id=parent_id,
    )
    db.add(contract)
    db.flush()
    obj = SchemaObjectDb(id=str(uuid.uuid4()), contract_id=contract.id, name="orders",
                         logical_type="object")
    db.add(obj)
    db.flush()
    for name, logical_type, required in props:
        db.add(SchemaPropertyDb(id=str(uuid.uuid4()), object_id=obj.id, name=name,
                                logical_type=logical_type, required=required))
    db.flush()
    return contract


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


class TestContractDiffVersions:
    def test_classifies_changes_between_two_versions(self, db_session):
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, "1.0.0", [("id", "string", True), ("note", "string", False)])
        v2 = _contract(db_session, family, "1.0.1", [("id", "integer", True)], parent_id=v1.id)

        result = _manager().diff_versions(db_session, base_id=v1.id, target_id=v2.id)

        EntityDiffResponse.model_validate(result)  # matches the route's response_model
        assert result["entity_type"] == "data_contract"
        assert (result["base"]["version"], result["target"]["version"]) == ("1.0.0", "1.0.1")
        paths = {c["path"]: c for c in result["changes"]}
        assert paths["schema[orders].properties[id].logicalType"]["bump"] == "major"
        assert paths["schema[orders].properties[note]"]["rule_id"] == "property-removed"
        assert result["suggested_bump"] == "major"
        assert result["suggested_version"] == "2.0.0"
        assert result["version_consistent"] is False  # 1.0.1 is only a patch bump
        removed = [ln for ln in result["unified_diff"].splitlines() if ln.startswith("-") and not ln.startswith("---")]
        added = [ln for ln in result["unified_diff"].splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        assert any("logicalType: string" in ln for ln in removed)
        assert any("logicalType: integer" in ln for ln in added)

    def test_identical_versions_have_no_changes(self, db_session):
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, "1.0.0", [("id", "string", True)])
        v2 = _contract(db_session, family, "1.0.1", [("id", "string", True)], parent_id=v1.id)

        result = _manager().diff_versions(db_session, base_id=v1.id, target_id=v2.id)

        assert result["changes"] == []
        assert result["suggested_bump"] == "none"
        assert result["version_consistent"] is True
        assert result["unified_diff"] == ""

    def test_rejects_different_families(self, db_session):
        a = _contract(db_session, str(uuid.uuid4()), "1.0.0", [("id", "string", True)])
        b = _contract(db_session, str(uuid.uuid4()), "1.0.0", [("id", "string", True)])

        with pytest.raises(ValueError):
            _manager().diff_versions(db_session, base_id=a.id, target_id=b.id)

    def test_missing_contract_is_lookup_error(self, db_session):
        a = _contract(db_session, str(uuid.uuid4()), "1.0.0", [("id", "string", True)])

        with pytest.raises(LookupError):
            _manager().diff_versions(db_session, base_id=a.id, target_id="does-not-exist")


class TestRender:
    def test_to_plain_stringifies_non_json_values(self):
        assert to_plain({"at": datetime(2026, 1, 2, 3, 4, 5)}) == {"at": "2026-01-02 03:04:05"}

    def test_unified_diff_labels_and_content(self):
        diff = unified_yaml_diff({"a": 1}, {"a": 2}, "orders 1.0.0", "orders 2.0.0")
        assert diff.startswith("--- orders 1.0.0\n+++ orders 2.0.0\n")
        assert "-a: 1\n" in diff and "+a: 2\n" in diff

    def test_response_versions_come_from_row_metadata(self):
        """Profiles strip the documents' own `version`; the response must still
        report and judge versions from the rows."""
        response = build_diff_response(
            "data_contract",
            {"id": "a", "name": "c", "version": "1.2.0", "status": "active"},
            {"id": "b", "name": "c", "version": "2.0.0", "status": "draft"},
            {"version": "ignored", "schema": [{"name": "s"}]},
            {"version": "ignored", "schema": []},
            ODCS_PROFILE, ODCS_RULES,
        )
        assert response["suggested_version"] == "2.0.0"
        assert response["version_consistent"] is True
        assert response["counts"]["major"] == 1
