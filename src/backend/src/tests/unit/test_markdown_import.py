"""Units of the Markdown import (#1478): paths, front matter, titles, targets, search items."""
import io
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.files import DirectoryEntry
from rdflib import ConjunctiveGraph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

from src.controller import markdown_import_manager as mim
from src.controller.markdown_import_manager import (
    FrontMatterError, MarkdownImportAccessDeniedError, MarkdownImportManager,
    MarkdownImportPathInvalidError, MarkdownImportPathNotFoundError,
    MarkdownImportTooManyFilesError, document_title, normalize_volume_path, parse_front_matter,
)
from src.controller.metadata_manager import MetadataManager, strip_front_matter
from src.controller.semantic_models_manager import SemanticModelsManager
from src.db_models.metadata import DocumentMetadataDb


class TestVolumePath:
    @pytest.mark.parametrize('raw, expected', [
        ('/Volumes/c/s/v', '/Volumes/c/s/v'),
        (' /Volumes/c/s/v/docs/ ', '/Volumes/c/s/v/docs'),
        ('/Volumes/c/s/v//docs', '/Volumes/c/s/v/docs'),
        ('/Volumes/c/s/v/a.md', '/Volumes/c/s/v/a.md'),
    ])
    def test_accepts_paths_inside_a_volume(self, raw, expected):
        assert normalize_volume_path(raw) == expected

    @pytest.mark.parametrize('raw', [
        '', '/tmp/docs', 'Volumes/c/s/v', '/Volumes/c/s', '/Volumes/c/s/v/../w',
        '/Volumes/c/s/v/./docs', '/Volumes/c/s/v\\docs', '/volumes/c/s/v',
    ])
    def test_refuses_other_paths_with_a_code(self, raw):
        with pytest.raises(MarkdownImportPathInvalidError) as raised:
            normalize_volume_path(raw)
        assert raised.value.code == 'markdown_import_path_invalid'
        assert raised.value.params == {'path': raw.strip()}


class TestFrontMatter:
    def test_reads_the_mapping_and_the_body(self):
        data, body = parse_front_matter('---\ndomain: Sales\nassets: [a, b]\n---\n# T\nText\n')
        assert data == {'domain': 'Sales', 'assets': ['a', 'b']}
        assert body == '# T\nText\n'

    def test_without_front_matter_the_text_is_the_body(self):
        assert parse_front_matter('# T\n---\nmore') == ({}, '# T\n---\nmore')

    def test_an_unclosed_block_is_plain_markdown(self):
        assert parse_front_matter('---\nno end') == ({}, '---\nno end')

    def test_an_empty_block_is_an_empty_mapping(self):
        assert parse_front_matter('---\n---\nBody') == ({}, 'Body')

    @pytest.mark.parametrize('text', ['---\n[a, b]\n---\n', '---\nkey: [unclosed\n---\n'])
    def test_invalid_yaml_or_a_list_is_refused(self, text):
        with pytest.raises(FrontMatterError):
            parse_front_matter(text)

    def test_strip_front_matter_keeps_the_body(self):
        assert strip_front_matter('---\na: 1\n---\n\nBody\n') == 'Body\n'
        assert strip_front_matter('Body only') == 'Body only'


class TestTitle:
    def test_front_matter_title_first(self):
        assert document_title({'title': ' Churn '}, '# Heading', '/V/c/s/v/x.md') == 'Churn'

    def test_then_the_first_heading(self):
        title = document_title({}, 'intro\n# Customer churn #\n## Sub', '/V/x.md')
        assert title == 'Customer churn'

    def test_then_the_file_name(self):
        title = document_title({'title': 3}, 'no heading', '/Volumes/c/s/v/glossary.md')
        assert title == 'glossary'

    def test_is_cut_to_the_column_size(self):
        assert len(document_title({'title': 'x' * 400}, '', '/a.md')) == 255


def _semantic(graph):
    manager = SemanticModelsManager.__new__(SemanticModelsManager)
    manager._graph = graph
    return manager


class TestFindConceptIris:
    @pytest.fixture
    def semantic(self):
        graph = ConjunctiveGraph()
        customer = URIRef('http://ex.org/onto#Customer')
        graph.add((customer, RDF.type, OWL.Class))
        graph.add((customer, RDFS.label, Literal('Customer')))
        order = URIRef('http://ex.org/onto/Order')
        graph.add((order, RDF.type, SKOS.Concept))
        # Same label on two concepts: ambiguous
        for name in ('A', 'B'):
            iri = URIRef(f'http://ex.org/onto#Account{name}')
            graph.add((iri, RDF.type, OWL.Class))
            graph.add((iri, SKOS.prefLabel, Literal('Account')))
        # A property with a label is not a concept
        prop = URIRef('http://ex.org/onto#name')
        graph.add((prop, RDF.type, OWL.DatatypeProperty))
        graph.add((prop, RDFS.label, Literal('Customer')))
        return _semantic(graph)

    def test_by_iri(self, semantic):
        assert semantic.find_concept_iris('http://ex.org/onto#Customer') == [
            'http://ex.org/onto#Customer']

    def test_by_label_case_insensitive(self, semantic):
        assert semantic.find_concept_iris(' customer ') == ['http://ex.org/onto#Customer']

    def test_by_local_name_without_a_label(self, semantic):
        assert semantic.find_concept_iris('order') == ['http://ex.org/onto/Order']

    def test_ambiguous_and_unknown(self, semantic):
        assert len(semantic.find_concept_iris('Account')) == 2
        assert semantic.find_concept_iris('Nothing') == []
        assert semantic.find_concept_iris('') == []


