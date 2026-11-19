"""A user-started run's identity reports a missing token as the coded error.

``RunIdentity.for_request`` builds its client with the real
``get_obo_workspace_client``, which answers a request without the user's token
with a route's 403 ``HTTPException`` raised from ``UserTokenRequiredError``. The
run needs the coded error itself, not the HTTP answer.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import src.common.workspace_client as wc
from src.common.api_errors import UserTokenRequiredError
from src.common.run_identity import RunIdentity

PROD = SimpleNamespace(
    ENV='PROD', OBO_ALLOW_SP_FALLBACK=False,
    DATABRICKS_HOST='https://example.cloud.databricks.com',
)


@pytest.fixture(autouse=True)
def no_app_client(monkeypatch):
    """The app's own client must not be reached in place of the user's."""
    spy = MagicMock(name='get_workspace_client')
    monkeypatch.setattr(wc, 'get_workspace_client', spy)
    monkeypatch.setattr(wc, '_CLIENT_CACHE', {})
    return spy


def test_no_token_raises_the_coded_error_not_the_http_answer(no_app_client):
    identity = RunIdentity.for_request(SimpleNamespace(headers={}), PROD)

    with pytest.raises(UserTokenRequiredError) as raised:
        identity.workspace_client()

    assert raised.value.code == 'user_token_required'
    assert identity.on_behalf_of_user is True
    no_app_client.assert_not_called()


def test_another_http_error_is_raised_unchanged(monkeypatch):
    def failing(request, settings=None):
        raise HTTPException(status_code=500, detail='boom') from ValueError('other')

    monkeypatch.setattr(wc, 'get_obo_workspace_client', failing)
    identity = RunIdentity.for_request(SimpleNamespace(headers={}), PROD)

    with pytest.raises(HTTPException) as raised:
        identity.workspace_client()

    assert raised.value.status_code == 500


@pytest.mark.parametrize("headers, on_behalf_of_user", [
    ({"x-forwarded-access-token": "user-token"}, True),
    ({}, False),  # the service principal fallback (ENV=LOCAL, OBO_ALLOW_SP_FALLBACK)
])
def test_a_user_identity_reports_the_client_it_really_is(headers, on_behalf_of_user):
    from src.common.run_identity import RunIdentity

    request = SimpleNamespace(headers=headers)
    with patch("src.common.workspace_client.get_obo_workspace_client", return_value=object()):
        identity = RunIdentity.for_request(request)
        assert identity.on_behalf_of_user is True  # until the client is built
        identity.workspace_client()

    assert identity.on_behalf_of_user is on_behalf_of_user
