"""Saving a column's description keeps its table's column snapshot in step (#1477)."""
from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import AssetUpdate


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


def _asset(db, type_name, location, properties=None, description=None):
    row = AssetDb(name=location.split('.')[-1], asset_type_id=_type(db, type_name).id,
                  platform='databricks', location=location, properties=properties,
                  description=description)
    db.add(row)
    db.flush()
    return row


def _snapshot(columns):
    return {'owner': 'sales', 'schema': {'column_count': len(columns), 'columns': columns}}


def test_a_column_written_to_unity_catalog_updates_the_table_snapshot(db_session):
    table = _asset(db_session, 'Table', 'main.sales.orders', _snapshot([
        {'name': 'order_id', 'data_type': 'bigint', 'description': 'Old'},
        {'name': 'amount', 'data_type': 'decimal', 'description': 'Amount'},
    ]))
    column = _asset(db_session, 'Column', 'main.sales.orders.order_id', description='Old')

    AssetsManager().update_asset(db_session, asset_id=column.id,
                                 asset_in=AssetUpdate(description='The order key'),
                                 current_user_id='u@example.com')
    # The save's route does this once the description is in Unity Catalog
    AssetsManager.update_table_column_snapshot(db_session, column)

    db_session.refresh(table)
    columns = table.properties['schema']['columns']
    assert columns[0] == {'name': 'order_id', 'data_type': 'bigint',
                          'description': 'The order key'}
    assert columns[1]['description'] == 'Amount'
    assert table.properties['owner'] == 'sales'


def test_a_save_alone_leaves_the_snapshot_until_unity_catalog_has_it(db_session):
    table = _asset(db_session, 'Table', 'main.sales.orders', _snapshot([
        {'name': 'order_id', 'description': 'Old'},
    ]))
    column = _asset(db_session, 'Column', 'main.sales.orders.order_id', description='Old')

    AssetsManager().update_asset(db_session, asset_id=column.id,
                                 asset_in=AssetUpdate(description='New'),
                                 current_user_id='u@example.com')

    db_session.refresh(table)
    assert table.properties['schema']['columns'][0]['description'] == 'Old'


def test_other_updates_leave_the_snapshot_alone(db_session):
    table = _asset(db_session, 'Table', 'main.sales.orders', _snapshot([
        {'name': 'order_id', 'description': 'Old'},
    ]))
    column = _asset(db_session, 'Column', 'main.sales.orders.order_id', description='Old')

    AssetsManager().update_asset(db_session, asset_id=column.id,
                                 asset_in=AssetUpdate(tags=['key']),
                                 current_user_id='u@example.com')

    db_session.refresh(table)
    assert table.properties['schema']['columns'][0]['description'] == 'Old'
