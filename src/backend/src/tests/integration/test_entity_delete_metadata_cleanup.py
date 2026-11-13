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
from src.db_models.metadata import DocumentMetadataDb, LinkMetadataDb, RichTextMetadataDb

SOURCE = '/Volumes/main/docs/context/glossary.md'
MODELS = (RichTextMetadataDb, LinkMetadataDb, DocumentMetadataDb)


def _seed(db, entity_type: str, entity_id: str, word: str) -> str:
    """A note, a link, an uploaded and an imported document; returns the upload's path."""
    upload = f'/Volumes/c/s/v/uploads/{uuid.uuid4().hex}.txt'
    imported = DocumentMetadataDb(
        entity_type=entity_type, entity_id=entity_id, title=f'Glossary {word}',
        original_filename='glossary.md', storage_path=SOURCE, source_path=SOURCE,
        content_hash='h', content_text=f'---\nx: 1\n---\nThe {word} is defined here.\n',
    )
    db.add_all([
        RichTextMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Note',
                           content_markdown='Body'),
        LinkMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Link',
                       url='https://example.com'),
        DocumentMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Upload',
                           original_filename='u.txt', storage_path=upload),
        imported,
    ])
    db.flush()
    app.state.metadata_manager.index_document(imported)
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
