"""The on-behalf-of workspace client requires the user's token.

``get_obo_workspace_client`` used to return the app's own (service principal)
client when a request had no ``x-forwarded-access-token``, so routes meant to
read Unity Catalog as the user read it as the app. It now answers 403
``user_token_required`` instead; only ENV=LOCAL (local development, where no
Databricks Apps proxy forwards a token) keeps the old fallback.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

import src.common.workspace_client as wc
from src.common.config import Settings
from src.common.api_errors import UserTokenRequiredError, coded_http_exception_handler

USER_CLIENT = object()


def _settings(env: str, **extra):
    return SimpleNamespace(
        ENV=env, DATABRICKS_HOST='https://example.cloud.databricks.com', **extra
    )


def _request(headers: dict):
    return SimpleNamespace(headers=headers)


@pytest.fixture
def app_client(monkeypatch):
    """The app's own client getter, replaced by a spy that must not be reached."""
    spy = MagicMock(name='get_workspace_client')
    monkeypatch.setattr(wc, 'get_workspace_client', spy)
    monkeypatch.setattr(wc, '_CLIENT_CACHE', {})
    return spy


@pytest.fixture
def user_client_builder(monkeypatch):
    """Build the user's client without the SDK or the network."""
    builder = MagicMock(name='WorkspaceClient', return_value=USER_CLIENT)
    monkeypatch.setattr(wc, 'WorkspaceClient', builder)
    monkeypatch.setattr(wc, '_verify_workspace_client', lambda client, **kwargs: client)
    monkeypatch.setattr(wc, 'CachingWorkspaceClient', lambda client, timeout=30: client)
    return builder


@pytest.mark.parametrize('env', ['PROD', 'DEV', 'TEST', ''])
def test_without_the_user_token_the_client_is_refused(app_client, user_client_builder, env):
    with pytest.raises(HTTPException) as exc_info:
        wc.get_obo_workspace_client(_request({}), _settings(env))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == wc.USER_TOKEN_REQUIRED_MESSAGE
    cause = exc_info.value.__cause__
    assert isinstance(cause, UserTokenRequiredError)
    assert cause.code == 'user_token_required'
    app_client.assert_not_called()
    user_client_builder.assert_not_called()


def test_an_empty_user_token_is_refused(app_client, user_client_builder):
    with pytest.raises(HTTPException) as exc_info:
        wc.get_obo_workspace_client(_request({'x-forwarded-access-token': ''}), _settings('PROD'))

    assert exc_info.value.status_code == 403
    app_client.assert_not_called()


def test_without_settings_the_global_env_decides(monkeypatch, app_client):
    monkeypatch.setattr(wc, 'get_settings', lambda: _settings('PROD'))

    with pytest.raises(HTTPException):
        wc.get_obo_workspace_client(_request({}))

    app_client.assert_not_called()


@pytest.mark.parametrize('env', ['LOCAL', 'local', 'LOCAL_DEV'])
def test_local_development_keeps_the_app_client(app_client, user_client_builder, env):
    settings = _settings(env)

    client = wc.get_obo_workspace_client(_request({}), settings, timeout=12)

    assert client is app_client.return_value
    app_client.assert_called_once_with(settings, 12)
    user_client_builder.assert_not_called()


def test_the_sp_fallback_setting_is_off_by_default():
    assert Settings.model_fields['OBO_ALLOW_SP_FALLBACK'].default is False


def test_with_the_sp_fallback_setting_off_the_client_is_refused(app_client):
    with pytest.raises(HTTPException) as exc_info:
        wc.get_obo_workspace_client(_request({}), _settings('PROD', OBO_ALLOW_SP_FALLBACK=False))

    assert exc_info.value.status_code == 403
    app_client.assert_not_called()


def test_with_the_sp_fallback_setting_on_the_app_client_is_returned(
    app_client, user_client_builder
):
    """Opt-in for deployments without on-behalf-of auth: the behaviour before."""
    settings = _settings('PROD', OBO_ALLOW_SP_FALLBACK=True)

    client = wc.get_obo_workspace_client(_request({}), settings, timeout=7)

    assert client is app_client.return_value
    app_client.assert_called_once_with(settings, 7)
    user_client_builder.assert_not_called()


@pytest.mark.parametrize('value', ['true', 'True', 1, MagicMock()])
def test_only_a_real_true_opts_in(app_client, value):
    with pytest.raises(HTTPException):
        wc.get_obo_workspace_client(_request({}), _settings('PROD', OBO_ALLOW_SP_FALLBACK=value))

    app_client.assert_not_called()


def test_the_setting_is_read_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv('OBO_ALLOW_SP_FALLBACK', 'true')

    settings = Settings(
        DATABRICKS_HOST='https://example.cloud.databricks.com',
        DATABRICKS_WAREHOUSE_ID='w', APP_AUDIT_LOG_DIR=str(tmp_path),
    )

    assert settings.OBO_ALLOW_SP_FALLBACK is True


def test_with_the_user_token_the_users_client_is_built(app_client, user_client_builder):
    request = _request({
        'x-forwarded-access-token': 'user-token-1234',
        'X-Forwarded-Email': 'reader@example.com',
    })

    client = wc.get_obo_workspace_client(request, _settings('PROD'))

    assert client is USER_CLIENT
    assert user_client_builder.call_args.kwargs['token'] == 'user-token-1234'
    app_client.assert_not_called()


def test_the_refusal_reaches_the_ui_as_a_coded_403(monkeypatch, app_client):
    """Through FastAPI's dependency injection and the app's coded error handler."""
    monkeypatch.setattr(wc, 'get_settings', lambda: _settings('PROD'))
    app = FastAPI()
    app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)

    @app.get('/probe')
    def probe(ws=Depends(wc.get_obo_workspace_client)):
        return {'ok': True}

    response = TestClient(app).get('/probe')

    assert response.status_code == 403
    assert response.json() == {'detail': {
        'code': 'user_token_required',
        'message': wc.USER_TOKEN_REQUIRED_MESSAGE,
        'params': {},
    }}
    app_client.assert_not_called()
