from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.catalog import GrantsAPI, Privilege, SecurableType

from src.controller.grant_manager import GrantManager


def _grant_payload():
    return {
        "principal": "analyst@example.com",
        "privileges": ["SELECT"],
        "securable_type": "table",
        "securable_name": "main.analytics.orders",
    }


def _workspace_with_real_grants_api():
    """Workspace client whose grants API is the real SDK class over a mocked ApiClient."""
    api_client = MagicMock()
    api_client._cfg.workspace_id = None
    api_client.do.return_value = {}
    workspace_client = MagicMock()
    workspace_client.grants = GrantsAPI(api_client)
    return workspace_client, api_client


def test_get_securable_type_returns_table_member():
    manager = GrantManager(settings=MagicMock())

    assert manager._get_securable_type("table") is SecurableType.TABLE


def test_get_securable_type_returns_installed_model_member():
    manager = GrantManager(settings=MagicMock())

    assert manager._get_securable_type("model").name in {"REGISTERED_MODEL", "MODEL"}


def test_apply_revoke_for_table_reaches_workspace_grants_update():
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_revoke(_grant_payload())

    assert result["success"] is True
    workspace_client.grants.update.assert_called_once()
    update_kwargs = workspace_client.grants.update.call_args.kwargs
    assert update_kwargs["securable_type"] == "TABLE"
    assert isinstance(update_kwargs["securable_type"], str)
    assert update_kwargs["full_name"] == "main.analytics.orders"
    assert len(update_kwargs["changes"]) == 1
    assert update_kwargs["changes"][0].principal == "analyst@example.com"
    assert update_kwargs["changes"][0].remove == [Privilege.SELECT]


def test_apply_grant_for_table_passes_string_securable_type():
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_grant(_grant_payload())

    assert result["success"] is True
    update_kwargs = workspace_client.grants.update.call_args.kwargs
    assert update_kwargs["securable_type"] == "TABLE"
    assert isinstance(update_kwargs["securable_type"], str)
    assert update_kwargs["full_name"] == "main.analytics.orders"
    assert update_kwargs["changes"][0].principal == "analyst@example.com"
    assert update_kwargs["changes"][0].add == [Privilege.SELECT]


@pytest.mark.parametrize(
    ("method_name", "change_key"),
    [("apply_grant", "add"), ("apply_revoke", "remove")],
)
def test_grant_change_builds_valid_uc_permissions_request(method_name, change_key):
    workspace_client, api_client = _workspace_with_real_grants_api()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = getattr(manager, method_name)(_grant_payload())

    assert result["success"] is True
    api_client.do.assert_called_once()
    method, path = api_client.do.call_args.args
    assert method == "PATCH"
    assert path == "/api/2.1/unity-catalog/permissions/TABLE/main.analytics.orders"
    body = api_client.do.call_args.kwargs["body"]
    assert body["changes"] == [
        {change_key: ["SELECT"], "principal": "analyst@example.com"}
    ]


def test_get_grants_builds_valid_uc_permissions_request():
    workspace_client, api_client = _workspace_with_real_grants_api()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    manager.get_grants("table", "main.analytics.orders")

    method, path = api_client.do.call_args.args
    assert method == "GET"
    assert path == "/api/2.1/unity-catalog/permissions/TABLE/main.analytics.orders"
