"""A data domain's tags and their values are saved through TagsManager on create and update."""

import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest
from fastapi import HTTPException

from src.controller.data_domains_manager import DataDomainManager
from src.controller.tags_manager import TagsManager
from src.db_models.data_domains import DataDomain
from src.db_models.tags import EntityTagAssociationDb, TagDb
from src.models.data_domains import DataDomainCreate, DataDomainUpdate
from src.models.tags import AssignedTagCreate
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.tags_repository import tag_namespace_repo

USER = 'admin@example.com'


@pytest.fixture
def manager():
    return DataDomainManager(repository=data_domain_repo, tags_manager=TagsManager())


@pytest.fixture
def tags(db_session):
    namespace = tag_namespace_repo.get_or_create_default_namespace(db_session, user_email=USER)
    suffix = uuid.uuid4().hex[:8]
    free = TagDb(name=f'owner_{suffix}', namespace_id=namespace.id, status='active')
    classified = TagDb(
        name=f'classification_{suffix}', namespace_id=namespace.id, status='active',
        possible_values=['public', 'confidential'],
    )
    db_session.add_all([free, classified])
    db_session.flush()
    return {'free': free, 'classified': classified}


def _fqn(tag: TagDb) -> str:
    return f'default/{tag.name}'


def _stored(db_session, domain_id: str) -> list[EntityTagAssociationDb]:
    return (
        db_session.query(EntityTagAssociationDb)
        .filter_by(entity_id=str(domain_id), entity_type='data_domain')
        .all()
    )


def _values(read) -> dict[str, str | None]:
    return {t.tag_name: t.assigned_value for t in read.tags}


class TestCreateSavesTags:
    def test_create_saves_tags_with_values(self, manager, db_session, tags):
        read = manager.create_domain(
            db_session,
            DataDomainCreate(
                name=f'Sales {uuid.uuid4().hex[:6]}',
                tags=[
                    AssignedTagCreate(tag_fqn=_fqn(tags['free']), assigned_value='team-a'),
                    AssignedTagCreate(tag_fqn=_fqn(tags['classified']), assigned_value='public'),
                ],
            ),
            current_user_id=USER,
        )

        assert _values(read) == {tags['free'].name: 'team-a', tags['classified'].name: 'public'}
        assert len(_stored(db_session, read.id)) == 2

    def test_create_without_tags_assigns_none(self, manager, db_session, tags):
        read = manager.create_domain(
            db_session, DataDomainCreate(name=f'Plain {uuid.uuid4().hex[:6]}'), current_user_id=USER,
        )

        assert read.tags == []
        assert _stored(db_session, read.id) == []

    def test_create_refuses_a_value_outside_the_list_and_writes_nothing(self, manager, db_session, tags):
        name = f'Refused {uuid.uuid4().hex[:6]}'

        with pytest.raises(HTTPException) as err:
            manager.create_domain(
                db_session,
                DataDomainCreate(
                    name=name,
                    tags=[AssignedTagCreate(tag_fqn=_fqn(tags['classified']), assigned_value='secret')],
                ),
                current_user_id=USER,
            )

        assert err.value.status_code == 422
        assert err.value.detail['code'] == 'tag_value_not_allowed'
        assert db_session.query(DataDomain).filter_by(name=name).count() == 0


