"""Unit tests for building the on-behalf-of (OBO) workspace client.

The app runs with the service principal's ``DATABRICKS_CLIENT_ID`` /
``DATABRICKS_CLIENT_SECRET`` in the process environment. Building an OBO client
must not touch those variables (other requests build service-principal clients
concurrently), and the OBO client must still authenticate with the user's token
only. No network: the SDK's host-metadata probe is stubbed out.
"""
import os
from types import SimpleNamespace

import pytest

import src.common.workspace_client as wc_mod

HOST = "https://example.cloud.databricks.com"
SP_ID = "sp-client-id"
SP_SECRET = "sp-client-secret"
USER_TOKEN = "dapi-user-obo-token-1234"


@pytest.fixture
def obo_env(monkeypatch):
    """Service-principal OAuth env present, empty client cache, no verification calls."""
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", SP_ID)
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", SP_SECRET)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
    monkeypatch.setattr(wc_mod, "_CLIENT_CACHE", {})
    monkeypatch.setattr(wc_mod, "_verify_workspace_client",
                        lambda ws, skip_cluster_check=False: ws)
    monkeypatch.setattr(wc_mod, "CachingWorkspaceClient", lambda ws, timeout=30: ws)
    return SimpleNamespace(DATABRICKS_HOST=HOST)


@pytest.fixture
def offline_sdk(monkeypatch):
    """Stub the SDK's host-metadata probe so Config() makes no network call."""
    import databricks.sdk.config as sdk_config

    def _offline(*_args, **_kwargs):
        raise RuntimeError("offline test: no host metadata")

    monkeypatch.setattr(sdk_config, "get_host_metadata", _offline)
    return sdk_config


def _request() -> SimpleNamespace:
    return SimpleNamespace(headers={
        "x-forwarded-access-token": USER_TOKEN,
        "X-Forwarded-Email": "user@example.com",
    })


def test_obo_build_does_not_touch_process_env(obo_env, monkeypatch):
    """While the OBO client is constructed, the SP env vars stay visible to other threads."""
    seen = {}

    def _fake_workspace_client(**kwargs):
        seen["env"] = (os.environ.get("DATABRICKS_CLIENT_ID"),
                       os.environ.get("DATABRICKS_CLIENT_SECRET"))
        seen["kwargs"] = kwargs
        return SimpleNamespace(config=SimpleNamespace(host=kwargs.get("host")))

    monkeypatch.setattr(wc_mod, "WorkspaceClient", _fake_workspace_client)

    wc_mod.get_obo_workspace_client(_request(), obo_env)

    assert seen["env"] == (SP_ID, SP_SECRET)
    assert seen["kwargs"]["token"] == USER_TOKEN
    assert seen["kwargs"]["auth_type"] == "pat"
    assert os.environ["DATABRICKS_CLIENT_ID"] == SP_ID
    assert os.environ["DATABRICKS_CLIENT_SECRET"] == SP_SECRET


def test_obo_client_authenticates_with_user_token_only(obo_env, offline_sdk, monkeypatch):
    """Real SDK config: SP OAuth env (even a forced auth type) is ignored for the OBO client."""
    monkeypatch.setenv("DATABRICKS_AUTH_TYPE", "oauth-m2m")

    client = wc_mod.get_obo_workspace_client(_request(), obo_env)

    assert client.config.auth_type == "pat"
    assert client.config.authenticate() == {"Authorization": f"Bearer {USER_TOKEN}"}
    assert os.environ["DATABRICKS_CLIENT_ID"] == SP_ID


def test_token_without_auth_type_conflicts_with_sp_env(obo_env, offline_sdk):
    """Why ``auth_type='pat'`` is needed: without it the SDK sees two auth methods."""
    with pytest.raises(ValueError, match="more than one authorization method"):
        offline_sdk.Config(host=HOST, token=USER_TOKEN)
