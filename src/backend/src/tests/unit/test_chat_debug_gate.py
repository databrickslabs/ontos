"""The chat's debug info is only returned to Ontos admins.

The debug info carries the tools' raw results, including the text of the errors
they hit, so a non-admin who sets ``debug`` gets the normal response.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.llm_search import ChatMessageCreate
from src.models.users import UserInfo
from src.routes import llm_search_routes as routes


def _request(is_admin):
    auth_manager = None
    if is_admin is not None:
        auth_manager = SimpleNamespace(is_user_ontos_admin=lambda groups: is_admin)
    state = SimpleNamespace(authorization_manager=auth_manager, settings_manager=None)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _user():
    return UserInfo(email="u@example.com", username="u", user="u", ip=None, groups=["data-consumers"])


def _run_chat(is_admin, debug=True):
    manager = MagicMock()
    manager.chat = AsyncMock(return_value=SimpleNamespace(session_id="s1", tool_calls_executed=0))
    audit = MagicMock()
    asyncio.run(
        routes.chat(
            request=_request(is_admin),
            message=ChatMessageCreate(content="hello", debug=debug),
            db=MagicMock(),
            current_user=_user(),
            audit_manager=audit,
            audit_user=_user(),
            manager=manager,
        )
    )
    return manager.chat.await_args.kwargs["debug"]


def test_an_admin_gets_the_debug_info():
    assert _run_chat(is_admin=True) is True


@pytest.mark.parametrize("is_admin", [False, None])
def test_a_non_admin_asking_for_debug_gets_the_normal_response(is_admin):
    # Before the gate, any user's debug=true reached the manager.
    assert _run_chat(is_admin=is_admin) is False


def test_a_failing_admin_check_means_no_debug_info():
    def boom(groups):
        raise RuntimeError("roles unavailable")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(authorization_manager=SimpleNamespace(is_user_ontos_admin=boom)))
    )
    assert routes._debug_allowed(request, _user()) is False


def test_debug_off_stays_off_for_an_admin():
    assert _run_chat(is_admin=True, debug=False) is False
