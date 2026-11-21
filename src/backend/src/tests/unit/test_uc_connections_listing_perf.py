"""The UC HTTP-connections listing is slow (one SDK page walk over every
connection in the workspace), so it must not stall the event loop; the cached
listings may stand in for a failed call only briefly and only on transient
failures."""

import inspect
from unittest.mock import MagicMock

import pytest
import requests
from databricks.sdk.errors import PermissionDenied, TemporarilyUnavailable, Unauthenticated

from src.common import workspace_client as wc
from src.common.workspace_client import CachingWorkspaceClient
from src.routes.directory_routes import list_uc_http_connections
from src.routes.workflows_routes import list_http_connections_for_workflows

CACHED = ["conn-a"]


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(wc.time, "time", lambda: now[0])
    return now


def _primed_client():
    """A client whose connections listing has been cached once at t=1000."""
    inner = MagicMock()
    inner.connections.list.return_value = iter(CACHED)
    client = CachingWorkspaceClient(inner)
    assert client.connections.list() == CACHED
    return client, inner


def test_connections_listing_is_cached_for_a_minute(clock):
    client, inner = _primed_client()

    clock[0] += 59
    client.connections.list()
    assert inner.connections.list.call_count == 1

    clock[0] += 2
    inner.connections.list.return_value = iter([])
    assert client.connections.list() == []
    assert inner.connections.list.call_count == 2


@pytest.mark.parametrize("error", [
    TemporarilyUnavailable("busy"),
    requests.exceptions.ConnectionError("reset"),
    wc.TimeoutError("slow"),
])
def test_transient_failure_returns_recent_stale_listing(clock, error):
    client, inner = _primed_client()
    clock[0] += 120
    inner.connections.list.side_effect = error

    assert client.connections.list() == CACHED


@pytest.mark.parametrize("error", [PermissionDenied("revoked"), Unauthenticated("expired")])
def test_non_transient_failure_raises_and_drops_the_cache(clock, error):
    client, inner = _primed_client()
    clock[0] += 120
    inner.connections.list.side_effect = error

    with pytest.raises(type(error)):
        client.connections.list()
    # The stale listing is gone: a later transient failure has nothing to fall back to
    inner.connections.list.side_effect = TemporarilyUnavailable("busy")
    with pytest.raises(TemporarilyUnavailable):
        client.connections.list()


def test_transient_failure_does_not_serve_a_listing_older_than_the_stale_limit(clock):
    client, inner = _primed_client()
    clock[0] += 301
    inner.connections.list.side_effect = TemporarilyUnavailable("busy")

    with pytest.raises(TemporarilyUnavailable):
        client.connections.list()


def test_http_connection_routes_run_in_the_threadpool():
    # An ``async def`` route would run the blocking SDK call on the event loop
    assert not inspect.iscoroutinefunction(list_http_connections_for_workflows)
    assert not inspect.iscoroutinefunction(list_uc_http_connections)
