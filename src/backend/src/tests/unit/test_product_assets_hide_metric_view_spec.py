"""A product's dataset views don't carry a metric view's stored definition (#1263).

``properties['metric_view']`` holds the view's parsed spec, which only users who
can read the view in Unity Catalog may see. A product reader gets the product's
datasets and their tables, views and columns, so those leave the key out.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller import data_products_manager as module
from src.controller.data_products_manager import DataProductsManager

SPEC = {'metric_view': {'spec': {'measures': [{'name': 'revenue', 'expr': 'SUM(amount)'}]}},
        'owner': 'sales'}


def _asset(asset_id, name):
    return SimpleNamespace(
        id=asset_id, name=name, description=None, status='active', location=f'main.s.{name}',
        properties=dict(SPEC), tags=[], created_at=None,
    )


def _rel(rel_id, target_id, relationship_type, target_type='Asset'):
    return SimpleNamespace(
        id=rel_id, target_id=target_id, target_type=target_type,
        relationship_type=relationship_type,
    )


@pytest.fixture
def manager(monkeypatch):
    assets = {'ds': _asset('ds', 'dataset'), 'mv': _asset('mv', 'orders_mv'),
              'col': _asset('col', 'region')}
    rels = {
        ('DataProduct', 'p1'): [_rel('r1', 'ds', 'hasDataset')],
        ('Dataset', 'ds'): [_rel('r2', 'mv', 'hasView')],
        ('Asset', 'mv'): [_rel('r3', 'col', 'hasColumn')],
    }

    def query_filtered(session, source_type, source_id, relationship_type=None):
        found = rels.get((source_type, source_id), [])
        return [r for r in found if relationship_type in (None, r.relationship_type)]

    monkeypatch.setattr(module.entity_relationship_repo, 'query_filtered', query_filtered)
    monkeypatch.setattr(module.asset_repo, 'get', lambda session, asset_id: assets.get(asset_id))
    mgr = DataProductsManager.__new__(DataProductsManager)
    mgr._db = MagicMock()
    mgr.get_product = MagicMock(return_value=SimpleNamespace(id='p1', name='Orders'))
    return mgr


def test_product_datasets_leave_out_the_metric_view_spec(manager):
    datasets = manager.get_product_datasets('p1')

    assert datasets[0]['properties'] == {'owner': 'sales'}


def test_product_hierarchy_leaves_out_the_metric_view_spec(manager):
    hierarchy = manager.get_product_hierarchy('p1')

    dataset = hierarchy['datasets'][0]
    view = dataset['views'][0]
    assert dataset['properties'] == {'owner': 'sales'}
    assert view['properties'] == {'owner': 'sales'}
    assert view['columns'][0]['properties'] == {'owner': 'sales'}
