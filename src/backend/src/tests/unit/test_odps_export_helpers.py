"""Value helpers of the ODPS export: custom property types and the creation timestamp."""
from datetime import datetime, timezone

import pytest

from src.controller.data_products_manager import _decode_stored_cp_value, _odps_timestamp
from src.controller.domain_export_adapter import domain_export_adapter


@pytest.mark.parametrize("stored,expected", [
    ("42", 42),
    ("-3.5", -3.5),
    ("true", True),
    ("false", False),
    ('{"nested": [1, "two"]}', {"nested": [1, "two"]}),
    ('["a", "b"]', ["a", "b"]),
    ("plain text", "plain text"),
    ("1.0e3", "1.0e3"),
    ("007", "007"),
    ("[not json", "[not json"),
    ("", ""),
    (None, None),
    (7, 7),
])
def test_a_stored_custom_property_value_gets_its_json_type_back(stored, expected):
    assert _decode_stored_cp_value(stored) == expected


def test_the_creation_timestamp_is_exported_in_utc():
    aware = datetime(2024, 6, 7, 10, 9, 10, tzinfo=timezone.utc)
    assert _odps_timestamp(aware) == "2024-06-07T10:09:10Z"
    assert _odps_timestamp(aware.replace(tzinfo=None)) == "2024-06-07T10:09:10Z"
    assert _odps_timestamp(None) is None


def test_an_original_domain_exported_as_json_text_is_read_as_a_list():
    doc = {"customProperties": [{"property": "ontosOriginalDomain", "value": '["sales", "ops"]'}]}
    assert domain_export_adapter.extract_original_domain_strings(doc) == ["sales", "ops"]
