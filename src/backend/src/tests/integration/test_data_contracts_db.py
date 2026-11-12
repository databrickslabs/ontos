import pytest
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.db_models.data_contracts import (
    DataContractDb,
    DataContractTagDb,
    DataContractRoleDb,
    DataContractServerDb,
    DataContractServerPropertyDb,
    DataContractTeamDb,
    DataContractSupportDb,
    DataContractPricingDb,
    DataContractAuthoritativeDefinitionDb,
    DataContractCustomPropertyDb,
    DataContractSlaPropertyDb,
    SchemaObjectDb,
    SchemaPropertyDb,
    DataQualityCheckDb,
    SchemaObjectAuthoritativeDefinitionDb,
    SchemaObjectCustomPropertyDb,
    SchemaPropertyAuthoritativeDefinitionDb,
    DataContractCommentDb,
)


class TestDataContractDbModels:
    """Database integration tests for DataContract models."""

    def test_create_basic_contract(self, db_session: Session):
        """Test creating a basic data contract."""
        contract = DataContractDb(
            name="Test Contract",
            version="1.0.0",
            status="draft",
            description_usage="Test usage"
        )

        db_session.add(contract)
        db_session.commit()

        # Verify the contract was created
        retrieved = db_session.query(DataContractDb).filter_by(name="Test Contract").first()
        assert retrieved is not None
        assert retrieved.name == "Test Contract"
        assert retrieved.version == "1.0.0"
        assert retrieved.status == "draft"
        assert retrieved.created_at is not None
        assert retrieved.updated_at is not None

    def test_contract_unique_constraint(self, db_session: Session):
        """Test that contracts with same name+version should have unique constraint if implemented."""
        contract1 = DataContractDb(
            name="Duplicate Contract",
            version="1.0.0",
            status="draft"
        )

        contract2 = DataContractDb(
            name="Duplicate Contract",
            version="1.0.0",
            status="active"
        )

        db_session.add(contract1)
        db_session.commit()

        db_session.add(contract2)
        # This should work since we allow duplicates, but if unique constraint exists, it would fail
        try:
            db_session.commit()
            # If no unique constraint, both should exist
            contracts = db_session.query(DataContractDb).filter_by(name="Duplicate Contract").all()
            assert len(contracts) == 2
        except IntegrityError:
            # If unique constraint exists, rollback and verify only one exists
            db_session.rollback()
            contracts = db_session.query(DataContractDb).filter_by(name="Duplicate Contract").all()
            assert len(contracts) == 1

    def test_contract_with_tags(self, db_session: Session):
        """Test contract with tags relationship."""
        contract = DataContractDb(
            name="Tagged Contract",
            version="1.0.0",
            status="draft"
        )
        db_session.add(contract)
        db_session.commit()

        # Add tags
        tag1 = DataContractTagDb(contract_id=contract.id, name="finance")
        tag2 = DataContractTagDb(contract_id=contract.id, name="analytics")

        db_session.add_all([tag1, tag2])
        db_session.commit()

        # Verify tags are associated
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.tags) == 2
        tag_names = [tag.name for tag in retrieved.tags]
        assert "finance" in tag_names
        assert "analytics" in tag_names

    def test_tag_unique_constraint(self, db_session: Session):
        """Test that duplicate tags per contract are prevented."""
        contract = DataContractDb(
            name="Tag Test Contract",
            version="1.0.0",
            status="draft"
        )
        db_session.add(contract)
        db_session.commit()

        # Add first tag
        tag1 = DataContractTagDb(contract_id=contract.id, name="duplicate-tag")
        db_session.add(tag1)
        db_session.commit()

        # Try to add duplicate tag
        tag2 = DataContractTagDb(contract_id=contract.id, name="duplicate-tag")
        db_session.add(tag2)

        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_contract_with_team_members(self, db_session: Session):
        """Test contract with team members."""
        contract = DataContractDb(
            name="Team Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add team members
        member1 = DataContractTeamDb(
            contract_id=contract.id,
            username="alice@example.com",
            role="Data Engineer",
            date_in="2023-01-01"
        )
        member2 = DataContractTeamDb(
            contract_id=contract.id,
            username="bob@example.com",
            role="Data Scientist",
            date_in="2023-02-01",
            date_out="2023-12-31",
            replaced_by_username="charlie@example.com"
        )

        db_session.add_all([member1, member2])
        db_session.commit()

        # Verify team members
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.team) == 2

        alice = next(m for m in retrieved.team if m.username == "alice@example.com")
        assert alice.role == "Data Engineer"
        assert alice.date_out is None

        bob = next(m for m in retrieved.team if m.username == "bob@example.com")
        assert bob.replaced_by_username == "charlie@example.com"

    def test_contract_with_roles(self, db_session: Session):
        """Test contract with access roles."""
        contract = DataContractDb(
            name="Role Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add roles
        role1 = DataContractRoleDb(
            contract_id=contract.id,
            role="data_reader",
            access="read",
            description="Read access to data",
            first_level_approvers="Manager",
            second_level_approvers="Director"
        )
        role2 = DataContractRoleDb(
            contract_id=contract.id,
            role="data_writer",
            access="write",
            first_level_approvers="Senior Manager"
        )

        db_session.add_all([role1, role2])
        db_session.commit()

        # Verify roles
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.roles) == 2

        reader_role = next(r for r in retrieved.roles if r.role == "data_reader")
        assert reader_role.access == "read"
        assert reader_role.description == "Read access to data"

    def test_contract_with_servers(self, db_session: Session):
        """Test contract with server configurations."""
        contract = DataContractDb(
            name="Server Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add server
        server = DataContractServerDb(
            contract_id=contract.id,
            server="production-db",
            type="postgresql",
            description="Production database server",
            environment="production"
        )
        db_session.add(server)
        db_session.commit()

        # Add server properties
        props = [
            DataContractServerPropertyDb(server_id=server.id, key="host", value="db.example.com"),
            DataContractServerPropertyDb(server_id=server.id, key="port", value="5432"),
            DataContractServerPropertyDb(server_id=server.id, key="database", value="production"),
            DataContractServerPropertyDb(server_id=server.id, key="schema", value="public")
        ]
        db_session.add_all(props)
        db_session.commit()

        # Verify server and properties
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.servers) == 1

        server = retrieved.servers[0]
        assert server.server == "production-db"
        assert server.type == "postgresql"
        assert len(server.properties) == 4

        host_prop = next(p for p in server.properties if p.key == "host")
        assert host_prop.value == "db.example.com"

    def test_contract_with_support_channels(self, db_session: Session):
        """Test contract with support channel configurations."""
        contract = DataContractDb(
            name="Support Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add support channels
        channels = [
            DataContractSupportDb(
                contract_id=contract.id,
                channel="#data-support",
                url="https://company.slack.com/channels/data-support",
                tool="slack",
                description="Primary support channel"
            ),
            DataContractSupportDb(
                contract_id=contract.id,
                channel="data-team@company.com",
                url="mailto:data-team@company.com",
                tool="email",
                scope="escalation"
            )
        ]
        db_session.add_all(channels)
        db_session.commit()

        # Verify support channels
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.support) == 2

        slack_channel = next(s for s in retrieved.support if s.tool == "slack")
        assert slack_channel.channel == "#data-support"
        assert slack_channel.description == "Primary support channel"

    def test_contract_with_pricing(self, db_session: Session):
        """Test contract with pricing information."""
        contract = DataContractDb(
            name="Priced Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add pricing
        pricing = DataContractPricingDb(
            contract_id=contract.id,
            price_amount="99.99",
            price_currency="USD",
            price_unit="per_month"
        )
        db_session.add(pricing)
        db_session.commit()

        # Verify pricing
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert retrieved.pricing is not None
        assert retrieved.pricing.price_amount == "99.99"
        assert retrieved.pricing.price_currency == "USD"
        assert retrieved.pricing.price_unit == "per_month"

    def test_contract_with_sla_properties(self, db_session: Session):
        """Test contract with SLA properties."""
        contract = DataContractDb(
            name="SLA Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add SLA properties
        sla_props = [
            DataContractSlaPropertyDb(
                contract_id=contract.id,
                property="availability",
                value="99.9",
                unit="percent",
                element="service"
            ),
            DataContractSlaPropertyDb(
                contract_id=contract.id,
                property="latency",
                value="100",
                value_ext="200",
                unit="ms",
                element="api_response",
                driver="performance"
            )
        ]
        db_session.add_all(sla_props)
        db_session.commit()

        # Verify SLA properties
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.sla_properties) == 2

        availability = next(s for s in retrieved.sla_properties if s.property == "availability")
        assert availability.value == "99.9"
        assert availability.unit == "percent"

        latency = next(s for s in retrieved.sla_properties if s.property == "latency")
        assert latency.value_ext == "200"
        assert latency.driver == "performance"

    def test_contract_with_schema_objects(self, db_session: Session):
        """Test contract with schema objects and properties."""
        contract = DataContractDb(
            name="Schema Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add schema object
        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="users_table",
            logical_type="table",
            physical_name="prod.users",
            business_name="User Data Table",
            physical_type="table",
            description="Contains user information",
            data_granularity_description="One row per user",
            tags='["pii", "customer_data"]'
        )
        db_session.add(schema_obj)
        db_session.commit()

        # Add properties
        properties = [
            SchemaPropertyDb(
                object_id=schema_obj.id,
                name="user_id",
                logical_type="string",
                physical_type="varchar(36)",
                required=True,
                unique=True,
                primary_key_position=1,
                classification="public",
                business_name="User Identifier"
            ),
            SchemaPropertyDb(
                object_id=schema_obj.id,
                name="email",
                logical_type="string",
                physical_type="varchar(255)",
                required=True,
                unique=True,
                classification="pii",
                encrypted_name="email_encrypted",
                critical_data_element=True
            ),
            SchemaPropertyDb(
                object_id=schema_obj.id,
                name="created_at",
                logical_type="timestamp",
                physical_type="timestamp",
                required=True,
                partitioned=True,
                partition_key_position=1,
                classification="public"
            )
        ]
        db_session.add_all(properties)
        db_session.commit()

        # Verify schema and properties
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.schema_objects) == 1

        schema = retrieved.schema_objects[0]
        assert schema.name == "users_table"
        assert schema.business_name == "User Data Table"
        assert len(schema.properties) == 3

        user_id = next(p for p in schema.properties if p.name == "user_id")
        assert user_id.primary_key_position == 1
        assert user_id.required == True

        email = next(p for p in schema.properties if p.name == "email")
        assert email.classification == "pii"
        assert email.encrypted_name == "email_encrypted"
        assert email.critical_data_element == True

    def test_schema_with_quality_checks(self, db_session: Session):
        """Test schema object with quality checks."""
        contract = DataContractDb(
            name="Quality Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="quality_table",
            logical_type="table"
        )
        db_session.add(schema_obj)
        db_session.commit()

        # Add quality checks
        quality_checks = [
            DataQualityCheckDb(
                object_id=schema_obj.id,
                name="null_check",
                rule="nullCheck",
                type="library",
                description="Check for null values",
                dimension="completeness",
                severity="error",
                business_impact="operational",
                schedule="0 2 * * *",
                scheduler="cron"
            ),
            DataQualityCheckDb(
                object_id=schema_obj.id,
                name="range_check",
                type="custom",
                description="Check value range",
                dimension="accuracy",
                severity="warning",
                must_be_gt="0",
                must_be_lt="100"
            )
        ]
        db_session.add_all(quality_checks)
        db_session.commit()

        # Verify quality checks
        retrieved_schema = db_session.query(SchemaObjectDb).filter_by(id=schema_obj.id).first()
        assert len(retrieved_schema.quality_checks) == 2

        null_check = next(q for q in retrieved_schema.quality_checks if q.name == "null_check")
        assert null_check.rule == "nullCheck"
        assert null_check.dimension == "completeness"

        range_check = next(q for q in retrieved_schema.quality_checks if q.name == "range_check")
        assert range_check.must_be_gt == "0"
        assert range_check.must_be_lt == "100"

    def test_schema_with_authoritative_definitions(self, db_session: Session):
        """Test schema object with authoritative definitions."""
        contract = DataContractDb(
            name="Authority Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="authority_table",
            logical_type="table"
        )
        db_session.add(schema_obj)
        db_session.commit()

        # Add authoritative definitions
        auth_defs = [
            SchemaObjectAuthoritativeDefinitionDb(
                schema_object_id=schema_obj.id,
                url="https://catalog.company.com/table/authority_table",
                type="catalog"
            ),
            SchemaObjectAuthoritativeDefinitionDb(
                schema_object_id=schema_obj.id,
                url="https://docs.company.com/schema/authority_table",
                type="documentation"
            )
        ]
        db_session.add_all(auth_defs)
        db_session.commit()

        # Verify authoritative definitions
        retrieved_schema = db_session.query(SchemaObjectDb).filter_by(id=schema_obj.id).first()
        assert len(retrieved_schema.authoritative_definitions) == 2

        catalog_def = next(a for a in retrieved_schema.authoritative_definitions if a.type == "catalog")
        assert "catalog.company.com" in catalog_def.url

    def test_schema_with_custom_properties(self, db_session: Session):
        """Test schema object with custom properties."""
        contract = DataContractDb(
            name="Custom Props Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="custom_table",
            logical_type="table"
        )
        db_session.add(schema_obj)
        db_session.commit()

        # Add custom properties
        custom_props = [
            SchemaObjectCustomPropertyDb(
                schema_object_id=schema_obj.id,
                property="business_key",
                value='["user_id", "timestamp"]'
            ),
            SchemaObjectCustomPropertyDb(
                schema_object_id=schema_obj.id,
                property="data_classification",
                value="sensitive"
            )
        ]
        db_session.add_all(custom_props)
        db_session.commit()

        # Verify custom properties
        retrieved_schema = db_session.query(SchemaObjectDb).filter_by(id=schema_obj.id).first()
        assert len(retrieved_schema.custom_properties) == 2

        business_key = next(p for p in retrieved_schema.custom_properties if p.property == "business_key")
        assert '"user_id"' in business_key.value

    def test_property_with_authoritative_definitions(self, db_session: Session):
        """Test schema property with authoritative definitions."""
        contract = DataContractDb(
            name="Property Authority Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        schema_obj = SchemaObjectDb(
            contract_id=contract.id,
            name="property_authority_table",
            logical_type="table"
        )
        db_session.add(schema_obj)
        db_session.commit()

        property_obj = SchemaPropertyDb(
            object_id=schema_obj.id,
            name="email",
            logical_type="string",
            required=True,
            classification="pii"
        )
        db_session.add(property_obj)
        db_session.commit()

        # Add property-level authoritative definitions
        prop_auth_defs = [
            SchemaPropertyAuthoritativeDefinitionDb(
                property_id=property_obj.id,
                url="http://example.com/business/properties#email",
                type="http://databricks.com/ontology/uc/semanticAssignment"
            ),
            SchemaPropertyAuthoritativeDefinitionDb(
                property_id=property_obj.id,
                url="https://schema.org/email",
                type="http://databricks.com/ontology/uc/semanticAssignment"
            )
        ]
        db_session.add_all(prop_auth_defs)
        db_session.commit()

        # Verify property authoritative definitions
        retrieved_property = db_session.query(SchemaPropertyDb).filter_by(id=property_obj.id).first()
        assert len(retrieved_property.authoritative_definitions) == 2

        business_def = next(a for a in retrieved_property.authoritative_definitions
                          if "business/properties" in a.url)
        assert business_def.url == "http://example.com/business/properties#email"
        assert business_def.type == "http://databricks.com/ontology/uc/semanticAssignment"

        schema_org_def = next(a for a in retrieved_property.authoritative_definitions
                            if "schema.org" in a.url)
        assert schema_org_def.url == "https://schema.org/email"

    def test_contract_with_comments(self, db_session: Session):
        """Test contract with comments."""
        contract = DataContractDb(
            name="Commented Contract",
            version="1.0.0",
            status="draft"
        )
        db_session.add(contract)
        db_session.commit()

        # Add comments
        comments = [
            DataContractCommentDb(
                contract_id=contract.id,
                author="reviewer@example.com",
                message="This needs more details in the description."
            ),
            DataContractCommentDb(
                contract_id=contract.id,
                author="owner@example.com",
                message="Updated the description as requested."
            )
        ]
        db_session.add_all(comments)
        db_session.commit()

        # Verify comments
        retrieved = db_session.query(DataContractDb).filter_by(id=contract.id).first()
        assert len(retrieved.comments) == 2

        first_comment = retrieved.comments[0]
        assert first_comment.author == "reviewer@example.com"
        assert first_comment.created_at is not None

    def test_cascade_delete_contract(self, db_session: Session):
        """Test that deleting a contract cascades to related objects."""
        # Create contract with all relationships
        contract = DataContractDb(
            name="Cascade Test Contract",
            version="1.0.0",
            status="active"
        )
        db_session.add(contract)
        db_session.commit()

        # Add various related objects
        tag = DataContractTagDb(contract_id=contract.id, name="test-tag")
        team = DataContractTeamDb(contract_id=contract.id, username="test@example.com", role="Engineer")
        schema_obj = SchemaObjectDb(contract_id=contract.id, name="test_table", logical_type="table")

        db_session.add_all([tag, team, schema_obj])
        db_session.commit()

        schema_prop = SchemaPropertyDb(object_id=schema_obj.id, name="test_col", logical_type="string")
        db_session.add(schema_prop)
        db_session.commit()

        # Add property authoritative definition
        prop_auth = SchemaPropertyAuthoritativeDefinitionDb(
            property_id=schema_prop.id,
            url="http://example.com/test",
            type="test"
        )
        db_session.add(prop_auth)
        db_session.commit()

        # Verify objects exist
        assert db_session.query(DataContractTagDb).filter_by(contract_id=contract.id).count() == 1
        assert db_session.query(DataContractTeamDb).filter_by(contract_id=contract.id).count() == 1
        assert db_session.query(SchemaObjectDb).filter_by(contract_id=contract.id).count() == 1
        assert db_session.query(SchemaPropertyDb).filter_by(object_id=schema_obj.id).count() == 1
        assert db_session.query(SchemaPropertyAuthoritativeDefinitionDb).filter_by(property_id=schema_prop.id).count() == 1

        # Delete contract
        db_session.delete(contract)
        db_session.commit()

        # Verify cascade delete worked
        assert db_session.query(DataContractTagDb).filter_by(contract_id=contract.id).count() == 0
        assert db_session.query(DataContractTeamDb).filter_by(contract_id=contract.id).count() == 0
        assert db_session.query(SchemaObjectDb).filter_by(contract_id=contract.id).count() == 0
        assert db_session.query(SchemaPropertyDb).filter_by(object_id=schema_obj.id).count() == 0
        assert db_session.query(SchemaPropertyAuthoritativeDefinitionDb).filter_by(property_id=schema_prop.id).count() == 0

    def test_contract_timestamps(self, db_session: Session):
        """Test that timestamps are properly set and updated."""
        contract = DataContractDb(
            name="Timestamp Test",
            version="1.0.0",
            status="draft"
        )
        db_session.add(contract)
        db_session.commit()

        initial_created = contract.created_at
        initial_updated = contract.updated_at

        assert initial_created is not None
        assert initial_updated is not None
        assert initial_created == initial_updated

        # The columns have one second resolution on SQLite: move updated_at
        # back so the next update has to change it.
        earlier = initial_updated - timedelta(minutes=1)
        contract.updated_at = earlier
        db_session.commit()

        # Update the contract
        contract.status = "active"
        db_session.commit()

        # Verify updated_at changed but created_at didn't
        assert contract.created_at == initial_created
        assert contract.updated_at > earlier
