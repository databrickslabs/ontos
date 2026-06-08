"""
Unity Catalog utilities for safe catalog, schema, and table operations.

This module provides centralized, security-hardened functions for creating
Unity Catalog objects using the Databricks SDK API to prevent SQL injection
vulnerabilities.

Key Features:
- Input sanitization for all identifiers (catalog, schema, table, column names)
- Type-safe table creation using Databricks SDK
- Idempotent catalog/schema/table creation with existence checks
- Structured error handling and logging
"""

import re
import uuid
from typing import Any, Dict, List, Optional

from databricks.sdk import WorkspaceClient
from src.common.logging import get_logger

logger = get_logger(__name__)
from databricks.sdk.service.catalog import (
    ColumnInfo,
    ColumnTypeName,
    TableType,
    DataSourceFormat,
)
from fastapi import HTTPException

from .logging import get_logger

logger = get_logger(__name__)


def is_valid_uuid(identifier: str) -> bool:
    """Check if a string is a valid UUID.
    
    This is used to identify Databricks service principal usernames, which are UUIDs.
    UUIDs are inherently safe for use as database identifiers since they follow a
    strict format and cannot contain SQL injection vectors.
    
    Args:
        identifier: The string to check
        
    Returns:
        True if the identifier is a valid UUID, False otherwise
        
    Example:
        >>> is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")
        True
        >>> is_valid_uuid("my_username")
        False
    """
    try:
        uuid.UUID(identifier)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def sanitize_uc_identifier(identifier: Optional[str], max_length: int = 255) -> str:
    """Sanitize and validate a Unity Catalog identifier.
    
    Unity Catalog identifiers (catalog, schema, table, column names) must:
    - Start with a letter or underscore
    - Contain only letters, digits, and underscores
    - Not exceed max_length characters
    
    Args:
        identifier: The identifier to sanitize
        max_length: Maximum allowed length (default: 255)
        
    Returns:
        The sanitized identifier
        
    Raises:
        ValueError: If identifier is invalid or cannot be sanitized
        
    Example:
        >>> sanitize_uc_identifier("my_table_123")
        "my_table_123"
        >>> sanitize_uc_identifier("invalid-name")
        ValueError: Invalid identifier 'invalid-name'...
    """
    if not identifier or not isinstance(identifier, str):
        raise ValueError("Identifier must be a non-empty string")
    
    identifier = identifier.strip()
    
    # Check length
    if len(identifier) > max_length:
        raise ValueError(f"Identifier exceeds maximum length of {max_length} characters")
    
    # Check for valid UC identifier pattern
    # Must start with letter or underscore, followed by letters, digits, or underscores
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', identifier):
        raise ValueError(
            f"Invalid identifier '{identifier}': must start with letter or underscore "
            "and contain only letters, digits, and underscores"
        )
    
    return identifier


