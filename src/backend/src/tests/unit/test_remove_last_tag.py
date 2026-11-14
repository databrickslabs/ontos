"""Removing the last tag from a product or contract sticks (#1435).

An update with ``tags: []`` removes every tag; an update without ``tags``
keeps them. The product path returned early on an empty list, so the last
tag could never be removed.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

import pytest

from src.controller.data_products_manager import DataProductsManager
from src.controller.tags_manager import TagsManager
from src.db_models.data_products import DataProductDb
from src.db_models.tags import EntityTagAssociationDb, TagDb
from src.repositories.tags_repository import entity_tag_repo, tag_namespace_repo


@pytest.fixture
def tag(db_session):
    namespace = tag_namespace_repo.get_or_create_default_namespace(db_session, user_email='admin@example.com')
    tag = TagDb(name=f'pii_{uuid.uuid4().hex[:8]}', namespace_id=namespace.id, status='active')
    db_session.add(tag)
    db_session.flush()
    return tag


@pytest.fixture
def product(db_session, tag):
    pid = str(uuid.uuid4())
    db_session.add(DataProductDb(id=pid, status='draft', name='P'))
    db_session.commit()
    entity_tag_repo.add_tag_to_entity(
        db_session, tag_id=tag.id, entity_id=pid, entity_type='data_product',
        assigned_value='x', assigned_by='someone@example.com',
    )
    db_session.commit()
    return pid


def _tag_count(db_session, entity_id):
    return db_session.query(EntityTagAssociationDb).filter_by(
        entity_id=entity_id, entity_type='data_product',
    ).count()


@pytest.fixture
def manager(db_session):
    return DataProductsManager(db=db_session, tags_manager=TagsManager())


def test_empty_tag_list_removes_the_last_tag(manager, product, db_session):
    manager._assign_tags_to_product(product, [])

    assert _tag_count(db_session, product) == 0


def test_update_with_empty_tags_removes_them(manager, product, db_session):
    manager.update_product(product, {'tags': []}, db=db_session, user='u')

    assert _tag_count(db_session, product) == 0


def test_update_without_tags_keeps_them(manager, product, db_session):
    manager.update_product(product, {'description': {'purpose': 'p'}}, db=db_session, user='u')

    assert _tag_count(db_session, product) == 1


def test_unparseable_tags_do_not_wipe_the_existing_ones(manager, product, db_session):
    """Only an explicit empty list clears; a list whose entries can't be read keeps the tags."""
    manager._assign_tags_to_product(product, [{'not_a_tag_field': 1}])

    assert _tag_count(db_session, product) == 1


@pytest.fixture
def contract(db_session, tag):
    from src.db_models.data_contracts import DataContractDb
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name='C', version='1.0.0', status='draft', created_by='u'))
    db_session.commit()
    entity_tag_repo.add_tag_to_entity(
        db_session, tag_id=tag.id, entity_id=cid, entity_type='data_contract',
        assigned_value=None, assigned_by='someone@example.com',
    )
    db_session.commit()
    return cid


def _contract_tags(db_session, cid):
    return db_session.query(EntityTagAssociationDb).filter_by(entity_id=cid, entity_type='data_contract').count()


@pytest.fixture
def contracts_manager():
    from pathlib import Path
    from src.controller.data_contracts_manager import DataContractsManager
    return DataContractsManager(data_dir=Path('/tmp'), tags_manager=TagsManager())


def test_contract_update_with_empty_tags_removes_them(contracts_manager, contract, db_session):
    contracts_manager.update_contract_with_relations(db_session, contract, {'tags': []}, current_user='u')

    assert _contract_tags(db_session, contract) == 0


def test_contract_update_without_tags_keeps_them(contracts_manager, contract, db_session):
    contracts_manager.update_contract_with_relations(db_session, contract, {'name': 'C2'}, current_user='u')

    assert _contract_tags(db_session, contract) == 1


def test_contract_update_with_unreadable_tags_keeps_them(contracts_manager, contract, db_session):
    contracts_manager.update_contract_with_relations(db_session, contract, {'tags': [None, 7]}, current_user='u')

    assert _contract_tags(db_session, contract) == 1


def test_clearing_the_last_tag_is_logged(manager, product, db_session):
    from src.db_models.change_log import ChangeLogDb

    manager._assign_tags_to_product(product, [])

    entry = db_session.query(ChangeLogDb).filter_by(entity_id=product, action='TAGS_SET').one()
    assert 'Tags cleared' in (entry.details_json or '')


def test_clearing_an_untagged_entity_logs_nothing(db_session):
    from src.db_models.change_log import ChangeLogDb

    TagsManager().set_tags_for_entity(
        db_session, entity_id='untagged', entity_type='data_product', tags=[], user_email='u',
    )

    assert db_session.query(ChangeLogDb).filter_by(entity_id='untagged').count() == 0


def test_details_page_put_with_empty_tags_clears_them_on_reload(
    contracts_manager, contract, db_session,
):
    """The contract details page PUTs ``tags: []`` once the last tag is removed; the
    reloaded contract has no tags (the reported contract case, #1435)."""
    from src.models.data_contracts_api import DataContractUpdate
    from src.repositories.data_contracts_repository import data_contract_repo

    body = DataContractUpdate(**{'name': 'C', 'version': '1.0.0', 'status': 'draft', 'tags': []})
    contracts_manager.update_contract_with_relations(db_session, contract, body, current_user='u')
    db_session.expire_all()

    reloaded = contracts_manager._build_contract_api_model(
        db_session, data_contract_repo.get_with_all(db_session, id=contract),
    )
    assert reloaded.tags == []


def test_failed_tag_write_is_rolled_back_and_the_update_is_saved(
    contracts_manager, contract, db_session, monkeypatch,
):
    """A tag write that fails part-way leaves the stored tags as they were (its own
    savepoint is rolled back) and the rest of the contract update is still saved."""
    from src.db_models.data_contracts import DataContractDb

    def failing_write(db, *, entity_id, entity_type, tags, user_email, commit=True):
        db.query(EntityTagAssociationDb).filter_by(
            entity_id=entity_id, entity_type=entity_type,
        ).delete(synchronize_session=False)
        db.flush()
        raise RuntimeError('tag write failed')

    monkeypatch.setattr(contracts_manager._tags_manager, 'set_tags_for_entity', failing_write)

    contracts_manager.update_contract_with_relations(
        db_session, contract, {'tags': [], 'name': 'Renamed'}, current_user='u',
    )
    db_session.expire_all()

    assert _contract_tags(db_session, contract) == 1
    assert db_session.query(DataContractDb).filter_by(id=contract).one().name == 'Renamed'
