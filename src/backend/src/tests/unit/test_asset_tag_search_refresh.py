"""Asset tag writes refresh the asset's search entry, from one shared hook in TagsManager.

Routes, the MCP tools and the workflow Assign Tag step all write through TagsManager, so the
entry is refreshed for each of them. Tag rename and delete refresh the assets that carried the
tag. The MCP tools check assets READ_WRITE for asset targets; the workflow step does not (it
runs with the workflow's authority, see the PR).
"""
import uuid
from types import SimpleNamespace

import pytest

from src.common.features import FeatureAccessLevel
from src.controller.assets_manager import AssetsManager
from src.controller.tags_manager import TagsManager
from src.db_models.assets import AssetTypeDb
from src.db_models.tags import TagDb
from src.models.assets import AssetCreate
from src.models.tags import AssignedTagCreate, TagUpdate
from src.repositories.tags_repository import tag_namespace_repo
from src.tools.base import ToolCaller, ToolContext
from src.tools.tags import AssignTagToEntityTool, RemoveTagFromEntityTool


class _Index:
    """Stands in for the wired SearchManager: records what was upserted and removed."""

    def __init__(self):
        self.calls = []
        self.removed = []

    def upsert_items(self, items):
        self.calls.append(list(items))

    def remove_item(self, item_id):
        self.removed.append(item_id)

    @property
    def items(self):
        return [item for call in self.calls for item in call]

    def last_for(self, asset_id):
        return [item for item in self.items if item.id == f"asset::{asset_id}"][-1]


@pytest.fixture
def index():
    return _Index()


@pytest.fixture
def manager(index):
    tags = TagsManager()
    tags._search_manager = index
    return tags


@pytest.fixture
def asset_type(db_session):
    row = AssetTypeDb(name=f'Type {uuid.uuid4().hex[:8]}', category='data')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def namespace(db_session):
    return tag_namespace_repo.get_or_create_default_namespace(db_session, user_email='admin@example.com')


@pytest.fixture
def pii(db_session, namespace):
    tag = TagDb(name=f'pii_{uuid.uuid4().hex[:6]}', namespace_id=namespace.id, status='active')
    db_session.add(tag)
    db_session.flush()
    return tag


@pytest.fixture
def asset(db_session, asset_type):
    return AssetsManager().create_asset(
        db_session,
        asset_in=AssetCreate(name=f'customers {uuid.uuid4().hex[:6]}', asset_type_id=asset_type.id),
        current_user_id='alice@example.com',
    )


def _tag_names(item):
    return set(item.tags)


class TestWritesRefreshTheEntry:
    def test_add_refreshes_the_asset_entry(self, manager, db_session, asset, pii, index):
        manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )

        assert pii.name in _tag_names(index.last_for(asset.id))

    def test_set_refreshes_the_asset_entry(self, manager, db_session, asset, pii, index):
        manager.set_tags_for_entity(
            db_session, entity_id=str(asset.id), entity_type='asset',
            tags=[AssignedTagCreate(tag_fqn=f'default/{pii.name}')], user_email='alice@example.com',
        )

        assert pii.name in _tag_names(index.last_for(asset.id))

    def test_remove_refreshes_the_asset_entry(self, manager, db_session, asset, pii, index):
        manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )
        manager.remove_tag_from_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            user_email='alice@example.com',
        )

        assert pii.name not in _tag_names(index.last_for(asset.id))

    def test_uncommitted_set_leaves_the_refresh_to_its_caller(self, manager, db_session, asset, pii, index):
        """Asset create and update and the bulk import set tags with commit=False and refresh after their own commit."""
        manager.set_tags_for_entity(
            db_session, entity_id=str(asset.id), entity_type='asset',
            tags=[AssignedTagCreate(tag_fqn=f'default/{pii.name}')], user_email='alice@example.com', commit=False,
        )

        assert index.calls == []

    def test_other_entity_types_are_not_refreshed(self, manager, db_session, pii, index):
        manager.add_tag_to_entity(
            db_session, entity_id='prod-1', entity_type='data_product', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )

        assert index.calls == []

    def test_a_refresh_failure_does_not_undo_the_write(self, manager, db_session, asset, pii, index, monkeypatch):
        def boom(items):
            raise RuntimeError('index down')

        monkeypatch.setattr(index, 'upsert_items', boom)

        result = manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )

        assert result.tag_id == pii.id


