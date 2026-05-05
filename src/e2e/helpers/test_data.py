"""
Payload factories for E2E tests.

Every factory populates ALL fields so round-trip tests can verify nothing is lost.
The `mutate_all_fields` helper changes every mutable field to a different valid value.

All names are prefixed with E2E_PREFIX so test data is identifiable and cleanable.
"""
import uuid
from copy import deepcopy
from typing import Any, Dict

E2E_PREFIX = "e2e-test-"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Data Domains
# ---------------------------------------------------------------------------
def make_domain(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"{E2E_PREFIX}domain-{_uid()}",
        "description": f"E2E domain created by automated tests",
    }
    defaults.update(overrides)
    return defaults


def mutate_domain(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}domain-{_uid()}"
    m["description"] = "Updated by E2E test"
    return m


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
def make_team(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"{E2E_PREFIX}team-{_uid()}",
        "title": f"E2E Test Team {_uid()}",
        "description": "E2E team created by automated tests",
        "metadata": {"website": "https://example.com/e2e"},
    }
    defaults.update(overrides)
    return defaults


def mutate_team(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}team-{_uid()}"
    m["title"] = "Updated Team Title"
    m["description"] = "Updated by E2E test"
    m["metadata"] = {"website": "https://example.com/e2e-updated"}
    return m


