"""Tests for CatalogCommanderManager schema inference functionality."""

import pytest
from unittest.mock import Mock, MagicMock
from typing import Dict, Any

from src.controller.catalog_commander_manager import CatalogCommanderManager


class TestCatalogCommanderManagerSchemaInference:
    """Test schema inference and UC metadata handling."""

    @pytest.fixture
    def mock_workspace_client(self):
        """Create a mock workspace client."""
        client = Mock()
        client.api_client = Mock()
        client.tables = Mock()
        return client

    @pytest.fixture
    def mock_obo_client(self):
        """Create a mock OBO workspace client."""
        client = Mock()
        client.api_client = Mock()
        client.tables = Mock()
        return client

    @pytest.fixture
    def catalog_manager(self, mock_workspace_client, mock_obo_client):
        """Create CatalogCommanderManager with mocked clients."""
        return CatalogCommanderManager(mock_workspace_client, mock_obo_client)

    @pytest.fixture
    def sample_uc_table_data(self):
        """Sample UC table data matching the New_query.csv structure."""
        return {
            'name': 'table_a',
            'catalog_name': 'lars_george_uc',
            'schema_name': 'test_db',
            'table_type': 'MANAGED',
            'data_source_format': 'DELTA',
            'storage_location': 's3://databricks-e2demofieldengwest/b169b504-4c54-49f2-bc3a-adf4b128f36d/tables/c39d273a-d87b-4a62-8792-0193f142fca7',
            'owner': 'lars.george@databricks.com',
            'comment': 'The table contains records of various entries identified by a unique ID. It includes additional information related to each entry. This data can be used for tracking, reporting, or analyzing specific items or events associated with the IDs.',
            'created_at': 'Mon Jul 28 12:31:34 UTC 2025',
            'updated_at': None,
            'properties': {
                'delta.enableDeletionVectors': 'true',
                'delta.feature.appendOnly': 'supported',
                'delta.feature.deletionVectors': 'supported',
                'delta.feature.invariants': 'supported',
                'delta.minReaderVersion': '3',
                'delta.minWriterVersion': '7'
            },
            'columns': [
                {
                    'name': 'id',
                    'type_text': 'int',
                    'type_name': 'int',
                    'data_type': 'int',
                    'nullable': False,
                    'comment': 'A unique identifier for each entry in the table, allowing for easy tracking and referencing of specific records.',
                    'partition_index': None
                },
                {
                    'name': 'info',
                    'type_text': 'string',
                    'type_name': 'string',
                    'data_type': 'string',
                    'nullable': True,
                    'comment': 'Contains additional details related to each entry, which can provide context or further information necessary for analysis or reporting.',
                    'partition_index': None
                }
            ]
        }

    def test_get_dataset_returns_enhanced_metadata(self, catalog_manager, mock_obo_client, sample_uc_table_data):
        """Test that get_dataset returns enhanced UC metadata."""
        # Setup mock to return sample data - use mock_obo_client since that's what self.client refers to
        mock_obo_client.tables.get.return_value = sample_uc_table_data

        # Call the method
        result = catalog_manager.get_dataset('lars_george_uc.test_db.table_a')

        # Verify structure
        assert 'schema' in result
        assert 'table_info' in result
        assert 'data' in result
        assert 'total_rows' in result

        # Verify table info
        table_info = result['table_info']
        assert table_info['name'] == 'table_a'
        assert table_info['catalog_name'] == 'lars_george_uc'
        assert table_info['schema_name'] == 'test_db'
        assert table_info['table_type'] == 'MANAGED'
        assert table_info['owner'] == 'lars.george@databricks.com'
        assert table_info['comment'] == sample_uc_table_data['comment']
        assert table_info['storage_location'] == sample_uc_table_data['storage_location']
        assert table_info['properties'] == sample_uc_table_data['properties']

    def test_get_dataset_returns_enhanced_schema(self, catalog_manager, mock_obo_client, sample_uc_table_data):
        """Test that get_dataset returns enhanced column schema."""
        # Setup mock to return sample data - use mock_obo_client since that's what self.client refers to
        mock_obo_client.tables.get.return_value = sample_uc_table_data

        # Call the method
        result = catalog_manager.get_dataset('lars_george_uc.test_db.table_a')

        # Verify schema structure
        schema = result['schema']
        assert len(schema) == 2

        # Verify id column
        id_col = schema[0]
        assert id_col['name'] == 'id'
        assert id_col['type'] == 'int'  # Original UC type
        assert id_col['physicalType'] == 'int'  # Physical type
        assert id_col['logicalType'] == 'integer'  # ODCS logical type
        assert id_col['nullable'] == False
        assert id_col['comment'] == 'A unique identifier for each entry in the table, allowing for easy tracking and referencing of specific records.'
        assert id_col['partitioned'] == False
        assert id_col['partitionKeyPosition'] is None

        # Verify info column
        info_col = schema[1]
        assert info_col['name'] == 'info'
        assert info_col['type'] == 'string'
        assert info_col['physicalType'] == 'string'
        assert info_col['logicalType'] == 'string'
        assert info_col['nullable'] == True
        assert info_col['comment'] == 'Contains additional details related to each entry, which can provide context or further information necessary for analysis or reporting.'
        assert info_col['partitioned'] == False

    def test_get_dataset_handles_dict_response(self, catalog_manager, mock_obo_client, sample_uc_table_data):
        """Test that get_dataset handles dictionary response from REST API."""
        # Mock tables.get to raise exception, forcing REST API path
        mock_obo_client.tables.get.side_effect = Exception("SDK method not available")
        mock_obo_client.api_client.do.return_value = sample_uc_table_data

        # Call the method
        result = catalog_manager.get_dataset('lars_george_uc.test_db.table_a')

        # Verify it worked with REST API response
        assert result['table_info']['name'] == 'table_a'
        assert len(result['schema']) == 2
        mock_obo_client.api_client.do.assert_called_once()

    @pytest.mark.parametrize("databricks_type,expected_logical_type", [
        ('int', 'integer'),
        ('bigint', 'integer'),
        ('smallint', 'integer'),
        ('tinyint', 'integer'),
        ('string', 'string'),
        ('varchar(255)', 'string'),
        ('char(10)', 'string'),
        ('text', 'string'),
        ('double', 'number'),
        ('float', 'number'),
        ('decimal(10,2)', 'number'),
        ('numeric', 'number'),
        ('date', 'date'),
        ('timestamp', 'date'),
        ('time', 'date'),
        ('boolean', 'boolean'),
        ('bool', 'boolean'),
        ('array<string>', 'array'),
        ('struct<name:string,age:int>', 'object'),
        ('map<string,int>', 'object'),
        ('unknown_type', 'string'),  # fallback
        ('', 'string'),  # empty string fallback
        (None, 'string'),  # None fallback
    ])
    def test_map_to_odcs_logical_type(self, catalog_manager, databricks_type, expected_logical_type):
        """Test mapping of Databricks types to ODCS logical types."""
        result = catalog_manager._map_to_odcs_logical_type(databricks_type)
        assert result == expected_logical_type

    def test_get_dataset_handles_partitioned_columns(self, catalog_manager, mock_obo_client):
        """Test handling of partitioned columns."""
        table_data = {
            'name': 'partitioned_table',
            'catalog_name': 'test_catalog',
            'schema_name': 'test_schema',
            'table_type': 'MANAGED',
            'columns': [
                {
                    'name': 'data_col',
                    'type_text': 'string',
                    'nullable': True,
                    'comment': 'Data column',
                    'partition_index': None
                },
                {
                    'name': 'partition_col',
                    'type_text': 'date',
                    'nullable': False,
                    'comment': 'Partition column',
                    'partition_index': 0
                }
            ]
        }

        mock_obo_client.tables.get.return_value = table_data

        result = catalog_manager.get_dataset('test_catalog.test_schema.partitioned_table')

        # Verify partition handling
        schema = result['schema']
        data_col = next(col for col in schema if col['name'] == 'data_col')
        partition_col = next(col for col in schema if col['name'] == 'partition_col')

        assert data_col['partitioned'] == False
        assert data_col['partitionKeyPosition'] is None

        assert partition_col['partitioned'] == True
        assert partition_col['partitionKeyPosition'] == 0

    def test_get_dataset_handles_missing_metadata(self, catalog_manager, mock_obo_client):
        """Test handling of missing optional metadata fields."""
        minimal_table_data = {
            'name': 'minimal_table',
            'columns': [
                {
                    'name': 'col1',
                    'type_text': 'string'
                    # Missing comment, nullable, partition_index
                }
            ]
        }

        mock_obo_client.tables.get.return_value = minimal_table_data

        result = catalog_manager.get_dataset('catalog.schema.minimal_table')

        # Verify defaults for missing fields
        table_info = result['table_info']
        assert table_info['owner'] is None
        assert table_info['comment'] is None
        assert table_info['storage_location'] is None

        schema = result['schema']
        col = schema[0]
        assert col['comment'] is None
        assert col['nullable'] is None
        assert col['partitioned'] == False

    def test_get_dataset_invalid_path_raises_error(self, catalog_manager):
        """Test that invalid dataset path raises ValueError."""
        with pytest.raises(ValueError, match="dataset_path must be in the form catalog.schema.table"):
            catalog_manager.get_dataset('invalid.path')

        with pytest.raises(ValueError, match="dataset_path must be in the form catalog.schema.table"):
            catalog_manager.get_dataset('too.many.parts.here')

    def test_get_dataset_sdk_error_propagates(self, catalog_manager, mock_obo_client):
        """Test that SDK errors are properly propagated."""
        # Mock both SDK and REST API to fail
        mock_obo_client.tables.get.side_effect = Exception("SDK error")
        mock_obo_client.api_client.do.side_effect = Exception("REST API error")

        with pytest.raises(Exception, match="REST API error"):
            catalog_manager.get_dataset('catalog.schema.table')