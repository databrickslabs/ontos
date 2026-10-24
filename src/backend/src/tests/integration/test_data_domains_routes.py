"""
Integration tests for Data Domains API Routes

Tests end-to-end API functionality including:
- HTTP request/response handling
- Authorization and permissions
- Audit logging
- Database persistence
- Hierarchical relationships
"""
import pytest
import json
import uuid
from fastapi.testclient import TestClient

from src.db_models.data_domains import DataDomain
from src.models.data_domains import DataDomainRead


def seed_domain(db_session, name, parent=None):
    """Store a domain row directly.

    Creating a child through POST binds the parent id as a ``uuid.UUID`` to a
    String column, which SQLite rejects (#1051); the GET routes are what these
    tests exercise.
    """
    domain = DataDomain(
        id=str(uuid.uuid4()), name=name, parent_id=parent.id if parent else None,
        created_by="test@example.com",
    )
    db_session.add(domain)
    db_session.flush()
    return domain


class TestDataDomainsRoutes:
    """Integration test suite for /api/data-domains endpoints"""

    @pytest.fixture
    def sample_domain_data(self):
        """Sample data domain payload for API requests."""
        return {
            "name": "API Test Domain",
            "description": "Test domain via API",
            "tags": None,
            "parent_id": None,
        }

    # =================================================================
    # GET /api/data-domains - List Domains
    # =================================================================

    def test_list_domains_success(self, client, db_session, sample_domain_data):
        """Test GET /api/data-domains returns all domains."""
        # Arrange - Create test domains
        client.post("/api/data-domains", json=sample_domain_data)

        # Act
        response = client.get("/api/data-domains")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_domains_empty(self, client):
        """Test listing domains when none exist."""
        # Act
        response = client.get("/api/data-domains")

        # Assert
        assert response.status_code == 200
        assert response.json() == []

    def test_list_domains_pagination(self, client):
        """Test pagination parameters."""
        # Arrange - Create multiple domains
        for i in range(10):
            client.post("/api/data-domains", json={
                "name": f"Domain {i:02d}",
                "description": f"Domain {i}",
            })

        # Act - Get second page
        response = client.get("/api/data-domains?skip=5&limit=3")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    def test_list_domains_requires_permission(self, client, mock_test_user):
        """Test that listing requires READ_ONLY permission."""
        # Arrange - Remove all permissions
        mock_test_user.groups = []

        # Act
        response = client.get("/api/data-domains")

        # Assert
        assert response.status_code == 403

    # =================================================================
    # POST /api/data-domains - Create Domain
    # =================================================================

    def test_create_domain_success(
        self, client, db_session, sample_domain_data, verify_audit_log
    ):
        """Test POST /api/data-domains creates new domain."""
        # Act
        response = client.post("/api/data-domains", json=sample_domain_data)

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == sample_domain_data["name"]
        assert data["description"] == sample_domain_data["description"]
        assert "id" in data
        assert data["id"] is not None

        # Verify audit log
        verify_audit_log("data-domains", "CREATE", success=True)

    def test_create_domain_minimal_fields(self, client):
        """Test creating domain with only required fields."""
        # Arrange
        minimal_data = {"name": "Minimal Domain"}

        # Act
        response = client.post("/api/data-domains", json=minimal_data)

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Domain"
        assert data["description"] is None

    def test_create_domain_with_parent(self, client, sample_domain_data):
        """Test creating domain with parent relationship."""
        # Arrange - Create parent domain first
        parent_response = client.post("/api/data-domains", json={
            "name": "Parent Domain",
            "description": "Parent",
        })
        parent_id = parent_response.json()["id"]

        # Act - Create child domain
        child_data = sample_domain_data.copy()
        child_data["name"] = "Child Domain"
        child_data["parent_id"] = parent_id
        response = client.post("/api/data-domains", json=child_data)

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["parent_id"] == parent_id
        assert data["parent_name"] == "Parent Domain"

    def test_create_domain_with_nonexistent_parent_fails(
        self, client, sample_domain_data
    ):
        """Test that creating domain with non-existent parent fails."""
        # Arrange
        sample_domain_data["parent_id"] = str(uuid.uuid4())

        # Act
        response = client.post("/api/data-domains", json=sample_domain_data)

        # Assert
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_create_domain_validation_error(self, client):
        """Test that invalid data returns 422 validation error."""
        # Arrange
        invalid_data = {
            "name": "",  # Empty name should fail
        }

        # Act
        response = client.post("/api/data-domains", json=invalid_data)

        # Assert
        assert response.status_code == 422

    def test_create_domain_duplicate_name_fails(self, client, sample_domain_data):
        """Test that duplicate name returns 409 conflict."""
        # Arrange - Create first domain
        client.post("/api/data-domains", json=sample_domain_data)

        # Act - Try to create duplicate
        response = client.post("/api/data-domains", json=sample_domain_data)

        # Assert
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"].lower()

    def test_create_domain_requires_write_permission(
        self, client, mock_test_user, sample_domain_data
    ):
        """Test that creation requires READ_WRITE permission."""
        # Arrange - Remove admin permissions
        mock_test_user.groups = []

        # Act
        response = client.post("/api/data-domains", json=sample_domain_data)

        # Assert
        assert response.status_code == 403

    # =================================================================
    # GET /api/data-domains/{domain_id} - Get Single Domain
    # =================================================================

    def test_get_domain_by_id_success(self, client, sample_domain_data):
        """Test GET /api/data-domains/{id} returns specific domain."""
        # Arrange
        create_response = client.post("/api/data-domains", json=sample_domain_data)
        domain_id = create_response.json()["id"]

        # Act
        response = client.get(f"/api/data-domains/{domain_id}")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == domain_id
        assert data["name"] == sample_domain_data["name"]

    def test_get_domain_by_id_not_found(self, client):
        """Test GET with non-existent ID returns 404."""
        # Act
        fake_uuid = str(uuid.uuid4())
        response = client.get(f"/api/data-domains/{fake_uuid}")

        # Assert
        assert response.status_code == 404

    def test_get_domain_includes_hierarchy_info(self, client, db_session):
        """Test that domain includes parent and children information."""
        # Arrange - Create hierarchy
        parent = seed_domain(db_session, "Parent Domain")
        child = seed_domain(db_session, "Child 1", parent)
        seed_domain(db_session, "Child 2", parent)

        # Act - Get parent domain
        response = client.get(f"/api/data-domains/{parent.id}")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["children_count"] == 2
        assert {c["name"] for c in data["children_info"]} == {"Child 1", "Child 2"}

        child_data = client.get(f"/api/data-domains/{child.id}").json()
        assert child_data["parent_id"] == parent.id
        assert child_data["parent_name"] == "Parent Domain"
        assert child_data["parent_info"]["name"] == "Parent Domain"

    # =================================================================
    # PUT /api/data-domains/{domain_id} - Update Domain
    # =================================================================

    def test_update_domain_success(
        self, client, db_session, sample_domain_data, verify_audit_log
    ):
        """Test PUT /api/data-domains/{id} updates domain."""
        # Arrange - Create domain
        create_response = client.post("/api/data-domains", json=sample_domain_data)
        domain_id = create_response.json()["id"]

        update_data = {
            "name": "Updated Domain Name",
            "description": "Updated description",
        }

        # Act
        response = client.put(f"/api/data-domains/{domain_id}", json=update_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Domain Name"
        assert data["description"] == "Updated description"

        # Verify audit log
        verify_audit_log("data-domains", "UPDATE", success=True)

    def test_update_domain_not_found(self, client):
        """Test updating non-existent domain returns 404."""
        # Arrange
        fake_uuid = str(uuid.uuid4())
        update_data = {"name": "Updated Name"}

        # Act
        response = client.put(f"/api/data-domains/{fake_uuid}", json=update_data)

        # Assert
        assert response.status_code == 404

    def test_update_domain_change_parent(self, client):
        """Test updating domain's parent relationship."""
        # Arrange - Create two potential parents and a child
        parent1_response = client.post("/api/data-domains", json={
            "name": "Parent 1",
        })
        parent1_id = parent1_response.json()["id"]

        parent2_response = client.post("/api/data-domains", json={
            "name": "Parent 2",
        })
        parent2_id = parent2_response.json()["id"]

        child_response = client.post("/api/data-domains", json={
            "name": "Child",
            "parent_id": parent1_id,
        })
        child_id = child_response.json()["id"]

        # Act - Change parent
        update_data = {"parent_id": parent2_id}
        response = client.put(f"/api/data-domains/{child_id}", json=update_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["parent_id"] == parent2_id
        assert data["parent_name"] == "Parent 2"

    def test_update_domain_duplicate_name_fails(self, client):
        """Test that updating to duplicate name fails."""
        # Arrange - Create two domains
        client.post("/api/data-domains", json={"name": "Domain 1"})
        
        domain2_response = client.post("/api/data-domains", json={"name": "Domain 2"})
        domain2_id = domain2_response.json()["id"]

        # Act - Try to rename domain2 to domain1's name
        response = client.put(f"/api/data-domains/{domain2_id}", json={
            "name": "Domain 1"
        })

        # Assert
        assert response.status_code == 409

    def test_update_domain_circular_reference_prevention(self, client):
        """Test that circular parent references are prevented."""
        # Arrange - Create parent and child
        parent_response = client.post("/api/data-domains", json={
            "name": "Parent",
        })
        parent_id = parent_response.json()["id"]

        child_response = client.post("/api/data-domains", json={
            "name": "Child",
            "parent_id": parent_id,
        })
        child_id = child_response.json()["id"]

        # Act - Try to make parent a child of child (circular)
        response = client.put(f"/api/data-domains/{parent_id}", json={
            "parent_id": child_id
        })

        # Assert
        assert response.status_code == 400
        assert "circular" in response.json()["detail"].lower()

    def test_update_domain_requires_write_permission(
        self, client, mock_test_user, sample_domain_data
    ):
        """Test that update requires READ_WRITE permission."""
        # Arrange
        create_response = client.post("/api/data-domains", json=sample_domain_data)
        domain_id = create_response.json()["id"]

        # Remove permissions
        mock_test_user.groups = []

        # Act
        response = client.put(f"/api/data-domains/{domain_id}", json={
            "name": "Updated Name"
        })

        # Assert
        assert response.status_code == 403

    # =================================================================
    # DELETE /api/data-domains/{domain_id} - Delete Domain
    # =================================================================

    def test_delete_domain_success(
        self, client, db_session, sample_domain_data, verify_audit_log
    ):
        """Test DELETE /api/data-domains/{id} removes domain."""
        # Arrange
        create_response = client.post("/api/data-domains", json=sample_domain_data)
        domain_id = create_response.json()["id"]

        # Act
        response = client.delete(f"/api/data-domains/{domain_id}")

        # Assert - the route answers 200 with the deleted domain
        assert response.status_code == 200
        assert response.json()["id"] == domain_id

        # Verify audit log (before the 404 below: an error response rolls back
        # the request session, which in this harness is the test's transaction)
        verify_audit_log("data-domains", "DELETE", success=True)

        # Verify deletion
        get_response = client.get(f"/api/data-domains/{domain_id}")
        assert get_response.status_code == 404

    def test_delete_domain_not_found(self, client):
        """Test deleting non-existent domain returns 404."""
        # Act
        fake_uuid = str(uuid.uuid4())
        response = client.delete(f"/api/data-domains/{fake_uuid}")

        # Assert
        assert response.status_code == 404

    def test_delete_domain_cascades_to_children(self, client, db_session):
        """Deleting a parent also deletes its children (cascade, see #520).

        Deletion is only blocked when the domain or a descendant is an entity's
        primary domain; children alone do not block it.
        """
        # Arrange - Create parent with child
        parent = seed_domain(db_session, "Parent")
        child = seed_domain(db_session, "Child", parent)
        parent_id, child_id = parent.id, child.id

        impact = client.get(f"/api/data-domains/{parent_id}/deletion-impact")
        assert impact.status_code == 200
        assert impact.json()["deletable"] is True

        # Act - Delete parent
        response = client.delete(f"/api/data-domains/{parent_id}")

        # Assert
        assert response.status_code == 200
        remaining = {d["id"] for d in client.get("/api/data-domains").json()}
        assert parent_id not in remaining
        assert child_id not in remaining

    def test_delete_domain_requires_admin_permission(
        self, client, mock_test_user, sample_domain_data
    ):
        """Test that deletion requires ADMIN permission."""
        # Arrange
        create_response = client.post("/api/data-domains", json=sample_domain_data)
        domain_id = create_response.json()["id"]

        # Remove admin permission
        mock_test_user.groups = ["non_admin_group"]

        # Act
        response = client.delete(f"/api/data-domains/{domain_id}")

        # Assert
        assert response.status_code == 403

    # =================================================================
    # Hierarchy - read from GET /api/data-domains and GET /api/data-domains/{id}
    # (the API has no /roots, /hierarchy, /path or /children routes)
    # =================================================================

    def test_get_root_domains(self, client, db_session):
        """Root domains are the listed domains without a parent."""
        # Arrange - Create hierarchy
        parent = seed_domain(db_session, "Parent")
        seed_domain(db_session, "Child", parent)
        seed_domain(db_session, "Another Root")

        # Act
        response = client.get("/api/data-domains")

        # Assert
        assert response.status_code == 200
        roots = {d["name"] for d in response.json() if d["parent_id"] is None}
        assert roots == {"Parent", "Another Root"}

    def test_get_domain_hierarchy(self, client, db_session):
        """The domain list carries the parent links that make up the tree."""
        # Arrange - Create multi-level hierarchy
        root = seed_domain(db_session, "Root")
        child1 = seed_domain(db_session, "Child 1", root)
        seed_domain(db_session, "Grandchild", child1)
        seed_domain(db_session, "Child 2", root)

        # Act
        response = client.get("/api/data-domains")

        # Assert
        assert response.status_code == 200
        by_id = {d["id"]: d for d in response.json()}
        parent_of = {
            d["name"]: by_id[d["parent_id"]]["name"] if d["parent_id"] else None
            for d in by_id.values()
        }
        assert parent_of == {
            "Root": None, "Child 1": "Root", "Child 2": "Root", "Grandchild": "Child 1",
        }
        assert by_id[root.id]["children_count"] == 2

    def test_get_domain_path(self, client, db_session):
        """Following parent_info from a domain gives its full path from the root."""
        # Arrange - Create hierarchy
        root = seed_domain(db_session, "Root")
        child = seed_domain(db_session, "Child", root)
        grandchild = seed_domain(db_session, "Grandchild", child)

        # Act - walk up from the grandchild
        path = []
        current = client.get(f"/api/data-domains/{grandchild.id}").json()
        while True:
            path.insert(0, current["name"])
            if not current["parent_info"]:
                break
            current = client.get(f"/api/data-domains/{current['parent_info']['id']}").json()

        # Assert
        assert path == ["Root", "Child", "Grandchild"]

    def test_get_child_domains(self, client, db_session):
        """children_info lists the direct children only."""
        # Arrange - Create parent with children
        parent = seed_domain(db_session, "Parent")
        child1 = seed_domain(db_session, "Child 1", parent)
        seed_domain(db_session, "Child 2", parent)
        # Create grandchild (should not be included)
        seed_domain(db_session, "Grandchild", child1)

        # Act
        response = client.get(f"/api/data-domains/{parent.id}")

        # Assert
        assert response.status_code == 200
        names = {d["name"] for d in response.json()["children_info"]}
        assert names == {"Child 1", "Child 2"}  # Only direct children

    # =================================================================
    # Error Scenarios
    # =================================================================

    def test_invalid_json_returns_400(self, client):
        """Test that malformed JSON returns 400."""
        # Act
        response = client.post(
            "/api/data-domains",
            data="invalid json{",
            headers={"Content-Type": "application/json"}
        )

        # Assert
        assert response.status_code in [400, 422]

    def test_invalid_uuid_format_returns_422(self, client):
        """Test that invalid UUID format returns 422."""
        # Act
        response = client.get("/api/data-domains/not-a-valid-uuid")

        # Assert
        assert response.status_code == 422
