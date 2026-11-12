from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.common.manager_dependencies import get_audit_manager

# test_settings fixture is not directly used here, but the client fixture uses it.
# from src.common.config import Settings # Not strictly needed for this test


@pytest.fixture(autouse=True)
def _override_audit_manager():
    """Audit manager is wired up at app startup; tests skip startup, so stub it.

    Required for routes that depend on ``AuditManagerDep`` (e.g. PUT /api/settings).
    """
    mock = MagicMock()
    mock.log_action_background = MagicMock()
    app.dependency_overrides[get_audit_manager] = lambda: mock
    yield
    app.dependency_overrides.pop(get_audit_manager, None)


@pytest.fixture(autouse=True)
def _share_settings_instance(test_settings):
    """Point the module-level global settings at ``test_settings``.

    The public ``GET /api/settings/ui-customization`` route reads the global
    ``get_settings()`` instance, while the ``SettingsManager`` in the client
    fixture mutates ``test_settings``. In production these are the same
    object (manager constructed with ``get_settings()``); in tests we wire
    them up here so PUT -> GET round-trips reflect the same instance.
    """
    from src.common import config as _config

    previous = _config._settings
    _config._settings = test_settings
    yield
    _config._settings = previous


def test_get_settings(client: TestClient):
    """Test GET /api/settings endpoint."""
    response = client.get("/api/settings")
    print("/api/settings response text:", response.text)
    assert response.status_code == 200

    response_data = response.json()

    # Check for top-level keys
    assert "current_settings" in response_data
    assert "available_workflows" in response_data
    assert response_data["job_cluster_id"] is None
    assert response_data["enabled_jobs"] == []

    # Check available_workflows (the workflows the app can install)
    workflows = response_data["available_workflows"]
    assert all(w["id"] and w["name"] for w in workflows)
    assert "compliance_checks" in [w["id"] for w in workflows]

    # Check current_settings (based on test_settings fixture and Settings.to_dict())
    current_settings = response_data["current_settings"]
    assert current_settings["job_cluster_id"] is None
    assert current_settings["sync_enabled"] is False
    assert current_settings["sync_repository"] is None
    assert current_settings["enabled_jobs"] == []
    assert current_settings["updated_at"] is None


# ---------------------------------------------------------------------------
# UI branding (issue #240) — public bootstrap + admin write round-trip
# ---------------------------------------------------------------------------


def test_get_ui_customization_includes_branding_fields_unset(client: TestClient):
    """Public bootstrap exposes branding fields as None when unset."""
    response = client.get("/api/settings/ui-customization")
    assert response.status_code == 200
    payload = response.json()
    for key in ("app_display_name", "app_short_name", "favicon_url"):
        assert key in payload, f"missing key '{key}' in bootstrap payload"
        assert payload[key] is None, f"expected '{key}' to be None when unset"


def test_branding_round_trip_set_and_clear(client: TestClient):
    """PUT /api/settings round-trips the branding fields and clears them on null."""
    # Set
    put = client.put(
        "/api/settings",
        json={
            "ui_app_display_name": "Acme Catalog",
            "ui_app_short_name": "ACME",
            "ui_favicon_url": "https://example.com/favicon.svg",
        },
    )
    assert put.status_code == 200, put.text

    boot = client.get("/api/settings/ui-customization").json()
    assert boot["app_display_name"] == "Acme Catalog"
    assert boot["app_short_name"] == "ACME"
    assert boot["favicon_url"] == "https://example.com/favicon.svg"

    # Clear (null + empty string both treated as cleared)
    clear = client.put(
        "/api/settings",
        json={
            "ui_app_display_name": None,
            "ui_app_short_name": "",
            "ui_favicon_url": None,
        },
    )
    assert clear.status_code == 200, clear.text

    boot_cleared = client.get("/api/settings/ui-customization").json()
    assert boot_cleared["app_display_name"] is None
    assert boot_cleared["app_short_name"] is None
    assert boot_cleared["favicon_url"] is None


def test_branding_rejects_unsafe_favicon_url(client: TestClient):
    """Disallowed URL schemes (e.g. javascript:) return 400 and do not persist."""
    response = client.put(
        "/api/settings",
        json={"ui_favicon_url": "javascript:alert(1)"},
    )
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "favicon" in detail.lower() or "http" in detail.lower()

    # Subsequent GET must still show favicon_url as None (no partial persist).
    boot = client.get("/api/settings/ui-customization").json()
    assert boot["favicon_url"] is None


def test_branding_rejects_display_name_too_long(client: TestClient):
    """Display name exceeding the documented max length is rejected."""
    response = client.put(
        "/api/settings",
        json={"ui_app_display_name": "X" * 200},
    )
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "display name" in detail.lower() or "characters" in detail.lower()


def test_ui_customization_extra_branding_defaults(client: TestClient):
    """Tagline, dark logo and theme colors are exposed and unset by default."""
    payload = client.get("/api/settings/ui-customization").json()
    assert payload["app_tagline"] is None
    assert payload["custom_logo_dark_url"] is None
    assert payload["theme"] == {
        "primary": None, "primary_dark": None, "accent": None, "accent_dark": None,
    }