def sanitize_postgres_identifier(identifier: str, max_length: int = 63) -> str:
    """Sanitize and validate a PostgreSQL identifier (database/schema/user name).
    
    PostgreSQL identifiers must:
    - Start with a letter or underscore
    - Contain only letters, digits, underscores, and dollar signs
    - Not exceed 63 characters (PostgreSQL NAMEDATALEN limit)
    - Not be a PostgreSQL reserved keyword
    
    Special case: UUIDs are allowed as-is (for Databricks service principals).
    
    This function provides SQL injection protection for PostgreSQL DDL operations
    that cannot use parameterized queries (like CREATE DATABASE).
    
    Args:
        identifier: The identifier to sanitize
        max_length: Maximum allowed length (default: 63 for PostgreSQL)
        
    Returns:
        The sanitized identifier
        
    Raises:
        ValueError: If identifier is invalid or uses reserved keyword
        
    Example:
        >>> sanitize_postgres_identifier("my_database")
        "my_database"
        >>> sanitize_postgres_identifier("select")
        ValueError: Invalid PostgreSQL identifier 'select': cannot use reserved keyword
        >>> sanitize_postgres_identifier("550e8400-e29b-41d4-a716-446655440000")
        "550e8400-e29b-41d4-a716-446655440000"
    """
    if not identifier or not isinstance(identifier, str):
        raise ValueError("PostgreSQL identifier must be a non-empty string")
    
    identifier = identifier.strip()
    
    # PostgreSQL max identifier length is 63 bytes (NAMEDATALEN - 1)
    if len(identifier) > max_length:
        raise ValueError(
            f"PostgreSQL identifier exceeds maximum length of {max_length} characters"
        )
    
    # UUIDs are allowed as-is (Databricks service principals)
    # UUIDs are inherently safe since they follow a strict format
    if is_valid_uuid(identifier):
        return identifier
    
    # PostgreSQL allows letters, digits, underscores, and dollar signs
    # Must start with letter or underscore
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_$]*$', identifier):
        raise ValueError(
            f"Invalid PostgreSQL identifier '{identifier}': must start with letter or underscore "
            "and contain only letters, digits, underscores, and dollar signs"
        )
    
    # Check against PostgreSQL reserved keywords (most common ones)
    # Full list: https://www.postgresql.org/docs/current/sql-keywords-appendix.html
    POSTGRES_RESERVED = {
        'all', 'analyse', 'analyze', 'and', 'any', 'array', 'as', 'asc',
        'asymmetric', 'both', 'case', 'cast', 'check', 'collate', 'column',
        'constraint', 'create', 'current_catalog', 'current_date',
        'current_role', 'current_time', 'current_timestamp', 'current_user',
        'default', 'deferrable', 'desc', 'distinct', 'do', 'else', 'end',
        'except', 'false', 'fetch', 'for', 'foreign', 'from', 'grant',
        'group', 'having', 'in', 'initially', 'intersect', 'into', 'lateral',
        'leading', 'limit', 'localtime', 'localtimestamp', 'not', 'null',
        'offset', 'on', 'only', 'or', 'order', 'placing', 'primary',
        'references', 'returning', 'select', 'session_user', 'some',
        'symmetric', 'table', 'then', 'to', 'trailing', 'true', 'union',
        'unique', 'user', 'using', 'variadic', 'when', 'where', 'window', 'with'
    }
    
    if identifier.lower() in POSTGRES_RESERVED:
        raise ValueError(
            f"Invalid PostgreSQL identifier '{identifier}': cannot use reserved keyword"
        )
    
    return identifier


def map_logical_type_to_column_type(logical_type: Optional[str]) -> ColumnTypeName:
    """Map a logical type string to Databricks ColumnTypeName enum.
    
    Args:
        logical_type: Logical type string (e.g., 'string', 'integer', 'boolean')
        
    Returns:
        ColumnTypeName enum value
        
    Example:
        >>> map_logical_type_to_column_type('string')
        ColumnTypeName.STRING
        >>> map_logical_type_to_column_type('integer')
        ColumnTypeName.LONG
    """
    logical_lower = (logical_type or '').lower()
    
    if logical_lower in ('integer', 'int', 'long'):
        return ColumnTypeName.LONG
    if logical_lower in ('smallint', 'short'):
        return ColumnTypeName.SHORT
    if logical_lower in ('tinyint', 'byte'):
        return ColumnTypeName.BYTE
    if logical_lower in ('number', 'double'):
        return ColumnTypeName.DOUBLE
    if logical_lower in ('float',):
        return ColumnTypeName.FLOAT
    if logical_lower in ('decimal', 'numeric'):
        return ColumnTypeName.DECIMAL
    if logical_lower in ('string', 'text'):
        return ColumnTypeName.STRING
    if logical_lower in ('boolean', 'bool'):
        return ColumnTypeName.BOOLEAN
    if logical_lower in ('date',):
        return ColumnTypeName.DATE
    if logical_lower in ('datetime', 'timestamp'):
        return ColumnTypeName.TIMESTAMP
    if logical_lower in ('binary',):
        return ColumnTypeName.BINARY
    
    # Default to STRING for unknown types
    logger.warning(f"Unknown logical type '{logical_type}', defaulting to STRING")
    return ColumnTypeName.STRING


