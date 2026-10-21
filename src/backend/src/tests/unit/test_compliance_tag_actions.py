"""Compliance DSL tag actions (ASSIGN_TAG / REMOVE_TAG) write real tag associations."""

import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.common.compliance_actions import ActionContext, AssignTagAction, RemoveTagAction
from src.controller.compliance_manager import ComplianceManager, TagsManagerTagAdapter
from src.db_models.change_log import ChangeLogDb
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.tags import EntityTagAssociationDb, TagDb
from src.repositories.tags_repository import entity_tag_repo, tag_namespace_repo, tag_repo


@pytest.fixture
def tag(db_session):
    namespace = tag_namespace_repo.get_or_create_default_namespace(
        db_session, user_email='admin@example.com'
    )
    tag = TagDb(name=f'review_{uuid.uuid4().hex[:8]}', namespace_id=namespace.id, status='active')
    db_session.add(tag)
    db_session.flush()
    return tag


def _context(adapter, entity_type='data_product', entity_id='prod-1') -> ActionContext:
    return ActionContext(
        entity={'type': entity_type, 'id': entity_id, 'name': 'Orders'},
        entity_type=entity_type,
        entity_id=entity_id,
        rule_id='rule-1',
        rule_name='Test rule',
        passed=False,
        tag_manager=adapter,
    )


def _associations(db, entity_type, entity_id):
    return (
        db.query(EntityTagAssociationDb)
        .filter_by(entity_type=entity_type, entity_id=entity_id)
        .all()
    )


class TestTagsManagerTagAdapter:
    def test_assign_tag_writes_association_and_change_log_without_commit(self, db_session, tag):
        adapter = TagsManagerTagAdapter(db_session, user_email='steward@example.com')

        with patch.object(db_session, 'commit') as commit:
            result = AssignTagAction(tag.name, 'needed').execute(_context(adapter))

        assert result.success is True
        commit.assert_not_called()
        [assoc] = _associations(db_session, 'data_product', 'prod-1')
        assert assoc.tag_id == tag.id
        assert assoc.assigned_value == 'needed'
        assert assoc.assigned_by == 'steward@example.com'
        log = db_session.query(ChangeLogDb).filter_by(entity_id='prod-1', action='TAG_ASSIGN').one()
        assert log.entity_type == 'data_product'

    def test_domain_entities_are_tagged_as_data_domain(self, db_session, tag):
        adapter = TagsManagerTagAdapter(db_session)

        result = AssignTagAction(tag.name, 'x').execute(
            _context(adapter, entity_type='domain', entity_id='dom-1')
        )

        assert result.success is True
        assert len(_associations(db_session, 'data_domain', 'dom-1')) == 1
        assert _associations(db_session, 'domain', 'dom-1') == []

    @pytest.mark.parametrize(
        'entity_type', ['table', 'schema', 'catalog', 'view', 'function', 'volume', 'review']
    )
    def test_unsupported_entity_types_fail_explicitly(self, db_session, tag, entity_type):
        adapter = TagsManagerTagAdapter(db_session)

        result = AssignTagAction(tag.name, 'x').execute(
            _context(adapter, entity_type=entity_type, entity_id='main.sales.orders')
        )

        assert result.success is False
        assert f"not supported for '{entity_type}'" in result.error
        assert (
            db_session.query(EntityTagAssociationDb)
            .filter_by(entity_id='main.sales.orders')
            .count()
            == 0
        )

    def test_unknown_tag_fails_with_clear_error(self, db_session):
        adapter = TagsManagerTagAdapter(db_session)

        result = AssignTagAction('does_not_exist', 'x').execute(_context(adapter))

        assert result.success is False
        assert "Tag 'does_not_exist' not found" in result.error

    def test_entity_without_id_is_rejected(self, db_session, tag):
        adapter = TagsManagerTagAdapter(db_session)

        result = AssignTagAction(tag.name, 'x').execute(_context(adapter, entity_id='unknown'))

        assert result.success is False
        assert 'Entity has no id' in result.error
        assert _associations(db_session, 'data_product', 'unknown') == []

    def test_failed_write_is_rolled_back_alone_and_session_stays_usable(self, db_session, tag):
        adapter = TagsManagerTagAdapter(db_session)
        AssignTagAction(tag.name, 'first').execute(_context(adapter, entity_id='prod-ok'))

        def failing_add(db, **kwargs):
            db.add(
                EntityTagAssociationDb(
                    entity_id=kwargs['entity_id'],
                    entity_type=kwargs['entity_type'],
                    tag_id=kwargs['tag_id'],
                )
            )
            db.flush()
            raise SQLAlchemyError('boom')

        with patch.object(entity_tag_repo, 'add_tag_to_entity', side_effect=failing_add):
            result = AssignTagAction(tag.name, 'second').execute(
                _context(adapter, entity_id='prod-bad')
            )

        assert result.success is False
        # The failing write left nothing behind, the earlier one survived, and the session works.
        assert _associations(db_session, 'data_product', 'prod-bad') == []
        assert len(_associations(db_session, 'data_product', 'prod-ok')) == 1
        assert (
            AssignTagAction(tag.name, 'third')
            .execute(_context(adapter, entity_id='prod-next'))
            .success
        )

    def test_tag_lookup_is_cached_per_adapter(self, db_session, tag):
        adapter = TagsManagerTagAdapter(db_session)

        with patch.object(
            tag_repo, 'get_by_fully_qualified_name', wraps=tag_repo.get_by_fully_qualified_name
        ) as lookup:
            for entity_id in ('p1', 'p2', 'p3'):
                assert (
                    AssignTagAction(tag.name, 'x')
                    .execute(_context(adapter, entity_id=entity_id))
                    .success
                )

        assert lookup.call_count == 1

    def test_remove_tag_removes_and_is_idempotent(self, db_session, tag):
        adapter = TagsManagerTagAdapter(db_session)
        AssignTagAction(tag.name, 'x').execute(_context(adapter))

        assert RemoveTagAction(tag.name).execute(_context(adapter)).success
        assert _associations(db_session, 'data_product', 'prod-1') == []
        # Removing again is a no-op, not an error, and logs no second removal.
        assert RemoveTagAction(tag.name).execute(_context(adapter)).success
        assert (
            db_session.query(ChangeLogDb).filter_by(entity_id='prod-1', action='TAG_REMOVE').count()
            == 1
        )


