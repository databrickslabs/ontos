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
        '/Volumes/c/s/v/%2e%2e/w', '/Volumes/c/s/v/%2E/docs', '/Volumes/c/s/v/\uff0e\uff0e/w',
        '/Volumes/c/s/v/a\x00b', '/Volumes/c/s/v/a\nb', '/Volumes/c/s/v/a\x7fb',
        '/Volumes/c/s\x01/v',
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

    def test_aliases_and_anchors_are_refused(self):
        bomb = '---\na: &a ["x", "x"]\nb: &b [*a, *a]\nc: [*b, *b]\n---\nbody'
        with pytest.raises(FrontMatterError):
            parse_front_matter(bomb)

    def test_a_front_matter_block_over_the_cap_is_refused(self):
        text = '---\ntitle: ' + 'x' * (mim.MAX_FRONT_MATTER_BYTES + 1) + '\n---\nbody'
        with pytest.raises(FrontMatterError):
            parse_front_matter(text)

    def test_deeply_nested_front_matter_is_refused_not_raised(self):
        # 16,000 nested "[" fit in 32 KB and overflow the YAML parser's recursion.
        text = '---\nkey: ' + '[' * 16000 + '\n---\nbody'
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


class TestConceptLookupPerImport:
    def test_the_concept_names_are_read_from_the_graph_once(self):
        semantic = MagicMock()
        semantic.concept_name_index.return_value.find.side_effect = (
            lambda value: [f'http://ex.org/{value}'])
        resolver = mim._TargetResolver(MagicMock(), semantic)

        for names in (['A', 'B'], ['C'], ['A', 'D']):
            targets, _ = resolver.resolve({'concepts': names})
            assert [t.entity_id for t in targets] == [f'http://ex.org/{n}' for n in names]

        semantic.concept_name_index.assert_called_once()
        semantic.find_concept_iris.assert_not_called()

    def test_a_failed_concept_index_is_not_rebuilt_for_every_value(self):
        semantic = MagicMock()
        semantic.concept_name_index.side_effect = RuntimeError('graph unavailable')
        resolver = mim._TargetResolver(MagicMock(), semantic)

        for names in (['A', 'B'], ['C'], ['A', 'D']):
            targets, unresolved = resolver.resolve({'concepts': names})
            assert targets == []
            assert [u.reason for u in unresolved] == ['lookup_failed'] * len(names)

        semantic.concept_name_index.assert_called_once()


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

    def test_folders_past_the_depth_limit_are_unread(self, monkeypatch):
        monkeypatch.setattr(mim, 'MAX_DEPTH', 1)
        ws = self._ws({
            '/Volumes/c/s/v': [DirectoryEntry(path='/Volumes/c/s/v/sub', is_directory=True)],
            '/Volumes/c/s/v/sub': [
                DirectoryEntry(path='/Volumes/c/s/v/sub/a.md', is_directory=False),
                DirectoryEntry(path='/Volumes/c/s/v/sub/deep', is_directory=True),
            ],
            '/Volumes/c/s/v/sub/deep': [
                DirectoryEntry(path='/Volumes/c/s/v/sub/deep/x.md', is_directory=False),
            ],
        })
        unread = []
        found = MarkdownImportManager(MagicMock())._list_markdown_files(
            ws, '/Volumes/c/s/v', unread)
        assert found == [('/Volumes/c/s/v/sub/a.md', None)]
        assert unread == ['/Volumes/c/s/v/sub/deep']

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

    def test_entries_outside_the_listed_folder_are_skipped(self):
        ws = self._ws({'/Volumes/c/s/v': [
            DirectoryEntry(path='/Volumes/c/s/v/ok.md', is_directory=False),
            DirectoryEntry(path='/Volumes/c/s/other/x.md', is_directory=False),
            DirectoryEntry(path='/Volumes/c/s/v/sub/../../w/y.md', is_directory=False),
            DirectoryEntry(path='/Volumes/c/s/v/..', is_directory=True),
            DirectoryEntry(path='/Volumes/c/s/v/bad\nname.md', is_directory=False),
            DirectoryEntry(path='/Volumes/c/s/v/dir/', is_directory=True),
        ], '/Volumes/c/s/v/dir': []})
        found = MarkdownImportManager(MagicMock())._list_markdown_files(ws, '/Volumes/c/s/v')
        assert found == [('/Volumes/c/s/v/ok.md', None)]
        listed = [call.args[0] for call in ws.files.list_directory_contents.call_args_list]
        assert listed == ['/Volumes/c/s/v', '/Volumes/c/s/v/dir']

    def test_the_listing_stops_at_the_cap_without_reading_every_page(self, monkeypatch):
        monkeypatch.setattr(mim, 'MAX_FILES', 2)
        read = []

        def pages(folder):
            for n in range(1000):
                read.append(n)
                yield DirectoryEntry(path=f'/Volumes/c/s/v/{n}.md', is_directory=False)
        ws = MagicMock()
        ws.files.list_directory_contents.side_effect = pages
        with pytest.raises(MarkdownImportTooManyFilesError):
            MarkdownImportManager(MagicMock())._list_markdown_files(ws, '/Volumes/c/s/v')
        assert len(read) == 3

    def test_too_many_files_is_refused(self, monkeypatch):
        monkeypatch.setattr(mim, 'MAX_FILES', 2)
        ws = self._ws({'/Volumes/c/s/v': [
            DirectoryEntry(path=f'/Volumes/c/s/v/{n}.md', is_directory=False) for n in range(3)
        ]})
        with pytest.raises(MarkdownImportTooManyFilesError) as raised:
            MarkdownImportManager(MagicMock())._list_markdown_files(ws, '/Volumes/c/s/v')
        assert raised.value.params == {'path': '/Volumes/c/s/v', 'max': 2}


