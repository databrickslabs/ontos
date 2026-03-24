"""
E2E API Test Suite - Fixtures and Configuration

Authenticates against a deployed Databricks App using the Databricks CLI
and provides a pre-configured requests.Session for all tests.

Configuration is loaded from config.yaml (defaults) with optional
config.local.yaml overrides, and environment variables take highest priority.
See config.yaml for available settings.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest
import requests
import yaml

# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------
_CONFIG_DIR = Path(__file__).parent


def _load_config() -> dict:
    """Load config.yaml, overlay config.local.yaml, then env vars."""
    # Defaults
    cfg_path = _CONFIG_DIR / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Missing config.yaml in {_CONFIG_DIR}. "
            "Copy config.yaml and adjust values for your environment."
        )
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}

    # Local overrides (gitignored)
    local_path = _CONFIG_DIR / "config.local.yaml"
    if local_path.exists():
        with open(local_path) as f:
            local = yaml.safe_load(f) or {}
        # Shallow-merge top-level keys, deep-merge 'databricks' section
        for key, val in local.items():
            if key == "databricks" and isinstance(val, dict):
                cfg.setdefault("databricks", {}).update(val)
            else:
                cfg[key] = val

    return cfg


_cfg = _load_config()

E2E_BASE_URL = os.environ.get("E2E_BASE_URL", _cfg.get("base_url", "http://localhost:8000"))
DATABRICKS_HOST = os.environ.get(
    "DATABRICKS_HOST",
    _cfg.get("databricks", {}).get("host", ""),
)
DATABRICKS_PROFILE = os.environ.get(
    "DATABRICKS_PROFILE",
    _cfg.get("databricks", {}).get("profile", "DEFAULT"),
)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def _get_databricks_token() -> str:
    """Obtain a fresh Databricks OAuth token via the CLI."""
    # Allow explicit override for CI / service-principal scenarios
    token = os.environ.get("E2E_DATABRICKS_TOKEN")
    if token:
        return token

    result = subprocess.run(
        [
            "databricks", "auth", "token",
            "-p", DATABRICKS_PROFILE,
            "--host", DATABRICKS_HOST,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(f"databricks auth token failed: {result.stderr.strip()}")

    try:
        data = json.loads(result.stdout)
        return data["access_token"]
    except (json.JSONDecodeError, KeyError):
        # Some CLI versions output just the token
        return result.stdout.strip()


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def base_url() -> str:
    return E2E_BASE_URL.rstrip("/")


@pytest.fixture(scope="session")
def auth_token() -> str:
    return _get_databricks_token()


@pytest.fixture(scope="session")
def api(base_url, auth_token):
    """Pre-authenticated requests.Session pointing at the deployed app."""
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    # Store base_url on the session for convenience
    session.base_url = base_url

    # Fail fast if the app is unreachable (use user/info as canary — lightweight)
    try:
        resp = session.get(f"{base_url}/api/user/info", timeout=15)
    except requests.ConnectionError as exc:
        pytest.fail(f"Cannot reach app at {base_url}: {exc}")

    if resp.status_code == 401:
        pytest.fail("Authentication failed — check your Databricks CLI login")
    if resp.status_code not in (200, 403):
        pytest.fail(
            f"Connectivity check failed: status={resp.status_code} body={resp.text[:300]}"
        )

    yield session
    session.close()


# ---------------------------------------------------------------------------
# Convenience helpers available to every test
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def url(base_url):
    """Build an absolute URL from a path."""
    def _url(path: str) -> str:
        return f"{base_url}{path}"
    return _url
