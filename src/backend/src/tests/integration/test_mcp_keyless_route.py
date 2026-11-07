"""Integration tests for the keyless MCP path on /api/mcp.

Exercises resolve_mcp_principal end-to-end through the JSON-RPC endpoint: an
app-gate-authenticated request (no X-API-Key) with a forwarded user token
resolves to the keyless default token, is scoped by that token, and is audited
under the user that ``current_user.me()`` returns for the token. The forwarded
email header alone is rejected.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.config import Settings, get_settings
from src.common.manager_dependencies import get_audit_manager
from src.controller.audit_manager import AuditManager
from src.db_models.mcp_tokens import MCPTokenDb
from src.db_models.audit_log import AuditLogDb
from src.models.users import UserInfo


FWD_EMAIL_HEADER = "X-Forwarded-Email"
CALLER = "genie@example.com"
# What the Databricks Apps proxy forwards: the user's token and email.
FORWARDED = {"x-forwarded-access-token": "user-token", FWD_EMAIL_HEADER: CALLER}


@pytest.fixture
def verified_caller(client, monkeypatch):
    """``current_user.me()`` for the forwarded token answers CALLER."""
    def _me(obo_client, real_ip=None):
        return UserInfo(email=CALLER, username=CALLER, user="Genie", ip=real_ip,
                        groups=["genie-users"])

    monkeypatch.setattr(app.state.users_manager, "get_current_user", _me)


@pytest.fixture(autouse=True)
def _clean_mcp_state(db_session):
    """Isolate each test.

    The MCP route commits its own DB transaction, which — given the shared
    in-memory SQLite engine — persists rows past the conftest rollback. Clear
    MCP tokens and audit rows before each test so state can't leak between them.
    """
    db_session.query(MCPTokenDb).delete()
    db_session.query(AuditLogDb).delete()
    db_session.commit()
    yield


@pytest.fixture
def mcp_client(client: TestClient, test_settings: Settings, db_session):
    """The shared TestClient with the MCP route's dependencies resolvable.

    MCP routes depend on ``get_settings`` and ``AuditManagerDep``, both normally
    wired at startup (skipped in tests). We provide a real AuditManager backed by
    the test session so audit rows are written and can be asserted on.
    """
    prev_settings = app.dependency_overrides.get(get_settings)
    prev_audit = app.dependency_overrides.get(get_audit_manager)
    audit_manager = AuditManager(settings=test_settings, db_session=db_session)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_audit_manager] = lambda: audit_manager
    try:
        yield client
    finally:
        for dep, prev in ((get_settings, prev_settings), (get_audit_manager, prev_audit)):
            if prev is not None:
                app.dependency_overrides[dep] = prev
            else:
                app.dependency_overrides.pop(dep, None)


@pytest.fixture
def keyless_default_token(db_session: Session):
    """Insert an active keyless-default token scoped to read-only glossary/search."""
    token = MCPTokenDb(
        name="keyless-default",
        token_hash="bcrypt-hash-unused-on-keyless-path",
        scopes=["semantic:read", "search:read"],
        created_by="admin@example.com",
        is_active=True,
        is_keyless_default=True,
    )
    db_session.add(token)
    db_session.commit()
    return token


def _rpc(client: TestClient, method: str, params=None, headers=None, _id=1, path="/api/mcp"):
    body = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post(path, json=body, headers=headers or {})


class TestNativePathAlias:
    """The server is mounted at both /mcp (native) and /api/mcp (legacy alias);
    the two must behave identically."""

    @pytest.mark.parametrize("path", ["/mcp", "/api/mcp"])
    def test_tools_list_identical_on_both_paths(
        self, mcp_client, keyless_default_token, verified_caller, path
    ):
        resp = _rpc(mcp_client, "tools/list", headers=FORWARDED, path=path)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert "error" not in payload, payload
        names = {t["name"] for t in payload["result"]["tools"]}
        assert "global_search" in names  # in scope for the keyless default

    def test_native_path_health(self, mcp_client):
        resp = mcp_client.get("/mcp/health")
        assert resp.status_code == 200, resp.text


class TestKeylessEnabled:
    def test_tools_list_filtered_to_default_scopes(
        self, mcp_client, keyless_default_token, verified_caller
    ):
        resp = _rpc(mcp_client, "tools/list", headers=FORWARDED)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert "error" not in payload, payload
        names = {t["name"] for t in payload["result"]["tools"]}

        # In scope for semantic:read / search:read.
        assert "search_glossary_terms" in names
        assert "global_search" in names
        # Out of scope: SPARQL and any write tool must not be listed.
        assert "execute_sparql_query" not in names
        assert "add_semantic_link" not in names

    def test_out_of_scope_tool_call_rejected(
        self, mcp_client, keyless_default_token, verified_caller
    ):
        resp = _rpc(
            mcp_client,
            "tools/call",
            params={"name": "execute_sparql_query", "arguments": {"sparql": "SELECT * WHERE {?s ?p ?o}"}},
            headers=FORWARDED,
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload.get("error"), payload
        # -32002 == MCP_AUTH_MISSING_SCOPE
        assert payload["error"]["code"] == -32002

    def test_scope_violation_audited_under_forwarded_caller(
        self, mcp_client, keyless_default_token, verified_caller, db_session: Session
    ):
        _rpc(
            mcp_client,
            "tools/call",
            params={"name": "execute_sparql_query", "arguments": {"sparql": "ASK {}"}},
            headers=FORWARDED,
        )
        audit = (
            db_session.query(AuditLogDb)
            .filter_by(feature="mcp", action="SCOPE_VIOLATION", username=CALLER)
            .first()
        )
        assert audit is not None, "keyless scope violation should be attributed to the forwarded caller"

    def test_the_forwarded_email_alone_is_rejected_and_audited(
        self, mcp_client, keyless_default_token, db_session: Session
    ):
        resp = _rpc(mcp_client, "tools/list", headers={FWD_EMAIL_HEADER: CALLER})
        payload = resp.json()
        assert payload["error"]["code"] == -32001, payload
        assert payload["error"]["message"] == "The caller's identity could not be verified."
        audit = (
            db_session.query(AuditLogDb)
            .filter_by(feature="mcp", action="IDENTITY_REJECTED")
            .first()
        )
        assert audit is not None and audit.success is False
        assert audit.details['reason'] == 'forwarded_token_missing'

    def test_a_token_me_rejects_is_refused_and_audited(
        self, mcp_client, keyless_default_token, db_session: Session, monkeypatch
    ):
        def _expired(obo_client, real_ip=None):
            raise RuntimeError("token expired")

        monkeypatch.setattr(app.state.users_manager, "get_current_user", _expired)
        resp = _rpc(mcp_client, "tools/list", headers=FORWARDED)
        payload = resp.json()
        assert payload["error"]["code"] == -32001, payload
        assert "expired" not in payload["error"]["message"]
        audit = (
            db_session.query(AuditLogDb)
            .filter_by(feature="mcp", action="IDENTITY_REJECTED")
            .first()
        )
        assert audit is not None and audit.details['reason'] == 'caller_unresolved'


class TestKeylessDisabled:
    def test_no_key_no_email_rejected_as_anonymous(self, mcp_client, db_session: Session):
        resp = _rpc(mcp_client, "tools/list")
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload.get("error"), payload
        # -32001 == MCP_AUTH_FAILED
        assert payload["error"]["code"] == -32001

        audit = (
            db_session.query(AuditLogDb)
            .filter_by(feature="mcp", action="AUTH_FAILURE", username="anonymous")
            .first()
        )
        assert audit is not None

    def test_email_but_no_active_default_rejected(self, mcp_client, db_session: Session):
        # No keyless_default_token fixture -> no default row exists.
        resp = _rpc(mcp_client, "tools/list", headers={FWD_EMAIL_HEADER: CALLER})
        payload = resp.json()
        assert payload.get("error"), payload
        assert payload["error"]["code"] == -32001


class TestProtocolNegotiation:
    """initialize must echo the client's requested protocolVersion when supported.

    A strict client (e.g. the Databricks AI Gateway) aborts with "unsupported
    protocol version" if the server answers with an older revision than it asked
    for, so the server must not force a single hardcoded version.
    """

    def _initialize(self, client, version):
        return _rpc(
            client,
            "initialize",
            params={
                "protocolVersion": version, "clientInfo": {"name": "test"}, "capabilities": {},
            },
            headers=FORWARDED,
        ).json()

    def test_newer_version_echoed(self, mcp_client, keyless_default_token, verified_caller):
        payload = self._initialize(mcp_client, "2025-06-18")
        assert payload["result"]["protocolVersion"] == "2025-06-18"

    def test_legacy_version_echoed(self, mcp_client, keyless_default_token, verified_caller):
        payload = self._initialize(mcp_client, "2024-11-05")
        assert payload["result"]["protocolVersion"] == "2024-11-05"

    def test_unsupported_version_falls_back_to_latest(
        self, mcp_client, keyless_default_token, verified_caller
    ):
        from src.routes.mcp_routes import MCP_PROTOCOL_VERSION
        payload = self._initialize(mcp_client, "1999-01-01")
        assert payload["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
