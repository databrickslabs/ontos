"""Unit tests for EntraIdProvider.

Covers OData escaping, $select projections, Principal normalisation
for users (UPN -> id) and groups (displayName -> id), and test()
happy/error paths against a mocked ``serving_endpoints.http_request``.
"""

import io
import json
from unittest.mock import MagicMock

import pytest

from src.controller.directory_providers import (
    DirectoryError,
    EntraIdProvider,
)
from src.controller.directory_providers.entra_id_provider import (
    _escape_odata,
    _read_response_body,
)
from src.models.directory import PrincipalType


def _stub_response(payload):
    """Build an SDK-shaped HttpRequestResponse-like object."""

    body = json.dumps(payload).encode("utf-8") if not isinstance(payload, str) else payload.encode("utf-8")
    resp = MagicMock()
    resp.contents = io.BytesIO(body)
    return resp


def _ws_returning(payload):
    """Build a fake WorkspaceClient whose http_request returns ``payload``."""

    ws = MagicMock()
    ws.serving_endpoints.http_request.return_value = _stub_response(payload)
    return ws


class TestOdataEscaping:
    def test_doubles_single_quote(self):
        assert _escape_odata("O'Brien") == "O''Brien"

    def test_passthrough_for_safe_string(self):
        assert _escape_odata("alice") == "alice"

    def test_doubles_multiple_quotes(self):
        assert _escape_odata("a'b'c") == "a''b''c"


class TestReadResponseBody:
    def test_handles_bytes(self):
        resp = MagicMock()
        resp.contents = b'{"value": []}'
        assert _read_response_body(resp) == '{"value": []}'

    def test_handles_str(self):
        resp = MagicMock()
        resp.contents = '{"value": []}'
        assert _read_response_body(resp) == '{"value": []}'

    def test_handles_stream(self):
        resp = MagicMock()
        resp.contents = io.BytesIO(b'{"value": []}')
        assert _read_response_body(resp) == '{"value": []}'

    def test_handles_none(self):
        resp = MagicMock()
        resp.contents = None
        assert _read_response_body(resp) == ""


class TestSearchUsers:
    def test_maps_userPrincipalName_to_id(self):
        ws = _ws_returning({
            "value": [
                {"id": "guid-1", "displayName": "Alice", "userPrincipalName": "alice@contoso.com", "mail": "alice@contoso.com"},
            ]
        })
        provider = EntraIdProvider(ws, connection_name="my-graph")
        results = provider.search_users("ali", top=20)
        assert len(results) == 1
        p = results[0]
        assert p.type == PrincipalType.USER
        assert p.id == "alice@contoso.com"   # UPN, not GUID
        assert p.display_name == "Alice"
        # sub_label exists and is non-empty
        assert p.sub_label

    def test_escapes_quote_in_query(self):
        ws = _ws_returning({"value": []})
        provider = EntraIdProvider(ws, connection_name="my-graph")
        provider.search_users("O'Brien", top=20)
        call = ws.serving_endpoints.http_request.call_args
        path = call.kwargs["path"]
        # Doubled quote present, raw single quote not adjacent to "Brien"
        assert "O''Brien" in path
        # Ensure consistency header attached for startswith filters
        assert call.kwargs["headers"] == {"ConsistencyLevel": "eventual"}

    def test_uses_select_projection(self):
        ws = _ws_returning({"value": []})
        provider = EntraIdProvider(ws, connection_name="my-graph")
        provider.search_users("a", top=5)
        path = ws.serving_endpoints.http_request.call_args.kwargs["path"]
        assert "$select=id,displayName,userPrincipalName,mail" in path
        assert "$top=5" in path

    def test_empty_query_short_circuits(self):
        ws = MagicMock()
        provider = EntraIdProvider(ws, connection_name="my-graph")
        assert provider.search_users("", top=20) == []
        ws.serving_endpoints.http_request.assert_not_called()

    def test_falls_back_to_mail_when_no_upn(self):
        ws = _ws_returning({
            "value": [{"id": "guid-2", "displayName": "Bob", "mail": "bob@x"}]
        })
        provider = EntraIdProvider(ws, connection_name="my-graph")
        p = provider.search_users("b", top=20)[0]
        assert p.id == "bob@x"


class TestSearchGroups:
    def test_maps_displayName_to_id(self):
        ws = _ws_returning({
            "value": [
                {"id": "group-guid", "displayName": "Data Producers", "description": "all DPs"},
            ]
        })
        provider = EntraIdProvider(ws, connection_name="my-graph")
        results = provider.search_groups("Data", top=20)
        assert len(results) == 1
        p = results[0]
        assert p.type == PrincipalType.GROUP
        assert p.id == "Data Producers"     # displayName, not GUID
        assert p.display_name == "Data Producers"
        assert p.sub_label == "group-guid"  # GUID exposed in sub_label

    def test_uses_group_select_projection(self):
        ws = _ws_returning({"value": []})
        provider = EntraIdProvider(ws, connection_name="my-graph")
        provider.search_groups("X", top=20)
        path = ws.serving_endpoints.http_request.call_args.kwargs["path"]
        assert "$select=id,displayName,description" in path


class TestTest:
    def test_happy_path(self):
        ws = _ws_returning({"value": [{"id": "guid"}]})
        provider = EntraIdProvider(ws, connection_name="my-graph")
        provider.test()  # no exception
        path = ws.serving_endpoints.http_request.call_args.kwargs["path"]
        assert path.startswith("/v1.0/users")
        assert "$top=1" in path

    def test_raises_on_graph_error_body(self):
        ws = _ws_returning({"error": {"code": "InvalidAuthenticationToken", "message": "Access token is empty."}})
        provider = EntraIdProvider(ws, connection_name="my-graph")
        with pytest.raises(DirectoryError, match="InvalidAuthenticationToken"):
            provider.test()

    def test_raises_on_transport_error(self):
        ws = MagicMock()
        ws.serving_endpoints.http_request.side_effect = RuntimeError("connection refused")
        provider = EntraIdProvider(ws, connection_name="my-graph")
        with pytest.raises(DirectoryError, match="connection refused"):
            provider.test()

    def test_raises_on_non_json_body(self):
        ws = MagicMock()
        ws.serving_endpoints.http_request.return_value = _stub_response("not json at all")
        provider = EntraIdProvider(ws, connection_name="my-graph")
        with pytest.raises(DirectoryError, match="non-JSON"):
            provider.test()

    def test_raises_on_empty_connection_name(self):
        with pytest.raises(DirectoryError):
            EntraIdProvider(MagicMock(), connection_name="")