class TestImportLock:
    @staticmethod
    def _db(dialect, locked=True):
        db = MagicMock()
        db.get_bind.return_value.dialect.name = dialect
        db.execute.return_value.scalar.return_value = locked
        return db

    def test_a_running_import_refuses_the_next_one_on_postgres(self):
        db = self._db('postgresql', locked=False)
        with pytest.raises(mim.MarkdownImportInProgressError) as raised:
            mim.acquire_import_lock(db, '/Volumes/c/s/v')
        assert raised.value.code == 'markdown_import_in_progress'
        assert 'pg_try_advisory_xact_lock' in str(db.execute.call_args.args[0])

    def test_a_free_lock_lets_it_run(self):
        mim.acquire_import_lock(self._db('postgresql', locked=True), '/Volumes/c/s/v')

    def test_other_databases_rely_on_the_unique_index(self):
        db = self._db('sqlite')
        mim.acquire_import_lock(db, '/Volumes/c/s/v')
        db.execute.assert_not_called()


class TestFileFailures:
    @pytest.mark.parametrize('content, size, reason', [
        (b'\xff\xfe\x00bad', None, 'not_utf8'),
        (b'---\n[1, 2]\n---\n', None, 'front_matter_invalid'),
        (b'---\na: &x 1\nb: *x\n---\n', None, 'front_matter_invalid'),
        (b'text \x00 nul', None, 'not_text'),
        (b'x', mim.MAX_FILE_BYTES + 1, 'too_large'),
    ])
    def test_reports_the_reason(self, content, size, reason):
        ws = MagicMock()
        ws.files.download.return_value = SimpleNamespace(contents=io.BytesIO(content))
        entry = MarkdownImportManager(MagicMock())._import_file(
            MagicMock(), ws, '/Volumes/c/s/v/a.md', size, MagicMock(), None, [], [])
        assert (entry.status, entry.reason) == ('failed', reason)

    def test_more_targets_than_the_cap_fail_the_file_before_any_lookup(self):
        names = ', '.join(f'a{n}' for n in range(mim.MAX_TARGETS_PER_FILE + 1))
        ws = MagicMock()
        ws.files.download.return_value = SimpleNamespace(
            contents=io.BytesIO(f'---\nassets: [{names}]\n---\nx\n'.encode()))
        resolver = MagicMock()
        entry = MarkdownImportManager(MagicMock())._import_file(
            MagicMock(), ws, '/Volumes/c/s/v/a.md', None, resolver, None, [], [])
        assert (entry.status, entry.reason) == ('failed', 'too_many_targets')
        resolver.resolve.assert_not_called()

    def test_a_path_the_index_cannot_hold_fails_that_file_only(self):
        ws = MagicMock()
        long_path = '/Volumes/c/s/v/' + 'd' * mim.MAX_SOURCE_PATH_BYTES + '/a.md'
        entry = MarkdownImportManager(MagicMock())._import_file(
            MagicMock(), ws, long_path, None, MagicMock(), None, [], [])
        assert (entry.status, entry.reason) == ('failed', 'path_too_long')
        ws.files.download.assert_not_called()

    def test_a_read_error_is_read_failed(self):
        ws = MagicMock()
        ws.files.download.side_effect = PermissionDenied('no')
        entry = MarkdownImportManager(MagicMock())._import_file(
            MagicMock(), ws, '/Volumes/c/s/v/a.md', None, MagicMock(), None, [], [])
        assert (entry.status, entry.reason) == ('failed', 'read_failed')


