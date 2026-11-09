"""The file models of the indirect delivery mode can be imported.

``src.file_models`` still imported the dataset file model removed with the
legacy Dataset entity, so every indirect delivery failed with
``No module named 'src.file_models.datasets'`` before writing anything.
"""
import importlib


def test_the_file_models_import_and_register_every_exported_entity():
    file_models = importlib.import_module('src.file_models')

    for entity_type in ('AppRole', 'DataContract', 'DataDomain', 'DataProduct', 'TagNamespace'):
        assert file_models.FileModelRegistry.get(entity_type) is not None, entity_type
