"""Bundled taxonomy file size on disk."""

from unittest.mock import patch

import pytest

from src.controller.semantic_models_manager import SemanticModelsManager


@pytest.fixture
def manager_no_rebuild(db_session, tmp_path):
    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", lambda self: None):
        yield SemanticModelsManager(db_session, data_dir=tmp_path)


def test_bundled_taxonomy_file_size_bytes(manager_no_rebuild, tmp_path):
    tax_dir = tmp_path / "taxonomies"
    tax_dir.mkdir(parents=True)
    payload = b"@prefix : <http://ex/> .\n"
    (tax_dir / "databricks_ontology.ttl").write_bytes(payload)

    assert manager_no_rebuild.bundled_taxonomy_file_size_bytes("databricks_ontology") == len(payload)
    assert manager_no_rebuild.bundled_taxonomy_file_size_bytes("missing_stem") is None
