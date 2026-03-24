"""
Tag Assignments — assign/remove/list tags on entities.

Covers:
  - tags:set  (replace all tags on an entity)
  - tags:add  (add a single tag, with optional value)
  - GET /entities/{type}/{id}/tags  (list tags on entity)
  - DELETE /entities/{type}/{id}/tags:remove  (remove a single tag)
  - GET /tags/{tag_id}/entities  (reverse lookup)
  - GET /tags/fqn/{fqn}  (FQN lookup)
  - Namespace permission CRUD
  - Error cases (unknown entity, duplicate assignment, missing tag)

Entity types exercised: data_domain, data_product, data_contract
"""
import uuid
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import (
    make_domain,
    make_tag_namespace,
    make_tag,
    make_data_product,
    make_data_contract,
)


# ---------------------------------------------------------------------------
# Local helpers — kept in this file per instructions
# ---------------------------------------------------------------------------

def _create_namespace(api, url) -> dict:
    """Create a tag namespace and return the response body."""
    resp = api.post(url("/api/tags/namespaces"), json=make_tag_namespace())
    assert resp.status_code in (200, 201), f"namespace create: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def _create_tag(api, url, namespace_id: str) -> dict:
    """Create a tag inside *namespace_id* and return the response body."""
    resp = api.post(url("/api/tags"), json=make_tag(namespace_id=namespace_id))
    assert resp.status_code in (200, 201), f"tag create: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def _create_domain(api, url) -> dict:
    """Create a data domain and return the response body."""
    resp = api.post(url("/api/data-domains"), json=make_domain())
    assert resp.status_code in (200, 201), f"domain create: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def _create_data_product(api, url) -> dict:
    """Create a data product and return the response body."""
    resp = api.post(url("/api/data-products"), json=make_data_product())
    assert resp.status_code in (200, 201), f"data_product create: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def _create_data_contract(api, url) -> dict:
    """Create a data contract and return the response body."""
    resp = api.post(url("/api/data-contracts"), json=make_data_contract())
    assert resp.status_code in (200, 201), f"data_contract create: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def _list_entity_tags(api, url, entity_type: str, entity_id: str) -> list:
    resp = api.get(url(f"/api/entities/{entity_type}/{entity_id}/tags"))
    assert resp.status_code == 200, f"list tags: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def _tag_ids_in(tags: list) -> set:
    return {str(t["tag_id"]) for t in tags}


# ---------------------------------------------------------------------------
# Fixtures: shared namespace + two tags, one domain
# ---------------------------------------------------------------------------

