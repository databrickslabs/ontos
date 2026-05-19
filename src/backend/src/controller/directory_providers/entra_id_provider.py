"""Microsoft Entra ID provider via Microsoft Graph + UC HTTP Connection.

Auth: all calls go through ``ws.serving_endpoints.http_request(connection_name=...)``
so UC handles OAuth2 client-credentials acquisition and token caching.

Endpoints used:
- ``GET /v1.0/users?$filter=...&$select=...&$top=...`` (search users)
- ``GET /v1.0/groups?$filter=...&$select=...&$top=...`` (search groups)
- ``GET /v1.0/users/<id>?$select=...`` (resolve user)
- ``GET /v1.0/groups/<id>?$select=...`` (resolve group)

The UC HTTP Connection is expected to be configured against Microsoft
Graph (``https://graph.microsoft.com``) with the
``https://graph.microsoft.com/.default`` scope so the entire ``/v1.0``
path is reachable.
"""

import json
from typing import Any, Callable, Dict, List, Optional

from src.common.logging import get_logger
from src.controller.directory_providers.base import (
    DirectoryError,
    DirectoryProvider,
)
from src.models.directory import Principal, PrincipalType

logger = get_logger(__name__)


# Field projections kept tight so responses stay small.
_USER_SELECT = "id,displayName,userPrincipalName,mail"
_GROUP_SELECT = "id,displayName,description"

# Graph requires this header for ``startswith`` filters against the
# directory's eventually-consistent indexes.
_EVENTUAL_CONSISTENCY_HEADERS = {"ConsistencyLevel": "eventual"}


def _escape_odata(value: str) -> str:
    """Escape a string for safe inclusion in an OData filter literal.

    Single quotes are the only OData string-literal terminator, so the
    only thing we ever need to do is double them (``O'Brien`` ->
    ``O''Brien``). We never inject the raw value anywhere else in the
    URL.
    """

    return value.replace("'", "''")