def make_team_member(**overrides) -> Dict[str, Any]:
    defaults = {
        "member_type": "user",
        "member_identifier": f"e2e-user-{_uid()}@example.com",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def make_project(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"{E2E_PREFIX}project-{_uid()}",
        "title": f"E2E Test Project {_uid()}",
        "description": "E2E project created by automated tests",
        "project_type": "TEAM",
        "metadata": {"repo": "https://github.com/example/e2e"},
    }
    defaults.update(overrides)
    return defaults


def mutate_project(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}project-{_uid()}"
    m["title"] = "Updated Project Title"
    m["description"] = "Updated by E2E test"
    m["metadata"] = {"repo": "https://github.com/example/updated"}
    return m


# ---------------------------------------------------------------------------
# Tag Namespaces & Tags
# ---------------------------------------------------------------------------
def make_tag_namespace(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"e2e-ns-{_uid()}",
        "description": "E2E namespace created by automated tests",
    }
    defaults.update(overrides)
    return defaults


def make_tag(namespace_id: str = None, **overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"e2e-tag-{_uid()}",
        "description": "E2E tag created by automated tests",
        "possible_values": ["val-a", "val-b", "val-c"],
        "status": "active",
        "version": "v1.0",
    }
    if namespace_id:
        defaults["namespace_id"] = namespace_id
    else:
        defaults["namespace_name"] = "default"
    defaults.update(overrides)
    return defaults


def mutate_tag(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"e2e-tag-{_uid()}"
    m["description"] = "Updated by E2E test"
    m["possible_values"] = ["val-x", "val-y"]
    m["version"] = "v2.0"
    return m


# ---------------------------------------------------------------------------
# Data Products (ODPS v1.0.0)
# ---------------------------------------------------------------------------
def make_data_product(**overrides) -> Dict[str, Any]:
    pid = f"{E2E_PREFIX}product-{_uid()}"
    defaults = {
        "apiVersion": "v1.0.0",
        "kind": "DataProduct",
        "id": pid,
        "status": "draft",
        "name": pid,
        "version": "1.0.0",
        "domain": "e2e-testing",
        "tenant": "e2e-org",
        "description": {
            "purpose": "E2E test product",
            "limitations": "Test data only",
            "usage": "Automated testing",
        },
        "customProperties": [
            {"property": "e2eTestId", "value": _uid(), "description": "E2E identifier"},
        ],
        "max_level_inheritance": 99,
    }
    defaults.update(overrides)
    return defaults


def mutate_data_product(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}product-{_uid()}"
    m["version"] = "1.1.0"
    m["domain"] = "e2e-testing-updated"
    m["tenant"] = "e2e-org-updated"
    m["description"] = {
        "purpose": "Updated E2E test product",
        "limitations": "Still test data",
        "usage": "Updated automated testing",
    }
    m["customProperties"] = [
        {"property": "e2eUpdated", "value": "true", "description": "Updated"},
    ]
    m["max_level_inheritance"] = 50
    return m


# ---------------------------------------------------------------------------
# Data Contracts (ODCS v3.0.2)
# ---------------------------------------------------------------------------
def make_data_contract(**overrides) -> Dict[str, Any]:
    cid = f"{E2E_PREFIX}contract-{_uid()}"
    defaults = {
        "kind": "DataContract",
        "apiVersion": "v3.0.2",
        "id": cid,
        "version": "1.0.0",
        "status": "draft",
        "name": cid,
        "domain": "e2e-testing",
        "description": {
            "purpose": "E2E test contract",
            "usage": "Automated round-trip testing",
        },
        "schema": [
            {
                "name": "e2e_table",
                "physicalName": "e2e_physical_table",
                "description": "Test schema object",
                "properties": [
                    {
                        "name": "id",
                        "logicalType": "integer",
                        "required": True,
                        "unique": True,
                        "primaryKey": True,
                        "description": "Primary key",
                    },
                    {
                        "name": "name",
                        "logicalType": "string",
                        "required": True,
                        "description": "Name field",
                        "maxLength": 255,
                    },
                    {
                        "name": "value",
                        "logicalType": "double",
                        "required": False,
                        "description": "Numeric value",
                    },
                ],
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def mutate_data_contract(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}contract-{_uid()}"
    m["version"] = "1.1.0"
    m["domain"] = "e2e-testing-updated"
    m["description"] = {
        "purpose": "Updated E2E test contract",
        "usage": "Updated automated testing",
    }
    # Add a column to the schema
    if m.get("schema") and len(m["schema"]) > 0:
        m["schema"][0]["properties"].append({
            "name": "updated_field",
            "logicalType": "string",
            "required": False,
            "description": "Added by E2E update test",
        })
    return m


# ---------------------------------------------------------------------------
# Compliance Policies
# ---------------------------------------------------------------------------
def make_compliance_policy(**overrides) -> Dict[str, Any]:
    defaults = {
        "id": str(uuid.uuid4()),
        "name": f"{E2E_PREFIX}policy-{_uid()}",
        "description": "E2E compliance policy",
        "rule": 'ALL data_contracts MUST HAVE status',
        "compliance": 0.0,
        "severity": "medium",
        "category": "e2e-testing",
        "is_active": True,
    }
    defaults.update(overrides)
    return defaults


def mutate_compliance_policy(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}policy-{_uid()}"
    m["description"] = "Updated E2E compliance policy"
    m["severity"] = "high"
    m["category"] = "e2e-testing-updated"
    return m


# ---------------------------------------------------------------------------
# Security Features
# ---------------------------------------------------------------------------
def make_security_feature(**overrides) -> Dict[str, Any]:
    defaults = {
        "id": f"{E2E_PREFIX}secfeat-{_uid()}",
        "name": f"E2E Security Feature {_uid()}",
        "description": "E2E security feature",
        "type": "row_filtering",
        "target": "e2e_catalog.e2e_schema.e2e_table",
        "conditions": ["user_group = 'e2e'"],
        "status": "active",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def make_notification(**overrides) -> Dict[str, Any]:
    from datetime import datetime, timezone
    defaults = {
        "id": str(uuid.uuid4()),
        "title": f"E2E Notification {_uid()}",
        "message": "This is an E2E test notification",
        "type": "info",
        "read": False,
        "can_delete": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Datasets
# ---------------------------------------------------------------------------
def make_dataset(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"{E2E_PREFIX}dataset-{_uid()}",
        "description": "E2E dataset created by automated tests",
        "status": "draft",
        "version": "1.0.0",
        "published": False,
        "max_level_inheritance": 99,
    }
    defaults.update(overrides)
    return defaults


def mutate_dataset(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}dataset-{_uid()}"
    m["description"] = "Updated by E2E test"
    m["version"] = "2.0.0"
    return m


# ---------------------------------------------------------------------------
# Dataset Instances
# ---------------------------------------------------------------------------
def make_dataset_instance(**overrides) -> Dict[str, Any]:
    defaults = {
        "physical_path": f"e2e_catalog.e2e_schema.e2e_table_{_uid()}",
        "asset_type": "table",
        "role": "main",
        "display_name": f"E2E Instance {_uid()}",
        "environment": "dev",
        "status": "active",
        "notes": "Created by E2E test",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Entitlements Personas
# ---------------------------------------------------------------------------
def make_persona(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"{E2E_PREFIX}persona-{_uid()}",
        "description": "E2E persona created by automated tests",
        "privileges": [],
        "groups": [],
    }
    defaults.update(overrides)
    return defaults


def mutate_persona(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}persona-{_uid()}"
    m["description"] = "Updated by E2E test"
    return m


# ---------------------------------------------------------------------------
# Security Features (extended)
# ---------------------------------------------------------------------------
def mutate_security_feature(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"E2E Security Feature Updated {_uid()}"
    m["description"] = "Updated by E2E test"
    return m


# ---------------------------------------------------------------------------
# Estates
# ---------------------------------------------------------------------------
def make_estate(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"{E2E_PREFIX}estate-{_uid()}",
        "description": "E2E estate created by automated tests",
        "workspace_url": "https://e2e-test.cloud.databricks.com",
        "cloud_type": "aws",
        "metastore_name": "e2e_metastore",
        "connection_type": "delta_share",
        "sharing_policies": [],
        "is_enabled": True,
        "sync_schedule": "0 0 * * *",
    }
    defaults.update(overrides)
    return defaults


def mutate_estate(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}estate-{_uid()}"
    m["description"] = "Updated by E2E test"
    m["sync_schedule"] = "0 6 * * *"
    return m


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------
def make_workflow(**overrides) -> Dict[str, Any]:
    defaults = {
        "name": f"{E2E_PREFIX}workflow-{_uid()}",
        "description": "E2E workflow created by automated tests",
        "trigger": {
            "type": "manual",
            "entity_types": ["data_contract"],
        },
        "scope": {
            "type": "all",
        },
        "is_active": False,
        "steps": [
            {
                "step_id": "step-1",
                "name": "E2E Notify Step",
                "step_type": "notification",
                "config": {
                    "recipients": "owner",
                    "template": "E2E test notification",
                },
                "on_failure": "pass",
            },
        ],
    }
    defaults.update(overrides)
    return defaults


def mutate_workflow(original: Dict[str, Any]) -> Dict[str, Any]:
    m = deepcopy(original)
    m["name"] = f"{E2E_PREFIX}workflow-{_uid()}"
    m["description"] = "Updated by E2E test"
    return m


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
def make_comment(entity_type: str, entity_id: str, **overrides) -> Dict[str, Any]:
    defaults = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "comment": f"E2E test comment {_uid()}",
        "title": f"E2E Comment {_uid()}",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------
def make_cost_item(entity_type: str, entity_id: str, **overrides) -> Dict[str, Any]:
    defaults = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": f"E2E Cost {_uid()}",
        "description": "E2E cost item created by automated tests",
        "cost_center": "INFRASTRUCTURE",
        "amount_cents": 5000,
        "currency": "USD",
        "start_month": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Metadata: Rich Texts
# ---------------------------------------------------------------------------
def make_rich_text(entity_type: str, entity_id: str, **overrides) -> Dict[str, Any]:
    defaults = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": f"E2E Rich Text {_uid()}",
        "content_markdown": "# E2E Test\n\nThis is a **rich text** created by automated tests.",
        "level": 50,
        "inheritable": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Metadata: Links
# ---------------------------------------------------------------------------
def make_link(entity_type: str, entity_id: str, **overrides) -> Dict[str, Any]:
    defaults = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": f"E2E Link {_uid()}",
        "url": "https://example.com/e2e-test",
        "short_description": "E2E test link",
        "level": 50,
        "inheritable": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Change Log
# ---------------------------------------------------------------------------
def make_change_log_entry(**overrides) -> Dict[str, Any]:
    defaults = {
        "entity_type": "data_product",
        "entity_id": f"e2e-entity-{_uid()}",
        "action": "E2E_TEST",
        "details_json": '{"test": true}',
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------
def make_rating(entity_type: str, entity_id: str, **overrides) -> Dict[str, Any]:
    defaults = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "rating": 4,
        "comment": f"E2E test rating {_uid()}",
    }
    defaults.update(overrides)
    return defaults