_TEXT = '---\nconcepts: [Customer]\n---\nChurn means no order.\n'


class TestSearchItem:
    def _doc(self, **overrides):
        values = dict(
            id=uuid.uuid4(), entity_type='concept', entity_id='http://ex.org/onto#Customer',
            title='Customer terms', source_path='/Volumes/c/s/v/t.md',
            is_shared=False,
        )
        values.update(overrides)
        return DocumentMetadataDb(**values)

    def test_an_imported_document_is_indexed_with_its_body(self):
        doc = self._doc()
        item = MetadataManager().build_document_search_item(doc, _TEXT)
        assert item.id == f'document::{doc.id}'
        assert (item.type, item.feature_id) == ('document', 'semantic-models')
        assert item.description == 'Churn means no order.\n'
        assert item.link == '/concepts/browser?concept=http%3A%2F%2Fex.org%2Fonto%23Customer'
        assert item.extra_data['source_path'] == '/Volumes/c/s/v/t.md'

    def test_the_indexed_text_is_capped_and_the_full_text_stays_in_the_database(self):
        from src.controller.metadata_manager import MAX_INDEXED_DESCRIPTION_CHARS

        body = 'x' * (MAX_INDEXED_DESCRIPTION_CHARS * 3)
        item = MetadataManager().build_document_search_item(self._doc(), f'---\na: b\n---\n{body}')
        assert item.description == body[:MAX_INDEXED_DESCRIPTION_CHARS]

    @pytest.mark.parametrize('entity_type, feature', [
        ('data_domain', 'data-domains'), ('asset', 'assets'), ('concept', 'semantic-models'),
    ])
    def test_readers_of_the_entity_feature_see_it(self, entity_type, feature):
        item = MetadataManager().build_document_search_item(
            self._doc(entity_type=entity_type), _TEXT)
        assert item.feature_id == feature

    def test_uploads_are_not_indexed(self):
        doc = self._doc(source_path=None)
        assert MetadataManager().build_document_search_item(doc, None) is None

    def test_delete_removes_an_imported_document_from_the_index(self):
        repo = MagicMock()
        repo.get.return_value = self._doc()
        manager = MetadataManager(document_repository=repo)
        search = MagicMock()
        manager.set_search_manager(search)
        manager.delete_document(MagicMock(), id='abc', user_email=None)
        search.remove_item.assert_called_once_with('document::abc')
