"""global_search follows the asset read rule (#1637).

An asset, and a Markdown document imported for an asset (its full text is in
the index), are returned only to a caller who may read that asset: ``assets``
READ_WRITE, or the asset is linked to an accessible Data Product (the rule of
``GET /api/assets/{id}``). Documents of other entities keep the feature check.
The filter applies before pagination, counts and facets, and fails closed.
"""
import asyncio
import uuid
from unittest.mock import MagicMock

import pytest

from src.common.features import FeatureAccessLevel
from src.common.search_interfaces import SearchIndexItem
from src.controller.assets_manager import AssetsManager
from src.controller.search_manager import SearchManager
from src.db_models.metadata import DocumentMetadataDb
from src.tools.base import ToolCaller, ToolContext
from src.tools.registry import create_default_registry

RO = FeatureAccessLevel.READ_ONLY
READER = ToolCaller(email='rita@example.com', auth_path='test', groups=['users'],
                    permissions={'assets': RO, 'data-domains': RO})
WRITER = ToolCaller(email='walt@example.com', auth_path='test', groups=['users'],
                    permissions={'assets': FeatureAccessLevel.READ_WRITE, 'data-domains': RO})


class _Index:
    def __init__(self, items):
        self._items = items

    def get_search_index_items(self):
        return self._items


class _Assets(AssetsManager):
    """The startup AssetsManager, with the #347 rule answering ``readable``."""

    def __init__(self, readable=(), error=None):
        super().__init__()
        self.readable = list(readable)
        self.error = error
        self.calls = 0

    def get_search_index_items(self):
        return []

    def resolve_accessible_asset_ids(self, db, *, data_products_manager, is_admin):
        self.calls += 1
        assert is_admin is False
        if self.error:
            raise self.error
        return self.readable


def _doc(db, entity_type, entity_id):
    path = f'/Volumes/main/docs/{uuid.uuid4().hex}.md'
    row = DocumentMetadataDb(
        entity_type=entity_type, entity_id=entity_id, title='Doc', original_filename='d.md',
        content_type='text/markdown', size_bytes=1, storage_path=path, source_path=path,
        content_hash='h',
    )
    db.add(row)
    db.flush()
    return row


def _item(id_, type_, feature_id, extra=None):
    return SearchIndexItem(id=id_, type=type_, feature_id=feature_id, title=f'Orders {id_}',
                           description='orders secret', link='/x', tags=[],
                           extra_data=extra or {})


@pytest.fixture
def world(db_session):
    hidden, shown = str(uuid.uuid4()), str(uuid.uuid4())
    docs = {
        'hidden': _doc(db_session, 'asset', hidden),
        'shown': _doc(db_session, 'asset', shown),
        'domain': _doc(db_session, 'data_domain', 'domain-1'),
    }
    items = [
        _item(f'asset::{hidden}', 'asset-table', 'assets'),
        _item(f'asset::{shown}', 'asset-view', 'assets'),
    ] + [
        _item(f'document::{row.id}', 'document',
              'assets' if row.entity_type == 'asset' else 'data-domains',
              {'entity_type': row.entity_type, 'entity_id': row.entity_id})
        for row in docs.values()
    ]
    ids = {
        'hidden asset': f'asset::{hidden}', 'shown asset': f'asset::{shown}',
        **{f'{k} doc': f'document::{row.id}' for k, row in docs.items()},
    }
    return db_session, items, ids, shown


def _search(world, caller, assets, **args):
    db, items, _ids, _shown = world
    search = SearchManager(searchable_managers=[_Index(items), assets])
    ctx = ToolContext(db=db, settings=MagicMock(), caller=caller, search_manager=search,
                      data_products_manager=MagicMock(), default_visibility='readable')
    res = asyncio.run(create_default_registry().execute(
        'global_search', ctx, {'query': '*', 'limit': 100, **args}))
    assert res.success, res.error
    return res.data


def _full_ids(data):
    return {f"{'asset' if r['type'].startswith('asset-') else r['type']}::{r['id']}"
            for r in data['results']}


def test_an_assets_reader_sees_only_readable_assets_and_their_documents(world):
    _db, _items, ids, shown = world
    assets = _Assets(readable=[uuid.UUID(shown)])

    data = _search(world, READER, assets)

    assert _full_ids(data) == {ids['shown asset'], ids['shown doc'], ids['domain doc']}
    assert data['total_count'] == 3
    assert data['facets']['type'] == {'asset-view': 1, 'document': 2}
    assert assets.calls == 1  # one lookup for the whole result set


def test_a_document_type_filter_keeps_the_rule(world):
    _db, _items, ids, shown = world

    data = _search(world, READER, _Assets(readable=[uuid.UUID(shown)]), type='document')

    assert _full_ids(data) == {ids['shown doc'], ids['domain doc']}


def test_an_assets_reader_of_no_asset_sees_no_asset_and_no_asset_document(world):
    _db, _items, ids, _shown = world

    data = _search(world, READER, _Assets(readable=[]), query='orders')

    assert _full_ids(data) == {ids['domain doc']}
    assert data['total_count'] == 1


def test_assets_read_write_sees_every_asset_and_document(world):
    _db, items, _ids, _shown = world
    assets = _Assets(readable=[])

    data = _search(world, WRITER, assets)

    assert data['total_count'] == len(items)
    assert assets.calls == 0


def test_a_failing_asset_rule_hides_every_asset_result(world):
    _db, _items, ids, _shown = world

    data = _search(world, READER, _Assets(error=RuntimeError('lookup failed')))

    assert _full_ids(data) == {ids['domain doc']}


def test_without_the_assets_manager_no_asset_result_is_returned(world):
    db, items, ids, _shown = world
    search = SearchManager(searchable_managers=[_Index(items)])
    ctx = ToolContext(db=db, settings=MagicMock(), caller=READER, search_manager=search,
                      data_products_manager=MagicMock())

    res = asyncio.run(create_default_registry().execute(
        'global_search', ctx, {'query': '*', 'limit': 100}))

    assert _full_ids(res.data) == {ids['domain doc']}


def test_a_stored_asset_type_in_another_casing_follows_the_rule(world):
    """The REST filter reads the item's entity type in any casing."""
    item = _item('document::x', 'document', 'assets', {'entity_type': 'Asset', 'entity_id': 'a1'})
    assert SearchManager.asset_of_item(item) == 'a1'
    assert SearchManager.asset_of_item(_item('asset::a2', 'asset-table', 'assets')) == 'a2'
    assert SearchManager.asset_of_item(_item('product::p', 'data-product', 'data-products')) \
        is None
