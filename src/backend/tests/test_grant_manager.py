from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.catalog import (
    GetPermissionsResponse,
    GrantsAPI,
    Privilege,
    PrivilegeAssignment,
)

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


def test_get_securable_type_returns_the_permissions_api_string():
    manager = GrantManager(settings=MagicMock())

    assert manager._get_securable_type("table") == "table"
    assert isinstance(manager._get_securable_type("table"), str)


def test_get_securable_type_maps_registered_models_to_function():
    # Unity Catalog documents registered models as a type of function: their privileges
    # (EXECUTE, APPLY TAG, CREATE MODEL VERSION) sit on the FUNCTION securable.
    manager = GrantManager(settings=MagicMock())

    assert manager._get_securable_type("model") == "function"
    assert manager._get_securable_type("registered_model") == "function"


def test_apply_revoke_for_table_reaches_workspace_grants_update():
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_revoke(_grant_payload())

    assert result["success"] is True
    workspace_client.grants.update.assert_called_once()
    update_kwargs = workspace_client.grants.update.call_args.kwargs
    assert update_kwargs["securable_type"] == "table"
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
    assert update_kwargs["securable_type"] == "table"
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
    assert path == "/api/2.1/unity-catalog/permissions/table/main.analytics.orders"
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
    assert path == "/api/2.1/unity-catalog/permissions/table/main.analytics.orders"


def test_get_securable_type_maps_every_type_name_it_knows():
    manager = GrantManager(settings=MagicMock())

    assert manager._get_securable_type("VIEW") == "table"
    assert manager._get_securable_type("connection") == "connection"
    assert manager._get_securable_type("metastore") == "metastore"
    assert manager._get_securable_type("external_location") == "external_location"


@pytest.mark.parametrize("method_name", ["apply_grant", "apply_revoke"])
def test_unsupported_securable_type_is_refused_without_calling_unity_catalog(method_name):
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())
    payload = {**_grant_payload(), "securable_type": "unknown_kind"}

    result = getattr(manager, method_name)(payload)

    assert result["success"] is False
    assert result["error_code"] == "unsupported_securable_type"
    assert result["error_params"]["securable_type"] == "unknown_kind"
    workspace_client.grants.update.assert_not_called()
    workspace_client.grants.get.assert_not_called()


def test_get_grants_refuses_unsupported_securable_type():
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.get_grants("unknown_kind", "main.analytics.orders")

    assert result["success"] is False
    assert result["error_code"] == "unsupported_securable_type"
    workspace_client.grants.get.assert_not_called()


