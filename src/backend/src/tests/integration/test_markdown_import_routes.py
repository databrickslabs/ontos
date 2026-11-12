"""Importing Markdown files from a volume as documents (#1478).

``POST /api/metadata/markdown-import`` reads the ``.md`` files of a volume
folder and adds each one as a document on the domain, assets and concepts its
front matter names. A re-run updates only the files that changed; files that
name no entity are reported as unlinked. The documents are the ones the
documents panel lists, and search finds their text.
"""
import io
import uuid
from types import SimpleNamespace

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.files import DirectoryEntry
from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from src.app import app
from src.controller.metadata_manager import MetadataManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.change_log import ChangeLogDb
from src.db_models.data_domains import DataDomain
from src.db_models.metadata import DocumentMetadataDb

ROOT = '/Volumes/main/docs/context'
CUSTOMER_IRI = 'http://example.org/ontology#Customer'

DOMAIN_FILE = """---
title: Customer domain overview
domain: Customer
---
# Overview

A customer is a person with at least one zorbleflux order.
"""

TERMS_FILE = """---
assets: [main.crm.customers]
concepts: [Customer]
---
# Customer terms

Churn means no order in 90 days.
"""

LOOSE_FILE = """# Loose notes

No front matter here.
"""


@pytest.fixture
def domain(db_session):
    row = DataDomain(name='Customer', description='Customer data', created_by='test@example.com')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def asset(db_session):
    asset_type = AssetTypeDb(name=f'Table {uuid.uuid4().hex[:8]}', category='data')
    db_session.add(asset_type)
    db_session.flush()
    row = AssetDb(name='customers', asset_type_id=asset_type.id, platform='databricks',
                  location='main.crm.customers')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def concept(client):
    graph = app.state.semantic_models_manager._graph
    triples = [
        (URIRef(CUSTOMER_IRI), RDF.type, OWL.Class),
        (URIRef(CUSTOMER_IRI), RDFS.label, Literal('Customer')),
    ]
    for triple in triples:
        graph.add(triple)
    yield CUSTOMER_IRI
    for triple in triples:
        graph.remove(triple)


@pytest.fixture
def volume(mock_workspace_client):
    """A fake volume: {path: text}. Folders are derived from the file paths."""
    files = {
        f'{ROOT}/domain.md': DOMAIN_FILE,
        f'{ROOT}/glossary/terms.md': TERMS_FILE,
        f'{ROOT}/glossary/loose.md': LOOSE_FILE,
        f'{ROOT}/glossary/image.png': 'not markdown',
    }

    def list_directory_contents(folder):
        if folder == '/Volumes/main/docs/missing':
            raise NotFound('no such folder')
        if folder == '/Volumes/main/secret/stuff':
            raise PermissionDenied('no READ VOLUME')
        children = {}
        for path, text in files.items():
            if not path.startswith(folder + '/'):
                continue
            first = path[len(folder) + 1:].split('/')[0]
            child = f'{folder}/{first}'
            children[child] = DirectoryEntry(
                path=child, name=first, is_directory=child != path,
                file_size=len(text.encode()) if child == path else None,
            )
        return list(children.values())

    def download(path):
        return SimpleNamespace(contents=io.BytesIO(files[path].encode('utf-8')))

    mock_workspace_client.files.list_directory_contents.side_effect = list_directory_contents
    mock_workspace_client.files.download.side_effect = download
    mock_workspace_client.files.delete.reset_mock()
    return files


def _import(client, path=ROOT):
    return client.post('/api/metadata/markdown-import', json={'path': path})


def _by_path(body):
    return {entry['path']: entry for entry in body['files']}


def test_import_links_each_file_to_the_entities_its_front_matter_names(
        client, db_session, domain, asset, concept, volume):
    response = _import(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['added'], body['updated'], body['unchanged'], body['unlinked'],
            body['failed']) == (2, 0, 0, 1, 0)
    files = _by_path(body)
    assert set(files) == {f'{ROOT}/domain.md', f'{ROOT}/glossary/terms.md',
                          f'{ROOT}/glossary/loose.md'}
    assert files[f'{ROOT}/domain.md']['targets'] == [
        {'entity_type': 'data_domain', 'entity_id': domain.id, 'name': 'Customer'}]
    assert {(t['entity_type'], t['entity_id'])
            for t in files[f'{ROOT}/glossary/terms.md']['targets']} == {
        ('asset', str(asset.id)), ('concept', CUSTOMER_IRI)}
    assert files[f'{ROOT}/glossary/loose.md']['status'] == 'unlinked'

    # The documents panel lists them, with the source path.
    listed = client.get('/api/entities/data_domain/documents', params={'entity_id': domain.id})
    assert listed.status_code == 200, listed.text
    [doc] = listed.json()
    assert doc['title'] == 'Customer domain overview'
    assert doc['source_path'] == f'{ROOT}/domain.md'
    assert doc['original_filename'] == 'domain.md'
    for entity_type, entity_id in (('asset', str(asset.id)), ('concept', CUSTOMER_IRI)):
        listed = client.get(f'/api/entities/{entity_type}/documents',
                            params={'entity_id': entity_id})
        assert listed.status_code == 200, listed.text
        assert [d['title'] for d in listed.json()] == ['Customer terms']

    # The content is served from the stored Markdown, not the source volume.
    content = client.get(f"/api/documents/{doc['id']}/content")
    assert content.status_code == 200
    assert content.text == DOMAIN_FILE
    assert content.headers['content-type'].startswith('text/markdown')


