"""
E2E API Test Suite - Fixtures and Configuration

Authenticates against a deployed Databricks App using the Databricks CLI
and provides a pre-configured requests.Session for all tests.

Configuration is loaded from config.yaml (defaults) with optional
config.local.yaml overrides, and environment variables take highest priority.
See config.yaml for available settings.

Persona fixtures (admin_api, producer_api, steward_api, consumer_api) are
provided for CUJ tests. Each falls back to the default token when no
persona-specific credentials are configured in config.local.yaml.
Tests decorated with @pytest.mark.requires_persona("X") are automatically
skipped when persona X resolves to the same token as the default session.
"""
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import pytest
import requests
import yaml

# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------
_CONFIG_DIR = Path(__file__).parent


def _load_config() -> dict:
    """Load config.yaml, overlay config.local.yaml, then env vars."""
    cfg_path = _CONFIG_DIR / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Missing config.yaml in {_CONFIG_DIR}. "
            "Copy config.yaml and adjust values for your environment."
        )
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}

    local_path = _CONFIG_DIR / "config.local.yaml"
    if local_path.exists():
        with open(local_path) as f:
            local = yaml.safe_load(f) or {}
        for key, val in local.items():
            if key in ("databricks", "personas", "sheet_reporter") and isinstance(val, dict):
                cfg.setdefault(key, {}).update(val)
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
# Auth helpers
# ---------------------------------------------------------------------------
def _get_token_via_cli(profile: str, host: str) -> str:
    result = subprocess.run(
        ["databricks", "auth", "token", "-p", profile, "--host", host],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"databricks auth token failed: {result.stderr.strip()}")
    try:
        return json.loads(result.stdout)["access_token"]
    except (json.JSONDecodeError, KeyError):
        return result.stdout.strip()


def _get_databricks_token() -> str:
    """Obtain default token — env var first, then CLI."""
    token = os.environ.get("E2E_DATABRICKS_TOKEN")
    if token:
        return token
    return _get_token_via_cli(DATABRICKS_PROFILE, DATABRICKS_HOST)


def _get_persona_token(persona: str) -> Optional[str]:
    """Return a token for a persona, or None if not configured.

    Resolution order: env var E2E_{PERSONA}_TOKEN > config token > config profile.
    Returns None if no persona-specific credentials are found (caller falls back
    to the default session).
    """
    env_key = f"E2E_{persona.upper()}_TOKEN"
    token = os.environ.get(env_key)
    if token:
        return token

    pcfg = _cfg.get("personas", {}).get(persona, {})
    if pcfg.get("token"):
        return pcfg["token"]
    if pcfg.get("profile"):
        try:
            return _get_token_via_cli(
                pcfg["profile"],
                pcfg.get("host", DATABRICKS_HOST),
            )
        except RuntimeError:
            return None
    return None


