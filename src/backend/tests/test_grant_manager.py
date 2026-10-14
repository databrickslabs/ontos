from unittest.mock import MagicMock

from databricks.sdk.service.catalog import Privilege, SecurableType

from src.controller.grant_manager import GrantManager


def test_get_securable_type_returns_table_member():
    manager = GrantManager(settings=MagicMock())

    assert manager._get_securable_type("table") is SecurableType.TABLE


def test_get_securable_type_returns_installed_model_member():
    manager = GrantManager(settings=MagicMock())

    assert manager._get_securable_type("model") is SecurableType.MODEL


def test_apply_revoke_for_table_reaches_workspace_grants_update():
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_revoke(
        {
            "principal": "analyst@example.com",
            "privileges": ["SELECT"],
            "securable_type": "table",
            "securable_name": "main.analytics.orders",
        }
    )

    assert result["success"] is True
    workspace_client.grants.update.assert_called_once()
    update_kwargs = workspace_client.grants.update.call_args.kwargs
    assert update_kwargs["securable_type"] is SecurableType.TABLE
    assert update_kwargs["full_name"] == "main.analytics.orders"
    assert len(update_kwargs["changes"]) == 1
    assert update_kwargs["changes"][0].principal == "analyst@example.com"
    assert update_kwargs["changes"][0].remove == [Privilege.SELECT]
