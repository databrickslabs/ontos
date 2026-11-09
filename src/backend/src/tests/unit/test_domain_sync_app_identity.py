"""Domain Sync uses one privileged app identity, not the initiating user's token."""

import inspect
from unittest.mock import MagicMock

from src.routes import domain_sync_routes


def test_domain_sync_manager_uses_app_service_principal(monkeypatch):
    app_client = MagicMock(name="app service-principal client")
    get_app_client = MagicMock(return_value=app_client)
    monkeypatch.setattr(domain_sync_routes, "get_workspace_client", get_app_client)

    manager = domain_sync_routes._get_manager()

    get_app_client.assert_called_once_with()
    assert manager._uc._ws is app_client


def test_domain_sync_manager_does_not_accept_a_request_identity():
    """The dependency signature must not ask FastAPI for a user request/token."""
    assert not inspect.signature(domain_sync_routes._get_manager).parameters
