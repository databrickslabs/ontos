"""Shared helpers for working with Unity Catalog Connections.

Today these are HTTP-type connections used by workflow webhook steps
and by the Directory layer. Centralising the listing logic so both
routes return the same shape and behave identically on SDK errors.
"""

from typing import Any, Dict, List

from src.common.logging import get_logger

logger = get_logger(__name__)


def list_http_connections(ws_client: Any) -> List[Dict[str, Any]]:
    """Return all HTTP-type Unity Catalog connections.

    Output shape matches the legacy ``/api/workflows/http-connections``
    response: ``[{name, connection_type, comment, owner, created_at,
    updated_at}, ...]``. On SDK errors an empty list is returned and a
    warning is logged -- the workspace may simply not expose HTTP
    connections yet, and surfacing the error as 500 was deemed worse
    than returning the no-op set.
    """

    try:
        connections: List[Dict[str, Any]] = []
        for conn in ws_client.connections.list():
            # ``ConnectionType.HTTP`` is not present in every SDK
            # version, so match the existing string-based check.
            conn_type = str(conn.connection_type) if conn.connection_type else ""
            if "HTTP" not in conn_type.upper():
                continue
            connections.append(
                {
                    "name": conn.name,
                    "connection_type": conn_type,
                    "comment": conn.comment,
                    "owner": conn.owner,
                    "created_at": conn.created_at,
                    "updated_at": conn.updated_at,
                }
            )
        return connections
    except Exception as exc:
        logger.warning(f"Failed to list HTTP connections: {exc}")
        return []
