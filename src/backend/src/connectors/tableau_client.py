"""
Tableau REST + Metadata API client

A thin client over ``requests`` for Tableau Cloud and Tableau Server:

- Sign-in with a Personal Access Token or a Connected App (direct trust, HS256 JWT).
- Sessions are cached per (server, site, identity) at module level. Connectors are
  built per request, and a new PAT sign-in ends the previous session of that PAT,
  so the session must outlive the connector instance.
- Paginated REST reads (``pageSize``/``pageNumber``) and Metadata API (GraphQL)
  queries. GraphQL can return partial data with warnings on HTTP 200; warnings
  are surfaced, never silently dropped.

Row-level data is never requested by this client.
"""

import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import requests

from src.common.logging import get_logger

logger = get_logger(__name__)

# Version used only to call serverinfo when no version is configured; any
# supported server answers it. 3.19 = Tableau Server 2023.1 (minimum supported).
_DISCOVERY_API_VERSION = "3.19"
_PAGE_SIZE = 1000
# Tableau Cloud sessions last 120 minutes, Server 240; refresh well before.
_SESSION_TTL_SECONDS = 100 * 60
_JWT_TTL_SECONDS = 5 * 60

DEFAULT_SCOPES = [
    "tableau:content:read",
    "tableau:views:download",
    "tableau:workbooks:download",
]

# GraphQL warning codes that mean the result is incomplete
INCOMPLETE_RESULT_CODES = {
    "NODE_LIMIT_EXCEEDED",
    "TIME_LIMIT_EXCEEDED",
    "MAX_PAGE_SIZE_EXCEEDED",
    "BACKFILL_RUNNING",
    "RATE_EXCEEDED",
}


