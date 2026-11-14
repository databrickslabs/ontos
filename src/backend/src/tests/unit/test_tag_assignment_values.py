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


class TestProjectReadsCarryTags:
    """Project reads must return the tags, or the edit dialog saves ``tags: []`` and clears them."""

    @pytest.fixture
    def project(self, db_session):
        from src.db_models.projects import ProjectDb
        db_project = ProjectDb(
            id=str(uuid.uuid4()), name=f'p-{uuid.uuid4().hex[:6]}', created_by='t', updated_by='t',
            extra_metadata='{}',
        )
        db_session.add(db_project)
        db_session.commit()
        return db_project

    def _tag_project(self, db_session, project, tag):
        entity_tag_repo.add_tag_to_entity(
            db_session, entity_id=project.id, entity_type='project', tag_id=tag.id,
            assigned_value='confidential', assigned_by='workflow@system',
        )
        db_session.commit()

    def test_get_by_id_returns_tags_with_values(self, db_session, tags, project):
        from src.controller.projects_manager import ProjectsManager
        self._tag_project(db_session, project, tags[0])

        read = ProjectsManager().get_project_by_id(db_session, project.id)

        assert [(t.tag_id, t.assigned_value) for t in read.tags] == [(tags[0].id, 'confidential')]

    def test_list_returns_tags_with_values(self, db_session, tags, project):
        from src.controller.projects_manager import ProjectsManager
        self._tag_project(db_session, project, tags[0])

        listed = ProjectsManager().get_all_projects(db_session, is_admin=True, limit=10_000)

        by_id = {p.id: p for p in listed}
        assert [(t.tag_id, t.assigned_value) for t in by_id[project.id].tags] == [(tags[0].id, 'confidential')]

    def test_list_falls_back_to_one_by_one_when_the_batch_fails(self, db_session, tags, project, monkeypatch):
        """A listed project without its tags would be saved with ``tags: []``."""
        from src.controller.projects_manager import ProjectsManager
        self._tag_project(db_session, project, tags[0])
        manager = ProjectsManager()

        def boom(*args, **kwargs):
            raise RuntimeError('batch failed')

        monkeypatch.setattr(manager.tags_manager, 'list_assigned_tags_for_entities', boom)
        listed = manager.get_all_projects(db_session, is_admin=True, limit=10_000)

        by_id = {p.id: p for p in listed}
        assert [t.tag_id for t in by_id[project.id].tags] == [tags[0].id]


class TestAddTagChangeLog:
    def _entries(self, db_session):
        from src.db_models.change_log import ChangeLogDb
        return (
            db_session.query(ChangeLogDb)
            .filter_by(entity_type=ENTITY['entity_type'], entity_id=ENTITY['entity_id'], action='TAG_ASSIGN')
            .all()
        )

    def test_re_adding_without_a_value_writes_no_entry(self, manager, db_session, tags):
        classification, _ = tags
        _assign(db_session, classification, 'confidential')
        before = len(self._entries(db_session))

        manager.add_tag_to_entity(
            db_session, tag_id=classification.id, assigned_value=None, user_email='admin@example.com', **ENTITY,
        )

        assert len(self._entries(db_session)) == before

    def test_a_value_change_logs_the_stored_value(self, manager, db_session, tags):
        import json
        classification, _ = tags
        _assign(db_session, classification, 'confidential')

        manager.add_tag_to_entity(
            db_session, tag_id=classification.id, assigned_value='public', user_email='admin@example.com', **ENTITY,
        )

        latest = self._entries(db_session)[-1]
        details = json.loads(latest.details_json)
        assert details['assigned_value'] == 'public'


class TestPossibleValues:
    """A value must be one of the tag's possible_values when the tag defines them (#1421)."""

    @pytest.fixture
    def classified(self, db_session):
        namespace = tag_namespace_repo.get_or_create_default_namespace(db_session, user_email='admin@example.com')
        tag = TagDb(
            name=f'classification_{uuid.uuid4().hex[:8]}', namespace_id=namespace.id, status='active',
            possible_values=['public', 'confidential'],
        )
        db_session.add(tag)
        db_session.flush()
        return tag

    def test_set_accepts_a_listed_value(self, manager, db_session, classified):
        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classified), assigned_value='confidential')],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, classified).assigned_value == 'confidential'

    def test_set_refuses_a_value_outside_the_list(self, manager, db_session, classified):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as err:
            manager.set_tags_for_entity(
                db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classified), assigned_value='secret')],
                user_email='admin@example.com', **ENTITY,
            )

        assert err.value.status_code == 422
        assert err.value.detail == {
            'code': 'tag_value_not_allowed',
            'message': f"Value 'secret' is not one of the possible values of tag '{classified.name}'.",
            'params': {'tag': classified.name, 'value': 'secret', 'allowed': ['public', 'confidential']},
        }
        assert db_session.query(EntityTagAssociationDb).filter_by(**ENTITY).count() == 0

    def test_refused_save_leaves_existing_values_alone(self, manager, db_session, classified):
        from fastapi import HTTPException

        _assign(db_session, classified, 'public')

        with pytest.raises(HTTPException):
            manager.set_tags_for_entity(
                db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classified), assigned_value='secret')],
                user_email='admin@example.com', **ENTITY,
            )

        assert _stored(db_session, classified).assigned_value == 'public'

    def test_untouched_value_outside_the_list_is_kept(self, manager, db_session, classified):
        """A stored value from before possible_values existed is not re-checked on an unrelated save."""
        _assign(db_session, classified, 'secret')

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classified))],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, classified).assigned_value == 'secret'

    def test_empty_string_clears_without_a_check(self, manager, db_session, classified):
        _assign(db_session, classified, 'public')

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(classified), assigned_value='')],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, classified).assigned_value is None

    def test_add_refuses_a_value_outside_the_list(self, manager, db_session, classified):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as err:
            manager.add_tag_to_entity(
                db_session, tag_id=classified.id, assigned_value='secret',
                user_email='admin@example.com', **ENTITY,
            )

        assert err.value.status_code == 422

    def test_add_accepts_a_listed_value(self, manager, db_session, classified):
        result = manager.add_tag_to_entity(
            db_session, tag_id=classified.id, assigned_value='public',
            user_email='admin@example.com', **ENTITY,
        )

        assert result.assigned_value == 'public'

    def test_free_text_tag_accepts_any_value(self, manager, db_session, tags):
        _, region = tags

        manager.set_tags_for_entity(
            db_session, tags=[AssignedTagCreate(tag_fqn=_fqn(region), assigned_value='anything at all')],
            user_email='admin@example.com', **ENTITY,
        )

        assert _stored(db_session, region).assigned_value == 'anything at all'

    def test_check_refuses_an_out_of_list_value_given_as_a_dict(self, manager, db_session, classified):
        """Product and contract payloads carry raw dicts; the check runs before their writes."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as err:
            manager.check_assigned_values(
                db_session, [{'tag_fqn': _fqn(classified), 'assigned_value': 'secret'}],
            )

        assert err.value.status_code == 422

    def test_check_passes_fqn_strings_and_listed_values(self, manager, db_session, classified):
        manager.check_assigned_values(db_session, [_fqn(classified), {'tag_fqn': _fqn(classified), 'assigned_value': 'public'}])