class TestRenameAndDelete:
    def test_rename_refreshes_the_assets_that_carry_the_tag(self, manager, db_session, asset, pii, index):
        manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )
        old_name = pii.name
        index.calls.clear()

        manager.update_tag(db_session, tag_id=pii.id, tag_in=TagUpdate(name='personal'), user_email='admin@example.com')

        tags = _tag_names(index.last_for(asset.id))
        assert 'personal' in tags
        assert old_name not in tags

    def test_rename_without_a_name_change_refreshes_nothing(self, manager, db_session, asset, pii, index):
        manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )
        index.calls.clear()

        manager.update_tag(db_session, tag_id=pii.id, tag_in=TagUpdate(description='new text'), user_email='admin@example.com')

        assert index.calls == []

    def test_delete_refreshes_the_assets_that_carried_the_tag(self, manager, db_session, asset, pii, index):
        manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )
        # The association is removed with the tag before the delete, as the tag screens do
        manager.remove_tag_from_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            user_email='alice@example.com',
        )
        manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )
        index.calls.clear()

        manager.delete_tag(db_session, tag_id=pii.id)

        assert pii.name not in _tag_names(index.last_for(asset.id))


class _Tools:
    @staticmethod
    def context(db, permissions):
        caller = ToolCaller(email='sue@example.com', auth_path='test', permissions=permissions)
        return ToolContext(db=db, settings=SimpleNamespace(), caller=caller)


class TestMcpAssetTargets:
    """The MCP tools need assets READ_WRITE for an asset target, in addition to tags READ_WRITE."""

    TAGS_ONLY = {'tags': FeatureAccessLevel.READ_WRITE}
    BOTH = {'tags': FeatureAccessLevel.READ_WRITE, 'assets': FeatureAccessLevel.READ_WRITE}

    def test_assign_to_an_asset_is_refused_without_assets_read_write(self, db_session, asset, pii, index):
        import asyncio
        ctx = _Tools.context(db_session, self.TAGS_ONLY)

        result = asyncio.run(AssignTagToEntityTool().execute(
            ctx, entity_type='asset', entity_id=str(asset.id), tag_id=str(pii.id),
        ))

        assert result.success is False
        assert 'assets' in result.error
        assert index.calls == []

    def test_assign_to_an_asset_runs_with_both_permissions_and_refreshes(self, db_session, asset, pii, index, monkeypatch):
        """The tool builds a fresh TagsManager; the refresh finds the SearchManager registered at startup."""
        import asyncio
        from src.common import app_state
        monkeypatch.setitem(app_state._managers_registry, 'search_manager', index)
        ctx = _Tools.context(db_session, self.BOTH)

        result = asyncio.run(AssignTagToEntityTool().execute(
            ctx, entity_type='asset', entity_id=str(asset.id), tag_id=str(pii.id),
        ))

        assert result.success is True
        assert pii.name in _tag_names(index.last_for(asset.id))

    def test_remove_from_an_asset_is_refused_without_assets_read_write(self, db_session, asset, pii):
        import asyncio
        ctx = _Tools.context(db_session, self.TAGS_ONLY)

        result = asyncio.run(RemoveTagFromEntityTool().execute(
            ctx, entity_type='asset', entity_id=str(asset.id), tag_id=str(pii.id),
        ))

        assert result.success is False
        assert 'assets' in result.error


class TestRetiredAssets:
    def test_a_retired_asset_loses_its_index_entry(self, manager, db_session, asset, pii, index):
        from src.db_models.assets import AssetDb
        db_session.query(AssetDb).filter_by(id=asset.id).update({'status': 'retired'})
        db_session.flush()

        manager.add_tag_to_entity(
            db_session, entity_id=str(asset.id), entity_type='asset', tag_id=pii.id,
            assigned_value=None, user_email='alice@example.com',
        )

        assert index.removed == [f'asset::{asset.id}']
        assert index.items == []
