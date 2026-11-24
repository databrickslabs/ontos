"""Unity Catalog views are seen as views by compliance rules (the SDK returns an enum)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.catalog import TableInfo

from src.common.compliance_dsl import evaluate_rule_on_object
from src.common.compliance_entities import (
    EntityIterator,
    UnityCatalogLoader,
    parse_entity_filter,
)


def _loader(*table_types):
    tables = [
        TableInfo.from_dict({
            'name': f't{i}', 'catalog_name': 'main', 'schema_name': 's',
            'full_name': f'main.s.t{i}', 'table_type': table_type,
        })
        for i, table_type in enumerate(table_types)
    ]
    ws = MagicMock()
    ws.catalogs.list.return_value = [SimpleNamespace(name='main')]
    ws.schemas.list.return_value = [SimpleNamespace(name='s')]
    ws.tables.list.return_value = tables
    return UnityCatalogLoader(ws)


def _load(loader, *entity_types):
    return {e['name']: e for e in loader.load_entities(list(entity_types))}


def test_a_view_is_loaded_as_a_view_with_a_plain_string_table_type():
    entities = _load(_loader('VIEW', 'MANAGED'), 'table', 'view')

    assert entities['t0']['type'] == 'view'
    assert entities['t0']['table_type'] == 'VIEW'
    assert entities['t1']['type'] == 'table'
    assert entities['t1']['table_type'] == 'MANAGED'


@pytest.mark.parametrize('table_type', ['MATERIALIZED_VIEW', 'METRIC_VIEW'])
def test_materialized_and_metric_views_are_views(table_type):
    [entity] = _load(_loader(table_type), 'table', 'view').values()

    assert entity['type'] == 'view'
    assert entity['table_type'] == table_type


@pytest.mark.parametrize('table_type', ['MANAGED', 'EXTERNAL', 'STREAMING_TABLE'])
def test_other_types_stay_tables(table_type):
    [entity] = _load(_loader(table_type), 'table', 'view').values()

    assert entity['type'] == 'table'


def test_a_view_rule_matches_the_view_and_a_table_rule_does_not():
    iterator = EntityIterator([_loader('VIEW', 'MANAGED')])

    views = list(iterator.iterate(parse_entity_filter("MATCH (v:view) ASSERT v.name != ''")))
    tables = list(iterator.iterate(parse_entity_filter("MATCH (t:table) ASSERT t.name != ''")))

    assert [e['name'] for e in views] == ['t0']
    assert [e['name'] for e in tables] == ['t1']


def test_the_table_type_of_a_loaded_view_satisfies_a_view_assertion():
    [view] = _load(_loader('VIEW'), 'view').values()

    passed, _ = evaluate_rule_on_object("ASSERT obj.table_type = 'VIEW'", view)

    assert passed
