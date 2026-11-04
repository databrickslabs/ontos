"""Unit tests for the workspace client of background schema import runs.

A run started with a forwarded user token must read Unity Catalog as that user,
even though the app's service-principal OAuth env vars are present, and must
fail (not fall back to the service principal) when the user client can't be
built. Without a token the service principal is used. No network: the SDK's
host-metadata probe is stubbed out.
"""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.common.database as database_mod
import src.common.workspace_client as wc_mod
import src.controller.schema_import_runs_manager as runs_mod
from src.controller.schema_import_runs_manager import (
    USER_CLIENT_FAILED_MESSAGE,
    SchemaImportRunsManager,
    UserWorkspaceClientError,
)

HOST = "https://example.cloud.databricks.com"
USER_TOKEN = "dapi-user-obo-token-5678"
SP_SENTINEL = object()


@pytest.fixture
def manager(monkeypatch):
    """Runs manager with SP OAuth env present and a recorded SP client builder."""
    import databricks.sdk.config as sdk_config

    def _offline(*_args, **_kwargs):
        raise RuntimeError("offline test: no host metadata")

    monkeypatch.setattr(sdk_config, "get_host_metadata", _offline)
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "sp-client-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "sp-client-secret")
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

    sp_calls = []

    def _sp_client(settings, *_args, **_kwargs):
        sp_calls.append(settings)
        return SP_SENTINEL

    monkeypatch.setattr(wc_mod, "get_workspace_client", _sp_client)
    mgr = SchemaImportRunsManager(SimpleNamespace(DATABRICKS_HOST=HOST), MagicMock(), MagicMock())
    mgr.sp_calls = sp_calls
    return mgr


def _failing_user_client(*_args, **_kwargs):
    raise ValueError(f"sdk rejected token {USER_TOKEN}")


@pytest.fixture
def user_client_fails(monkeypatch):
    """Every WorkspaceClient construction fails, wherever it is imported from."""
    import databricks.sdk

    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", _failing_user_client)
    monkeypatch.setattr(wc_mod, "WorkspaceClient", _failing_user_client)


def test_user_token_client_uses_the_user_token(manager):
    client = manager._build_workspace_client(USER_TOKEN)

    assert client is not SP_SENTINEL
    assert client.config.auth_type == "pat"
    assert client.config.authenticate() == {"Authorization": f"Bearer {USER_TOKEN}"}
    assert manager.sp_calls == []


def test_user_client_failure_raises_without_sp_fallback(manager, user_client_fails):
    with pytest.raises(UserWorkspaceClientError) as excinfo:
        manager._build_workspace_client(USER_TOKEN)

    assert str(excinfo.value) == USER_CLIENT_FAILED_MESSAGE
    assert excinfo.value.__cause__ is None and excinfo.value.__suppress_context__
    assert manager.sp_calls == []


def test_user_client_failure_fails_the_run(manager, user_client_fails, monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(database_mod, "get_session_factory", lambda: (lambda: db))
    repo = MagicMock()
    monkeypatch.setattr(runs_mod, "schema_import_runs_repo", repo)
    finalize = MagicMock()
    monkeypatch.setattr(manager, "_finalize_notification", finalize)

    manager._run_import(
        "run-1",
        {"connection_id": "00000000-0000-0000-0000-000000000001", "selected_paths": ["main"]},
        "user@example.com",
        USER_TOKEN, "notif-1", threading.Event(),
    )

    statuses = [c.args[2] for c in repo.update_status.call_args_list]
    assert statuses == ["failed"]
    assert repo.update_status.call_args.kwargs["error"] == USER_CLIENT_FAILED_MESSAGE
    assert finalize.call_args.kwargs["error"] == USER_CLIENT_FAILED_MESSAGE
    assert USER_TOKEN not in repr(repo.mock_calls) + repr(finalize.mock_calls)
    assert manager.sp_calls == []


def test_no_user_token_uses_service_principal(manager):
    assert manager._build_workspace_client(None) is SP_SENTINEL
    assert len(manager.sp_calls) == 1
