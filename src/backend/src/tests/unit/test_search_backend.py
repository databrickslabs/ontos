"""Unit tests for the in-memory search backend (no DB required).

The Postgres backend is covered by the local-PG integration test; here we verify
the InMemoryBackend delegates to the shared scorer correctly and maintains its
index, so switching backends is behaviour-preserving for the default path.
"""
import pytest

from src.common.search_interfaces import SearchIndexItem
from src.controller.search_backend import InMemoryBackend
from src.models.search_config import SearchConfig


class _FakeManager:
    """Minimal stand-in exposing what InMemoryBackend touches on SearchManager."""
    def __init__(self, items):
        self.index = list(items)
        self.config = SearchConfig()

    def _index_upsert_local(self, item):
        for i, existing in enumerate(self.index):
            if existing.id == item.id:
                self.index[i] = item
                return
        self.index.append(item)

    def _index_remove_local(self, item_id):
        self.index = [i for i in self.index if i.id != item_id]


def _item(id_, title, type_="data-product", feature="data-products", **extra):
    return SearchIndexItem(
        id=id_, type=type_, feature_id=feature, title=title,
        description="", link=f"/{id_}", tags=[], extra_data=extra,
    )


@pytest.fixture
def backend():
    return InMemoryBackend(_FakeManager([
        _item("product::1", "Customer Churn"),
        _item("product::2", "Sales Transactions"),
    ]))


def test_search_returns_scoring_dict(backend):
    out = backend.search("customer churn")
    assert out["total_count"] >= 1
    assert out["results"][0]["title"] == "Customer Churn"
    assert "facets" in out and "has_more" in out


def test_search_items_returns_ranked_items(backend):
    items = backend.search_items("sales")
    assert items[0].title == "Sales Transactions"
    assert all(isinstance(i, SearchIndexItem) for i in items)


def test_type_filter_and_list_mode(backend):
    out = backend.search("*", type_filter="data-product", limit=1)
    assert out["total_count"] == 2
    assert out["returned"] == 1
    assert out["has_more"] is True


def test_upsert_remove_rebuild(backend):
    backend.upsert([_item("product::3", "Revenue Model")])
    assert any(r["title"] == "Revenue Model" for r in backend.search("revenue")["results"])
    backend.remove("product::3")
    assert backend.search("revenue")["total_count"] == 0
    backend.rebuild([_item("product::9", "Only One")])
    assert backend.search("*")["total_count"] == 1
