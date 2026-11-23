"""Deleting a domain or a concept removes what is stored for it (#1478 follow-up).

As asset deletion already does (#1343): the notes, links and documents of the
entity go, uploaded document files are deleted from the volume once the
delete commits, imported Markdown documents leave the search index, and the
source files of imported documents are never deleted.
"""
import uuid
from pathlib import Path

import pytest

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.db_models.data_domains import DataDomain
from src.db_models.metadata import (
    DocumentMetadataDb, ImportedMarkdownFileDb, LinkMetadataDb, RichTextMetadataDb,
)

SOURCE = '/Volumes/main/docs/context/{word}.md'
MODELS = (RichTextMetadataDb, LinkMetadataDb, DocumentMetadataDb)


def _seed(db, entity_type: str, entity_id: str, word: str) -> str:
    """A note, a link, an uploaded and an imported document; returns the upload's path."""
    upload = f'/Volumes/c/s/v/uploads/{uuid.uuid4().hex}.txt'
    source = SOURCE.format(word=word)
    text = f'---\nx: 1\n---\nThe {word} is defined here.\n'
    imported = DocumentMetadataDb(
        entity_type=entity_type, entity_id=entity_id, title=f'Glossary {word}',
        original_filename=f'{word}.md', storage_path=source, source_path=source,
        content_hash='h',
    )
    db.add_all([
        RichTextMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Note',
                           content_markdown='Body'),
        LinkMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Link',
                       url='https://example.com'),
        DocumentMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Upload',
                           original_filename='u.txt', storage_path=upload),
        imported,
        ImportedMarkdownFileDb(source_path=source, content_hash='h', content_text=text),
    ])
    db.flush()
    app.state.metadata_manager.index_document(imported, text)
    return upload


def _counts(db, entity_type: str, entity_id: str) -> dict:
    return {
        model.__name__: db.query(model).filter(
            model.entity_type == entity_type, model.entity_id == entity_id).count()
        for model in MODELS
    }


def _document_hits(client, word: str) -> list:
    response = client.get('/api/search', params={'search_term': word})
    assert response.status_code == 200, response.text
    return [hit for hit in response.json() if hit['type'] == 'document']


@pytest.fixture
def files(mock_workspace_client):
    mock_workspace_client.files.delete.reset_mock()
    mock_workspace_client.files.delete.side_effect = None
    return mock_workspace_client.files


def _deleted_paths(files) -> set:
    return {call.args[0] for call in files.delete.call_args_list}


def test_deleting_a_domain_removes_its_metadata(client, db_session, files):
    domain = DataDomain(name='Customer', created_by='test@example.com')
    other = DataDomain(name='Orders', created_by='test@example.com')
    db_session.add_all([domain, other])
    db_session.flush()
    upload = _seed(db_session, 'data_domain', domain.id, 'zorbleflux')
    _seed(db_session, 'data_domain', other.id, 'quuxwidget')
    assert len(_document_hits(client, 'zorbleflux')) == 1

    response = client.delete(f'/api/data-domains/{domain.id}')

    assert response.status_code == 200, response.text
    assert _counts(db_session, 'data_domain', domain.id) == dict.fromkeys(
        (m.__name__ for m in MODELS), 0)
    assert _counts(db_session, 'data_domain', other.id) == {
        'RichTextMetadataDb': 1, 'LinkMetadataDb': 1, 'DocumentMetadataDb': 2}
    assert _deleted_paths(files) == {upload}  # never the imported source file
    assert _document_hits(client, 'zorbleflux') == []
    assert len(_document_hits(client, 'quuxwidget')) == 1


def test_deleting_a_parent_domain_removes_the_metadata_of_its_children(
        client, db_session, files):
    parent = DataDomain(name='Sales', created_by='test@example.com')
    db_session.add(parent)
    db_session.flush()
    child = DataDomain(name='Sales EU', parent_id=parent.id, created_by='test@example.com')
    db_session.add(child)
    db_session.flush()
    upload = _seed(db_session, 'data_domain', child.id, 'childword')

    response = client.delete(f'/api/data-domains/{parent.id}')

    assert response.status_code == 200, response.text
    assert sum(_counts(db_session, 'data_domain', child.id).values()) == 0
    assert _deleted_paths(files) == {upload}
    assert _document_hits(client, 'childword') == []


@pytest.fixture
def semantic_models_manager(client, db_session, tmp_path: Path):
    """A SemanticModelsManager on the test session (as test_knowledge_routes does)."""
    data_dir = tmp_path / 'sm_data'
    (data_dir / 'cache').mkdir(parents=True, exist_ok=True)
    (data_dir / 'taxonomies').mkdir(parents=True, exist_ok=True)
    previous = app.state.semantic_models_manager
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager('semantic_models_manager', manager)
    yield manager
    app.state.semantic_models_manager = previous
    set_app_state_manager('semantic_models_manager', previous)


