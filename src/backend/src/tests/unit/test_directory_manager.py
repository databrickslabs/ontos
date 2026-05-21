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
from src.controller.directory_providers import (
    DirectoryError,
    DirectoryProvider,
    DirectoryProviderConfig,
    DirectoryProviderContext,
)
from src.models.directory import (
    Principal,
    PrincipalType,
    SETTING_KEY_CONNECTION_NAME,
    SETTING_KEY_FILE_PATH,
    SETTING_KEY_LAKEBASE_TABLE,
    SETTING_KEY_PROVIDER_TYPE,
)


class _StubProvider(DirectoryProvider):
    """Test double; lets us prove the abstraction is enough on its own."""

    def __init__(self, ctx: DirectoryProviderContext, config: DirectoryProviderConfig):
        self.ctx = ctx
        self.config = config
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


def _stub_ctx() -> DirectoryProviderContext:
    return DirectoryProviderContext(ws_client=MagicMock(), db_engine=MagicMock())


@pytest.fixture
def stub_registered():
    """Register a 'stub' provider for the duration of the test.

    The fixture's job is teardown; tests that need a seeded stub
    instance re-register a counting factory inside the test body.
    """

    instances: List[_StubProvider] = []

    def factory(ctx, config):
        inst = _StubProvider(ctx, config)
        instances.append(inst)
        return inst

    register_provider("stub", factory, required_keys=(SETTING_KEY_CONNECTION_NAME,))
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

    def test_status_exposes_per_provider_settings(self, db_with_settings):
        # All three provider-specific fields make it back into the
        # status payload (for the Settings tab to hydrate).
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "file",
            SETTING_KEY_FILE_PATH: "/tmp/principals.csv",
            SETTING_KEY_LAKEBASE_TABLE: "main.directory.principals",
            SETTING_KEY_CONNECTION_NAME: "my-graph",
        }):
            status = DirectoryManager().get_status(db_with_settings)
        assert status.file_path == "/tmp/principals.csv"
        assert status.lakebase_table == "main.directory.principals"
        assert status.connection_name == "my-graph"
        # Only the active provider's required key gates "configured".
        assert status.configured is True

    def test_status_unconfigured_when_required_setting_missing(self, db_with_settings):
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "file",
            # No FILE_PATH set.
        }):
            status = DirectoryManager().get_status(db_with_settings)
        assert status.configured is False
        assert status.provider_type == "file"


class TestSearch:
    def test_empty_when_not_configured(self, db_with_settings):
        with _patch_settings({}):
            results = DirectoryManager().search(
                db_with_settings, _stub_ctx(), query="a", types=["user"],
            )
        assert results == []

    def test_dispatches_to_registered_provider(self, db_with_settings):
        seeded: List[_StubProvider] = []

        def factory(ctx, config):
            inst = _StubProvider(ctx, config)
            inst.next_users = [
                Principal(type=PrincipalType.USER, id="alice@x", display_name="Alice", sub_label="alice@x"),
            ]
            seeded.append(inst)
            return inst

        register_provider("stub", factory, required_keys=(SETTING_KEY_CONNECTION_NAME,))
        try:
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn",
            }):
                results = DirectoryManager().search(
                    db_with_settings, _stub_ctx(), query="ali", types=["user"],
                )
        finally:
            unregister_provider("stub")
        assert [(p.type, p.id) for p in results] == [(PrincipalType.USER, "alice@x")]

    def test_cache_hits_on_second_call(self, db_with_settings):
        created = []

        def factory(ctx, config):
            stub = _StubProvider(ctx, config)
            stub.next_users = [
                Principal(type=PrincipalType.USER, id="alice@x", display_name="Alice", sub_label="alice@x"),
            ]
            created.append(stub)
            return stub

        register_provider("stub", factory, required_keys=(SETTING_KEY_CONNECTION_NAME,))
        try:
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn",
            }):
                mgr = DirectoryManager()
                mgr.search(db_with_settings, _stub_ctx(), query="ali", types=["user"])
                mgr.search(db_with_settings, _stub_ctx(), query="ali", types=["user"])
                mgr.search(db_with_settings, _stub_ctx(), query="ALI", types=["user"])
                mgr.search(db_with_settings, _stub_ctx(), query=" ali ", types=["user"])
            assert sum(s.search_users_calls for s in created) == 1
        finally:
            unregister_provider("stub")

    def test_cache_invalidates_when_settings_change(self, db_with_settings):
        created = []

        def factory(ctx, config):
            stub = _StubProvider(ctx, config)
            stub.next_users = [
                Principal(type=PrincipalType.USER, id=f"u@{config.connection_name}", display_name="U", sub_label=None),
            ]
            created.append(stub)
            return stub

        register_provider("stub", factory, required_keys=(SETTING_KEY_CONNECTION_NAME,))
        try:
            mgr = DirectoryManager()
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn-A",
            }):
                mgr.search(db_with_settings, _stub_ctx(), query="a", types=["user"])
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn-B",
            }):
                mgr.search(db_with_settings, _stub_ctx(), query="a", types=["user"])
            assert sum(s.search_users_calls for s in created) == 2
        finally:
            unregister_provider("stub")

    def test_explicit_invalidate_drops_cache(self, db_with_settings):
        created = []

        def factory(ctx, config):
            stub = _StubProvider(ctx, config)
            stub.next_users = [
                Principal(type=PrincipalType.USER, id="x@x", display_name="X", sub_label=None),
            ]
            created.append(stub)
            return stub

        register_provider("stub", factory, required_keys=(SETTING_KEY_CONNECTION_NAME,))
        try:
            mgr = DirectoryManager()
            with _patch_settings({
                SETTING_KEY_PROVIDER_TYPE: "stub",
                SETTING_KEY_CONNECTION_NAME: "conn",
            }):
                mgr.search(db_with_settings, _stub_ctx(), query="a", types=["user"])
                mgr.invalidate_cache()
                mgr.search(db_with_settings, _stub_ctx(), query="a", types=["user"])
            assert sum(s.search_users_calls for s in created) == 2
        finally:
            unregister_provider("stub")

    def test_types_filter_narrows_calls(self, db_with_settings, stub_registered):
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "stub",
            SETTING_KEY_CONNECTION_NAME: "conn",
        }):
            DirectoryManager().search(
                db_with_settings, _stub_ctx(), query="x", types=["user"],
            )
        # The fixture registered a counting factory; verify it ran.
        assert sum(s.search_users_calls for s in stub_registered) == 1
        assert sum(s.search_groups_calls for s in stub_registered) == 0


class TestTestProbe:
    def test_raises_when_unconfigured(self, db_with_settings):
        with _patch_settings({}):
            with pytest.raises(DirectoryError, match="not configured"):
                DirectoryManager().test(db_with_settings, _stub_ctx())

    def test_raises_when_required_key_missing(self, db_with_settings, stub_registered):
        # Provider registered but its required setting (connection_name)
        # is absent => clear error message.
        with _patch_settings({SETTING_KEY_PROVIDER_TYPE: "stub"}):
            with pytest.raises(DirectoryError, match="missing required"):
                DirectoryManager().test(db_with_settings, _stub_ctx())

    def test_dispatches_to_provider(self, db_with_settings, stub_registered):
        with _patch_settings({
            SETTING_KEY_PROVIDER_TYPE: "stub",
            SETTING_KEY_CONNECTION_NAME: "conn",
        }):
            DirectoryManager().test(db_with_settings, _stub_ctx())
        # If we got here, dispatch worked (StubProvider.test() is a no-op).
