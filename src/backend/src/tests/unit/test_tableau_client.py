"""Tableau REST + Metadata API client: auth, session cache, pagination, GraphQL warnings."""

import json

import jwt
import pytest

from src.connectors.tableau_client import (
    ConnectedAppAuth,
    PatAuth,
    TableauAPIError,
    TableauClient,
    build_connected_app_jwt,
    clear_session_cache,
)

SERVER = "https://10xx.online.tableau.com"


class FakeResponse:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code = status
        self._body = body
        self.content = content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeHttp:
    """Records calls; answers from a list of (predicate, response) rules, first match wins."""

    def __init__(self):
        self.calls = []
        self.rules = []

    def on(self, method, url_part, *responses):
        self.rules.append([method, url_part, list(responses)])
        return self

    def _answer(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for rule in self.rules:
            if rule[0] == method and rule[1] in url:
                responses = rule[2]
                return responses.pop(0) if len(responses) > 1 else responses[0]
        raise AssertionError(f"unexpected {method} {url}")

    def request(self, method, url, **kwargs):
        return self._answer(method, url, **kwargs)


def _signin(token="tok-1"):
    return FakeResponse(body={"credentials": {"token": token, "site": {"id": "site-1"}, "user": {"id": "user-1"}}})


@pytest.fixture(autouse=True)
def _fresh_sessions():
    clear_session_cache()
    yield
    clear_session_cache()


def _client(http, auth=None):
    return TableauClient(SERVER, "mysite", auth or PatAuth("ontos", "s3cret"), api_version="3.30", http=http)


def test_connected_app_jwt_claims_and_signature():
    auth = ConnectedAppAuth(client_id="cid", secret_id="kid-1", secret_value="shh", username="svc@example.com")
    token = build_connected_app_jwt(auth, now=1_800_000_000)

    header = jwt.get_unverified_header(token)
    assert header["kid"] == "kid-1" and header["iss"] == "cid" and header["alg"] == "HS256"
    claims = jwt.decode(token, "shh", algorithms=["HS256"], audience="tableau", options={"verify_exp": False})
    assert claims["iss"] == "cid"
    assert claims["sub"] == "svc@example.com"
    assert claims["exp"] - 1_800_000_000 <= 600
    assert claims["scp"] == ["tableau:content:read", "tableau:views:download", "tableau:workbooks:download"]
    assert claims["jti"]


def test_pat_sign_in_payload_and_session_reuse():
    http = FakeHttp().on("POST", "/auth/signin", _signin()).on(
        "GET", "/sites/site-1/projects", FakeResponse(body={"projects": {"project": []}, "pagination": {"totalAvailable": "0"}}),
    )
    client = _client(http)
    client.get_json("/projects")
    _client(http).get_json("/projects")  # a second client instance reuses the cached session

    signins = [c for c in http.calls if "/auth/signin" in c[1]]
    assert len(signins) == 1
    creds = signins[0][2]["json"]["credentials"]
    assert creds["personalAccessTokenName"] == "ontos"
    assert creds["site"] == {"contentUrl": "mysite"}
    assert http.calls[-1][2]["headers"]["X-Tableau-Auth"] == "tok-1"


def test_connected_app_sign_in_sends_jwt():
    http = FakeHttp().on("POST", "/auth/signin", _signin())
    _client(http, ConnectedAppAuth("cid", "kid", "shh", "svc@example.com")).session()
    creds = http.calls[0][2]["json"]["credentials"]
    assert set(creds) == {"jwt", "site"}


def test_expired_session_signs_in_again_once():
    http = FakeHttp().on("POST", "/auth/signin", _signin("old"), _signin("new")).on(
        "GET", "/sites/site-1/workbooks/wb-1", FakeResponse(401, {"error": {"code": "401002"}}), FakeResponse(body={"workbook": {}}),
    )
    client = _client(http)
    client.session()
    assert client.get_json("/workbooks/wb-1") == {"workbook": {}}
    assert http.calls[-1][2]["headers"]["X-Tableau-Auth"] == "new"


def test_errors_carry_status_and_code():
    http = FakeHttp().on("POST", "/auth/signin", _signin()).on(
        "GET", "/views/v-1", FakeResponse(403, {"error": {"code": "403004", "detail": "no read"}}),
    )
    with pytest.raises(TableauAPIError) as exc:
        _client(http).get_json("/views/v-1")
    assert exc.value.status == 403 and exc.value.code == "403004"


def test_paginate_follows_total_available(monkeypatch):
    monkeypatch.setattr("src.connectors.tableau_client._PAGE_SIZE", 2)
    page1 = FakeResponse(body={"workbooks": {"workbook": [{"id": "a"}, {"id": "b"}]}, "pagination": {"totalAvailable": "3"}})
    page2 = FakeResponse(body={"workbooks": {"workbook": [{"id": "c"}]}, "pagination": {"totalAvailable": "3"}})
    http = FakeHttp().on("POST", "/auth/signin", _signin()).on("GET", "/workbooks", page1, page2)

    assert [w["id"] for w in _client(http).paginate("/workbooks", "workbooks", "workbook")] == ["a", "b", "c"]
    assert [c[2]["params"]["pageNumber"] for c in http.calls if c[0] == "GET"] == [1, 2]


def test_graphql_separates_warnings_from_errors():
    body = {
        "data": {"workbooks": []},
        "errors": [{"message": "partial", "extensions": {"severity": "WARNING", "code": "NODE_LIMIT_EXCEEDED"}}],
    }
    http = FakeHttp().on("POST", "/auth/signin", _signin()).on("POST", "/api/metadata/graphql", FakeResponse(body=body))

    result = _client(http).graphql("query { workbooks { id } }")

    assert result.data == {"workbooks": []}
    assert result.warning_codes == ["NODE_LIMIT_EXCEEDED"]
    assert result.is_complete is False


def test_graphql_error_without_data_raises():
    body = {"errors": [{"message": "Metadata API disabled"}]}
    http = FakeHttp().on("POST", "/auth/signin", _signin()).on("POST", "/api/metadata/graphql", FakeResponse(body=body))
    with pytest.raises(TableauAPIError):
        _client(http).graphql("query { x }")


def test_get_bytes_accepts_any_content_type():
    http = FakeHttp().on("POST", "/auth/signin", _signin()).on("GET", "/views/v-1/image", FakeResponse(content=b"\x89PNG"))
    assert _client(http).get_bytes("/views/v-1/image", {"resolution": "high"}) == b"\x89PNG"
    assert http.calls[-1][2]["headers"]["Accept"] == "*/*"


def test_auth_repr_hides_secrets():
    assert "s3cret" not in repr(PatAuth("ontos", "s3cret"))
    assert "shh" not in repr(ConnectedAppAuth("cid", "kid", "shh", "svc@example.com"))


def test_transport_errors_become_api_errors():
    import requests

    class Broken:
        def request(self, *args, **kwargs):
            raise requests.exceptions.SSLError("certificate verify failed")

    with pytest.raises(TableauAPIError, match="Cannot reach Tableau"):
        TableauClient(SERVER, "mysite", PatAuth("ontos", "s"), http=Broken()).server_info()
