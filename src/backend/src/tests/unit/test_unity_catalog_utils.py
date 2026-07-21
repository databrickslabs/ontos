"""
Unit tests for Unity Catalog utilities

Tests Unity Catalog utility functions including:
- UC identifier sanitization
- PostgreSQL identifier sanitization
- Type mapping functions
"""
import pytest
from databricks.sdk.service.catalog import ColumnTypeName

from src.common.unity_catalog_utils import (
    sanitize_uc_identifier,
    sanitize_postgres_identifier,
    map_logical_type_to_column_type,
)


class TestUnityCatalogUtils:
    """Test suite for Unity Catalog utilities"""

    # sanitize_uc_identifier tests
    def test_sanitize_uc_identifier_valid(self):
        """Test sanitizing valid UC identifier."""
        assert sanitize_uc_identifier("my_table") == "my_table"
        assert sanitize_uc_identifier("Table123") == "Table123"
        assert sanitize_uc_identifier("_private") == "_private"

    def test_sanitize_uc_identifier_with_whitespace(self):
        """Test sanitizing identifier with whitespace."""
        assert sanitize_uc_identifier("  my_table  ") == "my_table"

    def test_sanitize_uc_identifier_empty(self):
        """Test rejecting empty identifier."""
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_uc_identifier("")

    def test_sanitize_uc_identifier_none(self):
        """Test rejecting None identifier."""
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_uc_identifier(None)

    def test_sanitize_uc_identifier_too_long(self):
        """Test rejecting identifier that's too long."""
        long_name = "a" * 300
        with pytest.raises(ValueError, match="exceeds maximum length"):
            sanitize_uc_identifier(long_name)

    def test_sanitize_uc_identifier_invalid_start(self):
        """Test rejecting identifier starting with digit."""
        with pytest.raises(ValueError, match="must start with letter or underscore"):
            sanitize_uc_identifier("123table")

    def test_sanitize_uc_identifier_invalid_chars(self):
        """Test rejecting identifier with invalid characters."""
        with pytest.raises(ValueError, match="must start with letter or underscore"):
            sanitize_uc_identifier("my-table")
        
        with pytest.raises(ValueError, match="must start with letter or underscore"):
            sanitize_uc_identifier("my.table")

    def test_sanitize_uc_identifier_custom_max_length(self):
        """Test using custom max length."""
        assert sanitize_uc_identifier("short", max_length=10) == "short"
        
        with pytest.raises(ValueError, match="exceeds maximum length of 5"):
            sanitize_uc_identifier("toolong", max_length=5)

    # sanitize_postgres_identifier tests
    def test_sanitize_postgres_identifier_valid(self):
        """Test sanitizing valid PostgreSQL identifier."""
        assert sanitize_postgres_identifier("my_database") == "my_database"
        assert sanitize_postgres_identifier("db123") == "db123"
        assert sanitize_postgres_identifier("_private") == "_private"

    def test_sanitize_postgres_identifier_with_dollar(self):
        """Test PostgreSQL identifier with dollar sign."""
        assert sanitize_postgres_identifier("temp$db") == "temp$db"

    def test_sanitize_postgres_identifier_empty(self):
        """Test rejecting empty identifier."""
        with pytest.raises(ValueError, match="must be a non-empty string"):
            sanitize_postgres_identifier("")

    def test_sanitize_postgres_identifier_too_long(self):
        """Test rejecting identifier exceeding PostgreSQL limit."""
        long_name = "a" * 70
        with pytest.raises(ValueError, match="exceeds maximum length"):
            sanitize_postgres_identifier(long_name)

    def test_sanitize_postgres_identifier_reserved_keyword(self):
        """Test rejecting PostgreSQL reserved keywords."""
        with pytest.raises(ValueError, match="cannot use reserved keyword"):
            sanitize_postgres_identifier("select")
        
        with pytest.raises(ValueError, match="cannot use reserved keyword"):
            sanitize_postgres_identifier("table")
        
        with pytest.raises(ValueError, match="cannot use reserved keyword"):
            sanitize_postgres_identifier("SELECT")  # Case insensitive

    def test_sanitize_postgres_identifier_invalid_start(self):
        """Test rejecting identifier starting with digit."""
        with pytest.raises(ValueError, match="must start with letter or underscore"):
            sanitize_postgres_identifier("9database")

    def test_sanitize_postgres_identifier_invalid_chars(self):
        """Test rejecting identifier with invalid characters."""
        with pytest.raises(ValueError, match="must start with letter or underscore"):
            sanitize_postgres_identifier("my-database")

    def test_sanitize_postgres_identifier_databricks_email(self):
        """Lakebase roles for human users are Databricks emails."""
        assert (
            sanitize_postgres_identifier("laurel.kremer@databricks.com")
            == "laurel.kremer@databricks.com"
        )

    def test_sanitize_postgres_identifier_rejects_unsafe_email(self):
        """Reject email-like strings that could break quoted SQL identifiers."""
        with pytest.raises(ValueError):
            sanitize_postgres_identifier('evil@"databricks.com')

    # map_logical_type_to_column_type tests
    def test_map_logical_type_integer(self):
        """Test mapping integer types."""
        assert map_logical_type_to_column_type("integer") == ColumnTypeName.LONG
        assert map_logical_type_to_column_type("int") == ColumnTypeName.LONG
        assert map_logical_type_to_column_type("long") == ColumnTypeName.LONG
        assert map_logical_type_to_column_type("INTEGER") == ColumnTypeName.LONG

    def test_map_logical_type_smallint(self):
        """Test mapping smallint types."""
        assert map_logical_type_to_column_type("smallint") == ColumnTypeName.SHORT
        assert map_logical_type_to_column_type("short") == ColumnTypeName.SHORT

    def test_map_logical_type_tinyint(self):
        """Test mapping tinyint types."""
        assert map_logical_type_to_column_type("tinyint") == ColumnTypeName.BYTE
        assert map_logical_type_to_column_type("byte") == ColumnTypeName.BYTE

    def test_map_logical_type_double(self):
        """Test mapping double types."""
        assert map_logical_type_to_column_type("number") == ColumnTypeName.DOUBLE
        assert map_logical_type_to_column_type("double") == ColumnTypeName.DOUBLE

    def test_map_logical_type_float(self):
        """Test mapping float type."""
        assert map_logical_type_to_column_type("float") == ColumnTypeName.FLOAT

    def test_map_logical_type_decimal(self):
        """Test mapping decimal types."""
        assert map_logical_type_to_column_type("decimal") == ColumnTypeName.DECIMAL
        assert map_logical_type_to_column_type("numeric") == ColumnTypeName.DECIMAL

    def test_map_logical_type_string(self):
        """Test mapping string types."""
        assert map_logical_type_to_column_type("string") == ColumnTypeName.STRING
        assert map_logical_type_to_column_type("text") == ColumnTypeName.STRING
        assert map_logical_type_to_column_type("varchar") == ColumnTypeName.STRING

    def test_map_logical_type_boolean(self):
        """Test mapping boolean type."""
        assert map_logical_type_to_column_type("boolean") == ColumnTypeName.BOOLEAN
        assert map_logical_type_to_column_type("bool") == ColumnTypeName.BOOLEAN

    def test_map_logical_type_date(self):
        """Test mapping date type."""
        assert map_logical_type_to_column_type("date") == ColumnTypeName.DATE

    def test_map_logical_type_timestamp(self):
        """Test mapping timestamp types."""
        assert map_logical_type_to_column_type("timestamp") == ColumnTypeName.TIMESTAMP
        assert map_logical_type_to_column_type("datetime") == ColumnTypeName.TIMESTAMP

    def test_map_logical_type_binary(self):
        """Test mapping binary type."""
        assert map_logical_type_to_column_type("binary") == ColumnTypeName.BINARY

    def test_map_logical_type_unknown(self):
        """Test mapping unknown type defaults to STRING."""
        assert map_logical_type_to_column_type("unknown_type") == ColumnTypeName.STRING
        assert map_logical_type_to_column_type("") == ColumnTypeName.STRING
        assert map_logical_type_to_column_type(None) == ColumnTypeName.STRING

