"""Demo-mode sample definitions in asset reviews.

In demo mode, a view, function or notebook whose definition can't be fetched
shows a sample definition. The sample loader used ``Path`` without importing
it, so the ``NameError`` was logged and no sample was ever shown.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.models.data_asset_reviews import AssetType

SETTINGS = 'src.controller.data_asset_reviews_manager.get_settings'


def _definition(demo_mode: bool):
    manager = DataAssetReviewManager(db=MagicMock(), ws_client=None, notifications_manager=MagicMock())
    with patch(SETTINGS, return_value=SimpleNamespace(APP_DEMO_MODE=demo_mode)):
        return asyncio.run(manager.get_asset_definition('main.marketing.campaign_view', AssetType.VIEW))


def test_demo_mode_shows_the_sample_view_definition():
    definition = _definition(demo_mode=True)

    assert definition is not None
    assert definition.startswith('-- Sample View')


def test_outside_demo_mode_there_is_no_sample():
    assert _definition(demo_mode=False) is None