def ensure_catalog_exists(
    ws: WorkspaceClient,
    catalog_name: str,
    comment: Optional[str] = None,
    properties: Optional[Dict[str, str]] = None
) -> str:
    """Ensure a catalog exists, creating it if necessary (idempotent).
    
    Args:
        ws: Workspace client
        catalog_name: Name of the catalog (will be sanitized)
        comment: Optional comment/description for the catalog
        properties: Optional properties to set on the catalog
        
    Returns:
        The sanitized catalog name
        
    Raises:
        HTTPException: If catalog name is invalid or creation fails
        
    Example:
        >>> ensure_catalog_exists(ws, "my_catalog", "Test catalog")
        "my_catalog"
    """
    try:
        catalog_name = sanitize_uc_identifier(catalog_name)
    except ValueError as e:
        logger.error("Invalid catalog name: %s", e)
        raise HTTPException(status_code=400, detail="Invalid catalog name")
    
    try:
        # Check if catalog exists
        ws.catalogs.get(catalog_name)
        logger.debug(f"Catalog '{catalog_name}' already exists")
    except Exception:
        # Catalog doesn't exist, create it
        try:
            ws.catalogs.create(name=catalog_name, comment=comment, properties=properties)
            logger.info(f"Created catalog '{catalog_name}'")
        except Exception as e:
            logger.error("Failed to create catalog '%s': %s", catalog_name, e)
            raise HTTPException(status_code=500, detail="Failed to create catalog")
    
    return catalog_name


def ensure_schema_exists(
    ws: WorkspaceClient,
    catalog_name: str,
    schema_name: str,
    comment: Optional[str] = None,
    properties: Optional[Dict[str, str]] = None
) -> str:
    """Ensure a schema exists, creating it if necessary (idempotent).
    
    Args:
        ws: Workspace client
        catalog_name: Name of the parent catalog (will be sanitized)
        schema_name: Name of the schema (will be sanitized)
        comment: Optional comment/description for the schema
        properties: Optional properties to set on the schema
        
    Returns:
        The full schema name (catalog.schema)
        
    Raises:
        HTTPException: If names are invalid or creation fails
        
    Example:
        >>> ensure_schema_exists(ws, "my_catalog", "my_schema")
        "my_catalog.my_schema"
    """
    try:
        catalog_name = sanitize_uc_identifier(catalog_name)
        schema_name = sanitize_uc_identifier(schema_name)
    except ValueError as e:
        logger.error("Invalid schema identifier: %s", e)
        raise HTTPException(status_code=400, detail="Invalid schema identifier")
    
    full_schema_name = f"{catalog_name}.{schema_name}"
    
    try:
        # Check if schema exists
        ws.schemas.get(full_schema_name)
        logger.debug(f"Schema '{full_schema_name}' already exists")
    except Exception:
        # Schema doesn't exist, create it
        try:
            ws.schemas.create(
                name=schema_name,
                catalog_name=catalog_name,
                comment=comment,
                properties=properties
            )
            logger.info(f"Created schema '{full_schema_name}'")
        except Exception as e:
            logger.error("Failed to create schema '%s': %s", full_schema_name, e)
            raise HTTPException(status_code=500, detail="Failed to create schema")
    
    return full_schema_name


