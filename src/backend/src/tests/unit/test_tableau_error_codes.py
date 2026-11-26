"""Tableau errors reach clients as codes, never as raw Tableau or transport text (#1328 review 2)."""
import json
from pathlib import Path

import pytest
from databricks.sdk.errors import NotFound
from unittest.mock import MagicMock

from src.connectors import tableau_client
from src.connectors.base import ConnectorAuthenticationError, ConnectorConnectionError
from src.connectors.tableau import TableauConnector, TableauConnectorConfig
from src.connectors.tableau_client import (
    REASON_AUTH_FAILED,
    REASON_FORBIDDEN,
    REASON_NOT_FOUND,
    REASON_SERVER_ERROR,
    REASON_UNREACHABLE,
    PatAuth,
    TableauAPIError,
    TableauClient,
)

SECRET_VALUE = "s3cret-value-do-not-leak"
SERVER = "https://10xx.online.tableau.com"
LOCALES = Path(__file__).resolve().parents[4] / "frontend" / "src" / "i18n" / "locales"

# Every code the Tableau connector can send to a client; each needs a translation in all locales
CLIENT_CODES = [
    "tableau_unreachable", "tableau_auth_failed", "tableau_forbidden", "tableau_not_found",
    "tableau_server_error", "tableau_invalid_server_url", "tableau_blocked_server_address",
    "tableau_redirect_refused", "tableau_metadata_unavailable", "tableau_render_failed",
    "tableau_secret_unavailable", "tableau_not_configured", "tableau_invalid_secret_name",
    "connection_error", "import_failed", "connection_test_failed",
]


class _Resp:
    def __init__(self, status, body=None, text="<html>proxy page with internal host 10.1.2.3</html>"):
        self.status_code = status
        self._body = body
        self.text = text
        self.headers = {}

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class _Http:
    def __init__(self, response):
        self.response = response

    def request(self, method, url, **kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.parametrize("status,reason", [
    (401, REASON_AUTH_FAILED), (403, REASON_FORBIDDEN), (404, REASON_NOT_FOUND), (500, REASON_SERVER_ERROR),
    (503, REASON_SERVER_ERROR),
])
def test_http_status_maps_to_reason_and_non_json_body_stays_out_of_the_reason(status, reason):
    client = TableauClient(SERVER, "", PatAuth("ontos", SECRET_VALUE), api_version="3.30", http=_Http(_Resp(status)))
    with pytest.raises(TableauAPIError) as info:
        client.get_json("/projects")
    assert info.value.reason == reason
    assert "10.1.2.3" not in (info.value.reason or "")


def test_transport_failure_is_unreachable_and_keeps_details_in_the_message_only():
    import requests
    client = TableauClient(SERVER, "", PatAuth("ontos", SECRET_VALUE), api_version="3.30",
                           http=_Http(requests.ConnectionError("tls handshake to 10.1.2.3 failed")))
    with pytest.raises(TableauAPIError) as info:
        client.server_info()
    assert info.value.reason == REASON_UNREACHABLE
    assert "10.1.2.3" in str(info.value)  # for the server log


class _FailingClient:
    server_url = SERVER

    def __init__(self, exc):
        self._exc = exc

    @property
    def identity(self):
        return "pat:ontos"

    def server_info(self):
        raise self._exc


def test_health_check_error_is_a_code_not_raw_text():
    connector = TableauConnector(TableauConnectorConfig(server_url=SERVER, pat_name="x", secret_name="main.ops.s"),
                                 client=_FailingClient(TableauAPIError("sign-in leaked s3cret", reason=REASON_AUTH_FAILED)))
    result = connector.health_check()
    assert result["healthy"] is False
    assert result["error"] == "tableau_auth_failed"
    assert "s3cret" not in json.dumps(result)


def test_health_check_metadata_warning_has_no_exception_text():
    class Client(_FailingClient):
        def server_info(self):
            return {"productVersion": {"value": "2025.1"}, "restApiVersion": "3.26"}

        def session(self):
            return type("S", (), {"user_id": "u1"})()

        def get_json(self, path):
            raise TableauAPIError("role lookup leaked s3cret", reason=REASON_FORBIDDEN)

        def graphql(self, query):
            raise TableauAPIError("metadata leaked s3cret", reason=REASON_SERVER_ERROR)

    connector = TableauConnector(TableauConnectorConfig(server_url=SERVER, pat_name="x", secret_name="main.ops.s"),
                                 client=Client(None))
    result = connector.health_check()
    assert result["healthy"] is True
    assert "s3cret" not in json.dumps(result)
    assert result["metadata_api"] is False


def test_secret_read_failure_is_coded_and_does_not_echo_the_sdk_message():
    ws = MagicMock()
    ws.secrets_uc.get_secret.side_effect = NotFound("secret main.ops.s leaked s3cret")
    connector = TableauConnector(TableauConnectorConfig(server_url=SERVER, pat_name="x",
                                                        secret_name="main.ops.s", workspace_client=ws))
    with pytest.raises(ConnectorAuthenticationError) as info:
        connector._read_secret()
    assert info.value.code == "tableau_secret_unavailable"


def test_translated_api_error_keeps_the_reason_as_code():
    connector = TableauConnector(TableauConnectorConfig(server_url=SERVER, pat_name="x", secret_name="main.ops.s"))
    error = connector._translate(TableauAPIError("sign-in failed: body with s3cret", 401, reason=REASON_AUTH_FAILED))
    assert isinstance(error, ConnectorAuthenticationError)
    assert error.code == "tableau_auth_failed"


def test_refused_server_url_is_coded(monkeypatch):
    connector = TableauConnector(TableauConnectorConfig(server_url="http://tableau.example.com", pat_name="x",
                                                        secret_name="main.ops.s"))
    with pytest.raises(ConnectorConnectionError) as info:
        connector._ensure_client()
    assert info.value.code == "tableau_invalid_server_url"


def test_snapshot_error_is_a_code_not_the_raw_message():
    class Client:
        server_url = SERVER

        def get_bytes(self, path, params=None):
            raise TableauAPIError("render failed with s3cret in body", 500, reason=REASON_SERVER_ERROR)

    connector = TableauConnector(TableauConnectorConfig(server_url=SERVER, pat_name="x", secret_name="main.ops.s"),
                                 client=Client())
    snapshot = connector.capture_snapshot("p~p1.wb~wb1.v~v1")
    assert snapshot is not None
    assert snapshot.error == "tableau_render_failed"
    assert "s3cret" not in (snapshot.error or "")


def test_validate_asset_exists_returns_a_code(monkeypatch):
    connector = TableauConnector(TableauConnectorConfig(server_url=SERVER, pat_name="x", secret_name="main.ops.s"))

    def boom(identifier):
        raise ConnectorConnectionError("raw s3cret text", connector_type="tableau", code="tableau_unreachable")

    monkeypatch.setattr(connector, "get_asset_metadata", boom)
    result = connector.validate_asset_exists("p~p1")
    assert result.message == "tableau_unreachable"


@pytest.mark.parametrize("lang", ["en", "de", "es", "fr", "it", "ja", "nl", "pt"])
def test_every_client_code_is_translated(lang):
    keys = json.loads((LOCALES / lang / "settings.json").read_text(encoding="utf-8"))["connectors"]["errorCodes"]
    missing = [code for code in CLIENT_CODES if not keys.get(code)]
    assert missing == []


def test_reason_constants_are_module_level():
    assert tableau_client.REASON_UNREACHABLE == "unreachable"
