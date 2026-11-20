"""Whose Unity Catalog permissions a run reads with.

A run a user starts (a compliance policy run from the UI or the API, a check
they trigger) reads Unity Catalog with the user's own token, as the other
user-facing UC reads do (``get_obo_workspace_client``). Its stored results then
hold only what that user can read: a table they have no grant on is not listed,
and its tags or lineage are not read. Scheduled runs (the compliance-checks job)
have no user and read as the app.

The client is built on first use, so a run that reads no Unity Catalog object
needs no token.
"""

from typing import Any, Callable, Optional

from src.common.api_errors import UserTokenRequiredError

_UNSET = object()


class RunIdentity:
    """The workspace client a run reads Unity Catalog with, and whose it is."""

    def __init__(self, client_factory: Callable[[], Any], *, on_behalf_of_user: bool):
        self._factory = client_factory
        self._client: Any = _UNSET
        self.on_behalf_of_user = on_behalf_of_user

    @classmethod
    def app(cls) -> 'RunIdentity':
        """The app's own identity, for runs no user started (scheduled jobs)."""
        def app_client() -> Any:
            from src.common.workspace_client import get_workspace_client
            return get_workspace_client()
        return cls(app_client, on_behalf_of_user=False)

    @classmethod
    def for_request(cls, request: Any, settings: Optional[Any] = None) -> 'RunIdentity':
        """The requesting user's identity (their OBO token), for runs they start."""
        def user_client() -> Any:
            from fastapi import HTTPException
            from src.common.workspace_client import get_obo_workspace_client
            try:
                return get_obo_workspace_client(request, settings)
            except HTTPException as e:
                # No token: the coded error itself, not the HTTP answer of a route
                if isinstance(e.__cause__, UserTokenRequiredError):
                    raise e.__cause__ from None
                raise
        return cls(user_client, on_behalf_of_user=True)

    def workspace_client(self) -> Any:
        """The client, built on first use; raises what building it raises
        (``UserTokenRequiredError`` for a user without a token)."""
        if self._client is _UNSET:
            self._client = self._factory()
        return self._client
