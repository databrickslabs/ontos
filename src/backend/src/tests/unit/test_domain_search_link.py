"""A domain's search hit opens its detail page (#1478 follow-up).

The domain detail page lives at /settings/data-domains/<id>; the app has no
/data-domains/<id> route (only /data-domains redirects, to the list).
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.controller.data_domains_manager import DataDomainManager


def test_the_search_item_links_to_the_settings_detail_route():
    manager = DataDomainManager(repository=MagicMock(), tags_manager=MagicMock())
    domain = SimpleNamespace(id='d-1', name='Customer', description='', created_by='a', status=None)

    item = manager._build_search_index_item(domain)

    assert item.link == '/settings/data-domains/d-1'