def test_deleting_a_concept_removes_its_metadata(
        client, db_session, files, semantic_models_manager):
    collection = client.post('/api/knowledge/collections', json={
        'label': f'Coll {uuid.uuid4().hex[:8]}', 'collection_type': 'glossary',
        'scope_level': 'enterprise',
    })
    assert collection.status_code == 200, collection.text
    collection_iri = collection.json()['iri']
    client.post('/api/knowledge/concepts', json={
        'collection_iri': collection_iri, 'label': 'Doomed',
    }).raise_for_status()
    iri = f'{collection_iri}/doomed'
    upload = _seed(db_session, 'concept', iri, 'blorptastic')

    response = client.delete('/api/knowledge/concepts/by-iri', params={'iri': iri})

    assert response.status_code == 200, response.text
    assert sum(_counts(db_session, 'concept', iri).values()) == 0
    assert _deleted_paths(files) == {upload}
    assert _document_hits(client, 'blorptastic') == []


def _stored_texts(db, word: str) -> int:
    return db.query(ImportedMarkdownFileDb).filter(
        ImportedMarkdownFileDb.source_path == SOURCE.format(word=word)).count()


def test_deleting_a_collection_keeps_the_source_files_of_its_concepts_documents(
        client, db_session, files, semantic_models_manager):
    collection = client.post('/api/knowledge/collections', json={
        'label': f'Coll {uuid.uuid4().hex[:8]}', 'collection_type': 'glossary',
        'scope_level': 'enterprise',
    })
    assert collection.status_code == 200, collection.text
    collection_iri = collection.json()['iri']
    client.post('/api/knowledge/concepts', json={
        'collection_iri': collection_iri, 'label': 'Swept',
    }).raise_for_status()
    iri = f'{collection_iri}/swept'
    upload = _seed(db_session, 'concept', iri, 'plinkerdoo')
    assert len(_document_hits(client, 'plinkerdoo')) == 1

    response = client.delete(f'/api/knowledge/collections/{collection_iri}')

    assert response.status_code == 200, response.text
    assert sum(_counts(db_session, 'concept', iri).values()) == 0
    assert _deleted_paths(files) == {upload}  # never the imported source file
    assert _document_hits(client, 'plinkerdoo') == []
    assert _stored_texts(db_session, 'plinkerdoo') == 0


def test_imported_documents_leave_search_only_once_the_delete_commits(client, db_session):
    domain = DataDomain(name='Pending', created_by='test@example.com')
    db_session.add(domain)
    db_session.flush()
    _seed(db_session, 'data_domain', domain.id, 'snorkelwax')

    app.state.metadata_manager.remove_all_for_entity(
        db_session, entity_type='data_domain', entity_id=domain.id)

    # Not committed yet: a failed commit would leave the rows, so the hit stays.
    assert len(_document_hits(client, 'snorkelwax')) == 1
    db_session.commit()
    assert _document_hits(client, 'snorkelwax') == []


def test_a_rolled_back_delete_keeps_the_documents_in_search(client, db_session):
    domain = DataDomain(name='Kept', created_by='test@example.com')
    db_session.add(domain)
    db_session.flush()
    _seed(db_session, 'data_domain', domain.id, 'glimmerfoot')
    [doc_id] = [d.id for d in db_session.query(DocumentMetadataDb).filter(
        DocumentMetadataDb.entity_id == domain.id, DocumentMetadataDb.source_path.isnot(None))]
    assert f'document::{doc_id}' in {item.id for item in app.state.search_manager.index}

    app.state.metadata_manager.remove_all_for_entity(
        db_session, entity_type='data_domain', entity_id=domain.id)
    db_session.rollback()  # the delete's transaction fails: its rows come back
    db_session.add(DataDomain(name='Later', created_by='test@example.com'))
    db_session.commit()  # a later commit on the same session unindexes nothing

    # (The index itself: the rollback also undid this test's rows.)
    assert f'document::{doc_id}' in {item.id for item in app.state.search_manager.index}


def test_a_rolled_back_savepoint_keeps_its_documents_in_search(client, db_session):
    """As when an asset's delete savepoint fails and the cascade goes on to commit."""
    domain = DataDomain(name='Saved', created_by='test@example.com')
    gone = DataDomain(name='Gone', created_by='test@example.com')
    db_session.add_all([domain, gone])
    db_session.flush()
    _seed(db_session, 'data_domain', domain.id, 'wobblequark')
    _seed(db_session, 'data_domain', gone.id, 'fizzlebrook')
    manager = app.state.metadata_manager

    with db_session.begin_nested():  # a sibling savepoint, released
        manager.remove_all_for_entity(db_session, entity_type='data_domain', entity_id=gone.id)
    savepoint = db_session.begin_nested()
    manager.remove_all_for_entity(db_session, entity_type='data_domain', entity_id=domain.id)
    savepoint.rollback()
    db_session.commit()

    assert len(_document_hits(client, 'wobblequark')) == 1
    assert _document_hits(client, 'fizzlebrook') == []