@pytest.mark.parametrize("method_name", ["apply_grant", "apply_revoke"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_unknown_privilege_fails_instead_of_being_dropped(method_name, dry_run):
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())
    payload = {**_grant_payload(), "privileges": ["SELECT", "SELEKT"]}

    result = getattr(manager, method_name)(payload, dry_run=dry_run)

    assert result["success"] is False
    assert result["error_code"] == "unknown_privileges"
    assert result["error_params"]["privileges"] == ["SELEKT"]
    workspace_client.grants.update.assert_not_called()


def test_privileges_are_matched_case_insensitively():
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_grant({**_grant_payload(), "privileges": ["select", "Modify"]})

    assert result["success"] is True
    changes = workspace_client.grants.update.call_args.kwargs["changes"]
    assert changes[0].add == [Privilege.SELECT, Privilege.MODIFY]


def test_grant_on_registered_model_uses_function_securable():
    workspace_client, api_client = _workspace_with_real_grants_api()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_grant(
        {
            **_grant_payload(),
            "privileges": ["EXECUTE"],
            "securable_type": "model",
            "securable_name": "main.ml.churn",
        }
    )

    assert result["success"] is True
    _, path = api_client.do.call_args.args
    assert path == "/api/2.1/unity-catalog/permissions/function/main.ml.churn"


def test_revoke_all_reports_failure_when_grants_lookup_fails():
    workspace_client = MagicMock()
    workspace_client.grants.get.side_effect = RuntimeError("boom: host.example.com")
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_revoke({**_grant_payload(), "privileges": []})

    assert result["success"] is False
    assert result["error_code"] == "grants_lookup_failed"
    assert "No privileges to revoke" not in str(result)
    workspace_client.grants.update.assert_not_called()


def test_revoke_all_revokes_what_the_principal_currently_holds():
    workspace_client = MagicMock()
    assignment = PrivilegeAssignment(
        principal="analyst@example.com", privileges=[Privilege.SELECT, Privilege.MODIFY]
    )
    workspace_client.grants.get.return_value = GetPermissionsResponse(
        privilege_assignments=[assignment]
    )
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_revoke({**_grant_payload(), "privileges": []})

    assert result["success"] is True
    changes = workspace_client.grants.update.call_args.kwargs["changes"]
    assert changes[0].remove == [Privilege.SELECT, Privilege.MODIFY]


def test_revoke_all_with_no_current_grants_is_a_successful_no_op():
    workspace_client = MagicMock()
    workspace_client.grants.get.return_value = GetPermissionsResponse(privilege_assignments=[])
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_revoke({**_grant_payload(), "privileges": []})

    assert result["success"] is True
    assert "No privileges to revoke" in result["message"]
    workspace_client.grants.update.assert_not_called()


@pytest.mark.parametrize(
    ("method_name", "code"),
    [("apply_grant", "grant_failed"), ("apply_revoke", "revoke_failed")],
)
def test_failed_update_reports_code_without_exception_text(method_name, code):
    secret = "PERMISSION_DENIED at https://adb-123.azuredatabricks.net/api/2.1"
    workspace_client = MagicMock()
    workspace_client.grants.update.side_effect = RuntimeError(secret)
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = getattr(manager, method_name)(_grant_payload())

    assert result["success"] is False
    assert result["error_code"] == code
    assert result["error_params"] == {"securable_name": "main.analytics.orders"}
    assert secret not in str(result)
    assert "azuredatabricks" not in str(result)


def test_failed_get_grants_reports_code_without_exception_text():
    secret = "boom at https://adb-123.azuredatabricks.net"
    workspace_client = MagicMock()
    workspace_client.grants.get.side_effect = RuntimeError(secret)
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.get_grants("table", "main.analytics.orders")

    assert result["success"] is False
    assert result["error_code"] == "grants_lookup_failed"
    assert secret not in str(result)


@pytest.mark.parametrize("method_name", ["apply_grant", "apply_revoke"])
def test_missing_workspace_client_and_fields_are_coded(method_name):
    manager = GrantManager(settings=MagicMock())
    assert getattr(manager, method_name)(_grant_payload())["error_code"] == (
        "workspace_client_unavailable"
    )

    manager = GrantManager(ws_client=MagicMock(), settings=MagicMock())
    result = getattr(manager, method_name)({"principal": "analyst@example.com"})
    assert result["error_code"] == "missing_required_fields"


def test_delivery_service_keeps_the_coded_failure_in_the_direct_result():
    from src.controller.delivery_service import (
        DeliveryChangeType,
        DeliveryMode,
        DeliveryPayload,
        DeliveryService,
    )

    workspace_client = MagicMock()
    workspace_client.grants.update.side_effect = RuntimeError("secret detail")
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())
    service = DeliveryService(
        settings=MagicMock(DELIVERY_DIRECT_DRY_RUN=False), grant_manager=manager
    )
    payload = DeliveryPayload(
        change_type=DeliveryChangeType.GRANT,
        entity_type="data_product",
        entity_id="p1",
        data=_grant_payload(),
    )

    results = service.deliver(payload, modes=[DeliveryMode.DIRECT])

    assert results.all_success is False
    details = results.results[0].details
    assert details["error_code"] == "grant_failed"
    assert "secret detail" not in str(results.to_dict())


def test_null_privileges_on_revoke_means_revoke_all():
    workspace_client = MagicMock()
    workspace_client.grants.get.return_value = GetPermissionsResponse(
        privilege_assignments=[
            PrivilegeAssignment(principal="analyst@example.com", privileges=[Privilege.SELECT])
        ]
    )
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_revoke({**_grant_payload(), "privileges": None})

    assert result["success"] is True
    changes = workspace_client.grants.update.call_args.kwargs["changes"]
    assert changes[0].remove == [Privilege.SELECT]


def test_null_privileges_on_grant_is_a_coded_refusal():
    workspace_client = MagicMock()
    manager = GrantManager(ws_client=workspace_client, settings=MagicMock())

    result = manager.apply_grant({**_grant_payload(), "privileges": None})

    assert result["success"] is False
    assert result["error_code"] == "missing_required_fields"
    workspace_client.grants.update.assert_not_called()
