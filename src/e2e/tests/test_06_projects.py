"""Projects — full CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_project, mutate_project, make_team


class TestProjectsCRUD:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for project_id in reversed(self._to_delete):
            api.delete(url(f"/api/projects/{project_id}"))

    @pytest.mark.readonly
    def test_list_projects(self, api, url):
        resp = api.get(url("/api/projects"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_projects_summary(self, api, url):
        resp = api.get(url("/api/projects/summary"))
        assert resp.status_code == 200

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_project()

        # CREATE
        resp = api.post(url("/api/projects"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        project_id = created["id"]
        self._to_delete.append(project_id)

        assert_fields_match(payload, created, ignore={"team_ids"}, context="after CREATE")

        # READ
        resp = api.get(url(f"/api/projects/{project_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(payload, fetched, ignore={"team_ids"}, context="after GET")

        # UPDATE
        updated_payload = mutate_project(payload)
        resp = api.put(url(f"/api/projects/{project_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE response")

        # READ after update
        resp = api.get(url(f"/api/projects/{project_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(updated_payload, re_fetched, context="after UPDATE GET")

        # DELETE
        resp = api.delete(url(f"/api/projects/{project_id}"))
        assert resp.status_code in (200, 204)
        self._to_delete.remove(project_id)

        resp = api.get(url(f"/api/projects/{project_id}"))
        assert resp.status_code == 404

    @pytest.mark.crud
    def test_assign_and_remove_team_from_project(self, api, url):
        """Create team + project, assign team to project, verify listing, then remove."""
        # Create a team
        team_payload = make_team()
        resp = api.post(url("/api/teams"), json=team_payload)
        assert resp.status_code in (200, 201), f"Create team failed: {resp.status_code} {resp.text[:300]}"
        team_id = resp.json()["id"]

        # Create a project
        project_payload = make_project()
        resp = api.post(url("/api/projects"), json=project_payload)
        assert resp.status_code in (200, 201), f"Create project failed: {resp.status_code} {resp.text[:300]}"
        project_id = resp.json()["id"]
        self._to_delete.append(project_id)

        try:
            # Assign team to project
            resp = api.post(url(f"/api/projects/{project_id}/teams"), json={"team_id": team_id})
            assert resp.status_code in (200, 201), \
                f"Assign team failed: {resp.status_code} {resp.text[:300]}"

            # Verify team appears in project teams list
            resp = api.get(url(f"/api/projects/{project_id}/teams"))
            assert resp.status_code == 200, f"List project teams failed: {resp.status_code} {resp.text[:300]}"
            teams = resp.json()
            assert isinstance(teams, list)
            assert any(t.get("id") == team_id for t in teams), \
                "Assigned team not found in project teams listing"

            # Remove team from project
            resp = api.delete(url(f"/api/projects/{project_id}/teams/{team_id}"))
            assert resp.status_code in (200, 204), \
                f"Remove team failed: {resp.status_code} {resp.text[:300]}"

            # Verify removed
            resp = api.get(url(f"/api/projects/{project_id}/teams"))
            assert resp.status_code == 200
            teams = resp.json()
            assert isinstance(teams, list)
            assert not any(t.get("id") == team_id for t in teams), \
                "Team still listed after removal from project"
        finally:
            api.delete(url(f"/api/teams/{team_id}"))

    @pytest.mark.crud
    def test_list_project_teams(self, api, url):
        """Create a project and GET /api/projects/{id}/teams — 200 and list."""
        project_payload = make_project()
        resp = api.post(url("/api/projects"), json=project_payload)
        assert resp.status_code in (200, 201), f"Create project failed: {resp.status_code} {resp.text[:300]}"
        project_id = resp.json()["id"]
        self._to_delete.append(project_id)

        resp = api.get(url(f"/api/projects/{project_id}/teams"))
        assert resp.status_code == 200, f"List project teams failed: {resp.status_code} {resp.text[:300]}"
        body = resp.json()
        assert isinstance(body, list)
