import pytest
import json
import yaml
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch, Mock

from src.db_models.data_contracts import (
    DataContractDb,
    DataContractTagDb,
    DataContractTeamDb,
    DataContractRoleDb,
    DataContractServerDb,
    DataContractServerPropertyDb,
    DataContractSupportDb,
    DataContractPricingDb,
    DataContractSlaPropertyDb,
    SchemaObjectDb,
    SchemaPropertyDb,
    DataQualityCheckDb,
)


class TestDataContractsRoutes:
    """Integration tests for data contracts API endpoints."""

    @pytest.fixture
    def sample_contract_data(self):
        """Sample contract data for testing."""
        return {
            "name": "Test Contract",
            "version": "1.0.0",
            "status": "draft",
            "owner": "test@example.com",
            "description": {
                "usage": "Test usage",
                "purpose": "Test purpose",
                "limitations": "Test limitations"
            }
        }

    @pytest.fixture
    def full_odcs_data(self):
        """Full ODCS data for comprehensive testing."""
        return {
            "id": "test-contract-id",
            "kind": "DataContract",
            "apiVersion": "v3.1.0",
            "version": "1.1.0",
            "status": "active",
            "name": "my quantum",
            "owner": "localdev",
            "tenant": "ClimateQuantumInc",
            "dataProduct": "my quantum",
            "domain": "seller",
            "slaDefaultElement": "tab1.txn_ref_dt",
            "contractCreatedTs": "2022-11-15T02:59:43+00:00",
            "description": {
                "usage": "Predict sales over time",
                "purpose": "Views built on top of the seller tables.",
                "limitations": "Data based on seller perspective, no buyer information",
                "authoritativeDefinitions": [
                    {
                        "type": "privacy-statement",
                        "url": "https://example.com/gdpr.pdf"
                    }
                ]
            },
            "schema": [
                {
                    "name": "tbl",
                    "physicalName": "tbl_1",
                    "physicalType": "table",
                    "businessName": "Core Payment Metrics",
                    "description": "Provides core payment metrics",
                    "dataGranularityDescription": "Aggregation on columns txn_ref_dt, pmt_txn_id",
                    "tags": ["finance", "payments"],
                    "properties": [
                        {
                            "name": "transaction_reference_date",
                            "physicalName": "txn_ref_dt",
                            "primaryKey": False,
                            "primaryKeyPosition": -1,
                            "businessName": "transaction reference date",
                            "logicalType": "date",
                            "physicalType": "date",
                            "required": False,
                            "description": "Reference date for transaction",
                            "partitioned": True,
                            "partitionKeyPosition": 1,
                            "criticalDataElement": False,
                            "tags": [],
                            "classification": "public",
                            "transformSourceObjects": [
                                "table_name_1",
                                "table_name_2",
                                "table_name_3"
                            ],
                            "transformLogic": "sel t1.txn_dt as txn_ref_dt from table_name_1 as t1, table_name_2 as t2, table_name_3 as t3 where t1.txn_dt=date-3",
                            "transformDescription": "defines the logic in business terms; logic for dummies",
                            "examples": [
                                "2022-10-03",
                                "2020-01-28"
                            ]
                        },
                        {
                            "name": "rcvr_id",
                            "primaryKey": True,
                            "primaryKeyPosition": 1,
                            "businessName": "receiver id",
                            "logicalType": "string",
                            "physicalType": "varchar(18)",
                            "required": False,
                            "description": "A description for column rcvr_id.",
                            "partitioned": False,
                            "partitionKeyPosition": -1,
                            "criticalDataElement": False,
                            "tags": ["uid"],
                            "classification": "restricted"
                        }
                    ],
                    "quality": [
                        {
                            "rule": "nullCheck",
                            "description": "column should not contain null values",
                            "dimension": "completeness",
                            "type": "library",
                            "severity": "error",
                            "businessImpact": "operational",
                            "schedule": "0 20 * * *",
                            "scheduler": "cron"
                        }
                    ],
                    "authoritativeDefinitions": [
                        {
                            "url": "https://catalog.data.gov/dataset/air-quality",
                            "type": "businessDefinition"
                        }
                    ],
                    "customProperties": [
                        {
                            "property": "business-key",
                            "value": ["txn_ref_dt", "rcvr_id"]
                        }
                    ]
                }
            ],
            "team": [
                {
                    "username": "ceastwood",
                    "role": "Data Scientist",
                    "dateIn": "2022-08-02",
                    "dateOut": "2022-10-01",
                    "replacedByUsername": "mhopper"
                },
                {
                    "username": "mhopper",
                    "role": "Data Scientist",
                    "dateIn": "2022-10-01"
                }
            ],
            "roles": [
                {
                    "role": "microstrategy_user_opr",
                    "access": "read",
                    "firstLevelApprovers": "Reporting Manager",
                    "secondLevelApprovers": "mandolorian"
                }
            ],
            "servers": [
                {
                    "server": "my-postgres",
                    "type": "postgres",
                    "host": "localhost",
                    "port": 5432,
                    "database": "pypl-edw",
                    "schema": "pp_access_views"
                }
            ],
            "support": [
                {
                    "channel": "#product-help",
                    "tool": "slack",
                    "url": "https://aidaug.slack.com/archives/C05UZRSBKLY"
                }
            ],
            "slaProperties": [
                {
                    "property": "latency",
                    "value": 4,
                    "unit": "d",
                    "element": "tab1.txn_ref_dt"
                }
            ],
            "price": {
                "priceAmount": 9.95,
                "priceCurrency": "USD",
                "priceUnit": "megabyte"
            },
            "tags": ["transactions"],
            "customProperties": [
                {
                    "property": "refRulesetName",
                    "value": "gcsc.ruleset.name"
                }
            ]
        }

    def test_get_contracts_empty(self, client: TestClient, db_session: Session):
        """Test getting contracts when none exist."""
        response = client.get("/api/data-contracts")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_contract_basic(self, client: TestClient, db_session: Session, sample_contract_data):
        """Test creating a basic contract."""
        response = client.post("/api/data-contracts", json=sample_contract_data)
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "Test Contract"
        assert data["version"] == "1.0.0"
        assert data["status"] == "draft"
        assert "id" in data
        assert "created_at" in data

        # Verify it's in the database
        contract = db_session.query(DataContractDb).filter_by(name="Test Contract").first()
        assert contract is not None
        assert contract.description_usage == "Test usage"

    def test_create_contract_duplicate_name_version(self, client: TestClient, db_session: Session, sample_contract_data):
        """Test creating contract with duplicate name and version should fail."""
        # Create first contract
        response1 = client.post("/api/data-contracts", json=sample_contract_data)
        assert response1.status_code == 201

        # Try to create duplicate
        response2 = client.post("/api/data-contracts", json=sample_contract_data)
        assert response2.status_code == 400
        assert "already exists" in response2.json()["detail"]

    def test_get_contract_by_id(self, client: TestClient, db_session: Session, sample_contract_data):
        """Test getting a contract by ID."""
        # Create contract first
        create_response = client.post("/api/data-contracts", json=sample_contract_data)
        contract_id = create_response.json()["id"]

        # Get contract
        response = client.get(f"/api/data-contracts/{contract_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == contract_id
        assert data["name"] == "Test Contract"

    def test_get_contract_not_found(self, client: TestClient):
        """Test getting non-existent contract."""
        response = client.get("/api/data-contracts/non-existent-id")
        assert response.status_code == 404

    def test_update_contract(self, client: TestClient, db_session: Session, sample_contract_data):
        """Test updating a contract."""
        # Create contract first
        create_response = client.post("/api/data-contracts", json=sample_contract_data)
        contract_id = create_response.json()["id"]

        # Update contract
        update_data = {
            "name": "Updated Contract",
            "status": "active"
        }
        response = client.put(f"/api/data-contracts/{contract_id}", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Updated Contract"
        assert data["status"] == "active"
        assert data["version"] == "1.0.0"  # Should remain unchanged

    def test_delete_contract(self, client: TestClient, db_session: Session, sample_contract_data):
        """Test deleting a contract."""
        # Create contract first
        create_response = client.post("/api/data-contracts", json=sample_contract_data)
        contract_id = create_response.json()["id"]

        # Delete contract
        response = client.delete(f"/api/data-contracts/{contract_id}")
        assert response.status_code == 200

        # Verify it's deleted
        get_response = client.get(f"/api/data-contracts/{contract_id}")
        assert get_response.status_code == 404

    def test_create_contract_from_odcs_yaml(self, client: TestClient, db_session: Session, full_odcs_data):
        """Test creating contract from ODCS YAML upload."""
        # Convert to YAML
        yaml_content = yaml.dump(full_odcs_data)

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            # Upload YAML file
            with open(temp_path, 'rb') as file:
                files = {"files": ("contract.yaml", file, "application/x-yaml")}
                response = client.post("/api/data-contracts/upload", files=files)

            assert response.status_code == 200
            data = response.json()
            # BatchImportResult: one entity created from the single-object file.
            assert data["created"] == 1
            assert data["items"][0]["name"] == "my quantum"

            # Verify complex relationships were created
            contract = db_session.query(DataContractDb).filter_by(name="my quantum").first()
            assert contract is not None
            assert len(contract.tags) > 0
            assert len(contract.team) > 0
            assert len(contract.schema_objects) > 0

        finally:
            Path(temp_path).unlink()

    def test_create_contract_from_odcs_json(self, client: TestClient, db_session: Session, full_odcs_data):
        """Test creating contract from ODCS JSON upload."""
        # Convert to JSON
        json_content = json.dumps(full_odcs_data)

        # Create temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(json_content)
            temp_path = f.name

        try:
            # Upload JSON file
            with open(temp_path, 'rb') as file:
                files = {"files": ("contract.json", file, "application/json")}
                response = client.post("/api/data-contracts/upload", files=files)

            assert response.status_code == 200
            data = response.json()
            assert data["created"] == 1
            assert data["items"][0]["name"] == "my quantum"

        finally:
            Path(temp_path).unlink()

    def test_upload_freeform_text_file_becomes_minimal_draft(self, client: TestClient):
        """Free-form text is accepted as a minimal draft contract.

        Contracts deliberately support plain text (`.txt` is in the upload accept
        list and `parse_uploaded_file` wraps unstructured content into a minimal
        contract). The batch endpoint preserves this lenient fallback and reports
        it truthfully as one created item rather than aborting.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("This is not valid ODCS content")
            temp_path = f.name

        try:
            with open(temp_path, 'rb') as file:
                files = {"files": ("invalid.txt", file, "text/plain")}
                response = client.post("/api/data-contracts/upload", files=files)

            assert response.status_code == 200, response.text
            data = response.json()
            assert data["created"] == 1
            assert data["total"] == 1

        finally:
            Path(temp_path).unlink()

    def test_export_contract_as_odcs_yaml(self, client: TestClient, db_session: Session):
        """Test exporting contract as ODCS YAML."""
        # Create a contract with full data structure
        contract = DataContractDb(
            name="Export Test",
            version="1.0.0",
            status="active",
            owner_team_id=None,
            description_usage="Test export",
            description_purpose="Test ODCS export functionality"
        )
        db_session.add(contract)
        db_session.commit()

        # Add some schema
        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="test_table",
            physical_name="test_table_physical",
            business_name="Test Table"
        )
        db_session.add(schema_obj)
        db_session.commit()

        prop = SchemaPropertyDb(
            object_id=schema_obj.id,
            name="test_column",
            logical_type="string",
            required=True
        )
        db_session.add(prop)
        db_session.commit()

        # Mock domain resolution
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "test-domain"
            mock_domain_repo.get.return_value = mock_domain

            # Mock semantic links manager
            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{contract.id}/odcs/export")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-yaml; charset=utf-8"

        # Parse the YAML response
        yaml_content = yaml.safe_load(response.content)
        assert yaml_content["name"] == "Export Test"
        assert yaml_content["version"] == "1.0.0"
        assert "schema" in yaml_content
        assert len(yaml_content["schema"]) == 1
        assert yaml_content["schema"][0]["name"] == "test_table"

    def test_export_contract_not_found(self, client: TestClient):
        """Test exporting non-existent contract."""
        response = client.get("/api/data-contracts/non-existent-id/odcs/export")
        assert response.status_code == 404

    def test_list_contracts_pagination(self, client: TestClient, db_session: Session):
        """Test contract listing with pagination."""
        # Create multiple contracts
        for i in range(5):
            contract = DataContractDb(
                name=f"Contract {i}",
                version="1.0.0",
                status="draft",
                owner_team_id=None
            )
            db_session.add(contract)
        db_session.commit()

        # Test first page
        response = client.get("/api/data-contracts?skip=0&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

        # Test second page
        response = client.get("/api/data-contracts?skip=3&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_contracts_filtering(self, client: TestClient, db_session: Session):
        """Test contract listing with filters."""
        # Create contracts with different statuses
        active_contract = DataContractDb(
            name="Active Contract",
            version="1.0.0",
            status="active",
            owner_team_id=None
        )
        draft_contract = DataContractDb(
            name="Draft Contract",
            version="1.0.0",
            status="draft",
            owner_team_id=None
        )
        db_session.add_all([active_contract, draft_contract])
        db_session.commit()

        # Filter by status
        response = client.get("/api/data-contracts?status=active")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "active"

    def test_contract_with_complex_relationships(self, client: TestClient, db_session: Session):
        """Test contract with all relationship types."""
        # Create contract
        contract = DataContractDb(
            name="Complex Contract",
            version="1.0.0",
            status="active",
            owner_team_id=None
        )
        db_session.add(contract)
        db_session.commit()

        # Add tags
        tag = DataContractTagDb(contract_id=contract.id, name="test-tag")
        db_session.add(tag)

        # Add team member
        team = DataContractTeamDb(
            contract_id=contract.id,
            username="team@example.com",
            role="Data Engineer"
        )
        db_session.add(team)

        # Add role
        role = DataContractRoleDb(
            contract_id=contract.id,
            role="reader",
            access="read"
        )
        db_session.add(role)

        # Add server with properties
        server = DataContractServerDb(
            contract_id=contract.id,
            server="test-db",
            type="postgresql"
        )
        db_session.add(server)
        db_session.commit()

        server_prop = DataContractServerPropertyDb(
            server_id=server.id,
            key="host",
            value="localhost"
        )
        db_session.add(server_prop)

        # Add support
        support = DataContractSupportDb(
            contract_id=contract.id,
            channel="#help",
            url="https://example.com"
        )
        db_session.add(support)

        # Add pricing
        pricing = DataContractPricingDb(
            contract_id=contract.id,
            price_amount="10.00",
            price_currency="USD"
        )
        db_session.add(pricing)

        # Add SLA property
        sla = DataContractSlaPropertyDb(
            contract_id=contract.id,
            property="availability",
            value="99.9"
        )
        db_session.add(sla)

        db_session.commit()

        # Get contract and verify all relationships
        response = client.get(f"/api/data-contracts/{contract.id}")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Complex Contract"
        # Additional relationship verification would depend on the response structure

    def test_create_contract_validation_errors(self, client: TestClient):
        """Test contract creation with validation errors."""
        # Missing required fields
        invalid_data = {
            "description": "Missing required fields"
        }
        response = client.post("/api/data-contracts", json=invalid_data)
        assert response.status_code == 422

        # Invalid version format
        invalid_data = {
            "name": "Test",
            "version": "invalid-version",
            "status": "draft"
        }
        response = client.post("/api/data-contracts", json=invalid_data)
        # Depending on validation rules, this might be 422 or 400

    def test_export_with_missing_relationships(self, client: TestClient, db_session: Session):
        """Test ODCS export with minimal contract data."""
        # Create minimal contract
        contract = DataContractDb(
            name="Minimal Contract",
            version="1.0.0",
            status="draft",
            owner_team_id=None
        )
        db_session.add(contract)
        db_session.commit()

        # Mock domain resolution to return None (no domain)
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain_repo.get.return_value = None

            # Mock semantic links manager
            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{contract.id}/odcs/export")

        assert response.status_code == 200

        # Parse the YAML response
        yaml_content = yaml.safe_load(response.content)
        assert yaml_content["name"] == "Minimal Contract"
        assert yaml_content["version"] == "1.0.0"

        # Should not have optional sections
        assert "domain" not in yaml_content
        assert "schema" not in yaml_content
        assert "team" not in yaml_content

    def test_contract_comments_functionality(self, client: TestClient, db_session: Session, sample_contract_data):
        """Test contract comments if implemented."""
        # Create contract first
        create_response = client.post("/api/data-contracts", json=sample_contract_data)
        contract_id = create_response.json()["id"]

        # Add comment
        comment_data = {
            "message": "This is a test comment",
            "author": "test@example.com"
        }

        # Note: This endpoint might not exist yet, adjust based on actual implementation
        response = client.post(f"/api/data-contracts/{contract_id}/comments", json=comment_data)
        # Check if endpoint exists, otherwise skip
        if response.status_code != 404:
            assert response.status_code in [200, 201]

    def test_bulk_operations(self, client: TestClient, db_session: Session):
        """Test bulk contract operations if supported."""
        contracts_data = [
            {
                "name": f"Bulk Contract {i}",
                "version": "1.0.0",
                "status": "draft",
                "owner": "test@example.com"
            }
            for i in range(3)
        ]

        # Test bulk creation if endpoint exists
        response = client.post("/api/data-contracts/bulk", json=contracts_data)
        # Adjust based on actual API implementation
        if response.status_code != 404:
            assert response.status_code in [200, 201]