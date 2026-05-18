"""Unit tests for the /api/workspace/accessible-workspaces helper.

Covers the descriptor derivation that powers the wizard-driven workspace
dropdown. Endpoint-level integration is exercised via the existing FastAPI
TestClient suite in ``tests/integration/test_workspace_routes.py``; these
tests pin the parsing contract independent of FastAPI/auth wiring.
"""

from src.routes.workspace_routes import _derive_workspace_descriptor_from_host


def test_derive_descriptor_from_https_host():
    """https:// hosts: subdomain becomes id/name/deployment_name."""
    d = _derive_workspace_descriptor_from_host(
        "https://ontos-7474659920352264.aws.databricksapps.com"
    )
    assert d == {
        "id": "ontos-7474659920352264",
        "name": "ontos-7474659920352264",
        "deployment_name": "ontos-7474659920352264",
    }


def test_derive_descriptor_from_http_host():
    """http:// hosts (rare, dev only): same parse path."""
    d = _derive_workspace_descriptor_from_host("http://localhost:8000")
    # localhost:8000 → first split label is "localhost:8000" (no dot)
    assert d["deployment_name"] == "localhost:8000"


def test_derive_descriptor_from_bare_host():
    """Bare host without scheme: still parses."""
    d = _derive_workspace_descriptor_from_host("dbc-12345.cloud.databricks.com")
    assert d == {
        "id": "dbc-12345",
        "name": "dbc-12345",
        "deployment_name": "dbc-12345",
    }


def test_derive_descriptor_strips_trailing_slash():
    """Trailing slashes don't pollute the deployment subdomain."""
    d = _derive_workspace_descriptor_from_host("https://acme.databricks.com/")
    assert d["deployment_name"] == "acme"


def test_derive_descriptor_handles_none():
    """Falsy host: descriptor with sentinel id/name."""
    d = _derive_workspace_descriptor_from_host(None)
    assert d == {"id": "current", "name": "Current workspace", "deployment_name": "current"}


def test_derive_descriptor_handles_empty_string():
    """Empty string: same sentinel as None (caller might surface either)."""
    d = _derive_workspace_descriptor_from_host("")
    assert d["id"] == "current"