def _make_api_session(base_url: str, token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    session.base_url = base_url
    return session


# ---------------------------------------------------------------------------
# Session-scoped fixtures — default (admin / single-user)
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
    session = _make_api_session(base_url, auth_token)

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
# Persona fixtures — fall back to default api when not configured
# ---------------------------------------------------------------------------
def _persona_fixture(persona_name: str):
    """Factory that creates a session-scoped persona fixture."""
    @pytest.fixture(scope="session")
    def _fixture(base_url, auth_token):
        token = _get_persona_token(persona_name)
        is_distinct = token is not None
        session = _make_api_session(base_url, token or auth_token)
        session.is_distinct_persona = is_distinct
        session.persona_name = persona_name
        yield session
        session.close()
    _fixture.__name__ = f"{persona_name}_api"
    return _fixture


admin_api = _persona_fixture("admin")
producer_api = _persona_fixture("producer")
steward_api = _persona_fixture("steward")
consumer_api = _persona_fixture("consumer")


# ---------------------------------------------------------------------------
# Hook: skip requires_persona tests when persona == default identity
# ---------------------------------------------------------------------------
def pytest_runtest_setup(item):
    for mark in item.iter_markers("requires_persona"):
        persona = mark.args[0] if mark.args else None
        if not persona:
            continue
        # Check if the persona fixture resolved to a distinct token
        fixture_name = f"{persona}_api"
        if fixture_name in item.fixturenames:
            session_obj = item.session
            # Access via the fixture cache if already resolved
            try:
                cached = item._request.getfixturevalue(fixture_name)
                if not getattr(cached, "is_distinct_persona", False):
                    pytest.skip(
                        f"Skipped: requires a distinct '{persona}' persona token. "
                        f"Set personas.{persona}.token in config.local.yaml."
                    )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Convenience helpers available to every test
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def url(base_url):
    """Build an absolute URL from a path."""
    def _url(path: str) -> str:
        return f"{base_url}{path}"
    return _url


# ---------------------------------------------------------------------------
# Google Sheets reporter
# ---------------------------------------------------------------------------
_SHEET_RESULTS: dict[str, dict] = {}  # test_id -> {status, notes}
_SHEET_CFG = _cfg.get("sheet_reporter", {})


def _extract_test_id(nodeid: str) -> Optional[str]:
    """Pull ONT-CUJ-001 etc. from the test node ID."""
    import re
    m = re.search(r"(ONT-(?:CUJ|NEG|RBAC|FEAT)-\d+)", nodeid, re.IGNORECASE)
    return m.group(1).upper() if m else None


def pytest_runtest_logreport(report):
    if not _SHEET_CFG.get("enabled"):
        return
    if report.when != "call":
        return

    test_id = _extract_test_id(report.nodeid)
    if not test_id:
        return

    if report.passed:
        status, notes = "Pass", ""
    elif report.skipped:
        status, notes = "Blocked", str(report.longrepr[2]) if report.longrepr else "skipped"
    else:
        status, notes = "Fail", str(report.longreprtext)[:500] if hasattr(report, "longreprtext") else "failed"

    _SHEET_RESULTS[test_id] = {"status": status, "notes": notes}


def pytest_sessionfinish(session, exitstatus):
    if not _SHEET_CFG.get("enabled") or not _SHEET_RESULTS:
        return

    try:
        _write_sheet_results()
    except Exception as exc:
        print(f"\n[sheet_reporter] WARNING: could not write results to sheet: {exc}")


def _write_sheet_results():
    import subprocess
    import json as _json

    result = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError("gcloud token unavailable — run `gcloud auth application-default login`")
    token = result.stdout.strip()

    sheet_id = _SHEET_CFG["spreadsheet_id"]
    quota = _SHEET_CFG.get("quota_project", "gcp-dev-field-eng-aiapiquota")

    # Read the sheet to build test_id -> (tab_name, row_index) map
    import urllib.request
    import urllib.error

    def _api(path, method="GET", body=None):
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}{path}"
        data = _json.dumps(body).encode() if body else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "x-goog-user-project": quota,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return _json.loads(r.read())

    # Fetch all tabs to map test IDs to rows
    meta = _api("?fields=sheets.properties")
    tab_map = {}  # test_id -> (tab_title, row_index_0based)

    for sheet_prop in meta["sheets"]:
        title = sheet_prop["properties"]["title"]
        gid = sheet_prop["properties"]["sheetId"]
        # Fetch column A (Test IDs)
        safe_title = title.replace("'", "\\'")
        values_resp = _api(f"/values/'{safe_title}'!A:A")
        rows = values_resp.get("values", [])
        for row_idx, row in enumerate(rows):
            if row and row[0].startswith("ONT-"):
                tab_map[row[0]] = (title, row_idx)

    if not tab_map:
        raise RuntimeError("No ONT-* test IDs found in sheet — is the sheet empty?")

    # Build batch update requests
    # Column J (index 9) = Status, Column K (index 10) = Notes / Defect
    batch_data = []
    for test_id, result_data in _SHEET_RESULTS.items():
        if test_id not in tab_map:
            continue
        tab_title, row_idx = tab_map[test_id]
        safe_title = tab_title.replace("'", "\\'")
        # Status cell (column J)
        batch_data.append({
            "range": f"'{safe_title}'!J{row_idx + 1}",
            "values": [[result_data["status"]]],
        })
        # Notes cell (column K)
        if result_data.get("notes"):
            batch_data.append({
                "range": f"'{safe_title}'!K{row_idx + 1}",
                "values": [[result_data["notes"]]],
            })

    if not batch_data:
        return

    _api(
        "/values:batchUpdate",
        method="POST",
        body={"valueInputOption": "RAW", "data": batch_data},
    )
    print(f"\n[sheet_reporter] Updated {len(_SHEET_RESULTS)} test results in Google Sheet.")