class TestRunPolicyInlineTagActions:
    def test_run_tags_supported_entities_and_survives_unsupported_ones(self, db_session, tag):
        policy = CompliancePolicyDb(
            id=str(uuid.uuid4()),
            name='Retired products only',
            rule=(
                "MATCH (obj:Object)\n"
                "ASSERT obj.status = 'retired'\n"
                f"ON_FAIL ASSIGN_TAG {tag.name}: 'needed'"
            ),
            is_active=True,
        )
        db_session.add(policy)
        db_session.flush()

        iterator = MagicMock()
        iterator.iterate.return_value = iter(
            [
                {'type': 'data_product', 'id': 'prod-1', 'name': 'Orders', 'status': 'active'},
                {'type': 'table', 'id': 'main.sales.orders', 'name': 'orders', 'status': 'active'},
                {'type': 'domain', 'id': 'dom-1', 'name': 'Sales', 'status': 'active'},
            ]
        )

        with (
            patch(
                'src.controller.compliance_manager.create_entity_iterator', return_value=iterator
            ),
            patch('src.common.workspace_client.get_workspace_client', return_value=MagicMock()),
        ):
            run = ComplianceManager().run_policy_inline(
                db_session, policy=policy, current_user='steward@example.com'
            )

        assert run.status == 'succeeded'
        assert run.failure_count == 3
        assert (
            _associations(db_session, 'data_product', 'prod-1')[0].assigned_by
            == 'steward@example.com'
        )
        assert len(_associations(db_session, 'data_domain', 'dom-1')) == 1
        assert (
            db_session.query(EntityTagAssociationDb)
            .filter_by(entity_id='main.sales.orders')
            .count()
            == 0
        )
