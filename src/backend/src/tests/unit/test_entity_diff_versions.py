"""Version-diff service: manager ``diff_versions`` + response rendering (PRD #1086 slice 4)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import datetime
from pathlib import Path

import pytest

from src.common.entity_diff import Bump
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


def _product_manager(db):
    from unittest.mock import MagicMock

    from databricks.sdk import WorkspaceClient

    from src.controller.data_products_manager import DataProductsManager
    return DataProductsManager(db=db, ws_client=MagicMock(spec=WorkspaceClient))


def _product(db, family_id, version, output_port, parent_id=None):
    from src.models.data_products import DataProductCreate
    from src.repositories.data_products_repository import data_product_repo

    product = data_product_repo.create(db=db, obj_in=DataProductCreate(
        id=str(uuid.uuid4()), apiVersion="v1.0.0", kind="DataProduct", name="orders",
        version=version, status="active", version_family_id=family_id, parent_product_id=parent_id,
        outputPorts=[output_port] if output_port else [],
    ))
    db.commit()
    return product


PORT = {"name": "orders_table", "version": "1.0.0", "contractId": "c1", "type": "table",
        "server": {"location": "s3://lake/orders/v1", "format": "delta"}, "containsPii": False}


class TestProductDiffVersions:
    """Real DB round-trip: the ODPS export alone drops port server/type/PII,
    so these rules only fire if the diff document carries full ports."""

    @pytest.mark.parametrize("mutate,rule_id", [
        (lambda p: p["server"].update(location="s3://lake/orders/v2"), "output-port-server"),
        (lambda p: p.update(containsPii=True), "output-port-pii"),
        (lambda p: p.update(type="view"), "output-port-type"),
    ])
    def test_port_details_are_classified_major(self, db_session, mutate, rule_id):
        import copy
        family = str(uuid.uuid4())
        v1 = _product(db_session, family, "1.0.0", PORT)
        changed = copy.deepcopy(PORT)
        mutate(changed)
        v2 = _product(db_session, family, "1.0.1", changed, parent_id=v1.id)

        result = _product_manager(db_session).diff_versions(db_session, base_id=v1.id, target_id=v2.id)

        EntityDiffResponse.model_validate(result)
        assert result["suggested_bump"] == "major", result["changes"]
        assert any(c["rule_id"] == rule_id for c in result["changes"])
        assert result["version_consistent"] is False

    def test_removed_output_port_via_diff_from_parent(self, db_session):
        family = str(uuid.uuid4())
        v1 = _product(db_session, family, "1.0.0", PORT)
        draft = _product(db_session, family, "1.0.0-draft", None, parent_id=v1.id)

        legacy = _product_manager(db_session).get_diff_from_parent(db_session, product_id=draft.id)

        assert legacy["suggested_bump"] == "major"
        assert legacy["suggested_version"] == "2.0.0"
        assert legacy["analysis"]["breaking_changes"] == ["Output port removed: outputPorts[orders_table]"]
        assert "**" not in legacy["analysis"]["summary"]  # plain text, rendered as-is by the dialogs

    def test_unchanged_draft_still_suggests_a_patch_commit(self, db_session):
        family = str(uuid.uuid4())
        v1 = _product(db_session, family, "1.0.0", PORT)
        draft = _product(db_session, family, "1.0.0-draft", PORT, parent_id=v1.id)

        legacy = _product_manager(db_session).get_diff_from_parent(db_session, product_id=draft.id)

        assert legacy["analysis"]["version_bump"] == "none"
        assert (legacy["suggested_bump"], legacy["suggested_version"]) == ("patch", "1.0.1")

    def test_rejects_different_families(self, db_session):
        from src.common.entity_diff import VersionFamilyMismatch
        a = _product(db_session, str(uuid.uuid4()), "1.0.0", PORT)
        b = _product(db_session, str(uuid.uuid4()), "1.0.0", PORT)

        with pytest.raises(VersionFamilyMismatch):
            _product_manager(db_session).diff_versions(db_session, base_id=a.id, target_id=b.id)


class TestReviewFindingsSlice4:
    def test_same_name_ports_are_told_apart_by_version(self):
        from src.common.entity_diff import compare
        from src.common.entity_diff.rules_odps import ODPS_PROFILE, ODPS_RULES
        v1 = {"outputPorts": [{"name": "orders", "version": "1.0.0"}, {"name": "orders", "version": "2.0.0"}]}
        v2 = {"outputPorts": [{"name": "orders", "version": "2.0.0"}]}

        result = compare(v1, v2, ODPS_PROFILE, ODPS_RULES)

        # orders@1.0.0 was dropped; orders@2.0.0 is unchanged (not "1.0.0 → 2.0.0").
        assert [(c.path, c.op, c.rule_id) for c in result.changes] == [
            ("outputPorts[orders@1.0.0]", "removed", "output-port-removed"),
        ]
        assert result.suggested_bump == Bump.MAJOR

    def test_yaml_diff_hides_ignored_ids(self):
        response = build_diff_response(
            "data_contract",
            {"id": "a", "version": "1.0.0"}, {"id": "b", "version": "1.0.1"},
            {"schema": [{"name": "s", "id": "x1"}]}, {"schema": [{"name": "s", "id": "x2"}]},
            ODCS_PROFILE, ODCS_RULES,
        )
        assert response["changes"] == []
        assert response["unified_diff"] == ""
