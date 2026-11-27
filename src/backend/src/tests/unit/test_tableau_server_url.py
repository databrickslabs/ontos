"""Tableau server URLs: https only, public addresses only, no redirects (#1328 review 2)."""
import pytest

from src.connectors import tableau_client
from src.connectors.tableau_client import (
    REASON_BLOCKED_ADDRESS,
    REASON_INVALID_URL,
    REASON_REDIRECT,
    PatAuth,
    TableauAPIError,
    TableauClient,
    clear_session_cache,
    validate_server_url,
)

PUBLIC = "https://10xx.online.tableau.com"


def _resolver(*addresses):
    return lambda host, port: list(addresses)


def test_public_https_host_is_accepted():
    assert validate_server_url(PUBLIC, resolve=_resolver("52.1.2.3")) == PUBLIC


@pytest.mark.parametrize("url", [
    "http://10xx.online.tableau.com",
    "ftp://10xx.online.tableau.com",
    "https://user:pass@10xx.online.tableau.com",
    "https://",
    "",
])
def test_non_https_or_credentialled_urls_are_refused(url):
    with pytest.raises(TableauAPIError) as info:
        validate_server_url(url, resolve=_resolver("52.1.2.3"))
    assert info.value.reason == REASON_INVALID_URL


@pytest.mark.parametrize("address", [
    "127.0.0.1",          # loopback
    "10.0.0.5",           # private
    "192.168.1.9",        # private
    "172.16.4.4",         # private
    "169.254.169.254",    # link-local, cloud metadata
    "100.64.0.1",         # shared address space
    "0.0.0.0",            # unspecified
    "224.0.0.1",          # multicast
    "::1",                # IPv6 loopback
    "fe80::1",            # IPv6 link-local
    "fc00::1",            # IPv6 unique local
    "::ffff:127.0.0.1",   # IPv4-mapped loopback
])
def test_non_public_addresses_are_refused(address):
    with pytest.raises(TableauAPIError) as info:
        validate_server_url(PUBLIC, resolve=_resolver(address))
    assert info.value.reason == REASON_BLOCKED_ADDRESS


def test_one_private_record_among_public_ones_is_refused():
    with pytest.raises(TableauAPIError) as info:
        validate_server_url(PUBLIC, resolve=_resolver("52.1.2.3", "10.0.0.7"))
    assert info.value.reason == REASON_BLOCKED_ADDRESS


def test_unresolvable_host_is_refused():
    def fail(host, port):
        raise OSError("no such host")
    with pytest.raises(TableauAPIError) as info:
        validate_server_url(PUBLIC, resolve=fail)
    assert info.value.reason == REASON_INVALID_URL


class _Response:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.content = b""

    def json(self):
        return self._body


class _Http:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _fresh_sessions():
    clear_session_cache()
    yield
    clear_session_cache()


def test_every_request_disables_redirects_including_sign_in():
    signin = _Response(body={"credentials": {"token": "t", "site": {"id": "s"}, "user": {"id": "u"}}})
    listing = _Response(body={"projects": {"project": []}})
    http = _Http([signin, listing])
    client = TableauClient(PUBLIC, "", PatAuth("ontos", "secret"), api_version="3.30", http=http)
    client.get_json("/projects")
    assert [c[2]["allow_redirects"] for c in http.calls] == [False, False]
    assert "/auth/signin" in http.calls[0][1]


def test_a_redirect_is_an_error_and_is_not_followed():
    http = _Http([_Response(status=302, headers={"Location": "https://evil.example.net/"})])
    client = TableauClient(PUBLIC, "", PatAuth("ontos", "secret"), api_version="3.30", http=http)
    with pytest.raises(TableauAPIError) as info:
        client.session()
    assert info.value.reason == REASON_REDIRECT
    assert len(http.calls) == 1


def test_connector_refuses_http_before_any_request(monkeypatch):
    from src.connectors.tableau import TableauConnector, TableauConnectorConfig
    from src.connectors.base import ConnectorConnectionError

    def must_not_resolve(*args, **kwargs):
        raise AssertionError("no DNS lookup for a refused URL")

    monkeypatch.setattr(tableau_client.socket, "getaddrinfo", must_not_resolve)
    connector = TableauConnector(TableauConnectorConfig(server_url="http://tableau.example.com", pat_name="x",
                                                        secret_name="main.ops.s"))
    with pytest.raises(ConnectorConnectionError):
        connector._ensure_client()


def test_connector_refuses_a_host_that_resolves_to_metadata_address(monkeypatch):
    from src.connectors.tableau import TableauConnector, TableauConnectorConfig
    from src.connectors.base import ConnectorConnectionError

    monkeypatch.setattr(
        tableau_client.socket, "getaddrinfo",
        lambda host, port, **kwargs: [(2, 1, 6, "", ("169.254.169.254", 443))],
    )
    connector = TableauConnector(TableauConnectorConfig(server_url=PUBLIC, pat_name="x",
                                                        secret_name="main.ops.s"))
    with pytest.raises(ConnectorConnectionError):
        connector._ensure_client()