class TestListing:
    def _ws(self, tree):
        ws = MagicMock()

        def list_directory_contents(folder):
            if folder not in tree:
                raise NotFound('missing')
            return tree[folder]
        ws.files.list_directory_contents.side_effect = list_directory_contents
        return ws

    def test_walks_subfolders_and_keeps_only_markdown(self):
        ws = self._ws({
            '/Volumes/c/s/v': [
                DirectoryEntry(path='/Volumes/c/s/v/b.md', is_directory=False, file_size=3),
                DirectoryEntry(path='/Volumes/c/s/v/sub', is_directory=True),
                DirectoryEntry(path='/Volumes/c/s/v/x.txt', is_directory=False),
            ],
            '/Volumes/c/s/v/sub': [
                DirectoryEntry(path='/Volumes/c/s/v/sub/A.MD', is_directory=False, file_size=5),
            ],
        })
        found = MarkdownImportManager(MagicMock())._list_markdown_files(ws, '/Volumes/c/s/v')
        assert found == [('/Volumes/c/s/v/b.md', 3), ('/Volumes/c/s/v/sub/A.MD', 5)]

    def test_a_missing_folder_or_no_access_is_coded(self):
        manager = MarkdownImportManager(MagicMock())
        with pytest.raises(MarkdownImportPathNotFoundError):
            manager._list_markdown_files(self._ws({}), '/Volumes/c/s/v')
        ws = MagicMock()
        ws.files.list_directory_contents.side_effect = PermissionDenied('no')
        with pytest.raises(MarkdownImportAccessDeniedError):
            manager._list_markdown_files(ws, '/Volumes/c/s/v')

    def test_one_file_is_checked_with_its_metadata(self):
        ws = MagicMock()
        ws.files.get_metadata.return_value = SimpleNamespace(content_length=42)
        found = MarkdownImportManager(MagicMock())._list_markdown_files(ws, '/Volumes/c/s/v/a.md')
        assert found == [('/Volumes/c/s/v/a.md', 42)]
        ws.files.get_metadata.side_effect = NotFound('missing')
        with pytest.raises(MarkdownImportPathNotFoundError):
            MarkdownImportManager(MagicMock())._list_markdown_files(ws, '/Volumes/c/s/v/a.md')

    def test_too_many_files_is_refused(self, monkeypatch):
        monkeypatch.setattr(mim, 'MAX_FILES', 2)
        ws = self._ws({'/Volumes/c/s/v': [
            DirectoryEntry(path=f'/Volumes/c/s/v/{n}.md', is_directory=False) for n in range(3)
        ]})
        with pytest.raises(MarkdownImportTooManyFilesError) as raised:
            MarkdownImportManager(MagicMock())._list_markdown_files(ws, '/Volumes/c/s/v')
        assert raised.value.params == {'path': '/Volumes/c/s/v', 'max': 2}


class TestFileFailures:
    @pytest.mark.parametrize('content, size, reason', [
        (b'\xff\xfe\x00bad', None, 'not_utf8'),
        (b'---\n[1, 2]\n---\n', None, 'front_matter_invalid'),
        (b'x', mim.MAX_FILE_BYTES + 1, 'too_large'),
    ])
    def test_reports_the_reason(self, content, size, reason):
        ws = MagicMock()
        ws.files.download.return_value = SimpleNamespace(contents=io.BytesIO(content))
        entry = MarkdownImportManager(MagicMock())._import_file(
            MagicMock(), ws, '/Volumes/c/s/v/a.md', size, MagicMock(), None, [])
        assert (entry.status, entry.reason) == ('failed', reason)

    def test_a_read_error_is_read_failed(self):
        ws = MagicMock()
        ws.files.download.side_effect = PermissionDenied('no')
        entry = MarkdownImportManager(MagicMock())._import_file(
            MagicMock(), ws, '/Volumes/c/s/v/a.md', None, MagicMock(), None, [])
        assert (entry.status, entry.reason) == ('failed', 'read_failed')


class TestSearchItem:
    def _doc(self, **overrides):
        values = dict(
            id=uuid.uuid4(), entity_type='concept', entity_id='http://ex.org/onto#Customer',
            title='Customer terms', source_path='/Volumes/c/s/v/t.md',
            content_text='---\nconcepts: [Customer]\n---\nChurn means no order.\n',
            is_shared=False,
        )
        values.update(overrides)
        return DocumentMetadataDb(**values)

    def test_an_imported_document_is_indexed_with_its_body(self):
        doc = self._doc()
        item = MetadataManager().build_document_search_item(doc)
        assert item.id == f'document::{doc.id}'
        assert (item.type, item.feature_id) == ('document', 'data-domains')
        assert item.description == 'Churn means no order.\n'
        assert item.link == '/concepts/browser?concept=http%3A%2F%2Fex.org%2Fonto%23Customer'
        assert item.extra_data['source_path'] == '/Volumes/c/s/v/t.md'

    def test_uploads_are_not_indexed(self):
        doc = self._doc(source_path=None, content_text=None)
        assert MetadataManager().build_document_search_item(doc) is None

    def test_delete_removes_an_imported_document_from_the_index(self):
        repo = MagicMock()
        repo.get.return_value = self._doc()
        manager = MetadataManager(document_repository=repo)
        search = MagicMock()
        manager.set_search_manager(search)
        manager.delete_document(MagicMock(), id='abc', user_email=None)
        search.remove_item.assert_called_once_with('document::abc')