def test_ui_customization_extra_branding_round_trip(client: TestClient):
    """PUT validates/normalizes the new branding keys; GET returns them; null clears."""
    put = client.put(
        "/api/settings",
        json={
            "ui_app_tagline": "  Ontology of Acme ",
            "ui_custom_logo_dark_url": "/branding/acme/logo-dark.svg",
            "ui_theme_primary": "#2563eb",
            "ui_theme_primary_dark": "#93c5fd",
        },
    )
    assert put.status_code == 200, put.text
    boot = client.get("/api/settings/ui-customization").json()
    assert boot["app_tagline"] == "Ontology of Acme"
    assert boot["custom_logo_dark_url"] == "/branding/acme/logo-dark.svg"
    assert boot["theme"]["primary"] == "#2563eb"
    assert boot["theme"]["primary_dark"] == "#93c5fd"
    assert boot["theme"]["accent"] is None

    bad = client.put("/api/settings", json={"ui_theme_accent": "red;}"})
    assert bad.status_code == 400

    clear = client.put(
        "/api/settings",
        json={"ui_app_tagline": None, "ui_theme_primary": "", "ui_custom_logo_dark_url": None},
    )
    assert clear.status_code == 200, clear.text
    boot = client.get("/api/settings/ui-customization").json()
    assert boot["app_tagline"] is None
    assert boot["custom_logo_dark_url"] is None
    assert boot["theme"]["primary"] is None
    assert boot["theme"]["primary_dark"] == "#93c5fd"


@pytest.mark.parametrize(
    "key", ["ui_custom_logo_url", "ui_custom_logo_dark_url", "ui_favicon_url"]
)
@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "data:image/svg+xml,<svg/>", "//evil.example/x.svg",
    "/../etc/x.svg", "/branding/%2e%2e/x.svg", "/a b.svg",
])
def test_branding_images_reject_unsafe_values(client: TestClient, key: str, value: str):
    """Image fields take http(s) URLs or clean root-relative paths, nothing else."""
    response = client.put("/api/settings", json={key: value})
    assert response.status_code == 400
    boot = client.get("/api/settings/ui-customization").json()
    assert boot.get(key.removeprefix("ui_")) != value


def test_ui_customization_ignores_invalid_env_color(client: TestClient, test_settings):
    """A malformed color coming from the environment is dropped, not injected."""
    test_settings.UI_THEME_PRIMARY = "#fff;}body{display:none"
    try:
        payload = client.get("/api/settings/ui-customization").json()
        assert payload["theme"]["primary"] is None
    finally:
        test_settings.UI_THEME_PRIMARY = None


def test_ui_customization_show_powered_by(client: TestClient, test_settings):
    """The powered-by toggle defaults to on, round-trips as a bool and rejects other types."""
    try:
        assert client.get("/api/settings/ui-customization").json()["show_powered_by"] is True
        assert client.get("/api/settings").json()["ui_show_powered_by"] is True

        put = client.put("/api/settings", json={"ui_show_powered_by": False})
        assert put.status_code == 200, put.text
        assert client.get("/api/settings/ui-customization").json()["show_powered_by"] is False
        assert client.get("/api/settings").json()["ui_show_powered_by"] is False

        bad = client.put("/api/settings", json={"ui_show_powered_by": "no"})
        assert bad.status_code == 400
        # null clears the stored override but keeps the value in effect until restart
        clear = client.put("/api/settings", json={"ui_show_powered_by": None})
        assert clear.status_code == 200, clear.text
        assert client.get("/api/settings/ui-customization").json()["show_powered_by"] is False
    finally:
        test_settings.UI_SHOW_POWERED_BY = True


def test_branding_traversal_path_returns_a_coded_error(client: TestClient):
    """A `..` path says so (code + params) instead of "no scheme"."""
    response = client.put("/api/settings", json={"ui_custom_logo_url": "/../x.svg"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "branding_path_traversal"
    assert detail["params"] == {"field": "custom logo URL"}
    assert "no scheme" not in detail["message"]


def test_rejected_branding_save_leaves_earlier_keys_unchanged(client: TestClient):
    """One bad value makes the whole save a no-op."""
    before = client.get("/api/settings/ui-customization").json()
    bad = client.put("/api/settings", json={
        "ui_app_tagline": "Half saved",
        "ui_theme_primary": "#2563eb",
        "ui_favicon_url": "javascript:alert(1)",
    })
    assert bad.status_code == 400
    assert client.get("/api/settings/ui-customization").json() == before


def test_invalid_volume_is_rejected_with_a_code_and_stores_nothing(
    client: TestClient, test_settings
):
    """A volume that can't name a UC volume answers 400 with code + params and changes nothing."""
    response = client.put(
        "/api/settings",
        json={"databricks_volume": "a.b", "databricks_catalog": "other_catalog"},
    )

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "volume_invalid"
    assert detail["params"]["value"] == "a.b"
    assert test_settings.DATABRICKS_VOLUME == "test_volume"
    assert test_settings.DATABRICKS_CATALOG == "test_catalog"


def test_valid_volume_is_saved(client: TestClient, test_settings):
    response = client.put("/api/settings", json={"databricks_volume": "cat.sch.vol"})

    assert response.status_code == 200, response.text
    assert test_settings.DATABRICKS_VOLUME == "cat.sch.vol"