def test_a_rerun_updates_only_the_changed_file(client, db_session, domain, asset, concept, volume):
    assert _import(client).status_code == 200
    volume[f'{ROOT}/domain.md'] = DOMAIN_FILE.replace('at least one', 'two or more')

    response = _import(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['added'], body['updated'], body['unchanged'], body['unlinked']) == (0, 1, 1, 1)
    files = _by_path(body)
    assert files[f'{ROOT}/domain.md']['status'] == 'updated'
    assert files[f'{ROOT}/glossary/terms.md']['status'] == 'unchanged'
    docs = db_session.query(DocumentMetadataDb).filter(
        DocumentMetadataDb.source_path == f'{ROOT}/domain.md').all()
    assert len(docs) == 1
    assert 'two or more' in docs[0].content_text
    updates = db_session.query(ChangeLogDb).filter(
        ChangeLogDb.entity_type == 'data_domain:document', ChangeLogDb.action == 'UPDATE').count()
    assert updates == 1


def test_a_file_without_a_known_target_is_unlinked(client, db_session, volume):
    # No domain, asset or concept exists: every file is unlinked, nothing is stored.
    response = _import(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body['added'], body['unlinked']) == (0, 3)
    unresolved = _by_path(body)[f'{ROOT}/glossary/terms.md']['unresolved']
    assert {(u['kind'], u['value'], u['reason']) for u in unresolved} == {
        ('asset', 'main.crm.customers', 'not_found'), ('concept', 'Customer', 'not_found')}
    assert db_session.query(DocumentMetadataDb).count() == 0


def test_search_finds_the_imported_text(client, domain, asset, concept, volume):
    assert _import(client).status_code == 200

    response = client.get('/api/search', params={'search_term': 'zorbleflux'})

    assert response.status_code == 200, response.text
    [hit] = [item for item in response.json() if item['type'] == 'document']
    assert hit['title'] == 'Customer domain overview'
    assert hit['link'] == f'/settings/data-domains/{domain.id}'


def test_deleting_the_asset_keeps_the_source_file(
        client, db_session, asset, volume, mock_workspace_client):
    assert _import(client).status_code == 200
    # Linked only through the asset's FQN; the concept isn't loaded here.
    assert db_session.query(DocumentMetadataDb).filter(
        DocumentMetadataDb.entity_id == str(asset.id)).count() == 1

    response = client.delete(f'/api/assets/{asset.id}')

    assert response.status_code == 200, response.text
    assert db_session.query(DocumentMetadataDb).filter(
        DocumentMetadataDb.entity_id == str(asset.id)).count() == 0
    mock_workspace_client.files.delete.assert_not_called()


@pytest.mark.parametrize('path, status, code', [
    ('/tmp/docs', 400, 'markdown_import_path_invalid'),
    ('/Volumes/main/docs', 400, 'markdown_import_path_invalid'),
    (f'{ROOT}/../other', 400, 'markdown_import_path_invalid'),
    ('/Volumes/main/docs/missing', 404, 'markdown_import_path_not_found'),
    ('/Volumes/main/secret/stuff', 403, 'markdown_import_access_denied'),
])
def test_a_bad_path_answers_a_coded_error(client, volume, path, status, code):
    response = _import(client, path)

    assert response.status_code == status, response.text
    detail = response.json()['detail']
    assert detail['code'] == code
    assert detail['params']['path']


def test_needs_write_access_to_the_documents_feature(client, volume, mock_test_user):
    mock_test_user.groups = []

    response = _import(client)

    assert response.status_code == 403


def test_the_import_reads_the_volume_as_the_user(monkeypatch):
    """The route's client is the on-behalf-of one, so users import only files they can read."""
    from src.routes import metadata_routes

    sentinel = object()
    monkeypatch.setattr(metadata_routes, 'get_obo_workspace_client', lambda request: sentinel)
    assert metadata_routes._user_workspace_client(SimpleNamespace()) is sentinel


def test_imported_documents_are_in_the_search_index_at_startup(client, db_session, domain):
    db_session.add(DocumentMetadataDb(
        entity_type='data_domain', entity_id=domain.id, title='Glossary',
        original_filename='g.md', storage_path=f'{ROOT}/g.md', source_path=f'{ROOT}/g.md',
        content_hash='x', content_text='---\ndomain: Customer\n---\nChurn is defined here.\n',
    ))
    db_session.add(DocumentMetadataDb(
        entity_type='data_domain', entity_id=domain.id, title='Uploaded',
        original_filename='u.pdf', storage_path='/Volumes/c/s/v/u.pdf',
    ))
    db_session.flush()

    items = MetadataManager().get_search_index_items()

    assert [(item.title, item.description) for item in items] == [
        ('Glossary', 'Churn is defined here.\n')]