class EntraIdProvider(DirectoryProvider):
    """DirectoryProvider implementation for Microsoft Graph.

    The provider holds a reference to a Databricks ``WorkspaceClient``
    and the UC HTTP Connection name. It does not cache results -- that
    lives in ``DirectoryManager``.
    """

    def __init__(self, ws_client: Any, connection_name: str) -> None:
        if not connection_name:
            raise DirectoryError("UC HTTP connection name is required")
        self._ws = ws_client
        self._connection_name = connection_name

    # ----- DirectoryProvider --------------------------------------------------

    def search_users(self, prefix: str, top: int) -> List[Principal]:
        if not prefix:
            return []
        safe = _escape_odata(prefix)
        # ``startswith`` against three fields covers display name plus
        # the two most common login shapes users actually type. The
        # ``eventual`` consistency header is required for these filters.
        filter_expr = (
            f"startswith(displayName,'{safe}') "
            f"or startswith(userPrincipalName,'{safe}') "
            f"or startswith(mail,'{safe}')"
        )
        path = (
            f"/v1.0/users?"
            f"$filter={_url_quote(filter_expr)}&"
            f"$select={_USER_SELECT}&"
            f"$top={int(top)}&"
            f"$count=true"
        )
        body = self._graph_get(path, headers=_EVENTUAL_CONSISTENCY_HEADERS)
        return [self._user_to_principal(u) for u in body.get("value", [])]

    def search_groups(self, prefix: str, top: int) -> List[Principal]:
        if not prefix:
            return []
        safe = _escape_odata(prefix)
        filter_expr = f"startswith(displayName,'{safe}')"
        path = (
            f"/v1.0/groups?"
            f"$filter={_url_quote(filter_expr)}&"
            f"$select={_GROUP_SELECT}&"
            f"$top={int(top)}&"
            f"$count=true"
        )
        body = self._graph_get(path, headers=_EVENTUAL_CONSISTENCY_HEADERS)
        return [self._group_to_principal(g) for g in body.get("value", [])]

    def get_user(self, id: str) -> Principal:
        if not id:
            raise DirectoryError("Empty user id")
        # Graph accepts either GUID or UPN/email in the path segment.
        # Path-segment values are URL-encoded; OData escaping does not
        # apply here because we are not embedding into a filter literal.
        path = f"/v1.0/users/{_url_quote(id)}?$select={_USER_SELECT}"
        return self._user_to_principal(self._graph_get(path))

    def get_group(self, id: str) -> Principal:
        if not id:
            raise DirectoryError("Empty group id")
        # Graph's path-segment lookup for groups only accepts the GUID;
        # callers that have a display name need to use search_groups.
        # We surface that as a DirectoryError so the manager can fall
        # back gracefully.
        path = f"/v1.0/groups/{_url_quote(id)}?$select={_GROUP_SELECT}"
        return self._group_to_principal(self._graph_get(path))

    def test(self) -> None:
        # ``$top=1`` minimises payload while still exercising auth + a
        # real Graph response shape.
        path = "/v1.0/users?$select=id&$top=1"
        self._graph_get(path)

    # ----- mapping ------------------------------------------------------------

    @staticmethod
    def _user_to_principal(u: Dict[str, Any]) -> Principal:
        # UPN is the persisted identifier; ``mail`` is a fallback for
        # accounts that only carry a mail attribute.
        identifier = u.get("userPrincipalName") or u.get("mail") or u.get("id", "")
        display_name = u.get("displayName") or identifier
        sub_label = u.get("mail") or u.get("userPrincipalName")
        # Don't duplicate the same value across both lines.
        if sub_label == display_name:
            sub_label = u.get("userPrincipalName") if sub_label != u.get("userPrincipalName") else None
        return Principal(
            type=PrincipalType.USER,
            id=identifier,
            display_name=display_name,
            sub_label=sub_label,
        )

    @staticmethod
    def _group_to_principal(g: Dict[str, Any]) -> Principal:
        display_name = g.get("displayName") or g.get("id", "")
        sub_label = g.get("id") or g.get("description")
        return Principal(
            type=PrincipalType.GROUP,
            id=display_name,
            display_name=display_name,
            sub_label=sub_label,
        )

    # ----- transport ----------------------------------------------------------

    def _graph_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Issue a GET against Graph via UC HTTP Connection, return parsed JSON.

        The SDK ``http_request`` returns ``HttpRequestResponse(contents=
        BinaryIO)``; we read, decode, and parse as JSON. Any transport
        error or non-JSON / Graph-error body is translated into a
        ``DirectoryError``.
        """

        try:
            from databricks.sdk.service.serving import (
                ExternalFunctionRequestHttpMethod,
            )
        except ImportError as exc:  # pragma: no cover - SDK always present
            raise DirectoryError(
                "Databricks SDK does not support serving HTTP requests"
            ) from exc

        try:
            response = self._ws.serving_endpoints.http_request(
                connection_name=self._connection_name,
                method=ExternalFunctionRequestHttpMethod.GET,
                path=path,
                headers=headers if headers else None,
            )
        except Exception as exc:
            # Transport / auth failures bubble up here.
            raise DirectoryError(f"Graph request failed: {exc}") from exc

        body = _read_response_body(response)
        if not body:
            raise DirectoryError("Graph returned an empty response")

        try:
            parsed = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise DirectoryError(
                f"Graph returned a non-JSON response: {body[:200]}"
            ) from exc

        # Graph error responses are ``{"error": {"code": "...",
        # "message": "..."}}``. UC HTTP Connections do not surface
        # status codes via the SDK, so the response body is the only
        # signal we have.
        if isinstance(parsed, dict) and "error" in parsed and isinstance(parsed["error"], dict):
            err = parsed["error"]
            raise DirectoryError(
                f"Graph error: {err.get('code', '?')}: {err.get('message', '')}"
            )

        if not isinstance(parsed, dict):
            raise DirectoryError(
                f"Graph returned unexpected JSON shape: {type(parsed).__name__}"
            )

        return parsed


# ----- helpers ----------------------------------------------------------------

def _url_quote(value: str) -> str:
    """URL-encode a string with safe defaults for OData query strings."""

    from urllib.parse import quote

    # ``$`` and ``,`` are commonly present in OData and don't need
    # escaping. Single quotes inside literals are already doubled by
    # ``_escape_odata`` before we hit this function.
    return quote(value, safe="$',()")


def _read_response_body(response: Any) -> str:
    """Read the body out of an SDK ``HttpRequestResponse`` defensively.

    The SDK exposes ``response.contents`` as ``Optional[BinaryIO]``.
    Different SDK versions and the underlying transport have surfaced
    this as bytes, str, or a read()-able stream, so we accept all
    three shapes.
    """

    contents = getattr(response, "contents", None)
    if contents is None:
        return ""
    if isinstance(contents, (bytes, bytearray)):
        return contents.decode("utf-8", errors="replace")
    if isinstance(contents, str):
        return contents
    read: Optional[Callable[[], Any]] = getattr(contents, "read", None)
    if callable(read):
        raw = read()
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="replace")
        return str(raw)
    return str(contents)