class TableauAPIError(Exception):
    """A Tableau API call failed."""

    def __init__(self, message: str, status: Optional[int] = None, code: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.code = code


# ============================================================================
# Authentication
# ============================================================================

@dataclass(frozen=True)
class PatAuth:
    """Personal Access Token. Signing in again with the same PAT ends its previous session."""
    token_name: str
    token_secret: str = field(repr=False)

    @property
    def identity(self) -> str:
        return f"pat:{self.token_name}"


@dataclass(frozen=True)
class ConnectedAppAuth:
    """Connected App with direct trust: the client signs a short-lived JWT for ``username``."""
    client_id: str
    secret_id: str
    secret_value: str = field(repr=False)
    username: str
    scopes: Tuple[str, ...] = tuple(DEFAULT_SCOPES)

    @property
    def identity(self) -> str:
        return f"app:{self.client_id}:{self.username}"


TableauAuth = Union[PatAuth, ConnectedAppAuth]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_connected_app_jwt(auth: ConnectedAppAuth, now: Optional[float] = None) -> str:
    """HS256 JWT for Tableau Connected Apps (direct trust).

    Header carries ``kid`` (secret id) and ``iss`` (client id); claims are
    ``iss``, ``sub`` (username), ``aud="tableau"``, ``exp`` (<= 10 minutes),
    ``jti`` (unique) and ``scp`` (list of scopes).
    """
    issued = int(now if now is not None else time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": auth.secret_id, "iss": auth.client_id}
    claims = {
        "iss": auth.client_id,
        "sub": auth.username,
        "aud": "tableau",
        "exp": issued + _JWT_TTL_SECONDS,
        "jti": str(uuid.uuid4()),
        "scp": list(auth.scopes),
    }
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":")).encode("utf-8")) for part in (header, claims)
    )
    signature = hmac.new(auth.secret_value.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


# ============================================================================
# Session cache
# ============================================================================

@dataclass
class TableauSession:
    token: str = field(repr=False)
    site_id: str
    user_id: str
    api_version: str
    expires_at: float


_SESSIONS: Dict[Tuple[str, str, str], TableauSession] = {}
_SESSIONS_LOCK = threading.Lock()


def clear_session_cache() -> None:
    """Forget all cached sessions (tests, credential rotation)."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()


# ============================================================================
# GraphQL result
# ============================================================================

@dataclass
class GraphQLResult:
    data: Dict[str, Any]
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    # Non-warning errors returned alongside partial data
    errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def warning_codes(self) -> List[str]:
        return [str((w.get("extensions") or {}).get("code") or "") for w in self.warnings + self.errors]

    @property
    def is_complete(self) -> bool:
        return not self.errors and not (set(self.warning_codes) & INCOMPLETE_RESULT_CODES)


# ============================================================================
# Client
# ============================================================================

class TableauClient:
    """Tableau REST + Metadata API client for one site."""

    def __init__(
        self,
        server_url: str,
        site_content_url: str,
        auth: TableauAuth,
        *,
        api_version: Optional[str] = None,
        verify: Union[bool, str] = True,
        timeout: int = 30,
        http: Optional[requests.Session] = None,
    ):
        self.server_url = server_url.rstrip("/")
        self.site_content_url = site_content_url or ""
        self._auth = auth
        self._api_version = api_version
        self._verify = verify
        self._timeout = timeout
        self._http = http or requests.Session()

    # -- session -------------------------------------------------------------

    @property
    def identity(self) -> str:
        """Who the client signs in as (no secret material)."""
        return self._auth.identity

    @property
    def _cache_key(self) -> Tuple[str, str, str]:
        return (self.server_url, self.site_content_url, self._auth.identity)

    def _send(self, method: str, url: str, **kwargs) -> requests.Response:
        """Send a request; transport failures (TLS, DNS, timeouts) become TableauAPIError."""
        try:
            return self._http.request(method, url, verify=self._verify, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            raise TableauAPIError(f"Cannot reach Tableau at {self.server_url}: {exc}") from exc

    def server_info(self) -> Dict[str, Any]:
        """``GET /serverinfo`` (no auth): product version and REST API version."""
        version = self._api_version or _DISCOVERY_API_VERSION
        resp = self._send(
            "GET", f"{self.server_url}/api/{version}/serverinfo", headers={"Accept": "application/json"},
        )
        self._raise_for_status(resp, "serverinfo")
        return resp.json().get("serverInfo", {})

    def _resolve_api_version(self) -> str:
        if not self._api_version:
            self._api_version = str(self.server_info().get("restApiVersion") or _DISCOVERY_API_VERSION)
        return self._api_version

    def session(self, force_new: bool = False) -> TableauSession:
        """Cached session for this server/site/identity, signing in when needed."""
        key = self._cache_key
        with _SESSIONS_LOCK:
            cached = _SESSIONS.get(key)
            if cached and not force_new and cached.expires_at > time.time():
                return cached
            session = self._sign_in()
            _SESSIONS[key] = session
            return session

    def _sign_in(self) -> TableauSession:
        version = self._resolve_api_version()
        if isinstance(self._auth, PatAuth):
            credentials: Dict[str, Any] = {
                "personalAccessTokenName": self._auth.token_name,
                "personalAccessTokenSecret": self._auth.token_secret,
            }
        else:
            credentials = {"jwt": build_connected_app_jwt(self._auth)}
        credentials["site"] = {"contentUrl": self.site_content_url}
        resp = self._send(
            "POST", f"{self.server_url}/api/{version}/auth/signin",
            json={"credentials": credentials},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        self._raise_for_status(resp, "sign-in")
        cred = resp.json()["credentials"]
        logger.info(f"Signed in to Tableau {self.server_url} site '{self.site_content_url}' as {self._auth.identity}")
        return TableauSession(
            token=cred["token"],
            site_id=cred["site"]["id"],
            user_id=cred["user"]["id"],
            api_version=version,
            expires_at=time.time() + _SESSION_TTL_SECONDS,
        )

    def sign_out(self) -> None:
        with _SESSIONS_LOCK:
            session = _SESSIONS.pop(self._cache_key, None)
        if session is None:
            return
        try:
            self._send(
                "POST", f"{self.server_url}/api/{session.api_version}/auth/signout",
                headers={"X-Tableau-Auth": session.token},
            )
        except TableauAPIError as exc:
            logger.debug(f"Tableau sign-out failed: {exc}")

    # -- requests ------------------------------------------------------------

    @staticmethod
    def _raise_for_status(resp: requests.Response, what: str) -> None:
        if resp.status_code < 400:
            return
        code = None
        detail = ""
        try:
            err = resp.json().get("error", {})
            code = err.get("code")
            detail = err.get("detail") or err.get("summary") or ""
        except ValueError:
            detail = resp.text[:300]
        raise TableauAPIError(f"Tableau {what} failed ({resp.status_code}): {detail}", resp.status_code, code)

    def _request(
        self,
        method: str,
        site_path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        accept: str = "application/json",
        url: Optional[str] = None,
    ) -> requests.Response:
        """Authenticated request; ``site_path`` is relative to ``/api/{v}/sites/{site-id}``.

        Re-signs in once on 401 (expired session) and backs off on 429/503.
        """
        force_new = False
        for attempt in range(4):
            session = self.session(force_new=force_new)
            force_new = False
            target = url or f"{self.server_url}/api/{session.api_version}/sites/{session.site_id}{site_path}"
            resp = self._send(
                method, target, params=params, json=json_body,
                headers={"X-Tableau-Auth": session.token, "Accept": accept},
            )
            if resp.status_code == 401 and attempt == 0:
                force_new = True
                continue
            if resp.status_code in (429, 503) and attempt < 3:
                time.sleep(min(2 ** attempt, 8))
                continue
            break
        self._raise_for_status(resp, f"{method} {site_path or target}")
        return resp

    def get_json(self, site_path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", site_path, params=params).json()

    def paginate(
        self, site_path: str, collection: str, item: str, params: Optional[Dict[str, Any]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Iterate all items of a paginated REST collection (e.g. ``workbooks``/``workbook``)."""
        page = 1
        while True:
            query = dict(params or {})
            query.update({"pageSize": _PAGE_SIZE, "pageNumber": page})
            body = self.get_json(site_path, query)
            items = (body.get(collection) or {}).get(item) or []
            yield from items
            total = int((body.get("pagination") or {}).get("totalAvailable") or 0)
            if not items or page * _PAGE_SIZE >= total:
                return
            page += 1

    def get_bytes(self, site_path: str, params: Optional[Dict[str, Any]] = None) -> bytes:
        """Binary content (images). Tableau answers 406 to ``Accept: image/png``; use ``*/*``."""
        return self._request("GET", site_path, params=params, accept="*/*").content

    def graphql(self, query: str, variables: Optional[Dict[str, Any]] = None) -> GraphQLResult:
        """Metadata API query. Errors with severity WARNING are returned as warnings."""
        resp = self._request(
            "POST", "", json_body={"query": query, "variables": variables or {}},
            url=f"{self.server_url}/api/metadata/graphql",
        )
        body = resp.json()
        warnings: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for err in body.get("errors") or []:
            severity = str((err.get("extensions") or {}).get("severity") or "").upper()
            (warnings if severity == "WARNING" else errors).append(err)
        if errors and not body.get("data"):
            raise TableauAPIError(f"Tableau Metadata API error: {errors[0].get('message')}", resp.status_code)
        for err in errors:
            logger.warning(f"Tableau Metadata API reported an error with partial data: {err.get('message')}")
        return GraphQLResult(data=body.get("data") or {}, warnings=warnings, errors=errors)
