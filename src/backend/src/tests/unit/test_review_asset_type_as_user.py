"""A review request types its Unity Catalog assets with the requesting user's client.

Typing read Unity Catalog with the manager's client (the app's own), so the
type stored on a review (and returned to the requester) told a view or a
function from a table even for an object the requester can't see.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.catalog import TableType

from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.models.data_asset_reviews import AssetType


def _app_client() -> MagicMock:
    """The manager's own client: it sees every object, here a view."""
    app = MagicMock(name='app client')
    app.tables.get.return_value = SimpleNamespace(table_type=TableType.VIEW)
    return app


def _manager(app: MagicMock) -> DataAssetReviewManager:
    manager = DataAssetReviewManager(
        db=MagicMock(), ws_client=app, notifications_manager=MagicMock()
    )
    app.reset_mock()  # the constructor only checks that it has a client
    return manager


def test_an_asset_is_typed_with_the_users_client():
    app = _app_client()
    user = MagicMock(name='user client')
    user.tables.get.return_value = SimpleNamespace(table_type=TableType.METRIC_VIEW)

    asset_type = _manager(app)._determine_asset_type('main.sales.revenue', user)

    assert asset_type == AssetType.METRIC
    user.tables.get.assert_called_once_with(full_name='main.sales.revenue')
    assert app.mock_calls == []


def test_an_object_the_user_cant_see_is_typed_like_a_missing_one():
    app = _app_client()
    hidden = MagicMock(name='user client')
    hidden.tables.get.side_effect = PermissionDenied('User does not have USE SCHEMA')
    hidden.functions.get.side_effect = PermissionDenied('User does not have USE SCHEMA')
    missing = MagicMock(name='other user client')
    missing.tables.get.side_effect = NotFound('Table does not exist')
    missing.functions.get.side_effect = NotFound('Function does not exist')
    manager = _manager(app)

    assert manager._determine_asset_type('main.hr.v_salaries', hidden) == AssetType.TABLE
    assert manager._determine_asset_type('main.hr.v_salaries', missing) == AssetType.TABLE
    assert app.mock_calls == []


def test_without_a_users_client_the_managers_own_is_used():
    # Callers other than the route type protocol or app-entity FQNs only
    app = _app_client()

    assert _manager(app)._determine_asset_type('main.sales.v_orders') == AssetType.VIEW


def test_only_unity_catalog_names_read_the_catalog():
    manager = _manager(_app_client())

    assert manager.reads_catalog(['main.sales.orders'])
    assert manager.reads_catalog(['product:p-1', 'main.sales.orders'])
    assert not manager.reads_catalog(['product:p-1', 'contract:c-1'])
    assert not manager.reads_catalog(['mdm://config/run/match', 'term-mapping://s-1'])
    assert not manager.reads_catalog(['knowledge-concept://c', 'concept-changeset://c'])
    # Not catalog.schema.name: typed TABLE without a lookup
    assert not manager.reads_catalog(['sales.orders', 'orders'])
    assert not manager.reads_catalog([])