def create_table_safe(
    ws: WorkspaceClient,
    catalog_name: str,
    schema_name: str,
    table_name: str,
    columns: List[Dict[str, Any]],
    comment: Optional[str] = None,
    properties: Optional[Dict[str, str]] = None,
    table_type: TableType = TableType.MANAGED,
    data_source_format: DataSourceFormat = DataSourceFormat.DELTA,
    storage_location: Optional[str] = None
) -> str:
    """Create a table using Databricks SDK API (safe from SQL injection).
    
    This function provides a secure way to create Unity Catalog tables by:
    1. Sanitizing all identifiers (catalog, schema, table, column names)
    2. Using type-safe Databricks SDK APIs instead of raw SQL
    3. Validating column definitions
    4. Checking for table existence before creation (idempotent)
    
    Args:
        ws: Workspace client
        catalog_name: Name of the catalog (will be sanitized)
        schema_name: Name of the schema (will be sanitized)
        table_name: Name of the table (will be sanitized)
        columns: List of column definitions with 'name' and 'logicalType' keys
        comment: Optional table comment/description
        properties: Optional table properties
        table_type: Table type (default: MANAGED)
        data_source_format: Data format (default: DELTA)
        storage_location: Optional storage location (None = managed by UC)
        
    Returns:
        Full table name (catalog.schema.table)
        
    Raises:
        HTTPException: If identifiers are invalid or table creation fails
        
    Example:
        >>> columns = [
        ...     {'name': 'id', 'logicalType': 'integer', 'required': True},
        ...     {'name': 'name', 'logicalType': 'string'}
        ... ]
        >>> create_table_safe(ws, "catalog", "schema", "table", columns)
        "catalog.schema.table"
    """
    # Sanitize all identifiers
    try:
        catalog_name = sanitize_uc_identifier(catalog_name)
        schema_name = sanitize_uc_identifier(schema_name)
        table_name = sanitize_uc_identifier(table_name)
    except ValueError as e:
        logger.error("Invalid table identifier: %s", e)
        raise HTTPException(status_code=400, detail="Invalid table identifier")
    
    # Build column info list
    column_infos: List[ColumnInfo] = []
    for col in columns:
        col_name = col.get('name', '').strip()
        if not col_name:
            continue
            
        # Sanitize column name
        try:
            col_name = sanitize_uc_identifier(col_name)
        except ValueError as e:
            logger.error("Invalid column name '%s': %s", col_name, e)
            raise HTTPException(status_code=400, detail="Invalid column name")
        
        logical_type = col.get('logicalType') or col.get('logical_type') or 'string'
        column_type = map_logical_type_to_column_type(logical_type)
        
        column_infos.append(
            ColumnInfo(
                name=col_name,
                type_name=column_type,
                type_text=column_type.value,
                position=len(column_infos),
                nullable=not col.get('required', False),
                comment=col.get('description') or col.get('comment')
            )
        )
    
    # Add default id column if no columns specified
    if not column_infos:
        logger.warning(f"No columns specified for table {table_name}, adding default 'id' column")
        column_infos.append(
            ColumnInfo(
                name='id',
                type_name=ColumnTypeName.STRING,
                type_text=ColumnTypeName.STRING.value,
                position=0,
                nullable=True
            )
        )
    
    full_name = f"{catalog_name}.{schema_name}.{table_name}"
    
    # Check if table already exists
    try:
        existing_table = ws.tables.get(full_name=full_name)
        if existing_table:
            logger.info(f"Table '{full_name}' already exists, skipping creation")
            return full_name
    except Exception:
        # Table doesn't exist, proceed with creation
        pass
    
    # Create table using SDK API
    try:
        ws.tables.create(
            name=table_name,
            catalog_name=catalog_name,
            schema_name=schema_name,
            table_type=table_type,
            data_source_format=data_source_format,
            columns=column_infos,
            comment=comment,
            properties=properties,
            storage_location=storage_location
        )
        logger.info(f"Successfully created table '{full_name}'")
        return full_name
    except Exception as e:
        logger.error("Failed to create table '%s': %s", full_name, e)
        raise HTTPException(status_code=500, detail="Table creation failed")


def ensure_catalog_and_schema_exist(
    ws: WorkspaceClient,
    catalog_name: str,
    schema_name: str,
    catalog_comment: Optional[str] = None,
    schema_comment: Optional[str] = None
) -> tuple[str, str]:
    """Ensure both catalog and schema exist, creating them if necessary.
    
    This is a convenience function that ensures parent catalog exists before
    creating the schema.
    
    Args:
        ws: Workspace client
        catalog_name: Name of the catalog (will be sanitized)
        schema_name: Name of the schema (will be sanitized)
        catalog_comment: Optional catalog comment
        schema_comment: Optional schema comment
        
    Returns:
        Tuple of (catalog_name, full_schema_name)
        
    Raises:
        HTTPException: If names are invalid or creation fails
        
    Example:
        >>> ensure_catalog_and_schema_exist(ws, "my_catalog", "my_schema")
        ("my_catalog", "my_catalog.my_schema")
    """
    catalog_name = ensure_catalog_exists(ws, catalog_name, comment=catalog_comment)
    full_schema_name = ensure_schema_exists(ws, catalog_name, schema_name, comment=schema_comment)
    return catalog_name, full_schema_name