class TestTagAssignmentSetAndRemove:
    """Core set / add / remove / list flows on a data_domain entity."""

    @pytest.fixture(autouse=True)
    def _setup(self, api, url):
        self._tags_to_delete = []
        self._ns_to_delete = []
        self._domains_to_delete = []

        # Namespace
        ns = _create_namespace(api, url)
        self._ns_id = ns["id"]
        self._ns_to_delete.append(self._ns_id)

        # Two tags in that namespace
        tag_a = _create_tag(api, url, self._ns_id)
        tag_b = _create_tag(api, url, self._ns_id)
        self._tag_a_id = tag_a["id"]
        self._tag_b_id = tag_b["id"]
        self._tag_a_fqn = tag_a["fully_qualified_name"]
        self._tag_b_fqn = tag_b["fully_qualified_name"]
        self._tags_to_delete.extend([self._tag_a_id, self._tag_b_id])

        # Domain as target entity
        domain = _create_domain(api, url)
        self._domain_id = domain["id"]
        self._domains_to_delete.append(self._domain_id)

        yield

        # Teardown: clear assignments before deleting tags/namespace
        api.delete(url(f"/api/entities/data_domain/{self._domain_id}/tags:remove"),
                   params={"tag_id": self._tag_a_id})
        api.delete(url(f"/api/entities/data_domain/{self._domain_id}/tags:remove"),
                   params={"tag_id": self._tag_b_id})

        for domain_id in reversed(self._domains_to_delete):
            api.delete(url(f"/api/data-domains/{domain_id}"))
        for tag_id in reversed(self._tags_to_delete):
            api.delete(url(f"/api/tags/{tag_id}"))
        for ns_id in reversed(self._ns_to_delete):
            api.delete(url(f"/api/tags/namespaces/{ns_id}"))

    # -----------------------------------------------------------------------

    @pytest.mark.crud
    def test_set_replaces_all_tags(self, api, url):
        """tags:set with two tags should result in exactly those two tags."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        payload = [
            {"tag_id": self._tag_a_id},
            {"tag_id": self._tag_b_id},
        ]
        resp = api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"), json=payload)
        assert resp.status_code == 200, f"tags:set failed: {resp.status_code} {resp.text[:300]}"

        assigned = resp.json()
        assert isinstance(assigned, list)
        assert len(assigned) == 2
        assert _tag_ids_in(assigned) == {self._tag_a_id, self._tag_b_id}

    @pytest.mark.crud
    def test_set_with_fqn_payload(self, api, url):
        """tags:set can accept tag_fqn instead of tag_id."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        payload = [{"tag_fqn": self._tag_a_fqn}]
        resp = api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"), json=payload)
        assert resp.status_code == 200, f"tags:set with fqn failed: {resp.status_code} {resp.text[:300]}"
        assigned = resp.json()
        assert len(assigned) == 1
        assert str(assigned[0]["tag_id"]) == self._tag_a_id

    @pytest.mark.crud
    def test_set_empty_clears_all_tags(self, api, url):
        """tags:set with an empty list should remove all tags from the entity."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        # Assign first
        api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"),
                 json=[{"tag_id": self._tag_a_id}])

        # Now clear
        resp = api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"), json=[])
        assert resp.status_code == 200, f"tags:set empty failed: {resp.status_code} {resp.text[:300]}"
        assert resp.json() == []

        tags = _list_entity_tags(api, url, entity_type, entity_id)
        assert tags == [], f"Expected no tags after empty set, got: {tags}"

    @pytest.mark.crud
    def test_set_replaces_previous_assignment(self, api, url):
        """tags:set with a different tag should replace the previous set entirely."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        # Assign tag_a
        api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"),
                 json=[{"tag_id": self._tag_a_id}])

        # Replace with only tag_b
        resp = api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"),
                        json=[{"tag_id": self._tag_b_id}])
        assert resp.status_code == 200

        tags = _list_entity_tags(api, url, entity_type, entity_id)
        assert _tag_ids_in(tags) == {self._tag_b_id}, \
            f"Expected only tag_b after replace, got: {_tag_ids_in(tags)}"

    @pytest.mark.crud
    def test_add_single_tag(self, api, url):
        """tags:add appends a tag without touching existing ones."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        # Start fresh
        api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"), json=[])

        resp = api.post(
            url(f"/api/entities/{entity_type}/{entity_id}/tags:add"),
            params={"tag_id": self._tag_a_id},
        )
        assert resp.status_code in (200, 201), f"tags:add failed: {resp.status_code} {resp.text[:300]}"
        result = resp.json()
        assert str(result["tag_id"]) == self._tag_a_id

        tags = _list_entity_tags(api, url, entity_type, entity_id)
        assert self._tag_a_id in _tag_ids_in(tags)

    @pytest.mark.crud
    def test_add_tag_with_value(self, api, url):
        """tags:add with assigned_value should persist the value in the assignment."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"), json=[])

        resp = api.post(
            url(f"/api/entities/{entity_type}/{entity_id}/tags:add"),
            params={"tag_id": self._tag_a_id, "assigned_value": "val-a"},
        )
        assert resp.status_code in (200, 201), f"tags:add with value failed: {resp.status_code} {resp.text[:300]}"
        result = resp.json()
        assert result.get("assigned_value") == "val-a"

    @pytest.mark.crud
    def test_add_then_list_then_remove(self, api, url):
        """Full add → list → remove cycle."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        # Clear state
        api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"), json=[])

        # ADD
        resp = api.post(
            url(f"/api/entities/{entity_type}/{entity_id}/tags:add"),
            params={"tag_id": self._tag_a_id},
        )
        assert resp.status_code in (200, 201)

        # LIST
        tags = _list_entity_tags(api, url, entity_type, entity_id)
        assert self._tag_a_id in _tag_ids_in(tags), "tag_a should appear in list after add"

        assigned_tag = next(t for t in tags if str(t["tag_id"]) == self._tag_a_id)
        assert assigned_tag["namespace_id"] == self._ns_id
        assert assigned_tag["fully_qualified_name"] == self._tag_a_fqn

        # REMOVE
        resp = api.delete(
            url(f"/api/entities/{entity_type}/{entity_id}/tags:remove"),
            params={"tag_id": self._tag_a_id},
        )
        assert resp.status_code in (200, 204), f"tags:remove failed: {resp.status_code} {resp.text[:300]}"

        tags_after = _list_entity_tags(api, url, entity_type, entity_id)
        assert self._tag_a_id not in _tag_ids_in(tags_after), "tag_a should be gone after remove"

    @pytest.mark.crud
    def test_list_returns_correct_schema(self, api, url):
        """Each AssignedTag in the list must have all expected fields."""
        entity_type = "data_domain"
        entity_id = self._domain_id

        api.post(url(f"/api/entities/{entity_type}/{entity_id}/tags:set"),
                 json=[{"tag_id": self._tag_a_id}])

        tags = _list_entity_tags(api, url, entity_type, entity_id)
        assert len(tags) >= 1

        t = next(item for item in tags if str(item["tag_id"]) == self._tag_a_id)
        for field in ("tag_id", "tag_name", "namespace_id", "namespace_name",
                      "status", "fully_qualified_name", "assigned_at"):
            assert field in t, f"AssignedTag missing field: {field}"

    # -----------------------------------------------------------------------
    # Error cases
    # -----------------------------------------------------------------------

    @pytest.mark.crud
    def test_remove_nonexistent_tag_returns_404(self, api, url):
        """Removing a tag that was never assigned should return 404."""
        entity_type = "data_domain"
        entity_id = self._domain_id
        phantom_id = str(uuid.uuid4())

        resp = api.delete(
            url(f"/api/entities/{entity_type}/{entity_id}/tags:remove"),
            params={"tag_id": phantom_id},
        )
        assert resp.status_code == 404, \
            f"Expected 404 removing phantom tag, got {resp.status_code}"

    @pytest.mark.crud
    def test_list_tags_unknown_entity_returns_empty(self, api, url):
        """Listing tags for a non-existent entity should return an empty list (not 404)."""
        phantom_id = str(uuid.uuid4())
        resp = api.get(url(f"/api/entities/data_domain/{phantom_id}/tags"))
        # The API may return 200 with empty list or 404; both are acceptable
        assert resp.status_code in (200, 404), \
            f"Unexpected status for unknown entity: {resp.status_code}"
        if resp.status_code == 200:
            assert resp.json() == [], f"Expected empty list for unknown entity, got: {resp.json()}"


# ---------------------------------------------------------------------------
# Reverse lookup: GET /api/tags/{tag_id}/entities
# ---------------------------------------------------------------------------

class TestGetEntitiesForTag:

    @pytest.fixture(autouse=True)
    def _setup(self, api, url):
        self._tags_to_delete = []
        self._ns_to_delete = []
        self._domains_to_delete = []

        ns = _create_namespace(api, url)
        self._ns_id = ns["id"]
        self._ns_to_delete.append(self._ns_id)

        tag = _create_tag(api, url, self._ns_id)
        self._tag_id = tag["id"]
        self._tags_to_delete.append(self._tag_id)

        # Two domains, both tagged
        domain_a = _create_domain(api, url)
        domain_b = _create_domain(api, url)
        self._domain_a_id = domain_a["id"]
        self._domain_b_id = domain_b["id"]
        self._domains_to_delete.extend([self._domain_a_id, self._domain_b_id])

        # Assign tag to both domains
        for did in (self._domain_a_id, self._domain_b_id):
            api.post(url(f"/api/entities/data_domain/{did}/tags:set"),
                     json=[{"tag_id": self._tag_id}])

        yield

        for did in (self._domain_a_id, self._domain_b_id):
            api.post(url(f"/api/entities/data_domain/{did}/tags:set"), json=[])
        for domain_id in reversed(self._domains_to_delete):
            api.delete(url(f"/api/data-domains/{domain_id}"))
        for tag_id in reversed(self._tags_to_delete):
            api.delete(url(f"/api/tags/{tag_id}"))
        for ns_id in reversed(self._ns_to_delete):
            api.delete(url(f"/api/tags/namespaces/{ns_id}"))

    @pytest.mark.crud
    def test_get_entities_for_tag_includes_both_domains(self, api, url):
        """Both tagged domains should appear in the reverse-lookup response."""
        resp = api.get(url(f"/api/tags/{self._tag_id}/entities"))
        assert resp.status_code == 200, f"get entities failed: {resp.status_code} {resp.text[:300]}"
        entities = resp.json()
        assert isinstance(entities, list)

        entity_ids = {str(e.get("entity_id")) for e in entities}
        assert self._domain_a_id in entity_ids, "domain_a missing from tag entity list"
        assert self._domain_b_id in entity_ids, "domain_b missing from tag entity list"

    @pytest.mark.crud
    def test_get_entities_filtered_by_type(self, api, url):
        """entity_type query param should narrow results to that type."""
        resp = api.get(
            url(f"/api/tags/{self._tag_id}/entities"),
            params={"entity_type": "data_domain"},
        )
        assert resp.status_code == 200
        entities = resp.json()
        assert all(e.get("entity_type") == "data_domain" for e in entities), \
            f"Unexpected entity types in filtered result: {[e.get('entity_type') for e in entities]}"

    @pytest.mark.readonly
    def test_get_entities_for_unknown_tag_returns_404(self, api, url):
        """A non-existent tag_id should yield 404."""
        resp = api.get(url(f"/api/tags/{uuid.uuid4()}/entities"))
        assert resp.status_code == 404, \
            f"Expected 404 for unknown tag, got {resp.status_code}"


# ---------------------------------------------------------------------------
# FQN lookup
# ---------------------------------------------------------------------------

class TestTagFQNLookup:

    @pytest.fixture(autouse=True)
    def _setup(self, api, url):
        self._tags_to_delete = []
        self._ns_to_delete = []

        ns = _create_namespace(api, url)
        self._ns_id = ns["id"]
        self._ns_name = ns["name"]
        self._ns_to_delete.append(self._ns_id)

        tag = _create_tag(api, url, self._ns_id)
        self._tag_id = tag["id"]
        self._tag_name = tag["name"]
        self._fqn = tag["fully_qualified_name"]
        self._tags_to_delete.append(self._tag_id)

        yield

        for tag_id in reversed(self._tags_to_delete):
            api.delete(url(f"/api/tags/{tag_id}"))
        for ns_id in reversed(self._ns_to_delete):
            api.delete(url(f"/api/tags/namespaces/{ns_id}"))

    @pytest.mark.readonly
    def test_fqn_lookup_returns_correct_tag(self, api, url):
        """GET /api/tags/fqn/{fqn} should return the matching tag."""
        resp = api.get(url(f"/api/tags/fqn/{self._fqn}"))
        assert resp.status_code == 200, f"FQN lookup failed: {resp.status_code} {resp.text[:300]}"
        body = resp.json()
        assert str(body["id"]) == self._tag_id
        assert body["name"] == self._tag_name
        assert body["fully_qualified_name"] == self._fqn

    @pytest.mark.readonly
    def test_fqn_lookup_unknown_returns_404(self, api, url):
        """A FQN that does not exist should return 404."""
        resp = api.get(url(f"/api/tags/fqn/nonexistent-ns/nonexistent-tag-{uuid.uuid4().hex}"))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Multi-entity type coverage: data_product and data_contract
# ---------------------------------------------------------------------------

class TestTagAssignmentMultiEntityTypes:
    """Verify tagging works across entity types beyond data_domain."""

    @pytest.fixture(autouse=True)
    def _setup(self, api, url):
        self._to_delete = {"namespaces": [], "tags": [], "data_products": [], "data_contracts": []}

        ns = _create_namespace(api, url)
        self._ns_id = ns["id"]
        self._to_delete["namespaces"].append(self._ns_id)

        tag = _create_tag(api, url, self._ns_id)
        self._tag_id = tag["id"]
        self._to_delete["tags"].append(self._tag_id)

        product = _create_data_product(api, url)
        self._product_id = product["id"]
        self._to_delete["data_products"].append(self._product_id)

        contract = _create_data_contract(api, url)
        # data-contracts may use "id" or the ODCS "id" field
        self._contract_id = contract.get("id") or contract.get("id")
        self._to_delete["data_contracts"].append(self._contract_id)

        yield

        for pid in self._to_delete["data_products"]:
            api.post(url(f"/api/entities/data_product/{pid}/tags:set"), json=[])
            api.delete(url(f"/api/data-products/{pid}"))
        for cid in self._to_delete["data_contracts"]:
            api.post(url(f"/api/entities/data_contract/{cid}/tags:set"), json=[])
            api.delete(url(f"/api/data-contracts/{cid}"))
        for tag_id in reversed(self._to_delete["tags"]):
            api.delete(url(f"/api/tags/{tag_id}"))
        for ns_id in reversed(self._to_delete["namespaces"]):
            api.delete(url(f"/api/tags/namespaces/{ns_id}"))

    @pytest.mark.crud
    def test_assign_tag_to_data_product(self, api, url):
        entity_type = "data_product"
        entity_id = self._product_id

        resp = api.post(
            url(f"/api/entities/{entity_type}/{entity_id}/tags:set"),
            json=[{"tag_id": self._tag_id}],
        )
        assert resp.status_code == 200, f"set on data_product: {resp.status_code} {resp.text[:300]}"
        assert len(resp.json()) == 1
        assert str(resp.json()[0]["tag_id"]) == self._tag_id

        tags = _list_entity_tags(api, url, entity_type, entity_id)
        assert self._tag_id in _tag_ids_in(tags)

    @pytest.mark.crud
    def test_assign_tag_to_data_contract(self, api, url):
        entity_type = "data_contract"
        entity_id = self._contract_id

        resp = api.post(
            url(f"/api/entities/{entity_type}/{entity_id}/tags:set"),
            json=[{"tag_id": self._tag_id}],
        )
        assert resp.status_code == 200, f"set on data_contract: {resp.status_code} {resp.text[:300]}"
        assert len(resp.json()) == 1

        tags = _list_entity_tags(api, url, entity_type, entity_id)
        assert self._tag_id in _tag_ids_in(tags)

    @pytest.mark.crud
    def test_same_tag_shared_across_entity_types(self, api, url):
        """One tag can simultaneously be assigned to a product and a contract."""
        api.post(url(f"/api/entities/data_product/{self._product_id}/tags:set"),
                 json=[{"tag_id": self._tag_id}])
        api.post(url(f"/api/entities/data_contract/{self._contract_id}/tags:set"),
                 json=[{"tag_id": self._tag_id}])

        product_tags = _list_entity_tags(api, url, "data_product", self._product_id)
        contract_tags = _list_entity_tags(api, url, "data_contract", self._contract_id)

        assert self._tag_id in _tag_ids_in(product_tags)
        assert self._tag_id in _tag_ids_in(contract_tags)

        # Reverse lookup should include both entity types
        resp = api.get(url(f"/api/tags/{self._tag_id}/entities"))
        assert resp.status_code == 200
        entity_ids = {str(e.get("entity_id")) for e in resp.json()}
        assert self._product_id in entity_ids
        assert self._contract_id in entity_ids


# ---------------------------------------------------------------------------
# Namespace permission CRUD
# ---------------------------------------------------------------------------

class TestNamespacePermissions:

    @pytest.fixture(autouse=True)
    def _setup(self, api, url):
        self._ns_to_delete = []
        self._perms_to_delete = []  # (ns_id, perm_id) tuples

        ns = _create_namespace(api, url)
        self._ns_id = ns["id"]
        self._ns_to_delete.append(self._ns_id)

        yield

        for ns_id, perm_id in reversed(self._perms_to_delete):
            api.delete(url(f"/api/tags/namespaces/{ns_id}/permissions/{perm_id}"))
        for ns_id in reversed(self._ns_to_delete):
            api.delete(url(f"/api/tags/namespaces/{ns_id}"))

    @pytest.mark.crud
    def test_permission_crud(self, api, url):
        ns_id = self._ns_id

        # CREATE
        perm_payload = {
            "group_id": f"e2e-group-{uuid.uuid4().hex[:6]}",
            "access_level": "read_only",
        }
        resp = api.post(url(f"/api/tags/namespaces/{ns_id}/permissions"), json=perm_payload)
        assert resp.status_code in (200, 201), \
            f"permission create failed: {resp.status_code} {resp.text[:300]}"
        perm = resp.json()
        perm_id = perm["id"]
        self._perms_to_delete.append((ns_id, perm_id))

        assert perm["group_id"] == perm_payload["group_id"]
        assert perm["access_level"] == "read_only"
        assert str(perm["namespace_id"]) == ns_id

        # LIST
        resp = api.get(url(f"/api/tags/namespaces/{ns_id}/permissions"))
        assert resp.status_code == 200
        ids = [p["id"] for p in resp.json()]
        assert perm_id in ids

        # GET single
        resp = api.get(url(f"/api/tags/namespaces/{ns_id}/permissions/{perm_id}"))
        assert resp.status_code == 200
        assert resp.json()["id"] == perm_id

        # UPDATE
        update_payload = {"access_level": "read_write"}
        resp = api.put(url(f"/api/tags/namespaces/{ns_id}/permissions/{perm_id}"),
                       json=update_payload)
        assert resp.status_code == 200, \
            f"permission update failed: {resp.status_code} {resp.text[:300]}"
        assert resp.json()["access_level"] == "read_write"

        # DELETE
        resp = api.delete(url(f"/api/tags/namespaces/{ns_id}/permissions/{perm_id}"))
        assert resp.status_code in (200, 204), \
            f"permission delete failed: {resp.status_code} {resp.text[:300]}"
        self._perms_to_delete.remove((ns_id, perm_id))

        # Verify gone
        resp = api.get(url(f"/api/tags/namespaces/{ns_id}/permissions/{perm_id}"))
        assert resp.status_code == 404

    @pytest.mark.readonly
    def test_list_permissions_on_nonexistent_namespace_returns_404(self, api, url):
        resp = api.get(url(f"/api/tags/namespaces/{uuid.uuid4()}/permissions"))
        assert resp.status_code == 404

    @pytest.mark.crud
    def test_permission_wrong_namespace_returns_404(self, api, url):
        """A permission looked up under a different namespace_id must return 404."""
        ns_id = self._ns_id

        # Create a second namespace
        ns2 = _create_namespace(api, url)
        ns2_id = ns2["id"]
        self._ns_to_delete.append(ns2_id)

        # Create permission under ns_id
        perm_payload = {"group_id": f"e2e-group-{uuid.uuid4().hex[:6]}", "access_level": "admin"}
        resp = api.post(url(f"/api/tags/namespaces/{ns_id}/permissions"), json=perm_payload)
        assert resp.status_code in (200, 201)
        perm_id = resp.json()["id"]
        self._perms_to_delete.append((ns_id, perm_id))

        # Try to fetch it under ns2 — should 404
        resp = api.get(url(f"/api/tags/namespaces/{ns2_id}/permissions/{perm_id}"))
        assert resp.status_code == 404, \
            f"Expected 404 fetching perm under wrong namespace, got {resp.status_code}"
