"""A failing after-save step never fails a bulk import row (#1477)."""
from src.controller.asset_bulk_manager import AssetBulkManager, ImportAction
from src.db_models.assets import AssetTypeDb


def test_an_after_save_error_leaves_the_row_saved(db_session):
    if not db_session.query(AssetTypeDb).filter(AssetTypeDb.name == 'Table').first():
        db_session.add(AssetTypeDb(name='Table', category='data'))
        db_session.flush()

    def after_save(asset_id, previous_description, described):
        raise RuntimeError('unexpected')

    result = AssetBulkManager().execute_import(
        db_session, file_bytes=b'name,asset_type,description\norders,Table,About orders\n',
        filename='assets.csv', current_user_id='u@example.com', after_save=after_save,
    )

    assert result.errors == 0 and result.warnings == 0
    [item] = result.items
    assert item.action == ImportAction.CREATE and item.warnings == []
