"""Unit tests for ODCS Pydantic models in data_contracts_api."""

import pytest
from pydantic import ValidationError

from src.models.data_contracts_api import ColumnProperty


def test_column_property_transform_source_objects_accepts_list():
    """ODCS v3.1.0 defines transformSourceObjects as an array of strings.

    Regression test for issue #285: ODCS-compliant uploads with
    transformSourceObjects as a list previously failed Pydantic validation
    with HTTP 422 ("Input should be a valid string").
    """
    prop = ColumnProperty(
        name='col',
        logicalType='string',
        transformSourceObjects=['table_a', 'table_b'],
    )
    assert prop.transformSourceObjects == ['table_a', 'table_b']


def test_column_property_transform_source_objects_accepts_string_for_backcompat():
    """Plain-string input remains valid for backward compatibility."""
    prop = ColumnProperty(
        name='col',
        logicalType='string',
        transformSourceObjects='table_a',
    )
    assert prop.transformSourceObjects == 'table_a'


def test_column_property_transform_source_objects_optional():
    """Field is optional and may be omitted."""
    prop = ColumnProperty(name='col', logicalType='string')
    assert prop.transformSourceObjects is None
