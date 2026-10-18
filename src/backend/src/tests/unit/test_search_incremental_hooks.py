"""Incremental search-index hooks for write paths outside the owning manager (#1058).

- ``search_live_index``: workflow_executor reindexes products / assets after
  writing their status directly (contracts were fixed in #954).
- Glossary: concept/collection/ontology edits schedule one debounced refresh of
  every ``glossary-term`` entry.
- ``SearchManager.replace_type`` on the in-memory backend.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common import search_live_index
from src.common.search_interfaces import SearchIndexItem
from src.controller.semantic_models_manager import SemanticModelsManager


def _item(id_, type_="glossary-term", title="T"):
    return SearchIndexItem(id=id_, type=type_, feature_id="semantic-models", title=title,
                           description="", link="/", tags=[], extra_data={})


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(search_live_index._live)
    search_live_index._live.clear()
    yield
    search_live_index._live.clear()
    search_live_index._live.update(saved)


class DataProductsManager:  # name-matched stand-in for the registry
    def __init__(self):
        self._update_search_index = MagicMock()
        self._load_product_with_tags = MagicMock(side_effect=lambda row, db=None: ("api", row.id))


class AssetsManager:
    def __init__(self):
        self._update_search_index = MagicMock()


def test_reindex_helpers_are_noops_until_registered():
    search_live_index.reindex_product(SimpleNamespace(id="p1"), db=None)
    search_live_index.reindex_asset(SimpleNamespace(id="a1"))  # no error, nothing to call


def test_reindex_product_and_asset_use_the_live_managers():
    products, assets = DataProductsManager(), AssetsManager()
    search_live_index.register_live_search_managers([products, assets])
    row, db = SimpleNamespace(id="p1"), object()

    search_live_index.reindex_product(row, db)
    products._load_product_with_tags.assert_called_once_with(row, db=db)
    products._update_search_index.assert_called_once_with(("api", "p1"))

    asset = SimpleNamespace(id="a1")
    search_live_index.reindex_asset(asset)
    assets._update_search_index.assert_called_once_with(asset)


def test_reindex_never_raises():
    products = DataProductsManager()
    products._update_search_index.side_effect = RuntimeError("index down")
    search_live_index.register_live_search_managers([products])
    search_live_index.reindex_product(SimpleNamespace(id="p1"), db=None)  # logged, not raised


def _bare_semantic_manager(items):
    mgr = SemanticModelsManager.__new__(SemanticModelsManager)  # skip graph loading
    mgr.get_search_index_items = lambda: items
    return mgr


def test_glossary_refresh_is_skipped_before_search_is_wired(monkeypatch):
    mgr = _bare_semantic_manager([_item("glossary-term::a")])
    started = []
    monkeypatch.setattr("threading.Thread.start", lambda self: started.append(self.name))
    mgr._schedule_glossary_reindex()
    assert started == []


def test_glossary_refresh_is_debounced_and_replaces_the_type(monkeypatch):
    mgr = _bare_semantic_manager([_item("glossary-term::a"), _item("glossary-term::b")])
    search = MagicMock()
    mgr._search_manager = search
    started = []
    monkeypatch.setattr("threading.Thread.start", lambda self: started.append(self))

    mgr._schedule_glossary_reindex()
    mgr._schedule_glossary_reindex()  # burst of edits -> still one refresh pending
    assert len(started) == 1

    mgr._run_glossary_reindex(debounce=0)  # what the thread runs
    search.replace_type.assert_called_once()
    type_, items = search.replace_type.call_args.args
    assert type_ == "glossary-term" and [i.id for i in items] == ["glossary-term::a", "glossary-term::b"]

    mgr._schedule_glossary_reindex()  # after the run, the next edit schedules again
    assert len(started) == 2


def test_memory_replace_type_swaps_only_that_type(monkeypatch):
    from src.controller.search_manager import SearchManager
    monkeypatch.setattr(
        "src.common.config.get_settings",
        lambda: SimpleNamespace(SEARCH_BACKEND="memory", SEARCH_ENGINE="auto", SEARCH_TRGM_THRESHOLD=0.45,
                                SEARCH_BACKFILL_WAIT_SECONDS=0, SEARCH_BACKFILL_BATCH_SIZE=500),
    )

    class Src:
        def get_search_index_items(self):
            return [_item("glossary-term::old"), _item("product::1", type_="data-product")]

    from src.common.search_interfaces import SearchableAsset
    SearchableAsset.register(Src)
    mgr = SearchManager(searchable_managers=[Src()])
    mgr.replace_type("glossary-term", [_item("glossary-term::new")])
    assert {i.id for i in mgr.index} == {"product::1", "glossary-term::new"}
