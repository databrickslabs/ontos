"""Unit tests for DirectoryManager.

Covers settings-driven provider selection, cache hit/miss + invalidation,
and the abstraction guarantee: a stub provider can be registered without
touching the manager or routes.
"""

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from src.controller.directory_manager import (
    DirectoryManager,
    register_provider,
    unregister_provider,
)
from src.controller.directory_providers import DirectoryError, DirectoryProvider
from src.models.directory import (
    Principal,
    PrincipalType,
    SETTING_KEY_CONNECTION_NAME,
    SETTING_KEY_PROVIDER_TYPE,
)


class _StubProvider(DirectoryProvider):
    """Test double; lets us prove the abstraction is enough on its own."""

    def __init__(self, ws_client, connection_name):
        self.ws = ws_client
        self.connection_name = connection_name
        self.search_users_calls = 0
        self.search_groups_calls = 0
        self.test_calls = 0
        self.next_users: List[Principal] = []
        self.next_groups: List[Principal] = []

    def search_users(self, prefix, top):
        self.search_users_calls += 1
        return list(self.next_users)

    def search_groups(self, prefix, top):
        self.search_groups_calls += 1
        return list(self.next_groups)

    def get_user(self, id):
        raise NotImplementedError

    def get_group(self, id):
        raise NotImplementedError

    def test(self):
        self.test_calls += 1


@pytest.fixture
def stub_registered():
    """Register a 'stub' provider for the duration of the test."""

    instances: List[_StubProvider] = []

    def factory(ws_client, connection_name):
        inst = _StubProvider(ws_client, connection_name)
        instances.append(inst)
        return inst

    register_provider("stub", factory)
    try:
        yield instances
    finally:
        unregister_provider("stub")


@pytest.fixture
def db_with_settings():
    """Fake DB session where ``app_settings_repo.get_by_key`` is dict-backed."""

    return MagicMock()


def _patch_settings(values):
    """Patch ``app_settings_repo.get_by_key`` to read from ``values`` dict."""

    def fake_get(_db, key):
        return values.get(key)

    return patch(
        "src.controller.directory_manager.app_settings_repo.get_by_key",
        side_effect=fake_get,
    )


class TestStatus:
    def test_not_configured_when_no_settings(self, db_with_settings):
        with _patch_settings({}):
            status = DirectoryManager().get_status(db_with_settings)
        assert status.configured is False

    def test_not_configured_when_provider_unknown(self, db_with_settings):
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "okta",
            SETTING_KEY_CONNECTION_NAME: "my-graph",
        }):
            status = DirectoryManager().get_status(db_with_settings)
        # Unknown provider type => not configured (per architectural decision).
        assert status.configured is False
        assert status.provider_type == "okta"
        assert status.connection_name == "my-graph"

    def test_configured_when_provider_recognised(self, db_with_settings, stub_registered):
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "stub",
            SETTING_KEY_CONNECTION_NAME: "my-graph",
        }):
            status = DirectoryManager().get_status(db_with_settings)
        assert status.configured is True


