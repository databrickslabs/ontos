"""The UC HTTP-connections listing is slow (one SDK page walk over every
connection in the workspace), so it must neither stall the event loop nor be
refetched every minute."""

import inspect
from unittest.mock import MagicMock

from src.common import workspace_client as wc
from src.common.workspace_client import CachingWorkspaceClient
from src.routes.directory_routes import list_uc_http_connections
from src.routes.workflows_routes import list_http_connections_for_workflows


def _client_with_connections():
    inner = MagicMock()
    inner.connections.list.return_value = iter([])
    return CachingWorkspaceClient(inner), inner


def test_connections_listing_is_cached_past_the_default_ttl(monkeypatch):
    client, inner = _client_with_connections()
    now = [1000.0]
    monkeypatch.setattr(wc.time, "time", lambda: now[0])

    client.connections.list()
    now[0] += 120  # past the 60s default, within the connections TTL
    client.connections.list()

    assert inner.connections.list.call_count == 1


def test_connections_listing_is_refetched_after_its_ttl(monkeypatch):
    client, inner = _client_with_connections()
    now = [1000.0]
    monkeypatch.setattr(wc.time, "time", lambda: now[0])

    client.connections.list()
    now[0] += 301
    client.connections.list()

    assert inner.connections.list.call_count == 2


def test_other_listings_keep_the_default_ttl(monkeypatch):
    inner = MagicMock()
    inner.clusters.list.return_value = iter([])
    client = CachingWorkspaceClient(inner)
    now = [1000.0]
    monkeypatch.setattr(wc.time, "time", lambda: now[0])

    client.clusters.list()
    now[0] += 61
    client.clusters.list()

    assert inner.clusters.list.call_count == 2


def test_http_connection_routes_run_in_the_threadpool():
    # An ``async def`` route would run the blocking SDK call on the event loop
    assert not inspect.iscoroutinefunction(list_http_connections_for_workflows)
    assert not inspect.iscoroutinefunction(list_uc_http_connections)
