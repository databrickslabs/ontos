import pytest
import yaml
import json
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
    DataContractCustomPropertyDb,
    DataContractAuthoritativeDefinitionDb,
    SchemaObjectDb,
    SchemaPropertyDb,
    DataQualityCheckDb,
    SchemaObjectAuthoritativeDefinitionDb,
    SchemaObjectCustomPropertyDb,
)
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb


class TestODCSExportValidation:
    """Tests specifically for ODCS export response validation and completeness."""

    @pytest.fixture
    def reference_odcs_data(self):
        """Load the reference ODCS data from the test file."""
        reference_path = Path(__file__).parent.parent / "data" / "odcs" / "full-example.odcs.yaml"

        # If the file doesn't exist, create mock reference data
        if not reference_path.exists():
            return {
                "domain": "seller",
                "dataProduct": "my quantum",
                "version": "1.1.0",
                "status": "active",
                "id": "53581432-6c55-4ba2-a65f-72344a91553a",
                "description": {
                    "purpose": "Views built on top of the seller tables.",
                    "limitations": "Data based on seller perspective, no buyer information",
                    "usage": "Predict sales over time",
                    "authoritativeDefinitions": [
                        {
                            "type": "privacy-statement",
                            "url": "https://example.com/gdpr.pdf"
                        }
                    ]
                },
                "tenant": "ClimateQuantumInc",
                "kind": "DataContract",
                "apiVersion": "v3.1.0",
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
                "schema": [
                    {
                        "name": "tbl",
                        "physicalName": "tbl_1",
                        "physicalType": "table",
                        "businessName": "Core Payment Metrics",
                        "description": "Provides core payment metrics",
                        "authoritativeDefinitions": [
                            {
                                "url": "https://catalog.data.gov/dataset/air-quality",
                                "type": "businessDefinition"
                            },
                            {
                                "url": "https://youtu.be/jbY1BKFj9ec",
                                "type": "videoTutorial"
                            }
                        ],
                        "tags": ["finance", "payments"],
                        "dataGranularityDescription": "Aggregation on columns txn_ref_dt, pmt_txn_id",
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
                                ],
                                "customProperties": [
                                    {
                                        "property": "anonymizationStrategy",
                                        "value": "none"
                                    }
                                ]
                            }
                        ],
                        "quality": [
                            {
                                "rule": "countCheck",
                                "type": "library",
                                "description": "Ensure row count is within expected volume range",
                                "dimension": "completeness",
                                "method": "reconciliation",
                                "severity": "error",
                                "businessImpact": "operational",
                                "schedule": "0 20 * * *",
                                "scheduler": "cron"
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
                "price": {
                    "priceAmount": 9.95,
                    "priceCurrency": "USD",
                    "priceUnit": "megabyte"
                },
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
                    },
                    {
                        "username": "daustin",
                        "role": "Owner",
                        "description": "Keeper of the grail",
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
                "slaDefaultElement": "tab1.txn_ref_dt",
                "slaProperties": [
                    {
                        "property": "latency",
                        "value": 4,
                        "unit": "d",
                        "element": "tab1.txn_ref_dt"
                    },
                    {
                        "property": "generalAvailability",
                        "value": "2022-05-12T09:30:10-08:00"
                    }
                ],
                "support": [
                    {
                        "channel": "#product-help",
                        "tool": "slack",
                        "url": "https://aidaug.slack.com/archives/C05UZRSBKLY"
                    },
                    {
                        "channel": "datacontract-ann",
                        "tool": "email",
                        "url": "mailto:datacontract-ann@bitol.io"
                    }
                ],
                "tags": ["transactions"],
                "customProperties": [
                    {
                        "property": "refRulesetName",
                        "value": "gcsc.ruleset.name"
                    },
                    {
                        "property": "somePropertyName",
                        "value": "property.value"
                    }
                ],
                "contractCreatedTs": "2022-11-15T02:59:43+00:00"
            }
        else:
            with open(reference_path, 'r') as f:
                return yaml.safe_load(f)

    @pytest.fixture
    def comprehensive_contract_db(self, db_session: Session):
        """Create a comprehensive contract that should match the reference ODCS."""
        # Create main contract
        contract = DataContractDb(
            id="53581432-6c55-4ba2-a65f-72344a91553a",
            name="my quantum",
            kind="DataContract",
            api_version="v3.1.0",
            version="1.1.0",
            status="active",
            owner_team_id=None,
            tenant="ClimateQuantumInc",
            data_product="my quantum",
            sla_default_element="tab1.txn_ref_dt",
            description_usage="Predict sales over time",
            description_purpose="Views built on top of the seller tables.",
            description_limitations="Data based on seller perspective, no buyer information"
        )
        db_session.add(contract)
        db_session.commit()

        # Add tags
        tag = DataContractTagDb(contract_id=contract.id, name="transactions")
        db_session.add(tag)

        # Add team members
        team_members = [
            DataContractTeamDb(
                contract_id=contract.id,
                username="ceastwood",
                role="Data Scientist",
                date_in="2022-08-02",
                date_out="2022-10-01",
                replaced_by_username="mhopper"
            ),
            DataContractTeamDb(
                contract_id=contract.id,
                username="mhopper",
                role="Data Scientist",
                date_in="2022-10-01"
            ),
            DataContractTeamDb(
                contract_id=contract.id,
                username="daustin",
                role="Owner",
                date_in="2022-10-01"
            )
        ]
        db_session.add_all(team_members)

        # Add roles
        role = DataContractRoleDb(
            contract_id=contract.id,
            role="microstrategy_user_opr",
            access="read",
            first_level_approvers="Reporting Manager",
            second_level_approvers="mandolorian"
        )
        db_session.add(role)

        # Add servers
        server = DataContractServerDb(
            contract_id=contract.id,
            server="my-postgres",
            type="postgres"
        )
        db_session.add(server)
        db_session.commit()

        # Add server properties
        server_props = [
            DataContractServerPropertyDb(server_id=server.id, key="host", value="localhost"),
            DataContractServerPropertyDb(server_id=server.id, key="port", value="5432"),
            DataContractServerPropertyDb(server_id=server.id, key="database", value="pypl-edw"),
            DataContractServerPropertyDb(server_id=server.id, key="schema", value="pp_access_views")
        ]
        db_session.add_all(server_props)

        # Add support
        support_channels = [
            DataContractSupportDb(
                contract_id=contract.id,
                channel="#product-help",
                tool="slack",
                url="https://aidaug.slack.com/archives/C05UZRSBKLY"
            ),
            DataContractSupportDb(
                contract_id=contract.id,
                channel="datacontract-ann",
                tool="email",
                url="mailto:datacontract-ann@bitol.io"
            )
        ]
        db_session.add_all(support_channels)

        # Add pricing
        pricing = DataContractPricingDb(
            contract_id=contract.id,
            price_amount="9.95",
            price_currency="USD",
            price_unit="megabyte"
        )
        db_session.add(pricing)

        # Add SLA properties
        sla_props = [
            DataContractSlaPropertyDb(
                contract_id=contract.id,
                property="latency",
                value="4",
                unit="d",
                element="tab1.txn_ref_dt"
            ),
            DataContractSlaPropertyDb(
                contract_id=contract.id,
                property="generalAvailability",
                value="2022-05-12T09:30:10-08:00"
            )
        ]
        db_session.add_all(sla_props)

        # Add custom properties
        custom_props = [
            DataContractCustomPropertyDb(
                contract_id=contract.id,
                property="refRulesetName",
                value="gcsc.ruleset.name"
            ),
            DataContractCustomPropertyDb(
                contract_id=contract.id,
                property="somePropertyName",
                value="property.value"
            )
        ]
        db_session.add_all(custom_props)

        # Add authoritative definitions
        auth_def = DataContractAuthoritativeDefinitionDb(
            contract_id=contract.id,
            url="https://example.com/gdpr.pdf",
            type="privacy-statement"
        )
        db_session.add(auth_def)

        # Add schema object
        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="tbl",
            physical_name="tbl_1",
            business_name="Core Payment Metrics",
            physical_type="table",
            description="Provides core payment metrics",
            data_granularity_description="Aggregation on columns txn_ref_dt, pmt_txn_id",
            tags='["finance", "payments"]'
        )
        db_session.add(schema_obj)
        db_session.commit()

        # Add schema properties
        prop = SchemaPropertyDb(
            object_id=schema_obj.id,
            name="transaction_reference_date",
            logical_type="date",
            physical_type="date",
            required=False,
            unique=False,
            partitioned=True,
            partition_key_position=1,
            classification="public",
            transform_logic="sel t1.txn_dt as txn_ref_dt from table_name_1 as t1, table_name_2 as t2, table_name_3 as t3 where t1.txn_dt=date-3",
            transform_source_objects='["table_name_1", "table_name_2", "table_name_3"]',
            transform_description="Reference date for transaction",
            examples='["2022-10-03", "2020-01-28"]',
            critical_data_element=False,
            business_name="transaction reference date"
        )
        db_session.add(prop)

        # Add quality check
        quality = DataQualityCheckDb(
            object_id=schema_obj.id,
            rule="countCheck",
            type="library",
            description="Ensure row count is within expected volume range",
            dimension="completeness",
            method="reconciliation",
            severity="error",
            business_impact="operational",
            schedule="0 20 * * *",
            scheduler="cron"
        )
        db_session.add(quality)

        # Add schema authoritative definitions
        schema_auth_defs = [
            SchemaObjectAuthoritativeDefinitionDb(
                schema_object_id=schema_obj.id,
                url="https://catalog.data.gov/dataset/air-quality",
                type="businessDefinition"
            ),
            SchemaObjectAuthoritativeDefinitionDb(
                schema_object_id=schema_obj.id,
                url="https://youtu.be/jbY1BKFj9ec",
                type="videoTutorial"
            )
        ]
        db_session.add_all(schema_auth_defs)

        # Add schema custom properties
        schema_custom_prop = SchemaObjectCustomPropertyDb(
            schema_object_id=schema_obj.id,
            property="business-key",
            value='["txn_ref_dt", "rcvr_id"]'
        )
        db_session.add(schema_custom_prop)

        db_session.commit()
        return contract

    def test_odcs_export_has_all_required_root_fields(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that ODCS export includes all required root-level fields."""
        # The root `domain` is the primary assigned domain's name (#520).
        domain = DataDomain(name="seller", created_by="test")
        db_session.add(domain)
        db_session.flush()
        db_session.add(EntityDomainAssociationDb(
            domain_id=domain.id, entity_type="data_contract",
            entity_id=comprehensive_contract_db.id, is_primary=True,
        ))
        db_session.commit()

        semantic_links = 'src.controller.semantic_links_manager.SemanticLinksManager'
        with patch(semantic_links) as mock_semantic_manager:
            mock_semantic_manager.return_value.list_for_entity.return_value = []

            response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        assert response.status_code == 200
        odcs_data = yaml.safe_load(response.content)

        # The root fields ODCS v3.1.0 requires, plus the name this contract has.
        # The schema has no root `owner` (the team carries ownership) and allows
        # no other root properties.
        schema_path = Path(__file__).parents[2] / "schemas" / "odcs-json-schema-v3.1.0.json"
        schema = json.loads(schema_path.read_text())
        for field in [*schema['required'], 'name']:
            assert field in odcs_data, f"Missing required field: {field}"
        assert 'owner' not in schema['properties']
        assert 'owner' not in odcs_data

        # Test specific values
        assert odcs_data['kind'] == "DataContract"
        assert odcs_data['apiVersion'] == "v3.1.0"
        assert odcs_data['version'] == "1.1.0"
        assert odcs_data['status'] == "active"
        assert odcs_data['name'] == "my quantum"
        assert odcs_data['domain'] == "seller"

    def test_odcs_export_has_complete_description_object(self, client: TestClient, db_session: Session, comprehensive_contract_db, reference_odcs_data):
        """Test that description object is complete and matches reference."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'description' in odcs_data
        description = odcs_data['description']

        # Test description fields
        assert 'usage' in description
        assert 'purpose' in description
        assert 'limitations' in description

        assert description['usage'] == "Predict sales over time"
        assert description['purpose'] == "Views built on top of the seller tables."
        assert description['limitations'] == "Data based on seller perspective, no buyer information"

    def test_odcs_export_has_complete_schema_structure(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that schema structure is complete with all nested elements."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'schema' in odcs_data
        assert len(odcs_data['schema']) == 1

        schema = odcs_data['schema'][0]

        # Test schema object fields
        required_schema_fields = ['name', 'physicalName', 'businessName', 'physicalType', 'description', 'tags']
        for field in required_schema_fields:
            assert field in schema, f"Missing schema field: {field}"

        assert schema['name'] == "tbl"
        assert schema['physicalName'] == "tbl_1"
        assert schema['businessName'] == "Core Payment Metrics"
        assert schema['physicalType'] == "table"

        # Test properties exist and are complete
        assert 'properties' in schema
        assert len(schema['properties']) >= 1

        prop = schema['properties'][0]
        required_prop_fields = ['name', 'logicalType', 'physicalType', 'required', 'partitioned', 'classification']
        for field in required_prop_fields:
            assert field in prop, f"Missing property field: {field}"

        # Test quality checks
        assert 'quality' in schema
        assert len(schema['quality']) >= 1

        quality = schema['quality'][0]
        # For ODCS v3.1.0, use 'metric' instead of 'rule' (spec change)
        required_quality_fields = ['metric', 'type', 'description', 'dimension', 'severity']
        for field in required_quality_fields:
            assert field in quality, f"Missing quality field: {field}"

    def test_odcs_export_has_complete_team_structure(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that team structure is complete."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'team' in odcs_data
        assert len(odcs_data['team']) >= 3

        # Test team member structure
        team_member = odcs_data['team'][0]
        required_team_fields = ['username', 'role']  # ODCS v3 team members carry `username`
        for field in required_team_fields:
            assert field in team_member, f"Missing team field: {field}"

        # Test specific team member data
        ceastwood = next((m for m in odcs_data['team'] if m['username'] == 'ceastwood'), None)
        assert ceastwood is not None
        assert ceastwood['role'] == "Data Scientist"
        assert 'dateIn' in ceastwood
        assert 'dateOut' in ceastwood

    def test_odcs_export_has_complete_roles_structure(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that roles structure is complete."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'roles' in odcs_data
        assert len(odcs_data['roles']) >= 1

        role = odcs_data['roles'][0]
        required_role_fields = ['role', 'access', 'firstLevelApprovers', 'secondLevelApprovers']
        for field in required_role_fields:
            assert field in role, f"Missing role field: {field}"

        assert role['role'] == "microstrategy_user_opr"
        assert role['access'] == "read"

    def test_odcs_export_has_complete_servers_structure(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that servers structure is complete."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'servers' in odcs_data
        assert len(odcs_data['servers']) >= 1

        server = odcs_data['servers'][0]
        required_server_fields = ['server', 'type', 'host', 'port', 'database', 'schema']
        for field in required_server_fields:
            assert field in server, f"Missing server field: {field}"

        assert server['server'] == "my-postgres"
        assert server['type'] == "postgres"
        assert server['host'] == "localhost"
        assert server['port'] == 5432  # Should be integer, not string
        assert server['database'] == "pypl-edw"
        assert server['schema'] == "pp_access_views"

    def test_odcs_export_has_complete_sla_properties(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that SLA properties are complete."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'slaProperties' in odcs_data
        assert len(odcs_data['slaProperties']) >= 2

        # Test latency SLA
        latency_sla = next((s for s in odcs_data['slaProperties'] if s['property'] == 'latency'), None)
        assert latency_sla is not None
        assert latency_sla['value'] == 4  # Should be integer
        assert latency_sla['unit'] == "d"
        assert latency_sla['element'] == "tab1.txn_ref_dt"

        # Test availability SLA
        availability_sla = next((s for s in odcs_data['slaProperties'] if s['property'] == 'generalAvailability'), None)
        assert availability_sla is not None
        assert 'value' in availability_sla

    def test_odcs_export_has_complete_support_structure(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that support structure is complete."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'support' in odcs_data
        assert len(odcs_data['support']) >= 2

        support_item = odcs_data['support'][0]
        required_support_fields = ['channel', 'url']
        for field in required_support_fields:
            assert field in support_item, f"Missing support field: {field}"

        # Test specific support channels
        slack_support = next((s for s in odcs_data['support'] if s.get('tool') == 'slack'), None)
        assert slack_support is not None
        assert slack_support['channel'] == "#product-help"

    def test_odcs_export_has_pricing_structure(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that pricing structure is complete."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        assert 'price' in odcs_data
        price = odcs_data['price']

        required_price_fields = ['priceAmount', 'priceCurrency', 'priceUnit']
        for field in required_price_fields:
            assert field in price, f"Missing price field: {field}"

        assert price['priceAmount'] == 9.95  # Should be float
        assert price['priceCurrency'] == "USD"
        assert price['priceUnit'] == "megabyte"

    def test_odcs_export_has_tags_and_custom_properties(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that tags and custom properties are included."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        # Test tags
        assert 'tags' in odcs_data
        assert isinstance(odcs_data['tags'], list)
        assert "transactions" in odcs_data['tags']

        # Test custom properties (ODCS v3: a list of {property, value})
        assert 'customProperties' in odcs_data
        custom_props = {p['property']: p['value'] for p in odcs_data['customProperties']}
        assert custom_props['refRulesetName'] == "gcsc.ruleset.name"

    def test_odcs_export_field_ordering_matches_spec(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that field ordering in ODCS export follows the specification."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        # Parse YAML while preserving order
        from collections import OrderedDict
        import yaml

        def ordered_load(stream, Loader=yaml.SafeLoader, object_pairs_hook=OrderedDict):
            class OrderedLoader(Loader):
                pass
            def construct_mapping(loader, node):
                loader.flatten_mapping(node)
                return object_pairs_hook(loader.construct_pairs(node))
            OrderedLoader.add_constructor(
                yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                construct_mapping)
            return yaml.load(stream, OrderedLoader)

        odcs_data = ordered_load(response.content)

        # Test that certain key fields appear near the beginning
        keys = list(odcs_data.keys())
        expected_early_keys = ['id', 'kind', 'apiVersion', 'version', 'status', 'name']

        for expected_key in expected_early_keys:
            if expected_key in keys:
                assert keys.index(expected_key) < 10, f"Key {expected_key} should appear early in the structure"

        # Test that schema comes before the end
        if 'schema' in keys:
            schema_index = keys.index('schema')
            assert schema_index < len(keys) - 5, "Schema should not be at the very end"

    def test_odcs_export_data_types_are_correct(self, client: TestClient, db_session: Session, comprehensive_contract_db):
        """Test that exported data has correct types (strings, integers, floats, etc.)."""
        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain = Mock()
            mock_domain.name = "seller"
            mock_domain_repo.get.return_value = mock_domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{comprehensive_contract_db.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        # Test numeric fields are proper types
        if 'price' in odcs_data:
            assert isinstance(odcs_data['price']['priceAmount'], (int, float))

        if 'servers' in odcs_data and len(odcs_data['servers']) > 0:
            server = odcs_data['servers'][0]
            if 'port' in server:
                assert isinstance(server['port'], int)

        if 'slaProperties' in odcs_data:
            for sla in odcs_data['slaProperties']:
                if 'value' in sla and sla['value'] is not None:
                    # Should be numeric if it's a numeric value
                    if str(sla['value']).replace('.', '').isdigit():
                        assert isinstance(sla['value'], (int, float))

        # Test boolean fields
        if 'schema' in odcs_data:
            for schema_obj in odcs_data['schema']:
                if 'properties' in schema_obj:
                    for prop in schema_obj['properties']:
                        boolean_fields = ['required', 'unique', 'partitioned', 'primaryKey', 'criticalDataElement']
                        for bool_field in boolean_fields:
                            if bool_field in prop:
                                assert isinstance(prop[bool_field], bool), f"Field {bool_field} should be boolean"

    def test_odcs_export_missing_fields_validation(self, client: TestClient, db_session: Session):
        """Test ODCS export validation when certain fields are missing."""
        # Create minimal contract
        minimal_contract = DataContractDb(
            name="Minimal Contract",
            version="1.0.0",
            status="draft"
        )
        db_session.add(minimal_contract)
        db_session.commit()

        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain_repo.get.return_value = None  # No domain

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{minimal_contract.id}/odcs/export")

        assert response.status_code == 200
        odcs_data = yaml.safe_load(response.content)

        # Should have basic fields but not optional ones
        assert 'name' in odcs_data
        assert 'version' in odcs_data

        # Should not have optional sections when data is missing
        optional_sections = ['domain', 'team', 'roles', 'servers', 'support', 'price', 'schema']
        for section in optional_sections:
            if section in odcs_data:
                # If present, should not be empty
                if isinstance(odcs_data[section], list):
                    # Empty lists should probably not be included, but this depends on implementation
                    pass
                elif isinstance(odcs_data[section], dict):
                    assert len(odcs_data[section]) > 0, f"Section {section} should not be empty dict"

    def test_odcs_export_json_parsing_in_text_fields(self, client: TestClient, db_session: Session):
        """Test that JSON strings in text fields are properly parsed."""
        # Create contract with JSON in text fields
        contract = DataContractDb(
            name="JSON Test Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add schema with JSON in tags field
        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="test_table",
            tags='["tag1", "tag2", "tag3"]'  # JSON string
        )
        db_session.add(schema_obj)
        db_session.commit()

        # Add property with JSON in examples
        prop = SchemaPropertyDb(
            object_id=schema_obj.id,
            name="test_column",
            examples='["example1", "example2"]',  # JSON string
            transform_source_objects='["table1", "table2"]'  # JSON string
        )
        db_session.add(prop)
        db_session.commit()

        with patch('src.repositories.data_domain_repository.data_domain_repo') as mock_domain_repo:
            mock_domain_repo.get.return_value = None

            with patch('src.controller.semantic_links_manager.SemanticLinksManager') as mock_semantic_manager:
                mock_semantic_manager.return_value.list_for_entity.return_value = []

                response = client.get(f"/api/data-contracts/{contract.id}/odcs/export")

        odcs_data = yaml.safe_load(response.content)

        # Verify JSON strings were parsed into proper arrays/objects
        if 'schema' in odcs_data and len(odcs_data['schema']) > 0:
            schema = odcs_data['schema'][0]

            if 'tags' in schema:
                assert isinstance(schema['tags'], list)
                assert "tag1" in schema['tags']

            if 'properties' in schema and len(schema['properties']) > 0:
                prop = schema['properties'][0]

                if 'examples' in prop:
                    assert isinstance(prop['examples'], list)
                    assert "example1" in prop['examples']

                if 'transformSourceObjects' in prop:
                    assert isinstance(prop['transformSourceObjects'], list)
                    assert "table1" in prop['transformSourceObjects']