class TestUpdateSavesTags:
    @pytest.fixture
    def domain(self, manager, db_session, tags):
        return manager.create_domain(
            db_session,
            DataDomainCreate(
                name=f'Domain {uuid.uuid4().hex[:6]}',
                tags=[AssignedTagCreate(tag_fqn=_fqn(tags['classified']), assigned_value='public')],
            ),
            current_user_id=USER,
        )

    def test_omitted_tags_keep_the_stored_tags_and_values(self, manager, db_session, domain):
        read = manager.update_domain(
            db_session, domain.id, DataDomainUpdate(description='new text'), current_user_id=USER,
        )

        assert read.description == 'new text'
        assert [t.assigned_value for t in read.tags] == ['public']

    def test_empty_list_clears_the_tags(self, manager, db_session, domain):
        read = manager.update_domain(
            db_session, domain.id, DataDomainUpdate(tags=[]), current_user_id=USER,
        )

        assert read.tags == []
        assert _stored(db_session, domain.id) == []

    def test_a_new_list_replaces_the_tags_and_values(self, manager, db_session, tags, domain):
        read = manager.update_domain(
            db_session, domain.id,
            DataDomainUpdate(tags=[AssignedTagCreate(tag_fqn=_fqn(tags['classified']), assigned_value='confidential')]),
            current_user_id=USER,
        )

        assert _values(read) == {tags['classified'].name: 'confidential'}

    def test_refused_value_keeps_the_stored_tags(self, manager, db_session, tags, domain):
        with pytest.raises(HTTPException) as err:
            manager.update_domain(
                db_session, domain.id,
                DataDomainUpdate(tags=[AssignedTagCreate(tag_fqn=_fqn(tags['classified']), assigned_value='secret')]),
                current_user_id=USER,
            )

        assert err.value.status_code == 422
        assert err.value.detail['code'] == 'tag_value_not_allowed'
        stored = _stored(db_session, domain.id)
        assert [a.assigned_value for a in stored] == ['public']

    def test_resaving_a_stored_value_the_list_no_longer_allows_is_kept(self, manager, db_session, tags, domain):
        """A value stored before the list was narrowed is not re-checked on an unchanged save."""
        tags['classified'].possible_values = ['confidential', 'restricted']
        db_session.flush()

        read = manager.update_domain(
            db_session, domain.id,
            DataDomainUpdate(tags=[AssignedTagCreate(tag_fqn=_fqn(tags['classified']), assigned_value='public')]),
            current_user_id=USER,
        )

        assert [t.assigned_value for t in read.tags] == ['public']

    def test_a_different_value_outside_the_list_is_still_refused(self, manager, db_session, tags, domain):
        tags['classified'].possible_values = ['confidential', 'restricted']
        db_session.flush()

        with pytest.raises(HTTPException) as err:
            manager.update_domain(
                db_session, domain.id,
                DataDomainUpdate(tags=[AssignedTagCreate(tag_fqn=_fqn(tags['classified']), assigned_value='public-2')]),
                current_user_id=USER,
            )

        assert err.value.status_code == 422


class TestTagChangeLog:
    def _tag_set_entries(self, db_session, domain_id):
        from src.db_models.change_log import ChangeLogDb
        return (
            db_session.query(ChangeLogDb)
            .filter_by(entity_type='data_domain', entity_id=str(domain_id), action='TAGS_SET')
            .count()
        )

    def test_saving_unchanged_tags_writes_no_tags_set_entry(self, manager, db_session, tags):
        domain = manager.create_domain(
            db_session,
            DataDomainCreate(
                name=f'Logged {uuid.uuid4().hex[:6]}',
                tags=[AssignedTagCreate(tag_fqn=_fqn(tags['free']), assigned_value='team-a')],
            ),
            current_user_id=USER,
        )
        before = self._tag_set_entries(db_session, domain.id)

        manager.update_domain(
            db_session, domain.id,
            DataDomainUpdate(
                description='text only',
                tags=[AssignedTagCreate(tag_fqn=_fqn(tags['free']), assigned_value='team-a')],
            ),
            current_user_id=USER,
        )

        assert self._tag_set_entries(db_session, domain.id) == before

    def test_changing_a_value_writes_a_tags_set_entry(self, manager, db_session, tags):
        domain = manager.create_domain(
            db_session,
            DataDomainCreate(
                name=f'Logged {uuid.uuid4().hex[:6]}',
                tags=[AssignedTagCreate(tag_fqn=_fqn(tags['free']), assigned_value='team-a')],
            ),
            current_user_id=USER,
        )
        before = self._tag_set_entries(db_session, domain.id)

        manager.update_domain(
            db_session, domain.id,
            DataDomainUpdate(tags=[AssignedTagCreate(tag_fqn=_fqn(tags['free']), assigned_value='team-b')]),
            current_user_id=USER,
        )

        assert self._tag_set_entries(db_session, domain.id) == before + 1
