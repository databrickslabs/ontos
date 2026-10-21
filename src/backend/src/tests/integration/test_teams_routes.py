import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestTeamsRoutes:
    """Integration tests for teams API endpoints."""

    @pytest.fixture
    def sample_team_data(self):
        """Sample team data for testing."""
        return {
            "name": "Test Team",
            "description": "A test team for unit testing",
            "domain_id": None
        }

    @pytest.fixture
    def sample_team_member_data(self):
        """Sample team member data for testing."""
        return {
            "member_type": "user",
            "member_identifier": "test.member@example.com",
            "app_role_override": "Data Producer",
        }

    # Team CRUD Tests

    def test_list_teams(self, client: TestClient, db_session: Session):
        """Test getting teams - may have demo data."""
        response = client.get("/api/teams")
        assert response.status_code == 200
        # Response should be a list (may be empty or have demo data)
        assert isinstance(response.json(), list)

    def test_create_team(self, client: TestClient, db_session: Session, sample_team_data):
        """Test creating a basic team."""
        response = client.post("/api/teams", json=sample_team_data)
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "Test Team"
        assert data["description"] == "A test team for unit testing"
        assert "id" in data
        assert "created_at" in data

        # TODO: After audit logging is implemented, uncomment:
        # verify_audit_log(feature="teams", action="CREATE", success=True)

    def test_create_team_duplicate_name(self, client: TestClient, db_session: Session, sample_team_data):
        """Test creating team with duplicate name should fail."""
        # Create first team
        response1 = client.post("/api/teams", json=sample_team_data)
        assert response1.status_code == 201

        # Try to create duplicate
        response2 = client.post("/api/teams", json=sample_team_data)
        assert response2.status_code == 409  # Conflict
        assert "already exists" in response2.json()["detail"].lower() or "duplicate" in response2.json()["detail"].lower()

    def test_create_team_validation_errors(self, client: TestClient):
        """Test team creation with validation errors."""
        # Missing required fields
        invalid_data = {
            "description": "Missing name field"
        }
        response = client.post("/api/teams", json=invalid_data)
        assert response.status_code == 422

    def test_get_teams_with_data(self, client: TestClient, db_session: Session, sample_team_data):
        """Test getting teams when teams exist."""
        # Create a team first
        client.post("/api/teams", json=sample_team_data)

        # Fetch teams
        response = client.get("/api/teams")
        assert response.status_code == 200

        data = response.json()
        # The app's startup also creates the Admin Team.
        test_team = next((team for team in data if team["name"] == "Test Team"), None)
        assert test_team is not None
        assert test_team["description"] == "A test team for unit testing"

    def test_get_teams_pagination(self, client: TestClient, db_session: Session):
        """Test team listing with pagination."""
        # Create multiple teams
        for i in range(5):
            client.post("/api/teams", json={
                "name": f"Team {i}",
                "description": f"Description {i}"
            })

        # The app's startup also creates the Admin Team: 6 teams in all.
        # Test first page
        response = client.get("/api/teams?skip=0&limit=3")
        assert response.status_code == 200
        first_page = [team["name"] for team in response.json()]
        assert len(first_page) == 3

        # Test second page
        response = client.get("/api/teams?skip=3&limit=3")
        assert response.status_code == 200
        second_page = [team["name"] for team in response.json()]
        assert len(second_page) == 3

        # Past the end
        assert client.get("/api/teams?skip=6&limit=3").json() == []

        assert not set(first_page) & set(second_page)
        assert {f"Team {i}" for i in range(5)} <= set(first_page) | set(second_page)

    def test_get_team_by_id(self, client: TestClient, db_session: Session, sample_team_data):
        """Test getting a team by ID."""
        # Create team first
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]

        # Get team
        response = client.get(f"/api/teams/{team_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == team_id
        assert data["name"] == "Test Team"

    def test_get_team_not_found(self, client: TestClient):
        """Test getting non-existent team."""
        response = client.get("/api/teams/non-existent-id")
        assert response.status_code == 404

    def test_update_team(self, client: TestClient, db_session: Session, sample_team_data):
        """Test updating a team."""
        # Create team first
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]

        # Update team
        update_data = {
            "name": "Updated Team",
            "description": "Updated description"
        }
        response = client.put(f"/api/teams/{team_id}", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "Updated Team"
        assert data["description"] == "Updated description"

        # TODO: After audit logging is implemented, uncomment:
        # verify_audit_log(feature="teams", action="UPDATE", success=True)

    def test_update_team_not_found(self, client: TestClient):
        """Test updating non-existent team."""
        update_data = {"name": "New Name"}
        response = client.put("/api/teams/non-existent-id", json=update_data)
        assert response.status_code == 404

    def test_delete_team(self, client: TestClient, db_session: Session, sample_team_data):
        """Test deleting a team."""
        # Create team first
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]

        # Delete team
        response = client.delete(f"/api/teams/{team_id}")
        assert response.status_code == 200

        # Verify it's deleted
        get_response = client.get(f"/api/teams/{team_id}")
        assert get_response.status_code == 404

        # TODO: After audit logging is implemented, uncomment:
        # verify_audit_log(feature="teams", action="DELETE", success=True)

    def test_delete_team_not_found(self, client: TestClient):
        """Test deleting non-existent team."""
        response = client.delete("/api/teams/non-existent-id")
        assert response.status_code == 404

    # Team Summary Tests

    def test_get_teams_summary(self, client: TestClient, db_session: Session, sample_team_data):
        """Test getting teams summary."""
        # Create a team first
        client.post("/api/teams", json=sample_team_data)

        # Get summary
        response = client.get("/api/teams/summary")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        assert "id" in data[0]
        assert "name" in data[0]

    # Team Member Tests

    def test_add_team_member(self, client: TestClient, db_session: Session, sample_team_data, sample_team_member_data):
        """Test adding a member to a team."""
        # Create team first
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]

        # Add member
        response = client.post(f"/api/teams/{team_id}/members", json=sample_team_member_data)
        assert response.status_code == 201

        data = response.json()
        assert data["member_identifier"] == "test.member@example.com"
        assert data["member_type"] == "user"
        assert data["app_role_override"] == "Data Producer"
        assert "id" in data

    def test_add_team_member_duplicate(self, client: TestClient, db_session: Session, sample_team_data, sample_team_member_data):
        """Test adding duplicate member should fail."""
        # Create team first
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]

        # Add member first time
        response1 = client.post(f"/api/teams/{team_id}/members", json=sample_team_member_data)
        assert response1.status_code == 201

        # Try to add same member again
        response2 = client.post(f"/api/teams/{team_id}/members", json=sample_team_member_data)
        assert response2.status_code == 409  # Conflict

    def test_add_team_member_team_not_found(self, client: TestClient, sample_team_member_data):
        """Test adding member to non-existent team."""
        response = client.post("/api/teams/non-existent-id/members", json=sample_team_member_data)
        assert response.status_code == 404

    def test_get_team_members(self, client: TestClient, db_session: Session, sample_team_data, sample_team_member_data):
        """Test getting team members."""
        # Create team and add member
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]
        client.post(f"/api/teams/{team_id}/members", json=sample_team_member_data)

        # Get members
        response = client.get(f"/api/teams/{team_id}/members")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0
        assert data[0]["member_identifier"] == "test.member@example.com"

    def test_update_team_member(self, client: TestClient, db_session: Session, sample_team_data, sample_team_member_data):
        """Test updating a team member."""
        # Create team and add member
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]
        member_response = client.post(f"/api/teams/{team_id}/members", json=sample_team_member_data)
        member_id = member_response.json()["id"]

        # Update member
        update_data = {"app_role_override": "Data Steward"}
        response = client.put(f"/api/teams/{team_id}/members/{member_id}", json=update_data)
        assert response.status_code == 200

        data = response.json()
        assert data["app_role_override"] == "Data Steward"

    def test_update_team_member_not_found(self, client: TestClient, db_session: Session, sample_team_data):
        """Test updating non-existent team member."""
        # Create team
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]

        # Try to update non-existent member
        update_data = {"app_role_override": "Data Steward"}
        response = client.put(f"/api/teams/{team_id}/members/non-existent-id", json=update_data)
        assert response.status_code == 404

    def test_remove_team_member(self, client: TestClient, db_session: Session, sample_team_data, sample_team_member_data):
        """Test removing a member from a team."""
        # Create team and add member
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]
        member_response = client.post(f"/api/teams/{team_id}/members", json=sample_team_member_data)
        member_identifier = sample_team_member_data["member_identifier"]

        # Remove member
        response = client.delete(f"/api/teams/{team_id}/members/{member_identifier}")
        assert response.status_code == 204

        # Verify member is removed
        members_response = client.get(f"/api/teams/{team_id}/members")
        members = members_response.json()
        assert len(members) == 0

    def test_remove_team_member_not_found(self, client: TestClient, db_session: Session, sample_team_data):
        """Test removing non-existent team member."""
        # Create team
        create_response = client.post("/api/teams", json=sample_team_data)
        team_id = create_response.json()["id"]

        # Try to remove non-existent member
        response = client.delete(f"/api/teams/{team_id}/members/non-existent-member")
        assert response.status_code == 404

    # Domain-specific Tests

    def test_get_standalone_teams(self, client: TestClient, db_session: Session):
        """Test getting standalone teams (not assigned to a domain)."""
        # Create standalone team
        client.post("/api/teams", json={
            "name": "Standalone Team",
            "description": "No domain",
            "domain_id": None
        })

        # Get standalone teams
        response = client.get("/api/teams/standalone")
        assert response.status_code == 200

        # The app's startup also creates the (standalone) Admin Team.
        names = [team["name"] for team in response.json()]
        assert "Standalone Team" in names

    def test_get_teams_filtered_by_domain(self, client: TestClient, db_session: Session):
        """Test getting teams filtered by domain ID."""
        # Create team with domain
        domain_id = "test-domain-id"
        client.post("/api/teams", json={
            "name": "Domain Team",
            "description": "Belongs to domain",
            "domain_id": domain_id
        })

        # Create standalone team
        client.post("/api/teams", json={
            "name": "Standalone Team",
            "description": "No domain",
            "domain_id": None
        })

        # Filter by domain
        response = client.get(f"/api/teams?domain_id={domain_id}")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Domain Team"
        assert data[0]["domain_id"] == domain_id
