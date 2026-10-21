"""
Integration tests for semantic link processing during ODCS file upload.

Tests the complete flow of uploading ODCS files with semantic assignments
and verifying that EntitySemanticLinkDb records are created correctly.
"""

import json
import yaml
import pytest
from io import BytesIO
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.db_models.data_contracts import DataContractDb
from src.controller.semantic_links_manager import SemanticLinksManager


class TestSemanticUploadIntegration:
    """Integration tests for semantic link creation during ODCS upload."""

    @pytest.fixture
    def client(self):
        """Test client for API requests."""
        return TestClient(app)

    @pytest.fixture
    def odcs_contract_with_semantics(self):
        """Sample ODCS contract with semantic assignments at all levels."""
        return {
            "name": "semantic-test-contract",
            "version": "1.0.0",
            "status": "draft",
            "owner": "test-user",
            "kind": "DataContract",
            "apiVersion": "v3.1.0",
            "description": {
                "purpose": "Test contract for semantic link processing"
            },
            "authoritativeDefinitions": [
                {
                    "type": "http://databricks.com/ontology/uc/semanticAssignment",
                    "url": "https://example.com/business-concept/customer-contract"
                },
                {
                    "type": "http://other.com/ontology/standard",
                    "url": "https://example.com/standard/should-be-preserved"
                }
            ],
            "schema": [
                {
                    "name": "customers",
                    "physicalName": "customer_table",
                    "description": "Customer data table",
                    "authoritativeDefinitions": [
                        {
                            "type": "http://databricks.com/ontology/uc/semanticAssignment",
                            "url": "https://example.com/business-concept/customer-table"
                        }
                    ],
                    "properties": [
                        {
                            "name": "customer_id",
                            "logicalType": "string",
                            "required": True,
                            "primaryKey": True,
                            "authoritativeDefinitions": [
                                {
                                    "type": "http://databricks.com/ontology/uc/semanticAssignment",
                                    "url": "https://example.com/business-concept/customer-id"
                                }
                            ]
                        },
                        {
                            "name": "customer_name",
                            "logicalType": "string",
                            "required": True,
                            "authoritativeDefinitions": [
                                {
                                    "type": "http://databricks.com/ontology/uc/semanticAssignment",
                                    "url": "https://example.com/business-concept/customer-name"
                                }
                            ]
                        },
                        {
                            "name": "email",
                            "logicalType": "string",
                            "required": False
                            # No semantic assignments for this property
                        }
                    ]
                },
                {
                    "name": "orders",
                    "physicalName": "order_table",
                    "description": "Order data table",
                    # No schema-level semantic assignments
                    "properties": [
                        {
                            "name": "order_id",
                            "logicalType": "string",
                            "required": True,
                            "primaryKey": True,
                            "authoritativeDefinitions": [
                                {
                                    "type": "http://databricks.com/ontology/uc/semanticAssignment",
                                    "url": "https://example.com/business-concept/order-id"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

    def test_upload_yaml_with_semantic_assignments(self, client, db: Session, odcs_contract_with_semantics):
        """Test uploading a YAML file with semantic assignments creates EntitySemanticLinkDb records."""
        # Convert to YAML
        yaml_content = yaml.dump(odcs_contract_with_semantics, default_flow_style=False)

        # Create file upload
        files = {
            "files": ("semantic-test.yaml", BytesIO(yaml_content.encode()), "application/x-yaml")
        }

        # Mock authentication and permissions
        with client:
            response = client.post("/api/data-contracts/upload", files=files)

        assert response.status_code == 200
        contract_data = response.json()
        contract_id = contract_data["created_ids"][0]

        # Verify the contract was created
        contract_db = db.query(DataContractDb).filter(DataContractDb.id == contract_id).first()
        assert contract_db is not None
        assert contract_db.name == "semantic-test-contract"

        # Verify semantic links were created
        semantic_manager = SemanticLinksManager(db)

        # Check contract-level semantic link
        contract_links = semantic_manager.list_for_entity(
            entity_id=contract_id,
            entity_type="data_contract"
        )
        assert len(contract_links) == 1
        assert contract_links[0].iri == "https://example.com/business-concept/customer-contract"

        # Check schema-level semantic link (only customers schema has one)
        schema_links = semantic_manager.list_for_entity(
            entity_id=f"{contract_id}#customers",
            entity_type="data_contract_schema"
        )
        assert len(schema_links) == 1
        assert schema_links[0].iri == "https://example.com/business-concept/customer-table"

        # Check that orders schema has no semantic links
        orders_schema_links = semantic_manager.list_for_entity(
            entity_id=f"{contract_id}#orders",
            entity_type="data_contract_schema"
        )
        assert len(orders_schema_links) == 0

        # Check property-level semantic links
        customer_id_links = semantic_manager.list_for_entity(
            entity_id=f"{contract_id}#customers#customer_id",
            entity_type="data_contract_property"
        )
        assert len(customer_id_links) == 1
        assert customer_id_links[0].iri == "https://example.com/business-concept/customer-id"

        customer_name_links = semantic_manager.list_for_entity(
            entity_id=f"{contract_id}#customers#customer_name",
            entity_type="data_contract_property"
        )
        assert len(customer_name_links) == 1
        assert customer_name_links[0].iri == "https://example.com/business-concept/customer-name"

        # Check that email property has no semantic links
        email_links = semantic_manager.list_for_entity(
            entity_id=f"{contract_id}#customers#email",
            entity_type="data_contract_property"
        )
        assert len(email_links) == 0

        order_id_links = semantic_manager.list_for_entity(
            entity_id=f"{contract_id}#orders#order_id",
            entity_type="data_contract_property"
        )
        assert len(order_id_links) == 1
        assert order_id_links[0].iri == "https://example.com/business-concept/order-id"

        # Verify total count of semantic links
        all_links = db.query(EntitySemanticLinkDb).filter(
            EntitySemanticLinkDb.entity_id.like(f"{contract_id}%")
        ).all()
        # Expected: 1 contract + 1 schema + 3 properties = 5 total
        assert len(all_links) == 5

    def test_upload_json_with_semantic_assignments(self, client, db: Session, odcs_contract_with_semantics):
        """Test uploading a JSON file with semantic assignments."""
        # Convert to JSON
        json_content = json.dumps(odcs_contract_with_semantics, indent=2)

        # Create file upload
        files = {
            "files": ("semantic-test.json", BytesIO(json_content.encode()), "application/json")
        }

        # Mock authentication and permissions
        with client:
            response = client.post("/api/data-contracts/upload", files=files)

        assert response.status_code == 200
        contract_data = response.json()
        contract_id = contract_data["created_ids"][0]

        # Verify semantic links were created (same checks as YAML test)
        semantic_manager = SemanticLinksManager(db)

        all_links = db.query(EntitySemanticLinkDb).filter(
            EntitySemanticLinkDb.entity_id.like(f"{contract_id}%")
        ).all()
        # Expected: 1 contract + 1 schema + 3 properties = 5 total
        assert len(all_links) == 5

    def test_upload_contract_without_semantic_assignments(self, client, db: Session):
        """Test uploading a contract without semantic assignments creates no semantic links."""
        contract_without_semantics = {
            "name": "no-semantics-contract",
            "version": "1.0.0",
            "status": "draft",
            "owner": "test-user",
            "description": {
                "purpose": "Contract without semantic assignments"
            },
            "schema": [
                {
                    "name": "simple_table",
                    "properties": [
                        {
                            "name": "id",
                            "logicalType": "string",
                            "required": True
                        }
                    ]
                }
            ]
        }

        yaml_content = yaml.dump(contract_without_semantics, default_flow_style=False)
        files = {
            "files": ("no-semantics.yaml", BytesIO(yaml_content.encode()), "application/x-yaml")
        }

        with client:
            response = client.post("/api/data-contracts/upload", files=files)

        assert response.status_code == 200
        contract_data = response.json()
        contract_id = contract_data["created_ids"][0]

        # Verify no semantic links were created
        all_links = db.query(EntitySemanticLinkDb).filter(
            EntitySemanticLinkDb.entity_id.like(f"{contract_id}%")
        ).all()
        assert len(all_links) == 0

    def test_upload_with_mixed_authoritative_definitions(self, client, db: Session):
        """Test that only semantic assignment types create semantic links, others are preserved."""
        contract_with_mixed_auth_defs = {
            "name": "mixed-auth-defs-contract",
            "version": "1.0.0",
            "status": "draft",
            "owner": "test-user",
            "authoritativeDefinitions": [
                {
                    "type": "http://databricks.com/ontology/uc/semanticAssignment",
                    "url": "https://example.com/business-concept/semantic-link"
                },
                {
                    "type": "http://other.com/ontology/standard",
                    "url": "https://example.com/standard/preserved-but-not-linked"
                },
                {
                    "type": "http://example.com/custom/reference",
                    "url": "https://example.com/custom/also-preserved"
                }
            ]
        }

        yaml_content = yaml.dump(contract_with_mixed_auth_defs, default_flow_style=False)
        files = {
            "files": ("mixed-auth-defs.yaml", BytesIO(yaml_content.encode()), "application/x-yaml")
        }

        with client:
            response = client.post("/api/data-contracts/upload", files=files)

        assert response.status_code == 200
        contract_data = response.json()
        contract_id = contract_data["created_ids"][0]

        # Verify only one semantic link was created (for the semantic assignment type)
        semantic_links = db.query(EntitySemanticLinkDb).filter(
            EntitySemanticLinkDb.entity_id == contract_id,
            EntitySemanticLinkDb.entity_type == "data_contract"
        ).all()
        assert len(semantic_links) == 1
        assert semantic_links[0].iri == "https://example.com/business-concept/semantic-link"

        # Verify all authoritative definitions were preserved in the database
        # (This would need to query the DataContractAuthoritativeDefinitionDb table)
        from src.db_models.data_contracts import DataContractAuthoritativeDefinitionDb
        auth_defs = db.query(DataContractAuthoritativeDefinitionDb).filter(
            DataContractAuthoritativeDefinitionDb.contract_id == contract_id
        ).all()
        assert len(auth_defs) == 3

        # Verify all types were preserved
        auth_def_types = {auth_def.type for auth_def in auth_defs}
        expected_types = {
            "http://databricks.com/ontology/uc/semanticAssignment",
            "http://other.com/ontology/standard",
            "http://example.com/custom/reference"
        }
        assert auth_def_types == expected_types

    def test_round_trip_upload_then_export(self, client, db: Session, odcs_contract_with_semantics):
        """Test that uploading and then exporting preserves semantic assignments."""
        # Upload the contract
        yaml_content = yaml.dump(odcs_contract_with_semantics, default_flow_style=False)
        files = {
            "files": ("round-trip-test.yaml", BytesIO(yaml_content.encode()), "application/x-yaml")
        }

        with client:
            upload_response = client.post("/api/data-contracts/upload", files=files)

        assert upload_response.status_code == 200
        contract_data = upload_response.json()
        contract_id = contract_data["created_ids"][0]

        # Export the contract
        with client:
            export_response = client.get(f"/api/data-contracts/{contract_id}/odcs/export")

        assert export_response.status_code == 200

        # Parse the exported YAML
        exported_yaml = export_response.content.decode()
        exported_contract = yaml.safe_load(exported_yaml)

        # Verify semantic assignments are present in export
        contract_auth_defs = exported_contract.get("authoritativeDefinitions", [])
        semantic_auth_defs = [
            auth_def for auth_def in contract_auth_defs
            if auth_def.get("type") == "http://databricks.com/ontology/uc/semanticAssignment"
        ]
        # Should have the original semantic assignment plus any preserved non-semantic ones
        assert len(semantic_auth_defs) >= 1

        # Verify schema-level semantic assignments
        customers_schema = None
        for schema in exported_contract.get("schema", []):
            if schema.get("name") == "customers":
                customers_schema = schema
                break

        assert customers_schema is not None
        schema_auth_defs = customers_schema.get("authoritativeDefinitions", [])
        schema_semantic_auth_defs = [
            auth_def for auth_def in schema_auth_defs
            if auth_def.get("type") == "http://databricks.com/ontology/uc/semanticAssignment"
        ]
        assert len(schema_semantic_auth_defs) == 1
        assert schema_semantic_auth_defs[0]["url"] == "https://example.com/business-concept/customer-table"

        # Verify property-level semantic assignments
        customer_id_prop = None
        for prop in customers_schema.get("properties", []):
            if prop.get("name") == "customer_id":
                customer_id_prop = prop
                break

        assert customer_id_prop is not None
        prop_auth_defs = customer_id_prop.get("authoritativeDefinitions", [])
        prop_semantic_auth_defs = [
            auth_def for auth_def in prop_auth_defs
            if auth_def.get("type") == "http://databricks.com/ontology/uc/semanticAssignment"
        ]
        assert len(prop_semantic_auth_defs) == 1
        assert prop_semantic_auth_defs[0]["url"] == "https://example.com/business-concept/customer-id"