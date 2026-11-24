"""GET /api/search follows the by-id read rules of products and contracts.

A Data Consumer searching found unpublished products and contracts (a draft
with publication scope none came back) that the list and the by-id reads
hide: search checked only the feature permission. A product or contract hit is
now kept only when the caller may read it by id: published, a data-products
(data-contracts) admin, an owner, or, for products, a pending reviewer.
"""
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.features import FeatureAccessLevel
from src.common.search_interfaces import SearchIndexItem
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.search_manager import SearchManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb

RO = FeatureAccessLevel.READ_ONLY
ADMIN = FeatureAccessLevel.ADMIN


class _Index:
    def __init__(self, items):
        self._items = items

    def get_search_index_items(self):
        return self._items


def _item(id_, type_, feature_id):
    return SearchIndexItem(id=id_, type=type_, feature_id=feature_id, title=f'Zebra {id_}',
                           description='zebra', link='/x', tags=[], extra_data={})


@pytest.fixture
def world(db_session, monkeypatch):
    def product(status, owner=None):
        row = DataProductDb(id=str(uuid.uuid4()), name='Zebra', version='1.0.0',
                            status=status, draft_owner_id=owner)
        db_session.add(row)
        return row

    def contract(status, owner=None):
        row = DataContractDb(id=str(uuid.uuid4()), name='Zebra', version='1.0.0',
                             status=status, draft_owner_id=owner)
        db_session.add(row)
        return row

    rows = SimpleNamespace(
        published=product('active'),
        draft=product('draft'),
        owned_draft=product('draft', owner='olga@example.com'),
        reviewed_draft=product('draft'),
        published_contract=contract('active'),
        draft_contract=contract('draft'),
        owned_contract=contract('draft', owner='olga@example.com'),
    )
    db_session.flush()

    @contextmanager
    def _session():
        yield db_session

    monkeypatch.setattr('src.common.database.get_session_factory', lambda: _session)
    reviewed = str(rows.reviewed_draft.id)
    batch_calls = []

    def _pending(db, user, kind, entity_ids, nm=None):
        batch_calls.append(sorted(entity_ids))
        ok = kind == 'data_product' and user.email == 'rex@example.com'
        return {i for i in entity_ids if ok and i == reviewed}

    monkeypatch.setattr('src.common.review_access.pending_reviewer_ids', _pending)
    items = [
        _item(f'product::{r.id}', 'data-product', 'data-products')
        for r in (rows.published, rows.draft, rows.owned_draft, rows.reviewed_draft)
    ] + [
        _item(f'contract::{r.id}', 'data-contract', 'data-contracts')
        for r in (rows.published_contract, rows.draft_contract, rows.owned_contract)
    ]
    contracts = DataContractsManager.__new__(DataContractsManager)
    contracts.get_search_index_items = lambda: []
    search = SearchManager(searchable_managers=[_Index(items), contracts])
    rows.batch_calls = batch_calls
    return search, rows


def _hits(world, email, levels):
    search, _rows = world
    auth = MagicMock()
    auth.has_permission.side_effect = lambda eff, feature, level: level in eff.get(feature, ())
    user = SimpleNamespace(email=email, username=email, groups=['users'])
    results = search.search('zebra', auth, user, effective_permissions=levels)
    return {r.id for r in results}


def _ids(prefix, *rows):
    return {f'{prefix}::{r.id}' for r in rows}


READER = {'data-products': {RO}, 'data-contracts': {RO}}
ADMINS = {'data-products': {RO, ADMIN}, 'data-contracts': {RO, ADMIN}}


def test_consumer_gets_only_published_products_and_contracts(world):
    _s, rows = world
    assert _hits(world, 'carl@example.com', READER) == (
        _ids('product', rows.published) | _ids('contract', rows.published_contract)
    )


def test_owner_also_gets_their_drafts(world):
    _s, rows = world
    assert _hits(world, 'olga@example.com', READER) == (
        _ids('product', rows.published, rows.owned_draft)
        | _ids('contract', rows.published_contract, rows.owned_contract)
    )


def test_pending_reviewer_gets_the_product_under_review(world):
    _s, rows = world
    hits = _hits(world, 'rex@example.com', READER)
    assert _ids('product', rows.reviewed_draft) <= hits
    assert not _ids('product', rows.draft) & hits


def test_admins_get_everything(world):
    _s, rows = world
    assert _hits(world, 'ada@example.com', ADMINS) == (
        _ids('product', rows.published, rows.draft, rows.owned_draft, rows.reviewed_draft)
        | _ids('contract', rows.published_contract, rows.draft_contract, rows.owned_contract)
    )


def test_rule_failure_leaves_products_out(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('db down')

    monkeypatch.setattr('src.common.search_entity_visibility.readable_product_ids', boom)
    _s, rows = world
    hits = _hits(world, 'carl@example.com', READER)
    assert not any(h.startswith('product::') for h in hits)
    assert _ids('contract', rows.published_contract) <= hits


def test_reviewer_check_is_one_batch_for_the_drafts_not_owned(world):
    _s, rows = world
    _hits(world, 'carl@example.com', READER)
    assert rows.batch_calls == [sorted([str(rows.draft.id), str(rows.reviewed_draft.id),
                                        str(rows.owned_draft.id)])]


def test_product_rule_statement_count_does_not_grow_with_drafts(db_session):
    """40 unpublished drafts cost the same few queries as 5 (no per-row lookups)."""
    from sqlalchemy import event

    from src.common.search_entity_visibility import readable_product_ids

    def make(n):
        rows = [DataProductDb(id=str(uuid.uuid4()), name='d', version='1', status='draft')
                for _ in range(n)]
        db_session.add_all(rows)
        db_session.flush()
        return [str(r.id) for r in rows]

    def count(ids):
        seen = []
        bind = db_session.get_bind()

        def _on(*_args, **_kwargs):
            seen.append(1)

        event.listen(bind, 'before_cursor_execute', _on)
        try:
            user = SimpleNamespace(email='carl@example.com', groups=['users'])
            assert readable_product_ids(db_session, ids, user, MagicMock()) == set()
        finally:
            event.remove(bind, 'before_cursor_execute', _on)
        return len(seen)

    few, many = count(make(5)), count(make(40))
    assert many == few
    assert many <= 25  # savepoints included
