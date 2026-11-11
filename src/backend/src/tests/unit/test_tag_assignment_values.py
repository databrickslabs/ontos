"""Saving an entity's tags keeps the values already assigned to them (#1420)."""

import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest

from src.controller.tags_manager import TagsManager
from src.db_models.tags import EntityTagAssociationDb, TagDb
from src.models.tags import AssignedTagCreate
from src.repositories.tags_repository import entity_tag_repo, tag_namespace_repo

ENTITY = {'entity_id': 'prod-1', 'entity_type': 'data_product'}


@pytest.fixture
def manager():
    return TagsManager()


@pytest.fixture
def tags(db_session):
    namespace = tag_namespace_repo.get_or_create_default_namespace(db_session, user_email='admin@example.com')
    made = []
    for prefix in ('classification', 'region'):
        tag = TagDb(name=f'{prefix}_{uuid.uuid4().hex[:8]}', namespace_id=namespace.id, status='active')
        db_session.add(tag)
        made.append(tag)
    db_session.flush()
    return made


def _fqn(tag: TagDb) -> str:
    return f'{tag.namespace.name}/{tag.name}'


def _assign(db_session, tag, value, by='workflow@system'):
    entity_tag_repo.add_tag_to_entity(
        db_session, tag_id=tag.id, assigned_value=value, assigned_by=by, **ENTITY,
    )
    db_session.commit()


def _stored(db_session, tag) -> EntityTagAssociationDb:
    return db_session.query(EntityTagAssociationDb).filter_by(tag_id=tag.id, **ENTITY).one()


class TestSetTagsKeepsValues:
    def test_fqn_only_save_by_another_user_keeps_the_value(self, manager, db_session, tags):
        """The tags panel and the entity forms send bare FQNs for tags that stay selected."""
        classification, region = tags
        _assign(db_session, classification, 'confidential')

        result = manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classification)),
                              AssignedTagCreate(tag_fqn=_fqn(region))],
            user_email='admin@example.com', **ENTITY,
        )

        by_name = {t.tag_name: t for t in result}
        assert by_name[classification.name].assigned_value == 'confidential'
        assert by_name[region.name].assigned_value is None
        assert _stored(db_session, classification).assigned_value == 'confidential'

    def test_unchanged_save_keeps_who_assigned_it(self, manager, db_session, tags):
        classification, _ = tags
        _assign(db_session, classification, 'confidential')

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classification))],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, classification).assigned_by == 'workflow@system'

    def test_explicit_none_keeps_the_value(self, manager, db_session, tags):
        """Payloads that went through model_dump carry assigned_value=None for every tag."""
        classification, _ = tags
        _assign(db_session, classification, 'confidential')

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_id=classification.id, assigned_value=None)],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, classification).assigned_value == 'confidential'

    def test_a_new_value_replaces_the_old_one(self, manager, db_session, tags):
        classification, _ = tags
        _assign(db_session, classification, 'confidential')

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classification), assigned_value='public')],
            user_email='admin@example.com', **ENTITY,
        )

        stored = _stored(db_session, classification)
        assert stored.assigned_value == 'public'
        assert stored.assigned_by == 'admin@example.com'

    def test_an_empty_string_clears_the_value(self, manager, db_session, tags):
        classification, _ = tags
        _assign(db_session, classification, 'confidential')

        result = manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classification), assigned_value='')],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, classification).assigned_value is None
        assert result[0].assigned_value is None

    def test_a_new_tag_with_an_empty_string_has_no_value(self, manager, db_session, tags):
        _, region = tags

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(region), assigned_value='')],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, region).assigned_value is None

    def test_tags_left_out_are_removed(self, manager, db_session, tags):
        classification, region = tags
        _assign(db_session, classification, 'confidential')

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(region))],
            user_email='admin@example.com', **ENTITY,
        )

        remaining = db_session.query(EntityTagAssociationDb).filter_by(**ENTITY).all()
        assert [a.tag_id for a in remaining] == [region.id]


class TestAddTagKeepsValues:
    def test_add_without_a_value_keeps_the_stored_one(self, manager, db_session, tags):
        """``tags:add`` without ``assigned_value`` re-adds the tag and keeps its value."""
        classification, _ = tags
        _assign(db_session, classification, 'confidential')

        result = manager.add_tag_to_entity(
            db_session, tag_id=classification.id, assigned_value=None,
            user_email='admin@example.com', **ENTITY,
        )

        assert result.assigned_value == 'confidential'
        assert _stored(db_session, classification).assigned_by == 'workflow@system'

    def test_add_with_a_value_sets_it(self, manager, db_session, tags):
        classification, _ = tags
        _assign(db_session, classification, 'confidential')

        result = manager.add_tag_to_entity(
            db_session, tag_id=classification.id, assigned_value='restricted',
            user_email='admin@example.com', **ENTITY,
        )

        assert result.assigned_value == 'restricted'
        assert _stored(db_session, classification).assigned_by == 'admin@example.com'
