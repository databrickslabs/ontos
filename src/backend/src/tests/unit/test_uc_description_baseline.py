"""The Unity Catalog comment Ontos last saw (the drift baseline) and where it is recorded."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller import uc_description_baseline as baseline
from src.controller.assets_manager import AssetsManager
from src.controller.schema_import_manager import SchemaImportManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import (
    DESCRIPTION_BASELINE_PROPERTY, AssetMetadata, ColumnInfo, SchemaInfo, UnifiedAssetType,
    public_properties,
)
from src.models.schema_import import ImportPreviewItem


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


def test_a_baseline_keeps_the_text_and_a_digest_of_the_normalised_text():
    stored = baseline.make_baseline('Orders  \r\n')

    assert stored['text'] == 'Orders  \r\n'
    assert stored['digest'] == baseline.make_baseline('Orders')['digest']
    assert stored['digest'] != baseline.make_baseline('Other')['digest']
    assert baseline.make_baseline(None)['text'] is None
    assert baseline.make_baseline('')['digest'] == baseline.make_baseline(None)['digest']


@pytest.mark.parametrize('uc_comment,expected', [
    ('Orders', False), ('Orders \r\n', False), ('Changed', True), (None, True)])
def test_a_comment_differing_from_the_baseline_is_a_change(uc_comment, expected):
    assert baseline.changed_since(baseline.make_baseline('Orders'), uc_comment) is expected


def test_an_empty_comment_at_baseline_is_a_change_when_one_appears():
    empty = baseline.make_baseline(None)

    assert baseline.changed_since(empty, None) is False
    assert baseline.changed_since(empty, 'Somebody wrote this') is True


def test_without_a_baseline_nothing_counts_as_a_change():
    assert baseline.baseline_of({'owner': 'sales'}) is None
    assert baseline.baseline_of(None) is None
    assert baseline.baseline_of({DESCRIPTION_BASELINE_PROPERTY: 'garbage'}) is None
    assert baseline.changed_since(None, 'anything') is False


def test_setting_a_baseline_keeps_the_other_properties_and_hides_itself_from_clients(db_session):
    asset = AssetDb(name='orders', asset_type_id=_type(db_session, 'Table').id,
                    platform='databricks', location='main.sales.orders',
                    properties={'owner': 'sales'})
    db_session.add(asset)
    db_session.flush()

    baseline.set_baseline(db_session, asset, 'Orders')

    assert baseline.baseline_of(asset.properties)['text'] == 'Orders'
    assert asset.properties['owner'] == 'sales'
    assert public_properties(asset.properties) == {'owner': 'sales'}


class _Connector:
    connector_type = 'databricks'

    def __init__(self, table_comment, column_comment):
        self.table_comment, self.column_comment = table_comment, column_comment

    def get_asset_metadata(self, path):
        if path != 'main.sales.orders':
            return None
        return AssetMetadata(
            identifier=path, name='orders', asset_type=UnifiedAssetType.UC_TABLE,
            connector_type='databricks', description=self.table_comment,
            schema_info=SchemaInfo(columns=[
                ColumnInfo(name='order_id', data_type='int', description=self.column_comment)]))


def _import(db, connector, asset_type, path):
    for name in ('Table', 'Column'):
        _type(db, name)
    manager = SchemaImportManager(MagicMock(), AssetsManager())
    item = ImportPreviewItem(
        path=path, name=path.rsplit('.', 1)[-1], asset_type=asset_type,
        parent_path='.'.join(path.split('.')[:-1]))
    manager._create_asset_from_item(db, connector, item, 'u@x.com')
    return db.query(AssetDb).filter(AssetDb.location == path).one()


def test_an_imported_table_records_the_comment_it_was_imported_with(db_session):
    asset = _import(db_session, _Connector('Orders', 'Key'), 'Table', 'main.sales.orders')

    assert asset.description == 'Orders'
    assert baseline.baseline_of(asset.properties)['text'] == 'Orders'


def test_an_imported_column_records_its_own_comment(db_session):
    connector = _Connector('Orders', 'Key')
    _import(db_session, connector, 'Table', 'main.sales.orders')

    column = _import(db_session, connector, 'Column', 'main.sales.orders.order_id')

    assert column.description == 'Key'
    assert baseline.baseline_of(column.properties)['text'] == 'Key'


def test_an_import_of_an_object_without_a_comment_records_that_it_had_none(db_session):
    asset = _import(db_session, _Connector(None, None), 'Table', 'main.sales.orders')

    stored = baseline.baseline_of(asset.properties)
    assert stored is not None and stored['text'] is None


def test_an_import_that_could_not_read_the_object_records_nothing(db_session):
    connector = SimpleNamespace(connector_type='databricks', get_asset_metadata=lambda path: None)

    asset = _import(db_session, connector, 'Table', 'main.sales.orders')

    assert baseline.baseline_of(asset.properties) is None


def test_other_platforms_record_no_baseline(db_session):
    connector = _Connector('Orders', 'Key')
    connector.connector_type = 'snowflake'

    asset = _import(db_session, connector, 'Table', 'main.sales.orders')

    assert baseline.baseline_of(asset.properties) is None