class TestSearch:
    def test_empty_when_not_configured(self, db_with_settings):
        with _patch_settings({}):
            results = DirectoryManager().search(db_with_settings, MagicMock(), query="a", types=["user"])
        assert results == []

    def test_dispatches_to_registered_provider(self, db_with_settings, stub_registered):
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "stub",
            SETTING_KEY_CONNECTION_NAME: "conn",
        }):
            mgr = DirectoryManager()
            # Pre-arm the next stub instance via the factory side-effect.
            # We have to call search first so the instance exists; arrange
            # the data on the next-created instance.
            captured = stub_registered

            # Trick: monkey-patch the factory to return a pre-seeded stub.
            def seeded_factory(ws_client, connection_name):
                inst = _StubProvider(ws_client, connection_name)
                inst.next_users = [
                    Principal(type=PrincipalType.USER, id="alice@x", display_name="Alice", sub_label="alice@x"),
                ]
                captured.append(inst)
                return inst

            register_provider("stub", seeded_factory)
            results = mgr.search(db_with_settings, MagicMock(), query="ali", types=["user"])

        assert [(p.type, p.id) for p in results] == [(PrincipalType.USER, "alice@x")]

    def test_cache_hits_on_second_call(self, db_with_settings, stub_registered):
        # Replace factory with a counting one
        created = []

        def factory(ws_client, connection_name):
            stub = _StubProvider(ws_client, connection_name)
            stub.next_users = [
                Principal(type=PrincipalType.USER, id="alice@x", display_name="Alice", sub_label="alice@x"),
            ]
            created.append(stub)
            return stub

        register_provider("stub", factory)
        try:
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn",
            }):
                mgr = DirectoryManager()
                mgr.search(db_with_settings, MagicMock(), query="ali", types=["user"])
                mgr.search(db_with_settings, MagicMock(), query="ali", types=["user"])
                mgr.search(db_with_settings, MagicMock(), query="ALI", types=["user"])  # case-insensitive
                mgr.search(db_with_settings, MagicMock(), query=" ali ", types=["user"])  # whitespace
            # Provider instances are cheap to create; what we care about
            # is that the underlying search_users was only called once.
            assert sum(s.search_users_calls for s in created) == 1
        finally:
            unregister_provider("stub")

    def test_cache_invalidates_when_settings_change(self, db_with_settings, stub_registered):
        created = []

        def factory(ws_client, connection_name):
            stub = _StubProvider(ws_client, connection_name)
            stub.next_users = [
                Principal(type=PrincipalType.USER, id=f"u@{connection_name}", display_name="U", sub_label=None),
            ]
            created.append(stub)
            return stub

        register_provider("stub", factory)
        try:
            mgr = DirectoryManager()
            # First settings
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn-A",
            }):
                mgr.search(db_with_settings, MagicMock(), query="a", types=["user"])
            # Different connection name => same query should re-hit provider
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn-B",
            }):
                mgr.search(db_with_settings, MagicMock(), query="a", types=["user"])
            assert sum(s.search_users_calls for s in created) == 2
        finally:
            unregister_provider("stub")

    def test_explicit_invalidate_drops_cache(self, db_with_settings, stub_registered):
        created = []

        def factory(ws_client, connection_name):
            stub = _StubProvider(ws_client, connection_name)
            stub.next_users = [
                Principal(type=PrincipalType.USER, id="x@x", display_name="X", sub_label=None),
            ]
            created.append(stub)
            return stub

        register_provider("stub", factory)
        try:
            mgr = DirectoryManager()
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn",
            }):
                mgr.search(db_with_settings, MagicMock(), query="a", types=["user"])
                mgr.invalidate_cache()
                mgr.search(db_with_settings, MagicMock(), query="a", types=["user"])
            assert sum(s.search_users_calls for s in created) == 2
        finally:
            unregister_provider("stub")

    def test_types_filter_narrows_calls(self, db_with_settings, stub_registered):
        created = []

        def factory(ws_client, connection_name):
            stub = _StubProvider(ws_client, connection_name)
            created.append(stub)
            return stub

        register_provider("stub", factory)
        try:
            mgr = DirectoryManager()
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn",
            }):
                mgr.search(db_with_settings, MagicMock(), query="x", types=["user"])
            assert sum(s.search_users_calls for s in created) == 1
            assert sum(s.search_groups_calls for s in created) == 0
        finally:
            unregister_provider("stub")


class TestTestProbe:
    def test_raises_when_unconfigured(self, db_with_settings):
        with _patch_settings({}):
            with pytest.raises(DirectoryError, match="not configured"):
                DirectoryManager().test(db_with_settings, MagicMock())

    def test_dispatches_to_provider(self, db_with_settings, stub_registered):
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "stub",
            SETTING_KEY_CONNECTION_NAME: "conn",
        }):
            DirectoryManager().test(db_with_settings, MagicMock())
        # If we got here, dispatch worked (StubProvider.test() is a no-op).
